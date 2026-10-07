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

import pytest

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
        (BACKEND_DIR / "app" / "living_circle" / "fixtures" / "kaili-ev2.json",
         FRONTEND_FIXTURES / "kaili-ev2.json"),
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


def test_retired_stop_line_note_is_gone_from_both_ends():
    """R23-B2 撤句守卫：那句「停止线按点数、分子按门槛项」断言的是**两处单位不同** ——
    收手单位一改（`poi_collector._at_target` 与覆盖度分子读同一份实现）它就变成假话，
    所以撤句必须与换单位**同批**（计划 §4 B2 / §6 第 4 条）。

    判据按**句子本身**扫，不按常量名：改名留句这种情况锚在标识符上看不见。
    ⚠️ 同条内配活证人：同一次遍历必须看得见**仍在用**的那句（R23-B1 的第三子句），
    否则"扫到 0 处"可能只是根本没走进文件。
    """
    dirs = [PROJECT / "backend" / "app", PROJECT / "frontend" / "src"]
    files = [p for d in dirs for p in d.rglob("*") if p.is_file() and p.suffix in (".py", ".ts", ".tsx")]
    assert len(files) > 100, f"只扫到 {len(files)} 个文件 ⇒ 遍历没走通，下面的 0 处不算数"
    texts = {p: p.read_text(encoding="utf-8") for p in files}

    def where(needle: str) -> list:
        return sorted(str(p.relative_to(PROJECT)) for p, t in texts.items() if needle in t)

    retired = "不排除是采集先停的手"
    live = "本轮没有额度为这一类扩词"
    assert not where(retired), f"撤掉的句子还在 {where(retired)} ⇒ 换单位后这句话是假话"
    assert len(where(live)) >= 2, (
        f"活证人不足：「{live}」只见 {len(where(live))} 处（应 ≥2：后端常量 + 前端镜像）⇒ 这一屏扫不到正文")
    for name in ("_COV_STOP_LINE_NOTE", "COV_STOP_LINE_NOTE"):
        assert not where(name), f"常量名 {name} 仍被 {where(name)} 引用 ⇒ 撤得不干净"


def test_evidence_gap_note_is_one_text_on_both_ends():
    """片 R23-A（乙）+ R23-B1/B3/D：「没查过 / 没查全 / 它不给 / 没查成 / 整轮没扩词 / 扩到一半没钱」
    那半句在两端是**九份物理字面量 + 一条拼装规则** ⇒ 逐条比。

    与上面那条同一分工，只是对象换成一组常量：后端 `diagnosis_templates._GAP_*` 进生产正文，
    前端 `mocks/livingCircleReports.ts` 的 `GAP_*` 进演示态正文。改一边忘另一边 ⇒ 同一个事实
    两种说法，且今天没有任何东西会红。⚠️ 只比常量还不够 —— 常量在、正文没引用 = 假同源，
    所以两条"消费者计数"断言必须在（各 3 处：定义 1 + 医疗节 1 + 教育节 1）。

    ⚠️ R23-D 起**名单不再手写**：以前是一张固定字典，加一端子集就漏检（本文件当年靠我记得加条目）。
    现在两端各自枚举、再比**名字集合相等** ⇒ 任何一端单独多一个 `GAP_*` 都会红。
    """
    import re

    from app.core.pipeline import diagnosis_templates as dt

    ts_path = PROJECT / "frontend" / "src" / "mocks" / "livingCircleReports.ts"
    ts_src = ts_path.read_text(encoding="utf-8")

    py_side = {name[1:]: value for name, value in vars(dt).items() if name.startswith("_GAP_")}
    ts_side = dict(re.findall(r"^const (GAP_\w+) = '([^']*)'$", ts_src, re.M))
    assert py_side, "后端一个 `_GAP_*` 都没抽到 ⇒ 本条对它是恒真"
    assert set(py_side) == set(ts_side), (
        f"两端常量名集合已分叉：只有后端有 {sorted(set(py_side) - set(ts_side))}、"
        f"只有前端有 {sorted(set(ts_side) - set(py_side))}")
    # 抽不到 = 有人把它改成多行/双引号 ⇒ 判据会静默少比一条，必须当场报
    ts_declared = len(re.findall(r"^const GAP_\w+ =", ts_src, re.M))
    assert ts_declared == len(ts_side), (
        f"前端声明了 {ts_declared} 个 `GAP_*` 而正则只抽到 {len(ts_side)} 个"
        " ⇒ 有常量不再是「单行 + 单引号字面量」，本条对它失效")
    for name, py_val in py_side.items():
        assert py_val, f"后端常量 _{name} 是空串 ⇒ 本条对它是恒真"
        assert py_val == ts_side[name], (
            f"{name} 两端已分叉：后端「{py_val[:16]}…」vs 前端「{ts_side[name][:16]}…」")

    # 拼装规则也只许一份：定义 1 处 + 注册表里每一类一个消费者。
    # 为什么不再钉魔数 3：那等于把"只有医教两类能讲没查全"钉成当前形态，第 5 类要挂
    # 缺口注记必须先来改这条测试 ⇒ 名单退化成手工点取白名单。现在改由
    # `diagnosis_templates.GAP_NOTE_CATEGORIES` 供给，两端任一侧单独动仍红。
    py_src = (BACKEND_DIR / "app" / "core" / "pipeline" / "diagnosis_templates.py").read_text(encoding="utf-8")
    expect = 1 + len(dt.GAP_NOTE_CATEGORIES)
    for src, label, needle in ((py_src, "后端 _evidence_gap_note(", "_evidence_gap_note("),
                               (ts_src, "前端 evidenceGapNote(", "evidenceGapNote(")):
        assert src.count(needle) == expect, (
            f"{label}出现 {src.count(needle)} 次（应为 {expect}：定义 1 + "
            f"注册表 {list(dt.GAP_NOTE_CATEGORIES)} 各 1）"
            " ⇒ 函数还在、正文里已经没有它 = 假同源；或注册表与消费者已分叉")

def test_elderly_undetected_notes_are_one_text_on_both_ends():
    """片 E（#87 丙档）：养老那一维那四句「未检出」措辞在两端必须逐字同一份。

    后端 `diagnosis_templates._LC_ELDERLY_*` 进生产正文，前端 `mocks/livingCircleReports.ts`
    的 `LC_ELDERLY_*` 进演示态正文 —— 同一个事实两份物理字面量，改一边忘另一边不会有任何东西红。
    与 `test_evidence_gap_note_is_one_text_on_both_ends` 同一套三条腿：
    ① 名字集合相等（任何一端单独多一条就红）；② 值相等且期望值**从后端模块 import**（不是我抄的）；
    ③ 使用处数各 == 2（定义 1 + 正文 1）—— 常量还在而正文没引用 = 假同源。
    第 ④ 条是本刀特有的**退役断言**：那四句被撤掉的存在性说法不许再从任何一端漏回来。
    """
    import re

    from app.core.pipeline import diagnosis_templates as dt

    ts_path = PROJECT / "frontend" / "src" / "mocks" / "livingCircleReports.ts"
    py_path = BACKEND_DIR / "app" / "core" / "pipeline" / "diagnosis_templates.py"
    ts_src = ts_path.read_text(encoding="utf-8")
    py_src = py_path.read_text(encoding="utf-8")

    py_side = {name[1:]: value for name, value in vars(dt).items() if name.startswith("_LC_ELDERLY_")}
    ts_side = dict(re.findall(r"^const (LC_ELDERLY_\w+) = '([^']*)'$", ts_src, re.M))
    assert py_side, "后端一个 `_LC_ELDERLY_*` 都没抽到 ⇒ 本条对它是恒真"
    assert set(py_side) == set(ts_side), (
        f"两端常量名集合已分叉：只有后端有 {sorted(set(py_side) - set(ts_side))}、"
        f"只有前端有 {sorted(set(ts_side) - set(py_side))}")
    # 抽不到 = 有人把声明改成多行/双引号 ⇒ 判据会静默少比一条，必须当场报（同 GAP 那条的纪律）
    ts_declared = len(re.findall(r"^const LC_ELDERLY_\w+ =", ts_src, re.M))
    assert ts_declared == len(ts_side), (
        f"前端声明了 {ts_declared} 个 `LC_ELDERLY_*` 而正则只抽到 {len(ts_side)} 个"
        " ⇒ 有常量不再是「单行 + 单引号字面量」，本条对它失效")
    for name, py_val in py_side.items():
        assert py_val, f"后端常量 _{name} 是空串 ⇒ 本条对它是恒真"
        assert py_val == ts_side[name], (
            f"{name} 两端已分叉：后端「{py_val[:18]}…」vs 前端「{ts_side[name][:18]}…」")
        for src, label in ((py_src, "后端"), (ts_src, "前端")):
            used = src.count(f"_{name}" if label == "后端" else name)
            assert used == 2, (
                f"{label} {name} 出现 {used} 次（应为 2：定义 1 + 正文 1）"
                " ⇒ 常量还在、正文里没有它 = 假同源")

    # 10-03 甲-B 追加后三串：那三句**点名了具体检索词**，而词表当天就从 2 颗涨到 4 颗 ⇒
    # 列举式措辞与"词表会动"结构性冲突，抄回来就是假话。
    for retired in ("缺少机构养老资源", "严重不足（圈内 0 处）", "属显著缺口", "0 覆盖：建议引入",
                    "现役名称词只有", "现役词表不含社区级命名", "先按社区级命名补词重采",
                    "养老(养老院/日间照料)", "（养老院/日间照料中心）"):
        for src, label in ((py_src, "后端"), (ts_src, "前端")):
            assert retired not in src, f"{label}又漏回退役的存在性说法「{retired}」"

def test_shape_caliber_constants_are_one_value_on_both_ends():
    """**S22**：形状口径的四件声明 + 复算容差，后端与前端读侧必须是**同一把尺**。

    跨语言导不了常量 ⇒ 两端各留一份是既成事实，那就要有东西钉住它们相等。
    2026-10-06 审查实测过分叉：后端 B17 用 `1e-3`、前端 `shapeOfZone` 用 `1e-2`
    ⇒ 同一份 `circularity=0.718`（真值 0.7131）后端判违规、前端放行，
    读侧比签发侧松一个量级，正好把"手写 mock / 外部导入镜像会绕过 B17"那道防线反向松开。

    两端各自枚举、比名字集合与值，再做**消费者计数** —— 常量在、判据里没引用 = 假同源。
    照本文件 `_GAP_*` 那条同一手法，不新造机制。
    """
    import re

    from app.living_circle import geo_utils as gu

    ts_path = PROJECT / "frontend" / "src" / "lib" / "livingCircle.ts"
    ts_src = ts_path.read_text(encoding="utf-8")
    py_src = (BACKEND_DIR / "app" / "living_circle" / "geo_utils.py").read_text(encoding="utf-8")
    rc_src = (BACKEND_DIR / "app" / "living_circle" / "report_contract.py").read_text(encoding="utf-8")

    # 后端侧：不写死名单，扫声明 ⇒ 以后多加一件口径，这条自动要求前端也配
    py_declared = re.findall(r"^(SHAPE_[A-Z_]+) = ", py_src, re.M)
    py_side = {n.lower().removeprefix("shape_"): getattr(gu, n) for n in py_declared}
    assert py_side, "后端一个 SHAPE_* 都没扫到 ⇒ 本条恒真"

    m = re.search(r"const SHAPE_EXPECT = \{(.*?)\} as const", ts_src, re.S)
    assert m, "前端 SHAPE_EXPECT 块扫不到（改了写法？本条会静默少比，必须红）"
    ts_side = {}
    for key, raw in re.findall(r"^\s+(\w+):\s*([^,\n]+),?$", m.group(1), re.M):
        raw = raw.strip()
        ts_side[key] = float(raw) if raw and (raw[0].isdigit() or raw[0] == "-") else raw.strip("'")
    assert set(ts_side) == set(py_side), (
        f"口径声明两端名字集合已分叉：只有后端有 {sorted(set(py_side) - set(ts_side))}、"
        f"只有前端有 {sorted(set(ts_side) - set(py_side))}")
    for key, py_val in py_side.items():
        ts_val = ts_side[key]
        same = abs(float(py_val) - float(ts_val)) == 0 if isinstance(py_val, (int, float)) else py_val == ts_val
        assert same, f"{key} 两端已分叉：后端 {py_val!r} vs 前端 {ts_val!r}"

    # 消费者计数：定义 1 处 + 判据里至少 1 处，且**前端容差必须被两处判据各用一次**
    for const in py_declared:
        used = len(re.findall(rf"\b{const}\b", rc_src))
        assert used >= 2, (
            f"{const} 在 report_contract 里只出现 {used} 次（应为 import + 至少一处判据）"
            " ⇒ 常量挂着但签发闸没用它 = 假同源")
    tol_used = len(re.findall(r"SHAPE_EXPECT\.scalar_tol", ts_src))
    assert tol_used == 2, (
        f"前端 scalar_tol 被 {tol_used} 处判据使用（应为 2：圆度 + 比值）"
        " ⇒ 少一处就意味着那一侧还在用别的标尺")
    body = ts_src.split("export function shapeOfZone", 1)[1].split("\nexport function", 1)[0]
    bare = re.findall(r">\s*1e-\d", body)
    assert not bare, f"shapeOfZone 里又出现裸容差 {bare} ⇒ 绕过了 SHAPE_EXPECT.scalar_tol"


@pytest.mark.parametrize("key", REQUIRED_TOP)
def test_every_render_core_key_blocks_drift(key: str) -> None:
    """**S30（更正后的形态）**：「必须一致集」里每个键都要自己挡住单侧漂移。

    原计划写的是"镜像守卫只比 `isochrones`、不比 `caliber`"—— 那句是**假的**（从检索型
    子 Agent 的行号结论抄来、我没自己读循环）：`REQUIRED_TOP` 里就有 `caliber`，
    `assert_mirror_consistent` 第 70 行对整张表逐个深比较，实测四向都判红。

    真正的缺口在别处：本文件今天只给 `poi` / `scores` 写了"单侧漂移必红"的负向单测，
    `caliber` / `isochrones` / `scene` … 都没有。于是有人把某个键从 `REQUIRED_TOP` 里摘掉时
    —— 三对真夹具此刻是同步的 ⇒ 什么也不会红，守卫静默失守。
    这条按参数化遍历这张表 ⇒ 将来往表里加键，它自动被要求"真挡一次漂移"；
    而把任何一键摘出去，这一条立刻红（不是靠人记得补测试）。
    """
    back = _mk_report()
    front = _mk_report(**{key: {"mutated": "只在单侧出现"}})
    hits = assert_mirror_consistent(back, front)
    assert any(key in x for x in hits), (
        f"『{key}』在必须一致集里，却挡不住单侧漂移（违规清单：{hits}）"
        " ⇒ 这条守卫对它是摆设；要么修判据，要么把它从 REQUIRED_TOP 明确移出并说明理由")
