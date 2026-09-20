"""生活圈体检报告的**唯一组装实现**（跨数据源共用）。

## 为什么必须唯一

修复前有两份等价实现：``pipeline._assemble``（live 分支使用）与
``LiveDataSource.compute``（一份完整副本）。两份实现的成因不是「有人偷懒」，而是
**架构缺了一块**：组装需要「测时 → 采集 → 统计 → 判盲 → 评分 → 组装」全链路，
而数据源接口 ``DataSource.compute()`` 是**黑盒** —— pipeline 要在 measure/collect
阶段往外发 SSE 进度事件，于是只能自己再走一遍。

本轮的处置不是「把两份对齐」，而是**把组装与采集各收敛到一处**：

- 组装 → 本模块 ``assemble_living_circle``
- 采集 → ``data_source.load_poi``

两个调用方（pipeline / ``LiveDataSource``）退回为纯编排，不再各自携带业务规则。
（更彻底的根治 —— 让 ``compute()`` 支持 ``on_progress`` 回调、连编排也不重复 ——
属接口契约变更，按计划留待 v4.1 阶段 10 的传输层归一。）

## 口径唯一来源

组装里的一切空间判断都走 :class:`SpatialScope`（可达区 / 采集区 / 研究区的显式绑定），
没有 ``iso["isochrones"][-1]`` 这类「按位置取环」，也没有硬编码的 2000 / 2500。
"""
from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Dict, List, Optional

import numpy as np

from app.living_circle.blindspot import TRIAD_LABEL, find_blindspots_with_stats
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import point_in_ring, ring_area_km2, to_local_xy
from app.living_circle.isochrone import idw_for_points
from app.living_circle.poi import to_points, to_stats
from app.living_circle.scope import SpatialScope
from app.living_circle.scoring import compute_scores, triad_from_points

# 受影响人群估算口径（规划基准，非采集实测；见 R4/诚实代理）
DEMAND_DENSITY_HH_KM2 = 1200.0
HH_SIZE = 2.6


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ring_of(b: Dict[str, Any]) -> Optional[List[Any]]:
    """盲区 GeoJSON polygon 外环（closed lnglat）。"""
    poly = b.get("polygon") or {}
    coords = poly.get("coordinates") or [None]
    return coords[0]


def _reach_for(center_pt: tuple, field_fn: Any, b: Dict[str, Any]) -> Dict[str, Any]:
    """真实可达分钟：优先等时圈实测（field_fn/IDW, isochrone_based=true）。

    离线/无等时圈采样时降级为最近替代距离 / 80（isochrone_based=false，如实标注 R3/P2-6）。
    """
    rw = field_fn(center_pt)
    if rw is not None:
        return {"real_walk_min": round(float(rw), 1), "isochrone_based": True}
    ds = [n.get("distance_m") for n in b.get("nearest", []) if n.get("distance_m")]
    if ds:
        return {"real_walk_min": round(min(ds) / 80.0, 1), "isochrone_based": False}
    return {"real_walk_min": None, "isochrone_based": False}


def _affected_for(ring: Any, center: tuple, sample_pts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """受影响人群诚实代理（R1/R4）：采样点实测 + 密度估算。

    无盲区多边形或无采样点（含离线）→ 返回 null，不抛伪代理数。
    """
    if not ring or not sample_pts:
        return None
    sites = sum(1 for sp in sample_pts if point_in_ring((sp["lng"], sp["lat"]), ring))
    area = ring_area_km2(ring, center)
    hh = int(area * DEMAND_DENSITY_HH_KM2)
    return {
        "sampling_sites": sites,
        "estimated_households": hh,
        "estimated_residents": int(hh * HH_SIZE),
        "provenance": "proxy",
        "note": f"按 {DEMAND_DENSITY_HH_KM2:g} 户/km² 规划基准估算，仅供整改优先级参考，非真实人口数据",
    }


def assemble_living_circle(
    check: Any,
    iso: Dict[str, Any],
    per_category: Dict[str, List[Dict[str, Any]]],
    triads: Dict[str, List[Dict[str, Any]]],
    scope: SpatialScope,
    data_origin: str = "live",
    intake_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """由阶段产物组装 ``LivingCircleReport``（对齐前端 F0 契约）。

    参数
    ----
    check       : ``CheckParams``（含 scene/travel_mode/study_radius/sample_profile）
    iso         : ``IsochroneEngine.compute`` 输出（等时圈族 + 采样点）
    per_category: 8 类民生 POI（已清洗）
    triads      : 盲区三要素 POI（已清洗）
    scope       : 本次运行的空间口径绑定（可达区 / 采集区）
    intake_meta : intake 阶段的**溯源标注**（如名称与中心点是否同源）。
                  由编排层（pipeline）注入，组装层只负责落到 ``scene`` 上，
                  不做判定 —— 判定需要「样例库」这类 intake 知识，不属于几何组装。
    """
    center = tuple(check.center)
    sample_pts = iso["sampling"]["points"]
    sample_minutes = [sp["minutes"] for sp in sample_pts]
    sample_xy = np.array([to_local_xy(center, sp["lng"], sp["lat"]) for sp in sample_pts])

    # ── 类别统计（「圈内」= 可达区，由 scope 唯一决定）──────────────
    stats = to_stats(per_category, triads, scope, center)
    times_by_cat: Dict[str, List[Optional[float]]] = {}
    for s in stats:
        items = per_category.get(s["category"], [])
        if not items:
            continue
        query = np.array([to_local_xy(center, it["lng"], it["lat"]) for it in items])
        times = idw_for_points(sample_xy, sample_minutes, query)
        times_by_cat[s["category"]] = times
        paired = [(t, it) for t, it in zip(times, items) if t is not None]
        if paired:
            best_t, best_it = min(paired, key=lambda x: x[0])
            s["min_minutes"], s["nearest_name"] = best_t, best_it.get("name") or s.get("nearest_name")
        else:
            s["min_minutes"] = None

    def field_fn(pt: tuple) -> Optional[float]:
        xy = np.array([to_local_xy(center, pt[0], pt[1])])
        v = idw_for_points(sample_xy, sample_minutes, xy)[0]
        # 口径来自 scope（旧实现硬编码 get_caliber("walking")，忽略 travel_mode → 骑行/驾车场景口径错）
        return None if v is None or v > scope.reach_min else v

    def full(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"lng": it["lng"], "lat": it["lat"], "name": it.get("name", "")} for it in items]

    triads_conclusion = triad_from_points(
        full(triads.get("market", [])),
        full(triads.get("pharmacy", [])),
        full(triads.get("primary", [])),
        field_fn,
    )

    # ── 盲区（判定网格限定在可达区内；不可判定格计入 stats 显式暴露）──
    blindspots, blind_stats = find_blindspots_with_stats(
        center, scope, triads, prefix=check.scene_name
    )
    # 装配层补齐 真实可达(reach) + 受影响人口(affected) —— 二者数据(sampling/field_fn)只在此层持有(R1/R3)
    for b in blindspots:
        b["reach"] = _reach_for(tuple(b["center"]), field_fn, b)
        b["affected"] = _affected_for(_ring_of(b), center, sample_pts)
    scores = compute_scores(stats, triads_conclusion, len(blindspots))

    # ── 口径举证（唯一实现；含本次实测的空间量，便于回答「盲区为什么只有这么大」）──
    caliber = get_caliber(check.travel_mode)
    caliber_report = scope.payload(caliber, blind_stats)
    caliber_report["sample_profile"] = check.sample_profile

    return {
        "scene": {
            "name": check.scene_name,
            "city": check.city,
            "address": check.address,
            "center": [round(center[0], 6), round(center[1], 6)],
            "study_radius_m": int(check.study_radius_m),
            **(intake_meta or {}),
        },
        "generated_at": _now_iso(),
        "data_origin": data_origin,
        "caliber": caliber_report,
        "isochrones": iso["isochrones"],
        "sampling": iso["sampling"],
        "poi": {
            "categories": stats,
            "total": sum(s["total"] for s in stats),
            "in_circle": sum(s["in_circle"] for s in stats),
            "points": to_points(per_category, times_by_cat, scope, center),
        },
        "blindspots": blindspots,
        "scores": scores,
    }


def annotate_blindspots(report: Dict[str, Any]) -> Dict[str, Any]:
    """为**预计算**报告（fixture/快照）补齐盲区新字段，避免手编 JSON 造成契约漂移（契约文档 §8）。

    复用同一套纯函数与装配原语（severity/gap/fixes/reach/affected），并与实时
    ``assemble_living_circle`` 保持同构，保证演示态与实时态语义一致：
    - ``severity/gap_score`` 由 ``nearest`` 替代距离 + ``missing_facilities`` 推导（赛题口径）；
    - ``fixes`` 由缺失类与替代距离推导，并按 gap/serves 全局分配连续 priority；
    - ``reach`` 优先用报告中已实测的等时圈采样分钟(IDW)，否则降级 nearest/80；
    - ``affected`` 用采样点 polygon∩points 计数 + 密度估算；无采样 → null（R4）。
    返回新报告（浅拷贝，不就地改入参）。
    """
    import numpy as np  # noqa: PLC0415 局部引入以保持 assemble 顶层简洁

    from app.living_circle.blindspot import (
        _assign_priorities,
        _excess_farness,
        _fixes_for,
        _gap_score,
        _missing_nearest_m,
        _severity_of,
    )

    out = copy.deepcopy(report)
    center = tuple(out["scene"]["center"])
    sample_pts = (out.get("sampling") or {}).get("points") or []
    # 采样点与分钟**同源同长**（均含 None）交给 idw_from_local 内部按 valid 过滤，
    # 否则先滤 minutes 会与全量 sample_xy 脱节引发长度 assert（旧快照 498/497 实测崩过）。
    sample_minutes = [sp.get("minutes") for sp in sample_pts]
    sample_ok = bool(sample_pts) and any(m is not None for m in sample_minutes)

    if sample_ok:
        sample_xy = np.array([to_local_xy(center, sp["lng"], sp["lat"]) for sp in sample_pts])
        field_fn: Any
        field_fn = lambda pt: _idw_one(sample_xy, sample_minutes, center, pt)
    else:
        # 无采样/离线 → reach 降级 nearest/80，affected 置 null（R4 诚实）
        field_fn = None

    bs_list = out.get("blindspots") or []
    fixes_pool: List[Dict[str, Any]] = []
    for b in bs_list:
        # 防御：残缺盲区（缺 center/polygon，几何无法闭合）不参与增强，原样保留，绝不崩
        if not isinstance(b, dict) or not b.get("center") or not b.get("polygon"):
            continue
        missing_labels = b.get("missing_facilities") or []
        nearest = b.get("nearest") or []
        # missing_facilities 是中文标签 → 映射回 key；未知标签按原样跳过（不参与修饰）
        key_of_label = {v: k for k, v in TRIAD_LABEL.items()}
        miss_keys = [key_of_label.get(l, l) for l in missing_labels]
        miss_nearest = _missing_nearest_m(miss_keys, nearest)
        farness = _excess_farness(miss_nearest)
        gap = _gap_score(len(miss_keys) if miss_keys else 1, farness)
        b["severity"] = _severity_of(gap)
        b["gap_score"] = gap
        fix_served = _served_from_sampling(b, sample_pts)
        fixes = _fixes_for(miss_keys, miss_nearest, tuple(b["center"]), fix_served, gap)
        b["fixes"] = fixes
        fixes_pool.extend(fixes)
        # reach：以当前报告采样态为准重算（isochrone_based 忠实反映是否有实测采样，R3 幂等）
        if field_fn is not None:
            rw = field_fn(tuple(b["center"]))
            b["reach"] = (
                {"real_walk_min": round(float(rw), 1), "isochrone_based": True}
                if rw is not None
                else {"real_walk_min": None, "isochrone_based": False}
            )
        else:
            b["reach"] = _reach_for(tuple(b["center"]), lambda _p: None, b)
        # affected：无采样/离线 → null（R4），否则诚实代理（以当前采样态重算，幂等）
        b["affected"] = (
            _affected_for(_ring_of(b), center, sample_pts) if sample_ok else None
        )
    if fixes_pool:
        _assign_priorities(fixes_pool)
    return out


def _idw_one(sample_xy, sample_minutes, center, pt) -> Optional[float]:
    """报告已实测采样点上的单点 IDW 分钟（isochrone_based=true 的数据源）。"""
    from app.living_circle.isochrone import idw_for_points

    query = np.array([to_local_xy(center, pt[0], pt[1])])
    return idw_for_points(sample_xy, sample_minutes, query)[0]


def _served_from_sampling(b: Dict[str, Any], sample_pts: List[Dict[str, Any]]) -> int:
    """补点覆盖的盲簇采样点数（确定性代理，替代实时 pipeline 的格数即可用）。"""
    if not sample_pts or not b.get("center"):
        return 0
    from app.living_circle.geo_utils import haversine_m, point_in_ring

    ring = _ring_of(b)
    c = tuple(b["center"])
    return sum(1 for sp in sample_pts if point_in_ring((sp["lng"], sp["lat"]), ring))
