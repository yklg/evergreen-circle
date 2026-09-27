"""M1 · 等时圈引擎：采样网格对齐 / IDW（kNN）/ 等值线族契约。"""
import asyncio
import math

import numpy as np
import pytest

from app.living_circle.geo_utils import haversine_m, to_local_xy
from app.living_circle.isochrone import (
    MODE_PARAMS,
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


# ── D1/D2（计划 v4 阶段 0）· fine_band 透传 与 降规格披露 ──────────
# 形态沿用本仓先例：先「记录当前行为」把缺陷量化钉住，再配一条 `xfail(strict=True)`
# 断言应有行为 —— 修好后必须转 XPASS 报错，逼着把判据重指（禁止就地放宽或删掉）。

def test_fine_band_is_currently_borrowed_from_walking_for_wider_calibers():
    """**记录当前行为**：`compute()` 不透传 `fine_band` ⇒ 骑行/驾车的加密环带被步行的截断。

    `caliber.fine_band = (max(r_inner, 400), study_radius_m)` 是**逐档派生**的
    （步行 2500 / 骑行 5000 / 驾车 9000），但 `isochrone.py:302` 调 `build_sample_points`
    时不传 `fine_band`，只能落到 `:132-134` 的 `get_caliber("walking").fine_band` 硬回落
    ⇒ 骑行 20min 圈的外沿（2500–5000m）**一格加密都没有**。这不是精度偏好问题，
    是"配了逐档口径、实际用的是别人的口径"。
    """
    from app.living_circle.caliber import get_caliber

    def _density_km2(pts, lo, hi):
        n = sum(1 for p in pts if lo < haversine_m(CENTER, p) <= hi)
        return n / (math.pi * (hi * hi - lo * lo) / 1e6)

    riding_band = get_caliber("riding").fine_band
    assert riding_band[1] > 2500.0, "前置不成立：骑行口径的环带上沿本应超出步行研究半径"

    # 按 compute() 实际调用方式生成（不传 fine_band ⇒ 回落步行的 (400, 2500)）
    as_computed = build_sample_points(CENTER, 5000.0, 400, 150)
    per_mode = build_sample_points(CENTER, 5000.0, 400, 150, fine_band=riding_band)
    assert len(per_mode) > len(as_computed) * 1.2, (
        "按骑行自己的环带并没有多出点 ⇒ 对照不成立，请重指本用例"
    )

    inner = _density_km2(as_computed, 1500.0, 2500.0)  # 步行环带内 ⇒ 有 150m 加密
    outer = _density_km2(as_computed, 2600.0, 5000.0)  # 骑行该加密、却只剩 400m 粗格
    assert inner > outer * 2, (
        f"骑行研究半径内 2.6–5km 的采样密度 {outer:.1f} 点/km² 相对 1.5–2.5km 的 "
        f"{inner:.1f} 没有塌陷 ⇒ 回落效应已消失，本现状记录该转红重指了"
    )


@pytest.mark.xfail(
    strict=True,
    reason="计划 v4 阶段 0：`IsochroneEngine.compute()` 未收 `fine_band` 形参，"
           "骑行/驾车档的边界加密环带被步行口径硬回落（isochrone.py:289/302/132-134）",
)
def test_compute_should_accept_and_forward_fine_band():
    import inspect

    sig = inspect.signature(IsochroneEngine.compute)
    assert "fine_band" in sig.parameters, "compute() 必须能把生效环带说清楚，而不是让下游猜"


def test_degraded_sampling_currently_discloses_no_effective_spec():
    """**记录当前行为**：预算受限时采样规格被降（丢 fine 带），但插值格 `grid_n` 不动，
    且 `iso["sampling"]` 里**没有任何字段**说明这次实际用的是哪套规格。

    后果：IDW 拿 ~250m 间距的点云去填 83m 的插值格，图上看着一样精、实际更假 ——
    与「最内圈网格坍缩」同族。D5 要把推导方向翻成「规格→点数→预算」，前提是
    实际生效规格先变得**可观测**，否则降了规格也没人知道。
    """
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=375))
    assert 0 < iso["sample_count"] <= 375

    grid_n = MODE_PARAMS["standard"]["grid_n"]
    interp_step = 2 * 2500.0 / (grid_n - 1)
    sample_step = 2 * 2500.0 / (math.sqrt(4.0 * iso["sample_count"] / math.pi) - 1)
    assert interp_step * 2 < sample_step, (
        f"前置不成立：插值格距 {interp_step:.0f}m 与采样间距 {sample_step:.0f}m 没拉开，"
        f"本用例测不到过度插值"
    )
    leaked = {k for k in iso["sampling"] if k in {"coarse_m", "fine_m", "fine_band", "grid_n", "spec"}}
    assert leaked == set(), (
        f"实际生效规格已经被披露了（{leaked}）⇒ 本现状记录必须转红并重指到规格字段判据上"
    )


@pytest.mark.xfail(
    strict=True,
    reason="计划 v4 D5：预算不足时降的是**规格**并须如实标注；当前只降点数、"
           "grid_n 不动且无字段可举证（isochrone.py:157-185 vs :305）",
)
def test_sampling_should_disclose_the_effective_spec():
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=375))
    spec = iso["sampling"]["spec"]
    assert spec["fine_m"] in (None, 0), "375 点走的是单阶段粗网格，fine 带应声明为已放弃"
    assert spec["grid_step_m"] >= spec["sample_step_m"], (
        "插值格距必须不细于采样间距 —— 否则 IDW 在造没有测过的细节"
    )