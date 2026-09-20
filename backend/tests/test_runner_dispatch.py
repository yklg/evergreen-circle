"""runner._drive 按 tasks.kind 分发（计划 §3.4 / §5.3）。

TDD 规格，验证「精修复用 runner 基建」架构是否真的成立：
- test_runner_dispatch_refine：kind='refine' → _drive 路由到 refine 流水线
- test_runner_dispatch_research_unchanged：kind 缺省 → 仍走调研流水线（run_pipeline→research_pipeline）
- test_refine_cancel_no_partial_corruption：中途取消 → 任务 failed、报告未被部分写坏（原子性）

路由断言统一经 `runner.KIND_PIPELINES` 接缝注入假流水线，以适配封闭注册表
（注册表 import 时捕获函数引用，直接 patch 模块属性不再拦截）。

实现前（tasks 无 kind 列、_drive 无分发分支）：用例红；落地后转绿。
运行：backend/ 下 `pytest tests/test_runner_dispatch.py -q`（异步用例内嵌 asyncio.run）。
"""
import asyncio
import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["VERDA_DB_PATH"] = _TMP.name

from app.core import db, runner  # noqa: E402


def _conn():
    return db._connect()


def _insert_task(task_id, kind, query="r_x"):
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,created_at,kind)"
        " VALUES(?,?,?,?,?,?)",
        (task_id, query, "{}", "created", db._now(), kind),
    )
    _conn().commit()


def _make_report(rid, evidence_ids):
    evidence = [{
        "evidence_id": eid,
        "source_url": "https://example.com/" + eid,
        "source_type": "douyin",
        "domain": "example.com",
        "title": "自带证据 " + eid,
        "excerpt": "摘要内容",
        "credibility": 70.0,
        "collected_by": "tester",
        "brand": "品牌A",
        "captured_at": db._now(),
    } for eid in evidence_ids]
    report = {
        "id": rid, "title": "报告 " + rid, "subtitle": "", "query": "测试查询",
        "brands": ["品牌A"], "experts": [], "cover_image": "",
        "created_at": db._now(), "evidence": evidence, "claims": [], "metrics": {},
    }
    db.save_report(report, task_id="")


def _fake_pipeline(kind_tag, called):
    """返回一个 async generator：记录被调用，并产出 progress + done。"""
    async def _gen(task_id):
        called.append(kind_tag)
        yield {"type": "progress", "data": {"percent": 50, "stage": kind_tag, "evidence_count": 1}}
        yield {"type": "done", "data": {"reportId": db.get_task_full(task_id).get("query")}}
    return _gen


def test_runner_dispatch_refine(monkeypatch):
    """kind='refine' → _drive 路由到 refine 流水线；research 不应被调用。

    路由断言统一走 `runner.KIND_PIPELINES` 接缝（而非模块属性 monkeypatch），
    以适配封闭注册表实现：注册表在 import 时持有函数引用，直接 patch 模块属性不会拦截。
    """
    runner._running.clear()
    refine_calls, research_calls = [], []
    monkeypatch.setattr(runner, "KIND_PIPELINES", {
        "research": _fake_pipeline("research", research_calls),
        "refine": _fake_pipeline("refine", refine_calls),
    }, raising=False)

    async def _scenario():
        _insert_task("t_disp_refine_1", "refine", query="r_dr_1")
        runner.ensure_running("t_disp_refine_1")
        await asyncio.sleep(0.25)  # 让后台 _drive 跑完
    asyncio.run(_scenario())
    assert refine_calls == ["refine"], "应路由到 refine_report_pipeline"
    assert research_calls == [], "run_pipeline 不应被调用"
    assert db.get_task_full("t_disp_refine_1")["status"] == "done"


def test_runner_dispatch_research_unchanged(monkeypatch):
    """kind 缺省（runner 归一为 'research'）→ 仍走调研流水线，refine 不触发。

    语义与源项目一致（缺省＝调研），仅被测对象 run_pipeline→research_pipeline，
    断言经 `runner.KIND_PIPELINES` 接缝完成。
    """
    runner._running.clear()
    refine_calls, research_calls = [], []
    monkeypatch.setattr(runner, "KIND_PIPELINES", {
        "research": _fake_pipeline("research", research_calls),
        "refine": _fake_pipeline("refine", refine_calls),
    }, raising=False)

    async def _scenario():
        # 缺省 kind（INSERT 不含 kind 列，等价于未迁移旧任务）
        _conn().execute(
            "INSERT INTO tasks(task_id,query,clarifications,status,created_at)"
            " VALUES(?,?,?,?,?)", ("t_disp_research_1", "r_dre_1", "{}", "created", db._now()))
        _conn().commit()
        runner.ensure_running("t_disp_research_1")
        await asyncio.sleep(0.25)
    asyncio.run(_scenario())
    assert research_calls == ["research"], "缺省 kind 应仍走调研流水线"
    assert refine_calls == [], "refine 不应被调用"
    assert db.get_task_full("t_disp_research_1")["status"] == "done"


def test_runner_dispatch_brief(monkeypatch):
    """kind='brief' → _drive 路由到 brief 流水线；research/refine 均不应被调用（G7/B-01；经 KIND_PIPELINES 接缝断言）。"""
    runner._running.clear()
    refine_calls, research_calls, brief_calls = [], [], []
    monkeypatch.setattr(runner, "KIND_PIPELINES", {
        "research": _fake_pipeline("research", research_calls),
        "refine": _fake_pipeline("refine", refine_calls),
        "brief": _fake_pipeline("brief", brief_calls),
    }, raising=False)

    async def _scenario():
        _insert_task("t_disp_brief_1", "brief", query="r_db_1")
        runner.ensure_running("t_disp_brief_1")
        await asyncio.sleep(0.25)
    asyncio.run(_scenario())
    assert brief_calls == ["brief"], "应路由到 brief_report_pipeline"
    assert research_calls == [] and refine_calls == [], "run/refine 不应被调用"
    assert db.get_task_full("t_disp_brief_1")["status"] == "done"


def test_refine_cancel_no_partial_corruption(monkeypatch):
    """启动 refine → 中途取消 → 任务 failed；报告未被部分 save（原子性，P2-7）。"""
    runner._running.clear()
    _make_report("r_cancel_1", ["e_cancel_1"])

    # refine 模拟：先产一个 progress 后挂起，便于中途取消
    async def _slow_refine(task_id):
        yield {"type": "progress", "data": {"percent": 30, "stage": "精修第1/1章", "evidence_count": 1}}
        await asyncio.sleep(5.0)  # 长任务，供测试在其间取消
        yield {"type": "done", "data": {"reportId": "r_cancel_1"}}
    monkeypatch.setattr(runner, "KIND_PIPELINES", {"refine": lambda tid: _slow_refine(tid)}, raising=False)

    async def _scenario():
        _insert_task("t_cancel_1", "refine", query="r_cancel_1")
        runner.ensure_running("t_cancel_1")
        await asyncio.sleep(0.1)        # 让 progress 产出
        runner.cancel("t_cancel_1")      # 中途取消
        await asyncio.sleep(0.1)
    asyncio.run(_scenario())
    assert db.get_task_full("t_cancel_1")["status"] == "failed"
    # 报告段落不应被标 refined（未走到 done 的 save）
    rep = db.get_report("r_cancel_1")
    assert not any(s.get("refined") for s in rep.get("sections", [])), "取消后报告不应被部分写坏"


def test_runner_subscribe_terminal_done_no_rerun():
    """B-03：终态(done)任务重连订阅 → subscribe 首条即补 done{reportId}，不重跑原 pipeline。"""
    runner._running.clear()
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,report_id,created_at,kind)"
        " VALUES(?,?,?,?,?,?,?)",
        ("t_terminal_1", "r_term_1", "{}", "done", "r_term_1", db._now(), "brief"),
    )
    _conn().commit()

    async def _scenario():
        events = []
        async for ev in runner.subscribe("t_terminal_1"):
            events.append(ev)
            break  # 只取首帧验证补帧路径
        return events
    events = asyncio.run(_scenario())
    assert events[0]["type"] == "done", "终态补帧首条应为 done"
    assert events[0]["data"]["reportId"] == "r_term_1"
    # 只读终态句柄：无活 asyncio.Task（不重跑）
    assert runner._running["t_terminal_1"].alive is False
    # DB 任务不新增运行：status/report_id 保持终态
    full = db.get_task_full("t_terminal_1")
    assert full["status"] == "done" and full["report_id"] == "r_term_1"


def test_runner_subscribe_terminal_failed_no_rerun():
    """B-03（失败侧）：终态(failed)任务重连 → 首条补 error{message}，不重跑。"""
    runner._running.clear()
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,error,report_id,created_at,kind)"
        " VALUES(?,?,?,?,?,?,?,?)",
        ("t_terminal_2", "r_term_2", "{}", "failed", "LLM 未配置", None, db._now(), "brief"),
    )
    _conn().commit()

    async def _scenario():
        events = []
        async for ev in runner.subscribe("t_terminal_2"):
            events.append(ev)
            break
        return events
    events = asyncio.run(_scenario())
    assert events[0]["type"] == "error", "终态补帧失败侧首条应为 error"
    assert events[0]["data"]["message"] == "LLM 未配置"
    assert runner._running["t_terminal_2"].alive is False


def test_runner_success_stream_no_error_events(monkeypatch):
    """🔵 BE-2（覆盖拓展方案）· 成功流零 error 哨兵：正常 pipeline 的事件流不得出现 error。

    与 P0-1 广播用例（BE-1，随实施方案阶段 2 落地）成对探针：
    失败场景 error 计数==1、成功场景 error 计数==0 —— 防 _drive except 广播实现
    范围过宽把成功流也标错。被测范围：_drive 广播路径（订阅者视角，非终态补帧）。
    """
    runner._running.clear()
    research_calls: list = []
    monkeypatch.setattr(runner, "KIND_PIPELINES", {
        "research": _fake_pipeline("research", research_calls),
    }, raising=False)

    async def _scenario():
        _insert_task("t_noerr_1", "research", query="r_noerr_1")
        events = []
        # subscribe 内部 ensure_running；流在 stream_end 处自然终止
        # （stream_end 由 subscribe 内部消费、不下发给消费方，故收尾即 done）
        async for ev in runner.subscribe("t_noerr_1"):
            events.append(ev)
        return events

    events = asyncio.run(_scenario())
    types = [e["type"] for e in events]
    assert "done" in types, "正常流水线必须以 done 收尾"
    assert "error" not in types, "成功流不得出现 error 事件（广播过度动作哨兵）"
    assert types[-1] == "done"
    assert research_calls == ["research"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
