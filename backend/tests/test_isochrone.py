"""M1 · 等时圈引擎：采样网格对齐 / IDW（kNN）/ 等值线族契约。"""
import asyncio
import math

import numpy as np
import pytest

from app.living_circle.geo_utils import haversine_m, to_local_xy
from app.living_circle.isochrone import (
    REACH_FULL_MIN,
    IsochroneEngine,
    _flag_of,
    build_sample_points,
    idw_from_local,
    reach_flags,
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
        # 语义分离（阶段 −1）：timed = 测时返回了值；in_reach = 且 ≤ REACH_FULL_MIN
        assert sp["timed"] is (sp["minutes"] is not None)
        assert isinstance(sp["in_reach"], bool)
        if sp["in_reach"]:
            assert sp["timed"] and sp["minutes"] <= REACH_FULL_MIN


def test_iso_engine_reachability_counts():
    """分档汇总数必须与逐点字段一致，且**不得相等**（相等即语义退化复发）。

    汇总数位于 ``sampling`` 内（不是 iso 顶层）—— 顶层字段不会被 ``assemble`` 透传进报告，
    那样每个消费方就得自己 filter 一遍点集。
    """
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    pts = iso["sampling"]["points"]
    assert iso["sample_count"] == len(pts)
    assert iso["sampling"]["timed_count"] == sum(1 for sp in pts if sp["minutes"] is not None)
    assert iso["sampling"]["in_reach_count"] == sum(
        1 for sp in pts if sp["minutes"] is not None and sp["minutes"] <= REACH_FULL_MIN
    )
    # 合成测时场里 d∈(1500, 2200] 的点「已测时但 >20min」——若两数相等，
    # 说明 in_reach 又退化成了「测时返回了值」（阶段 −1 之前的旧 bug）。
    timed_c = iso["sampling"]["timed_count"]
    in_reach_c = iso["sampling"]["in_reach_count"]
    assert 0 < in_reach_c < timed_c <= iso["sample_count"], (
        f"分档未分离：timed={timed_c} in_reach={in_reach_c} sample={iso['sample_count']}"
    )


def test_sampling_point_field_contract():
    """T-BE-11 · 采样点字段契约：键集固定，旧名 reachable 已彻底移除，汇总数同处 sampling。"""
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    for sp in iso["sampling"]["points"]:
        assert set(sp) == {"idx", "lng", "lat", "minutes", "timed", "in_reach"}, set(sp)
        assert "reachable" not in sp
    assert "reachable" not in iso["sampling"]
    assert "reachable_count" not in iso["sampling"]
    # 汇总数随点集一起落 sampling（消费方读这里，不再各自 filter）
    assert {"timed_count", "in_reach_count"} <= set(iso["sampling"])


def test_flag_of_boundary_at_reach_full_min():
    """T-BE-12 · 边界：阈值上取整后比较，20.0 算可达、20.1 不算、None 两者皆否。

    这是 `_flag_of` 的单点判据（全项目唯一实现），边界错一格会让 126 变成 125/127。
    """
    assert REACH_FULL_MIN == 20.0
    assert _flag_of(None) == (False, False)
    assert _flag_of(0) == (True, True)
    assert _flag_of(REACH_FULL_MIN - 0.1) == (True, True)
    assert _flag_of(REACH_FULL_MIN) == (True, True)          # 含端点
    assert _flag_of(REACH_FULL_MIN + 0.1) == (True, False)   # 不含
    # 浮点噪声：20.0000001 取整后应判为可达，不被误伤
    assert _flag_of(REACH_FULL_MIN + 1e-7) == (True, True)


def test_reach_flags_counts_match_pointwise_flags():
    """T-BE-13 · 汇总函数与单点判据同源（防「产出处另算一遍」的历史病）。"""
    pts = [
        {"minutes": None}, {"minutes": 0}, {"minutes": 19.9},
        {"minutes": 20.0}, {"minutes": 20.1}, {"minutes": 75.0},
    ]
    f = reach_flags(pts)
    assert f.timed_count == 5
    assert f.in_reach_count == 3
    # 与逐点判据对照，二者必须一致
    assert f.timed_count == sum(1 for p in pts if _flag_of(p["minutes"])[0])
    assert f.in_reach_count == sum(1 for p in pts if _flag_of(p["minutes"])[1])


def test_build_sample_points_fine_band_extra():
    """双阶段采样（散点扇形，30% 评分点叙事）：fine 开启比仅粗网格点数更多。"""
    coarse_only = build_sample_points(CENTER, 2500, 400, None)
    with_fine = build_sample_points(CENTER, 2500, 400, 150)
    assert len(with_fine) > len(coarse_only)


# ── v5 U1-U6 · 预算感知采样（B2/C/D1/O3：max_points 上限不变式 / 边界 / 双阶段恢复判据）──

def test_u1_budget_sample_points_capped():
    """U1：max_points 有限 → 采样点数 ≤ max_points（预算上限硬不变式）。"""
    pts = build_sample_points(CENTER, 2500, 400, 150, max_points=375)
    assert 0 < len(pts) <= 375
    # 预算受限单阶段：中心点必须仍在采样点内（奇数对称格不坍缩）
    assert any(abs(p[0] - CENTER[0]) < 1e-6 and abs(p[1] - CENTER[1]) < 1e-6 for p in pts)


def test_u2_budget_compute_chunk_contract():
    """U2：compute(max_points=375, standard) → sample_count ≤ 375 且 chunk 折算 ≤ mat_budget。"""
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=375))
    assert 0 < iso["sample_count"] <= 375
    assert math.ceil(iso["sample_count"] / 25) <= 15  # chunk=25 折算（单元自定口径）
    assert iso["sample_count"] == len(iso["sampling"]["points"])


def test_u3_max_points_none_preserves_two_stage():
    """U3：max_points=None → 与未传参数完全一致（零回归，D4）。"""
    two_stage = build_sample_points(CENTER, 2500, 400, 150)
    assert build_sample_points(CENTER, 2500, 400, 150, max_points=None) == two_stage
    engine = IsochroneEngine()
    a = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard"))
    b = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=None))
    assert b["sample_count"] == a["sample_count"]
    assert b["sampling"]["points"] == a["sampling"]["points"]


@pytest.mark.parametrize("mp", [1, 0, -5])
def test_u4_max_points_edge_values_never_crash(mp):
    """U4：max_points ∈ {1, 0, 负} → 不抛、不除零、至少 1 点（≤0 保持旧双阶段）。"""
    pts = build_sample_points(CENTER, 2500, 400, 150, max_points=mp)
    assert len(pts) >= 1
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=mp))
    assert iso["sample_count"] >= 1


def test_u5_max_points_beyond_two_stage_restores_full():
    """U5（O3 恢复判据）：max_points ≥ 旧双阶段点数 → 直接双阶段全精度，不降采样。"""
    two_stage = build_sample_points(CENTER, 2500, 400, 150)
    full = build_sample_points(CENTER, 2500, 400, 150, max_points=len(two_stage) + 1)
    assert len(full) == len(two_stage)
    assert full == two_stage


def test_u6_travel_modes_budget_invariant():
    """U6：walking/riding/driving 各档 max_points 下不变式成立（点数 ≤ 上限、分块 ≤ mat_budget）。"""
    from app.living_circle.caliber import get_caliber
    from app.living_circle.quota import mat_budget, max_matrix_origins_for

    for tm in ("walking", "riding", "driving"):
        cal = get_caliber(tm)
        mp = max_matrix_origins_for(tm)
        chunk = cal.api.chunk or 25
        pts = build_sample_points(CENTER, cal.study_radius_m, 400, 150, max_points=mp)
        assert 0 < len(pts) <= mp, f"{tm}: {len(pts)} > {mp}"
        assert math.ceil(len(pts) / chunk) <= mat_budget(), f"{tm}: 分块数超 mat_budget"