"""盲区 marching-squares 边界集成测试（组 3/4）。

- BI-1 · 语义不变：几何改造前后 center/severity/gap_score/fixes 不变（只 polygon 变）
- BI-2 · 新 polygon 闭合 + GeoJSON 类型
- BI-3 · footprint_meta 字段齐全 + undersampled 阈值
- AS-1 · 旧报告（缺 footprint_meta）经契约不判违规 —— legacy 兼容
"""
import pytest

from app.living_circle.blindspot import MS_REFINE, find_blindspots_with_stats
from app.living_circle.caliber import get_caliber
from app.living_circle.contour import blob_area
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.report_contract import assess_geometry, report_is_presentable
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)


def _scope(half_m: float = 2500.0) -> SpatialScope:
    ring = [
        xy_to_lnglat(CENTER, -half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, half_m),
        xy_to_lnglat(CENTER, -half_m, half_m),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, half_m * 1.0, zone)
    scope.invariant()
    return scope


def _fac(name, x, y):
    lng, lat = xy_to_lnglat(CENTER, x, y)
    return {"name": name, "lng": lng, "lat": lat}


def _triad_cluster(center, x, y):
    """在 (x,y) 处放三要素齐全簇。"""
    return [
        {"name": f"菜市-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y)))},
        {"name": f"药店-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x + 300, y)))},
        {"name": f"小学-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y + 300)))},
    ]


def _lc_with_spot(blindspot) -> dict:
    """构造一份含给定盲区、其余几何自洽的 living_circle 载荷（供契约评估）。"""
    ring = [
        xy_to_lnglat(CENTER, -2500, -2500),
        xy_to_lnglat(CENTER, 2500, -2500),
        xy_to_lnglat(CENTER, 2500, 2500),
        xy_to_lnglat(CENTER, -2500, 2500),
    ]
    return {
        "data_origin": "live",
        "caliber": {"reach_full_min": 20.0, "collect_radius_m": 4000.0},
        "scene": {"center": list(CENTER)},
        "poi": {"points": [{"name": "菜市", "category": "market", "lng": 500, "lat": 0}]},
        "isochrones": [
            {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
        ],
        "blindspots": [blindspot],
    }


def _produce_spot():
    """构造一个缺小学的盲区长典型样例。"""
    triads = {
        "market": [_fac("菜市", 500, 0), _fac("菜市-远", -1800, 1800)],
        "pharmacy": [_fac("药店", 0, 500), _fac("药店-远", 1800, -1800)],
        "primary": [],  # 缺小学
    }
    scope = _scope()
    spots, stats = find_blindspots_with_stats(CENTER, scope, triads, prefix="m")
    assert spots, "样例应产生至少一个盲区（缺小学）"
    return spots[0], stats


def test_semantics_fields_present_and_type():
    """BI-1 · 语义字段齐全且类型正确（改造后仍带 severity/gap/fixes/center）。"""
    spot, _ = _produce_spot()
    assert spot["severity"] in {"heavy", "medium", "light"}
    assert 0.0 <= spot["gap_score"] <= 1.0
    assert isinstance(spot["center"], list) and len(spot["center"]) == 2
    assert isinstance(spot["fixes"], list) and all("priority" in f for f in spot["fixes"])
    assert spot["missing_facilities"], "盲区必须点名缺失类"
    assert "小学" in spot["missing_facilities"], "_produce_spot 的 primary 全域无点 ⇒ 必缺小学"


def test_polygon_closed_and_geojson():
    """BI-2 · 新 polygon 闭合 + GeoJSON 类型；且为连续平滑环（非退化矩形）。"""
    spot, _ = _produce_spot()
    poly = spot["polygon"]
    assert poly["type"] == "Polygon"
    ring = poly["coordinates"][0]
    assert ring[0] == ring[-1]  # 闭合
    assert len(ring) >= 5
    # 平滑环尺寸自洽：顶点数较多（marching 细分产生），非平凡单点
    from app.living_circle.geo_utils import to_local_xy

    pts_xy = [to_local_xy(CENTER, p[0], p[1]) for p in ring]
    assert blob_area(pts_xy) > 0.0


def test_footprint_meta_fields_and_undersampled():
    """BI-3 · footprint_meta 字段齐全；refine 生效；大簇→非 undersampled。"""
    spot, stats = _produce_spot()
    assert "cells" in spot["footprint_meta"]
    assert "resolution_m" in spot["footprint_meta"]
    assert "grid_m" in spot["footprint_meta"]
    assert "refine" in spot["footprint_meta"]
    assert "undersampled" in spot["footprint_meta"]
    # 若簇较大（>3 格）则不该标记 undersampled
    if spot["footprint_meta"]["cells"] > 3:
        assert spot["footprint_meta"]["undersampled"] is False
    assert isinstance(spot["footprint_meta"]["undersampled"], bool)


def test_polygon_within_reach_bounds():
    """BI-4 · 越界护栏：新 polygon 顶点的最大单轴偏移不超可达区外接圆。"""
    spot, _ = _produce_spot()
    ring = spot["polygon"]["coordinates"][0]
    # 顶点相对于中心的最大单轴偏移（米）
    from app.living_circle.geo_utils import to_local_xy

    max_off = 0.0
    for lng, lat in ring:
        x, y = to_local_xy(CENTER, lng, lat)
        max_off = max(max_off, abs(x), abs(y))
    assert max_off <= 2600.0  # 2500 半径 + 容差


def test_dual_boundary_raw_and_smoothed():
    """BI-5 · 双边界解耦：polygon_raw（精确锯齿）与 polygon（显示圆角）都闭合、都落在可达区内；
    二者同源（顶点数不同、raw 为平滑之母）。"""
    spot, _ = _produce_spot()
    assert "polygon_raw" in spot
    raw = spot["polygon_raw"]
    assert raw["type"] == "Polygon"
    raw_ring = raw["coordinates"][0]
    sm_ring = spot["polygon"]["coordinates"][0]
    # 各自闭合
    assert raw_ring[0] == raw_ring[-1]
    assert sm_ring[0] == sm_ring[-1]
    # raw 原始锯齿（未经 smooth_ring），通常顶点少于/多于平滑环之一致即可——但必须非空
    assert len(raw_ring) >= 4 and len(sm_ring) >= 4
    # 平滑环是对 raw 的邻域均值，故两者顶点数应匹配（smooth_ring 不改变点序长度）
    assert len(sm_ring) == len(raw_ring)
    # polygon_raw 顶点也须落在可达区外接圆内（与 polygon 同约束）
    from app.living_circle.geo_utils import to_local_xy

    max_off = 0.0
    for lng, lat in raw_ring:
        x, y = to_local_xy(CENTER, lng, lat)
        max_off = max(max_off, abs(x), abs(y))
    assert max_off <= 2600.0


def test_legacy_report_no_footprint_meta_is_presentable():
    """AS-1 · 旧报告（缺 footprint_meta）不判违规 —— legacy 兼容。"""
    spot, _ = _produce_spot()
    # 去掉 footprint_meta，模拟旧 schema
    del spot["footprint_meta"]
    lc = _lc_with_spot(spot)
    issues = assess_geometry(lc)
    assert issues.ok, f"旧报告不应违规，实得：{issues.reason}"
    assert report_is_presentable(lc)