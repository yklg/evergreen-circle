"""M1 · 服务盲区：1km 三要素判定 / 灰区聚合 / 最近设施近邻。

阶段 0.5 变更（Q1 修复）：`find_blindspots` 的第二个形参从 `study_radius_m: float`
改为 :class:`SpatialScope`。旧签名下判定网格按**研究半径**铺满，而采集半径只有 2km
⇒ 2km 外「没查到」被判成「没有」，四个角点起连通域 → 灰区外边界 = 整张方形。
现在网格只铺 `scope.reach_circumradius_m` 且只保留落在可达区多边形内、且 1km 邻域
被采集区完整覆盖的格（其余计入 `cells_unknown`，见 `test_report_invariants.py`）。
"""
from app.living_circle.blindspot import BLIND_RADIUS_M, find_blindspots
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
        {"id", "center", "radius_m", "missing_facilities", "nearest", "polygon", "severity", "gap_score", "fixes"}
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
    SEV_HEAVY,
    SEV_MEDIUM,
    _excess_farness,
    _gap_score,
    _severity_of,
)

# 赛题口径：缺失类的最近替代必≥1km（BLIND_RADIUS_M）；excess = d − 1000
# farness = mean(min(1, excess/1000))；gap = 0.6·(m/3) + 0.4·farness


def test_excess_farness_missing_inf_is_worst():
    # 缺失类无任何设施 → inf → 该项取 1
    assert _excess_farness({}) == 0.0
    assert _excess_farness({"market": float("inf")}) == 1.0
    assert _excess_farness({"market": 1000.0}) == 0.0  # 恰在必达下限 → 无超量
    assert _excess_farness({"market": 2000.0}) == 1.0  # 超出 1 个下限 → 归一满


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
    far_near = _excess_farness({"market": 1000.0})  # 0
    far_far = _excess_farness({"market": 2000.0})  # 1
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
