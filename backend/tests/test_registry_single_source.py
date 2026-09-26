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


# ──  视角行穷尽覆盖（v4.3 ③：B1 填行的前置门）────────────────────
# 症状（真机 r_69d064ad）：非亲子视角「没有针对性建议」，根因之一是视角能力散在**多张表**里，
# 漏填任何一张都不报错。评审要求把「一张表的清单」从手写改成扫描：手写清单本身就是一种
# 手抄 —— 新增/改名的表不会自动进清单，守卫于是安静地少守一张表。

def _sid_keyed_tables():
    """扫描（不列名单）research_types 里**以视角 sid 为主键**的模块顶层字典常量。"""
    sids = set(RT.PERSPECTIVE_SPECS)
    out = {}
    for name, val in vars(RT).items():
        # 只跳 dunder：私有名不是豁免理由，「以 sid 为键」才是判据
        if name.startswith("__") or not isinstance(val, dict) or not val:
            continue
        if not isinstance(next(iter(val.keys())), str):
            continue
        if sids & {str(k) for k in val}:
            out[name] = val
    return out


def test_every_sid_keyed_table_covers_every_perspective():
    """任何一张以视角 sid 为键的表都必须覆盖全部 sid —— 半填一行即红。

    两条防空过断言不是冗余：`PERSPECTIVE_SPECS` 空 ⇒ 判据退化为恒真；一张表都扫不到 ⇒
    守卫在没人察觉的情况下变成空转（表被改名/删除就是这个形状）。
    """
    sids = set(RT.PERSPECTIVE_SPECS)
    assert sids, "视角注册表为空 ⇒ 本守卫退化成恒真，先确认是不是改名了"
    tables = _sid_keyed_tables()
    assert tables, "一张以 sid 为键的表都没扫到 ⇒ 守卫空转（改名或删表会静默失效）"
    holes = {name: sorted(sids - {str(k) for k in val}) for name, val in tables.items()}
    holes = {n: miss for n, miss in holes.items() if miss}
    assert not holes, (
        "视角行只填了一部分表（漏填的那张表对该视角静默缺能力）：\n  "
        + "\n  ".join(f"{n} 缺 {m}" for n, m in sorted(holes.items()))
    )


def test_perspective_ownership_is_exactly_one_type_per_sid():
    """每个视角 sid 恰好被**一个**调研类型的 perspectives 认领，且认领键有词。

    0 个认领 ⇒ 该视角填了表也永远进不了任何报告（孤儿数据）；2 个 ⇒ 同一次答案在两型里
    会选到不同章，而 `structured_keys_for` 追加的键集是按 rtype 查的 ⇒ 章与分母不同源。
    """
    claimed: dict = {}
    for rtype, spec in RT.RESEARCH_TYPES.items():
        for key, p in (spec.get("perspectives") or {}).items():
            claimed.setdefault(p["section"], []).append((rtype, key, p))
    assert claimed, "没有任何类型认领任何视角 ⇒ 本守卫空转"
    orphans = sorted(set(RT.PERSPECTIVE_SPECS) - set(claimed))
    dupes = {sid: owners for sid, owners in claimed.items() if len(owners) > 1}
    unknown = sorted(set(claimed) - set(RT.PERSPECTIVE_SPECS))
    no_kw = sorted(sid for sid, owners in claimed.items()
                   if not any(o[2].get("keywords") for o in owners))
    assert not (orphans or dupes or unknown or no_kw), (
        f"视角归属破了：无主 {orphans} · 多主 {sorted(dupes)} · "
        f"未注册 {unknown} · 无关键词 {no_kw}")


def test_guard_fires_on_a_half_filled_perspective_row(monkeypatch):
    """真坏样本：新视角只填注册表、没填标题表 ⇒ 守卫必须点名那张表（否则它是恒绿假护栏）。"""
    monkeypatch.setitem(RT.PERSPECTIVE_SPECS, "persp_synthetic", {
        "angle_tpls": (), "spot_probe_tpls": (), "checklist_key": None,
        "checklist_columns": (), "rules_key": None, "packing_key": None,
        "hard_constraints": ()})
    sids = set(RT.PERSPECTIVE_SPECS)
    assert "persp_synthetic" in sids
    tables = _sid_keyed_tables()
    missing = {n for n, v in tables.items() if "persp_synthetic" not in {str(k) for k in v}}
    assert "SECTION_PLAN" in missing, (
        f"坏样本没被判出（漏填的表不在射程内 ⇒ 守卫空转）：{sorted(missing)}")
    # 归属侧同样要红：新 sid 没有任何类型认领
    assert "persp_synthetic" in (set(RT.PERSPECTIVE_SPECS) - {
        p["section"] for s in RT.RESEARCH_TYPES.values()
        for p in (s.get("perspectives") or {}).values()})


def test_perspective_keyword_priority_order_is_pinned():
    """视角键的**声明序**就是关键词优先级，此处钉死（派生化让它从字面序变成派生序）。

    `perspective_key()` 取首个命中 ⇒ 顺序是有语义的产品行为（「带长辈去拍照」归摄影还是
    长辈取决于谁先被扫到）。收敛前顺序写在 RESEARCH_TYPES 字面量里、肉眼可见；收敛后它
    来自 PERSPECTIVE_SPECS 的行序，挪一行就等于改优先级 —— 所以必须显式钉住，
    让「调换两个视角」成为一次看得见意图的改动，而不是 diff 里的一行搬家。
    """
    assert list(RT.RESEARCH_TYPES["guide"]["perspectives"]) == \
        ["family", "couple", "solo", "senior", "photo"]
    assert list(RT.RESEARCH_TYPES["assessment"]["perspectives"]) == \
        ["live", "invest", "study", "retire", "remote"]
    # 认领同序 ⇒ 派生没有悄悄重排（等值断言判不出顺序，这里单独钉）
    for rtype, order in (("guide", ["family", "couple", "solo", "senior", "photo"]),
                         ("assessment", ["live", "invest", "study", "retire", "remote"])):
        rows = [p["owner"][1] for p in RT.PERSPECTIVE_SPECS.values()
                if p["owner"][0] == rtype]
        assert rows == order, f"{rtype} 的视角行序与认领序不一致：{rows}"


def test_converged_perspective_fields_stay_the_single_definition():
    """派生重绑后，SECTION_* 三张表里的视角条目**只能来自**那一行（防有人把字面量抄回去）。

    双定义本身是本轮要消除的根因；改回去不会让任何行为测试变红（值一样），所以只能靠
    「从 PERSPECTIVE_SPECS 反构造一份，与现表比」来钉。
    """
    for sid, p in RT.PERSPECTIVE_SPECS.items():
        assert RT.SECTION_PLAN[sid] == p["title"]
        assert RT.SECTION_PROMPTS[sid] == p["prompt"]
        assert RT.SECTION_FIELDS[sid] == p["fields"]
    assert set(RT.SECTION_PLAN) - set(RT.PERSPECTIVE_SPECS) < set(RT.SECTION_PLAN)
