
"""青野 Verda 后端入口（FastAPI）。

挂载：48 专家 API + 任务创建/澄清 + SSE 思维流 + 报告/历史 + 仪表盘统计
+ 全局证据溯源库 + 竞品监控订阅 + 专家工作量看板 + 健康/验证接口。
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
from pydantic import BaseModel, field_validator

from app.living_circle.geo_utils import parse_bd_lnglat

from app.core import db
from app.core.llm import LLMModelUnavailable, LLMNotConfigured, chat
import logging
from app.core.orchestrator import create_task, run_pipeline, submit_clarify, refine_section, generate_clarify, create_refine_task, create_brief_task
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
    """启动编排：配置键迁移（键名泛化 zhipu_* -> llm_*）显式执行，fail-fast。

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


@app.get("/api/experts/integrity")
def experts_integrity():
    """名册结构性自检端点 —— 返回问题清单，不影响其他专家端点可用性。"""
    from app.data.schema import validate_roster
    problems = validate_roster(load_experts())
    return {"ok": len(problems) == 0, "problems": problems}


# ── 任务 / 澄清 ─────────────────────────────────────────
class CreateTaskBody(BaseModel):
    query: str
    mode: str = "deep"  # quick | deep | expert
    model: Optional[str] = None  # 用户选择的分析模型；空/'Auto'/None 表示按 settings 编排
    purpose: str = ""  # 目的地产出体裁：''(通用 research) | guide(攻略) | assess(评估) | 其余任意
    # 生活圈体检入参（type=living_circle，A1 独立流水线）
    type: str = "research"
    center: Optional[List[float]] = None  # [lng, lat] BD-09
    city: str = ""
    address: str = ""
    data_mode: str = ""  # ''=auto（live 无 AK 自动降级 fixture） | 'live' | 'fixture'
    travel_mode: str = "walking"  # walking / riding / driving（阶段 3 多方式）
    coord_sys: str = "bd09"  # 入参 center 的坐标系：'bd09' | 'wgs84'（后者由服务端 geoconv 转换）

    @field_validator("center", mode="before")
    @classmethod
    def _validate_center(cls, v):
        """BD-09 经纬度**值域**校验 —— 跨层坐标契约的唯一关口。

        `LngLat` 是裸元组 ``Tuple[float, float]``：BD-09 经纬度、百度墨卡托米、局部平面米
        三者在类型系统里**完全同形**，typing 与 TypeScript 都拦不住（喂错坐标系是「类型正确」的）。
        历史事故：BMapGL ``dragend`` 的 ``e.point`` 是墨卡托平面米
        ``(11440230.81, 2860409.52)``，被当作经纬度穿过 API → 落库 → 报告 ``scene.center``
        → 前端再渲染坏地图；**一次写库，之后每次打开都必现**（自我强化闭环）。

        故契约只能落在值域上，且必须卡在**唯一写入口**（此处）。``mode="before"`` 是有意的：
        在 pydantic 把 ``["107.9", "26.5"]`` 悄悄转成 float 之前就校验原始值——字符串坐标
        本身就是「上游没走契约」的信号，不该被容错掩盖。
        """
        if v is None:
            return None
        parsed = parse_bd_lnglat(v)
        if parsed is None:
            raise ValueError(
                "center 必须是 BD-09 经纬度 [lng, lat]（|lng|<=180 且 |lat|<=90）；"
                f"收到 {v!r}。若来自地图拖拽，注意 BMapGL 的 e.point 是墨卡托平面米，"
                "应取 e.latLng 或 marker.getPosition()"
            )
        return [parsed[0], parsed[1]]


async def _to_bd09(center: List[float], coord_sys: str) -> List[float]:
    """把入参 center 归一到 BD-09（本域**唯一**的合法坐标系）。

    `coord_sys='wgs84'`（浏览器原生定位，无浏览器 AK 时的降级路径）与 BD-09 相差约 600m
    —— 与 15 分钟生活圈同量级。旧实现在这条路上**直接把 WGS-84 当 BD-09 用**，中心静默偏移。

    缺 AK 或转换失败时**拒绝**（422/502），绝不「照抄一个看起来像坐标的值」：
    错中心一旦落库，报告 `scene.center` 就是坏的，之后每次打开都复现。
    """
    if coord_sys != "wgs84":
        return center
    from app.core.config import get_settings

    ak = get_settings().baidu_server_ak
    if not ak:
        raise HTTPException(
            status_code=422,
            detail="收到 WGS-84 坐标，但服务端未配置百度 AK，无法转换为 BD-09；"
                   "请在地图上选点，或直接输入 BD-09 经纬度",
        )
    from app.living_circle.baidu_client import BaiduClient

    client = BaiduClient(ak=ak)
    try:
        # from=1（WGS-84 GPS）→ to=5（BD-09 经纬度）
        conv = await client.geoconv([(float(center[0]), float(center[1]))], from_=1, to=5)
    finally:
        await client.aclose()
    parsed = parse_bd_lnglat(conv[0]) if conv else None
    if parsed is None:
        raise HTTPException(status_code=502, detail="坐标转换（geoconv）返回异常结果，请稍后重试")
    return [parsed[0], parsed[1]]


@app.post("/api/tasks")
async def post_task(body: CreateTaskBody):
    if body.type == "living_circle":
        from app.core.pipeline.living_circle import create_living_circle_task
        from app.living_circle.caliber import get_caliber

        # B1 修复：按 travel_mode 取 caliber.study_radius_m，不再硬编码 2500
        travel_mode = body.travel_mode if body.travel_mode in ("walking", "riding", "driving") else "walking"
        caliber = get_caliber(travel_mode)
        # 坐标系归一：WGS-84 → BD-09（缺 AK 时 422 拒绝，不静默照抄）
        center = await _to_bd09(body.center, body.coord_sys) if body.center else None

        task_id = create_living_circle_task({
            "scene_name": body.query,
            "city": body.city,
            "address": body.address,
            "center": center,
            "study_radius_m": float(caliber.study_radius_m),
            "sample_profile": body.mode if body.mode in ("quick", "standard", "precise") else "standard",
            "travel_mode": travel_mode,
            "data_mode": body.data_mode,
        })
        return {"taskId": task_id}
    kind = "travel_guide" if body.purpose == "guide" else "travel_assess" if body.purpose == "assess" else "research"
    return create_task(body.query, mode=body.mode, model=body.model, purpose=body.purpose, kind=kind)


class ClarifyBody(BaseModel):
    answers: dict = {}


@app.post("/api/tasks/{task_id}/clarify")
def post_clarify(task_id: str, body: ClarifyBody):
    return submit_clarify(task_id, body.answers)


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
def get_report_endpoint(report_id: str):
    """统一报告读取入口（Phase 8：双引擎合并）。
    
    自动识别报告类型（竞品调研 / 生活圈体检），返回完整报告数据。
    """
    rep = db.get_report(report_id)
    if not rep:
        return {"ok": False, "message": "report not ready"}
    return rep


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    """删除调研报告（级联清理证据/链路/反馈/任务）。"""
    db.delete_report(report_id)
    return {"ok": True}


# ── 生活圈体检报告（A1 独立端点 / 独立文档）───────────────
@app.get("/api/life-circle/regions")
def life_circle_regions():
    """全国省市区三级区划（离线内置，供前端联动地址选择）。

    仅返回名称层级（体积小）；中心坐标由后端统一解析（live geocoding → 离线区划），
    前端不携带坐标，避免双份定位逻辑。
    """
    from app.living_circle.geo_index.offline_geocoder import OfflineGeocoder

    geo = OfflineGeocoder()
    return {
        "ok": True,
        "regions": [
            {
                "province": p.get("province", ""),
                "cities": [
                    {"name": c.get("name", ""), "districts": [d.get("name", "") for d in c.get("districts", [])]}
                    for c in p.get("cities", [])
                ],
            }
            for p in geo._provinces
        ],
    }


@app.get("/api/life-circle/map-config")
def life_circle_map_config():
    """浏览器 AK + 个性化地图 styleId 下发（供前端 BMapGL 加载）。

    浏览器 AK 是公开键：百度侧按 Referer 白名单限域（localhost/部署域名），
    随页面源码公开属设计内行为，故不走 mask_effective 脱敏；空值表示未配置。
    styleId 为空时前端回退内置 S2 低饱和浅色 styleJson 模板。
    """
    from app.core.config import get_settings

    s = get_settings()
    return {"ok": True, "browser_ak": s.baidu_browser_ak, "map_style_id": s.baidu_map_style_id}


@app.get("/api/life-circle")
def list_life_circle_reports():
    """历史体检记录列表（短字段，对齐前端 LifeCircleRecord）。"""
    return db.list_living_circle_reports()


@app.get("/api/life-circle/compare")
def compare_life_circle(ids: str = ""):
    """双样例对比（对齐前端 LifeCircleCompare 契约）。"""
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if len(parts) < 2:
        raise HTTPException(status_code=422, detail="compare 需要至少两个 report id（逗号分隔）")
    reps = []
    for pid in parts:
        rep = db.get_living_circle_report(pid)
        if not rep:
            raise HTTPException(status_code=404, detail=f"体检报告不存在: {pid}")
        reps.append(rep)
    return {
        "reports": [rep.get("living_circle") for rep in reps[:2]],
        "diff": _lc_diff(reps[0].get("living_circle") or {}, reps[1].get("living_circle") or {}),
    }


@app.get("/api/life-circle/{report_id}/share")
def share_life_circle_report(report_id: str):
    """报告分享直达信息（E1，Phase 8：统一读取入口）：返回分享链接元数据；报告页本身公开可读，无需鉴权。"""
    rep = db.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="体检报告不存在")
    
    lc = rep.get("living_circle") or {}
    scene = lc.get("scene") or {}
    return {
        "ok": True,
        "url": f"/report/{report_id}?share=1",
        "title": rep.get("title", f"{scene.get('name', '生活圈')} · 体检报告"),
        "scene_name": scene.get("name", ""),
    }


@app.get("/api/life-circle/{report_id}")
def get_life_circle_report(report_id: str):
    """完整体检报告（Phase 8：统一读取入口）。"""
    rep = db.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="体检报告不存在")
    
    # 验证报告类型
    if rep.get("report_type") != "living_circle":
        raise HTTPException(status_code=404, detail="非生活圈体检报告")
    
    return rep


def _lc_diff(a: dict, b: dict) -> List[dict]:
    """双样例指标差异表（对齐前端 diff 字段：metric / a_value / b_value / desc）。

    P0-2：offline 报告不产出可比评分/盲区 → 相关行标注「离线估算·不可比」，不参与比较。
    """
    a15 = next((z["area_km2"] for z in a.get("isochrones", []) if z["minutes"] == 15), 0)
    b15 = next((z["area_km2"] for z in b.get("isochrones", []) if z["minutes"] == 15), 0)
    pa, pb = a.get("poi", {}), b.get("poi", {})
    a_off, b_off = a.get("data_origin") == "offline", b.get("data_origin") == "offline"
    sa, sb = a.get("scores", {}).get("total", 0), b.get("scores", {}).get("total", 0)
    ba, bb = len(a.get("blindspots", [])), len(b.get("blindspots", []))
    rows: List[dict] = [
        {"metric": "15min 等时圈面积 (km²)", "a_value": round(a15, 2), "b_value": round(b15, 2),
         "desc": ("A 更大" if a15 > b15 else "B 更大") if a15 != b15 else "相当"},
        {"metric": "POI 采集", "a_value": pa.get("total", 0), "b_value": pb.get("total", 0),
         "desc": "设施密度" if not (a_off or b_off) else "离线估算未采集 POI"},
        {"metric": "圈内 POI", "a_value": pa.get("in_circle", 0), "b_value": pb.get("in_circle", 0),
         "desc": "可达覆盖" if not (a_off or b_off) else "离线估算未采集 POI"},
        {"metric": "综合评分",
         "a_value": "离线估算" if a_off else sa,
         "b_value": "离线估算" if b_off else sb,
         "desc": "不可比 · 离线估算" if (a_off or b_off) else (("A 更优" if sa > sb else "B 更优") if sa != sb else "持平")},
        {"metric": "服务盲区",
         "a_value": "离线估算" if a_off else ba,
         "b_value": "离线估算" if b_off else bb,
         "desc": "不可比 · 离线估算" if (a_off or b_off) else (("A 更多" if ba > bb else "B 更多") if ba != bb else "持平")},
    ]
    return rows


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
    brand: Optional[str] = None,
    source_type: Optional[str] = None,
    min_cred: float = 0.0,
    limit: int = 200,
    report_id: Optional[str] = None,
):
    # report_id 过滤：不传 → 全部证据；'<rid>' → 仅该报告证据。
    items = db.query_evidences(
        brand=brand, source_type=source_type, min_cred=min_cred,
        limit=limit, report_id=report_id,
    )
    return {"items": items, "facets": db.evidence_facets()}


# ── 竞品监控订阅 ────────────────────────────────────────
class SubscriptionBody(BaseModel):
    query: str
    brands: List[str] = []


@app.get("/api/subscriptions")
def list_subscriptions():
    return db.list_subscriptions()


@app.post("/api/subscriptions")
def create_subscription(body: SubscriptionBody):
    import uuid
    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    return db.create_subscription(sub_id, body.query, body.brands)


@app.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: str):
    db.delete_subscription(sub_id)
    return {"ok": True}
