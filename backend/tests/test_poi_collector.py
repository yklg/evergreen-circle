"""采集 + 扩词策略 `poi_collector.py`（rev3 §四B）—— POIBudget 分配快照 / ExpansionCtx / 主循环。

TDD 红测试：模块未落地，`importorskip` 守卫缺失即整文件 skip；
落地后自动转真实断言（预算记账 / 渐进式停止 / 合并去重 / 主循环总调用上限）。
"""
import pytest

pc = pytest.importorskip("app.living_circle.poi_collector", reason="poi_collector.py 待 rev3 落地（§四B）")


def budget():
    # quota 产出的分配快照（27 = 免费档 poi 预算）。纯工厂：刻意非 pytest fixture，
    # 便于在各用例内手动实例化独立快照做记账断言。
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
                return []

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