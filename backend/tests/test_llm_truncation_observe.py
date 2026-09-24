"""截断可观测：守护「输出被 max_tokens 切断」一定能被上层看见。

背景（真实故障 r_f2cc14fd）：9/11 章的写稿 JSON 被单章 6000 token 上限截断，而
key_takeaway/highlights 排在输出契约末尾 → 结构字段整批丢失，前端「本章内容结构」
降级成一行正文计数，且全链路无人知晓（旧 trace 里连 finish_reason 都没记）。
推理模型的思考 token 与正文共享该预算，是这次被吃光的主因。

钉住的不变量：
I1 chat() 把 finish_reason 与推理 token 数记到 ContextVar，供上层判定（不改变调用行为）；
I2 finish_reason=='length' 时 trace span 的 decision 带截断标记 + 推理 token 数
   （决策回放可读，且不需要改 traces 表结构）；
I3 厂商不返回 completion_tokens_details 时退化为 0，不抛错。

依赖注入点：llm._get_client（假客户端，不联网）；trace.set_context 走 contextvar 设 task_id。
运行：backend/ 下 `pytest tests/test_llm_truncation_observe.py -q`
"""
from types import SimpleNamespace as NS

from app.core import llm, trace


def _usage(reasoning=0, total=10):
    return NS(total_tokens=total, prompt_tokens=1, completion_tokens=2,
              completion_tokens_details=NS(reasoning_tokens=reasoning))


def _resp(content, finish, reasoning=0):
    return NS(choices=[NS(message=NS(content=content), finish_reason=finish)],
              usage=_usage(reasoning))


def _fake_client(resp):
    return NS(chat=NS(completions=NS(create=lambda **kw: resp)))


def test_chat_records_finish_reason_and_reasoning(monkeypatch):
    """截断调用（finish_reason='length'）必须留下 finish_reason 与推理 token 读数。"""
    monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(_resp("{", "length", 4123)))
    out = llm.chat([{"role": "user", "content": "hi"}], model="m", purpose="撰写章节：交通与抵达")
    assert out == "{", "chat() 返回值不得因新增观测而改变"
    assert llm.last_finish_reason() == "length"
    assert llm.last_reasoning_tokens() == 4123


def test_span_decision_carries_truncation_mark(monkeypatch):
    """截断标记落在 span.decision：决策回放里一眼看出这段输出是被切掉的。"""
    trace.set_context("t_trunc", "L3-002", "write", "撰写章节：交通与抵达")
    try:
        monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(_resp("{", "length", 4123)))
        llm.chat([{"role": "user", "content": "hi"}], model="m", purpose="撰写章节：交通与抵达")
        spans = trace.drain("t_trunc")
    finally:
        trace.clear_context()
    assert spans, "被截断的调用也必须留下 span，否则决策回放看不到"
    assert "输出被截断" in spans[0]["decision"]
    assert "4123" in spans[0]["decision"]


def test_normal_finish_has_no_truncation_mark(monkeypatch):
    """正常收尾（finish_reason='stop'）不得被误标为截断（标记失真就没人信它了）。"""
    trace.set_context("t_ok", "L3-002", "write", "撰写章节：交通与抵达")
    try:
        monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(_resp('{"a":1}', "stop")))
        llm.chat([{"role": "user", "content": "hi"}], model="m", purpose="撰写章节：交通与抵达")
        spans = trace.drain("t_ok")
    finally:
        trace.clear_context()
    assert llm.last_finish_reason() == "stop"
    assert llm.last_reasoning_tokens() == 0
    assert "截断" not in spans[0]["decision"]


def test_usage_without_details_does_not_break(monkeypatch):
    """厂商不返回 completion_tokens_details 时退化为 0（观测不得变成新的失败面）。"""
    resp = NS(choices=[NS(message=NS(content="ok"), finish_reason="stop")],
              usage=NS(total_tokens=3, prompt_tokens=1, completion_tokens=2))
    monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(resp))
    assert llm.chat([{"role": "user", "content": "hi"}], model="m", purpose="p") == "ok"
    assert llm.last_finish_reason() == "stop"
    assert llm.last_reasoning_tokens() == 0
