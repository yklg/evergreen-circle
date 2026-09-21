"""类别判定规则 `category_rule.py`（rev3 §四A）—— S1/S2/S8 判据唯一事实源。

TDD 红测试：模块未落地，`importorskip` 守卫缺失即整文件 skip；
落地后自动转真实断言（5 条口径原则 + 便利店开关 + 置信度档位）。
"""
import pytest

cr = pytest.importorskip("app.living_circle.category_rule", reason="category_rule.py 待 rev3 落地（§四A）")


class TestCategoryKeys:
    """类别键集与既有 `poi.CATEGORY_DEFS` 一致（8 类民生），不双写两套表。"""

    def test_has_all_eight_categories(self):
        from app.living_circle.poi import CATEGORY_DEFS

        assert set(cr.CATEGORY_RULES) == set(CATEGORY_DEFS)
        assert len(cr.CATEGORY_RULES) == 8

    def test_each_rule_has_required_fields(self):
        for key, defn in cr.CATEGORY_RULES.items():
            for f in ("label", "keywords", "accept_tags", "reject_tags", "ideal_circle"):
                assert f in defn, f"{key} 缺 {f}"

    def test_triad_market_reuses_market_category(self):
        assert cr.TRIAD_RULES["market"] in cr.CATEGORY_RULES


class TestEvaluateCategory:
    """5 条口径判定原则（按服务属性裁，accept/reject 标签裁决）。"""

    def test_accept_tag_high_confidence(self):
        # 菜市场 accept_tag 命中 → 高置信归 market
        cat, conf = cr.evaluate_category({"name": "老街菜市场", "lng": 0, "lat": 0, "tag": "菜市场", "type": ""})
        assert cat == "market"
        assert conf >= cr.CONFIDENCE["high"]

    def test_reject_tag_excluded(self):
        # 海鲜餐厅带 reject_tag → 不得归 market
        cat, _ = cr.evaluate_category({"name": "渔港海鲜餐厅", "lng": 0, "lat": 0, "tag": "海鲜餐厅", "type": ""})
        assert cat != "market"

    def test_keyword_only_mid_confidence(self):
        # 仅名称含关键词、无标签 → 中置信
        cat, conf = cr.evaluate_category({"name": "凯里超市", "lng": 0, "lat": 0, "tag": "", "type": ""})
        assert cat == "shopping"
        assert conf == cr.CONFIDENCE["mid"]

    def test_no_signal_low_confidence_other(self):
        cat, conf = cr.evaluate_category({"name": "未知杂项", "lng": 0, "lat": 0, "tag": "", "type": ""})
        assert cat == "other"
        assert conf <= cr.CONFIDENCE["low"]

    def test_unknown_never_raises(self):
        # 脏数据/空 dict 不得抛
        for bad in ({}, {"name": None}, {"name": "x", "lng": None}):
            cr.evaluate_category(bad)


class TestConvenienceStoreCaliber:
    """便利店口径开关（rev3 §2.2 / §六）：默认算购物，切菜篮子优先则归降噪。"""

    def test_convenience_default_is_shopping(self):
        assert cr.SHOPPING_INCLUDE_CONVENIENCE is True
        cat, _ = cr.evaluate_category({"name": "美宜佳便利店", "lng": 0, "lat": 0, "tag": "便利店", "type": ""})
        assert cat == "shopping"

    def test_rules_include_convenience_keyword_when_enabled(self):
        assert any("便利店" in k for k in cr.CATEGORY_RULES["shopping"]["keywords"])


class TestRuleSelfConsistency:
    """判表自洽：accept 与 reject 不得含同词双重裁决（rev3 用例 8）。"""

    def test_accept_reject_disjoint(self):
        for key, defn in cr.CATEGORY_RULES.items():
            overlap = set(defn["accept_tags"]) & set(defn["reject_tags"])
            assert not overlap, f"{key} 预设词既 accept 又 reject: {overlap}"