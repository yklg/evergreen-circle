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
    backfill_nearest_minutes,
    clean,
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
    """M5.1 · 点位契约：字段齐全 / 只留圈内 / 每类截断。

    旧版此处断言 `market == ["圈内A", "圈内B", "圈外A"]` 且 `圈外A.in_circle is False`
    —— 那是 Q2 缺陷的「接口化」（把圈外点交给前端过滤）。现在圈外点**在源头被丢弃**。
    """
    per_cat = {
        "market": [
            {**_ll(2000, 0), "name": "圈外A"},   # 圈外 → 不应出现在返回值里
            {**_ll(100, 0), "name": "圈内A"},    # 圈内有耗时 → 最前
            {**_ll(200, 0), "name": "圈内B"},    # 圈内有耗时 → 次前
        ],
        "medical": [{**_ll(100, i * 50), "name": f"诊所{i}"} for i in range(30)],  # 30 条 → 截断 25
    }
    times = {
        "market": [None, 5.2, 6.1],
        "medical": [float(i) for i in range(30)],
    }
    pts = to_points(per_cat, times, SCOPE, CENTER)
    # 契约字段
    for p in pts:
        assert set(p.keys()) == {"id", "name", "category", "lnglat", "minutes", "in_circle"}
        assert p["in_circle"] is True
    # 圈外被丢弃；圈内按耗时升序
    market = [p for p in pts if p["category"] == "market"]
    assert [p["name"] for p in market] == ["圈内A", "圈内B"]
    assert market[0]["minutes"] == 5.2
    # 截断：medical 30 条 → 25
    medical = [p for p in pts if p["category"] == "medical"]
    assert len(medical) == 25


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
    pts = to_points(per_cat, {"market": [None, 4.0]}, TINY_SCOPE, CENTER)
    assert pts == []


def test_to_points_reachable_points_kept_and_out_of_reach_dropped():
    """Q2 本体：同一批 POI 里，圈内的保留、圈外的丢弃（不是全丢也不是全留）。"""
    per_cat = {"market": _cat_items("菜市场", [200, 2000])}
    pts = to_points(per_cat, {"market": [4.0, 9.0]}, SCOPE, CENTER)
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
    pts = to_points(per_cat, {"market": [None, None]}, SCOPE, CENTER)
    assert [p["name"] for p in pts] == ["ZZZ-最近", "AAA-最远"]


def test_to_points_times_shorter_than_items():
    """耗时列表短于点位列表（分块失败/截断）→ 缺失位次记 None，不得 IndexError。"""
    per_cat = {"medical": _cat_items("诊所", [100, 200, 300, 400])}
    pts = to_points(per_cat, {"medical": [3.0]}, SCOPE, CENTER)
    assert len(pts) == 4
    assert sorted(p["minutes"] for p in pts if p["minutes"] is not None) == [3.0]
    assert sum(1 for p in pts if p["minutes"] is None) == 3


def test_to_points_missing_time_category():
    """整类没有耗时数据（times_by_cat 未带该 key）→ 全 None 而非 KeyError。"""
    pts = to_points({"finance": _cat_items("银行", [100, 200])}, {}, SCOPE, CENTER)
    assert [p["minutes"] for p in pts] == [None, None]


def test_to_points_name_falls_back_to_category_label():
    """无名 POI（百度脏数据 / name 为 null）→ 回落类别 label，保证前端气泡有文字。"""
    per_cat = {"market": [{**_ll(100, 0)}, {**_ll(200, 0), "name": None}]}
    pts = to_points(per_cat, {}, SCOPE, CENTER)
    assert [p["name"] for p in pts] == ["菜市场", "菜市场"]


def test_to_points_ids_unique_across_categories():
    per_cat = {c: _cat_items(c, [100, 200]) for c in ("market", "medical", "education")}
    pts = to_points(per_cat, {}, SCOPE, CENTER)
    ids = [p["id"] for p in pts]
    assert len(ids) == len(set(ids)) == 6
    assert pts[0]["id"] == "poi-market-0"


def test_to_points_cap_zero_and_larger_than_input():
    """cap=0 → 空（调用方可显式关缺点位）；cap 大于条数 → 全量，不报错。"""
    per_cat = {"market": _cat_items("菜市场", [100, 200])}
    assert to_points(per_cat, {}, SCOPE, CENTER, cap_per_cat=0) == []
    assert len(to_points(per_cat, {}, SCOPE, CENTER, cap_per_cat=999)) == 2


def test_to_points_unknown_category_tolerated():
    """未知类别 key：点位化容忍（label 回落为 key 本身）。"""
    pts = to_points({"toilet": [{**_ll(100, 0), "name": "公厕"}]}, {}, SCOPE, CENTER)
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
    pts = to_points({"market": [{**_ll(137.5, -82.25), "name": "A"}]}, {}, SCOPE, CENTER)
    lng, lat = pts[0]["lnglat"]
    assert (lng, lat) == (round(lng, 6), round(lat, 6))
