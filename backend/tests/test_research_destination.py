"""目的地调研（攻略/评估）专家流水线：purpose 落库 / runner 路由 / 报告 voice / SSE 契约。

TDD 规格（计划 §5.1 覆盖矩阵 · BE-R1..R7）：
- BE-R1   runner._drive 按 kind 路由：research/travel_guide/travel_assess → 调研引擎；
         living_circle 走独立生活圈流水线（各不互串）。
- BE-R2   无 purpose 的 travel/research 任务 → 仍走既有调研路径（向后兼容）。
- BE-R3   TRAVEL_PROFILES 注入：guide/assess 各自的 personas/sections/label 正确选择。
- BE-R4   report_voice(purpose)：guide/assess 返回对应 voice；未知/缺省回退空 dict（等价类+边界）。
- BE-R5   purpose 经 POST /api/tasks 落库；GET status 回显 kind/purpose（前端判型回退）。
- BE-R7   travel_kind 的 SSE 事件流以 done 收尾、无 error 哨兵（工作台三栏可渲染）。

运行：backend/ 下 `pytest tests/test_research_destination.py -q`。
"""
import asyncio

from fastapi.testclient import TestClient

from app.core import db, orchestrator, runner  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _conn():
    return db._connect()


def _insert_task(task_id, kind, purpose="", query="r_q"):
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,created_at,kind,purpose)"
        " VALUES(?,?,?,?,?,?,?)",
        (task_id, query, "{}", "created", db._now(), kind, purpose),
    )
    _conn().commit()


def _fake_pipeline(tag, called):
    async def _gen(task_id):
        called.append(tag)
        yield {"type": "progress", "data": {"percent": 50, "stage": tag, "evidence_count": 1}}
        yield {"type": "done", "data": {"reportId": db.get_task_full(task_id).get("query")}}
    return _gen


def _patch_pipelines(monkeypatch):
    """把四类引擎全部替换为假流水线（经 `runner.KIND_PIPELINES` 接缝），记录各自被调用次数。

    封闭注册表在 import 时持有流水线函数引用，直接 patch 模块属性不拦截，
    故整表注入假工厂；此设计同时使本文件不 import 尚待落地的新 research 模块。
    """
    calls = {"research": [], "refine": [], "brief": [], "living": []}
    monkeypatch.setattr(runner, "KIND_PIPELINES", {
        "research": _fake_pipeline("research", calls["research"]),
        "travel_guide": _fake_pipeline("research", calls["research"]),
        "travel_assess": _fake_pipeline("research", calls["research"]),
        "refine": _fake_pipeline("refine", calls["refine"]),
        "brief": _fake_pipeline("brief", calls["brief"]),
        "living_circle": _fake_pipeline("living", calls["living"]),
    }, raising=False)
    return calls


def _await_drive(task_id):
    async def _scenario():
        runner.ensure_running(task_id)
        await asyncio.sleep(0.25)
    asyncio.run(_scenario())


# ── BE-R1 / R2：runner 按 kind 路由 ─────────────────────
def test_runner_routes_travel_research_kinds_to_research_engine(monkeypatch):
    """BE-R1：travel_guide / travel_assess 均路由到调研引擎（research_pipeline），不串生活圈/精修。"""
    runner._running.clear()
    calls = _patch_pipelines(monkeypatch)

    _insert_task("t_guide_1", "travel_guide", purpose="guide")
    _insert_task("t_assess_1", "travel_assess", purpose="assess")
    _await_drive("t_guide_1")
    _await_drive("t_assess_1")

    assert calls["research"] == ["research", "research"], "travel_guide/travel_assess 都应走调研引擎"
    assert calls["refine"] == [] and calls["brief"] == [] and calls["living"] == [], "其它引擎不应被调用"
    assert db.get_task_full("t_guide_1")["status"] == "done"
    assert db.get_task_full("t_assess_1")["status"] == "done"


def test_runner_routes_research_kind_to_research_engine(monkeypatch):
    """BE-R1：kind='research' → 调研引擎；不触发生活圈。"""
    runner._running.clear()
    calls = _patch_pipelines(monkeypatch)
    _insert_task("t_research_1", "research")
    _await_drive("t_research_1")
    assert calls["research"] == ["research"]
    assert calls["living"] == []


def test_runner_routes_living_circle_independently(monkeypatch):
    """BE-R1：kind='living_circle' → 生活圈流水线；调研/精修/简报均不得被调用。"""
    runner._running.clear()
    calls = _patch_pipelines(monkeypatch)
    _insert_task("t_lc_1", "living_circle")
    _await_drive("t_lc_1")
    assert calls["living"] == ["living"]
    assert calls["research"] == [] and calls["refine"] == [] and calls["brief"] == []


def test_runner_no_purpose_still_runs_research(monkeypatch):
    """BE-R2：无 purpose 的 research 任务兼容——仍走调研引擎，不因新字段回归。"""
    runner._running.clear()
    calls = _patch_pipelines(monkeypatch)
    # 通过 POST 默认创建（无 purpose），落 kind=research
    resp = client.post("/api/tasks", json={"query": "黄山", "mode": "deep"})
    assert resp.status_code == 200
    tid = resp.json()["taskId"]
    t = db.get_task_full(tid)
    assert t["kind"] == "research" and t["purpose"] == "", "缺省 purpose 应落空串"
    _await_drive(tid)
    assert calls["research"] == ["research"], "无 purpose 仍走调研引擎"


# ── BE-R3 / R4：报告 voice（TRAVEL_PROFILES / report_voice）──
def test_travel_profiles_inject_purpose_specific_sections(monkeypatch):
    """BE-R3：guide/assess 各自的章节集·人设·标题语正确注入，且互不混用。"""
    guide = orchestrator.TRAVEL_PROFILES["guide"]
    assess = orchestrator.TRAVEL_PROFILES["assess"]

    assert guide["label"] == "目的地攻略"
    assert guide["sections"] == [
        "summary", "guide_overview", "guide_transport", "guide_food_stay",
        "guide_route", "guide_safe", "guide_budget", "guide_voice", "conclusion",
    ]
    assert "旅游策划" in guide["persona"]

    assert assess["label"] == "目的地评估"
    assert assess["sections"] == [
        "summary", "assess_access", "assess_amenity", "assess_price",
        "assess_safety", "assess_voice", "assess_conclusion", "conclusion",
    ]
    assert "评估" in assess["persona"]
    # 两套章节不越界混用
    assert set(guide["sections"]) & set(assess["sections"]) == {"summary", "conclusion"}


def test_report_voice_maps_purpose_and_falls_back(monkeypatch):
    """BE-R4：report_voice 按 purpose 返回 voice；未知/缺省回退空 dict（等价类+边界）。"""
    assert orchestrator.report_voice("guide")["label"] == "目的地攻略"
    assert orchestrator.report_voice("assess")["sections"][1] == "assess_access"
    # 未知 purpose（等价类）与缺省（边界）都不该抛错，且不应污染为攻略/评估
    assert orchestrator.report_voice("unknown_purpose") == {}
    assert orchestrator.report_voice("") == {}


# ── BE-R5：purpose 落库 + status 回显 ───────────────────
def test_create_task_persists_purpose_via_endpoint():
    """BE-R5：POST /api/tasks 带 purpose=guide → task.kind=travel_guide 且 purpose 落库。"""
    resp = client.post("/api/tasks", json={"query": "黄山", "mode": "deep", "purpose": "guide"})
    assert resp.status_code == 200
    tid = resp.json()["taskId"]
    t = db.get_task_full(tid)
    assert t["kind"] == "travel_guide"
    assert t["purpose"] == "guide"


def test_status_echoes_kind_and_purpose():
    """BE-R5：GET /api/tasks/{id}/status 回显 kind/purpose（前端 taskViewProvider 判型回退依赖）。"""
    resp = client.post("/api/tasks", json={"query": "大理", "purpose": "assess"})
    tid = resp.json()["taskId"]
    status = client.get(f"/api/tasks/{tid}/status").json()
    assert status["kind"] == "travel_assess"
    assert status["purpose"] == "assess"


# ── BE-R7：travel_kind SSE 契约（done 收尾、无 error 哨兵）──
def test_runner_travel_stream_done_no_error(monkeypatch):
    """BE-R7：travel_assess 任务流以 done 收尾且无 error 哨兵（工作台可渲染）。"""
    runner._running.clear()
    calls = _patch_pipelines(monkeypatch)
    _insert_task("t_stream_assess_1", "travel_assess", purpose="assess", query="r_stream_1")

    async def _scenario():
        events = []
        async for ev in runner.subscribe("t_stream_assess_1"):
            events.append(ev)
        return events

    events = asyncio.run(_scenario())
    types = [e["type"] for e in events]
    assert "done" in types, "travel_assess 流必须以 done 收尾"
    assert types[-1] == "done"
    assert "error" not in types, "成功流不得出现 error 哨兵"
    assert calls["research"] == ["research"], "subscribe 应触发调研引擎"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))