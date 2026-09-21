"""Phase 6：生活圈体检专家团动态编排测试。

测试目标：
1. select_living_circle_team 能从名册中选择有效专家；
2. 返回的 IDs 都经过名册校验，无悬空引用；
3. LLM 失败时能回退到领域保底团队；
4. 不同设施类别触发不同的保底顾问组合。
"""
from __future__ import annotations

import pytest

from app.core.pipeline.lc_team import (
    _FACILITY_DOMAINS,
    _fallback_team_for_categories,
    _map_category_to_domain,
    _roster_index,
    select_living_circle_team,
)


class TestRosterIndex:
    """测试名册索引构建。"""

    def test_roster_contains_all_48_experts(self):
        """名册索引应包含全部 48 位专家。"""
        roster = _roster_index()
        assert len(roster) == 48

    def test_roster_ids_match_expected_sequence(self):
        """名册 ID 应符合 L3-001..L3-003, L2-001..L2-009, L1-001..L1-036 序列。"""
        roster = _roster_index()
        expected_ids = (
            [f"L3-{i:03d}" for i in range(1, 4)]
            + [f"L2-{i:03d}" for i in range(1, 10)]
            + [f"L1-{i:03d}" for i in range(1, 37)]
        )
        assert set(roster.keys()) == set(expected_ids)


class TestSelectLivingCircleTeam:
    """测试动态团队选择。"""

    def test_returns_valid_expert_ids(self):
        """返回的专家 IDs 都应存在于名册中。"""
        ids, reasons = select_living_circle_team(
            scene_name="测试社区",
            facility_categories=["医疗", "教育"],
            travel_mode="walking",
        )
        roster = _roster_index()
        assert len(ids) >= 5, "团队人数不应过少"
        for eid in ids:
            assert eid in roster, f"专家 {eid} 不在名册中"

    def test_returns_matching_reasons(self):
        """返回的 reasons 数量应与 ids 一致。"""
        ids, reasons = select_living_circle_team(
            scene_name="测试社区",
            facility_categories=["购物"],
            travel_mode="walking",
        )
        assert len(ids) == len(reasons), "IDs 与 reasons 数量不匹配"

    def test_leaders_first_in_list(self):
        """L3 决策层专家应排在团队列表前面。"""
        ids, _ = select_living_circle_team(
            scene_name="测试社区",
            facility_categories=[],
            travel_mode="walking",
        )
        # 前几位应包含 L3 专家
        l3_positions = [i for i, eid in enumerate(ids) if eid.startswith("L3")]
        assert l3_positions, "团队中应有 L3 决策层专家"
        assert all(pos < 3 for pos in l3_positions), "L3 专家应排在前 3 位"


class TestFallbackTeamForCategories:
    """测试保底团队生成。"""

    def test_medical_category_triggers_medical_advisor(self):
        """医疗类别应触发医疗顾问（L2-001）。"""
        ids, _ = _fallback_team_for_categories(["医疗"])
        assert "L2-001" in ids, "医疗类别应包含医疗顾问 L2-001"

    def test_education_category_triggers_education_advisor(self):
        """教育类别应触发教育规划师（L2-002）。"""
        ids, _ = _fallback_team_for_categories(["教育"])
        assert "L2-002" in ids, "教育类别应包含教育规划师 L2-002"

    def test_shopping_category_triggers_commerce_advisor(self):
        """购物类别应触发商业顾问（L2-004）。"""
        ids, _ = _fallback_team_for_categories(["购物"])
        assert "L2-004" in ids, "购物类别应包含商业顾问 L2-004"

    def test_multiple_categories_trigger_multiple_advisors(self):
        """多类别应触发多个对应顾问。"""
        ids, _ = _fallback_team_for_categories(["医疗", "教育", "购物"])
        assert "L2-001" in ids, "应包含医疗顾问"
        assert "L2-002" in ids, "应包含教育规划师"
        assert "L2-004" in ids, "应包含商业顾问"

    def test_empty_categories_uses_default_advisors(self):
        """空类别列表应使用默认核心顾问。"""
        ids, _ = _fallback_team_for_categories([])
        # 默认应包含核心决策层和方法专家
        assert "L3-001" in ids
        assert "L3-002" in ids
        assert "L1-025" in ids  # 空间定位师
        assert "L1-030" in ids  # POI 核验官

    def test_no_duplicate_ids(self):
        """保底团队不应有重复的专家 ID。"""
        ids, _ = _fallback_team_for_categories(["医疗", "教育", "购物", "养老"])
        assert len(ids) == len(set(ids)), "存在重复的专家 ID"

    def test_reasons_match_ids_count(self):
        """reasons 数量应与 ids 一致。"""
        ids, reasons = _fallback_team_for_categories(["医疗", "教育"])
        assert len(ids) == len(reasons)


class TestMapCategoryToDomain:
    """测试设施类别到领域的映射。"""

    def test_medical_keywords_map_to_medical(self):
        """医疗关键词应映射到 medical 领域。"""
        assert _map_category_to_domain("医疗") == "medical"
        assert _map_category_to_domain("医院") == "medical"
        assert _map_category_to_domain("诊所") == "medical"
        assert _map_category_to_domain("药店") == "medical"

    def test_education_keywords_map_to_education(self):
        """教育关键词应映射到 education 领域。"""
        assert _map_category_to_domain("教育") == "education"
        assert _map_category_to_domain("小学") == "education"
        assert _map_category_to_domain("幼儿园") == "education"

    def test_shopping_keywords_map_to_shopping(self):
        """购物关键词应映射到 shopping 领域。"""
        assert _map_category_to_domain("购物") == "shopping"
        assert _map_category_to_domain("菜市场") == "shopping"
        assert _map_category_to_domain("超市") == "shopping"

    def test_elderly_keywords_map_to_elderly(self):
        """养老关键词应映射到 elderly 领域。"""
        assert _map_category_to_domain("养老") == "elderly"
        assert _map_category_to_domain("养老院") == "elderly"

    def test_unknown_category_returns_none(self):
        """未知类别应返回 None。"""
        assert _map_category_to_domain("未知类别") is None
        assert _map_category_to_domain("") is None


class TestFacilityDomainsConstant:
    """测试设施领域常量结构。"""

    def test_all_domains_have_experts(self):
        """所有领域都应有对应的专家列表。"""
        for domain, experts in _FACILITY_DOMAINS.items():
            assert isinstance(experts, list), f"{domain} 的专家列表应为 list"
            assert len(experts) >= 2, f"{domain} 应至少有 2 位专家"
            # 第一位应为策略顾问（L2）
            assert experts[0].startswith("L2"), f"{domain} 的第一位专家应为 L2 策略顾问"
