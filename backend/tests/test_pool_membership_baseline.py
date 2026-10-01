"""信源分类与候选池成员基线（实施计划 v3 §九 · TC-29 真测试）。

守护的契约
----------
计划 v3 的 G0 要把散在多处、且**已存在两份重复实现**的信源分类逻辑收敛进
`app/core/source_type.py`。收敛的前提是「不改变分类结果」——这必须有一个冻结基线，
否则收敛会在没人察觉的情况下改掉某个域名的归属，而下游 `credibility._BASE_BY_TYPE`、
情报中心饼图、舆情平台分派全都按这个 id 分流。

本文件钉三件事：
  1. 一组 URL → 分类 id 的**黄金映射**（G0 迁移前后必须逐条等值）。
  2. 出现过的 id 全集（G0 新增类别时这里会红，逼你把新类别显式登记）。
  3. `collect` / `engine` / `spots` 三个消费者**都直接调用注册表**、自己不留副本
     （G0 的收敛结果；回潮或套壳即红）。

期望值来源
----------
黄金映射与 id 全集**不是手写猜测**，而是按下述命令从当前实现采集后固化：

    cd skip/backend && python3 - <<'PY'
    from app.core import source_type as ST
    for u in URLS: print(u, ST.source_type(u))
    PY

判定的真实依赖链（写在这里以免日后误判"基线错了"）：
  `source_type.source_type()` → `platforms.classify_platform()`（社媒优先）
  → 论坛/问答并入 `zhihu` → 财报关键词 → 新闻关键词 → `looks_official()` → `web`
"""
from __future__ import annotations

import pytest

from app.core import source_type as ST

# ── 采集自当前实现的黄金映射（顺序无关，按 URL 查表）──────────────────
CLASSIFY_GOLDEN = {
    # 社媒平台：注册表优先，域名命中即判该平台
    "https://www.douyin.com/video/123": "douyin",
    "https://b23.tv/abc": "bilibili",
    "https://www.xiaohongshu.com/explore/x": "xiaohongshu",
    "https://www.zhihu.com/question/1": "zhihu",
    "https://zhuanlan.zhihu.com/p/1": "zhihu",
    "https://www.ctrip.com/destination/x": "ctrip",
    "https://www.dianping.com/shop/1": "dianping",
    # 论坛/问答并入社区口碑（FORUM_HINTS 的显式归并）
    "https://tieba.baidu.com/p/123": "zhihu",
    "https://www.douban.com/group/1": "zhihu",
    # 财报/投关（FINANCIAL_HINTS，关键词同时查 domain 与整串 url）
    "https://ir.company.com/annualreport.pdf": "financial_report",
    "https://www.sec.gov/Archives/10-k.htm": "financial_report",
    # 新闻媒体词表（NEWS_HINTS）
    "https://www.36kr.com/p/1": "news",
    "https://finance.sina.com.cn/roll/1": "news",
    "https://www.caixin.com/2024/x.html": "news",
    "https://www.people.com.cn/n1/2024/0101/c1001-1.htm": "news",
    "https://www.thepaper.cn/newsDetail_forward_1": "news",
    "https://www.ifeng.com/a/1": "news",
    "https://news.qq.com/rain/a/1": "news",
    "https://cls.cn/detail/1": "news",
    "https://163.com/dy/article/x.html": "news",
    # 机构官网形态（looks_official：浅层级 + 不命中 NON_OFFICIAL_HINTS）
    "https://dali.gov.cn/zwgk/content.html": "official",
    "https://www.mct.gov.cn/whzx/ggtz/202401/t20240101_1.htm": "official",
    "https://www.baidu.com/": "official",
    # 普通网页：命中非官网特征、层级过深、无域名、无法解析
    "https://blog.example.com/post/1": "web",
    "https://en.wikipedia.org/wiki/x": "web",
    "https://www.csdn.net/article/1": "web",
    "https://www.toutiao.com/a1/": "web",
    "https://baijiahao.baidu.com/s?id=1": "web",
    "https://sub.domain.deep.example.com.cn/a/b": "web",
    "https://a-very-long-subdomain-name-here.travel.example.com/x": "web",
    "": "web",
    "not a url": "web",
}

# 采集中实际出现过的 id 全集。G0 若要新增类别（如 user_supplied），本集合必须同步，
# 且新类别只能由注册表带来 —— 这条断言把「悄悄多出一类」变成一次显式登记。
OBSERVED_IDS = {
    "bilibili", "ctrip", "dianping", "douyin", "financial_report",
    "news", "official", "web", "xiaohongshu", "zhihu",
}


@pytest.mark.parametrize("url", sorted(CLASSIFY_GOLDEN))
def test_classify_golden_each_url(url):
    assert ST.source_type(url) == CLASSIFY_GOLDEN[url], (
        f"{url} 的分类从 {CLASSIFY_GOLDEN[url]!r} 变了。"
        "G0 收敛必须保持逐条等值；确有理由改判请改本表并说明影响面"
        "（下游 credibility._BASE_BY_TYPE / 情报中心 platform_distribution / 舆情平台分派都按它分流）。"
    )


def test_classify_id_universe_is_exactly_the_registered_set():
    """分类输出不得凭空多出/丢失 id（防收敛时漏迁一类，也防顺带新增未登记的类别）。"""
    produced = {ST.source_type(u) for u in CLASSIFY_GOLDEN}
    assert produced, "探针 URL 集一个都没分类出结果 ⇒ 本守卫空转，先确认实现是否被改名"
    assert produced <= OBSERVED_IDS, f"出现未登记的分类 id：{sorted(produced - OBSERVED_IDS)}"
    missing = sorted(OBSERVED_IDS - produced)
    assert not missing, f"在册分类 id 未被任何探针覆盖：{missing}（收敛可能漏掉了那一支）"


def test_collect_delegates_to_the_registry_and_keeps_no_copy():
    """G0 后 `collect` 必须把分类**委托**给注册表，自己不留判据。

    生成本例时 `collect.py` 里有一份逐字相同的副本，那条用例的形状是
    「副本存在 ⇒ 比对两份输出；副本删除 ⇒ skip」。skip 会永远绿，等于没守。
    G0 落地后改写为正向钉法（§十.4 对"永远红不了的用例"的处置口径）：
      - collect 不再有本地 `_source_type`（回潮即红）；
      - collect 用的就是注册表那个函数对象本身（`is` 而非"结果恰好相同"，
        防止有人再写一个"转发壳"把两份实现藏在壳的两边）。
    行为等值另由 `test_classify_golden_each_url` 的 33 条黄金映射守着。
    """
    from app.core.pipeline.research import collect, engine, spots

    assert not hasattr(collect, "_source_type"), (
        "collect.py 里又出现了一份分类实现——G0 的收敛被回退了"
    )
    # 三个消费者同批改、同批钉：漏掉任何一个，它就是下一份"没人调用也没人改"的副本
    for mod in (collect, engine, spots):
        assert getattr(mod, "classify_source", None) is ST.source_type, (
            f"{mod.__name__} 没有直接调用注册表的 source_type()，而是在中间套了一层——"
            "这正是两份实现分叉的起始形状"
        )
