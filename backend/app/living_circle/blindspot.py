"""服务盲区识别（赛题口径）：研究网格上 1km 半径内三要素覆盖判定 + 灰区聚合。

判定：对研究范围内的 200m 网格点，检查其 1km 圆内是否同时存在
菜市场 / 药店 / 小学；缺失任一 → 该点判盲。相邻缺失点聚为连通簇，
输出：盲区中心（簇质心）+ 缺失设施 + 最近各类设施（距离/方位）+ 灰区多边形。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from app.living_circle.contour import mask_connect_center, smooth_ring, trace_exterior
from app.living_circle.geo_utils import (
    LngLat,
    direction_word,
    ensure_closed,
    haversine_m,
    round_lnglat,
    xy_to_lnglat,
)

# 盲区判定半径（赛题标准）与判定网格
BLIND_RADIUS_M = 1000.0
BLIND_GRID_M = 200.0

# 三要素键 → 前端缺位名（与契约 missing_facilities 一致）
TRIAD_LABEL: Dict[str, str] = {
    "market": "菜市场",
    "pharmacy": "药店",
    "primary": "小学",
}

TRIAD_KEYS = ("market", "pharmacy", "primary")


def cover_matrix(
    center: LngLat,
    study_radius_m: float,
    triads: Dict[str, Sequence[Tuple[float, float]]],
    grid_m: float = BLIND_GRID_M,
    radius_m: float = BLIND_RADIUS_M,
) -> Tuple[np.ndarray, float, float]:
    """构建缺失掩码（True=该格 1km 内缺要素）。

    返回 (miss_mask, grid_step, center_ij_index)；中心格在掩码中点。
    """
    n = max(3, int(math.ceil(study_radius_m / grid_m)) * 2 + 1)
    xs = np.linspace(-study_radius_m, study_radius_m, n)
    ys = np.linspace(-study_radius_m, study_radius_m, n)

    # 预转三要素为局部米坐标（加速 1km 命中判定）
    local: Dict[str, List[Tuple[float, float]]] = {}
    for k, pts in triads.items():
        if not pts:
            continue
        arr = np.array(
            [# x 米, y 米
                (dx, dy)
                for (lng, lat) in pts
                for (dx, dy) in [_local_m(center, lng, lat)]
            ],
            dtype=float,
        )
        local[k] = arr

    P = local.get("market")
    F = local.get("pharmacy")
    E = local.get("primary")

    miss = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(n):
            x, y = xs[j], ys[i]
            has_m = _has_within(x, y, P, radius_m)
            has_f = _has_within(x, y, F, radius_m)
            has_e = _has_within(x, y, E, radius_m)
            if (not has_m) or (not has_f) or (not has_e):
                miss[i, j] = True
    center_idx = (n - 1) // 2
    return miss, grid_m, center_idx


def _local_m(center: LngLat, lng: float, lat: float) -> Tuple[float, float]:
    from app.living_circle.geo_utils import to_local_xy

    return to_local_xy(center, lng, lat)


def _has_within(x: float, y: float, pts: Any, radius_m: float) -> bool:
    """局部米坐标点集内是否有 (x,y) 半径内的点（numpy 向量化）。"""
    if pts is None or len(pts) == 0:
        return False
    d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
    return bool((d2 <= radius_m * radius_m).any())


def find_blindspots(
    center: LngLat,
    study_radius_m: float,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
) -> List[Dict[str, Any]]:
    """识别盲区：契约 BlindSpot[]。

    triads: {market/pharmacy/primary: [{lng,lat,name}, ...]}（已清洗）。
    """
    point_sets: Dict[str, List[Tuple[float, float]]] = {
        k: [round_lnglat(p["lng"], p["lat"]) for p in v if "lng" in p and "lat" in p]
        for k, v in triads.items()
    }
    miss, step, c_idx = cover_matrix(center, study_radius_m, point_sets, grid_m)
    if not miss.any():
        return []

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

                # 簇质心（像素 → 米 → lnglat）
                rows, cols = np.where(cluster)
                cy = float(rows.mean())
                cx = float(cols.mean())
                x_m = cx * step - study_radius_m
                y_m = cy * step - study_radius_m
                cluster_center = xy_to_lnglat(center, x_m, y_m)

                miss_keys = [
                    k for k in TRIAD_KEYS
                    if not point_sets.get(k) or not _has_in_cluster(cluster, center, study_radius_m, point_sets[k], grid_m)
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

                # 灰区多边形 = 簇掩码外边界
                xy_ring = smooth_ring(trace_exterior(cluster, grid_m))
                ring_lnglat = [
                    xy_to_lnglat(center, v[0] - study_radius_m, v[1] - study_radius_m)
                    for v in xy_ring
                ]
                closed = ensure_closed(ring_lnglat)
                idx += 1
                result.append({
                    "id": f"bs-{prefix}-{idx}",
                    "center": [round(cluster_center[0], 6), round(cluster_center[1], 6)],
                    "radius_m": int(BLIND_RADIUS_M),
                    "missing_facilities": [TRIAD_LABEL.get(k, k) for k in miss_keys if k in TRIAD_LABEL],
                    "nearest": nearest,
                    "polygon": {"type": "Polygon", "coordinates": [closed]},
                })
    # 去重：同一缺失出现多次的簇只在 result 中出现一次（id 唯一由 idx 保证）
    return result


def _has_in_cluster(cluster: np.ndarray, center, study_radius_m, pts_key: Sequence[Tuple[float, float]], grid_m) -> bool:
    """簇内任一格 1km 圆内命中某类设施。"""
    rows, cols = np.where(cluster)
    for r, c in zip(rows, cols):
        x_m = float(c) * grid_m - study_radius_m
        y_m = float(r) * grid_m - study_radius_m
        if _has_within(x_m, y_m, np.array([_local_m(center, p[0], p[1]) for p in pts_key], dtype=float), BLIND_RADIUS_M):
            return True
    return False