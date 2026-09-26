"""rough-cliff-vole · 视角注册表 / 质量分母 / 问卷闸门契约钉（VR-A 组 + VR-B 后端侧）。

守护契约：
  VR-A1 视角键三处自洽（PERSPECTIVE_SPECS ↔ SECTION_STRUCTURED ↔ 静态键集不含视角键）
  VR-A2 structured_keys_for：非视角卷逐值等于静态表；视角卷恰追加专属键
  VR-A3 schema_completeness 分母不变性（评审 P0-1 守卫：条件键不得漂移静态分母）
  VR-A4 show_if 规则自校验（悬空条件即红——引用题存在、equals ∈ 被引题选项）
  VR-A5 PERSPECTIVE_SPECS 10 视角全登记 + 模板形状
  VR-B2/B3/B4 必答闸门正反例 / 题序 golden / 脏输入防线
"""
import string

import pytest

from app.core.pipeline.research import engine as O
from app.core.pipeline.research import errors as rt_err
from app.core import research_types as rt
from app.core.schemas import schema_completeness

_PERSP_SIDS = tuple(sid for sid in rt.SECTION_PLAN if sid.startswith("persp_"))
# 配置态按注册表派生（不写死 sid）：B1 填一行，该 sid 自动从惰性侧移到正向侧。
_CONFIGURED = tuple(s for s in _PERSP_SIDS if rt.perspective_structured_keys(s))
_UNCONFIGURED = tuple(s for s in _PERSP_SIDS if not rt.perspective_structured_keys(s))
# 视角章 → 归属调研类型（从两个类型的 perspectives 表反查，不另抄一份清单）
_OWNER = {p["section"]: t for t in rt.RESEARCH_TYPES
          for p in rt.type_spec(t)["perspectives"].values()}


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
    """未配置视角：专属键集为空 → 挂章/分行/分母三处零波及。

    原实现写的是「除 persp_family 外全 None」——B1 填一行情侣就整体失效，
    且它把「本期没填」误当成契约。这里改成按注册表派生配置态/未配置态。
    """
    for sid in _UNCONFIGURED:
        assert rt.perspective_structured_keys(sid) == ()
        assert rt.SECTION_STRUCTURED[sid] == ()
        for rtype in rt.RESEARCH_TYPES:
            assert rt.structured_keys_for(rtype, sid) == tuple(
                rt.type_spec(rtype)["structured_keys"]), f"{sid} 漂移了 {rtype} 分母"


def test_configured_split_is_non_degenerate():
    """两侧都非空，否则上面的惰性断言与下面的正向断言各自空过。"""
    assert set(_CONFIGURED) | set(_UNCONFIGURED) == set(_PERSP_SIDS)
    assert _CONFIGURED and _UNCONFIGURED


def test_inertness_comes_from_the_predicate_not_from_nobody_filling_a_row(monkeypatch):
    """合成一个空行，证明「惰性」是判据给的，不是恰好九行都没填出来的巧合。"""
    monkeypatch.setitem(rt.PERSPECTIVE_SPECS, "persp_zzz_synthetic", {
        "angle_tpls": (), "spot_probe_tpls": (), "checklist_key": None,
        "checklist_columns": (), "rules_key": None, "packing_key": None,
        "hard_constraints": ()})
    sid = "persp_zzz_synthetic"
    assert rt.perspective_structured_keys(sid) == ()
    assert rt.perspective_assemblable(sid, [{"spot_id": "s"}]) is False
    assert rt.data_grid_sections_for("guide", ["spots", sid]) == ("spots",)


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
    """每个已展开的群体追问都必答；未展开的（含无追问的选项）一律放行。"""
    m = rt.missing_conditional_answers
    assert m("guide", {"party": "亲子家庭"}) == ["child_age"]
    assert m("guide", {"party": "情侣/夫妻"}) == ["couple_trip"]
    assert m("guide", {"party": "独自旅行"}) == ["solo_priority"]
    assert m("guide", {"party": "摄影采风"}) == ["photo_focus"]
    assert m("guide", {"party": "带长辈"}) == ["senior_mobility"]
    # 「朋友结伴」无对应视角章 ⇒ 无追问，选它不该被任何条件题卡住
    assert m("guide", {"party": "朋友结伴"}) == []
    # 已答 → 放行；空白值 → 仍算缺
    assert m("guide", {"party": "亲子家庭", "child_age": "3-6 岁"}) == []
    assert m("guide", {"party": "亲子家庭", "child_age": "  "}) == ["child_age"]
    assert m("guide", {}) == []


def test_guide_conditional_questions_follow_their_trigger():
    """结构不变量：每道条件题都紧跟其触发题、且同触发的多题连续成块。

    原断言把「非条件题的 id 全集」写死在测试里，加一道群体追问就必红——
    那是把顺序细节当契约，逼后来人改测试而不是改设计。这里改钉真正的规则。
    """
    qs = rt.type_spec("guide")["clarify"]
    ids = [q["id"] for q in qs]
    by_trigger: dict = {}
    for q in qs:
        cond = q.get("show_if") or {}
        if cond:
            by_trigger.setdefault(str(cond["qid"]), []).append(str(q["id"]))
    assert by_trigger, "guide 问卷应至少有一道条件题（否则本断言空过）"
    for trig, group in by_trigger.items():
        start = ids.index(trig) + 1
        assert ids[start:start + len(group)] == group, \
            f"{trig} 的条件题必须紧接其后连续排列，实际 {ids}"


def test_guide_unconditional_question_order_golden():
    """非条件题的相对顺序是产品决策（先易后难、人群题在预算题前），钉住防漂移。"""
    qs = rt.type_spec("guide")["clarify"]
    base = [q["id"] for q in qs if not q.get("show_if")]
    assert base == ["days", "party", "budget_level", "travel_season", "origin",
                    "focus", "extra"]


def test_every_party_option_has_at_most_one_conditional_question():
    """一个人群选项只展开一道追问——多选人群不该被连环追问。"""
    qs = rt.type_spec("guide")["clarify"]
    party = next(q for q in qs if q["id"] == "party")
    gated: dict = {}
    for q in qs:
        cond = q.get("show_if") or {}
        if cond.get("qid") == "party":
            gated.setdefault(str(cond["equals"]), []).append(str(q["id"]))
    for option, ids in gated.items():
        assert len(ids) == 1, f"「{option}」展开了 {len(ids)} 道追问：{ids}"
    # 6 个选项里 5 个有专属追问，「朋友结伴」刻意保持通用（无对应视角章）
    assert set(gated) == {"亲子家庭", "情侣/夫妻", "独自旅行", "摄影采风", "带长辈"}


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
    monkeypatch.setattr(O.db, "get_clarify_questions", lambda tid: (None, False))
    saved = []
    monkeypatch.setattr(O.db, "update_task_clarify",
                        lambda tid, clar: saved.append(clar))
    with pytest.raises(O.ClarifyAnswerRequiredError):
        O.submit_clarify("t_gate", {"party": "亲子家庭", "destinations": ["大理"]})
    assert saved == [], "被拒的问卷绝不落库"
    # 群体追问已展开却没答 → 同样拒（情侣不再是"零追问"选项）
    with pytest.raises(O.ClarifyAnswerRequiredError):
        O.submit_clarify("t_gate", {"party": "情侣/夫妻", "destinations": ["大理"]})
    assert saved == [], "第二轮被拒同样不落库"
    # 答了就放行
    O.submit_clarify("t_gate", {"party": "情侣/夫妻", "couple_trip": "蜜月/纪念日",
                                "destinations": ["大理"]})
    assert len(saved) == 1
    # 无追问的选项不受任何条件题阻挡
    O.submit_clarify("t_gate", {"party": "朋友结伴", "destinations": ["大理"]})
    assert len(saved) == 2, "未触发缺答必须放行"


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
    assert rt.perspective_assemblable("", _SEED) is False, "通用人群无视角"
    # 「未配核查表」的反面样本按**判据**挑，不写死视角 id：B1 把情侣填上之后，
    # 原先拿 persp_couple 当"未配置"的用例会误判成判据坏了（实测就这么红过一次）。
    unconfigured = [sid for sid, p in rt.PERSPECTIVE_SPECS.items()
                    if not p.get("checklist_key")]
    assert unconfigured, (
        "已没有任何未配核查表的视角 ⇒ 这条负判据无样本可测，请改判或显式删除本断言")
    for sid in unconfigured:
        assert rt.perspective_assemblable(sid, _SEED) is False, f"{sid} 未配核查表却判可装配"


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


# ── VR-A8 反向消费契约：登记成 constraints 的题，必须有视角行认领 ────────
def test_every_constraints_question_is_claimed_by_a_perspective_row():
    """登记进 `CLARIFY_CONSUMERS` 标为 constraints 的题，必须出现在某一行 hard_constraints 里。

    D1 只查「声明的题真实存在」（正向），这条查反向：Part C 加了 4 道群体专属追问并登记为
    constraints 消费者，却没人把它们写进视角行 ⇒ `perspective.py` 的
    `constraints = "；".join(q for q in hard_q ...)` 永远读不到它们 ——
    「问了不听」的装饰题以**新形态**复发，而当时两道门都是绿的。

    为什么这道门必须存在而不是靠人记：题面、CLARIFY_CONSUMERS、视角行三处分别写在三个
    地方，中间没有任何引用把它们拴在一起；唯一的耦合是「运行时读 hard_constraints」，
    而漏声明的后果恰好是**什么都不发生**（不报错、不降级、报告照常出）。
    """
    for rtype, reg in rt.CLARIFY_CONSUMERS.items():
        declared = {q for q, v in reg.items() if v["consumer"] == rt.CONSUMER_CONSTRAINTS}
        claimed = {c for sid, p in rt.PERSPECTIVE_SPECS.items()
                   if _OWNER.get(sid) == rtype
                   for c in (p.get("hard_constraints") or ())}
        assert declared <= claimed, (
            f"{rtype} 有 {sorted(declared - claimed)} 登记为硬约束却无人认领 —— "
            "答案不会进任何提示词")


# ── VR-A7 视角行自洽（D1/D3/D4：填错一行必须当场红，而不是运行期静默劣化）──

@pytest.mark.parametrize("sid", _PERSP_SIDS)
def test_perspective_row_shape_self_consistent(sid):
    p = rt.perspective_spec(sid)
    rtype = _OWNER[sid]
    qids = {q["id"] for q in rt.type_spec(rtype)["clarify"]}
    # D1 问了就得有人听：hard_constraints 必须是该类型问卷里真实存在的题 id，
    #   否则 engine 的 `if clar.get(q)` 会静默跳过，约束形同没问。
    assert set(p["hard_constraints"]) <= qids, \
        f"{sid} 声明了 {rtype} 问卷里不存在的约束题"
    # D4 二查模板必须且只能按景点格式化。写错占位名（如 {dest}）会在
    #   asyncio.to_thread 里抛 KeyError 并被 spots 的 except 吞掉 → 全表静默占位。
    for t in p["spot_probe_tpls"]:
        fields = {f for _, f, _, _ in string.Formatter().parse(t) if f}
        assert fields == {"spot"}, f"{sid} 二查模板占位符异常：{fields or '（无 {spot}）'}"
    #   角度模板从不 format（planning 直接当检索词用），含花括号即把字面量送进检索。
    for t in p["angle_tpls"]:
        assert "{" not in t and "}" not in t, f"{sid} 角度模板不得含占位：{t}"
    if p.get("checklist_key"):
        assert p["checklist_columns"], f"{sid} 配了核查表却没有列定义"
        assert len(p["checklist_columns"]) == 4, \
            f"{sid} 列数 {len(p['checklist_columns'])}≠4，与前端定标（表宽/权重）不符"
        # 前端表头用 shortName = column.split('/')[0]，故要求短名非空且互不相同
        # （两列短名撞车＝表头无法区分；斜杠本身用不用是风格，不是契约）。
        shorts = [c.split("/")[0].strip() for c in p["checklist_columns"]]
        assert all(shorts), f"{sid} 有列的短名为空：{p['checklist_columns']}"
        assert len(set(shorts)) == len(shorts), f"{sid} 表头短名撞车：{shorts}"
        assert p.get("checklist_metric"), f"{sid} 缺 CSV 指标列文案"
        # D4b 列与探针**按位 1:1**：配额按列数派生（perspective_probe_budget），条数不等
        #   就意味着有的列天生分不到探针 —— 亲子实测 2 探针喂 4 列时两列归零 0/7。
        #   只断言长度（语义对齐靠人读：模板顺序必须与 checklist_columns 同序）。
        assert len(p["spot_probe_tpls"]) == len(p["checklist_columns"]), (
            f"{sid} 探针 {len(p['spot_probe_tpls'])} 条 ≠ 列 {len(p['checklist_columns'])} 个"
            " → 有列天生无据可填")
        # D3 种子可达：核查表行 seed 自 spot_ranking，类型没有它就只能产出空表。
        assert "spot_ranking" in rt.type_spec(rtype)["structured_keys"], \
            f"{sid} 属 {rtype}，该类型无景点榜可 seed → 核查表永远全占位且拉低质量分"


@pytest.mark.parametrize("sid", _PERSP_SIDS)
def test_conditional_constraints_belong_to_this_perspective(sid):
    """D1b 反向归属：视角挂靠的条件题，其触发值必须映射回本视角。

    现有断言只查「qid 存在」与「equals 唯一」，因此「长辈视角要求回答娃龄」
    这种两处各自成立、合起来荒谬的错配能同时过两道门。
    """
    p = rt.perspective_spec(sid)
    rtype = _OWNER[sid]
    by_id = {q["id"]: q for q in rt.type_spec(rtype)["clarify"]}
    for qid in p["hard_constraints"]:
        cond = (by_id.get(qid) or {}).get("show_if")
        if not cond:
            continue
        assert rt.perspective_section(rtype, str(cond["equals"])) == sid, \
            f"{sid} 挂靠 {qid}，但它由「{cond['equals']}」触发，属别的视角"


def test_party_options_resolve_to_distinct_perspectives():
    """D2b 触发值与视角一一对应。

    perspective_key 是**子串**匹配且取首个命中（优先级=dict 插入序），将来加一个
    「非亲子」这类含子串的选项，会同时命中 family 并被静默归到亲子视角。
    """
    party = next(q for q in rt.type_spec("guide")["clarify"] if q["id"] == "party")
    resolved = {opt: rt.perspective_section("guide", opt) for opt in party["options"]}
    with_sid = {o: s for o, s in resolved.items() if s}
    assert len(set(with_sid.values())) == len(with_sid), f"两个选项撞同一视角：{resolved}"
    assert resolved["朋友结伴"] == "", "「朋友结伴」应保持通用（无对应视角章）"
    assert len(with_sid) == 5


def test_served_question_set_exceeds_registry_only_by_enhanced_questions():
    """D7 钉住「注册表 ⊊ 服务端题集」：任何按注册表取白名单的答案过滤都是危险的。

    destinations/scope 由 _build_enhanced_questions 在注册表之外追加，却承载真实载荷
    （destinations 是 _checked_destinations 的唯一入口、进而决定核查表行种子）。
    """
    served = O._build_enhanced_questions({}, list(rt.type_spec("guide")["clarify"]), None,
                                        research_type="guide", query="")
    extra = ({q["id"] for q in served}
             - {q["id"] for q in rt.type_spec("guide")["clarify"]})
    assert extra <= {"scope", "destinations"}, f"出现注册表外的意外题：{extra}"
