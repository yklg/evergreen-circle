"""T1 · 口径不变量守护（test-coverage-expander 批次 1，回溯 I1/I10）。

守护的是「15 分钟是什么」这件事**只有一个事实源**，以及「画出来的圈确实是那个口径」。
不测几何细节（那是 test_isochrone.py 的职责），只测跨模块的口径一致性。

两条已知 P0 以 xfail(strict=True) 挂账：修好后用例会变 XPASS→失败，强制摘掉标记，
不允许静默转绿。
"""
from __future__ import annotations

import inspect
import json
import math
import re
import statistics
from pathlib import Path

import pytest

from app.living_circle import data_source, isochrone, scoring
from app.living_circle.caliber import get_caliber
from app.living_circle.data_source import CheckParams, OfflineDataSource
from app.living_circle.geo_utils import haversine_m
from app.living_circle.isochrone import ISO_MINUTES, MODE_PARAMS, build_sample_points
from app.living_circle.isochrone import hour_to_minutes

WALK_CALIBER = get_caliber("walking")
OFFLINE_DETOUR_K = WALK_CALIBER.detour_k
WALK_SPEED_M_PER_MIN = WALK_CALIBER.speed_m_per_min
REACH_FULL_MIN = WALK_CALIBER.reach_full_min

FIXTURES = Path(isochrone.__file__).parent / "fixtures"
KAILI = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
JINSONG = json.loads((FIXTURES / "beijing-jinsong.json").read_text(encoding="utf-8"))

# 政策口径：商务部 2021《城市一刻钟便民生活圈建设意见》「步行约 15 分钟的服务半径」，
# 《城市规划》2022.5 实测步行 15min ≈ 0.8–1.2km。
POLICY_WALK_15MIN_M = (800.0, 1200.0)


def _offline_report(center=(107.9758, 26.5734), name="凯里老街"):
    import asyncio

    ds = OfflineDataSource()
    return asyncio.run(ds.compute(CheckParams(scene_name=name, city="", address="", center=center)))


def _ring(report, minutes):
    z = next(z for z in report["isochrones"] if z["minutes"] == minutes)
    return z["geojson"]["coordinates"][0]


def _radial_stats(report, minutes):
    """圈相对自身中心的 (平均半径, 变异系数 CV, 顶点数, 面积)。

    CV = 半径标准差/均值：正圆 CV=0，真实路网等时圈必然 CV>0 —— 「不是画的圆」的量化判据。
    """
    c = tuple(report["scene"]["center"])
    radii = [haversine_m(c, (p[0], p[1])) for p in _ring(report, minutes)]
    mean = statistics.fmean(radii)
    return {
        "r_mean": mean,
        "cv": statistics.pstdev(radii) / mean,
        "vertices": len(radii),
        "area": next(z for z in report["isochrones"] if z["minutes"] == minutes)["area_km2"],
    }


# ── I1 · 速度口径单一源 ────────────────────────────────────────────

def test_speed_constant_derived_from_single_source():
    """口径常量只允许在 caliber.py 定义一次（B5：禁止散落第二份字面量）。"""
    from app.living_circle.caliber import DEFAULT_CALIBERS
    walking = DEFAULT_CALIBERS["walking"]
    assert walking.speed_m_per_min == 80


def test_caliber_constants_are_the_same_object_across_modules():
    """引用而非复制：`is` 断言，防「data_source 里再写一个 75.0」的口径漂移。"""
    assert data_source.get_caliber("walking") is isochrone.get_caliber("walking")
    assert inspect.signature(hour_to_minutes).parameters["speed"].default == WALK_SPEED_M_PER_MIN


def test_scoring_reach_threshold_is_tied_to_outermost_iso_ring():
    """可达性满分阈值必须等于最外圈分钟数（否则「满分」与圈层族口径脱钩）。"""
    assert scoring.REACH_FULL_MIN == ISO_MINUTES[-1]


def test_offline_note_text_matches_code_constants():
    """scores.note 是对外举证文本：必须与代码常量逐字相同，不得手写数字。"""
    note = _offline_report()["scores"]["note"]
    assert f"{WALK_SPEED_M_PER_MIN} m/min" in note
    assert f"绕行系数 {OFFLINE_DETOUR_K}" in note


# ── I1 · 离线口径反算落政策区间 ────────────────────────────────────

def test_offline_15min_radius_lands_in_policy_band():
    """速度 × 15min ÷ 绕行系数 = 直线服务半径，须落 0.8–1.2km（政策 + 文献量级）。"""
    r = ISO_MINUTES[2] * WALK_SPEED_M_PER_MIN / OFFLINE_DETOUR_K
    assert POLICY_WALK_15MIN_M[0] <= r <= POLICY_WALK_15MIN_M[1], f"15min 直线半径 {r:.0f}m 出政策口径"


def test_offline_rendered_15min_ring_matches_declared_model():
    """渲染出的 15min 圈平均半径必须≈口径反算值（文本说的和图上画的同源）。"""
    report = _offline_report()
    declared = ISO_MINUTES[2] * WALK_SPEED_M_PER_MIN / OFFLINE_DETOUR_K
    got = _radial_stats(report, 15)["r_mean"]
    assert abs(got - declared) / declared < 0.05, f"图上 {got:.0f}m vs 口径 {declared:.0f}m"


# ── I10 · 圈层真实性（正圆判据 / 跨城独立性）────────────────────────

@pytest.mark.parametrize("report", [KAILI, JINSONG], ids=["kaili", "jinsong"])
def test_live_rings_are_not_perfect_circles(report):
    """真实路网等时圈必须不规则：CV>0（正圆 = 算法退化为画圆）。"""
    for m in ISO_MINUTES:
        assert _radial_stats(report, m)["cv"] > 0.01, f"{m}min 圈 CV 过小，疑似正圆兜底"


@pytest.mark.parametrize("minutes", [10, 15, 20])
def test_live_rings_differ_between_cities(minutes):
    """两城同分钟圈应显著不同（路网结构不同）；10/15/20min 圈成立。"""
    a = _radial_stats(KAILI, minutes)
    b = _radial_stats(JINSONG, minutes)
    assert abs(a["r_mean"] - b["r_mean"]) / a["r_mean"] > 0.01
    assert abs(a["area"] - b["area"]) / a["area"] > 0.01


def test_innermost_live_ring_is_city_dependent():
    """不变量（原挂账项转正）：5min 圈形状必须由路网决定 → 两城不可能一致。

    历史：本用例曾以 `xfail(strict=True)` 挂账，因为旧快照里两城 5min 圈**逐点同形**
    （面积完全相同、r_mean 相对差 <1e-4、顶点数一致）——那是 B8「最内圈采样点坍缩」
    的症状。2026-09-20 以真实 AK 重跑 `scripts/snapshot_live.py` 后症状消失
    （新快照为 standard 档，5min 圈 r_mean 126.2m vs 107.2m，相对差 15%，面积差 25%），
    故摘掉 xfail 标记，改为硬不变量。

    ⚠️ B8 本体（`fine_band` 未透传 ⇒ 格距 > 最内圈半径/4）**仍未修复**，
    由 `test_grid_resolution_invariant_is_violated_at_innermost_ring` 继续量化跟踪；
    换回粗采样档（quick）时本不变量仍可能被打破 —— 这正是需要盯住的地方。
    """
    a = _radial_stats(KAILI, 5)
    b = _radial_stats(JINSONG, 5)
    assert abs(a["r_mean"] - b["r_mean"]) / a["r_mean"] > 0.01


def test_grid_resolution_invariant_is_violated_at_innermost_ring():
    """**记录当前行为** + 量化 B8 判据：格距与最内圈半径的比值。

    期望 `step ≤ 最内圈半径/4`；实际 356.7m vs 138.6m → 比值 0.23（最内圈内仅 1 个采样点），
    等值线只能由插值格（83.3m）凭空生成 —— 这就是两城 5min 圈同形的根因。
    """
    center = tuple(KAILI["scene"]["center"])
    inner_r = _radial_stats(KAILI, 5)["r_mean"]
    step = min(
        d for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, MODE_PARAMS["standard"]["coarse"], MODE_PARAMS["standard"]["fine"])) if d > 1.0
    )
    inside = sum(1 for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, 400, 150)) if d <= inner_r)
    assert inside == 1  # 仅中心点
    assert step > inner_r / 4  # 违反分辨率不变量（期望 <，见上方 xfail 用例）


@pytest.mark.xfail(strict=True, reason="P0（B8）：分辨率不变量未落地，caliber.py 落地后改为断言成立")
def test_grid_resolution_invariant_should_hold():
    TODO = "见 plan/graceful-fjord-swan.md R8/B8：格距须 ≤ 最内圈半径/4"
    center = tuple(KAILI["scene"]["center"])
    inner_r = _radial_stats(KAILI, 5)["r_mean"]
    step = min(
        d for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, 400, 150)) if d > 1.0
    )
    assert step <= inner_r / 4, TODO


# ── 死参数：IsochroneEngine(walk_speed=…) 不参与任何计算 ───────────

def test_injected_walk_speed_is_currently_inert():
    """**记录当前行为**：构造参数存到了 self.walk_speed，但 compute 全程不读它。

    口径来自调用方注入的 meter_fn，所以引擎层「配了但不用」= 假的可配置性。
    阶段 1 R5/R7 落地后本用例应转红（改为断言注入生效）。
    """
    import asyncio

    async def radial(pts):
        return [haversine_m((107.9758, 26.5734), p) / WALK_SPEED_M_PER_MIN for p in pts]

    slow = asyncio.run(isochrone.IsochroneEngine(walk_speed=15.0).compute((107.9758, 26.5734), radial, study_radius_m=2500, mode="quick"))
    fast = asyncio.run(isochrone.IsochroneEngine(walk_speed=150.0).compute((107.9758, 26.5734), radial, study_radius_m=2500, mode="quick"))
    assert [z["area_km2"] for z in slow["isochrones"]] == [z["area_km2"] for z in fast["isochrones"]]


@pytest.mark.xfail(strict=True, reason="R5/R7：walk_speed 为死参数，口径重构后须真正生效")
def test_injected_walk_speed_should_take_effect():
    import asyncio

    center = (107.9758, 26.5734)

    def radial(speed):
        async def m(pts):
            return [haversine_m(center, p) / speed for p in pts]
        return m

    slow = asyncio.run(isochrone.IsochroneEngine(walk_speed=37.5).compute(center, radial(75.0), study_radius_m=2500, mode="quick"))
    fast = asyncio.run(isochrone.IsochroneEngine(walk_speed=150.0).compute(center, radial(75.0), study_radius_m=2500, mode="quick"))
    assert slow["isochrones"][0]["area_km2"] != fast["isochrones"][0]["area_km2"]
