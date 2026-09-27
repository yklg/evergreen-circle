"""阶段 0.5 · 空间口径值对象（`SpatialScope`）的结构性契约。

Q1/Q2 的共同根因是「四个名字 / 三个概念 / 零个显式表示」：采集区、可达区、研究区
三者在代码里没有任何一等表示，只能靠形参名与注释约定。本文件守住三条机器判据：

1. **可达区必须按口径选（minutes），不得按位置取 `[-1]`** —— 因为按位置取环时，
   将来往等时圈族尾部加一个圈会**静默改变可达区语义**，且没有任何测试会红；
2. **空等时圈族必须拒** —— 这是「静默空壳报告」（P6：`isochrones=[]` 却报告全绿）的唯一入口；
3. **可达区 ⊆ 采集区**（构造即校验）—— 否则可达区内必然存在无数据格，
   「没查到」会被当成「没有」（Q1 本体）。
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

import pytest

from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat
from app.living_circle.scope import (
    BLIND_RADIUS_M,
    EVIDENCE_MARGIN_M,
    SCOPE_POLICY_VERSION,
    SpatialScope,
)

CENTER = (107.9758, 26.5734)
CALIBER = get_caliber("walking")  # reach_full_min = 20.0


def _zone(minutes: float, half_m: float) -> Dict[str, Any]:
    ring = [
        xy_to_lnglat(CENTER, -half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, half_m),
        xy_to_lnglat(CENTER, -half_m, half_m),
    ]
    return {"minutes": minutes, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}


def _iso(*zones: Dict[str, Any]) -> Dict[str, Any]:
    return {"isochrones": list(zones), "sampling": {"points": []}}


# ── 1. 按口径选环，不按位置 ──────────────────────────────────────
def test_from_iso_selects_ring_by_minutes_not_position():
    """尾部追加一个 25min 圈 → 可达区仍是 20min 圈（按位置取 `[-1]` 会静默变成 25min）。"""
    z20 = _zone(20.0, 1000.0)
    iso = _iso(
        _zone(5.0, 200.0),
        _zone(10.0, 400.0),
        _zone(15.0, 700.0),
        z20,
        _zone(25.0, 5000.0),  # 未来新增的圈：比可达区大得多，用来当「污染探针」
    )
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, iso)
    assert scope.reach_min == 20.0
    # 外接圆 = 20min 环顶点的实测最远距离；「取到 25min 圈」时该值会跳到 7000m 量级
    expected = max(haversine_m(CENTER, p) for p in z20["geojson"]["coordinates"][0])
    assert scope.reach_circumradius_m == pytest.approx(expected, rel=1e-9)
    assert scope.reach_circumradius_m < 2000.0, "取到了 25min 圈（按位置取 [-1] 的经典症状）"


def test_from_iso_ignores_ring_order():
    """等时圈族顺序被打乱 → 仍按 minutes 命中同一条环。"""
    z5, z20 = _zone(5.0, 200.0), _zone(20.0, 1000.0)
    a = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(z5, z20))
    b = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(z20, z5))
    assert a.reach_ring == b.reach_ring
    assert a.reach_circumradius_m == pytest.approx(b.reach_circumradius_m)


# ── 2. 空 / 不匹配必须拒 ─────────────────────────────────────────
def test_from_iso_rejects_empty_isochrones():
    """P6 的唯一入口：没有等时圈就没有可达区，绝不允许「无可达区」的报告流下去。"""
    with pytest.raises(ValueError, match="等时圈族为空"):
        SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso())


def test_from_iso_rejects_missing_reach_ring():
    """圈族里没有 minutes == reach_full_min 的圈 → 口径与数据不一致，必须拒。"""
    with pytest.raises(ValueError, match="没有 minutes="):
        SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(5.0, 200.0), _zone(10.0, 400.0)))


def test_from_reach_zone_rejects_minutes_mismatch():
    """显式传环时校验 `zone.minutes == caliber.reach_full_min`（防「形参名撒谎」复发）。"""
    with pytest.raises(ValueError, match="与口径 reach_full_min"):
        SpatialScope.from_reach_zone(CALIBER, CENTER, 2500.0, _zone(15.0, 700.0))


def test_from_reach_zone_rejects_degenerate_ring():
    """顶点数 < 3 → 构不成多边形，必须拒（否则 `point_in_ring` 会静默判「全在外」）。"""
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[[107.9758, 26.5734], [107.98, 26.58]]]}}
    with pytest.raises(ValueError, match="顶点数不足"):
        SpatialScope.from_reach_zone(CALIBER, CENTER, 2500.0, zone)


# ── 3. 采集区 ⊇ 可达区 + 证据余量（构造即校验）────────────────────
def test_evidence_margin_is_derived_from_blind_radius():
    """采集余量由**证据需求**导出，不是可填的名义值（原「D2 口径锁定」用例的原地改造）。

    这条用例本身曾是缺陷的**制度化载体**：它断言 `COLLECT_MARGIN_M == 0.0`，把「余量取 0」
    当成口径锁定 —— 而取 0 让可判定面积实测只剩 5%（97 格里判 5 格），而它换来的东西
    （「圈外点不进报告」）已由可达区过滤独立完整地保证 ⇒ 一个零收益的取舍。
    现在锁定的不再是某个数，而是**关系**：余量就是判定半径本身。
    """
    assert EVIDENCE_MARGIN_M == BLIND_RADIUS_M
    assert EVIDENCE_MARGIN_M is BLIND_RADIUS_M, "必须是同一个量，不是抄来的第二个 1000.0"
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    assert scope.collect_radius_m == pytest.approx(scope.reach_circumradius_m + BLIND_RADIUS_M)
    assert scope.invariant() is None  # 不抛即通过


def test_invariant_rejects_the_retired_zero_margin():
    """把余量改回 0（旧 D2）必须**当场报错**，而不是悄悄把判盲能力砍掉 95%。

    这是本次修复的防复发主闸：旧世界里 `COLLECT_MARGIN_M = 0.0` 是一行随时可改的常量，
    且没有任何一层会发现 —— 现在它是 invariant 的违反项，改回去第一次运行就炸。
    """
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    d2 = dataclasses.replace(scope, collect_radius_m=scope.reach_circumradius_m)
    with pytest.raises(ValueError, match="D2（余量 0）已废止"):
        d2.invariant()


def test_circumradius_is_measured_max_vertex_distance():
    """外接圆半径 = 环上**实测**顶点距中心的最大值（不是名义 study_radius_m）。"""
    ring = [
        xy_to_lnglat(CENTER, -1000.0, -1000.0),
        xy_to_lnglat(CENTER, 1400.0, -200.0),   # 最远顶点
        xy_to_lnglat(CENTER, 900.0, 300.0),
        xy_to_lnglat(CENTER, -300.0, 1100.0),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(CALIBER, CENTER, 2500.0, zone)
    expected = max(haversine_m(CENTER, p) for p in ring)
    assert scope.reach_circumradius_m == pytest.approx(expected, rel=1e-9)
    assert scope.reach_circumradius_m != pytest.approx(2500.0)


def test_invariant_rejects_collect_smaller_than_reach():
    """采集区小于可达区 → 可达区内必然有无数据格，构造后校验必须拦下。"""
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    broken = dataclasses.replace(scope, collect_radius_m=scope.reach_circumradius_m - 1.0)
    with pytest.raises(ValueError, match="D2（余量 0）已废止"):
        broken.invariant()


def test_invariant_rejects_non_positive_study_radius():
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    with pytest.raises(ValueError, match="研究半径必须为正"):
        dataclasses.replace(scope, study_radius_m=0.0).invariant()


# ── 4. 举证对象 ────────────────────────────────────────────────
def test_payload_declares_three_concepts_and_unknown_count():
    """报告口径必须把「可达区 / 采集区 / 未判定格」三件事都写出来，且冻结。"""
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    payload = scope.payload(CALIBER, {"cells_inside": 100, "cells_judged": 40, "cells_unknown": 60})
    for key in (
        "reach_full_min",
        "reach_radius_bound_m",
        "reach_circumradius_m",
        "collect_radius_m",
        "collect_margin_m",
        "scope_policy_version",
        "cells_inside",
        "cells_judged",
        "cells_unknown",
    ):
        assert key in payload, f"报告口径缺少 {key}（无可观测性出口 ⇒ 采集半径算错也看不出来）"
    assert payload["reach_full_min"] == 20.0
    assert payload["cells_unknown"] == 60
    # 版本由 payload **唯一发射**（读侧 `report_contract.reuse_policy` 与契约判据都读它，
    # 不进缓存键 —— 见 scope.SCOPE_POLICY_VERSION 的理由）
    assert payload["scope_policy_version"] == SCOPE_POLICY_VERSION
    # 原有字段不得丢（前端/评分依赖）
    for key in ("travel_mode", "speed_m_per_min", "detour_k", "study_radius_m", "iso_minutes", "basis", "measured"):
        assert key in payload


def test_scope_is_frozen():
    """值对象不可变：下游拿到 scope 后不能偷偷改口径。"""
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.reach_ring = ()  # type: ignore[misc]


def test_payload_without_stats_omits_cell_counts():
    """未跑盲区判定时不伪造格数（不写 0，避免「0 未判定」被读成「全覆盖」）。"""
    scope = SpatialScope.from_iso(CALIBER, CENTER, 2500.0, _iso(_zone(20.0, 1000.0)))
    payload = scope.payload(CALIBER)
    assert "cells_unknown" not in payload
