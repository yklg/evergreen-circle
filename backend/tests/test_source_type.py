"""信源分类 `app.core.source_type`（计划 §3.2，由 orchestrator `_source_type` 下沉）。

TDD 目标规格：import `app.core.source_type`（实现前 collection 报错标识未落地，落地后转绿）。
原语义：社媒平台→分类；论坛/问答→"zhihu"；财报/投关→"financial_report"；新闻媒体→"news"；
品牌官网(浅层级、无 blog/news 特征)→"official"；其余→"web"。

运行：backend/ 下 `pytest tests/test_source_type.py -q`。
"""
import pytest

from app.core.source_type import source_type


def test_news_media():
    assert source_type("https://www.36kr.com/p/123") == "news"


def test_forum_thirdparty_reputation():
    assert source_type("https://www.douban.com/group/topic/1/") == "zhihu"


def test_official_looks_like_brand_site():
    assert source_type("https://www.apple.com/") == "official"


def test_blog_hint_never_official():
    assert source_type("https://blog.examplecorp.com/x") == "web"


def test_unknown_or_empty_no_throw():
    # 未知域名合理回退；垃圾输入不抛
    for bad in ("https://xyz-foo-bar.net/page", "", "not-a-url"):
        assert isinstance(source_type(bad), str), f"应返回 str 而非抛错: {bad!r}"


if __name__ == "__main__":
    import sys
    raise SystemExit(pytest.main([__file__, "-q"]))