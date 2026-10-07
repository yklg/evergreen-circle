"""生活圈体检流水线（A2 独立 pipeline，A1 独立子域的编排入口）。

`living_circle_pipeline(task_id)`：async generator，被 runner._drive 按 kind 分发，
事件结构对齐 F0 冻结的 A4 契约（node_update/progress/message/evidence/report_ready/done，
report_ready/done 同时携带 `reportId`（runner 传统字段）与 `report_id`（前端 useTaskStream））。
旧 research 流水线零改动：本模块不 import orchestrator/runner。

流程（intake→plan→measure→collect→diagnose→report→audit）：
  1. intake：解析任务参数（scene/center/city/mode/data_mode）
  2. measure：IsochroneEngine 批量测时 + IDW 等值线族（真实计算在此发生）
  3. collect：8 类 POI + 三要素采集
  4. diagnose：类别统计/耗时回填/盲区/评分（确定性，无 Key 不阻塞）
  5. report：D4 规则模板组装完整 Report（专家署名）
  6. audit：落库 living_circle_reports 独立文档（A1）
"""
from __future__ import annotations

import datetime as _dt
import logging
import uuid
from functools import lru_cache
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, TypedDict

from app.core import db
from app.core.config import get_settings
from app.living_circle.caliber import (
    REACH_CALIBER_VERSION,
    caliber_payload_key,
    get_caliber,
)
from app.living_circle.data_source import (
    CheckParams,
    NEARBY_CACHE_M,
    live_forensic_steps,
    refine_live_with_profile,
    STEP_COLLECT,
    STEP_DEGRADED,
    STEP_JUDGE,
    STEP_MEASURE,
    STEP_REPORT,
    STEP_ROUND,
)
from app.living_circle.degrade_policy import detail_label
from app.living_circle.geo_utils import haversine_m
from app.living_circle.isochrone import REACH_FULL_MIN, IsochroneEngine, detour_residual, reach_flags
from app.living_circle.report_contract import (
    assess_geometry,
    narrative_refresh_needed,
    observe_shape_gate,
)

from .diagnosis_templates import NARRATIVE_VERSION, assemble_report

logger = logging.getLogger(__name__)

STAGES = ["intake", "plan", "measure", "collect", "diagnose", "report", "audit"]
# 各阶段到达百分比（runner 进度落库 + 前端进度条）
STAGE_PERCENT = {"intake": 5, "plan": 14, "measure": 48, "collect": 72, "diagnose": 86, "report": 95, "audit": 99}

# 名称与中心点的「同源」容差。取 50km 的理由：同名社区的地理编码歧义最多差几公里，
# 而真实事故（名称=北京劲松 / 中心=昆明）差 1800km —— 两个量级之间留足余量，
# 既不误伤「中心点被微调过几百米」的正常用法，也不放过跨省错配。
NAME_CENTER_MAX_M = 50_000.0


@lru_cache(maxsize=1)
def _sample_scene_centers() -> Tuple[Tuple[str, float, float], ...]:
    """样例场景「名称 → 中心点」，供名称/坐标同源校验。

    ⚠️ 必须**模式无关**：实测缺陷恰好发生在 live 模式，而 live 模式的
    ``CachingDataSource`` 并不透传 ``sample_scenes()`` —— 若用数据源取样例，
    守卫会在最需要它的场景里静默失效。故这里直接读内置 fixtures（本地文件，零网络）。
    """
    from app.living_circle.data_source import FixtureDataSource

    try:
        scenes = FixtureDataSource().sample_scenes()
    except Exception:  # fixtures 缺失不应让体检失败
        logger.warning("样例场景库不可用，名称/坐标同源校验跳过", exc_info=True)
        return ()
    out = []
    for s in scenes:
        c = s.get("center") or (0, 0)
        if s.get("name") and len(c) == 2:
            out.append((str(s["name"]), float(c[0]), float(c[1])))
    return tuple(out)


class TaskParams(TypedDict, total=False):
    """任务参数（存于 tasks.clarifications）。"""

    scene_name: str
    city: str
    address: str
    center: List[float]  # [lng, lat]
    study_radius_m: float
    sample_profile: str  # quick / standard / precise（旧字段名 `mode` 由读取端归一）
    travel_mode: str  # walking / riding / driving
    data_mode: str  # 'live' | 'fixture'
    mode: str  # 历史遗留别名，仅作读取兼容
    force: bool  # 4b：用户点名重测 ⇒ 跳过两级缓存复用（缺省 False＝今天的形状）


def _ev(type_: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": type_, "data": data}


def create_living_circle_task(params: TaskParams) -> str:
    """创建体检任务（kind='living_circle'），返回 task_id。"""
    task_id = f"lc-{uuid.uuid4().hex[:12]}"
    db.save_task(
        task_id,
        query=params.get("scene_name", "生活圈体检"),
        clarifications=dict(params),
        kind="living_circle",
    )
    return task_id


def _scene_key(params: TaskParams) -> str:
    """scene 缓存键（社区名 + 坐标 + 口径，供同中心秒开）。

    travel_mode 必传：步行/骑行/驾车可达区完全不同，漏传会让三种口径**互相串缓存**
    （用户选骑行却拿到步行报告）。
    """
    c = params.get("center") or [0, 0]
    return caliber_payload_key(
        params.get("scene_name", ""),
        tuple(c),
        params.get("study_radius_m", 2500),
        params.get("sample_profile") or params.get("mode") or "standard",
        params.get("travel_mode", "walking"),
    )


def _report_id(scene_key: str) -> str:
    return f"lc-{uuid.uuid4().hex[:8]}"


def _team_payload(expert_ids: List[str], reasons: List[str]) -> Dict[str, Any]:
    """报告 payload 里 `team` 键的**唯一**构造点。

    为什么必须收在一处：粗报、缓存命中、后台精报三条路径各写过一份字典，其中精报那份
    把 `reasons` 写成空数组 ⇒ 同一份报告被精报替换后，逐人指派理由退化成兜底句
    （「…负责本节评审与结论签发（D4 专家出诊断）」）。三份手写迟早会再漂一次。
    """
    return {"expert_ids": list(expert_ids), "reasons": list(reasons)}


def _fallback_center(source, scene_name: str) -> tuple:
    """中心点解析兜底：fixture 按场景名就近匹配样例中心，否则凯里老街（默认演示样区）。"""
    scenes = source.sample_scenes() if hasattr(source, "sample_scenes") else []
    hit = next(
        (s for s in scenes if scene_name and s.get("name") and scene_name in s["name"]),
        None,
    )
    if hit and hit.get("center"):
        return tuple(hit["center"])
    return (107.9758, 26.5734)  # 凯里老街


async def living_circle_pipeline(task_id: str) -> AsyncIterator[Dict[str, Any]]:
    """执行体检流水线（runner 消费）。事件契约见文件头。"""
    full = db.get_task_full(task_id) or {}
    params: TaskParams = (full.get("clarifications") or {}).copy()
    # R5 兼容闸门：历史任务与直调入参仍写旧字段 `mode`，读取端做一次别名归一；
    # 归一之后下游只认 `sample_profile` 单一名字，不出现「两份名字同时流通」。
    sample_profile = params.get("sample_profile") or params.get("mode") or "standard"
    travel_mode = params.get("travel_mode", "walking")
    data_mode = params.get("data_mode", "")
    ak = get_settings().baidu_server_ak

    from app.living_circle.data_source import get_data_source
    from app.living_circle.repository import Repository, SqliteCache, resolve_cache_path

    # v2：实时结果持久落盘（SqliteCache，独立 `app/lc_cache.db`）——同中心 30 天秒开 + 无 AK 离线可查。
    # 落点由 `resolve_cache_path()` 决定（默认即上面那份；`LC_CACHE_PATH` 可整份换掉，
    # 用途见那里的注释：重采要绕开一份「键不含检索词表」的 30 天旧载荷）。
    repo = Repository(backend=SqliteCache(resolve_cache_path()))
    source = get_data_source(data_mode or "fixture", ak=ak, repo=repo)

    # 中心点解析（v2 统一链）：显式坐标 > live 地理编码 > 离线区划定位 > fixture 样例匹配 > 凯里兜底
    center: Optional[tuple] = tuple(params.get("center")) if params.get("center") else None
    if center is None:
        # CachingDataSource 透传 .client 属性但可能为 None（内层离线源）——必须判 None
        live_client = getattr(source, "client", None)
        if live_client is not None:
            center = await live_client.geocoding(params.get("scene_name") or "")
        if center is None:
            from app.living_circle.geo_index.offline_geocoder import OfflineGeocoder

            hits = OfflineGeocoder().search(params.get("scene_name") or "")
            if hits and hits[0].center:
                center = tuple(hits[0].center)
        if center is None:
            center = _fallback_center(source, params.get("scene_name") or "")
    center = tuple(center)
    # 回写实际中心到任务参数：下游 _scene_key / 报告 scene 使用同一坐标
    params["center"] = [center[0], center[1]]

    # ── 名称/坐标同源校验（阶段 2 软守卫）───────────────────
    # 实测样本 lc-d3cfa371：scene_name=北京劲松、center=(102.76, 25.03) 昆明。
    # 此处**不拦截**（在自定义坐标上做体检是合法用法），只把「不同源」变成**可见**。
    intake_meta: Dict[str, Any] = {"name_source": "user_query"}
    sname = (params.get("scene_name") or "").strip()
    if sname:
        ref = next((s for s in _sample_scene_centers() if sname in s[0] or s[0] in sname), None)
        if ref is not None:
            dist_m = haversine_m(center, (ref[1], ref[2]))
            if dist_m > NAME_CENTER_MAX_M:
                intake_meta = {
                    "name_source": "user_query",
                    "name_center_mismatch": True,
                    "name_center_distance_m": round(dist_m),
                    "name_ref": ref[0],
                    "name_ref_center": [ref[1], ref[2]],
                }
                yield _ev("warn", {
                    "stage": "intake",
                    "code": "name_center_mismatch",
                    "text": (
                        f"名称「{sname}」与本次中心点（{center[0]:.4f}, {center[1]:.4f}）"
                        f"相距约 {dist_m / 1000:.0f}km（同名样例在 {ref[1]:.4f}, {ref[2]:.4f}），"
                        "二者可能不同源，请核对名称与坐标是否属于同一地点"
                    ),
                })

    # ── intake ───────────────────────────────────────────
    yield _ev("message", {"stage": "intake", "percent": STAGE_PERCENT["intake"], "text": f"已确立体检中心点：{params.get('scene_name', '')}（{center[0]:.4f}, {center[1]:.4f}），研究范围 {(params.get('study_radius_m') or 2500) / 1000:.1f}km，模式 {sample_profile}"})
    yield _ev("progress", {"stage": "intake", "percent": STAGE_PERCENT["intake"], "stage_seq": 1, "evidence_count": 0})

    # ── plan（专家队编排）────────────────────────────────
    from app.core.pipeline.lc_team import select_living_circle_team

    scene_name = params.get("scene_name", "未命名社区")

    dispatch_ids, dispatch_reasons, dispatch_degraded = select_living_circle_team(
        scene_name=scene_name,
        travel_mode=travel_mode,
    )

    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-plan", "label": "专家队编排", "status": "working", "expert": "L3-002"}})
    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-dispatch", "label": f"按域指派 {len(dispatch_ids)} 位专家", "status": "done", "expert": "L3-002"}})
    # 组队结果（含降级）走 **message 事件加字段**，不新增事件 type：
    #   · 新增 type 会撞 A4 白名单（`test_pipeline_event_contract`），且未登记的 type
    #     在前端 `SSE_SUBSCRIPTIONS` 处被传输层静默丢弃（`warn` 就是这么丢了很久的）；
    #   · 降级只进运行流、不进报告 payload —— 与调研侧 MIG-01 同源
    #     （`research/dispatch.py` 的 degraded 也只走 trace 与 SSE）。
    yield _ev("message", {
        "stage": "plan",
        "percent": STAGE_PERCENT["plan"],
        "kind": "team",
        "members": dispatch_ids,
        "degraded": dispatch_degraded,
        "text": (
            f"本次专家队由保底名单编排（{dispatch_degraded}），未经模型按场景挑选"
            if dispatch_degraded
            else f"编排完成：{len(dispatch_ids)} 位专家就位，覆盖医疗/教育/购物/养老等核心民生领域"
        ),
    })
    yield _ev("progress", {"stage": "plan", "percent": STAGE_PERCENT["plan"], "stage_seq": 2, "evidence_count": 0})

    engine = IsochroneEngine()
    check = CheckParams(
        scene_name=params.get("scene_name", "未命名社区"),
        city=params.get("city", ""),
        address=params.get("address", ""),
        center=center,
        study_radius_m=float(params.get("study_radius_m", 2500)),
        sample_profile=sample_profile,
        travel_mode=travel_mode,
        # 4b：把"用户点名要重测"传到唯一的读缓存入口。读法刻意用 `.get(...) is True`
        # 而不是 `bool(params.get("force"))`：任何非 `True` 的值（缺键、None、字符串）
        # 都退回今天的默认行为，不给"一个坏值意外把复用关掉、每次体检都重打配额"留缝。
        force=params.get("force") is True,
    )
    scene_key = _scene_key(params)

    # ── E1 缓存前置（v5 E0/E1）：peek 单一入口，命中零客户端调用 ──
    # fixture 源无 peek（getattr 判空）；CachingDataSource（live/offline 包装）命中即短路。
    # peek 是**同步**读（repo 内存/SQLite，无网络 I/O），不可 await（await 同步返回值
    # 会在未命中返回 None 时抛 "object NoneType can't be used in 'await' expression"）。
    # ⚠️ A 计划契约（延迟优化，防复发）：**缓存键相关步骤（center 解析/参数回写）必须在
    # peek 前**；**仅计算需要的富化（逆地理/地址补城市）必须延迟到 miss 后** ——
    # 命中路径零百度调用（U39 锚定 geocode/reverse/poi 四类计数器全为 0）。
    peek = getattr(source, "peek", None)
    cached_hit = peek(check) if peek is not None else None
    if cached_hit is not None:
        geometry = assess_geometry(cached_hit)
        if geometry.ok:
            served_from = cached_hit.get("served_from", "cache")
            if served_from == "nearby_cache":
                hit_text = "邻近既有体检结果：原中心距此 ≤500m（未消耗百度额度），直接复用"
            else:
                hit_text = "缓存命中：同地点 30 天内已有体检结果，直接复用（未消耗百度额度）"
            yield _ev("message", {"stage": "measure", "percent": STAGE_PERCENT["measure"], "text": hit_text})
            yield _ev("progress", {"stage": "measure", "percent": STAGE_PERCENT["measure"], "stage_seq": 3, "evidence_count": 0})
            yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 0})
            yield _ev("progress", {"stage": "diagnose", "percent": STAGE_PERCENT["diagnose"], "stage_seq": 5, "evidence_count": 0})

            report_data = cached_hit
            report_data["team"] = _team_payload(dispatch_ids, dispatch_reasons)

            # E2 幂等收尾（D19/D22）：**只有精确命中**才复用既有 report_id —— 那时落库行与
            # 服务出去的内容同源，复用 id 才等于「不重复落库」。
            # ⚠️ 邻近命中不能走这条路：`find_recent_report_near` 服务的是**别的 scene_key**
            # 的内容（同中心 ≤500m 的邻居），而 `get_latest_report_id_for_scene(scene_key)`
            # 取的是**本次 scene_key** 的行 ⇒ 两者一旦配对，就是「展示新内容、DB 仍指旧行」。
            # 实测代价：快照脚本按 done 里的 report_id 回读 DB，把一份史前载荷（sampling 还是
            # `reachable` 字段、collect_margin=0）当成本次实跑结果写进了夹具。
            report_id = (
                None if served_from == "nearby_cache"
                else db.get_latest_report_id_for_scene(scene_key)
            )
            if report_id is not None:
                db.mark_task_done(task_id, report_id)
                yield _ev("message", {"stage": "report", "percent": STAGE_PERCENT["report"], "text": f"报告已签发（复用既有体检结果 · {served_from}）"})
                yield _ev("progress", {"stage": "report", "percent": STAGE_PERCENT["report"], "stage_seq": 6, "evidence_count": len(report_data.get("evidence") or [])})
                yield _ev("progress", {"stage": "audit", "percent": 100, "stage_seq": 7, "evidence_count": len(report_data.get("evidence") or [])})
                yield _ev("report_ready", {"reportId": report_id, "report_id": report_id, "title": report_data.get("title") or report_data.get("scene", {}).get("name", "生活圈体检")})
                yield _ev("done", {"reportId": report_id, "report_id": report_id})
                return
            # 走到这里有两种情形，都**必须把服务出去的内容落回本次 scene_key**（内容归位）：
            #  ① 邻近命中 —— 内容来自邻居，本 scene_key 的旧行不是它（见上方 E2 说明）；
            #  ② 精确命中但落库缺失（异常态，D23）。
            # 与 miss 路径同构：`replace_scene=False`（不先删同场景其它行，存量历史按 D-4
            # 继续可见）+ 落库后 `backfill` 到本次精确键 —— 否则每次复查都命中同一个邻居、
            # 每次都长出一条新历史（`_report_id` 是随机 uuid，不是 scene_key 的确定函数）。
            # 零百度调用：内容已在手上。
            logger.info(
                "[living_circle] 缓存命中需内容归位（served_from=%s，scene_key=%s）—— 按本次"
                " scene_key 落库，不复用不相干的旧行 id",
                served_from, scene_key,
            )
            # 4b：门的依据是**这次跑的是哪种模式**，不是"这条分支必然是 live"——
            # 拿分支当依据，哪天数据源工厂多包一层缓存，屏幕上的复用声明就会静默长出来。
            report_id, reason, report = _finalize_living_report(
                report_data, scene_key, replace_scene=False, data_mode=data_mode)
            if reason is not None:
                msg = f"质检未通过：{reason}。请更换中心点或检查配额"
                db.set_task_failed(task_id, msg)
                yield _ev("error", {"stage": "audit", "code": "invalid_geometry", "message": msg})
                yield _ev("done", {"reportId": None, "report_id": None, "status": "failed", "error": msg})
                return
            backfill = getattr(source, "backfill", None)
            if backfill is not None:
                backfill(check, report_data)
            db.mark_task_done(task_id, report_id)
            yield _ev("report_ready", {"reportId": report_id, "report_id": report_id, "title": report["title"]})
            yield _ev("done", {"reportId": report_id, "report_id": report_id})
            return
        # 理论罕见：缓存报告几何不成立 → 记日志，继续实时重算
        logger.warning("[living_circle] 缓存命中但几何校验不通过（%s），转为实时重算", geometry.reason)

    # ── 城市解析（阶段 2：与中心点同源；**miss 路径才执行**）────────
    # ⚠️ 历史缺陷：前端把「当前展示报告」的城市塞进本次任务 —— 那是与本次查询**无关**的
    # 第三个来源（实测产出「名称=北京劲松 / 中心=昆明 / 城市=北京·朝阳」的自相矛盾报告）。
    # 现改为：显式 city > 中心点逆地理 > 留空。绝不从别的报告取。
    # A 计划契约（延迟优化）：逆地理富化**必须**在 peek 之后 —— 缓存键不含 city
    # （_scene_key 5 段，test_u34 锚定），命中时缓存报告自带 city/address，miss 才需要补。
    if not (params.get("city") or "").strip() and getattr(source, "client", None) is not None:
        rev = await source.client.reverse_geocoding(center)
        if rev and rev.get("city"):
            params["city"] = rev["city"]
            check.city = rev["city"]  # check 在 peek 前已构造，城市解析后须回写保持一致
            yield _ev("message", {"stage": "intake", "text": f"中心点逆地理定位：{rev.get('name') or rev['city']}"})

    # ── measure（测时采样 + IDW 等时圈）────────────────────
    # CachingDataSource 透传 .client 但可能为 None（内层离线源）——判 None 决定 live/offline 分支
    live_client = getattr(source, "client", None)
    yield _ev("message", {"stage": "measure", "percent": 30, "text": "批量距离矩阵测时采样中…（生效采样规格随档位与本次预算，产出那一步如实披露）"})

    if live_client is not None:
        # 取证编排走**全项目唯一实现** `live_forensic_steps`（计划 v6.1 片 0）。此前这段
        # 「等时圈 → 口径绑定 → 采集 → 绑证据 → 残缺判定 → 组装」在 pipeline 内联、
        # `LiveDataSource.compute`、`refine_live_with_profile` 里抄了三遍，而线上只跑第一份
        # ⇒ 回合循环接在任何一份上，另外两份永远学不到。这里从此只剩一件事：
        # **把每一步的事实翻成事件**，文本、stage 序号与 evidence_count 的取值逐字照旧
        # （这张时序表就是片 0 的验收线，网在 `test_u36`/`test_pipeline_event_contract`/`test_u40`）。
        report_data: Dict[str, Any] = {}
        async for step in live_forensic_steps(live_client, engine, check,
                                              intake_meta=intake_meta):
            if step.kind == STEP_MEASURE:
                iso = step.iso
                n_timed = iso["sampling"]["timed_count"]
                n_in_reach = iso["sampling"]["in_reach_count"]
                _spec = iso["sampling"]["spec"]
                # 生效规格只此一处出处（`isochrone.compute` 产出的 `spec`）：文案不抄档位常数（#86）。
                # 降级那支**不能说"放弃边界加密带"**：`fine_m` 为 None 有两种成因，而 quick 档
                # 的名义加密步长本就等于粗扫步长（且上限恒 200 ⇒ 任何预算下都被削）—— 它没放弃过什么。
                if _spec["degraded"]:
                    _spec_note = "；**预算受限已降规格**：退回单阶段粗网格，插值格距 " \
                                 f"{_spec['grid_step_m']:g}m vs 采样间距 {_spec['sample_step_m']:g}m"
                else:
                    _band_lo, _band_hi = _spec["fine_band"]
                    _spec_note = f"（粗扫 {_spec['coarse_m']:g}m + 边界带 {_band_lo:g}–{_band_hi:g}m 内加密 " \
                                 f"{_spec['fine_m']:g}m）"
                yield _ev("message", {"stage": "measure", "text": f"IDW 插值生成耗时场：采样 {iso['sample_count']} 点（已测时 {n_timed} · ≤{REACH_FULL_MIN:g}min 可达 {n_in_reach}），5/10/15/20 分钟等值线族已提取{_spec_note}"})
                yield _ev("evidence", {"stage": "measure", "evidence": {
                    "evidence_id": f"ev-{task_id}-measure", "source_url": "live://measure", "source_type": "api_measure",
                    "title": "采样点测时记录", "excerpt": f"批量算路返回 {n_timed} 条耗时，其中 ≤{REACH_FULL_MIN:g}min 可达 {n_in_reach} 条",
                    "credibility": 0.95, "collected_by": "L2-005", "captured_at": _now_iso(),
                }})
                yield _ev("progress", {"stage": "measure", "percent": STAGE_PERCENT["measure"], "stage_seq": 3, "evidence_count": 1})

            elif step.kind == STEP_DEGRADED:
                # 总量熔断降级（rev3 §四G / v3 §3.5）：预算耗尽时产出诚实离线报告
                # （data_origin='offline'、可视化占位、评分/盲区留待实时重检），**绝不**拿空 POI
                # 硬算后被几何质检拦成「调研失败」。触发判据的唯一出口在 `degrade_policy`：
                # 触发=数据缺失（等时圈空 / POI 全空）或**测时阶段**提前中止，配额信号只填 detail
                # （不用 `stats.quota_hits` 触发：它计在重试内，一次抖动+重试成功就会过度降级）。
                report_data = step.report or {}
                _label = detail_label((report_data.get("degraded") or {}).get("detail") or "unknown")
                yield _ev("message", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "text": f"百度{_label}：降级为离线估算，评分与盲区需配额恢复后实时重检"})
                # U36：熔断降级同样发 collect progress —— 保持 STAGES 进度连续（48→72→86），
                # 否则前端进度条在降级路径从 measure 直接跳到 diagnose。
                yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 0})

            elif step.kind == STEP_COLLECT:
                _n_poi = sum(len(v) for v in step.collected.per_category.values())
                # 残缺与否在这里就必须区分开：说「采集完成」而实际有几类没查到，
                # 是本轮改造的头号缺陷形状（把没查的说成查过了）。D1①：取证阶段的中止
                # 不打回离线，报告保持 live 并标 `partial`。
                _partial = step.partial
                if _partial is None:
                    _collect_text = f"8 类民生设施采集完成：总量 {_n_poi} 处"
                else:
                    _collect_text = (
                        f"8 类民生设施采集中止于配额：已得 {_n_poi} 处，"
                        f"未采到的类别按证据缺口披露（{detail_label(_partial['detail'])}，报告仍为实时口径）"
                    )
                yield _ev("message", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "text": _collect_text})
                yield _ev("evidence", {"stage": "collect", "evidence": {
                    "evidence_id": f"ev-{task_id}-collect", "source_url": "live://poi", "source_type": "poi_search",
                    "title": "POI 采集", "excerpt": f"共 {_n_poi} 处",
                    "credibility": 0.92, "collected_by": "L2-004", "captured_at": _now_iso(),
                }})
                yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 2})

            elif step.kind == STEP_JUDGE:
                # 判定步只交事实（掩码 + 三态账目），不发事件：上屏时序与片 0 逐字节相同。
                continue

            elif step.kind == STEP_ROUND:
                # 取证回合（计划 v7.0 片 4）：发**新事件类型 `round`**，不发 progress、不发 evidence。
                # 为什么不挂 `trace`（v6.0 原文那个名字）：`trace` 在前端有一个已定的
                # `TraceSpan` 形状（span_id/agent_id/prompt/tokens…），唯一发射点是 research 引擎，
                # 还牵 `db.traces` 那张表 —— 拿它装回合遥测就是在同一事件名下造第二种载荷。
                # 为什么不发 `progress`：`stage_seq == 1..7` 那五处契约会为多出来的回合改写；
                # 为什么不发 `evidence`：progress 里声明的 `evidence_count` 就会与实发条数分家。
                # 载荷只有一个来源：`ForensicRoundRecord.to_row()` —— 它与 `caliber.forensic`
                # 里那一份逐回合流水是同一个函数产的，上屏与落库无从各说各话。
                _row = (step.forensic_round.to_row() if step.forensic_round is not None else {})
                yield _ev("round", {
                    "stage": "collect",
                    "round": _row,
                    "text": (f"取证回合：在 {_row.get('anchors_sent', 0)} 个补算锚点上重查三要素"
                             f"（{_row.get('calls', 0)} 次调用），未决格 "
                             f"{_row.get('cells_undecided_before', 0)} → "
                             f"{_row.get('cells_undecided_after', 0)}"),
                })

            elif step.kind == STEP_REPORT:
                # STEP_REPORT —— 组装已在数据源层完成（唯一实现），这里只回填缓存。
                # v5 E1：实时重算结果回填缓存（编排器不摸 repo/键，走数据源层 backfill）。
                # 「live 缓存不装 offline 报告」不再在此判 —— 该不变量的唯一出口是
                # `Repository.cache_report`（本分支只会是实时产物，且新入口也一并被拦住）。
                report_data = step.report or {}
                backfill = getattr(source, "backfill", None)
                if backfill is not None:
                    backfill(check, report_data)

            else:
                # 这张 if-链是 kind → 事件的**唯一映射表**。`live_forensic_steps` 将来加第 6 类
                # 步而这里没接，落进兜底分支会被当成「无事发生」—— 事实照发、上屏静默，
                # 正是最难查的那类缺陷（改动在两个模块各对一半）。当场炸出来。
                raise ValueError(
                    f"取证编排发来未接线的事件步 {step.kind!r}：pipeline 的 kind→事件映射"
                    f"只认 {STEP_MEASURE!r}/{STEP_DEGRADED!r}/{STEP_COLLECT!r}/"
                    f"{STEP_JUDGE!r}/{STEP_ROUND!r}/{STEP_REPORT!r}，请在此显式接它"
                )
    else:
        # fixture：整包加载（含场景缓存）
        report_data = await source.compute(check)
        report_data["scene"].update(intake_meta)
        # 分档汇总数的**唯一真身是 points**：无论夹具里存的是什么，一律按点重算后覆盖，
        # 保证「报告内自洽」。夹具里存的数字若与点不符，由 CI 侧断言揪出（不在运行时静默放过）。
        fx_sampling = dict(report_data["sampling"])
        fx_points = fx_sampling.get("points") or []
        fx_flags = reach_flags(fx_points)  # 与 live 分支同一实现
        fx_sampling["timed_count"] = fx_flags.timed_count
        fx_sampling["in_reach_count"] = fx_flags.in_reach_count
        # 残差耗时 / 常态绕行标定**同样按点重算后覆盖**（与上面两个汇总数同一条纪律）：
        # 夹具里存着的那一份是烘快照那次量的，直接读它等于把「当时的解释」当
        # 「本次的解释」报给读者 —— 而 `rc-*` 这把版本键要的恰恰是后者。
        # ⚠️ **只对实测场做**（`interpolation == 'idw'`）：`circular_approx` 那份是距离模型的
        # 恒等式，标定会得到 k≡声明值、残差处处 0（`data_source.OfflineDataSource` 那段注释）。
        # 那种块发出去就是替一次没发生的测量举证，所以既不重算、也不声明这把版本键。
        if fx_sampling.get("interpolation") == "idw":
            _fx_mode = (report_data.get("caliber") or {}).get("travel_mode") or check.travel_mode
            _fx_cal = get_caliber(_fx_mode)
            fx_sampling["detour"] = detour_residual(
                tuple(report_data["scene"]["center"]),
                [(p["lng"], p["lat"]) for p in fx_points],
                [p.get("minutes") for p in fx_points],
                speed_m_per_min=_fx_cal.speed_m_per_min,
                declared_k=_fx_cal.detour_k,
            )
            # 键与键集同批发布：既然这次现算出了 `sampling.detour`，就**必须**声明这把版本。
            # 但只在口径块本来就存在时声明 —— 整块缺失的载荷（B0 要抓的那种）不该由这里
            # 凭空造一个 `caliber` 出来替它举证，那会把"没声明口径"洗成"声明了 rc-1"。
            if isinstance(report_data.get("caliber"), dict):
                report_data["caliber"]["reach_caliber_version"] = REACH_CALIBER_VERSION
        report_data["sampling"] = fx_sampling
        iso = {"isochrones": report_data["isochrones"], "sampling": fx_sampling,
               "sample_count": len(fx_points)}
        yield _ev("message", {"stage": "measure", "text": f"演示数据：fixture 等时圈（圆形近似）已加载，采样 {iso['sample_count']} 点（已测时 {iso['sampling']['timed_count']} · ≤{REACH_FULL_MIN:g}min 可达 {iso['sampling']['in_reach_count']}）"})
        yield _ev("evidence", {"stage": "measure", "evidence": {
            "evidence_id": f"ev-{task_id}-measure", "source_url": "fixture://measure", "source_type": "api_measure",
            "title": "采样点测时记录（fixture）", "excerpt": f"{iso['sample_count']} 点 · 已测时 {iso['sampling']['timed_count']} · ≤{REACH_FULL_MIN:g}min 可达 {iso['sampling']['in_reach_count']}",
            "credibility": 0.95, "collected_by": "L2-005", "captured_at": _now_iso(),
        }})
        yield _ev("progress", {"stage": "measure", "percent": STAGE_PERCENT["measure"], "stage_seq": 3, "evidence_count": 1})
        yield _ev("evidence", {"stage": "collect", "evidence": {
            "evidence_id": f"ev-{task_id}-collect", "source_url": "fixture://poi", "source_type": "poi_search",
            "title": "POI 采集（fixture）", "excerpt": f"共 {(report_data.get('poi') or {}).get('total', 0)} 处，圈内 {(report_data.get('poi') or {}).get('in_circle', 0)} 处",
            "credibility": 0.92, "collected_by": "L2-004", "captured_at": _now_iso(),
        }})
        yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 1})

    # ── diagnose（盲区/评分结论）───────────────────────────
    scores = report_data["scores"]
    if report_data.get("data_origin") == "offline":
        # P0-2：离线估算不产出可比评分/盲区，SSE 诚实标注
        yield _ev("message", {"stage": "diagnose", "percent": STAGE_PERCENT["diagnose"], "text": "离线估算模式：未联网采集 POI，评分与盲区待实时体检（本报告不可与实时分比较）"})
    else:
        yield _ev("message", {"stage": "diagnose", "percent": STAGE_PERCENT["diagnose"], "text": f"识别 {len(report_data['blindspots'])} 处服务盲区；综合评分 {scores['total']}（{_grade(scores['total'])}）"})
    if report_data["blindspots"]:
        b0 = report_data["blindspots"][0]
        yield _ev("evidence", {"stage": "diagnose", "evidence": {
            "evidence_id": f"ev-{task_id}-bs", "source_url": "live://blindspot", "source_type": "grid_scan",
            "title": f"盲区点位 {b0['id']}", "excerpt": f"1km 内无 {'、'.join(b0.get('missing_facilities', []))}",
            "credibility": 0.98, "collected_by": "L3-002", "captured_at": _now_iso(),
        }})
    yield _ev("progress", {"stage": "diagnose", "percent": STAGE_PERCENT["diagnose"], "stage_seq": 5, "evidence_count": 2})

    # ── report（D4 完整报告组装）──────────────────────────
    if report_data.get("data_origin") == "offline":
        yield _ev("message", {"stage": "report", "percent": STAGE_PERCENT["report"], "text": "离线估算报告已组装（骨架章节，评分/盲区留待实时体检）"})
    else:
        yield _ev("message", {"stage": "report", "percent": STAGE_PERCENT["report"], "text": "按 GB50180 生活圈标准撰写章节报告：养老配置与盲区整改优先级已标注"})
    
    # Phase 6：将动态选中的专家团队注入报告数据
    report_data["team"] = _team_payload(dispatch_ids, dispatch_reasons)

    # ── 落库前守卫：不合几何契约 ⇒ 置 failed，不得签收（同精报共用 _finalize_living_report）──
    # 实测 lc-c796c62d（迤栖村）：status=done / stage=audit / percent=100 / error=None，
    # 报告 isochrones=[] 且 poi.points=[]，scores.total=0、blindspots=1（面积=整张网格）。
    # ⇒ 用户读到「0 分 / 1 处盲区」，真实含义是「什么都没查到」。且顶层 7 个契约字段
    # **全部齐全** ⇒ 契约断言逐条通过，缺陷完全静默。
    # 判据**唯一实现**在 `living_circle.report_contract.assess_geometry`（与读路径同源）：
    #   · Tier A 内容缺件（live 无等时圈/无 POI）        → 报告不成立
    #   · Tier B 几何不自洽（盲区越出可达区、圈外点混入） → 报告会误导，同样不签发
    # 配额降级为 offline 的空白是**有意降级**（已有 P0-2 标注）→ 契约内部豁免，不受此守卫影响。
    # 4b：`reuse_window` 的发与不发由 `_finalize_living_report` 按 `data_mode` 判（演示态不发——
    # 那条链里没有 `CachingDataSource`、没有任何复用可言），这里只负责把**这次真实的模式**递进去。
    report_id, reason, report = _finalize_living_report(
        report_data, scene_key, replace_scene=False, data_mode=data_mode)
    yield _ev("progress", {"stage": "report", "percent": STAGE_PERCENT["report"], "stage_seq": 6, "evidence_count": len(report.get("evidence") or [])})

    if reason is not None:
        msg = f"质检未通过：{reason}。请更换中心点或检查配额"
        db.set_task_failed(task_id, msg)
        yield _ev("message", {"stage": "audit", "percent": 100, "text": msg})
        yield _ev("error", {"stage": "audit", "code": "invalid_geometry", "message": msg})
        yield _ev("done", {"reportId": None, "report_id": None, "status": "failed", "error": msg})
        return

    # ── audit（报告已由 _finalize_living_report 落库，此处标记任务终态 + 广播）────────
    db.mark_task_done(task_id, report_id)
    yield _ev("message", {"stage": "audit", "percent": STAGE_PERCENT["audit"], "text": "质检通过：证据溯源完整，报告已签发并归档"})
    yield _ev("progress", {"stage": "audit", "percent": 100, "stage_seq": 7, "evidence_count": len(report.get("evidence") or [])})
    yield _ev("report_ready", {"reportId": report_id, "report_id": report_id, "title": report["title"]})
    yield _ev("done", {"reportId": report_id, "report_id": report_id})


def _reuse_window() -> Dict[str, float]:
    """这份答复"在什么条件下会被直接复用"的三个真值（4b）。

    全部**引用现成常量**，不在这里再写一遍数字：屏上那句说明、以及"要不要给重算入口"的
    判断，都只能读自这些真值 —— 否则就是本仓第三次犯"文案与数据分家"（阈值改一次，
    屏幕上的话不会跟着改，而全量测试零红）。局部 import 与文件里其它 repository 引用同一条
    理由（`repository` 反向依赖 pipeline 侧的装配，模块级易生环）。
    """
    from app.living_circle.repository import DEFAULT_AUX_TTL_S, DEFAULT_REPORT_TTL_S

    return {
        "report_ttl_s": float(DEFAULT_REPORT_TTL_S),
        "aux_ttl_s": float(DEFAULT_AUX_TTL_S),
        "nearby_radius_m": float(NEARBY_CACHE_M),
    }


def refresh_report_for_display(report: Dict[str, Any]) -> Dict[str, Any]:
    """报告响应那一路的读侧装配：快照与当前装配器不同代 ⇒ 用载荷重装后再发出去。

    治的是这个：**正文/亮点/图件是写时装配后冻结落库的**，装配器此后继续变，而缓存命中路径
    直接回旧行不重装 ⇒ 改了 `diagnosis_templates` 对已缓存场景永远不可见（2026-10-07 实测：
    同一份官渡区载荷，存量 0 亮点/3 图/1152 字，当前代码重装 5 亮点/5 图/2560 字）。

    **只服务 `GET /api/reports/{id}` 这一个调用方。** 其余 `db.get_report` 的调用方
    （存在性检查、精炼 / 一页纸 / 复跑等派生链）必须继续吃固定快照 —— 派生要的是可复现
    输入，不是最新文案；把这层塞进 `db.get_report` 会顺手改掉它们的字节。

    三态一律"放行"，读路径不判可见性（签发是写路径 `assess_geometry` 的事，这里不越权）：
     · 同代次 → 直通，零额外 CPU；
     · 缺戳 / 异代次 → 重装（实测 `assemble_report` 对真实载荷 0.2–4.1 ms）；
     · 重装抛错 → 回落存量快照 + `logger.warning(exc_info)`。
    第三态不是"吞异常"：它换了个**有职责的**产物（快照本来就是兜底与审计副本，见
    `db.save_living_circle_report` 的角色声明），且把失败连栈打进日志，绝不空页、绝不 500。
    每态都记一行 `[narrative]` 读数 —— 读路径不判违规，但违规不能只有用户看得见。
    """
    report_id = report.get("id") if isinstance(report, dict) else None
    needed, why = narrative_refresh_needed(report, NARRATIVE_VERSION)
    if not needed:
        logger.info("[narrative] 直通 report_id=%s reason=%s", report_id, why or f"同代次 {NARRATIVE_VERSION}")
        return report
    try:
        rebuilt = assemble_report(
            report["living_circle"],
            report_id or "",
            db.get_living_circle_scene_key(report_id) if report_id else "",
            report.get("title") or "",
        )
    except Exception:
        logger.warning("[narrative] 重装失败，回落存量快照 report_id=%s", report_id, exc_info=True)
        return report
    logger.info("[narrative] 重装 report_id=%s reason=%s", report_id, why)
    return rebuilt


def _finalize_living_report(report_data, scene_key, replace_scene: bool = False, *,
                            data_mode: str):
    """组装外层 Report + 几何质检 + 落库；返回 `(report_id, 不合规原因或 None, Report)`。

    写路径**唯一收口**（粗报与后台精报共用）：避免两处各自拼报告 / 判契约 / 落库而漂移。
    ``replace_scene=True`` 时先清掉同 ``scene_key`` 旧报告（精报替换粗报，同场景仅保留最新）。

    ``data_mode`` 是**必填关键字参数**（不给默认值）：发不发 `reuse_window` 取决于"这次跑的是
    哪种模式"，而不是"走了哪个分支"。默认值存在 ＝ 新增调用点可以省略它、静默按 live 发；
    必填则逼每个调用点显式表态（与 `triad_from_points` 的 `blind_center` 同一条理由）。
    演示态（`'fixture'`）**不发**：那条链路里没有 `CachingDataSource`、没有任何复用可言，
    发出去就是让屏幕上那句"同参数 30 天内会被直接复用"承诺一条当下模式下不成立的规则。
    缺这一位时前端的降级是"只报时点与年龄"（`freshnessNote`），所以不发不等于功能坏掉。
    """
    report_id = _report_id(scene_key)
    # 4b · 复用条件随产物一起发出去。放在这个唯一收口而不是放在两个命中分支里：
    # 缓存命中、精扫重算、后台精报三条路都过这里 ⇒ 载荷不会出现"有时有、有时没有"的第二种形状。
    if data_mode != "fixture":
        report_data["reuse_window"] = _reuse_window()
    report = assemble_report(report_data, report_id, scene_key, "")
    # S32 · 形状闸上线观测：必须排在 `assess_geometry` **之前**。违规的那份接下来会被那道门
    # 判成不可展示、在这里早退，不落库 —— 若把读数挂在落库之后，"新闸第一批就拦住了东西"
    # 这件事恰恰只在被拦下的那批里成立，事后无处可看（新闸最坏的失效形态是静默，不是红）。
    observe_shape_gate(report_id, report_data)
    issues = assess_geometry(report_data)
    if not issues.ok:
        return report_id, issues.reason, report
    if replace_scene:
        db.delete_living_circle_reports_for_scene(scene_key)
    db.save_living_circle_report(report, scene_key=scene_key)
    return report_id, None, report


def _schedule_refine(client, check, repo, scene_key, dispatch_ids, dispatch_reasons, sample_profile):
    """后台精报：以 ``sample_profile`` 精采样 + 全量 POI 重算，产出精报**替换**粗报。

    fire-and-forget：出错只记日志，绝不带崩已交付的粗报/任务（粗报在进入此函数前已由
    尾部 ``_finalize_living_report`` 落库并 done）。精报结果写同 ``scene_key``，前端再取即得。

    ⚠ 这条链路**目前零生产调用点**（只有 `test_replace_scene_dormancy` / `test_degrade_chain`
    两个台架在驱动，判据 A/B/C 钉住 `replace_scene` 只能是字面 False）。`dispatch_reasons`
    是本轮补进来的形参：以前只带 ids 进来，落库时理由只能写空数组。留着这条休眠路径是因为
    "精报替换粗报"仍是既定能力，但它今天跑不到 —— 改动属修潜伏缺陷，不是修可见故障。
    """
    import asyncio

    async def _run():
        try:
            refined = await refine_live_with_profile(check, client, repo, sample_profile)
            # S-1（架构评审 P0-1）：精报若降级为离线估算 ⇒ **直接放弃，不落库、不替换**。
            # 否则 `replace_scene=True` 会先删后存（:462），而 `assess_geometry` 对 offline 整段
            # 豁免 ⇒ reason=None ⇒ 用离线骨架**覆盖并删除**已交付给用户的实时粗报。
            if (refined.get("data_origin") or "") == "offline":
                logger.warning(
                    "[living_circle] 精报降级为离线估算，保留粗报不替换（scene_key=%s, detail=%s）",
                    scene_key, (refined.get("degraded") or {}).get("detail") or "unknown",
                )
                return
            refined["team"] = _team_payload(dispatch_ids, dispatch_reasons)
            # 精报只由 live 路径调度（`refine_live_with_profile` 是 live 专属），故这里写死 live；
            # 它不省略参数是硬要求 —— `data_mode` 无默认值，漏传当场 TypeError 而不是静默按某档发。
            _, reason, _ = _finalize_living_report(
                refined, scene_key, replace_scene=True, data_mode="live")
            if reason is not None:
                logger.warning("[living_circle] 精报几何不成立，保留粗报：%s", reason)
            else:
                logger.info("[living_circle] 精报已替换粗报（scene_key=%s, profile=%s）", scene_key, sample_profile)
        except Exception as e:  # noqa: BLE001
            logger.warning("[living_circle] 后台精报失败，保留粗报：%s", e)

    return asyncio.create_task(_run())


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _grade(total: float) -> str:
    if total >= 85:
        return "优"
    if total >= 70:
        return "良"
    if total >= 55:
        return "中"
    return "差"