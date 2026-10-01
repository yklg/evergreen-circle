"""S1-S8 预算唯一事实源 `quota.py`（rev3 前置）—— 纯函数数值契约 + 单一归属护栏。

本文件是「先测试后落地」的 TDD 红测试：`quota.py` 尚未实现，
以 `pytest.importorskip` 守卫 —— 缺失即整文件 skip，不污染既有 705 全绿套件；
`quota.py` 按 rev3 §四F 落地后自动转真实断言。
"""
import pytest

quota = pytest.importorskip("app.living_circle.quota", reason="quota.py 待 rev3 落地（§四F 前置）")


class TestBudgetValues:
    """免费档预算数值（rev3 §五 推演铰点 + D5 反向导出）。"""

    def test_free_tier_matrix_and_poi(self):
        # D5 翻转后分区由**采样规格**导出：standard/步行 双阶段需求 1049 点、chunk=100
        # ⇒ 矩阵 11 次，其余 31 次全归取证。旧写法是恒为 (15, 27) 的比例分配 ——
        # 那 4 次凭空蒸发（矩阵用不掉、取证拿不到），正是「三要素被饿死」的来源之一。
        assert quota.quota_budget("standard", "walking") == (11, 31)

    def test_free_tier_partition_for_a_dense_spec_is_capped(self):
        """驾车 standard 需求 505 次，份额闸削到 15 ⇒ 取证永不被清零。"""
        assert quota.quota_budget("standard", "driving") == (15, 27)

    def test_forensics_always_afford_one_page_per_term(self):
        """分区怎么抢，取证至少得够「每个展示词查一次」—— 否则该类点位会整类消失。

        这条取代了旧的 `mat + poi <= total`：那个式子允许 (42, 0)，而 (42, 0) 恰是
        用户报的「点很少但不是盲区」的极端形状。
        """
        from app.living_circle.category_rule import CATEGORY_RULES

        need = sum(len(d["keywords"]) for d in CATEGORY_RULES.values())
        for profile in ("quick", "standard", "precise"):
            for tm in ("walking", "riding", "driving"):
                mat, poi = quota.quota_budget(profile, tm)
                assert mat + poi == quota.total_budget(), (profile, tm)
                assert poi >= need, f"{profile}/{tm}：取证 {poi} 次 < 词表 {need} 词 ⇒ 有词必被饿死"

    def test_total_budget_is_42(self):
        assert quota.total_budget() == 42

    def test_budget_partition_consistent(self):
        # 不变量：全局 = 矩阵 + POI，分区完整、POI 有余量
        mat, poi = quota.quota_budget("standard", "walking")
        assert mat + poi <= quota.total_budget()

    def test_poi_page_depth_free_tier_is_one(self):
        # 22 关键词 27 预算 → floor(27/22)=1
        assert quota.poi_page_depth(n_terms=22, poi_budget=27) == 1

    def test_poi_page_depth_deepens_when_budget_rich(self):
        # 词少预算足 → 页深回升（写入即外推：付费档自动获益）
        assert quota.poi_page_depth(n_terms=6, poi_budget=27) == 3


class TestPageDepthBoundaries:
    """`poi_page_depth` 边界：clamp 到 [1,3]，杜绝 0 / 负 / 爆表。"""

    def test_zero_budget_clamps_to_one(self):
        assert quota.poi_page_depth(n_terms=5, poi_budget=0) == 1

    def test_negative_budget_clamps_to_one(self):
        assert quota.poi_page_depth(n_terms=5, poi_budget=-3) == 1

    def test_huge_budget_caps_at_three(self):
        assert quota.poi_page_depth(n_terms=2, poi_budget=10_000) == 3

    def test_zero_terms_no_division_error(self):
        # 词表为空 → 不退化为出 0/除零；回退默认页深 1
        assert quota.poi_page_depth(n_terms=0, poi_budget=27) == 1


class TestQuotaSingleSourceGuard:
    """唯一事实源护栏（rev3 §八:15，P1-1）：除 `quota.py` 外不得另行定义预算公式。"""

    def test_budget_symbols_not_redefined_elsewhere(self, tmp_path):
        import re
        from pathlib import Path

        root = Path(quota.__file__).parent.parent.parent  # app/living_circle → app
        names = {"total_budget", "poi_budget", "poi_budget_for", "mat_budget",
                 "mat_budget_for", "matrix_calls_for", "max_matrix_origins"}
        violators = []
        for py in (root / "living_circle").glob("*.py"):
            src = py.read_text(encoding="utf-8")
            for n in names:
                # 只查「def 定义」而非引用：其他模块应 import 而非重定义公式
                if re.search(rf"^def\s+{re.escape(n)}\s*\(", src, flags=re.M):
                    violators.append(f"{py.name}:{n}")
        assert violators == [], f"预算公式必须单一归属 quota.py，不得在其它模块重定义: {violators}"


class TestMaxMatrixOriginsAndCeiling:
    """v5 B2/B4（U14-U15）+ D5：矩阵采样上限由规格导出 + 熔断上限接线。"""

    def test_u14_max_matrix_origins_is_spec_derived(self):
        # 同一个 15 次的份额闸，两种出行方式给出的上限差 4 倍 —— 因为 chunk 不同。
        # 旧函数签名收 `chunk` 整数（调用方各自去 caliber 读，三处漂移），
        # 现在收「档位 + 出行方式」，chunk 读取收敛到 `_chunk_of` 一处。
        assert quota.max_matrix_origins("standard", "driving") == 15 * 25 == 375
        assert quota.max_matrix_origins("standard", "walking") == 11 * 100 == 1100

    def test_u14_allowance_never_exceeds_demand(self):
        """矩阵额度 == min(规格需求, 份额闸) —— 一个子也不许多占。

        旧比例制的病灶就在这儿：步行 standard 需求 11 次也照占 15 次，那 4 次既没花在
        矩阵上、也没转给取证。翻转后额度贴着需求走，越闸才削平（削平即降级，由
        `sample_plan` 如实标 `degraded`）。
        顺带钉住「未越闸 ⇒ 不降级」：额度给足需求，采样器就没有理由丢边界加密带。
        """
        from app.living_circle.isochrone import matrix_demand_points

        ceil_ = quota._matrix_share_ceil()
        for profile in ("quick", "standard", "precise"):
            for tm in ("walking", "riding", "driving"):
                demand = matrix_demand_points(profile, tm)
                calls = quota.matrix_calls_for(demand, tm)
                mat = quota.mat_budget_for(profile, tm)
                assert mat == min(calls, ceil_), f"{profile}/{tm}: {mat} ≠ min({calls},{ceil_})"
                if calls < ceil_:
                    assert quota.max_matrix_origins(profile, tm) >= demand, (
                        f"{profile}/{tm}: 额度够却仍会把双阶段压成降级"
                    )

    def test_u14_chunk_zero_falls_back_one(self, monkeypatch):
        # chunk=0/负 → 兜底 1，杜绝 0 上限（采样坍缩成空）。
        # `_chunk_of` 在函数内 import caliber ⇒ 打模块属性即可命中，`monkeypatch` 负责还原。
        import app.living_circle.caliber as cal

        def _stub(chunk):
            return lambda *a, **k: type("Cal", (), {"api": type("A", (), {"chunk": chunk})()})()

        monkeypatch.setattr(cal, "get_caliber", _stub(0))
        assert quota._chunk_of("walking") == 1
        monkeypatch.setattr(cal, "get_caliber", _stub(-3))
        assert quota._chunk_of("walking") == 1
        monkeypatch.setattr(cal, "get_caliber", _stub(100))
        assert quota.matrix_calls_for(1049, "walking") == 11

    def test_u14_qps_escalation_extrapolates(self, monkeypatch):
        # 付费档写入即外推：qps 3→10 → total=140、份额闸 49、矩阵上限等比放大
        monkeypatch.setattr(quota, "_qps", lambda: 10.0)
        assert quota.total_budget() == 140
        assert quota._matrix_share_ceil() == 49
        # 闸不再是天花板：付费档下 precise/步行的真实需求 17 次被全额给出
        assert quota.mat_budget_for("precise", "walking") == 17
        assert quota.max_matrix_origins("standard", "driving") == 49 * 25

    def test_u15_ceiling_is_total_plus_forensic_plus_margin(self):
        # D2 + v5.4 闭 P0-5（v6.1 抬档）：42 精度预算 + 34 扩容回合独立格 + intake ≤3 头寸；
        # 熔断防失控循环。34 不是拍脑袋：一轮按需扩容在步行 ±2500m 形状下实算需 32 次
        # （药店 20 锚点×1 词 + 市场 4 锚点×3 词），旧档 23 撑不满 ⇒ 大范围档恒带 dropped。
        assert quota.total_calls_hard_ceiling() == (
            quota.total_budget() + quota.forensic_budget() + quota.INTAKE_MARGIN
        ) == 79
        # 「新开一格」的代价必须只落在熔断上限这一处，不许回头把首轮喂胖：
        # 窗口 `BUDGET_WINDOW_S` 一动，矩阵闸/首轮 poi/驾车档会三处同漂（复审 R-P0-3）
        assert quota.FORENSIC_WINDOW_S == 16.0 and quota.BUDGET_WINDOW_S == 20.0
        assert quota.forensic_budget() == 34
        assert quota.total_budget() == 42 and quota.poi_budget_for(11) == 31