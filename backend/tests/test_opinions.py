"""opinions 评价短语抽取契约（修复计划 · 步骤 3 · TC-12/13/14）。

沿用 `test_wordfreq.py` 的种子接缝手法：monkeypatch `_cut_tagged` 注入确定性
`(词, 词性)` 序列，使断言与 jieba 词典解耦；另配真 jieba 冒烟，保证生产路径不是
只测了假接缝。

守护的三条硬约束（模块 docstring 有对应说明）：
1. 只在 token 序列上匹配 —— 不得出现字符流碎片；
2. 实体硬排除 —— 词性像评价的地名必须被剔；
3. 三源合一 —— 只靠形容词词性会整批漏掉真实评价词。
"""
import pytest

from app.core import opinions

_ADJ_ONLY = [("很", "d"), ("舒服", "a")]


def _words(out):
    return [d["word"] for d in out]


def _pol(out, word):
    return next(d["polarity"] for d in out if d["word"] == word)


# ── 约束 1：不得出现字符流碎片 ───────────────────────────

def test_TC13_no_cross_token_fragments(monkeypatch):
    """TC-13：短语只能是**连续词元的原样拼接**，不得从字符流上切。

    对字符流跑正则会产出 `有美`/`到美丽`/`光秀丽`/`分美` 这类跨界碎片
    （诊断阶段实测复现过），本例把该失败模式钉死。
    """
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("前所未有", "i"), ("的", "u"), ("美好", "a")])
    got = _words(opinions.extract_opinions(["前所未有的美好"]))
    assert "美好" in got and "前所未有" in got
    for frag in ("有美", "到美丽", "美", "的前", "有美好"):
        assert frag not in got, f"出现字符流碎片：{frag}"


def test_TC13_fragment_defense_holds_under_real_jieba():
    """TC-13 真分词版：不依赖注入，走生产路径复验同一条性质。"""
    if not opinions._HAS_JIEBA:
        pytest.skip("jieba 未安装：接缝降级路径已由下一条覆盖")
    got = _words(opinions.extract_opinions(
        ["大理古城位于云南省西部，是大理最著名的景区，占地面积3平方公里。"]))
    for frag in ("有美", "到美丽", "光秀丽", "分美"):
        assert frag not in got


# ── 约束 2：实体硬排除 ───────────────────────────────────

def test_TC14_entity_hard_exclusion_beats_pos_tag(monkeypatch):
    """TC-14：`攀枝花` 被 posseg 标成成语 `i`，只靠词性白名单会整批漏进地名。

    结论是「i 类里地名与评价成语混居」⇒ 必须由调用方传入实体做双向子串剔除，
    而不是往黑名单里堆地名。
    """
    toks = [("攀枝花", "i"), ("风景如画", "i"), ("大理古城", "ns"), ("苍山", "nr")]
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: toks)
    out = opinions.extract_opinions(["任意"], exclude_entities=["攀枝花", "大理", "苍山"])
    got = _words(out)
    assert "风景如画" in got, "真评价成语不得被连带误杀"
    for e in ("攀枝花", "大理古城", "苍山"):
        assert e not in got, f"实体漏进评价层：{e}"


def test_TC14_substring_of_entity_also_dropped(monkeypatch):
    """TC-14 反向：实体含短语时也剔（「古城」⊆「大理古城」）。"""
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: [("古城", "n"), ("古朴", "a")])
    got = _words(opinions.extract_opinions(["大理古城"], exclude_entities=["大理古城"]))
    assert "古城" not in got and "古朴" in got


# ── 约束 3：三源合一 ─────────────────────────────────────

def test_lexicon_catches_words_posseg_tags_as_noun_or_verb(monkeypatch):
    """`出片`→v、`商业化`→n：只靠形容词词性会漏掉这两个高频口碑词。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("出片", "v"), ("商业化", "n"), ("洱海", "nr")])
    got = _words(opinions.extract_opinions(["很好出片，但商业化严重"], exclude_entities=["洱海"]))
    assert "出片" in got and "商业化" in got


def test_descriptive_blacklist_blocks_non_evaliative_adjectives(monkeypatch):
    """形态像形容词、语义只是客观陈述的词不得凑数（明显/完整/较大…）。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("明显", "a"), ("完整", "a"), ("较大", "a"), ("幽静", "a")])
    got = _words(opinions.extract_opinions(["季节变化不明显"]))
    assert got == ["幽静"]


def test_pattern_degree_plus_adjective(monkeypatch):
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: _ADJ_ONLY)
    out = opinions.extract_opinions(["很舒服"])
    assert _words(out) == ["很舒服"]
    assert _pol(out, "很舒服") == "pos", "舒服 ∈ 正面词表 ⇒ 程度短语继承极性"


def test_pattern_negation_flips_to_negative(monkeypatch):
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("不", "d"), ("舒服", "a")])
    out = opinions.extract_opinions(["不舒服"])
    assert _words(out) == ["不舒服"] and _pol(out, "不舒服") == "neg"


def test_pattern_valve_plus_verb(monkeypatch):
    """`值得去` 被切成 `值得`(v)+`去`(v)，单词元路径拿不到它。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("值得", "v"), ("去", "v")])
    out = opinions.extract_opinions(["值得去"])
    assert _words(out) == ["值得去"] and _pol(out, "值得去") == "pos"


def test_pattern_noun_degree_quantity_is_negative(monkeypatch):
    """`人太多` = 人(n)+太(d)+多(m)，且「多/挤/吵」判负。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("人", "n"), ("太", "d"), ("多", "m")])
    out = opinions.extract_opinions(["人太多"])
    assert _words(out) == ["人太多"] and _pol(out, "人太多") == "neg"


def test_long_span_wins_over_its_own_tail(monkeypatch):
    """「很舒服」与「舒服」不得同时产出——同一篇的同一感受算两遍会虚增权重。"""
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: _ADJ_ONLY)
    assert _words(opinions.extract_opinions(["很舒服"])) == ["很舒服"]


# ── 模式过度捕获的回归（离线重放真实语料时实测漏出过）────

@pytest.mark.parametrize("text,toks", [
    ("不需要理由", [("不", "d"), ("需要", "v"), ("理由", "n")]),
    ("不结婚", [("不", "d"), ("结婚", "v")]),
    ("推荐避开高峰", [("推荐", "v"), ("避开", "v"), ("高峰", "nr")]),
    ("地方很偏僻", [("有些", "r"), ("地方", "n"), ("很", "zg"), ("偏僻", "a")]),
    ("一路上都是风景", [("一路上", "l"), ("都", "d"), ("是", "v"), ("风景", "n")]),
    ("自然风光很好", [("自然风光", "l"), ("很", "d"), ("好", "a")]),
    ("合不合适", [("合不", "l"), ("合适", "a")]),
])
def test_patterns_do_not_over_capture(monkeypatch, text, toks):
    """否定/评价动词/名词前缀/习用语四类模式都不得把普通陈述当口碑。

    逐条都对应离线重放里真实漏出过的产物：`不需要`、`不结婚`、`推荐避开`、
    `地方很偏僻`、`一路上`、`自然风光`、`合不`。
    """
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: toks)
    got = _words(opinions.extract_opinions([text]))
    for bad in ("不需要", "不结婚", "推荐避开", "地方很偏僻", "一路上", "自然风光", "合不"):
        assert bad not in got, f"{text} → 漏出 {bad}"


def test_negation_still_catches_real_adjective_and_valve(monkeypatch):
    """收紧否定模式的反向守卫：真否定评价不得一起被砍掉。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("不", "d"), ("舒服", "a")] if t == "a"
                        else [("不", "d"), ("太", "d"), ("推荐", "v")])
    assert _words(opinions.extract_opinions(["a"])) == ["不舒服"]
    assert _words(opinions.extract_opinions(["b"])) == ["不太推荐"]


def test_degree_matched_by_surface_not_pos_flag():
    """jieba 把「地方很偏僻」里的 很 标成 `zg`，只认 `d` 会整批漏掉程度模式。"""
    toks = [("街", "n"), ("太", "d"), ("吵", "a")]
    spans = opinions._match_spans(toks)
    assert ("街太吵", "neg") in spans


# ── 计数口径：文档频次 ───────────────────────────────────

def test_weight_is_document_frequency_not_occurrences(monkeypatch):
    """同一篇里出现 5 次只记 1；跨 3 篇记 3。

    出现次数会让单篇长文灌水，也与「多少人有这个感受」的语义不符。
    用词表外的形容词，使本例只断言计数口径、不掺入极性判断。
    """
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("素净", "a")] * 5 if t == "a" else [("素净", "a")] * 2)
    out = opinions.extract_opinions(["a", "b", "c"])
    assert out == [{"word": "素净", "weight": 3, "kind": "opinion", "polarity": "neu"}]


def test_polarity_conflict_resolves_to_neutral():
    """pos 与 neg 同时出现 ⇒ 判不准就退回 neu，不硬猜一方。"""
    assert opinions._resolve_polarity({"pos"}) == "pos"
    assert opinions._resolve_polarity({"neg"}) == "neg"
    assert opinions._resolve_polarity({"neu"}) == "neu"
    assert opinions._resolve_polarity({"pos", "neg"}) == "neu"
    assert opinions._resolve_polarity({"pos", "neu"}) == "pos"


def test_polarity_is_order_independent(monkeypatch):
    """I1 确定性：极性裁决不得依赖文档顺序（折叠式合并会在这里翻车）。"""
    seq = {"p": [("不错", "a")], "n": [("宰客", "v")], "u": [("素净", "a")]}
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: seq[t])
    # 同一短语「不错」在 pos 与 neg 两种判定下都出现时，顺序无关地判 neu
    docs_a, docs_b = ["p", "n", "p"], ["p", "p", "n"]
    by_a = {d["word"]: d["polarity"] for d in opinions.extract_opinions(docs_a)}
    by_b = {d["word"]: d["polarity"] for d in opinions.extract_opinions(docs_b)}
    assert by_a == by_b
    assert by_a["不错"] == "pos" and by_a["宰客"] == "neg"


def test_min_count_one_keeps_singletons(monkeypatch):
    """评价天然低频：门槛设 2 就是专门把它们筛掉的（本 bug 的结构性成因）。"""
    monkeypatch.setattr(opinions, "_cut_tagged",
                        lambda t: [("风景如画", "i"), ("热情好客", "i")])
    got = _words(opinions.extract_opinions(["只出现一次"]))
    assert got == ["热情好客", "风景如画"], "同频按码位序，保证可复现"


def test_ordering_is_deterministic(monkeypatch):
    """I1：同输入同输出，且与入参文档顺序无关。"""
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: [("幽静", "a"), ("浪漫", "a")])
    a = opinions.extract_opinions(["x", "y"])
    b = opinions.extract_opinions(["y", "x"])
    assert a == b


# ── 降级与边界 ───────────────────────────────────────────

def test_TC12_degrades_without_jieba(monkeypatch):
    """TC-12：jieba 缺失 ⇒ 不出词、不抛、不造词（与 wordfreq 同纪律）。"""
    monkeypatch.setattr(opinions, "_HAS_JIEBA", False)
    assert opinions._cut_tagged("大理古城夜景很美") == []
    assert opinions.extract_opinions(["大理古城夜景很美"]) == []


def test_empty_inputs_return_empty():
    assert opinions.extract_opinions([]) == []
    assert opinions.extract_topics([]) == []


def test_real_jieba_smoke_on_guide_text():
    """真 jieba 冒烟：生产路径确实能出评价词，且头部不是地名。"""
    if not opinions._HAS_JIEBA:
        pytest.skip("jieba 未安装：接缝降级路径已由上一条覆盖")
    docs = [
        "跟着《去有风的地方》旅行,大理就是这么美~因为太喜欢大理了,前后来了5次大理,"
        "分享我最喜欢、也最值得去的5个小众地方:喜洲古镇:这个是我来大理最喜欢的古镇",
        "洱海确实很美,几年前去过,云南很多美景,有机会还是会去的",
        "大理,古朴幽静。在都市喧嚣中,有那么一些人向往着田园牧歌,追求简约和轻松",
    ]
    got = opinions.extract_opinions(docs, exclude_entities=["大理", "洱海", "云南", "喜洲古镇"])
    words = _words(got)
    assert words, "真分词路径应能抽出评价词"
    assert not {"大理", "洱海", "云南", "喜洲"} & set(words), "地名漏进评价层"
    assert any(w in words for w in ("幽静", "古朴", "喜欢", "值得去", "很美", "轻松")), words


# ── 话题层 ───────────────────────────────────────────────

def test_topics_only_report_listed_entities(monkeypatch):
    """话题层语义 = 「在聊哪个实体」，只统计 prefer_entities 命中项。"""
    monkeypatch.setattr(opinions, "_cut_tagged", lambda t: [("位于", "v"), ("图片", "n")])
    docs = ["大理古城很好", "大理古城和洱海", "喜洲"]
    out = opinions.extract_topics(docs, prefer_entities=["大理古城", "洱海", "喜洲"])
    assert _words(out) == ["喜洲", "大理古城", "洱海"] or \
        sorted(_words(out)) == ["喜洲", "大理古城", "洱海"]
    assert all(d["kind"] == "topic" and d["polarity"] == "neu" for d in out)
    assert next(d for d in out if d["word"] == "大理古城")["weight"] == 2


def test_topics_never_backfills_from_stopword_gaps():
    """关键守卫：实体不足时**不得**回落去取「高频实词」补位。

    `wordfreq._STOPWORDS` 只有 93 个虚词，不含 位于/图片/机型/查询/发表/很多/这里
    —— 补位等于把刚从评价层赶走的页面 chrome 词从话题层后门请回来。
    """
    out = opinions.extract_topics(["位于云南省，图片很多，机型齐全"], prefer_entities=[])
    assert out == []
    for leak in ("位于", "图片", "机型", "很多"):
        assert leak not in _words(out)


# ── I6 单一真相源 ────────────────────────────────────────

def test_sentiment_reads_this_lexicon_not_its_own_copy():
    """I6：`sentiment._rule_sentiment`（LLM 失败兜底的情感判据）必须与本模块共用一张表。

    历史上极性词表是 sentiment._POS/_NEG 两份列表，与词云各读一套 ⇒ 好评率与词云
    对「什么算正面」的理解会悄悄分叉。收敛后新增评价词只需改这里一处。
    """
    from app.core import sentiment as S

    assert S._POS is opinions.POS_TOKENS, "sentiment 仍在用自己的词表副本"
    assert S._NEG is opinions.NEG_TOKENS
    # 兜底判据与抽取判据对同一个词必须同向
    assert S._rule_sentiment("古城很安静，也很干净") == "pos"
    assert S._rule_sentiment("商业化严重，停车难，人太拥挤") == "neg"


# ── TC-21：词表防漂移元测试（I6）───────────────────────────

# 冻结期望集：四张表的**逐项**内容。加词/删词都必须在这里显式出现，否则第 ④ 条报漂移。
# 为什么值得为此维护一份字面量：本轮的病灶就是「词表与准入规则各改各的」，
# 没有这份冻结集，任何人往 POS_TOKENS 里塞一个 jieba 根本不认的词都不会被发现。
_EXPECTED_LEXICON = {
    "POS_TOKENS": frozenset("""
    vlog 不虚此行 不错 丝滑 亲切 人少 优秀 值得 值得再来 值得去 出片 原汁原味 原生态 古朴 喜欢 壮观 好 好吃 好拍 好看 安静 宜人 干净 幽静 强 性价比 恬静 悠闲
    惊艳 惬意 慢 推荐 方便 景美 流畅 流连忘返 浪漫 清新 清静 温暖 漂亮 烟火气 热情 爱了 秀丽 美 美丽 美味 自由 舒服 轻松 适合 适宜 震撼 靠谱 香
    """.split()),
    "NEG_TOKENS": frozenset("""
    bug 不值 不推荐 人挤 偏僻 停车难 劝退 卡 名不副实 商业化 喧闹 嘈杂 坑 垃圾 失望 宰客 差 强制 性价比低 拉胯 拥挤 捆绑 排队 排队久 敷衍 照骗 破旧 缺点 翻车
    脏乱 贵 踩坑 退 避雷 难用
    """.split()),
    "OPINION_LEXICON": frozenset("""
    不值 人挤 人流 值得去 停车难 出片 劝退 原生态 名不副实 商业化 喧闹 宰客 性价比 打卡 拉胯 拥挤 排队 敷衍 烟火气 照骗 网红 翻车 踩坑 避坑
    """.split()),
    "DESCRIPTIVE_BLACKLIST": frozenset("""
    一般 主要 初步 单独 即兴 基本 大型 天然 完整 官方 实际 小型 市级 常见 座位数 所有 敞篷 明显 明确 最新 有名 热门 直接 相关 省级 自驾游 著名 较大 重要
    """.split()),
}


def test_TC21_lexicon_passes_validation():
    """TC-21：当前词表必须**零问题**通过四条检查（守卫对象健康时返回空表）。"""
    assert opinions.validate_lexicon(_EXPECTED_LEXICON) == []


@pytest.mark.parametrize("table, add, remove, expect_hit", [
    # ① 准入类表塞单字词：单词元准入有 len>=2 硬门槛，等于白塞
    ("OPINION_LEXICON", "爽", None, "不可能被准入"),
    # ② 同词既正又负：_polarity_of 先查 neg ⇒ 好评率被静默偏置
    ("POS_TOKENS", "贵", None, "POS/NEG 同词冲突"),
    # ④ 未冻结的新词：加词必须同时改上面的期望集
    ("POS_TOKENS", "绝绝子", None, "未冻结的新词"),
    # ④ 删词同样要红（防止「先删了再说」）
    ("NEG_TOKENS", None, "垃圾", "缺了期望中的词"),
])
def test_TC21_guard_fails_on_broken_lexicon(table, add, remove, expect_hit, monkeypatch):
    """TC-21 自证：往守卫对象里注入坏词，它**必须**报问题（否则守卫是空转的）。"""
    original = getattr(opinions, table)
    broken = original | ({add} if add else set())
    if remove:
        broken = broken - {remove}
    monkeypatch.setattr(opinions, table, broken)
    problems = opinions.validate_lexicon(_EXPECTED_LEXICON)
    assert problems, "注入坏词后守卫仍返回空表 ⇒ 这条守卫是空转的"
    assert any(expect_hit in p for p in problems), problems


def test_TC21_polarity_check_catches_polarity_regression(monkeypatch):
    """③：词表条目必须真能被 `_polarity_of` 读出预期极性。

    自证只能靠改 `_polarity_of` 本身：当前实现是「先查 NEG 再查 POS」，所以对
    `POS_TOKENS - NEG_TOKENS` 的词条恒返回 pos —— 这条检查在**今天**必然为空，
    它守的是将来有人调换查询顺序、或改成按子串先匹配（那会让正词被负词根抢走着色）。
    把这点写进测试，是为了不让它看起来像一条"永远绿的装饰"。
    """
    assert opinions.validate_lexicon(_EXPECTED_LEXICON) == []

    def buggy(word):  # 模拟一次调换：POS 先查 ⇒ NEG 词条读不出 neg
        return "neg" if word in opinions.NEG_TOKENS and word != "垃圾" else ("pos" if word == "垃圾" else "neu")

    monkeypatch.setattr(opinions, "_polarity_of", buggy)
    problems = opinions.validate_lexicon(_EXPECTED_LEXICON)
    assert any("垃圾" in p and "读不出 neg" in p for p in problems), problems
