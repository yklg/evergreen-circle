"""甲-B（#87）· 盲区三要素的额度保底：谁让位、让位是否可见、关掉保底必须当场红。

背景一句话：POI 首轮那一格预算是「所有展示检索词 + 三要素 + S8 扩词」**共用的一个池子**，
所以往判表里加一颗词 = 从别的词嘴里抢额度。10-03 给 `elderly` 补了两颗社区养老命名后，
实测（`skip/tmp/plan-87a-elderly-keywords.md` §3）：precise 档 27 单位在旧词表下是
「A 25 + 三要素 2 = 27 恰好」，词表涨到 27 颗后**三要素整组被饿死** —— 而三要素是
盲区 1km 硬判的输入，它们没钱等于「这圈里有没有药店/小学」退化成"没查"。

本文件钉三件事：
① 保底只给 `triad-*` 键（单元面）；
② 走真实采集入口时，额度不够让位的是**展示词**，且让位**照旧进 `starved_terms`**
   （不藏饥饿 —— 这是这套账的底线纪律）；
③ **反向对照**：抹掉保底（把保底谓词改成**恒真** = 改动前"人人可用满额"的形状），
   **同一份输入**下让位的必须换回三要素。没有这一条，②完全可能只是"额度刚好够"的巧合，
   而那条用例是摆设。
"""
from __future__ import annotations

import asyncio

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import PlaceSearchOut, STOP_EMPTY
from app.living_circle.category_rule import CATEGORY_RULES
from app.living_circle.poi_collector import POIBudget

CENTER = (107.9758, 26.5734)

N_DISPLAY = sum(len(d["keywords"]) for d in CATEGORY_RULES.values())
N_TRIAD = len(pc.triad_search_keys())


class _EmptyStub:
    """每词返回 0 颗、stop=`empty` ⇒ 没有任何类因"达标"提前收手，账面只由额度决定。"""

    def __init__(self):
        self.calls = 0
        self.queries: list = []

    async def place_search(self, term, *a, **k):
        self.calls += 1
        self.queries.append(term)
        return PlaceSearchOut([], None, 1, STOP_EMPTY)


def _collect(total: int, reserve_off: bool = False):
    """跑真实采集入口。

    `reserve_off` 的**形状要选对**：抹掉保底 = "所有消费者都能动用满额"，也就是把谓词
    改成**恒真**（`_earmarked → True`），不是恒假。恒假会让三要素键也被 earmark 拦一道，
    变成"双重惩罚"，量的就不是"没有保底"而是"保底把三要素也关在外面"了 ——
    第一版写成恒假，实测把 1 颗展示词也拖下水，归因当场偏掉。
    """
    restore = None
    if reserve_off:
        restore = POIBudget._earmarked
        POIBudget._earmarked = lambda self, category: True
    stub = _EmptyStub()
    budget = POIBudget(total=total)
    try:
        collected = asyncio.run(
            pc.collect_poi(stub, CENTER, 2000.0, object(), budget_snapshot=budget)
        )
    finally:
        if restore is not None:
            POIBudget._earmarked = restore
    return stub, budget, collected


def _split_starved(collected):
    display, triad = set(), set()
    for cat, term in collected.evidence.starved_terms:
        (display if cat in CATEGORY_RULES else triad).add((cat, term))
    return display, triad


def _expansion_rows(collected):
    """本词不属于该类的初始 `keywords` ⇒ 是 S8 扩词发出去的（A 阶段的词都在 used_terms 里）。

    ⚠️ 必须先跳过三要素行：它们用注册表键（`pharmacy`/`primary`）当 category，不在
    `CATEGORY_RULES` 里 —— 第一版没跳，直接 `KeyError: 'pharmacy'`（同 `test_expansion_out_of_budget.py`
    的 `_expanded_categories` 那条注释讲的同一件事）。
    """
    return [t for t in collected.evidence.per_term
            if t.category in CATEGORY_RULES
            and t.term not in CATEGORY_RULES[t.category]["keywords"]]


# ── ① 单元面：保底只对 `triad-*` 键可见 ────────────────────────────

def test_earmark_is_spendable_only_by_triad_keys():
    b = POIBudget(total=3)
    b.earmark = 2
    assert b.consume("market") is True, "非保底部分（3−2=1）应可用"
    assert b.consume("medical") is False, "剩下 2 单位是留给三要素的，展示词不许动用"
    assert b.consume(f"{pc.TRIAD_CONSUME_PREFIX}pharmacy") is True
    assert b.earmark == 1, "三要素花掉保底就要减，不留谁都能花的假余额"
    assert b.consume(f"{pc.TRIAD_CONSUME_PREFIX}primary") is True
    assert b.remaining == 0 and b.earmark == 0


def test_zero_earmark_is_the_pre_existing_behavior():
    """默认 0 = 不保底 = 本字段引入之前的语义（二十多处替身靠它才不用跟着改）。"""
    b = POIBudget(total=2)
    assert b.consume("market") and b.consume("medical")
    assert b.remaining == 0


def test_fork_carries_the_earmark():
    b = POIBudget(total=5)
    b.earmark = 2
    assert b.fork().earmark == 2, "子快照丢掉保底 = 并发分账时三要素没头寸"


# ── ② 入口面：让位的是展示词，而且可见 ──────────────────────────────

def test_reserve_starves_display_terms_not_the_triad():
    """额度比"A 阶段 + 三要素"少一颗时：三要素两颗全拿到，展示词饿死 1 颗，且饥饿照常披露。"""
    stub, budget, collected = _collect(N_DISPLAY + 1)
    display, triad = _split_starved(collected)
    assert not triad, f"三要素被饿死 ⇒ 保底没生效：{sorted(triad)}"
    assert len(display) == 1, f"应恰有 1 颗展示词让位，实际 {sorted(display)}"
    assert stub.calls == N_DISPLAY + 1, "调用数必须等于额度（保底不产生白扣）"
    assert budget.remaining == 0
    assert collected.evidence.complete is False, "让位必须让报告判为证据面不完整，不许读成查全"


def test_reserve_is_released_after_the_triad_run():
    """三要素花不完的保底要交回池子，否则没花出去的钱变成谁也花不着的钱。"""
    _, budget, collected = _collect(N_DISPLAY + N_TRIAD + 3)
    display, triad = _split_starved(collected)
    assert not display and not triad
    assert budget.earmark == 0, "跑完还挂着保底 = 余量被锁死"
    assert _expansion_rows(collected), "交回的余量应喂到 S8 扩词（一个扩词都没发 = 保底没释放）"


# ── ③ 反向对照：保底谓词摘掉，同一输入必须换成三要素饿死 ─────────────

def test_reverse_control_without_the_reserve_the_triad_starves():
    """与 `test_reserve_starves_display_terms_not_the_triad` **同一份输入**（total = N + 1）。

    抹掉保底（谓词恒真 = 改动前"人人可用满额"的形状）后，27 颗展示词把额度吃光，
    三要素只够发第一颗、第二颗饿死 —— 让位的从"展示词"变回"硬判要素"，正是补词当天实测到的形状。
    这条红了才说明上一条的"三要素没饿死"确实由保底产生，不是额度巧合。
    """
    stub, budget, collected = _collect(N_DISPLAY + 1, reserve_off=True)
    display, triad = _split_starved(collected)
    assert not display, f"关掉保底后展示词不该让位（本条只验成因对调），实际 {sorted(display)}"
    assert len(triad) == 1, f"关掉保底后应有 1 颗三要素饿死，实际 {sorted(triad)}"
    assert stub.calls == N_DISPLAY + 1, "同一份额度还是全花掉了，只是落点换了"
    assert budget.remaining == 0
    assert collected.evidence.complete is False


def test_triad_search_keys_are_the_single_source_for_the_reserve():
    """保底数与三要素循环消费的键集合必须同源（第二份"发几次"迟早和池子对不上）。"""
    keys = set(pc.triad_search_keys())
    assert keys == {"pharmacy", "primary"}, f"三要素键集变了（{sorted(keys)}）⇒ 上面的账要重算"
    assert "market" not in keys, "market 复用类目通道，占保底就是虚增头寸"
    _, _, collected = _collect(N_DISPLAY + N_TRIAD)
    fired = {t.term for t in collected.evidence.per_term if t.category in keys}
    assert fired == {pc.triad_keywords(k)[0] for k in keys}, (
        f"实际发出的三要素词与 `triad_keywords` 不一致：{sorted(fired)}")


# ── ④ 优先序的地板：保底不得推翻"每类至少一颗首词"这条更老的契约 ──────
#
# `test_forensic_rounds.py::test_u38c_starvation_lands_on_category_tails` 早在阶段 3 就钉住了
# "预算再紧也不整类蒸发"。保底刚加进来时把它打红了（total=8 时两类被清零）⇒ 正确处置不是
# 改那条契约的期望值，而是给保底加地板：连"每类一颗"都摊不满时保底自动退让。

FIRST_WORDS = {d["keywords"][0] for d in CATEGORY_RULES.values()}


def test_floor_yields_the_reserve_when_one_word_per_category_does_not_fit():
    """total = 类别数 ⇒ 保底退让：八类首词全活，三要素整组饿死（落点回到甲-B 之前的形状）。"""
    total = len(CATEGORY_RULES)
    stub, _budget, collected = _collect(total)
    assert FIRST_WORDS <= set(stub.queries), (
        f"退让区里仍有类目一颗词都没拿到 ⇒ 地板没生效，缺：{sorted(FIRST_WORDS - set(stub.queries))}")
    _display, triad = _split_starved(collected)
    assert len(triad) == N_TRIAD, f"这一档该由三要素让位，实际饿死 {sorted(triad)}"


def test_reserve_and_first_word_per_category_coexist_at_a_real_tier():
    """真实档位那一幕（total = 词数 = precise 的那一格）：**两条契约同时成立**。

    让位的是 `shopping` 的尾部词，既不是任何类的首词，也不是三要素 —— 这条是本批唯一能证明
    "补词没有把某一大类挤没"的读数，不看它就只能靠 §3 那张探针表说话。
    """
    stub, _budget, collected = _collect(N_DISPLAY)
    display, triad = _split_starved(collected)
    assert not triad, f"真实档位下三要素不该让位：{sorted(triad)}"
    assert display, f"额度本就差 {N_TRIAD} 颗，总得有人让位；一个都不让说明保底没咬动"
    starved_terms = {t for _c, t in display}
    assert not (starved_terms & FIRST_WORDS), (
        f"让位落在首词上 = 整类蒸发回来了：{sorted(starved_terms & FIRST_WORDS)}")
    assert FIRST_WORDS <= set(stub.queries)
