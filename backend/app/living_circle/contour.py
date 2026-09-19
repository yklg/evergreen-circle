"""掩码 → 外边界环 的轮廓工具（等时圈 / 盲区灰区共用）。

纯 numpy 实现：中心连通域裁剪 → Moore 邻域外边界追踪 → 折线平滑。
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


def mask_connect_center(mask: np.ndarray, center_ij: Tuple[int, int]) -> np.ndarray:
    """取含给定像素的 4-邻域连通域掩码（其余置 False）。"""
    H, W = mask.shape
    out = np.zeros_like(mask)
    if not mask[center_ij]:
        return out
    out[center_ij] = True
    stack = [(int(center_ij[0]), int(center_ij[1]))]
    while stack:
        i, j = stack.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < H and 0 <= nj < W and mask[ni, nj] and not out[ni, nj]:
                out[ni, nj] = True
                stack.append((ni, nj))
    return out


def trace_exterior(mask: np.ndarray, step: float) -> List[List[float]]:
    """外边界追踪（网格边行走，内部始终在左侧）→ 物理坐标环 (x, y)。

    思路：对单连通集合，收集「格内 1 / 邻格 0」的共享边（有向，内部在左侧），
    从任一未走边出发，在每个顶点选择「最小左转角」的候选边继续，直到回起点。
    安全阀 max_steps 防异常数据死循环；返回物理坐标（×step）。
    """
    H, W = mask.shape
    ones = np.argwhere(mask)
    if len(ones) == 0:
        return []
    inside = {(int(r), int(c)) for r, c in ones}

    def is_in(r: int, c: int) -> bool:
        return (r, c) in inside

    # 收集有向边界边：内部在左侧。坐标(x=c, y=r)，方向四连：上/右/下/左
    edges = []  # ((x1,y1),(x2,y2)) 起点→终点，内部在左侧
    for (r, c) in inside:
        # 顶边：内部在其下方（y 增方向）→ 从 (c, r) → (c+1, r) 内部在下半
        if not is_in(r - 1, c):
            edges.append((c, r, c + 1, r))
        # 右边：内部在其左侧（x 减方向）→ (c+1, r) → (c+1, r+1) 内部在西侧
        if not is_in(r, c + 1):
            edges.append((c + 1, r, c + 1, r + 1))
        # 底边：内部在其上方 → (c+1, r+1) → (c, r+1)
        if not is_in(r + 1, c):
            edges.append((c + 1, r + 1, c, r + 1))
        # 左边：内部在其右侧 → (c, r+1) → (c, r)
        if not is_in(r, c - 1):
            edges.append((c, r + 1, c, r))
    if not edges:
        return []

    used = [False] * len(edges)
    # 起始：最接近左上角的边（最小 x+y 的起点）
    start_i = min(range(len(edges)), key=lambda i: (edges[i][0] + edges[i][1]))
    ring: List[List[float]] = []
    cur_i = start_i
    max_steps = len(edges) * 4 + 64
    for _ in range(max_steps):
        used[cur_i] = True
        e = edges[cur_i]
        ring.append([e[2] * step, e[3] * step])  # 记录终点
        # 终点 = 下一条边的起点
        tx, ty = e[2], e[3]
        cands = [i for i, f in enumerate(edges) if not used[i] and f[0] == tx and f[1] == ty]
        if not cands:
            break
        # 最小左转角：入向 (dx_in, dy_in) 与出向 (dx2, dy2) 的左转角度
        dx_in, dy_in = e[2] - e[0], e[3] - e[1]
        best = cands[0]
        best_ang = 1e9
        for i in cands:
            f = edges[i]
            dx_out, dy_out = f[2] - f[0], f[3] - f[1]
            # 叉积>0 为左转；取左转角度最小（顺时针为先）
            ang = _turn_angle(dx_in, dy_in, dx_out, dy_out)
            if ang < best_ang:
                best_ang = ang
                best = i
        cur_i = best
        if cur_i == start_i:
            break
    return ring


def _turn_angle(ax: float, ay: float, bx: float, by: float) -> float:
    """向量 a→b 的转向角（0~360°，越小越接近原方向，逆时针为正）。"""
    import math

    cross = ax * by - ay * bx
    dot = ax * bx + ay * by
    ang = math.degrees(math.atan2(cross, dot))
    if ang < 0:
        ang += 360.0
    return ang


def smooth_ring(pts: List[List[float]], strength: int = 1) -> List[List[float]]:
    """邻域均值平滑（消除像素锯齿）。"""
    if len(pts) < 4:
        return pts
    p = [np.array(v, dtype=float) for v in pts]
    for _ in range(strength):
        nxt = []
        m = len(p)
        for i in range(m):
            a = p[(i - 1) % m]
            b = p[i]
            c = p[(i + 1) % m]
            nxt.append((a + 2 * b + c) / 4.0)
        p = nxt
    return [[float(v[0]), float(v[1])] for v in p]