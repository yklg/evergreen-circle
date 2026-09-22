"""题-消费契约真相源（CLARIFY_CONSUMERS）的元测试（问卷优化 v2 · C1，TC-N1–N4）。

守护的不变量：
- N1 有题必有登记：静态题 ∪ 增强题（scope/destinations）与注册表键**双向精确一致**，
      且下发前端的每题都带合法 consumer 值——新增一题不登记即红（防「问了不听」回潮）。
- N2 plan_text 题面不得含承诺词：只进提示词参考文本的题，题面禁止「决定/依据/取舍」
      等承诺性文案（虚假预期是本轮改造的直接症状）。
- N3 答题摘要白名单只派生自注册表：digest 项 = digest=True 的题，且 origin/scope 恒不进摘要。
- N4 结构化消费点与接线配置一致：structured:focus 的题必须是 spec["focus_qid"]；
      focus 关键词映射必须**恰好覆盖**该题全部选项；structured:origin_angle 只允许出现在
      配了 origin_angle_tpl 的类型上。

运行：backend/ 下 `pytest tests/test_clarify_contract.py -q`
"""
import pytest

from app.core import orchestrator as O
from app.core import research_types as RT

TYPES = ["guide", "assessment"]
# 承诺性文案词表：只约束 plan_text / confirm_only 题（结构化消费题如实描述接线效果不受限）
PROMISE_WORDS = ("决定", "依据", "取舍", "据此", "将按此")
# 增强题固定两题：确认位 scope + 目的地 destinations
ENHANCED_IDS = {"scope", "destinations"}


def _all_question_ids(rtype: str) -> set:
    static = {q["id"] for q in RT.type_spec(rtype)["clarify"]}
    return static | ENHANCED_IDS


# ── N1 · 有题必有登记（双向一致 + 下发题带合法 consumer）──────
@pytest.mark.parametrize("rtype", TYPES)
def test_registry_covers_every_question_exactly(rtype):
    registered = set(RT.consumer_registry(rtype))
    actual = _all_question_ids(rtype)
    assert actual == registered, (f"缺登记: {actual - registered}；"
                                  f"多余登记（题已不存在）: {registered - actual}")


@pytest.mark.parametrize("rtype", TYPES)
def test_enhanced_questions_carry_legal_consumer(rtype):
    scope = {"subject": "大理", "domain": "旅游", "candidates": ["大理", "丽江"]}
    qs = O._build_enhanced_questions(scope, RT.type_spec(rtype)["clarify"],
                                     research_type=rtype)
    for q in qs:
        consumer = q.get("consumer")
        assert consumer, f"题 {q['id']!r} 未随问卷下发 consumer 键"
        assert consumer in RT.ALL_CONSUMERS, f"{q['id']}: 非法消费值 {consumer!r}"
        assert consumer == RT.consumer_of(rtype, q["id"])["consumer"]


# ── N2 · plan_text 题面禁止承诺词 ───────────────────────────
@pytest.mark.parametrize("rtype", TYPES)
def test_plan_text_questions_make_no_promises(rtype):
    checked = 0
    for qid, cfg in RT.consumer_registry(rtype).items():
        if cfg["consumer"] not in (RT.CONSUMER_PLAN_TEXT, RT.CONSUMER_CONFIRM_ONLY):
            continue
        text = _question_text(rtype, qid)
        assert not any(w in text for w in PROMISE_WORDS), (
            f"{rtype}.{qid} 只进提示词参考文本，题面却写了承诺词（虚假预期）：{text!r}")
        checked += 1
    assert checked >= 3, "样本量哨兵：plan_text 题若被整体改名/删除，本钉不得静默空转"


def _question_text(rtype: str, qid: str) -> str:
    if qid == "destinations":
        return "候选目的地选择题"      # 增强题固定文案，不在静态表里
    for q in RT.type_spec(rtype)["clarify"]:
        if q["id"] == qid:
            return q["question"]
    return ""


# ── N3 · 摘要白名单派生自注册表 ─────────────────────────────
@pytest.mark.parametrize("rtype", TYPES)
def test_digest_fields_derive_from_registry(rtype):
    fields = dict(RT.clarify_digest_fields(rtype))
    assert set(fields) == {qid for qid, cfg in RT.consumer_registry(rtype).items()
                           if cfg.get("digest")}
    assert all(label for label in fields.values()), "digest=True 的题必须有展示名"
    for qid in fields:
        assert qid in _all_question_ids(rtype), "摘要白名单不得指向不存在的题"
    assert "origin" not in fields and "scope" not in fields, (
        "出发地是检索凭据、scope 是校对位，都不进答题摘要（C6 契约）")


# ── N4 · 结构化消费点与接线配置一致 ─────────────────────────
@pytest.mark.parametrize("rtype", TYPES)
def test_focus_wiring_is_consistent(rtype):
    spec = RT.type_spec(rtype)
    qid = spec["focus_qid"]
    assert RT.consumer_of(rtype, qid)["consumer"] == RT._structured("focus")
    focus_q = next(q for q in spec["clarify"] if q["id"] == qid)
    assert set(spec["focus_angle_keywords"]) == set(focus_q["options"]), (
        "focus 关键词映射必须恰好覆盖题面全部选项：多一个空转、少一个漏接线")
    assert all(kw for kw in spec["focus_angle_keywords"].values())


@pytest.mark.parametrize("rtype", TYPES)
def test_origin_angle_only_where_wired(rtype):
    spec = RT.type_spec(rtype)
    has_consumer = any(cfg["consumer"] == RT._structured("origin_angle")
                       for cfg in RT.consumer_registry(rtype).values())
    assert has_consumer == bool(spec.get("origin_angle_tpl")), (
        "登记了 origin_angle 消费的题，该类型必须配模板（反之亦然）——两表漂移即死角度")
