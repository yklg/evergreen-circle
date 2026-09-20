"""M1 · 百度客户端（httpx.MockTransport 注入，无真实网络）：
参数组装 / 响应解析 / 批量矩阵分块 / 韧性重试。"""
import asyncio

import httpx
import pytest

from app.living_circle.baidu_client import BaiduClient
from app.living_circle.caliber import get_caliber
from app.living_circle.request_guard import CallGuard, GuardStats, RATE_LIMIT_STATUS

# 步骤 3：chunk 从 caliber 读取（walking=100）
WALKING_CHUNK = get_caliber("walking").api.chunk


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


# ── 逆地理：city 字段必须真的接线（阶段 2）──────────────────────────
# 历史实现返回 {"name": …, "city": ""} —— city 恒为空串，契约字段声明了却从未填。
# 后果：城市只能由调用方去别处猜（前端拿「当前展示报告」的城市）→ 名/坐标/城市三源不一，
# 实测产出「名称=北京劲松 / 中心=昆明 / 城市=北京·朝阳」的自相矛盾报告。

REV_GEO = {
    "status": 0,
    "result": {
        "formatted_address": "贵州省黔东南苗族侗族自治州凯里市西门街道",
        "addressComponent": {"province": "贵州省", "city": "黔东南苗族侗族自治州", "district": "凯里市"},
    },
}

# 直辖市：百度把 city 留空、只在 province 里给市名 —— 必须回落，否则城市又一次为空
REV_GEO_MUNICIPALITY = {
    "status": 0,
    "result": {
        "formatted_address": "北京市朝阳区劲松街道",
        "addressComponent": {"province": "北京市", "city": "", "district": "朝阳区"},
    },
}


def test_reverse_geocoding_extracts_city_and_district():
    c = _client([("/reverse_geocoding/v3/", REV_GEO)])
    out = asyncio_run(c.reverse_geocoding((107.9758, 26.5734)))
    assert out is not None
    assert out["city"] == "黔东南苗族侗族自治州", "city 必须来自 addressComponent，不得恒为空串"
    assert out["district"] == "凯里市"
    assert out["province"] == "贵州省"
    assert out["name"].startswith("贵州省黔东南")


def test_reverse_geocoding_municipality_falls_back_to_province():
    """直辖市（city 为空）必须回落 province —— 否则「北京」的城市字段又是空的。"""
    c = _client([("/reverse_geocoding/v3/", REV_GEO_MUNICIPALITY)])
    out = asyncio_run(c.reverse_geocoding((116.4637, 39.8832)))
    assert out is not None
    assert out["city"] == "北京市"


def test_reverse_geocoding_failure_returns_none():
    c = _client([("/reverse_geocoding/v3/", {"status": 401, "message": "invalid ak"})])
    assert asyncio_run(c.reverse_geocoding((1.0, 2.0))) is None


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
    n = WALKING_CHUNK + 5  # 触发两次分块
    def handler(request: httpx.Request) -> httpx.Response:
        qp = dict(httpx.QueryParams(request.url.query))
        origins = qp["origins"]
        n_orig = len(origins.split("|"))
        # routematrix/v2 真实结构：result 为行数组，行内直接带 duration/restrictions_status
        rows = [
            {"distance": {"text": f"{i + 1}米", "value": (i + 1)},
             "duration": {"text": f"{i + 1}分钟", "value": 60 * (i + 1)},
             "restrictions_status": 0, "retrograde_dist": 0}
            if i % 3 != 2 else {"distance": {"value": 0}, "duration": {"value": 0},
                                "restrictions_status": 302, "retrograde_dist": 0}
            for i in range(n_orig)
        ]
        return httpx.Response(200, json={"status": 0, "result": rows})

    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=CallGuard(min_interval_s=0))
    origins = [(107.9758, 26.5734)] * n  # 确保正好 n 个 origin
    out = asyncio_run(c.route_matrix_walking(origins, (107.9758, 26.5734)))
    assert len(out) == n
    assert out[0] == pytest.approx(1.0)  # 60s → 1min
    # P3 探针结论：restrictions_status 不可靠，不再用作不可达判定；duration.value 存在即视为可达
    assert out[2] == pytest.approx(0.0)  # duration.value=0 → 0min（非 None）


def test_route_matrix_legacy_wrapped_rows():
    """兼容 {result:{rows:[...]}} 包裹变体（历史实现）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        rows = [
            {"duration": {"value": 300}, "restrictions_status": 0},
            {"duration": {"value": 900}, "restrictions_status": 0},
        ]
        return httpx.Response(200, json={"status": 0, "result": {"rows": rows}})

    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=CallGuard(min_interval_s=0))
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 2, (107.9758, 26.5734)))
    assert out == [pytest.approx(5.0), pytest.approx(15.0)]


def test_route_matrix_short_rows_falls_back_to_directionlite():
    """批量块行数不足（配额收紧）→ 逐点 directionlite 单点兜底（批量为主、单点兜底策略）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if "routematrix" in str(request.url):
            return httpx.Response(200, json={"status": 0, "result": []})  # 空结果 → 触发兜底
        # directionlite/v1/walking
        return httpx.Response(200, json={"status": 0, "result": {"routes": [{"duration": 600}]}})

    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=CallGuard(min_interval_s=0))
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 3, (107.9758, 26.5734)))
    assert out == [10.0, 10.0, 10.0]  # 600s → 10min × 3


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


# ── T3 · 测时通道的失败与降级分支（I7）───────────────────────────────

def _fast_guard(**kw):
    return CallGuard(min_interval_s=0, max_retries=kw.pop("max_retries", 0), backoff_base_s=0.001, **kw)


def _counting_handler(matrix_payload, lite_payload=None):
    """记录各类请求次数；matrix_payload/lite_payload 可为 callable(request)。"""
    hits = {"matrix": 0, "lite": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "routematrix" in url:
            hits["matrix"] += 1
            body = matrix_payload(request) if callable(matrix_payload) else matrix_payload
        else:
            hits["lite"] += 1
            body = lite_payload if lite_payload is not None else {"status": 500, "message": "not-mocked"}
        return httpx.Response(200, json=body)

    return handler, hits


def _row(minutes, status=0):
    return {"duration": {"value": int(minutes * 60)}, "restrictions_status": status}


def test_matrix_get_failure_falls_back_per_point_and_yields_none():
    """_get 整体失败（重试耗尽返回 None）→ 逐点兜底，兜底也失败 → 全 None，不抛。"""
    handler, hits = _counting_handler({"status": 500, "message": "boom"}, {"status": 500, "message": "boom"})
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 3, (107.9758, 26.5734)))
    assert out == [None, None, None]
    assert hits["matrix"] == 1 and hits["lite"] == 3


def test_matrix_empty_rows_and_short_rows_both_trigger_fallback():
    """空 rows 与短 rows 同属「块不完整」→ 都走单点兜底（长度语义不能只认空）。"""
    for label, rows in [("empty", []), ("short", [_row(2.0)])]:
        def matrix(req, rows=rows):
            return {"status": 0, "result": rows}

        handler, hits = _counting_handler(matrix, {"status": 0, "result": {"routes": [{"duration": 300}]}})
        c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
        out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 3, (107.9758, 26.5734)))
        assert out == [5.0, 5.0, 5.0], label
        assert hits["matrix"] == 1 and hits["lite"] == 3, label


def test_matrix_non_dict_row_is_unreachable():
    """行内出现 null/字符串（百度部分失败时的脏行）→ 该点 None，不得抛。"""
    def matrix(req):
        return {"status": 0, "result": [_row(1.0), None, "oops", {"duration": None, "restrictions_status": 0}]}

    handler, _ = _counting_handler(matrix)
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 4, (107.9758, 26.5734)))
    assert out == [1.0, None, None, None]


def test_matrix_duration_as_bare_number_supported():
    """duration 既兼容 {value:N} 也兼容裸数字（历史响应变体）。"""
    def matrix(req):
        return {"status": 0, "result": [{"duration": 900, "restrictions_status": 0}, {"duration": "900", "restrictions_status": 0}]}

    handler, _ = _counting_handler(matrix)
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 2, (107.9758, 26.5734)))
    assert out == [15.0, None]  # 字符串 duration 不作数（宁可不可达，不猜值）


def test_matrix_missing_restrictions_status_defaults_to_reachable():
    """**记录当前行为**：缺 restrictions_status 按 0（可达）处理。

    宽松默认让「字段改名」表现为静默全可达（评分虚高）而非全不可达。
    TODO：探针 P2 坐实字段必在后改为「缺失即 None」。
    """
    def matrix(req):
        return {"status": 0, "result": [{"duration": {"value": 600}}]}

    handler, _ = _counting_handler(matrix)
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    assert asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)], (107.9758, 26.5734))) == [10.0]


@pytest.mark.parametrize(
    "n,expected_calls",
    [(1, 1), (WALKING_CHUNK, 1), (WALKING_CHUNK + 1, 2), (WALKING_CHUNK * 2, 2), (WALKING_CHUNK * 2 + 1, 3)],
)
def test_matrix_chunking_boundaries(n, expected_calls):
    """分块边界：恰好整块不额外发请求，跨块才多一次。"""
    def matrix(req):
        qp = dict(httpx.QueryParams(req.url.query))
        k = len(qp["origins"].split("|"))
        return {"status": 0, "result": [_row(1.0)] * k}

    handler, hits = _counting_handler(matrix)
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * n, (107.9758, 26.5734)))
    assert len(out) == n
    assert hits["matrix"] == expected_calls
    assert hits["lite"] == 0


def test_matrix_empty_origins_makes_no_request():
    handler, hits = _counting_handler({"status": 0, "result": []})
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    assert asyncio_run(c.route_matrix_walking([], (107.9758, 26.5734))) == []
    assert hits == {"matrix": 0, "lite": 0}


def test_matrix_extra_rows_currently_appended_and_misaligned():
    """**记录当前行为**：返回行数多于请求行数时，多出的行会追加进结果。

    下游按 `times[idx]` 与采样点一一对齐（data_source._minutes_by_point / poi.to_points），
    多出来的一行会把后续点的耗时整体错位。百度不会多给，但脏响应/上游变更时会静默错值。
    TODO：按 `rows[:len(chunk)]` 截断并告警。
    """
    def matrix(req):
        return {"status": 0, "result": [_row(1.0), _row(2.0), _row(3.0)]}

    handler, _ = _counting_handler(matrix)
    c = BaiduClient(ak="t", transport=httpx.MockTransport(handler), guard=_fast_guard())
    out = asyncio_run(c.route_matrix_walking([(107.9758, 26.5734)] * 2, (107.9758, 26.5734)))
    assert out == [1.0, 2.0, 3.0]  # 长度 3 > 请求 2 → 错位


def test_guard_401_perm_error_currently_retries():
    """**记录当前行为**：401（AK 无效）按配额类错误退避重试。

    401 是永久性错误，重试只会白烧额度并拖慢降级路径（应与 429 分开分类）。
    """
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return {"status": 401, "message": "invalid ak"}

    guard = CallGuard(min_interval_s=0, max_retries=2, backoff_base_s=0.001)
    assert asyncio.run(guard.call(work)) is None
    assert calls["n"] == 3  # 1 + 2 次重试


@pytest.mark.xfail(strict=True, reason="I7：永久性 401/402 应与瞬时性 429/403 分开分类")
def test_guard_401_should_not_retry():
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return {"status": 401, "message": "invalid ak"}

    guard = CallGuard(min_interval_s=0, max_retries=2, backoff_base_s=0.001)
    assert asyncio.run(guard.call(work)) is None
    assert calls["n"] == 1  # 期望：立即放弃，交给数据源降级


def test_guard_returns_none_on_non_dict_body():
    guard = CallGuard(min_interval_s=0, max_retries=0)

    async def work():
        return "just-a-string"

    assert asyncio.run(guard.call(work)) is None


def test_direction_walking_variants():
    """单点兜底自身的三条分支：正常 / 无 routes / status!=0。"""
    def lite(payload):
        return httpx.MockTransport(lambda req: httpx.Response(200, json=payload))

    c = BaiduClient(ak="t", transport=lite({"status": 0, "result": {"routes": [{"duration": 120}]}}), guard=_fast_guard())
    assert asyncio_run(c.direction_walking((107.9758, 26.5734), (107.99, 26.59))) == pytest.approx(2.0)
    c = BaiduClient(ak="t", transport=lite({"status": 0, "result": {"routes": []}}), guard=_fast_guard())
    assert asyncio_run(c.direction_walking((107.9758, 26.5734), (107.99, 26.59))) is None
    c = BaiduClient(ak="t", transport=lite({"status": 302, "message": "no route"}), guard=_fast_guard())
    assert asyncio_run(c.direction_walking((107.9758, 26.5734), (107.99, 26.59))) is None


def asyncio_run(coro):
    return asyncio.run(coro)