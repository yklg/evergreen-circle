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


class TestElderlyCommunityNaming:
    """甲（#87）· 两颗社区级养老命名的**名称通道**，以及它救不了的那一支。

    读码账目（同文件顶部原则）：标签通道先裁、名称通道只在**没有任何类 accept_tag 命中**时才走到，
    且要求**唯一命中**。所以"补词就把社区养老认下"这句话只在 tag 不撞车时成立 ——
    本类把成立与不成立两支**分开钉**，不共用一句（共用必有一支说谎）。
    """

    STATION = "北京市朝阳区团结湖街道社区养老服务驿站"
    CENTER_ = "朝阳区八里庄街道养老服务中心"
    KAILI = "凯里市和谐社区居家养老服务站"

    def test_new_terms_are_registered_once_in_elderly_only(self):
        for term in ("养老服务驿站", "养老服务中心"):
            homes = [k for k, d in cr.CATEGORY_RULES.items() if term in d["keywords"]]
            assert homes == ["elderly"], f"「{term}」出现在 {homes} ⇒ 一颗检索词喂给多个大类"

    def test_community_naming_is_recognized_via_name_channel(self):
        """tag 不撞车时：名称含这两颗词 ⇒ `elderly`，且只中"弱先验"那一档（0.6，不是 0.9）。"""
        for name in (self.STATION, self.CENTER_):
            for tag in ("", "生活服务:社区服务中心", "医疗保健:卫生院", "地名地址信息:门牌信息"):
                cat, conf = cr.evaluate_category({"name": name, "lng": 0, "lat": 0, "tag": tag, "type": ""})
                assert cat == "elderly", f"{name} / tag={tag!r} 判成 {cat} ⇒ 补词没被认下"
                assert conf == cr.CONFIDENCE["mid"], f"{name} 走的是名称弱先验，不该给高置信"

    def test_service_tag_still_wins_and_that_is_yi_not_jia(self):
        """现状钉（**不是** xfail）：`tag` 含「社区服务站」时政务在标签通道先赢，补词救不了它。

        甲只改名称通道；这条形状属乙（通道优先级），本批刻意不修。写成断言现状而不是挂 xfail，
        是因为"没修"在这里不是缺陷未修，而是**已拍板的范围边界** —— 挂 xfail 会让乙落地那天
        必须来摘标，而那一天真正要改的是这条断言的**方向**（改成 elderly 优先），不是它的存在。
        """
        for name in (self.KAILI, self.STATION):
            for tag in ("社区服务站", "生活服务:社区服务站"):
                cat, conf = cr.evaluate_category({"name": name, "lng": 0, "lat": 0, "tag": tag, "type": ""})
                assert cat == "service", f"{name} / tag={tag!r} 判成 {cat} ⇒ 通道优先级已被改动，先复核乙"
                assert conf >= cr.CONFIDENCE["high"]

    def test_kaili_style_naming_still_needs_a_third_term(self):
        """「居家养老服务站」不含这两颗词 ⇒ 甲**没**把它认下（第 3 颗词待凯里侧取证）。"""
        cat, _ = cr.evaluate_category({"name": self.KAILI, "lng": 0, "lat": 0, "tag": "", "type": ""})
        assert cat == "other", f"{self.KAILI} 判成 {cat} ⇒ 第 3 颗词已落地，本条该改写"
        assert "居家养老" not in cr.CATEGORY_RULES["elderly"]["keywords"]