"""rough-cliff-vole · 视角注册表 / 质量分母 / 问卷闸门契约钉（VR-A 组 + VR-B 后端侧）。

守护契约：
  VR-A1 视角键三处自洽（PERSPECTIVE_SPECS ↔ SECTION_STRUCTURED ↔ 静态键集不含视角键）
  VR-A2 structured_keys_for：非视角卷逐值等于静态表；视角卷恰追加专属键
  VR-A3 schema_completeness 分母不变性（评审 P0-1 守卫：条件键不得漂移静态分母）
  VR-A4 show_if 规则自校验（悬空条件即红——引用题存在、equals ∈ 被引题选项）
  VR-A5 PERSPECTIVE_SPECS 10 视角全登记 + 模板形状
  VR-B2/B3/B4 必答闸门正反例 / 题序 golden / 脏输入防线
"""
import pytest

from app.core import orchestrator as O
from app.core import research_types as rt
from app.core.schemas import schema_completeness

_PERSP_SIDS = tuple(sid for sid in rt.SECTION_PLAN if sid.startswith("persp_"))


# ── VR-A5 注册表穷尽 ────────────────────────────────────────────

def test_all_perspective_sections_registered():
    """10 个视角章全部有契约条目（新增视角章不填表即红）。"""
    assert set(_PERSP_SIDS) == set(rt.PERSPECTIVE_SPECS)


def test_family_spec_shape():
    p = rt.PERSPECTIVE_SPECS["persp_family"]
    assert p["checklist_key"] == "family_checklist"
    assert len(p["checklist_columns"]) == 4
    assert all("{spot}" in t for t in p["spot_probe_tpls"]), "二查模板必须含景点占位"
    assert "child_age" in p["hard_constraints"]


def test_unconfigured_perspectives_are_inert():
    """非亲子视角本期 checklist/rules/packing 全 None → 专属键集为空（零波及谓词源）。"""
    for sid in _PERSP_SIDS:
        if sid == "persp_family":
            continue
        assert rt.perspective_structured_keys(sid) == ()


# ── VR-A1/A2 键集三处自洽 ───────────────────────────────────────

def test_perspective_keys_never_in_static_structured_keys():
    """视角键混进静态表 = 非视角卷分母漂移（评审 P0-1 的结构性防线）。"""
    for spec in rt.RESEARCH_TYPES.values():
        assert not set(rt.PERSP_STRUCTURED_KEYS) & set(spec["structured_keys"])


def test_perspective_keys_mounted_in_section_structured():
    """配置了专属键的视角章必须在 SECTION_STRUCTURED 挂章（不登记即孤儿数据）。"""
    for sid, p in rt.PERSPECTIVE_SPECS.items():
        owned = rt.perspective_structured_keys(sid)
        if owned:
            assert rt.SECTION_STRUCTURED.get(sid) == owned, f"{sid} 的键未挂章"


def test_structured_keys_for_non_perspective_equals_static():
    for rtype in rt.RESEARCH_TYPES:
        assert rt.structured_keys_for(rtype, "") == tuple(
            rt.type_spec(rtype)["structured_keys"])


def test_structured_keys_for_family_appends_owned_keys():
    base = tuple(rt.type_spec("guide")["structured_keys"])
    got = rt.structured_keys_for("guide", "persp_family")
    assert got == base + ("family_checklist", "persp_rules", "persp_packing")


def test_perspective_grouped_keys_registered_dest_rows():
    """视角块按组级 destination 分组 → 登记 DEST_KEYED_ROWS（组级主键安全；
    行级景点名绝不登记——被整表滤光即 calm-reef-pigeon P0-1 的同族事故）。"""
    paths = dict(rt.DEST_KEYED_ROWS)
    for k in ("structured.family_checklist", "structured.persp_rules",
              "structured.persp_packing"):
        assert paths.get(k) == "destination"
    assert not any("spot_name" in key for key in paths), "景点名不得作行主键登记"


# ── VR-A3 质量分母不变性 ────────────────────────────────────────

def _base_structured():
    return {"spot_ranking": [{"destination": "大理", "items": [{"name": "洱海"}]}]}


def test_completeness_denominator_stable_without_perspective():
    base = _base_structured()
    golden = schema_completeness(base, "guide")
    assert schema_completeness(base, "guide", "") == golden
    # 视角键混入载荷也不改变非视角卷得分（分母不认、内容不数）
    polluted = dict(base, family_checklist=[{"destination": "大理", "items": [{"spot_id": "x"}]}])
    assert schema_completeness(polluted, "guide") == golden


def test_completeness_family_denominator_grows():
    base = _base_structured()
    plain = schema_completeness(base, "guide")
    with_persp = schema_completeness(base, "guide", "persp_family")
    assert with_persp < plain, "亲子卷分母应含三视角键（未填充则得分下移）"
    filled = dict(base,
                  family_checklist=[{"destination": "大理", "items": [{"spot_id": "s1"}]}],
                  persp_rules=[{"destination": "大理", "items": [{"rule": "r"}]}],
                  persp_packing=[{"destination": "大理", "items": [{"item": "i"}]}])
    # 精确分数钉：guide 基础 7 键 + 视角 3 键 = 分母 10；填充 1+3 = 4 → 0.4
    assert schema_completeness(filled, "guide", "persp_family") == round(4 / 10, 3)
    assert round(plain, 3) == round(1 / 7, 3)


# ── VR-A4 show_if 自校验 ────────────────────────────────────────

@pytest.mark.parametrize("rtype", list(rt.RESEARCH_TYPES))
def test_show_if_rules_are_not_dangling(rtype):
    qs = rt.type_spec(rtype)["clarify"]
    by_id = {q["id"]: q for q in qs}
    for q in qs:
        cond = q.get("show_if") or {}
        if not cond:
            continue
        assert cond.get("qid") in by_id, f"{q['id']} 引用了不存在的题 {cond.get('qid')}"
        assert cond.get("equals") in by_id[cond["qid"]]["options"], \
            f"{q['id']} 的触发值不在 {cond['qid']} 选项里"


# ── VR-B2/B3/B4 问卷闸门与题序 ──────────────────────────────────

def test_missing_conditional_answers_matrix():
    m = rt.missing_conditional_answers
    assert m("guide", {"party": "情侣/夫妻"}) == []
    assert m("guide", {"party": "亲子家庭"}) == ["child_age"]
    assert m("guide", {"party": "亲子家庭", "child_age": "3-6 岁"}) == []
    assert m("guide", {"party": "亲子家庭", "child_age": "  "}) == ["child_age"]
    assert m("guide", {}) == []


def test_guide_question_order_child_age_adjacent_to_party():
    ids = [q["id"] for q in rt.type_spec("guide")["clarify"]]
    assert ids.index("child_age") == ids.index("party") + 1
    assert [i for i in ids if i != "child_age"] == [
        "days", "party", "budget_level", "travel_season", "origin", "focus", "extra"]


def test_visible_questions_filter_shares_gate_predicate():
    """前端可见集与后端闸门同一判据源（两处判据漂移=显隐与必答打架）。"""
    fam = [q["id"] for q in rt.visible_clarify_questions("guide", {"party": "亲子家庭"})]
    assert "child_age" in fam
    solo = [q["id"] for q in rt.visible_clarify_questions("guide", {"party": "独自旅行"})]
    assert "child_age" not in solo


def test_child_age_consumer_registered():
    cfg = rt.consumer_of("guide", "child_age")
    assert cfg["consumer"] == rt.CONSUMER_CONSTRAINTS
    assert rt.CONSUMER_CONSTRAINTS in rt.ALL_CONSUMERS


def test_submit_clarify_rejects_triggered_missing(monkeypatch):
    monkeypatch.setattr(O, "_task_research_type", lambda tid: "guide")
    saved = []
    monkeypatch.setattr(O.db, "update_task_clarify",
                        lambda tid, clar: saved.append(clar))
    with pytest.raises(O.ClarifyAnswerRequiredError):
        O.submit_clarify("t_gate", {"party": "亲子家庭", "destinations": ["大理"]})
    assert saved == [], "被拒的问卷绝不落库"
    O.submit_clarify("t_gate", {"party": "情侣/夫妻", "destinations": ["大理"]})
    assert len(saved) == 1, "未触发缺答必须放行"


def test_submit_clarify_family_with_age_persists(monkeypatch):
    monkeypatch.setattr(O, "_task_research_type", lambda tid: "guide")
    saved = {}
    monkeypatch.setattr(O.db, "update_task_clarify",
                        lambda tid, clar: saved.update(clar))
    O.submit_clarify("t_ok", {"party": "亲子家庭", "child_age": "3-6 岁"})
    assert saved["child_age"] == "3-6 岁"


def test_dirty_child_age_does_not_trigger_family_perspective():
    """VR-B4：视角解析只认 party 关键词——脏输入（情侣+娃龄）不得点亮亲子链路。"""
    assert rt.perspective_section("guide", "情侣/夫妻") != "persp_family"
    assert rt.perspective_section("guide", "亲子家庭") == "persp_family"
