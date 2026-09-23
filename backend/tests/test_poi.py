"""M1 · POI：名称归一 / 清洗去重（50m 聚簇）/ 类别统计 / 点位契约。

阶段 0.5 变更（Q2 修复）：`to_stats` / `to_points` 的「圈」从**裸环**改为
:class:`SpatialScope`，`to_points` 额外要求显式传 **查询中心**（第三排序键由
「名称字母序」改为「距中心距离」），且**圈外点不再出现在返回值里**
（旧行为：返回 `in_circle=False` 的点，让前端自己过滤 —— 实测 88% 是圈外点）。

本文件按**新契约**断言；被替换掉的旧断言在各自 docstring 里留了痕迹，
避免后人误以为覆盖率下降。
"""
import math

import pytest

from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import (
    POI_CAP_PER_CAT,
    backfill_nearest_minutes,
    check_poi_conservation,
    clean,
    dedupe_pois,
    derive_stats_from_points,
    is_duplicate,
    norm_name,
    to_points,
    to_stats,
)
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)
_R = 1600.0


def _ll(x, y):
    return {"lng": xy_to_lnglat(CENTER, x, y)[0], "lat": xy_to_lnglat(CENTER, x, y)[1]}


def _square(half: float):
    """以 CENTER 为中心的 ±half 米方环（4 顶点，闭合由 point_in_ring 容忍）。"""
    return [
        xy_to_lnglat(CENTER, -half, -half),
        xy_to_lnglat(CENTER, half, -half),
        xy_to_lnglat(CENTER, half, half),
        xy_to_lnglat(CENTER, -half, half),
    ]


def _scope(ring, *, reach_min: float = 20.0, study_radius_m: float = 2500.0) -> SpatialScope:
    """由裸环造一个 `SpatialScope`（本文件默认步行口径 reach=20min）。"""
    zone = {"minutes": reach_min, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, study_radius_m, zone)


# 1500m 方环：对角 2121m（沿用原测试的「15min 近似方环」几何）
RING = _square(1500.0)
SCOPE = _scope(RING)
# ±10m 方环：用于「圈内一个都没有」的判定（任何 100m 外的点都在圈外）
TINY_SCOPE = _scope(_square(10.0))


def test_norm_name():
    assert norm_name(" 凯里 老街（店） ") == "凯里老街"
    assert norm_name("凯里老街(店厅)") == "凯里老街"


def test_clean_dedupe_50m():
    items = [
        {**_ll(100, 0), "name": "益民大药房"},
        {**_ll(120, 0), "name": "益民大药房"},  # 20m 内 → 去重
        {**_ll(1000, 0), "name": "仁信大药房"},
        {**_ll(1010, 0), "name": "仁 信 大药房"},  # 名称归一后重复 → 去重
        {**_ll(-500, 300), "name": "诚和药店"},
    ]
    out = clean(items, dedupe_radius_m=50.0)
    assert len(out) == 3
    names = {it["name"] for it in out}
    assert names == {"益民大药房", "仁信大药房", "诚和药店"}


def test_to_stats_in_circle_and_coverage():
    per_cat = {
        "market": [
            {**_ll(100, 0), "name": "菜市场A"},
            {**_ll(1000, 1000), "name": "菜市场B"},  # 对角 1414m 圈内
            {**_ll(2000, 0), "name": "菜市场C"},  # 圈外
        ]
    }
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    s = stats[0]
    assert s["category"] == "market"
    assert s["in_circle"] == 2
    assert s["coverage"] == pytest.approx(2 / 3, abs=0.001)  # ideal=3 → min(1, 2/3)
    assert s["nearest_name"] == "菜市场A"


def test_to_stats_coverage_capped_at_one():
    per_cat = {"shopping": [{**_ll(100, i * 100), "name": f"超市{i}"} for i in range(6)]}
    stats = to_stats(per_cat, {}, SCOPE, CENTER)
    assert stats[0]["coverage"] == 1.0  # ideal=3 → 6/3 封顶 1


def test_to_points_contract_sort_and_cap():
    """M5.1 · 点位契约：字段齐全 / 只留圈内 / **默认上限 200 不触发**。

    旧版此处断言 `market == ["圈内A", "圈内B", "圈外A"]` 且 `圈外A.in_circle is False`
    —— 那是 Q2 缺陷的「接口化」（把圈外点交给前端过滤）。现在圈外点**在源头被丢弃**。

    阶段 1.5 变更：默认上限 25 → `POI_CAP_PER_CAT=200`，故本用例的 30 条 medical
    **不再被截断**（截断语义另由 `test_to_points_discloses_truncation` 用显式小上限锁定）。
    返回值也从裸 list 变为 :class:`PoiPointsOut`（`points` + `truncated`）——截断信息
    无法被调用方顺手丢掉。
    """
    per_cat = {
        "market": [
            {**_ll(2000, 0), "name": "圈外A"},   # 圈外 → 不应出现在返回值里
            {**_ll(100, 0), "name": "圈内A"},    # 圈内有耗时 → 最前
            {**_ll(200, 0), "name": "圈内B"},    # 圈内有耗时 → 次前
        ],
        "medical": [{**_ll(100, i * 50), "name": f"诊所{i}"} for i in range(30)],
    }
    times = {
        "market": [None, 5.2, 6.1],
        "medical": [float(i) for i in range(30)],
    }
    out = to_points(per_cat, times, SCOPE, CENTER)
    pts = out.points
    # 契约字段
    for p in pts:
        assert set(p.keys()) == {"id", "name", "category", "lnglat", "minutes", "in_circle"}
        assert p["in_circle"] is True
    # 圈外被丢弃；圈内按耗时升序
    market = [p for p in pts if p["category"] == "market"]
    assert [p["name"] for p in market] == ["圈内A", "圈内B"]
    assert market[0]["minutes"] == 5.2
    # 30 条 < 默认上限 200 → 全量保留，且**明确披露「无截断」**
    assert len([p for p in pts if p["category"] == "medical"]) == 30
    assert out.truncated == [], "未触发上限时必须给出空披露（而非省略该信息）"


def test_to_points_discloses_truncation():
    """阶段 1.3 · **截断必须被披露**：`dropped` 逐类给出「砍了几条」。

    这是本阶段的核心动作之一 —— 旧实现在 `entries[:cap_per_cat]` 处静默砍掉 6 条购物点，
    报告里毫无痕迹，于是「面板写圈内 104 / 图上只有 98」无人发现。
    """
    per_cat = {
        "shopping": [{**_ll(100, i * 20), "name": f"超市{i}"} for i in range(31)],
        "market": [{**_ll(100, 0), "name": "菜市场A"}],
    }
    out = to_points(per_cat, {}, SCOPE, CENTER, cap_per_cat=25)
    assert len([p for p in out.points if p["category"] == "shopping"]) == 25
    assert out.truncated == [{"category": "shopping", "kept": 25, "dropped": 6}]
    # 未触发的类别不进披露（避免「全类都报 dropped=0」的噪声）
    assert all(t["category"] != "market" for t in out.truncated)


def test_to_points_explicit_cap_zero_discloses_all_dropped():
    """cap=0 → 点位为空，但**全部被丢弃这件事必须被披露**（不能变成静默清空）。"""
    per_cat = {"market": _cat_items("菜市场", [100, 200])}
    out = to_points(per_cat, {}, SCOPE, CENTER, cap_per_cat=0)
    assert out.points == []
    assert out.truncated == [{"category": "market", "kept": 0, "dropped": 2}]


def test_backfill_nearest_minutes():
    stats = [{"category": "medical", "min_minutes": None, "nearest_name": None}]
    per_cat = {
        "medical": [
            {**_ll(100, 0), "name": "诊所近"},
            {**_ll(800, 0), "name": "诊所远"},
            {**_ll(2000, 0), "name": "诊所超圈"},  # field 返回 None
        ]
    }

    def field_fn(pt):
        x = relative_x(pt)
        return None if x > 1500 else x / 75.0  # 线性步行耗时

    def relative_x(pt):
        dx = pt[0] - CENTER[0]
        return dx * 111_320 * math.cos(math.radians(CENTER[1]))

    out = backfill_nearest_minutes(stats, per_cat, field_fn)
    assert out[0]["min_minutes"] == pytest.approx(100 / 75.0, abs=0.1)
    assert out[0]["nearest_name"] == "诊所近"


# ── T4 · POI 归一化与点位化的边界（I8）──────────────────────────────


def _cat_items(cat, xs):
    return [{**_ll(x, 0), "name": f"{cat}{i}"} for i, x in enumerate(xs)]


def test_to_stats_with_degenerate_scope_no_crash_and_zero_coverage():
    """可达区极小时：圈内 0 / 覆盖度 0，但 total 与最近设施仍成立（不得抛、不得伪装成满覆盖）。

    旧版标题是「empty_ring」：`iso15` 圈缺失时传空环。现在**空环在构造 `SpatialScope`
    时就被拒**（见 `test_scope.py::test_from_iso_rejects_empty_isochrones`），
    所以这里退化为「一个有界的极小可达区」——语义相同（圈内必然为空），但不再允许
    「没有可达区」这种自相矛盾的状态流到统计层。
    """
    per_cat = {"market": _cat_items("菜市场", [100, 900, 2000])}
    s = to_stats(per_cat, {}, TINY_SCOPE, CENTER)[0]
    assert s["total"] == 3
    assert s["in_circle"] == 0
    assert s["coverage"] == 0.0
    assert s["nearest_name"] == "菜市场0"
    assert s["min_minutes"] is None  # 由 live 管线回填


def test_to_points_drops_out_of_reach_points():
    """极小可达区 → 返回值**空列表**（不是「两条 in_circle=False 的点」）。

    旧断言：`[p["in_circle"] for p in pts] == [False, False]` —— 圈外点被当成「正常点位」
    交给前端。这正是用户报的「检索出来一堆圈外地点」在接口层的形态。
    """
    per_cat = {"market": _cat_items("菜市场", [100, 900])}
    out = to_points(per_cat, {"market": [None, 4.0]}, TINY_SCOPE, CENTER)
    assert out.points == []
    # 圈内被几何过滤掉**不是截断**：不得报 dropped，否则「截断」这个词会被稀释成噪声
    assert out.truncated == []


def test_to_points_reachable_points_kept_and_out_of_reach_dropped():
    """Q2 本体：同一批 POI 里，圈内的保留、圈外的丢弃（不是全丢也不是全留）。"""
    per_cat = {"market": _cat_items("菜市场", [200, 2000])}
    pts = to_points(per_cat, {"market": [4.0, 9.0]}, SCOPE, CENTER).points
    assert [p["name"] for p in pts] == ["菜市场0"]
    assert pts[0]["minutes"] == 4.0


def test_to_points_tiebreak_is_distance_not_name():
    """同耗时档内的第三排序键是**距中心的距离**，不是名称字母序。

    旧实现按「名称字母序」截断 ⇒ 留下的是「按名字挑的点」而不是「离得近的点」：
    同耗时下 `AAA` 永远排在被截断的那批前面，与「便民可达性」无关。
    """
    per_cat = {
        "market": [
            {**_ll(1200, 0), "name": "AAA-最远"},   # 名称最小但在最后
            {**_ll(200, 0), "name": "ZZZ-最近"},    # 名称最大但在最前
        ]
    }
    pts = to_points(per_cat, {"market": [None, None]}, SCOPE, CENTER).points
    assert [p["name"] for p in pts] == ["ZZZ-最近", "AAA-最远"]


def test_to_points_times_shorter_than_items():
    """耗时列表短于点位列表（分块失败/截断）→ 缺失位次记 None，不得 IndexError。"""
    per_cat = {"medical": _cat_items("诊所", [100, 200, 300, 400])}
    pts = to_points(per_cat, {"medical": [3.0]}, SCOPE, CENTER).points
    assert len(pts) == 4
    assert sorted(p["minutes"] for p in pts if p["minutes"] is not None) == [3.0]
    assert sum(1 for p in pts if p["minutes"] is None) == 3


def test_to_points_missing_time_category():
    """整类没有耗时数据（times_by_cat 未带该 key）→ 全 None 而非 KeyError。"""
    pts = to_points({"finance": _cat_items("银行", [100, 200])}, {}, SCOPE, CENTER).points
    assert [p["minutes"] for p in pts] == [None, None]


def test_to_points_name_falls_back_to_category_label():
    """无名 POI（百度脏数据 / name 为 null）→ 回落类别 label，保证前端气泡有文字。"""
    per_cat = {"market": [{**_ll(100, 0)}, {**_ll(200, 0), "name": None}]}
    pts = to_points(per_cat, {}, SCOPE, CENTER).points
    assert [p["name"] for p in pts] == ["菜市场", "菜市场"]


def test_to_points_ids_unique_across_categories():
    per_cat = {c: _cat_items(c, [100, 200]) for c in ("market", "medical", "education")}
    pts = to_points(per_cat, {}, SCOPE, CENTER).points
    ids = [p["id"] for p in pts]
    assert len(ids) == len(set(ids)) == 6
    assert pts[0]["id"] == "poi-market-0"


def test_to_points_cap_larger_than_input_keeps_all():
    """cap 大于条数 → 全量，不报错，且披露为空（不虚构截断）。"""
    per_cat = {"market": _cat_items("菜市场", [100, 200])}
    out = to_points(per_cat, {}, SCOPE, CENTER, cap_per_cat=999)
    assert len(out.points) == 2
    assert out.truncated == []


def test_default_cap_constant_is_two_hundred():
    """阶段 1.5：默认上限是**唯一共享常量** `POI_CAP_PER_CAT = 200`（§8-D3）。"""
    assert POI_CAP_PER_CAT == 200
    per_cat = {"shopping": _cat_items("超市", list(range(210)))}
    out = to_points(per_cat, {}, SCOPE, CENTER)
    assert out.truncated == [{"category": "shopping", "kept": 200, "dropped": 10}]


def test_collector_side_no_longer_truncates():
    """阶段 1.5 · **采集出口不得截断**（旧 `_CAP_PER_CAT = 25` 已删除）。

    若采集侧也截一次，`poi.total`（采集口径，含圈外）会被「展示上限」压小 ——
    等于让展示层篡改采集事实。数量收敛只允许发生在 `poi.to_points` 一处。
    """
    from app.living_circle import poi_collector as pc

    assert not hasattr(pc, "_CAP_PER_CAT"), "采集侧不应再持有截断常量"
    items = [{"lng": 107.9 + i * 0.001, "lat": 26.57, "name": f"超市{i}"} for i in range(30)]
    assert len(pc.merge_all({"shopping": items})["shopping"]) == 30


def test_to_points_unknown_category_tolerated():
    """未知类别 key：点位化容忍（label 回落为 key 本身）。"""
    pts = to_points({"toilet": [{**_ll(100, 0), "name": "公厕"}]}, {}, SCOPE, CENTER).points
    assert pts[0]["category"] == "toilet" and pts[0]["name"] == "公厕"


def test_to_stats_unknown_category_raises_currently():
    """**记录当前行为 + TODO**：`to_stats` 对未知类别直接 KeyError（与 to_points 的容忍不对称）。

    类别表若与前端/新增域不同步，整份报告在 diagnose 阶段炸掉而不是降级出统计。
    TODO：与 `to_points` 统一为 `CATEGORY_DEFS.get(cat, {})` + 兜底 ideal_circle=1。
    """
    with pytest.raises(KeyError):
        to_stats({"toilet": _cat_items("公厕", [100])}, {}, SCOPE, CENTER)


def test_to_points_lnglat_rounded_to_six():
    """坐标输出固定 6 位小数（报告体积与前端 BMapGL 精度契约）。"""
    pts = to_points({"market": [{**_ll(137.5, -82.25), "name": "A"}]}, {}, SCOPE, CENTER).points
    lng, lat = pts[0]["lnglat"]
    assert (lng, lat) == (round(lng, 6), round(lat, 6))


# ── 阶段 1.2/1.4 · 派生收敛与守恒判据（唯一实现）────────────────────


def test_derive_stats_from_points_single_source():
    """`in_circle`/`coverage` 由 `points` 派生，`total` 保持采集口径不动。"""
    stats = [
        {"category": "shopping", "label": "购物", "total": 31, "in_circle": 31, "coverage": 1.0},
        {"category": "market", "label": "菜市场", "total": 5, "in_circle": 5, "coverage": 1.0},
    ]
    points = [{"category": "shopping"} for _ in range(25)] + [{"category": "market"} for _ in range(5)]
    out = derive_stats_from_points(stats, points)
    by = {s["category"]: s for s in out}
    assert by["shopping"]["in_circle"] == 25  # 截断后实到
    assert by["shopping"]["total"] == 31      # 采集口径**不动**（审查 R1：反算会把 217 塌成 98）
    assert by["market"]["in_circle"] == 5 and by["market"]["total"] == 5


def test_check_poi_conservation_reports_per_category_delta():
    """违规描述必须给出**逐类**差额（只说「不相等」会让排查又回到数点位上）。"""
    bad = {
        "categories": [{"category": "shopping", "in_circle": 31}, {"category": "market", "in_circle": 5}],
        "points": [{"category": "shopping"} for _ in range(25)] + [{"category": "market"} for _ in range(5)],
    }
    issue = check_poi_conservation(bad)
    assert issue is not None
    assert "31" in issue and "25" in issue and "shopping" in issue
    assert check_poi_conservation(
        {"categories": [{"category": "market", "in_circle": 1}], "points": [{"category": "market"}]}
    ) is None


# ── v5 U7-U13 · POI 去重新规则（D3：同名<50m 或 贴脸<10m 才合并）────────

def test_u7_same_name_within_50m_merges():
    """U7：同名、40m → 合并 1 条（同一家店被多关键词重复返回）。"""
    items = [
        {**_ll(100, 0), "name": "金马便利店"},
        {**_ll(140, 0), "name": "金马便利店"},
    ]
    out = dedupe_pois(items)
    assert len(out) == 1


def test_u8_different_names_within_50m_kept():
    """U8：**不同名、40m → 保留 2 条**（金马/瑞霖便利店回归，问题 3 本体）。"""
    items = [
        {**_ll(100, 0), "name": "金马便利店"},
        {**_ll(140, 0), "name": "瑞霖便利店"},
    ]
    out = dedupe_pois(items)
    assert len(out) == 2
    assert {it["name"] for it in out} == {"金马便利店", "瑞霖便利店"}


def test_u9_different_names_within_10m_merges():
    """U9：不同名、8m → 合并 1 条（贴脸同址，店招/别称差异）。"""
    items = [
        {**_ll(100, 0), "name": "金马便利店"},
        {**_ll(108, 0), "name": "瑞霖便利店"},
    ]
    out = dedupe_pois(items)
    assert len(out) == 1


def test_u10_same_name_beyond_50m_kept():
    """U10：同名、80m（连锁店）→ 保留 2 条（不同门面，不是同一家）。"""
    items = [
        {**_ll(100, 0), "name": "美宜佳"},
        {**_ll(180, 0), "name": "美宜佳"},
    ]
    out = dedupe_pois(items)
    assert len(out) == 2


def test_u11_boundary_is_strict_less_than():
    """U11：边界语义严格 < —— 49.9m 同名合并 / 50.1m 同名保留；9.9m 不同名合并 / 10.1m 不同名保留。"""
    same_close = [{**_ll(0, 0), "name": "A店"}, {**_ll(49.9, 0), "name": "A店"}]
    assert len(dedupe_pois(same_close)) == 1
    same_far = [{**_ll(0, 0), "name": "A店"}, {**_ll(50.1, 0), "name": "A店"}]
    assert len(dedupe_pois(same_far)) == 2
    near_close = [{**_ll(0, 0), "name": "A店"}, {**_ll(9.9, 0), "name": "B店"}]
    assert len(dedupe_pois(near_close)) == 1
    near_far = [{**_ll(0, 0), "name": "A店"}, {**_ll(10.1, 0), "name": "B店"}]
    assert len(dedupe_pois(near_far)) == 2


def test_u12_norm_name_fullwidth_space_brackets():
    """U12：名称归一（全角空格/括号）→ 归一后同名合并。"""
    items = [
        {**_ll(100, 0), "name": "金马　便利店（旗舰店）"},
        {**_ll(120, 0), "name": "金马便利店"},
    ]
    out = dedupe_pois(items)
    assert len(out) == 1
    assert norm_name("金马　便利店（旗舰店）") == "金马便利店"


def test_u13_empty_and_single_never_crash():
    """U13：空列表 / 单点去重 → 不抛、原样返回。"""
    assert dedupe_pois([]) == []
    single = {**_ll(100, 0), "name": "独苗便利店"}
    assert dedupe_pois([single]) == [single]


def test_u20_clean_converged_to_new_rule():
    """U20：clean 与 dedupe_pois 同规则（去重收敛单一实现后行为一致，不丢相邻不同名设施）。"""
    items = [
        {**_ll(100, 0), "name": "金马便利店"},
        {**_ll(140, 0), "name": "瑞霖便利店"},   # 40m 不同名 → 保留
        {**_ll(200, 0), "name": "金马便利店"},   # 100m 同名 → 保留（>50m，连锁店）
        {**_ll(300, 0), "name": "金马便利店"},   # 距第 1 条 200m、距第 3 条 100m → 均 >50m → 保留
    ]
    out = clean(items)
    assert len(out) == 4
