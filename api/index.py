"""青野 Verda 后端入口（FastAPI）。

挂载：48 专家 API + 任务创建/澄清 + SSE 思维流 + 报告/历史 + 仪表盘统计
+ 全局证据溯源库 + 目的地持续追踪订阅 + 专家工作量看板 + 健康/验证接口。
真实 LLM（智谱 GLM）+ 真实搜索（博查 Bocha）+ 真实抓取 + SQLite 持久化，绝不 demo。
"""
from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

# Vercel Python runtime 把函数代码放在 /var/task/api/index.py。
# app/ 包位于同级 api/app/ 目录下，需要显式把 api/ 目录加入 Python 搜索路径。
_API_DIR = os.path.dirname(os.path.abspath(__file__))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import db
from app.core import research_types as rt
from app.core.config import get_settings
from app.core.llm import LLMNotConfigured, chat
from app.core.orchestrator import create_task, run_pipeline, submit_clarify, refine_section, GuideSingleDestinationError
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core.search import search
from app.data import expert_by_id, load_experts

settings = get_settings()

app = FastAPI(title="青野 Verda API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 基础 / 健康 ─────────────────────────────────────────
# 注意：根路径 / 留给前端静态页面（index.html），FastAPI 不占根路由


@app.get("/health")
def health():
    return {"status": "ok", "llm_configured": settings.llm_configured}


@app.get("/api/llm/ping")
def llm_ping():
    try:
        reply = chat(
            [
                {"role": "system", "content": "你只回复一个词。"},
                {"role": "user", "content": "请回复：可用"},
            ],
            max_tokens=16,
        )
        return {"ok": True, "model": settings.zhipu_model, "reply": reply}
    except LLMNotConfigured as e:
        return {"ok": False, "reason": "not_configured", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "error", "message": str(e)}


@app.get("/api/search")
def search_endpoint(q: str, num: int = 10, site: Optional[str] = None):
    try:
        results = search(q, num=num, site=site)
        return {"ok": True, "query": q, "site": site, "results": results}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "query": q, "reason": "error", "message": str(e)}


# ── 专家 ────────────────────────────────────────────────
@app.get("/api/experts")
def list_experts():
    return load_experts()


@app.get("/api/experts/workload")
def experts_workload():
    """专家工作量看板：真实累计任务/产出论点/采集证据。"""
    stats = {s["expert_id"]: s for s in db.expert_workload()}
    out = []
    for e in load_experts():
        s = stats.get(e["id"])
        out.append({
            "id": e["id"],
            "name": e.get("name", e["id"]),
            "title": e.get("role_title", ""),
            "layer": e.get("level", ""),
            "avatar": e.get("avatar", ""),
            "missions": s["missions"] if s else 0,
            "claims_authored": s["claims_authored"] if s else 0,
            "evidence_collected": s["evidence_collected"] if s else 0,
            "last_active": s["last_active"] if s else "",
        })
    out.sort(key=lambda x: (x["missions"], x["claims_authored"], x["evidence_collected"]), reverse=True)
    return out


@app.get("/api/experts/{eid}")
def get_expert(eid: str):
    e = expert_by_id(eid)
    if not e:
        return {"ok": False, "message": "not found"}
    stat = next((s for s in db.expert_workload() if s["expert_id"] == eid), None)
    return {**e, "stats": stat or {"missions": 0, "claims_authored": 0, "evidence_collected": 0, "last_active": ""}}


# ── 任务 / 澄清 ─────────────────────────────────────────
class CreateTaskBody(BaseModel):
    query: str
    mode: str = "deep"
    type: str = DEFAULT_RESEARCH_TYPE  # guide（游玩攻略）| assessment（调研评估）
    model: Optional[str] = None  # 用户选择的分析模型；空/'Auto'/None 表示按 settings 编排


@app.get("/api/research-types")
def research_types():
    """调研类型选择器数据源（首页卡片），与后端注册表单一真相源。"""
    return rt.research_type_options()


@app.post("/api/tasks")
def post_task(body: CreateTaskBody):
    return create_task(body.query, mode=body.mode, model=body.model, research_type=body.type)


class ClarifyBody(BaseModel):
    answers: dict = {}


@app.post("/api/tasks/{task_id}/clarify")
def post_clarify(task_id: str, body: ClarifyBody):
    try:
        return submit_clarify(task_id, body.answers)
    except GuideSingleDestinationError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "guide_single_destination", "message": str(e)},
        )


# ── SSE 思维流 ──────────────────────────────────────────
@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str, request: Request, sub_id: str = ""):
    async def gen():
        # 与 runner 同一终态契约：serverless 入口不经 runner，终态在此就地收口
        terminal_seen = False
        try:
            async for ev in run_pipeline(task_id, sub_id=sub_id):
                if await request.is_disconnected():
                    break
                etype = ev["type"]
                if etype == "error":
                    terminal_seen = True
                    db.set_task_failed(task_id, str(ev["data"].get("message") or "任务失败"))
                elif etype == "done":
                    terminal_seen = True
                data = json.dumps(ev["data"], ensure_ascii=False)
                yield f"event: {etype}\ndata: {data}\n\n"
            if not terminal_seen:
                # 耗尽/断连而未落终态 → 合成 failed，绝不留悬空 running
                msg = "任务异常结束（未落终态）"
                db.set_task_failed(task_id, msg)
                err = json.dumps({"message": msg}, ensure_ascii=False)
                yield f"event: error\ndata: {err}\n\n"
        except Exception as e:  # noqa: BLE001
            db.set_task_failed(task_id, str(e))
            err = json.dumps({"message": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 报告 / 历史（持久化）─────────────────────────────────
@app.get("/api/reports")
def list_reports():
    """我的调研：真实历史报告列表（卡片，不含全文）。"""
    return db.list_reports()


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    rep = db.get_report(report_id)
    if not rep:
        return {"ok": False, "message": "report not ready"}
    return rep


# ── 可观测性 Trace + 反馈 + 批注深化 ──────────────────────
@app.get("/api/tasks/{task_id}/trace")
def get_task_trace(task_id: str):
    from app.core import trace as _trace
    spans = _trace.get_trace(task_id) or db.get_traces_by_task(task_id)
    return {"taskId": task_id, "spans": spans}


@app.get("/api/reports/{report_id}/trace")
def get_report_trace(report_id: str):
    spans = db.get_traces_by_report(report_id)
    if not spans:
        rep = db.get_report(report_id)
        spans = (rep or {}).get("trace", [])
    return {"reportId": report_id, "spans": spans}


class FeedbackBody(BaseModel):
    edited_blocks: int = 0
    total_blocks: int = 0
    data: dict = {}


@app.post("/api/reports/{report_id}/feedback")
def post_feedback(report_id: str, body: FeedbackBody):
    db.save_report_feedback(report_id, body.edited_blocks, body.total_blocks, body.data)
    rep = db.get_report(report_id)
    if rep and rep.get("metrics"):
        from app.core.metrics import apply_feedback
        rep["metrics"] = apply_feedback(rep["metrics"], body.edited_blocks, body.total_blocks)
        db.save_report(rep, task_id="")
    return {"ok": True}


class RefineBody(BaseModel):
    section_id: str
    annotations: List[str] = []


@app.post("/api/reports/{report_id}/refine")
def post_refine(report_id: str, body: RefineBody):
    return refine_section(report_id, body.section_id, body.annotations)


# ── 仪表盘（真实统计）───────────────────────────────────
@app.get("/api/dashboard")
def dashboard():
    return db.dashboard_stats()


# ── 全局证据溯源库 ──────────────────────────────────────
@app.get("/api/evidences")
def evidences(
    destination: Optional[str] = None,
    source_type: Optional[str] = None,
    min_cred: float = 0.0,
    limit: int = 200,
):
    items = db.query_evidences(
        destination=destination, source_type=source_type, min_cred=min_cred, limit=limit,
    )
    return {"items": items, "facets": db.evidence_facets()}


# ── 目的地持续追踪订阅 ──────────────────────────────────
class SubscriptionBody(BaseModel):
    query: str
    destinations: List[str] = []
    type: str = DEFAULT_RESEARCH_TYPE


@app.get("/api/subscriptions")
def list_subscriptions():
    return db.list_subscriptions()


@app.post("/api/subscriptions")
def create_subscription(body: SubscriptionBody):
    import uuid
    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    return db.create_subscription(sub_id, body.query, body.destinations, body.type)


@app.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: str):
    db.delete_subscription(sub_id)
    return {"ok": True}
