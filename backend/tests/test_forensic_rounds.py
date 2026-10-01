"""取证-判盲同源改造的**回合层**测试（计划 v4 批次一 · T1 与 T3 混居）。

T1（真断言，今日即绿）
  B2  `test_u38b_admission_set_is_stable_across_runs`
      —— 同参两次跑出**同一准入词集**。锁的是「确定性」这件事本身，不锁具体是哪几个词；
      阶段 3 换成转置轮询后必须仍然绿（那时变的是内容，不是稳定性）。
  B2b `test_u38c_starvation_lands_on_category_tails`
      —— C 型**现状记录**：饿死落在「每类尾部」，预算再紧也不整类蒸发。
      原钉 `CATEGORY_RULES` 字典序前缀；阶段 3 的转置轮询按纪律把它打红后**重指**，未删。

T3（前置红测试：实现未落地即 skip，不污染全绿套件 —— 沿用 `test_quota.py:1-9` 先例）
  B5  同锚点同半径的重复检索被去重
  B1 / B3  **片 4 落地后已转真判据**（文件末「T3 · 外循环落地后的真判据」那一段）：
          它们要断的是外循环的行为，而循环的载荷在前几轮还不存在，当时写出来只能是恒真。

守卫按**单条**打 skipif 而非整文件 `importorskip`：整文件守卫会把 T1 那两条一起静默掉，
而 T1 恰恰是今天就该生效的锁。
"""
import importlib.util

import pytest

pc = pytest.importorskip("app.living_circle.poi_collector", reason="poi_collector.py 待 rev3 落地（§四B）")

from app.living_circle.baidu_client import PlaceSearchOut  # noqa: E402
from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES  # noqa: E402

CENTER = (107.9758, 26.5734)

_HAS_ROUND = hasattr(pc, "collect_triad_evidence")
_HAS_ANCHORS = importlib.util.find_spec("app.living_circle.anchors") is not None
needs_round = pytest.mark.skipif(
    not _HAS_ROUND, reason="取证回合 poi_collector.collect_triad_evidence 待计划阶段 5 落地"
)
needs_anchors = pytest.mark.skipif(
    not _HAS_ANCHORS, reason="锚点源 app.living_circle.anchors 待计划阶段 1 落地"
)


class _Stub:
    """一律返回空结果的百度桩，同时记录每次发出的 (query, center, radius)。"""

    def __init__(self):
        self.calls = 0
        self.queries = []

    async def place_search(self, query, center=None, radius_m=None, **kw):
        self.calls += 1
        self.queries.append((query, tuple(center) if center else None, radius_m))
        return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)


def _collect(total: int):
    import asyncio

    stub = _Stub()
    b = pc.POIBudget(total=total)
    collected = asyncio.run(
        pc.collect_poi(stub, center=CENTER, radius_m=2000, scope=object(), budget_snapshot=b)
    )
    return stub, b, collected


def _admitted(queries):
    return tuple(dict.fromkeys(q[0] for q in queries))


def _searched_terms():
    """采集器实际会发起的词序列（展示词表 + 三要素里另检的那两个）。

    镜像采集器的枚举口径（A 阶段的 `a_plan` 转置循环 + 其后的三要素循环）：`market` 复用类目
    结果不另发一次，其余两个三要素各取 `keywords[0]`。准入/饿死的判据必须建立在这份**完整**
    词表上，否则「三要素被饿死」会被当成「词表之外的噪声」漏掉。
    """
    terms = [kw for defn in CATEGORY_RULES.values() for kw in defn["keywords"]]
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_") or key == "market":
            continue
        kws = ref["keywords"] if isinstance(ref, dict) else [ref]
        if kws and kws[0] not in terms:
            terms.append(kws[0])
    return terms


# ── T1 · 今日即绿 ────────────────────────────────────────────────

def test_u38b_admission_set_is_stable_across_runs():
    """B2 · 同参两次跑出同一准入词集（「检索随机性太强」的机器反证）。"""
    s1, b1, c1 = _collect(total=2)
    s2, b2, c2 = _collect(total=2)

    assert _admitted(s1.queries) == _admitted(s2.queries), (
        f"同参两次跑出发出不同的词：{s1.queries} vs {s2.queries} ⇒ 点位集合不可复现"
    )
    assert c1.evidence.starved_terms == c2.evidence.starved_terms, (
        "被饿死的词集两次不一致 ⇒ 报告举证 `evidence_starved_terms` 不可复算"
    )
    assert b1.remaining == b2.remaining == 0
    # 准入 + 饿死 = 全词表（含另检的两个三要素词）：一条都不许凭空蒸发（P0-2 可见性）
    starved = {t for _cat, t in c1.evidence.starved_terms}
    assert set(_admitted(s1.queries)) | starved == set(_searched_terms()), (
        "有词既没被检索、也没被登记为饿死 ⇒ 该类点位会静默消失"
    )


def test_u38c_starvation_lands_on_category_tails():
    """B2b · **现状记录（阶段 3 重指）**：饿死落在「每类尾部」，预算再紧也不整类蒸发。

    本用例原先钉的是 `CATEGORY_RULES` 字典序前缀（旧策略）。阶段 3 的转置轮询把它打红，
    按纪律**重指**到新落点上而非删掉。留下的理由和删掉的代价是同一条：准入落点若哪天退回
    顺序依赖，只有这条能发现 —— u38b 只钉「同参同集」，而**任何稳定的错误顺序它都放行**。

    判据一律取自 :mod:`category_rule` 本身，不抄采集器的那条 `for idx: for cat:` 循环：
    把生产逻辑誊进测试再断言它，等于恒真（F1 那一类）。
    """
    cats = sorted(CATEGORY_RULES)
    total = len(cats)                      # 恰好够「每类一个词」——旧策略在这点上最难看
    stub, _b, collected = _collect(total=total)
    admitted = _admitted(stub.queries)
    starved = {t for _cat, t in collected.evidence.starved_terms}

    # ① 本轮策略的字面落点：转置 = 先摊「每类首词」，类间按 `sorted()` 而非定义序。
    assert admitted == tuple(CATEGORY_RULES[c]["keywords"][0] for c in cats), (
        f"准入词集不再是「每类首词」：{admitted}"
    )
    # ② 承重的那条。旧策略在 total=8 时只会摊开字典序最前的 3 类，剩下 5 类**一条证据都不剩**
    #    ⇒ 那些类的点位凭空消失。转置的意义全在这里：它不要求顺序永远是「首词优先」，
    #    只要求预算再紧也不牺牲整类。故①被未来的改动改掉时，②仍是该守的那道闸。
    touched = {c for c, defn in CATEGORY_RULES.items() if set(defn["keywords"]) & set(admitted)}
    assert touched == set(CATEGORY_RULES), (
        f"{total} 单位预算下有类目完全没被检索：{tuple(sorted(set(CATEGORY_RULES) - touched))}"
    )
    # ③ 可见性账目不凭空蒸发。只断并集覆盖、**不断不相交**：`starved_terms` 是
    #    (类别, 词) 对，三要素里的 `primary/小学` 会在 A 阶段已检过后仍按「该类别未取得证据」
    #    登记（逐类检索半径可以不同）⇒ 词级投影本就允许同词两态。
    assert set(admitted) | starved == set(_searched_terms()), (
        "有词既没被检索、也没被登记为饿死 ⇒ 该类点位会静默消失"
    )


# ── T3 · 外循环落地后的真判据（计划 v7.0 片 4）──────────────────
#
# B1（终止阶梯顺序不可反）与 B3（回合数不定仍正确终止）**先前标的是"待生成"**，理由写在
# 这里以备有人再问：那时外循环只有一个名字（`compute_stream`）没有载荷，在测试里手写一个
# while 再断言它 = 把判据写在测试自己身上（F1 那一类恒真）。片 4 把循环接进 `live_forensic_steps`
# 并交出 `ForensicRoundRecord` 之后，下面每一条断的都是**生产跑出来的那份 dict**，
# 且每条都指着一件具体会坏的事（顺序反了、烧超额、明细与结论分家、展示面被偷偷喂胖）。

import asyncio  # noqa: E402
from typing import Dict  # noqa: E402

from app.living_circle import data_source as ds  # noqa: E402
from app.living_circle import quota as quota_mod  # noqa: E402
from app.living_circle.baidu_client import STOP_COMPLETE, STOP_PAGE_CAP  # noqa: E402
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat  # noqa: E402
from app.living_circle.isochrone import IsochroneEngine  # noqa: E402


class _LoopStub:
    """驱动整条取证编排的假百度。

    `hub_truncated` 说的是**真实形状**，不是测试花招：第 0 步两城实测里，稠密类在分析中心
    一次就撞单页上限（凯里药店 3 个锚点 `total` 60/62/68 各只回 20），而补算锚点周围稀疏、
    一页查得完。所以"中心那次截断、别处查全"是这条回路最常遇到的输入，也是唯一能把
    「判全」与「轮次封顶」两条终点**放到同一次跑动里比先后**的输入。
    """

    def __init__(self, *, hub_truncated: bool, arm_m: float = 1400.0, per_call: int = 3,
                 hub_arm_m: float = 2200.0) -> None:
        self.hub_truncated = hub_truncated
        self.arm_m = arm_m
        self.per_call = per_call
        self.hub_arm_m = hub_arm_m
        self.place_calls = 0
        self.matrix_calls = 0
        self.guard = None                    # 没有闸 ⇒ 残缺与否只由取证池决定
        # 每次检索按"发起它的是哪一段"记账：`first` = 首轮 `collect_poi`，`round` = 取证回合。
        # 这个桶由下面那个 spy 翻（它只**观察**、不改行为）。有了它，"回合不许重发中心"
        # 才是一条落在具体坐标上的判据，而不是"总调用数看起来少了点"。
        self.bucket = "first"
        self.seen = []

    async def measure_matrix(self, mode, pts, center):
        self.matrix_calls += 1
        return [haversine_m(tuple(center), p) / 80.0 * 1.3 for p in pts]

    async def place_search(self, term, center, radius_m=None, max_pages=1, **kw):
        self.place_calls += 1
        lng, lat = float(center[0]), float(center[1])
        at_hub = (round(lng, 6), round(lat, 6)) == (round(CENTER[0], 6), round(CENTER[1], 6))
        self.seen.append((self.bucket, term, (round(lng, 6), round(lat, 6))))
        truncated = at_hub and self.hub_truncated
        arm = self.hub_arm_m if not truncated else self.arm_m
        items = []
        for i in range(self.per_call):
            p = xy_to_lnglat((lng, lat), arm * (0.3 + 0.35 * i), 0.0)
            items.append({"name": f"{term}{i}", "lng": round(p[0], 6), "lat": round(p[1], 6),
                          "address": ""})
        return PlaceSearchOut(items, 200, 1, STOP_PAGE_CAP if truncated else STOP_COMPLETE)


def _drive(client, *, rounds=1, pool=None, monkeypatch=None):
    """跑一次真实编排 ⇒ (步序, 末份报告, 那次跑动的取证账目)。"""
    if monkeypatch is not None:
        monkeypatch.setattr(ds, "MAX_FORENSIC_ROUNDS", rounds)
        if pool is not None:
            monkeypatch.setattr(quota_mod, "forensic_budget", lambda: pool)
    engine = IsochroneEngine()
    check = ds.CheckParams(scene_name="回合台架", city="凯里", address="测试", center=CENTER,
                           study_radius_m=2500.0, sample_profile="standard",
                           travel_mode="walking")

    async def _run():
        return [s async for s in ds.live_forensic_steps(client, engine, check)]

    steps = asyncio.run(_run())
    report = next(s.report for s in steps if s.kind == ds.STEP_REPORT)
    return steps, report


def _count_judge_once(monkeypatch) -> Dict[str, int]:
    """数**一次真实跑动**里 `judge_once` 被执行了几次（G-10 数的是代码里的调用点）。"""
    import app.living_circle.blindspot as bs

    counter = {"n": 0}
    real = bs.judge_once

    def wrapper(*a, **kw):
        counter["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(ds, "judge_once", wrapper)
    return counter


def test_b3_loop_terminates_within_forensic_pool_and_judges_once_per_pass(monkeypatch):
    """B3 · 回合数不由我定，而由"还要不要打"定 ⇒ **有界**才是判据。

    三条各自拦一种坏形状：
    ① `pool_used <= forensic_budget()` —— 拦"池子内循环还花池子外的钱"（P0-5 那一族的复活）；
    ② `rounds <= max_rounds` —— 拦空转（第六轮复审 P0-2b：全类停手/池子饿死都不 break 就是它）；
    ③ `judge_once 次数 == caliber.forensic.judging_passes` —— 拦"账目上的趟数与真判的趟数
      分家"。这条**故意不写死 1 或 2**：它断的是两个来源必须相等，所以回合数怎么改它都成立，
      而循环里少判/多判一次当场红。
    """
    steps, report = _drive(_LoopStub(hub_truncated=True))
    block = report["caliber"]["forensic"]
    # 计数器装在**跑动之前** ⇒ 它数的是这一次真执行了几遍逐格判定（G-10 数的是调用点，
    # 只有这条能抓住"编排里顺手多判了一遍"）。
    judged = _count_judge_once(monkeypatch)
    steps2, report2 = _drive(_LoopStub(hub_truncated=True))
    block2 = report2["caliber"]["forensic"]

    assert block["pool_used"] <= quota_mod.forensic_budget(), (
        f"取证回合花了 {block['pool_used']} 次，而额度源只给 "
        f"{quota_mod.forensic_budget()} 次 ⇒ 池子只是装饰")
    assert block["rounds"] <= block["max_rounds"]
    assert block["rounds"] >= 1, "这份输入本该打出一个回合（中心那次被页截断）"
    assert [s.kind for s in steps].count(ds.STEP_ROUND) == block["rounds"], (
        "回合事件条数与账目里的回合数不是一份数")
    assert block2["judging_passes"] == block2["rounds"] + 1
    assert judged["n"] == block2["judging_passes"], (
        f"这一次跑动实际判了 {judged['n']} 遍，账目却写 {block2['judging_passes']} 趟 "
        "⇒ 上屏的趟数不是这次跑出来的趟数")


def test_b1_hard_end_point_wins_when_both_conditions_hold_at_once(monkeypatch):
    """B1 · 阶梯顺序：`undecided==0` 必须**赢过**轮次封顶 —— 造得出"两条同时成立"的那一趟。

    为什么用 `MAX_FORENSIC_ROUNDS = 0` 来造，而不是"打满一轮之后再判全"：后者要求一次回合
    把 32 个未决格也判干净，而 market 一类有 **3 个词** ⇒ 份额公式下它一轮根本打不完
    （实测：一轮后未决 124→32，`market` 仍 reason=expand）。硬凑那个输入就会变成
    "调桩调到断言成立"，那是假绿的另一张脸。
    `MAX=0` 时首轮那一趟**同时**满足「pass_no 已到上限」和（查全的输入下）「未决格归零」
    ⇒ 两条 break 真的在这一趟里比先后。对照半边（同一道封顶、换成会被页截断的输入）拦的是
    另一个方向：只留第一条，一个"无条件报 undecided_zero"的实现也能混过去 —— 它同样让第一条
    成立。两条各钉一个反方向，缺一条就是半边闸。
    """
    complete = _LoopStub(hub_truncated=False)     # 三类一次查全 ⇒ 首轮未决格归零
    steps, report = _drive(complete, rounds=0, monkeypatch=monkeypatch)
    block = report["caliber"]["forensic"]
    assert block["stop_reason"] == ds.STOP_UNDECIDED_ZERO, (
        f"未决格已归零、轮次上限也到了，收手原因却是 {block['stop_reason']!r} "
        "⇒ 两条 break 的次序反了（把好消息报成'我们自己不收手'）")
    assert block["rounds"] == 0
    assert ds.STEP_ROUND not in [s.kind for s in steps], "判全了还派回合 = 白烧"

    truncated = _LoopStub(hub_truncated=True)     # 同一道封顶，未决格 > 0 ⇒ 该报封顶
    _steps, report2 = _drive(truncated, rounds=0, monkeypatch=monkeypatch)
    block2 = report2["caliber"]["forensic"]
    assert block2["stop_reason"] == ds.STOP_ROUNDS_EXHAUSTED, block2["stop_reason"]
    assert block2["per_category"] and any(
        v["cells_uncovered"] for v in block2["per_category"].values()), (
        "对照组必须真的还有未覆盖格，否则上面那条 `rounds_exhausted` 是白拿的")


def test_judging_reads_the_union_while_the_display_stays_first_round(monkeypatch):
    """片 4 那面"两面性"的判据：并集进判盲，**不**进 8 类计数与评分。

    对照组 = 同一份桩、把 `MAX_FORENSIC_ROUNDS` 打成 0（一个回合都派不出去）。
    于是两次跑动只差"有没有补算"，而这条断的是：
    ① 补算确实发生了（`rounds == 1`、`points_added_judging_only > 0`）；
    ② 展示面**一个字没动**（`poi` 整块逐位相同）—— 这条是 v5.1 用户拍板"批次二才动展示面"
      的机器闸，谁把回合点位顺手并进 `to_stats`，这里当场红；
    ③ 判盲侧确实换了输入（盲区条数/分账与对照组不同）。只断"不等"就够了吗？不够 ——
      所以②先钉"展示面必须等"，③再钉"判定面必须不等"，两条方向相反，缺一条都放行。
    """
    with_pool = _LoopStub(hub_truncated=True)
    _steps1, r1 = _drive(with_pool)
    _steps0, r0 = _drive(_LoopStub(hub_truncated=True), rounds=0, monkeypatch=monkeypatch)

    assert r1["caliber"]["forensic"]["rounds"] == 1
    assert r1["caliber"]["forensic"]["points_added_judging_only"] > 0
    assert r0["caliber"]["forensic"]["rounds"] == 0
    assert r1["poi"] == r0["poi"], "回合点位漏进了 8 类展示口径 —— 那是批次二的破坏性改动"
    assert (r1["caliber"]["cells_blind"], len(r1["blindspots"])) != (
        r0["caliber"]["cells_blind"], len(r0["blindspots"])), (
        "补算回来的点位与圆盘没改变任何一格结论 ⇒ 并集根本没进判定路径"
        "（`judge_points`/`region` 被就地丢弃了）")


def test_quota_short_forensic_pool_discloses_not_run_and_lands_partial(monkeypatch):
    """池子只给 4 次 ⇒ `not_run` 是**字段**不是注释，且 partial 归因到「取证额度不足」。

    拦的三件事各有其名：`anchors_not_run>0`（计划要打却没打满词表）、
    `starved_terms>0`（一次请求都没发出的词）、`partial.detail`（读者看到的那句话）。
    先前 P0-4 的复验就是"池子见底在 partial 上永远读不出来"，因为 `POIBudget` 耗尽
    **不是** guard 中止 —— 这条就是它的正向对照。
    """
    steps, report = _drive(_LoopStub(hub_truncated=True), pool=4, monkeypatch=monkeypatch)
    block = report["caliber"]["forensic"]

    assert block["pool_total"] == 4
    assert block["calls"] <= 4
    assert block["anchors_not_run"] > 0, block
    assert report.get("partial"), "额度不足却没声明残缺 = 把没查的格子说成不用查"
    assert report["partial"]["detail"] == "forensic_pool_short"
    assert report["data_origin"] == "live", "取证池耗尽**不得**把整份报告打回离线（D1①）"


def test_round_accounting_identities_hold_for_every_dispatch(monkeypatch):
    """逐回合账目的两条恒等式（P0-3「截断不得静默」的算术面）。

    `planned == sent + dropped`（规划到的 = 发出去的 + 被份额砍掉的）与
    `sent == used + merged + not_run`（发出去的 = 查完的 + 同回合重掉的 + 半路饿死的）。
    顶层那几个 `anchors_*` 只累加**派发过**的趟次 —— 未派发那趟只是"又量了一次需求"，
    把它并进总数就会凭空多出十几个"打算打却从没打算打"的锚点。
    """
    for pool in (34, 8):
        _steps, report = _drive(_LoopStub(hub_truncated=True), pool=pool, monkeypatch=monkeypatch)
        block = report["caliber"]["forensic"]
        rows = [r for r in block["rounds_detail"] if r["dispatched"]]
        assert rows, f"池子 {pool} 时本该至少派一个回合"
        for row in rows:
            assert row["anchors_planned"] == row["anchors_sent"] + row["anchors_dropped"], row
            assert row["anchors_sent"] == (row["anchors_used"] + row["anchors_merged"]
                                           + row["anchors_not_run"]), row
        assert block["anchors_planned"] == sum(r["anchors_planned"] for r in rows)
        assert block["calls"] == sum(r["calls"] for r in rows)


def test_round_never_requeries_the_analysis_center(monkeypatch):
    """首轮那次检索就打在中心格上 ⇒ 中心格恒为"已试"，回合一个词都不该重发。

    判据落在**具体坐标 + 具体发起段**上（`client.seen` 里桶为 `round` 的那批），不是
    "调用总数看起来少了点"：少种一次 `already_tried`，market 一类就会在中心重发 3 个词，
    而总数判据在别的参数下也可能碰巧对上。`anchors.py` 的相位事实
    （`i0 = mid % m` ⇒ 中心格恒在候选里）是这条之所以会坏的原因，也是它之所以能当闸的原因。

    那个 spy 只翻一个桶标记、原样把调用交回生产实现 —— 它不改行为，只让"谁发的"可读。
    """
    client = _LoopStub(hub_truncated=True)
    real = ds.collect_triad_evidence

    async def spy(*a, **kw):
        client.bucket = "round"
        try:
            return await real(*a, **kw)
        finally:
            client.bucket = "first"

    monkeypatch.setattr(ds, "collect_triad_evidence", spy)
    _steps, report = _drive(client)

    hub = (round(CENTER[0], 6), round(CENTER[1], 6))
    assert report["caliber"]["forensic"]["rounds"] == 1, "前置：这次跑动真派出了一个回合"
    rehit = [row for row in client.seen if row[0] == "round" and row[2] == hub]
    assert not rehit, f"回合在分析中心重发了 {len(rehit)} 次（首轮已证过这块）：{rehit[:4]}"

@needs_round
@needs_anchors
def test_same_anchor_same_radius_is_not_queried_twice():
    """B5 · 已证域必须被记住：同锚点同词不得重发（否则回合数直接翻倍烧预算）。

    判据的接缝按计划 v5.8 分成两处（本用例原先把两层都假设住在回合函数里）：
      ① **同一回合内**传重了 ⇒ 只发一次，且"重了几个"由 `anchors_merged` 如实披露；
      ② **跨回合**不重发归 `plan_expansion(already_tried=…)` —— 让采集函数再收一份 region
         去判「哪些点已证」，等于让它第二次决定「打哪儿」，那正是本仓要消灭的第二实现。
         所以第二层的判据是「把上一轮打过的锚点喂回规划侧 ⇒ 本轮排不出新锚点 ⇒ 回合实发 0 次」，
         这条把 `plan_expansion` 与 `collect_triad_evidence` 串起来跑，不是各测各的。

    判据精确到失败种类：断的是「同一个 (锚点, 词) 出现两次」，不是「调用总数 == 锚点数」——
    market 一类有 **3 个词**（R-P0-2 那条更正），旧写法那条等式本身就数错了。
    """
    import asyncio

    from app.living_circle.anchors import (
        LatticeAnchors, PLAN_COVERED, PLAN_EXPAND, PLAN_NO_NEW_ANCHOR,
    )
    from app.living_circle.caliber import get_caliber
    from app.living_circle.geo_utils import xy_to_lnglat
    from app.living_circle.grid import judge_grid
    from app.living_circle.scope import EvidenceDisc, EvidenceRegion, SpatialScope

    half = 2500.0
    ring = [xy_to_lnglat(CENTER, -half, -half), xy_to_lnglat(CENTER, half, -half),
            xy_to_lnglat(CENTER, half, half), xy_to_lnglat(CENTER, -half, half)]
    zone = {"minutes": 20.0,
            "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, half, zone)

    dup = (107.9758, 26.5734)
    other = (107.98, 26.57)
    anchors = {"market": (dup, dup, other), "pharmacy": (dup, dup), "primary": (other,)}

    # ── ① 同回合去重 ────────────────────────────────────────────
    stub = _Stub()
    r1 = asyncio.run(pc.collect_triad_evidence(
        stub, scope, anchors, pc.POIBudget(total=30), round_no=1))
    pairs = [(c, q) for q, c, _r in stub.queries]
    assert len(pairs) == len(set(pairs)), (
        f"同一个 (锚点, 词) 被发了两次：{sorted({p for p in pairs if pairs.count(p) > 1})}"
    )
    want = (2 * len(pc.triad_keywords("market"))          # market 去重后 2 个锚点 × 3 词
            + 1 * len(pc.triad_keywords("pharmacy"))
            + 1 * len(pc.triad_keywords("primary")))
    assert stub.calls == want, f"去重后该发 {want} 次，实测 {stub.calls}"
    assert r1.anchors_merged == {"market": 1, "pharmacy": 1, "primary": 0}, (
        f"并掉的重复锚点必须是字段不是注释：{r1.anchors_merged}"
    )
    assert r1.anchors_planned == {"market": 3, "pharmacy": 2, "primary": 1}
    assert r1.anchors_used == {"market": 2, "pharmacy": 1, "primary": 1}
    assert r1.anchors_not_run == {"market": 0, "pharmacy": 0, "primary": 0}
    # `anchors_not_run` 是由 planned/used/merged 派生的，拿它去断恒等式等于断自己的定义
    # （第四轮复审 P1-6）⇒ 这里只断一条真有失败可能的不等式：已用 + 已并 不得超过计划数。
    for cat, n in r1.anchors_planned.items():
        assert r1.anchors_used[cat] + r1.anchors_merged[cat] <= n, (
            f"{cat}：used({r1.anchors_used[cat]}) + merged({r1.anchors_merged[cat]}) 超过了 "
            f"planned({n}) ⇒ 分账在重复计数"
        )

    # ── ② 跨回合：把第 1 回合**实际打过的锚点名单**喂回规划侧 ⇒ 第 2 轮不得重发 ──────
    # 名单来自 `ForensicRound.anchors_attempted`（P1-4 补的唯一出口）。注意不能喂
    # `p1.anchors`：那是「本轮规划到的」全集，含被池子掐掉的那些，喂它等于把没打的点
    # 记成「已试」⇒ 扩容会静默停止。
    grid = judge_grid(CENTER, scope, 200.0)
    inside = grid.inside_mask(scope)
    lat = LatticeAnchors()

    class _FarStub:
        """每个锚点只证到 ~1500m（页上限截断）⇒ 可判定半径 500m，一轮铺不满。

        必须用这种"浅盘"桩：`_Stub` 回的是查全（可判定半径 3.5km），一轮下去 `cells_uncovered`
        直接归零 ⇒ 第 2 轮会以 `covered` 收场，本用例就成了「测不出重发」的空过形状。
        """

        def __init__(self):
            self.calls = 0
            self.queries = []

        async def place_search(self, query, center=None, radius_m=None, **kw):
            self.calls += 1
            self.queries.append((query, tuple(center), radius_m))
            lng, lat_ = center
            item = {"name": query, "lng": round(lng + 0.0151, 6), "lat": lat_, "address": ""}
            return PlaceSearchOut([item], 60, 1, pc.STOP_PAGE_CAP)

    shallow = EvidenceRegion([EvidenceDisc(
        category="pharmacy", anchor=CENTER, request_radius_m=1500.0,
        exhausted_radius_m=1500.0, stop_reason=pc.STOP_PAGE_CAP)])
    assert lat.count_uncovered_cells(shallow, grid, "pharmacy", inside) > 0, (
        "前置不成立：浅盘已铺满 ⇒ 本用例的 ② 会空过"
    )
    p1 = lat.plan_expansion(shallow, grid, "pharmacy", inside=inside)
    assert p1.anchors, "前置不成立：第 1 轮排不出锚点"
    # 候选必须被可达区裁过：裸格阵（13×13=169）大于裁剪后的数量 ⇒ 圆外格不许当锚点（P0-2）
    assert len(p1.anchors) < 13 * 13, (
        f"候选没有按可达区裁剪（{len(p1.anchors)} 个 = 裸格阵），圆外的格被当成锚点"
    )

    pool1 = 30
    stub2 = _FarStub()
    round1 = asyncio.run(pc.collect_triad_evidence(
        stub2, scope, {"pharmacy": p1.anchors}, pc.POIBudget(total=pool1), round_no=1))
    attempted_r1 = tuple(round1.anchors_attempted["pharmacy"])
    assert len(attempted_r1) == round1.anchors_used["pharmacy"] == pool1, (
        f"池子给多少就该打多少个锚点，实测 attempted={len(attempted_r1)} "
        f"used={round1.anchors_used['pharmacy']}"
    )
    assert round1.anchors_not_run["pharmacy"] == len(p1.anchors) - pool1, (
        "池子掐掉的候选必须记成 not_run（没打过），不许混进已证域"
    )

    merged_region = EvidenceRegion(tuple(shallow.discs) + round1.discs)
    p2 = lat.plan_expansion(merged_region, grid, "pharmacy", inside=inside,
                             already_tried=attempted_r1)
    assert set(p2.anchors).isdisjoint(attempted_r1), (
        "第 2 轮排出了第 1 轮已打过的锚点 ⇒ 已证域没被记住"
    )
    assert p2.anchors and p2.reason == PLAN_EXPAND, (
        f"第 1 轮只跑了 {pool1}/{len(p1.anchors)} 个候选，第 2 轮该继续而不是收手："
        f"reason={p2.reason} 未覆盖格={p2.cells_uncovered}"
    )
    stub3 = _FarStub()
    round2 = asyncio.run(pc.collect_triad_evidence(
        stub3, scope, {"pharmacy": p2.anchors}, pc.POIBudget(total=20), round_no=2))
    pairs_r1 = {(c, q) for q, c, _r in stub2.queries}
    pairs_r2 = [(c, q) for q, c, _r in stub3.queries]
    assert len(pairs_r2) == len(set(pairs_r2)), "第 2 回合内部出现重发"
    assert not (set(pairs_r2) & pairs_r1), (
        f"第 2 回合重发了第 1 回合的 (锚点, 词)：{sorted(set(pairs_r2) & pairs_r1)[:3]}"
    )
    assert len(round2.anchors_attempted["pharmacy"]) == 20
    # 再走一回合：候选还没打完 ⇒ 仍该是 `expand`（这格实测 31 个新候选、未覆盖格 206），
    # 把剩下的打完之后才轮到 `no_new_anchor`
    p3 = lat.plan_expansion(EvidenceRegion(tuple(merged_region.discs) + round2.discs), grid,
                            "pharmacy", inside=inside,
                            already_tried=attempted_r1
                            + tuple(round2.anchors_attempted["pharmacy"]))
    assert p3.reason == PLAN_EXPAND and p3.anchors, (
        f"候选未耗尽就收手了：reason={p3.reason} 未覆盖格={p3.cells_uncovered}"
    )
    stub4 = _FarStub()
    round3 = asyncio.run(pc.collect_triad_evidence(
        stub4, scope, {"pharmacy": p3.anchors},
        pc.POIBudget(total=len(p3.anchors)), round_no=3))
    all_tried = (attempted_r1 + tuple(round2.anchors_attempted["pharmacy"])
                 + tuple(round3.anchors_attempted["pharmacy"]))
    assert len(all_tried) == len(set(all_tried)) == len(p1.anchors), (
        f"三回合应当把 {len(p1.anchors)} 个候选各打一次而不重复：实得 {len(all_tried)} 个、"
        f"去重后 {len(set(all_tried))} 个"
    )
    p_end = lat.plan_expansion(
        EvidenceRegion(tuple(merged_region.discs) + round2.discs + round3.discs),
        grid, "pharmacy", inside=inside, already_tried=all_tried)
    # 候选打满之后实测 `cells_uncovered == 0` ⇒ 由 `covered` 收场。两条诚实出路的**次序是刻意的**
    # （覆盖先判）：`no_new_anchor` 只在「候选被喂满而覆盖仍未铺到」时才出现，而这里恰好
    # Witness 了格阵的覆盖下界 —— stride 由 `min_exhausted_m` 导出 ⇒ 候选全打完必然铺满 `inside`。
    assert p_end.reason == PLAN_COVERED, (
        f"候选打满且已铺满却报了别的出路：{p_end.reason}（未覆盖格={p_end.cells_uncovered}）"
    )
    assert p_end.cells_uncovered == 0, "`covered` 却带着未覆盖格 ⇒ 那个数是假的"
    assert p_end.anchors == ()
    stub5 = _Stub()
    asyncio.run(pc.collect_triad_evidence(
        stub5, scope, {"pharmacy": p_end.anchors}, pc.POIBudget(total=30), round_no=4))
    assert stub5.calls == 0, f"已铺满却仍发了 {stub5.calls} 次 ⇒ 回合不收敛"
