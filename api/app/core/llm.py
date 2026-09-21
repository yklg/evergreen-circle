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
import time
from typing import Any, Iterator, Optional

from openai import OpenAI

from app.core import trace
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
    """判断模型是否支持思考模式开关（glm-5 系列、glm-4.6 支持 thinking 参数）。"""
    m = model.lower()
    return "glm-5" in m or "glm-4.6" in m or "glm-4-6" in m


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


def chat(
    messages: list[dict],
    temperature: float = 0.6,
    max_tokens: int = 2048,
    model: str | None = None,
    *,
    purpose: str = "",
    evidence_ids: Optional[list] = None,
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
            # 关闭思考模式：glm-5 系列默认开思考，会吃光 token 且更慢；
            # 调研流水线追求速度与稳定输出，统一关闭（实测质量仍很高）。
            if _supports_thinking(use_model):
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            t0 = time.perf_counter()
            resp = client.chat.completions.create(**kwargs)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            content = _strip_think(resp.choices[0].message.content or "")
            usage = None
            try:
                usage = resp.usage
                if usage:
                    TOKEN_USAGE["total"] += int(usage.total_tokens or 0)
            except Exception:
                pass
            # 无侵入埋点：记录本次调用的 trace span
            try:
                trace.record_span(
                    model=use_model,
                    messages=messages,
                    response=content,
                    usage=usage,
                    latency_ms=latency_ms,
                    decision=purpose,
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
    """要求 LLM 输出 JSON，解析为对象；失败返回 None（调用方决定是否重试）。"""
    raw = chat(messages, temperature=temperature, max_tokens=max_tokens,
               model=model, purpose=purpose)
    return _extract_json(raw)


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
    # 退而求其次：抓第一个 { } 或 [ ]
    for pat in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pat, text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
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
