"""中文词频统计（jieba 分词 + 停用词过滤）——舆情词云的唯一真实数据源。

- 词频全部来自真实评论文本的**出现次数**（weight=计数），LLM 不参与造词。
- jieba 不可用（依赖未装齐等极端部署形态）时如实返回空表：词云缺位，不编造词。
- 排序确定性：频次降序 → 同频按码位序，保证可复现。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

try:  # noqa: C901 —— 依赖缺失是边界场景（部署未 pip install），降级为「不出词云」
    import jieba

    jieba.setLogLevel(60)  # 静音分词日志，避免污染服务 stdout
    _HAS_JIEBA = True
except ImportError:
    jieba = None  # type: ignore[assignment]
    _HAS_JIEBA = False


def _cut(text: str) -> List[str]:
    """分词接缝（测试可 monkeypatch 注入确定性词列）。"""
    if not _HAS_JIEBA or not text:
        return []
    return list(jieba.lcut(text))


# 中文通用虚词/泛义噪声词（保实词：目的地、平台、体感词均不在此表）
_STOPWORDS = frozenset("""
的 了 和 是 我 你 他 她 它 们 就 不 也 都 很 到 说 要 会 着 没 没有 这 那 与 及 或 等 为 以 之
而 但 并 把 被 让 给 从 对 于 在 上 下 中 里 外 个 一些 一点 还是 或者 因为 所以 如果 虽然 但是
已经 可以 可能 应该 需要 觉得 感觉 知道 真的 确实 比较 有点 非常 特别 而且 然后 现在 以后 时候
自己 大家 别人 什么 怎么 为什么 这个 那个 这些 那些 这样 那样 不是 没有 一个 我们 你们 他们
""".split())

_WORD_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·\-]{1,}$")


def top_words(texts: List[str], *, limit: int = 40, min_count: int = 2) -> List[Dict[str, Any]]:
    """词频统计 → [{"word","weight"}]（weight=出现次数）。

    - 词长 <2 或命中停用词或纯符号 → 剔除；出现次数 < min_count 视为噪声。
    - 全停用词/无文本/jieba 缺失 → 空表（调用方据此不产图）。
    """
    if not texts:
        return []
    freq: Dict[str, int] = {}
    for t in texts:
        for w in _cut(t):
            w = w.strip()
            if len(w) < 2 or w in _STOPWORDS or not _WORD_RE.match(w):
                continue
            freq[w] = freq.get(w, 0) + 1
    items = sorted(((w, c) for w, c in freq.items() if c >= min_count),
                   key=lambda kv: (-kv[1], kv[0]))
    return [{"word": w, "weight": c} for w, c in items[:limit]]
