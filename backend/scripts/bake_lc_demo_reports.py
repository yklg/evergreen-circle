"""离线演示报告 · 由后端装配器现产，烘进前端（让正文只有一个作者）。

用法：
  cd backend && python3 scripts/bake_lc_demo_reports.py          # 烘（写文件）
  cd backend && python3 scripts/bake_lc_demo_reports.py --check   # 只比对，不写（判据用）

为什么要有这个脚本：演示态那份报告正文原先由前端 TypeScript 又算了一遍
（`frontend/src/mocks/livingCircleReports.ts::buildLivingCircleReport`），它与后端
`core/pipeline/diagnosis_templates.py::assemble_report` 是**同一份 Report 契约的两个作者**，
而两侧之间没有任何强制对齐（那个文件自己在注释里承认了）。后果是实测出来的：
后端升到 `nar-3` 加的三张图（各类最近可达耗时 / 盲区散点 / 整改优先级）演示态一直没有，
演示态的专家署名还钉在一份过期的保底名册上（含 `L3-002`，而真名册里没有这个人）。

**按文件名点名，不按中心点匹配**：内置样区里唯一带逐格台账的那份是 `kaili-ev2`，
而 `data_source.py::FixtureDataSource._pick_key` 刻意把 `-evN` 变体排在基础样本之后
（2026-10-06 真事故的产物：同中心平手时谁先被遇到取决于目录顺序，开发机 65.4、CI 68.4）。
所以"跑一次 fixture 档体检"永远拿不到台账那一份 —— 本脚本直接按 stem 取载荷，绕开那条匹配。

产出：`frontend/src/mocks/fixtures/livingCircleReports/{stem}.report.json`
  - **剥掉 `living_circle` 载荷**：那三份夹具每张约 250KB，整份烘进 bundle 会翻倍。
    读路径把 `living_circle` 从 `livingCircleMock.ts` 已在 import 的同一份载荷拼回，
    所以字节内容不变，只是不再有两个作者。
  - `_` 前缀的键是生成元数据，不属于 Report 契约。
  - 那两句"来路"正文（概览章「数据口径：live；…」、结论章「提醒：本报告为真实接口取证…」）
    在演示件上换成"内置快照"的说法（见 `DEMO_ORIGIN_REWRITES` / `relabel_origin_for_demo`）：
    载荷确实是历史真实跑批留档，但**演示这一次一个接口都没调**，原话搬到演示态就是假话。

⚠️ 烘出来的是**某个代次的产物**：改了装配器就必须同笔重跑本脚本，否则
`backend/tests/test_lc_demo_report_mirror.py` 会红（形照 `test_narrative_assembly_golden.py`
的成对设计 —— 改了产物不重烘红，重烘了却没实质变化也红）。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.pipeline.diagnosis_templates import (  # noqa: E402
    NARRATIVE_VERSION,
    assemble_report,
)

FIXTURES_DIR = BACKEND_DIR / "app" / "living_circle" / "fixtures"
OUT_DIR = BACKEND_DIR.parent / "frontend" / "src" / "mocks" / "fixtures" / "livingCircleReports"

# 演示三件套 = 后端夹具目录里的三份载荷，按 stem 点名。
# 逐格台账只在 kaili-ev2 上（判盲 8 格 + 1 处盲区）；另两份是台账上线前冻结的件。
DEMO_STEMS: Tuple[str, ...] = ("kaili", "kaili-ev2", "beijing-jinsong")

# 读路径必须能拼回载荷 ⇒ 报告 id 沿用前端今天的 `LC_REPORT_ID(sceneId)` = `lc-{stem}`，
# 别名页（lc-kaili-r1 等）也继续解析到基础那份，演示态的路由与 e2e 锚点因此不受影响。
REPORT_ID = lambda stem: f"lc-{stem}"  # noqa: E731

# Report 的必填键（前端渲染器无条件消费的那些）。快照一旦少发一位，编译不红、
# 运行时才崩 —— 所以这里钉一份清单，烘的时候逐项断言（判据在 test_lc_demo_report_mirror.py）。
REQUIRED_REPORT_KEYS: Tuple[str, ...] = (
    "id",
    "report_type",
    "narrative_version",
    "title",
    "subtitle",
    "query",
    "mode",
    "created_at",
    "experts",
    "dispatch",
    "toc",
    "sections",
    "charts",
    "evidence",
    "claims",
    "glossary",
    "methodology",
)


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_fixture(stem: str) -> Dict[str, Any]:
    path = FIXTURES_DIR / f"{stem}.json"
    if not path.exists():
        raise FileNotFoundError(f"夹具不在：{path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _assert_is_this_sample(stem: str, lc: Dict[str, Any], report: Dict[str, Any]) -> None:
    """烘之前证明"点到的名 == 拿到的内容"，错配一律拒绝写盘。

    与 `snapshot_live.py::_assert_snapshot_is_this_scene` 同一意图：这条脚本的产物会被
    直接当演示事实源，一旦把别的东西烘进去，前后端两侧同时坏而测试仍绿（两侧同源）。
    三条各自拦一种复发：
      - 场景名/中心点：拿错文件（`kaili` 与 `kaili-ev2` 是同一社区的两轮口径，名字相同、
        中心点逐字相同 ⇒ 只有 stem 与"有没有台账"能区分它们，所以第三条才是关键）。
      - 台账在场性：`kaili-ev2` 的意义就是逐格台账。烘丢它等于演示态没有台账卡，
        而这正是这份件存在的唯一理由（见 livingCircleReports.ts 里"不列它就等于假交付"那条）。
    """
    scene = lc.get("scene") or {}
    problems: List[str] = []

    expected_center = scene.get("center") or []
    if len(expected_center) != 2:
        problems.append(f"载荷缺 scene.center（{expected_center!r}）")
    if not scene.get("name"):
        problems.append("载荷缺 scene.name")

    has_ledger = "cells_ledger" in (lc.get("caliber") or {})
    if stem.endswith("-ev2") and not has_ledger:
        problems.append("点名的是台账变体，但载荷里没有 caliber.cells_ledger ⇒ 要么拿错文件，要么夹具被重做过")
    if not stem.endswith("-ev2") and has_ledger:
        problems.append(f"{stem}  unexpectedly 带 cells_ledger ⇒ 两份凯里件的内容互串了")

    if report.get("narrative_version") != NARRATIVE_VERSION:
        problems.append(f"产物代次 {report.get('narrative_version')!r} ≠ 代码常量 {NARRATIVE_VERSION!r}")

    missing = [k for k in REQUIRED_REPORT_KEYS if k not in report]
    if missing:
        problems.append(f"产物缺 Report 必填键：{missing}")

    if problems:
        raise RuntimeError(f"{stem}: 拒绝烘进演示态 ——\n  - " + "\n  - ".join(problems))


# ── 演示件专用的「来路改写」────────────────────────────────────────
# 为什么必须有：烘出来的这三份是**仓库里躺着的历史真实跑批件**，而装配器写的两句正文都在
# 说"这份报告是刚跑的"（概览章「数据口径：live；…」、结论章「提醒：本报告为真实接口取证
# （data_origin=live）…」。真实态那一行走同一颗装配器、同一个 `data_origin=live`，那句话
# 对它是**成立的**；搬到演示态就成了一句假话 —— 演示一次采集都不发。
#
# 为什么住在烘件脚本而不是装配器：装配器只看得到载荷里的 `data_origin`，它**不知道**这份载荷
# 是三分钟前刚跑的还是仓里烘的；把"烘的"这件事塞进载荷身份会撞跨语言镜像闸
# （`test_fixture_mirror.py` 钉三份夹具两侧字节相同），把这句改写塞进前端又等于让前端重新写
# 正文（本轮刚拆掉的那个病灶）。所以由"烘"这个动作自己承认它带来的语义差。
#
# 为什么不用豁免名单：镜像闸（`test_lc_demo_report_mirror.py`）直接调用这颗函数，它的期望值
# 就是"改写后的当代产物" ⇒ 面级比较一条都不放过。豁免面一旦存在就会长大，这是那族病的起点。
#
# 形状：(装配器原文, 演示态说法)。每条**必须恰好命中 1 次**，命不中或多余命中一律抛错 ——
# 那意味着装配器把那两句话挪了/改了，此时宁可烘不动、让 CI 上有人看见，也不能把"真实取证"
# 那半句静默留在演示件上，也不能反过来把新增的第三句漏改。
DEMO_ORIGIN_REWRITES: Tuple[Tuple[str, str], ...] = (
    (
        "数据口径：live；",
        "数据口径：内置快照（历史真实跑批留档，本次演示未联网）；",
    ),
    (
        "提醒：本报告为真实接口取证（data_origin=live）",
        "提醒：本报告为内置快照（data_origin=live · 历史真实跑批留档，本次演示未发起采集）",
    ),
)


def relabel_origin_for_demo(report: Dict[str, Any]) -> Dict[str, Any]:
    """把装配器产物里那两句"来路"说法换成演示态成立的说法，返回新对象（不改原产物）。

    只动 `sections[*].paragraphs[*]`：证据的 `source_url=live://poi` 与
    `methodology.note=data_origin=live · …` 是**机器溯源指针**（原样照报载荷字段），
    不是"这次采了"的说法，所以刻意不碰它们 —— 碰了反而把可回溯的字段名改成不可回溯的文案。
    """
    hit_total: Dict[str, int] = {old: 0 for old, _ in DEMO_ORIGIN_REWRITES}
    sections = copy.deepcopy(report.get("sections") or [])
    for sec in sections:
        paras = sec.get("paragraphs")
        if not isinstance(paras, list):
            continue
        for i, text in enumerate(paras):
            if not isinstance(text, str):
                continue
            for old, new in DEMO_ORIGIN_REWRITES:
                n = text.count(old)
                if n:
                    hit_total[old] += n
                    text = text.replace(old, new)
            paras[i] = text
    out = dict(report)
    out["sections"] = sections

    problems = [
        f"「{old[:24]}…」命中 {hit_total[old]} 次（要求恰好 1 次）⇒ 装配器那句话挪了或改了，"
        f"烘件脚本的改写表要同笔跟上，不能把旧说法静默烘进演示件"
        for old, _ in DEMO_ORIGIN_REWRITES
        if hit_total[old] != 1
    ]
    if problems:
        raise RuntimeError(f"{report.get('id', '?')}: 拒绝烘进演示态 ——\n  - " + "\n  - ".join(problems))
    return out


def build(stem: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """返回 (剥掉载荷的快照, 原载荷)。"""
    lc = _load_fixture(stem)
    report = assemble_report(lc, REPORT_ID(stem), stem, "")
    _assert_is_this_sample(stem, lc, report)
    report = relabel_origin_for_demo(report)

    payload = dict(report)
    payload.pop("living_circle", None)  # 读路径从现成 import 拼回，见模块 docstring
    # `brands` 是旅游契约退役期留下的**恒空旧键**：`types.ts:424-425` 标成可选并注「兼容旧报告保留」，
    # 前端零消费方（grep `\.brands` 排除测试后为空），后端自己也只写死空数组
    # （`diagnosis_templates.py:1654`，`test_semantic_residue.py:52` 给它的是"legacy 空数组键、读兼容"这条豁免）。
    # 把它复制进前端新文件会要求为该目录新开一条"竞品语义"白名单豁免 —— 为一份恒空数组不值得，
    # 且缺席与在场在可选契约上等价。真态库里那行仍带它，我们不动它。
    payload.pop("brands", None)
    snapshot: Dict[str, Any] = {
        "_generated_by": "backend/scripts/bake_lc_demo_reports.py",
        "_source_fixture": f"backend/app/living_circle/fixtures/{stem}.json",
        "_narrative_version": report["narrative_version"],
        "_captured_at": _now_iso(),
        "_note": (
            "演示态报告正文快照。作者只有后端装配器（diagnosis_templates.py::assemble_report）；"
            "改了装配器必须同笔重跑本脚本，否则 test_lc_demo_report_mirror.py 红。"
            "`living_circle` 载荷不在这里，由 livingCircleMock.ts 现成的那份 import 在读时拼回。"
        ),
    }
    snapshot.update(payload)
    return snapshot, lc


def _stats(snapshot: Dict[str, Any], lc: Dict[str, Any]) -> str:
    charts = snapshot.get("charts") or []
    sections = snapshot.get("sections") or []
    highlights = sum(len(s.get("highlights") or []) for s in sections)
    experts = snapshot.get("experts") or []
    ledger = "有" if "cells_ledger" in (lc.get("caliber") or {}) else "无"
    return (
        f"{snapshot['id']:<20} 代次={snapshot['narrative_version']:<6} 章={len(sections)} "
        f"图={len(charts)} 亮点={highlights} 台账={ledger} "
        f"名册={len(experts)}人({experts[0]}…{experts[-1]})"
    )


def main(argv: List[str]) -> int:
    check = "--check" in argv
    if not OUT_DIR.exists() and not check:
        OUT_DIR.mkdir(parents=True)

    drift: List[str] = []
    for stem in DEMO_STEMS:
        snapshot, lc = build(stem)
        out = OUT_DIR / f"{stem}.report.json"
        if check:
            if not out.exists():
                drift.append(f"{out.name} 不在盘上（演示态缺这份快照）")
                continue
            with open(out, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            # 只比内容，不比生成时刻
            a = {k: v for k, v in snapshot.items() if not k.startswith("_captured_at")}
            b = {k: v for k, v in on_disk.items() if not k.startswith("_captured_at")}
            if a != b:
                drift.append(f"{out.name} 落后于当代装配器（改过 diagnosis_templates.py 没重烘）")
            else:
                print(f"[ok] {_stats(snapshot, lc)}")
            continue

        with open(out, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        print(f"[烘出] {_stats(snapshot, lc)}  → {out.relative_to(OUT_DIR.parent.parent.parent)}")

    if drift:
        print("\n".join(drift), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
