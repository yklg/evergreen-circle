"""常青圈后端入口（FastAPI）。

挂载：48 专家 API + 任务创建/澄清 + SSE 思维流 + 报告/历史 + 仪表盘统计
+ 全局证据溯源库 + 目的地持续追踪订阅 + 专家工作量看板 + 健康/验证接口。
真实 LLM（智谱 GLM）+ 真实搜索（博查 Bocha）+ 真实抓取 + SQLite 持久化，绝不 demo。
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator

from app.core import db
from app.core import research_types as rt
from app.core import source_type
from app.core.llm import LLMModelUnavailable, LLMNotConfigured, chat
from app.core.research_types import DEFAULT_RESEARCH_TYPE
import logging
from app.core.orchestrator import create_task, run_pipeline, submit_clarify, refine_section, generate_clarify, create_refine_task, create_brief_task, GuideSingleDestinationError, ClarifyAnswerRequiredError
from app.core import runner
from app.living_circle.geo_utils import parse_bd_lnglat
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
from app.core.fetcher import normalize_user_url_list
from app.core.user_prefs import (
    PrefsValidationError,
    apply_prefs,
    prefs_doc,
)
from app.data import DOMAINS as EXPERT_DOMAINS, expert_by_id, load_experts

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


app = FastAPI(title="常青圈 API", version="2.0.0", lifespan=lifespan)

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
        "name": "常青圈 API",
        "version": "2.0.0",
        "slogan": "让每个结论都有出处，让每次调研都活着。",
        "llm_configured": bool(get_effective_settings().get("llm_api_key")),
        "experts": len(load_experts("travel")),
        # 双名册各自报数：只报 travel 一份会让"生活圈名册丢了/串了"在健康检查里隐形
        "experts_by_domain": {d: len(load_experts(d)) for d in EXPERT_DOMAINS},
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
    # 8 个请求体统一 forbid：未声明键不再被静默丢弃（判据见 tests/test_request_body_contract.py）
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    - 标量键类型错误 / 超长：整包 422，附字段级错误，任何键都不落库（不做半写）。
    - `list[str]` 键（默认引用清单）：**整键隔离** —— 该键被拒不连坐其它键，其余照常落库，
      拒因走 `key_errors` 回给前端（必须可见地拒掉，不能静默收下，也不能 422 掉整包；
      理由见 `user_prefs.apply_prefs` docstring）。
    """
    key_errors: dict = {}
    try:
        values = apply_prefs(body.patch or {}, key_errors_out=key_errors)
    except PrefsValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    out: dict = {"ok": True, "values": values, "stored": sorted(values.keys())}
    if key_errors:
        out["key_errors"] = key_errors
    return out


@app.get("/api/search")
def search_endpoint(q: str, num: int = 10, site: Optional[str] = None):
    try:
        results = search(q, num=num, site=site)
        return {"ok": True, "query": q, "site": site, "results": results}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "query": q, "reason": "error", "message": str(e)}


# ── 专家 ────────────────────────────────────────────────
def _require_domain(domain: str) -> str:
    """端点层的域校验：非法域报 422，绝不静默当成 travel。

    端点缺省仍是 travel —— 那不是"忘记传域"，而是 `/api/experts` 这个 URL 的公开契约
    （前端取 travel 名册时刻意不带查询参，`lib/api.ts:54`）。要防的是**拼错/传错域**
    被悄悄洗成另一本人设：两本名册共用同一套 48 个 id，串域不会 404，只会换人名。
    """
    if domain not in EXPERT_DOMAINS:
        raise HTTPException(status_code=422, detail=f"未知专家域 {domain!r}，可选：{', '.join(EXPERT_DOMAINS)}")
    return domain


@app.get("/api/experts")
def list_experts(domain: str = "travel"):
    """专家名册按域取：travel（缺省）/ living_circle；非法域 422。"""
    return load_experts(_require_domain(domain))


@app.get("/api/experts/workload")
def experts_workload(domain: str = "travel"):
    """专家工作量看板：真实累计任务/产出论点/采集证据（按域取名册）。"""
    domain = _require_domain(domain)
    stats = {s["expert_id"]: s for s in db.expert_workload()}
    out = []
    for e in load_experts(domain):
        s = stats.get(e["id"])
        out.append({
            "id": e["id"],
            "name": e.get("name", e["id"]),
            "title": e.get("role_title", ""),
            "layer": e.get("level", ""),
            "avatar": e.get("avatar", ""),
            "domain": domain,
            "missions": s["missions"] if s else 0,
            "claims_authored": s["claims_authored"] if s else 0,
            "evidence_collected": s["evidence_collected"] if s else 0,
            "last_active": s["last_active"] if s else "",
        })
    out.sort(key=lambda x: (x["missions"], x["claims_authored"], x["evidence_collected"]), reverse=True)
    return out


@app.get("/api/experts/integrity")
def experts_integrity():
    """名册结构性自检（双域）：返回问题清单，不影响专家端点可用性。"""
    from app.data.schema import validate_roster
    problems = []
    for domain in EXPERT_DOMAINS:
        for prob in validate_roster(load_experts(domain)):
            problems.append({"domain": domain, **(prob if isinstance(prob, dict) else {"msg": prob})})
    return {"ok": len(problems) == 0, "problems": problems}


@app.get("/api/experts/{eid}")
def get_expert(eid: str, domain: str = "travel"):
    e = expert_by_id(eid, _require_domain(domain))
    if not e:
        return {"ok": False, "message": "not found"}
    stat = next((s for s in db.expert_workload() if s["expert_id"] == eid), None)
    return {**e, "stats": stat or {"missions": 0, "claims_authored": 0, "evidence_collected": 0, "last_active": ""}}


# ── 任务 / 澄清 ─────────────────────────────────────────
class CreateTaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    mode: str = "deep"  # quick | deep | expert
    # None=客户端未显式指定（旧 bundle 只发 purpose）；归一逻辑在 post_task：
    # 显式合法 type 优先 → purpose 别名 → DEFAULT_RESEARCH_TYPE。
    type: Optional[str] = None  # guide | assessment | living_circle
    model: Optional[str] = None
    # ── 生活圈体检（type=living_circle）专用可选字段 ──
    purpose: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    center: Optional[List[float]] = None
    coord_sys: str = "bd09"  # bd09 | wgs84（后者经 geoconv 归一，缺 AK 拒绝）
    travel_mode: Optional[str] = None
    data_mode: Optional[str] = None
    # R0（片 0）：生活圈采样档位是**它自己的字段**，不再借 research 的 `mode`。
    # 前端自「R5 一名四义」改造起就一直发 `sample_profile`（`lib/api.ts:176`），而本模型
    # 只声明 `mode` ⇒ pydantic 把它**静默丢弃**，任何档位请求都恒按 standard 跑完，
    # 全程无提示。缝在这儿，D1/D2 的 `scenario` 走的也是这条缝 —— 先把缝缝上。
    sample_profile: Optional[str] = None  # quick | standard | precise
    # 用户指定信源（计划 v3 §二 B1）：手填网址，流水线检索时**直抓**这些地址。
    # 必须显式声明：`extra="forbid"` 下未声明的键会被 pydantic 静默丢弃，
    # 而这条键一丢，用户填的网址就只是"看起来提交了"。
    source_urls: Optional[List[str]] = None
    # 4b · 强制重算（只对生活圈体检有意义；research 侧今天忽略它，不新造第二套语义）。
    # 同样**必须显式声明**：`extra="forbid"` 下前端发一个模型没写的键会得到 422 而不是静默
    # 丢弃 —— 这是"键没声明"的响亮失败（`test_request_body_contract.py` 在守整体封闭性），
    # 但 422 也是坏体验，所以在这里写清：它是请求侧的**意图**，不参与缓存键。
    force: bool = False

    @field_validator("center", mode="before")
    @classmethod
    def _validate_center(cls, v):
        """BD-09 经纬度值域校验（唯一写入口；拦墨卡托米/短列表/字符串坐标）。"""
        if v is None:
            return None
        parsed = parse_bd_lnglat(v)
        if parsed is None:
            raise ValueError(
                "center 必须是 BD-09 经纬度 [lng, lat]（|lng|<=180 且 |lat|<=90）；"
                f"收到 {v!r}。BMapGL 的 e.point 是墨卡托平面米，应取 e.latLng。"
            )
        return [parsed[0], parsed[1]]


@app.get("/api/research-types")
def research_types():
    """调研类型选择器数据源（首页卡片），与后端注册表单一真相源。"""
    return rt.research_type_options()


@app.get("/api/source-kinds")
def source_kinds():
    """信源类别的展示视图（id + 中文名 + 是否入统计），唯一真相源＝`app.core.source_type` 注册表。

    前端证据链/情报中心的中文标签从这里取，不再手写 `SOURCE_LABEL` 映射表：
    新增一类信源时若前端各抄一份，新类别会显示成裸 key（"user_supplied" 直接上屏），
    而且没有任何东西会变红。
    """
    return {"kinds": source_type.kind_view()}


# 生活圈采样档位取值域（与 research 的 quick|deep|expert **是两套词表**，同名不同义）。
LC_SAMPLE_PROFILES = ("quick", "standard", "precise")


def _lc_sample_profile(body: "CreateTaskBody") -> str:
    """生活圈采样档位的**唯一解析点**（R0）。

    优先级：显式 `sample_profile` → 旧入口 `mode` → `standard`。

    保留 `mode` 回落是刻意的，不是偷懒：它的行为被 `test_living_circle_api` 的 t6 组
    钉着（含「非法值静默回落 standard」那条已登记的 TODO/B1）。片 0 只修「字段被
    pydantic 丢掉」这一半；把非法值改成显式 422 属另一条独立契约变更（B1），
    不在这里顺手改 —— 顺手改会让两套语义同时动，红了分不清是谁。
    """
    for candidate in (body.sample_profile, body.mode):
        if candidate in LC_SAMPLE_PROFILES:
            return candidate
    return "standard"


@app.post("/api/tasks")
async def post_task(body: CreateTaskBody):
    # 生活圈体检：独立流水线 + 坐标系归一（WGS-84→BD-09，缺 AK 422 拒绝）。
    # 只认显式 type=living_circle（purpose 是旅游体裁别名，不许在此分流）。
    if body.type == "living_circle":
        from app.core.pipeline.living_circle import create_living_circle_task
        from app.living_circle.caliber import get_caliber

        # 显式拒，不在这里静默丢：生活圈体检不联网抓网页，"填了却什么都没发生"
        # 与 R0 那条被 pydantic 静默丢弃的 sample_profile 是同一个形状。
        if body.source_urls:
            raise HTTPException(
                status_code=422,
                detail="用户指定信源只在调研流水线生效；生活圈体检按 POI 数据作答，不读网页。")

        travel_mode = body.travel_mode if body.travel_mode in ("walking", "riding", "driving") else "walking"
        caliber = get_caliber(travel_mode)
        center = await _to_bd09(body.center, body.coord_sys) if body.center else None
        task_id = create_living_circle_task({
            "scene_name": body.query, "city": body.city, "address": body.address,
            "center": center, "study_radius_m": float(caliber.study_radius_m),
            "sample_profile": _lc_sample_profile(body),
            "travel_mode": travel_mode, "data_mode": body.data_mode,
            # 4b：用户点名重测 ⇒ 一路传到 `CheckParams.force` ⇒ `CachingDataSource.peek` 早退。
            # 缺省 False ⇒ 今天的全部复用行为逐字不变（U22/U23/U39 那四条零新增调用的不变式照旧）。
            "force": bool(body.force),
        })
        return {"taskId": task_id}

    # 旅游调研：攻略/评估。归一优先级——显式合法 type > 旧客户端 purpose 别名 > 默认 guide。
    # （type 默认 None 才能区分「未发 type」与「显式发 guide」，否则 purpose 永远不可达。）
    # purpose 兼容旧前端方言：assess→assessment（权威 key），travel_* kind 同源归一。
    purpose_aliases = {"assess": "assessment", "travel_assess": "assessment",
                       "guide": "guide", "travel_guide": "guide"}
    if body.type in rt.RESEARCH_TYPES:
        rtype = body.type
    elif (body.purpose or "").strip().lower() in purpose_aliases:
        rtype = purpose_aliases[body.purpose.strip().lower()]
    else:
        rtype = DEFAULT_RESEARCH_TYPE
    return create_task(body.query, mode=body.mode, model=body.model, research_type=rtype,
                       source_urls=body.source_urls)


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

class ClarifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    # 展示源 = 载荷 + 当前装配器；库里那份快照只是兜底与审计副本（角色声明见
    # `db.save_living_circle_report`，三态与"为什么只在这一路"见
    # `pipeline.living_circle.refresh_report_for_display`）。
    # 函数内 import 与本文件既有写法一致（`:426`、`:1098`）：HTTP 层不在模块级拖进流水线。
    if isinstance(rep, dict) and rep.get("report_type") == "living_circle":
        from app.core.pipeline.living_circle import refresh_report_for_display

        rep = refresh_report_for_display(rep)
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
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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


# ── 情报中心（目的地调研域的整屏聚合）────────────────────
@app.get("/api/intel")
def intel():
    """报告中心「目的地调研」tab 的唯一数据源。

    与 `/api/dashboard` 分家的理由：侧栏只要两个计数，情报中心要图谱与概览卡。
    合成一个端点就等于让每个侧栏轮询都付一次全量报告反序列化 —— 而聚合口径
    仍只有一份（两者都出自 `db._agg_compute()` 的同一份缓存）。
    """
    return db.intel_overview()


# ── 全局证据溯源库 ──────────────────────────────────────
def _reject_unknown_query_params(request: Request) -> None:
    """拒收端点签名里没有的 query 参数。

    为什么要这道闸：FastAPI 对未知 query **静默忽略** ⇒ 前端把参数名写成后端不认识的
    样子时，过滤条件整个消失而接口仍返 200，没有任何异常可抓（`api.ts` 的证据库过滤
    条件就这么潜伏了很久，见架构评审 v4 事实 10）。

    允许集从端点自己的签名派生（`route.dependant.query_params`），**不再维护第二份白名单**
    —— 闸自己另列一份清单，就会漂成第二个真相源。
    """
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        # 拿不到元信息就是闸失效。宁可炸，也不静默放行 —— 那正是本闸要消灭的形状。
        raise HTTPException(status_code=500, detail="无法校验查询参数：路由元信息缺失")
    allowed = {(getattr(f, "alias", None) or f.name) for f in dependant.query_params}
    unknown = sorted(set(request.query_params) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知查询参数：{unknown}")


@app.get("/api/evidences")
def evidences(
    destination: Optional[str] = None,
    source_type: Optional[str] = None,
    min_cred: float = 0.0,
    limit: int = 200,
    report_id: Optional[str] = None,
    offset: int = 0,
    _: None = Depends(_reject_unknown_query_params),
):
    # report_id 过滤：不传 → 全部证据；'<rid>' → 仅该报告证据。
    # 参数校验闸挂在签名上：新增查询参数时白名单自动跟着走，无需两处同步。
    items = db.query_evidences(
        destination=destination, source_type=source_type, min_cred=min_cred,
        limit=limit, report_id=report_id, offset=offset,
    )
    return {"items": items, "facets": db.evidence_facets()}


# ── 目的地持续追踪订阅 ──────────────────────────────────
class SubscriptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    destinations: List[str] = []
    type: str = DEFAULT_RESEARCH_TYPE
    # 这条订阅的用户指定信源清单（计划 v3 §二 B8）：复跑必须带同一份，
    # 否则第二次跑出来的报告不含用户钉的文档，两次口径不可比而界面看不出差别。
    source_urls: Optional[List[str]] = None


@app.get("/api/subscriptions")
def list_subscriptions():
    return db.list_subscriptions()


@app.post("/api/subscriptions")
def create_subscription(body: SubscriptionBody):
    import uuid
    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    cleaned = normalize_user_url_list(body.source_urls or [])
    sub = db.create_subscription(sub_id, body.query, body.destinations, body.type,
                                 source_urls=cleaned["urls"])
    if body.source_urls:
        # 与 POST /api/tasks 同一份卫生口径（同键同形状）：超限截断、非法条目被拒都必须
        # 回报，否则订阅记录里"看起来存了 10 条"、用户却以为自己钉了 11 条 —— 静默少一条
        # 正是这一步要消灭的形状。未填清单时响应形状与改前逐键一致。
        sub["sourceUrls"] = {
            "accepted": cleaned["urls"],
            "truncated": cleaned["truncated"],
            "rejected": cleaned["rejected"],
        }
    return sub


@app.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: str):
    db.delete_subscription(sub_id)
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

    ⚠️ **styleId 默认不下发**（阶段 0.2 / 决策 D4，详见 config.py 同名注释）：
    控制台样式里的「底图 POI 注记是否关闭」**代码无法验证**，而百度第三方设施名与我们
    的应用 Marker 同款呈现，会被读成自家数据（本计划 §1 症状成因之一）；且 `setMapStyleV2`
    的 `styleId` 与 `styleJson` 互斥二选一，无法「用它的配色 + 代码关 poilabel」。
    故前端**默认**拿到空值 → 回退内置 `LC_MAP_STYLE_LIGHT`（`poilabel` 整层关闭、
    保留行政区名/路名），纪律随代码进版本控制。
    只有显式置 `BAIDU_ALLOW_CONSOLE_STYLE=1` 才下发 styleId（确知该样式已关 POI 注记时）。
    """
    from app.core.config import get_settings

    s = get_settings()
    style_id = s.baidu_map_style_id if s.baidu_allow_console_style else ""
    return {"ok": True, "browser_ak": s.baidu_browser_ak, "map_style_id": style_id}


@app.get("/api/life-circle")
def list_life_circle_reports():
    """历史体检记录列表（短字段，对齐前端 LifeCircleRecord）。"""
    return db.list_living_circle_reports()


@app.get("/api/life-circle/compare")
def compare_life_circle(ids: str = ""):
    """双样例对比（对齐前端 LifeCircleCompare 契约），可带第三份作**参照列**。

    契约形状：`reports` 恒为两份（A/B），`diff` 恒为 A/B 两两 —— 加第三份不改动它们，
    第三份走新增的可选 `reference` 键。理由：差异表的行语义、前后端共用的那份契约夹具、
    以及 A>B / A<B 的双向措辞全都建立在"两份"上；把它扩成多变比较的收益是零，
    代价是那套措辞判据整体重排。
    ⚠️ 超过三份直接 422，不再静默截断 —— 原先的 `reps[:2]` 就是把第四份悄悄吃掉的那类形状。
    """
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if len(parts) < 2:
        raise HTTPException(status_code=422, detail="compare 需要至少两个 report id（逗号分隔）")
    if len(parts) > 3:
        raise HTTPException(status_code=422, detail="compare 最多三份（两份对比 + 一份参照）")
    reps = []
    for pid in parts:
        rep = db.get_living_circle_report(pid)
        if not rep:
            raise HTTPException(status_code=404, detail=f"体检报告不存在: {pid}")
        reps.append(rep)
    out = {
        "reports": [rep.get("living_circle") for rep in reps[:2]],
        "diff": _lc_diff(reps[0].get("living_circle") or {}, reps[1].get("living_circle") or {}),
    }
    if len(reps) == 3:
        out["reference"] = reps[2].get("living_circle")
    return out


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


@app.delete("/api/life-circle/{report_id}")
def delete_life_circle_report(report_id: str):
    """删除一份生活圈体检报告（派生行级联清单与调研报告删除同源，见 db._REPORT_SCOPED_TABLES）。

    为什么返 `200 + deleted:false` 而不是 404：报告中心的删除确认框要把「我删掉了」和
    「这条已经不在」显示成两种可观察结果，但不必为后者走异常分支；更重要的是这个形状
    与所摘归档层（`components/RecordRow.tsx` 的消费方）的期望一致 —— 让后端与客户端各说
    一套契约，正是本波次要消灭的那类分叉。
    """
    return {"ok": True, "deleted": db.delete_living_circle_report(report_id)}


# 对比差异表的三处固定字面量 —— 与前端/契约夹具**同一份**（见 compareDiffContract.json）。
_DIFF_VALUE_OFFLINE = "离线估算"
_DIFF_DESC_NOT_COLLECTED = "离线估算未采集 POI"
_DIFF_DESC_NOT_COMPARABLE = "不可比 · 离线估算"
_DIFF_EQUAL_WORD = "持平"
# ── 口径不可比结论句：**按轴子句组合**，不按子集枚举 ─────────────────────────
# 原来这里是三句写死的常量（判盲一句、评分一句、"两句都不同"再一句），并在前后端各分一次支。
# 两把尺是 3 个非空子集看着还好，**第三根轴就是 7 个子集 × 两处分支 × 两端逐字同源常量** ——
# 加口径轴的成本会指数涨，而加轴恰是这套机制的常态演化。改成每轴只贡献一个子句、句子按
# 固定顺序拼之后，加一根轴 ＝ 这里多一行。前端 `lib/livingCircle.ts` 同形状同处置，
# 三句字面量仍由契约夹具 `compareDiffContract.json` 在两侧各自钉住。
#
# ⚠️ 子句必须**自带解释**，不许为了短砍掉「（点数 → 门槛项）」：判盲轴解释不了
# "65.4 与 68.4 之间那 3 分是分子换代产生的"（第 21 轮 P1-3）。
# 为什么必须专门有"两轴都不同"这一档：只报判盲那半，读者仍会把分差归给一把尺。
_GAP_CLAUSES: Tuple[Tuple[str, str], ...] = (
    ("ev", "判盲口径已升级"),      # 证据域定义变更（凯里旧口径实测只判了 5/97 的格）
    ("cov", "评分口径已升级（点数 → 门槛项）"),  # 覆盖度**分子**变更，与证据域互相独立
    # 第三根轴：实测耗时场**怎么被解释**（本次标定的常态绕行系数 + 残差耗时）。
    # 子句同样必须自带解释，"可达口径已升级"这五个字不说明升级了什么＝没说。
    # ⚠️ 它今天**不拦任何一行**（见 `_GAP_AXES` 里那条注释）：rc-1 只新增解释、不改任何
    # 一行的读数，写进行级归属就是替这把尺撒谎 —— #83 教训的反面。
    ("rc", "可达口径已升级（耗时场新增常态绕行与残差解释）"),
    # 第四根轴（笔九 S20 · `sh-1`）：等时圈形状量（八方位最远可达 + 圆度 + 最弱方位比）。
    # 与 `rc` 同一族：**横幅照报、行级不拦** —— 两侧同 ev/cov 时每一行的读数逐位相同，
    # 换它只是"这一份多了一块诊断面板"。写进行级归属就是替这把尺撒谎（#83 的反面）。
    # 它真正会改变屏幕形态的地方是**报告页第三屏在场与否**，那一侧由前端的
    # `shapeOfZone(...) == null` 缺键判据负责整块不出现，不靠这句提示。
    ("sh", "形状口径已升级（等时圈新增八方位诊断尺）"),
)


def _gap_desc(axes: Tuple[str, ...]) -> Optional[str]:
    """若干根轴不同 ⇒ 那一句「不可比 …」（空集 ⇒ None ＝ 可比）。

    顺序恒为 `_GAP_CLAUSES` 的顺序，与调用方传入的轴顺序无关 —— 否则同一对报告在
    差异表与横幅上会拼出两种词序。
    """
    clauses = [clause for axis, clause in _GAP_CLAUSES if axis in axes]
    return f"不可比 · {'、'.join(clauses)}" if clauses else None


_DIFF_DESC_CALIBER_GAP = _gap_desc(("ev",))
_DIFF_DESC_COVERAGE_GAP = _gap_desc(("cov",))
_DIFF_DESC_REACH_GAP = _gap_desc(("rc",))
_DIFF_DESC_SHAPE_GAP = _gap_desc(("sh",))
_DIFF_DESC_BOTH_GAP = _gap_desc(("ev", "cov"))
_DIFF_DESC_ALL_GAP = _gap_desc(("ev", "cov", "rc", "sh"))
# 每根轴读载荷里**哪个版本字段**（契约夹具 `gap.axis_fields` 钉同一张表）。
# 有了这张表，`_lc_diff` 不再为每根轴多一个布尔形参 —— 加轴只改两张表，不改函数签名。
_GAP_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("ev", "scope_policy_version"),
    ("cov", "coverage_caliber_version"),
    ("rc", "reach_caliber_version"),
    ("sh", "shape_caliber_version"),
)


def _differing_axes(a: dict, b: dict) -> Tuple[str, ...]:
    """两份载荷之间**哪几根口径轴**不同（含一侧根本没声明）。

    ⚠️ 只比两份载荷自带的声明，**不许**把代码常量（`SCOPE_POLICY_VERSION` 等）塞进来当
    对照值：那会把「两份都缺键」判成不可比（本批刚在复用门那边犯过一次），而两份旧报告
    互相比较时尺子确实是同一把 —— 它们只是都没有这把尺的读数而已。
    """
    ca, cb = a.get("caliber") or {}, b.get("caliber") or {}
    return tuple(axis for axis, field in _GAP_FIELDS if ca.get(field) != cb.get(field))

# 每行**受哪几根口径轴影响**（`ev` = 判盲那把尺，`cov` = 覆盖度分子）。
# ⚠️ #83：原来这里是一行 `_CALIBER_GAP_ROWS = ("服务盲区", "综合评分")` + 一把「任一根轴不同」
# 的结论句喂给两行 —— 那会替评分轴撒谎。盲区数只由判盲尺决定（1km 内有无菜市场/药店/小学），
# `cov-1` 换的是分子：两侧 `ev` 相同而 `cov` 不同那一档，盲区行其实**可比**
# （10-03 真库实测：新报告 vs 09-30 那份，盲区 1 vs 1，屏上却写「不可比 · 评分口径已升级」）。
# 计划 §22⑫ 与 `tmp/plan-r23h-row-axis.md`；前端 `lib/livingCircle.ts` 同形状同处置。
_GAP_AXES: Dict[str, Tuple[str, ...]] = {
    "服务盲区": ("ev",),
    "综合评分": ("ev", "cov"),  # 分数两把尺都吃：证据域会变、分子也会变
    # ⚠️ `rc` **刻意不在任何一行的轴清单里**（笔 3-B）。rc-1 只新增"耗时场怎么被解释"
    # （标定绕行系数 + 残差分钟），一行的读数都没改：盲区数、总分、面积、可达点数在
    # 两侧同 ev/cov 时逐位相同。把它写进去 ⇒ 那一行被一句影响不到它的话拦住，
    # 正是 #83 抓过的形态（那次是评分轴去拦盲区行）反过来重演一遍。
    # 等残差进评分那一档（`rc-2`，β 落地）再把 "综合评分" 扩成 ("ev","cov","rc") ——
    # 那才是加一根轴的**全部**成本：两张表各一行 + 夹具两项。
}
# 受**某根**轴影响的行并集（契约夹具 `gap.applies_to` 钉的是这个集合与顺序）。
_CALIBER_GAP_ROWS: Tuple[str, ...] = tuple(k for k, ax in _GAP_AXES.items() if ax)
# 评分轴拦得住的行（契约夹具 `gap.coverage_applies_to`）⇒ 盲区行**不在**其列，这条就是 #83。
_COVERAGE_GAP_ROWS: Tuple[str, ...] = tuple(k for k, ax in _GAP_AXES.items() if "cov" in ax)
# 可达轴拦得住的行（契约夹具 `gap.reach_applies_to`）⇒ 今天**是空的**，这条空集本身就是判据。
_REACH_GAP_ROWS: Tuple[str, ...] = tuple(k for k, ax in _GAP_AXES.items() if "rc" in ax)
# 形状轴拦得住的行（契约夹具 `gap.shape_applies_to`）⇒ 与 `rc` 同一条决定：**必须是空集**。
# 空集本身就是判据，记的是"sh-1 一行的读数都不改，只多一块诊断面板"这件事。
_SHAPE_GAP_ROWS: Tuple[str, ...] = tuple(k for k, ax in _GAP_AXES.items() if "sh" in ax)


def _as_num(x: Any) -> float:
    """比较用的数值兜底（`None` / 缺字段 / 非数 → 0）。**只影响比较，不影响展示值**。"""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _diff_desc(better: str, template: str, na: float, nb: float,
               name_a: str = "A", name_b: str = "B") -> str:
    """「{胜者}{template}」/「持平」—— 与前端 `lib/livingCircle.compareDesc()` **逐字同源**。

    ⚠️ **方向由 `better` 承载，不是一句 `na > nb`**：服务盲区是「越小越好」，
    误用「大者胜」会把「盲区更少」挂在盲区**更多**那一侧 —— 即事实相反
    （旧实现用字符串比较时的形态：`'0 处' > '1 处'` 为 false ⇒ 输出「B盲区更少」）。
    契约夹具里 `服务盲区 a=0 b=1` 那条用例就是这条的负对照。

    称呼（`name_a`/`name_b`）是**参数**：真实态用 `"A"/"B"`（城市名太长，表格放不下），
    前端演示态传场景实名 —— 对齐的是**句式骨架**，称呼本身保留各自形态。
    """
    if _as_num(na) == _as_num(nb):
        return _DIFF_EQUAL_WORD
    a_wins = na > nb if better == "higher" else na < nb
    return f"{name_a if a_wins else name_b}{template}"


def _row_gap_desc(metric: str, differing: Tuple[str, ...]) -> Optional[str]:
    """**这一行**的口径不可比结论（None ⇒ 这一行可比），只看影响得到它的那几根轴（#83）。

    与「多轴合起来那一句」分家是必须的：横幅问的是「这对报告整体能不能并排看」（那几句在
    前端 `lib/livingCircle.compareCaliberNotices()` 由两份载荷现算，后端没有出口），行级问的是
    「这一行的两个数是不是同一把尺量出来的」。两轴都不同那一档两者就不同 —— 评分行拿第三句、
    盲区行仍只拿判盲句（分子换代不改盲区数，把第三句挂上去等于把评分账记到判盲头上）。

    形参是一把**轴名列表**而不是每轴一个布尔：加一根轴不改签名、不加一个形参位，
    调用方也不会漏传（漏传第三根 = 那一根永远拦不住任何东西，静默失效）。
    """
    axes = _GAP_AXES.get(metric, ())
    # 交集顺序由 `_gap_desc` 按 `_GAP_CLAUSES` 归一，这里只管"这一行吃不吃得到那根轴"。
    return _gap_desc(tuple(a for a in axes if a in differing))


def _lc_diff(a: dict, b: dict) -> List[dict]:
    """双样例指标差异表（对齐前端 diff 字段：metric / a_value / b_value / desc）。

    行名、行序、解读句式与前端 `lib/livingCircle.COMPARE_ROWS` **逐项相同**（Py/TS 各一份实现，
    靠**同一份契约夹具**的期望字面量在两侧测试各自断言对齐 —— 范式同
    `poi_metric_label`/`poiMetricLabel`）。夹具：`frontend/src/__tests__/fixtures/compareDiffContract.json`。

    P0-2：offline 报告不产出可比评分/盲区 → 相关行标注「离线估算·不可比」，不参与比较。
    ⚠️ 该离线分支**逐行保留**，不得因「两模式对齐」而被吞掉（`test_living_circle_api.py:236` 在守）。

    P0-3：两侧 `caliber.scope_policy_version` 不同（含一侧未声明 = 判盲口径升级前的旧报告）
    ⇒ 「服务盲区」「综合评分」标注「不可比 · 判盲口径已升级」。这两行**数值照原样给**（事实
    没被改），只有结论句被拦 —— 旧口径的证据面只有可达区一角（凯里实测 5/97），盲区少报、
    分数偏高，分差会被读成「社区不同」而不是「尺子换了」。双样例对比是答辩演示路径。

    第 21 轮 P1-3：同一对行还要看**第二根轴** `caliber.coverage_caliber_version`（覆盖度分子
    从圈内点数换成门槛项数）。两根轴独立 ⇒ 三句结论句各说各的事：只判盲不同 / 只评分不同 /
    两轴都不同。"判盲相同但评分轴一边缺键"这一支以前被判**可比**，而它的分差全部来自分子换代。

    #83 补的那半：上面那句「同一对行」只对**判盲轴**成立。第二根轴接进来时行级守卫沿用了一把
    「任一根轴不同」的共用结论句 ⇒ 只评分轴不同那一档，「服务盲区」也被写上「不可比 · 评分口径
    已升级」，而分子换代影响不到盲区数（10-03 真库配对实测：两侧 `ev-2` 相同、盲区 1 vs 1）。
    现在行级按 `_GAP_AXES` 分派：盲区行只吃 `ev`，评分行吃 `ev` + `cov`。

    实现形态：**一张行规格表 + 一个循环**。加一行只改这张表一处 —— 而不是在返回值里
    手工拼一行（那样行名/行序/句式会分散，与前端分叉时无人发现）。
    """
    # 局部导入：`diagnosis_templates` 依赖 pipeline，放模块级易生循环依赖（项目内既有惯例）。
    from app.core.pipeline.diagnosis_templates import sampling_counts

    a15 = next((z["area_km2"] for z in a.get("isochrones", []) if z["minutes"] == 15), 0)
    b15 = next((z["area_km2"] for z in b.get("isochrones", []) if z["minutes"] == 15), 0)
    # ⚠️ 面积**先定成两位小数再用**：展示值与比较值必须是同一个数，否则 `1.561` 与 `1.564`
    # 会显示成两个 `1.56` 却判出「B 更大」——读者无法用看到的数复核结论。前端 `_isoArea15()`
    # 同样先 `toFixed(2)`（两模式显示值必须一致：此前前端吐 1.562、后端吐 1.56）。
    ra15, rb15 = round(a15, 2), round(b15, 2)
    pa, pb = a.get("poi", {}), b.get("poi", {})
    a_off, b_off = a.get("data_origin") == "offline", b.get("data_origin") == "offline"
    off = a_off or b_off
    # 口径轴对照：两侧**任一根**版本声明不同（含一侧根本没声明）⇒ 那几个数不是同一把尺量出来的。
    # 四根轴（判盲 `ev` / 评分 `cov` / 可达 `rc` / 形状 `sh`）由 `_GAP_FIELDS` 一张表读，不再逐轴开布尔 ——
    # 逐轴布尔的形状是"每加一根轴就改四处"，漏一根就是静默失效（`_differing_axes` 的注释）。
    # ⚠️ 只比载荷自带的声明，不 import 代码常量当对照值：那会把"两份都缺键"判成不可比。
    differing = _differing_axes(a, b)
    # ⚠️ 这里**不再**先塌成一句「多轴合起来的结论句」（#83）：那把句在旧实现里同时喂给
    # 「服务盲区」与「综合评分」两行，于是评分轴的差异会去拦一个它影响不到的行。各轴
    # 一起交给 `_row_gap_desc()`，由它按行的轴归属决定拦不拦、说哪句。对比页**横幅**那几句不在
    # 后端（前端 `lib/livingCircle.compareCaliberNotices()` 由两份载荷现算），故此处不留共用值。
    sa, sb = a.get("scores", {}).get("total", 0), b.get("scores", {}).get("total", 0)
    ba, bb = len(a.get("blindspots", [])), len(b.get("blindspots", []))
    # 「可达采样点数」走 sampling_counts()（叙述文案的**唯一取值口径**）：汇总数缺失的历史快照
    # 由它内部按点回算，且回算走同一个 reach_flags 判据 —— 与前端 samplingReach() 同口径。
    a_reach, b_reach = sampling_counts(a)[1], sampling_counts(b)[1]
    a_total, b_total = pa.get("total", 0), pb.get("total", 0)
    # 「圈内 POI」**重算** Σ categories[].in_circle，**不读**顶层冗余的 `poi.in_circle`
    # （顶层那个是「与 categories 可能不一致的自我声明」——与 `poi_metric_label` 同处置）。
    # ⚠️ 实测 25/25 份两种读法同值 ⇒ 这是**口径归位，不改任何显示值**，不是行为修复。
    a_in = sum(int((c or {}).get("in_circle") or 0) for c in (pa.get("categories") or []))
    b_in = sum(int((c or {}).get("in_circle") or 0) for c in (pb.get("categories") or []))

    # 行规格表 —— (行名, A/B 比较值, A/B 展示值, 方向, 句式, 离线时的替代 desc)
    # ⚠️ 数值行上「比较值」与「展示值」**故意取同一个数**（面积取两位小数后的值）——
    #    判据必须挂在读者看得到的那个数上，否则同一对数字配两种结论。
    specs: List[tuple] = [
        ("15min 等时圈面积 (km²)", ra15, rb15, ra15, rb15,
         "higher", "可达范围更大", None),
        ("可达采样点数", a_reach, b_reach, a_reach, b_reach,
         "higher", "可达采样点更多", None),
        ("POI 采集", a_total, b_total, a_total, b_total,
         "higher", "采集面更广", _DIFF_DESC_NOT_COLLECTED),
        ("圈内 POI", a_in, b_in, a_in, b_in,
         "higher", "可达设施更密", _DIFF_DESC_NOT_COLLECTED),
        ("服务盲区", ba, bb,
         _DIFF_VALUE_OFFLINE if a_off else ba, _DIFF_VALUE_OFFLINE if b_off else bb,
         "lower", "盲区更少", _DIFF_DESC_NOT_COMPARABLE),
        ("综合评分", _as_num(sa), _as_num(sb),
         _DIFF_VALUE_OFFLINE if a_off else sa, _DIFF_VALUE_OFFLINE if b_off else sb,
         "higher", "更成熟", _DIFF_DESC_NOT_COMPARABLE),
    ]

    rows: List[dict] = []
    for metric, na, nb, va, vb, better, template, off_desc in specs:
        # 处置优先级：离线 > 口径版本 > 常规胜负。离线那档连 POI 都没采，没什么可比可言；
        # 口径版本这档比的是「同一指标换了一把尺」，数值本身没坏，但差值没有意义。
        if off and off_desc:
            desc = off_desc
        else:
            # 行级按轴分派（#83）：这一行受哪几根轴影响，就只有那几根轴的差异拦得住它。
            desc = _row_gap_desc(metric, differing) or _diff_desc(better, template, na, nb)
        rows.append({"metric": metric, "a_value": va, "b_value": vb, "desc": desc})
    return rows

