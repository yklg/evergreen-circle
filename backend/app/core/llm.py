"""LLM 客户端封装（OpenAI 兼容协议，默认智谱 GLM，走 BigModel 兼容网关）。

- 模型 / APIKEY 走 env + 运行时配置（llm_* 键，厂商无关），不硬编码、不外泄（第 16.4 章）。
- 支持普通 chat 与流式 chat（供思维流 SSE 使用）。
- chat/chat_json/chat_stream 均支持 model 参数覆盖默认模型（多模型并行调度用）。
- 每次 chat() 调用自动记录 trace span（无侵入埋点，见 trace.py）。
- 未配置 key 时抛出明确错误，由上层决定是否走 demo 兜底。
"""
from __future__ import annotations

import json
import re
import threading
import time
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

from openai import OpenAI

from app.core import db, trace
from app.core.runtime_config import get_effective_settings


class LLMNotConfigured(RuntimeError):
    """未配置 LLM API Key。"""


class LLMModelUnavailable(RuntimeError):
    """模型不可用（厂商已下架/重命名/无权访问）。

    携带厂商在错误响应里给出的建议模型，供上层给出「一键迁移」入口。
    """

    def __init__(self, message: str, suggested_model: str | None = None):
        super().__init__(message)
        self.suggested_model = suggested_model


def _parse_model_unavailable(err: Exception) -> tuple[str | None, str | None]:
    """从厂商错误消息里提取「当前模型名」和「建议模型名」。

    评审 P1 加固：先确认消息表达「模型不可用」，再提取，避免 401/429 等
    错误文案里夹带的 `models/xxx` 片段被误判为可迁移建议。
    """
    msg = str(err)
    if not re.search(
        r"(?:no longer available|does not exist|not found|unavailable|deprecated|is not supported)",
        msg,
        re.I,
    ):
        return (None, None)
    # Gemini: "This model models/gemini-2.5-pro is no longer available ... use models/gemini-3.1-pro-preview"
    # OpenAI: "The model `gpt-foo` does not exist" / "does not exist or you do not have access"
    # 优先提取带强意图（use / update / try）的建议模型
    suggested = re.search(r"(?:use|update|try).*?models?/([\w\-.]+)", msg, re.I)
    current = re.search(r"models?/([\w\-.]+)", msg, re.I)
    return (
        current.group(1) if current else None,
        suggested.group(1) if suggested else None,
    )


def _raise_if_model_unavailable(err: Exception) -> None:
    """若 err 是「模型不可用」且能提取建议模型，转抛 LLMModelUnavailable；否则原样 raise。"""
    if _is_rate_limit(err):
        raise err
    _, suggested = _parse_model_unavailable(err)
    if suggested:
        raise LLMModelUnavailable(str(err), suggested_model=suggested) from err
    raise err


_client: OpenAI | None = None
# 客户端签名：记录建客户端时用的配置。签名变化即重建，
# 使界面改配置后**无需重启**立即生效（根治 RC2）。
_client_sig: tuple | None = None


def invalidate_client() -> None:
    """配置变更后调用：丢弃缓存客户端，下次 _get_client() 用新配置重建。"""
    global _client, _client_sig
    _client = None
    _client_sig = None

# 进程级 token 计数（供 progress 真实上报）
TOKEN_USAGE = {"total": 0}

# 429 限速退避：智谱低档位账户 QPS 很严，遇 429 自动等几秒重试
_RATE_LIMIT_BACKOFFS = [4.0, 8.0, 15.0, 25.0]


def _is_rate_limit(err: Exception) -> bool:
    msg = str(err)
    return "429" in msg or "rate" in msg.lower() or "1302" in msg


def is_temporary_unavailable(err: Exception) -> bool:
    """评审 P1-a：仅当 HTTP 503 且命中 Google 临时高负载文案特征时判定为临时不可用。

    必须同时满足「503 状态码」+「Google 文案特征」，避免把「永久下架也返回 503」
    的厂商误当可重试并误导用户「稍后重试」。
    """
    msg = str(err)
    is_503 = getattr(err, "status_code", None) == 503 or "503" in msg
    if not is_503:
        return False
    return bool(re.search(r"(high demand|temporarily|unavailable|overloaded)", msg, re.I))


def _get_client() -> OpenAI:
    """按 (key, base_url, timeout, retries) 签名缓存客户端。

    签名不变则复用（省去重复建连开销）；签名变化则重建，
    因此界面保存配置后下一次 LLM 调用即走新配置，无需重启进程。
    """
    global _client, _client_sig
    s = get_effective_settings()
    if not s.get("llm_api_key"):
        raise LLMNotConfigured(
            "未配置 LLM API Key，请在「模型配置」页面选择服务商后粘贴，或写入 backend/.env 的 "
            "LLM_API_KEY（旧名 ZHIPU_API_KEY 仍兼容）。"
        )
    sig = (
        s.get("llm_api_key"),
        s.get("llm_base_url"),
        float(s.get("llm_timeout") or 180),
        int(s.get("llm_max_retries") or 0),
    )
    if _client is None or _client_sig != sig:
        _client = OpenAI(
            api_key=sig[0],
            base_url=sig[1],
            timeout=sig[2],
            max_retries=sig[3],
        )
        _client_sig = sig
    return _client


def _supports_thinking(model: str) -> bool:
    """名字判据 = traits 缓存的**初始已知值**（L1 止血），不再承担对新模型的
    唯一防线——能力真相以 `thinking_toggle_supported` 实测缓存为准（L4）。

    deepseek-flash 默认开思考：真实故障 r_38bdd649 里 spots 抽取/结构化调用的
    推理 token 吃光 max_tokens（finish=length）→ 结构化全空 → 报告可视化整层
    缺位。api.deepseek.com 已验接受 `thinking:{"type":"disabled"}`（2026-09-22，
    finish=stop、零 reasoning）。deepseek-chat/reasoner 等旧名不在列，行为不变。"""
    m = model.lower()
    return ("glm-5" in m or "glm-4.6" in m or "glm-4-6" in m
            or ("deepseek" in m and ("v4" in m or "flash" in m or "pro" in m)))


# ── L4 · 模型能力运行时缓存（brisk-pond-finch）────────────────
# base_url+model 复合键 → {"thinking_toggle_supported": true/false}。能力是外部
# 网关的运行时事实，探明一次即沉淀：显式实测值**优先于**上面的名字判据（实测拒参
# 过，名字命中也不带参；实测接受过，恒带参）。settings kv 整值 JSON 覆盖（无迁移、
# 并发写不半更新）；invalidate_client()/配置保存不动本缓存（键含网关，天然隔离）。
_TRAITS_KEY = "model_traits"
_TRAITS_LOCK = threading.Lock()
_TRAITS_MEM: Optional[Dict[str, Dict[str, Any]]] = None


def _traits_map() -> Dict[str, Dict[str, Any]]:
    global _TRAITS_MEM
    if _TRAITS_MEM is None:
        raw = db.get_setting(_TRAITS_KEY)
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {}
        _TRAITS_MEM = parsed if isinstance(parsed, dict) else {}
    return _TRAITS_MEM


def _traits_key(model: str) -> str:
    return f"{get_effective_settings().get('llm_base_url') or ''}|{model}"


def record_model_fact(model: str, **facts: Any) -> None:
    """写入实测能力事实（线程安全；无变化不写库，避免热路径反复落盘）。"""
    with _TRAITS_LOCK:
        m = _traits_map()
        k = _traits_key(model)
        e = dict(m.get(k) or {})
        changed = False
        for fk, fv in facts.items():
            if e.get(fk) != fv:
                e[fk] = fv
                changed = True
        if not changed:
            return
        e["updated_at"] = int(time.time())
        m[k] = e
        _TRAITS_MEM = m
        try:
            db.set_setting(_TRAITS_KEY, json.dumps(m, ensure_ascii=False))
        except Exception:
            pass  # 观测性缓存写失败不得影响调用本身


def thinking_toggle_supported(model: str) -> Optional[bool]:
    e = _traits_map().get(_traits_key(model)) or {}
    v = e.get("thinking_toggle_supported")
    return v if isinstance(v, bool) else None


_PARAM_REJECT_HINTS = ("body", "parameter", "param", "field",
                       "unknown", "unrecognized", "invalid", "not supported")


def _is_thinking_param_rejection(err: Exception) -> bool:
    """「网关拒收 thinking 参数」判据（评审建议 1 / 评估 LT-5a）。

    必须**先于** `_raise_if_model_unavailable` 求值：后者 regex 含
    `is not supported`，拒参文案若先撞上会被转抛 LLMModelUnavailable 杀整个
    任务（错桶）。互斥判据：状态码 400/422 ∧ message 同时含 `thinking` 与参数类
    特征；「model x is not supported」（不含 thinking）仍归模型缺失桶。429 状态
    码不匹配，天然归既有退避圈，不占本阶梯计数。"""
    code = getattr(err, "status_code", None)
    if code not in (400, 422):
        return False
    msg = str(err).lower()
    return "thinking" in msg and any(h in msg for h in _PARAM_REJECT_HINTS)


def _send_thinking_off(model: str, force: bool = False) -> bool:
    """本次调用是否携带关思考参数：显式 traits > force（L4 阶梯指令）> L1 名字初值。"""
    known = thinking_toggle_supported(model)
    if known is False:
        return False
    if known is True:
        return True
    return force or _supports_thinking(model)


def _strip_think(text: str) -> str:
    """剥离部分模型（如 glm-z1 系列）内联输出的 <think>...</think> 思考块。"""
    if not text:
        return text
    # 去掉成对 <think>..</think>
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    # 去掉残留的未闭合 <think> 开头块（截断时常见）
    if "<think>" in cleaned and "</think>" not in cleaned:
        cleaned = cleaned.split("<think>")[0]
    return cleaned.strip()


# 截断观测（只读，不改变任何调用行为）：让上层能区分「这次输出是被 max_tokens
# 切断的」与「模型正常收尾」。用 ContextVar 而非进程共享变量——写稿章经
# asyncio.to_thread 执行，chat() 与读取方在同一线程上下文（copy_context 副本）内，
# 并行的各章互不串扰。
_LAST_FINISH: ContextVar[str] = ContextVar("llm_last_finish", default="")
_LAST_REASONING: ContextVar[int] = ContextVar("llm_last_reasoning", default=0)
# 最近一次 chat() 是否真的携带了关思考参数（拒参裸参重发后置 False）：
# chat_json 的截断契约阶梯据此判「带参已生效仍 length → 不盲重试」。
_LAST_PARAM_SENT: ContextVar[bool] = ContextVar("llm_last_param_sent", default=False)


def last_param_sent() -> bool:
    """最近一次 chat() 是否带出了 thinking 关参（同线程读，ContextVar 单向 copy）。"""
    return _LAST_PARAM_SENT.get()


def last_finish_reason() -> str:
    """最近一次 chat() 的结束原因（'stop' / 'length' / …）；尚未调用过为空串。"""
    return _LAST_FINISH.get()


def last_reasoning_tokens() -> int:
    """最近一次 chat() 的推理 token 数（厂商不返回该字段时为 0）。"""
    return _LAST_REASONING.get()


def _create_toggle_fallback(client: OpenAI, kwargs: dict, model: str):
    """发一次调用；若带出的 thinking 参数被网关拒绝 → 记 traits=false 并裸参数
    **同次**重发一次（发现期上界之一）。第二次仍失败按原异常上抛，回到既有
    退避/模型不可用处置——拒参在 llm 层内部消化，绝不外漏给调用点的吞异常面。"""
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        if kwargs.get("extra_body") and _is_thinking_param_rejection(e):
            record_model_fact(model, thinking_toggle_supported=False)
            bare = {k: v for k, v in kwargs.items() if k != "extra_body"}
            _LAST_PARAM_SENT.set(False)
            return client.chat.completions.create(**bare)
        raise


def chat(
    messages: list[dict],
    temperature: float = 0.6,
    max_tokens: int = 2048,
    model: str | None = None,
    *,
    purpose: str = "",
    evidence_ids: Optional[list] = None,
    force_thinking_off: bool = False,
) -> str:
    """一次性返回完整回复文本。遇 429 自动退避重试。

    Args:
        model: 可选，覆盖配置中的默认模型（用于多模型并行调度）。
        purpose/evidence_ids: 可选，补充到 trace span（便于决策回放）。
    """
    client = _get_client()
    last_err: Exception | None = None
    use_model = model or get_effective_settings().get("llm_model")
    for delay in [0.0] + _RATE_LIMIT_BACKOFFS:
        if delay:
            time.sleep(delay)
        try:
            kwargs = dict(
                model=use_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # 关闭思考模式：默认开思考的模型会吃光 token 且更慢；调研流水线追求
            # 速度与稳定输出，统一关闭。是否带参由 traits 实测 > 名字初值决定。
            if _send_thinking_off(use_model, force=force_thinking_off):
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            _LAST_PARAM_SENT.set(bool(kwargs.get("extra_body")))
            t0 = time.perf_counter()
            resp = _create_toggle_fallback(client, kwargs, use_model)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            content = _strip_think(resp.choices[0].message.content or "")
            finish = str(getattr(resp.choices[0], "finish_reason", "") or "")
            reasoning = 0
            usage = None
            try:
                usage = resp.usage
                if usage:
                    TOKEN_USAGE["total"] += int(usage.total_tokens or 0)
                    details = getattr(usage, "completion_tokens_details", None)
                    reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)
            except Exception:
                pass
            _LAST_FINISH.set(finish)
            _LAST_REASONING.set(reasoning)
            # 参数被接受即沉淀能力事实（仅在 traits 未知时落库，热路径零写盘）。
            if kwargs.get("extra_body") and thinking_toggle_supported(use_model) is None:
                record_model_fact(use_model, thinking_toggle_supported=True)
            # 无侵入埋点：记录本次调用的 trace span。被截断时在 decision 上留痕，
            # 决策回放里一眼看出「这段输出是被 max_tokens 切断的」+ 推理烧了多少。
            decision = purpose
            if finish == "length":
                decision += f"· 输出被截断（推理 {reasoning} tok）" if reasoning else "· 输出被截断"
            try:
                trace.record_span(
                    model=use_model,
                    messages=messages,
                    response=content,
                    usage=usage,
                    latency_ms=latency_ms,
                    decision=decision,
                    evidence_ids=evidence_ids,
                )
            except Exception:
                pass
            return content
        except Exception as e:  # noqa: BLE001
            last_err = e
            if not _is_rate_limit(e):
                _raise_if_model_unavailable(e)
    assert last_err is not None
    raise last_err


def chat_json(
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
    model: str | None = None,
    *,
    purpose: str = "",
) -> Optional[Any]:
    """要求 LLM 输出 JSON，解析为对象；失败返回 None（调用方决定是否重试）。

    截断契约阶梯（L4）：解析失败 ∧ 本次调用 `finish=length` ∧ 上次**未**带关思考
    参数（带参已生效仍截断 → 不盲重试，直接 None 走上层可见降级）时，带参重试
    恰好一次。traits 实测「不支持关参」的模型跳过（不浪费往返）。每调用额外往返
    ≤1，叠加 chat 内拒参回退 ≤1——发现期上界 ≤2，结论入 traits 后永久短路。"""
    raw = chat(messages, temperature=temperature, max_tokens=max_tokens,
               model=model, purpose=purpose)
    parsed = _extract_json(raw)
    if (parsed is None and _LAST_FINISH.get() == "length"
            and not _LAST_PARAM_SENT.get()):
        use_model = model or get_effective_settings().get("llm_model")
        if use_model and thinking_toggle_supported(use_model) is not False:
            raw = chat(messages, temperature=temperature, max_tokens=max_tokens,
                       model=model,
                       purpose=f"{purpose}·截断契约重试(关思考)" if purpose else "截断契约重试(关思考)",
                       force_thinking_off=True)
            parsed = _extract_json(raw)
    return parsed


def chat_schema(
    messages: list[dict],
    coerce,
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    model: str | None = None,
    purpose: str = "",
):
    """结构化输出：要求 LLM 输出 JSON，再用 coerce(raw) 容错校验为目标 Schema。

    coerce: Callable[[Any], Any]，把原始解析结果规整成 Schema（丢非法字段/越界）。
    失败返回 coerce(None) 或 None。
    """
    raw = chat_json(messages, temperature=temperature, max_tokens=max_tokens,
                    model=model, purpose=purpose)
    try:
        return coerce(raw)
    except Exception:
        return None


def _extract_json(text: str) -> Optional[Any]:
    if not text:
        return None
    # 去掉 ```json 围栏
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    # 优先尝试整体解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 退而求其次：候选按**起始位置**排序取先解析成功者（起点相同时对象优先）。
    # 不能再按「数组优先」的固定顺序试：模型只要在对象外面加一句寒暄，
    # 贪婪的 `\[.*\]` 就会把对象内部的数组整段抓走并解析成功，
    # 于是返回 list 而非 dict，调用方的 isinstance(data, dict) 判定落空 →
    # 静默走兜底（真实故障：48 位专家每次只用那 6 位，见 quiet-shore-pike R3）。
    cands: list[tuple[int, int, str]] = []
    for prio, pat in enumerate((r"\{.*\}", r"\[.*\]")):
        m = re.search(pat, text, re.S)
        if m:
            cands.append((m.start(), prio, m.group(0)))
    for _, _, blob in sorted(cands):
        try:
            return json.loads(blob)
        except Exception:
            continue
    return None


def chat_stream(
    messages: list[dict],
    temperature: float = 0.6,
    max_tokens: int = 2048,
    model: str | None = None,
) -> Iterator[str]:
    """流式返回文本增量（供思维流逐条 append）。"""
    client = _get_client()
    use_model = model or get_effective_settings().get("llm_model")
    try:
        stream = client.chat.completions.create(
            model=use_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except LLMModelUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        _raise_if_model_unavailable(e)
