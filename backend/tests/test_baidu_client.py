"""M1 · 百度客户端（httpx.MockTransport 注入，无真实网络）：
参数组装 / 响应解析 / 批量矩阵分块 / 韧性重试。"""
import asyncio

import httpx
import pytest

from app.living_circle.baidu_client import MATRIX_CHUNK, BaiduClient
from app.living_circle.request_guard import CallGuard, GuardStats, RATE_LIMIT_STATUS


def _router(routes):
    """构造按「path 子串 + 冒烟」匹配的 MockTransport handler。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, payload in routes:
            if key in url:
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"status": 404, "message": "route-not-mocked"})

    return httpx.MockTransport(handler)


GEOC = {"status": 0, "result": {"location": {"lng": 107.9758, "lat": 26.5734}}}


def _client(routes, guard=None):
    return BaiduClient(ak="test-ak", transport=_router(routes), guard=guard)


def test_geocoding_parses_lnglat():
    c = _client([("/geocoding/v3/", GEOC)])
    out = asyncio_run(c.geocoding("凯里老街"))
    assert out == (107.9758, 26.5734)


def test_geocoding_failure_returns_none():
    c = _client([("/geocoding/v3/", {"status": 401, "message": "invalid ak"})])
    assert asyncio_run(c.geocoding("x")) is None


def test_place_search_normalizes_results():
    payload = {
        "status": 0,
        "results": [
            {"name": "凯里老街菜市场", "location": {"lng": 107.9760, "lat": 26.5740}, "address": "老街"},
            {"name": "东门口早市", "location": {"lng": 107.98, "lat": 26.57}, "address": ""},
        ],
    }
    c = _client([("/place/v2/search", payload)])
    items = asyncio_run(c.place_search("菜市场", (107.9758, 26.5734)))
    assert len(items) == 2
    assert items[0]["name"] == "凯里老街菜市场"
    assert items[0]["lng"] == pytest.approx(107.9760)


def test_route_matrix_chunks_and_parses():
    n = MATRIX_CHUNK + 5  # 触发两次分块
    def handler(request: httpx.Request) -> httpx.Response:
        qp = dict(httpx.QueryParams(request.url.query))
        origins = qp["origins"]
        n_orig = len(origins.split("|"))
        elems = [
            {"status": 0, "duration": {"value": 60 * (i + 1)}}
            if i % 3 != 2 else {"status": 302, "duration": {"value": 0}}
            for i in range(n_orig)
        ]
        return httpx.Response(200, json={"status": 0, "result": {"elements": elems}})

    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=CallGuard(min_interval_s=0))
    origins = [(107.9758, 26.5734), (107.99, 26.59)] * (n // 2)
    out = asyncio_run(c.route_matrix_walking(origins[:n], (107.9758, 26.5734)))
    assert len(out) == n
    assert out[0] == pytest.approx(1.0)  # 60s → 1min
    assert out[2] is None  # 302 失败元素


def test_guard_429_retries_then_succeeds():
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"status": 429, "message": "quota"}  # 前两次触发退避
        return {"status": 0, "result": "ok"}

    guard = CallGuard(max_retries=3, backoff_base_s=0.01, backoff_max_s=0.05)
    resp = asyncio.run(guard.call(work))
    assert resp == {"status": 0, "result": "ok"}
    assert calls["n"] == 3
    assert guard.stats.ok == 1
    assert guard.stats.retried == 2


def test_guard_quota_status_classification():
    guard = CallGuard()
    assert guard._is_biz_error({"status": 0}) is None
    assert guard._is_biz_error({"status": 429}) is not None
    assert guard._is_biz_error({"status": 302}) is not None


def test_guard_stats_success_rate():
    s = GuardStats(ok=8, fail=2)
    assert s.success_rate() == pytest.approx(0.8)
    assert RATE_LIMIT_STATUS.issuperset({401, 403, 429})


def asyncio_run(coro):
    return asyncio.run(coro)