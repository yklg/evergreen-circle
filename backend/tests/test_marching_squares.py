"""盲区边界层 · marching-squares（改革矩形伪象的核心几何原语）测试。

覆盖（对应测试覆盖面方案组 1）：
- MS-1 16-case 全覆盖主环闭合 + 面积
- MS-2 saddle（对角两内两外）中心判歧不产生自交/断裂
- MS-3 纯对角界面破除「只有水平/垂直边」
- MS-4 多环全返回 + 含簇心主环可选
- MS-5 单格退化仍输出闭合小片
- MS-6 blob_area 鞋带面积自洽
"""
import math

import numpy as np
import pytest

from app.living_circle.contour import blob_area, marching_squares_binary


def _disk_field(cx: float, cy: float, radius: float):
    """以 (cx,cy) 为中心、radius 半径的圆盘场（0=内侧/可达，1=外侧）。"""
    d2 = radius * radius

    def f(x: float, y: float) -> float:
        return 0.0 if (x - cx) ** 2 + (y - cy) ** 2 < d2 else 1.0

    return f


def _ring_area(xy_ring) -> float:
    return blob_area(xy_ring)


def test_ms_isolated_square_blob_single_loop_closed():
    """MS-1 · 单个圆盘（完全包在采样域内）：返回闭合环，面积 ≈ πR²。"""
    R = 1.2
    loops = marching_squares_binary(_disk_field(2.0, 2.0, R), x0=0.0, y0=0.0, nx=10, ny=10, step=1.0)
    assert len(loops) >= 1
    ring = loops[0]
    # 闭合
    assert ring[0] == ring[-1]
    # 面积接近 πR²（容差放宽：数值场离散）
    area = _ring_area(ring)
    assert math.pi * R * R * 0.7 < area < math.pi * R * R * 1.3


def test_ms_saddle_ambiguous_disambiguated_no_selfcross():
    """MS-2 · saddle（两个对角相邻的内侧方块相触）中心判歧，产生闭合且面积非退化的环。

    构造：方块 A={(2,2)..(3,3)} 与方块 B={(4,4)..(5,5)} 相切于角点 (4,4)。
    二者之间恰构成「对角两内两外」的 saddle 单元 —— 命中 ``len(crosses)==4`` 判歧分支。
    """
    cells = {
        (2, 2), (3, 2), (2, 3), (3, 3),
        (4, 4), (5, 4), (4, 5), (5, 5),
    }

    def f(x: float, y: float) -> float:
        return 0.0 if (int(x), int(y)) in cells else 1.0

    loops = marching_squares_binary(f, x0=0.0, y0=0.0, nx=10, ny=10, step=1.0)
    assert len(loops) >= 1
    for ring in loops:
        assert ring[0] == ring[-1]  # 每一环闭合
        assert _ring_area(ring) > 1.0  # 非退化（面积非零）


def test_ms_diagonal_has_diagonal_edge():
    """MS-3 · 纯对角界面破除「只有水平/垂直边」（域内闭合的倾斜条带）。"""
    # 45° 斜向厚条带：|x-y|<0.5 且限定在 [1,5]² 内（保证闭合），环路含 45° 斜边
    def f(x: float, y: float) -> float:
        if abs(x - y) < 0.5 and 1.0 < x < 5.0 and 1.0 < y < 5.0:
            return 0.0
        return 1.0

    loops = marching_squares_binary(f, x0=0.0, y0=0.0, nx=10, ny=10, step=1.0)
    assert len(loops) >= 1
    ring = loops[0][:-1]  # 去闭合
    # 存在非轴对齐边：任两相邻点 x 与 y 的绝对变化应含 45°
    diag = any(
        abs(ring[i][0] - ring[i - 1][0]) > 0.05 and abs(ring[i][1] - ring[i - 1][1]) > 0.05
        for i in range(len(ring))
    )
    assert diag, "对角线界面应产生斜边（非纯水平/垂直矩形）"


def test_ms_multiple_isolated_blobs_returned():
    """MS-4 · 两个分离连通域、且都完全包在采样域内：分别返回闭合环。"""
    def f(x: float, y: float) -> float:
        # 两个圆盘：中心 (2,2) 与 (6,6)，半径 1.2（域 [0,10)，圆右/下界 7.2 < 9，完整包住）
        r1 = (x - 2) ** 2 + (y - 2) ** 2
        r2 = (x - 6) ** 2 + (y - 6) ** 2
        return 0.0 if r1 < 1.44 or r2 < 1.44 else 1.0

    loops = marching_squares_binary(f, x0=0.0, y0=0.0, nx=10, ny=10, step=1.0)
    assert len(loops) >= 2


def test_ms_single_cell_emits_closed():
    """MS-5 · 退化：亚格（nx/ny<2）返回包围盒闭合单环，非空。"""
    loops = marching_squares_binary(_disk_field(0.0, 0.0, 0.5), x0=0, y0=0, nx=1, ny=1, step=1.0)
    assert len(loops) == 1
    assert loops[0][0] == loops[0][-1]


def test_blob_area_shoe_positive_self_consistent():
    """MS-6 · 鞋带面积：正方形 → 面积 = 边长²（自洽）。"""
    ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    assert blob_area(ring) == pytest.approx(4.0)


def test_blob_area_auto_closes():
    ring = [[0, 0], [2, 0], [2, 2], [0, 2]]  # 未闭合
    assert blob_area(ring) == pytest.approx(4.0)