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
    # ── 4a 探针四条（`tests/test_probe_timeaxis_shape.py`）───────────────
    # 这组变异打的是 **脚本文件**而不是 `app/`：探针花真实额度，它自己的形状判据
    # 与生产判据同等重要（首跑就因为坐标顺序写反把 13 次调用换成零行数据）。
    Mutation(
        label="4a 事故本身：destinations 退回 lng,lat ⇒ 整批 status=2、零行数据",
        rel="scripts/probe_baidu.py",
        old='        "destinations": f"{dest_latlng[0]},{dest_latlng[1]}",',
        new='        "destinations": f"{dest_latlng[1]},{dest_latlng[0]}",',
        test="tests/test_probe_timeaxis_shape.py::test_matrix_request_sends_both_origins_and_destinations_as_lat_lng",
    ),
    Mutation(
        label="探针另打一条端点（directionlite）⇒ 能力结论对生产链不再适用",
        rel="scripts/probe_baidu.py",
        old='MATRIX_PATHS = {"walking": "/routematrix/v2/walking", "riding": "/routematrix/v2/riding",',
        new='MATRIX_PATHS = {"walking": "/directionlite/v1/walking", "riding": "/routematrix/v2/riding",',
        test="tests/test_probe_timeaxis_shape.py::test_matrix_path_is_read_from_the_same_table_as_production",
    ),
    Mutation(
        label="边界选点取消「点数不足就拒绝」⇒ 偏样本照样自称 n=20",
        rel="scripts/probe_baidu.py",
        old="    if len(pts) < want or len(center) != 2:",
        new="    if len(center) != 2:",
        test="tests/test_probe_timeaxis_shape.py::test_boundary_sample_is_stratified_deterministic_and_refuses_thin_bands",
    ),
    Mutation(
        label="把花额度的组并进默认列表 ⇒ 任何一次裸跑都静默烧一整轮额度",
        rel="scripts/probe_baidu.py",
        old='    groups = sys.argv[1:] or ["geo", "poi", "route", "matrix", "conv", "geocode"]',
        new='    groups = sys.argv[1:] or ["geo", "poi", "route", "matrix", "conv", "geocode", "timeaxis", "rowfields"]',
        test="tests/test_probe_timeaxis_shape.py::test_quota_spending_groups_are_not_in_the_default_run",
    ),
    Mutation(
        label="丢掉阴性对照键 ⇒ 「值没变」被读成「接口不支持」（假结论）",
        rel="scripts/probe_baidu.py",
        old='DEADBEEF = "probe_deadbeef_4a"        # 阴性对照键：任何真实接口都不该认识它',
        new='DEADBEEF = ""        # 阴性对照键：任何真实接口都不该认识它',
        test="tests/test_probe_timeaxis_shape.py::test_negative_controls_are_declared_not_improvised",
    ),
    # ── 笔 B｜口径对照环 7 条（`tests/test_iso_compare_ring.py`）──────────
    # 其中第二条就是 10-06 当天的真实事故：`_apply_manifest_caliber` 逐字段手抄重建，
    # 新字段 `iso_compare_min` 没进清单 ⇒ 步行档写了 8.0、`get_caliber` 拿回来是 None，
    # 整条对照环静默不产出。改成 `dataclasses.replace` 之后，这条变异必须撞红哨兵往返判据。
    Mutation(
        label="口径表取消步行档的对照阈值 ⇒ 勾选项永远是灰的",
        rel="app/living_circle/caliber.py",
        old="        iso_compare_min=8.0,\n",
        new="",
        test="tests/test_iso_compare_ring.py::test_walking_field_produces_the_compare_ring_alongside_four_zones",
    ),
    Mutation(
        label="manifest 重建退回逐字段手抄（今天的真实漏抄形状）",
        rel="app/living_circle/caliber.py",
        old="    return replace(caliber, api=api, measured=measured)",
        new="    return ReachCaliber(travel_mode=caliber.travel_mode, speed_m_per_min=caliber.speed_m_per_min,\n"
            "        detour_k=caliber.detour_k, study_radius_m=caliber.study_radius_m,\n"
            "        iso_minutes=caliber.iso_minutes, reach_full_min=caliber.reach_full_min, api=api,\n"
            "        basis=caliber.basis, measured=measured, blind_radius_m=caliber.blind_radius_m)",
        test="tests/test_iso_compare_ring.py::test_manifest_application_touches_only_api_and_measured",
    ),
    Mutation(
        label="引擎不发对照环（整位消失）",
        rel="app/living_circle/isochrone.py",
        old='        if iso_compare is not None:\n            out["iso_compare"] = iso_compare\n',
        new="",
        test="tests/test_iso_compare_ring.py::test_walking_field_produces_the_compare_ring_alongside_four_zones",
    ),
    Mutation(
        label="把对照环并进四档 ⇒ 第五条线冒充政策档（配色表与面积单调性都会误读）",
        rel="app/living_circle/isochrone.py",
        old='        if iso_compare is not None:\n            out["iso_compare"] = iso_compare',
        new='        if iso_compare is not None:\n'
            '            zones.append({k: iso_compare[k] for k in ("minutes", "geojson", "area_km2")})\n'
            '            out["iso_compare"] = iso_compare',
        test="tests/test_iso_compare_ring.py::test_walking_field_produces_the_compare_ring_alongside_four_zones",
    ),
    Mutation(
        label="引擎抄第二份阈值 ⇒ 骑行/驾车也跟着发（把步行文献贴到车速上）",
        rel="app/living_circle/isochrone.py",
        old="        compare_min = get_caliber(travel_mode).iso_compare_min",
        new="        compare_min = 8.0",
        test="tests/test_iso_compare_ring.py::test_non_walking_modes_declare_nothing_and_emit_nothing",
    ),
    Mutation(
        label="B16 把「缺席」判成违规 ⇒ 离线件与所有存量报告一起从历史列表里消失",
        rel="app/living_circle/report_contract.py",
        old="    if cmp_zone is None:\n        return []",
        new='    if cmp_zone is None:\n        return ["对照环缺席"]',
        test="tests/test_iso_compare_ring.py::test_absent_compare_ring_is_legal",
    ),
    Mutation(
        label="B16 不罚能力断言式 claim ⇒ 群体窗口被写成具体居民走不到",
        rel="app/living_circle/report_contract.py",
        old='    if cmp_zone.get("claim") != "caliber_comparison_only":',
        new="    if False:",
        test="tests/test_iso_compare_ring.py::test_capability_claim_is_rejected",
    ),
    Mutation(
        label="离线链把对照环接回去 ⇒ 用估算场做的对照冒充实测读数",
        rel="app/living_circle/data_source.py",
        # 锚点跟的是发射处 `"isochrones": iso_zones,` —— 笔二给离线链摘形状键时把这里从
        # `iso["isochrones"]` 改成了 `iso_zones`，旧锚点因此命中 0 次（2026-10-07 台架实测）。
        old='            "isochrones": iso_zones,',
        new='            "isochrones": iso_zones,\n            "iso_compare": iso.get("iso_compare"),',
        test="tests/test_iso_compare_ring.py::test_offline_report_carries_no_compare_ring",
    ),
    Mutation(
        label="非有限测时值退回「不筛」（NaN 穿过 `<= 0` 判据）⇒ 标定整块染污而台账还说入样了",
        rel="app/living_circle/isochrone.py",
        old="        if m is None or not math.isfinite(float(m)):",
        new="        if m is None:",
        test="tests/test_reach_calibration.py::test_non_finite_minutes_are_untimed_and_never_poison_the_block",
    ),
    Mutation(
        label="B14 退回旧闸（只判 ≤0）⇒ `float(nan) <= 0` 为 False，NaN 标定值照样签发",
        rel="app/living_circle/report_contract.py",
        old="    if k is not None and not isfinite(float(k)):",
        new="    if False:",
        test="tests/test_reach_calibration.py::test_b14_rejects_a_poisoned_calibration_block",
    ),
    Mutation(
        label="B14 丢掉残差分位的有限性检查 ⇒ 非有限分位以「披露」的名义上屏",
        rel="app/living_circle/report_contract.py",
        old="        polluted = [name for name, v in res.items()\n"
            "                    if not isinstance(v, (int, float)) or not isfinite(float(v))]",
        new="        polluted: List[str] = []",
        test="tests/test_reach_calibration.py::test_b14_rejects_a_poisoned_calibration_block",
    ),
    Mutation(
        label="B17 形状口径：分相退回 floor（缺口被相邻方向最大值掩盖）",
        rel="app/living_circle/geo_utils.py",
        old="        k = int(((bearing(center, p) + 22.5) % 360.0) // SHAPE_BIN_DEG) % 8",
        new="        k = int((bearing(center, p) % 360.0) // SHAPE_BIN_DEG) % 8",
        test="tests/test_shape_caliber.py::test_bin_phase_is_a_caliber_not_an_implementation_detail",
    ),
    Mutation(
        label="B17 形状口径：圆度改由 bins_m 反推面积（长出第二个面积真源）",
        rel="app/living_circle/geo_utils.py",
        old="    eq_r = math.sqrt(area_km2 * 1_000_000.0 / math.pi)",
        new="    eq_r = sum(bins) / len(bins)",
        test="tests/test_shape_caliber.py::test_shape_scalars_are_derived_from_this_zone_only",
    ),
    Mutation(
        label="B17 契约整体早退（半代发、口径漂移全部静默）",
        rel="app/living_circle/report_contract.py",
        old="    if not with_shape:\n        return []                                   # 这套载荷没声明形状口径 ⇒ 整套跳过",
        new="    if True:\n        return []",
        test="tests/test_shape_caliber.py::test_b17_catches_half_emission",
    ),
    Mutation(
        label="B17 形状口径：词表顺序闸被摘（整体转一格没人报）",
        rel="app/living_circle/report_contract.py",
        old="        if [str(w) for w in words] != list(_DIRECTIONS):",
        new="        if False and [str(w) for w in words] != list(_DIRECTIONS):",
        test="tests/test_shape_caliber.py::test_b17_catches_word_table_rotated_out_of_order",
    ),
    Mutation(
        label="S22 签发侧容差放宽到 1e-2（读侧比签发侧松，绕过 B17 的载荷能上屏）",
        rel="app/living_circle/geo_utils.py",
        old="SHAPE_SCALAR_TOL = 1e-3",
        new="SHAPE_SCALAR_TOL = 1e-2",
        test="tests/test_fixture_mirror.py::test_shape_caliber_constants_are_one_value_on_both_ends",
    ),
    Mutation(
        label="**S28 元判据自证**：摘掉词表序闸 ⇒ 字段级元判据必须抓到（不是空判）",
        rel="app/living_circle/report_contract.py",
        old="        if [str(w) for w in words] != list(_DIRECTIONS):",
        new="        if False and [str(w) for w in words] != list(_DIRECTIONS):",
        test="tests/test_shape_caliber.py::test_every_declared_shape_field_moves_a_gate",
    ),
    Mutation(
        label="B17 档位集合回退成字面 (15.0, 20.0)（第二真源，收窄口径必假红）",
        rel="app/living_circle/report_contract.py",
        old="    for m in (float(x) for x in SHAPE_MINUTES):",
        new="    for m in (15.0, 20.0):",
        test="tests/test_shape_caliber.py::test_b17_tier_set_is_read_from_the_emission_valve",
    ),
    Mutation(
        label="B17 外接半径恒等式的前提守卫被摘（满分线挪出四档就假红）",
        rel="app/living_circle/report_contract.py",
        old="        if m is not None and abs(float(m) - reach_min) < 1e-6 and reach_min in iso_minutes:",
        new="        if m is not None and abs(float(m) - reach_min) < 1e-6:",
        test="tests/test_shape_caliber.py::test_b17_circumradius_identity_is_conditional",
    ),
    Mutation(
        label="发键口径收窄成只发 15min（引擎侧条件被改，20min 那圈上不了屏）",
        rel="app/living_circle/isochrone.py",
        old="SHAPE_MINUTES = (15, 20)",
        new="SHAPE_MINUTES = (15,)",
        test="tests/test_shape_caliber.py::test_engine_emits_shape_only_for_walking_15_and_20",
    ),
    Mutation(
        label="离线链不再摘形状键（数学正圆带着圆度 1.000 上屏）",
        rel="app/living_circle/data_source.py",
        old='        iso_zones = [{k: v for k, v in z.items() if k not in shape_zone_keys()}\n                     for z in iso["isochrones"]]',
        new='        iso_zones = list(iso["isochrones"])',
        test="tests/test_shape_caliber.py::test_offline_report_carries_no_shape_keys",
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
        # ⚠️ **不许写字节码缓存** —— 这条不是洁癖，是 2026-10-06 真实踩到的假阴性：
        # importlib 的 .pyc 校验只看 `(源文件 mtime 的整秒, 字节数)`。有些变异**恰好等长**
        # （例：`f"{a[0]},{a[1]}"` → `f"{a[1]},{a[0]}"`），而注入与还原发生在同一秒内
        # ⇒ 子进程加载到上一轮的旧 .pyc，变异没生效、判据照样绿，机器留证会把它误报成
        # "该守卫是摆设"。等长变异是常态而不是巧合，所以闸必须打在台架上，不是打在选词上。
        "PYTHONDONTWRITEBYTECODE": "1",
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
