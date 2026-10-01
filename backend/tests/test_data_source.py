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

    async def place_search(self, query, center, radius_m=2000, scope=2, page_size=20, max_pages=1):
        self.poi_calls += 1
        return self._poi_set(query, center)

    async def _measure_matrix(self, travel_mode, origins, destination, chunk_size=None):
        """阶段 3：通用矩阵方法（stub 实现）。"""
        self.matrix_calls += 1
        return [
            round((haversine_m(destination, p) / self.speed), 1) if haversine_m(destination, p) < 2200 else None
            for p in origins
        ]

    async def measure_matrix(self, travel_mode, origins, destination):
        """公开测时入口 —— `live_forensic_steps` 只认这一个（与真实 `BaiduClient` 同面）。

        ⚠️ 补齐它不是为了迁就实现：片 0 之前 pipeline 走公开、`LiveDataSource.compute`
        走私有，两份 stub 各按「自己那份编排」挑方法实现 ⇒ 这个 fake 一直比真客户端少一面。
        收拢成一份编排后统一走公开面，缺这面的 fake 就在真接缝上断。
        """
        return await self._measure_matrix(travel_mode, origins, destination)

    async def aclose(self):
        pass


def test_fixture_source_nearby_match():
    ds = FixtureDataSource()
    r = asyncio.run(ds.compute(CheckParams(scene_name="查不到", center=KAILI_CENTER)))
    assert r["scene"]["name"] == "凯里老街"
    r2 = asyncio.run(ds.compute(CheckParams(scene_name="x", center=JINSONG_CENTER)))
    assert r2["scene"]["name"] == "北京劲松"


def test_fixture_source_returns_expected_fixture_data():
    """M5：内置快照为真实百度实跑数据（live / IDW）。

    断言的是**快照性质与结构自洽**，不是具体分值：旧版把坐标钉成
    `scores.total == 58.5` / `blindspots == 3`，用真实 AK 重算夹具后立刻假红，
    而它真正想守的是「fixture 是真实实跑产物、契约字段完整」。
    """
    ds = FixtureDataSource()
    r = asyncio.run(ds.compute(CheckParams(scene_name="kaili", center=KAILI_CENTER)))
    assert r["data_origin"] == "live"
    assert r["sampling"]["interpolation"] == "idw"
    assert [z["minutes"] for z in r["isochrones"]] == [5, 10, 15, 20]
    assert 0 <= r["scores"]["total"] <= 100
    assert len(r["poi"]["categories"]) == 8
    assert len(r["poi"]["points"]) > 0
    # 空间口径举证（Q1/Q2 可判据化的最小集，必须随快照一起冻结）
    cal = r["caliber"]
    assert cal["collect_radius_m"] >= cal["reach_circumradius_m"] * 0.999
    assert cal["cells_judged"] + cal["cells_unknown"] == cal["cells_inside"]


def test_live_source_full_pipeline_contract():
    center = KAILI_CENTER
    stub = StubBaidu(center)
    ds = LiveDataSource(ak="stub", client=stub, engine=IsochroneEngine(), repo=Repository())
    params = CheckParams(scene_name="凯里老街", city="贵州·凯里", center=center, sample_profile="quick")
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
    # M5.1：逐 POI 点位（真实坐标，BMapGL 渲染契约）——live 管线必须产出
    pts = r["poi"]["points"]
    assert len(pts) > 0
    for p in pts:
        assert set(p.keys()) == {"id", "name", "category", "lnglat", "minutes", "in_circle"}
        assert p["id"].startswith("poi-")
        assert len(p["lnglat"]) == 2
        assert isinstance(p["lnglat"][0], float)
        assert isinstance(p["in_circle"], bool)
    # 每类截断 ≤ 25
    from collections import Counter

    for cat, n in Counter(p["category"] for p in pts).items():
        assert n <= 25
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
    params = CheckParams(scene_name="凯里老街", center=center, sample_profile="quick")
    asyncio.run(ds.compute(params))
    calls_after_first = (stub.poi_calls, stub.matrix_calls)
    asyncio.run(ds.compute(params))  # 同场景 → 缓存命中，不重复采集
    assert (stub.poi_calls, stub.matrix_calls) == calls_after_first


def test_get_data_source_factory_modes():
    """v2 路由：fixture 显式 → Fixture；有 AK → Caching(Live)；无 AK → Caching(Offline)。"""
    from app.living_circle.data_source import CachingDataSource, OfflineDataSource, get_data_source

    fixture = get_data_source("fixture")
    assert isinstance(fixture, FixtureDataSource)
    live = get_data_source("live", ak="x")
    assert isinstance(live, CachingDataSource)
    assert isinstance(live.source, LiveDataSource)
    offline = get_data_source("live", ak="")
    assert isinstance(offline, CachingDataSource)
    assert isinstance(offline.source, OfflineDataSource)
    assert offline.read_only is True  # 离线结果不写回 live 缓存


# 补点注解的**载体**。⚠️ 为什么要自带：`ev-1` 重刷后两份出厂快照的实测盲区都是 0
# （劲松判定覆盖率 9.1%→21.2%，新判得的格三类皆有据），于是原来那句
# `assert bs, "劲松快照应至少含 1 处盲区"` 会变成"永远拿不到样本"—— 若只是把它删掉，
# 整条注解链路（severity/gap/fixes/reach/affected）就在无人察觉的情况下空转了。
# 载体结构照出厂快照：只有 `id/center/radius_m/missing_facilities/nearest/polygon`
# 是**未注解**的原始盲区，正好是要交给 `annotate_blindspots` 补齐的那副输入。
SYN_BLINDSPOT: dict = {
    "id": "bs-合成载体-1",
    "center": [116.4637, 39.8832],
    "radius_m": 1000,
    "missing_facilities": ["菜市场", "小学"],
    "nearest": [
        {"facility": "market", "name": "载体用最近菜市", "distance_m": 1450.0, "direction": "正东"},
        {"facility": "primary", "name": "载体用最近小学", "distance_m": 1320.0, "direction": "正南"},
    ],
    "polygon": {
        "type": "Polygon",
        "coordinates": [[
            [116.4570, 39.8790], [116.4680, 39.8790], [116.4680, 39.8870],
            [116.4570, 39.8870], [116.4570, 39.8790],
        ]],
    },
}


def _jinsong_with_carrier() -> dict:
    """劲松快照 + 一枚未注解的合成盲区（出厂快照若有真盲区，一并留在里面受同样的检）。"""
    import copy as _copy

    ds = FixtureDataSource()
    r = asyncio.run(ds.compute(CheckParams(scene_name="jing", center=JINSONG_CENTER)))
    out = _copy.deepcopy(r)
    out["blindspots"] = list(out.get("blindspots") or []) + [_copy.deepcopy(SYN_BLINDSPOT)]
    return out


def test_fixture_blindspots_annotated_with_new_fields():
    """契约文档 §8：演示态由后端归一化补齐盲区新字段（不手编 JSON）。

    守护：severity∈三枚举、gap∈[0,1]、fixes 目标不重复且 priority 连续唯一、
    reach.isochrone_based 为 true（fixture 有实测采样点）、affected 为诚实 proxy。
    """
    from app.living_circle.assemble import annotate_blindspots

    r = _jinsong_with_carrier()
    raw = r["blindspots"][-1]
    assert not {"severity", "fixes"} & set(raw), "合成载体必须是一副未注解的原始输入"
    out = annotate_blindspots(r)
    bs = out["blindspots"]
    assert len(bs) == len(r["blindspots"]), "annotate 不得增删盲区"
    assert bs, "合成载体失效：一条样本都没有，本用例等于没跑"
    priorities: set = set()
    for b in bs:
        assert b["severity"] in {"heavy", "medium", "light"}
        assert 0.0 <= b["gap_score"] <= 1.0
        assert {"severity", "gap_score", "fixes", "reach", "affected"} <= set(b.keys())
        # reach 应复用实测采样点 IDW → isochrone_based=true（R3）
        assert b["reach"]["isochrone_based"] is True
        assert "real_walk_min" in b["reach"]
        # fixes 目标不重复
        facs = [f["facility"] for f in b["fixes"]]
        assert len(facs) == len(set(facs))
        for f in b["fixes"]:
            assert isinstance(f["priority"], int) and f["priority"] >= 1
            priorities.add(f["priority"])
            assert f["strategy"] in {"mobile_service", "reroute", "build"}
        # affected 为诚实代理（非空采样 → proxy，非 null）
        assert b["affected"] is not None
        assert b["affected"]["provenance"] == "proxy"
    assert priorities == set(range(1, len(priorities) + 1)), "fixes.priority 须从 1 连续唯一"


def test_annotate_blindspots_offline_null_affected():
    """R4：无采样点的报告（离线/缺 sampling）→ affected=null、reach 降级 nearest/80。"""
    import copy as _copy

    from app.living_circle.assemble import annotate_blindspots

    stripped = _copy.deepcopy(_jinsong_with_carrier())
    stripped["sampling"]["points"] = []  # 模拟离线：无采样
    out = annotate_blindspots(stripped)
    for b in out["blindspots"]:
        # R4：无采样 → affected=null，不抛伪代理数
        assert b["affected"] is None
        # reach 降级 isochrone_based=false（无实测采样，不能谎称等时圈实测）
        assert b["reach"]["isochrone_based"] is False