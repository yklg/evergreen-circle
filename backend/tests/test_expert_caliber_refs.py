"""CI 前向闸：专家 caliber_refs 与口径索引的双向校验。

测试目标：
1. 所有专家的 caliber_refs 中的 ref 都必须存在于 caliber_index.all_refs() 中；
2. 改名/删除口径常量后，引用该常量的专家会在校验时失败；
3. vocabulary gate 能捕获未授权的指标术语。
"""
from __future__ import annotations

import pytest

from app.data.schema import validate_roster
from app.living_circle import caliber_index


def load_current_roster() -> list[dict]:
    """加载当前生成的名册（从 backend/app/data/experts.json）。"""
    import json
    from pathlib import Path
    roster_file = Path(__file__).parent.parent / "app" / "data" / "experts.json"
    with open(roster_file, encoding="utf-8") as f:
        return json.load(f)


class TestCaliberRefsValidity:
    """测试 caliber_refs 中的所有 ref 都存在于口径索引中。"""

    def test_all_refs_exist_in_index(self):
        """所有专家的 caliber_refs 必须指向真实存在的口径标识符。"""
        roster = load_current_roster()
        all_valid_refs = caliber_index.all_refs()

        for expert in roster:
            eid = expert.get("id", "?")
            refs = expert.get("caliber_refs", [])
            for ref_entry in refs:
                ref = ref_entry.get("ref", "")
                assert ref in all_valid_refs, (
                    f"[{eid}] ref={ref!r} 不在 caliber_index.all_refs() 中，"
                    f"可能是拼写错误或口径已被删除"
                )

    def test_l3_003_has_required_kinds(self):
        """L3-003（decision 组）必须同时包含 scoring 和 caliber 种类。"""
        roster = load_current_roster()
        l3_003 = next((e for e in roster if e["id"] == "L3-003"), None)
        assert l3_003 is not None, "L3-003 不存在于名册中"

        refs = l3_003.get("caliber_refs", [])
        kinds_present = {r["ref"].split("::")[0] for r in refs if "::" in r["ref"]}

        required = {"scoring", "caliber"}
        missing = required - kinds_present
        assert not missing, (
            f"L3-003 缺少必需的口径种类：{missing}，实际仅有 {kinds_present}"
        )

    def test_ref_note_length_constraint(self):
        """所有 caliber_refs 的 note 字段必须 ≤40 字符。"""
        roster = load_current_roster()
        problems = validate_roster(roster)
        # 过滤出只关于 note 长度的问题
        note_problems = [p for p in problems if "note" in p and "40" in p]
        assert not note_problems, f"发现 note 长度超限：{note_problems}"


class TestVocabularyGate:
    """测试词表闸能正确识别未授权的指标术语。"""

    def test_allowed_terms_pass(self):
        """允许词表中的术语应该通过校验。"""
        allowed_texts = [
            "掌握覆盖率计算方法",
            "评估可达率与多样性",
            "检查均衡性得分",
            "分析采样点可达率",
            "执行名称归一与聚簇去重口径",
        ]
        for text in allowed_texts:
            problems = caliber_index.validate_vocabulary(text)
            assert not problems, f"文本 {text!r} 应通过词表闸，但发现问题：{problems}"

    def test_fictional_metrics_detected(self):
        """虚构的指标术语应被词表闸捕获。"""
        fictional_texts = [
            "测时成功率达到 95%",  # 已替换为"采样点可达率"
            "POI去重率为 80%",     # 已替换为"名称归一与聚簇去重口径"
            "数据完整率达到 99%",   # 虚构术语
        ]
        for text in fictional_texts:
            problems = caliber_index.validate_vocabulary(text)
            assert problems, f"文本 {text!r} 应被词表闸拒绝，但未发现问题"

    def test_roster_prose_passes_vocabulary_gate(self):
        """名册中所有专家的 prose 字段都应通过词表闸。"""
        roster = load_current_roster()
        all_problems = []

        for expert in roster:
            eid = expert.get("id", "?")
            for field_name in ("one_liner", "knowledge_base"):
                text = expert.get(field_name, "")
                if text:
                    problems = caliber_index.validate_vocabulary(text)
                    if problems:
                        all_problems.extend([f"[{eid}] {field_name}: {p}" for p in problems])

        assert not all_problems, (
            f"名册中有专家的 prose 未通过词表闸：\n" + "\n".join(all_problems)
        )


class TestRefRenameDetection:
    """测试改名/删除口径常量后的检测机制。"""

    def test_rename_would_cause_validation_failure(self):
        """如果口径常量改名，引用旧名的专家会在校验时失败。"""
        roster = load_current_roster()
        # 模拟：假设 caliber::walking.reach_full_min 改名为 caliber::walking.max_reach_time
        # 则 L3-003 的引用会失效
        fake_roster = []
        for expert in roster:
            new_expert = dict(expert)
            if expert["id"] == "L3-003":
                new_refs = []
                for ref_entry in expert.get("caliber_refs", []):
                    new_ref = dict(ref_entry)
                    if new_ref["ref"] == "caliber::walking.reach_full_min":
                        new_ref["ref"] = "caliber::walking.max_reach_time"  # 不存在的 ref
                    new_refs.append(new_ref)
                new_expert["caliber_refs"] = new_refs
            fake_roster.append(new_expert)

        problems = validate_roster(fake_roster)
        # validate_roster 本身不检查 ref 是否存在，需要额外检查
        all_valid_refs = caliber_index.all_refs()
        invalid_refs = []
        for expert in fake_roster:
            for ref_entry in expert.get("caliber_refs", []):
                if ref_entry["ref"] not in all_valid_refs:
                    invalid_refs.append(f"[{expert['id']}] {ref_entry['ref']}")

        assert invalid_refs, "改名后的 ref 应该被检测为无效"
        assert any("max_reach_time" in ref for ref in invalid_refs), (
            "应该检测到 max_reach_time 这个不存在的 ref"
        )
