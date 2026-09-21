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
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, TypedDict

from app.core import db
from app.core.config import get_settings
from app.living_circle.assemble import assemble_living_circle
from app.living_circle.caliber import caliber_payload_key, get_caliber
from app.living_circle.data_source import (
    CheckParams,
    degrade_to_offline,
    load_poi,
    refine_live_with_profile,
)
from app.living_circle.geo_utils import haversine_m
from app.living_circle.isochrone import IsochroneEngine
from app.living_circle.report_contract import assess_geometry
from app.living_circle.scope import SpatialScope

from .diagnosis_templates import assemble_report

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
    from app.living_circle.repository import Repository, SqliteCache

    # v2：实时结果持久落盘（SqliteCache，独立 backend/lc_cache.db）——同中心 30 天秒开 + 无 AK 离线可查
    cache_path = Path(__file__).resolve().parent.parent.parent / "lc_cache.db"
    repo = Repository(backend=SqliteCache(cache_path))
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

    # ── 城市解析（阶段 2：与中心点同源）─────────────────────
    # ⚠️ 历史缺陷：前端把「当前展示报告」的城市塞进本次任务 —— 那是与本次查询**无关**的
    # 第三个来源（实测产出「名称=北京劲松 / 中心=昆明 / 城市=北京·朝阳」的自相矛盾报告）。
    # 现改为：显式 city > 中心点逆地理 > 留空。绝不从别的报告取。
    if not (params.get("city") or "").strip() and getattr(source, "client", None) is not None:
        rev = await source.client.reverse_geocoding(center)
        if rev and rev.get("city"):
            params["city"] = rev["city"]
            yield _ev("message", {"stage": "intake", "text": f"中心点逆地理定位：{rev.get('name') or rev['city']}"})

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

    # 从 params 中提取设施类别信息（若有）
    facility_cats = params.get("facility_categories", [])
    scene_name = params.get("scene_name", "未命名社区")

    dispatch_ids, dispatch_reasons = select_living_circle_team(
        scene_name=scene_name,
        facility_categories=facility_cats if isinstance(facility_cats, list) else [],
        travel_mode=travel_mode,
    )

    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-plan", "label": "专家队编排", "status": "working", "expert": "L3-002"}})
    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-dispatch", "label": f"按域指派 {len(dispatch_ids)} 位专家", "status": "done", "expert": "L3-002"}})
    yield _ev("message", {"stage": "plan", "percent": STAGE_PERCENT["plan"], "text": f"编排完成：{len(dispatch_ids)} 位专家就位，覆盖医疗/教育/购物/养老等核心民生领域"})
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
    )

    # ── measure（测时采样 + IDW 等时圈）────────────────────
    # CachingDataSource 透传 .client 但可能为 None（内层离线源）——判 None 决定 live/offline 分支
    live_client = getattr(source, "client", None)
    yield _ev("message", {"stage": "measure", "percent": 30, "text": "粗扫 400m 网格 → 15min 边界带加密 → 批量距离矩阵测时中…"})

    if live_client is not None:
        iso = await engine.compute(
            center,
            lambda pts: live_client.measure_matrix(travel_mode, pts, center),
            study_radius_m=check.study_radius_m, mode=check.sample_profile,
        )
        sample_minutes = [p["minutes"] for p in iso["sampling"]["points"]]
        n_reach = sum(1 for m in sample_minutes if m is not None)
        yield _ev("message", {"stage": "measure", "text": f"IDW 插值生成耗时场：采样 {iso['sample_count']} 点（可达 {n_reach}），5/10/15/20 分钟等值线族已提取"})
        yield _ev("evidence", {"stage": "measure", "evidence": {
            "evidence_id": f"ev-{task_id}-measure", "source_url": "live://measure", "source_type": "api_measure",
            "title": "采样点测时记录", "excerpt": f"批量算路返回 {n_reach} 条可达耗时",
            "credibility": 0.95, "collected_by": "L2-005", "captured_at": _now_iso(),
        }})
        yield _ev("progress", {"stage": "measure", "percent": STAGE_PERCENT["measure"], "stage_seq": 3, "evidence_count": 1})

        # 空间口径绑定（可达区/采集区/研究区三概念显式化）—— 与 LiveDataSource 同一构造，
        # 「圈内」从此只由 scope 决定，不再有 iso["isochrones"][-1] 这类按位置取环。
        scope = SpatialScope.from_iso(get_caliber(travel_mode), center, check.study_radius_m, iso)
        scope.invariant()

        # collect：POI 采集（半径唯一来自 scope.collect_radius_m；不再硬编码 2000）
        per_category, triads = await load_poi(live_client, center, scope.collect_radius_m, scope=scope)
        # 总量熔断降级（rev3 §四G / v3 §3.5）：预算耗尽时产出诚实离线报告（data_origin=offline,
        # 可视化占位、评分/盲区留待实时重检），**绝不**拿空 POI 硬算后被几何质检拦成「调研失败」。
        guard = getattr(live_client, "guard", None)
        if guard is not None and getattr(guard, "total_meltdown", False):
            report_data = await degrade_to_offline(check)
            report_data["degraded"] = {"reason": "baidu_quota_exhausted", "note": "百度调用预算耗尽，实时采集被熔断，已降级为离线估算"}
            yield _ev("message", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "text": "百度配额已用尽（总量熔断）：降级为离线估算，评分与盲区需配额恢复后实时重检"})
        else:
            yield _ev("message", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "text": f"8 类民生设施采集完成：总量 {sum(len(v) for v in per_category.values())} 处"})
            yield _ev("evidence", {"stage": "collect", "evidence": {
                "evidence_id": f"ev-{task_id}-collect", "source_url": "live://poi", "source_type": "poi_search",
                "title": "POI 采集", "excerpt": f"共 {sum(len(v) for v in per_category.values())} 处",
                "credibility": 0.92, "collected_by": "L2-004", "captured_at": _now_iso(),
            }})
            yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 2})

            # diagnose：统计/盲区/评分（确定性）—— 组装走全项目唯一实现
            report_data = assemble_living_circle(check, iso, per_category, triads, scope, intake_meta=intake_meta)
    else:
        # fixture：整包加载（含场景缓存）
        report_data = await source.compute(check)
        report_data["scene"].update(intake_meta)
        iso = {"isochrones": report_data["isochrones"], "sampling": report_data["sampling"],
               "sample_count": len(report_data["sampling"]["points"]),
               "reachable_count": sum(1 for p in report_data["sampling"]["points"] if p.get("reachable"))}
        yield _ev("message", {"stage": "measure", "text": f"演示数据：fixture 等时圈（圆形近似）已加载，采样 {iso['sample_count']} 点"})
        yield _ev("evidence", {"stage": "measure", "evidence": {
            "evidence_id": f"ev-{task_id}-measure", "source_url": "fixture://measure", "source_type": "api_measure",
            "title": "采样点测时记录（fixture）", "excerpt": f"{iso['sample_count']} 点 · 可达 {iso['reachable_count']}",
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
    report_data["team"] = {
        "expert_ids": dispatch_ids,
        "reasons": dispatch_reasons,
    }

    # ── 落库前守卫：不合几何契约 ⇒ 置 failed，不得签收（同精报共用 _finalize_living_report）──
    # 实测 lc-c796c62d（迤栖村）：status=done / stage=audit / percent=100 / error=None，
    # 报告 isochrones=[] 且 poi.points=[]，scores.total=0、blindspots=1（面积=整张网格）。
    # ⇒ 用户读到「0 分 / 1 处盲区」，真实含义是「什么都没查到」。且顶层 7 个契约字段
    # **全部齐全** ⇒ 契约断言逐条通过，缺陷完全静默。
    # 判据**唯一实现**在 `living_circle.report_contract.assess_geometry`（与读路径同源）：
    #   · Tier A 内容缺件（live 无等时圈/无 POI）        → 报告不成立
    #   · Tier B 几何不自洽（盲区越出可达区、圈外点混入） → 报告会误导，同样不签发
    # 配额降级为 offline 的空白是**有意降级**（已有 P0-2 标注）→ 契约内部豁免，不受此守卫影响。
    _scene_key_ = _scene_key(params)
    report_id, reason, report = _finalize_living_report(report_data, _scene_key_, replace_scene=False)
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


def _finalize_living_report(report_data, scene_key, replace_scene: bool = False):
    """组装外层 Report + 几何质检 + 落库；返回 `(report_id, 不合规原因或 None, Report)`。

    写路径**唯一收口**（粗报与后台精报共用）：避免两处各自拼报告 / 判契约 / 落库而漂移。
    ``replace_scene=True`` 时先清掉同 ``scene_key`` 旧报告（精报替换粗报，同场景仅保留最新）。
    """
    report_id = _report_id(scene_key)
    report = assemble_report(report_data, report_id, scene_key, "")
    issues = assess_geometry(report_data)
    if not issues.ok:
        return report_id, issues.reason, report
    if replace_scene:
        db.delete_living_circle_reports_for_scene(scene_key)
    db.save_living_circle_report(report, scene_key=scene_key)
    return report_id, None, report


def _schedule_refine(client, check, repo, scene_key, dispatch_ids, sample_profile):
    """后台精报：以 ``sample_profile`` 精采样 + 全量 POI 重算，产出精报**替换**粗报。

    fire-and-forget：出错只记日志，绝不带崩已交付的粗报/任务（粗报在进入此函数前已由
    尾部 ``_finalize_living_report`` 落库并 done）。精报结果写同 ``scene_key``，前端再取即得。
    """
    import asyncio

    async def _run():
        try:
            refined = await refine_live_with_profile(check, client, repo, sample_profile)
            refined["team"] = {"expert_ids": dispatch_ids, "reasons": []}
            _, reason, _ = _finalize_living_report(refined, scene_key, replace_scene=True)
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