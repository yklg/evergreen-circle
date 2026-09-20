"""舆情/口碑中立模块 `app.core.sentiment`（计划 §3.2 / §4-B4，含舆情需要定案）。

TDD 目标规格：本文件 import `app.core.sentiment`（实现前 collection 报错标识未落地，落地后转绿）。
语义继承自 orchestrator（brand→topic 中性化）+ 新增确定性聚合：
- D1 category_keywords：中/英混合分词、去重保序、空→[]；
- D2/D3 sentiment_relevant：主题≥2字直击即相关；单字主题需关键词背书；空主题宽松放行；
- D4 aggregate_sentiment 空集 → 零计数、空 themes/quotes、不抛；
- D5 带标注证据 → 正/中/负计数正确、主题词频有界、quote 绑定真实 evidence_id。

运行：backend/ 下 `pytest tests/test_sentiment.py -q`。
"""
import pytest

from app.core.sentiment import aggregate_sentiment, category_keywords, sentiment_relevant


# ── D1：category_keywords ──────────────────────────────
def test_category_keywords_mixed_cjk_latin_dedupe():
    kws = category_keywords("交通与票务 Transportation")
    assert "交通" in kws and "票务" in kws, "中文按2字以上短语分词"
    assert any(w for w in kws if w.startswith("transportation") or w == "transportation")
    assert len(kws) == len(set(kws)), "去重保序"


def test_category_keywords_empty():
    assert category_keywords("") == []
    assert category_keywords(None) == []


# ── D2 / D3：sentiment_relevant ─────────────────────────
def test_relevant_topic_hit_with_len2_plus():
    # ≥2 字中文主题直击即相关
    assert sentiment_relevant("黄山", ["山"], "黄山风景区实测", "") is True


def test_relevant_keyword_backing_when_topic_misses():
    # 主题未命中 → 有品类关键词背书即相关
    assert sentiment_relevant("泰山", ["黄山", "缆车"], "缆车排队很久", "") is True


def test_relevant_both_miss_dropped():
    # 主题与关键词皆未命中 → 丢弃
    assert sentiment_relevant("泰山", ["缆车"], "今天天气不错", "") is False


def test_single_char_topic_needs_backing():
    # 单字主题不作为直击（防「山」字误配「黄山/泰山」）——需关键词背书，否则丢弃
    assert sentiment_relevant("山", [], "泰山风景区", "") is False
    assert sentiment_relevant("山", ["泰山"], "泰山风景区", "") is True


def test_empty_topic_lenient():
    # 主题为空 → 宽松放行（不抛、不误杀）
    assert sentiment_relevant("", [], "任意内容", "") is True


# ── D4：aggregate_sentiment 空集 ────────────────────────
def test_aggregate_empty_no_throw_zero_counts():
    out = aggregate_sentiment([], "黄山")
    assert out["positive"] == 0 and out["neutral"] == 0 and out["negative"] == 0
    assert out["themes"] == [] and out["quotes"] == []
    assert out["topic"] == "黄山"


# ── D5：aggregate_sentiment 带标注 → 确定性计数 ─────────────
def _ev(text, sentiment, topic="黄山", theme="缆车", eid=None):
    return {"evidence_id": eid or f"e_{id(text)}", "text": text, "appraisal": sentiment,
            "topic": topic, "theme": theme}


def test_aggregate_counts_and_quotes_bound_to_real_ids():
    evs = [
        _ev("好评缆车刺激", "positive", theme="缆车", eid="e1"),
        _ev("好评风景壮丽", "positive", theme="风景", eid="e2"),
        _ev("差评排队太久", "negative", theme="排队", eid="e3"),
        _ev("中评一般般", "neutral", theme="整体", eid="e4"),
    ]
    out = aggregate_sentiment(evs, "黄山")
    assert out["positive"] == 2 and out["neutral"] == 1 and out["negative"] == 1
    assert out["themes"], "主题词频非空"
    # quotes 必须绑定到真实 evidence_id
    real = {e["evidence_id"] for e in evs}
    for q in out["quotes"]:
        assert q["evidence_id"] in real, "quote 必须绑定真实证据"
    assert out["topic"] == "黄山"


if __name__ == "__main__":
    import sys
    raise SystemExit(pytest.main([__file__, "-q"]))