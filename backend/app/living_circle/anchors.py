"""取证锚点：让**判定格**反过来当采集中心（计划 v4 阶段 1）。

## 为什么锚点必须长在判定格上

判盲的结论只在格心成立，取证能证明的也只有以锚点为心的那些圆盘。两者若不同源，
就会出现本次改造要结束的那个状态：采集一套几何、判定另一套几何，外沿的格永远
`unknown`。锚点取判定格点阵的**整数 stride 子格**之后，锚点恒在格格心上 ⇒ 掩码对齐
不需要任何新几何，也不需要容差。

## 两条间距约束（方向相反，容易写反）

- 上界（覆盖够不够）：方格点阵的覆盖半径是 `s/√2`，要让每个可判格都落在某锚点的
  可判定域内 ⇒ `s ≤ √2 · (穷尽深度 − 判定半径)`。
- 下界（会不会白烧预算）：`s ≥ grid.step`。锚点密于判定格 = 取证精度超过判定精度，
  多花的那次检索换不来任何一条新结论。

⚠️ 计划 v4 原文写的是 `m = ceil(cap_step / grid.step)`，那个取整方向**会把锚点排得比
要求的更疏**（stride 只增不减），于是 `s > cap_step` 留下覆盖空洞 —— 正是要防的那件事。
本实现用 `floor`（stride 只取不超过上界的最大值），并把这条偏离写回计划。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Sequence, Tuple

import numpy as np

from app.living_circle.geo_utils import LngLat
from app.living_circle.grid import GridSpec
from app.living_circle.scope import EvidenceRegion, TRIAD_KEYS, blind_radius_or

SQRT2 = math.sqrt(2.0)

# 本轮为什么没排锚点 —— 五种是完全不同的事实，合成一个「0 个锚点」就把它们抹平了：
# `covered` 该类在可达区内的每一格都已被自己的某个圆盘判得动（**无需再扩**，
#   这是 S-P0-1 的正腿：判据读 region 的未覆盖格数，读出来是 0 就该如实停下）；
# `no_evidence` 这类一次都没查成（缺口在我们身上，得标 missing，不许白烧）；
# `below_stride_floor` 查了但边界够不到判定半径（扩也证不出东西，落第三态）；
# `no_new_anchor` 该间距下的候选点本轮之前全试过（**不声称已覆盖**，只说没有新点可打
#   —— 这是回合的终止守卫；「到底覆盖全了没」由 `covered` 回答，不在这条里混）；
# `expand` 排得出还没试过的锚点。
PLAN_COVERED = "covered"
PLAN_NO_EVIDENCE = "no_evidence"
PLAN_BELOW_FLOOR = "below_stride_floor"
PLAN_NO_NEW_ANCHOR = "no_new_anchor"
PLAN_EXPAND = "expand"


def anchor_key(point: LngLat) -> Tuple[float, float]:
    """锚点的稳定比较键。经纬度是浮点，`==` 会因最后一位而漏判「同一个点」。

    公开给 `poi_collector.collect_triad_evidence` 共用：**「是不是同一个锚点」只能有一处判法** ——
    规划侧（`already_tried` 排除）与采集侧（同回合去重）各写一份四舍五入，就会出现
    「一边算重复、一边算新点」的双烧或漏打。
    """
    return (round(float(point[0]), 6), round(float(point[1]), 6))


def hub_cell(grid: GridSpec) -> LngLat:
    """点阵的正中那一格 = 分析中心那一次检索**实际站在哪儿**。

    取法只有一个：`n // 2` 就是 `anchors()` 定相位用的同一个 `mid`
    （`i0 = mid % m` ⇒ 中心格恒在候选里）。
    """
    n = int(grid.n)
    return grid.cell(n // 2, n // 2)


def hub_attempted(grid: GridSpec, categories: Sequence[str] = TRIAD_KEYS
                  ) -> Dict[str, Tuple[LngLat, ...]]:
    """「首轮已经站过的锚点」= 每一类各一个中心格。

    公开它是因为这句话现在有**两个读者**：取证回合的 `already_tried` 初值（生产循环）与
    成本推演脚本（同一笔账要能复算）。各写一份 `grid.cell(n//2, n//2)`，哪天相位规则动一下
    就变成"生产收了钱、脚本以为没收"。漏记这一格更贵：回合会把中心那一圈连同整张词表
    重发一遍（market 是 3 次白烧）。
    """
    hub = hub_cell(grid)
    return {cat: (hub,) for cat in categories}


@dataclass(frozen=True)
class AnchorsPlan:
    """一个类别本轮的取证计划，含**截断披露**（P0-3：砍掉的锚点不许凭空消失）。"""

    category: str
    reason: str
    exhausted_min_m: Optional[float]
    cap_step_m: float
    stride: int
    anchors: Tuple[LngLat, ...]
    anchors_total: int          # 排除「已试过」之后的合法候选数
    anchors_dropped: int        # 其中因 `max_anchors_per_cat` 被砍掉的数量
    # 该类判据范围内的未覆盖格数（S-P0-1 的正腿读数）。`None` = **没测**（调用方没给 inside
    # 掩码），与 0 = **测了且一格不缺** 必须是两个值 —— 把「没测」写成 0 就等于凭空宣布不用扩。
    cells_uncovered: Optional[int] = None

    @property
    def anchors_requested(self) -> int:
        return self.anchors_total - self.anchors_dropped


class AnchorSource(Protocol):
    """锚点来源协议。目前**只有** `LatticeAnchors` 一个实现。

    刻意不给「聚类锚点」预留空实现：没有真实需求时写一个占位实现，等于让后人以为
    那里已经接过一条路（本仓挂账的「三份实现漂移」多半都从这种占位开始）。
    """

    def anchors(self, grid: GridSpec, cap_step_m: float,
                keep: Optional[Sequence[bool]] = None) -> Tuple[LngLat, ...]:
        ...


@dataclass(frozen=True)
class LatticeAnchors:
    """判定格点阵的整数 stride 子格。"""

    def cap_step_m(self, exhausted_radius_m: float, radius_m: Optional[float] = None) -> float:
        """给定锚点的穷尽深度，返回锚点间距**上界**（米）。

        公式只许住在这一个地方：`s/√2 ≤ 穷尽深度 − 判定半径` 是「每格都被覆盖」的充要
        条件，谁抄一遍就可能抄错一个 √2，而抄错的表现是报告里悄悄少判一片格。
        判定半径原先硬写在体内（= 21 条取值途径之一），现在由调用方传；省略时按口径决议，
        而**回落哪一档要点名**（`LatticeAnchors` 是纯几何对象，没有 `travel_mode` 可读）——
        批 A① 的收紧：`blind_radius_or` 的 `travel_mode` 已无默认值，静默按步行档算的形状
        在这里写成了明账。
        （`blindspot` 那条生产路径恒显式传，见 `plan_expansion`）。
        """
        return SQRT2 * max(0.0, float(exhausted_radius_m) - blind_radius_or(radius_m, "walking"))

    def min_step_m(self, grid: GridSpec) -> float:
        """锚点间距**下界** = 实际判定格距（不是名义 grid_m，见 `GridSpec.step`）。"""
        return float(grid.step)

    def stride_for(self, grid: GridSpec, cap_step_m: float) -> int:
        """满足「≤ 上界 且 ≥ 判定格距」的最大整数 stride；上界比一格还小时退回 1。

        退回 1 时点阵已是最密的合法形状 —— 再密就越过下界（白烧预算），所以此时
        可达区外沿可能仍有格覆盖不到，那是**证据不足**而非排布错误，须由调用方如实
        标 `unjudgeable`，不许靠加密锚点假装覆盖到了。
        """
        step = float(grid.step)
        if cap_step_m <= 0.0 or step <= 0.0:
            return 1
        return max(1, int(math.floor(cap_step_m / step)))

    def anchors(self, grid: GridSpec, cap_step_m: float,
                keep: Optional[Sequence[bool]] = None) -> Tuple[LngLat, ...]:
        """按 stride 取子格作锚点。`keep` 给定时只保留其中为真的格（通常是可达区内）。

        子格的**相位取在中心格上**（`i0 = mid % m`），不从 (0,0) 起：可达区是以分析中心为心
        的圆盘，从角上起排时一旦 stride 大到只剩一个锚点，那一个会落在角上 ⇒ 「换新锚点」的
        读数可能比现状**更差**，而这个变差与取证强度无关，纯是排布相位造成的。
        取中心相位后 `mid % m == i0` ⇒ 中心格恒在锚点集里；间距仍是 `m·step`，
        覆盖上界 `s/√2` 不受影响（整点阵平移不改最远格心距的上界）。
        """
        m = self.stride_for(grid, cap_step_m)
        i0 = (grid.n // 2) % m            # 奇数 n ⇒ n//2 恰是中心格
        mask = None
        if keep is not None:
            mask = np.asarray(keep, dtype=bool)
        out = []
        for i in range(i0, grid.n, m):
            for j in range(i0, grid.n, m):
                if mask is not None and not mask[i, j]:
                    continue
                out.append(grid.cell(i, j))
        return tuple(out)

    def count_uncovered_cells(
        self,
        region: Optional[EvidenceRegion],
        grid: GridSpec,
        category: str,
        inside: Optional[Sequence[Sequence[bool]]],
        radius_m: Optional[float] = None,
    ) -> Optional[int]:
        """该类判得动的格没铺满可达区 ⇒ 还差多少格（S-P0-1 的唯一读数点）。

        判据只读 region 的事实（`inside & ~to_mask(cat)`），**不读标量** `frontier_m`/
        `category_bound_m`：后者在多锚点后塌成各盘 `max`（边界虚高），拿它判「还剩多少格
        没铺到」会把第二轮之后的判据静默熄火 —— 那正是「用标量代表区域」在判据侧复活。

        `radius_m` 必须与判盲那一次 `to_mask` 的实参同一个值（两边省略时都走同一个决议点
        `scope.blind_radius_or` ⇒ 不会再各取一份）；判据用一把尺、判盲用另一把，两条就会算出
        两个「未覆盖」，口径又分叉了。
        ⚠️ 这条纪律今天**只有形状级判据**：`test_expansion_criterion_and_judging_share_one_radius_default`
        钉的是「四处默认值都仍是哨兵 + 省略时决议点给同一个数」。两把尺当前同值 ⇒ 把决议点换成
        别的同值来源，全量仍绿（第十五轮复审 P1-5）。能真红的判据要等档位取不同值那一批才有载体，
        已登记台账；在那之前别把这条注释当成"有闸"。
        """
        if region is None or inside is None:
            return None
        judged = region.to_mask(grid, category, radius_m=radius_m)
        return int((np.asarray(inside, dtype=bool) & ~np.asarray(judged, dtype=bool)).sum())

    def plan_expansion(self, region: Optional[EvidenceRegion], grid: GridSpec, category: str,
                       *, max_anchors_per_cat: Optional[int] = None,
                       already_tried: Sequence[LngLat] = (),
                       inside: Optional[Sequence[Sequence[bool]]] = None,
                       radius_m: Optional[float] = None) -> AnchorsPlan:
        """该类本轮该打哪些锚点 —— 取证强度规划的**唯一出口**（T-P0-2，计划 v5.6）。

        四条纪律都在这一个函数里，各有它要防的事：

        1. **步长由 `min_exhausted_m` 导出，不是 `frontier_m`**（复审 T-P0-2）。间距上界
           `√2·(穷尽深度 − 判定半径)` 若按该类最乐观那块盘算，短盘周围的格永远落不进任何
           新圆盘 ⇒ 外沿的格「有缺口却无人认领」。
        2. **触发判据读 region 的未覆盖格，不读标量**（复审 S-P0-1）：给了 `inside` 就算出
           `cells_uncovered`，为 0 ⇒ `covered`，一格都不许多打（成本推演里 140 次白烧的
           形状就是这么来的）。`inside` 没给 ⇒ `cells_uncovered=None` = **没测**，
           此时不许冒充「已覆盖」，只按其余三条给结论。
           ⚠️ `inside` 是这个函数里**唯一**的掩码入参（第四轮复审 P0-2 打掉的正是这里）：
           旧写法另有 `keep` 管候选裁剪，两个入参管同一件事 ⇒ 只给 `inside` 时排出来的锚点
           **不裁可达区**，把圆外的格也当候选（实测裸格阵 169 个 vs 裁剪后应远少之）。
           一件事一个名字，宁可少一个旋钮。
           成本控制约定（接线那一轮必须照做，否则按需判据会因逐类不对称而大量发点）：
           调用方传的应当是「**判盲那一次仍未判出的格**」而不是整片可达区 —— 判据是逐类的，
           而判盲只需一类有据，两类掩码不等价（复审 P0-3）。
        3. **`already_tried` 排除**（复审 T-P0-2 的「非终止」那条）：纯函数按格阵重排，
           第二轮会把同一批点再发一遍 ⇒ 回合永远不收敛。排除后若一个都不剩，
           报 `no_new_anchor`（只说没有新点，不声称覆盖全了）。
        4. **截断如实披露**（P0-3）：`max_anchors_per_cat` 砍掉的数量是字段，不是注释。
           被砍掉的锚点覆盖的格必须有下家（`anchors_dropped > 0` ⇒ 调用方归因进
           第三态或 `partial`），否则「少打了几次」在报告里长得像「这些地方不用打」。

        无盘（该类根本没证据）⇒ `no_evidence` 且 0 锚点，且**不进未覆盖判据**：
        无盘类别的 `to_mask` 恒全 False，`inside & ~mask` 于是恒等于可达区全部格 ⇒
        判据永远喊扩（复审 T-P0-1 实测无盘类 78/99 格全命中）。「没有证据」不等于
        「全盘未覆盖」，对着空气排锚点是白烧。
        """
        exhausted = region.min_exhausted_m(category) if region is not None else None
        if exhausted is None:
            return AnchorsPlan(category=category, reason=PLAN_NO_EVIDENCE,
                               exhausted_min_m=None, cap_step_m=0.0, stride=0,
                               anchors=(), anchors_total=0, anchors_dropped=0,
                               cells_uncovered=None)
        cap = self.cap_step_m(exhausted, radius_m)
        uncovered = self.count_uncovered_cells(region, grid, category, inside, radius_m)
        if uncovered == 0:
            # 该类在可达区内每一格都判得动 —— 这里若还发锚点，发的就不是「补证据」，
            # 而是「把同一件事再证明一遍」。P0-4 的标量止损闸因此不必再走：两个都不扩。
            return AnchorsPlan(category=category, reason=PLAN_COVERED,
                               exhausted_min_m=float(exhausted), cap_step_m=cap, stride=0,
                               anchors=(), anchors_total=0, anchors_dropped=0,
                               cells_uncovered=0)
        if cap < float(grid.step) - 1e-9:
            # P0-4 止损：此时 `stride_for` 只能退回 1 = 每个可判格都当锚点。那不是在补证据，
            # 是在用锚点数量假装覆盖到了 —— 边界短到连一格都撑不起来，扩出来的盘照样证不出
            # 「这一圈没有」，所以如实收手并交给第三态归因（`anchors.py` 文件头那条纪律）。
            # 与「未覆盖格数」是**两道并联的闸**（复审 T-P0-1：v5.5 曾把这道改成按格数判，
            # 于是唯一挡住 72/99 锚点爆炸的闸没了）。
            return AnchorsPlan(category=category, reason=PLAN_BELOW_FLOOR,
                               exhausted_min_m=float(exhausted), cap_step_m=cap, stride=1,
                               anchors=(), anchors_total=0, anchors_dropped=0,
                               cells_uncovered=uncovered)
        stride = self.stride_for(grid, cap)
        tried = {anchor_key(p) for p in already_tried}
        candidates = [a for a in self.anchors(grid, cap, keep=inside) if anchor_key(a) not in tried]
        if not candidates:
            return AnchorsPlan(category=category, reason=PLAN_NO_NEW_ANCHOR,
                               exhausted_min_m=float(exhausted), cap_step_m=cap, stride=stride,
                               anchors=(), anchors_total=0, anchors_dropped=0,
                               cells_uncovered=uncovered)
        total = len(candidates)
        if max_anchors_per_cat is None or total <= int(max_anchors_per_cat):
            used, dropped = total, 0
        else:
            used = int(max_anchors_per_cat)
            dropped = total - used
        return AnchorsPlan(category=category, reason=PLAN_EXPAND,
                           exhausted_min_m=float(exhausted), cap_step_m=cap, stride=stride,
                           anchors=tuple(candidates[:used]),
                           anchors_total=total, anchors_dropped=dropped,
                           cells_uncovered=uncovered)


__all__ = [
    "AnchorSource", "AnchorsPlan", "LatticeAnchors", "SQRT2", "anchor_key", "hub_attempted",
    "hub_cell",
    "PLAN_EXPAND", "PLAN_NO_EVIDENCE", "PLAN_BELOW_FLOOR", "PLAN_NO_NEW_ANCHOR", "PLAN_COVERED",
]
