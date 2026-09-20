"""M2 · 生活圈体检流水线：A4 事件契约 / 落库独立文档 / D4 完整报告结构。

以 fixture 数据模式驱动（无网络），覆盖：
  - 事件序列（intake→…→audit 阶段顺序单调；report_ready/done 双字段）
  - 报告落库（living_circle_reports 独立文档，report_type 弱关联）
  - assemble_report 结构（章节/结论/证据/专家队/渲染适配器判据）
"""
import asyncio

from app.core import db
from app.core.pipeline.living_circle import (
    STAGES,
    create_living_circle_task,
    living_circle_pipeline,
)

KAILI = {
    "scene_name": "凯里老街",
    "city": "贵州·凯里",
    "address": "凯里市西门街道老街片区",
    "center": [107.9758, 26.5734],
    "study_radius_m": 2500.0,
    "mode": "standard",
    "data_mode": "fixture",  # 测试无网络：fixture 分支
}


def _run_pipeline(task_id: str) -> list:
    async def _impl():
        events = []
        async for ev in living_circle_pipeline(task_id):
            events.append(ev)
        return events

    return asyncio.run(_impl())


def test_pipeline_event_contract():
    """A4：事件类型白名单 + 阶段顺序单调 + 收尾 report_ready/done 双字段。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    types = [e["type"] for e in events]
    allowed = {"node_update", "message", "progress", "evidence", "report_ready", "done"}
    assert set(types) <= allowed
    assert "report_ready" in types and "done" in types

    # progress 阶段序列：与 STAGES 顺序一致且单调
    progress = [e["data"] for e in events if e["type"] == "progress"]
    assert progress, "必须产生进度事件"
    stage_idx = {s: i for i, s in enumerate(STAGES)}
    for prev, cur in zip(progress, progress[1:]):
        assert stage_idx[cur["stage"]] >= stage_idx[prev["stage"]]
        assert cur["percent"] >= prev["percent"]
    # 尾进度 100
    assert progress[-1]["percent"] == 100

    ready = next(e for e in events if e["type"] == "report_ready")
    done = next(e for e in events if e["type"] == "done")
    # 双字段兼容（runner 传统 reportId + 前端 A4 report_id）
    assert ready["data"]["reportId"] == ready["data"]["report_id"]
    assert done["data"]["report_id"] == ready["data"]["report_id"]


def test_pipeline_persists_independent_document():
    """A1：落库 living_circle_reports（独立文档，report_type 弱关联）。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    assert rep is not None
    assert rep["report_type"] == "living_circle"
    # 断言**快照性质与内部自洽**，而不是钉死具体分值：夹具是真实实跑快照，
    # 一旦用真实 AK 重算（AK 配额 / 路网变化），硬编码分值会把这条"落库链路"用例带成假红。
    lc = rep["living_circle"]
    assert lc["scene"]["name"] == "凯里老街"
    assert lc["data_origin"] == "live"
    assert 0 <= lc["scores"]["total"] <= 100
    assert len(lc["scores"]["triads"]) == 3
    assert len(lc["isochrones"]) == 4
    # 空间口径举证随报告一起落库（Q1/Q2 的可判据化必须活到持久层）
    cal = lc["caliber"]
    assert cal["collect_radius_m"] >= cal["reach_circumradius_m"] * 0.999
    assert cal["cells_judged"] + cal["cells_unknown"] == cal["cells_inside"]
    assert len(lc["blindspots"]) <= cal["cells_judged"], "盲区数不可能超过可判定格数"
    records = db.list_living_circle_reports()
    assert any(r["id"] == rid for r in records)
    # task 终态完成
    task = db.get_task_full(tid)
    assert task["status"] == "done"
    assert task["report_id"] == rid


def test_pipeline_assemble_report_structure():
    """D4：8 章节 / 结论带专家署名 / 证据闭环 / toc 对齐。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)

    assert len(rep["sections"]) >= 8
    for need in ["overview", "medical", "education", "market", "elderly", "isochrone", "blindspot", "conclusion"]:
        assert any(s["id"] == need for s in rep["sections"])
    assert [t["id"] for t in rep["toc"]] == [s["id"] for s in rep["sections"]]
    # 结论专家署名 + 证据引用可解析
    ev_ids = {e["evidence_id"] for e in rep["evidence"]}
    assert len(rep["claims"]) > 5
    for c in rep["claims"]:
        assert c.get("author"), "结论必须带专家署名（D4）"
        for eid in c["evidence_ids"]:
            assert eid in ev_ids
    # 盲区章节表格与盲区数一致
    bs_sec = next(s for s in rep["sections"] if s["id"] == "blindspot")
    assert bs_sec["data_grid"]["rows"] == [] or len(bs_sec["data_grid"]["rows"]) == len(rep["living_circle"]["blindspots"])
    # dispatch 与专家表闭合
    assert any(d["id"] == "L3-001" for d in rep["dispatch"])


def test_pipeline_report_has_caliber_field():
    """R2/R6：报告顶层包含 caliber 举证对象，记录出行方式、速度、绕行系数等口径。

    注：`sample_profile` 断言的是**夹具自述的采样档**——权威快照由
    `scripts/snapshot_live.py` 以 `mode="standard"` 实跑生成，两者必须一致。
    """
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    
    lc = rep["living_circle"]
    assert "caliber" in lc, "生活圈报告必须包含 caliber 字段"
    cal = lc["caliber"]
    assert cal["travel_mode"] == "walking"
    assert isinstance(cal["speed_m_per_min"], (int, float))
    assert isinstance(cal["detour_k"], (int, float))
    assert isinstance(cal["study_radius_m"], int)
    assert isinstance(cal["iso_minutes"], list)
    assert isinstance(cal["basis"], str) and len(cal["basis"]) > 0
    assert cal["measured"] is True  # walking 是实测
    assert cal["sample_profile"] == "standard"
    # ── 空间口径三概念（可达区 / 采集区 / 研究区）必须显式举证 ──
    assert cal["reach_full_min"] == 20.0
    assert cal["reach_radius_bound_m"] > 0
    assert cal["reach_circumradius_m"] > 0
    assert cal["collect_radius_m"] >= cal["reach_circumradius_m"] * 0.999
    assert cal["collect_margin_m"] >= 0
    assert cal["cells_judged"] + cal["cells_unknown"] == cal["cells_inside"]


def test_create_task_requires_pipeline_kind():
    tid = create_living_circle_task(KAILI)
    task = db.get_task_full(tid)
    assert task["kind"] == "living_circle"
    assert (task["clarifications"] or {}).get("center") == [107.9758, 26.5734]


def test_pipeline_resolves_center_without_coordinates():
    """M3：纯地名输入（无 center）→ 按场景名匹配 fixture 样例中心（凯里老街兜底）。"""
    params = {k: v for k, v in KAILI.items() if k != "center"}
    tid = create_living_circle_task(params)
    assert not (db.get_task_full(tid)["clarifications"] or {}).get("center")
    events = _run_pipeline(tid)
    intake = next(e for e in events if e["type"] == "message" and e["data"]["stage"] == "intake")
    assert "107.9758, 26.5734" in intake["data"]["text"]
    # 未匹配样例名的场景回退默认样区
    tid2 = create_living_circle_task({**params, "scene_name": "不存在的小区"})
    events2 = _run_pipeline(tid2)
    intake2 = next(e for e in events2 if e["type"] == "message" and e["data"]["stage"] == "intake")
    assert "107.9758, 26.5734" in intake2["data"]["text"]