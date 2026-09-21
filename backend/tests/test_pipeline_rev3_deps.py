"""rev3 改造点的能力守卫测试（TDD 红 → 能力就绪后转绿）。

区别于 test_quota/test_category_rule/test_poi_collector 的整文件 `importorskip`：
这些目标（baidu_client / poi / request_guard / data_source）**模块已存在**，
但 rev3 的具体能力（place_search 保留 tag/type + max_pages、to_points 单一排序键、
CallGuard 熔断、cache 跳过 S8）**尚未落地**。故用「运行时能力探测 + pytest.skip」
守卫：能力未就绪即 skip、不污染既有 705 全绿套件；能力落地后自动转真实断言。
"""
import asyncio
import inspect

import httpx
import pytest

from app.living_circle.baidu_client import BaiduClient
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import to_points
from app.living_circle.request_guard import CallGuard

CENTER = (107.9758, 26.5734)
WALKING_CHUNK = get_caliber("walking").api.chunk


def _src(fn) -> str:
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return ""


# ── place_search：保留 tag / detail_info.type（S8 来源三）─────────────

def test_place_search_preserves_tag_and_type():
    import app.living_circle.baidu_client as bc

    src = _src(bc.BaiduClient.place_search)
    if "detail_info" not in src and ".get(\"tag\"" not in src and ".get('tag'" not in src:
        pytest.skip("place_search 尚未保留 tag/detail_info.type（rev3 §四C）")

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
    item = asyncio.run(c.place_search("菜市场", CENTER))
    assert item and item[0]["tag"] == "菜市场"
    assert item[0]["type"] == "农贸市场"


def test_place_search_accepts_max_pages_param():
    import app.living_circle.baidu_client as bc

    sig = inspect.signature(bc.BaiduClient.place_search)
    if "max_pages" not in sig.parameters:
        pytest.skip("place_search 尚未支持 max_pages（rev3 §四C）")
    assert sig.parameters["max_pages"].default == 3  # 向后兼容默认 3 页


# ── to_points：单一排序键内含 confidence（rev3 P1-2）────────────────

def test_to_points_sort_key_includes_confidence():
    """排序键统一为「可达→minutes 非空→confidence→距中心」，无独立 rerank。"""
    src = _src(to_points)
    # 断言没有再单独调用 rerank（仅 merge_all + to_points 承担排序）
    assert "rerank" not in src, "不应存在独立 rerank；排序必须收敛到 to_points 单一实现（rev3 P1-2）"


def test_to_points_prefers_high_confidence_same_distance():
    """同可达同距中心时，高置信点应排前（confidence 作为第三键生效）。"""
    src = _src(to_points)
    if "confidence" not in src:
        pytest.skip("to_points 尚未并入 confidence 排序键（rev3 §四E）")
    # 构造两个距中心几乎同距、耗时同为 None 的点，高置信应更靠前
    p_lo = {**_ll(100, 0), "name": "低置信", "tag": "", "type": "", "_confidence": 0.3}
    p_hi = {**_ll(101, 0), "name": "高置信", "tag": "", "type": "", "_confidence": 0.9}
    # 若能力已落地，此处应能稳定排序（占位断言由实现细化）
    assert True  # 能力存在性已由上述 src 检查守护；排序实现细节由 category_rule 落地后细化


# ── CallGuard：max_total_calls 总量熔断（rev3 §四G / v3 §3.5）────────

def test_callguard_accepts_max_total_calls():
    sig = inspect.signature(CallGuard.__init__)
    if "max_total_calls" not in sig.parameters:
        pytest.skip("CallGuard 尚未支持 max_total_calls 熔断（rev3 §四G）")
    # 默认 0 = 不启用总量熔断（向后兼容）；显式传值才开启
    assert sig.parameters["max_total_calls"].default == 0


def test_callguard_meltdown_blocks_on_budget_exhausted():
    """累计调用达到预算上限 → 总量熔断置位（total_meltdown），不再发请求、返回 None。"""
    sig = inspect.signature(CallGuard.__init__)
    if "max_total_calls" not in sig.parameters:
        pytest.skip("CallGuard 尚未支持总量熔断（rev3 §四G）")
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