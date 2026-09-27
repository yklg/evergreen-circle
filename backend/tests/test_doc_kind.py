"""doc_kind 文档类型判定契约（修复计划 · 步骤 1 · TC-16/17/18）。

三条种子不变量：
- I7 相关性/类型门槛：非口碑文本不得混进词云，且剔除理由可交代（reasons 非空）；
- I6 单一真相源：「算不算口碑」只有 `counts_as_review` 一处判据；
- I2 缺省即降级不造假：未打标 = UNKNOWN，不进词云但计入统计。

TC-18 是**特征化金标准**：夹具取自真实报告 r_6dadffee 的 25 条舆情证据，
逐条人工定标后冻结。判据表任何一次改动都必须在这 25 条上复现人工结论，
否则就是拿真语料换了个错判法。
"""
import json
from pathlib import Path

import pytest

from app.core import doc_kind

_FIXTURE = Path(__file__).parent / "fixtures" / "sentiment_corpus.json"
_CORPUS = json.loads(_FIXTURE.read_text(encoding="utf-8"))["rows"]

# 人工定标分布（写死而非从夹具反推，否则夹具错了自己验自己）
EXPECTED_TALLY = {"review": 7, "seo": 5, "ticket_faq": 5, "guide": 3, "flight": 3, "news": 1, "chrome": 1}


@pytest.mark.parametrize("row", _CORPUS, ids=lambda r: r["title"][:24])
def test_TC18_golden_corpus_classification(row):
    """TC-18：25 条真实舆情语料的判定必须逐项复现人工定标。"""
    kind, reasons = doc_kind.classify_doc(row["url"], row["title"], row["text"])
    assert kind == row["expected_kind"], (
        f"判成 {kind}，人工定标 {row['expected_kind']}\n"
        f"  标题：{row['title'][:60]}\n  理由：{reasons}")
    assert reasons, "判定必须给出可交代的命中说明（供 trace 与验收对照）"


def test_TC18_review_yield_is_reported_honestly():
    """金标准分布冻结：口碑只占 28%，这正是词云失真的根因量级。"""
    kinds = [doc_kind.classify_doc(r["url"], r["title"], r["text"])[0] for r in _CORPUS]
    tally = doc_kind.kind_counts([{"doc_kind": k} for k in kinds])
    assert {k: v for k, v in tally.items() if v} == EXPECTED_TALLY
    assert sum(EXPECTED_TALLY.values()) == len(_CORPUS) == 25


# ── TC-16 判据优先级 ─────────────────────────────────────

def test_TC16_hard_exclusion_wins_over_review_gate():
    """TC-16：一条文本同时带口碑形态与票务/交通标记时，硬排除类先截走。

    真实形态：携程景点详情页常抄一段「适合生活的地方，当地人日出而作」，
    含感受句式但本质是票务页；航班页也可能出现「我去过」。
    """
    mixed_ticket = ("https://you.ctrip.com/sight/dali/1.html",
                    "大理古城门票/地址/图片/开放时间【携程攻略】",
                    "我去过很多次，这里是个适合生活的地方，让人感到很可惜。")
    assert doc_kind.classify_doc(*mixed_ticket)[0] == "ticket_faq"

    mixed_flight = ("https://flights.ctrip.com/schedule/lzo.dlu.html",
                    "泸州到大理航班查询, 泸州到大理航班时刻表【携程机票】",
                    "我去过，准点率、座位数、机型都让人失望。")
    assert doc_kind.classify_doc(*mixed_flight)[0] == "flight"


def test_TC16_page_shell_wins_over_everything():
    """TC-16：JS 墙/登录墙排最前——壳文本里混着真实标题也不许当口碑。"""
    shell = ("https://jingxuan.douyin.com/m/video/1",
             "网红骑马闯洱海 大理古城很好玩",
             "We're\nsorry\nbut\nreact app\ndoesn't\nwork properly\nwithout JavaScript\nenabled."
             "Please enable it to continue.立即打开")
    assert doc_kind.classify_doc(*shell)[0] == "chrome"


def test_near_empty_body_never_reaches_cloud_or_stats():
    """近乎为空的文本进不了词云与统计——但走的是「无标记 ⇒ other」，不是长度门槛。

    刻意不断言它判成 chrome：长度门槛曾把「洱海很美。」这类一句话点评误判成页面壳，
    已删除。真正的守门是「没有任何类型标记就不算口碑」，与文本长短无关。
    """
    kind, _ = doc_kind.classify_doc("https://a.example/x", "大理", "大理很美")
    c = {"text": "大理很美", "doc_kind": kind}
    assert kind != doc_kind.REVIEW_KIND
    assert doc_kind.counts_as_review(c) is False
    assert doc_kind.counts_in_sentiment(c) is False


def test_one_line_chinese_review_is_not_mistaken_for_shell():
    """一句话点评不得被当成页面壳（金标准夹具抓不到的那类错）。

    夹具里 25 条正文都是 100–280 字，所以任何长度阈值都不会让 TC-18 变红；
    而真实的一句话口碑可以只有十几个字。
    """
    short_review = ("https://www.douyin.com/note/1", "洱海骑行",
                    "环海骑行很舒服，风吹过来很自由，这是我今年最喜欢的一天")
    kind, reasons = doc_kind.classify_doc(*short_review)
    assert kind == doc_kind.REVIEW_KIND, f"一句话点评未被认出口碑形态：{reasons}"
    assert len(short_review[2]) < 40, "本例的意义在于它远短于夹具量级"


# ── TC-17 unknown 语义 ───────────────────────────────────

def test_TC17_absent_doc_kind_is_unknown_not_review():
    """TC-17：未打标 = UNKNOWN ⇒ 不进词云（counts_as_review 为假）。"""
    c = {"text": "大理古城夜景很美", "platform": "douyin"}
    assert "doc_kind" not in c
    assert doc_kind.counts_as_review(c) is False


def test_TC17_unknown_still_counts_in_corpus():
    """TC-17：但 UNKNOWN 必须计入 corpus_size——「没判过」不等于「不存在」。

    这条是「保守降级」的落点：若把未打标当成非口碑并从语料里抹掉，任何尚未接线
    doc_kind 的调用路径都会静默产出空舆情，且看不出是被剔了还是压根没采到。
    """
    rows = [{"doc_kind": "review"}, {"text": "无标"}, {"doc_kind": "flight"}]
    counts = doc_kind.kind_counts(rows)
    assert counts[doc_kind.UNKNOWN] == 1
    assert sum(counts.values()) == len(rows)


def test_TC17_empty_doc_kind_string_falls_back_to_unknown():
    """空串/空白不得被当成某个真实类型（防调用方写 `c["doc_kind"] = ""`）。"""
    assert doc_kind.counts_as_review({"doc_kind": ""}) is False
    assert doc_kind.kind_counts([{"doc_kind": ""}])[doc_kind.UNKNOWN] == 1


def test_two_gates_differ_for_unknown():
    """两个判据必须不同：未打标「计入统计但不进词云」。

    合成一条判据会二选一地出错：
    - 都按 review 判 ⇒ 未打标文本冒充观点证据，词云症状原样留下；
    - 都按 unknown 排除 ⇒ 任何尚未接线 doc_kind 的路径静默产出空舆情，
      且分不清「被剔了」还是「压根没采到」。
    """
    unknown = {"text": "未打标"}
    review = {"text": "我去过，很不错", "doc_kind": "review"}
    guide = {"text": "大理三日游攻略", "doc_kind": "guide"}

    assert doc_kind.counts_in_sentiment(unknown) is True
    assert doc_kind.counts_as_review(unknown) is False
    # 真口碑两处都进；非口碑两处都不进（好评率不再被航班查询页稀释）
    assert doc_kind.counts_in_sentiment(review) is True
    assert doc_kind.counts_as_review(review) is True
    assert doc_kind.counts_in_sentiment(guide) is False
    assert doc_kind.counts_as_review(guide) is False


def test_bare_question_is_not_review():
    """提问帖（无人作答）不是口碑：含「我」也不许进正门。

    百度知道/问答类页面大量是「大理好玩吗？求介绍」这种零信息提问，
    放进词云等于让问题本身当评价。
    """
    q = ("https://zhidao.baidu.com/question/1.html", "大理好玩吗",
         "大理好玩吗？第一次去，求介绍一下，谢谢。")
    assert doc_kind.classify_doc(*q)[0] != doc_kind.REVIEW_KIND


def test_review_gate_is_precision_first_by_design():
    """已知召回边界（不是 bug，别当 bug 修）：无第一人称形态标记的评价句会被漏掉。

    「洱海廊道风景好，很舒服」有评价词却没有人称/叙事形态，本闸门判不出它是口碑。
    取向是**精度优先**：漏一条真口碑只是少一个样本，放进一条 SEO 文案则会污染整张
    词云与好评率。召回由采集侧承担（spots 的检索角度已改为「真实评价 / 体验 吐槽」），
    不靠把这张形态表扩到无边界 —— 那会让它与 opinions 的评价词表职责重合。
    """
    missed = ("https://www.douyin.com/note/9", "洱海廊道",
              "洱海廊道风景好，水很清，人也不多，走着很舒服。")
    assert doc_kind.classify_doc(*missed)[0] != doc_kind.REVIEW_KIND


# ── I6 职责边界守卫 ──────────────────────────────────────

# 评价形容词：回答「好不好」，属 opinions 的词表，出现在 doc_kind 即职责越界。
_EVALUATIVE_ADJECTIVES = frozenset({
    "美", "很美", "美丽", "好看", "好玩", "值得", "值得去", "性价比", "古朴", "幽静",
    "浪漫", "舒适", "舒服", "惊艳", "出片", "商业化", "踩坑", "宰客", "照骗", "劝退",
    "失望", "难用", "翻车", "排队", "人挤", "贵", "差", "垃圾",
})


@pytest.mark.parametrize("marks", [doc_kind._REVIEW_MARKS, doc_kind._CHROME_MARKS,
                                   doc_kind._NEWS_MARKS, doc_kind._SEO_MARKS,
                                   doc_kind._GUIDE_MARKS],
                         ids=["review", "chrome", "news", "seo", "guide"])
def test_lexicon_boundary_marks_are_form_not_opinion(marks):
    """I6：doc_kind 只准放「形态/站点/人称」标记，评价形容词一律归 opinions。

    两个词表回答的是不同问题：doc_kind 问「这段文本像不像真人在讲自己的经历」，
    opinions 问「这些人觉得怎么样」。混用会造出第二套评价口径，
    而好评率与词云一旦各读一套，数字就对不上（本计划 D3 要修的正是这个）。
    """
    leaked = [m for m in marks if m in _EVALUATIVE_ADJECTIVES]
    assert not leaked, f"评价形容词漏进 doc_kind 形态表：{leaked}"


def test_every_kind_in_rules_is_declared():
    """判据表不得产出 KINDS 之外的类型（防加规则忘登记，导致报表出现野桶）。"""
    produced = {k for k, _, _ in doc_kind._RULES}
    assert produced <= set(doc_kind.KINDS)
    assert produced == set(doc_kind.KINDS) - {"other"}, "other 是兜底桶，不该出现在规则表里"
