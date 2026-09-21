"""掩码 → 外边界环 的轮廓工具（等时圈 / 盲区灰区共用）。

两套边界抽取：
- ``trace_exterior``（Moore 邻域外边界追踪）→ 等时圈 / 旧的矩形伪象盲区（**阶段前保留**）。
- ``marching_squares_binary``（连续场 16-case 等值线 + saddle 判歧）→ 盲区平滑边界（破除矩形伪象）。

marching-squares 建于 **field 之上**（grid-agnostic，见 ``field.py``），
阶段2 换 H3 判定只需换 ``field.read`` 实现、本函数不动（评审 P0 ①）。
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

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


# ────────────────────────────────────────────────────────────────
# marching-squares：连续标量场 → 等值线环族（破除矩形伪象的边界层）
# ────────────────────────────────────────────────────────────────
# 教科书算法：对场在格网的每个单元，取 4 角「值<level」布尔 → 决定单元内等值线段
# （等值线穿过两侧角点所在边的中点，线性插值）。saddle（对角两高一两低）由中心采样
# 判连通方式避免线段自交。跨单元边界时线段端点坐标一致 → 全局贪心拼接成闭合环。
# 参考对照（外部经验）：16-case 查表 + saddle 中心判歧，saddle 案例 5/10 需判向。
# 输入 grid-agnostic 的场（field.read 语义，见 field.py）；输出物理坐标(m)环族。


def _ms_sample(field: Callable[[float, float], float], x: float, y: float, level: float) -> bool:
    """角点在等值线内侧 ⇔ value < level。"""
    return field(x, y) < level


def marching_squares_binary(
    field: Callable[[float, float], float],
    x0: float,
    y0: float,
    nx: int,
    ny: int,
    step: float,
    level: float = 0.5,
) -> List[List[List[float]]]:
    """对连续场在 ``[x0, x0+nx*step) x [y0, y0+ny*step)`` 的 nx×ny 采样上跑 marching-squares。

    返回物理坐标闭合环族（可分多环）；``nx<2 或 ny<2`` 视作亚格退化，返回包围盒单环
    （``undersampled`` 由上游标注）。
    """
    if nx < 2 or ny < 2:
        return [[
            [x0, y0], [x0 + step, y0], [x0 + step, y0 + step], [x0, y0 + step], [x0, y0],
        ]]
    # 线段：以(点坐标,点坐标)表示；跨单元共边用一致坐标，便于拼接。
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    corners = [(0, 0), (1, 0), (1, 1), (0, 1)]  # 左上,右上,右下,左下
    # 边定义（角 0-1, 1-2, 2-3, 3-0），返回边上等值点坐标（线性插值）。
    # 计入顺序（a,b）一致，保证相邻单元共享边的端点「同坐标」。
    for j in range(ny - 1):
        for i in range(nx - 1):
            ox, oy = x0 + i * step, y0 + j * step
            vals = [_ms_sample(field, ox + dx * step, oy + dy * step, level) for dx, dy in corners]
            inside = [k for k, v in enumerate(vals) if v]
            n_in = len(inside)
            if n_in == 0 or n_in == 4:
                continue
            # 各边上的等值点：仅当边两端一内一外才产生。
            edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
            crosses: Dict[int, Tuple[float, float]] = {}
            for ei, (a, b) in enumerate(edges):
                if vals[a] != vals[b]:
                    crosses[ei] = _edge_cross(ox, oy, step, (a, b), vals[a], vals[b], level)
            if len(crosses) == 2:
                eids = list(crosses.keys())
                segments.append((crosses[eids[0]], crosses[eids[1]]))
            elif len(crosses) == 4:
                # saddle：对角两内两外，两两配对，由中心采样决定走法。
                cx = ox + step / 2.0
                cy = oy + step / 2.0
                if _ms_sample(field, cx, cy, level):
                    # 中心在内：连 (0,1)&(3,0) 与 (1,2)&(2,3) 或对角 —— 取不切割中心的配对
                    i0, i1 = 0, 2
                else:
                    i0, i1 = 1, 3
                eids = sorted(crosses)
                # 中心在内 → 配对 <(0,1),(1,2)> & <(2,3),(3,0)>；中心在外 → 交替
                segs = _saddle_pairs(eids, center_inside=_ms_sample(field, cx, cy, level))
                segments.append((crosses[segs[0][0]], crosses[segs[0][1]]))
                segments.append((crosses[segs[1][0]], crosses[segs[1][1]]))
    if not segments:
        return []
    return _stitch_loops(segments)


def _edge_cross(
    ox: float, oy: float, step: float,
    edge: Tuple[int, int], va: bool, vb: bool, level: float,
) -> Tuple[float, float]:
    """单元边 (a,b) 上等值点坐标：角点为 (ox+dx*step, oy+dy*step)，线性插值取中点。"""
    cxy = [(0, 0), (1, 0), (1, 1), (0, 1)]
    ax, ay = cxy[edge[0]]
    bx, by = cxy[edge[1]]
    # 一内一外，等值+落在边的中点（level=0.5 时对称）
    return (ox + (ax + bx) / 2.0 * step, oy + (ay + by) / 2.0 * step)


def _saddle_pairs(
    eids: List[int], center_inside: bool,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """saddle 的 4 条跨界线段按中心在场内/场外配对，防止自交。"""
    eids = sorted(eids)
    if center_inside:
        return ((eids[0], eids[1]), (eids[2], eids[3]))
    return ((eids[0], eids[2]), (eids[1], eids[3]))


def _stitch_loops(segments: List[Tuple[Tuple[float, float], Tuple[float, float]]]) -> List[List[List[float]]]:
    """把线段列表拼接成闭合环（物理坐标）。可多环。

    贪婪走线：每次从某点出发，沿「未用过、且非本级」的邻接线段走，直到无路可走即闭环。
    用 (点坐标, 线段索引) 定位，避免几何上多线段共享同坐标时的误配。
    """
    if not segments:
        return []
    adj: Dict[Tuple[float, float], List[Tuple[int, Tuple[float, float]]]] = {}
    for k, (a, b) in enumerate(segments):
        adj.setdefault(a, []).append((k, b))
        adj.setdefault(b, []).append((k, a))
    used = [False] * len(segments)
    loops: List[List[List[float]]] = []

    for k in range(len(segments)):
        if used[k]:
            continue
        seg0 = segments[k]
        cur = seg0[0]
        route: List[List[float]] = [[cur[0], cur[1]]]
        cur_seg: Optional[int] = k
        guard = len(segments) * 2 + 8
        while guard > 0:
            guard -= 1
            if cur_seg is None or used[cur_seg]:
                break
            used[cur_seg] = True
            a, b = segments[cur_seg]
            nxt_pt = b if a == cur else a
            route.append([nxt_pt[0], nxt_pt[1]])
            cur = nxt_pt
            nxt_seg = None
            for oi, _ in adj.get(cur, []):
                if not used[oi] and oi != cur_seg:
                    nxt_seg = oi
                    break
            cur_seg = nxt_seg
        if route and route[0] == route[-1]:
            closed = _ensure_loop_closed(route)
            if closed:
                loops.append(closed)
    return loops


def _ensure_loop_closed(loop: List[List[float]]) -> Optional[List[List[float]]]:
    """环首尾补齐全等（面积运算符要求闭合）。"""
    if not loop:
        return None
    if not (loop[0][0] == loop[-1][0] and loop[0][1] == loop[-1][1]):
        loop = loop + [list(loop[0])]
    if len(loop) < 4:
        return None
    return loop


def blob_area(ring: Sequence[Sequence[float]]) -> float:
    """鞋带公式求环面积（m²，物理坐标）。环需闭合（自动视首尾）。"""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if not pts:
        return 0.0
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0