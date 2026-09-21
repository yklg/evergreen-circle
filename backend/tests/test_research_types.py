"""调研类型注册表（research_types.py）泛型守卫 —— B1。

守护的是「类型契约 = 单一真相源」这一不变量：注册表与章节/字段/图表/平台/结构化键
之间的表间一致性。全部断言**泛型遍历注册表**，新增第 3 个调研类型自动被同一批断言守护，
不需要改测试（R1 单一真相源一致性；种子：test_config_contract.py / test_api_mirror_guard.py）。

运行：backend/ 下 `pytest tests/test_research_types.py -q`
"""
import ast
from pathlib import Path

import pytest

from app.core import platforms
from app.core import research_types as rt

_TYPES = list(rt.RESEARCH_TYPES)
_MODULE_PATH = Path(rt.__file__)

# 分析契约键的合法取值域（guard 白名单：改名/新增必须同步改这里，防静默漂移）
_ANALYSIS_KEYS_ALLOWED = {
    "comparison", "livability", "budget", "cost", "season", "safety_index",
    "share_estimate", "trends", "contradictions",
}


# ── ① 章节集 ⊆ SECTION_PLAN，且 quick ⊆ deep ⊆ expert ────────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_sections_subset_of_plan_and_monotonic(rtype):
    spec = rt.RESEARCH_TYPES[rtype]
    assert set(spec["sections"]) == set(rt.MODES), "三档模式必须齐全"
    for mode, ids in spec["sections"].items():
        assert ids, f"{rtype}.{mode} 章节集不能为空"
        assert len(set(ids)) == len(ids), f"{rtype}.{mode} 章节 id 不能重复"
        unknown = [s for s in ids if s not in rt.SECTION_PLAN]
        assert not unknown, f"{rtype}.{mode} 含未注册章节 {unknown}（缺标题/缺 prompt）"
    for low, high in (("quick", "deep"), ("deep", "expert")):
        assert set(spec["sections"][low]) <= set(spec["sections"][high]), \
            f"{rtype}: {low} 章节集必须 ⊆ {high}"


@pytest.mark.parametrize("rtype", _TYPES)
def test_section_prompts_cover_all_sections(rtype):
    """每个被引用的章节都必须有撰写 prompt（否则静默降级为兜底文案）。"""
    for mode, ids in rt.RESEARCH_TYPES[rtype]["sections"].items():
        for sid in ids:
            assert sid in rt.SECTION_PROMPTS, f"{rtype}.{mode}: 章节 {sid} 缺 SECTION_PROMPTS"


# ── ② SECTION_FIELDS ⊇ 全部章节；未知 id 回落 ("overview",) ──────
def test_section_fields_covers_every_section():
    assert set(rt.SECTION_FIELDS) == set(rt.SECTION_PLAN), \
        "SECTION_FIELDS 与 SECTION_PLAN 必须一一对应（防新增章节漏配字段）"
    for sid, (fields, charts) in rt.SECTION_FIELDS.items():
        assert isinstance(fields, tuple) and isinstance(charts, tuple)
        assert all(isinstance(f, str) for f in fields)
        for ct in charts:
            assert ct in rt.CHART_TYPES, f"章节 {sid} 引用了未声明图表 {ct}"


def test_section_fields_unknown_id_falls_back():
    assert rt.section_fields("not_a_section") == (("overview",), ())
    assert rt.field_keywords("not_a_field") == ()


def test_claim_fields_cover_section_fields():
    """每类型 claim 字段全集必须覆盖其章节用到的字段（否则检索不到相关论点）。"""
    for rtype in _TYPES:
        allowed = set(rt.claim_fields_for(rtype))
        spec = rt.RESEARCH_TYPES[rtype]
        for mode, ids in spec["sections"].items():
            for sid in ids:
                fields, _ = rt.section_fields(sid)
                assert set(fields) <= allowed, \
                    f"{rtype}.{mode}: 章节 {sid} 字段 {set(fields) - allowed} 不在 claim 白名单"


# ── ③ 结构化键：每类型恰好 3 个且 ⊆ 白名单 ──────────────────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_structured_keys_shape(rtype):
    keys = rt.RESEARCH_TYPES[rtype]["structured_keys"]
    assert len(keys) == 3, "schema_completeness 的分母为 3，键数必须恒为 3"
    assert len(set(keys)) == 3
    assert set(keys) <= set(rt.STRUCTURED_FIELDS)


# ── ④ 分析键取值合法，且废弃键已清除 ───────────────────────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_analysis_keys_valid(rtype):
    spec = rt.RESEARCH_TYPES[rtype]
    keys = spec["analysis_keys"]
    assert keys and len(set(keys)) == len(keys)
    assert set(keys) <= _ANALYSIS_KEYS_ALLOWED, f"未知分析键 {set(keys) - _ANALYSIS_KEYS_ALLOWED}"
    assert spec["radar_key"] in keys, "雷达图数据键必须在该类型的 analysis_keys 内"
    assert spec["cost_bar"]["key"] in keys, "成本柱图数据键必须在该类型的 analysis_keys 内"
    assert "share_estimate" in keys and "trends" in keys and "contradictions" in keys


@pytest.mark.parametrize("rtype", _TYPES)
def test_deprecated_fields_absent(rtype):
    """旧契约字段（feature_tree/pricing_model/user_persona/swot）不得在任何类型出现。"""
    spec = rt.RESEARCH_TYPES[rtype]
    pool = set(rt.claim_fields_for(rtype)) | set(spec["analysis_keys"]) | set(spec["structured_keys"])
    assert not (pool & set(rt.DEPRECATED_CLAIM_FIELDS))
    assert "market_share" not in spec["analysis_keys"]
    assert "five_forces" not in spec["analysis_keys"]


# ── ⑤ 图表集合法且与全局白名单等价 ────────────────────────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_charts_subset_and_unique(rtype):
    charts = rt.RESEARCH_TYPES[rtype]["charts"]
    assert charts and len(set(charts)) == len(charts)
    assert set(charts) <= set(rt.CHART_TYPES)
    assert "sentiment_donut" in charts and "platform_bar" in charts, "舆情两图是每类型必备"


def test_chart_types_whitelist_is_exactly_used():
    used = set().union(*(set(rt.RESEARCH_TYPES[t]["charts"]) for t in _TYPES))
    assert set(rt.CHART_TYPES) == used, \
        "CHART_TYPES 必须恰好等于各类型图表集的并集（无死条目、无漏声明）"


@pytest.mark.parametrize("rtype", _TYPES)
def test_section_chart_slots_within_type_charts(rtype):
    """章节挂载的图表类型必须是该类型允许产出的（否则挂了永远生不出的图）。"""
    allowed = set(rt.RESEARCH_TYPES[rtype]["charts"])
    for mode, ids in rt.RESEARCH_TYPES[rtype]["sections"].items():
        for sid in ids:
            _, charts = rt.section_fields(sid)
            assert set(charts) <= allowed, f"{rtype}.{mode}: 章节 {sid} 挂了类型外的图 {set(charts) - allowed}"


# ── ⑥ 舆情平台白名单 ⊆ platforms.PLATFORMS，且有序去重 ──────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_sentiment_platforms_subset_of_registry(rtype):
    plats = rt.RESEARCH_TYPES[rtype]["sentiment_platforms"]
    assert plats, "舆情平台白名单不能为空（否则该类型不采集口碑）"
    assert len(set(plats)) == len(plats), "白名单不能重复"
    unknown = [p for p in plats if p not in platforms.PLATFORMS]
    assert not unknown, f"{rtype} 引用了未注册平台 {unknown}"


@pytest.mark.parametrize("rtype", _TYPES)
def test_sentiment_angles_are_templates(rtype):
    angles = rt.RESEARCH_TYPES[rtype]["sentiment_angles"]
    assert angles and len(set(angles)) == len(angles)
    assert all("{d}" in a for a in angles), "舆情角度模板必须含 {d} 占位符"


# ── ⑦ 未知类型一律回落默认类型 ────────────────────────────────
@pytest.mark.parametrize("bad", ["", None, "nope", "GUIDE ", "ASSESSMENT-X"])
def test_unknown_type_falls_back_to_default(bad):
    assert rt.type_spec(bad) is rt.RESEARCH_TYPES[rt.DEFAULT_RESEARCH_TYPE]
    assert rt.sections_for(bad, "deep") == rt.sections_for(rt.DEFAULT_RESEARCH_TYPE, "deep")


def test_type_key_normalizes_known_and_unknown():
    assert rt.type_key(" Assessment ") == "assessment"
    assert rt.type_key("nope") == rt.DEFAULT_RESEARCH_TYPE
    assert rt.type_key(None) == rt.DEFAULT_RESEARCH_TYPE


def test_unknown_mode_falls_back_to_default_mode():
    assert rt.sections_for("guide", "hyper") == rt.sections_for("guide", rt.DEFAULT_MODE)


# ── ⑧ 叶子模块：禁止 import app.core.*（防再造循环依赖）──────────
def test_leaf_module_imports_no_app_packages():
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.split(".")[0] == "app"]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] == "app" or node.level:
                offenders.append(mod or "<relative>")
    assert not offenders, f"research_types.py 必须保持为叶子模块，发现 app 内导入：{offenders}"


# ── 视角章节：按类型解析 + 插在 conclusion 之前 ─────────────────
@pytest.mark.parametrize("rtype,raw,expect", [
    ("guide", "亲子家庭", "persp_family"),
    ("guide", "带长辈", "persp_senior"),
    ("guide", "摄影采风", "persp_photo"),
    ("guide", "朋友结伴", ""),
    ("guide", "通用/综合", ""),
    ("assessment", "置业投资", "persp_invest"),
    ("assessment", "养老避寒", "persp_retire"),
    ("assessment", "数字游民", "persp_remote"),
    ("assessment", "仅作横向对比", ""),
])
def test_perspective_section_resolution(rtype, raw, expect):
    assert rt.perspective_section(rtype, raw) == expect


def test_perspective_sections_are_registered_and_type_scoped():
    guide_sections = {p["section"] for p in rt.RESEARCH_TYPES["guide"]["perspectives"].values()}
    assess_sections = {p["section"] for p in rt.RESEARCH_TYPES["assessment"]["perspectives"].values()}
    assert not (guide_sections & assess_sections), "两类型的视角章节不得重叠"
    for sid in guide_sections | assess_sections:
        assert sid in rt.SECTION_PLAN and sid in rt.SECTION_PROMPTS and sid in rt.SECTION_FIELDS


def test_perspective_inserted_before_conclusion():
    ids = rt.sections_for("guide", "expert", "亲子家庭")
    assert "persp_family" in ids
    assert ids.index("persp_family") < ids.index("conclusion")
    base = rt.sections_for("guide", "expert")
    assert ids == base[:base.index("conclusion")] + ["persp_family"] + base[base.index("conclusion"):]
    assert rt.sections_for("guide", "expert", "朋友结伴") == base


def test_perspective_source_points_to_real_clarify_question():
    for rtype in _TYPES:
        spec = rt.RESEARCH_TYPES[rtype]
        ids = {q["id"] for q in spec["clarify"]}
        assert spec["perspective_source"][0] in ids, \
            f"{rtype} 视角取值键 {spec['perspective_source'][0]} 不在澄清题目里"


# ── 编号：只给白名单内、且实际出现的章节，按白名单顺序 ─────────────
@pytest.mark.parametrize("rtype", _TYPES)
def test_numbered_titles_only_whitelist_and_sequential(rtype):
    spec = rt.RESEARCH_TYPES[rtype]
    present = [s for s in rt.sections_for(rtype, "expert") if s != "summary"]
    titles = rt.numbered_titles(present, rtype)
    whitelist = [s for s in spec["numbered"] if s in set(present)]
    assert list(titles) == whitelist, "编号顺序必须与白名单一致（而非报告物理顺序）"
    for i, sid in enumerate(whitelist):
        assert titles[sid] == f"{rt._CN_NUM[i]}、{rt.SECTION_PLAN[sid]}"
    # 白名单外的章节不得带序号
    for sid in ("summary", "conclusion", "risk", "contrarian", "verdict"):
        if sid in titles:
            assert sid in spec["numbered"]


def test_numbered_titles_quick_mode_still_sequential():
    """快速模式章节更少 → 序号按实际出现的白名单连续，不留空号。"""
    titles = rt.numbered_titles(rt.sections_for("guide", "quick"), "guide")
    assert list(titles.values()) == [
        "一、交通与抵达", "二、住宿区域与选型", "三、逐日路线安排", "四、预算拆解",
    ]


# ── API 载荷 / 澄清问卷形状 / 报告标题 ─────────────────────────
def test_research_type_options_matches_registry():
    opts = rt.research_type_options()
    assert [o["key"] for o in opts] == _TYPES
    for o in opts:
        spec = rt.RESEARCH_TYPES[o["key"]]
        assert o["label"] == spec["label"] and o["subtitle"] == spec["subtitle"]
        assert o["label"] and o["subtitle"]


@pytest.mark.parametrize("rtype", _TYPES)
def test_clarify_question_shape(rtype):
    qs = rt.RESEARCH_TYPES[rtype]["clarify"]
    assert len(qs) >= 5
    ids = [q["id"] for q in qs]
    assert len(set(ids)) == len(ids)
    for q in qs:
        assert q["id"] and q["question"]
        assert q["type"] in ("single", "multi", "text")
        if q["type"] == "text":
            assert q["options"] == []
        else:
            assert len(q["options"]) >= 2
            assert len(set(q["options"])) == len(q["options"])


def test_report_title_uses_type_suffix():
    assert rt.report_title(["大理", "丽江"], "guide") == "大理、丽江 旅游攻略报告"
    assert rt.report_title(["成都", "杭州"], "assessment") == "成都、杭州 宜居评估报告"
    assert rt.report_title([], "guide") == "目的地 旅游攻略报告"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
