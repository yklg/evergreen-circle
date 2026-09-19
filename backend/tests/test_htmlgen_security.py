"""htmlgen 安全过滤契约测试（执行计划 2.3 承诺 + 方案 B-08）。

守护不变量（backend/app/core/htmlgen_security.py，契约=单一事实源）：
- safe_url：绝对 http(s) 原样放行；javascript:/data:/vbscript: 及其
  大小写/前导空白/内部空白/换行走私变体 → ''；空/None/相对/协议相对 → ''。
- escape_html：& < > " ' 全转义；None → ''；纯文本保持。
- 纯函数：任意输入不抛异常、可重复调用。
运行：backend/ 下 `pytest tests/test_htmlgen_security.py -q`
"""
import pytest

from app.core.htmlgen_security import escape_html, safe_url


# ── safe_url：等价类（放行 / 拒绝）────────────────────────
@pytest.mark.parametrize("u", [
    "https://example.com/a?b=1&c=2",
    "http://example.com",
    "https://example.com/#frag",
])
def test_safe_url_allows_absolute_http(u):
    assert safe_url(u) == u


@pytest.mark.parametrize("u", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",          # 大小写走私
    " javascript:alert(1)",         # 前导空白
    "java\tscript:alert(1)",        # 内部制表符
    "java\nscript:alert(1)",        # 内部换行
    "\n javascript:alert(1)",
    "data:text/html,<script>1</script>",
    "DATA:TEXT/HTML,x",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "vbscript:msgbox(1)",
    "VBScript:msgbox(1)",
])
def test_safe_url_rejects_dangerous_schemes(u):
    assert safe_url(u) == ""


@pytest.mark.parametrize("u", [
    None, "", "   ", "/relative/path", "foo.html", "//evil.example.com/x", "mailto:a@b.com",
])
def test_safe_url_neutral_for_empty_relative_or_other_scheme(u):
    assert safe_url(u) == ""


def test_safe_url_is_pure_and_repeatable():
    for u in ("https://ok.com", "javascript:x", None, "mm"):
        first = safe_url(u)
        assert all(safe_url(u) == first for _ in range(3))


# ── escape_html：转义全集 + 纯文本保持（幂等下限）──────────
def test_escape_html_escapes_special_chars():
    assert escape_html('<a href="x">&\'</a>') == (
        "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;"
    )


def test_escape_html_none_empty_and_plain():
    assert escape_html(None) == ""
    assert escape_html("") == ""
    assert escape_html("纯文本 123") == "纯文本 123"


def test_escape_html_never_emits_raw_tag():
    for evil in ("<script>", "<img src=x onerror=1>", "</div>", "\"><svg onload=1>", "&amp;"):
        out = escape_html(evil)
        assert out not in ("<script>", "<img src=x onerror=1>", "</div>", "\"><svg onload=1>")


# ── 组合：URL 净化 + 转义后的安全输出──────────────
def test_safe_url_and_escape_compose_safe_html_attr():
    url = safe_url("javascript:alert(1)")
    assert url == ""
    assert url == "" and escape_html(url) == ""
    href = f'href="{escape_html(safe_url("https://a.com/x?y=<z>"))}"'
    assert "<z>" not in href


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))