"""P1 笔 1 · 三要素卡的「两把尺」判据。

守一件事：`scores.triads[]` 不许再把「可达区内有没有」和「中心 1km 直线内有没有」
塌成一个布尔 —— 那正是 `diagnosis_templates.py:623` 那句「这一句判的是小学 1km 三要素
事实」（其实判的是可达区）能一路绿灯到屏上的根因，也是 `JudgeMasks` 的 ⚠️ 与
`ev-1` 整套改造在盲区侧已经消灭过一次的形状。

不测盲区判定本身（那是 test_blindspot* 的职责），只测：
  - 中心格的索引确实落在分析中心（1km 尺读的是哪一格）；
  - 三态里「无从知道」不等于「没有」；
  - `covered` 与 `in_reach` 逐例相同（兼容别名不许漂）。
"""
from __future__ import annotations

import numpy as np
import pytest

from app.living_circle.grid import grid_spec
from app.living_circle.judgement import JudgeMasks
from app.living_circle.scoring import triad_from_points

CENTER = (107.9758, 26.5734)
TRIAD_KEYS = ("market", "pharmacy", "primary")


def _masks(n: int = 5, present: int = 1, nearest_m: float = 300.0) -> JudgeMasks:
    """造一份只够测中心格读数的掩码。

    ⚠️ 中心格填**哨兵值**，其余格填另一组值 —— 整张填同一个数会让 `center_readings()`
    里的索引写错（比如把 `k` 写成 `0`）也照样通过，那条判据就成了假绿。
    """
    grid = grid_spec(CENTER, scan=400.0, grid_m=200.0)
    assert grid.n == n, "格阵边长由 grid_spec 唯一推导，这里只做前提校验"
    k = grid.n // 2
    shape = (grid.n, grid.n)

    def filled(center_val: float, other_val: float) -> np.ndarray:
        a = np.full(shape, other_val)
        a[k, k] = center_val
        return a

    return JudgeMasks(
        grid=grid,
        region=None,                                   # 本测试不碰证据区域
        step=grid.step,
        inside=np.ones(shape, dtype=bool),
        blind=np.zeros(shape, dtype=bool),
        verdict=np.ones(shape, dtype=bool),
        capped=np.zeros(shape, dtype=bool),
        judgeable={k2: np.ones(shape, dtype=bool) for k2 in TRIAD_KEYS},
        present={k2: filled(present, 99).astype(np.int8) for k2 in TRIAD_KEYS},
        nearest_m={k2: filled(nearest_m, 8888.0) for k2 in TRIAD_KEYS},
    )


def test_center_reading_lands_exactly_on_the_analysis_center():
    """奇数对称格阵 ⇒ `cell(k,k)` 就是分析中心本身，不偏半格。

    这条是 1km 尺取"中心格"的**全部**前提。它一旦不成立，三要素卡报的就是某个邻格的
    1km 结论，而卡片文案说的是"以社区为中心"。
    """
    grid = grid_spec(CENTER, scan=400.0, grid_m=200.0)
    k = grid.n // 2
    lng, lat = grid.cell(k, k)
    assert abs(lng - CENTER[0]) < 1e-9 and abs(lat - CENTER[1]) < 1e-9
    # 中心到自身格的直线距离必须是 0（`distance_field` 与 `center_readings` 共用同一几何）
    assert grid.distance_field()[k, k] == pytest.approx(0.0, abs=1e-6)


def test_center_readings_cover_every_required_category():
    readings = _masks().center_readings()
    assert set(readings) == set(TRIAD_KEYS)
    assert readings["pharmacy"] == (1, 300.0)


# ── 两把尺的合取：field_fn 是可达尺，blind_center 是 1km 直线尺 ──────────────

def _point(name: str, lng: float = 107.9858, lat: float = 26.5734) -> dict:
    """直线约 950m（正东）的一家店 —— 正落在 1km 判盲尺与可达尺的交界带上。"""
    return {"lng": lng, "lat": lat, "name": name}


def _run(field_fn, blind_center, pharmacy=(), market=(), primary=()):
    return {t["facility"]: t for t in triad_from_points(
        list(market), list(pharmacy), list(primary), field_fn, blind_center)}


def test_river_case_reports_present_within_1km_but_unreachable():
    """隔河：直线 950m 有药店，步行 20min 内到不了 ⇒ 三态必须同时说清这两件事。

    这是修复前会印成「药店三要素 1km 内缺失」的那一格 —— 一句假话。
    """
    got = _run(
        field_fn=lambda _pt: None,                     # 可达尺：环外/超阈值 ⇒ 封顶成 None
        blind_center={"pharmacy": (1, 950.0)},         # 1km 尺：有据且命中
        pharmacy=[_point("吉大夫健康药房")],
    )["药店"]
    assert got["in_reach"] is False
    assert got["within_blind_radius"] is True
    assert got["nearest_m"] == 950.0
    assert got["blocked_by_geometry"] is True          # ← 赛题要的"道路并非直线"的证据
    assert got["covered"] is False                     # 兼容别名仍等于 in_reach


def test_no_block_when_the_facility_is_walkable():
    """可达区内有 ⇒ 即使 1km 内也有，`blocked_by_geometry` 必须是 False 而不是 None。"""
    got = _run(
        field_fn=lambda _pt: 12.5,
        blind_center={"pharmacy": (1, 950.0)},
        pharmacy=[_point("可达药房")],
    )["药店"]
    assert got["in_reach"] is True and got["nearest_minutes"] == 12.5
    assert got["within_blind_radius"] is True
    assert got["blocked_by_geometry"] is False


def test_absent_with_evidence_is_a_real_negative():
    got = _run(field_fn=lambda _pt: None,
               blind_center={"pharmacy": (0, -1.0)},
               pharmacy=[])["药店"]
    assert got["in_reach"] is False
    assert got["within_blind_radius"] is False
    assert got["nearest_m"] is None             # -1 = 无从知道，不是 0 米
    assert got["blocked_by_geometry"] is False


def test_unsearched_is_unknown_and_never_false():
    """中心格「无从下结论」(present=-1) ⇒ 三态落 None。

    塌成 False 就等于把"我们没查全"洗成"1km 内确实没有" —— `baidu_client.py:36-44`
    为 `page_size` 静默降级写过同一条理由，`JudgeMasks` 的 ⚠️ 为 int8 三态也写过。
    """
    got = _run(field_fn=lambda _pt: None,
               blind_center={"pharmacy": (-1, -1.0)},
               pharmacy=[_point("河对岸药房")])["药店"]
    assert got["within_blind_radius"] is None
    assert got["blocked_by_geometry"] is None
    assert got["nearest_m"] is None
    # 未知不许传染可达尺：in_reach 仍是有据的 False
    assert got["in_reach"] is False


def test_missing_category_key_is_unknown_not_a_crash():
    """`present` 里没有这一类 ⇒ 读作无从知道，不抛、也不默认成"没有"。"""
    got = _run(field_fn=lambda _pt: None, blind_center={}, pharmacy=[_point("x")])["药店"]
    assert got["within_blind_radius"] is None and got["blocked_by_geometry"] is None


@pytest.mark.parametrize("present,nearest_m,in_reach_min", [
    (1, 400.0, 9.0), (1, 950.0, None), (0, -1.0, None), (-1, -1.0, 7.0),
])
def test_covered_is_always_the_in_reach_alias(present, nearest_m, in_reach_min):
    """兼容别名漂了就等于旧消费者各读各的 —— 逐例钉住 `covered is in_reach`。"""
    got = _run(
        field_fn=lambda _pt: in_reach_min,
        blind_center={"primary": (present, nearest_m)},
        primary=[_point("凯里市第十三小学")],
    )["小学"]
    assert got["covered"] is got["in_reach"]
