"""信源类别注册表：一个 URL 属于哪类信源、该类信源该怎么被对待（唯一真相源）。

这里建模的是**类别**（`official` / `news` / `douyin` / `user_supplied` …），
一个类别同时携带：中文展示名、可信度基准分、域名判据、能否直抓、是否入统计、
是否参与转载归并、来源可信级。下游一律从此派生，不再各写一份：

  - `credibility.BASE_BY_TYPE`  ← 本表 base_score
  - `platforms.PLATFORMS`       ← 本表的社媒视图（domain_hints / search_site / cookie 键）
  - 前端 `SOURCE_LABEL`         ← 经 `/api/source_kinds` 下发 label_zh（禁止再手写映射表）

历史成因（为何必须收敛到这一处）
--------------------------------
分类判据词表与分类函数曾同时存在于两份模块：本模块（`source_type()`，有测试守护）与
`pipeline/research/collect.py`（`_source_type()`，**生产流水线实际调用的是这一份**）。
两份的内容逐字相同，于是"改一处忘另一处"只会让行为静默分叉，而不会让任何测试变红。
`tests/test_source_registry_single_source.py` 现在把这种回潮钉成静态守卫。

语义约定：
  - 社媒平台优先（由 `platforms.classify_platform` 的 domain_hints 命中）
  - 论坛/问答 → `zhihu`（社区口碑口径）
  - 财报/投关 → `financial_report`
  - 新闻媒体、机构官网、普通网页逐级回退
中性站点表型判定，与调研对象/题材无关。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from app.core.fetcher import domain_of
from app.core.platforms import PLATFORMS, classify_platform

# 明显非官网的特征（命中则不可能是 official）
NON_OFFICIAL_HINTS: Tuple[str, ...] = (
    "blog", "news", "wiki", "csdn", "jianshu", "juejin", "zhihu", "baijiahao",
    "toutiao", "medium", "wordpress", "cnblogs", "segmentfault", "oschina",
)

# 论坛/问答 → 并入社区口碑
FORUM_HINTS: Tuple[str, ...] = ("tieba.baidu", "douban", "v2ex", "reddit", "quora")

# 财报 / 投资者关系（关键词同时查域名与整串 URL）
FINANCIAL_HINTS: Tuple[str, ...] = (
    "ir.", "investor", "annualreport", "sec.gov", "10-k", "财报", "年报",
)

# 新闻媒体（国内主流 + 科技财经媒体的常见域名片段）
NEWS_HINTS: Tuple[str, ...] = (
    "news", "36kr", "sina", "163.com", "qq.com", "ifeng", "sohu",
    "huxiu", "tmtpost", "caixin", "yicai", "people.com", "xinhuanet",
    "thepaper", "cls.cn", "stcn", "eastmoney", "cnbeta", "leiphone",
    "iyiou", "geekpark", "techcrunch", "theverge", "bloomberg",
)


@dataclass(frozen=True)
class SourceKind:
    key: str                       # 写进 evidences.source_type 的稳定标识
    label_zh: str                  # 中文展示名（报告 / 证据链 / 情报中心饼图）
    base_score: int                # credibility 基准分（域名权威/低质修正另计）
    hints: Tuple[str, ...] = ()    # 域名/URL 片段判据（社媒类由 platforms 提供）
    fetchable: bool = False        # 允许"用户给一个地址、服务端直接去抓"
    in_stats: bool = True          # 是否计入 platform_distribution
    in_groups: bool = True         # 是否参与转载归并（False 会破坏"杜绝转载冒充多源"）
    provenance: str = "remote"     # remote=搜索引擎返回（半可信）/ user=用户手填（不可信）
    must_read: bool = False        # 必读：入池时占保留槽，不被位置截断挤出 prompt


# ── 非社媒类别 ──────────────────────────────────────────────────────
_FIXED_KINDS: Tuple[SourceKind, ...] = (
    SourceKind("official", "机构官网", 70, fetchable=True),
    SourceKind("financial_report", "财报/投关", 75, fetchable=True),
    SourceKind("news", "新闻媒体", 60, hints=NEWS_HINTS, fetchable=True),
    SourceKind("web", "普通网页", 30, fetchable=True),
    SourceKind("review", "点评聚合", 32),
    SourceKind("unknown", "未归类", 30),
    # 本需求新增：用户手填地址直抓。可直抓、入统计、参与归并，但来源不可信 ⇒ 必过内网闸门；
    # 且它是"必读文档"⇒ 入池占保留槽（A-1 的修法就落在这个字段上）。
    SourceKind("user_supplied", "用户指定", 60, fetchable=True,
               provenance="user", must_read=True),
)

# zhihu 既是社媒平台（domain_hints 命中）又承担"论坛/问答"归并口径，故单独给分数。
_ZHIHU_BASE_SCORE = 50

# 社媒/OTA 类别的基准分：与 platforms.PLATFORMS 的键一一对应。
# 这些分值是从收敛前的 credibility._BASE_BY_TYPE 逐项搬来的，
# 由 tests/test_pool_membership_baseline.py 的黄金等值断言钉住（搬错即红）。
_PLATFORM_BASE_SCORES: Dict[str, int] = {
    "douyin": 35,
    "xiaohongshu": 38,
    "bilibili": 45,
    "weibo": 40,
    "zhihu": _ZHIHU_BASE_SCORE,
    "ctrip": 52,
    "qunar": 48,
    "mafengwo": 50,
    "fliggy": 46,
    "dianping": 48,
}


def _platform_kinds() -> List[SourceKind]:
    """由 platforms 注册表派生社媒/OTA 类别（label 与 domain_hints 同源，不再手抄）。"""
    out: List[SourceKind] = []
    for key, plat in PLATFORMS.items():
        out.append(SourceKind(
            key=key,
            label_zh=plat.label,
            base_score=_PLATFORM_BASE_SCORES[key],
            hints=plat.domain_hints,
            fetchable=True,
        ))
    return out


SOURCE_KINDS: Dict[str, SourceKind] = {
    k.key: k for k in (*_FIXED_KINDS, *_platform_kinds())
}

# credibility 的唯一数据源（取代它自己那份字面量表）。
BASE_BY_TYPE: Dict[str, int] = {key: kind.base_score for key, kind in SOURCE_KINDS.items()}

# 前端展示名的下发视图（`/api/source_kinds`）；单条顺序按分值降序，便于 UI 直接分段。
def kind_view() -> List[Dict[str, object]]:
    return [
        {"id": k.key, "label": k.label_zh, "in_stats": k.in_stats}
        for k in sorted(SOURCE_KINDS.values(), key=lambda x: (-x.base_score, x.key))
    ]


def kind_label(key: str) -> str:
    """类别的中文展示名；未登记类别回落 key 本身（不抛错、不塌成"未归类"）。

    报告与前端都从这里取名，别再各写一份 id→中文 的映射表（§二 G0：标签的真相源是注册表）。
    """
    kind = SOURCE_KINDS.get(key)
    return kind.label_zh if kind else key


def is_must_read_kind(key: str) -> bool:
    """该类别的证据是否**必须进写作/分析上下文**（保留槽判据）。

    判据取自注册表的 `must_read` 字段：用户手填（`provenance="user"`）的网址是"必读文档"，
    位置截断会把排在第 21 条之后的那份挤出写作 prompt，于是"用户信源没被引用"根本分不清
    是没引用还是没进上下文（计划 v3 §一 A-1）。
    放在这里而不是调用点写死 `source_type == "user_supplied"`：类别语义归注册表管，
    将来再加一类必读信源（如内部资料库）只改这张表。
    """
    kind = SOURCE_KINDS.get(key)
    return bool(kind and kind.must_read)


def looks_official(domain: str) -> bool:
    """粗略判断是否像机构官网：层级浅（主域+顶级域）、不含博客/新闻/社区特征。"""
    if any(h in domain for h in NON_OFFICIAL_HINTS):
        return False
    parts = [p for p in domain.split(".") if p]
    if len(parts) <= 3 and parts and len(parts[0]) <= 18:
        return True
    return False


def source_type(url: str) -> str:
    """URL → 信源类别 key。**分类判据只有这一处**。"""
    d = domain_of(url)
    plat = classify_platform(url)        # 社媒优先（domain_hints 由 platforms 注册表提供）
    if plat:
        return plat
    if any(h in d for h in FORUM_HINTS):
        return "zhihu"                   # 论坛/问答归到社区口碑
    if any(k in (d + url) for k in FINANCIAL_HINTS):
        return "financial_report"
    if any(k in d for k in NEWS_HINTS):
        return "news"
    if not d:
        return "web"
    # 仅当域名形态像「机构官网」时才判 official；其余归普通网页，
    # 避免把不权威的新闻/博客误判为官网（对应需求：置信度修正）。
    if looks_official(d):
        return "official"
    return "web"
