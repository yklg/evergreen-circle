"""HTML 产物安全原语（契约测试 `tests/test_htmlgen_security.py` 的权威实现）。

背景：执行计划 2.3 声称存在但全仓缺失的「htmlgen 安全过滤契约」据此落地。
安全逻辑不依赖任何渲染器；HTML 生成方（前端/脚本）组装用户可控内容时必须经过本模块。

职责边界：
- `safe_url(url)`：仅放行绝对 http(s)，其余一律中立（''）。防 javascript:/data:/协议走私。
- `escape_html(s)`：HTML 转义，防注入到属性/正文。

参考语义：.trae/skills 的桌面 HTML 脚本仅作历史参考，安全规则以本模块为准
（契约测试=单一事实源，后续安全性改动必须同步更新 tests/test_htmlgen_security.py）。
"""
from __future__ import annotations

import re
from html import escape as _html_escape

__all__ = ["safe_url", "escape_html"]

# 绝对 http(s) 才能放行；协议走私变体（大小写 / 前导空白 / 内部控制字符）一律拒绝。
_HTTP_PREFIX = ("http://", "https://")
# 拆掉 URL 内部的控制字符与空白（防 "java\tscript:"、"htt\x00p" 之类的 scheme 走私）
_CTRL_SPACE = re.compile(r"[\x00-\x20\x7f]")


def safe_url(url: str | None) -> str:
    """净化可点击 URL：仅允许绝对 http(s)，其余（含空/相对）返回中立 ''。

    边界防御的合理下限（不承诺全协议检测）：
    - javascript:/data:text/html/vbscript 及其大小写、前导空白、内部空白/换行变体 → ''
    - 相对路径、协议相对路径（//evil）、mailto: 等 → ''（保守，避免点击劫持面）
    """
    if not url:
        return ""
    s = _CTRL_SPACE.sub("", url.strip())
    if not s:
        return ""
    try:
        low = s.lower()
    except Exception:  # noqa: BLE001 —— 非字符串输入按不安全处理
        return ""
    if low.startswith(_HTTP_PREFIX):
        return s
    return ""


def escape_html(s: str | None) -> str:
    """HTML 转义用户可控文本（& < > " '），None → ''。"""
    if s is None:
        return ""
    return _html_escape(str(s), quote=True)