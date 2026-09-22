"""景点榜单评分（stdlib 叶子模块）：LLM 只抽信号，分数全部由本模块公式算出。

设计约束（与 research_types 同一层规约）：
- **纯函数、确定性**：同一输入两次调用结果全等（可复现、可审计），禁止 random/time/网络。
- **sanitize 在边界**：LLM 抽取的信号可能含负数/None/非数值/越界占比，统一收敛到
  [0, +inf)（占比类收敛到 [0,1]），非法值按 0 计——不抛错、不遮盖（清洗结果随
  `signals_clean` 回传，榜单可展示计算明细）。
- 权重是模块常量：声量 0.4 / 口碑 0.4 / 性价比 0.2；归一化用 max 缩放（榜内相对分）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

WEIGHT_VOICE = 0.4
WEIGHT_SENTIMENT = 0.4
WEIGHT_VALUE = 0.2

# 三类信号 → (原始字段, 是否占比类[0,1])。占比类不做 max 缩放，直接加权。
_SIGNAL_DEFS: Tuple[Tuple[str, str, bool], ...] = (
    ("voice", "mentions", False),
    ("sentiment", "positive_ratio", True),
    ("value", "value_score", False),
)

SCORE_MIN = 0.0
SCORE_MAX = 100.0


def _to_number(raw: Any) -> float:
    """非法/缺失/负数一律按 0 计（bool 视为非法——True 不该等于 1 分信号）。"""
    if isinstance(raw, bool) or raw is None:
        return 0.0
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if val != val:  # NaN
        return 0.0
    return max(0.0, val)


def _clamp_ratio(val: float) -> float:
    return min(max(val, 0.0), 1.0)


def sanitize_signals(row: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    """把一条榜单原始信号收敛为三类规范信号 {"voice","sentiment","value"} → float。

    输入兼容两种形状：row["signals"] 嵌套字典，或 row 顶层直接给字段（LLM 常见漂移）。
    """
    src: Dict[str, Any] = {}
    nested = row.get("signals")
    if isinstance(nested, Mapping):
        src.update(dict(nested))
    for _, field, _ in _SIGNAL_DEFS:
        src.setdefault(field, row.get(field))

    out: Dict[str, float] = {}
    voice = _to_number(src.get("mentions"))
    positive = _clamp_ratio(_to_number(src.get("positive_ratio")))
    value = _clamp_ratio(_to_number(src.get("value_score")))
    out["voice"] = voice
    out["sentiment"] = positive
    out["value"] = value
    return out


def rank_spots(rows: Sequence[Mapping[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    """对景点原始行（含 signals）做归一化加权评分并降序截断。

    返回行 = 原行浅拷贝 + signals_clean（三类规范信号）+ dims（归一化后各维分）
    + score（0-100，保留 1 位小数）。平局按归一化名称再按原序升序，保证稳定。

    归一化规则：
    - voice / value 中 value 视为 [0,1] 相对分直接缩放；voice 按榜内 max 缩放（max=0 时全体 0）。
    - sentiment / value 已是占比，直接 ×100。
    """
    cleaned: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        item = dict(row)
        item["signals_clean"] = sanitize_signals(row)
        item["_orig_idx"] = idx
        cleaned.append(item)

    max_voice = max((c["signals_clean"]["voice"] for c in cleaned), default=0.0)
    for c in cleaned:
        sig = c["signals_clean"]
        voice_norm = (sig["voice"] / max_voice) if max_voice > 0 else 0.0
        dims = {
            "voice": round(voice_norm * 100.0, 1),
            "sentiment": round(sig["sentiment"] * 100.0, 1),
            "value": round(sig["value"] * 100.0, 1),
        }
        score = (WEIGHT_VOICE * dims["voice"]
                 + WEIGHT_SENTIMENT * dims["sentiment"]
                 + WEIGHT_VALUE * dims["value"])
        c["dims"] = dims
        c["score"] = round(min(max(score, SCORE_MIN), SCORE_MAX), 1)
        c["rank"] = 0  # 排序后回填

    cleaned.sort(key=lambda c: (-c["score"], str(c.get("name") or ""), c["_orig_idx"]))
    out: List[Dict[str, Any]] = []
    for rank, c in enumerate(cleaned[:max(0, top_n)], start=1):
        c["rank"] = rank
        c.pop("_orig_idx", None)
        out.append(c)
    return out
