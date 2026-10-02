"""生活圈后端/前端夹具镜像守卫（契约级，v2 —— P0-A 架构修复）。

v1 用 **md5 逐字节** 比对，把「合法新增可选契约字段」误判为漂移（BE1）：
当当前算法给盲区新增 `footprint_meta`/`polygon_raw`（可选元数据，见
`report_contract.py:350` 与 `test_blindspot_marching.py::AS-1`），前端快照更新、
后端仍为 legacy，md5 即红——演变一次就要求全量重刷另一侧。

v2 改为**契约级比对**：
  - **必须一致集**（渲染核心，双侧须存在且深比较相等）：顶层 `scene/sampling/scores/
    poi/isochrones/caliber/data_origin/generated_at`，以及盲区用户可见字段
    `id/center/radius_m/missing_facilities/nearest/polygon`。这些是真漂移 → 判红。
  - **可选元数据可单向增补**：盲区 `footprint_meta`/`polygon_raw` 允许仅一侧存在；
    双侧都有的关键判据 `footprint_meta.schema_version` 须一致，否则判红。
  - **坏输入判红**：任一侧非对象或缺必须键，直接判红（不静默放行）。
md5 不再作为崩溃判据。

判据封装为纯函数 `assert_mirror_consistent(back, front) -> list[str]`，便于单测驱动。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT = BACKEND_DIR.parent  # skip/
FRONTEND_FIXTURES = PROJECT / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"

# 顶层：渲染核心，必须双侧存在且值相等（真漂移）。
REQUIRED_TOP: List[str] = [
    "data_origin",
    "sampling",
    "scores",
    "poi",
    "isochrones",
    "scene",
    "caliber",
    "generated_at",
]
# 盲区：用户可见字段（必须双侧存在且相等）。
REQUIRED_BLINDSPOT: List[str] = [
    "id",
    "missing_facilities",
    "nearest",
    "polygon",
    "center",
    "radius_m",
]


def _load(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def assert_mirror_consistent(back: Any, front: Any) -> List[str]:
    """契约级镜像一致性判据。返回 violations（空列表 = 一致）。"""
    violations: List[str] = []

    if not isinstance(back, dict) or not isinstance(front, dict):
        return ["顶层不是 JSON 对象（坏输入），禁止放行"]
    if "blindspots" not in back or "blindspots" not in front:
        return ["顶层缺失 blindspots（坏输入），禁止放行"]

    # ① 顶层渲染核心：存在 + 深比较相等（对称闭包：一侧缺 key 即红）。
    all_top = set(REQUIRED_TOP)
    missing = all_top - back.keys() | (all_top - front.keys())
    if missing:
        violations.append(f"顶层缺失必须键: {sorted(x for x in missing if x in REQUIRED_TOP) or '见后'}")
    for key in REQUIRED_TOP:
        if back.get(key) != front.get(key):
            violations.append(f"顶层『{key}』两侧不一致（真漂移）")

    # ② 盲区：数量 + 逐项用户可见字段一致；可选元数据允许单向增补。
    bb, bf = back["blindspots"], front["blindspots"]
    if not isinstance(bb, list) or not isinstance(bf, list):
        violations.append("盲区必须是数组")
        return violations
    if len(bb) != len(bf):
        violations.append(f"盲区数量不一致: backend={len(bb)} frontend={len(bf)}（真漂移）")
        return violations

    by_id_b = {x.get("id"): x for x in bb if isinstance(x, dict)}
    by_id_f = {x.get("id"): x for x in bf if isinstance(x, dict)}
    if by_id_b.keys() != by_id_f.keys():
        violations.append(f"盲区 id 集合不一致: {sorted(by_id_b.keys())} vs {sorted(by_id_f.keys())}")
        return violations

    for bid in by_id_b:
        b, f = by_id_b[bid], by_id_f[bid]
        for key in REQUIRED_BLINDSPOT:
            if key not in b or key not in f:
                violations.append(f"盲区 {bid} 缺用户可见键 {key}")
            elif b[key] != f[key]:
                violations.append(f"盲区 {bid}『{key}』两侧不一致（真漂移）")
        # 可选元数据：默认允许单侧存在；仅当双侧都有时做一致性核对。
        # footprint_meta 以 schema_version 为硬判据；polygon_raw 以整体相等为判据。
        if "footprint_meta" in b and "footprint_meta" in f:
            if (b["footprint_meta"] or {}).get("schema_version") != (f["footprint_meta"] or {}).get("schema_version"):
                violations.append(
                    f"盲区 {bid} footprint_meta.schema_version 冲突: "
                    f"{(b['footprint_meta'] or {}).get('schema_version')} vs "
                    f"{(f['footprint_meta'] or {}).get('schema_version')}"
                )
        if "polygon_raw" in b and "polygon_raw" in f and b["polygon_raw"] != f["polygon_raw"]:
            violations.append(f"盲区 {bid}『polygon_raw』双侧都有但不一致")
    return violations


def _pair_mirror_check(backend_f: Path, front_f: Path) -> List[str]:
    if not front_f.exists() or not backend_f.exists():
        return [f"夹具缺失: 后端={backend_f.exists()} 前端={front_f.exists()} —— {backend_f.name}"]
    return assert_mirror_consistent(_load(backend_f), _load(front_f))


def test_living_circle_fixtures_mirror_frontend():
    pairs = [
        (BACKEND_DIR / "app" / "living_circle" / "fixtures" / "kaili.json",
         FRONTEND_FIXTURES / "kaili.json"),
        (BACKEND_DIR / "app" / "living_circle" / "fixtures" / "beijing-jinsong.json",
         FRONTEND_FIXTURES / "beijing-jinsong.json"),
    ]
    failures = []
    for backend_f, front_f in pairs:
        v = _pair_mirror_check(backend_f, front_f)
        if v:
            failures.append(f"\n— {backend_f.name}:\n\t" + "\n\t".join(v))
    assert not failures, "镜像契约不一致（表现层漂移）:" + "".join(failures)


# ── 净正向/负向单测（纯函数驱动，不依赖真实文件）──────────────
def _mk_bs(bid="bs-1") -> Dict[str, Any]:
    return {
        "id": bid, "center": [1.0, 2.0], "radius_m": 500.0,
        "missing_facilities": ["market"], "nearest": [{"name": "X"}],
        "polygon": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]},
    }


def _mk_report(**over) -> Dict[str, Any]:
    base = {
        "data_origin": "live", "sampling": {"interpolation": "idw"},
        "scores": {"total": 80}, "poi": {"points": []},
        "isochrones": {"0": []}, "scene": {"center": [1.0, 2.0]},
        "caliber": {"mode": "walk"}, "generated_at": "2026-09-19T12:00:00.000Z",
        "blindspots": [_mk_bs()],
    }
    base.update(over)
    return base


def test_identical_reports_pass():
    assert assert_mirror_consistent(_mk_report(), _mk_report()) == []


def test_optional_meta_one_side_only_is_legal():
    """P0-A 目标：盲区可选元数据只在前端存在 → 合法，不判红。"""
    front = _mk_report()
    front["blindspots"][0]["footprint_meta"] = {"schema_version": 1, "grid": "square", "cells": 4}
    front["blindspots"][0]["polygon_raw"] = front["blindspots"][0]["polygon"]
    assert assert_mirror_consistent(_mk_report(), front) == []


def test_optional_meta_both_sides_equal_is_legal():
    b = _mk_report(); f = _mk_report()
    for d in (b, f):
        d["blindspots"][0]["footprint_meta"] = {"schema_version": 1, "grid": "square", "cells": 4}
    assert assert_mirror_consistent(b, f) == []


def test_schema_version_conflict_flagged():
    b = _mk_report(); f = _mk_report()
    b["blindspots"][0]["footprint_meta"] = {"schema_version": 1, "grid": "square"}
    f["blindspots"][0]["footprint_meta"] = {"schema_version": 2, "grid": "square"}
    v = assert_mirror_consistent(b, f)
    assert any("schema_version" in x for x in v)


def test_user_visible_polygon_drift_flagged():
    f = _mk_report()
    f["blindspots"][0]["polygon"]["coordinates"] = [[[9, 9], [2, 1], [2, 2], [1, 1]]]
    v = assert_mirror_consistent(_mk_report(), f)
    assert any("polygon" in x for x in v)


def test_render_core_poi_drift_flagged():
    f = _mk_report()
    f["poi"] = {"points": [{"name": "never_rendered_core_drift"}]}
    assert any("poi" in x for x in assert_mirror_consistent(_mk_report(), f))


def test_render_core_scores_drift_flagged():
    f = _mk_report()
    f["scores"] = {"total": 41}
    assert any("scores" in x for x in assert_mirror_consistent(_mk_report(), f))


def test_missing_required_key_flagged():
    f = _mk_report()
    del f["isochrones"]
    assert any("isochrones" in x for x in assert_mirror_consistent(_mk_report(), f))


def test_bad_input_flagged():
    assert assert_mirror_consistent("nope", _mk_report()) != []
    assert assert_mirror_consistent(_mk_report(), [1, 2]) != []
    assert assert_mirror_consistent({"data_origin": "x"}, _mk_report()) != []


def test_cov_stop_line_note_is_one_text_on_both_ends():
    """第 22 轮 R22-1 的连带：那句"停止线按点数、分子按门槛项"在两端是**两份物理字面量** ⇒ 得有人比。

    后端 `diagnosis_templates._COV_STOP_LINE_NOTE` 进生产正文，前端 `mocks/livingCircleReports.ts`
    的同名常量进演示态正文（演示数字来自这里）。前端**拿不到满分线数值**（`ideal_circle` 不在报告
    payload 里，§十九），所以两边都写成**条件句**才可能逐字相同。改一边忘另一边 ⇒ 同一个事实两种说法，
    而今天没有任何东西会红 —— 本条就是补那只眼睛（与夹具双侧 md5 那条同一分工，只是对象换成文案）。
    """
    import re

    from app.core.pipeline import diagnosis_templates as dt

    py_note = dt._COV_STOP_LINE_NOTE
    ts_path = PROJECT / "frontend" / "src" / "mocks" / "livingCircleReports.ts"
    ts_src = ts_path.read_text(encoding="utf-8")
    block = re.search(r"const COV_STOP_LINE_NOTE =\s*(.*?)\n\n", ts_src, re.S)
    assert block, f"前端那份常量没了（{ts_path.name}）⇒ 演示态那句交代静默消失"
    ts_note = "".join(re.findall(r"'([^']*)'", block.group(1)))

    assert py_note, "后端常量是空串 ⇒ 下面那句等值断言恒真"
    for token in ("停止线", "圈内点数", "门槛项"):
        assert token in py_note, f"抽到的不是那句话（缺「{token}」）⇒ 本条在比空串"
    assert py_note == ts_note, (
        f"两端已分叉：后端「{py_note[:18]}…」vs 前端「{ts_note[:18]}…」"
        "⇒ 同一个事实在生产正文与演示正文里有两种说法")

    # 常量存在 ≠ 正文用了它：两个消费者各引用一次才算真同源（否则只是两份没人读的字符串）
    py_src = (BACKEND_DIR / "app" / "core" / "pipeline" / "diagnosis_templates.py").read_text(encoding="utf-8")
    assert py_src.count("+ _COV_STOP_LINE_NOTE") == 2, (
        f"后端引用该常量的正文处数 = {py_src.count('+ _COV_STOP_LINE_NOTE')}（应为 2：医疗缺口分支 + 教育那句）"
        " ⇒ 常量还在、正文里已经没有它 = 假同源")
    assert ts_src.count("${COV_STOP_LINE_NOTE}") == 2, (
        f"前端插值处数 = {ts_src.count('${COV_STOP_LINE_NOTE}')}（应为 2，同上）")


def test_evidence_gap_note_is_one_text_on_both_ends():
    """片 R23-A（乙）+ R23-B1：「没查过 / 没查全 / 整轮没扩词」那半句在两端是**六份物理字面量 + 一条拼装规则** ⇒ 逐条比。

    与上面那条同一分工，只是对象换成一组常量：后端 `diagnosis_templates._GAP_*` 进生产正文，
    前端 `mocks/livingCircleReports.ts` 的 `GAP_*` 进演示态正文。改一边忘另一边 ⇒ 同一个事实
    两种说法，且今天没有任何东西会红。⚠️ 只比常量还不够 —— 常量在、正文没引用 = 假同源，
    所以两条"消费者计数"断言必须在（各 3 处：定义 1 + 医疗节 1 + 教育节 1）。
    """
    import re

    from app.core.pipeline import diagnosis_templates as dt

    ts_path = PROJECT / "frontend" / "src" / "mocks" / "livingCircleReports.ts"
    ts_src = ts_path.read_text(encoding="utf-8")
    pairs = {
        "GAP_LEAD": dt._GAP_LEAD,
        "GAP_STARVED": dt._GAP_STARVED,
        "GAP_TRUNCATED": dt._GAP_TRUNCATED,
        "GAP_UNFUNDED": dt._GAP_UNFUNDED,
        "GAP_JOIN": dt._GAP_JOIN,
        "GAP_TAIL": dt._GAP_TAIL,
    }
    for name, py_val in pairs.items():
        assert py_val, f"后端常量 _{name} 是空串 ⇒ 本条对它是恒真"
        block = re.search(rf"^const {name} = '([^']*)'$", ts_src, re.M)
        assert block, f"前端常量 {name} 没了或不再是单行单引号字面量 ⇒ 镜像判据抽不到它"
        assert py_val == block.group(1), (
            f"{name} 两端已分叉：后端「{py_val[:16]}…」vs 前端「{block.group(1)[:16]}…」")

    # 拼装规则也只许一份：两个消费者各引一次
    py_src = (BACKEND_DIR / "app" / "core" / "pipeline" / "diagnosis_templates.py").read_text(encoding="utf-8")
    for src, label, needle in ((py_src, "后端 _evidence_gap_note(", "_evidence_gap_note("),
                               (ts_src, "前端 evidenceGapNote(", "evidenceGapNote(")):
        assert src.count(needle) == 3, (
            f"{label}出现 {src.count(needle)} 次（应为 3：定义 1 + 医疗节 1 + 教育节 1）"
            " ⇒ 函数还在、正文里已经没有它 = 假同源")