"""R23-B3 · 「这一类扩过词、却在额度见底时仍没达标」必须留痕（计划 §7 丁 → §14）。

现场读数（§18④ 那次重跑，凯里老街，31 次真实调用）：`education` 拿到**全部 4 个**扩词单位、门槛项仍 1/3，
而当时它只被 `truncated` 那一位交代（「有 2 个教育类词发了但没查全」）⇒ 屏上看得到"没翻完"，
看不到"扩词额度也用光了"。真实情况是两件事叠在一起。
⚠️ 本文件第一版这里写的是"四个键全空、上屏是空串"—— **那是错的**：取证脚本绕过了唯一绑定点
`data_source.bind_evidence`，而 `truncated_terms` 只在绑定点注入 ⇒ 那一位在脚本产物里结构性恒空
（计划 §17①）。本位该不该有，不依赖那句错话。

本位与 R23-B1 那一位（`expansion_unfunded`）的分界是 **`searched` 是否为 0**：前者是排程没摊到，
本位是摊到了但额度太薄。B 阶段那条 while 有五种出口，本文件把五种各自的披露归属钉住
（达标 / 没词 / 零增益冻结 / 调用失败 / 额度见底），前四种都**不许**进本位。
"没词"这一种不必单独写一条：`remaining == 0` 时 while 守卫先进不去 ⇒ `ctx.next` 永不被调用 ⇒
`no_vocab` 与本位在结构上互斥，第 2 条（钱够 ⇒ 两位都空）就是它的活证人。

与 B1 同一条纪律：**刻意不动 `evidence_complete`** —— 那把尺管证据边界（判盲与复用门吃它），
本位管覆盖度分子的召回（要不要并是 §7 丙′那笔账）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Set

from app.core.pipeline import diagnosis_templates as dt
from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import STOP_API_ERROR, STOP_COMPLETE, PlaceSearchOut
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
# 与 `test_expansion_unfunded.py` 同一算法：A 阶段每词一页 ⇒ 词数那么多；三要素**只发 2 次**
# （`market` 复用类目通道）。数错了下面每条的 `stub.n` 前置就会红。
# 10-03 甲-B 起三要素那颗数从生产派生（`triad_search_keys()` = 三要素循环与保底共用的同一键集合）。
N_KEYWORDS = sum(len(d["keywords"]) for d in pc.CATEGORY_RULES.values())
N_TRIAD = len(pc.triad_search_keys())
A_PLUS_TRIAD = N_KEYWORDS + N_TRIAD
IDEAL = {cat: defn["ideal_circle"] for cat, defn in pc.CATEGORY_RULES.items()}

# 扩词头寸 0..4：覆盖"现实那一档"（步行 standard 首轮 31 − A 阶段 − 三要素）——
# 10-03 甲补两颗社区养老词前那是 31 − 27 = 4，之后是 31 − 29 = **2**；区间留着往上扫，
# 因为本文件测的是"头寸大小怎么改变归因形状"，不是"今天剩几次"。
HEADROOMS = (0, 1, 2, 3, 4)


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _point(dx: float, dy: float, uid: str, name: str) -> Dict[str, Any]:
    lng, lat = xy_to_lnglat(CENTER, dx, dy)
    return {"name": name, "lng": lng, "lat": lat, "address": "关兴路",
            "tag": "农贸市场", "type": "农贸市场", "uid": uid}


class FixedPoint:
    """每次都回**同一颗**可达区内的点 ⇒ 圈内永不增点（不达标、也不冻结），只烧额度。

    这正是"钱不够"最纯的形态：`ctx.next` 有词、`_at_target` 永远差、`quench` 永不触发 ⇒
    while 只能从"额度见底"那个守卫出口离开。点位彼此同名不同 uid 但**坐标相同**，
    归并只按几何重叠判 ⇒ 永远只算一颗。
    """

    def __init__(self) -> None:
        self.n = 0

    async def place_search(self, query, center, **kw):
        self.n += 1
        return PlaceSearchOut([_point(300.0, 0.0, "u-fixed", "同心农贸市场")], 1, 1, STOP_COMPLETE)


class SeedsThenGrows(FixedPoint):
    """A 阶段照旧给同一颗点（每类起点 1），**扩词每次给一颗远处新点** ⇒ 扩两轮就到标线。

    新点彼此与原点相距 1100m 以上、且都在 ±2000m 方框内 ⇒ 50m 去重与设施归并（按几何重叠判）
    都碰不到它们；名字也各不相同，免得"同名一家"那条实体判据把三颗算成一家。
    """

    _SPOTS = [(1100.0, 800.0), (-600.0, 1500.0), (1600.0, -1200.0)]

    async def place_search(self, query, center, **kw):
        if self.n < A_PLUS_TRIAD:
            return await FixedPoint.place_search(self, query, center, **kw)
        i = self.n - A_PLUS_TRIAD
        dx, dy = self._SPOTS[min(i, len(self._SPOTS) - 1)]
        self.n += 1
        return PlaceSearchOut([_point(dx, dy, f"u-grow-{i}", f"集散市集{i}号")], 1, 1, STOP_COMPLETE)


class SeedsThenEmpty(FixedPoint):
    """扩词一律空手而归 ⇒ 该类被 `quench` 冻结（另一种收手原因）。"""

    async def place_search(self, query, center, **kw):
        if self.n < A_PLUS_TRIAD:
            return await FixedPoint.place_search(self, query, center, **kw)
        self.n += 1
        return PlaceSearchOut([], 0, 1, STOP_COMPLETE)


class FailOnNth(FixedPoint):
    """第 `at` 次**扩词**返回 `None` ⇒ 走 `api_error` 那条出口（第 1 次扩词时 `n == A_PLUS_TRIAD`）。"""

    def __init__(self, at: int) -> None:
        super().__init__()
        self.at = at

    async def place_search(self, query, center, **kw):
        if self.n == A_PLUS_TRIAD + self.at - 1:
            self.n += 1
            return None
        return await FixedPoint.place_search(self, query, center, **kw)


def _run(headroom: int, stub=None, total=None):
    scope = _scope()
    s = stub or FixedPoint()
    # ⚠️ `headroom` 是**名义**头寸 = "总预算减去 A_PLUS_TRIAD"，不等于 S8 真拿得到的单位数：
    # A 阶段每词耗的是**页深** `poi_page_depth(n_terms, total)`（clamp 到 [1,3]），词多/钱多时会 >1。
    # 10-03 甲把词数从 25 抬到 27 之后，`_run(40)` 那一档的真实 B 头寸从 15 掉到 13 单位，
    # "钱多而词少"的前提当场不成立 ⇒ 需要字面头寸的用例请显式传 `total`（见下面 GENEROUS_TOTAL）。
    budget_total = A_PLUS_TRIAD + headroom if total is None else total
    budget = pc.POIBudget(total=budget_total)
    col = asyncio.run(pc.collect_poi(s, CENTER, 2000.0, scope=scope,
                                     budget_snapshot=budget))
    s.budget_remaining = budget.remaining
    assert s.n <= budget_total, (
        f"发了 {s.n} 次，超过额度 {budget_total} ⇒ 扣款与调用不闭合，下面的读数都不可信")
    return col, s, scope


# 充裕档要用**字面**头寸：页深被 clamp 到 3 ⇒ A 恰耗 `3 * N_KEYWORDS`，剩下的才是 B 的头寸。
GENEROUS_TOTAL = 3 * N_KEYWORDS + N_TRIAD + 40


def _expanded_categories(ev: pc.CollectionEvidence) -> Set[str]:
    """从举证行数**推**出"跑过扩词的类"：某类行数 > 它的关键词数 ⇒ 至少扩过一次。

    与 `test_expansion_unfunded.py` 里那份同一算法：不硬编"哪一类先拿到额度"（B 阶段按
    `CATEGORY_RULES` 插入序摊是实现细节，钉进断言就等于把字典序写进契约）。
    ⚠️ 三要素行用的是注册表键（`pharmacy`/`primary`），不在 `CATEGORY_RULES` 里 ⇒ 先跳过。
    """
    per: Dict[str, int] = {}
    for row in ev.per_term:
        per[row.category] = per.get(row.category, 0) + 1
    return {c for c, n in per.items()
            if c in pc.CATEGORY_RULES and n > len(pc.CATEGORY_RULES[c]["keywords"])}


def _failed_categories(ev: pc.CollectionEvidence) -> Set[str]:
    """留下 `api_error` 行的类 —— 这一档另有 `complete=False` 出口，不该被说成"没钱"。"""
    return {r.category for r in ev.per_term if r.stop_reason == STOP_API_ERROR}


def _at_target(col, scope, cat: str) -> bool:
    """收手判据只读生产那一份实现，不留第二把尺。"""
    return pc._at_target(cat, col.per_category.get(cat, []), scope, IDEAL.get(cat, 1))


# ──────── 1. 正半 + 额度敏感性扫：本位只收"跑过却没钱"的类，且与第三位互斥 ────────

def test_out_of_budget_only_lists_classes_that_actually_ran():
    """现实额度（头寸 0..4）逐档扫：本位 ⊆ 跑过扩词的类，且与 `unfunded` 交集为空。

    写成关系断言而不是钉死"第几类"：见 `_expanded_categories` 的说明。
    ⚠️ 至少要有一档非空，否则这一整条退化成"比几个空集"。
    """
    any_hit: List[str] = []
    for headroom in HEADROOMS:
        col, _, _ = _run(headroom)
        ev = col.evidence
        hit = set(ev.expansion_out_of_budget)
        assert hit <= _expanded_categories(ev), (
            f"头寸 {headroom}：没跑过扩词的类被记成跑到一半 {sorted(hit - _expanded_categories(ev))}")
        assert hit.isdisjoint(ev.expansion_unfunded), (
            f"头寸 {headroom}：同一类既进'整轮没跑'又进'跑到一半'："
            f"{sorted(hit & set(ev.expansion_unfunded))}")
        any_hit += list(hit)
    assert any_hit, f"头寸 0..4 一档都没记过 ⇒ 本位的谓词大概恒假：{HEADROOMS}"


# ──────── 2. 反向对照：钱够 ⇒ 两位都空（防"任何写法都会记到东西"） ────────

def test_generous_budget_records_neither_expansion_key():
    """额度充裕 ⇒ 每类都能扩到"没词/达标/冻结"之一而停，两位都必须是空的。

    这条同时是"没词"那一种出口的证人：它钱多而词少，若本位把"词榨干了"也说成"没钱"就会红。

    ⚠️ 前置证人（10-03 补词那天补上的）：**跑完钱必须还有剩**。本条要的是"钱多而词少"，
    而"钱多"以前只是名义值 —— 页深随 `total/n_terms` 跳到 2 之后，名义 40 单位里 A 阶段
    实际吃掉 54，留给 S8 的只有 13，购物那一类真就被切在半路（本条就是这样红的）。
    没有这条前置，"两位都是空"和"额度其实不够、只是恰好没人被记"两种形状长得一样。
    """
    col, stub, _ = _run(0, total=GENEROUS_TOTAL)
    ev = col.evidence
    assert stub.budget_remaining > 0, (
        f"额度花到剩 {stub.budget_remaining} ⇒ '钱多'这个前提不成立，下面的空表什么都不是")
    assert _expanded_categories(ev), "钱给足了却没跑过任何扩词 ⇒ 前置不成立，下面的空表说明不了事"
    assert ev.expansion_out_of_budget == (), f"额度充裕却记了跑到一半：{ev.expansion_out_of_budget}"
    assert ev.expansion_unfunded == (), f"额度充裕却记了整轮没跑：{ev.expansion_unfunded}"


# ──────── 3. 零头寸 ⇒ 只属于第三位（本位必须严格窄于"没钱"） ────────

def test_zero_headroom_is_unfunded_not_out_of_budget():
    """头寸 0：一类扩词都没发起 ⇒ 进 `unfunded`，**绝不**进本位。

    这条是第 1 条的另一半：只看 1 看不出本位是不是把 unfunded 抄了一遍。
    """
    col, stub, _ = _run(0)
    ev = col.evidence
    assert stub.n == A_PLUS_TRIAD, f"0 头寸却发了 {stub.n - A_PLUS_TRIAD} 次扩词 ⇒ 前置不成立"
    assert ev.expansion_unfunded, "0 头寸时'整轮没跑'那一位却是空的 ⇒ 对照失效"
    assert _expanded_categories(ev) == set(), "0 头寸却有类跑过扩词 ⇒ 上面的对照失效"
    assert ev.expansion_out_of_budget == (), (
        f"一次都没发起却记成'跑到一半'：{ev.expansion_out_of_budget}")


# ──────── 4. 达标收手不是"没钱"（同一头寸换桩做差分） ────────

def test_at_target_stop_is_not_reported_as_out_of_budget():
    """同一头寸（2）：给"扩两轮就到标线"的载荷 ⇒ 那一类从本位消失。

    差分而不是猜实现：两趟都是同一个类先拿到额度，唯一区别是收手原因（达标 / 额度见底）。
    """
    grew, _, scope = _run(2, SeedsThenGrows())
    money, _, _ = _run(2)
    ran = _expanded_categories(grew.evidence)
    assert len(ran) == 1, f"2 个头寸应只喂到一类，实测 {sorted(ran)}"
    cat = next(iter(ran))
    assert cat in money.evidence.expansion_out_of_budget, (
        f"对照那一趟没把 {cat} 记进本位 ⇒ 差分两头都空，下面的否证恒真")
    assert _at_target(grew, scope, cat), f"{cat} 在达标那一趟里其实没达标 ⇒ 前置不成立"
    assert cat not in grew.evidence.expansion_out_of_budget, (
        f"{cat} 已经扩到达标线，却被记成'额度见底'")


# ──────── 5. 零增益冻结不是"没钱" ────────

def test_quenched_stop_is_not_reported_as_out_of_budget():
    """`quench`（这个词一点新东西都没带来）是**另一种**收手原因 ⇒ 该类不进本位。

    同一头寸（1）换桩差分：固定点那一趟该类进本位，空手而归那一趟它被冻结 ⇒ 退出本位。
    """
    froze, _, _ = _run(1, SeedsThenEmpty())
    money, _, _ = _run(1)
    ran = _expanded_categories(froze.evidence)
    assert ran, "1 个头寸却没跑过扩词 ⇒ 前置不成立"
    assert froze.evidence.expansion_out_of_budget == (), (
        f"零增益冻结的类被记成额度见底：{froze.evidence.expansion_out_of_budget}")
    assert set(money.evidence.expansion_out_of_budget) == ran, (
        f"同一头寸不换桩时本位记的不是这些类（{sorted(money.evidence.expansion_out_of_budget)} "
        f"vs {sorted(ran)}）⇒ 上面那条否证是恒真")


# ──────── 6. 调用失败不是"没钱"（它由 api_error 行披露） ────────

def test_api_error_stop_is_not_reported_as_out_of_budget():
    """第 2 次扩词失败 ⇒ 那一类不进本位，而它确实留下了 `api_error` 行且令 `complete` 为假。

    ⚠️ 本条只钉"失败不许被归因成没钱"。失败那一类此时**两位都不进**，出口在 `complete=False`
    （见 `_record_failure`）；把它的措辞与 §14⑤.3 那笔边角账一起留在计划里，不在这里改判据。
    """
    failed, _, _ = _run(2, FailOnNth(2))
    money, _, _ = _run(2)
    ev = failed.evidence
    ran = _expanded_categories(ev)
    assert ran & _failed_categories(ev), "两趟额度相同却没有'跑过又失败'的类 ⇒ 桩没生效，下面的否证恒真"
    assert set(money.evidence.expansion_out_of_budget) == ran, (
        "对照那一趟本位记的不是同一批类 ⇒ 差分不成立")
    assert ev.expansion_out_of_budget == (), (
        f"因调用失败停手的类被记成额度见底：{ev.expansion_out_of_budget}")
    assert ev.complete is False, "api_error 行没让证据面判为不完整 ⇒ 另一处出口也断了"


# ──────── 7. 写侧只许一处：字段 → as_detail → scope.payload ────────

def test_detail_and_payload_carry_the_same_list():
    col, _, scope = _run(1)
    ev = col.evidence
    assert ev.expansion_out_of_budget, "头寸 1 没记到本位 ⇒ 下面只是在比两个空集"
    detail = ev.as_detail()
    assert detail["expansion_out_of_budget_categories"] == list(ev.expansion_out_of_budget)
    bound = scope.with_evidence(
        ev.triad_frontier_m(("market", "pharmacy", "primary")),
        complete=ev.complete, detail=detail)
    cal = bound.payload(get_caliber("walking"))      # `payload()` 返回的就是 caliber 本身
    assert cal["evidence_expansion_out_of_budget_categories"] == list(ev.expansion_out_of_budget)


# ──────── 8. 读侧：第四子句只为本类印，与前一位并列时顺序/连接符也是契约 ────────

def test_report_prints_the_fourth_clause_only_for_categories_in_the_list():
    both = {"evidence_expansion_unfunded_categories": ["medical"],
            "evidence_expansion_out_of_budget_categories": ["education"]}
    assert dt._evidence_gap_note(both, "education", "教育") == (
        "另需交代：" + dt._GAP_OUT_OF_BUDGET + dt._GAP_TAIL)
    assert dt._evidence_gap_note(both, "medical", "医疗") == (
        "另需交代：" + dt._GAP_UNFUNDED + dt._GAP_TAIL)
    assert dt._evidence_gap_note(both, "shopping", "购物") == "", "两位都不含购物类却印了句子"
    # 键缺席（R23-B3 之前的快照）读作"不知道"，不许印成"没有类别扩到一半停了"
    absent = dt._evidence_gap_note({"evidence_expansion_unfunded_categories": ["education"]},
                                   "education", "教育")
    assert absent == "另需交代：" + dt._GAP_UNFUNDED + dt._GAP_TAIL, absent
    # 同一类**两种成因同时命中** ⇒ 两个子句并列、共用**一个**前缀。
    # ⚠️ 载荷取自 §19 真跑那一格（教育：2 个词没查全 + 扩词额度见底）。这里**不**用
    # 「unfunded + out_of_budget」凑一对 —— 那两位按 `searched` 是否为 0 分家，同一类不可能都占
    # （本文件第 1 节那条互斥扫就是钉这个的），拿永不可达的载荷验"将来上屏那句话"等于没验。
    together = dt._evidence_gap_note(
        {"evidence_truncated_terms": ["education:幼儿园", "education:博南高级中学"],
         "evidence_expansion_out_of_budget_categories": ["education"]}, "education", "教育")
    assert together == ("另需交代："
                        + dt._GAP_TRUNCATED.format(n=2, label="教育",
                                                   terms="education:幼儿园、education:博南高级中学")
                        + "；" + dt._GAP_OUT_OF_BUDGET + dt._GAP_TAIL), together
    assert together.count("另需交代：") == 1


# ──────── 9. §14⑤.3 边角：首次扩词就失败的那一类，那句话必须仍然为真 ────────

def test_a_class_that_failed_its_first_attempt_is_labeled_truthfully():
    """这一类**发起过**一次扩词（只是接口没成），且此时额度归零 ⇒ 它进"整轮没跑成"那一位。

    旧措辞写的是「一个扩词词都没发起」—— 在这一档是**假话**；已改成「一次都没扩成」
    （两种分支都为真）。这条判据同时钉住"它确实发起过"这个事实，免得下次有人把措辞"优化"回去。
    """
    col, _, _ = _run(1, FailOnNth(1))
    ev = col.evidence
    failed = _failed_categories(ev)
    assert len(failed) == 1, f"没造出'首次扩词即失败'那一格：{sorted(failed)}"
    cat = next(iter(failed))
    assert cat in ev.expansion_unfunded, f"{cat} 一分钱没跑成却没进'整轮没跑成'那一位"
    assert cat not in ev.expansion_out_of_budget, "一次都没跑成，不该记成'跑到一半'"
    note = dt._evidence_gap_note({"evidence_expansion_unfunded_categories": [cat]}, cat, cat)
    assert "一次都没扩成" in note, note
    assert "一个扩词词都没发起" not in note, f"说假话的旧措辞回来了：{note}"


# ──────── 10. 并集（乙2）与本位同源：本位记到的类必须一个不落地进并集 ────────

def test_out_of_budget_class_also_lands_in_the_numerator_union():
    col, _, _ = _run(1)
    ev = col.evidence
    assert ev.expansion_out_of_budget, "这一档没记到任何类 ⇒ 下面那条包含关系恒真"
    union = ev.as_detail()["coverage_numerator_incomplete_categories"]
    assert set(ev.expansion_out_of_budget) <= set(union), f"{ev.expansion_out_of_budget} 不在 {union}"
    # 并集只有一份实现：`as_detail()` 不许自己再算一遍（第二份就会有一处漏）
    assert union == list(ev.coverage_numerator_incomplete), f"{union} != {ev.coverage_numerator_incomplete}"
