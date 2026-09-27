"""证据域「三层同源」测试（计划 v4 阶段 1/2a · T3 前置红测试）。

事实源 `EvidenceRegion`（每类一组圆盘 `{anchor, exhausted_radius}`）派生两个视图：
`to_mask()` 喂判盲、`to_ring()` 喂出图。**两者必须同源**，否则「取证面 vs 判盲面」
又退回各说各话 —— 那正是本次改造的靶子。

实现未落地 ⇒ 逐条 skipif（不整文件 skip：本文件的守卫粒度足够细，将来落地时
只有真未实现的用例继续 skip，不会连坐）。先例见 `test_quota.py:1-9`、
`test_poi_collector.py:8`（两者都是「先测试后落地」的 TDD 红测试）。

回溯：A1 合并算子可判别 / A2 新模型=旧模型一般化 / A3 穷尽深度恰=判定半径 /
A5 三态分账闭合 / A7 掩码与多边形同源。
"""
import math

import pytest

from app.living_circle.blindspot import BLIND_RADIUS_M
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)

try:
    from app.living_circle.scope import EvidenceDisc, EvidenceRegion
except ImportError:  # 阶段 1 未落地
    EvidenceDisc = EvidenceRegion = None

try:
    from app.living_circle.blindspot import judge_grid
except ImportError:  # 阶段 1 未落地
    judge_grid = None

needs_region = pytest.mark.skipif(EvidenceRegion is None, reason="EvidenceRegion 待计划阶段 1 落地")
needs_grid = pytest.mark.skipif(judge_grid is None, reason="judge_grid/GridSpec 待计划阶段 1 落地")


def _scope(half_m: float = 2500.0) -> SpatialScope:
    ring = [
        xy_to_lnglat(CENTER, -half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, half_m),
        xy_to_lnglat(CENTER, -half_m, half_m),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, half_m, zone)
    scope.invariant()
    return scope


def _disc(category, x_m, y_m, exhausted_m, *, complete=True, cap_hit=False):
    return EvidenceDisc(
        category=category,
        anchor=xy_to_lnglat(CENTER, x_m, y_m),
        request_radius_m=exhausted_m + BLIND_RADIUS_M,
        exhausted_radius_m=float(exhausted_m),
        complete=complete,
        cap_hit=cap_hit,
    )


def _cell_dists(grid):
    """格心到分析中心的距离矩阵（米），用于把掩码与旧的标量判据逐格对照。"""
    return [
        [math.hypot(grid.coords[j], grid.coords[i]) for j in range(grid.n)]
        for i in range(grid.n)
    ]


# ── A2 · 新模型是旧模型的一般化（本文件最重要的一条）──────────────

@needs_region
@needs_grid
def test_single_disc_mask_equals_the_legacy_scalar_rule():
    """A2 · 单圆盘 region（锚点=分析中心）派生的可判定掩码，必须与旧的「d ≤ 边界−1km」
    标量判据**逐格相同**。

    这条等价性是「批次一零行为变更」的机器证明：新表示法一旦落地，旧口径就是它的一个
    退化特例，而不是一条需要保留的旁路分支。若哪天有人想加回标量分支，本用例会说明
    它已经是冗余的。
    """
    bound = 2000.0
    scope = _scope().with_evidence({"market": bound}, complete=False)
    grid = judge_grid(CENTER, scope, 200.0)
    region = EvidenceRegion([_disc("market", 0.0, 0.0, bound)])

    mask = region.to_mask(grid, "market", radius_m=BLIND_RADIUS_M)
    legacy_limit = bound - BLIND_RADIUS_M
    expected = [[d <= legacy_limit + 1e-9 for d in row] for row in _cell_dists(grid)]

    got = [[bool(v) for v in row] for row in mask]
    assert got == expected, (
        f"单圆盘掩码与标量判据不一致：不一致格数 {sum(a != b for ra, rb in zip(got, expected) for a, b in zip(ra, rb))}"
        " ⇒ 表示法升级改变了判定，批次一的「零行为变更」前提破了"
    )
    assert any(any(row) for row in got), "前置不成立：一个可判定格都没有，本用例将空过"


# ── A1 · 合并算子必须可判别（今天 min→max→union 无人能测出来）──────

@needs_region
@needs_grid
def test_two_far_apart_discs_are_a_union_not_a_scalar_min():
    """A1 · 两个互不覆盖的远端圆盘 ⇒ 可判定面必须是**并集**。

    旧表示法只有一个标量：`scope.py:220` 取登记类的 `min()`，且这个 min 此前**没有任何
    一条测试钉住**（改成 max 或并集都不会红，见 `test_report_invariants.py` 的
    `test_assemble_evidence_merge_is_min_not_max_nor_union`）。本用例钉的是新语义：
    并集面积严格大于「把两个圆盘塌回一个以中心为圆心的标量」所能判定的面积。
    """
    grid = judge_grid(CENTER, _scope(), 200.0)
    r = 1600.0
    union = EvidenceRegion([_disc("market", -1900.0, 0.0, r), _disc("market", 1900.0, 0.0, r)])
    collapsed = EvidenceRegion([_disc("market", 0.0, 0.0, r)])

    u_cells = int(union.to_mask(grid, "market").sum())
    c_cells = int(collapsed.to_mask(grid, "market").sum())
    assert u_cells > c_cells, (
        f"两远端圆盘并集判出 {u_cells} 格，与塌回中心的 {c_cells} 格相同 ⇒ "
        "并集被偷偷塌成了标量（第二事实源回来了）"
    )


# ── A3 · 穷尽深度恰等于判定半径 ⇒ 可判定面为空，且不得伪装成「没查」──

@needs_region
@needs_grid
def test_exhaustion_equal_to_judge_radius_yields_no_conclusive_cell():
    """A3 · `exhausted_radius == BLIND_RADIUS_M` 时可判定半径恰为 0 ⇒ 一格都判不了。

    边界取自「证据刚好只铺满判定圆」这一临界：此时该锚点对「这格 1km 圆内有没有 X」
    仍然无法下结论（判定圆需要**完整落在**证据域内）。
    """
    grid = judge_grid(CENTER, _scope(), 200.0)
    just_enough = EvidenceRegion([_disc("market", 0.0, 0.0, BLIND_RADIUS_M)])
    one_step_more = EvidenceRegion([_disc("market", 0.0, 0.0, BLIND_RADIUS_M + 200.0)])

    assert int(just_enough.to_mask(grid, "market").sum()) == 0, (
        "穷尽深度只到判定半径就判得出格 ⇒ 把「刚查完中心」当成了「查全了 1km 圆」"
    )
    assert int(one_step_more.to_mask(grid, "market").sum()) > 0, (
        "外扩 200m 仍判不出任何格 ⇒ 可判定半径的公式没接上"
    )


@needs_region
def test_cap_hit_short_disc_carries_its_attribution():
    """A3b · 被 60 条封顶卡死的锚点必须自带归因字段（`cap_hit`），第三态才有原料。

    「接口能力封顶」与「我们没查」在报告里必须是两个数（D1③）。本用例只钉 region 侧
    携带了这个区分位；分账闭合本身在 A5 与 `test_degrade_chain.py` 的 C3 对上。
    """
    capped = EvidenceRegion([_disc("pharmacy", 0.0, 0.0, 700.0, complete=False, cap_hit=True)])
    never_run = EvidenceRegion([_disc("pharmacy", 0.0, 0.0, 0.0, complete=False, cap_hit=False)])

    assert [d.cap_hit for d in capped.discs] == [True], "封顶事实没随圆盘带出来"
    assert [d.cap_hit for d in never_run.discs] == [False]
    assert all(d.exhausted_radius_m < BLIND_RADIUS_M for d in capped.discs), (
        "封顶样本的穷尽深度不低于判定半径 ⇒ 样本造错了，它本该落进可判态"
    )


# ── A5 · 三态分账闭合 ────────────────────────────────────────────

@needs_region
def test_three_state_cells_accounting_closes_on_the_reach_grid():
    """A5 · `inside = judged + unknown + unjudgeable_by_cap`，三态互斥不重不漏。"""
    from app.living_circle.blindspot import find_blindspots_with_stats

    scope = _scope().with_evidence({"market": 700.0, "pharmacy": 700.0, "primary": 700.0}, complete=False)
    _spots, stats = find_blindspots_with_stats(CENTER, scope, {"market": [], "pharmacy": [], "primary": []}, prefix="a5")
    assert stats["cells_inside"] == (
        stats["cells_judged"] + stats["cells_unknown"] + stats["cells_unjudgeable_by_cap"]
    ), f"三态分账不闭合：{stats}"
    assert stats["cells_unjudgeable_by_cap"] > 0, "证据边界 700m < 判定半径，却一格都没归到封顶态"


# ── A7 · 判定视图与呈现视图同源 ──────────────────────────────────

@needs_region
@needs_grid
def test_rendered_area_and_judging_mask_agree():
    """A7 · `to_ring()`/`area_km2()`（画给人看）与 `to_mask()`（喂判盲）必须同源同量。

    两个视图各算各的是本仓反复出事的形状（文案一个数、图上一个数）。判据取
    「掩码折算面积 ≈ 环面积」，容差按一个格距的边界带估（marching-squares 离散化误差）。
    """
    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)
    region = EvidenceRegion([_disc("market", -800.0, 600.0, 1800.0), _disc("market", 900.0, -700.0, 1500.0)])

    cells = int(region.to_mask(grid, "market").sum())
    mask_km2 = cells * grid.step * grid.step / 1e6
    ring_km2 = region.area_km2("market", scope.reach_ring)
    # 边界带宽度取一个格距：环是连续轮廓、掩码是格心判定，二者只可能在边界带上分歧
    band_km2 = (2 * math.pi * 1500.0 * grid.step) / 1e6
    assert abs(mask_km2 - ring_km2) <= band_km2 * 1.5, (
        f"掩码折算 {mask_km2:.3f}km² vs 图上 {ring_km2:.3f}km²（容差 {band_km2 * 1.5:.3f}）"
        " ⇒ 出图与判定已分叉，两份事实源回来了"
    )
    assert cells > 0, "前置不成立：掩码一格未判，本用例将空过"


# ── property-based 变体（hypothesis 为可选 dev 依赖，未装即 skip 本条）──

@needs_region
@needs_grid
def test_prop_single_disc_equivalence_holds_for_any_radius():
    """A2p · 对任意（合法）单圆盘半径，退化等价都成立。"""
    from hypothesis import given, strategies as st

    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)

    @given(bound=st.floats(min_value=BLIND_RADIUS_M + 1.0, max_value=4000.0, allow_nan=False))
    def _check(bound):
        region = EvidenceRegion([_disc("market", 0.0, 0.0, bound)])
        got = [[bool(v) for v in row] for row in region.to_mask(grid, "market")]
        want = [[d <= bound - BLIND_RADIUS_M + 1e-9 for d in row] for row in _cell_dists(grid)]
        assert got == want

    _check()


@needs_region
@needs_grid
def test_prop_mask_is_monotone_in_exhausted_radius():
    """A2m · 证据越全 ⇒ 可判定面只会变大（单调性，任何圆盘组合下都必须成立）。"""
    from hypothesis import given, strategies as st

    grid = judge_grid(CENTER, _scope(), 200.0)

    @given(
        r1=st.floats(min_value=BLIND_RADIUS_M, max_value=3500.0, allow_nan=False),
        grow=st.floats(min_value=0.0, max_value=500.0, allow_nan=False),
        x=st.floats(min_value=-2000.0, max_value=2000.0, allow_nan=False),
    )
    def _check(r1, grow, x):
        base = EvidenceRegion([_disc("market", x, 0.0, r1)])
        grown = EvidenceRegion([_disc("market", x, 0.0, r1 + grow)])
        assert int(base.to_mask(grid, "market").sum()) <= int(grown.to_mask(grid, "market").sum())

    _check()


def test_anchor_distance_uses_metres_not_degrees():
    """A0 · 桩件自检：`xy_to_lnglat`/`haversine_m` 往返一致，否则上面全部判据都在空转。

    本仓最贵的一类缺陷是「判据没有样本」；这条是判据的样本哨兵，不是被测功能。
    """
    for x, y in ((0.0, 0.0), (500.0, -1200.0), (2400.0, 2400.0)):
        lng, lat = xy_to_lnglat(CENTER, x, y)
        d = haversine_m(CENTER, (lng, lat))
        assert abs(d - math.hypot(x, y)) < 5.0, f"米坐标往返漂移 {d - math.hypot(x, y):.1f}m"
