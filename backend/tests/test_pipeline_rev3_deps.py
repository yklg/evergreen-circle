"""rev3 改造点的能力守卫测试。

**本文件的形态变更（计划 v4 阶段 0-d）**：原来 5 条用例用「运行时能力探测 + `pytest.skip`」
守卫，理由是 rev3 的能力（place_search 保留 tag/type + max_pages、to_points 单一排序键、
CallGuard 总量熔断）尚未落地。实测**这五项都已接线**：
`baidu_client.py:138` 传 `max_total_calls=quota.total_calls_hard_ceiling()`、
`poi_collector.py:411/486/510` 逐处显式传 `max_pages`、`to_points` 的排序键含 `_confidence`。
于是那 5 个 skip 从「防污染套件」变成了**空转守卫** —— 能力若被回退，它们不会红，只会
继续 skip（这正是 skip 形态的固有代价）。故全部转为真实断言，删除能力探测。

同批修掉本文件的一处假绿：`test_to_points_prefers_high_confidence_same_distance`
原先以 `assert True` 收尾（"能力存在性已由 src 检查守护"）—— 源文本里出现一个词并不等于
排序真的按它发生，现在改为对产出点位排序。
"""
import asyncio
import inspect

import httpx

from app.living_circle.baidu_client import BaiduClient
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import to_points
from app.living_circle.request_guard import CallGuard
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)
WALKING_CHUNK = get_caliber("walking").api.chunk


def _src(fn) -> str:
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return ""


def _square(half: float):
    """以 CENTER 为中心的 ±half 米方环（与 `test_poi.py` 同一手法造 scope）。"""
    return [xy_to_lnglat(CENTER, dx, dy) for dx, dy in
            ((-half, -half), (half, -half), (half, half), (-half, half))]


def _scope(ring, *, reach_min: float = 20.0, study_radius_m: float = 2500.0) -> SpatialScope:
    zone = {"minutes": reach_min, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(
        get_caliber("walking"), CENTER, study_radius_m, zone
    )


# ── place_search：保留 tag / detail_info.type（S8 来源三）─────────────

def test_place_search_preserves_tag_and_type():
    """rev3 §四C 已接线：`tag` 与 `detail_info.type` 必须原样交回采集侧。"""
    payload = {
        "status": 0,
        "results": [
            {
                "name": "凯里老街菜市场",
                "location": {"lng": 107.9760, "lat": 26.5740},
                "address": "老街",
                "tag": "菜市场",
                "detail_info": {"type": "农贸市场"},
            },
        ],
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=CallGuard(min_interval_s=0))
    out = asyncio.run(c.place_search("菜市场", CENTER, radius_m=2000))
    assert out.items and out.items[0]["tag"] == "菜市场"
    assert out.items[0]["type"] == "农贸市场"


def test_place_search_accepts_max_pages_param():
    """rev3 §四C：页深由调用方决定，默认 3 保向后兼容。"""
    sig = inspect.signature(BaiduClient.place_search)
    assert sig.parameters["max_pages"].default == 3  # 向后兼容默认 3 页


# ── to_points：单一排序键内含 confidence（rev3 P1-2）────────────────

def test_to_points_sort_key_includes_confidence():
    """排序键统一为「可达→minutes 非空→confidence→距中心」，无独立 rerank。"""
    src = _src(to_points)
    # 断言没有再单独调用 rerank（仅 merge_all + to_points 承担排序）
    assert "rerank" not in src, "不应存在独立 rerank；排序必须收敛到 to_points 单一实现（rev3 P1-2）"


def test_to_points_prefers_high_confidence_same_distance():
    """同可达、同耗时空缺时，高置信点必须排在前 —— confidence 是生效的第三键。

    两点相距 1m 且**低置信先入列**：若排序只吃输入序或只吃距离，低置信都会在前，
    于是本用例真正判别的是「第三键有没有接上」，而不是源文本里有没有那个词。
    """
    per_cat = {
        "market": [
            {**_ll(100, 0), "name": "低置信点", "_confidence": 0.3},
            {**_ll(101, 0), "name": "高置信点", "_confidence": 0.9},
        ],
    }
    out = to_points(per_cat, {"market": [None, None]}, _scope(_square(1500.0)), CENTER)
    names = [p["name"] for p in out.points if p["category"] == "market"]
    assert names[0].startswith("高置信"), (
        f"同距离下 confidence 没有参与排序 ⇒ 点位回到「按输入序/按名字挑」：{names}"
    )


# ── CallGuard：max_total_calls 总量熔断（rev3 §四G / v3 §3.5）────────

def test_callguard_accepts_max_total_calls():
    """rev3 §四G 已接线：默认 0 = 不启用（向后兼容），显式传值才开启总量熔断。"""
    sig = inspect.signature(CallGuard.__init__)
    assert sig.parameters["max_total_calls"].default == 0


def test_callguard_meltdown_blocks_on_budget_exhausted():
    """累计调用达到预算上限 → 总量熔断置位（total_meltdown），不再发请求、返回 None。"""
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return {"status": 0, "result": "ok"}

    guard = CallGuard(min_interval_s=0, max_retries=0, max_total_calls=2)
    for _ in range(5):
        asyncio.run(guard.call(work))
    assert calls["n"] == 2  # 熔断后不再发请求
    assert guard.total_meltdown is True

    # 熔断是独立的「总量耗尽」语义，与「配额类错误」区分（quota_blocked 仍 False）
    assert guard.quota_blocked is False


# ── cache 短路：S8 扩词不进（rev3 §2.6 / 用例 25）────────────────────

def test_cache_hit_skips_expansion_zero_baidu_calls():
    """复用 `test_data_source` 已全链路验证的 StubBaidu 契约，避免自造残缺 stub。"""
    from app.living_circle.data_source import CheckParams, LiveDataSource
    from app.living_circle.isochrone import IsochroneEngine
    from app.living_circle.repository import Repository

    class StubBaidu:
        """镜像 test_data_source.py 的成熟 stub：place_search 计数 + 通用矩阵测时。"""

        def __init__(self, center, speed=75.0):
            self.center = center
            self.speed = speed
            self.poi_calls = 0

        def _poi_set(self, query, center) -> list:
            pts = []
            for idx, (dx, dy) in enumerate([(300, 300), (-900, -900), (1500, 0)]):
                lng, lat = xy_to_lnglat(center, dx, dy)
                pts.append({"name": f"{query}-{idx}", "lng": round(lng, 6), "lat": round(lat, 6), "address": ""})
            return pts

        async def place_search(self, query, center, radius_m=2000, scope=2, page_size=20, max_pages=1):
            self.poi_calls += 1
            return self._poi_set(query, center)

        async def _measure_matrix(self, travel_mode, origins, destination, chunk_size=None):
            from app.living_circle.geo_utils import haversine_m

            return [
                round((haversine_m(destination, p) / self.speed), 1) if haversine_m(destination, p) < 2200 else None
                for p in origins
            ]

        async def aclose(self):
            pass

    stub = StubBaidu(CENTER)
    ds = LiveDataSource(ak="stub", client=stub, engine=IsochroneEngine(), repo=Repository())
    params = CheckParams(scene_name="凯里老街", center=CENTER, sample_profile="quick")
    asyncio.run(ds.compute(params))
    first = stub.poi_calls
    asyncio.run(ds.compute(params))  # 同场景 → 缓存命中
    assert stub.poi_calls == first  # 命中 30 天缓存，连 S8 扩词都不进、百度零新增调用


def _ll(x, y):
    return {"lng": xy_to_lnglat(CENTER, x, y)[0], "lat": xy_to_lnglat(CENTER, x, y)[1]}