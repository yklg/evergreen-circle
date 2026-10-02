"""R23-I · 报告里那位「成功返回的检索页数」（欠账出处：计划 §22⑧）。

为什么要有这一位：10-03 那次全链路真跑，事前预登记了"这一趟要打多少次接口"，事后在报告里
却**没有任何一把键能核销它** —— `POIBudget.usage` 是**预扣**掉的额度（按计划要翻几页就扣几页），
它回答"我批准了多少"，不回答"到手了多少"。两者在 v5.6「失败不退款 + 记 `api_error` 举证」这条
政策下本来就该不等，而"不等多少"恰恰是每次真跑最想知道的那个成本数。

本位的确切语义（⚠️ 不是"外呼次数"）：`pages_fetched` 只在响应正常（`status == 0`）之后自增
（`baidu_client.py:393`），失败那次当场 `break`、不留计数 ⇒ 每一笔 `api_error` 词行至少欠一次
未被计入的发送。所以 `evidence_pages_returned` 报的是**下界**。要把发送次数记全得往
`PlaceSearchOut` 加字段，那是客户端契约改动（十几处位置构造的测试替身要连账一起核），
留作独立一片 —— 本文件因此**不许**出现"实发次数"这种说法。

发射是**条件**的（`scope.payload()` 里那句 `if "pages_returned" in self.evidence_detail`）：
离线估算与演示夹具从未走过采集，给它们补一份 `0` 等于替一次没发生的外呼举证，而 0 在这里
是有含义的读数（"打了外呼、一页都没回来"）。⇒ 判据必须两面都跑：有明细时发、没明细时不发。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import (
    PlaceSearchOut, STOP_API_ERROR, STOP_COMPLETE, STOP_EMPTY, STOP_PAGE_CAP,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.category_rule import CATEGORY_RULES
from app.living_circle.data_source import bind_evidence
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.quota import poi_page_depth
from app.living_circle.scope import TRIAD_KEYS, SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
RADIUS = 2000.0

# 三种真实形状各挂一个词（都是 `CATEGORY_RULES` 里的**现成关键词**，否则桩压根不会被触发）
TERM_FULL = "超市"        # 3 页翻满、末页仍是满页 ⇒ 被截断，到手 3 页
TERM_EMPTY = "幼儿园"      # 首页就空 ⇒ 查全，到手 1 页
TERM_FAILED = "便利店"     # 首页就没成 ⇒ 到手 0 页（这一页额度花掉了却没拿到东西）
assert TERM_FULL in CATEGORY_RULES["shopping"]["keywords"]
assert TERM_EMPTY in CATEGORY_RULES["education"]["keywords"]
assert TERM_FAILED in CATEGORY_RULES["shopping"]["keywords"]
# 预扣页深必须是 3：这样"计划要 3 页 / 实际到手 ≤2 页"这对读数才真的不等（下面第 4 条判据吃它）
N_KEYWORDS = sum(len(d["keywords"]) for d in CATEGORY_RULES.values())
CHARGED_PAGES_PER_TERM = poi_page_depth(N_KEYWORDS, 100)
assert CHARGED_PAGES_PER_TERM == 3, (
    f"前提不成立：预算 100 下每词预扣 {CHARGED_PAGES_PER_TERM} 页，"
    "桩给的页数就压不出'到手 < 预扣'那道缺口")


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _point(dx: float, name: str, uid: str) -> Dict[str, Any]:
    lng, lat = xy_to_lnglat(CENTER, dx, 0.0)
    return {"name": name, "lng": lng, "lat": lat, "address": "友好路",
            "tag": name, "type": "shop", "uid": uid}


def _items(n: int, tag: str) -> List[Dict[str, Any]]:
    return [_point(200.0 + 10 * i, f"{tag}{i}", f"u-{tag}-{i}") for i in range(n)]


class _ThreeShapes:
    """零 HTTP 的桩：三个词各给一种实测形状，其余词一律「到手 1 页、5 个点、查全」。

    给满 5 个点是为了让 S8 扩词不必替这些类补证据（行数与额度都保持在小而确定的规模上）。
    """

    async def place_search(self, query: str, center: Tuple[float, float], **kw: Any) -> PlaceSearchOut:
        if query == TERM_FULL:
            # 3 页 × 20 条 = 60 条、末页满页、total 也是 60 ⇒ 与"翻满就跑"的截断形状逐字同形。
            # ⚠️ 页数为啥取 3 不取 2：本页另有一行是 0 页（下面那笔失败）。若这里给 2，
            # 一处 +1 与一处 −1 正好抵消 ⇒ "页数之和"与"行数"相等，第 1 条用例的前提断言
            # 会当场抓住（第一版就是这样红的）—— 那正是这三条前提存在的用处。
            return PlaceSearchOut(_items(60, "超市"), 60, 3, STOP_PAGE_CAP)
        if query == TERM_EMPTY:
            return PlaceSearchOut([], 0, 1, STOP_EMPTY)
        if query == TERM_FAILED:
            # 与真实客户端首页失败时的产物逐字同形：无 items、无 total、0 页、原因 api_error
            return PlaceSearchOut([], None, 0, STOP_API_ERROR)
        return PlaceSearchOut(_items(5, query), 5, 1, STOP_COMPLETE)


def _collect() -> pc.PoiCollection:
    return asyncio.run(pc.collect_poi(
        _ThreeShapes(), CENTER, RADIUS, scope=_scope(),
        budget_snapshot=pc.POIBudget(total=100)))


def _row(cat: str, term: str, pages: int, returned: int, stop: str) -> pc.TermEvidence:
    return pc.TermEvidence(category=cat, term=term, requested_radius_m=RADIUS,
                            pages_fetched=pages, returned=returned,
                            total=returned or None, stop_reason=stop,
                            farthest_m=None if stop in (STOP_COMPLETE, STOP_EMPTY) else 800.0)


# ──────────── 1. 真链：发射位 == 生产逐词行的页数之和（同源复算，不是手抄表） ────────────

def test_collect_chain_emits_pages_returned_matching_the_per_term_rows():
    """走 `collect_poi → bind_evidence → payload()` 这条**生产链**，断发射值等于同一趟采集
    逐词行 `pages_fetched` 之和。

    为什么不是写死数字：词数由 `CATEGORY_RULES` 决定、扩词是否发生由达标情况决定，任何字面量
    都会随口径表变动而变成假红。这里的复算取自 `as_detail()["terms"]`（行视图，由 `as_row()`
    产出），与发射值取自 `pages_returned`（求和 property）是**两条不同的生产代码路**，
    所以等式能抓到"求和对象被换成行数/点位数"这类改写。
    """
    collected = _collect()
    cal = bind_evidence(_scope(), collected).payload(get_caliber("walking"))
    rows = collected.evidence.as_detail()["terms"]

    from_rows = sum(int(r["pages_fetched"]) for r in rows)
    assert cal["evidence_pages_returned"] == from_rows, (
        f"发射值 {cal.get('evidence_pages_returned')} 与逐词行之和 {from_rows} 不符")

    # 三条"这组数据不是恰好让错误实现也成立"的前提（缺它们，上面的等式可能只是恒真的影子）
    assert len(rows) != from_rows, (
        f"行数 {len(rows)} 与页数之和 {from_rows} 相等 ⇒ 把 property 写成 `len(per_term)` 也绿，"
        "本用例测不出求和对象")
    assert sum(int(r["returned"]) for r in rows) != from_rows, (
        "点位数之和恰好等于页数之和 ⇒ 读错字段（`returned` 当 `pages_fetched`）也测不出")
    assert any(int(r["pages_fetched"]) != 1 for r in rows), (
        "每一行都只到手 1 页 ⇒ 求和退化成分词计数")


# ──────────── 2. 语义核心：失败那次**不计入**，但必须以 failed 形式可见 ────────────

def test_failed_term_contributes_zero_pages_yet_stays_visible_as_failed():
    """`api_error` 词行给 0 页 ⇒ 不进成本账，但 `failed_terms` 必须点名它。

    这一对断言是本片的全部风险所在：只断"不计入"会鼓励另一种错法（把失败行**删掉**来少算），
    而删掉就回到了 T-P0-3 修掉的那个洞 —— "根本没查成"在报告里什么都留不下。所以两半都要钉：
    账上不出现，名单里必须在。
    """
    collected = _collect()
    ev = collected.evidence
    detail = ev.as_detail()

    failed = [t for t in ev.per_term if t.term == TERM_FAILED]
    assert len(failed) == 1, f"桩没能造出恰好一笔失败行，实测 {len(failed)} 笔"
    assert failed[0].stop_reason == STOP_API_ERROR, failed[0].stop_reason
    assert failed[0].pages_fetched == 0, (
        "前提不成立：失败行带着非 0 页数，下面那句'不计入'就没被测到")
    assert f"{failed[0].category}:{TERM_FAILED}" in detail["failed_terms"], detail["failed_terms"]

    others = [t for t in ev.per_term if t is not failed[0]]
    assert ev.pages_returned == sum(int(t.pages_fetched) for t in others), (
        "失败行的 0 页不该改变求和 —— 但它若是被**丢出 per_term** 来达成同一读数，"
        "上面那条 failed_terms 断言会先红")


# ──────────── 3. 字面量：求和不是分词计数，也不是别的字段 ────────────

def test_pages_returned_is_a_literal_sum_over_rows():
    """手造一份已知页数的账目，钉**字面量**（第 1 条的关系断言抓不到"两边一起改错"）。

    构造：三要素三行各到手 1 页（=3）+ 四行 2/1/0/3 页（=6）⇒ **9**。
    同时这几个数两两不同，所以：写成 `len(per_term)` 得 7、写成点位数之和得 23 —— 都会红。
    """
    rows = [*[ _row(k, f"{k}·三要素", 1, 3, STOP_COMPLETE) for k in TRIAD_KEYS ],
            _row("education", "小学", 2, 5, STOP_PAGE_CAP),
            _row("shopping", "超市", 1, 5, STOP_COMPLETE),
            _row("shopping", "便利店", 0, 0, STOP_API_ERROR),
            _row("recreation", "公园", 3, 4, STOP_PAGE_CAP)]
    ev = pc.CollectionEvidence(requested_radius_m=RADIUS, per_term=tuple(rows))

    assert ev.pages_returned == 9, ev.pages_returned
    # 三个候选错法各自的读数：必须都与 9 不同，否则这份数据 discriminating 不了
    assert len(rows) == 7 and ev.pages_returned != len(rows)
    assert sum(int(t.returned) for t in rows) == 23 and ev.pages_returned != 23

    cal = bind_evidence(_scope(), pc.PoiCollection(
        per_category={}, triads={}, evidence=ev)).payload(get_caliber("walking"))
    assert cal["evidence_pages_returned"] == 9, cal["evidence_pages_returned"]


# ──────────── 4. 与预扣额度的关系：到手 ≤ 批准，且这一趟确实不等 ────────────

def test_pages_returned_is_bounded_by_precharged_quota_and_strictly_below_it():
    """成本账的**另一头**：`POIBudget.usage` 是预扣额度，恒有 `到手页数 ≤ 预扣额度`。

    严格小于那一半才是本片存在的理由 —— 若两个数恒等，读侧直接看额度就够了，不必新增键。
    缺口来自本次桩给的三种形状：每词预扣 3 页（`poi_page_depth(25, 100) == 3`，文件头已断言），
    而到手最多 2 页。
    """
    budget = pc.POIBudget(total=100)
    collected = asyncio.run(pc.collect_poi(
        _ThreeShapes(), CENTER, RADIUS, scope=_scope(), budget_snapshot=budget))
    charged = sum(budget.usage.values())
    returned = collected.evidence.pages_returned

    assert charged > 0, "前提不成立：这趟一次额度都没预扣，下面两条断言是空的"
    assert returned <= charged, f"到手 {returned} 页竟超过预扣 {charged} 次额度"
    assert returned < charged, (
        f"到手 {returned} == 预扣 {charged} ⇒ 本轮没造出'批了没到手'的形状，"
        "这一位与额度就无从区分（本用例的靶子消失）")


# ──────────── 5. 条件发射的两面：没账可报 ⇒ 不出键；真报了 0 ⇒ 键在且是 0 ────────────

def test_key_is_emitted_only_when_the_collection_detail_actually_carries_it():
    """负半在前、正半在后（顺序不能反：只测负半会把"根本没发射"也判成通过）。

    - 正半①：明细带着非 0 页数 ⇒ 键在、值对；
    - 正半②：明细带着**真 0**（一次都没到手）⇒ 键仍在、值仍是 0 ⇒ 挡住 `… or 0` 这类
      "缺键与零值同形"的写法；
    - 负半：从未走过采集的 scope（`detail` 空）⇒ **不出这个键**，而不是替它报 0。
    """
    frontier = {k: _scope().required_radius_m(k) for k in TRIAD_KEYS}

    with_real_number = _scope().with_evidence(
        frontier, complete=False, detail={"pages_returned": 5}).payload(get_caliber("walking"))
    assert with_real_number["evidence_pages_returned"] == 5, with_real_number

    with_true_zero = _scope().with_evidence(
        frontier, complete=False, detail={"pages_returned": 0}).payload(get_caliber("walking"))
    assert "evidence_pages_returned" in with_true_zero, (
        "真 0（打了外呼、一页没回来）被当成'没记账'吞掉了 —— 这两件事是相反的事实")
    assert with_true_zero["evidence_pages_returned"] == 0, with_true_zero

    never_collected = _scope().with_evidence(frontier, complete=False).payload(get_caliber("walking"))
    assert "evidence_pages_returned" not in never_collected, (
        "从未采集的口径格发出了页数 ⇒ 离线估算/夹具被替一次没发生的外呼举了证")


# ──────────── 6. 零行为变更：新增载荷键不许动复用门 ────────────

def test_new_key_does_not_move_the_reuse_gate():
    """`reuse_policy` 逐字不看这一位 ⇒ 带着它和不带它必须同判。

    这条是"批次零回归" claim 的落点：这一位进了 `caliber` 载荷，而缓存与邻近复用吃的就是
    那份载荷。若哪天有人把它变成复用判据（比如"到手页数为 0 就不给复用"），本用例先红 ——
    那种降级应当由 `evidence_complete` 那条链负责，不该藏在成本读数里。
    """
    from app.living_circle.report_contract import reuse_policy
    from app.living_circle.scope import COVERAGE_CALIBER_VERSION, SCOPE_POLICY_VERSION

    base: Dict[str, Any] = {
        "data_origin": "live",
        "scene": {"name": "凯里老街", "center": [107.9758, 26.5734], "study_radius_m": 2500},
        "caliber": {"scope_policy_version": SCOPE_POLICY_VERSION,
                    "coverage_caliber_version": COVERAGE_CALIBER_VERSION,
                    "travel_mode": "walking", "sample_profile": "standard"},
    }
    wanted = {"travel_mode": "walking", "sample_profile": "standard", "study_radius_m": 2500.0}
    assert reuse_policy(base, wanted) == (True, ""), (
        "前提不成立：这份基准载荷本来就不给复用，比不出'新增键没改变判定'")

    with_key = {**base, "caliber": dict(base["caliber"], evidence_pages_returned=9)}
    without_key = {**base,
                   "caliber": {k: v for k, v in base["caliber"].items()
                               if k != "evidence_pages_returned"}}
    assert reuse_policy(with_key, wanted) == reuse_policy(without_key, wanted) == (True, "")
