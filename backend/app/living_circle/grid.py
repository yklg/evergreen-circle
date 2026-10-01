"""判定格规格 —— 「判盲用的格」与「取证用的锚点格」的**唯一**推导点（计划 v4 阶段 1）。

为什么单独一个模块而不是留在 `blindspot.py`：证据域 `EvidenceRegion.to_mask()` 住在
`scope.py`，而 `blindspot.py` 依赖 `scope.py`。格规格若长在 blindspot 里，`scope` 要复用
它就得反向 import blindspot ⇒ 环依赖。抽到本模块后两边都只依赖几何，方向仍然单向。

⚠️ 消费方一律用 `GridSpec.step`（**实际**格距），不要用名义 `grid_m`：
`step = 2·scan/(n-1)` 由「奇数对称格 + 外接圆扫描」导出，实测比名义值小（181.6 < 200）。
拿名义值去约束锚点间距（如「锚点不得密于判定格」），会让采集精度悄悄超过判定精度 ——
多花的那部分预算换不来任何新判定。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np

from app.living_circle.geo_utils import LngLat, point_in_ring, xy_to_lnglat


@dataclass(frozen=True)
class GridSpec:
    """一次判定的格：扫描半径、实际格距、格心坐标轴与边长。

    坐标轴是**对称**的（n 为奇数 ⇒ 分析中心恰落在格心上，中心格不会被半格偏移污染），
    格心为 `(coords[j], coords[i])` 的局部米坐标：行 `i` 沿 y、列 `j` 沿 x。
    """

    center: LngLat
    scan: float                       # 扫描半径 = 可达区外接圆半径（米）
    step: float                       # 实际格距 = 2·scan/(n-1)，≤ 名义 grid_m
    n: int                            # 边长格数（恒为奇数）
    coords: np.ndarray = field(compare=False)   # 长度 n 的对称坐标轴（米）

    def cell(self, i: int, j: int) -> LngLat:
        """格心 → 经纬度（锚点复用同一份几何，不另起一套坐标换算）。"""
        return xy_to_lnglat(self.center, float(self.coords[j]), float(self.coords[i]))

    def distance_field(self) -> np.ndarray:
        """每格心到分析中心的直线距离 (n, n)（米）。"""
        axis = np.asarray(self.coords, dtype=float)
        return np.hypot(axis[None, :], axis[:, None])

    def inside_mask(self, scope) -> np.ndarray:
        """可达区内的格掩码 —— 可达区外**语义上就不该判盲**（没有「可达但缺设施」这回事）。"""
        inside = np.zeros((self.n, self.n), dtype=bool)
        ring = scope.reach_ring
        for i in range(self.n):          # i = y 行
            for j in range(self.n):      # j = x 列
                if point_in_ring(self.cell(i, j), ring):
                    inside[i, j] = True
        return inside

    def cells(self) -> int:
        return self.n * self.n


def grid_spec(center: LngLat, scan: float, grid_m: float) -> GridSpec:
    """由扫描半径与名义格距推出格规格 —— 这套算术的**唯一住所**。

    单独开这一层给读侧守卫用（`report_contract` 的 B13 要拿落库的 `n`/`step_m` 复算格阵）。
    让守卫照 `judge_grid` 再抄一遍 `ceil`/`linspace` 就是第二处格阵来源：`grid_m` 一改，
    抄的那份会先漂。
    """
    scan = float(scan)
    k = max(1, int(math.ceil(scan / grid_m)))
    n = 2 * k + 1
    step = (2.0 * scan) / (n - 1)
    coords = np.linspace(-scan, scan, n)
    return GridSpec(center=center, scan=scan, step=step, n=n, coords=coords)


def judge_grid(center: LngLat, scope, grid_m: float) -> GridSpec:
    """按可达区外接圆铺判定格（从 `blindspot.cover_matrix` 原样搬来，逐位等价）。"""
    return grid_spec(center, float(scope.reach_circumradius_m), grid_m)


__all__ = ["GridSpec", "grid_spec", "judge_grid"]
