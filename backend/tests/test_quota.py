"""S1-S8 预算唯一事实源 `quota.py`（rev3 前置）—— 纯函数数值契约 + 单一归属护栏。

本文件是「先测试后落地」的 TDD 红测试：`quota.py` 尚未实现，
以 `pytest.importorskip` 守卫 —— 缺失即整文件 skip，不污染既有 705 全绿套件；
`quota.py` 按 rev3 §四F 落地后自动转真实断言。
"""
import pytest

quota = pytest.importorskip("app.living_circle.quota", reason="quota.py 待 rev3 落地（§四F 前置）")


class TestBudgetValues:
    """免费档预算数值（rev3 §五 推演铰点）。"""

    def test_free_tier_matrix_and_poi(self):
        mat, poi = quota.quota_budget()
        assert (mat, poi) == (15, 27)

    def test_total_budget_is_42(self):
        assert quota.total_budget() == 42

    def test_budget_partition_consistent(self):
        # 不变量：全局 = 矩阵 + POI，分区完整、POI 有余量
        mat, poi = quota.quota_budget()
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
        names = {"total_budget", "poi_budget"}
        violators = []
        for py in (root / "living_circle").glob("*.py"):
            src = py.read_text(encoding="utf-8")
            for n in names:
                # 只查「def 定义」而非引用：其他模块应 import 而非重定义公式
                if re.search(rf"^def\s+{re.escape(n)}\s*\(", src, flags=re.M):
                    violators.append(f"{py.name}:{n}")
        assert violators == [], f"预算公式必须单一归属 quota.py，不得在其它模块重定义: {violators}"