"""体检报告的**几何契约**（跨层共用：执行引擎 + 读路径 + 体检脚本 + 测试）。

## 一个契约，四处消费，零处复刻

「这份报告算不算数」是**业务契约**，不是某一段代码的局部实现细节。它有四个消费者，
分处三层：

- **写路径**：``core/pipeline/living_circle.py`` 落库前判定 → 不合格就置 ``failed``，
  绝不签发。
- **读路径**：``core/db.py:list_living_circle_reports`` 列表时跳过存量不合规项
  （历史脏数据仍需隐藏，否则前端列表会展示「0 分 / 1 处盲区」「29km² 灰方框」这类
  误导性结论）。
- **体检脚本**：``scripts/lc_healthcheck.py`` 逐条列出违规原因（人工可读）。
- **测试**：``tests/test_report_contract.py`` 钉住本模块自身的判别力。

四条路径若各自写一份判据，必然漂移 —— 写路径收紧了、读路径还按老口径放行，
于是"修好的"系统依旧在列表里漏出坏数据。故判据只此一处。

## 两级判据（**不要合并**，语义不同）

**Tier A · 硬缺失**（``missing``）—— 报告内容缺件，不成立：

1. ``isochrones`` 为空 ⇒ 没有可达区，生活圈无从谈起（P6 静默空壳报告）
2. ``data_origin == 'live'`` 且 ``poi.points`` 为空 ⇒ 等级评分没有输入，分数无意义

> ``offline`` 的空白是**有意降级**（P0-2：无网络时只出骨架，UI 如实标注「离线估算 · 未联网采集 POI」），
> 故 ``offline`` **豁免** Tier A 的第 1 条 —— 否则读路径会把「诚实的离线骨架」和「静默的空壳」一起隐藏，
> 而这两者恰好靠 ``data_origin`` 就能区分。``fixture`` / ``fixture_sample`` 声称的是一次完整体检，
> 没有等时圈同样是空壳，**不豁免**。

**Tier B · 几何自洽**（``violations``）—— 内容齐了但**自相矛盾**，是 Q1/Q2 的复发信号：

| 判据 | 对应缺陷 | 修复前实测 |
|---|---|---|
| 盲区最远点 ⊆ 可达区外接圆 | Q1：判定网格铺满研究区 | 2900m vs 1249m ❌ |
| Σ盲区面积 ≤ 可达区面积 × 2 | Q1：整片判盲 | 29.12 vs 3.23 ❌ |
| 点位 ``in_circle=True`` 者 ⊆ 外接圆 | Q2：圈外点混入 | 大量越界 ❌ |
| 送达点位不含 ``in_circle=False`` | Q2：圈外点进了报告 | 151 中 133 圈外 ❌ |
| live 报告声明 ``caliber.reach_full_min`` / ``collect_radius_m`` | 口径不可举证 | 7/7 份缺失 ❌ |
| ``collect_radius_m ≥ reach 外接圆`` | 采集区盖不住可达区 | 未声明 ❌ |

## 设计纪律：**判不了 ≠ 违规**

Tier B 的每条判据都要求相应输入齐备（``scene.center``、``geojson.coordinates``、
``poi.points[].in_circle``…）。**输入不足时一律跳过该条，不判违规** —— 与
``SpatialScope.unknown_mask`` 同一哲学：缺数据是「不知道」，不是「有罪」。
否则一个字段命名变化就会让全库报告集体消失（假阳性比漏报更难排查）。

## 为什么「陈旧快照」不需要新增 schema

``fixture_sample`` 的 3 份老快照几何来自旧版夹具（4 个完美 2km 方格），必然违反
Tier B 的「盲区 ⊆ 可达区」；7 份旧算法 live 报告必然缺 ``caliber``。**陈旧是几何的
派生属性，不是一列状态位** —— 所以「标记 stale」= 读路径按本契约隐藏 + 体检脚本
给出原因，零 schema 迁移、零回填脚本、且下次算法再变时自动继续生效。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.living_circle.geo_utils import LngLat, haversine_m, ring_area_km2, to_local_xy

# ── 阈值：唯一取值处 ─────────────────────────────────────────────
# 外接圆容差：环是多边形逼近，顶点理论上已在圆上，只留浮点/四舍五入余量
GEOM_TOL = 1.02
# Σ盲区面积相对可达区面积的上限倍数
BLINDSPOT_AREA_RATIO_MAX = 2.0

# 盲区严重度合法取值（与 blindspot._severity_of 对齐）
_VALID_SEVERITY: Tuple[str, ...] = ("heavy", "medium", "light")

# Tier A 口径：live 报告的必填几何项（(字段路径, 缺失时的中文描述)）
_LIVE_REQUIRED: Tuple[Tuple[Any, str], ...] = (
    ("isochrones", "路网等时圈数据"),
    (("poi", "points"), "设施点位数据（POI）"),
)


# ── 内部取值工具 ────────────────────────────────────────────────
def _dig(data: Dict[str, Any], path: Any):
    """按「字符串或路径元组」取值（路径元组支持取嵌套字段）。"""
    if isinstance(path, str):
        return data.get(path)
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _center(lc: Dict[str, Any]) -> Optional[LngLat]:
    """取场景中心点；**值域校验**后才返回（墨卡托米不得参与几何判定）。"""
    c = (lc.get("scene") or {}).get("center")
    if not isinstance(c, (list, tuple)) or len(c) != 2:
        return None
    try:
        lng, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        return None
    if abs(lng) > 180.0 or abs(lat) > 90.0:
        return None
    return (lng, lat)


def _ring(zone: Any) -> Optional[List[LngLat]]:
    """从等时圈/盲区对象里取闭合环；取不到返回 ``None``（→ 跳过相关判据）。"""
    if not isinstance(zone, dict):
        return None
    coords = ((zone.get("geojson") or {}).get("coordinates")) or None
    if not isinstance(coords, list) or not coords:
        # 盲区用的是 ``polygon`` 键（与等时圈不同）—— 两个键都认
        coords = ((zone.get("polygon") or {}).get("coordinates")) or None
    if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
        return None
    pts: List[LngLat] = []
    for p in coords[0]:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        try:
            pts.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError):
            return None
    return pts if len(pts) >= 3 else None


def _reach_zone(lc: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """按**口径**取可达区环 → ``(环, 违规描述)``（不是按位置取 ``[-1]``）。

    口径唯一来源：``caliber.reach_full_min``。旧报告缺该字段时退化为
    ``max(minutes)``（兼容存量），此时不产生违规 —— 责任在「缺口径声明」那条判据。
    """
    iso = lc.get("isochrones")
    if not isinstance(iso, list) or not iso:
        return None, None
    zones = [z for z in iso if isinstance(z, dict) and z.get("minutes") is not None]
    if not zones:
        return None, None
    target = (lc.get("caliber") or {}).get("reach_full_min")
    if target is None:
        return max(zones, key=lambda z: float(z["minutes"])), None
    try:
        t = float(target)
    except (TypeError, ValueError):
        return max(zones, key=lambda z: float(z["minutes"])), None
    matches = [z for z in zones if abs(float(z["minutes"]) - t) < 1e-9]
    if not matches:
        have = sorted(float(z["minutes"]) for z in zones)
        return None, (
            f"可达区口径 minutes={t:g} 在等时圈族里不存在（实有 {have}）—— 口径与数据不一致"
        )
    return matches[0], None


def _circumradius(center: LngLat, ring: Sequence[LngLat]) -> float:
    return max(haversine_m(center, p) for p in ring)


def _max_abs_offset(center: LngLat, ring: Sequence[LngLat]) -> float:
    """环上所有点相对中心的最大单轴偏移（米）—— 「bbox 是否越出可达区」的度量。"""
    m = 0.0
    for lng, lat in ring:
        x, y = to_local_xy(center, lng, lat)
        m = max(m, abs(x), abs(y))
    return m


# ── 契约结果 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class GeometryIssues:
    """一份报告的几何契约体检结论。"""

    missing: Tuple[str, ...] = ()
    violations: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """是否可作为用户可见的正式报告。"""
        return not self.missing and not self.violations

    @property
    def reason(self) -> str:
        """人话原因（空字符串 = 合规），供日志/体检脚本留痕。"""
        parts: List[str] = []
        if self.missing:
            parts.append("内容缺件：" + "、".join(self.missing))
        if self.violations:
            parts.append("几何不自洽：" + "；".join(self.violations))
        return " / ".join(parts)


# ── Tier A：硬缺失（写路径据此置 failed）────────────────────────
def live_geometry_deficiency(lc: Dict[str, Any]) -> Optional[str]:
    """live 报告的几何缺失检查 → 缺失项中文描述（完整则 ``None``）。

    :param lc: ``LivingCircleReport`` 载荷本身（即报告里的 ``living_circle`` 节点），
               不是外层 ``Report``。写路径传 ``assemble_living_circle`` 的返回值，
               读路径传 ``data["living_circle"]`` —— 两者是同一结构。

    **语义边界**：只查「内容缺件」，不做几何自洽判定 —— 后者见
    :func:`assess_geometry`。写路径对两者都要求合格（缺件 → ``failed``，
    不自洽 → 同样不签发），故写路径调 :func:`assess_geometry` 即可；
    本函数保留是因为「缺件」需要一个**稳定、可参数化**的最小谓词。
    """
    if not isinstance(lc, dict) or (lc.get("data_origin") or "") != "live":
        return None
    for path, label in _LIVE_REQUIRED:
        if not _dig(lc, path):
            return label
    return None


def is_incomplete_live(lc: Dict[str, Any]) -> bool:
    """Tier A 的 live 谓词（**仅供兼容/测试**）。

    读路径**不要**用它 —— 它只查「内容缺件」，放得过几何不自洽的报告（Q1/Q2 那类）。
    要问「这份报告能不能给用户看」，用 :func:`report_is_presentable`。
    """
    return live_geometry_deficiency(lc) is not None


# ── Tier A + Tier B：完整几何契约 ───────────────────────────────
def assess_geometry(lc: Dict[str, Any]) -> GeometryIssues:
    """报告的**完整**几何契约体检 → :class:`GeometryIssues`。

    纯函数、不抛异常、不依赖 DB；输入不足的判据自动跳过（判不了 ≠ 违规）。
    """
    if not isinstance(lc, dict) or not lc:
        return GeometryIssues(missing=("报告载荷为空（living_circle 节点缺失）",))

    origin = lc.get("data_origin") or ""
    offline = origin == "offline"      # 有意降级：只出骨架，UI 已标注 → 豁免 Tier A 第 1 条

    missing: List[str] = []
    if not offline and not lc.get("isochrones"):
        missing.append("路网等时圈数据")
    if origin == "live" and not _dig(lc, ("poi", "points")):
        missing.append("设施点位数据（POI）")
    if missing:
        # 内容缺件时几何判据无意义（没有可达区就没有参照系），直接返回
        return GeometryIssues(missing=tuple(missing))

    violations: List[str] = []
    center = _center(lc)

    # B0 · 口径可举证性（live 必填；非 live 的旧夹具走「判不了即跳过」）
    caliber = lc.get("caliber") or {}
    if origin == "live":
        if "reach_full_min" not in caliber:
            violations.append("未声明可达区口径 caliber.reach_full_min（可达区无法被唯一确定）")
        if "collect_radius_m" not in caliber:
            violations.append("未声明采集半径 caliber.collect_radius_m（采集区关系不可举证）")

    if center is None:
        # 中心点不可用 ⇒ 一切「距中心」判据都判不了（不判违规）
        return GeometryIssues(violations=tuple(violations))

    reach, reach_err = _reach_zone(lc)
    if reach_err:
        violations.append(reach_err)
    reach_ring = _ring(reach) if reach else None
    if reach_ring is None:
        return GeometryIssues(violations=tuple(violations))

    cr = _circumradius(center, reach_ring)

    # B6 · 采集半径必须盖住可达区（否则可达区内必然有无数据格）
    if "collect_radius_m" in caliber:
        try:
            collect = float(caliber["collect_radius_m"])
        except (TypeError, ValueError):
            collect = None
        if collect is not None and collect < cr * 0.999:
            violations.append(
                f"采集半径 {collect:.0f}m < 可达区外接圆 {cr:.0f}m（可达区内存在无数据格）"
            )

    # B1/B2 · 盲区必须被可达区裁住（Q1 核心判据）
    blindspots = lc.get("blindspots")
    if isinstance(blindspots, list) and blindspots:
        reach_area = ring_area_km2(reach_ring, center)
        total = 0.0
        worst = 0.0
        worst_id = None
        for b in blindspots:
            ring = _ring(b)
            if ring is None:
                continue
            got = _max_abs_offset(center, ring)
            if got > worst:
                worst, worst_id = got, (b.get("id") if isinstance(b, dict) else None)
            total += ring_area_km2(ring, center)
        if worst > cr * GEOM_TOL:
            violations.append(
                f"盲区 {worst_id} 最远点 {worst:.0f}m 越出可达区外接圆 {cr:.0f}m"
                f"（判定网格未按可达区限定 —— Q1 本体）"
            )
        if total > reach_area * BLINDSPOT_AREA_RATIO_MAX:
            violations.append(
                f"盲区总面积 {total:.3f}km² > 可达区面积 {reach_area:.3f}km² × "
                f"{BLINDSPOT_AREA_RATIO_MAX:g}（整片判盲/网格越界）"
            )

    # B7 · 盲区语义硬判据（表征有效性：severity/gap 校验、fixes 优先级唯一连续、affected 诚实代理）
    if isinstance(blindspots, list):
        seen_priorities: set = set()
        for b in blindspots:
            if not isinstance(b, dict):
                continue
            sev = b.get("severity")
            if sev is not None and sev not in _VALID_SEVERITY:
                violations.append(f"盲区 {b.get('id')} severity={sev!r} 非 {{heavy,medium,light}}")
            gap = b.get("gap_score")
            if gap is not None and not (isinstance(gap, (int, float)) and 0.0 <= float(gap) <= 1.0):
                violations.append(f"盲区 {b.get('id')} gap_score={gap!r} 超出 [0,1]")
            for f in b.get("fixes") or []:
                if not isinstance(f, dict):
                    continue
                pri = f.get("priority")
                if not isinstance(pri, int) or pri < 1 or pri in seen_priorities:
                    violations.append(
                        f"盲区 {b.get('id')} fixes priority 非正整数或重复（{pri!r}）"
                    )
                elif pri:
                    seen_priorities.add(pri)
            affected = b.get("affected")
            if affected is not None:
                if not isinstance(affected, dict) or affected.get("provenance") != "proxy":
                    violations.append(f"盲区 {b.get('id')} affected 缺诚实 provenance=proxy")
                sites = (affected or {}).get("sampling_sites")
                if sites is not None and (not isinstance(sites, int) or sites < 0):
                    violations.append(f"盲区 {b.get('id')} sampling_sites 非法（{sites!r}）")

    # B3/B4 · 送达点位必须全部落在可达区内（Q2 核心判据）
    points = _dig(lc, ("poi", "points"))
    if isinstance(points, list) and points:
        out_of_ring = 0
        not_in_circle = 0
        first_out: Optional[str] = None
        for pt in points:
            if not isinstance(pt, dict):
                continue
            if pt.get("in_circle") is False:
                # 圈外点被送进报告 = Q2 本体（判据只看标记，与几何无关）
                not_in_circle += 1
                continue
            if pt.get("in_circle") is not True:
                continue  # 无标记 ⇒ 判不了几何，跳过
            lnglat = pt.get("lnglat") or [pt.get("lng"), pt.get("lat")]
            if not isinstance(lnglat, (list, tuple)) or len(lnglat) < 2:
                continue
            try:
                p = (float(lnglat[0]), float(lnglat[1]))
            except (TypeError, ValueError):
                continue
            if haversine_m(center, p) > cr * GEOM_TOL:
                out_of_ring += 1
                if first_out is None:
                    first_out = str(pt.get("name") or pt.get("id") or "?")
        if not_in_circle:
            violations.append(
                f"{not_in_circle} 个点位 in_circle=False 却被送进报告（圈外点不应展示、不应计分）"
            )
        if out_of_ring:
            violations.append(
                f"{out_of_ring} 个点位标记 in_circle=True 却越出可达区外接圆 {cr:.0f}m"
                f"（首个：{first_out}）"
            )

    return GeometryIssues(violations=tuple(violations))


def report_is_presentable(lc: Dict[str, Any]) -> bool:
    """读路径谓词：这份报告是否可以出现在用户可见列表里。"""
    return assess_geometry(lc).ok


def staleness_reason(lc: Dict[str, Any]) -> Optional[str]:
    """报告不可展示的原因（可展示则 ``None``）—— 审计/日志用。

    「陈旧」在本设计里不是一列状态位，而是**几何契约的派生结论**：
    老夹具快照违反「盲区 ⊆ 可达区」，旧算法 live 报告缺口径声明，两者都会在这里现形。
    """
    issues = assess_geometry(lc)
    return None if issues.ok else issues.reason


__all__ = [
    "BLINDSPOT_AREA_RATIO_MAX",
    "GEOM_TOL",
    "GeometryIssues",
    "assess_geometry",
    "is_incomplete_live",
    "live_geometry_deficiency",
    "report_is_presentable",
    "staleness_reason",
]
