"""M1 · 数据源：Fixture 就近匹配 / Live 全链路（stub client） / 缓存生效。"""
import asyncio

from app.living_circle.data_source import CheckParams, FixtureDataSource, LiveDataSource
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat
from app.living_circle.isochrone import IsochroneEngine
from app.living_circle.repository import Repository

KAILI_CENTER = (107.9758, 26.5734)
JINSONG_CENTER = (116.4637, 39.8832)


class StubBaidu:
    """极简 stub：place_search 按关键词返回围绕中心的小簇；route_matrix 用线性步行耗时。"""

    def __init__(self, center, speed=75.0):
        self.center = center
        self.speed = speed
        self.poi_calls = 0
        self.matrix_calls = 0

    def _poi_set(self, query, center) -> list:
        # 每关键词生成 3 个点：中心东北 300m、西南 900m、东 1500m
        pts = []
        for idx, (dx, dy) in enumerate([(300, 300), (-900, -900), (1500, 0)]):
            lng, lat = xy_to_lnglat(center, dx, dy)
            pts.append({"name": f"{query}-{idx}", "lng": round(lng, 6), "lat": round(lat, 6), "address": ""})
        return pts

    async def place_search(self, query, center, radius_m=2000, scope=2, page_size=20):
        self.poi_calls += 1
        return self._poi_set(query, center)

    async def route_matrix_walking(self, origins, destination):
        self.matrix_calls += 1
        return [
            (haversine_m(destination, p) / self.speed) if haversine_m(destination, p) < 2200 else None
            for p in origins
        ]

    async def aclose(self):
        pass


def test_fixture_source_nearby_match():
    ds = FixtureDataSource()
    r = asyncio.run(ds.compute(CheckParams(scene_name="查不到", center=KAILI_CENTER)))
    assert r["scene"]["name"] == "凯里老街"
    r2 = asyncio.run(ds.compute(CheckParams(scene_name="x", center=JINSONG_CENTER)))
    assert r2["scene"]["name"] == "北京劲松"


def test_fixture_source_returns_expected_fixture_data():
    ds = FixtureDataSource()
    r = asyncio.run(ds.compute(CheckParams(scene_name="kaili", center=KAILI_CENTER)))
    assert r["data_origin"] == "fixture_sample"
    assert r["scores"]["total"] == 65
    assert len(r["blindspots"]) == 4
    assert r["sampling"]["interpolation"] == "circular_approx"


def test_live_source_full_pipeline_contract():
    center = KAILI_CENTER
    stub = StubBaidu(center)
    ds = LiveDataSource(ak="stub", client=stub, engine=IsochroneEngine(), repo=Repository())
    params = CheckParams(scene_name="凯里老街", city="贵州·凯里", center=center, mode="quick")
    r = asyncio.run(ds.compute(params))

    # 契约顶层字段
    for k in ["scene", "generated_at", "data_origin", "isochrones", "sampling", "poi", "blindspots", "scores"]:
        assert k in r
    assert r["data_origin"] == "live"
    assert r["scene"]["center"] == [round(center[0], 6), round(center[1], 6)]
    # 4 级等时圈
    assert {z["minutes"] for z in r["isochrones"]} == {5, 10, 15, 20}
    # 8 类 POI
    assert len(r["poi"]["categories"]) == 8
    assert r["poi"]["total"] > 0
    # 评分 0-100 + 三要素 3 条
    assert 0 <= r["scores"]["total"] <= 100
    assert len(r["scores"]["triads"]) == 3
    # 盲区契约
    for b in r["blindspots"]:
        assert b["polygon"]["type"] == "Polygon"
    # 采样
    assert r["sampling"]["interpolation"] == "idw"


def test_live_source_repository_cache_used():
    center = KAILI_CENTER
    stub = StubBaidu(center)
    repo = Repository()
    ds = LiveDataSource(ak="stub", client=stub, engine=IsochroneEngine(), repo=repo)
    params = CheckParams(scene_name="凯里老街", center=center, mode="quick")
    asyncio.run(ds.compute(params))
    calls_after_first = (stub.poi_calls, stub.matrix_calls)
    asyncio.run(ds.compute(params))  # 同场景 → 缓存命中，不重复采集
    assert (stub.poi_calls, stub.matrix_calls) == calls_after_first


def test_get_data_source_factory_modes():
    from app.living_circle.data_source import get_data_source

    fixture = get_data_source("fixture")
    assert isinstance(fixture, FixtureDataSource)
    live = get_data_source("live", ak="x")
    assert isinstance(live, LiveDataSource)