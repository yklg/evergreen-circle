"""服务盲区识别（赛题口径）：可达区内 1km 半径三要素覆盖判定 + 灰区聚合。

判定：对**可达区**内的网格点，检查其 1km 圆内是否同时存在 菜市场 / 药店 / 小学；
缺失任一 → 该点判盲。相邻缺失点聚为连通簇，输出：盲区中心（簇质心）+ 缺失设施 +
最近各类设施（距离/方位）+ 灰区多边形。

## 本轮修复的两个结构性缺陷（Q1 本体）

1. **判定网格越出可达区**（旧：``xs = linspace(-study_radius_m, study_radius_m, n)``）
   判定网格铺满「研究区 ±2500m」，而采集区只有 2000m 半径 ⇒ 2km 外「**没查**」被当成
   「**没有**」，四个角点必然缺失 → 从角点起连通域 → 外边界 = 整张方形（5.4km，比研究区还大）。
   现在：网格铺 ±``scope.reach_circumradius_m``，且**只保留落在可达区多边形内的格**。
   可达区外没有「可达但缺设施」这回事，语义上就不该判盲。

2. **像素→米换算用了名义格距**（旧：``return miss, grid_m, center_idx``）
   名义 ``grid_m=200``，而 ``linspace`` 的实际格距是 ``2R/(n-1)``（27 格时 = 192.31m）
   ⇒ 所有多边形尺寸被放大 4%。现在 ``cover_matrix`` 返回**实际格距** ``step``，
   下游（``trace_exterior`` / ``_has_in_cluster`` / 簇质心）一律只用 ``step``，不再用名义值。

## 第三件事：采集区外沿的格必须标 unknown，不能判盲

判「某格 1km 内没有药店」的前提是**那个 1km 圆被采集区完整覆盖**。格越靠近采集边界，
其 1km 圆就有越大比例落在采集区外 —— 那部分「没查」，不构成「没有」。
故引入 ``judged``（可判定）掩码：``|cell| ≤ 采集半径 − 1km`` 的格才判盲，
其余落在可达区内的格计入 ``cells_unknown`` 并在报告口径里**显式暴露**。
⇒ 采集半径若算错，症状是「unknown 计数上升（可见、可诊断）」，而不是「盲区膨胀成整张网格（静默错误）」。
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from app.living_circle.contour import (
    blob_area,
    marching_squares_binary,
    mask_connect_center,
    smooth_ring,
    trace_exterior,
)
from app.living_circle.field import BlindnessField
from app.living_circle.geo_utils import (
    LngLat,
    direction_word,
    ensure_closed,
    haversine_m,
    point_in_ring,
    round_lnglat,
    to_local_xy,
    xy_to_lnglat,
)
from app.living_circle.scope import SpatialScope

_logger = logging.getLogger(__name__)

# 盲区判定半径（赛题标准）与判定网格
BLIND_RADIUS_M = 1000.0
BLIND_GRID_M = 200.0

# marching-squares 采样细化倍率：把每个判定格细分为 refine² 个子采样，
# 使边界能贴合设施真实覆盖（破除规则四边形）。取值平衡精度与开销。
MS_REFINE = 4

# 三要素键 → 前端缺位名（与契约 missing_facilities 一致）
TRIAD_LABEL: Dict[str, str] = {
    "market": "菜市场",
    "pharmacy": "药店",
    "primary": "小学",
}

TRIAD_KEYS = ("market", "pharmacy", "primary")

# 补点策略：按「最近替代距离」分档（数据驱动，可扩展策略类型）
#  ≤600m → 流动服务；600–1200m → 移动点/改道；>1200m → 新建
EFFORT_BY_DIST: Tuple[Tuple[float, str], ...] = (
    (600.0, "mobile_service"),
    (1200.0, "reroute"),
)

# 严重度分档阈值（gap 越大越严重）
SEV_HEAVY = 0.6
SEV_MEDIUM = 0.33
SEVERITIES = ("heavy", "medium", "light")


def judge_radius_m(scope: SpatialScope, radius_m: float = BLIND_RADIUS_M) -> float:
    """可判定半径：圆心到「1km 圆仍完整落在采集区内」的最远距离。

    = 采集半径 − 判定半径。可达区内超出该半径的格**不判盲**（数据不足以支撑结论）。
    """
    return max(0.0, float(scope.collect_radius_m) - float(radius_m))


def cover_matrix(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, Sequence[Tuple[float, float]]],
    grid_m: float = BLIND_GRID_M,
    radius_m: float = BLIND_RADIUS_M,
) -> Tuple[np.ndarray, float, Dict[str, int]]:
    """构建缺失掩码（True = 该格判盲）。

    网格铺 ``±scope.reach_circumradius_m``，仅保留两重筛选后的格：
      - ``inside``：格心落在可达区多边形内（可达区外不判盲）；
      - ``judged``：格心距中心 ≤ ``采集半径 − radius_m``（1km 圆被采集区完整覆盖）。

    返回 ``(miss, step, stats)``：
      - ``step`` 为**实际格距** ``2R/(n-1)``（不是名义 ``grid_m``）；
      - ``stats`` 为格数分档（``cells_inside`` / ``cells_judged`` / ``cells_unknown``），
        供报告口径显式暴露「有多少可达区内的格没被判定」。
    """
    scan = float(scope.reach_circumradius_m)
    k = max(1, int(math.ceil(scan / grid_m)))
    n = 2 * k + 1
    step = (2.0 * scan) / (n - 1)  # ← 真实格距（旧实现返回的是名义 grid_m，尺寸偏 4%）
    coords = np.linspace(-scan, scan, n)
    judge_r = judge_radius_m(scope, radius_m)

    inside = np.zeros((n, n), dtype=bool)
    judged = np.zeros((n, n), dtype=bool)
    for i in range(n):          # i = y 行
        for j in range(n):      # j = x 列
            x, y = float(coords[j]), float(coords[i])
            lng, lat = xy_to_lnglat(center, x, y)
            if not point_in_ring((lng, lat), scope.reach_ring):
                continue
            inside[i, j] = True
            if math.hypot(x, y) <= judge_r + 1e-9:
                judged[i, j] = True

    # 预转三要素为局部米坐标（加速 1km 命中判定）
    local: Dict[str, np.ndarray] = {}
    for k2, pts in triads.items():
        if not pts:
            continue
        local[k2] = np.array([_local_m(center, lng, lat) for (lng, lat) in pts], dtype=float)

    miss = np.zeros((n, n), dtype=bool)
    rows, cols = np.where(judged)
    for i, j in zip(rows, cols):
        x, y = float(coords[j]), float(coords[i])
        has_m = _has_within(x, y, local.get("market"), radius_m)
        has_f = _has_within(x, y, local.get("pharmacy"), radius_m)
        has_e = _has_within(x, y, local.get("primary"), radius_m)
        if (not has_m) or (not has_f) or (not has_e):
            miss[i, j] = True

    stats = {
        "cells_inside": int(inside.sum()),
        "cells_judged": int(judged.sum()),
        "cells_unknown": int((inside & ~judged).sum()),
    }
    return miss, float(step), stats


def _local_m(center: LngLat, lng: float, lat: float) -> Tuple[float, float]:
    from app.living_circle.geo_utils import to_local_xy

    return to_local_xy(center, lng, lat)


def _has_within(x: float, y: float, pts: Any, radius_m: float) -> bool:
    """局部米坐标点集内是否有 (x,y) 半径内的点（numpy 向量化）。"""
    if pts is None or len(pts) == 0:
        return False
    d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
    return bool((d2 <= radius_m * radius_m).any())


def _missing_nearest_m(miss_keys: Sequence[str], nearest: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """每个缺失类的小区最近替代距离。

    赛题口径下缺失类必无 1km 内设施，故 ``nearest`` 只可能在 >1km 处有值；
    若某缺失类连任何设施都没有（``nearest`` 里被跳过），按其最严重处理（``inf``）。
    """
    by_key = {n.get("facility"): n.get("distance_m") for n in nearest}
    return {k: float(by_key.get(k, float("inf"))) for k in miss_keys}


def _excess_farness(miss_nearest: Dict[str, float], min_gap: float = BLIND_RADIUS_M) -> float:
    """度量「超出必达下限的距离」而非绝对距离，保证三档真实可达（R2/架构审查）。

    ``farness = mean over 缺失类 of min(1, max(0, d_k − min_gap)/min_gap)``。
    缺失类若完全无设施（``inf``）→ 该项取 1（最严重，P1-1 回退）。
    归一到 [0,1]。
    """
    if not miss_nearest:
        return 0.0
    total = 0.0
    for d in miss_nearest.values():
        if d == float("inf"):
            total += 1.0
        else:
            total += min(1.0, max(0.0, d - min_gap) / min_gap)
    return total / len(miss_nearest)


def _gap_score(m: int, farness: float) -> float:
    """连续缺口指数 ∈ [0,1]：缺失占比 m/类数 + 超出必达下限的替代距离。

    ``m/类数`` 用 ``len(TRIAD_KEYS)`` 归一化（而非硬编码 3），未来加品类不失真（P1-2）。
    """
    if m <= 0:
        return 0.0
    m_norm = min(m / len(TRIAD_KEYS), 1.0)
    g = 0.6 * m_norm + 0.4 * farness
    return round(min(1.0, g), 3)


def _severity_of(gap: float) -> str:
    if gap >= SEV_HEAVY:
        return "heavy"
    if gap >= SEV_MEDIUM:
        return "medium"
    return "light"


def _strategy_for(distance_m: float) -> str:
    if distance_m == float("inf"):
        return "build"
    for threshold, strategy in EFFORT_BY_DIST:
        if distance_m <= threshold:
            return strategy
    return "build"


def _cluster_served(cluster: np.ndarray, step: float, radius_m: float = BLIND_RADIUS_M) -> int:
    """簇质心 1km 内的判盲格数（补点优先级的 serves 基准）。"""
    rows, cols = np.where(cluster)
    if len(rows) == 0:
        return 0
    cy, cx = float(rows.mean()), float(cols.mean())
    served = 0
    for r, c in zip(rows, cols):
        if math.hypot(c - cx, r - cy) * step <= radius_m:
            served += 1
    return int(served)


def _fixes_for(
    miss_keys: Sequence[str],
    miss_nearest: Dict[str, float],
    cluster_center: LngLat,
    served: int,
    gap: float,
) -> List[Dict[str, Any]]:
    """为每个缺失类生成补点处方；``_key_*`` 为全局优先级排序用内部字段，末尾剔除。"""
    out: List[Dict[str, Any]] = []
    for k in miss_keys:
        d = miss_nearest.get(k, float("inf"))
        out.append({
            "facility": TRIAD_LABEL.get(k, k),
            "point": [round(cluster_center[0], 6), round(cluster_center[1], 6)],
            "strategy": _strategy_for(d),
            "nearest_alt_m": None if d == float("inf") else round(d, 1),
            "served": served,
            "_key_gap": gap,
            "_key_serves": served,
        })
    return out


def _assign_priorities(fixes: List[Dict[str, Any]]) -> None:
    """按 gap↓、serves↓、设施名 排序，给全部补点处方连续唯一 priority。"""
    for pos, f in enumerate(
        sorted(fixes, key=lambda x: (-x.get("_key_gap", 0.0), -x.get("_key_serves", 0), x.get("facility", ""))),
        start=1,
    ):
        f["priority"] = pos
        f.pop("_key_gap", None)
        f.pop("_key_serves", None)


def find_blindspots_with_stats(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """识别盲区，并返回格数分档（供报告口径举证）。

    triads: {market/pharmacy/primary: [{lng,lat,name}, ...]}（已清洗）。
    """
    point_sets: Dict[str, List[Tuple[float, float]]] = {
        k: [round_lnglat(p["lng"], p["lat"]) for p in v if "lng" in p and "lat" in p]
        for k, v in triads.items()
    }
    miss, step, stats = cover_matrix(center, scope, point_sets, grid_m)
    scan = float(scope.reach_circumradius_m)

    # 盲区连续缺失场：以真实设施坐标建，供 marching-squares 按任意亚格点采样
    # （破除矩形伪象的边界层 —— 评审 P0 ①，field 与判定网格解耦）。
    blindness_field = BlindnessField.build(center, triads)

    if not miss.any():
        if stats["cells_unknown"]:
            _logger.info(
                "盲区判定：可达区内 %d 格未判定（采集区未覆盖其 1km 邻域）—— 非「无盲区」",
                stats["cells_unknown"],
            )
        return [], stats

    # 每个缺失簇独立聚合（在掩码中按连通域逐个提取）
    result: List[Dict[str, Any]] = []
    worked = np.zeros_like(miss)
    n = miss.shape[0]
    idx = 0
    for i in range(n):
        for j in range(n):
            if miss[i, j] and not worked[i, j]:
                cluster = mask_connect_center(miss & ~worked, (i, j))
                worked |= cluster

                # 簇质心（像素 → 米 → lnglat）；像素→米一律用真实格距 step
                rows, cols = np.where(cluster)
                cy = float(rows.mean())
                cx = float(cols.mean())
                cluster_center = xy_to_lnglat(center, cx * step - scan, cy * step - scan)

                miss_keys = [
                    k for k in TRIAD_KEYS
                    if not point_sets.get(k)
                    or not _has_in_cluster(cluster, center, scan, point_sets[k], step)
                ]
                if not miss_keys:
                    miss_keys = list(TRIAD_KEYS)  # 理论上必缺，兜底展示

                # 最近各类设施（距离 + 方位）
                nearest = []
                for k in TRIAD_KEYS:
                    if not point_sets.get(k):
                        continue
                    best_p = None
                    best_d = float("inf")
                    name = ""
                    for it in triads.get(k, []):
                        it_p = (it["lng"], it["lat"])
                        d = haversine_m(cluster_center, it_p)
                        if d < best_d:
                            best_d = d
                            best_p = it_p
                            name = it.get("name", "")
                    if best_p is not None:
                        nearest.append({
                            "facility": k,
                            "name": name,
                            "distance_m": round(best_d, 1),
                            "direction": direction_word(cluster_center, best_p),
                        })

                # 严重度/连续缺口指数/补点处方（纯函数，仅依赖 triad 中心 —— 装配层负责 reach/affected）
                miss_nearest = _missing_nearest_m(miss_keys, nearest)
                farness = _excess_farness(miss_nearest)
                gap = _gap_score(len(miss_keys), farness)
                severity = _severity_of(gap)
                served = _cluster_served(cluster, step)
                fixes = _fixes_for(miss_keys, miss_nearest, cluster_center, served, gap)

                # 灰区多边形：从连续缺失场抽取 smooth 边界（破除矩形伪象）
                # marching-squares 建于 field 之上（grid-agnostic），stage2 换 H3 不动这里。
                raw_xy = _cluster_footprint_ring(
                    blindness_field, cluster, step, scan, refine=MS_REFINE
                )
                # 双边界解耦（需求 §二·1 / §7.1.3）：raw=精确锯齿（供严格点内判断），
                # smoothed=显示圆角（默认渲染）。raw_xy 已是「相对 center 的米」坐标系，
                # 直投 xy_to_lnglat（勿再减 scan，否则双重偏移错位）。
                raw_lnglat = [xy_to_lnglat(center, v[0], v[1]) for v in raw_xy]
                sm_lnglat = [xy_to_lnglat(center, v[0], v[1]) for v in smooth_ring(raw_xy)]
                closed = ensure_closed(sm_lnglat)
                raw_closed = ensure_closed(raw_lnglat)
                cells_n = int(cluster.sum())
                idx += 1
                result.append({
                    "id": f"bs-{prefix}-{idx}",
                    "center": [round(cluster_center[0], 6), round(cluster_center[1], 6)],
                    "radius_m": int(BLIND_RADIUS_M),
                    "missing_facilities": [TRIAD_LABEL.get(k, k) for k in miss_keys if k in TRIAD_LABEL],
                    "nearest": nearest,
                    "severity": severity,
                    "gap_score": gap,
                    "fixes": fixes,
                    "polygon": {"type": "Polygon", "coordinates": [closed]},
                    "polygon_raw": {"type": "Polygon", "coordinates": [raw_closed]},
                    "footprint_meta": {
                        "cells": cells_n,
                        "grid_m": round(step, 3),
                        "resolution_m": round(step / MS_REFINE, 3),
                        "refine": MS_REFINE,
                        "area_m2": round(blob_area(raw_xy), 1),
                        "undersampled": cells_n <= 3,
                        "grid": "square",
                        "schema_version": 1,
                    },
                })
    # 全局排序：给全部补点处方分配连续唯一 priority（gap↓、serves↓）
    _fixes_all = [f for b in result for f in b.get("fixes", [])]
    _assign_priorities(_fixes_all)
    return result, stats


def find_blindspots(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
) -> List[Dict[str, Any]]:
    """识别盲区：契约 ``BlindSpot[]``（``find_blindspots_with_stats`` 的薄壳）。"""
    spots, _stats = find_blindspots_with_stats(center, scope, triads, grid_m=grid_m, prefix=prefix)
    return spots


def _has_in_cluster(
    cluster: np.ndarray,
    center: LngLat,
    scan_radius_m: float,
    pts_key: Sequence[Tuple[float, float]],
    step: float,
) -> bool:
    """簇内任一格 1km 圆内命中某类设施（像素→米一律用真实格距 step）。"""
    rows, cols = np.where(cluster)
    arr = np.array([_local_m(center, p[0], p[1]) for p in pts_key], dtype=float)
    for r, c in zip(rows, cols):
        x_m = float(c) * step - scan_radius_m
        y_m = float(r) * step - scan_radius_m
        if _has_within(x_m, y_m, arr, BLIND_RADIUS_M):
            return True
    return False


def _cluster_footprint_ring(
    field: "BlindnessField",
    cluster: np.ndarray,
    step: float,
    scan: float,
    refine: int = MS_REFINE,
) -> List[List[float]]:
    """簇的连续边界环（物理米坐标，相对场地中心）。

    在簇的像素 bbox **外扩 1 判定格** 内，每个判定格按 ``refine`` 细分，对 ``field``
    采样后跑 marching-squares → 返回含簇质心的主环。

    外扩原因：marching-squares 在「内侧区域被采样窗完整包围」时才能闭合。若直接把
    采样窗取成簇 bbox，簇填满窗口（如整片可达区皆盲）时四角全是内侧、无 served 环
    ⇒ 不产生任何线段 ⇒ 环为空。外扩 1 格让簇外的 served 格进入窗内，正常闭合。

    **兜底**：若簇在采样窗内仍无界（整片可达区全盲），marching-squares 无环可闭合，
    退化为 ``trace_exterior`` 沿簇掩码外边界走环（保证闭合，边界沿格边、仍为方形）。
    既保证每个盲区必有多边形，又让「有 served 邻居」的主流场景吃到平滑边界。
    像素→米沿用判定约定：``x = col*step - scan``、``y = row*step - scan``。
    """
    rows, cols = np.where(cluster)
    if len(rows) == 0:
        return []
    c_min, c_max = int(cols.min()), int(cols.max())
    r_min, r_max = int(rows.min()), int(rows.max())
    pad = 1  # 判定格外扩单元数，保证簇外有 served 环 → marching 可闭合
    # 采样原点（米）：外扩后的 bbox 左上角，含每个判定格 refine 个子采样
    x0 = float(c_min - pad) * step - scan
    y0 = float(r_min - pad) * step - scan
    nx = (c_max - c_min + 1 + 2 * pad) * refine
    ny = (r_max - r_min + 1 + 2 * pad) * refine
    # 实际采样步长 = 判定格距 / refine
    h = step / refine if refine > 0 else step
    loops = marching_squares_binary(field.read, x0, y0, nx, ny, h, level=0.5)
    if not loops:
        # 无 served 环可闭合（整片皆盲）→ 沿簇掩码外边界兜底，保证闭合
        return [
            [px * step - scan, py * step - scan] for px, py in trace_exterior(cluster, 1.0)
        ]
    # 簇质心（米坐标）用于选主环
    cy = float(rows.mean()) * step - scan
    cx = float(cols.mean()) * step - scan
    cx_off, cy_off = cx - x0, cy - y0
    return loose_pick_ring(loops, cx_off, cy_off)


def loose_pick_ring(
    loops: List[List[List[float]]], px: float, py: float
) -> List[List[float]]:
    """在环族中选包含 (px,py) 者（物理米坐标，点相对采样原点）；缺测时返回最大环。"""
    # 每环面积（鞋带）
    best = None
    best_area = -1.0
    for ring in loops:
        area = blob_area(ring)
        contained = _point_in_xy_ring(ring, px, py)
        if contained or area > best_area:
            if area > best_area:
                best_area = area
                best = ring
    return best or (loops[0] if loops else [])


def _point_in_xy_ring(ring: Sequence[Sequence[float]], x: float, y: float) -> bool:
    """点 (x,y) 是否在多边形内（物理米坐标，首尾一致）。"""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) < 3:
        return False
    inside = False
    n = len(pts)
    for i in range(n - 1):
        xi, yi = pts[i]
        xj, yj = pts[i + 1]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
    return inside
