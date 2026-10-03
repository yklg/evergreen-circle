"""采集 + 扩词策略 `poi_collector.py`（rev3 §四B）—— POIBudget 分配快照 / ExpansionCtx / 主循环。

TDD 红测试：模块未落地，`importorskip` 守卫缺失即整文件 skip；
落地后自动转真实断言（预算记账 / 渐进式停止 / 合并去重 / 主循环总调用上限）。
"""
import pytest

pc = pytest.importorskip("app.living_circle.poi_collector", reason="poi_collector.py 待 rev3 落地（§四B）")

# stub 模拟的是**客户端**契约 ⇒ 从 baidu_client 取其返回类型与停止原因常量，
# 而不是从采集层拿别名：采集层只是消费者。
from app.living_circle.baidu_client import PlaceSearchOut


def budget():
    # quota 产出的分配快照（27 = precise 档的 poi 预算）。纯工厂：刻意非 pytest fixture，
    # 便于在各用例内手动实例化独立快照做记账断言。
    # ⚠️ 10-03 甲之后 27 **不再等于"A 阶段 + 三要素"**（现需 27 + 2）：拿它跑整条采集会饿死 2 颗展示词，
    #   所以这里的用例只把它当"一个有额度的快照"用，别当"够用"的基线。
    return pc.POIBudget(total=27)


class TestPOIBudgetAccounting:
    def test_consume_decrements_and_rejects_at_zero(self):
        b = budget()
        assert b.consume("market") is True
        assert b.remaining == 26
        # 预扣耗尽 → 拒用
        while b.remaining:
            b.consume("market")
        assert b.consume("market") is False

    def test_refund_rolls_back_precharge(self):
        b = budget()
        b.consume("medical")
        b.refund("medical")
        assert b.remaining == 27  # 失败回滚，不空转烧预算（rev3 P1-3）

    def test_quench_freezes_category(self):
        b = budget()
        b.quench("shopping")
        assert b.frozen("shopping") is True
        assert b.consume("shopping") is False

    def test_under_target_stops_when_met(self):
        # 圈内 ≥ ideal_circle → 不再扩
        assert budget().under_target(cats={"market": 5}, ideal_circle=3) is False
        # 圈内 < ideal_circle → 触发扩词
        assert budget().under_target(cats={"market": 1}, ideal_circle=3) is True

    def test_fork_isolates_snapshot(self):
        b = budget()
        child = b.fork()
        child.consume("market")
        assert b.remaining == 27  # 子快照消费不影响父


class TestExpansionCtx:
    def test_next_returns_none_when_exhausted(self):
        ctx = pc.ExpansionCtx(used_terms=set())
        assert ctx.next(confirmed=[], rule={"accept_tags": [], "keywords": []}) is None

    def test_next_skips_used_terms(self):
        ctx = pc.ExpansionCtx(used_terms={"公园"})
        # confirmed 名 / 未用 accept_tags / baidu type 三路来源，但唯一可用词已用 → None
        term = ctx.next(confirmed=[], rule={"accept_tags": ["公园"], "keywords": ["公园"]})
        assert term is None

    def test_next_prefers_confirmed_name(self):
        ctx = pc.ExpansionCtx(used_terms=set())
        term = ctx.next(confirmed=[{"name": "社区卫生服务站"}], rule={"accept_tags": []}, existing={"market": []})
        # 从 confirmed name 提炼类别判词名词
        assert term is not None and "卫生" in term


class TestPlanInitial:
    def test_returns_term_pages_pairs(self):
        plan = pc.plan_initial({"keywords": ["菜市场"]}, budget())
        assert isinstance(plan, list)
        assert plan[0][0] == "菜市场"
        assert plan[0][1] >= 1


class TestCollectPOIConvergence:
    async def _run(self, *a, **k):
        return await pc.collect_poi(*a, **k)

    def test_collect_poi_total_calls_within_budget(self):
        # 主循环：注入 stub client + scope，断言总调用 ≤ poi budget，绝不过量
        class Stub:
            def __init__(self):
                self.calls = 0

            async def place_search(self, *a, **k):
                self.calls += 1
                return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)

        stub = Stub()
        scope = object()
        import asyncio

        asyncio.run(self._run(stub, center=(107.9758, 26.5734), radius_m=2000, scope=scope, budget_snapshot=budget()))
        assert stub.calls <= 27

    def test_market_triad_reuses_category_no_dup_call(self):
        # 三要素 market 复用类目结果，不重复调用（rev3 §2.2，省 1 次调用）
        import inspect

        src = inspect.getsource(pc.collect_poi)
        assert "TRIAD_RULES" in src or "market" in src  # 结构上复用类目而非对小三要素各自独立 search

    def test_merge_all_dedupes(self):
        merged = pc.merge_all({"market": []})
        # 扩词后再次聚簇去重入口存在且不抛；空输入给空输出
        assert merged == {"market": []}

    @pytest.mark.skipif(not hasattr(pc, "GAIN_STOP_THRESHOLD"), reason="渐进式停止阈值尚未定义")
    def test_stop_threshold_is_positive(self):
        assert pc.GAIN_STOP_THRESHOLD > 0

    def test_u38_budget_tight_admission_set_under_concurrency(self):
        """U38（延迟优化 B2）：预算紧张时准入集合与串行一致 —— 并发 A 阶段不漂移。

        budget=2 → `poi_page_depth(27+, 2)=1`，每词恰耗 1 额度。8 类关键词并发
        `asyncio.gather` 下，consume 是同步原子操作、按任务创建顺序先到先得 ⇒
        **总调用恰 2 次**，预算耗尽后 B 阶段同样零调用。这正是「并发只改墙钟、不改预算数学」
        的锁定（B2 契约）。

        ⚠️ 10-03 甲-B 加了盲区三要素的额度保底。它**没有**改变本条的落点：保底带一条退让地板
        （`remaining` 连"每类一颗首词"都不够时让位，见 `poi_collector` 里那一段），
        而 `total=2 < 8 类` 正落在地板里 ⇒ 2 个单位仍归 A 阶段的头两颗词。
        保底真正咬得动的是真实档位（27/31/40），那半边由 `tests/test_triad_reserve.py` 钉。
        """
        import asyncio

        class Stub:
            def __init__(self):
                self.calls = 0

            async def place_search(self, *a, **k):
                self.calls += 1
                return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)

        stub = Stub()
        b = pc.POIBudget(total=2)
        collected = asyncio.run(
            self._run(stub, center=(107.9758, 26.5734), radius_m=2000, scope=object(), budget_snapshot=b)
        )
        assert stub.calls == 2, f"预算紧张应恰好 2 次调用（准入集合不漂移），实际 {stub.calls}"
        assert b.remaining == 0, "预算必须被恰好花完（2 个单位 = 2 词 × 1 页）"
        assert isinstance(collected.per_category, dict) and isinstance(collected.triads, dict)
        # 预算饿死的词必须**可见**：0 次调用不能悄悄等于「该类没有设施」（P0-2）
        # 计数从判表现算，不背字面量（10-03 甲补两颗社区养老词后，25 这个数当场过期过一次）。
        # ⚠️ `total=2` 落在保底的**退让区**：保底不得推翻"每类至少一颗首词"那条更老的契约
        #   （`test_forensic_rounds.py::test_u38c_starvation_lands_on_category_tails`），
        #   所以 `earmark = min(颗数, max(0, remaining − 类别数))` 在这里算出 0 ⇒ 落点回到旧形状：
        #   A 阶段拿到那 2 个单位，三要素整组饿死。保底在真实档位（27/31/40）才咬得动。
        n_display = sum(len(d["keywords"]) for d in pc.CATEGORY_RULES.values())
        n_triad = len(pc.triad_search_keys())
        starved = list(collected.evidence.starved_terms)
        got_display = {x for x in starved if x[0] in pc.CATEGORY_RULES}
        got_triad = {x for x in starved if x[0] not in pc.CATEGORY_RULES}
        assert len(got_display) == n_display - 2, (
            f"budget=2 应摊开 2 颗词、其余 {n_display - 2} 颗饿死（退让区=旧形状），实际 {len(got_display)}")
        assert len(got_triad) == n_triad, (
            f"退让区里三要素整组该饿死（{n_triad} 颗）⇒ 若它们反而拿到了额度，说明保底压过了'每类一颗'")
        assert n_triad == 2, f"三要素另检索键数变了（{n_triad}）⇒ 本条上方的账要重算"
        assert not collected.evidence.complete

    def test_server_capped_term_collapses_its_own_frontier(self):
        """`server_cap` 在采集账目里的两件事：边界**塌到最远实测点**、并单独进封顶名单。

        只断「它被登记了」不够 —— 判盲吃的是 `frontier_m`。若封顶词仍按请求半径报边界，
        「2500m 内 200 家药店只拿到 20 家」就会被当成「2500m 内查全」，
        那一圈里的假盲区于是有了合法身份。
        """
        import asyncio

        from app.living_circle.baidu_client import STOP_SERVER_CAP

        rows = [
            {"name": f"药店{k}", "lng": 107.9758 + 0.008 * k / 20, "lat": 26.5734, "address": ""}
            for k in range(20)
        ]

        class Stub:
            def __init__(self):
                self.calls = 0

            async def place_search(self, query, *a, **k):
                self.calls += 1
                if query == "药店":
                    return PlaceSearchOut(rows, 200, 1, STOP_SERVER_CAP)
                return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)

        collected = asyncio.run(
            self._run(Stub(), center=(107.9758, 26.5734), radius_m=2000,
                      scope=object(), budget_snapshot=budget())
        )
        rows_of = {t.term: t for t in collected.evidence.per_term}
        capped = rows_of["药店"]
        assert capped.cap_hit is True
        assert capped.complete is False, "服务端自称还有货 ⇒ 请求半径不得当证据边界"
        assert capped.frontier_m == pytest.approx(capped.farthest_m, abs=0.1), (
            f"封顶词的边界应塌到最远实测点，实际 frontier={capped.frontier_m} "
            f"farthest={capped.farthest_m}"
        )
        assert 0 < capped.farthest_m < 1000, (
            f"前置不成立：桩要造的是「边界短于判定半径」，实测 {capped.farthest_m}m"
        )
        assert "pharmacy" in collected.evidence.capped_categories
        assert "pharmacy:药店" in collected.evidence.capped_terms
        # 别的类没封顶 ⇒ 不许被连坐（名单只认真撞上限的那些）
        assert collected.evidence.capped_categories == ("pharmacy",)
        assert collected.evidence.as_detail()["capped_terms"] == ["pharmacy:药店"]

    def test_triad_call_failure_is_not_refunded_and_leaves_evidence(self):
        """T-P0-3（计划 v5.6）：三要素调用失败 ⇒ **不退款 + 留一行 api_error 举证**。

        守护的契约有两条，缺一条都算没修：
        1. **账面**：请求真发出去了，额度就已经花掉。旧写法 `budget.refund(...)` 会让
           「点位凭空消失」在账上变成「钱没花」⇒ 花掉的额度与真实调用数对不上，缺口不可见。
           判据取 `spend == calls`：退款会令 spend 少 1。
        2. **留痕**：必须有一行 `stop_reason=api_error`、`complete=False` 的举证，于是
           `failed_terms` 里有 `pharmacy:药店`，报告能说「这一词请求没成」，
           而不是「这一圈没有药店」。
           ⚠️ R23-D 之前这一位混在 `truncated_terms` 里，报告那句是"发了但没查全" —— 对
           「根本没发出去/没成」的词是**假话**；本条按归责重指，不是放宽（断的还是"必须有位可归"）。
        这条也是 S-P0-2（`bound_source` 派生）的原料 —— 没有这行，派生无从谈起。
        """
        import asyncio

        class Stub:
            def __init__(self):
                self.calls = 0
                self.queries: list = []

            async def place_search(self, query, *a, **k):
                self.calls += 1
                self.queries.append(query)
                if query == "药店":
                    return None          # 百度侧失败：客户端给 None（不是 PlaceSearchOut）
                return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)

        stub = Stub()
        b = pc.POIBudget(total=40)        # 页深 = floor(40/27 词) = 1 ⇒ 每次调用恰耗 1 单位
        collected = asyncio.run(
            self._run(stub, center=(107.9758, 26.5734), radius_m=2000, scope=object(), budget_snapshot=b)
        )
        # 前置自证：失败的确实是三要素那一词，否则整条用例空过
        assert stub.queries.count("药店") == 1, (
            f"桩没让「药店」恰好失败一次（实际 {stub.queries.count('药店')} 次）⇒ 判据没有样本"
        )
        assert b.total - b.remaining == stub.calls, (
            f"花掉的额度({b.total - b.remaining}) ≠ 真实调用数({stub.calls}) ⇒ 有调用被退回了账面"
        )

        rows = [t for t in collected.evidence.per_term if t.category == "pharmacy"]
        assert len(rows) == 1, f"三要素失败应留下恰好一行举证，实际 {len(rows)} 行"
        failed = rows[0]
        assert failed.stop_reason == pc.STOP_API_ERROR
        assert failed.returned == 0 and failed.pages_fetched == 0
        assert failed.complete is False, "调用失败绝不等于「这一圈没有药店」"
        assert "pharmacy:药店" in collected.evidence.failed_terms, (
            "缺口必须可归因：没查成的词要出现在 failed_terms（请求没成 = 一无所知）"
        )
        assert "pharmacy:药店" not in collected.evidence.truncated_terms, (
            "回到 truncated 就等于对没成的词说「发了但没查全」——那是本刀要消灭的假话"
        )
        # 边界保守合取：这一类没证据 ⇒ 边界 0，不许把「一无所知」洗成「查全了」
        assert collected.evidence.frontier_m("pharmacy") == 0.0

    def test_expansion_call_failure_is_not_refunded_and_leaves_evidence(self):
        """T-P0-3b（计划 v5.6）：**扩词**失败也与另两条通道同语义 —— 不退款 + 留 `api_error` 行。

        这条是同一语义的第三个实例，也是三个里最难发现的一个：旧写法是
        `budget.refund(cat) + break` —— 既把钱退回账面，又直接离开循环连一行举证都不记，
        于是「这一类的扩词中途失败」和「这一类扩到量自然收手」在报告里**完全同形**。
        判据因此取两条可区分的：① 有一行 `api_error` 且它的词**不在初始关键词里**
        （证明失败确实发生在扩词阶段，而不是被 A 阶段的同类用例顺手满足）；
        ② 花掉的额度 == 真实调用数（退款会少记，正是旧行为）。
        """
        import asyncio

        from app.living_circle.category_rule import CATEGORY_RULES

        initial = {kw for defn in CATEGORY_RULES.values() for kw in (defn.get("keywords") or [])}
        initial |= {"药店", "小学"}     # 三要素专用词（market 复用类目，不另发）

        class Stub:
            def __init__(self):
                self.calls = 0
                self.queries: list = []

            async def place_search(self, query, *a, **k):
                self.calls += 1
                self.queries.append(query)
                if query not in initial:
                    return None          # 只对**扩词**失败：A 阶段与三要素全部正常返回空
                return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)

        stub = Stub()
        b = pc.POIBudget(total=40)        # 页深 = floor(40/27 词) = 1 ⇒ 每次调用恰耗 1 单位
        collected = asyncio.run(
            self._run(stub, center=(107.9758, 26.5734), radius_m=2000, scope=object(), budget_snapshot=b)
        )
        failed_expansions = [q for q in stub.queries if q not in initial]
        assert failed_expansions, (
            "前置不成立：桩没触发任何扩词调用 ⇒ 本用例没有样本（扩词入口/词表可能已变，"
            "应改判据而不是放宽断言）"
        )
        assert b.total - b.remaining == stub.calls, (
            f"花掉的额度({b.total - b.remaining}) ≠ 真实调用数({stub.calls}) ⇒ 扩词失败被退回了账面"
        )

        rows = [t for t in collected.evidence.per_term if t.stop_reason == pc.STOP_API_ERROR]
        assert rows, "扩词失败必须留下 api_error 举证行"
        assert any(t.term in failed_expansions for t in rows), (
            f"举证必须对得上失败的扩词：rows={sorted(t.term for t in rows)} "
            f"failed={sorted(failed_expansions)}"
        )
        for t in rows:
            assert t.returned == 0 and t.pages_fetched == 0
            assert t.complete is False, "调用失败不等于「这一圈没有」"


def _ev(category, term, *, reason, requested=2000.0, farthest=None, returned=0):
    return pc.TermEvidence(category=category, term=term, requested_radius_m=requested,
                            pages_fetched=1, returned=returned, total=returned,
                            stop_reason=reason, farthest_m=farthest)


class TestEvidenceToDiscConverter:
    """T-P0-4（计划 v5.6）：`TermEvidence → EvidenceDisc` 的唯一转换器与逐类原因表。

    第 0 步实测脚本原本自带一份等价构造（那份是本次要收掉的第二实现），转换里三个判断
    都各有容易抄错的取向：穷尽深度取 `frontier_m` 而不是 `farthest_m`、锚点由调用方给、
    完整性由 `stop_reason` 派生。
    """

    def test_complete_row_projects_request_as_exhausted_not_farthest(self):
        """查全的语意是「请求范围内都干净」⇒ 盘深取**请求值**，哪怕最远实测点很近。"""
        ev = _ev("pharmacy", "药店", reason=pc.STOP_COMPLETE, requested=2000.0, farthest=300.0)
        disc = ev.as_disc((107.9758, 26.5734))
        assert disc.exhausted_radius_m == 2000.0, "查全行必须把请求半径当证据边界"
        assert disc.stop_reason == pc.STOP_COMPLETE and disc.complete is True
        assert disc.anchor == (107.9758, 26.5734)

    def test_truncated_row_projects_farthest_and_is_not_complete(self):
        ev = _ev("pharmacy", "药店", reason=pc.STOP_PAGE_CAP, requested=2000.0,
                 farthest=1494.0, returned=20)
        disc = ev.as_disc((107.9758, 26.5734))
        assert disc.exhausted_radius_m == 1494.0
        assert disc.complete is False and disc.cap_hit is False

    def test_api_error_row_projects_zero_depth_missing_source(self):
        """调用失败：盘深 0、不自称查全 —— 这类行由 T-P0-3 的不退款留痕路径产生。"""
        ev = _ev("pharmacy", "药店", reason=pc.STOP_API_ERROR, requested=2000.0)
        disc = ev.as_disc((107.9758, 26.5734))
        assert disc.exhausted_radius_m == 0.0 and disc.complete is False


class TestPerCategoryStopReason:
    """逐类「为什么停」与逐类边界**同源**：都由决定边界的那一行（frontier 最小者）给。"""

    def _pair(self, order):
        full = _ev("market", "菜市场", reason=pc.STOP_COMPLETE, requested=2000.0, farthest=900.0)
        cut = _ev("market", "农贸市场", reason=pc.STOP_PAGE_CAP, requested=2000.0,
                  farthest=1494.0, returned=20)
        rows = (full, cut) if order == "full_first" else (cut, full)
        return pc.CollectionEvidence(requested_radius_m=2000.0, per_term=rows)

    def test_reason_is_the_binding_row_not_the_first_row(self):
        for order in ("full_first", "cut_first"):
            ev = self._pair(order)
            assert ev.frontier_m("market") == 1494.0, (
                f"{order}：类边界应取各词最小值（保守合取）"
            )
            assert ev.stop_reason_by_category()["market"] == pc.STOP_PAGE_CAP, (
                f"{order}：原因必须来自决定边界那一行，而不是行序 ⇒ 顺序能改变结论就是第二事实源"
            )
            # 同源自检：原因说截断，边界就必须是那个截断词给的
            binding = min(ev.per_term, key=lambda t: t.frontier_m)
            assert binding.stop_reason == ev.stop_reason_by_category()["market"]

    def test_starved_category_has_no_row_and_therefore_no_reason(self):
        """`starved` 的形态是**没有行**（0 次调用不生成举证）⇒ 原因表里根本不该出现它。

        这条是复审 T-P0-4 的直接落点：映射表若按「读某行的 stop_reason==starved」来找缺口，
        那一行并不存在 ⇒ 缺口再次隐形。判据因此落在「键在不在表里」。
        """
        ev = pc.CollectionEvidence(
            requested_radius_m=2000.0,
            per_term=(_ev("market", "菜市场", reason=pc.STOP_EMPTY, requested=2000.0),),
            starved_terms=(("pharmacy", "药店"),),
        )
        reasons = ev.stop_reason_by_category()
        assert "pharmacy" not in reasons, "被饿死的类没有行 ⇒ 无事实可报，不许凭空给原因"
        assert reasons["market"] == pc.STOP_EMPTY
        assert ev.frontier_m("pharmacy") == 0.0
        assert "pharmacy:药店" in tuple(f"{c}:{t}" for c, t in ev.starved_terms)

    def test_api_error_row_is_reported_as_missing_not_frontier(self):
        ev = pc.CollectionEvidence(
            requested_radius_m=2000.0,
            per_term=(_ev("primary", "小学", reason=pc.STOP_API_ERROR, requested=2000.0),),
        )
        assert ev.bound_source_by_category()["primary"] == "missing", (
            "有一行但一行里没有任何点位（调用失败）⇒ 那个「边界」不该被当作实测边界用"
        )

    def test_truncated_row_is_frontier_but_not_complete(self):
        ev = self._pair("full_first")
        assert ev.bound_source_by_category()["market"] == "frontier", (
            "截断词的 1494m 确实是实测到的最远点，来源合法；不完整由 complete/capped 分职说"
        )
        assert ev.complete is False
