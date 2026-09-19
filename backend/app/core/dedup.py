"""信源组归一化工具：把内容级同质（转载文）归并为「一个信源组」。

架构约束（见 accuracy-objectivity-hardening.md）：
- 本模块只被采集层（orchestrator._collect_brand）调用，用于生产证据时一次归一化，
  产出 Evidence.source_group / republished_from；
- 下游（claim 置信 / audit 指标 / 报告披露）一律只读 Evidence 上的组字段，
  不得再 import 本模块重算相似度——避免同一概念多份实现。

实现要点（v2.1.2 修正）：
- 中文按字符 n-gram 生成的 token，对「前缀/首段插入」（转载常见改写）极度敏感
  （整段位移 → 指纹完全不同）。因此放弃 SimHash 汉明距离，改用
  **token 集合 + Jaccard 相似度**：位置无关，标题/首段改写后正文 token 集合高度重合，
  同质转载可稳定归并，异文安全分离。
- content_fingerprint 仍为确定性 64-bit 标识（md5(token 集合排序拼接) 前 16 hex），
  供 Evidence.content_hash / 披露展示，跨进程可复现（规避 PYTHONHASHSEED 随机化）。
- 短文本（< DEDUP_MIN_CHARS）不参与归并：短 snippet 间 token 集合极小、Jaccard 抖动大，
  误判成本高于去重收益（沿用 textquality.is_relevant_content 的短文本放行先例）。
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple

# 与既有信源组判同质的 token 集合 Jaccard 阈值：转载改标题/首段后正文 token 集合
# 重合度仍远高于 0.8（同文前缀测试 ≈0.99）；不同内容远低于此。
DEDUP_SIMILARITY_THRESHOLD = 0.80
# 短文本跳过归并的最小字符数（与 textquality.is_relevant_content 的短文本放行先例一致）
DEDUP_MIN_CHARS = 80

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_RE = re.compile(r"[a-z][a-z0-9\-]{1,}")
_NON_TEXT_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]")


def normalize_text(text: str) -> str:
    """小写化 + 去非中英数字符；数字归一位 #。"""
    if not text:
        return ""
    t = _NON_TEXT_RE.sub("", (text or "").lower())
    return re.sub(r"\d+", "#", t)


def _n_grams(norm: str) -> List[str]:
    """中文 2/3/4-gram 滑动窗口 + 英文整词。"""
    out: List[str] = []
    for m in _EN_RE.finditer(norm):
        out.append(m.group(0))
    for seg in _CJK_RE.findall(norm):
        n = len(seg)
        for size in (2, 3, 4):
            if n < size:
                continue
            step = max(1, size - 1)
            for i in range(0, n - size + 1, step):
                out.append(seg[i:i + size])
    return out


def tokenize(text: str, limit: int = 2000) -> List[str]:
    """归一化 + 分词，返回 token 列表（确定性；组内与指纹共用同一产物）。"""
    norm = normalize_text((text or "")[:limit])
    if not norm:
        return []
    return _n_grams(norm)


def content_fingerprint(text: str, limit: int = 2000) -> str:
    """确定性 64-bit 内容标识（16 位 hex）。

    取 token 集合排序拼接后的 md5 前 16 hex——顺序无关、跨进程可复现
    （用 md5 而非内建 hash，规避 PYTHONHASHSEED 随机化）。
    """
    toks = sorted(set(tokenize(text, limit=limit)))
    if not toks:
        return ""
    return hashlib.md5("|".join(toks).encode("utf-8")).hexdigest()[:16]


def hamming(a: str, b: str) -> int:
    """两个 hex 指纹的海明距离（工具函数；指纹为集合标识而非 SimHash）。"""
    x = int(a, 16) ^ int(b, 16)
    return bin(x).count("1")


def token_similarity(a: List[str], b: List[str]) -> float:
    """token 集合 Jaccard 相似度（0..1）：位置无关，对标题/首段改写鲁棒。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def group_new_text(
    new_text: str,
    groups: List[Dict],
    *,
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
    min_chars: int = DEDUP_MIN_CHARS,
) -> Tuple[Optional[str], List[str]]:
    """将新正文归并到既有信源组，返回 (group_id, republished_from)。

    - 空文本 / 短文本（< min_chars）不参与归并 → 返回 (None, [])（按新组处理）；
    - 与某组 token 集合 Jaccard ≥ threshold → 返回该组的 (id, [])，调用方把新 URL 追加进组；
    - 否则返回 (None, [])，表示应开新组。

    groups 形如 [{"id": "g_xxx", "tokens": [...], "urls": [url...]}]，
    由采集边界（_collect_brand）维护。
    """
    if not new_text or len(new_text) < min_chars:
        return (None, [])
    toks = tokenize(new_text)
    if not toks:
        return (None, [])
    for g in groups:
        gid = g.get("id")
        g_toks = g.get("tokens") or []
        if gid and g_toks and token_similarity(toks, g_toks) >= threshold:
            return (gid, [])
    return (None, [])