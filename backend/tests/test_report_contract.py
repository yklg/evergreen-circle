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
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from app.living_circle.geo_utils import haversine_m, ring_area_km2, xy_to_lnglat
from app.living_circle.report_contract import (
    BLINDSPOT_AREA_RATIO_MAX,
    GEOM_TOL,
    assess_geometry,
    report_is_presentable,
    staleness_reason,
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
