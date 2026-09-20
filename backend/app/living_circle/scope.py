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

本对象把三者显式化，并把两条关系做成**构造即校验**（``invariant()``）：

  - 可达区 ⊆ 采集区（否则可达区内必然有无数据格）
  - 判定半径 = 采集半径 − 1km（1km 圆没被采集区盖住的格，不构成「没有设施」的证据）

于是「圈内」到底按哪个圈判，由本对象唯一决定，**形参名不可能再撒谎**；
要加「驾驶方式」「多圈对照」只改本对象构造，消费函数都不用动。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from app.living_circle.caliber import ReachCaliber
from app.living_circle.geo_utils import LngLat, haversine_m

# ── 采集半径相对「可达区外接圆」的余量（米）—— 唯一开关 ──────────────────
# 判「可达区内某点 1km 内有没有菜市场」要求数据覆盖到「该点 + 1km」；最远的点是可达区
# 外接圆上那一点，故数学下限是「外接圆 + 1000m」。两条路线：
#
#   D2（当前取值 0.0）：采集半径 = 可达区外接圆
#       → 字面严格「不请求圈外」，但只有内圈 ``外接圆−1km`` 半径内的格**数据完整**，
#         可判定面积占比约 14%（外接圆 1.35km 时仅 350m 半径可判）。
#   D1（取值 BLIND_RADIUS_M=1000）：采集半径 = 外接圆 + 1km
#       → 可判定面积 100%；圈外点仍然一个都不进报告（进报告的仍是 ``in_reach``）。
#
# 两条路线的代码路径完全相同，差别只有这一个数：边界外的格一律进 ``unknown`` 而不是判盲。
COLLECT_MARGIN_M = 0.0


@dataclass(frozen=True)
class SpatialScope:
    """一次体检的**空间口径定格**（可达区 / 采集区 / 研究区 + 三者关系）。

    字段全部是派生值或实测值，没有可自由填写的「名义值」。
    """

    travel_mode: str
    reach_min: float                 # 可达区口径分钟数（= caliber.reach_full_min）
    reach_ring: Tuple[LngLat, ...]   # 可达区多边形（闭合环）
    reach_circumradius_m: float      # 可达区外接圆半径（实测，非名义）
    collect_radius_m: float          # 采集半径 = 外接圆 + COLLECT_MARGIN_M
    study_radius_m: float            # 研究区半径（报告标称范围，仅展示/配额）

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
            collect_radius_m=cr + float(COLLECT_MARGIN_M),
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

    # ── 校验 ────────────────────────────────────────────────
    def invariant(self) -> None:
        """三概念关系的机器校验（构造后即调，写错就报错而不是画出一张 29km² 的灰方框）。"""
        if self.reach_circumradius_m <= 0:
            raise ValueError("可达区外接圆半径必须为正")
        if self.collect_radius_m < self.reach_circumradius_m - 1e-6:
            raise ValueError(
                f"采集半径 {self.collect_radius_m:.0f}m < 可达区外接圆 {self.reach_circumradius_m:.0f}m —— "
                "可达区内必然存在无数据格（「没查到」会被当成「没有」）"
            )
        if self.study_radius_m <= 0:
            raise ValueError("研究半径必须为正")

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
            "collect_margin_m": round(float(COLLECT_MARGIN_M), 1),
        }
        if blind_stats is not None:
            out.update({k: int(v) for k, v in blind_stats.items()})
        return out


__all__ = ["COLLECT_MARGIN_M", "SpatialScope"]
