"""Phase 6：生活圈体检专家团动态编排测试。

测试目标：
1. `select_living_circle_team` 能从名册中选择有效专家；
2. 返回的 IDs 都经过名册校验，无悬空引用；
3. LLM 失败时能回退到保底团队，**且把降级原因带出来**（第三个返回值）；
4. 保底名单的席位与生活圈名册职位对得上；
5. 「按设施类别配顾问」那套从未生效的代码**不得留任何残留**（半迁移 = 0）。

第 5 条是本轮删改的守卫：旧实现有一张「中文类别关键词 → 域 → 席位」的表，但它依赖的
`facility_categories` 参数从来没有调用方会传（`TaskParams` 里没这个字段，且组队排在 POI
采集之前、类别还没确定），线上永远走默认分支；表里 elderly 还挂着 L1-019「无障碍环境顾问」
与 L1-020「儿童友好规划师」（机构养老顾问其实是 L1-008）。删干净比留着更值钱。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.pipeline.lc_team import (
    _FALLBACK_SEATS,
    _all_categories_text,
    _fallback_team,
    _roster_index,
    select_living_circle_team,
)

LC_TEAM_SRC = Path(__file__).resolve().parent.parent / "app" / "core" / "pipeline" / "lc_team.py"
PIPELINE_SRC = Path(__file__).resolve().parent.parent / "app" / "core" / "pipeline" / "living_circle.py"


class TestRosterIndex:
    """测试名册索引构建。"""

    def test_roster_contains_all_48_experts(self):
        """名册索引应包含全部 48 位专家。"""
        assert len(_roster_index()) == 48

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
        ids, reasons, _degraded = select_living_circle_team(scene_name="测试社区", travel_mode="walking")
        roster = _roster_index()
        assert len(ids) >= 5, "团队人数不应过少"
        for eid in ids:
            assert eid in roster, f"专家 {eid} 不在名册中"

    def test_returns_matching_reasons(self):
        """返回的 reasons 数量应与 ids 一致。"""
        ids, reasons, _degraded = select_living_circle_team(scene_name="测试社区")
        assert len(ids) == len(reasons), "IDs 与 reasons 数量不匹配"

    def test_leaders_first_in_list(self):
        """L3 决策层专家应排在团队列表前面。"""
        ids, _, _degraded = select_living_circle_team(scene_name="测试社区")
        l3_positions = [i for i, eid in enumerate(ids) if eid.startswith("L3")]
        assert l3_positions, "团队中应有 L3 决策层专家"
        assert all(pos < 3 for pos in l3_positions), "L3 专家应排在前 3 位"

    def test_signature_has_no_category_param(self):
        """函数签名里不得再有 `facility_categories`。

        判据取签名而非行为：参数留着，就还会有人以为"按类别配顾问"在发生。
        """
        import inspect

        assert "facility_categories" not in inspect.signature(select_living_circle_team).parameters


class TestFallbackTeam:
    """测试保底团队。"""

    def test_seats_all_exist_in_roster(self):
        ids, reasons = _fallback_team()
        roster = _roster_index()
        missing = [i for i in ids if i not in roster]
        assert not missing, f"保底名单有席位不在名册：{missing}"
        assert len(ids) >= 5, f"保底名单不该比 LLM 最低门槛还短：{len(ids)}"
        assert len(ids) == len(reasons)
        assert len(set(ids)) == len(ids), "保底名单不该有重复席位"

    def test_advisors_match_living_circle_roles(self):
        """四枚领域顾问席位必须真的是管这件事的人（职位文字含对应领域）。"""
        from app.data import load_experts

        role = {e["id"]: e["role_title"] for e in load_experts("living_circle")}
        expect = {
            "L2-001": "医疗",
            "L2-002": "教育",
            "L2-003": "养老",
            "L2-004": "菜市",
        }
        for seat, keyword in expect.items():
            assert keyword in role[seat], f"{seat} 的职位是「{role[seat]}」，不含「{keyword}」，保底名单要重排"

    def test_method_seats_cover_the_four_pipeline_steps(self):
        """定位 / 核验 / 测时 / 评分四步都要有对应方法专家。"""
        from app.data import load_experts

        role = {e["id"]: e["role_title"] for e in load_experts("living_circle")}
        ids, _ = _fallback_team()
        for seat, keyword in (
            ("L1-025", "空间定位"),
            ("L1-030", "核验"),
            ("L1-027", "可达性"),
            ("L1-032", "评分建模"),
        ):
            assert seat in ids, f"保底名单缺方法专家 {seat}"
            assert keyword in role[seat], f"{seat} 职位是「{role[seat]}」，不含「{keyword}」"

    def test_dropped_seat_is_not_silently_kept(self, monkeypatch):
        """名册里查不到的席位必须被摘掉，不能交出一个悬空 id。"""
        import app.core.pipeline.lc_team as mod

        real = _roster_index()
        partial = {k: v for k, v in real.items() if k != "L1-032"}
        monkeypatch.setattr(mod, "_roster_index", lambda: partial)
        ids, _ = _fallback_team()
        assert "L1-032" not in ids, "名册已无该席位，保底名单还在交出去"


class TestDegradedVisibility:
    """降级必须可被调用方看见（第三个返回值），三态各钉一次。"""

    def test_normal_llm_team_reports_no_degradation(self, monkeypatch):
        import app.core.llm as llm

        roster = _roster_index()
        ids = list(roster)[:8]
        monkeypatch.setattr(
            llm, "chat_json",
            lambda *a, **k: {"team": [{"id": i, "reason": "分工"} for i in ids]},
        )
        got, reasons, degraded = select_living_circle_team(scene_name="测试社区")
        assert degraded == "", f"模型正常返回时不该标降级，实得 {degraded!r}"
        assert len(got) == len(reasons) == 8

    def test_llm_exception_marks_llm_error(self, monkeypatch):
        import app.core.llm as llm

        def boom(*a, **k):
            raise RuntimeError("401 令牌过期")

        monkeypatch.setattr(llm, "chat_json", boom)
        _, _, degraded = select_living_circle_team(scene_name="测试社区")
        assert degraded == "llm_error", degraded

    def test_short_team_marks_team_too_small(self, monkeypatch):
        """模型活着但只给出 2 个人 ⇒ 与"调用失败"是两种成因，文案要能分开。"""
        import app.core.llm as llm

        roster = _roster_index()
        two = list(roster)[:2]
        monkeypatch.setattr(
            llm, "chat_json",
            lambda *a, **k: {"team": [{"id": i, "reason": "分工"} for i in two]},
        )
        ids, _, degraded = select_living_circle_team(scene_name="测试社区")
        assert degraded == "team_too_small", degraded
        assert len(ids) >= 5, "降级后仍要交出一份够用的保底名单"


class TestCategoriesComeFromRegistry:
    """组队输入里的类别必须从唯一真相源遍历取。"""

    def test_prompt_lists_all_registry_categories(self):
        from app.living_circle.category_rule import CATEGORY_RULES

        text = _all_categories_text()
        for key, rule in CATEGORY_RULES.items():
            assert rule["label"] in text, f"注册表类别 {key}（{rule['label']}）没进组队输入"
        assert text.count("、") == len(CATEGORY_RULES) - 1, f"类别串形状异常：{text}"


class TestNoGhostCategoryPlumbing:
    """删掉的东西不许留残骸（残留 = 0）。

    判据取**代码形状**（形参/实参/定义/赋值），不是"文件里出现这个词"——
    文件头的注释要解释"为什么删掉了 `_FACILITY_DOMAINS`"，按字面量扫会被自己的文档误伤。
    """

    #: 形状 → 人类可读名；命中任意一条即说明那套东西还在被使用
    DEAD_SHAPES = {
        "facility_categories=": "按类别传参的调用点",
        "facility_categories:": "按类别的形参声明",
        "def _map_category_to_domain": "中文关键词→域的映射函数",
        "def _fallback_team_for_categories": "按类别生成保底的函数",
        "_FACILITY_DOMAINS.": "设施域席位表的使用点",
        "_FACILITY_DOMAINS =": "设施域席位表的定义",
        "_FALLBACK_TEAM =": "无人引用的旧保底常量",
    }

    @pytest.mark.parametrize("src", [LC_TEAM_SRC, PIPELINE_SRC], ids=["lc_team", "living_circle"])
    def test_no_removed_code_shapes_survive(self, src):
        text = src.read_text(encoding="utf-8")
        hit = {shape: why for shape, why in self.DEAD_SHAPES.items() if shape in text}
        assert not hit, f"{src.name} 里还有：{hit}"

    def test_fallback_seats_are_the_only_team_constant(self):
        """`_FALLBACK_SEATS` 必须是唯一一份保底名单来源，且席位都在名册里。"""
        roster = _roster_index()
        assert all(eid in roster for eid, _ in _FALLBACK_SEATS)
