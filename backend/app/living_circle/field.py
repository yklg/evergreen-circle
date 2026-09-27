"""连续标量场抽象（grid-agnostic）—— 盲区边界的「口径单一事实源」。

评审 P0 ①（需求定义 §9.1）要求：边界层（marching-squares）建于 **field 接口**之上，
而非方形父格之上 —— 这样阶段 2 换 H3 判定只需换 ``read`` 实现、边界层零返工。

本模块只定义「场」这一抽象及其读口，不含 marching-squares 本身（在 ``contour.py``）。
核心思想：把「某处是否属于盲区/可达」建模为连续标量函数（0.0..1.0），
由 ``read(x,y)`` 给出，与底层采样网格解耦；边界几何从场派生，而非从网格格边描边。

- :class:`Field`：抽象基类，唯一公开能力是 ``read(x,y) -> float``（物理米坐标）。
- :class:`BlindnessField`：盲区连续缺失场 —— ``read`` = 该点 1km 内是否缺失某个必达设施
  （1.0 = 盲，0.0 = 已覆盖）。以真实设施局部坐标构造，**可对任意亚格点采样**，
  故 marching-squares 能切出贴合设施真实覆盖的连续边界（破除矩形伪象）。
- :class:`IsoField`：等时圈可达场适配器 —— 包一层合成/实测耗时场，供阶段2 接入
  marching-squares 时复用（本阶段等时圈仍走已验证的 trace_exterior，见实施计划 §3.1 取舍）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence, Tuple

from app.living_circle.geo_utils import to_local_xy
from app.living_circle.scope import BLIND_RADIUS_M, TRIAD_KEYS

# 判定半径与必达要素登记表**不在此处定义**。
# 旧版这里各写一份字面量，注释的理由是「与 `blindspot` 同源但不能 import —— `blindspot`
# 已经 import 本模块，反向 import 会成环」。环是真的，但解法不该是复制口径：
# 两者现在都从 `scope` 取（`scope` 在最底层，无环），`test_field.py` 固化的
# 「TRIAD_LABEL 键集合 == TRIAD_KEYS」契约因此由**同一个来源**天然成立。


class Field(ABC):
    """连续标量场抽象：给定物理坐标 (x,y)，返回一个 0.0..1.0 的连续标量。

    语义由具体场指定（盲区缺失度、可达似然…）；本抽象与采样网格无关。
    """

    @abstractmethod
    def read(self, x: float, y: float) -> float:
        """点 (x,y) 的场值（米坐标）。0.0 ≤ 返回值 ≤ 1.0。"""


class BlindnessField(Field):
    """盲区连续缺失场。

    构造见 :meth:`.build`：以场地中心 + 必达设施列表建连续场。
    ``read(x,y)`` = 该点 1km 圆内缺失任一必达设施 → 1.0，否则 0.0。
    因直接基于真实设施坐标（局部米）判定，**任意亚格点**都能被正确采样，
    marching-squares 据此切出贴合设施覆盖的连续边界（不再是规则四边形）。
    """

    def __init__(self, center, triads_local: Dict[str, List[Tuple[float, float]]]) -> None:
        self._center = center
        # 设施局部坐标（米）：k -> [(x,y), ...]，已归一化到场地中心
        self._local: Dict[str, List[Tuple[float, float]]] = triads_local
        self._radius_m = BLIND_RADIUS_M

    @classmethod
    def build(
        cls,
        center,
        triads: Dict[str, List[dict]],
    ) -> "BlindnessField":
        """从契约 triads（{k: [{lng,lat,...},...]}）构建盲区连续缺失场。

        内部只投影一次局部坐标，之后 read 全在局部平面（米）判定，快且紧贴设施真实位置。
        """
        local: Dict[str, List[Tuple[float, float]]] = {}
        for k, pts in (triads or {}).items():
            arr = []
            for p in pts or []:
                if isinstance(p, dict) and "lng" in p and "lat" in p:
                    arr.append(to_local_xy(center, p["lng"], p["lat"]))
            if arr:
                local[k] = arr
        return cls(center, local)

    def read(self, x: float, y: float) -> float:
        # 盲区语义：某点「已覆盖」当且仅当**每个**必达类都有设施落在其 1km 圆内。
        # 求值类 = 三元组全集 ∪ 实际提供的类别（容忍未知键读数），
        # 故「缺失某必达类 / 该类整体为空 / 该类缺席」都正确判盲（1.0）。
        for _k in dict.fromkeys([*TRIAD_KEYS, *self._local.keys()]):
            pts = self._local.get(_k, ())
            if not any(
                (x - px) ** 2 + (y - py) ** 2 <= self._radius_m**2 for px, py in pts
            ):
                return 1.0
        return 0.0


class IsoField(Field):
    """等时圈可达场适配器（阶段2 marching-squares 的接入点）。

    用合成/实测耗时函数包装成 0.0..1.0 场。本阶段等时圈生产路径仍走
    ``mask_connect_center + trace_exterior``（已验证），本场仅作阶段2 的统一接入面。
    """

    def __init__(self, meter_fn) -> None:
        # 接收一个回调：sub (x,y 米) -> 分钟（None=不可达）
        self._meter = meter_fn

    def read(self, x: float, y: float) -> float:
        m = self._meter(x, y)
        if m is None:
            return 1.0  # 不可达
        # 归一化：≤10min 视为已可达（场值降，靠近 0），越远离越小 → 1
        return 1.0 - min(1.0, m / 10.0)


__all__ = [
    "BLIND_RADIUS_M",
    "TRIAD_KEYS",
    "BlindnessField",
    "Field",
    "IsoField",
]