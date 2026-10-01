"""文本质量过滤（对应需求：网页乱码、题不对版）。

- is_garbled：检测乱码（替换符占比、不可打印字符占比、CJK/可读字符比例过低）。
- is_relevant_content：抓回的正文做目的地/关键词二次相关性校验
  （search.py 只在搜索阶段按标题/摘要过滤，抓回的正文可能跑题）。
"""
from __future__ import annotations

import re

_REPLACEMENT = "\ufffd"  # � 替换符
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_READABLE_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9，。、；：？！,.\s]")


def is_garbled(text: str) -> bool:
    """启发式判断文本是否乱码。"""
    if not text:
        return False
    n = len(text)
    if n < 10:
        return False

    # 替换符占比过高
    repl = text.count(_REPLACEMENT)
    if repl / n > 0.02:
        return True

    # 不可打印控制字符占比
    ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    if ctrl / n > 0.05:
        return True

    # 可读字符（中英数字标点空白）占比过低 → 大概率乱码
    readable = len(_READABLE_RE.findall(text))
    if readable / n < 0.6:
        return True

    return False


def _keywords(query: str, destinations):
    kws = set()
    for b in (destinations or []):
        if b:
            kws.add(str(b).lower())
    # query 里的英文词与中文词
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (query or "").lower()):
        kws.add(w)
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", query or ""):
        kws.add(w.lower())
    return {k for k in kws if k}


def is_relevant_content(text: str, destinations, query: str = "") -> bool:
    """正文二次相关性校验：至少命中一个目的地名或查询关键词。

    宽松策略——只要命中任一目的地或关键词即视为相关，避免误杀。
    文本过短（多为 snippet 兜底）直接放行，交由可信度降级处理。
    """
    if not text or len(text) < 80:
        return True
    low = text.lower()
    # 目的地命中优先
    for b in (destinations or []):
        if b and str(b).lower() in low:
            return True
    # 关键词命中
    kws = _keywords(query, destinations)
    hits = sum(1 for k in kws if k in low)
    return hits >= 1 if kws else True


def _query_terms(query: str) -> set:
    """任务级 query 的可匹配词元：拉丁词 + CJK 片段（长片段再切 2-gram）。

    `_keywords` 用 `[\u4e00-\u9fff]{2,}` 取**极大**连续段，"大理亲子游攻略" 会整串成一个词元，
    正文里几乎不可能原样出现 ⇒ 用它判"跑题"会把绝大多数合法信源误判成跑题。
    目的地判定不受此影响（目的地本来就短），所以这里单独一条路，不改动 `_keywords`。
    """
    terms: set = set()
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (query or "").lower()):
        terms.add(w)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", query or ""):
        terms.add(run)
        if len(run) > 4:
            terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def is_relevant_to_query(text: str, query: str) -> bool:
    """用户指定信源的跑题判据（计划 v3 §一 A-2）：只按**任务级 query** 判，不按目的地判。

    为什么必须另开一条判据：用户钉的常常是一份全省/全国公报，它天然不含某个目的地名，
    用 `is_relevant_content(text, [destination], destination)` 去判必然误杀。
    与 `is_relevant_content` 一致：正文过短（多为 snippet 兜底）直接放行，交由可信度降级处理。
    """
    if not text or len(text) < 80:
        return True
    terms = _query_terms(query)
    if not terms:
        return True
    low = text.lower()
    return any(t in low for t in terms)
