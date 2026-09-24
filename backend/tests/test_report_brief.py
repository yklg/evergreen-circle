"""报告一页纸精炼（brief）—— 派生数据生命周期测试（test-coverage-expander 方案）。

契约（《报告简报与 PPT 汇报方案 v3》）：
- `orchestrator.generate_brief(report_id)`：幂等（已存在不重复调 LLM）、失败记 brief_failed_at、
  成功清 brief_failed_at、并发经 db._LOCK 串行 + 写回前重读校验、无 summary/metrics 时降级组装。
- `db.invalidate_report_brief(report_id)`：清除 data.brief / brief_failed_at，幂等（brief 不存在不报错）。
- `POST /api/reports/{id}/brief`（G7 迁移）：创建 kind='brief' 后台任务并返回 {taskId}；404 不变；
  幂等/失败语义移入 brief_report_pipeline（已有 brief → done 快路径；失败 → error 事件 + 任务 failed 终态）。
- `brief_report_pipeline`：事件协议 progress→done{reportId} / error；阻塞 LLM 走 asyncio.to_thread。
- 失效挂点：post_refine、post_feedback、refine_report_pipeline 成功出口各清除一次 brief。

依赖真实逻辑的注入点：
- orchestrator.chat_json（模块级 from-import 绑定，见 orchestrator.py:38）→ monkeypatch 假实现。
- orchestrator._rewrite_section → monkeypatch 假实现（沿用 test_refine_evidence 模式）。

mock 策略（对齐 test_refine_evidence.py）：patch orchestrator 模块属性，不调真实 LLM；
TestClient 测端点；内嵌 asyncio.run 消费 pipeline；VERDA_DB_PATH 由 conftest 在 import app 前隔离。
运行：backend/ 下 `pytest tests/test_report_brief.py -q`
"""
import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core import db, runner
from app.core.pipeline.research import engine as orchestrator
from app.main import app


def _conn():
    return db._connect()


def _make_report(rid, with_summary: bool = True):
    """种子报告：含可被 generate_brief 组装的最小结构。"""
    summary_section = {
        "id": "summary",
        "title": "执行摘要 · 核心判断",
        "key_takeaway": "摘要结论",
        "highlights": ["亮点1", "亮点2"],
        "paragraphs": ["全文"],
    }
    sections = [summary_section] if with_summary else []
    report = {
        "id": rid, "title": "报告 " + rid, "subtitle": "副标题", "query": "测试查询",
        "destinations": ["目的地A"], "experts": [], "cover_image": "",
        "created_at": db._now(),
        "evidence": [], "claims": [], "metrics": {},
        "sections": sections,
    }
    db.save_report(report, task_id="")


def _fake_chat_json(calls_holder):
    """假 LLM：接收真实签名 (messages, **kwargs)，返回一页纸精炼四段结构并计数调用。"""
    def _fake(messages, **kwargs):
        calls_holder.append(messages)
        return {
            "summary": "一句话概括",
            "judgments": ["判断1", "判断2", "判断3"],
            "key_data": ["数据1", "数据2"],
            "actions": ["行动1", "行动2", "行动3"],
        }
    return _fake


def _seed_brief(rid, calls_holder=None, monkeypatch=None):
    """生成报告 + 用假 LLM 落一份 brief，返回该 brief。"""
    _make_report(rid)
    holder = calls_holder if calls_holder is not None else []
    if monkeypatch is not None:
        monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(holder))
    brief = orchestrator.generate_brief(rid)
    assert brief, "种子自检：generate_brief 应产出 brief"
    return brief


def _seed_brief_with_evidence(rid, specs, monkeypatch):
    """生成报告（带 evidences 表证据，specs=[(eid,cred)]）并落一份 brief（仿 test_refine_evidence 种子）。"""
    _make_report(rid)
    for eid, cred in specs:
        _conn().execute(
            "INSERT OR REPLACE INTO evidences(evidence_id,report_id,source_url,source_type,domain,"
            "title,excerpt,credibility,collected_by,destination,captured_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (eid, rid, "https://example.com/" + eid, "web", "example.com", "证据 " + eid,
             "内容", cred, "tester", "目的地A", db._now()),
        )
    _conn().commit()
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json([]))
    brief = orchestrator.generate_brief(rid)
    assert brief, "种子自检：generate_brief 应产出 brief"
    return brief


def _fake_rewrite(section, extra_context, system_prompt):
    """替换 _rewrite_section：就地重写，不调真实 LLM（沿用 test_refine_evidence）。"""
    section["paragraphs"] = ["重写段落：" + section.get("title", "")]
    section["refined"] = True
    section["absorbed_evidence_ids"] = extra_context.get("absorbed_evidence_ids", []) \
        if isinstance(extra_context, dict) else []
    return section


async def _drain(pipeline_coro):
    events = []
    async for ev in pipeline_coro:
        events.append(ev)
    return events


# ── 幂等：已存在 brief 不再触发 LLM ─────────────────────────
def test_brief_idempotent_no_llm_call(monkeypatch):
    """首次生成后 data.brief 存在；再次调用不再调 chat_json，返回同一份 brief。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_idem_1")

    first = orchestrator.generate_brief("r_idem_1")
    n_after_first = len(calls)
    assert first and n_after_first == 1

    second = orchestrator.generate_brief("r_idem_1")
    assert len(calls) == n_after_first, "已有 brief 时不应再次调用 LLM"
    assert second == first


# ── 端点：创建任务 {taskId} / 404 ─────────────────────────
def test_brief_endpoint_creates_task(monkeypatch):
    """POST brief（G7 迁移后）→ 200 + {taskId}；不再同步返回 brief。"""
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json([]))
    _make_report("r_ep_ok")
    r = TestClient(app).post("/api/reports/r_ep_ok/brief")
    assert r.status_code == 200
    j = r.json()
    assert j.get("taskId"), "迁移后端点应返回 {taskId}"
    assert db.get_task_full(j["taskId"])["kind"] == "brief"


def test_brief_endpoint_not_found_404():
    """不存在的 report_id → 404（创建任务前置守卫）。"""
    client = TestClient(app)
    r = client.post("/api/reports/r_missing_404/brief")
    assert r.status_code == 404


def test_brief_endpoint_creates_task_returns_json_with_detail_on_missing():
    """404 响应体含可读 detail（前端显式抛错契约）。"""
    r = TestClient(app).post("/api/reports/r_m404d/brief")
    assert r.status_code == 404
    assert r.json().get("detail")


# ── brief_report_pipeline：事件协议 / 终态 ─────────────────
def test_brief_pipeline_generates_and_done(monkeypatch):
    """新建报告 → pipeline 产出 progress+done；brief 四段落库。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_pl_ok")
    tid = orchestrator.create_brief_task("r_pl_ok")["taskId"]

    async def _real():
        return await _drain(orchestrator.brief_report_pipeline(tid))
    events = asyncio.run(_real())
    types = [e["type"] for e in events]
    assert types == ["progress", "done"], f"事件协议应为 progress→done，实际 {types}"
    assert events[-1]["data"]["reportId"] == "r_pl_ok"
    assert db.get_report("r_pl_ok")["brief"]["summary"]


def test_brief_full_chain_via_runner(monkeypatch):
    """全链路：runner.ensure_running(drive brief pipeline) → 任务 done + brief 落库（DB 终态由 _drive 落账）。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_chain")
    tid = orchestrator.create_brief_task("r_chain")["taskId"]

    async def _scenario():
        runner.ensure_running(tid)
        await asyncio.sleep(0.35)  # 让后台 _drive 跑完 brief pipeline
        return db.get_task_full(tid)["status"]
    status = asyncio.run(_scenario())
    assert status == "done", "runner 全链路应以 done 收尾"
    assert db.get_report("r_chain")["brief"]["summary"]


def test_brief_pipeline_idempotent_no_llm_call(monkeypatch):
    """已有 brief → pipeline 只走 done 快路径，不再调 LLM。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _seed_brief("r_pl_idem", calls_holder=calls, monkeypatch=monkeypatch)
    n_before = len(calls)
    tid = orchestrator.create_brief_task("r_pl_idem")["taskId"]

    async def _real():
        events = await _drain(orchestrator.brief_report_pipeline(tid))
        return events
    events = asyncio.run(_real())
    assert len(calls) == n_before, "已有 brief 时 pipeline 不应再调 LLM"
    assert [e["type"] for e in events] == ["progress", "done"]


def test_brief_pipeline_report_missing_error_failed(monkeypatch):
    """报告不存在 → error 事件 + 任务 failed 终态（不再 503/404 混合语义）。"""
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json([]))
    tid = orchestrator.create_brief_task("r_pl_missing")["taskId"]

    async def _real():
        return await _drain(orchestrator.brief_report_pipeline(tid))
    events = asyncio.run(_real())
    assert [e["type"] for e in events] == ["error"]
    assert "报告不存在" in events[-1]["data"]["message"]
    assert db.get_task_full(tid)["status"] == "failed"


def test_brief_pipeline_unconfigured_error_failed(monkeypatch):
    """LLM 未配置 → error 事件（含可读消息）+ 任务 failed 终态。"""
    def _raise(*args, **kwargs):
        raise orchestrator.LLMNotConfigured("LLM 未配置")
    monkeypatch.setattr(orchestrator, "chat_json", _raise)
    _make_report("r_pl_503")
    tid = orchestrator.create_brief_task("r_pl_503")["taskId"]

    async def _real():
        return await _drain(orchestrator.brief_report_pipeline(tid))
    events = asyncio.run(_real())
    assert events[-1]["type"] == "error", "最后事件应为 error"
    assert "LLM 未配置" in events[-1]["data"]["message"]
    assert db.get_task_full(tid)["status"] == "failed"


def test_brief_pipeline_llm_failure_error_failed(monkeypatch):
    """LLM 普通失败 → error 事件 + 任务 failed；不写 brief 但保留 brief_failed_at。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(orchestrator, "chat_json", _boom)
    _make_report("r_pl_fail")
    tid = orchestrator.create_brief_task("r_pl_fail")["taskId"]

    async def _real():
        return await _drain(orchestrator.brief_report_pipeline(tid))
    events = asyncio.run(_real())
    assert events[-1]["type"] == "error", "最后事件应为 error"
    rep = db.get_report("r_pl_fail")
    assert "brief" not in (rep or {})
    assert db.get_task_full(tid)["status"] == "failed"


# ── SSE 传输层契约（HTTP）─────────────────────────────────
def test_brief_sse_transport_done_event(monkeypatch):
    """GET /api/tasks/{tid}/stream → 200 + text/event-stream；body 含 event: done。"""
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json([]))
    _make_report("r_sse_1")
    tid = orchestrator.create_brief_task("r_sse_1")["taskId"]

    with TestClient(app) as cli:
        with cli.stream("GET", f"/api/tasks/{tid}/stream") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            body = "".join(r.iter_text())
    assert "event: done" in body, "SSE body 应含 done 事件"


# ── 失效挂点 ×3 ────────────────────────────────────────────
def test_invalidate_via_refine_endpoint(monkeypatch):
    """挂点1：post_refine 成功后 data.brief / brief_failed_at 被清除。"""
    _seed_brief("r_inv_rf", monkeypatch=monkeypatch)
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    client = TestClient(app)
    section_id = db.get_report("r_inv_rf")["sections"][0]["id"]
    r = client.post("/api/reports/r_inv_rf/refine",
                    json={"section_id": section_id, "annotations": ["批注"]})
    assert r.status_code == 200
    rep = db.get_report("r_inv_rf")
    assert "brief" not in (rep or {}), "refine 后 brief 应被清除"
    assert "brief_failed_at" not in (rep or {})


def test_invalidate_via_feedback_endpoint(monkeypatch):
    """挂点2：post_feedback 成功后 brief 被清除。"""
    _seed_brief("r_inv_fb", monkeypatch=monkeypatch)
    client = TestClient(app)
    r = client.post("/api/reports/r_inv_fb/feedback",
                    json={"edited_blocks": 1, "total_blocks": 3, "data": {}})
    assert r.status_code == 200
    rep = db.get_report("r_inv_fb")
    assert "brief" not in (rep or {}), "feedback 后 brief 应被清除"
    assert "brief_failed_at" not in (rep or {})


def test_invalidate_via_refine_pipeline_done(monkeypatch):
    """挂点3：refine_report_pipeline 成功出口（save_report 后、done 前）清除 brief。"""
    # 与 test_refine_evidence 一致：需要 ≥min_cred 的证据才会进入重写 → done
    _seed_brief_with_evidence("r_inv_pl", [("e_pl_1", 90.0)], monkeypatch=monkeypatch)
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)

    async def _real():
        tid = orchestrator.create_refine_task("r_inv_pl", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    events = asyncio.run(_real())
    assert any(e["type"] == "done" for e in events)
    rep = db.get_report("r_inv_pl")
    assert "brief" not in (rep or {}), "pipeline done 后 brief 应被清除"


# ── 生命周期三步：生成 → 失效 → 重建 ────────────────────────
def test_brief_rebuild_after_invalidate(monkeypatch):
    """invalidate 后再次 generate 可重建新 brief（派生数据完整闭环）。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_rebuild")
    first = orchestrator.generate_brief("r_rebuild")
    assert first

    db.invalidate_report_brief("r_rebuild")
    assert "brief" not in db.get_report("r_rebuild")

    second = orchestrator.generate_brief("r_rebuild")
    assert second and second.get("judgments"), "失效后应可重建"


# ── 失败路径 / 防重 ─────────────────────────────────────────
def test_brief_llm_failure_records_failed_at(monkeypatch):
    """LLM 失败 → 记 brief_failed_at、不写 brief。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(orchestrator, "chat_json", _boom)
    _make_report("r_fail")
    brief = orchestrator.generate_brief("r_fail")
    assert brief is None, "失败不应产出 brief"
    rep = db.get_report("r_fail")
    assert "brief" not in (rep or {})
    assert rep.get("brief_failed_at"), "应记录失败时间戳用于防重"


def test_brief_success_clears_failed_at(monkeypatch):
    """先失败后成功 → brief_failed_at 被清除。"""
    state = {"boom": True}
    def _flaky(messages, **kwargs):
        if state["boom"]:
            raise RuntimeError("first try fails")
        return {"summary": "S", "judgments": ["J"], "key_data": [], "actions": []}
    monkeypatch.setattr(orchestrator, "chat_json", _flaky)
    _make_report("r_retry")
    orchestrator.generate_brief("r_retry")
    assert db.get_report("r_retry").get("brief_failed_at")

    state["boom"] = False
    brief = orchestrator.generate_brief("r_retry")
    assert brief
    rep = db.get_report("r_retry")
    assert rep.get("brief")
    assert "brief_failed_at" not in rep, "成功后应清除失败标记"


def test_invalidate_brief_idempotent():
    """无 brief 的报告调用 invalidate_report_brief 不抛错、无副作用。"""
    _make_report("r_plain")
    db.invalidate_report_brief("r_plain")  # 不应抛异常
    db.invalidate_report_brief("r_does_not_exist")  # 不存在报告也不应抛


# ── 并发串行 ───────────────────────────────────────────────
def test_brief_concurrent_generate_serialized(monkeypatch):
    """并发两次 generate_brief：_LOCK 串行 + 写回前重读校验，结果一致、落库一份、无异常。"""
    import threading
    import time
    calls = []
    real_fake = _fake_chat_json([])

    def _slow_fake(messages, **kwargs):
        time.sleep(0.05)  # 放大竞态窗口
        calls.append(messages)
        return real_fake(messages, **kwargs)

    monkeypatch.setattr(orchestrator, "chat_json", _slow_fake)
    _make_report("r_conc")
    outs = []

    def _job():
        try:
            outs.append(orchestrator.generate_brief("r_conc"))
        except Exception as e:  # noqa: BLE001
            outs.append(e)

    t1 = threading.Thread(target=_job)
    t2 = threading.Thread(target=_job)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not any(isinstance(o, Exception) for o in outs), "并发不应抛异常"
    assert outs[0] == outs[1], "并发返回应一致（串行化 + 读命中）"
    rep = db.get_report("r_conc")
    assert rep.get("brief"), "最终应落库一份有效 brief"


# ── 降级：无 summary / metrics 组装不崩 ─────────────────────
def test_brief_assembly_without_summary(monkeypatch):
    """无 summary 节 / 无 metrics 的存量报告：上下文组装降级，产出完整结构。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_nosum", with_summary=False)
    brief = orchestrator.generate_brief("r_nosum")
    assert brief and brief.get("summary") and isinstance(brief.get("judgments"), list)


# ── M3d：结构化数据事实摘要（8 章改造） ────────────────────────
def _user_prompt(messages) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def test_brief_facts_block_from_structured(monkeypatch):
    """新 8 章报告：spot_ranking/food_ranking/shop_list/cost_breakdown/stay_options 的
    真实数字进 brief prompt（key_data 有依据），缺字段行不猜值。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_facts")
    rep = db.get_report("r_facts")
    rep["sections"] += [
        {"id": "spots", "title": "景点分布调研",
         "structured": {"type": "spot_ranking", "data": [{
             "destination": "大理", "items": [
                 {"name": "洱海", "score": 88.5, "ticket": "免费", "stay_minutes": 120},
                 {"name": "无名景点"}]}]}},
        {"id": "food", "title": "美食清单",
         "structured": {"type": "food_ranking", "data": [{
             "destination": "大理", "items": [{"name": "乳扇", "price_range": "¥10-20"}]}]}},
        {"id": "shops", "title": "美食商铺调研",
         "structured": {"type": "shop_list", "data": [{
             "destination": "大理", "items": [
                 {"name": "老字号", "food": "乳扇", "price_per_person": 58}]}]}},
        {"id": "budget", "title": "预算拆解",
         "structured": {"type": "cost_breakdown", "data": [{
             "destination": "大理", "items": [
                 {"category": "住宿", "amount": 1500, "unit": "元/人"}]}]}},
        {"id": "stay", "title": "住宿",
         "structured": {"type": "stay_options", "data": [{
             "destination": "大理", "areas": [
                 {"area": "才村", "price_range": "¥300-500", "for_whom": "亲子家庭"}]}]}},
    ]
    db.save_report(rep, task_id="")
    assert orchestrator.generate_brief("r_facts")
    prompt = _user_prompt(calls[-1])
    assert "结构化数据事实" in prompt
    assert "景点「洱海」综合分 88.5；门票 免费；建议停留 120 分钟" in prompt
    assert "美食「乳扇」人均 ¥10-20" in prompt
    assert "商铺「老字号」（乳扇）人均参考价 58 元" in prompt
    assert "预算·住宿 1500元/人" in prompt
    assert "住宿「才村」¥300-500，适合 亲子家庭" in prompt
    assert "景点「无名景点」综合分 —" in prompt  # 缺数字用占位符，不猜值


def test_brief_legacy_report_prompt_unchanged(monkeypatch):
    """存量报告（无 structured 键）：不出现数据事实块，旧精炼 prompt 不受影响。"""
    calls = []
    monkeypatch.setattr(orchestrator, "chat_json", _fake_chat_json(calls))
    _make_report("r_legacy_facts")
    assert orchestrator.generate_brief("r_legacy_facts")
    assert "结构化数据事实" not in _user_prompt(calls[-1])


def test_brief_facts_block_empty_structured_is_safe():
    """structured 形状异常（data 为空/类型不对）→ 返回空串，不抛。"""
    assert orchestrator._brief_facts_block([]) == ""
    assert orchestrator._brief_facts_block(
        [{"structured": {"type": "spot_ranking", "data": []}}]) == ""
    assert orchestrator._brief_facts_block([{"structured": "不是dict"}]) == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))