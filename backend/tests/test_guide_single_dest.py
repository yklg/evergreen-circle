"""guide 单目的地闸门（8 章改造 M3c，待确认 #7 拍板硬拒绝）+ 出发地题（M3b）契约。

守护的不变量（三层闸门各挡一条漏网路径）：
- 层① 预防位：guide 增强问卷的目的地题是**单选**（assessment 保持多选）；
- 层② 落库闸门：submit_clarify 在写库**前**拒绝 guide 多目的地（坏问卷不会被 runner 带进管线）；
- 层③ 终点闸门：_plan_research 在采集/算分之前兜住「原文点名多目的地」与旧缓存问卷；
- API 层：POST /api/tasks/{id}/clarify 返回结构化 422（detail.code=guide_single_destination），
  assessment 多目的地完全不受影响；
- 问卷结构：guide/assessment 静态问卷都含 origin（出发地）题，位于 travel_season 之后。

运行：backend/ 下 `pytest tests/test_guide_single_dest.py -q`
"""
import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core.pipeline.research import engine as O
from app.core import research_types as RT
from app.core import trace
from app.main import app


def _mk(query: str, rtype: str) -> str:
    return O.create_task(query, "deep", None, rtype)["taskId"]


# ── 层② submit_clarify：先拒后落库 ─────────────────────────
def test_sc_rejects_guide_multi_before_persist():
    tid = _mk("大理 丽江 5 天亲子游攻略", "guide")
    with pytest.raises(O.GuideSingleDestinationError) as ei:
        O.submit_clarify(tid, {"destinations": ["大理", "丽江"]})
    assert "单个目的地" in str(ei.value)
    clar = (db.get_task(tid) or {}).get("clarifications", {}) or {}
    assert "destinations" not in clar, "拒绝必须发生在落库之前，坏答案不得入库"


def test_sc_allows_guide_single_in_list_and_str_form():
    tid = _mk("大理 5 天亲子游攻略", "guide")
    assert O.submit_clarify(tid, {"destinations": ["大理"]}) == {"ok": True}
    tid2 = _mk("大理 5 天亲子游攻略", "guide")
    assert O.submit_clarify(tid2, {"destinations": "大理"})["ok"] is True


def test_sc_assessment_multi_unaffected():
    tid = _mk("评估成都和杭州哪个更适合长期居住", "assessment")
    assert O.submit_clarify(tid, {"destinations": ["成都", "杭州"]})["ok"] is True


# ── 层③ 计划终点闸门：原文点名多城市也拦得住 ────────────────
class _PlanLLM:
    """按 purpose 分发的计划 LLM 假件；未知 purpose 一律 raise（TC-X0 契约）。"""

    def __init__(self, plan):
        self.plan = plan

    def __call__(self, messages, temperature=0.3, max_tokens=2048, model=None, *, purpose=""):
        if purpose.startswith("拆解调研计划"):
            return dict(self.plan)
        raise AssertionError(f"未预期的 LLM 调用 purpose：{purpose!r}")


MULTI_PLAN = {"subject": "大理", "destinations": ["大理", "丽江"],
              "focus": ["交通"], "search_angles": ["交通攻略", "住宿推荐"]}


def test_plan_rejects_guide_multi_from_query_path(monkeypatch):
    monkeypatch.setattr(O, "chat_json", _PlanLLM(MULTI_PLAN), raising=False)
    task_id = "t_single_dest_plan"
    trace.cleanup(task_id)
    with pytest.raises(O.GuideSingleDestinationError) as ei:
        O._plan_research("大理 丽江 5 天亲子游攻略", {}, 7, "guide", task_id)
    assert "调研评估" in str(ei.value), "拒绝文案应指路改用 assessment 做对比"
    spans = [s for s in trace.get_trace(task_id) if s["purpose"] == O._DEST_PLAN_STEP]
    assert len(spans) == 1 and "多目的地被拒" in spans[0]["decision"], "拒绝事实必须留在决策日志"


def test_plan_assessment_multi_unaffected(monkeypatch):
    monkeypatch.setattr(O, "chat_json", _PlanLLM(MULTI_PLAN), raising=False)
    out = O._plan_research("大理 丽江 5 天亲子游攻略", {}, 7, "assessment", "t_single_dest_plan")
    assert out["destinations"] == ["大理", "丽江"]


# ── API 层：结构化 422，前端可就地展示 ─────────────────────
def test_api_clarify_422_for_guide_multi():
    tid = _mk("大理 丽江 5 天亲子游攻略", "guide")
    r = TestClient(app).post(f"/api/tasks/{tid}/clarify",
                             json={"answers": {"destinations": ["大理", "丽江"]}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, dict) and detail["code"] == "guide_single_destination"
    assert "单个目的地" in detail["message"]


def test_api_clarify_assessment_multi_still_ok():
    tid = _mk("评估成都和杭州哪个更适合长期居住", "assessment")
    r = TestClient(app).post(f"/api/tasks/{tid}/clarify",
                             json={"answers": {"destinations": ["成都", "杭州"]}})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ── 层① 预防位 + M3b：问卷结构 ─────────────────────────────
def test_guide_enhancer_destination_question_is_single():
    base = [dict(q) for q in RT.type_spec("guide")["clarify"]]
    scope = {"subject": "大理", "domain": "旅游", "candidates": ["大理", "丽江"]}
    qs = O._build_enhanced_questions(scope, base, research_type="guide")
    dq = next(q for q in qs if q["id"] == "destinations")
    assert dq["type"] == "single" and "单个目的地" in dq["question"]


def test_assessment_enhancer_destination_question_stays_multi():
    base = [dict(q) for q in RT.type_spec("assessment")["clarify"]]
    scope = {"subject": "成都", "domain": "旅游", "candidates": ["成都", "杭州"]}
    qs = O._build_enhanced_questions(scope, base, research_type="assessment")
    dq = next(q for q in qs if q["id"] == "destinations")
    assert dq["type"] == "multi" and "可多选" in dq["question"]


@pytest.mark.parametrize("rtype,expected", [("guide", "text"), ("assessment", "single")])
def test_origin_question_in_static_clarify(rtype, expected):
    """guide 出发地是自由输入城市（接通城际交通检索，C3）；assessment 保持档位单选（plan_text）。"""
    ids = [q["id"] for q in RT.type_spec(rtype)["clarify"]]
    assert "origin" in ids, "出发地题是交通与抵达章节的路线起点依据（M3b）"
    q = RT.type_spec(rtype)["clarify"][ids.index("origin")]
    assert q["type"] == expected


# ── C5 · destinations 条件出题：原文唯一点名即锁定（TC-L1–L5）──
LOCK_QUERY = "大理 5 天亲子游攻略"
SCOPE_LOCKED = {"subject": "大理", "domain": "旅游", "candidates": ["大理", "丽江"]}


def _enh(scope, query, rtype="guide"):
    base = [dict(q) for q in RT.type_spec(rtype)["clarify"]]
    return O._build_enhanced_questions(scope, base, research_type=rtype, query=query)


def test_L1_locked_query_skips_destination_question():
    qs = _enh(SCOPE_LOCKED, LOCK_QUERY)
    assert "destinations" not in {q["id"] for q in qs}, "用户已说清的事不再追问"
    scope_q = next(q for q in qs if q["id"] == "scope")
    assert "大理" in scope_q["question"], "锁定事实必须出现在确认位题面"


def test_L2_unnamed_query_still_asks():
    qs = _enh({"subject": "亲子游", "domain": "旅游", "candidates": ["大理", "丽江"]},
              "亲子游哪里好")
    assert "destinations" in {q["id"] for q in qs}


def test_L3_assessment_never_skips():
    """评估类型天然多目的地对比，锁定判据不适用——原文点名也照出题。"""
    qs = _enh(SCOPE_LOCKED, LOCK_QUERY, rtype="assessment")
    assert "destinations" in {q["id"] for q in qs}


def test_multi_mentioned_query_is_not_locked():
    qs = _enh(SCOPE_LOCKED, "大理 丽江 5 天亲子游攻略")
    assert "destinations" in {q["id"] for q in qs}, "点名两城不满足『唯一』，必须回到问卷澄清"


def test_L4_enhancer_skip_iff_plan_agrees():
    """一致性钉：问卷不出题 ⇔ 计划层目的地集合恰为 [锁定名]（两时点同一谓词，防分叉）。"""
    locked = O.locked_destination(LOCK_QUERY, SCOPE_LOCKED["candidates"])
    dests, _ = O._destination_set(LOCK_QUERY, {}, SCOPE_LOCKED["candidates"])
    assert locked == "大理" and dests == ["大理"]
    assert ("destinations" in {q["id"] for q in _enh(SCOPE_LOCKED, LOCK_QUERY)}) == (not locked)


def test_L1_trace_records_lock(monkeypatch):
    """锁定不只是不出题：trace 必须留痕，决策日志能回答「为什么没问目的地」。"""
    import asyncio
    query = "大理 5 天攻略验痕"
    db.save_discovery_cache(db._query_hash(query), dict(SCOPE_LOCKED))  # 缓存命中，零 LLM
    tid = _mk(query, "guide")
    trace.cleanup(tid)
    payload = asyncio.run(O._discover_and_build(tid, query, O._baseline_questions(query, "guide"), 5.0))
    assert "destinations" not in {q["id"] for q in payload["questions"]}
    spans = [s for s in trace.get_trace(tid) if s["purpose"] == O._DEST_PLAN_STEP]
    assert spans and "锁定" in spans[0]["decision"] and "大理" in spans[0]["decision"]
