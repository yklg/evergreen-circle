"""基于新证据异步精修报告（计划 §3.4 / §5.2）。

TDD 规格，契约见 blazing-vortex-einstein-D1XyWvhG.md。
覆盖「异步架构基石」：tasks.kind 列 + save_task(kind=) + create_refine_task +
refine_report_pipeline（与 run_pipeline 同事件协议）+ refine-evidence 端点。
实现前除 save_task 默认参数外的用例均为红，落地后转绿。

mock 策略：单测 refine_report_pipeline 时 monkeypatch orchestrator._rewrite_section
（同步 helper，内含阻塞 chat_json）→ 避免真实 LLM；P1-2 验证用 monkeypatch asyncio.to_thread。
运行：backend/ 下 `pytest tests/test_refine_evidence.py -q`（requirements-dev 仅 pytest>=8.0，
异步用例内嵌 asyncio.run，无需 pytest-asyncio）。
"""
import asyncio
import json
import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["VERDA_DB_PATH"] = _TMP.name

from app.core import db  # noqa: E402
from app.core.pipeline.research import engine as orchestrator  # noqa: E402


def _conn():
    return db._connect()


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
        "created_at": db._now(),
        "evidence": evidence,
        # 精修/refine_section 都按 sections 重写，种子必须含章节
        "sections": [{"id": "s1", "title": "核心判断", "paragraphs": ["原段落内容"], "refined": False}],
        "claims": [], "metrics": {},
    }
    db.save_report(report, task_id="")


def _seed_report_with_cred(rid, specs):
    """specs: [(eid, credibility), ...] 写入 reports + evidences（report_id=rid）并设各自 cred。"""
    _make_report(rid, [e for e, _ in specs])
    for eid, cred in specs:
        _conn().execute(
            "UPDATE evidences SET credibility=? WHERE evidence_id=?", (cred, eid))
        _conn().commit()


def _get_report(rid):
    return db.get_report(rid)


# ── 任务 kind 迁移 + save_task 默认参数 ─────────────────────
def test_save_task_kind_default_research():
    """save_task 加默认 kind='research'，既有调用向后兼容。"""
    db.save_task("t_default_1", "竞品分析", {})
    full = db.get_task_full("t_default_1")
    assert full is not None
    # 计划 §3.4：save_task 加 kind 列；未传则默认 research
    assert full.get("kind") == "research"


def test_tasks_kind_migration_idempotent():
    """全新临时库 reload → tasks 含 kind 列；重复迁移不报错（复用 collect:314 模板）。"""
    import importlib
    fresh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    saved = os.environ.get("VERDA_DB_PATH")
    os.environ["VERDA_DB_PATH"] = fresh.name
    try:
        importlib.reload(db)
        cols = [r[1] for r in db._connect().execute("PRAGMA table_info(tasks)").fetchall()]
        assert "kind" in cols
        # 再跑一次迁移逻辑必须幂等
        db._init_schema(db._connect())
        cols2 = [r[1] for r in db._connect().execute("PRAGMA table_info(tasks)").fetchall()]
        assert "kind" in cols2
    finally:
        os.environ["VERDA_DB_PATH"] = saved
        importlib.reload(db)


# ── create_refine_task 生成 kind=refine 任务（计划 §3.4）──────
def test_create_refine_task_kind():
    """create_refine_task(rid,[eids],70) → 返回 taskId；get_task_full: kind=='refine'、
    clarifications 含 report_id/evidence_ids/min_cred、query==rid。"""
    res = orchestrator.create_refine_task("r_ct_1", ["e_ct_1"], 70)
    assert res and res.get("taskId")
    tid = res["taskId"]
    full = db.get_task_full(tid)
    assert full is not None
    assert full.get("kind") == "refine"
    clar = full.get("clarifications", {})
    assert clar.get("report_id") == "r_ct_1"
    assert clar.get("evidence_ids") == ["e_ct_1"]
    assert clar.get("min_cred") == 70
    assert full.get("query") == "r_ct_1"


# ── refine_report_pipeline：cred 过滤 / 边界 / 子集 / 无高质 → error ──
def _fake_rewrite(section, extra_context, system_prompt):
    """替换 _rewrite_section：直接就地标注 refined（不调 LLM）。"""
    section["paragraphs"] = ["重写段落：" + section.get("title", "")]
    section["refined"] = True
    absorbed = extra_context.get("absorbed_evidence_ids", []) if isinstance(extra_context, dict) else []
    section["absorbed_evidence_ids"] = absorbed
    return section


async def _drain(pipeline_coro):
    events = []
    async for ev in pipeline_coro:
        events.append(ev)
    return events


def test_refine_pipeline_filters_by_cred(monkeypatch):
    """报告证据 cred 90/50，min_cred=70 → 仅≥70 被吸收、段落重写、refined、absorbed 设。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_fc_1", [("e_fc_hi", 90.0), ("e_fc_lo", 50.0)])

    async def _real():
        tid = orchestrator.create_refine_task("r_fc_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    events = asyncio.run(_real())
    rep = _get_report("r_fc_1")
    refined = [s for s in rep.get("sections", []) if s.get("refined")]
    assert refined, "应有章节被标 refined"
    # 吸收的证据来自 cred>=70
    all_abs = [a for s in refined for a in s.get("absorbed_evidence_ids", [])]
    assert "e_fc_hi" in all_abs
    assert "e_fc_lo" not in all_abs


def test_refine_pipeline_min_cred_boundary(monkeypatch):
    """cred==70 含 / ==69 不含（边界等价类）。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_bd_1", [("e_bd_eq", 70.0), ("e_bd_lo", 69.0)])
    import asyncio as _a

    async def _real():
        tid = orchestrator.create_refine_task("r_bd_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    _a.run(_real())
    rep = _get_report("r_bd_1")
    all_abs = [a for s in rep.get("sections", []) for a in s.get("absorbed_evidence_ids", [])]
    assert "e_bd_eq" in all_abs
    assert "e_bd_lo" not in all_abs


def test_refine_pipeline_evidence_ids_subset(monkeypatch):
    """指定 evidence_ids，仅这些被考虑；其余高 cred 忽略。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_sub_1", [("e_sub_a", 90.0), ("e_sub_b", 90.0)])
    import asyncio as _a

    async def _real():
        tid = orchestrator.create_refine_task("r_sub_1", ["e_sub_a"], 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    _a.run(_real())
    rep = _get_report("r_sub_1")
    all_abs = [a for s in rep.get("sections", []) for a in s.get("absorbed_evidence_ids", [])]
    assert "e_sub_a" in all_abs
    assert "e_sub_b" not in all_abs


def test_refine_pipeline_no_high_cred_error(monkeypatch):
    """全<min_cred → 仅 yield error 事件，且不调用 save_report（报告不被改写）。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_ne_1", [("e_ne_1", 40.0)])

    saved_flag = {"n": 0}

    def _spy_save(rep, task_id=""):
        saved_flag["n"] += 1
        return db.save_report.__wrapped__(rep, task_id) if hasattr(db.save_report, "__wrapped__") else None
    monkeypatch.setattr(db, "save_report", _spy_save, raising=False)

    import asyncio as _a

    async def _real():
        tid = orchestrator.create_refine_task("r_ne_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    events = _a.run(_real())
    assert any(e["type"] == "error" for e in events), "应产出 error 事件"
    assert saved_flag["n"] == 0, "无高质证据时不应 save_report"


def test_refine_pipeline_progress_and_done(monkeypatch):
    """drain → N 个 progress(percent 递增, stage『精修第 i/M 章』) + 末 done{reportId}。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_pd_1", [("e_pd_1", 90.0)])

    import asyncio as _a

    async def _real():
        tid = orchestrator.create_refine_task("r_pd_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    events = _a.run(_real())
    progresses = [e for e in events if e["type"] == "progress"]
    assert progresses, "应有 progress 事件"
    percents = [e["data"]["percent"] for e in progresses]
    assert percents == sorted(percents), "percent 应递增"
    assert any("精修第" in e["data"].get("stage", "") for e in progresses)
    dones = [e for e in events if e["type"] == "done"]
    assert dones and dones[-1]["data"].get("reportId") == "r_pd_1"


def test_refine_pipeline_persists_on_done(monkeypatch):
    """done 后段落 saved、refined + absorbed 落库。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_ps_1", [("e_ps_1", 90.0)])

    import asyncio as _a

    async def _real():
        tid = orchestrator.create_refine_task("r_ps_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    _a.run(_real())
    rep = _get_report("r_ps_1")
    assert any(s.get("refined") for s in rep.get("sections", []))


def test_refine_pipeline_uses_to_thread(monkeypatch):
    """P1-2：_rewrite_section 必须经由 asyncio.to_thread 调用，避免阻塞事件循环。"""
    calls = []
    real_tt = asyncio.to_thread

    async def _spy_tt(func, *args):
        calls.append((func, args))
        return await real_tt(func, *args)
    monkeypatch.setattr(asyncio, "to_thread", _spy_tt)
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_tt_1", [("e_tt_1", 90.0)])

    async def _real():
        tid = orchestrator.create_refine_task("r_tt_1", None, 70)["taskId"]
        return await _drain(orchestrator.refine_report_pipeline(tid))
    asyncio.run(_real())
    assert any(fn is orchestrator._rewrite_section or getattr(fn, "__name__", "") == "_rewrite_section"
               for fn, _ in calls), "应有一次 to_thread(_rewrite_section)"


def test_refine_section_refactor_regression(monkeypatch):
    """F 重构守护：抽 _rewrite_section 后，既有 refine_section 行为不变（段落重写 + refined）。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _seed_report_with_cred("r_rf_1", [("e_rf_1", 90.0)])
    res = orchestrator.refine_section("r_rf_1", _get_report("r_rf_1")["sections"][0]["id"], ["批注"])
    assert res.get("ok") is True
    assert res.get("section", {}).get("refined") is True


def test_refine_endpoint_returns_taskid():
    """POST /api/reports/{id}/refine-evidence → 200 + {taskId}；tasks 行 kind=refine。"""
    from fastapi.testclient import TestClient
    from app.main import app
    _seed_report_with_cred("r_ep_1", [("e_ep_1", 90.0)])
    client = TestClient(app)
    r = client.post("/api/reports/r_ep_1/refine-evidence", json={"min_cred": 70})
    assert r.status_code == 200, r.status_code
    j = r.json()
    assert j.get("taskId")
    full = db.get_task_full(j["taskId"])
    assert full.get("kind") == "refine"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
