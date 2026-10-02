"""R23-B1 · 「这一类整轮没跑过扩词」必须留痕（现实额度下这是**常态**，不是边角）。

现场读数（stub 客户端，零真实调用）：步行 standard 的 POI 首轮额度是 31 次，
A 阶段 25 词 × 页深 1 = 25，三要素 **2** 次（`market` 复用类目通道、只 pharmacy/primary 另检索，
见 `poi_collector.py` 的「三要素（盲区硬判）：market 复用类目」）⇒ **剩给 S8 扩词只有 4 次**。
八类里点数未达标的往往有
四到六类，3 次根本摊不到它们 —— 而旧写法在额度归零时是 `while budget.remaining > 0` 静默退出：
既不记 `starved`（没有"某个词被拒"这件事，词甚至没被推导出来），也不动 `aborted`
（它要 `starved` 非空才为真）。于是"这一类整轮没扩"与"这一类不需要扩"在账面上同形。

三种「证据不够」分名分职，本文件只管第四种，并且**刻意不去动 `evidence_complete`**：
那把尺管证据边界（判盲与缓存复用门都吃它），本项管覆盖度分子的召回 —— 并进去会让一次
扩词没钱去降级整份盲区结论的置信度（要不要改是计划 §5 丙那笔账）。
"""
from __future__ import annotations

import asyncio

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import STOP_COMPLETE, PlaceSearchOut
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
# A 阶段按"每词一页"预扣 ⇒ 这一步花掉的就是类目关键词总数；三要素**只发 2 次**
# （`market` 复用类目通道，见 `poi_collector.py` 里「三要素：market 复用类目」那段）。
# 这个字面值不许"顺手改"：它错了下面每条的前置 `stub.n == A_PLUS_TRIAD` 就会红 ——
# 前置就是它的活证人（第一版写 3，把"扩词 0 额度"那一档悄悄让成了 1 额度）。
N_KEYWORDS = sum(len(d["keywords"]) for d in pc.CATEGORY_RULES.values())
N_TRIAD = 2
A_PLUS_TRIAD = N_KEYWORDS + N_TRIAD


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


class Stub:
    """每次调用都回**同一颗**可达区内的点。

    为什么这样造：点位固定 ⇒ 归并后每类圈内只有 1 颗 ⇒ `ideal_circle=3` 的那几类
    （菜市场/医疗/教育/购物）永远未达标、一定会进 B 阶段；而 `ctx.next` 的三路来源
    （名字提炼 / accept_tags / type 补词）在这种载荷下是**有界的** ⇒ 只要摊到额度就至少扩过一次。
    反过来，第一版用"每次一颗新点 + 唯一 type"，词源取之不尽 ⇒ 第一个类把额度全吃掉，
    "钱够就不该进表"那条正向对照什么都测不出（本文件首跑就红在这里）。
    """

    def __init__(self):
        self.n = 0

    async def place_search(self, query, center, **kw):
        self.n += 1
        lng, lat = xy_to_lnglat(CENTER, 300.0, 0.0)
        item = {"name": "一心堂药店", "lng": lng, "lat": lat, "address": "关兴路",
                "tag": "药店", "type": "药店", "uid": "u-fixed"}
        return PlaceSearchOut([dict(item)], 1, 1, STOP_COMPLETE)


class SeedsThenEmpty(Stub):
    """A 阶段照常给点（喂得出可扩的词），扩词一律空手而归 ⇒ 该类被 `quench` 冻结。"""

    async def place_search(self, query, center, **kw):
        if self.n < A_PLUS_TRIAD:
            return await Stub.place_search(self, query, center, **kw)
        self.n += 1
        return PlaceSearchOut([], 0, 1, STOP_COMPLETE)


def _run(total: int, stub=None):
    scope = _scope()
    s = stub or Stub()
    col = asyncio.run(pc.collect_poi(s, CENTER, 2000.0, scope=scope,
                                     budget_snapshot=pc.POIBudget(total=total)))
    return col, s, scope


def _in_circle_of(col, scope, cat) -> int:
    """该类**归并后落在可达区内**的点数 —— 与生产收手闸用的是同一个原语，不留第二份算法。"""
    return pc._in_circle_count(col.per_category.get(cat, []), scope)


def _expanded_categories(ev: pc.CollectionEvidence) -> set:
    """从举证行数**推**出"跑过扩词的类"：某类行数 > 它的关键词数 ⇒ 至少扩过一次。

    不硬编"哪一类先拿到额度"：B 阶段按 `CATEGORY_RULES` 的插入序摊，那是实现细节，
    钉进断言就等于把字典序写进契约（A 阶段特意转置过，见 `poi_collector.py:560` 那段）。
    ⚠️ 三要素那几行用的是 `pharmacy` / `primary` 这类注册表键，不在 `CATEGORY_RULES` 里 ⇒ 先跳过。
    """
    per: dict = {}
    for row in ev.per_term:
        per[row.category] = per.get(row.category, 0) + 1
    return {c for c, n in per.items() if c in pc.CATEGORY_RULES and n > len(pc.CATEGORY_RULES[c]["keywords"])}


# ───────────────────────── 1. 没钱 ⇒ 进表，且指得到是哪几类 ─────────────────────────

def test_unfunded_categories_are_recorded_when_the_budget_is_already_gone():
    col, stub, scope = _run(A_PLUS_TRIAD)      # A 阶段 + 三要素刚好花光，扩词 0 额度
    ev = col.evidence
    assert stub.n == A_PLUS_TRIAD, f"实际发了 {stub.n} 次，与额度 {A_PLUS_TRIAD} 不符 ⇒ 前置不成立"
    assert ev.expansion_unfunded, "额度归零且有类别未达标，却一个都没记 ⇒ 缺陷仍在"
    assert set(ev.expansion_unfunded).isdisjoint(_expanded_categories(ev)), (
        f"跑过扩词的类被记成没跑：{ev.expansion_unfunded}")
    for cat in ev.expansion_unfunded:
        assert _in_circle_of(col, scope, cat) < pc.CATEGORY_RULES[cat]["ideal_circle"], (
            f"{cat} 进了表，但它的圈内点数已达满分线 ⇒ 它本来就不该扩词")


# ───────────────────────── 2. 钱够 ⇒ 不许进表（反向对照，防恒真） ─────────────────────────

def test_generous_budget_records_nothing():
    """给足额度 ⇒ 每个未达标类至少扩过一次 ⇒ 表必须是空的。

    ⚠️ 这条是本文件的"另一只眼"：只跑第 1 条看不出判据是不是恒绿 —— 任何写法都会"记到点东西"。
    """
    col, _, _ = _run(A_PLUS_TRIAD + 40)
    # 先证"这一轮真的跑了扩词"，否则空表可能只是**没进过 B 阶段** ⇒ 那条否证会恒真。
    assert _expanded_categories(col.evidence), "钱给足了却没跑过任何扩词 ⇒ 前置不成立，下面的空表说明不了事"
    assert col.evidence.expansion_unfunded == (), (
        f"钱够却还是记了没跑：{col.evidence.expansion_unfunded}")


def test_partial_funding_only_lists_the_ones_that_got_nothing():
    """额度只够一类扩词 ⇒ 表里应是"其余未达标类"，摊到那次的类不在表里。"""
    col, _, _ = _run(A_PLUS_TRIAD + 1)
    ev = col.evidence
    expanded = _expanded_categories(ev)
    assert len(expanded) == 1, f"1 个单位应只喂到一类，实测 {sorted(expanded)}"
    assert ev.expansion_unfunded, "还有别的类没摊到额度，表却是空的"
    assert set(ev.expansion_unfunded).isdisjoint(expanded), "摊到额度的类不得进表"


# ───────────────────────── 3. 「没词可扩」与「被冻结」都不是「没钱」 ─────────────────────────

def test_exhausted_vocabulary_is_not_reported_as_unfunded(monkeypatch):
    """`ctx.next()` 返空 ⇒ 停手的原因是"没词"，绝不能记成"没钱"（两种缺陷分名分职）。

    ⚠️ 额度必须是 `A_PLUS_TRIAD + 1`（扩词头寸**恰好 1**）而不是 `A_PLUS_TRIAD`（0）：
    0 头寸时 `while budget.remaining > 0` 根本不进循环，`ctx.next` 一次都没被调用 ⇒
    "没词"这个原因**无从发生**，这条测的就成了守卫而不是归因。第一版写成 0 额度也能绿，
    是因为那时 `A_PLUS_TRIAD` 算错成 28（三要素按 3 次记，实际只发 2 次）⇒ 恰好还剩 1。
    """
    budget = A_PLUS_TRIAD + 1
    # 正半**先**跑（`monkeypatch` 一上就撤不干净）：同一额度下不补丁时表非空 ⇒ 下面的否证不是恒真
    untouched, _, _ = _run(budget)
    assert untouched.evidence.expansion_unfunded, (
        "不打补丁时表也是空的 ⇒ 两半都在比空集，这条测不到任何东西")
    monkeypatch.setattr(pc.ExpansionCtx, "next", lambda self, **kw: None)
    col, stub, _ = _run(budget)
    assert stub.n == A_PLUS_TRIAD, f"打了补丁后仍发了 {stub.n - A_PLUS_TRIAD} 次扩词 ⇒ 前置不成立"
    assert col.evidence.expansion_unfunded == (), (
        "词都推导不出来，却被记成「没钱扩词」：" + str(col.evidence.expansion_unfunded))


def test_quenched_category_leaves_the_list_while_the_others_stay():
    """`quench`（这个词一点新东西都没带来）是**另一种**收手原因 ⇒ 该类从表里消失，其余照旧。

    差分做法（不靠猜实现细节）：同一颗 stub 只多给 1 个额度 ⇒ 第一个未达标类会真跑一次扩词、
    拿到空结果并被冻结 ⇒ 它不再算"没跑过"，而后面那些类依然一分钱没摊到。
    """
    zero_col, _, _ = _run(A_PLUS_TRIAD, SeedsThenEmpty())
    one_col, _, _ = _run(A_PLUS_TRIAD + 1, SeedsThenEmpty())
    zero = set(zero_col.evidence.expansion_unfunded)
    one = set(one_col.evidence.expansion_unfunded)
    assert zero, "0 额度时表是空的 ⇒ 下面这个差分什么都比不出来"
    expanded = _expanded_categories(one_col.evidence)
    assert len(expanded) == 1, f"1 个额度应只喂到一类，实测 {sorted(expanded)}"
    # 被冻结的那一类从表里消失，其余照旧 —— 差集从数据里推，不硬编"谁排在前面"
    assert one == zero - expanded, f"{sorted(zero)} → {sorted(one)}，扩过的那类是 {sorted(expanded)}"


# ───────────────────────── 4. 分职：不许牵连 complete / starved / 判定域 ─────────────────────────

def test_new_slot_does_not_leak_into_complete_or_starved():
    """`evidence_complete` 管证据边界（判盲与复用门吃它），本项管分子召回 ⇒ 两把尺不复用。

    这条断的是**今天的行为**：额度归零、几类没跑扩词，`complete` 仍按"发出去的词都查全了"给 true。
    """
    col, _, _ = _run(A_PLUS_TRIAD)
    ev = col.evidence
    assert ev.expansion_unfunded and ev.starved_terms == ()
    assert ev.aborted is False and ev.complete is True


def test_detail_and_payload_carry_the_same_list():
    """写侧只许一处：`as_detail()` → `scope.payload()`，读侧不许自己数点位。"""
    col, _, scope = _run(A_PLUS_TRIAD)
    detail = col.evidence.as_detail()
    assert detail["expansion_unfunded_categories"] == list(col.evidence.expansion_unfunded)
    bound = scope.with_evidence(
        col.evidence.triad_frontier_m(("market", "pharmacy", "primary")),
        complete=col.evidence.complete, detail=detail)
    cal = bound.payload(get_caliber("walking"))      # `payload()` 返回的就是 caliber 本身
    assert cal["evidence_expansion_unfunded_categories"] == list(col.evidence.expansion_unfunded)
    assert cal["evidence_expansion_unfunded_categories"], "空表 ⇒ 这条在比两个空集，什么都测不出"


# ───────────────────────── 5. 报告侧那句：第三子句 ─────────────────────────

def test_report_prints_the_third_clause_only_for_categories_in_the_list():
    from app.core.pipeline import diagnosis_templates as dt

    cal = {"evidence_expansion_unfunded_categories": ["medical"]}
    med = dt._evidence_gap_note(cal, "medical", "医疗")
    edu = dt._evidence_gap_note(cal, "education", "教育")
    assert med == "另需交代：本轮没有额度为这一类扩词（一个扩词词都没发起）" + dt._GAP_TAIL, med
    assert edu == "", f"教育类不在这张表里却印了句子：{edu}"
    # 与前两种成因并列时，分隔符与顺序也是契约（三种缺陷各说各的，不许互相吞）
    both = dt._evidence_gap_note(
        {"evidence_starved_terms": ["medical:社区医院"],
         "evidence_expansion_unfunded_categories": ["medical"]}, "medical", "医疗")
    assert both == ("另需交代：本次有 1 个医疗类检索词因预算未发起（medical:社区医院）"
                    "；本轮没有额度为这一类扩词（一个扩词词都没发起）" + dt._GAP_TAIL), both
