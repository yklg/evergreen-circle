"""网页来源类型分类（中性站点表型判定，与对象/题材无关）。

从 orchestrator 下沉：把「一个 url 属于什么来源（社媒/新闻/论坛/官网/财报/普通网页）」
这类通用能力从竞品编排中剥离，供目的地调研 live 采集对证据打 source_type，
配合 credibility.score_evidence 做置信度修正。不含任何对象/品牌语义。

语义约定（与 orchestrator 历史行为一致）：
  - 社媒平台优先（注册表 classify_platform 自动识别）
  - 论坛/问答类 → zhihu（社区口碑）
  - 财报/投关 → financial_report
  - 新闻媒体、机构官网、普通网页逐级回退
"""
from __future__ import annotations

from typing import List

from app.core.fetcher import domain_of
from app.core.platforms import classify_platform

# 明显非官网的特征（命中则不可能是 official）
NON_OFFICIAL_HINTS: List[str] = (
    "blog", "news", "wiki", "csdn", "jianshu", "juejin", "zhihu", "baijiahao",
    "toutiao", "medium", "wordpress", "cnblogs", "segmentfault", "oschina",
)


def looks_official(domain: str) -> bool:
    """粗略判断是否像机构官网：层级浅（主域+顶级域）、不含博客/新闻/社区特征。"""
    if any(h in domain for h in NON_OFFICIAL_HINTS):
        return False
    parts = [p for p in domain.split(".") if p]
    # 形如 brand.com / brand.cn / brand.io / brand.com.cn —— 2-3 段且主体不太长
    if len(parts) <= 3 and parts and len(parts[0]) <= 18:
        return True
    return False


def source_type(url: str) -> str:
    d = domain_of(url)
    plat = classify_platform(url)        # 注册表驱动：社媒平台自动识别
    if plat:
        return plat
    if "tieba.baidu" in d or "douban" in d or "v2ex" in d or "reddit" in d or "quora" in d:
        return "zhihu"  # 论坛/问答类归到社区口碑
    # 财报/投关页
    if any(k in (d + url) for k in ("ir.", "investor", "annualreport", "sec.gov", "10-k", "财报", "年报")):
        return "financial_report"
    # 新闻媒体（含国内主流与科技财经媒体的常见域名）
    if any(k in d for k in ("news", "36kr", "sina", "163.com", "qq.com", "ifeng", "sohu",
                            "huxiu", "tmtpost", "caixin", "yicai", "people.com", "xinhuanet",
                            "thepaper", "cls.cn", "stcn", "eastmoney", "cnbeta", "leiphone",
                            "iyiou", "geekpark", "techcrunch", "theverge", "bloomberg")):
        return "news"
    if not d:
        return "web"
    # 仅当域名形态像「机构官网」（短主域、无新闻/博客特征）时才判 official；
    # 其余一律归为普通网页，避免把不权威的新闻/博客误判为官网（对应需求：置信度修正）。
    if looks_official(d):
        return "official"
    return "web"