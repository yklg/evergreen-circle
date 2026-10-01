"""平台注册表：URL 分类 / 可信度打分 / 舆情 / `site:` 限定 共用的平台元数据（唯一真相）。

⚠️ 这张表**只授予"认得出"的能力，不授予"抓得到"的能力**——早先的注释把两者混为一谈，
是错的。加一条记录带来的是：该域名的 URL 会被归到这一类（`classify_platform` →
`source_type` 的社媒分支）、拿到对应的基准分、舆情/站内检索能用上它的 `search_site`。
它**不会**产生任何出网请求：流水线今天的真实出网口只有博查 Web Search（`search.py`）
与百度地图服务端 API（`living_circle/baidu_client.py`），10 个平台里 7 个
`cookie_setting_key=""`，另外 3 个的 cookie 键也没有进入任何请求——社交平台直采未实现。
「用户手填网址由服务端直接抓取」的读文件在 `app.core.source_type.SourceKind.fetchable`
与 `fetcher.fetch_page` 上，不在这里。

分层关系：
- 本模块是**社媒站点视图**：类别层的语义（是否入统计、基准分、来源可信级）在
  `app.core.source_type` 的注册表里，那边从这里派生 `hints`（即下面的 `domain_hints`），
  所以导入方向是 source_type → platforms，本模块不得反向导入它。
- 两套平台口径统一在此建模：
  1) 预留 Cookie 直采平台（douyin / xiaohongshu / bilibili）：`cookie_setting_key` 非空，
     意为"将来可靠存储的 cookie 串鉴权"，今天尚无对应代码路径。
  2) 证据/舆情展示平台（含 weibo / zhihu / 携程等 OTA 与旅行社区）：`cookie_setting_key`
     为空字符串，仅用于分类与展示。
- 本模块是叶子模块，仅依赖标准库；调用方单向导入它，不存在循环依赖。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlatformDef:
    key: str                          # 内部标识：douyin / xiaohongshu / bilibili / weibo / zhihu ...
    label: str                        # 中文展示名（报告/UI 用）
    domain_hints: Tuple[str, ...]     # 分类判据：URL 命中其一即归该类别（source_type 从这里取）
    search_site: str                  # 站内检索 site: 域名（复用 sentiment 原 PLATFORM_SITES）
    cookie_setting_key: str           # 对应 runtime_config 的 cookie 配置键；"" = 不支持采集


# 顺序即展示顺序（抖音永远排第一，与历史行为一致）。
PLATFORMS: Dict[str, PlatformDef] = {
    "douyin":      PlatformDef("douyin",      "抖音",   ("douyin",),            "douyin.com",      "douyin_cookie"),
    "xiaohongshu": PlatformDef("xiaohongshu", "小红书", ("xiaohongshu", "xhs"), "xiaohongshu.com", "xhs_cookie"),
    "bilibili":    PlatformDef("bilibili",    "B站",    ("bilibili", "b23.tv"), "bilibili.com",    "bilibili_cookie"),
    # 展示口径平台一并登记，使分类/展示/打分统一；cookie_setting_key="" 表示暂不支持采集
    "weibo":       PlatformDef("weibo",       "微博",   ("weibo",),            "weibo.com",       ""),
    "zhihu":       PlatformDef("zhihu",       "知乎",   ("zhihu",),            "zhihu.com",       ""),
    # OTA / 旅行社区：证据分类与展示口径（舆情平台集按调研类型收敛，见 research_types）
    "ctrip":       PlatformDef("ctrip",       "携程",   ("ctrip",),            "ctrip.com",       ""),
    "qunar":       PlatformDef("qunar",       "去哪儿", ("qunar",),            "qunar.com",       ""),
    "mafengwo":    PlatformDef("mafengwo",    "马蜂窝", ("mafengwo",),         "mafengwo.cn",     ""),
    "fliggy":      PlatformDef("fliggy",      "飞猪",   ("fliggy",),           "fliggy.com",      ""),
    "dianping":    PlatformDef("dianping",    "大众点评", ("dianping",),       "dianping.com",    ""),
}


def classify_platform(url: str) -> str:
    """URL → 平台 key（`source_type.source_type()` 的社媒分支）。

    命中 domain_hints 返回 key，否则返回空字符串（交给调用方继续走 web/official/news 等逻辑）。
    """
    d = urlparse(url).netloc.lower().replace("www.", "")
    for p in PLATFORMS.values():
        if any(h in d or h in url for h in p.domain_hints):
            return p.key
    return ""


def get_platform(key: str) -> PlatformDef:
    return PLATFORMS[key]
