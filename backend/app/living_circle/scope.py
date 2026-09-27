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
  - 采集区 ≥ 可达区外接圆 + 判定半径（外沿的格其 1km 圆伸出采集区 ⇒ 只能标 unknown；
    而把整个外沿不判，等于砍掉判盲能力 —— 见 ``EVIDENCE_MARGIN_M`` 的理由）
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

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple

from app.living_circle.caliber import ReachCaliber
from app.living_circle.geo_utils import LngLat, haversine_m

# ── 判盲口径的唯一事实源 ────────────────────────────────────────────
# 盲区判定半径（赛题标准）：判「某点 1km 圆内有没有某类必达设施」。
# 定义权在**本模块**：它是「采集区 / 可达区 / 判定区」三概念之间那条关系的另一半，
# 只有判定半径住在这里，`judge_radius_m()` 才可能做成「构造即校验」的关系（见文件头）。
# `blindspot` 与 `field` 过去各写了一份字面量 —— 那正是本仓反复出事的「同一口径两处定义」。
BLIND_RADIUS_M = 1000.0

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
SCOPE_POLICY_VERSION = "ev-1"

# ── 证据需求决定采集余量（不是「唯一开关」，是**导出值**）────────────
# 判「某格 1km 内没有药店」的前提是**那个 1km 圆被完整查过一遍**。所以采集必须覆盖
# 「该点 + 1km」，最远点是可达区外接圆上那点 ⇒ 数学下限就是「外接圆 + 判定半径」。
#
# 旧版这里是一个可以自由取 0 的魔数 `COLLECT_MARGIN_M`，并用注释摆了两条路线：
#   D2（余量 0）字面严格「不请求圈外」，但可判定面积实测只剩 5%（97 格里 5 格）；
#   D1（余量 = 判定半径）可判定面积 100%，圈外点仍然一个都不进报告。
# 取 0 的代价是把盲区识别能力砍掉 95%，而它换来的东西（「不进报告」）已由可达区过滤
# **独立完整**地保证（`poi.to_points` / `to_stats.in_circle` / `blindspot` 的 inside 掩码）
# ⇒ 那是一个**零收益**的取舍。故余量不再可填，只能由证据需求导出。
#
# ⚠️ 余量解决的是「请求到哪」；「实际查到哪」是另一件事，由 `with_evidence()` 绑定的
#   **实测边界**决定（百度单页硬上限 20 条 ⇒ 稠密类别一页查不完，见 capability_manifest）。
EVIDENCE_MARGIN_M = BLIND_RADIUS_M

# 需要 1km 完整证据的类别登记表 —— 判盲必达要素，即 `TRIAD_KEYS` 本身。
# 这里**不另立一份清单**：登记表就是必达要素表，加一类必达要素只改 `TRIAD_LABEL`，
# 采集侧（`required_radius_m`）与判定侧（`triad_judge_radius_m`）同时跟着动。
EVIDENCE_REQUIRED_CATEGORIES: Tuple[str, ...] = TRIAD_KEYS


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
    collect_radius_m: float          # 采集半径 = 外接圆 + EVIDENCE_MARGIN_M（按类下界见 required_radius_m）
    study_radius_m: float            # 研究区半径（报告标称范围，仅展示/配额）

    # ── 事后举证相（采集完成前为 None / 空）────────────────────
    evidence_radius_m: Optional[float] = None
    evidence_frontier_m: Mapping[str, float] = field(default_factory=dict)
    evidence_complete: bool = False
    evidence_detail: Mapping[str, Any] = field(default_factory=dict)

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
            collect_radius_m=cr + float(EVIDENCE_MARGIN_M),
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
        """本次要为某类别查到哪儿 —— 由「判盲是否需要它周围 1km 的完整证据」决定。

        登记类（= 必达要素）⇒ 外接圆 + 判定半径；其余 ⇒ 外接圆。
        这是 D-1「最小必要越界」的落点：展示用的 20 多个检索词一个字都不越界，
        只有判定真正需要的几类外扩。加一类必达要素只改 `TRIAD_LABEL`，这里自动跟着动。
        """
        base = float(self.reach_circumradius_m)
        if category in EVIDENCE_REQUIRED_CATEGORIES:
            return base + float(EVIDENCE_MARGIN_M)
        return base

    # ── 事后：绑定实测证据 ───────────────────────────────────
    def with_evidence(
        self,
        frontier_m: Mapping[str, float],
        *,
        complete: bool,
        detail: Mapping[str, Any] = frozenset(),
    ) -> "SpatialScope":
        """把采集侧的**实测证据边界**绑成新的定格（返回新实例，自动过 ``invariant``）。

        ``frontier_m``：逐类「实际查到哪儿」（米）。由 `poi_collector.CollectionEvidence`
        换算而来 —— 那里才是唯一知道页深/饱和/熔断事实的地方。

        ``evidence_radius_m`` 取登记类边界的**最小值**：判一个点要同时具备三类必达要素的
        1km 证据，短板决定可判定面。取 max 会把「有一类没查全」说成「都查全了」。
        """
        fr = {str(k): float(v) for k, v in (frontier_m or {}).items()}
        bound = min((fr.get(k, 0.0) for k in EVIDENCE_REQUIRED_CATEGORIES), default=0.0)
        new = replace(
            self,
            evidence_radius_m=bound,
            evidence_frontier_m=fr,
            evidence_complete=bool(complete),
            evidence_detail=dict(detail or {}),
        )
        new.invariant()
        return new

    # ── 校验 ────────────────────────────────────────────────
    def invariant(self) -> None:
        """三概念 × 两时刻关系的机器校验（构造后即调，写错就报错而不是画出一张 29km² 的灰方框）。"""
        if self.reach_circumradius_m <= 0:
            raise ValueError("可达区外接圆半径必须为正")
        if self.collect_radius_m < self.reach_circumradius_m + EVIDENCE_MARGIN_M - 1e-6:
            raise ValueError(
                f"采集半径 {self.collect_radius_m:.0f}m < 可达区外接圆 "
                f"{self.reach_circumradius_m:.0f}m + 判定半径 {EVIDENCE_MARGIN_M:.0f}m —— "
                "D2（余量 0）已废止：余量由证据需求导出，不是可填的名义值。"
                "可达区外沿的格其 1km 圆伸出采集区 ⇒ 那些格只能标 unknown，"
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

    def judge_radius_m(self, radius_m: float = BLIND_RADIUS_M) -> float:
        """可判定半径：圆心到「`radius_m` 圆仍被证据边界完整覆盖」的最远距离。

        = 证据边界 − 判定半径。可达区内超出该半径的格**不判盲**（数据不足以支撑结论）。

        本方法从消费方（旧 `blindspot.judge_radius_m`）上移到值对象：它是「三概念之间的
        关系」，按本文件头的主张（关系做成构造即校验）本就该长在这里 —— 住在消费方时，
        任何新判定都得自己抄一遍这条公式，而抄错没有任何一层能发现。
        """
        return max(0.0, self.evidence_bound_m - float(radius_m))

    def triad_judge_radius_m(
        self, category: str, radius_m: float = BLIND_RADIUS_M
    ) -> float:
        """逐类可判定半径：该类的实测证据边界 − 判定半径。

        为什么必须逐类：一个点判盲要求**三类**各自的 1km 圆都查全。药店稠密到一页查不完
        （凯里实测 60 家 / 单页上限 20），菜市场与小学却一页就穷尽 ⇒ 三类的边界天然不同。
        用单一几何半径判，等于让最稠密那一类的证据缺口，去替最稀疏那一类下结论。
        """
        if self.evidence_radius_m is None:
            bound = float(self.collect_radius_m)      # 未绑定 ⇒ 与 judge_radius_m 同源退回
        else:
            bound = float(self.evidence_frontier_m.get(category, 0.0))
        return max(0.0, bound - float(radius_m))

    # ── 举证 ────────────────────────────────────────────────
    def payload(self, caliber: ReachCaliber, blind_stats: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """报告顶层 ``caliber`` 举证对象（口径 + 几何 + 判盲覆盖度）。

        ``cells_unknown`` 是**可观测性出口**：采集半径若算错，读数会上升（可见、可诊断），
        而不是让盲区悄悄膨胀成整张网格。
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
            # `collect ≈ circumradius + collect_margin` 恒等式读它）；值现在是**导出量**。
            "collect_margin_m": round(float(EVIDENCE_MARGIN_M), 1),
            # ── 事后举证相：「实际查到哪儿」与「请求了多大」并列可查 ──
            "evidence_margin_m": round(float(EVIDENCE_MARGIN_M), 1),
            "evidence_radius_m": (
                None if self.evidence_radius_m is None else round(self.evidence_radius_m, 1)
            ),
            "evidence_frontier_m": {
                k: round(v, 1) for k, v in sorted(self.evidence_frontier_m.items())
            },
            "evidence_complete": bool(self.evidence_complete),
            "evidence_bound_source": self.evidence_bound_source,
            "judge_radius_m": round(self.judge_radius_m(), 1),
            # 两种「没查全」是**不同的缺陷**，不得合并成一个键：
            #   truncated = 发了请求但被单页上限截断（边界外仍有设施，只是没拿到）
            #   starved   = 预算拒绝，一次请求都没发（连边界都没有）
            # 混成一个词，「截断」就会被稀释成噪声 —— 与 `poi.truncated`（展示上限）
            # 刻意不复用同一个词是同一纪律。
            "evidence_truncated_terms": list(self.evidence_detail.get("truncated_terms") or []),
            "evidence_starved_terms": list(self.evidence_detail.get("starved_terms") or []),
            # 口径版本：复用门（`report_contract.reuse_policy`）与契约判据据此判别
            # 「这份报告是不是本次这一套口径的产物」。写侧只有这一处发射点。
            "scope_policy_version": SCOPE_POLICY_VERSION,
        }
        if blind_stats is not None:
            out.update({k: int(v) for k, v in blind_stats.items()})
        return out


__all__ = [
    "BLIND_RADIUS_M",
    "EVIDENCE_MARGIN_M",
    "EVIDENCE_REQUIRED_CATEGORIES",
    "SCOPE_POLICY_VERSION",
    "SpatialScope",
    "TRIAD_KEYS",
    "TRIAD_LABEL",
]
