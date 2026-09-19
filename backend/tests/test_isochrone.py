"""M1 · 等时圈引擎：采样网格对齐 / IDW（kNN）/ 等值线族契约。"""
import asyncio

import numpy as np

from app.living_circle.geo_utils import haversine_m, to_local_xy
from app.living_circle.isochrone import (
    IsochroneEngine,
    build_sample_points,
    idw_from_local,
)

CENTER = (107.9758, 26.5734)


async def _radial_meter(pts, speed=75.0):
    out = []
    for p in pts:
        d = haversine_m(CENTER, p)
        out.append(d / speed if d < 2200 else None)
    return out


def test_build_sample_points_center_aligned():
    pts = build_sample_points(CENTER, 2500, 400, 400)
    assert len(pts) > 100
    # 中心点必须在采样点内（粗网格奇数对称）
    assert any(abs(p[0] - CENTER[0]) < 1e-6 and abs(p[1] - CENTER[1]) < 1e-6 for p in pts)
    # 研究范围约束
    for p in pts:
        assert haversine_m(CENTER, p) <= 2500 + 50


def test_idw_knn_local_field_is_local():
    """kNN IDW：200m 处应接近相邻采样值的线性插值（≤ 最近非零点 4.76min）。"""
    pts = build_sample_points(CENTER, 2500, 400, 400)
    mins = asyncio.run(_radial_meter(pts))
    sxy = np.array([to_local_xy(CENTER, p[0], p[1]) for p in pts])
    f = idw_from_local(sxy, mins, np.array([[200.0, 0.0]]))
    assert 0 < float(f[0]) < 6.0, f"200m 处耗时应在 0~6min，实际 {f[0]:.2f}"


def test_iso_engine_monotonic_zones():
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    zones = {z["minutes"]: z for z in iso["isochrones"]}
    assert set(zones) == {5, 10, 15, 20}
    areas = [zones[m]["area_km2"] for m in (5, 10, 15, 20)]
    # 单调递增
    assert all(b > a for a, b in zip(areas, areas[1:]))
    # 半径理论（r = m*75m）：5min=375m→0.44, 10=750→1.77, 15=1125→3.97, 20=1500→7.07
    expected = [0.44, 1.77, 3.97, 7.07]
    for got, exp in zip(areas, expected):
        assert 0.5 * exp < got < 1.6 * exp, f"{got} vs 理论 {exp}"


def test_iso_engine_contract_shape():
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard"))
    s = iso["sampling"]
    assert s["interpolation"] == "idw"
    assert isinstance(s["is_scattered"], bool)
    assert len(s["points"]) == iso["sample_count"]
    for z in iso["isochrones"]:
        ring = z["geojson"]["coordinates"][0]
        assert z["geojson"]["type"] == "Polygon"
        assert ring[0] == ring[-1]  # 闭合
        assert z["area_km2"] > 0
    for sp in s["points"]:
        assert isinstance(sp["idx"], int)
        if sp["reachable"]:
            assert sp["minutes"] is not None


def test_iso_engine_reachability_counts():
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    reachable = [sp for sp in iso["sampling"]["points"] if sp["reachable"]]
    assert iso["reachable_count"] == len(reachable)


def test_build_sample_points_fine_band_extra():
    """双阶段采样（散点扇形，30% 评分点叙事）：fine 开启比仅粗网格点数更多。"""
    coarse_only = build_sample_points(CENTER, 2500, 400, None)
    with_fine = build_sample_points(CENTER, 2500, 400, 150)
    assert len(with_fine) > len(coarse_only)