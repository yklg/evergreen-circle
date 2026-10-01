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
import dataclasses
import math

import pytest

from app.living_circle.blindspot import BLIND_RADIUS_M
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat
from app.living_circle.scope import SpatialScope, TRIAD_KEYS

CENTER = (107.9758, 26.5734)

# 停止原因是**采集侧契约**的词汇，取处按契约归属放在 baidu_client（与 test_poi_collector
# 文件头那条主张一致）：T-P0-4 之后盘上的完整性由它派生，测试要造形状就得能直接点名它。
from app.living_circle.baidu_client import (
    STOP_API_ERROR,
    STOP_COMPLETE,
    STOP_DUP_STOP,
    STOP_EMPTY,
    STOP_NOT_RUN,
    STOP_PAGE_CAP,
    STOP_SERVER_CAP,
    is_exhausted,
)

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


def _disc(category, x_m, y_m, exhausted_m, *, complete=True, cap_hit=False, request_m=None,
          stop_reason=None):
    """造一个圆盘。`request_m` 缺省 = 穷尽深度。

    最初的写法是 `request = exhausted + BLIND_RADIUS_M` + `complete=True`，那是自相矛盾：
    「查全」的定义就是**穷尽深度等于请求半径**（`poi_collector.TermEvidence.frontier_m`
    的语义），把请求半径凭空放大 1km 再说「查全」，`EvidenceDisc.invariant` 必须拦。
    要造「请求了但没查全」的形状，传 `complete=False`（A3b 就是这么造的）。

    T-P0-4（计划 v5.6）之后 `complete`/`cap_hit` 在盘上是 `stop_reason` 的**派生量**、
    不再是可填字段，所以本工厂把这两个测试意图翻成原因（翻译规则唯一，且只在这里）：
    `stop_reason` 显式给定 ⇒ 原样用它；否则 `cap_hit`⇒服务端封顶、`complete`⇒查全、
    两者皆 False⇒「我们翻到页上限就停了」。要造**合成盘**（无原因、按定义不自称查全）
    传 `stop_reason=None` 之外再显式写 `stop_reason=STOP_NOT_RUN` 或直接构造 `EvidenceDisc`。
    """
    reason = stop_reason
    if reason is None:
        reason = STOP_SERVER_CAP if cap_hit else (STOP_COMPLETE if complete else STOP_PAGE_CAP)
    return EvidenceDisc(
        category=category,
        anchor=xy_to_lnglat(CENTER, x_m, y_m),
        request_radius_m=float(exhausted_m if request_m is None else request_m),
        exhausted_radius_m=float(exhausted_m),
        stop_reason=reason,
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


# ── A3 · 穷尽深度恰等于判定半径 ⇒ 可判定面缩到只剩锚点格 ──────────────

@needs_region
@needs_grid
def test_exhaustion_equal_to_judge_radius_leaves_only_the_anchor_cell():
    """A3 · `exhausted_radius == BLIND_RADIUS_M` 时可判定半径恰为 0 ⇒ 只剩锚点自己那一格。

    本用例原先断的是「一格都判不了」，那与 A2 相矛盾：A2 钉住「新掩码与旧标量判据**逐格
    相同**」，而旧判据是 `d ≤ 边界 − 1km`（含等号，因为 `_has_within` 的命中判定也取 ≤ 1km）。
    边界恰为 1000m 时锚点格 d=0 正落在含等号那一侧 ⇒ 它**是**有结论的：一次穷尽到 1000m 的
    检索确实完整覆盖了锚点周围那个 1km 判定圆。要判「0 格」就得把命中改成严格小于，那才是
    把 A2 的零回归证明拆掉。故此处改判「只剩 1 格、且恰是锚点格」+「可判定半径为 0」，
    比原来的条数断言更严（多判一格、或那一格不在锚点上，都会红）。
    """
    grid = judge_grid(CENTER, _scope(), 200.0)
    just_enough = EvidenceRegion([_disc("market", 0.0, 0.0, BLIND_RADIUS_M)])
    one_step_more = EvidenceRegion([_disc("market", 0.0, 0.0, BLIND_RADIUS_M + 200.0)])

    assert just_enough.discs[0].judge_radius_m(BLIND_RADIUS_M) == 0.0, (
        "穷尽深度恰等于判定半径时可判定半径不为 0 ⇒ 那条半径关系被改了"
    )
    mask = just_enough.to_mask(grid, "market")
    assert int(mask.sum()) == 1, (
        f"可判定半径为 0 却判出 {int(mask.sum())} 格 ⇒ 判定圆未被完整覆盖的格漏进了可判态"
    )
    hit = [(i, j) for i in range(grid.n) for j in range(grid.n) if mask[i, j]][0]
    assert abs(float(grid.coords[hit[0]])) < 1e-6 and abs(float(grid.coords[hit[1]])) < 1e-6, (
        f"唯一可判格 {hit} 不是锚点所在格 ⇒ 圆盘圆心与坐标原点接错了"
    )
    assert int(one_step_more.to_mask(grid, "market").sum()) > 1, (
        "外扩 200m 仍判不出更多格 ⇒ 可判定半径的公式没接上"
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
    """A5 · `inside = judged + unknown + unjudgeable_by_cap`，三态互斥不重不漏。

    第三态的原料是圆盘自带的 `cap_hit`（接口封顶），所以本用例**必须**走 region 路径 ——
    原先用标量 `frontier` 造，退化圆盘的 cap_hit 恒为 False（封顶事实只能来自采集侧，
    `degenerate_evidence_region` 不许凭空写 True），第三态于是永远数不出来。
    """
    from app.living_circle.blindspot import find_blindspots_with_stats

    capped = EvidenceRegion([
        _disc(cat, 0.0, 0.0, 700.0, complete=False, cap_hit=True)
        for cat in ("market", "pharmacy", "primary")
    ])
    scope = _scope().with_evidence(complete=False, region=capped)
    _spots, stats = find_blindspots_with_stats(
        CENTER, scope, {"market": [], "pharmacy": [], "primary": []}, prefix="a5")
    assert stats["cells_inside"] == (
        stats["cells_judged"] + stats["cells_unknown"] + stats["cells_unjudgeable_by_cap"]
    ), f"三态分账不闭合：{stats}"
    assert stats["cells_unjudgeable_by_cap"] > 0, "证据边界 700m < 判定半径，却一格都没归到封顶态"
    # 三类全封顶 ⇒ 判得出的只剩锚点格（穷尽深度 700m 的可判定半径为 0），其余全归封顶
    assert stats["cells_unknown"] == 0, (
        f"三类皆封顶却仍有 unknown：{stats} ⇒ 第三态没吃到 cap_hit，仍把它算成我们的失职"
    )
    assert stats["cells_judged"] == 1, f"判得出结论的应只有锚点那一格：{stats}"


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
    # 本节标题承诺「未装即 skip」，之前只写了裸 `import` ⇒ 解释器没装 hypothesis 时是
    # ModuleNotFoundError（红），不是 skip。`importorskip` 才是那句承诺的实现。
    hypothesis = pytest.importorskip("hypothesis")
    given, st = hypothesis.given, hypothesis.strategies

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
    hypothesis = pytest.importorskip("hypothesis")
    given, st = hypothesis.given, hypothesis.strategies

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


def test_anchor_lattice_respects_both_spacing_bounds():
    """A6 · 锚点间距必须同时守上界（覆盖够）与下界（不白烧预算）。

    上界 `s ≤ √2·(穷尽深度 − 判定半径)` 由「方格点阵覆盖半径 = s/√2」导出；
    下界 `s ≥ grid.step` 是「取证精度不得超过判定精度」。计划原文的
    `m = ceil(cap_step/step)` 会把 stride 抬到上界之外 ⇒ 留下覆盖空洞，
    本用例钉的就是这个方向（换成 ceil 立刻红）。
    """
    from app.living_circle.anchors import LatticeAnchors

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    exhausted = 1973.0                       # 北京劲松 market 的实测边界
    cap = lat.cap_step_m(exhausted)
    assert cap == pytest.approx(math.sqrt(2.0) * (exhausted - BLIND_RADIUS_M))

    stride = lat.stride_for(grid, cap)
    assert stride * grid.step <= cap + 1e-9, (
        f"stride={stride} 排出的间距 {stride * grid.step:.0f}m 超过上界 {cap:.0f}m ⇒ 取整方向"
        "写反了，外沿会留下覆盖不到又无人标注的格"
    )
    assert stride * grid.step >= grid.step - 1e-9
    assert (stride + 1) * grid.step > cap, "stride 没取到「不超过上界的最大值」，锚点排得太疏"

    # 上界比一格还密时退回 stride=1：此时证据不足必须如实落进第三态，而不是加密锚点装覆盖
    assert lat.stride_for(grid, grid.step / 3.0) == 1

    anchors = lat.anchors(grid, cap)
    # 锚点是经纬度、格心是局部米 —— 不同源的坐标系直接相减会得到「度」当「米」的垃圾数。
    # 这条同时也是 A0 哨兵守的那类缺陷在这里的具体形状（覆盖半径会算出 5km 这种荒谬值）。
    from app.living_circle.geo_utils import to_local_xy

    anch_xy = [to_local_xy(CENTER, a[0], a[1]) for a in anchors]
    farthest = 0.0
    for i in range(grid.n):
        for j in range(grid.n):
            x, y = float(grid.coords[j]), float(grid.coords[i])
            d = min(math.hypot(x - ax, y - ay) for ax, ay in anch_xy)
            farthest = max(farthest, d)
    assert farthest <= cap + 1e-6, (
        f"点阵覆盖半径实测 {farthest:.0f}m 超过上界 {cap:.0f}m ⇒ 有格永远判不了却无人认领"
    )
    assert len(anch_xy) == len(anchors) > 1

    # 相位必须取在中心格上。造一个「stride 大到每轴只剩一格」的档 —— 数值从**这张格阵自己**
    # 导出而不是写死（换格距还成立，也不会像我第一版那样对 n=37 直接空过）：
    # 要 m > n//2 ⇒ cap = (n//2 + 1)·step ⇒ 穷尽深度 = 判定半径 + cap/√2。
    # 此时若从 (0,0) 起排，那个唯一的锚点会落在角上 ⇒ 换新锚点的读数反而比现状差，
    # 而变差与取证强度毫无关系。
    if grid.n % 2 == 1:
        mid = grid.n // 2
        cap_lone = (mid + 1.01) * grid.step
        exhausted_lone = BLIND_RADIUS_M + cap_lone / math.sqrt(2.0)
        assert lat.stride_for(grid, cap_lone) == mid + 1, "前置不成立：没压到每轴一格，本用例会空过"
        lone = lat.anchors(grid, lat.cap_step_m(exhausted_lone))
        assert len(lone) == 1, f"这一档应每轴只剩一个锚点，实际 {len(lone)} 个 ⇒ 前置不成立"
        assert lone[0] == grid.cell(mid, mid), (
            f"单锚点档必须锚在分析中心，实际给出 {lone[0]}"
        )


def test_anchor_distance_uses_metres_not_degrees():
    """A0 · 桩件自检：`xy_to_lnglat`/`haversine_m` 往返一致，否则上面全部判据都在空转。

    本仓最贵的一类缺陷是「判据没有样本」；这条是判据的样本哨兵，不是被测功能。
    """
    for x, y in ((0.0, 0.0), (500.0, -1200.0), (2400.0, 2400.0)):
        lng, lat = xy_to_lnglat(CENTER, x, y)
        d = haversine_m(CENTER, (lng, lat))
        assert abs(d - math.hypot(x, y)) < 5.0, f"米坐标往返漂移 {d - math.hypot(x, y):.1f}m"


def _mk_disc(reason, request_m=2000.0, exhausted_m=2000.0):
    return EvidenceDisc(
        category="pharmacy", anchor=xy_to_lnglat(CENTER, 0.0, 0.0),
        request_radius_m=float(request_m), exhausted_radius_m=float(exhausted_m),
        stop_reason=reason,
    )


@needs_region
def test_disc_completeness_is_derived_and_cannot_be_filled_in():
    """T-P0-4（计划 v5.6）：盘上的完整性是**派生量**，不再是能被单独填写的字段。

    守两件不同的事，任何一件失守都算回归：
    1. **填不进去** —— `EvidenceDisc(..., complete=True)` 必须 `TypeError`。若能接受，
       「声称查全」就又能脱离证据存在（`cap_hit` 当年正是这样被收掉的，同一形状）。
    2. **合成盘不自称查全** —— `stop_reason=None`（从报告里存的标量边界反推出来的盘）
       一律 `complete=False`：「报告存了这个数」不等于「我们证明了这一圈没有」。
    """
    assert _mk_disc(STOP_COMPLETE).complete is True
    assert _mk_disc(STOP_EMPTY).complete is True
    for reason in (STOP_PAGE_CAP, STOP_DUP_STOP, STOP_SERVER_CAP, STOP_API_ERROR, STOP_NOT_RUN):
        d = _mk_disc(reason)
        assert d.complete is False, f"{reason} 不得被当成查全"
    assert _mk_disc(None).complete is False, "合成盘（无原因）按定义不自称查全"

    with pytest.raises(TypeError):
        EvidenceDisc(category="pharmacy", anchor=xy_to_lnglat(CENTER, 0.0, 0.0),
                     request_radius_m=2000.0, exhausted_radius_m=2000.0, complete=True)


@needs_region
def test_completeness_predicate_has_a_single_home_across_the_three_layers():
    """同一条「什么算查全」的词汇判定，三层（客户端返回 / 逐词举证 / 证据圆盘）必须给同一个答案。

    判据不是「各自看起来对」，而是**指向同一个函数**：将来加第四种停止原因时，只会有
    `baidu_client.is_exhausted` 一处需要更新 —— 这条用例保证其它两层没留第二份 `in (...)`，
    因为若留了，某一处漏更时这里会先红。
    """
    from app.living_circle.baidu_client import PlaceSearchOut
    from app.living_circle.poi_collector import TermEvidence

    reasons = (STOP_COMPLETE, STOP_EMPTY, STOP_PAGE_CAP, STOP_DUP_STOP,
               STOP_SERVER_CAP, STOP_API_ERROR, STOP_NOT_RUN)
    for reason in reasons:
        out = PlaceSearchOut([], 0, 1, reason)
        ev = TermEvidence(category="pharmacy", term="药店", requested_radius_m=2000.0,
                          pages_fetched=1, returned=0, total=0, stop_reason=reason,
                          farthest_m=None)
        disc = _mk_disc(reason)
        assert out.evidence_complete == ev.complete == disc.complete == is_exhausted(reason), (
            f"{reason} 在三层里被判成了不同的完整性 ⇒ 有人抄了第二份判据"
        )
        # 封顶也必须同源（它是第三态 `unjudgeable_by_cap` 的唯一原料，判错就是把外部
        # 限制说成自己的漏查，或反过来）
        assert out.cap_hit == ev.cap_hit == disc.cap_hit == (reason == STOP_SERVER_CAP), (
            f"{reason} 的封顶判定在三层不一致"
        )



def _two_disc_region():
    """同类两块盘：一块穷尽到 2500m、一块只到 1500m ⇒ max/min 塌缩刻意不同值。"""
    return EvidenceRegion([
        _mk_disc_of("pharmacy", 0.0, 0.0, 2500.0, STOP_PAGE_CAP, request_m=2500.0),
        _mk_disc_of("pharmacy", 1200.0, 0.0, 1500.0, STOP_PAGE_CAP, request_m=2500.0),
    ])


def _mk_disc_of(category, x_m, y_m, exhausted_m, reason, request_m=None):
    return EvidenceDisc(
        category=category, anchor=xy_to_lnglat(CENTER, x_m, y_m),
        request_radius_m=float(exhausted_m if request_m is None else request_m),
        exhausted_radius_m=float(exhausted_m), stop_reason=reason,
    )


@needs_region
def test_min_and_max_collapses_are_different_numbers_on_purpose():
    """两个标量塌缩必须**分名分值**：max 给标量视图，min 给取证强度规划。"""
    reg = _two_disc_region()
    assert reg.frontier_m("pharmacy") == 2500.0, "payload 用的乐观塌缩（向后兼容既有键）"
    assert reg.min_exhausted_m("pharmacy") == 1500.0, "规划用的保守塌缩"
    assert reg.min_exhausted_m("market") is None, (
        "无盘必须给 None 而不是 0.0 ⇒ 0.0 会让「一次都没查」在公式里等价于「查了但没查到」"
    )


@needs_region
def test_plan_expansion_spaces_by_min_exhausted_not_max():
    """T-P0-2：间距上界由该类**最浅那块盘**导出（复审说 max 会虚高 ⇒ 外沿格无人认领）。"""
    from app.living_circle.anchors import LatticeAnchors, PLAN_EXPAND

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    reg = _two_disc_region()
    plan = lat.plan_expansion(reg, grid, "pharmacy")
    assert plan.reason == PLAN_EXPAND
    assert plan.exhausted_min_m == 1500.0
    assert plan.cap_step_m == pytest.approx(lat.cap_step_m(1500.0))
    # 前置要断的是「min 与 max 导出**两个不同的档**」，而不是「min 档比格距还小」：
    # `cap_step_m(grid.step)` 在 step(≈196m) < 判定半径(1000m) 时恒为 0，拿它当对照等于
    # 断言一个恒不成立的数（这条第一版就这么写错了，且从未被跑到过）。
    optimistic = lat.cap_step_m(reg.frontier_m("pharmacy"))          # 2500m 那块盘导出的上界
    assert plan.cap_step_m < optimistic, (
        f"min={plan.cap_step_m:.1f} 与 max={optimistic:.1f} 必须算出不同的间距上界，"
        "否则本用例没有对照样本"
    )
    assert plan.stride < lat.stride_for(grid, optimistic), (
        "两个塌缩既然不同档，落到整数 stride 上也必须分档（否则白烧与漏判看不出来）"
    )
    assert plan.stride == lat.stride_for(grid, plan.cap_step_m)
    # 关键对照：若有人改回 max 塌缩，间距会明显变疏、锚点会变少 ⇒ 这条立刻红
    looser = lat.anchors(grid, optimistic)
    assert len(plan.anchors) >= len(looser), (
        f"保守塌缩排出的锚点({len(plan.anchors)})不该比乐观塌缩({len(looser)})更稀"
    )


@needs_region
def test_plan_expansion_excludes_tried_anchors_and_terminates():
    """同锚点不重发 = 回合的终止守卫；候选全试过报 `no_new_anchor`，**不声称已覆盖**。"""
    from app.living_circle.anchors import (
        LatticeAnchors, PLAN_EXPAND, PLAN_NO_NEW_ANCHOR,
    )

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    reg = _two_disc_region()
    first = lat.plan_expansion(reg, grid, "pharmacy")
    assert first.reason == PLAN_EXPAND and first.anchors, "前置：第一轮必须排得出锚点"

    second = lat.plan_expansion(reg, grid, "pharmacy", already_tried=first.anchors)
    assert second.reason == PLAN_NO_NEW_ANCHOR
    assert second.anchors == () and second.anchors_total == 0
    assert second.exhausted_min_m == first.exhausted_min_m, "原因变了不该改动证据事实"


@needs_region
def test_plan_expansion_reports_dropped_anchors_instead_of_hiding_them():
    """P0-3：被上限砍掉的锚点是**字段**，不是注释。砍掉就必须有下家去归因。"""
    from app.living_circle.anchors import LatticeAnchors, PLAN_EXPAND

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    reg = _two_disc_region()
    full = lat.plan_expansion(reg, grid, "pharmacy")
    assert full.anchors_dropped == 0 and full.anchors_total == len(full.anchors)
    if full.anchors_total < 2:
        pytest.skip("该格阵下候选锚点不足 2 个 ⇒ 截断形状造不出来（换格距再测，不放宽断言）")
    cut = lat.plan_expansion(reg, grid, "pharmacy", max_anchors_per_cat=1)
    assert cut.reason == PLAN_EXPAND
    assert len(cut.anchors) == 1
    assert cut.anchors_total == full.anchors_total
    assert cut.anchors_dropped == cut.anchors_total - 1, (
        f"砍掉数量必须如实：total={cut.anchors_total} used={len(cut.anchors)}"
    )


@needs_region
def test_plan_expansion_refuses_categories_without_evidence():
    """T-P0-1 的闸门：没有盘的类**不进判据**（对着空气排锚点就是白烧）。"""
    from app.living_circle.anchors import LatticeAnchors, PLAN_NO_EVIDENCE

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    plan = lat.plan_expansion(_two_disc_region(), grid, "market")   # region 里没有 market 盘
    assert plan.reason == PLAN_NO_EVIDENCE
    assert plan.anchors == () and plan.exhausted_min_m is None
    assert plan.cap_step_m == 0.0 and plan.stride == 0, "无证据不该算出任何间距档位"

    empty = lat.plan_expansion(None, grid, "market")
    assert empty.reason == PLAN_NO_EVIDENCE, "连 region 都没有 ⇒ 同一条答案，不许换个 reason"


@needs_region
def test_plan_expansion_stops_when_stride_would_collapse_to_one():
    """P0-4 止损：边界浅到撑不起一格间距时**不扩**（退回 stride 1 = 满格阵是假装覆盖）。"""
    from app.living_circle.anchors import LatticeAnchors, PLAN_BELOW_FLOOR

    lat = LatticeAnchors()
    grid = judge_grid(CENTER, _scope(), 200.0)
    shallow = EvidenceRegion([_mk_disc_of("pharmacy", 0.0, 0.0, 900.0, STOP_PAGE_CAP, request_m=2000.0)])
    assert lat.cap_step_m(900.0) == 0.0, "前置：900m 边界低于判定半径 ⇒ 上界为 0"
    plan = lat.plan_expansion(shallow, grid, "pharmacy")
    assert plan.reason == PLAN_BELOW_FLOOR
    assert plan.anchors == () and plan.anchors_total == 0, "止损不许发出满格阵那么密的锚点"


# ── S-P0-1 / T-P0-1 · 触发判据读 region 的未覆盖格，不读标量 ────────────

@needs_region
def test_expansion_criterion_counts_uncovered_cells_and_stops_at_zero():
    """S-P0-1 的正腿：可达区里还有格落不进该类任何圆盘才扩；一格都不缺就**如实停下**。

    复审点名的是「只有『扩』一条腿」的判据 —— 它会把已铺满的类也拖去重打（成本推演里
    140 次白烧的形状）。所以本用例两头都要断：**铺满 ⇒ 0 个锚点**，**没铺满 ⇒ 未覆盖格数
    是个真数**（不是 None、不是 0）。
    """
    from app.living_circle.anchors import LatticeAnchors, PLAN_COVERED

    lat = LatticeAnchors()
    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)
    inside_total = int(inside.sum())
    assert inside_total > 1, f"前置不成立：可达区只有 {inside_total} 格，未覆盖判据会被测成空过"

    # 一块把整个可达区都判得动的盘 ⇒ 未覆盖 0 格 ⇒ covered，一个锚点都不许多打
    wide = EvidenceRegion([_mk_disc_of("pharmacy", 0.0, 0.0, 8000.0, STOP_COMPLETE)])
    done = lat.plan_expansion(wide, grid, "pharmacy", inside=inside)
    assert done.cells_uncovered == 0, f"盘面已铺满可达区，读数却不是 0：{done.cells_uncovered}"
    assert done.reason == PLAN_COVERED
    assert done.anchors == () and done.anchors_total == 0 and done.anchors_dropped == 0, (
        "已覆盖还发锚点 = 把同一件事再证明一遍（白烧）"
    )

    # 一块只能判中心格的盘 ⇒ 未覆盖 = 可达区其余格；且它与下面的止损闸是**两道并联的闸**
    # （复审 T-P0-1：v5.5 曾把止损改成按格数判，于是唯一挡住 72/99 锚点爆炸的闸没了）
    thin = EvidenceRegion([_mk_disc_of("pharmacy", 0.0, 0.0, 900.0, STOP_PAGE_CAP, request_m=2000.0)])
    short = lat.plan_expansion(thin, grid, "pharmacy", inside=inside)
    assert short.cells_uncovered == inside_total - 1, (
        f"边界 900m 时可判定半径为 0 ⇒ 只有锚点格有据，未覆盖该是 {inside_total - 1} 格，"
        f"实测 {short.cells_uncovered}"
    )
    assert short.reason != PLAN_COVERED, "明明只剩锚点那一格有据，判据却宣布不用扩"

    # 「没测」必须是 None，不许冒充 0 ⇒ 否则调用方漏传 inside 就等于凭空宣布已覆盖
    unmeasured = lat.plan_expansion(wide, grid, "pharmacy")
    assert unmeasured.cells_uncovered is None, "没给 inside 掩码时读数必须是「没测」而不是 0"
    assert unmeasured.reason != PLAN_COVERED

    # radius_m 是**活参数**：换了它，未覆盖读数就换（若被写死，这条会红着指出它没接线）
    assert lat.count_uncovered_cells(thin, grid, "pharmacy", inside, radius_m=0.0) < inside_total - 1


@needs_region
def test_categories_without_evidence_never_meet_the_uncovered_criterion():
    """T-P0-1 的闸门：无盘类别的 mask 恒全 False ⇒ 未覆盖判据对它**恒等于整个可达区**，
    所以这类必须在进判据**之前**就退回 `no_evidence`（实测形状：78/99 格、7 个展示类全命中）。
    """
    from app.living_circle.anchors import LatticeAnchors, PLAN_NO_EVIDENCE

    lat = LatticeAnchors()
    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)
    reg = _two_disc_region()                      # 只有 pharmacy 的盘

    plan = lat.plan_expansion(reg, grid, "market", inside=inside)
    assert plan.reason == PLAN_NO_EVIDENCE
    assert plan.cells_uncovered is None, (
        "无盘类不得产出一个未覆盖读数 —— 那个数在数学上恒等于整片可达区，"
        "它说的不是「有缺口」，而是「我们一次都没查」"
    )
    # 反面事实钉住：真的去数会得到整片格数 ⇒ 上面那条 `is None` 不是空话，是在避开一个具体陷阱
    assert lat.count_uncovered_cells(reg, grid, "market", inside) == int(inside.sum())


@needs_region
def test_cover_matrix_takes_an_explicit_region_without_binding_it_into_the_scope():
    """T-P0-1 选项①：区域可以**作为参数**进判盲，但 scope 的标量口径一个字都不动。

    为什么不走 `with_evidence(region=…)`：那会把 payload 的标量视图来源从「采集器逐词取 min」
    换成「圆盘取 max」，与 B5/B10/B11 及前端 6 份复算副本同批才动得了（批次二）。
    本用例钉两件事：显式 region **改变了判出的格数**（说明参数不是装饰），
    以及它**没有**顺手改 scope（说明标量视图没被换来源）。
    """
    from app.living_circle.blindspot import cover_matrix

    scope = _scope().with_evidence({"market": 1500.0, "pharmacy": 1500.0, "primary": 1500.0})
    triads = {k: [] for k in ("market", "pharmacy", "primary")}
    _m0, _s0, base = cover_matrix(CENTER, scope, triads, 200.0)
    assert scope.evidence_region is None, "前置：这条 scope 只绑了标量，region 走的是退化特例"

    wide = EvidenceRegion([
        _mk_disc_of(k, 0.0, 0.0, 8000.0, STOP_COMPLETE)
        for k in ("market", "pharmacy", "primary")
    ])
    _m1, _s1, got = cover_matrix(CENTER, scope, triads, 200.0, region=wide)
    assert got["cells_blind"] > base["cells_blind"], (
        f"把证据面从 1500m 放大到 8000m，判出盲区的格数却没变（{base['cells_blind']}）"
        " ⇒ 显式 region 根本没进判定路径"
    )
    assert scope.evidence_region is None, "显式参数把 region 反写进了 scope —— 报告口径的来源被动过"
    assert scope.category_bound_m("market") == 1500.0, "标量视图被显式参数顺手改写了"
    assert got["cells_inside"] == base["cells_inside"], "判定格阵不该因区域而换"


@needs_region
def test_cover_matrix_default_path_is_bitwise_the_degenerate_single_disc():
    """零回归的落法：不给 `region` 时，判定结果与显式给「退化单圆盘」**逐位相同**。

    断的是逐位（掩码 + 格距 + 分账），不是「都不报错」—— 后者会把结论测成反向。
    """
    from app.living_circle.blindspot import cover_matrix

    scope = _scope().with_evidence({"market": 2200.0, "pharmacy": 1800.0, "primary": 2000.0})
    triads = {
        "market": [xy_to_lnglat(CENTER, 400.0, 300.0)],
        "pharmacy": [],
        "primary": [xy_to_lnglat(CENTER, -900.0, 600.0)],
    }
    miss_a, step_a, stats_a = cover_matrix(CENTER, scope, triads, 200.0)
    miss_b, step_b, stats_b = cover_matrix(
        CENTER, scope, triads, 200.0, region=scope.degenerate_evidence_region(CENTER))
    assert miss_a.tolist() == miss_b.tolist(), "缺省路径与退化重放逐位不一致 ⇒ 多了一条分支"
    assert step_a == step_b and stats_a == stats_b


@needs_region
def test_cover_matrix_refuses_two_different_region_sources():
    """两条取法同时给**不同对象** ⇒ 报错；给**同一个对象** ⇒ 放行（与 `with_evidence` 同哲学）。"""
    from app.living_circle.blindspot import cover_matrix

    reg = EvidenceRegion([_mk_disc_of("market", 0.0, 0.0, 1800.0, STOP_COMPLETE)])
    scope = _scope().with_evidence(region=reg)
    triads = {k: [] for k in ("market", "pharmacy", "primary")}
    other = EvidenceRegion([_mk_disc_of("market", 600.0, 0.0, 1800.0, STOP_COMPLETE)])

    with pytest.raises(ValueError, match="唯一来源"):
        cover_matrix(CENTER, scope, triads, 200.0, region=other)
    # 同一个对象不构成「两个来源」，不许误伤；且它必须逐位等于缺省路径（否则「放行」是空话）
    _m, _s, ok = cover_matrix(CENTER, scope, triads, 200.0, region=scope.evidence_region)
    _m2, _s2, default = cover_matrix(CENTER, scope, triads, 200.0)
    assert ok == default, f"同一个对象作显式参数却算出不同分账：{ok} vs {default}"


@needs_region
def test_find_blindspots_stats_passes_the_region_through():
    """`find_blindspots_with_stats` 的 `region` 必须是**通的**，不是签名上的装饰。

    判据取用户入口那一侧：同一份 scope + 同一批点位，只换注入的区域 ⇒ 分账要跟着变。
    若透传漏了一环（`cover_matrix(...)` 少传一个实参），这里就回到缺省路径，断言立刻红。
    """
    from app.living_circle.blindspot import find_blindspots_with_stats

    scope = _scope().with_evidence({"market": 1500.0, "pharmacy": 1500.0, "primary": 1500.0})
    triads = {k: [] for k in ("market", "pharmacy", "primary")}
    _spots, bare = find_blindspots_with_stats(CENTER, scope, triads, prefix="p1")
    wide = EvidenceRegion([
        _mk_disc_of(k, 0.0, 0.0, 8000.0, STOP_COMPLETE)
        for k in ("market", "pharmacy", "primary")
    ])
    _spots_wide, injected = find_blindspots_with_stats(
        CENTER, scope, triads, prefix="p2", region=wide)
    assert injected["cells_judged"] > bare["cells_judged"], (
        f"注入更大区域后可判格数没变（{bare['cells_judged']}）⇒ region 参数在某个调用点被丢了"
    )
    assert injected["cells_inside"] == bare["cells_inside"], "注入区域不该换掉判定格阵"


@needs_region
def test_expansion_criterion_and_judging_share_one_radius_default():
    """判据（`cells_uncovered`）与判盲（`cover_matrix`）不许各填各的 `radius_m`。

    ⚠️ **判据升版（生活圈片 1b）**：原来钉的是「两边默认值都等于 `BLIND_RADIUS_M`」——
    那条断言当时是对的，但函数默认值在 **def 期求值**，值被焊进函数对象，所以"改口径源头"
    永远改不到这些默认路径（γ 守卫 G-11 因此禁止这个形状）。今天这四处的默认值是哨兵
    ``None``，同源关系改由**决议点**保证：省略 ⇒ 同一个 `blind_radius_or` 从同一个口径对象取。
    所以这里钉两件事：① 四个默认值都是 `None`（哨兵形状齐，没人生病回字面量）；
    ② 省略与不省略在 walking 档**数值相同**（这才是"一把尺"的本意）。
    """
    import inspect

    from app.living_circle import scope as scope_mod
    from app.living_circle.anchors import LatticeAnchors
    from app.living_circle.blindspot import cover_matrix

    def _default(fn, name):
        return inspect.signature(fn).parameters[name].default

    for fn, nm in ((cover_matrix, "radius_m"),
                   (LatticeAnchors.plan_expansion, "radius_m"),
                   (LatticeAnchors.count_uncovered_cells, "radius_m"),
                   (EvidenceRegion.to_mask, "radius_m")):
        assert _default(fn, nm) is None, (
            f"{getattr(fn, '__name__', fn)}.{nm} 的默认值又变回字面量了：分档时这条默认路径"
            "不会跟着口径变（G-11 判红的那个形状）"
        )
    # 正向对照：哨兵省略 ⇒ 与显式传 walking 档的登记值**同一个数**（不是"都等于 1000"的巧合）
    # ⚠️ 第二形参现在**必填**（批 A① 收紧：回落哪一档要点名，签名不许替调用方选步行档）。
    walking = scope_mod.get_caliber("walking").blind_radius_m
    assert scope_mod.blind_radius_or(None, "walking") == walking
    assert scope_mod.blind_radius_or(800.0, "walking") == 800.0, "显式值必须原样用，不许被口径覆盖"
    assert BLIND_RADIUS_M == walking, "兼容名必须仍等于口径登记值，否则它成了第二处定义"


# ── v5.9 前置① · 判据读的是「判盲那一次仍未判出的格」────────────────
#
# 下面三条共用同一份输入（复审 P0-3 点名的形状要有数，不能只有不等号）。读数取自
# `skip/tmp/lc_v59_readings.py`（`.venv/bin/python`，零真实调用，2026-09-29）：
#   cells_inside=625 cells_judged=347 cells_unknown=278 cells_unjudgeable_by_cap=0
#   cells_blind=332  undecided=278    inside&~blind=293
#   pharmacy 候选锚点：整片 inside 排出 49 个（未覆盖 596）→ 未判出格排出 20 个（未覆盖 272）
# 形状：market 只查到东侧（造出「有据且确实缺失」的判盲格）、primary 查到 9km、
# pharmacy 只查到中心 1.6km（⇒ 它是唯一还需要取证的那一类）。

def _v59_inputs():
    scope = _scope()
    region = EvidenceRegion([
        _mk_disc_of("market", 900.0, 0.0, 2200.0, STOP_COMPLETE),
        _mk_disc_of("primary", 0.0, 0.0, 9000.0, STOP_COMPLETE),
        _mk_disc_of("pharmacy", 0.0, 0.0, 1600.0, STOP_COMPLETE),
    ])
    triads = {
        "market": [xy_to_lnglat(CENTER, 900.0 + 260.0 * k, 300.0 * (k % 3) - 300.0) for k in range(6)],
        "primary": [xy_to_lnglat(CENTER, -2200.0 + 400.0 * k, 200.0 * (k % 5)) for k in range(12)],
        "pharmacy": [xy_to_lnglat(CENTER, 200.0 * k - 400.0, 150.0 * k) for k in range(4)],
    }
    return scope, region, triads


@needs_region
@needs_grid
def test_undecided_mask_is_the_cells_judging_left_open():
    """前置①的出口：`undecided_mask` 交出的正是三态分账里「判不动」的那部分格。

    两条腿都要断，否则会退化成「掩码非空」这种恒真式：
      - 判出盲的格**一格都不许在**掩码里（已有结论的格再取证买不到新信息）；
      - 数量恰等于 `cells_unknown + cells_unjudgeable_by_cap`，而不是「非盲区」——
        反面事实钉着：`inside & ~blind` = 293 ≠ 278，差的就是 15 格「确认不盲」。
    """
    from app.living_circle.blindspot import cover_matrix, undecided_mask

    scope, region, triads = _v59_inputs()
    miss, step, stats = cover_matrix(CENTER, scope, triads, 200.0, region=region)
    open_cells, grid = undecided_mask(CENTER, scope, triads, grid_m=200.0, region=region)

    # 前置：这批输入里既有判盲格也有「确认不盲」格，否则「排除已判出」这句话测不出东西
    assert stats["cells_blind"] > 0, "前置不成立：一个盲区都没判出"
    assert stats["cells_judged"] - stats["cells_blind"] == 15, (
        f"「确认不盲」的格子数变了（原 15）⇒ 本用例的反面事实不再判别，读数需重取"
    )
    assert int((open_cells & miss).sum()) == 0, "已判出盲区的格还在向取证要钱"
    # ⚠️ 下面这条等式在两个出口共用同一份计算后**已是构造恒等**（判它红的是那三个字面值：
    # 278 / 15 / 293）。留着只说明分账没算歪，别把它读成一条独立验证（复审 P1-4/D1 点名过）。
    assert int(open_cells.sum()) == stats["cells_unknown"] + stats["cells_unjudgeable_by_cap"] == 278, (
        f"未判出格数与三态分账对不上：{int(open_cells.sum())} vs {stats}"
    )
    inside = grid.inside_mask(scope)
    assert int((inside & ~miss).sum()) == 293 != int(open_cells.sum()), (
        "掩码若等于「非盲区」就说明它读的是 miss 而不是 verdict —— 那 15 格会被白烧"
    )
    # 格阵必须是判定那一次的那一份（调用方不许自己重算 ⇒ 第二处格阵来源）
    assert grid.step == step and grid.n == 37, "返回的格阵与判盲用的不是同一份"


@needs_region
@needs_grid
def test_open_cells_demand_fewer_anchors_than_the_whole_reachable_area():
    """前置①的成本读数：判据换吃未判出格 ⇒ 同一份区域排出的锚点**严格变少**。

    这条就是 D6「约 50 次/场景」从推演变成读数的落点：pharmacy 一类 49 个候选降到 20 个
    （该类全关键词表只有 1 个词 ⇒ 差 29 次真实调用）。两个数都钉字面，漂了要重取而不是放宽。
    """
    from app.living_circle.anchors import LatticeAnchors, PLAN_EXPAND
    from app.living_circle.blindspot import undecided_mask

    scope, region, triads = _v59_inputs()
    lat = LatticeAnchors()
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)

    full = lat.plan_expansion(region, grid, "pharmacy", inside=inside)
    open_cells, grid2 = undecided_mask(CENTER, scope, triads, grid_m=200.0, region=region)
    lean = lat.plan_expansion(region, grid2, "pharmacy", inside=open_cells)

    assert full.reason == lean.reason == PLAN_EXPAND, (
        f"两条腿都得真在规划：{full.reason} / {lean.reason}"
    )
    assert full.anchors_total == 49, f"整片可达区的候选锚点数变了（原 49）：{full.anchors_total}"
    assert lean.anchors_total == 20, f"改吃未判出格后锚点数变了（原 20）：{lean.anchors_total}"
    assert lean.cells_uncovered == 272 and full.cells_uncovered == 596, (
        f"未覆盖读数没跟着掩码走：lean={lean.cells_uncovered} full={full.cells_uncovered}"
    )
    assert lean.anchors_total > 0, "少到 0 就不叫省成本，叫把判据改成永不取证"


@needs_region
@needs_grid
def test_enlarging_the_evidence_region_never_reopens_a_decided_cell():
    """区域方向单调：把证据盘放大 ⇒ 未判出格只减不增，已判出的格不会回流。

    这是「把已判出的格从取证需求里划掉」合法的**那一半**前提（第五轮复审 P0-1 要求写准范围：
    另一半在点位方向**不成立**，见下一条）。
    """
    from app.living_circle.blindspot import cover_matrix, undecided_mask

    scope, region, triads = _v59_inputs()
    open_before, _g1 = undecided_mask(CENTER, scope, triads, grid_m=200.0, region=region)
    miss_before, _s, stats_before = cover_matrix(CENTER, scope, triads, 200.0, region=region)

    wider = EvidenceRegion([
        region.of_category("market")[0], region.of_category("primary")[0],
        _mk_disc_of("pharmacy", 0.0, 0.0, 4200.0, STOP_COMPLETE),
    ])
    open_after, _g2 = undecided_mask(CENTER, scope, triads, grid_m=200.0, region=wider)
    miss_after, _s2, stats_after = cover_matrix(CENTER, scope, triads, 200.0, region=wider)

    assert int(open_before.sum()) == 278 and int(open_after.sum()) == 63, (
        f"放大证据面后可判格数没动：{open_before.sum()} → {open_after.sum()}"
    )
    assert int((open_after & ~open_before).sum()) == 0, (
        "把区域放大后冒出了新的「未判出格」⇒ 这张掩码在区域方向不单调，划格逻辑不成立"
    )
    assert int((miss_before & ~miss_after).sum()) == 0, "已有盲区被后续取证翻案了"
    assert stats_after["cells_blind"] == 522 > stats_before["cells_blind"] == 332


@needs_region
@needs_grid
def test_a_newly_found_facility_reopens_the_cells_it_dissolves():
    """点位方向**不**单调（复审 P0-1 的真实形状）：回合带回来的新点位会把盲区退回未判出格。

    机制不是 bug：某格原本靠「market 有据且确实没有」判成盲区，新点把「没有」这条证据消掉，
    而其余两类在该格还不够有据 ⇒ 既不能说盲也不能说不盲，诚实状态就是 unknown。
    ⇒ 三条硬结论写在这里给接线那一轮用：① 掩码**每轮重算**，不许缓存；② `covered` 只是本轮
    结论、不是永久断言；③ 方向偏保守（宁可重新要一次取证）。
    """
    from app.living_circle.blindspot import cover_matrix, undecided_mask

    scope = _scope()
    # market 查到 1754m（可判定到中心外 754m）；药/小只查到 1050m（可判定仅中心外 50m）
    # ⇒ 754m 环带里绝大多数格「只有 market 一类有据」，正是能被新点翻案的形状
    region = EvidenceRegion([
        _mk_disc_of("market", 0.0, 0.0, 1754.0, STOP_PAGE_CAP),
        _mk_disc_of("pharmacy", 0.0, 0.0, 1050.0, STOP_COMPLETE),
        _mk_disc_of("primary", 0.0, 0.0, 1050.0, STOP_COMPLETE),
    ])
    mid = xy_to_lnglat(CENTER, 0.0, 0.0)
    before = {"market": [], "pharmacy": [mid], "primary": [mid]}
    open_1, _g = undecided_mask(CENTER, scope, before, grid_m=200.0, region=region)
    _m1, _s1, stats1 = cover_matrix(CENTER, scope, before, 200.0, region=region)

    after = {"market": [xy_to_lnglat(CENTER, -600.0, 200.0)], "pharmacy": [mid], "primary": [mid]}
    open_2, _g2 = undecided_mask(CENTER, scope, after, grid_m=200.0, region=region)
    _m2, _s2, stats2 = cover_matrix(CENTER, scope, after, 200.0, region=region)

    assert stats1["cells_blind"] == 45 and stats2["cells_blind"] == 12, (
        f"新点位溶掉的盲区数变了（原 45→12）：{stats1['cells_blind']}→{stats2['cells_blind']}"
    )
    assert int(open_1.sum()) == 580 and int(open_2.sum()) == 612, (
        f"未判出格没随点位回流（原 580→612）：{int(open_1.sum())}→{int(open_2.sum())}"
    )
    assert int((open_2 & ~open_1).sum()) == 32, "回流格数与两读数之差不一致 ⇒ 掩码算重了"


# ── v5.9 前置② · 判定吃的那块区域是落库/举证的唯一来源 ────────────────

@needs_region
def test_judge_region_is_the_single_resolution_point_for_judging_and_landing():
    """「判定吃哪块区域」只许有一处解析：显式 > 绑定 > 退化单圆盘（v5.9 前置②第 1 处）。

    此前这段判断抄在 `cover_matrix` 里、落库侧另读 `scope.evidence_region` ⇒ 参数通道一旦被
    接线用上，报告的格分账与逐锚点举证就不是同一块区域撑的。三条出路各自钉住。
    """
    reg = EvidenceRegion([_mk_disc_of("pharmacy", 0.0, 0.0, 1800.0, STOP_COMPLETE)])
    bound = _scope().with_evidence(region=reg)
    bare = _scope().with_evidence({"market": 1500.0, "pharmacy": 1500.0, "primary": 1500.0})

    assert bound.judge_region(CENTER) is reg, "绑定了 region 却不认它 ⇒ 解析点又分了家"
    # 已经绑过 region 的 scope **不许**再吃一块不同的：这是 T-P0-1 选项①自带的纪律，
    # 不是漏了放行。⇒ 接线的真实约束是「回合中途注入新区域，前提是这份 scope 没绑过 region」
    # （生产今天走 `with_evidence(frontier_m=…)` 标量绑定 ⇒ region 恒为 None，通道是通的）。
    other = EvidenceRegion([_mk_disc_of("pharmacy", 600.0, 0.0, 1800.0, STOP_COMPLETE)])
    with pytest.raises(ValueError, match="唯一来源"):
        bound.judge_region(CENTER, other)
    with pytest.raises(ValueError, match="唯一来源"):
        bound.judge_region(CENTER, EvidenceRegion(other.discs))   # 内容相同也不是同一对象
    assert bare.judge_region(CENTER, other) is other, (
        "未绑定 region 时显式参数必须优先 —— 取证回合靠这条把新区域递进判定"
    )
    degenerate = bare.judge_region(CENTER)
    assert sorted(d.category for d in degenerate.discs) == sorted(TRIAD_KEYS), (
        f"退化区域登记的类别与必达要素名册不一致：{[d.category for d in degenerate.discs]}"
    )
    assert [d.exhausted_radius_m for d in degenerate.discs] == [1500.0, 1500.0, 1500.0], (
        f"退化圆盘没从标量边界导出：{[(d.category, d.exhausted_radius_m) for d in degenerate.discs]}"
    )
    assert [d.anchor for d in degenerate.discs] == [CENTER, CENTER, CENTER], (
        "退化盘的锚点必须是分析中心 —— 否则「现状」就不是区域模型的特例，而是另一个东西"
    )


@needs_region
def test_payload_emits_anchors_from_the_region_judging_ate():
    """举证块跟着判定吃的那块走（v5.9 前置②第 2 处）：缺省逐位不变，显式给了才换来源。"""
    reg = EvidenceRegion([
        _mk_disc_of("pharmacy", 0.0, 0.0, 2000.0, STOP_COMPLETE),
        _mk_disc_of("pharmacy", 900.0, 0.0, 1700.0, STOP_SERVER_CAP, request_m=2000.0),
    ])
    caliber = get_caliber("walking")
    scalar_scope = _scope().with_evidence(
        {"market": 2200.0, "pharmacy": 2000.0, "primary": 2100.0})

    assert "evidence_anchors" not in scalar_scope.payload(caliber), (
        "缺省路径凭空多出举证键 = 动了既有报告形状（批次一的零回归约束）"
    )
    shown = scalar_scope.payload(caliber, judged_region=reg)["evidence_anchors"]
    assert [r["category"] for r in shown] == ["pharmacy", "pharmacy"]
    assert [r["exhausted_radius_m"] for r in shown] == [2000.0, 1700.0], (
        f"发射的不是判定吃的那块盘的深度：{shown}"
    )
    assert [r["cap_hit"] for r in shown] == [False, True], "封顶事实没跟着盘走"

    # 同一对象作显式参数 ⇒ 与缺省逐字相同（不许因为「走了参数通道」而换形状）
    bound = scalar_scope.with_evidence(region=reg)
    assert bound.payload(caliber, judged_region=reg) == bound.payload(caliber)
    with pytest.raises(ValueError, match="唯一来源"):
        bound.payload(caliber, judged_region=EvidenceRegion(reg.discs[:1]))


@needs_region
def test_bound_region_payload_is_self_consistent_for_the_b12_gate():
    """写侧同源（v5.9 前置②第 3 处的对照腿）：**区域绑定**这条路落库时，标量视图恰是该类圆盘的最大值。

    B12 在读取侧只要求标量边界落在明细深度区间内（min/max 两种合法塌缩都放行，见
    `test_report_contract.py::test_frontier_at_the_min_collapse_is_not_flagged`）。本用例钉的是
    区域绑定这一路的**具体**塌缩值：market 两块盘取 max=2200 而不是 min=1800 —— 若这里被改成
    min，`with_evidence(region=…)` 与旧的单圆盘标量值就不再逐位恒等，B5/B10 的复算会漂。
    """
    reg = EvidenceRegion([
        _mk_disc_of("market", 0.0, 0.0, 2200.0, STOP_COMPLETE),
        _mk_disc_of("market", 900.0, 0.0, 1800.0, STOP_COMPLETE),
        _mk_disc_of("pharmacy", 0.0, 0.0, 2000.0, STOP_COMPLETE),
        _mk_disc_of("primary", 0.0, 0.0, 2100.0, STOP_COMPLETE),
    ])
    cal = _scope().with_evidence(region=reg).payload(get_caliber("walking"))
    rows = cal["evidence_anchors"]
    assert len(rows) == 4, "逐锚点明细被塌过 ⇒ 报告答不出「这片的证据是哪几个点撑的」"
    assert cal["evidence_frontier_m"]["market"] == 2200.0, (
        "区域绑定时标量视图用的是 min 塌缩（那是采集器逐词的取法）而不是 max ⇒ 与旧的单圆盘"
        "标量值不再逐位恒等，B5/B10 与前端 6 份复算会一起漂"
    )
    for cat in ("market", "pharmacy", "primary"):
        depths = [r["exhausted_radius_m"] for r in rows if r["category"] == cat]
        assert cat in cal["evidence_frontier_m"], f"{cat} 有明细却没边界，B12 会把这份判违规"
        assert cal["evidence_frontier_m"][cat] == max(depths), (
            f"{cat} 的标量视图与明细不同源：{cal['evidence_frontier_m'][cat]} vs {max(depths)}"
        )


@needs_region
def test_explicit_judging_radius_propagates_through_every_layer():
    """验收线 2（生活圈片 1b）：显式 `radius_m=800` 必须**一路跟变**，一层都不落。

    这条抓的是「归一归了个寂寞」的形状：默认值都换成哨兵了，但链上某层还在读兼容常量 ⇒
    总分看起来"也变了"（因为别的层变了），那一层却按 1000 算。所以每项**分别**比，
    并且给一个方向性断言（半径变小 ⇒ 判定圆更容易被证据盘完整覆盖 ⇒ `cells_judged` 必增），
    方向断言比"不等"更强：它把"改了但改反了/只改了一半"也测得出来。
    最后一条正向对照：显式传 1000 与省略实参**逐位相同** ⇒ 决议点今天确实落在 walking 档。
    """
    from app.living_circle.blindspot import judge_once

    scope = _scope().with_evidence({"market": 2200.0, "pharmacy": 1800.0, "primary": 2000.0})
    triads = {
        "market": [xy_to_lnglat(CENTER, 400.0, 300.0)],
        "pharmacy": [],
        "primary": [xy_to_lnglat(CENTER, -900.0, 600.0)],
    }
    d = judge_once(CENTER, scope, triads, grid_m=200.0, prefix="r1000")
    r = judge_once(CENTER, scope, triads, grid_m=200.0, prefix="r0800", radius_m=800.0)
    same = judge_once(CENTER, scope, triads, grid_m=200.0, prefix="r1000b", radius_m=1000.0)

    assert d.radius_m == 1000.0, f"省略时该按口径决议到 walking 档，实得 {d.radius_m}"
    assert r.radius_m == 800.0
    for spot in r.spots:
        assert spot["radius_m"] == 800, f"上屏半径仍写常量：{spot['id']} → {spot['radius_m']}"
    for spot in d.spots:
        assert spot["radius_m"] == 1000

    assert r.stats["cells_judged"] > d.stats["cells_judged"], (
        f"半径从 1000 缩到 800，可判定的格却没变（{d.stats['cells_judged']} → "
        f"{r.stats['cells_judged']}）⇒ 掩码那一层还在吃兼容常量"
    )
    assert r.masks.blind.sum() != d.masks.blind.sum(), "盲区掩码没跟着半径变"
    assert r.stats != d.stats, "五键账目一字不差 ⇒ 半径没进判定路径"

    # 场/环这一层：先要**前置成立**（两边都判得出簇），不许用 `if` 把断言条件化 ——
    # 条件化的那条在空集上恒真，正是我在这条链上反复撤掉的那种形状。
    assert d.spots and r.spots, (
        f"前置不成立：这组输入在某一半径下判不出任何盲区（{len(d.spots)}/{len(r.spots)}），"
        "场与环那一层就没东西可比"
    )
    a0 = d.spots[0]["footprint_meta"]["area_m2"]
    a1 = r.spots[0]["footprint_meta"]["area_m2"]
    assert a0 != a1, (
        f"footprint 面积没变（两边都 {a0}）⇒ `BlindnessField` 那条场仍按 1000 切，"
        "报告里会出现「判盲用 800、画圈仍按 1000」的自相矛盾（第十二轮 P1-2）"
    )
    p0 = d.spots[0]["polygon"]["coordinates"][0]
    p1 = r.spots[0]["polygon"]["coordinates"][0]
    assert p0 != p1, "连续缺失场的环完全相同 ⇒ 场没接到决议值"

    # 正向对照：显式传 1000 与省略**逐位相同**（决议点没夹带别的默认值）
    assert same.stats == d.stats
    assert [s["radius_m"] for s in same.spots] == [s["radius_m"] for s in d.spots]


def test_fractional_ruler_survives_the_int_emission():
    """半径的住所类型是 `float` ⇒ 非整档位必须判得出产物（第十五轮 P2-1）。

    发射端把尺取整（`blindspot.py` 的 `"radius_m": int(radius)`，逐字节契约不改），而
    `Judgement` 的一致性检查原先按 `!=` 逐位比 —— 800.6m 那档会拿 `self.radius_m=800.6`
    对上 spot 的 `800`，判成"报告宣称了一把没人用过的尺"⇒ **构造即抛、判定链整条断**。
    成对给反向：真的换了一把尺（差 ≥ 发射宽度 1m）时那道检查仍必须红，容差不许被顺手放宽。
    """
    from app.living_circle.blindspot import judge_once

    scope = _scope().with_evidence({"market": 2200.0, "pharmacy": 1800.0, "primary": 2000.0})
    triads = {
        "market": [xy_to_lnglat(CENTER, 400.0, 300.0)],
        "pharmacy": [],
        "primary": [xy_to_lnglat(CENTER, -900.0, 600.0)],
    }
    j = judge_once(CENTER, scope, triads, grid_m=200.0, prefix="rf", radius_m=800.6)
    assert j.radius_m == 800.6, "决议值不该被取整（只有发射端取整）"
    assert j.spots, "前置不成立：这组输入判不出盲区，反向那半就没载体"
    for spot in j.spots:
        assert spot["radius_m"] == 800, (
            f"发射端仍在原样写浮点（{spot['radius_m']}）⇒ 逐字节契约被这份改动动了"
        )

    # 反向：把某条上屏的尺改成 799（差 1m = 发射宽度）⇒ 一致性检查必须仍然判红
    mismatched = [dict(j.spots[0], radius_m=799)] + list(j.spots[1:])
    with pytest.raises(ValueError, match="报告宣称了一把没人用过的尺"):
        dataclasses.replace(j, spots=mismatched)
