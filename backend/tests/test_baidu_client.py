"""百度服务端客户端降级契约测试（M2a / 用例编号 TC-B01）。

约定（《目的地实体政策》）：任何外部失败都必须以 envelope 返回、绝不抛异常，
spots 阶段据此走占位降级且任务不失败。

等价类：缺 AK / 超时 / 连接错 / 非 200 / 非 JSON / 百度 status≠0 / 空结果。
mock 边界：monkeypatch baidu._server_config + baidu._client（httpx.MockTransport，
用 stdlib 自带的 httpx 测试传输，不新增 respx 依赖）。
"""
import httpx
import pytest

from app.services import baidu


def _install(monkeypatch, handler, ak="FAKE_AK", timeout=8.0):
    monkeypatch.setattr(baidu, "_server_config", lambda: (ak, timeout))
    monkeypatch.setattr(
        baidu, "_client", lambda _t: httpx.Client(transport=httpx.MockTransport(handler))
    )


def _json(status, payload):
    def handler(request):
        return httpx.Response(status, json=payload)
    return handler


# ── 可用性入口 ─────────────────────────────────────────────

def test_no_ak_all_entrypoints_degrade_without_raising(monkeypatch):
    _install(monkeypatch, _json(200, {"status": 0}), ak="")
    assert baidu.available() is False
    assert baidu.place_search("古城", "大理") == {"ok": False, "reason": "no_ak"}
    assert baidu.geocode("大理古城") == {"ok": False, "reason": "no_ak"}
    assert baidu.direction("transit", "1,1", "2,2", city="大理")["reason"] == "no_ak"


def test_available_true_when_ak_present(monkeypatch):
    _install(monkeypatch, _json(200, {}), ak="X")
    assert baidu.available() is True


# ── 外部失败等价类：全部降级不抛 ──────────────────────────

@pytest.mark.parametrize(
    "handler,reason",
    [
        (_json(500, {"status": 0}), "http_500"),
        (_json(401, {"status": 0}), "http_401"),
        (_json(200, {"status": 302, "message": "夸配额"}), "api_status_302"),
        (_json(200, {"status": 101}), "api_status_101"),
    ],
    ids=["http500", "http401", "quota302", "status101"],
)
def test_http_and_api_status_failures_degrade(monkeypatch, handler, reason):
    _install(monkeypatch, handler)
    out = baidu.place_search("崇圣寺三塔", "大理")
    assert out["ok"] is False and out["reason"] == reason


def _raise(exc):
    def handler(request):
        raise exc
    return handler


def test_timeout_degrades(monkeypatch):
    _install(monkeypatch, _raise(httpx.ReadTimeout("slow")))
    assert baidu.geocode("大理古城") == {"ok": False, "reason": "timeout"}


def test_connect_error_degrades(monkeypatch):
    _install(monkeypatch, _raise(httpx.ConnectError("refused")))
    assert baidu.direction("driving", "1,1", "2,2")["reason"] == "network"


def test_non_json_body_degrades(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")
    _install(monkeypatch, handler)
    assert baidu.place_search("x", "y")["reason"] == "bad_json"


def test_non_dict_body_degrades(monkeypatch):
    _install(monkeypatch, _json(200, ["unexpected", "list"]))
    assert baidu.geocode("x")["reason"] == "bad_body"


# ── 正常路径归一化 ─────────────────────────────────────────

def test_request_carries_ak_and_query(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": 0, "results": []})

    _install(monkeypatch, handler)
    baidu.place_search("洱海", "大理")
    assert "FAKE_AK" in seen["url"]
    assert "region_limit=true" in seen["url"]
    assert "query=" in seen["url"]


# ── 真实响应形状契约钉（P4-K）────────────────────────────────
# 2026-09-23 实跑抓样（place/v2/search?query=大理古城&region=大理&region_limit=true&output=json）。
# 用真实键名做 fixture：曾经把候选读成 body["result"]（真实是 body["results"]），
# 导致 POI 精确匹配分支静默恒空、真机 7 景点只认出 1 个——假响应复刻了实现的错，
# 所以这条钉的价值在于"形状来自抓样而非记忆"。
_REAL_PLACE_SAMPLE = {
    "status": 0,
    "message": "ok",
    "total": 66,
    "result_type": "poi_type",
    "query_type": "precise",
    "results": [
        {
            "name": "大理古城",
            "location": {"lat": 25.700801, "lng": 100.170478},
            "address": "云南省大理白族自治州大理市一塔路42号",
            "province": "云南省",
            "city": "大理白族自治州",
            "area": "大理市",
            "uid": "44207646660fce16deee8bf6",
            "detail_info": {"tag": "旅游景点;其他", "label": "AAAA景区,古城 古镇"},
        },
        {
            "name": "大理古城-南门",
            "location": {"lat": 25.693278, "lng": 100.170639},
            "address": "云南省大理白族自治州大理市一塔路42号",
            "area": "大理市",
        },
    ],
}


def test_place_search_parses_real_response_shape(monkeypatch):
    """真实抓样必须被解析出候选（顶层 results，非 result）。"""
    _install(monkeypatch, _json(200, _REAL_PLACE_SAMPLE))
    out = baidu.place_search("大理古城", "大理")
    assert out["ok"] is True
    assert [p["name"] for p in out["places"]] == ["大理古城", "大理古城-南门"]
    assert out["places"][0]["lat"] == 25.700801 and out["places"][0]["lng"] == 100.170478
    assert out["places"][0]["area"] == "大理市"
    # 旧口径（读 body["result"]）会在这里静默返回空——正是本次真机故障的形状
    assert out["places"], "results 键被读成 result 时恒为空"


def test_place_search_normalizes_rows(monkeypatch):
    payload = {
        "status": 0,
        "results": [
            {"name": " 大理古城 ", "location": {"lat": 25.69, "lng": 100.16},
             "area": "大理市", "address": "护国路1号", "tag": "文物古迹"},
            "junk-row-should-skip",
            {"name": "无坐标"},
        ],
    }
    _install(monkeypatch, _json(200, payload))
    out = baidu.place_search("大理古城", "大理")
    # 非 dict 垃圾行剔除；合法行缺坐标 → 保留（由调用方判 matched）
    assert out["ok"] is True and len(out["places"]) == 2
    first = out["places"][0]
    assert first["name"] == "大理古城" and first["lat"] == 25.69 and first["area"] == "大理市"
    assert out["places"][1]["name"] == "无坐标" and out["places"][1]["lat"] is None


def test_place_search_empty_is_ok_not_failure(monkeypatch):
    _install(monkeypatch, _json(200, {"status": 0, "results": []}))
    out = baidu.place_search("不存在的地方", "大理")
    assert out == {"ok": True, "places": []}  # 空结果=检索成功，兜底决策归调用方


def test_geocode_success_and_missing_location(monkeypatch):
    _install(monkeypatch, _json(200, {"status": 0, "result": {
        "location": {"lat": 25.69, "lng": 100.16}, "confidence": 80}}))
    out = baidu.geocode("大理古城南门", "大理")
    assert out == {"ok": True, "lat": 25.69, "lng": 100.16, "confidence": 80}

    _install(monkeypatch, _json(200, {"status": 0, "result": {}}))
    assert baidu.geocode("乱码地址") == {"ok": False, "reason": "empty_result"}


def test_direction_sorts_routes_by_duration_and_digests_steps(monkeypatch):
    payload = {"status": 0, "result": {"routes": [
        {"duration": 2400, "distance": 8200, "steps": [
            {"instruction": "乘坐地铁", "vehicle": "地铁", "distance": {"text": "1.2公里"}},
            "junk",
        ]},
        {"duration": 900, "distance": 5100, "steps": [
            {"instruction": "步行", "vehicle": {"description": "步行"}}]},
    ]}}
    _install(monkeypatch, _json(200, payload))
    out = baidu.direction("transit", "25.7,100.1", "25.6,100.2", city="大理")
    assert out["ok"] is True
    assert [r["duration_s"] for r in out["routes"]] == [900, 2400]
    assert out["routes"][1]["steps"][0]["vehicle"] == "地铁"
    assert out["routes"][1]["steps"][0]["distance_m"] == "1.2公里"


def test_direction_rejects_unknown_mode(monkeypatch):
    _install(monkeypatch, _json(200, {}))
    assert baidu.direction("flying", "1,1", "2,2") == {"ok": False, "reason": "bad_mode_flying"}


# ── 打车估价：纯函数、可复现、必标估算 ────────────────────

@pytest.mark.parametrize(
    "distance_m,fare",
    [(800, 10), (3000, 10), (12500, 29), (100000, 204)],
    ids=["short", "boundary3km", "normal", "long"],
)
def test_taxi_estimate_deterministic(distance_m, fare):
    out = baidu.taxi_estimate(distance_m)
    assert out == {"ok": True, "fare_yuan": fare,
                   "distance_km": round(distance_m / 1000, 1), "estimated": True}


@pytest.mark.parametrize("distance_m", [None, 0, -500], ids=["none", "zero", "negative"])
def test_taxi_estimate_bad_distance(distance_m):
    assert baidu.taxi_estimate(distance_m)["ok"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
