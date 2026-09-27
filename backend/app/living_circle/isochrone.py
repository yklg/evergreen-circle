"""等时圈引擎：渔网网格采样 → 步行测时 → IDW 插值 → 掩码等值线族。

对齐 F0 契约（src/types.ts IsochroneZone / SamplingPoint）：
  - 输出 5/10/15/20 分钟等值线族（GeoJSON Polygon 环 + area_km2）
  - sampling.points 采样点（idx/lng/lat/minutes/timed/in_reach）
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
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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

# 可达判定阈值（分钟）：单一事实源 = `caliber.reach_full_min`（当前 20.0）。
#
# ⚠️ 严禁把分钟数硬编码进本模块。阶段 −1 之前这里只有 `reachable = m is not None`，
# 语义其实是「测时返回了值」而非「在可达区内」——于是「采样点 1049 个（可达 1049）」
# 把 938 个 >20min 的点也算成了可达。现在拆成两个语义互不重叠的字段：
#   timed    = 测时返回了分钟值（可插值，与是否可达无关）
#   in_reach = timed 且 minutes ≤ 本阈值（这才是「可达」）
REACH_FULL_MIN = float(get_caliber("walking").reach_full_min)


@dataclass(frozen=True)
class ReachFlags:
    """采样点可达性分档（两字段语义互不重叠，见模块顶部说明）。"""
    timed_count: int
    in_reach_count: int


def reach_flags(points: Sequence[Mapping[str, Any]]) -> ReachFlags:
    """从 ``sampling.points`` 统计可达性分档 —— **全项目唯一实现**。

    为什么要有这个函数：``timed`` / ``in_reach`` 的判定必须先于统计统一，
    否则「产出点」与「数点数」会像 ``assemble.poi`` 那样各算各的（同一个对象的
    两个字段由两条链路装配），一旦漂移就无人发现。三个调用点共用本函数：
    ``IsochroneEngine.compute``（live）、``pipeline.living_circle``（fixture 分支）、
    ``scripts/lc_healthcheck``。

    判据（与 ``_flag_of`` 同源）：
      - ``timed``    = ``minutes is not None``
      - ``in_reach`` = ``timed`` 且 ``minutes <= REACH_FULL_MIN``
    """
    timed = 0
    in_reach = 0
    for p in points:
        m = p.get("minutes")
        if m is None:
            continue
        timed += 1
        if round(float(m), 1) <= REACH_FULL_MIN:
            in_reach += 1
    return ReachFlags(timed_count=timed, in_reach_count=in_reach)


def _flag_of(m: Optional[float]) -> Tuple[bool, bool]:
    """单点分档 → ``(timed, in_reach)``。阈值取整后再比：``minutes`` 已 ``round(…, 1)``，
    避免 20.0000001 这类浮点噪声被误判为不可达。"""
    timed = m is not None
    return timed, bool(timed and round(float(m), 1) <= REACH_FULL_MIN)

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


def _two_stage_points(
    center: LngLat,
    study_radius_m: float,
    coarse_m: float,
    fine_m: Optional[float],
    fine_band: Optional[Tuple[float, float]],
) -> List[LngLat]:
    """旧双阶段采样点（粗网格全覆盖 + 边界环带加密），完整保留原语义。

    `fine_band` 的缺省回落在 `sample_plan` 里**只解析一次**：本函数不再自带步行口径的
    隐式默认，否则「哪套环带生效」会有两处实现（正是本仓反复踩的三份漂移）。
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


def _budget_stage_points(
    center: LngLat,
    study_radius_m: float,
    max_points: int,
) -> Tuple[List[LngLat], float]:
    """预算受限单阶段粗网格（v5 B2/O3）：放弃 fine 带，把点数压到 ≤ max_points。

    - 圆内网格点 ≈ π/4·n²（圆内接于 n×n 方网格），取满足 π/4·n² ≤ max_points 的
      最大奇数 n（奇数保证中心点恰落格）；
    - 步长 = 2·R/(n−1)：预算下标准档步长 ≤ 内圈半径 308m，不触发最内圈坍缩（D1）；
    - 边构建边校验 len ≤ max_points，越界则 n 减 2 重试（保证不变量成立，杜绝边界效应破限）。

    返回 `(点列, **实际**步长)` —— 步长必须回传：降预算时它会长到超过名义 `coarse_m`
    或缩到比它更密（点数被 n 取整左右），调用方只拿点数的话就看不见这件事。
    """
    n = int(math.floor(math.sqrt(4.0 * max_points / math.pi)))
    if n % 2 == 0:
        n -= 1
    if n < 1:
        n = 1
    while n > 1:
        axis = _aligned_axis(study_radius_m, n)
        pts = [
            xy_to_lnglat(center, x, y)
            for x in axis
            for y in axis
            if math.hypot(x, y) <= study_radius_m
        ]
        if len(pts) <= max_points:
            return pts, 2.0 * study_radius_m / (n - 1)
        n -= 2
    # 只剩中心一个点：没有任何间距信息可言，按整个直径计（下游只会判得更粗）。
    return [xy_to_lnglat(center, 0.0, 0.0)], 2.0 * study_radius_m


@dataclass(frozen=True)
class SamplePlan:
    """一次采样的**实际生效规格**：光有点数不足以举证用的是哪一套规格。

    `degraded=True` ⇒ 预算逼着放弃了边界 fine 加密带、退回单阶段粗网格，此时
    `fine_m`/`fine_band` 如实为 None（而不是继续报名义档位那套）。存在本类型的理由：
    `compute()` 过去只把点数交给下游，于是「点被压过」与「环带被丢」两件事实都不可见，
    插值格仍按名义档位选 ⇒ IDW 在没有测过的尺度上凭空造细节。
    """
    points: List[LngLat]
    coarse_m: float
    fine_m: Optional[float]
    fine_band: Optional[Tuple[float, float]]
    sample_step_m: float
    degraded: bool


def sample_plan(
    center: LngLat,
    study_radius_m: float = 2500.0,
    coarse_m: float = 400.0,
    fine_m: Optional[float] = None,
    fine_band: Optional[Tuple[float, float]] = None,
    max_points: Optional[int] = None,
) -> SamplePlan:
    """采样规格的唯一推导点 —— `build_sample_points` 与 `compute` 共用，不分两处各算一遍。

    `max_points` 三档语义同 `build_sample_points`（None/≤0 → 双阶段；≥双阶段点数 → 双阶段
    全精度；否则 → 预算受限单阶段并标 `degraded`）。

    `fine_band=None` 且给了 `fine_m` 时回落**步行**口径环带 —— 这是 `build_sample_points`
    的历史语义（离线源与合成场测试零回归靠它）；真实多档调用必须由调用方显式传band，
    见 `IsochroneEngine.compute` 的 `travel_mode`/`fine_band` 形参。
    """
    band = fine_band
    if band is None and fine_m and fine_m > 0:
        band = get_caliber("walking").fine_band
    two_stage = _two_stage_points(center, study_radius_m, coarse_m, fine_m, band)
    if max_points is None or max_points <= 0 or len(two_stage) <= max_points:
        n_coarse = math.ceil(study_radius_m / coarse_m) * 2 + 1
        return SamplePlan(
            points=two_stage,
            coarse_m=coarse_m,
            fine_m=fine_m,
            fine_band=band,
            sample_step_m=2.0 * study_radius_m / (n_coarse - 1),
            degraded=False,
        )
    pts, step = _budget_stage_points(center, study_radius_m, max_points)
    return SamplePlan(
        points=pts,
        coarse_m=coarse_m,
        fine_m=None,          # 环带确实被丢掉了：如实报 None，不替名义档位作证
        fine_band=None,
        sample_step_m=step,
        degraded=True,
    )


def build_sample_points(
    center: LngLat,
    study_radius_m: float = 2500.0,
    coarse_m: float = 400.0,
    fine_m: Optional[float] = None,
    fine_band: Optional[Tuple[float, float]] = None,
    max_points: Optional[int] = None,
) -> List[LngLat]:
    """生成测时采样点：粗网格全覆盖 + 边界环带细网格加密（或预算受限单阶段）。

    返回 (lng, lat) 列表；粗网格用奇数对称格（中心恰落在 (0,0) 采样点）。
    fine_band 未指定时由**步行**口径派生（最内圈半径 → 研究半径），防最内圈坍缩（B8/I10）；
    骑行/驾车档必须自己传，否则会拿到步行的环带（历史默认，非正确行为）。

    ``max_points``（v5 B2）：
      - 为空/≤0 → 保持旧双阶段（离线源与测试合成场零回归，D4）；
      - 有限且 ≥ 旧双阶段点数 → 直接用旧双阶段（O3 恢复判据，付费档全精度）；
      - 否则 → 预算受限单阶段（D1，免费档：coarse 步长仍 < 内圈半径，不坍缩）。

    本函数只是 `sample_plan(...).points` 的薄封装 —— 需要同时知道「实际用了哪套规格」的
    调用方（`IsochroneEngine.compute`）直接走 `sample_plan`。
    """
    return sample_plan(
        center, study_radius_m, coarse_m, fine_m, fine_band, max_points
    ).points



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
        max_points: Optional[int] = None,
        travel_mode: str = "walking",
        fine_band: Optional[Sequence[float]] = None,
    ) -> Dict[str, Any]:
        """执行等时圈计算 → 契约结构。

        meter_fn(points) -> 步行耗时(分钟)列表（None=不可达）；由调用方注入
        （live=百度 route_matrix 批量；fixture 测试=合成场）。
        ``max_points``（v5 B2）：预算感知采样上限（免费档 375）；None/≤0 保持双阶段。
        ``travel_mode``：边界加密环带**归属哪一档口径**。必须显式传 —— 环带
        `(max(最内圈半径,400), 研究半径)` 是逐档派生的（步行 2500 / 骑行 5000 / 驾车 9000），
        而本函数只收到已解析好的 `study_radius_m`，无从推断，过去因此一路硬回落到步行
        ⇒ 骑行/驾车在自己研究半径的外沿**一格加密都没有**（半径给了、精度没给）。
        ``fine_band``：显式覆盖环带（给定时优先于 `travel_mode` 派生值）。
        """
        params = MODE_PARAMS.get(mode, MODE_PARAMS["standard"])
        coarse = params["coarse"]
        fine = params["fine"]
        grid_n = params["grid_n"]

        eff_band = tuple(float(v) for v in fine_band) if fine_band is not None else get_caliber(travel_mode).fine_band
        plan = sample_plan(center, study_radius_m, coarse, (fine or coarse), eff_band, max_points=max_points)
        sample_pts = plan.points
        minutes = await meter_fn(sample_pts)

        # 插值格仍按名义档位的 grid_n 选（本批不改几何，只把它变成可观测的量）：
        # 计划 v4 的 D5 要把方向翻成「规格→点数→预算」，届时 `grid_step_m ≥ sample_step_m`
        # 才是能立起来的硬不变量 —— 现在它连双阶段正常路径都不满足（格 ~77m vs 采样 150m），
        # 单靠把格调粗只会让所有等时圈面积凭空变化，那是拿一个错换另一个错。
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

        # ── 采样点可达性：两个字段，语义互不重叠（见模块顶部 REACH_FULL_MIN 说明）──
        # timed    = 测时返回了分钟值 → 可参与插值（与「可达」无关）
        # in_reach = timed 且 minutes ≤ REACH_FULL_MIN → 这才是「可达」
        point_rows: List[Dict[str, Any]] = []
        for i, (p, m) in enumerate(zip(sample_pts, minutes)):
            is_timed, is_in_reach = _flag_of(m)
            point_rows.append({
                "idx": i,
                "lng": round(p[0], 6),
                "lat": round(p[1], 6),
                "minutes": round(m, 1) if m is not None else None,
                "timed": is_timed,
                "in_reach": is_in_reach,
            })
        flags = reach_flags(point_rows)  # 统一实现，不在产出处另算一遍
        sampling = {
            "points": point_rows,
            "interpolation": "idw",
            # 实际用了什么就报什么：`plan.fine_m` 在预算受限路径下是 None，
            # 于是 `is_scattered` 不再替"名义上有边界加密"作证（旧写法读 MODE_PARAMS
            # 的 fine，即使加密带已被丢弃也照样返回 True）。
            "is_scattered": plan.fine_m is not None and plan.fine_m > 0,
            # ── 实际生效规格（计划 v4 阶段 0 · D5 的前置可观测性）──────────
            # 只有 `sample_count` 的报告会撒谎：点数被预算压过、环带被丢过，从数字上
            # 看不出来，于是"降规格"与"按规格跑"产出的报告长得一模一样。这里把两者
            # 拆开披露，其中 `grid_step_m` 与 `sample_step_m` 的比值就是"插值凭空造了
            # 多少没测过的细节"的直接读数（D5 要让这个比值 ≥ 1，见下方注释）。
            "spec": {
                "profile": mode,                    # 名义档位（quick/standard/precise）
                "travel_mode": travel_mode,         # 环带按哪一档口径派生
                "coarse_m": float(coarse),          # 名义粗网格间距
                "fine_m": None if plan.fine_m is None else float(plan.fine_m),
                "fine_band": None if plan.fine_band is None else [float(plan.fine_band[0]), float(plan.fine_band[1])],
                "grid_n": int(grid_n),
                "grid_step_m": round(float(step), 1),
                "sample_step_m": round(float(plan.sample_step_m), 1),
                "degraded": bool(plan.degraded),
            },
            # ⚠️ 汇总数**放在 sampling 内**，而不是叫 iso 顶层：
            # `assemble.py` 只把 `iso["sampling"]` 透传进报告，顶层字段会被丢掉，
            # 于是每个消费方（前端文案 / 诊断模板 / 专家）只好各自 filter 一遍点集 ——
            # 同一语义 N 处实现，改名或改阈值时必有一处静默漂移。放这里才能单源。
            # 已测时点数（旧名 reachable_count 的语义即此，改名以免与「可达」混淆）
            "timed_count": flags.timed_count,
            # 真正可达点数（≤ REACH_FULL_MIN 分钟）；「可达率」只能用它算
            "in_reach_count": flags.in_reach_count,
        }
        return {
            "isochrones": zones,
            "sampling": sampling,
            "sample_count": len(sample_pts),
        }


def hour_to_minutes(distance_m: float, speed: float = WALK_SPEED_M_PER_MIN) -> float:
    """距离(米) → 步行耗时(分钟)（线性近似，供合成场/文档口径统一）。"""
    return distance_m / speed