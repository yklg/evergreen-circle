"""目的地级舆情采集段的安全网（词云口碑化架构修复计划 v7 · 步骤 0）。

这条链路（engine.py 舆情采集 for 循环）此前**零测试**：景点级 `_collect_spot_comments`
有 test_sentiment_by_spot.py 守着，目的地级却一个用例都没有，而它正是修复计划要下手的
地方（切片 bug + 后续 doc_kind 分流）。

守护的不变量：
- I7 相关性硬门槛：题不对版的结果必须被剔除；
- 且**剔除不得占用 `platform_take` 名额** —— 名额是「要收多少条口碑」的配额，
  不是「要看多少条搜索结果」。先切片后过滤会把配额花在即将被丢弃的结果上，
  等于用配额预算去买垃圾。

运行：backend/ 下 `pytest tests/test_engine_sentiment_collect.py -q`
"""
import pytest

from app.core import search
from app.core import research_types as RT
from app.core import sentiment as sentiment_mod
from app.core.pipeline.research import engine as O

from test_two_type_pipeline import _install_fakes, _run_pipeline

# 舆情检索角度模板（research_types.py: sentiment_angles），据此把舆情查询与
# 主采集/视角探针的查询区分开——它们共用同一个 multi_search 桩。
_SENTIMENT_ANGLES = ("值得去吗", "怎么样", "踩坑", "真实体验")

_IRRELEVANT_TITLE = "上海迪士尼入园须知"
_IRRELEVANT_SNIPPET = "上海迪士尼度假区最新入园须知与排队时长说明，与本次调研对象无关。"


def _is_sentiment_query(q: str) -> bool:
    return any(a in q for a in _SENTIMENT_ANGLES)


@pytest.fixture()
def sentiment_corpus(monkeypatch):
    """把舆情查询的返回值换成「前 5 条题不对版 + 后 3 条真相关」。

    返回 (计数容器, 恢复句柄)。计数容器记录总共递出了多少条相关结果，
    供断言「相关结果应全部入样」——不写死条数，避免与平台数耦合。
    """
    _install_fakes(monkeypatch)
    base_ms = search.multi_search
    tally = {"relevant_served": 0, "irrelevant_served": 0}
    seq = {"n": 0}

    def fake(queries, *, num=10, site=None, freshness="noLimit"):
        if not any(_is_sentiment_query(q) for q in queries):
            return base_ms(queries, num=num, site=site, freshness=freshness)
        out = []
        # 题不对版排在前：先切片后过滤的实现会正好切走它们
        for _ in range(5):
            seq["n"] += 1
            out.append({"url": f"https://offtopic.example.com/{seq['n']}",
                        "title": _IRRELEVANT_TITLE, "snippet": _IRRELEVANT_SNIPPET,
                        "captured_at": "2026-08-01"})
            tally["irrelevant_served"] += 1
        for _ in range(3):
            seq["n"] += 1
            out.append({"url": f"https://dali.example.com/{seq['n']}",
                        "title": "大理古城夜游实拍",
                        "snippet": "大理古城夜景很美，这是我今年最喜欢的一次骑行。",
                        "captured_at": "2026-08-01"})
            tally["relevant_served"] += 1
        return out

    monkeypatch.setattr(search, "multi_search", fake)
    monkeypatch.setattr(sentiment_mod, "chat_json", lambda *a, **k: None, raising=False)
    return tally


def test_irrelevant_results_must_not_consume_take_quota(sentiment_corpus):
    """题不对版不得占用口碑配额：递出的每条相关结果都必须入样。

    步骤 2b 已把 `plat_results[:take]` 改成「先过滤后计数」，本例由 xfail(strict) 转正。
    历史失败模式（留此说明，勿删）：quick 档 take=5，夹具把 5 条垃圾排在前面，
    名额被吃光 → 真实相关口碑一条都进不来。
    """
    tally = sentiment_corpus
    _, _, report = _run_pipeline("guide")

    assert tally["relevant_served"] > 0, "夹具失效：舆情查询没被喂到相关结果"
    assert report["sentiment"]["sample_size"] == tally["relevant_served"], (
        f"递出 {tally['relevant_served']} 条相关口碑，实际入样 "
        f"{report['sentiment']['sample_size']} 条 —— 差额即被提前切掉的配额")


def test_offtopic_results_are_still_dropped(sentiment_corpus):
    """反向守门（现行为即正确）：题不对版的结果一条都不许进样本。

    与上一条配对使用——修 [:take] 时若把过滤一起放宽掉，这条会当场判红。
    """
    tally = sentiment_corpus
    _, _, report = _run_pipeline("guide")

    assert tally["irrelevant_served"] > 0
    texts = [v["text"] for v in report["sentiment"]["voices"]]
    assert not any(_IRRELEVANT_TITLE in t for t in texts), "题不对版内容漏进了舆情原声"


def test_doc_kind_is_recorded_for_every_kept_comment(monkeypatch):
    """步骤 2a：采集层必须对每条入样的舆情文本打标，且判据来自 doc_kind 单一来源。

    本步只要求「打标」——统计与词云此刻仍读全量语料（行为零变化），分流在步骤 4 才生效。
    所以断言的是**接线位置与次数**：classify_doc 恰好被调用「入样条数」次。

    刻意用「相关结果排在前面」的语料，与切片 bug 解耦——否则 [:take] 全被题不对版
    吃掉，一条都不入样，本例会在步骤 2b 之前因为「压根没走到打标」而红，
    那测的就不是 2a 而是 2b 了。
    """
    from app.core import doc_kind as dk

    _install_fakes(monkeypatch)
    base_ms = search.multi_search
    seq = {"n": 0}

    def fake(queries, *, num=10, site=None, freshness="noLimit"):
        if not any(_is_sentiment_query(q) for q in queries):
            return base_ms(queries, num=num, site=site, freshness=freshness)
        out = []
        for q in queries:
            for i in range(3):
                seq["n"] += 1
                good = i < 2  # 每条查询：2 条相关 + 1 条题不对版
                out.append({
                    "url": f"https://{'dali' if good else 'off'}.{seq['n']}.example.com/p",
                    "title": "大理古城夜游实拍" if good else _IRRELEVANT_TITLE,
                    "snippet": ("大理古城夜景很美，这是我今年最喜欢的一次骑行。" if good
                                else _IRRELEVANT_SNIPPET),
                    "captured_at": "2026-08-01"})
        return out

    monkeypatch.setattr(search, "multi_search", fake)
    monkeypatch.setattr(sentiment_mod, "chat_json", lambda *a, **k: None, raising=False)

    calls: list[tuple[str, str]] = []
    real_classify = dk.classify_doc

    def spy(url, title, text):
        kind, reasons = real_classify(url, title, text)
        calls.append((url, kind))
        return kind, reasons

    monkeypatch.setattr(O, "classify_doc", spy)
    _, _, report = _run_pipeline("guide")

    kept = report["sentiment"]["sample_size"]
    assert kept > 0, "夹具失效：没有口碑入样"
    assert len(calls) == kept, (
        f"打标 {len(calls)} 次 ≠ 入样 {kept} 条：classify_doc 必须恰好对每条入样评论调一次")
    assert {k for _, k in calls} <= set(dk.KINDS), "打标产出了未登记的类型"
    assert all(u.startswith("https://dali.") for u, k in calls if k == "review"), \
        "题不对版内容被判成了口碑"


def test_sentiment_finding_thought_reports_doc_kind_distribution(monkeypatch):
    """可观测性：`doc_kind` 分布必须出现在运行流 thought 里，不能只落 DB。

    这张分布表是本次验收的必查数（用来判 ctrip/mafengwo 分流后是否归零）。
    只写库不写 trace，就意味着每次验收都要有人手工开 sqlite 查 —— 那等于没有可观测性。
    """
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide")

    texts = [e["data"].get("text", "") for e in evs if e["type"] == "thought"]
    hits = [t for t in texts if "文档类型分布" in t]
    assert hits, "舆情汇总 thought 没报文档类型分布"
    tail = hits[-1]
    assert "review" in tail, f"分布里连口碑桶都没有：{tail}"
    # thought 里报的数必须与落库口径一致（同一份语料，两处不得各算一套）
    assert f"{report['sentiment']['corpus_size']} 条" in tail, tail

