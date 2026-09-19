"""M1 · POI：名称归一 / 清洗去重（50m 聚簇）/ 类别统计 / 耗时回填。"""
import math

import pytest

from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import (
    backfill_nearest_minutes,
    clean,
    norm_name,
    to_stats,
)

CENTER = (107.9758, 26.5734)
_R = 1600.0


def _ll(x, y):
    return {"lng": xy_to_lnglat(CENTER, x, y)[0], "lat": xy_to_lnglat(CENTER, x, y)[1]}


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
    # 15min 圈近似为半径 1500m 的方形评分环（用正方形代圆，几何正确性由 isochrone 保证）
    ring = [
        xy_to_lnglat(CENTER, -1500, -1500),
        xy_to_lnglat(CENTER, 1500, -1500),
        xy_to_lnglat(CENTER, 1500, 1500),
        xy_to_lnglat(CENTER, -1500, 1500),
    ]
    per_cat = {
        "market": [
            {**_ll(100, 0), "name": "菜市场A"},
            {**_ll(1000, 1000), "name": "菜市场B"},  # 对角 1414m 圈内
            {**_ll(2000, 0), "name": "菜市场C"},  # 圈外
        ]
    }
    stats = to_stats(per_cat, {}, ring, CENTER)
    s = stats[0]
    assert s["category"] == "market"
    assert s["in_circle"] == 2
    assert s["coverage"] == pytest.approx(2 / 3, abs=0.001)  # ideal=3 → min(1, 2/3)
    assert s["nearest_name"] == "菜市场A"


def test_to_stats_coverage_capped_at_one():
    ring = [xy_to_lnglat(CENTER, -1500, -1500), xy_to_lnglat(CENTER, 1500, -1500), xy_to_lnglat(CENTER, 1500, 1500), xy_to_lnglat(CENTER, -1500, 1500)]
    per_cat = {"shopping": [{**_ll(100, i * 100), "name": f"超市{i}"} for i in range(6)]}
    stats = to_stats(per_cat, {}, ring, CENTER)
    assert stats[0]["coverage"] == 1.0  # ideal=3 → 6/3 封顶 1


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
        import math

        dx = pt[0] - CENTER[0]
        return dx * 111_320 * math.cos(math.radians(CENTER[1]))

    out = backfill_nearest_minutes(stats, per_cat, field_fn)
    assert out[0]["min_minutes"] == pytest.approx(100 / 75.0, abs=0.1)
    assert out[0]["nearest_name"] == "诊所近"