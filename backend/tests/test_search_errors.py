"""搜索错误分级 fail-fast（修复计划 wise-flint-darter item3；覆盖评估 B 组 5 钉）。

守护的不变量（app/core/search.py）：
- 服务商级终态错误（Key 无效/欠费/配额：HTTP 或业务码 401/403/429 及文案命中族）
  → SearchProviderError，multi_search 不吞、一条即止（不再烧剩余查询）。
- 瞬时失败（5xx/网络抖动）→ 维持逐条跳过、聚合已得的尽力而为语义。
- 缺 key → 安全降级抛错（现状钉），且任何对外文案不带 API key（防泄漏）。

零网络：httpx.Client 与 settings 全部 mock。
运行：backend/ 下 `pytest tests/test_search_errors.py -q`
"""
import json

import pytest

from app.core import search as S
from app.core.search import SearchProviderError

FAKE_KEY = "sk-SECRET-do-not-leak"
SETTINGS = {"bocha_api_key": FAKE_KEY, "bocha_base_url": "https://bocha.invalid/v1",
            "search_timeout": 5}


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body


def _ok_body(query="大理 攻略"):
    return {"code": 200, "data": {"webPages": {"value": [
        {"url": "https://a.example/1", "name": f"{query} 公开资料",
         "summary": f"{query}：交通住宿预算信息", "datePublished": "2026-08-01",
         "siteName": "a.example"}]}}}


def _install_client(monkeypatch, responder):
    """responder(call_no, payload) -> _Resp | raise；记录调用次数与请求体。"""
    state = {"n": 0, "payloads": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            state["n"] += 1
            state["payloads"].append(json or {})
            return responder(state["n"], json or {})

    monkeypatch.setattr(S.httpx, "Client", _Client)
    monkeypatch.setattr(S, "get_effective_settings", lambda: dict(SETTINGS))
    return state


def _http(status, body=None):
    def _r(_n, _p):
        return _Resp(status, body)
    return _r


# ── TC-S1 等价类：终态码 → SearchProviderError；5xx → 普通 RuntimeError ──
@pytest.mark.parametrize("status,is_terminal", [
    (401, True), (403, True), (429, True),
    (500, False), (400, False),
])
def test_bocha_error_classification(monkeypatch, status, is_terminal):
    _install_client(monkeypatch, _http(status))
    exc = SearchProviderError if is_terminal else RuntimeError
    with pytest.raises(exc) as ei:
        S.search_bocha("大理 攻略")
    if not is_terminal:
        assert not isinstance(ei.value, SearchProviderError), f"{status} 属瞬时类，不得判终态"
    assert str(ei.value)


def test_business_code_terminal_in_http_200(monkeypatch):
    """HTTP 200 但 body 业务码 403（欠费）：同样判服务商终态。"""
    _install_client(monkeypatch, _http(200, {"code": 403, "msg": "余额不足"}))
    with pytest.raises(SearchProviderError) as ei:
        S.search_bocha("大理 攻略")
    assert "余额不足" in str(ei.value)


def test_unmapped_code_with_quota_msg_is_terminal(monkeypatch):
    """未映射业务码但文案命中「余额/配额/鉴权」族 → 也判终态。"""
    _install_client(monkeypatch, _http(200, {"code": 9999, "msg": "账户配额已用尽"}))
    with pytest.raises(SearchProviderError):
        S.search_bocha("大理 攻略")


# ── TC-S2 multi_search 首条终态错误：原样上抛且只发 1 次 HTTP ──────────
def test_multi_search_fail_fast_single_http(monkeypatch):
    state = _install_client(monkeypatch, _http(403))
    with pytest.raises(SearchProviderError):
        S.multi_search(["大理 攻略", "大理 美食", "大理 住宿", "大理 交通"])
    assert state["n"] == 1, f"欠费必须一条即止，实发 {state['n']} 次 HTTP"


# ── TC-S3 瞬时失败逐条跳过、聚合正常结果 ──────────────────────────────
def test_multi_search_skips_transient_and_aggregates(monkeypatch):
    def responder(n, _p):
        if n == 1:
            return _Resp(500)          # 首条瞬时失败
        return _Resp(200, _ok_body("大理 美食"))
    state = _install_client(monkeypatch, responder)
    out = S.multi_search(["大理 攻略", "大理 美食"])
    assert state["n"] == 2
    assert out and out[0]["query"] == "大理 美食", "瞬时失败跳过后应聚合后续成功结果"


# ── TC-S4 缺 key：安全降级抛错（现状钉）───────────────────────────────
def test_missing_key_raises_without_http(monkeypatch):
    state = _install_client(monkeypatch, _http(200, _ok_body()))
    monkeypatch.setattr(S, "get_effective_settings", lambda: {"bocha_api_key": ""})
    with pytest.raises(RuntimeError) as ei:
        S.search_bocha("大理 攻略")
    assert "未配置" in str(ei.value)
    assert state["n"] == 0, "缺 key 不得发出任何请求"


# ── TC-S5 对外文案不泄漏 API key ──────────────────────────────────────
def test_error_messages_do_not_leak_key(monkeypatch):
    for status in (401, 403, 429, 500):
        _install_client(monkeypatch, _http(status))
        with pytest.raises(RuntimeError) as ei:
            S.search_bocha("大理 攻略")
        assert FAKE_KEY not in str(ei.value)
    # 请求头携带 key，但异常文案只来自映射表
    _install_client(monkeypatch, lambda n, p: (_ for _ in ()).throw(ConnectionError("net down")))
    with pytest.raises(Exception) as ei:
        S.search_bocha("大理 攻略")
    assert FAKE_KEY not in str(ei.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
