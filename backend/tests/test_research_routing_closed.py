"""封闭路由注册表与 fail-loud（计划 §3.0 / R-1b）。

TDD 目标规格（一期落地后转绿）：
- A1  closed registry 把 research / travel_guide / travel_assess 都路由到调研流水线；
- A2/A3 未知 kind → fail-loud（广播 error + 落库 failed + 不落任何流水线）；
- A4  终态(done)重连不重跑；
- A6/H1 legacy `run_pipeline` 不得出现在注册表（防 else 兜底复辟）。
- H2  删竞品族后 import 仍自洽。

实现前（runner 尚无 KIND_PIPELINES / research.py 未落地）：A6/H1/H2 报红，其余经接缝注入即可绿。
运行：backend/ 下 `pytest tests/test_research_routing_closed.py -q`。
"""
import asyncio
import importlib
import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["VERDA_DB_PATH"] = _TMP.name

from app.core import db, runner  # noqa: E402


def _conn():
    return db._connect()


def _insert_task(task_id, kind, purpose=None, status="created"):
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,created_at,kind,purpose)"
        " VALUES(?,?,?,?,?,?,?)",
        (task_id, f"q_{task_id}", "{}", status, db._now(), kind, purpose),
    )
    _conn().commit()


def _fake_pipeline(tag, called):
    async def _gen(task_id):
        called.append(tag)
        yield {"type": "progress", "data": {"percent": 50, "stage": tag, "evidence_count": 1}}
        yield {"type": "done", "data": {"reportId": db.get_task_full(task_id).get("query")}}
    return _gen


def _patch_research_registry(monkeypatch, called, extra_kinds=None):
    """注入含 research 一族 + living 的封闭注册表；extra_kinds 追加其他 kind 的假引擎。"""
    kinds = {
        "research": _fake_pipeline("research", called),
        "travel_guide": _fake_pipeline("research", called),
        "travel_assess": _fake_pipeline("research", called),
        "living_circle": _fake_pipeline("living", called),
    }
    if extra_kinds:
        kinds.update(extra_kinds)
    monkeypatch.setattr(runner, "KIND_PIPELINES", kinds, raising=False)


# ── A1 ────────────────────────────────────────────────
def test_closed_registry_routes_research_and_travel_kinds(monkeypatch):
    runner._running.clear()
    called: list = []
    _patch_research_registry(monkeypatch, called)

    for i, kind in enumerate(["research", "travel_guide", "travel_assess"], start=1):
        _insert_task(f"t_a1_{i}", kind, purpose="guide")
        _run_once(f"t_a1_{i}")

    assert called == ["research", "research", "research"], "research/travel_* 应都走调研流水线"


# ── A2 / A3：未知 kind fail-loud ──────────────────────────
def _run_once(task_id):
    async def _scenario():
        runner.ensure_running(task_id)
        await asyncio.sleep(0.25)
    asyncio.run(_scenario())


def test_unknown_kind_fails_loud_no_pipeline(monkeypatch):
    """A2：未登记 kind → 广播 error、落库 failed，且不落任何流水线（不静默走竞品/else）。"""
    runner._running.clear()
    called: list = []
    _patch_research_registry(monkeypatch, called)
    _insert_task("t_agree_unk", "not_a_kind")

    events = _subscribe_once("t_agree_unk")
    assert events and events[0]["type"] == "error", "未知 kind 首事件应为 error"
    assert "not_a_kind" in events[0]["data"].get("message", "")
    assert db.get_task_full("t_agree_unk")["status"] == "failed"
    assert called == [], "不应触发任何流水线"


def test_unknown_kind_no_done_event(monkeypatch):
    """A3：未知 kind 流向以 error 收尾，绝不以 done 冒充成功。"""
    runner._running.clear()
    called: list = []
    _patch_research_registry(monkeypatch, called)
    _insert_task("t_agree_unk2", "bogus_kind")
    events = _subscribe_once("t_agree_unk2")
    types = [e["type"] for e in events]
    assert "error" in types
    assert "done" not in types, "失败流不得发 done"


def _subscribe_once(task_id):
    async def _scenario():
        out = []
        async for e in runner.subscribe(task_id):
            out.append(e)
        return out
    return asyncio.run(_scenario())


# ── A4：终态不重跑 ─────────────────────────────────────
def test_terminal_done_no_rerun_of_research(monkeypatch):
    runner._running.clear()
    called: list = []
    _patch_research_registry(monkeypatch, called)
    _insert_task("t_a4_done", "research", status="done")
    # 直接标终态 + report_id，模拟已完成任务
    _conn().execute(
        "UPDATE tasks SET status=?, report_id=? WHERE task_id=?",
        ("done", "r_a4", "t_a4_done"),
    )
    _conn().commit()

    events = _subscribe_once("t_a4_done")
    assert called == [], "终态任务不应重新驱动流水线"
    assert events[0]["type"] == "done", "终态首帧补 done{reportId}"


# ── A6 / H1 / H2：注册表边界与退役守卫 ─────────────────────
def test_registry_boundaries_research_kinds_contained():
    """A6：真实注册表须含 research 一族与 living_circle，且不含 legacy run_pipeline。"""
    kinds = set(runner.KIND_PIPELINES.keys())
    assert {"research", "travel_guide", "travel_assess", "living_circle"} <= kinds


def test_no_run_pipeline_default_exit():
    """H1：组织级护栏——`run_pipeline` 不得作为默认兜底出现在注册表（防 else 复辟）。"""
    pipelines = runner.KIND_PIPELINES
    for k, factory in pipelines.items():
        # factory 可通过惰性导入拿到真实流水线；绝不回落到 run_pipeline 语义键
        assert k != "run_pipeline", "默认 exit 不得是竞品引擎"
    assert "run_pipeline" not in set(pipelines.keys())


def test_modules_import_clean_after_retire():
    """H2：竞品族退役后，核心模块 + 新 research 模块 import 自洽（无循环/残留 import 崩）。"""
    importlib.import_module("app.core.orchestrator")
    importlib.import_module("app.core.runner")
    research = importlib.import_module("app.core.pipeline.research")
    assert callable(getattr(research, "research_pipeline"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))