"""
装配层盲区增强（R1/R3/R4）：
- ``_reach_for``：真实等时圈(IDW)实测分钟 → isochrone_based=true；无实测降级 nearest/80 → false。
- ``_affected_for``：采样点 polygon∩points 计数 + 密度估算（proxy）；无采样/离线 → null（R4）。
"""
import numpy as np
import pytest

from app.living_circle.assemble import (
    DEMAND_DENSITY_HH_KM2,
    HH_SIZE,
    _affected_for,
    _reach_for,
)
from app.living_circle.geo_utils import xy_to_lnglat, to_local_xy, ring_area_km2


def _ring_square(center, half_m=800.0):
    """局部 ±half_m 方形闭合环（lnglat）。"""
    pts = [
        xy_to_lnglat(center, -half_m, -half_m),
        xy_to_lnglat(center, half_m, -half_m),
        xy_to_lnglat(center, half_m, half_m),
        xy_to_lnglat(center, -half_m, half_m),
        xy_to_lnglat(center, -half_m, -half_m),
    ]
    return [list(p) for p in pts]


CENTER = (107.9758, 26.5734)


class _Check:
    scene_name = "测试社区"
    city = "测试市"
    address = "测试区"
    center = list(CENTER)


def test_reach_priority_isochrone_then_fallback():
    # ① 有 IDW 实测 → isochrone_based=true，取 field_fn 分钟
    b_live = {
        "center": CENTER,
        "nearest": [{"facility": "market", "distance_m": 1500, "direction": "北", "name": "A"}],
    }
    field = lambda pt: 18.5  # noqa: E731 真实等时圈实测 18.5min
    assert _reach_for(CENTER, field, b_live) == {"real_walk_min": 18.5, "isochrone_based": True}

    # ② 无实测（field_fn→None）→ 降级 nearest 距离/80，isochrone_based=false（R3 如实）
    field_none = lambda pt: None  # noqa: E731
    out = _reach_for(CENTER, field_none, b_live)
    assert out == {"real_walk_min": round(1500 / 80.0, 1), "isochrone_based": False}

    # ③ 既无实测也无 nearest → real_walk_min=None（不编造）
    b_bare = {"center": CENTER, "nearest": []}
    assert _reach_for(CENTER, field_none, b_bare)["real_walk_min"] is None


def test_affected_sampling_sites_matches_polygon_intersection():
    """R1：sampling_sites == 手工 polygon∩points 计数（确定性真数据）。"""
    ring = _ring_square(CENTER)  # ±800m 方形
    # 造一批采样点：4 个落在方形内，2 个在方形外
    sample = []
    sample += [{"lng": l, "lat": t, "minutes": 10.0, "reachable": True}
               for l, t in [xy_to_lnglat(CENTER, 200, 200), xy_to_lnglat(CENTER, -200, 300),
                            xy_to_lnglat(CENTER, 400, -100), xy_to_lnglat(CENTER, -300, -200)]]
    sample += [{"lng": l, "lat": t, "minutes": 25.0, "reachable": False}
               for l, t in [xy_to_lnglat(CENTER, 1500, 0), xy_to_lnglat(CENTER, -1600, 1600)]]

    from app.living_circle.geo_utils import point_in_ring

    manual = sum(1 for sp in sample if point_in_ring((sp["lng"], sp["lat"]), ring))
    assert manual == 4
    out = _affected_for(ring, CENTER, sample)
    assert out is not None
    assert out["provenance"] == "proxy"
    assert out["sampling_sites"] == 4
    area = ring_area_km2(ring, CENTER)
    hh = int(area * DEMAND_DENSITY_HH_KM2)
    assert out["estimated_households"] == hh
    assert out["estimated_residents"] == int(hh * HH_SIZE)
    assert "非真实人口数据" in out["note"]


def test_affected_proxy_density_scales_with_area():
    """面积越大 → 估算户数/人数越大（密度常数口径自洽）。"""
    small = _affected_for(_ring_square(CENTER, 400), CENTER,
                          [{"lng": l, "lat": t, "minutes": 8.0, "reachable": True}
                           for l, t in [xy_to_lnglat(CENTER, 0, 0)]])
    large = _affected_for(_ring_square(CENTER, 1000), CENTER,
                          [{"lng": l, "lat": t, "minutes": 8.0, "reachable": True}
                           for l, t in [xy_to_lnglat(CENTER, 0, 0)]])
    assert large["estimated_residents"] > small["estimated_residents"]
    assert large["sampling_sites"] == small["sampling_sites"] == 1


def test_affected_null_when_no_ring_or_no_sampling():
    """R4：无盲区多边形或无采样点（离线/非 sampling 报告）→ None，不抛伪代理数。"""
    ring = _ring_square(CENTER)
    assert _affected_for(None, CENTER, [{"lng": CENTER[0], "lat": CENTER[1]}]) is None
    assert _affected_for(ring, CENTER, []) is None
    assert _affected_for(ring, CENTER, None) is None


def test_proxy_not_labeled_as_measured():
    """诚实口径（架构审查）：provenance 恒为 proxy，绝不冒充真实人口数据。"""
    out = _affected_for(_ring_square(CENTER), CENTER,
                        [{"lng": l, "lat": t, "minutes": 8.0, "reachable": True}
                         for l, t in [xy_to_lnglat(CENTER, 100, 100)]])
    assert out["provenance"] == "proxy"
    assert "估算" in out["note"]


def test_annotate_handles_mismatched_sample_minutes_regression():
    """旧快照回归（实测 lc-9f5d9238 崩溃点）：采样点全量含 None 分钟时，
    sample_xy 与 minutes 必须**同长**（None 留待 idw_from_local 内部 valid 过滤），
    否则 annotate 触发 isochrone 长度 assert（498/497），导致 list 接口 500。"""
    from app.living_circle.assemble import annotate_blindspots

    ring = _ring_square(CENTER)
    # 构造一个含 None 分钟的采样点集（旧快照中部分点位分钟缺失）
    pts = []
    for dx, dy in [(-600, -600), (600, -600), (600, 600), (-600, 600)]:
        l, t = xy_to_lnglat(CENTER, dx, dy)
        pts.append({"lng": l, "lat": t, "minutes": 7.0, "reachable": True})
    # 再混入 2 个 None 分钟点，模拟采样分钟与坐标脱节的旧快照
    for dx, dy in [(200, 0), (-200, 300)]:
        l, t = xy_to_lnglat(CENTER, dx, dy)
        pts.append({"lng": l, "lat": t, "minutes": None, "reachable": False})

    report = {
        "scene": {"name": "测试", "center": list(CENTER), "study_radius_m": 2500},
        "sampling": {"points": pts},
        "blindspots": [
            {
                "id": "bs-旧-1", "center": list(CENTER), "radius_m": 1000,
                "missing_facilities": ["菜市场"], "nearest": [],
                "polygon": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }
    out = annotate_blindspots(report)
    b = out["blindspots"][0]
    assert b["severity"] in {"heavy", "medium", "light"}
    assert 0.0 <= b["gap_score"] <= 1.0
    assert "reach" in b
    assert ("affected" in b) and b["affected"] is not None