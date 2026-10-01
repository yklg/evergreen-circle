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
    sample_plan,
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
    """U6：walking/riding/driving 各档 max_points 下不变式成立（点数 ≤ 上限、分块 ≤ 矩阵额度）。"""
    from app.living_circle.caliber import get_caliber
    from app.living_circle.quota import mat_budget_for, max_matrix_origins

    for tm in ("walking", "riding", "driving"):
        cal = get_caliber(tm)
        mp = max_matrix_origins("standard", tm)
        chunk = cal.api.chunk or 25
        pts = build_sample_points(CENTER, cal.study_radius_m, 400, 150, max_points=mp)
        assert 0 < len(pts) <= mp, f"{tm}: {len(pts)} > {mp}"
        assert math.ceil(len(pts) / chunk) <= mat_budget_for("standard", tm), \
            f"{tm}: 分块数超矩阵额度"


# ── D1/D2（计划 v4 阶段 0）· fine_band 透传 与 降规格披露 ──────────
#
# 阶段 0 落了两件事：① `compute()` 收 `travel_mode`/`fine_band` 并**真的**透传到采样几何；
# ② `sampling.spec` 披露实际生效规格（被预算丢掉的 fine 带如实为 None）。
# 于是原挂账的 D1t 转正式断言；D2t 拆成两半 —— 披露半转正，仍不成立的那一半
# （插值格不得细于采样）判据**重指**后继续 strict 挂账到 D5（阶段 3）。
# 为什么不靠把插值格调粗来凑绿：现状连双阶段正常路径都不满足（格 ≈77m vs 边界带 150m），
# 动格子会让所有历史等时圈面积漂移 —— 那是拿一个错换另一个错，正解是反向导出规格。

def test_compute_forwards_the_travel_mode_band():
    """D1t 转正 · 计划 v4 阶段 0 验收原话：travel_mode 切换时细带环带随之改变。

    判据刻意不只看签名或只看 `spec` 字段 —— 那两种写法在「参数收了、传错了」时照样绿。
    这里用点数分布证明环带真的进了几何：2.6–5km 那一圈，粗网格本来只有 ≈376 个点，
    换成骑行自己的环带（833–5000m）会多出加密点；借来的步行环带止于 2500m，多不出来。
    """
    from app.living_circle.caliber import get_caliber

    engine = IsochroneEngine()
    # quick 档（fine=粗格距）即可判环带归属，与档位点数无关；R=5000 才够到步行环带之外
    iso = asyncio.run(engine.compute(
        CENTER, _radial_meter, study_radius_m=5000, mode="quick", travel_mode="riding"))
    spec = iso["sampling"]["spec"]
    assert spec["travel_mode"] == "riding"
    assert spec["fine_band"] == [float(v) for v in get_caliber("riding").fine_band], (
        "spec 里的环带不等于骑行口径的派生值 ⇒ 透传的是别人的口径"
    )

    borrowed = sample_plan(
        CENTER, 5000.0, 400, 150, get_caliber("walking").fine_band).points
    measured = [(p["lng"], p["lat"]) for p in iso["sampling"]["points"]]

    def _in_annulus(pts, lo, hi):
        return sum(1 for p in pts if lo < haversine_m(CENTER, p) <= hi)

    outer_borrowed = _in_annulus(borrowed, 2600.0, 5000.0)
    assert _in_annulus(measured, 2600.0, 5000.0) > outer_borrowed * 1.5, (
        f"按骑行环带在 2.6–5km 并没有明显加密（{outer_borrowed} → 未达 {outer_borrowed * 1.5:.0f}）"
        f"⇒ 本用例判别力已失效，请重指判据而不是删掉"
    )

    # 显式 `fine_band` 必须压过 `travel_mode` 的派生值，且几何真的以它的外沿为界：
    # 骑行的派生环带到 5000m，若没被覆盖，采样点会一路铺出研究半径。
    override = asyncio.run(engine.compute(
        CENTER, _radial_meter, study_radius_m=1200, mode="standard",
        travel_mode="riding", fine_band=(100.0, 1200.0)))
    assert override["sampling"]["spec"]["fine_band"] == [100.0, 1200.0]
    farthest = max(haversine_m(CENTER, (p["lng"], p["lat"]))
                   for p in override["sampling"]["points"])
    assert farthest <= 1201.0, (
        f"传了 fine_band=(100,1200) 却仍采样到 {farthest:.0f}m ⇒ 形参没收进几何，只进了 spec"
    )


def test_build_sample_points_default_band_is_still_walking():
    """**现状记录**：`build_sample_points` 不传 band 时仍回落**步行**口径（历史语义，有意保留）。

    阶段 0 修的是 `compute()` 的透传；这个默认值本身没动，因为离线源与合成场测试全靠它
    保持零回归（D4）。留本用例的理由是它把这个默认的**代价量化**出来了：骑行研究半径内
    2.6–5km 的采样密度相对 1.5–2.5km 塌了一个量级。将来若有人把默认改成"按 mode 派生"或
    "不给 band 就报错"，本用例必须转红 ⇒ 届时把判据重指到新默认上，别直接删。
    """
    from app.living_circle.caliber import get_caliber

    def _density_km2(pts, lo, hi):
        n = sum(1 for p in pts if lo < haversine_m(CENTER, p) <= hi)
        return n / (math.pi * (hi * hi - lo * lo) / 1e6)

    riding_band = get_caliber("riding").fine_band
    assert riding_band[1] > 2500.0, "前置不成立：骑行口径的环带上沿本应超出步行研究半径"

    # 不传 fine_band ⇒ 回落步行的 (400, 2500)
    as_computed = build_sample_points(CENTER, 5000.0, 400, 150)
    per_mode = build_sample_points(CENTER, 5000.0, 400, 150, fine_band=riding_band)
    assert len(per_mode) > len(as_computed) * 1.2, (
        "按骑行自己的环带并没有多出点 ⇒ 对照不成立，请重指本用例"
    )

    inner = _density_km2(as_computed, 1500.0, 2500.0)  # 步行环带内 ⇒ 有加密
    outer = _density_km2(as_computed, 2600.0, 5000.0)  # 骑行该加密、却只剩粗格
    assert inner > outer * 2, (
        f"回落效应已经消失（2.6–5km 密度 {outer:.1f} vs 1.5–2.5km 的 {inner:.1f}）⇒ "
        f"本现状记录该转红重指了"
    )


def test_degraded_sampling_discloses_the_effective_spec():
    """D2t 的披露半转正：预算逼着降规格时，`sampling.spec` 必须说清实际用了哪一套。

    旧写法只有 `sample_count`，于是「按规格跑满」与「被预算压过、环带丢了」产出的报告
    长得一模一样 —— D5 要把推导方向翻成「规格→点数→预算」，前提是先看得见实际规格。
    """
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(
        CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=375))
    spec = iso["sampling"]["spec"]

    assert 0 < iso["sample_count"] <= 375
    assert spec["degraded"] is True, "375 点走的是预算受限单阶段，必须自报降过规格"
    assert spec["fine_m"] is None and spec["fine_band"] is None, (
        "加密带已被丢弃，spec 却还在替名义档位作证"
    )
    assert iso["sampling"]["is_scattered"] is False, (
        "`is_scattered` 旧写法读 MODE_PARAMS 的 fine，降过规格也返回 True ⇒ 现在必须跟随实际"
    )
    # 名义值不删（答辩要看"本来想跑什么档"），但 `sample_step_m` 必须描述**实际**点距：
    # 从返回的点集反推间距来对账，而不是再抄一遍 `_budget_stage_points` 的公式 ——
    # 抄公式的判据只会自证（测的是测试自己），数不同经度个数测的才是真产出的几何。
    distinct_lng = {p["lng"] for p in iso["sampling"]["points"]}
    implied_step = 2 * 2500.0 / (len(distinct_lng) - 1)
    assert abs(implied_step - spec["sample_step_m"]) < 1.0, (
        f"spec 报的间距 {spec['sample_step_m']}m 与点集实际间距 {implied_step:.1f}m 不符"
        f"（名义 coarse_m={spec['coarse_m']}）"
    )
    assert spec["profile"] == "standard" and spec["coarse_m"] == 400.0
    assert spec["grid_n"] == MODE_PARAMS["standard"]["grid_n"]
    assert iso["sample_count"] == len(iso["sampling"]["points"])


def test_interpolation_grid_is_currently_finer_than_the_sampling_it_interpolates():
    """**现状记录**：格距 ≈77m 的 IDW 在填间距 ≈250m 的点云 —— 阶段 0 只让它可观测，没让它自洽。

    这正是「最内圈网格坍缩」同族根因的另一面：点被预算压过，插值格却按名义档选，
    图上看着一样精、实际更假。配对的 `xfail(strict)` 用例钉的是应有不变量；D5 落地时
    **两条一起动**（本用例转红、那条转正），谁先单独被删都会把这件事重新藏起来。
    """
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(
        CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=375))
    spec = iso["sampling"]["spec"]
    assert spec["grid_step_m"] * 2 < spec["sample_step_m"], (
        f"插值格距 {spec['grid_step_m']}m 已经不细于采样间距 {spec['sample_step_m']}m ⇒ "
        f"D5 已落地，请把本现状记录转红并重指到应有判据上"
    )
    assert spec["grid_n"] == MODE_PARAMS["standard"]["grid_n"], (
        "格点数已被联动下调 ⇒ 不再是「名义档 grid_n 不动」的现状，重指判据"
    )


@pytest.mark.xfail(
    strict=True,
    reason="计划 v4 D5（阶段 3）：预算不足时降的应是**规格**。阶段 0 只交付了可观测性"
           "（sampling.spec），插值格仍按名义 grid_n 选；正常双阶段路径同样不满足该不变量"
           "（格 ≈77m vs 边界带 150m），故解在「规格→点数→预算」反向导出，不是调粗格子",
)
def test_sampling_must_not_interpolate_finer_than_it_measured():
    """应有不变量：`grid_step_m ≥ sample_step_m` —— IDW 不得造没测过的细节。

    两条路径都得满足：预算受限（375）与正常双阶段（None）。只测降规格那条会让"健康路径"
    继续凭空造细节而无人知晓。
    """
    engine = IsochroneEngine()
    for max_points in (375, None):
        iso = asyncio.run(engine.compute(
            CENTER, _radial_meter, study_radius_m=2500, mode="standard", max_points=max_points))
        spec = iso["sampling"]["spec"]
        assert spec["grid_step_m"] >= spec["sample_step_m"], (
            f"max_points={max_points}：格距 {spec['grid_step_m']}m 细于采样间距 "
            f"{spec['sample_step_m']}m（degraded={spec['degraded']}）"
        )
