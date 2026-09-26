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

from app.core.pipeline.research import engine as O
from app.core.pipeline.research import errors as rt_err
from app.core import research_types as rt
from app.core.schemas import schema_completeness

_PERSP_SIDS = tuple(sid for sid in rt.SECTION_PLAN if sid.startswith("persp_"))


# ── VR-A5 注册表穷尽 ────────────────────────────────────────────

def test_all_perspective_sections_registered():
    """10 个视角章全部有契约条目（新增视角章不填表即红）。"""
    assert set(_PERSP_SIDS) == set(rt.PERSPECTIVE_SPECS)


def test_family_spec_shape():
    p = rt.PERSPECTIVE_SPECS["persp_family"]
    assert p["checklist_key"] == "persp_checklist"
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
    assert got == base + ("persp_checklist", "persp_rules", "persp_packing")


def test_perspective_grouped_keys_registered_dest_rows():
    """视角块按组级 destination 分组 → 登记 DEST_KEYED_ROWS（组级主键安全；
    行级景点名绝不登记——被整表滤光即 calm-reef-pigeon P0-1 的同族事故）。"""
    paths = dict(rt.DEST_KEYED_ROWS)
    for k in ("structured.persp_checklist", "structured.persp_rules",
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
    polluted = dict(base, persp_checklist=[{"destination": "大理", "items": [{"spot_id": "x"}]}])
    assert schema_completeness(polluted, "guide") == golden


def test_completeness_family_denominator_grows():
    base = _base_structured()
    plain = schema_completeness(base, "guide")
    with_persp = schema_completeness(base, "guide", "persp_family")
    assert with_persp < plain, "亲子卷分母应含三视角键（未填充则得分下移）"
    filled = dict(base,
                  persp_checklist=[{"destination": "大理", "items": [{"spot_id": "s1"}]}],
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


# ── VR-B5 脏答案闸门（E1′：未触发条件题的残留值不得被任何出口读到）──

def test_drop_untriggered_removes_stale_child_age():
    """先答亲子再改情侣：娃龄残留必须被摘掉，否则情侣卷摘要会印「娃龄」。"""
    dirty = {"party": "情侣/夫妻", "child_age": "3-6 岁", "days": "1-2 天"}
    assert rt.drop_untriggered_conditional_answers("guide", dirty) == {
        "party": "情侣/夫妻", "days": "1-2 天"}


def test_drop_untriggered_keeps_triggered_answer():
    clean = {"party": "亲子家庭", "child_age": "3-6 岁"}
    assert rt.drop_untriggered_conditional_answers("guide", clean) == clean


def test_drop_untriggered_is_noop_when_no_conditional_answer():
    """未答条件题时不复制字典（避免给下游一个「看起来变了」的假信号）。"""
    base = {"party": "独自旅行", "days": "3-5 天"}
    assert rt.drop_untriggered_conditional_answers("guide", base) is base


def test_drop_untriggered_preserves_non_registry_and_meta_keys():
    """P0 防线：白名单式过滤会连带删掉 destinations，把目的地降级成 query 猜测。

    服务端实际下发题集 = 注册表 clarify 题 + _build_enhanced_questions 追加的
    scope/destinations；后者不在注册表里，任何"按注册表取交集"的写法都会吃掉它们。
    """
    from app.core.pipeline.research.planning import _checked_destinations
    dirty = {"party": "情侣/夫妻", "child_age": "3-6 岁",
             "destinations": ["大理"], "scope": "准确，继续",
             "_mode": "deep", "_type": "guide", "_model_override": "m-x",
             "_region": "云南"}
    out = rt.drop_untriggered_conditional_answers("guide", dirty)
    assert "child_age" not in out
    assert out["destinations"] == ["大理"] and out["scope"] == "准确，继续"
    assert {k: out[k] for k in out if k.startswith("_")} == {
        "_mode": "deep", "_type": "guide", "_model_override": "m-x", "_region": "云南"}
    assert _checked_destinations(out) == _checked_destinations(dirty), \
        "过滤前后目的地解析结果必须逐值相等（核查表行种子 primary_destination 依赖它）"


def test_pipeline_digest出口不再泄漏娃龄(monkeypatch):
    """端到端：脏答案进管线后，报告头摘要不含「娃龄」（v2.1 曾误判为"重渲染会复发"）。"""
    from app.core.pipeline.research.assemble import _answers_digest
    dirty = {"party": "情侣/夫妻", "child_age": "3-6 岁", "days": "1-2 天"}
    cleaned = rt.drop_untriggered_conditional_answers("guide", dirty)
    labels = [d["label"] for d in _answers_digest(cleaned, ["三亚"], "guide")]
    assert "娃龄" not in labels
    assert "人群" in labels and "天数" in labels


# ── VR-A6 装配判据与质量分母同源（P1-3）──────────────────────────

_SEED = [{"spot_id": "s1", "name": "洱海"}]


def test_assemblable_predicate_covers_all_negative_shapes():
    assert rt.perspective_assemblable("persp_family", _SEED) is True
    assert rt.perspective_assemblable("persp_family", []) is False, "空 seed 不可装配"
    assert rt.perspective_assemblable("persp_couple", _SEED) is False, "未配核查表"
    assert rt.perspective_assemblable("", _SEED) is False, "通用人群无视角"


def test_empty_seed_does_not_demand_perspective_keys_in_denominator():
    """空 seed 时分母必须退回静态键集——否则三键计入应产出却永远填不上。"""
    static = rt.type_spec("guide")["structured_keys"]
    assert rt.structured_keys_for("guide", "") == static
    # 分母入参与装配判据同源：不可装配 ⇒ 不计入
    sid = "persp_family" if rt.perspective_assemblable("persp_family", []) else ""
    assert rt.structured_keys_for("guide", sid) == static
    # 可装配 ⇒ 恰追加本行专属键（不牵连静态分母）
    sid_ok = "persp_family" if rt.perspective_assemblable("persp_family", _SEED) else ""
    assert rt.structured_keys_for("guide", sid_ok) == static + rt.SECTION_STRUCTURED["persp_family"]


# ── VR-B6 必答闸门以「实际下发题集」为准（Part C 前置死锁防线）────

def test_stale_served_set_does_not_demand_unseen_question():
    """旧快照里没有那道条件题 ⇒ 不得要求回答（否则用户被没见过的题卡死）。"""
    stale = [q for q in rt.type_spec("guide")["clarify"] if q["id"] != "child_age"]
    assert rt.missing_conditional_answers("guide", {"party": "亲子家庭"}) == ["child_age"], \
        "按注册表当前题集确实会要求娃龄（这正是死锁的来源）"
    assert rt.missing_conditional_answers("guide", {"party": "亲子家庭"}, stale) == [], \
        "按下发题集必须放行"


def test_served_set_still_demands_question_user_saw():
    """反向防线：题集里有且已触发，缺答照旧必红——放宽的是来源，不是判据。"""
    served = list(rt.type_spec("guide")["clarify"])
    assert rt.missing_conditional_answers("guide", {"party": "亲子家庭"}, served) == ["child_age"]
    assert rt.missing_conditional_answers(
        "guide", {"party": "亲子家庭", "child_age": "3-6 岁"}, served) == []


def test_submit_clarify_unblocks_task_with_pre_existing_questionnaire(monkeypatch):
    """端到端：任务问卷是加题前的快照时，答完 party 能正常提交。"""
    monkeypatch.setattr(O, "_task_research_type", lambda tid: "guide")
    monkeypatch.setattr(O.db, "get_task", lambda tid: {"clarifications": {}})
    monkeypatch.setattr(O.db, "update_task_clarify", lambda tid, clar: None)
    stale = {"questions": [q for q in rt.type_spec("guide")["clarify"] if q["id"] != "child_age"],
             "complete": True}
    monkeypatch.setattr(O.db, "get_clarify_questions", lambda tid: (stale, True))
    O.submit_clarify("t_stale", {"party": "亲子家庭", "days": "1-2 天"})

    fresh = {"questions": list(rt.type_spec("guide")["clarify"]), "complete": True}
    monkeypatch.setattr(O.db, "get_clarify_questions", lambda tid: (fresh, True))
    with pytest.raises(rt_err.ClarifyAnswerRequiredError):
        O.submit_clarify("t_fresh", {"party": "亲子家庭", "days": "1-2 天"})
