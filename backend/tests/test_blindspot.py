"""M1 · 服务盲区：1km 三要素判定 / 灰区聚合 / 最近设施近邻。

阶段 0.5 变更（Q1 修复）：`find_blindspots` 的第二个形参从 `study_radius_m: float`
改为 :class:`SpatialScope`。旧签名下判定网格按**研究半径**铺满，而采集半径只有 2km
⇒ 2km 外「没查到」被判成「没有」，四个角点起连通域 → 灰区外边界 = 整张方形。
现在网格只铺 `scope.reach_circumradius_m` 且只保留落在可达区多边形内、且 1km 邻域
被采集区完整覆盖的格（其余计入 `cells_unknown`，见 `test_report_invariants.py`）。
"""
from app.living_circle.blindspot import BLIND_RADIUS_M, find_blindspots, find_blindspots_with_stats
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)


def _scope(half_m: float = 2500.0) -> SpatialScope:
    """±half_m 米方形可达区（对应旧测试里的 `study_radius_m=2500.0`）。"""
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


SCOPE = _scope()


def _fac(name, x, y):
    lng, lat = xy_to_lnglat(CENTER, x, y)
    return {"name": name, "lng": lng, "lat": lat}


def _dense_triad(center, x=0, y=0):
    """在一个方位点（局部米坐标）放置三要素齐全的一簇设施。"""
    return [
        {"name": f"菜市-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y)))},
        {"name": f"药店-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x + 200, y)))},
        {"name": f"小学-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y + 200)))},
    ]


def test_no_blindspots_when_triad_everywhere():
    """每 1km 圆内三要素齐备 → 0 盲区（用 400m 网格铺满三要素簇）。

    可达区边界附近的格若 1km 邻域未被采集区完整覆盖，只记 `cells_unknown` 而不判盲，
    因此「角落缺数据」不会伪装成盲区（这正是 Q1 的判别点）。
    """
    triads = {"market": [], "pharmacy": [], "primary": []}
    for x in range(-2000, 2001, 400):
        for y in range(-2000, 2001, 400):
            for k, name in zip(("market", "pharmacy", "primary"), _dense_triad(CENTER, x, y)):
                triads[k].append(name)
    spots = find_blindspots(CENTER, SCOPE, triads, prefix="t")
    assert spots == []


# ── 证据域修复：判定覆盖率与逐类门控 ─────────────────────────────

def test_judged_coverage_spans_reach_not_just_the_center_cells():
    """判定覆盖率不再被「采集余量 0」锁死在中心几格。

    旧口径：可判定半径 = 外接圆 − 1km（凯里实测 1367 − 1000 = 367m）⇒ 97 格里只有 5 格
    有资格被判定。用户问的「左上角右下角设施更稀疏为何不判」就是这么丢的。
    现在余量由证据需求导出（= 判定半径本身）⇒ 未绑定实测证据时，可达区内的格全部可判。

    允许 4 格边界余量：方形可达区的角点距中心恰等于外接圆半径，浮点上可能差之毫厘。
    """
    triads = {k: [_fac(f"{k}-only", 0.0, 0.0)] for k in ("market", "pharmacy", "primary")}
    spots, stats = find_blindspots_with_stats(CENTER, SCOPE, triads, prefix="t")
    assert stats["cells_inside"] > 0
    assert stats["cells_judged"] >= stats["cells_inside"] - 4, (
        f"仍有格被证据门控挡在外面：judged={stats['cells_judged']} / inside={stats['cells_inside']}"
    )
    assert stats["cells_blind"] > 0 and spots, "只有中心有设施 ⇒ 外围应判出盲区，不该整片 unknown"


def test_blind_verdict_needs_only_one_category_with_complete_evidence():
    """判盲是**存在性**结论：一类证据齐 + 该类确实没有 ⇒ 可判，不必等三类都齐。

    这是把 `judged` 从「三类边界取最小」改成「逐类门控」的直接效果。凯里实测：
    菜市场 18 家 / 小学 17 家**一页即穷尽**（边界可达 2.3km），药店 60 家被单页 20 条
    截断（边界只到 1754m）。若按 min 统一门控，最稠密那一类的证据缺口会替最稀疏那两类
    下结论 —— 本可判出的角落会被整体降级成 unknown。

    场景：market 证据到 2400m，药店/小学只到 300m；三要素全放中心 200m 处。
    ⇒ 距中心 ≤1400m 的格对 market 有据可断，外围 1km 圆内无 market ⇒ 应判盲。
    """
    scope = SCOPE.with_evidence(
        {"market": 2400.0, "pharmacy": 300.0, "primary": 300.0}, complete=False
    )
    triads = {k: [_fac(f"{k}-c", 200.0, 0.0)] for k in ("market", "pharmacy", "primary")}
    spots, stats = find_blindspots_with_stats(CENTER, scope, triads, prefix="t")
    assert stats["cells_blind"] > 0, "market 证据已覆盖该格 ⇒ 应判出盲区，不该整片 unknown"
    assert spots, "有盲区格就必须产出盲区簇"


def test_not_blind_verdict_requires_all_three_categories():
    """不对称规则的另一半：说「这格**不盲**」要求三类**都**有据且都命中。

    上一用例的场景里，中心附近那格三类都有设施，但药店/小学证据只到 300m ⇒
    该格 1km 圆伸出药店/小学的证据边界 ⇒ 只能说「不知道」，不能说「不盲」。
    把 unknown 当成 covered 是反向的过度乐观，与 Q1 同源。
    """
    scope = SCOPE.with_evidence(
        {"market": 2400.0, "pharmacy": 300.0, "primary": 300.0}, complete=False
    )
    triads = {k: [_fac(f"{k}-c", 200.0, 0.0)] for k in ("market", "pharmacy", "primary")}
    _spots, stats = find_blindspots_with_stats(CENTER, scope, triads, prefix="t")
    assert stats["cells_unknown"] > 0, (
        "药店/小学证据边界外、但三要素都在 1km 内的格必须落 unknown，不得记成「已覆盖」"
    )
    assert (stats["cells_judged"] + stats["cells_unknown"]) == stats["cells_inside"], "分账必须闭合"


def test_single_missing_facility_produces_blindspot():
    """东南方位缺小学 → 东南角簇盲区，missing_facilities 含小学。"""
    triads = {
        "market": [_fac("菜市", 500, 0), _fac("菜市-远", -1800, 1800), _fac("菜市-北", 0, 1800)],
        "pharmacy": [_fac("药店", 0, 500), _fac("药店-远", 1800, -1800), _fac("药店-北", 1800, 0)],
        # 缺 primary 小学
        "primary": [],
    }
    spots = find_blindspots(CENTER, SCOPE, triads, prefix="kaili")
    assert len(spots) >= 1
    for s in spots:
        assert "小学" in s["missing_facilities"]
        assert s["radius_m"] == int(BLIND_RADIUS_M)
        assert s["polygon"]["type"] == "Polygon"
        ring = s["polygon"]["coordinates"][0]
        assert ring[0] == ring[-1]
        # nearest 应报告最近药店/菜市距离与方位
        assert any(n["facility"] == "pharmacy" for n in s["nearest"])
        assert any(n["distance_m"] > 0 for n in s["nearest"])


def test_blindspot_contract_fields():
    triads = {
        "market": [_fac("菜市", 500, 0)],
        "pharmacy": [_fac("药店", 0, 500)],
        "primary": [],
    }
    spots = find_blindspots(CENTER, SCOPE, triads, prefix="t2")
    first = spots[0]
    # 既有字段必须全部保留（A6 兼容），且新增 严重度/缺口/补点处方 为增量
    assert {"id", "center", "radius_m", "missing_facilities", "nearest", "polygon"} <= set(first.keys())
    assert frozenset(first) == frozenset(
        {"id", "center", "radius_m", "missing_facilities", "nearest", "polygon", "polygon_raw", "severity", "gap_score", "fixes", "footprint_meta"}
    )
    assert first["id"].startswith("bs-t2-")
    assert len(first["center"]) == 2
    assert first["severity"] in {"heavy", "medium", "light"}
    assert 0.0 <= first["gap_score"] <= 1.0
    assert isinstance(first["fixes"], list)


def test_blindspot_dedup_ids_unique():
    triads = {
        "market": [_fac("菜市", 800, 800)],
        "pharmacy": [_fac("药店", -200, -200)],
        "primary": [],
    }
    spots = find_blindspots(CENTER, SCOPE, triads, prefix="u")
    ids = [s["id"] for s in spots]
    assert len(ids) == len(set(ids))


def test_blindspots_confined_to_reach():
    """Q1 回归护栏：盲区多边形不得越出可达区外接圆。"""
    from app.living_circle.geo_utils import haversine_m

    triads = {"market": [], "pharmacy": [], "primary": []}  # 三要素全无 → 全片判盲
    spots = find_blindspots(CENTER, SCOPE, triads, prefix="q1")
    assert spots, "三要素全无时应当判出盲区"
    cr = SCOPE.reach_circumradius_m
    for s in spots:
        for lng, lat in s["polygon"]["coordinates"][0]:
            d = haversine_m(CENTER, (lng, lat))
            assert d <= cr * 1.02, f"盲区顶点距中心 {d:.0f}m 越出可达区外接圆 {cr:.0f}m（Q1 本体）"


# ── R2 严重度标定（纯函数，架构审查收敛）：三档真实可达 + 随 excess 单调上升 ──
from app.living_circle.blindspot import (  # noqa: E402
    BLIND_RADIUS_M,
    SEV_HEAVY,
    SEV_MEDIUM,
    _excess_farness,
    _gap_score,
    _severity_of,
)

# 赛题口径：缺失类的最近替代必≥1km（BLIND_RADIUS_M）；excess = d − 1000
# farness = mean(min(1, excess/1000))；gap = 0.6·(m/3) + 0.4·farness
# ⚠️ 半径现在**必须由调用方显式给**（片 1b 纪律一：私有几何不许自己取口径，否则
# `assemble.py` 那条反向 import 的路会在 helper 内部长出第二个住所）⇒ 下面每条都传 `BLIND_RADIUS_M`。


def test_excess_farness_missing_inf_is_worst():
    # 缺失类无任何设施 → inf → 该项取 1
    assert _excess_farness({}, BLIND_RADIUS_M) == 0.0
    assert _excess_farness({"market": float("inf")}, BLIND_RADIUS_M) == 1.0
    assert _excess_farness({"market": 1000.0}, BLIND_RADIUS_M) == 0.0  # 恰在必达下限 → 无超量
    assert _excess_farness({"market": 2000.0}, BLIND_RADIUS_M) == 1.0  # 超出 1 个下限 → 归一满


def test_excess_farness_requires_an_explicit_ruler():
    """纪律一的正向对照：省略半径必须**响亮失败**，而不是静默按步行档算。

    为什么这条比"能算出数"更重要：`_excess_farness` 拿不到 `travel_mode`，让它自己取口径
    就等于在同一场判定里允许第二把尺存在（`assemble.py:377` 正是反向 import 原语的那条路）。
    空输入也要拦 —— 否则「空 dict 的那格可以不带尺来」，规则漏一个洞。
    """
    import pytest

    with pytest.raises(ValueError, match="_excess_farness"):
        _excess_farness({"market": 1200.0})
    with pytest.raises(ValueError, match="_excess_farness"):
        _excess_farness({})


def test_gap_score_uses_triad_count_not_hardcoded_3():
    # m=1 缺一类，farness=0 → 0.6·(1/3) = 0.2
    assert _gap_score(1, 0.0) == 0.2
    # m=3 全缺，farness=1 → 0.6·1 + 0.4·1 = 1.0
    assert _gap_score(3, 1.0) == 1.0
    assert _gap_score(0, 0.5) == 0.0


def test_severity_three_tiers_all_reachable():
    """R2 硬判据：三档各自在合理构造下可到达，且随 gap 单调上升。"""
    assert _severity_of(0.0) == "light"
    assert _severity_of(SEV_MEDIUM - 1e-9) == "light"
    assert _severity_of(SEV_MEDIUM) == "medium"
    assert _severity_of(SEV_HEAVY - 1e-9) == "medium"
    assert _severity_of(SEV_HEAVY) == "heavy"
    assert _severity_of(1.0) == "heavy"


def test_severity_monotonic_with_excess():
    """同 m 下，替代设施越远 → gap 越高 → 严重度越重（决策分档可信）。"""
    far_near = _excess_farness({"market": 1000.0}, BLIND_RADIUS_M)  # 0
    far_far = _excess_farness({"market": 2000.0}, BLIND_RADIUS_M)  # 1
    g_near = _gap_score(1, far_near)
    g_far = _gap_score(1, far_far)
    assert g_far > g_near
    assert _severity_of(g_far) in {"medium", "heavy"}
    assert _severity_of(g_near) in {"light", "medium"}


def test_gap_score_monotonic_increasing():
    for farness in (0.0, 0.25, 0.5, 0.75, 1.0):
        for m in (1, 2, 3):
            assert 0.0 <= _gap_score(m, farness) <= 1.0
    # 远距替代使缺口严格上升
    assert _gap_score(2, 1.0) > _gap_score(2, 0.0)


def test_fixes_are_per_missing_type_with_priority_and_strategy():
    from app.living_circle.blindspot import _fixes_for

    cluster_center = (CENTER[0], CENTER[1])
    # 缺失 菜市(900m→reroute)、药店(无→build、served=5)
    fixes = _fixes_for(
        ["market", "pharmacy"],
        {"market": 900.0, "pharmacy": float("inf")},
        cluster_center,
        served=5,
        gap=0.5,
    )
    # 目标缺失类不重复（facility 为中文标签：菜市场/药店）
    facs = [f["facility"] for f in fixes]
    assert len(facs) == len(set(facs))
    assert set(facs) == {"菜市场", "药店"}
    strat = {f["facility"]: f["strategy"] for f in fixes}
    assert strat["菜市场"] == "reroute"  # 600–1200m 档
    assert strat["药店"] == "build"  # 无设施 → 新建
    # 点=盲簇质心、served 透传
    assert fixes[0]["point"] == [round(cluster_center[0], 6), round(cluster_center[1], 6)]
    assert all(f["served"] == 5 for f in fixes)


def test_fix_strategy_tier_by_distance():
    from app.living_circle.blindspot import _strategy_for

    assert _strategy_for(300.0) == "mobile_service"  # ≤600 → 流动服务
    assert _strategy_for(600.0) == "mobile_service"
    assert _strategy_for(900.0) == "reroute"  # 600–1200 → 改道
    assert _strategy_for(1200.0) == "reroute"
    assert _strategy_for(2000.0) == "build"  # >1200 → 新建
    assert _strategy_for(float("inf")) == "build"
