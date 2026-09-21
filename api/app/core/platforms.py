"""平台注册表：直采 / URL 分类 / 可信度打分 / 舆情 共用的平台元数据（唯一真相）。

设计目标（生长性）：
- 新增平台 = 在 PLATFORMS 加一条记录；行为层（orchestrator / credibility / sentiment）
  全部从此读取，无需改逻辑代码。
- 两套平台口径统一在此建模：
  1) Cookie 直采平台（douyin / xiaohongshu / bilibili）：cookie_setting_key 非空，靠存储的
     cookie 串鉴权。
  2) 证据/舆情展示平台（含 weibo / zhihu / 携程等 OTA 与旅行社区）：cookie_setting_key
     为空字符串，仅用于分类与展示，暂不支持直采。
- 本模块是叶子模块，仅依赖标准库；orchestrator/credibility/sentiment 单向导入它，
  不存在循环依赖。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlatformDef:
    key: str                          # 内部标识：douyin / xiaohongshu / bilibili / weibo / zhihu ...
    label: str                        # 中文展示名（报告/UI 用）
    domain_hints: Tuple[str, ...]     # _source_type 分类：URL 命中其一即判为该平台
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
    """URL → 平台 key（对应 orchestrator._source_type 的社媒分支）。

    命中 domain_hints 返回 key，否则返回空字符串（交给调用方继续走 web/official/news 等逻辑）。
    """
    d = urlparse(url).netloc.lower().replace("www.", "")
    for p in PLATFORMS.values():
        if any(h in d or h in url for h in p.domain_hints):
            return p.key
    return ""


def get_platform(key: str) -> PlatformDef:
    return PLATFORMS[key]
