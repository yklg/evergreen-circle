"""空间口径绑定：把 caliber（名义口径）与**本次实测到的可达区几何**绑成一个值对象。

## 为什么需要它

修复前的代码里「四个名字 / 三个概念 / 零个显式表示」：

================  ====================================  ==============================
代码里的东西        实际承载的空间语义                      缺陷
================  ====================================  ==============================
``place_search(…,   **采集区** collect                    硬编码 ``radius_m=2000``，与 caliber 无关
 radius_m=2000)``
``study_radius_m=  **研究区** study                      判定网格铺满 ±2500m，被当成**判定区**用
 2500`` → 判定网格
``iso["isochrones" **可达区** reach                      形参名却是 ``iso15_ring``，实收 20min 圈
 ][-1]``（20min）
``docs/…算法.md``   **可达区**（文档口径写「15min 圈内」）  文档 / 形参名 / 实际基准三者不一致
 写「15min」
================  ====================================  ==============================

⇒ Q1（整片盲区）=「判定用研究区，但数据只有采集区」；
⇒ Q2（圈外点）=「采集用采集区、评分与展示用可达区」。
**两问是同一个缺失概念的两个投影。**

本对象把三者显式化，并把关系做成**构造即校验**（``invariant()``）：

  - 可达区 ⊆ 采集区（否则可达区内必然有无数据格）
  - 采集区 ≥ 可达区外接圆 + 本次判定半径（外沿的格其判定圆伸出采集区 ⇒ 只能标 unknown；
    而把整个外沿不判，等于砍掉判盲能力 —— 理由与「留边为何是导出量」见 `EVIDENCE_MARGIN_M`
    那一段注释，它已不再是常量）
  - 证据边界 ≤ 请求半径；且 ``evidence_complete`` 不得与「没采到边」并存

## 第二轮：三个概念 × **两个时刻**

上一轮显式化了「事前」，但只有几何 —— 于是「我**请求**了多大」被直接当成
「我**证明**了多大」用。剩下的缺口是类型层面的：采集是否被分页截断、是否烧穿预算，
在本对象里**没有一格可以安放**，只能被省略；而省略的收益（少写代码）不可见，
代价（盲区少报）方向上**让分数变好**（`scoring` 只按盲区条数扣分）——
缺陷于是被评分函数奖励，且没有任何测试会红。

补上「事后举证」相（``with_evidence`` / ``evidence_*`` / ``triad_judge_radius_m``）后，
可判定半径由**实测边界**逐类导出，而不是由请求半径猜。

于是「圈内」到底按哪个圈判，由本对象唯一决定，**形参名不可能再撒谎**；
要加「驾驶方式」「多圈对照」「新的必达要素类别」只改本对象构造与 ``TRIAD_LABEL``，
消费函数都不用动。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from app.living_circle.baidu_client import STOP_SERVER_CAP, is_exhausted, is_server_cap
from app.living_circle.caliber import ReachCaliber, get_caliber
from app.living_circle.geo_utils import (
    LngLat,
    ensure_closed,
    haversine_m,
    point_in_ring,
    to_local_xy,
    xy_to_lnglat,
)

# ── 判盲口径的唯一事实源 ────────────────────────────────────────────
# 盲区判定半径（赛题标准）：判「某点 1km 圆内有没有某类必达设施」。
#
# ⚠️ **定义权已搬到口径对象**（生活圈片 1b）：住所在 `caliber.ReachCaliber.blind_radius_m`，
# 因为它是「随出行方式取值的政策量」，与 speed/detour_k/study_radius 同族。这里留的
# `BLIND_RADIUS_M` 是 **walking 档的兼容名**，不是第二处定义 —— 它读一次口径、不再写字面量。
#
# 为什么非搬不可：这个数有 **21 条取值途径**（15 个函数默认值 + 5 处体内硬用 + 1 处发射进
# 报告）。Python 在 **def 期**就把默认值焊进函数对象，所以"改源头常量"永远改不到那 15 条
# 默认路径（改了、行为没改、测试全绿 —— 本仓最难发现的那类形状）。因此配套上了 γ 守卫
# **G-11**：`app/**` 里任何函数默认值都不许再写这两把尺。
#
# 取用面统一走 `resolve_blind_radius_m()` / `SpatialScope.blind_radius_m`；`blindspot` 与
# `field` 过去各写了一份字面量 —— 那正是本仓反复出事的「同一口径两处定义」。
BLIND_RADIUS_M = get_caliber("walking").blind_radius_m


def resolve_blind_radius_m(travel_mode: str) -> float:
    """判定半径的**唯一取用点**：从口径对象读，按出行方式分档。

    `travel_mode` 是**必填**的（批 A① 的"省略路径收紧"）。此前它默认 `walking`，于是
    `EvidenceRegion`/`EvidenceDisc`/`LatticeAnchors` 这些**纯几何值对象**在调用方省略半径时
    会静默按步行档算 —— 分档那天就是一条无人报警的错尺。现在回落必须**点名**：那四个拿不到
    `travel_mode` 的站点各自显式写 `"walking"` 并说明为什么，读代码的人一眼看得见债在哪。
    半径本身仍优先由调用方显式下传（`_verdict_masks` / `judge_once` 手里有 `scope.travel_mode`）。
    """
    return float(get_caliber(travel_mode).blind_radius_m)


def blind_radius_or(value: Optional[float], travel_mode: str) -> float:
    """哨兵解析：省略实参（``None``）⇒ 取该档口径登记的那把尺；显式值原样返回。

    为什么默认值是 ``None`` 而不是 ``BLIND_RADIUS_M``：**函数默认值在 def 期求值**，
    写成常量就等于把 1000.0 焊进每个函数对象 —— 日后口径分档，那 15 条默认路径一条都不跟
    （γ 守卫 G-11 钉的正是这个形状）。决议只能发生在调用时、只能从口径对象读。
    ⚠️ `travel_mode` 无默认值：回落给哪一档必须是**写出来的**，不是签名替我选的。
    """
    return resolve_blind_radius_m(travel_mode) if value is None else float(value)

# 必达要素登记表：类别键 → 前端缺位名（与契约 `missing_facilities` 一致）。
# 判盲语义 = 「任一登记类在该点 `BLIND_RADIUS_M` 内无设施 ⇒ 该点判盲」。
# 这张表**同时是采集侧证据半径的开关**（`SpatialScope.required_radius_m`）：
# 登记一类 = 声明「判盲需要它周围 1km 的完整证据」⇒ 该类检索需外扩一个判定半径。
# 加/减一类必达要素只改这里，`blindspot.TRIAD_KEYS` / `field.TRIAD_KEYS` 一律派生。
TRIAD_LABEL: Dict[str, str] = {
    "market": "菜市场",
    "pharmacy": "药店",
    "primary": "小学",
}
TRIAD_KEYS: Tuple[str, ...] = tuple(TRIAD_LABEL)

# 判盲空间口径的**版本号**：写进报告 `caliber`，由复用门与契约判据共同读取。
#
# 为什么走 payload 而不是走缓存键（`caliber.caliber_payload_key`）：
#   - 那个键**同时是 DB 的 `scene_key` 列** ⇒ 键里加一段版本，同一地点会在升级边界上
#     裂成两条历史，且「重算后覆盖」再也对不上原行；
#   - 邻近复用（`repository.find_recent_report_near`）走的是**键前缀扫 + 从值里读
#     `scene.center`** ⇒ 换键根本拦不住邻近命中，只留下裂开的历史。
# 所以版本必须是**载荷里的一个事实**，由读侧谓词判定，而不是键的一部分。
#
# `ev-1` = 证据相（证据域独立于可达域、逐类半径、`evidence_anchors` 明细）。
# `ev-2` = 在 `ev-1` 之上追加**逐格台账** `caliber.cells_ledger`（契约 B13）与其渲染尺。
#   为什么值得占一个版本号而不是"有就有、没有就跳过"：门禁若按后者写，
#   "声明了新版本却没发台账"这种半吊子发布就永远查不出来 —— 版本号与键集是同一次发布的两半。
#   存量 `ev-1` 报告（凯里老街 `lc-7b252c2c` 与劲松出厂快照）因此自动落到"旧版本 ⇒ 跳过 B5/B10/
#   B11/B12/B13 + 前端陈旧提示"，**不会**从历史列表消失（可见性由 `assess_geometry` 管，
#   而版本不等时那些条根本不触发）。
SCOPE_POLICY_VERSION = "ev-2"

# ── 采集留边是**导出量**，不是旋钮（片 1b 第二段：与判定半径解绑）────────
# 判「某格 R 圆内没有药店」的前提是**那个 R 圆被完整查过一遍**。所以采集必须覆盖
# 「该点 + R」，最远点是可达区外接圆上那点 ⇒ 数学下限就是「外接圆 + 本次判定半径」。
#
# 旧版这里是一个可以自由取 0 的魔数 `COLLECT_MARGIN_M`，并用注释摆了两条路线：
#   D2（余量 0）字面严格「不请求圈外」，但可判定面积实测只剩 5%（97 格里 5 格）；
#   D1（余量 = 判定半径）可判定面积 100%，圈外点仍然一个都不进报告。
# 取 0 的代价是把盲区识别能力砍掉 95%，而它换来的东西（「不进报告」）已由可达区过滤
# **独立完整**地保证（`poi.to_points` / `to_stats.in_circle` / `blindspot` 的 inside 掩码）
# ⇒ 那是一个**零收益**的取舍。故余量不再可填，只能由证据需求导出。
#
# ⚠️「导出」发生在**取值时刻**，不在 import 期。这条链上曾写着 `EVIDENCE_MARGIN_M = BLIND_RADIUS_M`，
#   那是把 **walking 档的快照**焊进模块命名空间；而判定链已经改成按 `scope.travel_mode` 决议，
#   于是同一个数在两条链上跟着不同的时刻走：骑行档把判定半径调到 1500m 时，检索外扩仍按 1000m
#   留边 ⇒ 可判面静默缩、`cells_unknown` 上涨，而全量测试**零红**（第十五轮复审 P1-1）。
#   所以现在**没有这个常量**，留边只在两处现算：`from_reach_zone`（用手里那份 `caliber`）与
#   `required_radius_m` / `invariant`（用 `self.blind_radius_m`）。判据：
#   `test_collect_margin_follows_this_runs_ruler`（把两档半径改成不同值后现测，改前代码上必红）。
#
# ⚠️ 余量解决的是「请求到哪」；「实际查到哪」是另一件事，由 `with_evidence()` 绑定的
#   **实测边界**决定（百度单页硬上限 20 条 ⇒ 稠密类别一页查不完，见 capability_manifest）。

# 需要 1km 完整证据的类别登记表 —— 判盲必达要素，即 `TRIAD_KEYS` 本身。
# 这里**不另立一份清单**：登记表就是必达要素表，加一类必达要素只改 `TRIAD_LABEL`，
# 采集侧（`required_radius_m`）与判定侧（`triad_judge_radius_m`）同时跟着动。
EVIDENCE_REQUIRED_CATEGORIES: Tuple[str, ...] = TRIAD_KEYS


# ── 证据域：从「每类一个标量半径」升级为「一组圆盘」（计划 v4 阶段 1）────
@dataclass(frozen=True)
class EvidenceDisc:
    """一个锚点上的一次检索：以 `anchor` 为心、`exhausted_radius_m` 为**已证明查全**的半径。

    两件半径是不同时刻的事实，必须分开记：

      ===================  ======  ================================================
      字段                  时刻     语义
      ===================  ======  ================================================
      ``request_radius_m``  事前     这次向接口**请求**了多大
      ``exhausted_radius_m`` 事后    实际**证明**到哪儿：查全则等于请求值，被分页或
                                    结果数封顶截断则退到「最远那条实测点的距离」
      ===================  ======  ================================================

    证据语义本身沿用 `poi_collector.TermEvidence.frontier_m`（那是对的），本次只换**表示法**：
    一个标量装不下「多个锚点各自查到哪儿」，于是外沿的格只能统统标 unknown。
    把「请求」当「证明」用则是 u27 那一族「把没查的说成查过了」缺陷的根型，故本类型
    在构造时就把这条关系验掉（`invariant`）。

    ``cap_hit`` 区分的是「接口能力封顶」（如单次检索 60 条上限）与「我们没查」：
    前者只能进第三态 `unjudgeable_by_cap`（点名百度的天花板），后者才是 `unknown`
    （我们的失职）。混起来会让报告把外部限制说成自己的漏查，也会让降级闸误判
    （计划 D1③：能力封顶**不得**触发任何降级）。

    ## 完整性不是可填字段（T-P0-4，计划 v5.6）

    `complete` / `cap_hit` 都是 **`stop_reason` 的派生量**，判据的唯一归属在
    `baidu_client.is_exhausted` / `is_server_cap`（那里才是这套词汇的主人）。原先两者是
    可以独立填写的布尔 —— 于是「一个声称查全、穷尽深度却只到一半」的盘能被构造出来，
    只能靠 `invariant()` 事后追打；现在填不出来：说查全就必须拿得出查全的原因。

    `stop_reason=None` 表示**合成盘**（从报告里存的标量边界反推，没有逐词原因）。它一律
    **不自称查全** —— 快照里那个数是谁、按几页查出来的，重建时无从知道；要它「查全」等于
    由表示层替证据作伪证。真正带原因的盘由 `poi_collector` 的转换器喂（唯一实现）。
    """

    category: str
    anchor: LngLat
    request_radius_m: float
    exhausted_radius_m: float
    stop_reason: Optional[str] = None

    @property
    def complete(self) -> bool:
        """本盘是否**证明了**请求半径内查全（合成盘恒 False）。"""
        return is_exhausted(self.stop_reason)

    @property
    def cap_hit(self) -> bool:
        """本盘是否撞在接口能力上限上（第三态 `unjudgeable_by_cap` 的唯一原料）。"""
        return is_server_cap(self.stop_reason)

    def judge_radius_m(self, radius_m: Optional[float] = None) -> float:
        """本圆盘能下结论的最远距离 = 穷尽深度 − 判定半径（负值截成 0）。

        判一格「1km 圆内没有 X」要求那一公里的**整个圆**都落在已查全的域内 ⇒ 锚点周围
        可判面比证据面小一圈。穷尽深度恰等于判定半径时，可判面缩到锚点那一格（不是空）：
        1000m 的检索确实完整覆盖了 1000m 的判定圆，中心格是有结论的。
        """
        # 本盘是纯几何值对象、拿不到 `travel_mode` ⇒ 回落哪一档必须**点名**（批 A① 收紧）。
        # 生产路径由调用方显式传尺，这条默认只兜测试与读数脚本省略实参的那批调用。
        return max(0.0, float(self.exhausted_radius_m) - blind_radius_or(radius_m, "walking"))

    def invariant(self) -> None:
        if self.exhausted_radius_m < -1e-6:
            raise ValueError(f"{self.category} 盘的穷尽深度为负：{self.exhausted_radius_m}")
        if self.exhausted_radius_m > self.request_radius_m + 1e-6:
            raise ValueError(
                f"{self.category} 盘 @({self.anchor[0]:.5f},{self.anchor[1]:.5f}) 实测穷尽 "
                f"{self.exhausted_radius_m:.0f}m > 请求 {self.request_radius_m:.0f}m —— "
                "实测不可能大于请求，换算或绑定顺序有误"
            )
        if self.complete and self.exhausted_radius_m < self.request_radius_m - 1e-6:
            raise ValueError(
                f"{self.category} 盘声称查全，却只证明到 {self.exhausted_radius_m:.0f}m "
                f"< 请求 {self.request_radius_m:.0f}m —— 有词被截断/饿死/熔断时不得 complete=True"
            )


@dataclass(frozen=True)
class EvidenceRegion:
    """若干证据圆盘组成的集合：判盲、出图、举证三件事的**唯一事实源**。

    `to_mask()`（喂判盲）与 `to_ring()` / `area_km2()`（喂出图与面积举证）都从本集合派生。
    过去「图上画一个圈、判定用另一个数」两份事实源各说各话，正是本次改造的靶子；
    同源之后，`test_evidence_region.py::test_rendered_area_and_judging_mask_agree`
    才可能用机器判据守着，而不是靠约定。

    单圆盘（锚点=分析中心、穷尽深度=旧的类边界）是**退化特例**，不是保留的旁路分支：
    `to_mask()` 在该特例下与旧标量判据逐格相同（A2 已钉）。
    """

    discs: Tuple[EvidenceDisc, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "discs", tuple(self.discs))
        for disc in self.discs:
            disc.invariant()

    # ── 索引 ────────────────────────────────────────────────
    def of_category(self, category: str) -> Tuple[EvidenceDisc, ...]:
        return tuple(d for d in self.discs if d.category == category)

    def categories(self) -> Tuple[str, ...]:
        seen: Dict[str, None] = {}
        for d in self.discs:
            seen.setdefault(d.category, None)
        return tuple(seen)

    def frontier_m(self, category: str) -> float:
        """该类「证明到哪儿」的标量塌缩值 = 各类圆盘穷尽深度的**最大值**。

        只为向后兼容既有 `evidence_frontier_m` 键而存在（单圆盘下与旧值恒等）。
        多锚点下它必然低估可判定面 —— 所以判定一律走 `to_mask()`，谁再拿这个标量判盲，
        就等于把并集偷偷塌回一个圆（`test_two_far_apart_discs_are_a_union_not_a_scalar_min`
        钉的正是这件事）。
        """
        return max((float(d.exhausted_radius_m) for d in self.of_category(category)), default=0.0)

    def is_cap_bound(self, category: str, radius_m: Optional[float] = None) -> bool:
        """该类是否**所有**圆盘都撞了接口封顶、且没有一个够得着判定半径 ⇒ 第三态原料。

        半径改从口径决议（原先是体内硬写 `BLIND_RADIUS_M`，是"21 条取值途径"里第 5 处），
        但**比较形状一字未动**：`exhausted < 半径` 的严格号在「恰等于半径」那一格是有结论的
        （`test_evidence_region.py` 的 A3 就钉在那条边界上），换成 `judge_radius_m() <= 0`
        会把该格改判成封顶 —— 归一不许顺手改判据。
        """
        limit = blind_radius_or(radius_m, "walking")   # 同上：值对象无 mode，回落须点名（批 A①）
        discs = self.of_category(category)
        return bool(discs) and all(d.cap_hit and d.exhausted_radius_m < limit for d in discs)

    def min_exhausted_m(self, category: str) -> Optional[float]:
        """该类各圆盘穷尽深度的**最小值**；该类无盘 ⇒ `None`（不是 0）。

        为什么与 `frontier_m` 分名而不是分参数：两个塌缩服务两件不同的事，方向还相反。

          ==========================  ==========  =========================================
          塌缩                         用在哪       错用另一边的后果
          ==========================  ==========  =========================================
          `frontier_m`（max）          标量视图：    拿去定锚点间距 ⇒ 间距按最乐观那块盘算，
                            payload/B5           短盘覆盖的格永远没人取证（虚高）
          `min_exhausted_m`（min）     取证强度规划：  拿去发 payload ⇒ 与旧单圆盘标量值不等，
                            锚点间距            B5 恒等式与前端复算当场红
          ==========================  ==========  =========================================

        返回 `None` 而不是 `0.0` 是刻意的：`0.0` 会让「这类我们一次都没查」在数学上等价于
        「查了但什么都没查到边界内」，于是间距公式照样算得出数、照样发锚点 —— 而那正是复审
        T-P0-1 点名的形状：判据对没有证据的类喊「扩」，扩出来的格阵全是白烧。调用方必须显式
        处理「没有盘」这件事。
        """
        discs = self.of_category(category)
        if not discs:
            return None
        return min(float(d.exhausted_radius_m) for d in discs)

    # ── 判定视图 ────────────────────────────────────────────
    def to_mask(self, grid, category: str, *, radius_m: Optional[float] = None):
        """可判定格掩码 (n, n)：该格的判定圆完整落在**任一**同类圆盘内 ⇒ 能下结论。

        与 `grid` 同一坐标系（格心局部米坐标），**不**按可达区裁剪 —— 裁剪是判盲那一层
        的事（`blindspot` 里与 inside 掩码取交）。这条分工是 A2「逐格等于旧标量判据」成立
        的前提：一旦在这里裁一刀，退化重放就对不上旧读数了。
        """
        import numpy as np

        axis = np.asarray(grid.coords, dtype=float)
        xx, yy = np.meshgrid(axis, axis)
        mask = np.zeros((grid.n, grid.n), dtype=bool)
        for disc in self.of_category(category):
            limit = disc.judge_radius_m(radius_m)
            ax, ay = to_local_xy(grid.center, disc.anchor[0], disc.anchor[1])
            mask |= np.hypot(xx - ax, yy - ay) <= limit + 1e-9
        return mask

    def count_judged(self, grid, category: str, *, radius_m: Optional[float] = None) -> int:
        """该类在该格阵上判得出结论的格数（供 B5/B10/B11 由 payload 里的 discs 复算）。"""
        return int(self.to_mask(grid, category, radius_m=radius_m).sum())

    # ── 呈现视图（与 to_mask 同源）───────────────────────────
    def read_m(self, center: LngLat, category: str, radius_m: Optional[float] = None):
        """连续场 `read(x, y) -> 米`：点到**最近**同类圆盘可判定边界的带符号距离。

        负值 = 在可判定面内 ⇒ marching-squares 取 ``level=0.0``。这就是「画给人看的圈」
        与「喂给判盲的掩码」的共同底稿 —— 两者分歧只可能来自离散化，不可能来自口径。
        """
        import math

        cells = [
            (to_local_xy(center, d.anchor[0], d.anchor[1]), d.judge_radius_m(radius_m))
            for d in self.of_category(category)
        ]

        def read(x: float, y: float) -> float:
            if not cells:
                return math.inf
            return min(math.hypot(x - ax, y - ay) - lim for (ax, ay), lim in cells)

        return read

    def to_ring(
        self,
        grid,
        category: str,
        *,
        radius_m: Optional[float] = None,
        refine: Optional[int] = None,
    ) -> list:
        """可判定面的连续外轮廓族（BD-09 环，闭合）。采样分辨率挂在**判定格**上。

        `refine` 缺省取 `blindspot.MS_REFINE`：那是等值线细分倍率的唯一事实源，但
        `blindspot` 依赖本模块，模块级 import 会成环 ⇒ 函数内惰性取。
        """
        from app.living_circle.contour import marching_squares_binary

        if refine is None:
            from app.living_circle.blindspot import MS_REFINE

            refine = MS_REFINE
        discs = self.of_category(category)
        if not discs:
            return []
        read = self.read_m(grid.center, category, radius_m)
        pad = grid.step
        lo_x = min(to_local_xy(grid.center, d.anchor[0], d.anchor[1])[0]
                   - d.judge_radius_m(radius_m) for d in discs) - pad
        hi_x = max(to_local_xy(grid.center, d.anchor[0], d.anchor[1])[0]
                   + d.judge_radius_m(radius_m) for d in discs) + pad
        lo_y = min(to_local_xy(grid.center, d.anchor[0], d.anchor[1])[1]
                   - d.judge_radius_m(radius_m) for d in discs) - pad
        hi_y = max(to_local_xy(grid.center, d.anchor[0], d.anchor[1])[1]
                   + d.judge_radius_m(radius_m) for d in discs) + pad
        h = grid.step / refine if refine and refine > 0 else grid.step
        nx = max(2, int(math.ceil((hi_x - lo_x) / h)) + 1)
        ny = max(2, int(math.ceil((hi_y - lo_y) / h)) + 1)
        loops = marching_squares_binary(read, lo_x, lo_y, nx, ny, h, level=0.0)
        return [
            ensure_closed([xy_to_lnglat(grid.center, v[0], v[1]) for v in ring])
            for ring in loops
            if len(ring) >= 4
        ]

    def area_km2(
        self,
        category: str,
        reach_ring: Tuple[LngLat, ...],
        *,
        radius_m: Optional[float] = None,
        cell_m: float = 100.0,
    ) -> float:
        """可判定面与可达区交集的面积（km²）—— 与 `to_mask()` 同一个 `read_m` 场。

        格点计数（`cell_m` 一步）而不是解析圆并集面积：并集要处理相交/包含，而这里要的
        只是「图上说多少平方公里」与「判盲面多大」能对上账 —— 同源自洽优先于解析精确。
        交集用可达区裁剪，因为超出可达区的证据面在报告里没有承载物。
        """
        discs = self.of_category(category)
        if not discs or not reach_ring:
            return 0.0
        origin = (
            sum(p[0] for p in reach_ring) / len(reach_ring),
            sum(p[1] for p in reach_ring) / len(reach_ring),
        )
        read = self.read_m(origin, category, radius_m)
        pts = [to_local_xy(origin, d.anchor[0], d.anchor[1]) for d in discs]
        lims = [d.judge_radius_m(radius_m) for d in discs]
        lo_x = min(ax - lim for (ax, _), lim in zip(pts, lims))
        hi_x = max(ax + lim for (ax, _), lim in zip(pts, lims))
        lo_y = min(ay - lim for (_, ay), lim in zip(pts, lims))
        hi_y = max(ay + lim for (_, ay), lim in zip(pts, lims))
        nx = max(1, int(math.ceil((hi_x - lo_x) / cell_m)))
        ny = max(1, int(math.ceil((hi_y - lo_y) / cell_m)))
        # 只数「格心在可判定面内 且 在可达区内」的格 —— 与判盲对格心的处理完全同构
        cx = (nx + 1) * 0.5
        cy = (ny + 1) * 0.5
        hit = 0
        for i in range(1, nx + 1):
            x = (i - cx) * cell_m
            for j in range(1, ny + 1):
                y = (j - cy) * cell_m
                if read(x, y) >= 0.0:
                    continue
                if point_in_ring(xy_to_lnglat(origin, x, y), reach_ring):
                    hit += 1
        return hit * cell_m * cell_m / 1e6


@dataclass(frozen=True)
class SpatialScope:
    """一次体检的**空间口径定格**：三个概念 × 两个时刻。

    ============================  =========  =========================================
    字段                          时刻        语义
    ============================  =========  =========================================
    ``reach_ring`` / ``circum``   事前(几何)  可达区 —— 报告与展示的域
    ``collect_radius_m``          事前(几何)  **请求**了多大（证据需求导出的上界）
    ``study_radius_m``            事前(几何)  研究区 —— 标称范围，仅展示/配额
    ``evidence_radius_m``         事后(举证)  **实际证明**到哪儿（逐类实测边界的最小值）
    ``evidence_frontier_m``       事后(举证)  逐类实测边界
    ``evidence_complete``         事后(举证)  有无词被截断/饿死/熔断
    ``evidence_capped_categories`` 事后(举证)  哪些类撞了**接口自有**上限（≠ 我们没查）
    ============================  =========  =========================================

    旧版只有前三行，于是「我请求了多大」被直接当成「我证明了多大」用 —— 分页饱和在类型
    上无处安放，只能被省略；而省略的收益（少写代码）不可见、代价（盲区少报）方向上让
    分数变好，缺陷于是被评分函数**奖励**。补上后三行，才是这次修复的正解。

    字段全部是派生值或实测值，没有可自由填写的「名义值」。
    """

    travel_mode: str
    reach_min: float                 # 可达区口径分钟数（= caliber.reach_full_min）
    reach_ring: Tuple[LngLat, ...]   # 可达区多边形（闭合环）
    reach_circumradius_m: float      # 可达区外接圆半径（实测，非名义）
    collect_radius_m: float          # 采集半径 = 外接圆 + 本次判定半径（按类下界见 required_radius_m）
    study_radius_m: float            # 研究区半径（报告标称范围，仅展示/配额）

    # ── 事后举证相（采集完成前为 None / 空）────────────────────
    evidence_radius_m: Optional[float] = None
    evidence_frontier_m: Mapping[str, float] = field(default_factory=dict)
    evidence_complete: bool = False
    # 撞了**接口自有**上限的类别（由 `place_search` 的 `cap_hit` 逐级回传）。与
    # `evidence_complete` 分名分职：complete=False 说「我们没查全」，capped 说「百度不给」。
    # 只有后者能喂第三态 `cells_unjudgeable_by_cap`（计划 D1③：能力封顶不得触发降级）。
    evidence_capped_categories: Tuple[str, ...] = ()
    # 逐类**为什么**停（`stop_reason`）：T-P0-4（计划 v5.6）补的那一格 —— 盘上的
    # `complete`/`cap_hit` 现在都从它派生，所以「查全」这个声明第一次有了可核查的出处。
    # 取的是**决定该类边界的那一行**（frontier 最小者）的原因：边界由短板定，原因也该由
    # 同一块短板给，否则会出现「边界是截断词定的、完整性却声称查全」。
    evidence_stop_reasons: Mapping[str, str] = field(default_factory=dict)
    evidence_detail: Mapping[str, Any] = field(default_factory=dict)
    # 证据**区域**（计划 v4 阶段 1）：None = 尚未按区域取证（旧路径 / 离线源不得伪造圆盘）。
    # 标量三件（radius/frontier/complete）继续原样发射，区域只是**追加**的第二视图：
    # 单圆盘下两者恒等，所以 B5/B10/B11 与前端复算都不破（批次一的零回归靠这条）。
    evidence_region: Optional["EvidenceRegion"] = None

    # ── 构造 ────────────────────────────────────────────────
    @classmethod
    def from_reach_zone(
        cls,
        caliber: ReachCaliber,
        center: LngLat,
        study_radius_m: float,
        zone: Mapping[str, Any],
    ) -> "SpatialScope":
        """由**显式指定的**可达区环构造，并校验环的 minutes 与口径一致。"""
        minutes = float(zone.get("minutes"))
        if abs(minutes - float(caliber.reach_full_min)) > 1e-9:
            raise ValueError(
                f"可达区环 minutes={minutes} 与口径 reach_full_min={caliber.reach_full_min} 不一致"
                f"（travel_mode={caliber.travel_mode!r}）—— 形参名与实参语义不符正是 Q2 根因"
            )
        ring = tuple((float(p[0]), float(p[1])) for p in zone["geojson"]["coordinates"][0])
        if len(ring) < 3:
            raise ValueError(f"可达区环顶点数不足（{len(ring)}）—— 无法构成多边形")
        cr = max(haversine_m(center, p) for p in ring)
        return cls(
            travel_mode=caliber.travel_mode,
            reach_min=minutes,
            reach_ring=ring,
            reach_circumradius_m=cr,
            collect_radius_m=cr + float(caliber.blind_radius_m),
            study_radius_m=float(study_radius_m),
        )

    @classmethod
    def from_iso(
        cls,
        caliber: ReachCaliber,
        center: LngLat,
        study_radius_m: float,
        iso: Mapping[str, Any],
    ) -> "SpatialScope":
        """从等时圈族里**按 minutes 选环**（不是按位置取 ``[-1]``）。

        按位置取环的隐患：将来加一个 25min 圈 → 可达区语义静默改变，而没有任何测试会红。
        """
        zones = list(iso.get("isochrones") or [])
        if not zones:
            raise ValueError("等时圈族为空 ⇒ 无法确定可达区（这正是「静默空壳报告」的入口）")
        target = float(caliber.reach_full_min)
        matches = [z for z in zones if abs(float(z.get("minutes")) - target) < 1e-9]
        if not matches:
            have = sorted(float(z.get("minutes")) for z in zones if z.get("minutes") is not None)
            raise ValueError(f"等时圈族里没有 minutes={target} 的圈（实有 {have}）—— 口径与数据不一致")
        return cls.from_reach_zone(caliber, center, study_radius_m, matches[0])

    # ── 事前：按类别的**证据需求半径** ───────────────────────
    def required_radius_m(self, category: str) -> float:
        """本次要为某类别查到哪儿 —— 由「判盲是否需要它周围一整个判定圆的完整证据」决定。

        登记类（= 必达要素）⇒ 外接圆 + **本次判定半径**（按 `self.travel_mode` 现算，
        不是 import 期快照）；其余 ⇒ 外接圆。
        这是 D-1「最小必要越界」的落点：展示用的 20 多个检索词一个字都不越界，
        只有判定真正需要的几类外扩。加一类必达要素只改 `TRIAD_LABEL`，这里自动跟着动。
        """
        base = float(self.reach_circumradius_m)
        if category in EVIDENCE_REQUIRED_CATEGORIES:
            return base + self.blind_radius_m
        return base

    # ── 事后：绑定实测证据 ───────────────────────────────────
    def with_evidence(
        self,
        frontier_m: Optional[Mapping[str, float]] = None,
        *,
        complete: bool = False,
        detail: Mapping[str, Any] = frozenset(),
        capped: Sequence[str] = (),
        stop_reasons: Optional[Mapping[str, str]] = None,
        region: Optional["EvidenceRegion"] = None,
    ) -> "SpatialScope":
        """把采集侧的**实测证据**绑成新的定格（返回新实例，自动过 ``invariant``）。

        两种输入形状，**互斥**（同时给即报错，不留「谁覆盖谁」的第二套口径）：

        - ``frontier_m``：逐类一个标量（旧形状）。由 `poi_collector.CollectionEvidence`
          换算而来 —— 那里才是唯一知道页深/饱和/熔断事实的地方。
        - ``region``：逐锚点一组圆盘（新形状，计划 v4 阶段 1）。标量三件仍由 region
          **塌缩**得到（`EvidenceRegion.frontier_m` 取该类圆盘穷尽深度的最大值），
          所以既有 payload 键与 B5/B10/B11、前端复算全部不破；单圆盘下与旧值逐位恒等。

        ``evidence_radius_m`` 取登记类边界的**最小值**：判一个点要同时具备三类必达要素的
        1km 证据，短板决定可判定面。取 max 会把「有一类没查全」说成「都查全了」。
        """
        if region is not None and frontier_m:
            raise ValueError(
                "with_evidence 同时收到 frontier_m 与 region —— 标量与区域必须有唯一来源，"
                "让其中一个悄悄覆盖另一个就是第二事实源回来了"
            )
        if region is not None:
            fr = {cat: region.frontier_m(cat) for cat in region.categories()}
            # 区域在手就以区域为准：封顶是从**盘**上读出来的，让调用方再传一遍 `capped`
            # 就是第二事实源（漏传一次 ⇒ 第三态凭空变 0，比标量时代更难发现）。
            capped_src = tuple(
                cat for cat in region.categories()
                if all(d.cap_hit for d in region.of_category(cat))
            )
            # 逐类原因与逐类边界**同源**：`frontier_m` 塌缩取该类盘的最大穷尽深度，所以原因
            # 也取那个盘的 `stop_reason`。二者若各按各的规则塌缩，标量视图就会自相矛盾
            # （边界是乐观值、完整性却是保守值，或反过来）。
            reasons_src = {
                cat: max(region.of_category(cat), key=lambda d: d.exhausted_radius_m).stop_reason or ""
                for cat in fr
            }
        else:
            fr = {str(k): float(v) for k, v in (frontier_m or {}).items()}
            capped_src = tuple(str(c) for c in capped)
            reasons_src = {str(k): str(v) for k, v in (stop_reasons or {}).items()}
        bound = min((fr.get(k, 0.0) for k in EVIDENCE_REQUIRED_CATEGORIES), default=0.0)
        new = replace(
            self,
            evidence_radius_m=bound,
            evidence_frontier_m=fr,
            evidence_complete=bool(complete),
            evidence_detail=dict(detail or {}),
            evidence_capped_categories=capped_src,
            evidence_stop_reasons=reasons_src,
            evidence_region=region,
        )
        new.invariant()
        return new

    # ── 校验 ────────────────────────────────────────────────
    def invariant(self) -> None:
        """三概念 × 两时刻关系的机器校验（构造后即调，写错就报错而不是画出一张 29km² 的灰方框）。"""
        if self.reach_circumradius_m <= 0:
            raise ValueError("可达区外接圆半径必须为正")
        if self.collect_radius_m < self.reach_circumradius_m + self.blind_radius_m - 1e-6:
            raise ValueError(
                f"采集半径 {self.collect_radius_m:.0f}m < 可达区外接圆 "
                f"{self.reach_circumradius_m:.0f}m + 采集留边（本次判定半径 "
                f"{self.blind_radius_m:.0f}m）—— "
                "D2（余量 0）已废止：余量由证据需求导出，不是可填的名义值。"
                "可达区外沿的格其判定圆伸出采集区 ⇒ 那些格只能标 unknown，"
                "而把整个外沿不判等于砍掉判盲能力。"
            )
        if self.study_radius_m <= 0:
            raise ValueError("研究半径必须为正")
        # 举证相自洽：证据不可能超过请求；也不许「声称完整」同时又承认没采到边
        if self.evidence_radius_m is not None:
            if not (-1e-6 <= self.evidence_radius_m <= self.collect_radius_m + 1e-6):
                raise ValueError(
                    f"证据边界 {self.evidence_radius_m:.0f}m 超出请求半径 "
                    f"{self.collect_radius_m:.0f}m —— 实测不可能大于请求，绑定顺序或换算有误"
                )
            if self.evidence_complete and self.evidence_radius_m < self.collect_radius_m - 1e-6:
                raise ValueError(
                    f"声称证据完整，但实测边界 {self.evidence_radius_m:.0f}m "
                    f"< 请求 {self.collect_radius_m:.0f}m —— 有词被截断/饿死/熔断时不得 complete=True"
                )
        if self.evidence_capped_categories:
            # 名单只认「这次真量过边界的那些类」。写错一个类名不会报错、只会让第三态
            # 静默变 0 —— 而静默变 0 恰是本轮要消灭的形状（把没归因的缺口说成没有缺口）。
            orphan = tuple(c for c in self.evidence_capped_categories
                           if c not in self.evidence_frontier_m)
            if orphan:
                raise ValueError(
                    f"封顶名单里的 {orphan} 没有对应的实测边界 ⇒ 类名写错，"
                    "或在绑定边界之前就声明了封顶"
                )
        # 逐圆盘式（与上面的标量式**并存**校验；单圆盘下两者等价 ⇒ 批次一零回归可被证明）：
        # 每个锚点的请求都不得越过本次体检的采集半径。越过只有两种可能 —— 锚点用了另一套
        # 半径口径（那么它测的已经不是这次的空间口径），或换算/绑定顺序错了。
        # 计划里那条 `request ≥ coverage + BLIND_RADIUS_M` 要等 LatticeAnchors 知道每个锚点
        # 实际负责哪些格才谈得上，故落在阶段 3 而不是这里硬凑一个恒真式。
        if self.evidence_region is not None:
            for disc in self.evidence_region.discs:
                if disc.request_radius_m > self.collect_radius_m + 1e-6:
                    raise ValueError(
                        f"{disc.category} 盘请求半径 {disc.request_radius_m:.0f}m 超出本次采集半径 "
                        f"{self.collect_radius_m:.0f}m ⇒ 该锚点用的不是这次的空间口径"
                    )
                if disc.exhausted_radius_m > self.collect_radius_m + 1e-6:
                    raise ValueError(
                        f"{disc.category} 盘实测穷尽 {disc.exhausted_radius_m:.0f}m 超出采集半径 "
                        f"{self.collect_radius_m:.0f}m"
                    )

    # ── 派生：判定域 ────────────────────────────────────────
    @property
    def evidence_bound_m(self) -> float:
        """证据边界：已绑定 ⇒ 实测值；未绑定 ⇒ 退回请求半径（**旧行为**，并在 payload 里注明来源）。

        未绑定只可能发生在不跑真实采集的路径（离线骨架 / 夹具）。退回几何值是为了不炸那些
        路径，但退回这件事本身必须可见 —— 否则「没绑定证据」就成了「默认证据充分」。
        """
        if self.evidence_radius_m is None:
            return float(self.collect_radius_m)
        return float(self.evidence_radius_m)

    @property
    def evidence_bound_source(self) -> str:
        return "measured" if self.evidence_radius_m is not None else "unbound_geometric_fallback"

    @property
    def blind_radius_m(self) -> float:
        """本次体检真正使用的判定半径（按 `travel_mode` 从口径对象取）。

        这是**取用面**，不是第二处定义 —— 数住在 `caliber.ReachCaliber.blind_radius_m`。
        住在 scope 上是因为只有这里同时拿得到「哪种出行方式」与「判盲要的那把尺」；
        `EvidenceRegion`/`EvidenceDisc`/`LatticeAnchors` 这些纯几何值对象没有 mode，
        它们的半径一律由**调用方**（`blindspot`，手里有 scope）显式传下去。
        """
        return resolve_blind_radius_m(self.travel_mode)

    def judge_radius_m(self, radius_m: Optional[float] = None) -> float:
        """可判定半径：圆心到「`radius_m` 圆仍被证据边界完整覆盖」的最远距离。

        = 证据边界 − 判定半径。可达区内超出该半径的格**不判盲**（数据不足以支撑结论）。

        本方法从消费方（旧 `blindspot.judge_radius_m`）上移到值对象：它是「三概念之间的
        关系」，按本文件头的主张（关系做成构造即校验）本就该长在这里 —— 住在消费方时，
        任何新判定都得自己抄一遍这条公式，而抄错没有任何一层能发现。
        """
        return max(0.0, self.evidence_bound_m - blind_radius_or(radius_m, self.travel_mode))

    def category_bound_m(self, category: str) -> float:
        """该类**实际证明到哪儿**（米）—— 逐类边界的唯一取法。

        未绑定证据 ⇒ 退回请求半径（与 `evidence_bound_m` 同源的旧行为，来源由 payload 的
        `evidence_bound_source` 披露）。这条选择只许住在一处：`triad_judge_radius_m` 与
        `degenerate_evidence_region` 都吃它 —— 前者算可判半径、后者造退化圆盘，两处各抄
        一遍就是本仓反复出事的「同一口径两个定义」（阶段 1 初版我自己就抄重了，故抽出）。
        """
        if self.evidence_radius_m is None:
            return float(self.collect_radius_m)
        return float(self.evidence_frontier_m.get(category, 0.0))

    def triad_judge_radius_m(
        self, category: str, radius_m: Optional[float] = None
    ) -> float:
        """逐类可判定半径：该类的实测证据边界 − 判定半径。

        为什么必须逐类：一个点判盲要求**三类**各自的 1km 圆都查全。药店稠密到一页查不完
        （凯里实测 60 家 / 单页上限 20），菜市场与小学却一页就穷尽 ⇒ 三类的边界天然不同。
        用单一几何半径判，等于让最稠密那一类的证据缺口，去替最稀疏那一类下结论。

        区域路径（阶段 1 起是**唯一**路径）不再需要本方法 —— 它由
        `EvidenceDisc.judge_radius_m()` 逐圆盘算。留着它只为标量举证（payload 的
        `judge_radius_m` 键、B10 复算、前端那份独立复核）还能读到同一个数。
        """
        return max(0.0, self.category_bound_m(category) - blind_radius_or(radius_m, self.travel_mode))

    def degenerate_evidence_region(self, center: LngLat) -> "EvidenceRegion":
        """把标量证据边界表达成「每类一个圆盘」的退化 region。

        这是计划 v4 的架构姿态 2：判定路径**只认区域**，不给标量留旁支分支 —— 「现状」于是
        是 `EvidenceRegion` 的一个特例（锚点=分析中心，穷尽深度=该类的标量边界）。只有这么
        表达，A2 那条重放用例才能证明「新模型是旧模型的一般化」，而不是让两套实现并存到
        谁也不敢删。

        `cap_hit` 逐类取自 `evidence_capped_categories`（由 `place_search` 的 `STOP_SERVER_CAP`
        逐级回传）：这里仍不许凭空写 True —— 没有采集侧的「服务端自称还欠一整页」这条事实，
        替接口的能力上限作伪证就只是换个地方撒谎。
        `request_radius_m` 取 ``max(采集半径, 穷尽深度)``：标量时代只校验逐类边界的**最小值**
        不超过请求，所以某一类越界今天无人发现；这里不跟着编造一个更大的请求值，也不让
        越界事实被圆盘自检吞掉（它是红的，正是要红）。
        """
        collect = float(self.collect_radius_m)
        capped = set(self.evidence_capped_categories)
        discs = tuple(
            EvidenceDisc(
                category=key,
                anchor=(float(center[0]), float(center[1])),
                request_radius_m=max(collect, bound),
                exhausted_radius_m=bound,
                # T-P0-4：`complete`/`cap_hit` 都从 `stop_reason` 派生，这里不再手填布尔。
                # 退化盘是**合成**的（从报告存的标量边界反推），所以只允许带一种原因：
                # 「该类撞过接口自有上限」——它来自采集侧逐级回传的事实，不是这里编的。
                # 其余一律 `None` ⇒ 合成盘**不自称查全**：标量塌缩后的数字与当初那一行的
                # requested/exhausted 关系已经不是同一件事，替它声明查全才是作伪证
                # （查全与否在标量侧仍由 `evidence_complete` 承担，那是采集侧的事实）。
                stop_reason=(STOP_SERVER_CAP if key in capped else None),
            )
            for key in TRIAD_KEYS
            for bound in (self.category_bound_m(key),)
        )
        return EvidenceRegion(discs)

    def _one_region_source(self, override: Optional["EvidenceRegion"], where: str) -> None:
        """「两条取法不许交出两块不同区域」这条守卫的**唯一实现**（计划 v5.9 前置②）。

        判据/判盲（`judge_region`）与举证发射（`payload`）都过这里。守卫长在调用方各自抄一遍
        是本仓反复出事的形状 —— 抄漏一处，「报告展示的盘」与「判定吃的盘」就能安静地分家。
        """
        if (override is not None and self.evidence_region is not None
                and override is not self.evidence_region):
            raise ValueError(
                f"{where}：判定区域必须有唯一来源 —— 显式 region 与 scope.evidence_region "
                "不是同一个对象。让其中一个悄悄覆盖另一个，报告里的格分账与逐锚点举证"
                "就不是同一块区域撑起来的（第二事实源）"
            )

    def judge_region(self, center: LngLat,
                     override: Optional["EvidenceRegion"] = None) -> "EvidenceRegion":
        """判定这一次吃哪块证据区域 —— 这条解析只许存在一处（计划 v5.9 前置②）。

        三条出路按优先级：显式 `override` > 绑在定格上的 `evidence_region` >
        `degenerate_evidence_region` 的单圆盘特例（「现状」的表示法）。**但参数通道有适用面**：
        已经绑过 region 的 scope 再给一块不同的 ⇒ 报错，只有「同一对象」或「没绑过」才放行。
        对取证回合的含义：中途注入「A ∪ 本轮」必须建立在**没绑过 region** 的那份 scope 上
        （生产 `data_source.bind_evidence()` 走标量绑定，正是这一形状）。此前这段判断写在
        `blindspot.cover_matrix` 里（T-P0-1 落地时开的参数通道），落库侧读的是另一个字段
        （复审 P2-10）⇒ 参数通道一旦被接线用上，报告的 `cells_*` 分账与 `evidence_anchors`
        就不是同一块区域撑的，且没有一层能发现。收拢到值对象上，判定与举证共用同一处解析。

        为什么留参数通道而不改成「一律 `with_evidence(region=…)` 绑定」：绑定会把 payload 的
        标量视图来源从「采集器逐词取 min」换成「圆盘取 max」，那是要与 B5/B10/B11、前端 6 份
        复算副本同批改的破坏性改动（批次二）。缺省路径与今天逐位相同。
        """
        self._one_region_source(override, "judge_region")
        return override or self.evidence_region or self.degenerate_evidence_region(center)

    # ── 举证 ────────────────────────────────────────────────
    def payload(self, caliber: ReachCaliber, blind_stats: Optional[Dict[str, int]] = None, *,
                judged_region: Optional["EvidenceRegion"] = None,
                forensic: Optional[Mapping[str, Any]] = None,
                cells_ledger: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """报告顶层 ``caliber`` 举证对象（口径 + 几何 + 判盲覆盖度）。

        ``cells_unknown`` 是**可观测性出口**：采集半径若算错，读数会上升（可见、可诊断），
        而不是让盲区悄悄膨胀成整张网格。

        ``judged_region``（v5.9 前置②）：逐锚点举证那一块必须由**判定真正吃的那片区域**发射，
        而不是固定读 `self.evidence_region`。不传 ⇒ 与今天逐字相同；传了且与绑定块不是同一对象
        ⇒ 报错（同 `judge_region` 那条纪律）。缺省路径下判定与举证天然同块。

        ``forensic``（片 4）：取证回合的账目（跑了几轮、打了几个锚点、为什么收手）。
        留**参数通道**而不是在 scope 上加字段，理由与 `blind_stats` 同一条：这些事实长在
        编排层的循环上，不在口径定格上 —— 让它们绕道住进 `SpatialScope`，就等于允许
        「一份 scope 配一套回合账目」。
        ⚠️ 不传 ⇒ **不发这个键**（与 `evidence_anchors` 同纪律）：离线估算与夹具从未走过
        取证阶段，给它们补一份 `rounds: 0` 等于替一次没发生的取证举证。

        ``cells_ledger``（计划 cells-ledger-judge-scale §4）：逐格台账 —— 判定那一次算出的
        每张 ``n×n`` 掩码摊成行字符串。本层**只管发射**，不懂逐格语义（渲染在
        ``blindspot.render_cells_ledger``，那里才持有掩码的字母表）。同样「不传 ⇒ 不发」：
        离线骨架与升级前的路径没有逐格判定，替它们补一张空台账就是伪造举证。
        """
        out: Dict[str, Any] = {
            "travel_mode": caliber.travel_mode,
            "speed_m_per_min": caliber.speed_m_per_min,
            "detour_k": caliber.detour_k,
            "study_radius_m": caliber.study_radius_m,
            "iso_minutes": list(caliber.iso_minutes),
            "basis": caliber.basis,
            "measured": caliber.measured,
            # 空间口径三概念 + 关系（本轮新增，Q1/Q2 的可判据化）
            "reach_full_min": caliber.reach_full_min,
            "reach_radius_bound_m": round(caliber.reach_radius_bound_m, 1),
            "reach_circumradius_m": round(self.reach_circumradius_m, 1),
            "collect_radius_m": round(self.collect_radius_m, 1),
            # 键名保留 `collect_margin_m`（前端契约 `livingCircleContract.test.ts:89` 的
            # `collect ≈ circumradius + collect_margin` 恒等式读它）。值现在是**本次这档的判定
            # 半径**（构造采集区时真正用的那把尺），不再是 import 期的 walking 快照 ⇒ 读侧 B5
            # （`report_contract.py:296`）拿它复算，检的是「这次留的边够不够盖住判定圆」。
            "collect_margin_m": round(self.blind_radius_m, 1),
            # ── 事后举证相：「实际查到哪儿」与「请求了多大」并列可查 ──
            "evidence_margin_m": round(self.blind_radius_m, 1),
            "evidence_radius_m": (
                None if self.evidence_radius_m is None else round(self.evidence_radius_m, 1)
            ),
            "evidence_frontier_m": {
                k: round(v, 1) for k, v in sorted(self.evidence_frontier_m.items())
            },
            "evidence_complete": bool(self.evidence_complete),
            "evidence_bound_source": self.evidence_bound_source,
            "judge_radius_m": round(self.judge_radius_m(), 1),
            # 三种「证据不够」是**不同的缺陷**，不得合并成一个键：
            #   truncated = 发了请求但被单页上限截断（我们没接着翻 ⇒ 我们的失职）
            #   starved   = 预算拒绝，一次请求都没发（连边界都没有 ⇒ 还是我们的失职）
            #   capped    = 服务端自称还有货却断了页（再多的预算也拿不到 ⇒ 百度的天花板）
            # 前两种喂 `unknown`，第三种喂 `unjudgeable_by_cap`：混起来就是把外部限制写成
            # 自己的漏查，或把自己的没查洗成天经地义。与 `poi.truncated`（展示上限）
            # 刻意不复用同一个词是同一纪律。
            "evidence_truncated_terms": list(self.evidence_detail.get("truncated_terms") or []),
            "evidence_starved_terms": list(self.evidence_detail.get("starved_terms") or []),
            "evidence_capped_categories": sorted(self.evidence_capped_categories),
            # T-P0-4（计划 v5.6）追加发射，读侧暂时无人消费 ⇒ 批次一零回归不受影响。
            # 逐类「为什么停」，与 `evidence_frontier_m` **同源**（都由决定边界的那一行给）：
            # 有了它，"边界 1494m" 才能区分是「药店截断在 20 条」还是「那一词我们没查成」。
            "evidence_stop_reasons": {
                k: str(v) for k, v in sorted(self.evidence_stop_reasons.items())
            },
            # 口径版本：复用门（`report_contract.reuse_policy`）与契约判据据此判别
            # 「这份报告是不是本次这一套口径的产物」。写侧只有这一处发射点。
            "scope_policy_version": SCOPE_POLICY_VERSION,
        }
        # 逐锚点举证（计划 v4 阶段 2a · **追加**发射，无人绑定 region 时不出这个键）：
        # 报告要能回答「这片的证据是哪几个点撑起来的」，否则多锚点与单锚点在读数上无从
        # 区分 —— 而区分它们正是这次改造的全部理由。上面三个标量键一个都不删，
        # B5/B10/B11 与前端复算照旧吃得动（批次一的零回归约束）。
        # v5.9 前置②：展示哪一块由 `judged_region` 定，缺省仍是绑定那块 ⇒ 逐位不变。
        self._one_region_source(judged_region, "payload(judged_region=…)")
        shown_region = judged_region if judged_region is not None else self.evidence_region
        if shown_region is not None:
            out["evidence_anchors"] = [
                {
                    "category": d.category,
                    "anchor": [round(d.anchor[0], 6), round(d.anchor[1], 6)],
                    "request_radius_m": round(d.request_radius_m, 1),
                    "exhausted_radius_m": round(d.exhausted_radius_m, 1),
                    "complete": bool(d.complete),
                    "cap_hit": bool(d.cap_hit),
                    # T-P0-4：完整性与封顶的**出处**。`null` 表示这是合成盘（从标量边界反推），
                    # 它按定义不自称查全 —— 读侧据此才能把「盘的 complete=False」与
                    # 「盘的原因写着 api_error」区分开（前者可能只是没有原因可说）。
                    "stop_reason": d.stop_reason,
                }
                for d in shown_region.discs
            ]
        if blind_stats is not None:
            out.update({k: int(v) for k, v in blind_stats.items()})
        if forensic is not None:
            out["forensic"] = dict(forensic)
        if cells_ledger is not None:
            out["cells_ledger"] = dict(cells_ledger)
        return out


__all__ = [
    "BLIND_RADIUS_M",
    "EVIDENCE_REQUIRED_CATEGORIES",
    "SCOPE_POLICY_VERSION",
    "SpatialScope",
    "TRIAD_KEYS",
    "TRIAD_LABEL",
]
