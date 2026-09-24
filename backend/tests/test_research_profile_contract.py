"""REPORT_PROFILES / report_voice 单一真源契约（计划 §3.2，与 §八 B-1 一致）。

TDD 目标规格：本文件 import `app.core.research_profile`（实现前 collection 报错标识未落地，落地后转绿）。
覆盖：
- B1/B2 guide & assess 章节集（含新 口碑/舆情 guest 章）、label、persona；
- B3 research(默认) 章节 = guide ∪ assess（去重、含口碑+风评）；
- B4 未知/空 purpose → {}（不抛、不污染）；
- B5 别名同源：research_profile 与 orchestrator 的导出指向同一真源。

运行：backend/ 下 `pytest tests/test_research_profile_contract.py -q`。
"""
import pytest

from app.core import research_profile
from app.core.research_profile import REPORT_PROFILES, report_voice

GUIDE = set(REPORT_PROFILES["guide"]["sections"])
ASSESS = set(REPORT_PROFILES["assess"]["sections"])


# ── B1 / B2 ────────────────────────────────────────────
def test_guide_profile_has_voice_section():
    assert "guide_voice" in GUIDE, "攻略报告须含口碑/舆情章"
    assert REPORT_PROFILES["guide"]["label"] == "目的地攻略"
    assert "策划" in REPORT_PROFILES["guide"]["persona"]


def test_assess_profile_has_voice_section():
    assert "assess_voice" in ASSESS, "评估报告须含风评/舆情章"
    assert REPORT_PROFILES["assess"]["label"] == "目的地评估"
    # guide 与 assess 章节仅允许交 summary/conclusion
    assert GUIDE & ASSESS == {"summary", "conclusion"}, "两种报告章节不应越界耦合"


# ── B3：research(默认) ────────────────────────────────
def test_research_default_profile_union_guide_assess():
    default = list(REPORT_PROFILES["research"]["sections"])
    assert GUIDE <= set(default) and ASSESS <= set(default), "默认=guide∪assess"
    assert len(default) == len(set(default)), "默认章节不得重复"
    assert {"guide_voice", "assess_voice"} <= set(default)


# ── B4：未知/空 purpose ────────────────────────────────
@pytest.mark.parametrize("purpose", ["", "bogus", "  "])
def test_unknown_purpose_returns_empty(purpose):
    assert report_voice(purpose) == {}, f"未知 purpose 应返回空 dict，不抛不污染（{purpose!r}）"


# ── B5：flip 后 voice 真源边界（M3 注册表收敛前的过渡契约）────────
def test_voice_single_source_is_research_profile_module():
    """M2-flip 后 orchestrator 是纯 re-export 外壳，不再持有 report_voice 副本；
    voice 表唯一真源为 research_profile 模块（M3 将随决策 8 并入 research_types）。"""
    from app.core import orchestrator
    assert not hasattr(orchestrator, "report_voice"), (
        "orchestrator 不得再持有 report_voice（旅游引擎已改用 research_types）"
    )
    assert callable(research_profile.report_voice)
    assert research_profile.REPORT_PROFILES is REPORT_PROFILES


if __name__ == "__main__":
    import sys
    raise SystemExit(pytest.main([__file__, "-q"]))