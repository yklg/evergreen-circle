"""wordfreq 词频统计契约：确定性、过滤规则与 jieba 缺失降级。

种子接缝：monkeypatch wordfreq._cut 注入确定词列，断言与 jieba 词典解耦；
另有一条真 jieba 冒烟（未安装时 skip），保证生产路径不是只测了假接缝。
"""
from app.core import wordfreq


def test_top_words_filters_stopwords_short_and_nonword(monkeypatch):
    """等价类：停用词/单字/数字开头/标点一次全剔除，只留真实词频 ≥min_count 的词。"""
    monkeypatch.setattr(wordfreq, "_cut",
                        lambda t: ["古城", "古城", "很", "v", "，", "3天", "古城"])
    assert wordfreq.top_words(["任意文本"]) == [{"word": "古城", "weight": 3}]


def test_top_words_tie_break_is_codepoint_stable(monkeypatch):
    """同频按码位序（可复现排序）：改输入顺序不得改输出顺序。"""
    monkeypatch.setattr(wordfreq, "_cut",
                        lambda t: ["洱海", "古城", "洱海", "古城"] if t == "a"
                        else ["古城", "洱海", "古城", "洱海"])
    out1 = [w["word"] for w in wordfreq.top_words(["a"])]
    out2 = [w["word"] for w in wordfreq.top_words(["b"])]
    assert out1 == out2 == ["古城", "洱海"]  # 「古」U+53E4 < 「洱」U+64EA


def test_top_words_min_count_and_limit(monkeypatch):
    """噪声词（次数<min_count）剔除；超出 limit 截断，保留高频头部。"""
    seq = {"t": ["旺季", "旺季", "旺季", "旺季", "旺季",
                 "排队", "排队", "排队", "机位", "夜景"]}
    monkeypatch.setattr(wordfreq, "_cut", lambda t: seq[t])
    out = wordfreq.top_words(["t"], limit=2)
    assert out == [{"word": "旺季", "weight": 5}, {"word": "排队", "weight": 3}]


def test_top_words_empty_input_no_cloud():
    """无文本 → 空表（调用方据此不产图）。"""
    assert wordfreq.top_words([]) == []


def test_top_words_all_stopwords_gives_empty(monkeypatch):
    """全停用词文本 → 空表：宁可无词云，不硬凑词。"""
    monkeypatch.setattr(wordfreq, "_cut", lambda t: ["的", "了", "非常", "非常"])
    assert wordfreq.top_words(["t"]) == []


def test_cut_degrades_without_jieba(monkeypatch):
    """jieba 缺失（部署未装依赖）→ _cut 返回空 → 词云如实缺位，不抛不造词。"""
    monkeypatch.setattr(wordfreq, "_HAS_JIEBA", False)
    assert wordfreq._cut("大理古城夜景很美") == []
    assert wordfreq.top_words(["大理古城夜景很美"]) == []


def test_real_jieba_smoke():
    """真 jieba 在位时冒烟：常见景点词能被切成 ≥2 字词并正确计频。"""
    import pytest

    if not wordfreq._HAS_JIEBA:
        pytest.skip("jieba 未安装：接缝降级路径已由上一条覆盖")
    out = wordfreq.top_words(["大理古城夜景很美，值得去", "大理古城人多但是很美"])
    assert {"word": "古城", "weight": 2} in out
