"""M1 · 百度客户端（httpx.MockTransport 注入，无真实网络）：
参数组装 / 响应解析 / 批量矩阵分块 / 韧性重试。"""
import asyncio
import logging
import time

import httpx
import pytest

from app.living_circle.baidu_client import BaiduClient, STOP_COMPLETE
from app.living_circle.caliber import get_caliber
from app.living_circle.data_source import LiveDataSource
from app.living_circle.request_guard import (
    CallGuard,
    GuardStats,
    RATE_LIMIT_STATUS,
    get_daily_budget,
)

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
    out = asyncio_run(c.place_search("菜市场", (107.9758, 26.5734), radius_m=2000))
    # 返回的是 PlaceSearchOut（点位 + 完整性举证），不是裸 list —— 见其 docstring 的理由
    assert out.stop_reason == STOP_COMPLETE and out.pages_fetched == 1
    items = out.items
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


# ── v5 U16 · 默认韧性层接线（B4：总量熔断上限必须真正生效）──────────

def test_u16_default_guard_wired_to_hard_ceiling():
    """U16：`_default_guard()` 无参构造 → `.max_total_calls == total_calls_hard_ceiling()`。

    R2b 根因：旧默认 `CallGuard()` 的 ``max_total_calls=0``（不启用）→ 管线 L277-281 的
    ``total_meltdown`` 降级路径永不触发。本用例钉住接线：预算耗尽 → 熔断 → 诚实离线。
    """
    from app.living_circle.baidu_client import _default_guard
    from app.living_circle.quota import total_calls_hard_ceiling

    guard = _default_guard()
    assert guard.max_total_calls == total_calls_hard_ceiling()  # 免费档 45，非 0
    assert guard.max_total_calls > 0


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


def test_u37_matrix_batches_concurrent_and_ordered():
    """U37（延迟优化 B1）：矩阵分块并发锚 —— gather 期间真实并发、调用数不变、顺序不变。

    fake transport 内 `await asyncio.sleep(0)` 让出事件循环 + 在飞计数：
      - max in-flight ≥ 2 → 并发**真实发生**（不是串行 for 循环，B1 白改的防线）；
      - 调用总数 == 块数 → 并发不改变调用数（预算数学不变）；
      - 结果顺序 == 输入顺序（asyncio.gather 返回顺序即输入顺序，语言级保证）。
    不做时间断言（禁 flaky）。

    ⚠️ 语义注记：`CallGuard._sem` 只闸**限速入口**（`_pace`），HTTP 工作本身并发执行
    —— 故 in-flight 上界是**块数**而非 `max_concurrency`；QPS 上限由级间 pacing 单独
    锁定（`_pace` 的 `min_interval_s`），不在此断言。

    ⚠️ **为何本用例是全文件唯一的 `allow_ungated=True`（β · 2026-09-22 实测）**：
    它断言的是 `gather` 的**并发机制本身**，而进程级闸的级间 pacing
    （`min_interval = 1/QPS ≈ 0.333s`）会把三块的**入闸**串起来 —— mock transport 瞬时
    返回 ⇒ 第 2 块入闸时第 1 块早已收工 ⇒ 实测 `max_in_flight == 1`（**未豁免必红**）。
    生产侧不受影响：真实 routematrix 延迟 ≫ 0.333s，块间重叠照常发生。
    替代方案（把 mock 的 `await asyncio.sleep(0)` 改成 `sleep(0.5)` 以便在 pacing 下
    仍重叠）**被否决**：那会让本用例变成**墙钟 + 配置耦合**（`.env` 把 QPS 调到 1
    ⇒ 间隔 1s ⇒ 又红），与本节末「不做时间断言（禁 flaky）」的纪律直接冲突。
    ⇒ 判据：**断言依赖「零 pacing」才可观测** ⇒ 豁免；其余 16 处不豁免（它们经共享闸
    照常逐条断言通过 = β 的「合法必绿」半边）。
    """
    n = WALKING_CHUNK * 2 + 5  # 100+100+5 → 3 块
    in_flight = 0
    max_in_flight = 0
    total_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight, total_calls
        total_calls += 1
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0)  # 让出循环 → 其余块并发进入 handler（确定性 ≥2）
        in_flight -= 1
        qp = dict(httpx.QueryParams(request.url.query))
        n_orig = len(qp["origins"].split("|"))
        rows = [
            {"distance": {"text": f"{i + 1}米", "value": i + 1},
             "duration": {"text": f"{i + 1}分钟", "value": 60 * (i + 1)}}
            for i in range(n_orig)
        ]
        return httpx.Response(200, json={"status": 0, "result": rows})

    # allow_ungated=True —— 本文件唯一的进程级闸豁免（理由见 docstring 末段）
    c = BaiduClient(
        ak="t",
        transport=httpx.MockTransport(handler),
        guard=CallGuard(min_interval_s=0),
        allow_ungated=True,
    )
    origins = [(107.9758 + i * 0.001, 26.5734) for i in range(n)]
    out = asyncio_run(c.route_matrix_walking(origins, (107.9758, 26.5734)))
    assert len(out) == n
    # gather 顺序 == 输入顺序：块内局部序号 i → minutes = i+1
    assert out == [pytest.approx((i % WALKING_CHUNK) + 1) for i in range(n)], "并发后结果顺序必须与输入一致"
    assert total_calls == 3, f"并发不改变调用数：期望 3 块 3 次，实际 {total_calls}"
    assert max_in_flight >= 2, f"并发未发生（max in-flight={max_in_flight}），B1 串行化失效"
    assert max_in_flight <= 3, f"in-flight 上界应为块数 3，实际 {max_in_flight}"


# ── J4 / J11 · β：构造期绑定共享闸（2026-09-22 · 批次 2）────────────


def test_j04_three_construction_styles_share_one_gate():
    """J4（🔴→🟢 · P0 集成）：`BaiduClient` 三种**构造风格**必须落在**同一把**进程级闸上。

    被测范围：`BaiduClient.__init__` 的**构造期绑定**（β = `_attach_shared_gates`）。
    修复前「显式传 `guard=`」会**静默整条跳过** `_default_guard` ⇒ 风格 ② 的
    `rate_limiter is None` ⇒ 拿私有闸、零级间间隔、不计入共享日预算 = **静默脱离治理**。

    触发规则：同 AK 以 ① 默认 ② `guard=CallGuard(min_interval_s=0)`
    ③ `LiveDataSource(ak=…, client=<②造的那个>)` 三种风格各并发 2 次，记录每次 work 进入时刻。

    期望：合并后**相邻入闸间隔 ≥ 闸的 `min_interval_s`**（🔴 修复前**必红**：风格 ② 零间隔），
    且**调用总数守恒 6**（🔵 配对哨兵 —— 否则「把并发改成串行」或「少发请求」也能满足间隔）。

    ⚠️ **风格 ③ 的定位（E14 订正）**：它与 ② **同源**（`LiveDataSource` 只在 `client` 为空时
    才自建 `BaiduClient`），**不是独立后门**；本用例据它确认「经数据源传递不改闸」。
    真正独立的生产入口是 `LiveDataSource(ak=ak)` 自建那条（`data_source.py:124`）—— 一并断言。
    """
    ak = "a-j4"
    per = 2                      # 每种风格并发次数
    entries: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        entries.append(time.monotonic())          # 「入闸之后」的时刻：闸生效则其间隔被拉平
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1.0, "lat": 2.0}}})

    tr = httpx.MockTransport(handler)
    c1 = BaiduClient(ak=ak, transport=tr)                                        # ① 默认
    c2 = BaiduClient(ak=ak, transport=tr, guard=CallGuard(min_interval_s=0))     # ② 显式 guard
    c3 = LiveDataSource(ak=ak, client=c2).client                                 # ③ 经数据源传入

    shared = c1.guard.rate_limiter
    assert shared is not None, "① 默认风格竟未挂共享闸"
    assert c2.guard.rate_limiter is shared, "② 显式 guard 未共享同一把闸（β 未生效）"
    assert c3.guard.rate_limiter is shared, "③ 经 LiveDataSource 传入后闸被换掉"
    assert LiveDataSource(ak=ak).client.guard.rate_limiter is shared, (
        "`LiveDataSource(ak=ak)` 自建 client 那条生产入口未落同一把闸"
    )

    interval = shared.min_interval_s
    assert interval > 0, (
        "前置条件不成立：共享闸 `min_interval_s == 0` ⇒ 间隔断言对**任何**实现都成立"
        "（= 假护栏）。本用例要求 `Settings.baidu_max_qps` 为正常值（默认 3.0 ⇒ 0.333s）。"
    )

    async def scenario():
        await asyncio.gather(
            *[c1.geocoding(f"a{i}") for i in range(per)],
            *[c2.geocoding(f"b{i}") for i in range(per)],
            *[c3.geocoding(f"c{i}") for i in range(per)],
        )

    asyncio.run(scenario())

    assert len(entries) == 3 * per, f"调用总数应守恒 {3 * per}（并发不改变调用数），实际 {len(entries)}"
    gaps = [b - a for a, b in zip(entries, entries[1:])]
    tol = 0.05   # 仅吸收「记账时刻」的调度抖动（µs 级）；间隔本身由闸保证
    assert all(g >= interval - tol for g in gaps), (
        f"相邻入闸间隔必须 ≥ min_interval_s={interval}s（风格 ② 此前零间隔）——"
        f"实测 gaps={[round(g, 3) for g in gaps]}"
    )


def test_j11_ungated_traffic_is_not_counted(caplog):
    """J11（🟠 · P2 · K10 契约）：`allow_ungated=True` 的流量**不计入**共享日预算、**不占**共享闸。

    被测范围：`BaiduClient(allow_ungated=True)` 与 `_attach_shared_gates` 的**不施加**分支。
    必要性：该计数器**看起来完全像个准确数字**，任何拿它做计量 / 告警 / 报表的地方都会
    **系统性低估** ⇒ 必须显式钉死语义，避免日后有人拿它当真源（K10 裁决）。

    ⚠️ **两个必须**（否则本用例是假绿）：
    1. **cap 必须 > 0**：`GlobalDailyBudget.consume` 在 `cap <= 0` 时**直接 return、不累加**
       —— 用测试环境默认的 `cap=0` 断言「计数不变」会**恒真**（什么都不计，当然不变）。
       故先以非零 cap 播种缓存（工厂键只含 AK ⇒ 后续 `_shared_gate_params` 取回同一个对象）。
    2. **必须配「计入路径是活的」正控**：先让一个**非豁免** client 计数，证明这条路真的会涨；
       否则「不变」无法区分「豁免生效」与「整体就不计数」。
    """
    ak = "j11"
    tr = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1.0, "lat": 2.0}}})
    )
    budget = get_daily_budget(ak, 100)          # 播种非零 cap（先建为准）
    assert budget.cap == 100, "前置条件：cap 必须 > 0，否则计数恒不增长（假绿）"
    assert budget.calls == 0

    # ① 🔵 配对正控：非豁免 client 的流量**必须**被计入
    gated = BaiduClient(ak=ak, transport=tr)
    assert gated.guard.daily_budget is budget, "非豁免 client 未接到共享日预算"
    asyncio.run(gated.geocoding("gated-a"))
    asyncio.run(gated.geocoding("gated-b"))
    assert budget.calls == 2, f"计入路径未生效（calls={budget.calls}）—— 本用例的正控失效"

    # ② 被测：豁免 client 的流量**不得**改变计数
    with caplog.at_level(logging.WARNING, logger="app.living_circle.baidu_client"):
        exempt = BaiduClient(ak=ak, transport=tr, guard=CallGuard(min_interval_s=0), allow_ungated=True)
        warnings = [r.getMessage() for r in caplog.records if "显式豁免进程级闸" in r.getMessage()]

        assert exempt.guard.daily_budget is None, "豁免 client 仍被挂上了共享日预算"
        assert exempt.guard.rate_limiter is None, "豁免 client 仍被挂上了共享闸"
        for i in range(3):
            asyncio.run(exempt.geocoding(f"exempt-{i}"))

    assert len(warnings) == 1, f"豁免必须**显式留痕**（WARNING 恰好 1 条），实际 {len(warnings)} 条"
    assert budget.calls == 2, (
        f"豁免流量不得计入共享日预算：期望仍为 2，实际 {budget.calls}"
        "（> 2 说明豁免被绕过，K10 契约失守）"
    )

    # ③ 配对哨兵：`allow_ungated` **不得**成为「不传 guard 也能绕过」的通用旁路
    naked = BaiduClient(ak=ak, transport=tr, allow_ungated=True)   # 无显式 guard ⇒ 豁免无对象
    assert naked.guard.daily_budget is budget, (
        "`allow_ungated=True` 但未传 `guard=` 时仍必须受共享闸约束（否则它就是通用旁路）"
    )


def asyncio_run(coro):
    return asyncio.run(coro)