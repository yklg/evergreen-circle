"""M1 · 轮廓工具：连通域裁剪 / 外边界追踪（闭合、几何正确）。"""
import numpy as np

from app.living_circle.contour import mask_connect_center, trace_exterior


def _circle_mask(n: int = 41, radius: float = 12.0) -> np.ndarray:
    c = (n - 1) / 2.0
    ys, xs = np.mgrid[0:n, 0:n]
    return (np.hypot(xs - c, ys - c) <= radius).astype(bool)


def test_connect_center_single_component():
    mask = np.zeros((9, 9), dtype=bool)
    mask[3:6, 4] = True
    mask[4, 3:6] = True  # 十字
    comp = mask_connect_center(mask, (4, 4))
    assert comp.sum() == mask.sum()  # 单连通全部保留
    # 与主体隔离的孤立点不并入
    mask[0, 0] = True
    comp2 = mask_connect_center(mask, (4, 4))
    assert comp2[0, 0] == False  # noqa: E712


def test_trace_exterior_circle_closed_and_size():
    mask = _circle_mask()
    ring = trace_exterior(mask, step=125.0)
    assert len(ring) >= 8
    # 近闭环（首尾点相邻一格外内容差容忍）
    first, last = ring[0], ring[-1]
    assert abs(first[0] - last[0]) <= 125.0 * 1.5 and abs(first[1] - last[1]) <= 125.0 * 1.5
    # 直径 ≈ 2*radius*step（像素直径 24 → 3000m），容差一格
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    assert 23 * 125 < max(xs) - min(xs) < 26 * 125
    assert 23 * 125 < max(ys) - min(ys) < 26 * 125


def test_trace_exterior_single_pixel_does_not_hang():
    mask = np.zeros((5, 5), dtype=bool)
    mask[2, 2] = True
    ring = trace_exterior(mask, step=100.0)
    # 单像素外边界应是 4 顶点小方块（不会死循环）
    assert len(ring) >= 3


def test_trace_exterior_bounded_loop():
    """安全阀：异常数据也不得无限循环（回归防护）。"""
    mask = np.ones((30, 30), dtype=bool)  # 全连通满矩形
    ring = trace_exterior(mask, step=50.0)
    assert len(ring) >= 4
    # 满矩形周长 = 4*(29*50) = 5800（像素边线）→ 顶点数应远小于安全阀
    assert len(ring) < 30 * 30 * 4