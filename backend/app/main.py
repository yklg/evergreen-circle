"""青野 Verda 后端入口（FastAPI）。

挂载：48 专家 API + 任务创建/澄清 + SSE 思维流 + 报告/历史 + 仪表盘统计
+ 全局证据溯源库 + 目的地持续追踪订阅 + 专家工作量看板 + 健康/验证接口。
真实 LLM（智谱 GLM）+ 真实搜索（博查 Bocha）+ 真实抓取 + SQLite 持久化，绝不 demo。
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import db
from app.core import research_types as rt
from app.core.llm import LLMModelUnavailable, LLMNotConfigured, chat
from app.core.research_types import DEFAULT_RESEARCH_TYPE
import logging
from app.core.orchestrator import create_task, run_pipeline, submit_clarify, refine_section, generate_clarify, create_refine_task, create_brief_task, GuideSingleDestinationError, ClarifyAnswerRequiredError
from app.core import runner
from app.core.runtime_config import (
    GROUP_FIELDS,
    SECRET_KEYS,
    SettingsValidationError,
    apply_settings,
    configured_flags,
    get_effective_settings,
    mask_effective,
    migrate_legacy_settings,
    migrate_model_values,
)
from app.core.search import search
from app.core.user_prefs import (
    PrefsValidationError,
    apply_prefs,
    prefs_doc,
)
from app.data import expert_by_id, load_experts

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动编排：配置键迁移（键名泛化 zhipu_* → llm_*）显式执行，fail-fast。

    并回收孤儿 running：进程重启后内存里的实时任务已丢，DB 仍标记 running 会
    让前端悬浮条永久转圈，这里统一标 failed。
    """
    migrate_legacy_settings()
    migrate_model_values()
    runner.reconcile_orphans()
    yield


app = FastAPI(title="青野 Verda API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 基础 / 健康 ─────────────────────────────────────────
@app.get("/")
def root():
    return {
        "name": "青野 Verda API",
        "version": "2.0.0",
        "slogan": "让每个结论都有出处，让每次调研都活着。",
        "llm_configured": bool(get_effective_settings().get("llm_api_key")),
        "experts": len(load_experts()),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_configured": bool(get_effective_settings().get("llm_api_key")),
    }


@app.get("/api/llm/ping")
def llm_ping():
    try:
        reply = chat(
            [
                {"role": "system", "content": "你只回复一个词。"},
                {"role": "user", "content": "请回复：可用"},
            ],
            max_tokens=200,
        )
        return {
            "ok": True,
            "model": get_effective_settings().get("llm_model"),
            "reply": reply.strip(),
        }
    except LLMNotConfigured as e:
        return {"ok": False, "reason": "not_configured", "message": str(e)}
    except LLMModelUnavailable as e:
        return {
            "ok": False,
            "reason": "model_unavailable",
            "message": str(e),
            "suggested_model": e.suggested_model,
        }
    except Exception as e:  # noqa: BLE001
        from app.core.llm import is_temporary_unavailable

        if is_temporary_unavailable(e):
            return {
                "ok": False,
                "reason": "temporarily_unavailable",
                "message": "当前模型服务负载较高（503），请稍后 30 秒左右重试。",
            }
        return {"ok": False, "reason": "error", "message": str(e)}


def _normalize_model_id(mid: str) -> str:
    """评审 P0：剥离 Google OpenAI-兼容网关返回的命名空间前缀 `models/`。

    使用捕获组提取（^models/(.+)$），绝不全局替换，避免误伤模型名本体——
    例如 tuned 模型 `publishers/google/models/xxx` 不以 `models/` 开头，应原样保留。
    """
    return re.sub(r"^models/(.+)$", r"\1", mid)


@app.get("/api/llm/models")
def list_provider_models():
    """运行时从厂商拉取模型列表（enrichment layer）。

    仅服务端读取已保存的 llm_base_url + llm_api_key，密钥不出服务端、不回传前端。
    失败（未配置 / 网络 / 401 / 非标准响应）→ 返回 ok:false，前端静默回退硬编码预设。
    """
    eff = get_effective_settings()
    base = eff.get("llm_base_url")
    key = eff.get("llm_api_key")
    if not base or not key:
        return {"ok": False, "reason": "no-credential"}
    try:
        r = httpx.get(
            f"{base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        # 评审 P0：剥离 Google OpenAI-兼容网关返回的命名空间前缀 `models/`，
        # 用捕获组提取，绝不全局替换（避免误伤本体含 models/ 的模型名，如 publishers/.../models/...）。
        ids = [_normalize_model_id(m["id"]) for m in data if isinstance(m, dict) and m.get("id")]
        return {"ok": True, "models": ids}
    except Exception as e:  # noqa: BLE001
        # 评审 P2：记录原始响应片段，便于排查 Gemini 等厂商的 /models 非标格式
        _logger.warning(
            "enrichment /models 拉取失败 base=%s status=%s body=%s",
            base,
            getattr(e, "status_code", None),
            (r.text[:300] if "r" in dir() and hasattr(r, "text") else ""),
        )
        return {"ok": False, "reason": "fetch_failed"}


# ── 运行时配置（供「模型配置」页使用）─────────────────────
class SettingsPatch(BaseModel):
    patch: Dict[str, Any] = {}


@app.get("/api/settings")
def get_settings_api():
    """返回脱敏后的有效配置 + 分组结构 + 各能力是否已配置。

    密钥字段一律返回脱敏值（如 sk-****9f2a），绝不明文回传。
    """
    eff = get_effective_settings()
    return {
        "ok": True,
        "values": mask_effective(eff),
        "secrets": sorted(SECRET_KEYS),
        "groups": GROUP_FIELDS,
        "configured": configured_flags(eff),
    }


@app.put("/api/settings")
def put_settings_api(body: SettingsPatch):
    """保存运行时配置覆盖：校验 → 落库 → 失效缓存与 LLM 客户端。

    - 密钥字段传空字符串 = 保留原值（不修改）。
    - 未知键被忽略。
    - 类型转换失败：整包 422，附带字段级错误信息。
    保存后下一次 LLM/搜索调用即生效，无需重启。
    """
    try:
        eff = apply_settings(body.patch or {})
    except SettingsValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    return {
        "ok": True,
        "values": mask_effective(eff),
        "configured": configured_flags(eff),
    }


# ── 用户级偏好（昵称 / 公司 / 界面选择）────────────────────
# 与 /api/settings 的边界：settings 是系统级运行时配置（脱敏、受 CONFIG_SCHEMA 约束）；
# prefs 是用户级偏好（明文、无密钥、原样返回）。分表分域，见 core/user_prefs.py。
class PrefsPatch(BaseModel):
    patch: Dict[str, Any] = {}


@app.get("/api/prefs")
def get_prefs_api():
    """返回用户偏好全量（**仅库中实际存在的键**）+ 分组元信息。

    刻意不合成默认值：前端首次启动需要靠 `stored` 区分「远端为空（新库）→
    保留本地并上推」与「远端有值 → 以远端为准」，否则会误清用户已有资料。
    """
    return {"ok": True, **prefs_doc()}


@app.put("/api/prefs")
def put_prefs_api(body: PrefsPatch):
    """保存用户偏好：校验 → 落库（单事务）→ 回全量。

    - 未知键被忽略（跨版本兼容）。
    - 类型错误 / 超长：整包 422，附字段级错误，任何键都不落库（不做半写）。
    """
    try:
        values = apply_prefs(body.patch or {})
    except PrefsValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    return {"ok": True, "values": values, "stored": sorted(values.keys())}


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
    mode: str = "deep"  # quick | deep | expert
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
    except ClarifyAnswerRequiredError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "clarify_answer_required", "message": str(e)},
        )


# ── SSE 思维流（纯订阅者；执行由 runner 后台常驻，断连只撤订阅不杀任务）─
@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str, request: Request, sub_id: str = ""):
    runner.ensure_running(task_id)  # 首次连接触发执行；重连只订阅

    async def gen():
        try:
            async for ev in runner.subscribe(task_id):
                if await request.is_disconnected():
                    break  # 仅断订阅，pipeline 继续在后台跑
                etype = ev["type"]
                data = json.dumps(ev["data"], ensure_ascii=False)
                yield f"event: {etype}\ndata: {data}\n\n"
        except asyncio.CancelledError:
            pass  # 客户端断开，订阅协程被取消属正常
        except Exception as e:  # noqa: BLE001
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


# ── 任务运行态查询 / 列表 / 取消（前端悬浮条 + 侧栏入口 + 返回语义依赖）──
@app.get("/api/tasks/{task_id}/status")
def task_status(task_id: str):
    """实时进度与状态；断连后仍在后台跑，此接口可持续返回 running + 增长 percent。"""
    return runner.get_status(task_id)


@app.get("/api/tasks/running")
def tasks_running():
    """进行中的任务列表（供侧栏/悬浮条入口）。"""
    return runner.list_running()


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str):
    """取消进行中的任务（前端返回语义的兜底，正常返回不取消）。"""
    runner.cancel(task_id)
    return {"ok": True}


# ── 澄清问卷 SSE（懒生成；create_task 不再同步调 LLM）─────────
@app.get("/api/tasks/{task_id}/clarify/stream")
async def stream_clarify(task_id: str, request: Request):
    async def gen():
        # 重连/刷新：DB 已有完整问卷则直接推送，避免重复 LLM 调用（P1 重连直读）
        existing, complete = db.get_clarify_questions(task_id)
        if existing and complete:
            yield f"event: clarify_ready\ndata: {json.dumps(existing, ensure_ascii=False)}\n\n"
            return
        task = db.get_task(task_id)
        query = (task or {}).get("query", "") if task else ""
        try:
            async for ev in generate_clarify(task_id, query):
                if await request.is_disconnected():
                    break
                yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
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


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    """删除调研报告（级联清理证据/链路/反馈/任务）。"""
    db.delete_report(report_id)
    return {"ok": True}


# ── 可观测性 Trace（决策链路 / 决策回放）──────────────────
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


# ── 报告反馈（人工修正率 → 业务闭环指标）──────────────────
class FeedbackBody(BaseModel):
    edited_blocks: int = 0
    total_blocks: int = 0
    data: dict = {}


@app.post("/api/reports/{report_id}/feedback")
def post_feedback(report_id: str, body: FeedbackBody):
    db.save_report_feedback(report_id, body.edited_blocks, body.total_blocks, body.data)
    # 同步更新报告内 metrics 的人工修正率
    rep = db.get_report(report_id)
    if rep and rep.get("metrics"):
        from app.core.metrics import apply_feedback
        rep["metrics"] = apply_feedback(rep["metrics"], body.edited_blocks, body.total_blocks)
        db.save_report(rep, task_id="")
    # 派生数据失效钩子：metrics 已变化，简报/一页纸精炼作废（失效即淘汰，防陈旧结论）
    db.invalidate_report_brief(report_id)
    return {"ok": True}


# ── 简报一页纸精炼（派生数据，kind='brief' 后台任务 + SSE 订阅）──
@app.post("/api/reports/{report_id}/brief")
def post_brief(report_id: str):
    """创建「生成一页纸精炼」的后台任务（G7，已从同步端点迁移）。

    不再同步阻塞 HTTP：返回 {taskId}，前端订阅 GET /api/tasks/{taskId}/stream
    消费 progress→done（幂等：已有 brief 走 done 快路径）/ error 事件。
    报告不存在 → 404；LLM 未配置由 brief_report_pipeline 转为 error 事件。
    """
    if not db.get_report(report_id):
        raise HTTPException(status_code=404, detail="报告不存在或未就绪")
    return create_brief_task(report_id)


# ── 按批注深化章节（人工介入二次调研）────────────────────
class RefineBody(BaseModel):
    section_id: str
    annotations: List[str] = []


@app.post("/api/reports/{report_id}/refine")
def post_refine(report_id: str, body: RefineBody):
    res = refine_section(report_id, body.section_id, body.annotations)
    # 派生数据失效钩子：章节正文已改写，简报/一页纸精炼作废
    db.invalidate_report_brief(report_id)
    return res


# ── 基于新证据异步精修报告（kind=refine 后台任务）──────────
class RefineEvidenceBody(BaseModel):
    evidence_ids: List[str] = []
    min_cred: float = 70.0


@app.post("/api/reports/{report_id}/refine-evidence")
def refine_evidence(report_id: str, body: RefineEvidenceBody):
    """基于新补充的高可信度证据精修报告正文。

    仅创建一个 kind='refine' 的后台任务并返回 {taskId}（同步快路径，无阻塞 LLM 调用）。
    前端拿 taskId 订阅既有 GET /api/tasks/{taskId}/stream 获取进度/取消/重连。
    """
    if not db.get_report(report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    return create_refine_task(
        report_id,
        body.evidence_ids or None,
        body.min_cred,
    )


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
    report_id: Optional[str] = None,
):
    # report_id 过滤：不传 → 全部证据；'<rid>' → 仅该报告证据。
    items = db.query_evidences(
        destination=destination, source_type=source_type, min_cred=min_cred,
        limit=limit, report_id=report_id,
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
