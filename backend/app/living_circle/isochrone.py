"""等时圈引擎：渔网网格采样 → 步行测时 → IDW 插值 → 掩码等值线族。

对齐 F0 契约（src/types.ts IsochroneZone / SamplingPoint）：
  - 输出 5/10/15/20 分钟等值线族（GeoJSON Polygon 环 + area_km2）
  - sampling.points 采样点（idx/lng/lat/minutes/reachable）
  - interpolation='idw'，is_scattered 表示是否双阶段（粗扫+边界加密）散点采样

算法要点（赛题 30% 评分点——不取底层路网）：
  - 以中心点研究范围做粗网格 → 边界环带加密（fine_band 由口径派生，防最内圈坍缩）
  - IDW（k-近邻反距离加权）由采样耗时场推导连续耗时场
  - 对每个分钟阈值取「中心连通可达掩码」的外边界环（Moore 追踪）→ 多边形
依赖：numpy（已有）；测时注入 `meter_fn`（live=百度批量矩阵；测试=合成径向场）。
口径单一事实源：速度 / 圈层 / fine_band 全部从 `caliber.py` 派生（R1）。
"""
from __future__ import annotations

import math
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.living_circle.caliber import ReachCaliber, get_caliber
from app.living_circle.contour import mask_connect_center, smooth_ring, trace_exterior
from app.living_circle.geo_utils import (
    LngLat,
    ensure_closed,
    ring_area_km2,
    to_local_xy,
    xy_to_lnglat,
)

# ── 兼容旧接口：保留常量名但改为引用 caliber（防外部直接 import 断裂）───
ISO_MINUTES = list(get_caliber("walking").iso_minutes)

# 采样档位预设（与 travel_mode 解耦；travel_mode 的半径/grid_n 由 caliber 提供）
MODE_PARAMS = {
    "quick": {"coarse": 400, "fine": None, "grid_n": 41},
    "standard": {"coarse": 400, "fine": 150, "grid_n": get_caliber("walking").grid_n_for_standard},
    "precise": {"coarse": 300, "fine": 120, "grid_n": 81},
}
WALK_SPEED_M_PER_MIN = get_caliber("walking").speed_m_per_min


def get_mode_params_for_travel_mode(travel_mode: str, sample_profile: str = "standard") -> Dict[str, Any]:
    """获取指定出行方式 + 采样档位的完整参数（含半径 + grid_n）。
    
    步骤 3：按 travel_mode 分档，从 caliber 读取 study_radius_m 和 grid_n。
    """
    caliber = get_caliber(travel_mode)
    base = MODE_PARAMS.get(sample_profile, MODE_PARAMS["standard"])
    return {
        **base,
        "study_radius_m": caliber.study_radius_m,
        "grid_n": caliber.grid_n_for_standard if sample_profile == "standard" else base["grid_n"],
    }


def _aligned_axis(half: float, n: int) -> List[float]:
    """对称网格轴：[-half, half] 等距 n 点（n 奇数 → 中心恰在格点）。"""
    step = 2.0 * half / (n - 1)
    return [round(-half + i * step, 3) for i in range(n)]


def build_sample_points(
    center: LngLat,
    study_radius_m: float = 2500.0,
    coarse_m: float = 400.0,
    fine_m: Optional[float] = None,
    fine_band: Optional[Tuple[float, float]] = None,
) -> List[LngLat]:
    """生成测时采样点：粗网格全覆盖 + 边界环带细网格加密。

    返回 (lng, lat) 列表；粗网格用奇数对称格（中心恰落在 (0,0) 采样点）。
    fine_band 未指定时由口径派生（最内圈半径 → 研究半径），防最内圈坍缩（B8/I10）。
    """
    pts: List[LngLat] = []
    half = study_radius_m
    # 粗网格（奇数点数使中心点落格）
    n_coarse = math.ceil(half / coarse_m) * 2 + 1
    axis = _aligned_axis(half, n_coarse)
    for x in axis:
        for y in axis:
            if math.hypot(x, y) <= study_radius_m:
                pts.append(xy_to_lnglat(center, x, y))
    # 边界带加密
    if fine_m and fine_m > 0:
        if fine_band is None:
            cal = get_caliber("walking")
            fine_band = cal.fine_band
        lo, hi = fine_band
        n_fine = math.ceil((hi - lo) / fine_m) + 1
        # 以极坐标生成环内点（角度均匀 + 半径分级），避免笛卡尔网格在斜角处的空洞
        for r in np.linspace(lo, hi, n_fine):
            n_angle = max(12, int(2 * math.pi * r / fine_m))
            for k in range(n_angle):
                theta = 2 * math.pi * k / n_angle
                x = float(r * math.cos(theta))
                y = float(r * math.sin(theta))
                pts.append(xy_to_lnglat(center, x, y))
    # 去重（粗网格与细网格可能重叠）
    seen: set = set()
    dedup: List[LngLat] = []
    for p in pts:
        key = (round(p[0], 5), round(p[1], 5))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(p)
    return dedup


def idw_from_local(
    sample_xy: np.ndarray,
    minutes: Sequence[Optional[float]],
    grid_xy: np.ndarray,
    k: int = 8,
) -> np.ndarray:
    """IDW 插值（k-近邻反距离加权，numpy 向量化）。

    sample_xy: 采样点**局部平面坐标**（(N,2)，与 grid_xy 同一原点，由调用方投影）；
    minutes: 同 N 长（None=不可达，不参与加权）；grid_xy: 插值格点 (G,2) 局部坐标。
    返回 (G,) 耗时（分钟）向量。

    用 k-近邻（默认 8）而非全量加权：避免稀疏粗网格中心区被远处高值样本
    全局平均拉高（全量加权下 200m 处曾被拉到 10min，实际应 ≈4min）。
    """
    assert sample_xy.shape[0] == len(minutes), (sample_xy.shape, len(minutes))
    valid_idx = [i for i in range(len(minutes)) if minutes[i] is not None]
    if not valid_idx:
        return np.full(len(grid_xy), float("inf"))
    vals = np.array([minutes[i] for i in valid_idx], dtype=float)
    sample = sample_xy[valid_idx]

    grid = np.asarray(grid_xy, dtype=float)
    # 距离矩阵 (G, S)
    d = np.sqrt(((grid[:, None, :] - sample[None, :, :]) ** 2).sum(axis=2))
    kk = min(k, len(vals))
    order = np.argsort(d, axis=1)[:, :kk]
    kd = np.take_along_axis(d, order, axis=1)
    kv = np.take_along_axis(np.broadcast_to(vals[None, :], d.shape), order, axis=1)
    kd = np.maximum(kd, 1e-3)
    p = 2.0
    kw = 1.0 / (kd**p)
    eps = 1e-9
    w_sum = kw.sum(axis=1, keepdims=True)
    # 注意：分子分母必须同为 (G,1) —— 一维 (G,) 会被 numpy 广播成行向量，
    # 与 (G,1) 相除得到 (G,G) 的错乱矩阵（numpy 2.x 行为）。
    field = (kw * kv).sum(axis=1, keepdims=True) / (w_sum + eps)
    return field.reshape(-1)


def idw_for_points(
    sample_xy: np.ndarray,
    minutes: Sequence[Optional[float]],
    query_xy: np.ndarray,
) -> List[Optional[float]]:
    """对任意查询点集求耗时（供 POI/三要素回填；None=不可达/无有效样本）。"""
    f = idw_from_local(sample_xy, minutes, np.asarray(query_xy, dtype=float))
    return [None if not np.isfinite(v) else round(float(v), 1) for v in f]


class IsochroneEngine:
    """测时-插值-等值线引擎；测时逻辑注入（解耦 baidu 客户端，便于单测）。

    ⚠️ walk_speed 参数已废弃：实际耗时由调用方注入的 meter_fn 决定，本引擎不读此字段。
    口径速度在 `caliber.py` 中统一定义（R1/R5）。保留参数仅为向后兼容，将在阶段 3 移除。
    """

    def __init__(self, walk_speed: Optional[float] = None) -> None:
        # 死参数记录：存了但不用（test_caliber_invariants.py 已挂 xfail 待修复）
        self.walk_speed = walk_speed or WALK_SPEED_M_PER_MIN

    def _grid_coords(self, center: LngLat, study_radius_m: float, n: int) -> Tuple[np.ndarray, float]:
        """插值网格（米坐标，奇数 n 使中心落在格点）。"""
        half = study_radius_m
        step = 2 * half / (n - 1)
        xs = np.linspace(-half, half, n)
        ys = np.linspace(-half, half, n)
        gx, gy = np.meshgrid(xs, ys)
        grid = np.stack([gx.ravel(), gy.ravel()], axis=1)
        return grid, step

    async def compute(
        self,
        center: LngLat,
        meter_fn: Callable[[List[LngLat]], Awaitable[List[Optional[float]]]],
        study_radius_m: float = 2500.0,
        mode: str = "standard",
    ) -> Dict[str, Any]:
        """执行等时圈计算 → 契约结构。

        meter_fn(points) -> 步行耗时(分钟)列表（None=不可达）；由调用方注入
        （live=百度 route_matrix 批量；fixture 测试=合成场）。
        """
        params = MODE_PARAMS.get(mode, MODE_PARAMS["standard"])
        coarse = params["coarse"]
        fine = params["fine"]
        grid_n = params["grid_n"]

        sample_pts = build_sample_points(center, study_radius_m, coarse, (fine or coarse))
        minutes = await meter_fn(sample_pts)

        grid_xy, step = self._grid_coords(center, study_radius_m, grid_n)

        # 局部平面上插值：采样点与插值格点统一以 center 为原点投影
        sample_xy = np.array([to_local_xy(center, p[0], p[1]) for p in sample_pts])
        field = idw_from_local(sample_xy, minutes, grid_xy)
        field2d = field.reshape(grid_n, grid_n)

        # 中心格索引：center 恰为局部原点 (0,0)，位于网格中点
        col_c = (grid_n - 1) // 2
        row_c = (grid_n - 1) // 2

        zones: List[Dict[str, Any]] = []
        for minutes_th in sorted(ISO_MINUTES, reverse=True):
            mask = field2d <= minutes_th
            if not mask.any():
                continue
            comp = mask_connect_center(mask, (int(row_c), int(col_c)))
            if not comp.any():
                continue
            xy_ring = smooth_ring(trace_exterior(comp, step))
            if len(xy_ring) < 4:
                continue
            # 像素(x=列,y=行) → 相对 center 的米：网格原点在 (-half,-half)，中心在网格中点
            ring_lnglat = [
                xy_to_lnglat(center, v[0] - study_radius_m, v[1] - study_radius_m)
                for v in xy_ring
            ]
            closed = ensure_closed(ring_lnglat)
            area = ring_area_km2(closed, center)
            zones.append({
                "minutes": minutes_th,
                "geojson": {"type": "Polygon", "coordinates": [closed]},
                "area_km2": round(area, 3),
            })
        zones.sort(key=lambda z: z["minutes"])

        reachable_count = sum(1 for m in minutes if m is not None)
        sampling = {
            "points": [
                {
                    "idx": i,
                    "lng": round(p[0], 6),
                    "lat": round(p[1], 6),
                    "minutes": round(m, 1) if m is not None else None,
                    "reachable": m is not None,
                }
                for i, (p, m) in enumerate(zip(sample_pts, minutes))
            ],
            "interpolation": "idw",
            "is_scattered": fine is not None and fine > 0,
        }
        return {
            "isochrones": zones,
            "sampling": sampling,
            "sample_count": len(sample_pts),
            "reachable_count": reachable_count,
        }


def hour_to_minutes(distance_m: float, speed: float = WALK_SPEED_M_PER_MIN) -> float:
    """距离(米) → 步行耗时(分钟)（线性近似，供合成场/文档口径统一）。"""
    return distance_m / speed