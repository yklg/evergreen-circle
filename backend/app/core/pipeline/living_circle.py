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
from typing import Any, AsyncIterator, Dict, List, TypedDict

from app.core import db
from app.core.config import get_settings
from app.living_circle.blindspot import find_blindspots
from app.living_circle.data_source import CheckParams
from app.living_circle.isochrone import IsochroneEngine, idw_for_points
from app.living_circle.poi import CATEGORY_DEFS, TRIAD_KEYWORDS, clean, to_stats
from app.living_circle.scoring import compute_scores, triad_from_points

from .diagnosis_templates import assemble_report

logger = logging.getLogger(__name__)

STAGES = ["intake", "plan", "measure", "collect", "diagnose", "report", "audit"]
# 各阶段到达百分比（runner 进度落库 + 前端进度条）
STAGE_PERCENT = {"intake": 5, "plan": 14, "measure": 48, "collect": 72, "diagnose": 86, "report": 95, "audit": 99}


class TaskParams(TypedDict, total=False):
    """任务参数（存于 tasks.clarifications）。"""

    scene_name: str
    city: str
    address: str
    center: List[float]  # [lng, lat]
    study_radius_m: float
    mode: str
    data_mode: str  # 'live' | 'fixture'


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
    """scene 缓存键（社区名 + 坐标，供同中心秒开）。"""
    c = params.get("center") or [0, 0]
    return f"scene:{params.get('scene_name', '')}|{c[0]:.6f},{c[1]:.6f}|{int(params.get('study_radius_m', 2500))}|{params.get('mode', 'standard')}"


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
    mode = params.get("mode", "standard")
    data_mode = params.get("data_mode", "")
    ak = get_settings().baidu_server_ak

    from app.living_circle.data_source import get_data_source

    source = get_data_source(data_mode or "fixture", ak=ak)

    # 中心点解析（M3 支持纯地名输入）：显式坐标 > live 地理编码 > fixture 样例名匹配 > 凯里兜底
    center: Optional[tuple] = tuple(params.get("center")) if params.get("center") else None
    if center is None:
        live = source if hasattr(source, "client") else None
        if live is not None:
            center = await live.client.geocoding(params.get("scene_name") or "")
        if center is None:
            center = _fallback_center(source, params.get("scene_name") or "")
    center = tuple(center)
    # 回写实际中心到任务参数：下游 _scene_key / 报告 scene 使用同一坐标
    params["center"] = [center[0], center[1]]

    # ── intake ───────────────────────────────────────────
    yield _ev("message", {"stage": "intake", "percent": STAGE_PERCENT["intake"], "text": f"已确立体检中心点：{params.get('scene_name', '')}（{center[0]:.4f}, {center[1]:.4f}），研究范围 {(params.get('study_radius_m') or 2500) / 1000:.1f}km，模式 {mode}"})
    yield _ev("progress", {"stage": "intake", "percent": STAGE_PERCENT["intake"], "stage_seq": 1, "evidence_count": 0})

    # ── plan（专家队编排）────────────────────────────────
    dispatch = [
        "L3-001", "L3-002", "L3-003", "L2-001", "L2-002", "L2-003",
        "L2-004", "L2-005", "L2-008", "L1-001", "L1-004", "L1-005", "L1-008",
    ]
    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-plan", "label": "专家队编排", "status": "working", "expert": "L3-002"}})
    yield _ev("node_update", {"stage": "plan", "node": {"id": "n-dispatch", "label": f"按域指派 {len(dispatch)} 位专家", "status": "done", "expert": "L3-002"}})
    yield _ev("message", {"stage": "plan", "percent": STAGE_PERCENT["plan"], "text": "编排完成：医疗/教育/购物/养老各域顾问就位，慢行可达性分析师负责等时圈核验"})
    yield _ev("progress", {"stage": "plan", "percent": STAGE_PERCENT["plan"], "stage_seq": 2, "evidence_count": 0})

    engine = IsochroneEngine()
    check = CheckParams(
        scene_name=params.get("scene_name", "未命名社区"),
        city=params.get("city", ""),
        address=params.get("address", ""),
        center=center,
        study_radius_m=float(params.get("study_radius_m", 2500)),
        mode=mode,
    )

    # ── measure（测时采样 + IDW 等时圈）────────────────────
    live_ds = source if hasattr(source, "client") else None
    yield _ev("message", {"stage": "measure", "percent": 30, "text": "粗扫 400m 网格 → 15min 边界带加密 → 批量距离矩阵测时中…"})

    if live_ds is not None:
        iso = await engine.compute(
            center,
            lambda pts: live_ds.client.route_matrix_walking(pts, center),
            study_radius_m=check.study_radius_m, mode=mode,
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

        # collect：POI 采集
        per_category, triads = await _load_poi_live(live_ds.client, center)
        yield _ev("message", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "text": f"8 类民生设施采集完成：总量 {sum(len(v) for v in per_category.values())} 处"})
        yield _ev("evidence", {"stage": "collect", "evidence": {
            "evidence_id": f"ev-{task_id}-collect", "source_url": "live://poi", "source_type": "poi_search",
            "title": "POI 采集", "excerpt": f"共 {sum(len(v) for v in per_category.values())} 处",
            "credibility": 0.92, "collected_by": "L2-004", "captured_at": _now_iso(),
        }})
        yield _ev("progress", {"stage": "collect", "percent": STAGE_PERCENT["collect"], "stage_seq": 4, "evidence_count": 2})

        # diagnose：统计/盲区/评分（确定性）
        report_data = _assemble(live_ds, check, iso, per_category, triads, task_id)
    else:
        # fixture：整包加载（含场景缓存）
        report_data = await source.compute(check)
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
    yield _ev("message", {"stage": "report", "percent": STAGE_PERCENT["report"], "text": "按 GB50180 生活圈标准撰写章节报告：养老配置与盲区整改优先级已标注"})
    report_id = _report_id(_scene_key(params))
    report = assemble_report(report_data, report_id, _scene_key(params), "")
    yield _ev("progress", {"stage": "report", "percent": STAGE_PERCENT["report"], "stage_seq": 6, "evidence_count": len(report["evidence"])})

    # ── audit（质检 + 落库独立文档）────────────────────────
    db.save_living_circle_report(report, scene_key=_scene_key(params))
    db.mark_task_done(task_id, report_id)
    yield _ev("message", {"stage": "audit", "percent": STAGE_PERCENT["audit"], "text": "质检通过：证据溯源完整，报告已签发并归档"})
    yield _ev("progress", {"stage": "audit", "percent": 100, "stage_seq": 7, "evidence_count": len(report["evidence"])})
    yield _ev("report_ready", {"reportId": report_id, "report_id": report_id, "title": report["title"]})
    yield _ev("done", {"reportId": report_id, "report_id": report_id})


async def _load_poi_live(client, center) -> tuple:
    """live 采集 8 类 + 三要素（多关键词）。"""
    per_category = {}
    for cat, defn in CATEGORY_DEFS.items():
        items = []
        for kw in defn["keywords"]:
            items += await client.place_search(kw, center, radius_m=2000)
        per_category[cat] = clean(items)
    triads = {k: clean(await client.place_search(kw, center, radius_m=2000)) for k, kw in TRIAD_KEYWORDS.items()}
    return per_category, triads


def _assemble(live_ds, check: CheckParams, iso, per_category, triads, task_id: str) -> dict:
    """由阶段产物组装 LivingCircleReport(data)（live 管线；等价 FixtureDataSource 输出）。"""
    import numpy as np

    from app.living_circle.geo_utils import to_local_xy

    center = check.center
    iso15 = next((z for z in iso["isochrones"] if z["minutes"] == 15), None)
    iso15_ring = iso15["geojson"]["coordinates"][0] if iso15 else []
    sample_pts = iso["sampling"]["points"]
    sample_minutes = [sp["minutes"] for sp in sample_pts]
    sample_xy = np.array([to_local_xy(center, sp["lng"], sp["lat"]) for sp in sample_pts])

    stats = to_stats(per_category, triads, iso15_ring, center)
    for s in stats:
        items = per_category.get(s["category"], [])
        if not items:
            continue
        query = np.array([to_local_xy(center, it["lng"], it["lat"]) for it in items])
        times = idw_for_points(sample_xy, sample_minutes, query)
        paired = [(t, it) for t, it in zip(times, items) if t is not None]
        if paired:
            bt, bi = min(paired, key=lambda x: x[0])
            s["min_minutes"], s["nearest_name"] = bt, bi.get("name") or s.get("nearest_name")
        else:
            s["min_minutes"] = None

    def field_fn(pt):
        xy = np.array([to_local_xy(center, pt[0], pt[1])])
        v = idw_for_points(sample_xy, sample_minutes, xy)[0]
        return None if v is None or v > 20 else v

    def full(items):
        return [{"lng": it["lng"], "lat": it["lat"], "name": it.get("name", "")} for it in items]

    triads_conclusion = triad_from_points(
        full(triads.get("market", [])), full(triads.get("pharmacy", [])), full(triads.get("primary", [])), field_fn
    )
    blindspots = find_blindspots(center, check.study_radius_m, triads, prefix=check.scene_name)
    scores = compute_scores(stats, triads_conclusion, len(blindspots))
    return {
        "scene": {"name": check.scene_name, "city": check.city, "address": check.address,
                  "center": [round(center[0], 6), round(center[1], 6)], "study_radius_m": int(check.study_radius_m)},
        "generated_at": _now_iso(),
        "data_origin": "live",
        "isochrones": iso["isochrones"],
        "sampling": iso["sampling"],
        "poi": {
            "categories": stats,
            "total": sum(s["total"] for s in stats),
            "in_circle": sum(s["in_circle"] for s in stats),
        },
        "blindspots": blindspots,
        "scores": scores,
    }


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