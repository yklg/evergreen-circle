"""U1 · OfflineGeocoder：地名→坐标 / 逆地理（T1/A2，覆盖方案 U1-1~U1-9）。"""
import json

import pytest

from app.living_circle.geo_index.offline_geocoder import OfflineGeocoder


def _geo():
    return OfflineGeocoder()


def test_u1_1_exact_district_hit():
    hits = _geo().search("上海市浦东新区")
    assert hits
    hit = hits[0]
    assert hit.name == "浦东新区"
    assert hit.path[0] == "上海市"
    assert hit.path[1] == "上海市"
    assert hit.center and len(hit.center) == 2
    # 区县中心（非兜底近似）
    assert hit.approximate == ""


def test_u1_2_full_path_search():
    hits = _geo().search("上海市 浦东新区")
    assert hits
    assert hits[0].path[:2] == ["上海市", "上海市"]


def test_u1_3_detail_address_with_district():
    hits = _geo().search("上海市浦东新区陆家嘴街道")
    assert hits
    assert hits[0].name == "浦东新区"
    assert hits[0].center  # 命中区县中心（近似标注，调用方按区县中心兜底）


def test_u1_4_ambiguous_district_returns_collection():
    hits = _geo().search("朝阳区")
    names = {(h.path[0], h.name) for h in hits}
    # 北京朝阳 / 长春朝阳 等并列候选（同名消歧依赖调用方携带 path）
    assert len(hits) >= 2
    assert ("北京市", "朝阳区") in names
    assert ("吉林省", "朝阳区") in names
    for h in hits:
        assert len(h.path) == 3


def test_u1_5_unknown_place_returns_empty():
    assert _geo().search("不存在的社区xyz") == []


@pytest.mark.parametrize("q", ["", "   ", None])
def test_u1_6_empty_or_none_query(q):
    assert _geo().search(q) == []


def test_u1_7_missing_data_file_falls_back_empty(tmp_path):
    geo = OfflineGeocoder(data_path=tmp_path / "nope.json")
    assert geo.search("上海市") == []
    assert geo.reverse(121.4, 31.2) is None


def test_u1_8_reverse_geocode_hit():
    hit = _geo().reverse(121.47, 31.23)  # 上海市中心附近
    assert hit is not None
    assert hit.path[0] == "上海市"
    assert hit.approximate == "最近区县近似"


def test_u1_9_reverse_outside_bounds():
    # 远离任何区县中心 → 仍返回最近（近似）；极端经纬度不抛错
    hit = _geo().reverse(180.0, 0.0)
    assert hit is None or hit.center


def test_u1_city_level_fallback():
    """市名命中：市中心或省级近似（区县中心缺失时的降级链）。"""
    hits = _geo().search("贵阳市")
    assert hits
    h = hits[0]
    assert h.name == "贵阳市"
    assert h.center


def test_index_built_from_committed_asset():
    """区划数据资产随仓库提交：省≥34、区县≥3000、含中心坐标区县≥2000（T1 生成产物守护）。"""
    geo = _geo()
    assert len(geo._provinces) >= 34
    n_dist = sum(len(c.get("districts", [])) for p in geo._provinces for c in p.get("cities", []))
    n_center = sum(1 for it in geo._index if it["center"])
    assert n_dist >= 3000
    assert n_center >= 2000
