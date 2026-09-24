"""brisk-pond-finch L4 测试钉：模型能力运行时缓存 + 拒参分类 + chat_json 截断阶梯。

钉落点（计划 L3 分层约定）：本文件全部走「**真 chat/chat_json + 假 `_get_client`**」，
调用计数用 seen 列表（不依赖墙钟）；DB 经 conftest 隔离库，traits 整值 JSON 可直接断言。

不变量：
LT-1  参数下发矩阵 = traits(实测) > force(阶梯) > L1 名字初值；
LT-4  阶梯：解析失败∧finish=length∧上次未带参 → 带参重试恰 1 次；
      带参已生效仍 length → 不盲重试；traits=false → 不浪费往返；
      429 归既有退避圈，不误入拒参桶、不占阶梯计数；
LT-5  拒参（400/422 ∧ thinking ∧ 参数特征）→ 记 false + 同次裸参重发，异常不外漏；
LT-5a 分类互斥：模型缺失文案（404 no longer available）转抛 LLMModelUnavailable、
      「is not supported」但无 thinking 的 400 原样上抛——三桶唯一归宿；
LT-5b traits=false 优先于名字命中；缓存与 invalidate_client 解耦、跨进程读回（db 持久）。
"""
import json
from types import SimpleNamespace as NS

import pytest

from app.core import db
from app.core import llm
from app.core.llm import (LLMModelUnavailable, chat, chat_json,
                          record_model_fact, thinking_toggle_supported)


class _ApiError(Exception):
    """OpenAI SDK 异常替身：带 status_code，str(err) 即厂商 message。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _resp(content: str, finish: str = "stop"):
    return NS(choices=[NS(message=NS(content=content), finish_reason=finish)],
              usage=NS(total_tokens=10, prompt_tokens=5, completion_tokens=5,
                       completion_tokens_details=NS(reasoning_tokens=0)))


@pytest.fixture(autouse=True)
def _fresh_traits():
    """conftest 清的是 DB；进程内 _TRAITS_MEM 必须一并复位，防用例串扰。"""
    llm._TRAITS_MEM = None
    yield
    llm._TRAITS_MEM = None


def _client(script):
    """脚本化假客户端：script 逐元素 = _resp(...) 或异常实例；返回 (client, seen)。"""
    seen = []

    def create(**kw):
        seen.append(kw)
        item = script[min(len(seen) - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return NS(chat=NS(completions=NS(create=create))), seen


def _install(monkeypatch, script):
    client, seen = _client(script)
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    return seen


# ── LT-1 参数下发矩阵 ────────────────────────────────────
@pytest.mark.parametrize("model,attach", [
    ("deepseek-flash", True), ("deepseek-v4-pro", True),
    ("glm-5-turbo", True), ("glm-4.6", True),
    ("deepseek-chat", False), ("deepseek-reasoner", False), ("gpt-4o", False),
])
def test_lt1_extra_body_matrix(monkeypatch, model, attach):
    seen = _install(monkeypatch, [_resp("ok")])
    chat([{"role": "user", "content": "hi"}], model=model, purpose="p")
    assert ("extra_body" in seen[0]) is attach
    if attach:
        assert seen[0]["extra_body"] == {"thinking": {"type": "disabled"}}


# ── LT-4 chat_json 截断阶梯 ──────────────────────────────
def test_lt4_ladder_retries_once_with_param(monkeypatch):
    seen = _install(monkeypatch, [_resp("{", "length"), _resp('{"ok":1}', "stop")])
    out = chat_json([{"role": "user", "content": "hi"}], model="m-newcomer-1", purpose="结构化")
    assert out == {"ok": 1}
    assert len(seen) == 2, "首次截断 → 带参重试恰一次"
    assert "extra_body" not in seen[0] and seen[1].get("extra_body")
    assert thinking_toggle_supported("m-newcomer-1") is True, "参数被接受 → 事实沉淀"


def test_lt4_no_blind_retry_when_param_already_sent(monkeypatch):
    seen = _install(monkeypatch, [_resp("{", "length")])
    assert chat_json([{"role": "user", "content": "hi"}], model="deepseek-flash", purpose="p") is None
    assert len(seen) == 1, "带参已生效仍 length：不盲重试，直接 None 走可见降级"


def test_lt4_ladder_skipped_when_toggle_unsupported(monkeypatch):
    record_model_fact("m-newcomer-2", thinking_toggle_supported=False)
    seen = _install(monkeypatch, [_resp("{", "length")])
    assert chat_json([{"role": "user", "content": "hi"}], model="m-newcomer-2", purpose="p") is None
    assert len(seen) == 1, "实测不支持关参的模型不再浪费往返"


def test_lt4_rate_limit_not_param_bucket(monkeypatch):
    monkeypatch.setattr(llm, "_RATE_LIMIT_BACKOFFS", [0.0])
    seen = _install(monkeypatch, [
        _ApiError(429, "Rate limit reached for thinking-enabled traffic"),
        _resp('{"ok":2}', "stop"),
    ])
    assert chat_json([{"role": "user", "content": "hi"}], model="deepseek-flash", purpose="p") == {"ok": 2}
    assert len(seen) == 2
    assert thinking_toggle_supported("deepseek-flash") is not False, "429 不得记成拒参"
    assert all("extra_body" in kw for kw in seen), "429 退避重发仍带参，不占阶梯"


# ── LT-5 / LT-5a 拒参分类与互斥桶 ────────────────────────
def test_lt5_param_rejection_recorded_and_bare_resend(monkeypatch):
    seen = _install(monkeypatch, [
        _ApiError(400, "Request body 'thinking' is not supported for this deployment"),
        _resp("ok", "stop"),
    ])
    assert chat([{"role": "user", "content": "hi"}], model="deepseek-flash", purpose="p") == "ok"
    assert len(seen) == 2 and "extra_body" in seen[0] and "extra_body" not in seen[1]
    assert thinking_toggle_supported("deepseek-flash") is False


def test_lt4_ladder_survives_rejection_midway(monkeypatch):
    """阶梯+回退级联：无参截断 → 带参重试被拒 → 裸参重发拿结果（发现期 ≤2 上界）。"""
    seen = _install(monkeypatch, [
        _resp("{", "length"),
        _ApiError(400, "Request body 'thinking' is not supported"),
        _resp('{"ok":3}', "stop"),
    ])
    assert chat_json([{"role": "user", "content": "hi"}], model="m-newcomer-3", purpose="p") == {"ok": 3}
    assert len(seen) == 3, "首次+阶梯1+拒参回退1 = 上界内"
    assert thinking_toggle_supported("m-newcomer-3") is False


def test_lt5a_model_missing_bucket_untouched(monkeypatch):
    seen = _install(monkeypatch, [
        _ApiError(404, "Error code: 404 This model models/gemini-2.5-pro is no longer available "
                       "to new users. Please update to use models/gemini-3.1-pro-preview"),
    ])
    with pytest.raises(LLMModelUnavailable):
        chat([{"role": "user", "content": "hi"}], model="glm-5-x", purpose="p")
    assert len(seen) == 1 and thinking_toggle_supported("glm-5-x") is None, "模型缺失桶不得写拒参事实"


def test_lt5a_not_supported_without_thinking_stays_generic(monkeypatch):
    """对抗样本：400 +「is not supported」但不含 thinking → 既非拒参也提不出建议模型，
    原样上抛（不被模型缺失桶转抛，更不被误记 traits=false）。"""
    seen = _install(monkeypatch, [_ApiError(400, "The model `foo-bar` is not supported")])
    with pytest.raises(Exception) as ei:
        chat([{"role": "user", "content": "hi"}], model="foo-bar", purpose="p")
    assert not isinstance(ei.value, LLMModelUnavailable)
    assert len(seen) == 1
    assert thinking_toggle_supported("foo-bar") is None


# ── LT-5b traits 优先规则 + 持久化 ───────────────────────
def test_lt5b_explicit_traits_beats_name_whitelist(monkeypatch):
    record_model_fact("deepseek-flash", thinking_toggle_supported=False)
    seen = _install(monkeypatch, [_resp("ok")])
    chat([{"role": "user", "content": "hi"}], model="deepseek-flash", purpose="p")
    assert "extra_body" not in seen[0], "实测拒参过：名字命中也不带参"


def test_lt5b_survives_client_invalidation(monkeypatch):
    record_model_fact("m-persist-1", thinking_toggle_supported=True)
    llm.invalidate_client()
    llm._TRAITS_MEM = None  # 模拟新进程：从 settings 表读回
    assert thinking_toggle_supported("m-persist-1") is True


def test_lt5_whole_json_no_clobber():
    record_model_fact("m-a", thinking_toggle_supported=True)
    record_model_fact("m-b", thinking_toggle_supported=False)
    doc = json.loads(db.get_setting("model_traits"))
    assert len([k for k in doc if k.endswith("|m-a")]) == 1
    assert len([k for k in doc if k.endswith("|m-b")]) == 1, "整值覆盖不得抹掉既有键"
