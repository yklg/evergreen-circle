"""U2 · OfflineDataSource：离线估算契约完整 + 复用引擎同构 + 不产可比评分/盲区（覆盖方案 U2-1~U2-7）。"""
import asyncio

from app.living_circle.data_source import CheckParams, OfflineDataSource
from app.living_circle.isochrone import WALK_SPEED_M_PER_MIN  # noqa: F401  (口径同源校验)


def _compute(scene_name="上海市浦东新区陆家嘴", center=None, city="上海市", address="", sample_profile="standard"):
    ds = OfflineDataSource()
    params = CheckParams(scene_name=scene_name, city=city, address=address, center=center, sample_profile=sample_profile)
    return asyncio.run(ds.compute(params))


def test_u2_1_contract_complete():
    r = _compute()
    for k in ["scene", "generated_at", "data_origin", "isochrones", "sampling", "poi", "blindspots", "scores"]:
        assert k in r
    assert r["data_origin"] == "offline"
    assert {z["minutes"] for z in r["isochrones"]} == {5, 10, 15, 20}
    assert r["sampling"]["interpolation"] == "circular_approx"
    assert r["sampling"]["is_scattered"] is False
    assert r["scene"]["center"] == [round(r["scene"]["center"][0], 6), round(r["scene"]["center"][1], 6)]


def test_u2_2_engine_reuse_isomorphic_with_live():
    """与 live 同构：isochrones 字段结构一致 + 面积随分钟单调递增。"""
    r = _compute()
    prev = 0.0
    for z in r["isochrones"]:
        assert set(z.keys()) == {"minutes", "area_km2", "geojson"}
        assert z["geojson"]["type"] == "Polygon"
        assert z["area_km2"] > prev  # 距离模型下大圈必然更大
        prev = z["area_km2"]
    # 采样点可达性自洽（距离模型无不可达）
    for p in r["sampling"]["points"]:
        assert p["reachable"] is True
        assert p["minutes"] is not None and p["minutes"] >= 0


def test_u2_3_no_comparable_score():
    r = _compute()
    assert r["blindspots"] == []
    assert r["scores"]["total"] == 0
    assert "需实时体检" in r["scores"]["note"]
    assert "不可与实时分比较" in r["scores"]["note"]
    assert r["scores"]["triads"] == []
    assert r["scores"]["radar"] == []


def test_u2_4_poi_empty_and_marked():
    r = _compute()
    assert r["poi"] == {"categories": [], "total": 0, "in_circle": 0, "points": []}


def test_u2_5_zero_center_still_contract():
    r = _compute(scene_name="未知名", center=(0.0, 0.0))
    assert r["data_origin"] == "offline"
    assert {z["minutes"] for z in r["isochrones"]} == {5, 10, 15, 20}


def test_u2_6_empty_scene_name_no_crash():
    r = _compute(scene_name="")
    assert r["data_origin"] == "offline"
    assert r["scene"]["name"] == ""


def test_u2_7_deterministic():
    a = _compute()
    b = _compute()
    # 仅 generated_at 时间戳允许差异，其余逐字段相等（无随机）
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b
