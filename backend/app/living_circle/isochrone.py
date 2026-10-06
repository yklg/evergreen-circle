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

from app.living_circle.caliber import (ISO_COMPARE_BASIS, ReachCaliber, get_caliber)
from app.living_circle.contour import mask_connect_center, smooth_ring, trace_exterior
from app.living_circle.geo_utils import (
    LngLat,
    ensure_closed,
    haversine_m,
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

# ── 实测场的**形态**参数（插值口径）───────────────────────────
# 为什么从函数体字面量提成有名常量：`sampling.interpolation` 一直在说"这个场是 IDW 造的"，
# 但**造法本身没处可查** —— 幂次是 `idw_from_local` 里的一个 `p = 2.0`，邻域数是默认形参 `k=8`。
# 拿得到载荷的人知道方法名却复不出这个场，这正是 P1 那条根因（量的出处没做成一等公民）的形状。
# 实测过它有多吃紧（两份实跑快照，复算先与生产函数逐位对账）：p 从 2 改 1 或 3、k 从 8 改 4/16
# ⇒ 圈内格平均绝对差 0.24–0.44min，最坏单格 17.1min，且有 12–18 个圈内格跨过 20min 满分线
# —— 与残差信号（八类最近设施 −1.9…+4.3min）**同量级**。所以它是口径，不是实现细节。
# ⚠️ 声明只由**产生这个场的那一层**发出（`IsochroneEngine.compute`）：演示链不重跑 IDW，
#    就不该替历史快照里的场作保；离线链随 `detour` 一起摘掉（`data_source.py`）。
IDW_POWER = 2.0        # 反距离加权的幂次 p：权重 = 1 / 距离^p
IDW_NEIGHBORS = 8      # 每个格点取最近 k 个实测点加权（不是全量加权，理由见 `idw_from_local`）


def interpolation_form_keys() -> Dict[str, float]:
    """实测场形态的**唯一发射口**（`sampling` 里那两个键的两半由这一个函数给）。

    返回的是"当前这份场是怎么造的"，因此只允许在真造过场之后调用；把常量抄进别处的
    `sampling` 字典＝第二处实现，两处一改就出现"方法名说 IDW、参数说别的"那种自相矛盾件。
    """
    return {"interpolation_power": float(IDW_POWER),
            "interpolation_neighbors": int(IDW_NEIGHBORS)}


def has_interpolation_form(sampling: Mapping[str, Any]) -> bool:
    """这份载荷是否**完整地**声明了场形态（两半齐备才算数）。

    存在性判据与发射口必须共用同一个键名表，否则判据会比键名、发射口改键名，
    两边各自漂移后这条判据就再也不看任何东西（本仓出过两次的那类空转）。
    """
    keys = set(interpolation_form_keys())
    return keys <= set(sampling)


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


# 预期耗时场在这一点上坍缩为 0（分母），隐含系数随之发散 ⇒ 中心点不入标定样本。
_DETOUR_CENTER_EPS_M = 1.0


def detour_residual(
    center: LngLat,
    sample_pts: Sequence[LngLat],
    minutes: Sequence[Optional[float]],
    *,
    speed_m_per_min: float,
    declared_k: float,
) -> Dict[str, Any]:
    """把实测耗时场拆成「同城常态绕行」与**残差耗时**两部分（纯函数，零外呼）。

    为什么要拆：``minutes`` 把「距离 × 曲折 × 障碍」揉成一个标量 ⇒ 一处 12 分钟究竟是
    因为远，还是因为隔河/跨铁路，报告回答不了。赛题点名的「红绿灯、过街天桥、施工围挡」
    正落在这第二个问题上，而全仓没有任何字段承载它。残差 = 实测 −（直线距离 × detour ÷ 速度），
    正值就是「比同城常态多花的那几分钟」。

    ⚠️ **代理量，不宣称因果**：河道、铁路、封闭街区与单次测时噪声在数据里不可区分
    （北大学报综述那句「常规几何交互模型不适用微观尺度可达性研究」就是这条边界），
    所以对外一律叫「残差耗时 / 受阻代理」。
    ⚠️ **量纲纪律**：残差按**分钟**呈现，不许换算成百分比 —— 那会把一次减法重新变成除法。

    ``detour_factor`` 用**本次实测分布的中位数反标定**，不预设常数：仓内声明值（步行 1.3）
    与文献值（+14% ≈ 1.14）长期并存、从未校准，而三份实跑件量出的隐含系数是 1.53–1.62。
    扣掉中位数那部分常态绕行，剩下的才是各处的异常，且这把尺对每座城各自成立。

    样本口径 —— 被剔除的点**计数上屏**，不静默丢：
      · 距中心 ≤ ``_DETOUR_CENTER_EPS_M`` 的点（预期场在此坍缩为 0）
      · 未测时的点（``minutes is None``，只有降级采样路径才产出）
      · ``minutes ≤ 0`` 的点（耗时为 0 意味着「同点」或测时异常，隐含系数无意义）
    样本为空 ⇒ ``detour_factor_measured`` 与 ``residual_min`` 发 ``None`` 而不是发 0
    （「没量到」与「量到 0」是两件事，与逐格台账 int8 三态同一条纪律）。
    """
    pairs: List[Tuple[float, float]] = []  # (直线米数, 实测分钟) —— 一遍定口径，两遍用同一份
    excluded = {"near_center": 0, "untimed": 0, "non_positive": 0}
    for pt, m in zip(sample_pts, minutes):
        dist = haversine_m(center, pt)
        if dist <= _DETOUR_CENTER_EPS_M:
            excluded["near_center"] += 1
            continue
        if m is None:
            excluded["untimed"] += 1
            continue
        if float(m) <= 0:
            excluded["non_positive"] += 1
            continue
        pairs.append((dist, float(m)))
    if not pairs:
        return {
            "declared_detour_k": float(declared_k),
            "detour_factor_measured": None,
            "implied_detour_p10": None,
            "implied_detour_p90": None,
            "points_used": 0,
            "excluded": excluded,
            "residual_min": None,
        }
    implied = np.asarray([obs * speed_m_per_min / dist for dist, obs in pairs], dtype=float)
    k_med = float(np.median(implied))
    vals = np.asarray([obs - dist * k_med / speed_m_per_min for dist, obs in pairs], dtype=float)
    return {
        "declared_detour_k": float(declared_k),
        "detour_factor_measured": round(k_med, 3),
        "implied_detour_p10": round(float(np.percentile(implied, 10)), 3),
        "implied_detour_p90": round(float(np.percentile(implied, 90)), 3),
        "points_used": len(pairs),
        "excluded": excluded,
        "residual_min": {
            "p50": round(float(np.percentile(vals, 50)), 1),
            "p90": round(float(np.percentile(vals, 90)), 1),
            "p95": round(float(np.percentile(vals, 95)), 1),
            "max": round(float(vals.max()), 1),
            "min": round(float(vals.min()), 1),
        },
    }


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


def matrix_demand_points(
    sample_profile: str,
    travel_mode: str,
    center: LngLat = (0.0, 0.0),
) -> int:
    """某档采样规格**需要**多少个点 —— 预算反向导出（计划 v4 D5）的取数口。

    刻意走 `_two_stage_points` 真造一遍再数，而不是另写一条闭式公式：点数由
    「奇数对称粗网格 ∩ 圆 + 极坐标环带 + 5 位坐标去重」共同决定，任何近似式都是
    同一口径的第二份实现（本仓最贵的那类债）。代价是数百点的构建，换来的是
    「预算算的点数」与「实际发的点数」**必然**一致。

    `center` 只影响去重键的浮点舍入（±1 点量级），默认 (0,0) 已够预算用；
    要逐次精确就把真实中心传进来。
    """
    params = get_mode_params_for_travel_mode(travel_mode, sample_profile)
    coarse = float(params["coarse"])
    fine = params.get("fine")
    band = get_caliber(travel_mode).fine_band if fine and float(fine) > 0 else None
    return len(_two_stage_points(center, float(params["study_radius_m"]), coarse, fine, band))


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
    k: Optional[int] = None,
) -> np.ndarray:
    """IDW 插值（k-近邻反距离加权，numpy 向量化）。

    sample_xy: 采样点**局部平面坐标**（(N,2)，与 grid_xy 同一原点，由调用方投影）；
    minutes: 同 N 长（None=不可达，不参与加权）；grid_xy: 插值格点 (G,2) 局部坐标。
    返回 (G,) 耗时（分钟）向量。

    用 k-近邻（默认取 `IDW_NEIGHBORS`）而非全量加权：避免稀疏粗网格中心区被远处高值样本
    全局平均拉高（全量加权下 200m 处曾被拉到 10min，实际应 ≈4min）。幂次取 `IDW_POWER`
    —— 这两个数现在同时是**被声明的口径**（`sampling.interpolation_*`，发射口
    :func:`interpolation_form_keys`），所以这里不许再出现第三种写法。

    ⚠️ 默认值写成 `None` 而不是 `k: int = IDW_NEIGHBORS`：形参默认值在**定义时**求值一次，
    那种写法会把数烤进函数签名，之后无论常量怎么改、载荷声明的都是旧值 —— 判据要测
    "改常量 ⇒ 场跟着变"时它照样绿（等价于把口径藏进签名的第二份字面量）。运行时解析
    才让这里只有一份事实。
    """
    if k is None:
        k = IDW_NEIGHBORS
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
    p = IDW_POWER
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

    def _ring_zone_at(self, field2d: np.ndarray, minutes_th: float, center: LngLat,
                      study_radius_m: float, step: float, row_c: int,
                      col_c: int) -> Optional[Dict[str, Any]]:
        """把耗时场在 `minutes_th` 这一档切出**唯一一条含中心的环** → 环 + 面积；切不出就 `None`。

        四档等值线与口径对比环**共用这一颗**（旧写法是循环体里的六行，第二条环要复用就得
        抄一遍 —— 抄的那份会漂移，而"两条环的连通域判据不一致"正是本域反复出事的那类形状）。
        `mask_connect_center` 保证只取含中心的那个连通域：中心都不连通时返回 `None`，
        不返回一个"看起来像环"的碎片。
        """
        mask = field2d <= minutes_th
        if not mask.any():
            return None
        comp = mask_connect_center(mask, (int(row_c), int(col_c)))
        if not comp.any():
            return None
        xy_ring = smooth_ring(trace_exterior(comp, step))
        if len(xy_ring) < 4:
            return None
        # 像素(x=列,y=行) → 相对 center 的米：网格原点在 (-half,-half)，中心在网格中点
        ring_lnglat = [
            xy_to_lnglat(center, v[0] - study_radius_m, v[1] - study_radius_m)
            for v in xy_ring
        ]
        closed = ensure_closed(ring_lnglat)
        return {
            "minutes": minutes_th,
            "geojson": {"type": "Polygon", "coordinates": [closed]},
            "area_km2": round(ring_area_km2(closed, center), 3),
        }

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
        ``max_points``（v5 B2 / D5）：预算感知采样上限，由 `quota.max_matrix_origins(档位, 出行方式)`
        反向导出（免费档 standard：步行 1100 / 驾车 375）；None/≤0 保持双阶段。
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
            zone = self._ring_zone_at(field2d, minutes_th, center, study_radius_m,
                                     step, row_c, col_c)
            if zone is not None:
                zones.append(zone)
        zones.sort(key=lambda z: z["minutes"])

        # ── 口径对比环（笔 B）：同一份场按文献阈值再多切一条，**不并进 `isochrones`** ──
        # 四档是硬契约（配色表钉 `length === 4`、面积单调性、前端图例按四档渲染），把 8min
        # 塞进那个数组＝把第五档冒充成政策档；单独发一块，读者才看得出它是"另一把尺的对照"。
        # 判不了就不发：档未给值（骑行/驾车）、掩码空、环退化 ⇒ 整块缺席，前端缺键不渲染。
        compare_min = get_caliber(travel_mode).iso_compare_min
        iso_compare: Optional[Dict[str, Any]] = None
        if compare_min is not None:
            zone = self._ring_zone_at(field2d, compare_min, center, study_radius_m,
                                     step, row_c, col_c)
            if zone is not None:
                iso_compare = {**zone,
                               "basis": ISO_COMPARE_BASIS,
                               # 机器可读的断言边界：这句是**口径对比**，不是人群能力判断。
                               "claim": "caliber_comparison_only"}

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
        _run_cal = get_caliber(travel_mode)
        sampling = {
            "points": point_rows,
            "interpolation": "idw",
            # 方法名与场形态是**同一件事的两半**：说了 IDW 就必须说清幂次与近邻数，
            # 否则拿到载荷的人只能信、不能复算。抄常量＝第二处实现，一律走发射口。
            **interpolation_form_keys(),
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
            # ── 残差耗时场（受阻代理）：与上面两个汇总数同一出处 ──
            # 放这里而不是让装配层从 `points` 反推：反推要把点集再遍历一遍、并把
            # `speed_m_per_min`/`detour_k` 第二条链读一遍 —— 那正是「实测场」与「对其的解释」
            # 分家的形态（本仓已为此写过三次勘误）。
            "detour": detour_residual(
                center, sample_pts, minutes,
                speed_m_per_min=_run_cal.speed_m_per_min,
                declared_k=_run_cal.detour_k,
            ),
        }
        out = {
            "isochrones": zones,
            "sampling": sampling,
            "sample_count": len(sample_pts),
        }
        # 切不出就**整位缺席**（不是发 null）：读侧统一"缺键即不渲染"，既省掉每个消费点都要
        # 防的 `x && x.y`，也不让一个 null 冒充"量过了但没有环"（三态纪律，同 `detour` 那句）。
        if iso_compare is not None:
            out["iso_compare"] = iso_compare
        return out


def hour_to_minutes(distance_m: float, speed: float = WALK_SPEED_M_PER_MIN) -> float:
    """距离(米) → 步行耗时(分钟)（线性近似，供合成场/文档口径统一）。"""
    return distance_m / speed