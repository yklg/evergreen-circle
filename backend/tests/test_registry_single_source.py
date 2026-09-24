"""注册表单一真相源守卫（融合决策 8 / 实施计划 §18·§25）。

M3 完成后，旅游调研的「类型 → 章节集」只许由 `research_types.sections_for()`
给出（`SECTION_PLAN` 是 sid→标题字典，不是章节清单）。本守卫把三类回潮钉死：

1. **旧体裁模块不得复活**：简版时代的 `app.core.research_profile.py`
   （REPORT_PROFILES + report_voice，内含 guide_*/assess_* 旧章节清单）已删除——
   生产零消费、章节 id 与新注册表完全不兼容；任何重新引入该模块的提交即红。
2. **旧章节词汇不得回流**：guide_overview/guide_voice/assess_access 等 13 个
   简版 sid 不得再出现在 app/ 任何源码里（字符串/注解也算——它们没有合法的新身份）。
3. **注册表外不得再出现有序章节清单**：除 research_types.py 外，任何字面量列表
   含 ≥3 个在册 sid 即视为「第二份章节清单」。合法的横切分组（assemble 的
   conclusion/risk 插入锚点、charts_build 的图表归属对、modes.CORE_SECTIONS
   无序集合）要么 ≤2 项、要么是 tuple/set 而非有序 list，均不触线。

运行时的正向不变量（实际生成章节 == sections_for）由
test_two_type_pipeline.test_report_sections_and_type_match_registry 钉住，
与本静态守卫合起来构成「唯一来源 + 产出一致」的完整闭环。
"""
import ast
import importlib.util
from pathlib import Path

import pytest

from app.core import research_types as RT

_BACKEND = Path(__file__).resolve().parents[1]
_APP = _BACKEND / "app"

# research_profile 退役前的 13 个简版章节 sid（guide 档 8 + assess 档 7，去公共 summary/conclusion）
_LEGACY_SECTION_TOKENS = frozenset({
    "guide_overview", "guide_transport", "guide_food_stay", "guide_route",
    "guide_safe", "guide_budget", "guide_voice",
    "assess_access", "assess_amenity", "assess_price", "assess_safety",
    "assess_voice", "assess_conclusion",
})

# 有序章节清单的最小规模阈值：注册表外 list 字面量含在册 sid 达到该数即判违例
_SECOND_LIST_THRESHOLD = 3


def test_research_profile_module_is_retired():
    """app.core.research_profile 已随决策 8 删除（persona/voice 由 research_types 承载，
    章节集由 sections_for 给出）；重新引入该模块即红。"""
    assert importlib.util.find_spec("app.core.research_profile") is None, (
        "research_profile 已退役：需要体裁语查 research_types.type_spec，"
        "需要章节集查 sections_for()，不得复活第二份体裁/章节表"
    )


@pytest.mark.parametrize("token", sorted(_LEGACY_SECTION_TOKENS))
def test_legacy_section_vocabulary_never_returns(token):
    """简版 sid 不得在任何生产源码里出现（含字符串字面量/注释外的一切 token）。"""
    hits = []
    for p in _APP.rglob("*.py"):
        if token in p.read_text(encoding="utf-8"):
            hits.append(p.relative_to(_BACKEND).as_posix())
    assert not hits, f"旧章节词汇 {token!r} 回流：{hits}"


def _list_literals_with_section_keys():
    """产出 (文件, 行号, 重叠 sid 列表)：注册表外有序 list 里的在册章节 id。"""
    keys = set(RT.SECTION_PLAN)
    out = []
    for p in sorted(_APP.rglob("*.py")):
        if p.name == "research_types.py":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.List):
                continue
            overlap = [e.value for e in node.elts
                       if isinstance(e, ast.Constant) and isinstance(e.value, str)
                       and e.value in keys]
            if len(overlap) >= _SECOND_LIST_THRESHOLD:
                out.append((p.relative_to(_BACKEND).as_posix(), node.lineno, overlap))
    return out


def test_no_ordered_chapter_list_outside_registry():
    """research_types 之外不得出现 ≥3 个在册 sid 的有序列表（第二份章节清单）。

    合法的横切分组（插入锚点/图表归属 ≤2 项；CORE_SECTIONS 为无序 frozenset）
    均不触线；若将来确需新的横切分组，用 tuple/set 并在此处登记理由。
    """
    found = _list_literals_with_section_keys()
    assert not found, (
        "发现注册表外的有序章节清单（章节集只能由 sections_for() 派生）：\n  "
        + "\n  ".join(f"{rel}:{ln} -> {ov}" for rel, ln, ov in found)
    )
