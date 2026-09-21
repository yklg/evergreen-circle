"""口径单一事实源（R1）：按出行方式分档的测时与圈层定义。

所有模块不得再硬编码速度 / 绕行系数 / 研究半径 / 圈层分钟数；统一从本模块取值。
口径变更只改这里，其余模块通过导入常量或调用派生函数获得值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ApiCapability:
    """百度 API 能力描述（探针回填，非硬编码）。"""
    matrix_path: str          # e.g. "/routematrix/v2/walking"
    chunk: int                # 单次批量上限
    fallback_path: str        # 单点兜底路径
    restrictions_field: str   # 不可达判定字段名


@dataclass(frozen=True)
class ReachCaliber:
    """某出行方式的口径定义（唯一事实源）。

    - speed / detour_k / study_radius / iso_minutes：政策与文献依据；
    - fine_band：由最内圈半径派生（防「最内圈网格坍缩」复发），非硬编码；
    - api：实测能力（探针写入 manifest.json 后加载）；
    - basis：政策原文出处（答辩举证用）；
    - measured：是否经真实路网测时验证（True=步行，False=近似口径）。
    """
    travel_mode: str
    speed_m_per_min: float
    detour_k: float
    study_radius_m: int
    iso_minutes: Tuple[int, ...] = (5, 10, 15, 20)
    reach_full_min: float = 20.0  # 可达性满分阈值（= 最外圈分钟数）
    api: Optional[ApiCapability] = None
    basis: str = ""
    measured: bool = False

    @property
    def innermost_radius_m(self) -> float:
        """最内圈理论半径（直线距离模型下）。"""
        return self.iso_minutes[0] * self.speed_m_per_min / self.detour_k

    @property
    def reach_radius_bound_m(self) -> float:
        """可达区半径的**理论下界**（直线距离模型：分钟 × 速度 ÷ 绕行系数）。

        不是可达区的实际半径 —— 实际半径由路网实测的等时圈决定（通常 ≥ 本值，
        因为路网绕行比 ``detour_k`` 更曲折）。它的用途是**量级校验**：
        把实测外接圆与这个下界比对，若实测值反而更小，说明测时或圈层提取出了问题
        （``SpatialScope`` 与本值一起举证，让「圈为什么这么小」在报告里可查）。
        """
        return self.reach_full_min * self.speed_m_per_min / self.detour_k

    @property
    def fine_band(self) -> Tuple[float, float]:
        """边界带加密区间：从最内圈半径起算，到研究半径止。

        派生而非硬编码 → 换 mode 或调 speed/detour 时自动适配，根治 P0 坍缩。
        """
        r_inner = self.innermost_radius_m
        return (max(r_inner, 400.0), float(self.study_radius_m))

    @property
    def grid_n_for_standard(self) -> int:
        """标准档位插值格点数：保证 step ≤ 最内圈半径/4。

        step = 2*R/(n-1) ≤ r_inner/4  →  n ≥ 8*R/r_inner + 1
        """
        import math
        r_inner = self.innermost_radius_m
        if r_inner <= 0:
            return 61  # 兜底
        n = math.ceil(8 * self.study_radius_m / r_inner) + 1
        return max(n, 41)  # 不低于 quick 档位


# ── 默认口径表（步行有政策依据，骑行/驾车为近似口径，待探针验证）───────────

DEFAULT_CALIBERS: Dict[str, ReachCaliber] = {
    "walking": ReachCaliber(
        travel_mode="walking",
        speed_m_per_min=80.0,  # R7: 75→80，落在政策 0.8–1.2km 上沿
        detour_k=1.3,
        study_radius_m=2500,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        basis="商务部 2021《城市一刻钟便民生活圈建设意见》「步行约15分钟的服务半径」；"
              "《城市规划》2022.5 实测步行 15min ≈ 0.8–1.2km",
        measured=True,
        api=ApiCapability(
            matrix_path="/routematrix/v2/walking",
            chunk=25,
            fallback_path="/directionlite/v1/walking",
            restrictions_field="restrictions_status",
        ),
    ),
    "riding": ReachCaliber(
        travel_mode="riding",
        speed_m_per_min=200.0,  # 暂定 12km/h，待探针 P5 反算校准
        detour_k=1.2,
        study_radius_m=5000,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        basis="近似口径（无官方政策原文），速度参考共享单车平均巡航速度",
        measured=False,
        api=ApiCapability(
            matrix_path="/routematrix/v2/riding",
            chunk=25,
            fallback_path="/directionlite/v1/riding",
            restrictions_field="restrictions_status",
        ),
    ),
    "driving": ReachCaliber(
        travel_mode="driving",
        speed_m_per_min=500.0,  # 暂定 30km/h，待探针 P5 反算校准
        detour_k=1.15,
        study_radius_m=9000,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        basis="近似口径（无官方政策原文），速度参考城市道路平均车速",
        measured=False,
        api=ApiCapability(
            matrix_path="/routematrix/v2/driving",
            chunk=25,
            fallback_path="/direction/v2/driving",
            restrictions_field="restrictions_status",
        ),
    ),
}


def _load_manifest() -> Dict[str, Any]:
    """加载探针能力清单（若存在）。"""
    import json
    from pathlib import Path
    
    manifest_path = Path(__file__).parent / "capability_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _apply_manifest_caliber(caliber: ReachCaliber, manifest: Dict[str, Any]) -> ReachCaliber:
    """用 manifest 实测值覆盖 caliber 的 api 字段。"""
    cap = manifest.get("capacity", {}).get(caliber.travel_mode, {})
    if not cap:
        return caliber
    
    # 从 manifest 读取 chunk 上限
    chunk = cap.get("chunk_max_origins", caliber.api.chunk if caliber.api else 25)
    
    # 构建新的 ApiCapability
    api = caliber.api
    if api:
        api = ApiCapability(
            matrix_path=api.matrix_path,
            chunk=chunk,
            fallback_path=api.fallback_path,
            restrictions_field=api.restrictions_field,
        )
    
    # 返回更新后的 caliber（measured 标记为 True 若有实测数据）
    measured = cap.get("measured", caliber.measured)
    return ReachCaliber(
        travel_mode=caliber.travel_mode,
        speed_m_per_min=caliber.speed_m_per_min,
        detour_k=caliber.detour_k,
        study_radius_m=caliber.study_radius_m,
        iso_minutes=caliber.iso_minutes,
        reach_full_min=caliber.reach_full_min,
        api=api,
        basis=caliber.basis,
        measured=measured,
    )


# 加载 manifest 并应用实测值
_MANIFEST = _load_manifest()
if _MANIFEST:
    for mode in list(DEFAULT_CALIBERS.keys()):
        DEFAULT_CALIBERS[mode] = _apply_manifest_caliber(DEFAULT_CALIBERS[mode], _MANIFEST)


def get_caliber(travel_mode: str = "walking") -> ReachCaliber:
    """获取指定出行方式的口径定义（默认步行）。"""
    if travel_mode not in DEFAULT_CALIBERS:
        raise ValueError(
            f"未知出行方式: {travel_mode!r}，可用值: {list(DEFAULT_CALIBERS.keys())}"
        )
    return DEFAULT_CALIBERS[travel_mode]


def all_travel_modes() -> List[str]:
    """返回所有已定义的出行方式列表。"""
    return list(DEFAULT_CALIBERS.keys())


def caliber_payload_key(
    scene_name: str,
    center: Tuple[float, float],
    study_radius_m: int,
    sample_profile: str,
    travel_mode: str = "walking",
) -> str:
    """统一的场景身份键（B3/R6：纳入 travel_mode，防串缓存）。

    三份实现（LiveDataSource / CachingDataSource / pipeline）收敛到此函数，
    不再各自拼接字符串。
    """
    c = center or (0.0, 0.0)
    return (
        f"{scene_name}|{c[0]:.6f},{c[1]:.6f}|"
        f"{int(study_radius_m)}|{sample_profile}|{travel_mode}"
    )
