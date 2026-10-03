#!/usr/bin/env python3
"""阶段 0/3/4 守卫的**判别力机器留证**（mutation check）。

## 这份脚本回答的问题

「这些测试真的能拦住回归吗？」—— 单纯全绿只说明「当前代码让测试满意」，
不说明「测试真的在检查东西」。做法：**逐条往生产代码里注入一个变异**（把守卫写坏），
断言目标用例**转红**；再还原，断言 sha256 与原始一致。

红不了 ⇒ 该守卫是摆设（测试与被测对象一起漂移，假绿）。这正是 v2 计划
「先红后绿纪律」要留的证据，只不过把一次性的手工操作固化成了可复跑的脚本。

## 安全措施

- 变异前后用 sha256 校验还原；任何一步不一致立即中止（不静默继续）。
- 每个变异都在 ``try/finally`` 里还原，Ctrl-C / 异常都会还原。
- 只改 ``MUTATIONS`` 里显式声明的、**唯一匹配**的字符串；匹配不唯一则跳过并报错
  （避免误改）。

用法：``cd backend && .venv/bin/python scripts/mutation_check.py``
退出码：有任一「变异后仍绿」或「还原失败」→ 1。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PY = str(BACKEND / ".venv" / "bin" / "python")


@dataclass(frozen=True)
class Mutation:
    label: str          # 人话说明：这个变异模拟什么回归
    rel: str            # 相对 backend/ 的文件
    old: str            # 必须唯一匹配的原文
    new: str            # 变异后的文本
    test: str           # 期望转红的用例（pytest node id）


MUTATIONS: list[Mutation] = [
    Mutation(
        label="读路径退回「只查内容缺件」（丢掉 Tier B 几何判据）",
        rel="app/core/db.py",
        old="            issues = assess_geometry(lc)\n            if not issues.ok:",
        new="            from app.living_circle.report_contract import live_geometry_deficiency\n"
            "            issues_ok = live_geometry_deficiency(lc) is None\n"
            "            if not issues_ok:",
        test="tests/test_intake_and_shell.py::test_list_hides_incomplete_live_reports",
    ),
    Mutation(
        label="B1 盲区越界判定反向（> 写成 <）",
        rel="app/living_circle/report_contract.py",
        old="        if worst > cr * GEOM_TOL:",
        new="        if worst < cr * GEOM_TOL:",
        test="tests/test_report_contract.py::test_blindspot_outside_reach_is_flagged",
    ),
    Mutation(
        label="丢掉「圈外点被送进报告」这一条（Q2 的标记形态）",
        rel="app/living_circle/report_contract.py",
        old='            if pt.get("in_circle") is False:',
        new='            if False:',
        test="tests/test_report_contract.py::test_point_marked_out_of_circle_is_flagged",
    ),
    Mutation(
        label="丢掉口径可举证判据（B0：存量旧算法 live 报告正是靠它现形）",
        rel="app/living_circle/report_contract.py",
        old='        if "reach_full_min" not in caliber:',
        new='        if False:',
        test="tests/test_report_contract.py::test_live_report_without_caliber_is_flagged",
    ),
    Mutation(
        label="丢掉采集半径下限判据（B6）",
        rel="app/living_circle/report_contract.py",
        old="        if collect is not None and collect < cr * 0.999:",
        new="        if collect is not None and collect < 0:",
        test="tests/test_report_contract.py::test_collect_radius_smaller_than_reach_is_flagged",
    ),
    Mutation(
        label="offline 豁免失效（会把「诚实的离线骨架」也隐藏）",
        rel="app/living_circle/report_contract.py",
        old='    offline = origin == "offline"',
        new="    offline = False",
        test="tests/test_report_contract.py::test_offline_blank_is_exempt",
    ),
    Mutation(
        label="写路径守卫短路（落库前不再判几何契约）",
        rel="app/core/pipeline/living_circle.py",
        old="    issues = assess_geometry(report_data)\n    if not issues.ok:",
        new="    issues = assess_geometry(report_data)\n    if False:",
        test="tests/test_intake_and_shell.py::test_pipeline_refuses_to_sign_report_violating_contract",
    ),
    Mutation(
        label="runner 无条件 mark_task_done（覆盖引擎写的 failed）",
        rel="app/core/runner.py",
        old='                if d.get("status") == "failed":',
        new='                if False:',
        test="tests/test_intake_and_shell.py::test_runner_honours_failed_done",
    ),
    Mutation(
        label="副标题设施数退回采集总数（口径失真：读者据此高估本区设施密度）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old="共 {poi_in_reach} 处设施（可达区内）",
        new='共 {poi.get("total") or 0} 处设施（可达区内）',
        test="tests/test_report_invariants.py::test_subtitle_counts_in_circle_not_total",
    ),
    Mutation(
        label="地点前缀不判空（恢复「昆明市 · ｜综合 …」悬空分隔符）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='    joined = " · ".join(p for p in parts if p)\n    return f"{joined}｜" if joined else ""',
        new='    joined = f"{parts[0]} · {parts[1]}"\n    return f"{joined}｜"',
        test="tests/test_report_invariants.py::test_subtitle_has_no_dangling_separator_when_address_empty",
    ),
    Mutation(
        label="地点全未知时仍输出「｜」（孤立的段分隔符开头）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='    return f"{joined}｜" if joined else ""',
        new='    return f"{joined}｜"',
        test="tests/test_report_invariants.py::test_subtitle_omits_whole_prefix_when_location_unknown",
    ),
    Mutation(
        label="一律省略地点前缀（掩盖地址信息）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='    joined = " · ".join(p for p in parts if p)',
        new='    joined = ""',
        test="tests/test_report_invariants.py::test_subtitle_keeps_address_when_present",
    ),
    Mutation(
        label="跨行 f-string 吞掉分隔符前的空格（「盲区· 共」）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='f" · 共 {poi_in_reach} 处设施（可达区内）"',
        new='f"· 共 {poi_in_reach} 处设施（可达区内）"',
        test="tests/test_report_invariants.py::test_subtitle_separator_spacing_is_intact",
    ),
    # ── rev2 · 证据相三条（B5 / B10 / B11）──────────────────────────
    Mutation(
        label="丢掉「余量≤0」判据（B5：D2 余量 0 回退不再现形）",
        rel="app/living_circle/report_contract.py",
        old="    if margin is not None and margin <= 0:",
        new="    if False:",
        test="tests/test_report_contract.py::test_evidence_margin_zero_is_flagged",
    ),
    Mutation(
        label="丢掉「带缺口不得称完整」判据（B5：谎报证据面）",
        rel="app/living_circle/report_contract.py",
        old="        if complete is True and ev_radius < collect - EVIDENCE_RECOMPUTE_TOL_M:",
        new="        if False:",
        test="tests/test_report_contract.py::test_complete_flag_with_short_frontier_is_flagged",
    ),
    Mutation(
        label="丢掉判定域复算判据（B10：judge_radius 与证据脱钩）",
        rel="app/living_circle/report_contract.py",
        old="        if abs(judge - expected_judge) > EVIDENCE_RECOMPUTE_TOL_M:",
        new="        if False:",
        test="tests/test_report_contract.py::test_judge_radius_not_derived_from_evidence_is_flagged",
    ),
    Mutation(
        label="丢掉「未判格必须全有归因」判据（B10：判不了冒充不盲）",
        rel="app/living_circle/report_contract.py",
        old="        if judged == 0 and gap != 0:",
        new="        if False:",
        test="tests/test_report_contract.py::test_zero_judged_cells_must_all_be_accounted",
    ),
    Mutation(
        label="B10 退回按两态算（把接口封顶那一位从归因面里丢掉）⇒ 纯封顶自洽报告被自家门拒发",
        rel="app/living_circle/report_contract.py",
        old="        accounted = unknown + (capped or 0.0)",
        new="        accounted = unknown",
        test="tests/test_report_contract.py::test_zero_judged_with_the_cap_accounted_is_issuable",
    ),
    Mutation(
        label="丢掉「低覆盖率不得称 full」判据（B11 降档方向）",
        rel="app/living_circle/report_contract.py",
        old='    if share is not None and conf == "full" and share < 1.0 - FULL_JUDGE_SHARE_TOL:',
        new="    if False:",
        test="tests/test_report_contract.py::test_full_confidence_with_partial_coverage_is_flagged",
    ),
    Mutation(
        label="丢掉扣分复算判据（B11：扣分被改回只按条数也无人追究）",
        rel="app/living_circle/report_contract.py",
        old="        if got is None or abs(got - expected_pen) > PENALTY_RECOMPUTE_TOL:",
        new="        if False:",
        test="tests/test_report_contract.py::test_penalty_reverted_to_count_only_is_flagged",
    ),
    # ── 片 A（#86）：measure 那两句话的规格必须来自 `sampling.spec`，不是抄来的档位常数 ──
    # 这三条不是"防别人手滑"，是防**我自己下轮重构时把它抄回去**（旧写法读起来更顺，
    # 而全仓此前零测试锚这两句 ⇒ 抄回去没人报警；详见 skip/tmp/plan-a-measure-copy.md）。
    Mutation(
        label="片 A 复发：发起句重新抄上「粗扫 400m → 边界带加密」（此刻规格还没产出）",
        rel="app/core/pipeline/living_circle.py",
        old='    yield _ev("message", {"stage": "measure", "percent": 30, "text": "批量距离矩阵测时采样中…（生效采样规格随档位与本次预算，产出那一步如实披露）"})',
        new='    yield _ev("message", {"stage": "measure", "percent": 30, "text": "粗扫 400m 网格 → 15min 边界带加密 → 批量距离矩阵测时中…"})',
        test="tests/test_measure_copy.py::test_a_t1_lead_message_carries_no_spacing_number_at_all",
    ),
    Mutation(
        label="片 A 复发：生效句把加密步长抄回档位常数（standard 的 150m 冒充一切档位）",
        rel="app/core/pipeline/living_circle.py",
        old="f\"{_spec['fine_m']:g}m）\"",
        new="f\"150m）\"",
        test="tests/test_measure_copy.py::test_a_t2_two_stage_note_reads_the_spec_not_the_profile_constant",
    ),
    Mutation(
        label="片 A 复发：降级句改回「放弃边界加密带」（quick 从没带可放弃 ⇒ 对 quick 说谎）",
        rel="app/core/pipeline/living_circle.py",
        old='"；**预算受限已降规格**：退回单阶段粗网格，插值格距 "',
        new='"；**预算受限已降规格**：放弃边界加密带，插值格距 "',
        test="tests/test_measure_copy.py::test_a_t3_degraded_note_reads_both_step_numbers_from_spec",
    ),
    Mutation(
        label="G1 复发：「最近 X 分钟」退回只卡时间、不卡可达多边形",
        rel="app/living_circle/assemble.py",
        old="        if not point_in_ring((float(pt[0]), float(pt[1])), scope.reach_ring):\n            return None",
        new="        if False:\n            return None",
        test="tests/test_report_invariants.py::test_g1_out_of_polygon_point_must_not_set_min_minutes",
    ),
    Mutation(
        label="缺陷 1 复发：邻近命中也沿用本次 scene_key 的旧行 id（展示新内容、DB 指旧行）",
        rel="app/core/pipeline/living_circle.py",
        old="                None if served_from == \"nearby_cache\"\n                else db.get_latest_report_id_for_scene(scene_key)",
        new="                db.get_latest_report_id_for_scene(scene_key)",
        test="tests/test_intake_and_shell.py::test_nearby_cache_hit_persists_the_served_content",
    ),
    Mutation(
        label="片 E 复发：后端「未检出」尾句被改一字 ⇒ 两端值分叉（判据第一条腿必须红）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='_LC_ELDERLY_UNDETECTED_TAIL = "，现役检索词表未检出（读作“未检出”，不等于“不存在”）"',
        new='_LC_ELDERLY_UNDETECTED_TAIL = "，现役检索词表未检出（读作“未检出”，不等于“不缺”）"',
        test="tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends",
    ),
    Mutation(
        label="片 E 复发：前端演示态那份常量单独改一字 ⇒ 同一个事实两种说法（必须红，证明前端也被比着）",
        rel="../frontend/src/mocks/livingCircleReports.ts",
        old="const LC_ELDERLY_UNDETECTED_CLAIM = '未检出（圈内 0 处，按现役名称词表检索无命中）'",
        new="const LC_ELDERLY_UNDETECTED_CLAIM = '未检出（圈内 0 处，按现役名称词表检索有命中）'",
        test="tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends",
    ),
    Mutation(
        label="片 E 复发：后端正文不引常量、把「属显著缺口」那句抄回字面量 ⇒ 假同源（必须红在使用处数那条腿）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old="{(_LC_ELDERLY_UNDETECTED_TAIL if missing else '')}",
        new="{('，属显著缺口，适老化优先级最高' if missing else '')}",
        test="tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends",
    ),
    Mutation(
        label="片 E 复发：前端正文不引常量、把旧那句「缺少机构养老资源」抄回演示态",
        rel="../frontend/src/mocks/livingCircleReports.ts",
        old="${missing ? LC_ELDERLY_UNDETECTED_CAUSE : `最近「${el?.nearest_name}」${fmtMin(el?.min_minutes ?? null)}。`}",
        new="${missing ? '该样区老年群体步行可达范围内缺少机构养老资源，需在整改建议中列为 P0 项。' : `最近「${el?.nearest_name}」${fmtMin(el?.min_minutes ?? null)}。`}",
        test="tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends",
    ),
    Mutation(
        label="片 E 复发：把退役的「属显著缺口」说法抄回「覆盖正常」那支 ⇒ 只有退役短语那条腿能红（证明第 ④ 条腿在承重）",
        rel="app/core/pipeline/diagnosis_templates.py",
        old='else "养老配置覆盖正常"',
        new='else "养老配置覆盖正常（属显著缺口已补齐）"',
        test="tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends",
    ),
    # ── U5（#94 重采前置）：缓存落点那颗保护型开关的两条复发形状 ──
    Mutation(
        label="U5 复发：pipeline 把缓存文件名写回死路径 ⇒ 只有接线腿能红（开关对真实链路失效）",
        rel="app/core/pipeline/living_circle.py",
        old="SqliteCache(resolve_cache_path())",
        new='SqliteCache(Path(__file__).resolve().parents[2] / "lc_cache.db")',
        test="tests/test_repository.py::test_u5_4_pipeline_takes_its_cache_location_from_the_resolver",
    ),
    Mutation(
        label="U5 复发：resolver 读不到 LC_CACHE_PATH（当成没设）⇒ 只有两态对照那条腿能红",
        rel="app/living_circle/repository.py",
        old="    override = os.environ.get(CACHE_PATH_ENV)",
        new='    override = ""',
        test="tests/test_repository.py::test_u5_2_env_redirects_every_write",
    ),
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run_test(node: str) -> tuple[bool, str]:
    tb = subprocess.run(["mktemp", "-d"], capture_output=True, text=True).stdout.strip()
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "TMPDIR": tb,
    }
    r = subprocess.run(
        [PY, "-m", "pytest", node, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(BACKEND), capture_output=True, text=True, env=env,
    )
    tail = "\n".join((r.stdout or "").strip().splitlines()[-3:])
    return r.returncode == 0, tail


def main() -> int:
    failures: list[str] = []

    # 基线：所有目标用例在未变异时必须全绿（否则「红」无法归因于变异）
    nodes = sorted({m.test for m in MUTATIONS})
    print("=" * 92)
    print("基线：目标用例在未变异代码上必须全绿")
    print("=" * 92)
    for node in nodes:
        green, tail = _run_test(node)
        print(f"  {'✅' if green else '❌'} {node}")
        if not green:
            print(f"      {tail}")
            failures.append(f"基线不绿：{node}")

    print()
    print("=" * 92)
    print("变异：注入回归 → 目标用例必须转红 → 还原 → 必须再绿")
    print("=" * 92)
    for m in MUTATIONS:
        path = BACKEND / m.rel
        if not path.exists():
            failures.append(f"{m.label}: 文件不存在 {m.rel}")
            continue
        original = path.read_bytes()
        before = hashlib.sha256(original).hexdigest()
        text = original.decode("utf-8")
        n = text.count(m.old)
        if n != 1:
            failures.append(f"{m.label}: 目标片段命中 {n} 次（需恰为 1 次）—— 源码可能已漂移，需更新变异")
            print(f"  ❓ {m.label}\n      匹配 {n} 次，跳过")
            continue

        try:
            path.write_text(text.replace(m.old, m.new, 1), encoding="utf-8")
            green, tail = _run_test(m.test)
        finally:
            path.write_bytes(original)
            after = _sha(path)
            if after != before:
                print(f"  🚨 还原失败（sha 不一致）：{m.rel} —— 立即中止")
                return 2

        if green:
            failures.append(f"{m.label}: 变异后目标用例**仍为绿**（守卫/测试是摆设）")
            print(f"  ❌ {m.label}\n      变异后仍绿：{m.test}")
        else:
            print(f"  ✅ {m.label}\n      变异 → 红：{tail.splitlines()[-1] if tail else ''}")

    print()
    print("=" * 92)
    if failures:
        print(f"判别力校验：❌ {len(failures)} 项不通过")
        for f in failures:
            print(f"  · {f}")
    else:
        print(f"判别力校验：✅ 全部通过（{len(nodes)} 条基线 + {len(MUTATIONS)} 个变异）")
    print("=" * 92)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
