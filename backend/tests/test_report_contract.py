"""几何契约（``app.living_circle.report_contract``）的**判别力**测试。

## 为什么要单独测「契约本身」

``test_report_invariants.py`` 是**数据层的 oracle**：它自己算几何（外接圆、鞋带面积、
点在环内），对夹具与组装产物断言 —— 那是「数据对不对」。
本文件问的是另一个问题：**契约这个仪器准不准**。

两者不能合并：若测试直接 ``assert assess_geometry(lc).ok``，契约里写错一条判据
（阈值反了、字段取错、漏了一个 in_circle=False 的点）测试依然会绿 —— 因为它和被测
对象共用同一份实现。所以这里用**变异样本**：拿真实夹具当底，注入一类缺陷，断言命中的
是**那一条**判据（而不是笼统地 ``not ok``）。

## 覆盖的缺陷类别（每一类都对应一次真实事故）

===========================  ==================================  ==========================
变异                          对应事故                            期望命中的判据
===========================  ==================================  ==========================
盲区放大到可达区外（±5000m）    Q1：判定网格铺满研究区               盲区最远点越出外接圆
多个贴边大盲区                  Q1：整片判盲                        盲区总面积 > 可达区×2
POI 标 ``in_circle=False`` 送达  Q2：圈外点进报告                    圈外点不应展示
POI 标 True 但坐标在 3km 外     Q2 变体：标记与几何矛盾              越出外接圆（首个点名）
删掉 ``caliber``               存量 7 份旧算法 live 报告             未声明可达区口径
``isochrones=[]``              P6：迤栖村静默空壳                    缺件「路网等时圈数据」
``collect_radius_m`` 调小       采集区盖不住可达区                    采集半径 < 外接圆
口径 20min 但只有 5/10/15 圈     口径与数据不一致                     可达区口径不存在
删掉环的 ``geojson``           判不了（信息不足）                    **不得误报**
===========================  ==================================  ==========================

 rev2 追加三条（证据相，底本先把夹具升格成**当前版本**自洽口径）：

===========================  ==================================  ==========================
余量改回 0 / collect≠外接圆+余量   D2 回退 ⇒ 判盲面塌回 5%          B5 余量≤0、关系复算不符
实测边界 > 请求 / 带缺口称完整     「没查完」被省略                B5
judge_radius 未减判定半径 /      判定域与证据脱钩；「判不了」冒充    B10
judged=0 却非全未定               「不盲」
缺 confidence / 低覆盖称 full /   扣分口径被改回「只按条数」        B11
penalty 复算不符
旧口径报告（无版本号）             存量 26 次历史体检              **不得误报、不得隐藏**
===========================  ==================================  ==========================
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from app.living_circle.blindspot import BLIND_GRID_M
from app.living_circle.geo_utils import haversine_m, ring_area_km2, xy_to_lnglat
from app.living_circle.grid import grid_spec
from app.living_circle.report_contract import (
    BLINDSPOT_AREA_RATIO_MAX,
    GEOM_TOL,
    assess_geometry,
    report_is_presentable,
    staleness_reason,
)
from app.living_circle.scope import (
    BLIND_RADIUS_M,
    SCOPE_POLICY_VERSION,
    TRIAD_KEYS,
)
from app.living_circle.scoring import (
    BLINDSPOT_PENALTY_CAP,
    BLINDSPOT_PENALTY_PER_EXTRA,
    compute_scores,
)

FIXTURES = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))


def _base() -> dict:
    """以真实夹具为底（保证字段形状与产线一致）—— 变异测试的前提。"""
    return copy.deepcopy(json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8")))


def _center(lc: dict):
    return tuple(lc["scene"]["center"])


def _reach_ring(lc: dict):
    target = lc["caliber"]["reach_full_min"]
    zone = next(z for z in lc["isochrones"] if z["minutes"] == target)
    return [(float(p[0]), float(p[1])) for p in zone["geojson"]["coordinates"][0]]


def _circumradius_m(lc: dict) -> float:
    c = _center(lc)
    return max(haversine_m(c, p) for p in _reach_ring(lc))


def _reach_area_km2(lc: dict) -> float:
    return ring_area_km2(_reach_ring(lc), _center(lc))


def _square(center, half: float):
    """以 center 为中心、半边 ``half`` 米的方形闭环。"""
    return [xy_to_lnglat(center, x, y) for x, y in
            [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]]


def _blindspot(bid: str, center, half: float) -> dict:
    return {"id": bid, "polygon": {"type": "Polygon",
                                   "coordinates": [[list(p) for p in _square(center, half)]]}}


# ── 正向：现行产物必须全绿 ──────────────────────────────────────
@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_current_fixtures_are_presentable(path):
    """现行夹具（= 现行组装实现的冻结快照）必须逐条合规。"""
    lc = json.loads(path.read_text(encoding="utf-8"))
    issues = assess_geometry(lc)
    assert issues.ok, f"{path.name} 不合几何契约：{issues.reason}"


def test_kaili_fixture_is_blindspot_free():
    """变异设计的前提：凯里夹具必须**无盲区**（否则「越出可达区」的变异无从下手）。"""
    assert _base()["blindspots"] == [], "凯里夹具无盲区是本文件变异设计的前提"


def test_fixture_caliber_declares_reach_and_collect():
    """变异设计的前提之二：夹具带口径声明，且采集半径盖住可达区。"""
    cal = _base()["caliber"]
    assert cal["reach_full_min"] == 20.0
    assert cal["collect_radius_m"] >= _circumradius_m(_base()) * 0.999


# ── B1：盲区越出可达区（Q1 本体）────────────────────────────────
def test_blindspot_outside_reach_is_flagged():
    lc = _base()
    lc["blindspots"] = [_blindspot("bs-mutated", _center(lc), 5000.0)]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("越出可达区外接圆" in v and "bs-mutated" in v for v in issues.violations), issues.reason
    assert "越出可达区外接圆" in (staleness_reason(lc) or "")


def test_blindspot_inside_reach_is_clean():
    """反例护栏：盲区在可达区内 ⇒ 不得报违规（防止「一律判违规」的假修复）。"""
    lc = _base()
    lc["blindspots"] = [_blindspot("bs-inside", _center(lc), 500.0)]
    assert assess_geometry(lc).ok, assess_geometry(lc).reason


# ── B2：盲区总面积上限（Q1 的「整片判盲」形态）──────────────────
def test_blindspot_total_area_bound_is_flagged():
    """贴边的多个大盲区：每个都不越界（B1 不响），但总面积远超可达区 ×2（B2 响）。"""
    lc = _base()
    c = _center(lc)
    cr = _circumradius_m(lc)
    # 方形半边 h ⇒ 角点偏移 h·√2；取 h = 0.9·cr/√2 保证角点 0.9cr < cr（B1 沉默）
    half = 0.9 * cr / math.sqrt(2.0)
    lc["blindspots"] = [_blindspot(f"bs-area-{i}", c, half) for i in range(4)]

    issues = assess_geometry(lc)
    assert not any("越出可达区外接圆" in v for v in issues.violations), (
        f"变异样本不应触发 B1（越界），实际：{issues.reason}"
    )
    assert any("盲区总面积" in v for v in issues.violations), issues.reason
    assert BLINDSPOT_AREA_RATIO_MAX == 2.0


# ── B3/B4：圈外点（Q2 本体）────────────────────────────────────
def test_point_marked_out_of_circle_is_flagged():
    lc = _base()
    far = xy_to_lnglat(_center(lc), 3000.0, 0.0)
    lc["poi"]["points"] = [{"id": "p-far", "name": "圈外点", "in_circle": False,
                            "lnglat": [far[0], far[1]]}] + lc["poi"]["points"]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("in_circle=False" in v for v in issues.violations), issues.reason


def test_point_marked_in_circle_but_geometrically_outside_is_flagged():
    """标记与几何矛盾（Q2 的另一种形态）：标 True 却在 3km 外。"""
    lc = _base()
    far = xy_to_lnglat(_center(lc), 3000.0, 0.0)
    lc["poi"]["points"] = lc["poi"]["points"] + [
        {"id": "p-liar", "name": "谎报点", "in_circle": True, "lnglat": [far[0], far[1]]}
    ]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("越出可达区外接圆" in v and "谎报点" in v for v in issues.violations), issues.reason


def test_tolerance_boundary():
    """容差常数必须真的参与判定：1.01×外接圆放行，1.10×外接圆判违规。"""
    c = _center(_base())
    cr = _circumradius_m(_base())

    inside = _base()
    p = xy_to_lnglat(c, 0.0, cr * 1.01)
    inside["poi"]["points"] = [{"id": "p1", "in_circle": True, "lnglat": [p[0], p[1]]}]
    assert assess_geometry(inside).ok, assess_geometry(inside).reason
    assert cr * 1.01 <= cr * GEOM_TOL

    outside = _base()
    p = xy_to_lnglat(c, 0.0, cr * 1.10)
    outside["poi"]["points"] = [{"id": "p2", "in_circle": True, "lnglat": [p[0], p[1]]}]
    assert not assess_geometry(outside).ok


# ── B0：口径可举证（存量 7 份旧算法 live 报告的判据）─────────────
def test_live_report_without_caliber_is_flagged():
    lc = _base()
    lc.pop("caliber")
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("reach_full_min" in v for v in issues.violations), issues.reason
    assert any("collect_radius_m" in v for v in issues.violations), issues.reason


def test_non_live_report_without_caliber_only_skips_b0():
    """非 live 报告不要求口径声明（历史夹具没有 ⇒「判不了」而非「有罪」）。"""
    lc = _base()
    lc.pop("caliber")
    lc["data_origin"] = "fixture_sample"
    lc["blindspots"] = [_blindspot("bs-far", _center(lc), 5000.0)]
    issues = assess_geometry(lc)
    assert not any("reach_full_min" in v for v in issues.violations), issues.reason
    # 但几何判据照旧生效（老夹具快照正是这样被认出来的）
    assert any("越出可达区外接圆" in v for v in issues.violations), issues.reason


# ── B6：采集区必须盖住可达区 ───────────────────────────────────
def test_collect_radius_smaller_than_reach_is_flagged():
    lc = _base()
    lc["caliber"]["collect_radius_m"] = 100.0
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("采集半径" in v for v in issues.violations), issues.reason


# ── 口径与数据不一致 ───────────────────────────────────────────
def test_caliber_reach_minute_absent_from_isochrones_is_flagged():
    lc = _base()
    lc["caliber"]["reach_full_min"] = 25.0
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("口径与数据不一致" in v for v in issues.violations), issues.reason


# ── Tier A：内容缺件 ───────────────────────────────────────────
@pytest.mark.parametrize(
    "origin,empty_iso,empty_poi,expect_missing",
    [
        ("live", True, True, ["路网等时圈数据", "设施点位数据（POI）"]),
        ("live", False, True, ["设施点位数据（POI）"]),
        ("live", True, False, ["路网等时圈数据"]),
        ("fixture", True, False, ["路网等时圈数据"]),
        ("fixture_sample", True, False, ["路网等时圈数据"]),
    ],
)
def test_content_missing(origin, empty_iso, empty_poi, expect_missing):
    lc = _base()
    lc["data_origin"] = origin
    if empty_iso:
        lc["isochrones"] = []
    if empty_poi:
        lc["poi"]["points"] = []
    assert list(assess_geometry(lc).missing) == expect_missing


def test_offline_blank_is_exempt():
    """``offline`` 的空白是**有意降级**（P0-2 已在 UI 标注）⇒ 不得被隐藏。

    这条与 ``test_report_invariants`` 的「isochrones 非空」并不矛盾：不变量管的是
    「声称做过完整体检的报告」，而 offline 明确声称自己没做（无网络）。
    区分二者靠 ``data_origin`` —— 一个字段就够，不需要两套判据。
    """
    lc = _base()
    lc["data_origin"] = "offline"
    lc["isochrones"] = []
    lc["poi"]["points"] = []
    lc.pop("caliber", None)
    issues = assess_geometry(lc)
    assert issues.ok, issues.reason
    assert report_is_presentable(lc) is True
    assert staleness_reason(lc) is None


def test_empty_payload_is_missing():
    issues = assess_geometry({})
    assert not issues.ok
    assert any("载荷为空" in m for m in issues.missing), issues.reason


# ── 判不了 ≠ 违规（防假阳性）───────────────────────────────────
@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda lc: lc["isochrones"][0].pop("geojson"), "等时圈无 geojson"),
        (lambda lc: [z.pop("geojson") for z in lc["isochrones"]], "全部等时圈无 geojson"),
        (lambda lc: lc["scene"].pop("center"), "无中心点"),
        (lambda lc: lc["scene"].__setitem__("center", [1.0]), "中心点长度非法"),
        (lambda lc: lc["poi"]["points"][0].pop("in_circle"), "点位无 in_circle 标记"),
        (lambda lc: lc.__setitem__("poi", {}), "poi 为空对象(live 会命中 Tier A)"),
        (lambda lc: lc.__setitem__("blindspots", [{"id": "b", "polygon": {}}]), "盲区无坐标"),
        (lambda lc: lc["scene"].__setitem__("center", [11440230.81, 2860409.52]), "墨卡托米当经纬度"),
    ],
)
def test_insufficient_input_is_not_a_violation(mutate, label):
    """输入不足 ⇒ 该判据跳过，**不得**因此判违规（假阳性比漏报更难排查）。

    例外：``poi`` 整块缺失在 live 报告里是 Tier A 缺件（missing 而非 violations），
    本用例只钉「不得凭空判 violations」。
    """
    lc = _base()
    mutate(lc)
    issues = assess_geometry(lc)
    assert issues.violations == (), f"{label} 不该被当成几何违规，实际：{issues.reason}"


# ── B5 / B10 / B11：证据相三条 ──────────────────────────────────
# 这三条守的不是几何，而是「我实际查到哪儿」与「我据此敢下多大结论」之间的那条链。
# 底本必须先把夹具升格成 **当前版本自洽产物**：新口径下不合规的报告会让任何一条恒真命中，
# 变异样本也就失去判别力（与 B1/B2 用「凯里夹具无盲区」当前提是同一纪律）。

#: 台账的字母表在测试里**写成字面量**，不从 `blindspot` 导入：那三个字符就是写侧与读侧的
#: 契约本身。测试若跟着常量走，常量被改错的那天测试会跟着一起改错（恒真断言）。
LED_YES, LED_NO, LED_UNK, LED_NO_DIST = "1", "0", ".", "-"


def _ledger_for(lc: dict, *, blind: int = 0, capped: int = 0) -> dict:
    """按 caliber 现有的分账**合成**一张自洽台账，供 B5/B10/B11 的用例当底本。

    ⚠️ 它是"照分账摆出来的格子"，不是任何一次真实判定的产物 —— 用途只有一个：
    让底本在 `ev-2` 门禁下自洽（否则 B13 的"缺台账即违规"会把每条无关用例都拖红）。
    B13 自己的判别力由下面那批**故意改坏**的用例提供。

    摆法（行优先）：前 `blind` 格判盲（菜市场 judge=1/present=0，其余两类命中）、
    接着 `judged-blind` 格确认不盲（三类皆有据且命中）、再 `capped` 格记封顶、
    剩下的未定 —— 后两类三类输入位全是 `.`，正是"没查过"该有的形状。
    """
    cal = lc["caliber"]
    spec = grid_spec(_center(lc), float(cal["reach_circumradius_m"]), BLIND_GRID_M)
    n = spec.n
    inside_n = int(cal["cells_inside"])
    judged = int(cal["cells_judged"])
    if not (0 <= blind <= judged <= inside_n <= n * n) or not 0 <= capped <= inside_n - judged:
        raise ValueError(
            f"无法为分账 inside={inside_n}/judged={judged} 摆出台账（blind={blind} capped={capped}）")
    radius = int(round(float((lc.get("blindspots") or [{}])[0].get("radius_m", BLIND_RADIUS_M))))

    marks = {name: [[LED_NO] * n for _ in range(n)] for name in ("inside", "capped", "blind", "verdict")}
    judge = {k: [[LED_NO] * n for _ in range(n)] for k in TRIAD_KEYS}
    present = {k: [[LED_UNK] * n for _ in range(n)] for k in TRIAD_KEYS}
    near = {k: [[LED_NO_DIST] * n for _ in range(n)] for k in TRIAD_KEYS}

    cells = [(i, j) for i in range(n) for j in range(n)]
    groups = (
        (cells[:blind], "blind"),
        (cells[blind:judged], "ok"),
        (cells[judged:judged + capped], "capped"),
        (cells[judged + capped:inside_n], "unknown"),
    )
    for span, kind in groups:
        for i, j in span:
            marks["inside"][i][j] = LED_YES
            if kind == "blind":
                marks["blind"][i][j] = marks["verdict"][i][j] = LED_YES
            elif kind == "ok":
                marks["verdict"][i][j] = LED_YES
            elif kind == "capped":
                marks["capped"][i][j] = LED_YES
            if kind not in ("blind", "ok"):
                continue                       # 未定/封顶的格：三类输入位保持 `.`
            for idx, k in enumerate(TRIAD_KEYS):
                judge[k][i][j] = LED_YES
                # 判盲格让**第一个类**缺命中（存在性结论），其余类命中；不盲格三类全命中。
                hit = kind == "ok" or idx > 0
                present[k][i][j] = LED_YES if hit else LED_NO
                near[k][i][j] = str(400 + 10 * idx) if hit else str(radius + 200)

    cal["cells_blind"] = blind
    cal["cells_unjudgeable_by_cap"] = capped
    cal["cells_unknown"] = inside_n - judged - capped
    return {
        "grid": "square", "schema_version": 1, "n": n,
        "step_m": round(spec.step, 1), "scan_m": round(spec.scan, 1),
        "radius_m": radius,
        "center": [round(_center(lc)[0], 6), round(_center(lc)[1], 6)],
        **{name: ["".join(r) for r in rows] for name, rows in marks.items()},
        **{f"judge.{k}": ["".join(r) for r in judge[k]] for k in TRIAD_KEYS},
        **{f"present.{k}": ["".join(r) for r in present[k]] for k in TRIAD_KEYS},
        **{f"nearest.{k}": [" ".join(r) for r in near[k]] for k in TRIAD_KEYS},
    }


def _ev1_caliber(lc: dict, **over) -> dict:
    """把夹具的旧 D2 口径（余量 0、collect == 外接圆）升格成**当前版本**自洽口径。

    含逐格台账：`ev-2` 的门禁是"声明了本版本就必须自带"，底本不带 ⇒ B13 会把这里
    每一条无关用例都判红（那正是 P0-2 预判过的形状，落在这里当回归哨）。
    """
    cal = lc["caliber"]
    circum = float(cal["reach_circumradius_m"])
    collect = circum + BLIND_RADIUS_M
    inside = int(cal["cells_inside"])
    cal.update({
        "collect_radius_m": round(collect, 1),
        "collect_margin_m": round(BLIND_RADIUS_M, 1),
        "scope_policy_version": SCOPE_POLICY_VERSION,
        "evidence_margin_m": round(BLIND_RADIUS_M, 1),
        "evidence_radius_m": round(collect, 1),
        "evidence_frontier_m": {k: round(collect, 1) for k in TRIAD_KEYS},
        "evidence_complete": True,
        "evidence_bound_source": "measured",
        "judge_radius_m": round(collect - BLIND_RADIUS_M, 1),
        "cells_judged": inside,
        "cells_unknown": 0,
    })
    cal.update(over)
    cal["cells_ledger"] = _ledger_for(
        lc, blind=int(over.get("cells_blind") or 0),
        capped=int(over.get("cells_unjudgeable_by_cap") or 0))
    return cal


def _set_coverage(lc: dict, *, judged: int, blind: int = 0, capped: int = 0) -> dict:
    """改判定面，并**同步重摆台账**。

    为什么要有这个助手而不是直接 `caliber.update(...)`：台账是从分账摆出来的，只改数不改台账
    ⇒ B13 的"计数与台账对不上账"会在每条无关用例上响。噪声吃掉判别力之后，真违规也就看不见了。
    """
    lc["caliber"]["cells_judged"] = judged
    lc["caliber"]["cells_ledger"] = _ledger_for(lc, blind=blind, capped=capped)
    return lc


def _rescore(lc: dict) -> dict:
    """按**当前** caliber/blindspots 用真公式重算 confidence/evidence（保持一致底）。"""
    cal = lc["caliber"]
    inside = int(cal.get("cells_inside") or 0)
    share = (int(cal.get("cells_judged") or 0) / inside) if inside else None
    fresh = compute_scores(
        lc["poi"]["categories"], lc["scores"].get("triads") or [], len(lc["blindspots"]),
        judged_share=share, evidence_complete=bool(cal.get("evidence_complete")),
    )
    lc["scores"]["confidence"] = fresh["confidence"]
    lc["scores"]["evidence"] = fresh["evidence"]
    return lc


def _ev1(**over) -> dict:
    """当前版本自洽底本（默认判满可达区 ⇒ share=1、confidence=full，且自带台账）。"""
    lc = _base()
    _ev1_caliber(lc, **over)
    return _rescore(lc)


def test_ev1_consistent_report_is_clean():
    """反「一律判违规」护栏：新口径下自洽的报告，三条都不得响。"""
    lc = _ev1()
    issues = assess_geometry(lc)
    assert issues.ok, issues.reason
    assert lc["caliber"]["cells_judged"] == lc["caliber"]["cells_inside"]


def test_legacy_report_without_version_is_not_flagged():
    """存量报告（无 ``scope_policy_version``）⇒ 三条整体跳过，**不得**被隐藏。

    这正是 D-4「只拦复用、不拦可见性」的读侧落点：旧口径的 88.4 分仍是用户的历史。
    """
    lc = _base()
    assert "scope_policy_version" not in lc["caliber"], "夹具须停留在旧口径，本用例才有判别力"
    assert lc["caliber"]["collect_margin_m"] == 0.0, "夹具应是 D2（余量 0）形状"
    assert assess_geometry(lc).ok, assess_geometry(lc).reason


# ── B5 · 证据域自洽 ─────────────────────────────────────────────
def test_evidence_margin_zero_is_flagged():
    """余量被偷偷改回 0（D2 回退）⇒ 采集区不再为 1km 证据兜底。"""
    lc = _ev1()
    cal = lc["caliber"]
    cal["evidence_margin_m"] = 0.0
    cal["collect_radius_m"] = cal["evidence_radius_m"] = float(cal["reach_circumradius_m"])
    cal["judge_radius_m"] = 0.0
    assert any("余量" in v and "≤ 0" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_collect_radius_not_derived_from_margin_is_flagged():
    """余量声明 1000 却只外扩一半 ⇒ 关系被写死而不是导出。"""
    lc = _ev1()
    lc["caliber"]["collect_radius_m"] = round(
        float(lc["caliber"]["reach_circumradius_m"]) + BLIND_RADIUS_M / 2, 1
    )
    assert any("≠ 可达区外接圆" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_measured_evidence_beyond_request_is_flagged():
    """实测边界大于请求半径在物理上不可能 ⇒ 只能是没有校验的换算/绑定顺序错。"""
    lc = _ev1()
    lc["caliber"]["evidence_radius_m"] = round(float(lc["caliber"]["collect_radius_m"]) + 300, 1)
    assert any("实测不可能大于请求" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_complete_flag_with_short_frontier_is_flagged():
    """声称「证据完整」却承认只查到边内 400m ⇒ 「没查完」被省略的那条路。"""
    lc = _ev1()
    lc["caliber"]["evidence_radius_m"] = round(float(lc["caliber"]["collect_radius_m"]) - 400, 1)
    assert any("不得称完整" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_short_frontier_marked_incomplete_is_clean():
    """反例：同样只查到边内 400m，但如实标 complete=false 并同步缩判定域 ⇒ 不得判违规。

    「判不了 ≠ 有罪」在证据相的落点：诚实承认证据有缺口是合规的，谎称完整才不是。
    """
    short = round(float(_ev1()["caliber"]["collect_radius_m"]) - 400, 1)
    lc = _ev1(evidence_complete=False, evidence_radius_m=short,
              judge_radius_m=round(short - BLIND_RADIUS_M, 1))
    issues = assess_geometry(_rescore(lc))
    assert issues.ok, issues.reason


def test_declared_version_without_evidence_keys_is_flagged():
    """版本号与键集是同一次发布的两半：只发版本不发键 ⇒ 无从举证。"""
    lc = _ev1()
    for k in ("evidence_margin_m", "evidence_frontier_m", "evidence_complete",
              "evidence_bound_source", "judge_radius_m"):
        lc["caliber"].pop(k, None)
    assert any("却缺" in v and "举证" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


# ── B10 · 判定域由证据域导出 ────────────────────────────────────
def test_judge_radius_not_derived_from_evidence_is_flagged():
    """忘了减判定半径（judge == 证据边界）⇒ 外沿的格会被当成可判。"""
    lc = _ev1()
    lc["caliber"]["judge_radius_m"] = round(float(lc["caliber"]["evidence_radius_m"]), 1)
    assert any("判定域不再由证据域导出" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_b10_fires_when_the_run_used_a_different_ruler():
    """**成对判据·红的那条**：报告按 800m 的尺自洽，B10 今天仍然判它违规 ⇒ 证明 B10 读的是
    兼容常量（1000），不是本次判定实际吃的那把尺（计划 v6.9 ⑧″，第十四轮 P0-3 打回的
    就是"只写一条极性"—— 单写不叫的那条会退化成任何实现都沉默的假闸）。

    分档真上线（阶段 3-5）之后这条就是**误报**：riding 报告会被按步行档判成不合规。
    修法在批次二（B10 改读产物自己声明的半径），所以这里同时钉住文本，别红错地方。
    """
    lc = _ev1()
    bound = float(lc["caliber"]["evidence_radius_m"])
    lc["caliber"]["judge_radius_m"] = round(bound - 800.0, 1)   # 自称按 800m 判
    violations = assess_geometry(lc).violations
    hits = [v for v in violations if "判定域不再由证据域导出" in v]
    assert hits, f"按 800m 自洽的报告今天没被 B10 抓住 ⇒ B10 的取法已改，本判据要重指：{violations}"
    assert "1000m" in hits[0], hits[0]


def test_b10_cannot_see_the_declared_ruler_yet():
    """**成对判据·不叫的那条**：产物里写了「本次用 800」，B10 今天完全看不见它。

    这条今天**绿**（不叫 = 现状为真），批次二让 B10 改读该声明后它必须**变红** ——
    留在这里的作用是把"第二把尺"这件事说成事实而不是承诺：口径键 `blind_radius_m`
    目前**没有任何读者**（写侧也没发，见 v6.9 ③′.5 决定「不加顶层披露键」）。
    """
    lc = _ev1()
    lc["caliber"]["blind_radius_m"] = 800.0        # 本次用的尺（今天无人读，明天是靶子）
    issues = assess_geometry(lc)
    assert issues.ok, f"该键今天不该有读者；若 B10 已开始读它，请把上一条红的那起改名：{issues.reason}"


def test_zero_judged_with_the_cap_accounted_is_issuable():
    """**本刀的靶（P1-5）**：一格都没判成、但缺口全部记在第三态 ⇒ 门不许假红，报告必须能签发。

    `assess_geometry` 是写路径的签发条件（本文件 :231「不自洽 → 同样不签发」），所以 B10 那支
    按两态算的旧判据会让一份**自洽**的纯封顶报告直接发不出去 —— 而那句指控恰好说反了：
    未判成的格**正是**被记成了"判不了"，只是记在 `cells_unjudgeable_by_cap` 那一位
    （分账恒等式 `inside = judged + unknown + unjudgeable_by_cap`，A5/`test_degrade_chain.py:1293` 钉着）。

    前置先跑一遍：三态闭合、且这份载荷除了 B10 那一支以外没有别的违规 —— 否则"红了"
    可能红在无关的支上，那条判据就不测本刀要测的东西（改前它应当红在 B10 那句上）。
    """
    lc = _set_coverage(_ev1(), judged=0, capped=5)
    _rescore(lc)
    cal = lc["caliber"]
    inside = int(cal["cells_inside"])
    assert int(cal["cells_unknown"]) + int(cal["cells_unjudgeable_by_cap"]) == inside, (
        "前置不成立：三态账没闭合，下面那句'该放行'就不成立")

    issues = assess_geometry(lc)
    joined = " ".join(issues.violations)
    assert "判不了」被当成「不盲" not in joined, (
        f"三态闭合的纯封顶报告被 B10 误判：{issues.reason}")
    assert issues.ok, f"仍有其它违规 ⇒ 报告不会签发：{issues.reason}"


def test_zero_judged_cells_must_all_be_accounted():
    """反向对照（原意一条不许松）：一格未判时，缺口必须**全部有归因** —— 未定 或 接口封顶。

    本条与上一条 `test_zero_judged_with_the_cap_accounted_is_issuable` 是一对：那条钉"账闭合就
    不许拦"，这条钉"账不闭合必须拦"。名字原本叫 `…must_all_be_unknown`（P1-5 之前判定面只有两态），
    第三态落地后"未判成"合法地可以归因到接口封顶 ⇒ 判据从"全记未定"改成"全有归因"，样本也随之
    改成**真少记 3 格**的形状 —— 改前它构造的其实是三态闭合的自洽载荷，却断言违规发生，
    也就是把 B10 的那次假红钉成了期望（计划 §4③）。

    已知重叠、不当噪声处理：这份样本 B13 会一起报「顶层 `cells_unknown` 与台账复算对不上」——
    少记格子在台账侧同样是错。所以本条只断 B10 那一支的**种类 + 差额**，不断"只有它在叫"。
    """
    lc = _set_coverage(_ev1(), judged=0, capped=5)
    inside = int(lc["caliber"]["cells_inside"])
    lc["caliber"]["cells_unknown"] = inside - 5 - 3      # 三格既没判成、也没记成封顶
    _rescore(lc)                                          # 份额/置信度跟着判定面走，排除无关支
    hit = [v for v in assess_geometry(lc).violations if "判不了」被当成「不盲" in v]
    assert len(hit) == 1, assess_geometry(lc).reason
    assert "差 3 格" in hit[0] and "接口封顶 5 格" in hit[0], hit[0]


def test_judged_mask_cannot_survive_zero_judge_radius():
    """判定半径 0m ⇒ 物理上最多中心一格可判；报出 10 格即掩码退化。"""
    lc = _ev1()
    cal = lc["caliber"]
    cal["evidence_radius_m"] = round(BLIND_RADIUS_M, 1)   # 只查到 1000m ⇒ judge=0
    cal["judge_radius_m"] = 0.0
    cal["evidence_complete"] = False
    _set_coverage(lc, judged=10)
    assert any("judged 掩码已退化" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


# ── B12 · 逐锚点举证与逐类标量边界必须由**同一批盘**导出（计划 v5.9 前置②）──
# 写侧守卫（`SpatialScope._one_region_source`）只拦「经过值对象」的写法；落库件是 JSON，
# 拼得出「明细来自回合区域、标量却来自首轮绑定」的报告 —— 而那正是取证回合接线后同时持有的
# 两块。判据取**区间包含**而不是「等于 max」：同一批盘有两种合法塌缩（采集器逐类取各词最小值
# =保守合取；区域视图取圆盘最大值 =向后兼容既有键），钉死其中一种等于替批次二预定标量语义。

def _anchor_row(cat, exhausted, *, request=None, cap_hit=False, reason="page_cap"):
    return {
        "category": cat, "anchor": [106.0, 29.0],
        "request_radius_m": round(float(exhausted if request is None else request), 1),
        "exhausted_radius_m": round(float(exhausted), 1),
        "complete": not cap_hit, "cap_hit": cap_hit, "stop_reason": reason,
    }


def test_anchor_detail_disagreeing_with_frontier_is_flagged():
    """明细里药店最深只到「标量边界 − 900m」，标量却报满采集半径 ⇒ 那个数不来自这批盘。"""
    lc = _ev1()
    cal = lc["caliber"]
    front = float(cal["evidence_frontier_m"]["pharmacy"])
    cal["evidence_anchors"] = [_anchor_row("pharmacy", front - 900.0, request=front)]
    assert any("落在该锚点明细的深度区间" in v for v in assess_geometry(lc).violations), (
        assess_geometry(lc).reason
    )


def test_frontier_at_the_min_collapse_is_not_flagged():
    """生产标量绑定取的是逐类**各词边界的最小值** ⇒ 必须被判为同源（第五轮复审 P0-2 的形状）。

    `poi_collector.frontier_m` 明确 min、`EvidenceRegion.frontier_m` 明确 max，两者都从同一批
    `TermEvidence` 行导出。门禁若只认 max，阶段 3 第一份带 `judged_region` 的报告就会违规
    —— 而 market 本来就有 3 个词，min≠max 是常态不是异常。
    """
    lc = _ev1()
    cal = lc["caliber"]
    front = float(cal["evidence_frontier_m"]["market"])
    cal["evidence_anchors"] = [
        _anchor_row("market", front, reason="complete"),
        _anchor_row("market", front - 2000.0, request=front),
    ]
    cal["evidence_frontier_m"]["market"] = round(front - 2000.0, 1)   # 逐类取 min = 生产写法
    violations = assess_geometry(lc).violations
    assert not any("深度区间" in v for v in violations), f"min 塌缩被误判成不同源：{violations}"


def test_anchor_detail_without_frontier_entry_is_flagged():
    """有盘却无该类逐类边界 ⇒ 报告答不出这块盘把边界推到哪儿（第三态归因也跟着断线）。"""
    lc = _ev1()
    cal = lc["caliber"]
    cal["evidence_frontier_m"].pop("pharmacy")
    cal["evidence_anchors"] = [_anchor_row("pharmacy", 2000.0, reason=None, cap_hit=False)]
    assert any("却缺 `evidence_frontier_m` 条目" in v for v in assess_geometry(lc).violations), (
        assess_geometry(lc).reason
    )


def test_anchor_detail_consistent_with_frontier_is_clean():
    """控制腿（防「一律判违规」）：明细覆盖标量值时不得响。

    market 给两块**不同深度**的盘，是为了让区间这条判据真的在测区间 —— 若判据被改回
    「等于第一块盘」，这里就该红。
    """
    lc = _ev1()
    cal = lc["caliber"]
    front = cal["evidence_frontier_m"]
    rows = [_anchor_row(cat, float(front[cat]), reason="complete") for cat in TRIAD_KEYS]
    rows.insert(0, _anchor_row("market", float(front["market"]) - 400.0, reason="complete"))
    cal["evidence_anchors"] = rows
    issues = assess_geometry(lc)
    assert issues.ok, issues.reason


# ── B11 · 扣分与判定面一致 ──────────────────────────────────────
def test_new_report_without_confidence_is_flagged():
    lc = _ev1()
    lc["scores"].pop("confidence")
    assert any("缺 scores.confidence" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_full_confidence_with_partial_coverage_is_flagged():
    """覆盖率 82% 却自称 full ⇒ 「没判的 17 格」冒充「没问题」。"""
    lc = _ev1()
    inside = int(lc["caliber"]["cells_inside"])
    _set_coverage(lc, judged=inside - 17)      # 未定 17 格由台账同步摆出来
    lc["scores"]["confidence"] = "full"
    assert any("冒充「没问题」" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_full_confidence_with_incomplete_evidence_is_flagged():
    lc = _ev1(evidence_complete=False)
    lc["scores"]["confidence"] = "full"
    assert any("证据不完整" in v or "截断/饿死/熔断" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_penalty_reverted_to_count_only_is_flagged():
    """本条是 D-3 的守门人：把扣分改回「只按条数」必须被复算判据抓住。

    构造：判定面覆盖 8 成 + 2 处有据盲区 ⇒ 外推 2.5 处 ⇒ 扣 ≈5.9 分；按条数只扣 4.0 分。
    两侧都必须在封顶线以下，比较才有判别力（触顶时两种口径都得 12 分，等于没测）。
    """
    lc = _ev1()
    c = _center(lc)
    inside = int(lc["caliber"]["cells_inside"])
    judged = round(inside * 0.8)
    lc["caliber"]["evidence_complete"] = False
    _set_coverage(lc, judged=judged)
    lc["blindspots"] = [_blindspot("bs-a", c, 300.0), _blindspot("bs-b", c, 300.0)]
    _rescore(lc)
    assert assess_geometry(lc).ok, assess_geometry(lc).reason
    share = judged / inside
    extrapolated = min(BLINDSPOT_PENALTY_CAP, max(0.0, len(lc["blindspots"]) / share - 1.0) * BLINDSPOT_PENALTY_PER_EXTRA)
    count_only = max(0.0, len(lc["blindspots"]) - 1.0) * BLINDSPOT_PENALTY_PER_EXTRA
    assert extrapolated > count_only > 0, "变异样本须让两种口径真的分岔"

    lc["scores"]["evidence"]["penalty_applied"] = round(count_only, 1)   # 变异：回退成按条数
    assert any("无法由公式复算" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_judged_share_must_match_the_cells_accounting():
    """评分读到的判定面与报告声明的不是同一个数 ⇒ 两处账本必须对齐。"""
    lc = _ev1()
    lc["scores"]["evidence"]["judged_share"] = 0.99
    assert any("与 caliber 分账" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


# ── B13：逐格台账（计划 cells-ledger-judge-scale §4.3）────────────────
# 这批用例问的是同一件事：**台账说的、计数说的、规则重抄出来的，三者是不是同一次判定**。
# 每条变异都断言**命中的那一条判据文本**，不断言笼统的 `not ok` —— 后者会让"底本不自洽"
# 冒充成"判据有效"（本仓反复出事的恒真形状）。

def _b13(lc: dict) -> list:
    """只取台账相关的违例行（其余判据可能同时红，但那不是本批用例的判别对象）。"""
    issues = assess_geometry(lc)
    return [v for v in issues.violations
            if "cells_ledger" in v or "台账" in v or "不对称规则" in v]


def test_ledger_consistent_with_accounting_is_clean():
    """正向对照（防"一律判违规"）：自洽底本上 B13 一条都不许响。"""
    lc = _ev1()
    assert lc["caliber"]["cells_ledger"]["n"] % 2 == 1
    assert _b13(lc) == [], _b13(lc)


def test_declared_version_without_ledger_is_flagged():
    """声明了当前版本却没发台账 ⇒ 违规。这正是"键缺席即跳过"那条路永远查不到的形状。"""
    lc = _ev1()
    del lc["caliber"]["cells_ledger"]
    hits = _b13(lc)
    assert len(hits) == 1 and "却缺 cells_ledger" in hits[0], hits


def test_legacy_ev1_report_is_not_flagged_and_stays_visible():
    """P0-2 的回归哨：存量 `ev-1` 报告（没有台账这个键）**不得**被 B13 判违规、更不得消失。

    这条是整批改动的代价边界 —— 门禁若写成"有版本号就必须带台账"，库里唯一那条 ev-1
    实测报告与劲松出厂快照会从历史列表与报告页一起蒸发（`list_living_circle_reports`
    默认按 `assess_geometry` 过滤）。
    """
    lc = _ev1()
    lc["caliber"]["scope_policy_version"] = "ev-1"
    del lc["caliber"]["cells_ledger"]
    assert "ev-1" != SCOPE_POLICY_VERSION, "底本须落后当前版本，本用例才有判别力"
    issues = assess_geometry(lc)
    assert _b13(lc) == [], _b13(lc)
    assert report_is_presentable(lc), issues.reason


def test_third_state_collapsed_to_zero_is_flagged():
    """把 `.` 抹成 `0`（"没查过"写成"查过且没有"）⇒ 必须报第三态被压成二态。

    这就是复审 P0-1 的形状：`present` 若用 bool 承载，塌缩发生在**渲染之前**，
    B13 会把"无从知道"复算成"确认不盲"。
    """
    lc = _ev1()
    led = lc["caliber"]["cells_ledger"]
    led["present.pharmacy"] = [r.replace(LED_UNK, LED_NO) for r in led["present.pharmacy"]]
    hits = _b13(lc)
    assert any("第三态被压成了二态" in v for v in hits), hits


def test_blind_bit_flipped_against_the_rule_is_flagged():
    """只翻结论位、不动输入位 ⇒ 必须被"不对称规则重抄"抓到。

    没有这一条，B13 就只剩"台账与计数同源复算"的同义反复：`blind` 与计数一起改错时
    谁都发现不了。规则重抄是**读侧独立实现**，与 B11 重抄扣分公式同理。
    """
    lc = _ev1()
    led = lc["caliber"]["cells_ledger"]
    assert sum(r.count(LED_YES) for r in led["blind"]) == 0, "底本默认无盲格，翻一位才是干净的注入"
    row = list(led["blind"][0])
    row[led["inside"][0].index(LED_YES)] = LED_YES
    led["blind"][0] = "".join(row)
    hits = _b13(lc)
    # 只报"规则重抄"那一条，**不**报计数不符 —— 两个检查看的不是同一件事：
    # 计数由输入位复算（没动），结论位却被人改过。只留一条断言就看不出这层分工。
    assert len(hits) == 1 and "盲区位与规则不符" in hits[0], hits


def test_count_drift_against_ledger_is_flagged():
    """顶层计数与台账复算差 3 格 ⇒ 报"对不上账"，且**不许**有容差。"""
    lc = _ev1()
    lc["caliber"]["cells_blind"] = int(lc["caliber"]["cells_blind"]) + 3
    hits = _b13(lc)
    assert len(hits) == 1 and "计数与逐格台账对不上账" in hits[0], hits


def test_truncated_matrix_is_flagged_not_skipped():
    """半截台账（少一行）必须报违规 —— 不许按"判不了即跳过"放行。

    缺键有"缺 cells_ledger"那条兜着，形状不符若被跳过，等于给序列化截断开了后门。
    """
    lc = _ev1()
    led = lc["caliber"]["cells_ledger"]
    led["inside"] = led["inside"][:-1]
    hits = _b13(lc)
    assert any("缺失或形状/字母不符" in v for v in hits), hits
    assert any("inside" in v for v in hits), hits


def test_ledger_grid_drift_is_flagged():
    """`step_m` 与外接圆/格距推出的格阵不符 ⇒ 台账不是这次判定那张格阵。"""
    lc = _ev1()
    lc["caliber"]["cells_ledger"]["step_m"] = 999.0
    hits = _b13(lc)
    assert any("≠ 格阵复算" in v and "step_m" in v for v in hits), hits


def test_ledger_n_not_derivable_is_flagged():
    """`n` 与 `reach_circumradius_m` 推出来的边长不等 ⇒ 报格阵不符（复算走 `grid_spec`，
    测试不另抄一遍 ceil/linspace —— 抄的那份会在 `BLIND_GRID_M` 改动那天先漂）。"""
    lc = _ev1()
    cal = lc["caliber"]
    want = grid_spec(_center(lc), float(cal["reach_circumradius_m"]), BLIND_GRID_M).n
    cal["cells_ledger"]["n"] = want + 2
    hits = _b13(lc)
    assert any(f"推出的 {want}" in v for v in hits), hits


def test_ledger_ruler_must_match_the_blindspot_ruler():
    """台账那把尺与上屏盲区声明的尺分叉 ⇒ 图上 800m 圆旁边会标着 1km，必须报。"""
    lc = _ev1()
    lc["blindspots"] = [dict(lc["blindspots"][0], radius_m=800)] if lc["blindspots"] else \
        [{"id": "bs-注入-1", "radius_m": 800}]
    lc["caliber"]["cells_ledger"]["radius_m"] = 1000
    hits = _b13(lc)
    assert any("不是同一把尺" in v for v in hits), hits


def test_distance_and_hit_bit_cannot_disagree():
    """命中位与最近距离互相打脸（说没命中却报 300m，尺是 1000m）⇒ 必须报。

    这一条盯的是 `_hit_and_nearest_m` 被拆回两份实现的那天：距离与命中一旦分家，
    卡片上"1km 内没有"和"最近 300m"会同时上屏。
    """
    lc = _ev1(cells_blind=2)          # 底本带 2 个判盲格：那里 market 是 present=0 + 距离>尺
    led = lc["caliber"]["cells_ledger"]
    assert _b13(lc) == [], "带盲格的底本自身须自洽，注入才是干净的"
    radius = int(led["radius_m"])
    i = next(r for r, row in enumerate(led["inside"]) if LED_YES in row)
    j = led["inside"][i].index(LED_YES)
    toks = led["nearest.market"][i].split(" ")
    assert toks[j] != LED_NO_DIST and int(toks[j]) > radius, "底本里这格应是判盲格（距离 > 尺）"
    toks[j] = str(radius - 700)
    led["nearest.market"][i] = " ".join(toks)
    hits = _b13(lc)
    assert any("最近距离与命中位互相打脸" in v for v in hits), hits
