"""可观测性 Trace 系统（对应需求 4 / 10：每个 Agent 的 Prompt/输入/输出/Token/决策可查可回放）。

设计要点：
- run_pipeline 的所有同步调用都用 asyncio.to_thread 包裹；Python 3.9 的 to_thread 会
  copy_context() 后在线程内 ctx.run(func)，因此 async 侧 set_context 设置的 contextvar
  会被复制进线程，对线程内嵌套的 llm.chat() 可见 —— 据此实现「无侵入埋点」。
- 每次 LLM 调用在 chat() 内自动 record_span()，从当前 contextvar 取 agent/stage/purpose。
- run_pipeline 每个阶段结束 drain() 增量取出新 span 并通过 SSE("trace") 推给前端悬浮面板。
- 结束后精简版随报告 JSON 落库，供报告页「决策回放」与独立 Trace 页签使用。
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import itertools
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TraceSpan:
    span_id: str
    task_id: str
    seq: int
    agent_id: str
    stage: str
    purpose: str
    model: str
    prompt: str          # 摘要（system+user 拼接裁剪）
    response: str        # 摘要（裁剪）
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    decision: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    ts: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# 当前调用上下文（task_id, agent_id, stage, purpose）
_CTX: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "evergreen_trace_ctx", default={}
)

_BUFFER: Dict[str, List[TraceSpan]] = {}
_DRAINED: Dict[str, int] = {}          # task_id -> 已 drain 到的索引
_LOCK = threading.Lock()
_SEQ = itertools.count(1)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_context(task_id: str, agent_id: str, stage: str, purpose: str) -> None:
    """在 async 侧调用 to_thread 之前设置；线程内的 chat() 会读取它。"""
    _CTX.set({"task_id": task_id, "agent_id": agent_id, "stage": stage, "purpose": purpose})


def clear_context() -> None:
    _CTX.set({})


def _summarize_messages(messages: Any, limit: int = 600) -> str:
    try:
        parts = []
        for m in messages:
            role = m.get("role", "")
            content = str(m.get("content", ""))
            parts.append(f"[{role}] {content}")
        text = "\n".join(parts)
    except Exception:
        text = str(messages)
    return text[:limit]


def record_span(
    model: str,
    messages: Any,
    response: str,
    usage: Any = None,
    latency_ms: int = 0,
    decision: str = "",
    evidence_ids: Optional[List[str]] = None,
) -> Optional[TraceSpan]:
    """由 llm.chat() 在每次调用后调用。从 contextvar 取上下文组装 span 入 buffer。"""
    ctx = _CTX.get()
    task_id = ctx.get("task_id", "")
    if not task_id:
        return None  # 不在调研流程内（如健康检查 ping），不记录

    pt = ct = tt = 0
    try:
        if usage is not None:
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", 0) or 0)
    except Exception:
        pass

    span = TraceSpan(
        span_id="sp_" + uuid.uuid4().hex[:10],
        task_id=task_id,
        seq=next(_SEQ),
        agent_id=ctx.get("agent_id", ""),
        stage=ctx.get("stage", ""),
        purpose=ctx.get("purpose", ""),
        model=model,
        prompt=_summarize_messages(messages),
        response=str(response or "")[:600],
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        latency_ms=int(latency_ms),
        decision=decision,
        evidence_ids=list(evidence_ids or []),
        ts=_now(),
    )
    with _LOCK:
        _BUFFER.setdefault(task_id, []).append(span)
    return span


def record_manual_span(
    task_id: str,
    agent_id: str,
    stage: str,
    purpose: str,
    detail: str = "",
    decision: str = "",
    evidence_ids: Optional[List[str]] = None,
    latency_ms: int = 0,
    model: str = "—（检索/规则，无 LLM）",
) -> Optional[TraceSpan]:
    """手动记录一个非 LLM 的 trace span（如证据采集、规则质检）。

    让决策链路里「证据采集 / 质检审裁」等不调 LLM 的阶段也有可观测记录，
    不再出现空白阶段。detail 作为该步的输入/产出摘要展示。
    """
    if not task_id:
        return None
    span = TraceSpan(
        span_id="sp_" + uuid.uuid4().hex[:10],
        task_id=task_id,
        seq=next(_SEQ),
        agent_id=agent_id,
        stage=stage,
        purpose=purpose,
        model=model,
        prompt=str(detail or "")[:600],
        response=str(decision or detail or "")[:600],
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        latency_ms=int(latency_ms),
        decision=decision,
        evidence_ids=list(evidence_ids or []),
        ts=_now(),
    )
    with _LOCK:
        _BUFFER.setdefault(task_id, []).append(span)
    return span


def drain(task_id: str) -> List[Dict[str, Any]]:
    """取出自上次以来的新 span（供 SSE 增量推送），返回 dict 列表。"""
    with _LOCK:
        spans = _BUFFER.get(task_id, [])
        start = _DRAINED.get(task_id, 0)
        new = spans[start:]
        _DRAINED[task_id] = len(spans)
        return [s.to_dict() for s in new]


def get_trace(task_id: str) -> List[Dict[str, Any]]:
    """全量取出（运行中查询用）。"""
    with _LOCK:
        return [s.to_dict() for s in _BUFFER.get(task_id, [])]


def cleanup(task_id: str) -> None:
    """任务结束、落库后清理内存 buffer。"""
    with _LOCK:
        _BUFFER.pop(task_id, None)
        _DRAINED.pop(task_id, None)
