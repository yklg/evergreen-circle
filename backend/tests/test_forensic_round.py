"""按需扩容取证回合（`collect_triad_evidence`）—— 计划阶段 5 / v5.8。

这些用例**不打真实接口**：全部走鸭子类型 stub client，只验「打了几个词、留下什么证据、
盘长在哪儿、池子见底时怎么披露」，以及最后那条回路方向（并集把未覆盖格数往下推）。
"""
import asyncio

import app.living_circle  # noqa: F401  (口径 resolver 需先触发包初始化)
import pytest

from app.living_circle.anchors import anchor_key, LatticeAnchors
from app.living_circle.baidu_client import STOP_COMPLETE, STOP_PAGE_CAP, PlaceSearchOut
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.grid import judge_grid
from app.living_circle.poi_collector import (
    STOP_API_ERROR,
    STOP_NOT_RUN,
    CollectionEvidence,
    POIBudget,
    TermEvidence,
    collect_triad_evidence,
    triad_keywords,
)
from app.living_circle.scope import EvidenceRegion, SpatialScope

CENTER = (107.9758, 26.5734)
TRIADS = ("market", "pharmacy", "primary")


def _scope(half_m: float = 2500.0) -> SpatialScope:
    ring = [
        xy_to_lnglat(CENTER, -half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, -half_m),
        xy_to_lnglat(CENTER, half_m, half_m),
        xy_to_lnglat(CENTER, -half_m, half_m),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, half_m, zone)


class Stub:
    """假客户端：按 (词, 锚点) 记调用，返回可预测的点与停止原因。"""

    def __init__(self, total: int = 5, stop_reason: str = STOP_COMPLETE, fail: bool = False,
                 empty: bool = False) -> None:
        self.calls = 0
        self.seen = []                       # [(term, (lng, lat))]
        self.total = total
        self.stop_reason = stop_reason
        self.fail = fail
        self.empty = empty

    async def place_search(self, term, center, radius_m=None, max_pages=1, **kw):
        self.calls += 1
        self.seen.append((term, (round(float(center[0]), 6), round(float(center[1]), 6))))
        if self.fail:
            return None
        if self.empty:
            return PlaceSearchOut([], 0, 1, STOP_COMPLETE)
        lng, lat = center
        items = [{"name": f"{term}{i}", "lng": round(lng + i * 0.002, 6),
                  "lat": round(lat + 0.001, 6), "address": ""} for i in range(3)]
        return PlaceSearchOut(items, self.total, 1, self.stop_reason)


def _run(scope, anchors, pool, round_no=1):
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(stub, scope, anchors, pool, round_no=round_no))
    return stub, out


def test_round_uses_the_full_keyword_table_at_every_anchor():
    """每锚点全词（market 3 词、pharmacy/primary 各 1 词）⇒ 凯里那种「1 锚点 = 5 次调用」的形状。

    这是 R-P0-2 那条更正的落点：脚本 `keywords[0]` 的 1 词口径**不是**生产口径。
    """
    assert triad_keywords("market") == ("菜市场", "农贸市场", "生鲜市场")
    assert triad_keywords("pharmacy") == ("药店",) and triad_keywords("primary") == ("小学",)
    assert triad_keywords("不存在的类") == (), "解析点不得为未知类别凭空造词"

    scope = _scope()
    a_mkt = (107.9858, 26.5734)
    pool = POIBudget(total=10)
    stub, out = _run(scope, {"market": (a_mkt,)}, pool)
    assert stub.calls == 3, f"market 一个锚点应发 3 次（全词），实测 {stub.calls}"
    assert {t for t, _ in stub.seen} == set(triad_keywords("market"))
    assert len(out.evidence.per_term) == 3 and len(out.discs) == 3
    assert out.anchors_planned == {"market": 1, "pharmacy": 0, "primary": 0}
    assert out.anchors_used["market"] == 1 and out.anchors_not_run["market"] == 0


def test_pool_exhaustion_leaves_no_disc_and_is_counted_not_run():
    """池子拒掉的词：0 次调用 ⇒ 无行、**无盘**，只进 `starved_terms` 与 `anchors_not_run`。

    把「没打」写成一块半径 0 的盘，等于凭空宣布「这里查过且什么都没有」—— 那条错误方向
    在报告里与真·查全只隔一个字段，必须在这里就断掉。
    """
    scope = _scope()
    a1 = (107.9858, 26.5734)
    a2 = (107.9958, 26.5734)
    pool = POIBudget(total=4)                    # 只够 4 次：market 3 + pharmacy 1
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(
        stub, scope, {"market": (a1, a2), "pharmacy": (a1,)}, pool))
    assert stub.calls == 4 and pool.total - pool.remaining == stub.calls, (
        f"花掉的额度({pool.total - pool.remaining}) ≠ 真实调用数({stub.calls}) ⇒ 有人退了款或多扣了"
    )
    assert len(out.discs) == 4, "被拒的词不得产出证据盘"
    assert len(out.evidence.per_term) == 4 and len(out.evidence.starved_terms) == 3
    # `anchors_used` 只数「词表全部发出去」的锚点：market 的第二个锚点只打了 1/3 个词，
    # 保守方向必须算没打满 —— 把「只查了一个词」报成「这个点查干净了」就是误报盲区。
    assert out.anchors_planned == {"market": 2, "pharmacy": 1, "primary": 0}
    assert out.anchors_used == {"market": 1, "pharmacy": 0, "primary": 0}
    assert out.anchors_not_run == {"market": 1, "pharmacy": 1, "primary": 0}
    assert {c for c, _ in out.evidence.starved_terms} == {"market", "pharmacy"}, (
        f"饿死账要指到类与词，实测 {out.evidence.starved_terms}"
    )
    assert out.evidence.aborted is True, "池子见底且有词被饿死 ⇒ aborted 要说真话"


def test_failed_call_is_not_refunded_and_leaves_an_api_error_row():
    """回合里的调用失败与三条既有通道**同一语义**：不退款 + 记 `api_error` 行 + 不产盘。"""
    scope = _scope()
    pool = POIBudget(total=10)
    stub = Stub(fail=True)
    out = asyncio.run(collect_triad_evidence(
        stub, scope, {"pharmacy": ((107.9858, 26.5734),)}, pool))
    assert pool.total - pool.remaining == stub.calls == 1, "失败了也不许把钱退回账面"
    rows = out.evidence.per_term
    assert len(rows) == 1 and rows[0].stop_reason == STOP_API_ERROR
    assert rows[0].complete is False and rows[0].pages_fetched == 0
    assert out.discs == (), "调用失败产不出证据盘（无盘 = 这类在这里什么都没证明）"
    assert out.points["pharmacy"] == ()


def test_discs_are_anchored_at_the_anchor_not_the_analysis_center():
    """盘的心必须是**这一锚点**。写成分析中心就是把多锚点取证又塌回了一个圆（A1 那个靶子）。"""
    scope = _scope()
    a = (107.9858, 26.5734)
    _stub, out = _run(scope, {"pharmacy": (a,)}, POIBudget(total=5))
    disc = out.discs[0]
    assert (round(disc.anchor[0], 6), round(disc.anchor[1], 6)) == a
    assert disc.anchor != CENTER, "盘心漂回分析中心 ⇒ 锚点白打"
    assert disc.request_radius_m == pytest.approx(scope.required_radius_m("pharmacy"))
    # 与生产唯一转换器逐字段对齐（回合函数不许自带第二份盘构造）
    row = out.evidence.per_term[0]
    assert disc.exhausted_radius_m == row.as_disc(a).exhausted_radius_m
    assert disc.stop_reason == row.as_disc(a).stop_reason


def test_points_dedupe_across_anchors_but_evidence_does_not():
    """两个锚点抓回同一个设施 ⇒ 点位归并成一条，**证据盘仍是两块**。

    归并是给展示/评分数设施用的；判盲要的是「这一带查全到哪儿」。把两者合成一个动作，
    就会因归并而**偷偷缩小可判定面**。
    """
    scope = _scope()
    a1 = (107.9758, 26.5734)
    a2 = (107.97587, 26.57343)          # 与 a1 相距几米 ⇒ 同一批点会被几何去重吃掉
    pool = POIBudget(total=10)
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(stub, scope, {"pharmacy": (a1, a2)}, pool))
    assert stub.calls == 2 and len(out.discs) == 2, "证据按锚点计，两块盘就是两块"
    assert len(out.points["pharmacy"]) == 3, (
        f"两个几乎同心的锚点各回 3 条同源点 ⇒ 点位应归并到 3 条，实测 {len(out.points['pharmacy'])}"
    )


def test_round_returns_evidence_and_points_together_so_the_caller_can_union():
    """「A ∪ 本轮」的原料必须同批交付：只回证据会逼调用方去 `per_term` 反推点位。"""
    scope = _scope()
    _stub, out = _run(scope, {"market": ((107.9858, 26.5734),)}, POIBudget(total=10))
    assert set(out.points) == set(TRIADS), "三类都要有键（没打的类给空元组，不是缺键）"
    assert out.points["market"], "打了就该有点位"
    assert isinstance(out.evidence, CollectionEvidence)
    assert out.round_no == 1


def test_union_of_a_and_round_widens_the_judgeable_face_and_terminates():
    """回路方向钉死：把回合盘并进 region 后，未覆盖格数必须**往下走**（否则扩容无意义）。

    这一条同时是「回合终止」的机器判据原型：`covered` 之所以能宣布不用再扩，靠的就是
    并集铺满 `inside`；若并集不改变可判定面，判据会永远喊扩（复审 T-P0-1 点名的形状）。
    """
    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)
    lat = LatticeAnchors()
    req_pharmacy = scope.required_radius_m("pharmacy")

    # A 屏证据：中心一块浅盘（请求 1500m 被页上限截断），可判定半径只有 500m
    a_row = TermEvidence(category="pharmacy", term="药店", requested_radius_m=1500.0,
                         pages_fetched=1, returned=3, total=60, stop_reason=STOP_PAGE_CAP,
                         farthest_m=1500.0)
    region_a = EvidenceRegion([a_row.as_disc(CENTER)])
    before = lat.count_uncovered_cells(region_a, grid, "pharmacy", inside)
    assert before > 0, "前置不成立：A 屏就已铺满，本用例将空过"

    # 回合：往东 ~1200m 打一个锚点，这一词查到全 ⇒ 该盘的可判定面以**那个锚点**为心
    pool = POIBudget(total=5)
    anchor = (107.9868, 26.5734)
    stub = Stub(total=3, stop_reason=STOP_COMPLETE)
    out = asyncio.run(collect_triad_evidence(stub, scope, {"pharmacy": (anchor,)}, pool))
    region_ab = EvidenceRegion(tuple(region_a.discs) + out.discs)
    after = lat.count_uncovered_cells(region_ab, grid, "pharmacy", inside)
    assert after < before, f"并集没有把未覆盖格推下去（{before} → {after}）⇒ 扩容白烧"
    # 两个标量塌缩在回合之后**必须仍分名分值**：min 给规划、max 给标量视图
    assert region_ab.min_exhausted_m("pharmacy") == 1500.0, (
        "并集后保守塌缩该由那块浅盘给；被乐观盘抬走 ⇒ 下一轮间距会虚高（复审 T-P0-2 那条）"
    )
    assert region_ab.frontier_m("pharmacy") == pytest.approx(req_pharmacy)


def test_full_coverage_is_the_honest_stop_and_needs_no_more_calls():
    """一块够大的中心盘 ⇒ 判据直接说 `covered`，回合一次都不该发（按需的那条「不扩」腿）。"""
    scope = _scope()
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)
    big = EvidenceRegion([TermEvidence(
        category="pharmacy", term="药店", requested_radius_m=9000.0, pages_fetched=1,
        returned=3, total=3, stop_reason=STOP_COMPLETE, farthest_m=9000.0).as_disc(CENTER)])
    plan = LatticeAnchors().plan_expansion(big, grid, "pharmacy", inside=inside)
    assert plan.reason == "covered" and plan.cells_uncovered == 0
    pool = POIBudget(total=10)
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(stub, scope, {"pharmacy": plan.anchors}, pool))
    assert stub.calls == 0 and out.discs == () and pool.remaining == pool.total, (
        "判据说不用扩，回合就必须一次都不打（额度也没动）"
    )
    assert out.anchors_planned["pharmacy"] == 0


def test_page_capped_anchor_still_lands_a_disc_but_not_a_complete_one():
    """撞页上限的锚点要留下**盘**（数是真的，只是不完整），`complete` 必须是 False。

    反过来才是危险的：把截断当成查全 ⇒ 那一圈的「没有」是猜的。
    """
    scope = _scope()
    pool = POIBudget(total=5)
    stub = Stub(total=60, stop_reason=STOP_PAGE_CAP)
    out = asyncio.run(collect_triad_evidence(stub, scope, {"pharmacy": ((107.9858, 26.5734),)}, pool))
    disc = out.discs[0]
    assert disc.complete is False and disc.cap_hit is False, "页上限不是服务端封顶，别混归因"
    assert 0.0 < disc.exhausted_radius_m < disc.request_radius_m, (
        f"被截断时证据边界该是「最远实测点」：既不能等于请求半径 {disc.request_radius_m}"
        f"（那等于宣称查全），也不能是 0（那是根本没打），实测 {disc.exhausted_radius_m}"
    )
    assert out.evidence.capped_terms == () and out.evidence.truncated_terms, (
        "截断词要进 `truncated_terms`（与首轮的词汇同一处）"
    )


def test_attempted_anchors_are_the_only_source_for_next_round_already_tried():
    """第四轮复审 P1-4：`already_tried` 必须喂**实际打过的名单**，不是本轮规划到的全集。

    形状：规划 6 个候选、池子只够 2 个 ⇒ `anchors_attempted` 恰好 2 个、`not_run` 记 4 个。
    若接线时图省事喂 `plan.anchors`（含那 4 个没打的），下一轮会认为它们「已试」⇒
    扩容被没花出去的那半池子**静默掐死**。这条断的就是这两份名单不能混同。
    """
    scope = _scope()
    cand = tuple((107.9758 + 0.004 * i, 26.5734) for i in range(6))
    pool = POIBudget(total=2)
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(stub, scope, {"pharmacy": cand}, pool))
    attempted = out.anchors_attempted["pharmacy"]
    assert stub.calls == 2 and len(attempted) == 2, f"池子只够 2 次，实发 {stub.calls}"
    # 名单里是**归一后**（6 位小数）的坐标 —— 这正是喂回 `plan_expansion(already_tried=…)`
    # 能対上的原因：两边用同一个 `anchor_key` 判等。拿原始浮点去比会因末位差异误判。
    normalized = {anchor_key(c) for c in cand}
    assert len(normalized) == 6, "前置不成立：归一把 6 个不同点并成了一个"
    assert set(attempted) < normalized, (
        f"attempted 必须是规划集（归一后）的真子集，没打的那些不在里面：{attempted}"
    )
    assert out.anchors_planned["pharmacy"] == 6 and out.anchors_used["pharmacy"] == 2
    assert out.anchors_not_run["pharmacy"] == 4, (
        f"被池子掐掉的 4 个候选必须记 not_run：{out.anchors_not_run}"
    )
    assert len(out.discs) == 2, "只有真打出去的锚点才有盘"
    # 喂回 attempted（不是 p.anchors）⇒ 剩下 4 个候选仍排得出来
    region = EvidenceRegion(out.discs)
    grid = judge_grid(CENTER, scope, 200.0)
    nxt = LatticeAnchors().plan_expansion(region, grid, "pharmacy",
                                          already_tried=attempted, inside=grid.inside_mask(scope))
    assert set(nxt.anchors).isdisjoint(attempted)
    assert nxt.anchors or nxt.reason == "covered", (
        "候选没打完就宣布终止 ⇒ 上一轮被掐掉的点再也没人打（静默停止）"
    )


def test_bare_single_anchor_is_rejected_naming_the_category():
    """裸 `(lng, lat)` 会被当成「两个锚点、各只有一个坐标分量」。

    这条我自己就踩过（4 个用例同时栽）：默认路径下报的是 `'float' object is not subscriptable`，
    看不出是谁、在哪儿传错了 ⇒ 必须报错指名 `anchors['<类>']` 与「锚点序列」这两个词。
    判据精确到失败种类：不是「抛了个异常」，而是**这一类**错、且话里点到了类名。
    """
    scope = _scope()
    with pytest.raises(ValueError, match=r"anchors\['pharmacy'\].*锚点序列"):
        asyncio.run(collect_triad_evidence(
            Stub(), scope, {"pharmacy": (107.9858, 26.5734)}, POIBudget(total=10)))
    # 写成序列就正常（同一条数据，只差一层括号）
    _stub, out = _run(scope, {"pharmacy": ((107.9858, 26.5734),)}, POIBudget(total=10))
    assert out.anchors_planned["pharmacy"] == 1


def test_duplicate_anchor_in_one_round_is_queried_once_and_the_merge_is_disclosed():
    """同回合传重的锚点只发一次，且"并掉几个"是字段（B5 那层判据的披露面）。"""
    scope = _scope()
    dup = (107.9858, 26.5734)
    stub, out = _run(scope, {"pharmacy": (dup, dup, dup)}, POIBudget(total=10))
    assert stub.calls == 1, f"同一个锚点被发了 {stub.calls} 次 ⇒ 重复检索白烧预算"
    assert out.anchors_planned["pharmacy"] == 3 and out.anchors_merged["pharmacy"] == 2
    assert out.anchors_used["pharmacy"] == 1 and out.anchors_not_run["pharmacy"] == 0
    assert len(out.discs) == 1


def test_round_never_invents_anchors_or_budget():
    """`anchors` 空 ⇒ 一次都不打；函数不自己挑锚点、不猜预算（纪律 1）。"""
    scope = _scope()
    pool = POIBudget(total=10)
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(stub, scope, {}, pool))
    assert stub.calls == 0 and out.discs == () and out.points["market"] == ()
    assert pool.remaining == 10, "没打就不该扣钱"
    assert out.anchors_planned == {k: 0 for k in TRIADS}


def test_not_run_vocabulary_is_available_for_the_round_caller():
    """`STOP_NOT_RUN` 是「没打」的词汇位（与 `api_error`=打了没成 分名）。

    本用例只钉这个区分**存在**且不与 `api_error` 混用：回合里被池子拒的词不进 `per_term`
    （0 次调用无行），而 `not_run` 这个词留给调用方在落库时标锚点状态。
    """
    assert STOP_NOT_RUN != STOP_API_ERROR
    scope = _scope()
    pool = POIBudget(total=1)
    stub = Stub()
    out = asyncio.run(collect_triad_evidence(
        stub, scope, {"market": ((107.9858, 26.5734),), "pharmacy": (), "primary": ()}, pool))
    assert stub.calls == 1 and len(out.evidence.per_term) == 1
    assert all(t.stop_reason != STOP_NOT_RUN for t in out.evidence.per_term), (
        "没发出去的词不得伪装成一行举证 —— 它的正确去处是 starved/not_run 两个披露位"
    )
