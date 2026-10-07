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
| **B5** 证据域自洽：余量>0、``collect == 外接圆+余量``、实测边界 ≤ 请求、不得带缺口称完整 | 余量被改回 0 / 「没查完」被省略 | 余量 0 ⇒ 判盲面 5% ❌ |
| **B10** ``judge_radius == 证据边界 − 判定半径``（复算）、``judged==0 ⇒ unknown==inside`` | 判定域与证据脱钩 | 5/97 判却报「0 处盲区」❌ |
| **B11** 新产物必带 ``scores.confidence``；``share<1`` 或证据不齐 ⇒ 不得 full；``penalty_applied`` 可由公式复算 | 证据越少分越高 | 2 处盲区只扣 4 分 ❌ |
| **B13** 新产物必带 ``cells_ledger``；四张计数由台账复算、结论位由不对称规则重抄、``n``/``step_m``/``scan_m`` 由格阵复算 | 「哪一格凭什么这个结论」无法复原 | 环跨 16 格却只报 8 格 ❌ |

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

import math

from dataclasses import dataclass
from math import isfinite
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.living_circle.caliber import REACH_CALIBER_VERSION, get_caliber
from app.living_circle.category_rule import COVERAGE_CALIBER_VERSION
from app.living_circle.geo_utils import LngLat, haversine_m, ring_area_km2, to_local_xy
from app.living_circle.isochrone import interpolation_form_keys, shape_zone_keys, SHAPE_MINUTES
from app.living_circle.geo_utils import (
    SHAPE_AZIMUTH_FN,
    SHAPE_BIN_DEG,
    SHAPE_BIN_PHASE,
    SHAPE_ORIGIN,
    SHAPE_SCALAR_TOL,
    _DIRECTIONS,
)

# 可达档外接半径恒等式的复算容差（米）。**它是判据的容差，不是量出来的数**，所以留在契约层：
# 今天这条判据只在 `max(bins_m)` 与 `caliber.reach_circumradius_m` 差超 0.6m 时判「两个真源」，
# 而 0.6 这个数原先在判据与判据自己的用例里各写一份（收紧/放宽一次要改两处）。
# 已进口径名册（`report_contract::SHAPE_CIRCUMRADIUS_TOL_M`），用例改读它。
SHAPE_CIRCUMRADIUS_TOL_M = 0.6
# B13（逐格台账）要读写侧的字母表与格距常量 —— 从 `blindspot` 取，不在这里另定一套：
# 台账的三个字符 `1/0/.` 一旦有两份定义，读侧守卫就会在写侧改字母表的那天开始说谎。
# 依赖方向是 读侧守卫 → 判定模块，与既有 `scope.BLIND_RADIUS_M` 同一条，不构成环
# （`blindspot` 及其依赖 `geometry/field/geo_utils/grid/judgement/scope` 都不指回本模块）。
from app.living_circle.blindspot import (
    BLIND_GRID_M,
    LEDGER_GRID,
    LEDGER_NO,
    LEDGER_SCHEMA_VERSION,
    LEDGER_UNKNOWN,
    LEDGER_YES,
)
from app.living_circle.grid import grid_spec
from app.living_circle.judgement import STAT_KEYS
from app.living_circle.scope import BLIND_RADIUS_M, SCOPE_POLICY_VERSION, TRIAD_KEYS
from app.living_circle.scoring import (
    BLINDSPOT_PENALTY_CAP,
    BLINDSPOT_PENALTY_PER_EXTRA,
    FULL_JUDGE_SHARE_TOL,
    JUDGE_SHARE_FLOOR,
)

# ── 阈值：唯一取值处 ─────────────────────────────────────────────
# 外接圆容差：环是多边形逼近，顶点理论上已在圆上，只留浮点/四舍五入余量
GEOM_TOL = 1.02
# Σ盲区面积相对可达区面积的上限倍数
BLINDSPOT_AREA_RATIO_MAX = 2.0
# B10 复算容差：`judge_radius_m` 与 `evidence_radius_m` 在 payload 里各保留 1 位小数
EVIDENCE_RECOMPUTE_TOL_M = 0.15
# B11 复算容差：`penalty_applied` 保留 1 位、`judged_share` 保留 4 位
PENALTY_RECOMPUTE_TOL = 0.1

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


def _num(v: Any) -> Optional[float]:
    """安全取浮点（缺失/脏值 ⇒ ``None`` = 判不了，而不是违规）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Tier B · 证据相五条（B5 / B10 / B11 / B12 / B13）───────────────────
def _evidence_phase_violations(lc: Dict[str, Any]) -> List[str]:
    """证据域自洽（B5）、判定域由证据域导出（B10）、扣分与判定面一致（B11）、
    逐锚点举证与标量边界同源（B12）、逐格台账与分账/规则/格阵对得上（B13）。

    这四条**只读 payload 数值**，不需要几何参照系 ⇒ 在 ``center is None`` 早退之前调用，
    否则「中心点缺失」会把这几条一起跳过，而它们看的是数字之间对不对得上。

    **门禁 = ``caliber.scope_policy_version``**：旧口径产物整套证据键都可能缺席，对它们
    一律「判不了即跳过」（否则存量报告集体被隐藏，正是本模块反复警告的假阳性）。
    反过来，声明了本版本的报告**必须**自带这些键 —— 版本号与键集是同一次发布的两半。

    公式在**本函数里重抄一遍**，不 import ``scoring._blindspot_penalty``：两侧同源时
    「把扣分改回只按条数」会同步漂移、判据形同虚设。只有独立复算才拦得住回退
    （与本文件「判据只此一处」不矛盾：那条讲的是**同一判据的四处消费**，这里讲的是
    写侧与其读侧守卫必须是两份实现）。
    """
    cal = lc.get("caliber")
    if not isinstance(cal, dict) or cal.get("scope_policy_version") != SCOPE_POLICY_VERSION:
        return []

    out: List[str] = []
    margin = _num(cal.get("evidence_margin_m"))
    circum = _num(cal.get("reach_circumradius_m"))
    collect = _num(cal.get("collect_radius_m"))
    ev_radius = _num(cal.get("evidence_radius_m"))
    judge = _num(cal.get("judge_radius_m"))
    source = cal.get("evidence_bound_source")
    complete = cal.get("evidence_complete")
    inside, judged, unknown, capped = (_num(cal.get(k)) for k in (
        "cells_inside", "cells_judged", "cells_unknown", "cells_unjudgeable_by_cap"))

    # B5 · 证据相的键必须齐（版本号与键集同批发布，缺一即无从举证）
    absent = [
        k
        for k in ("evidence_margin_m", "evidence_frontier_m", "evidence_complete",
                  "evidence_bound_source", "judge_radius_m")
        if k not in cal
    ]
    if absent:
        out.append(
            f"声明了 scope_policy_version={SCOPE_POLICY_VERSION} 却缺 {absent}"
            " —— 新产物必须自带证据相举证"
        )

    # B5 · 余量是导出量，不是可填的名义值（拦 D2「余量 0」回退）
    if margin is not None and margin <= 0:
        out.append(
            f"证据余量 {margin:g}m ≤ 0 —— D2（余量 0）已废止：采集余量由「判盲需要 1km 完整证据」"
            "导出，取 0 会把可达区外沿全部退化成判不了"
        )
    if None not in (circum, collect, margin) and abs(collect - (circum + margin)) > EVIDENCE_RECOMPUTE_TOL_M:
        out.append(
            f"采集半径 {collect:.0f}m ≠ 可达区外接圆 {circum:.0f}m + 证据余量 {margin:.0f}m"
            " —— 采集区不再是证据需求的导出值"
        )

    # B5 · 「实际查到哪儿」不得大于「请求了哪儿」，也不许带着缺口自称完整
    if source == "measured" and ev_radius is not None and collect is not None:
        if ev_radius > collect + EVIDENCE_RECOMPUTE_TOL_M:
            out.append(
                f"实测证据边界 {ev_radius:.0f}m > 请求半径 {collect:.0f}m —— 实测不可能大于请求，"
                "绑定顺序或换算有误"
            )
        if complete is True and ev_radius < collect - EVIDENCE_RECOMPUTE_TOL_M:
            out.append(
                f"声称证据完整（evidence_complete=true）却只查到 {ev_radius:.0f}m < 请求 "
                f"{collect:.0f}m —— 有词被截断/饿死/熔断时不得称完整"
            )

    # B10 · 判定域必须由证据域导出（复算，不接受「名义上判满了」）
    # ⚠️ 半径在这里仍是**兼容名**（`scope.BLIND_RADIUS_M` = walking 档快照），不是本次判定
    # 实际吃的那把尺 —— 复算拿不到 `Judgement.radius_m`（`assess_geometry` 只吃落库 dict，
    # 而 dict 里没有承载"本次尺"的顶层键）。住所在 `caliber.ReachCaliber.blind_radius_m`
    # 之后，这条读侧就是**第二把尺**：今天三档同值 ⇒ 无差异；一旦分档，riding/driving 的报告
    # 会被这条按 1000m 误判。修法属批次二（改读产物自己声明的半径，存量件需回落规则），
    # 由 `test_b10_reads_the_constant_not_this_runs_ruler` 成对钉住（计划 v6.9 ⑧″）。
    bound = ev_radius if (source == "measured" and ev_radius is not None) else collect
    if judge is not None and bound is not None:
        expected_judge = max(0.0, bound - BLIND_RADIUS_M)
        if abs(judge - expected_judge) > EVIDENCE_RECOMPUTE_TOL_M:
            out.append(
                f"judge_radius_m {judge:.1f}m ≠ 证据边界 {bound:.0f}m − 判定半径 "
                f"{BLIND_RADIUS_M:.0f}m（复算 {expected_judge:.1f}m）—— 判定域不再由证据域导出"
            )
    # B12 · 逐锚点明细与逐类标量边界必须由**同一批盘**导出（计划 v5.9 前置②）
    # 写侧有一条守卫（`SpatialScope._one_region_source`：显式 region 与绑定 region 不许是两个
    # 对象），但那守卫只在「经过值对象」时生效。落库件是 JSON，拼得出「明细来自回合区域、标量
    # 却来自首轮绑定」的形状 —— 而接线后的取证回合恰好就会同时持有这两块。
    # ⚠️ 期望值写成**区间包含**而不是「等于 max」：同一批盘有两种合法塌缩 —— 采集器逐类取
    # **min**（`poi_collector.frontier_m`，保守合取：一个词被截断该类边界就只到那儿），
    # 区域视图取 **max**（`EvidenceRegion.frontier_m`，向后兼容既有键）。第五轮复审 P0-2 证明
    # 「等于 max」会把生产自己的标量绑定判成违规（market 三个词 ⇒ min 1500 / max 4535 是常态），
    # 那等于替批次二预定标量语义。区间外的值只可能来自**另一批盘** ⇒ 那才是要拦的形状。
    # 键缺席 ⇒ 判不了即跳过（存量 27 份报告没有 `evidence_anchors`，本条对它们恒不触发）。
    anchors = cal.get("evidence_anchors")
    if isinstance(anchors, list) and anchors:
        front = cal.get("evidence_frontier_m")
        front = front if isinstance(front, dict) else {}
        spans: Dict[str, List[float]] = {}
        for row in anchors:
            if not isinstance(row, dict):
                continue
            depth = _num(row.get("exhausted_radius_m"))
            if depth is not None:
                spans.setdefault(str(row.get("category")), []).append(depth)
        for cat, depths in sorted(spans.items()):
            if cat not in front:
                out.append(
                    f"{cat} 有逐锚点举证（{len(depths)} 块盘）却缺 `evidence_frontier_m` 条目 "
                    "—— 明细与标量视图不是同一块区域塌出来的"
                )
                continue
            got = _num(front.get(cat))
            lo, hi = min(depths), max(depths)
            if got is None or not (lo - EVIDENCE_RECOMPUTE_TOL_M <= got <= hi + EVIDENCE_RECOMPUTE_TOL_M):
                out.append(
                    f"evidence_frontier_m[{cat}]={front.get(cat)!r} 落在该锚点明细的深度区间 "
                    f"[{lo:.0f}, {hi:.0f}]m 之外 —— 举证与判定吃的不是同一批盘"
                    f"（两种合法塌缩 min/max 都在区间内，区间外只能来自另一批证据）"
                )

    if None not in (inside, judged, unknown):
        # P1-5：判定面有**三态**之后（阶段 3-f 把「接口自有上限」从「我们没查」里分出来），
        # 分账恒等式是 `inside = judged + unknown + unjudgeable_by_cap`。这一支原本按两态算
        # （`unknown != inside`），于是一份自洽的纯封顶报告（一格没判成、缺口全记在第三态）
        # 会被判成「判不了被当成不盲」而**不予签发** —— 指控恰好说反了。
        # ⚠️ 第三态缺席（旧 ev-2 件没这键）按 `0` 算：那时确实没有格被记为封顶，
        # 判定与两态时代逐字相同，不是新造一条放行面（对比 R23-I 那条"发射侧不许把不知道写成 0"——
        # 那里是把未知量落成数字，这里是门禁复算一个恒等式，缺声明就是"这一位没有格"）。
        accounted = unknown + (capped or 0.0)
        gap = inside - accounted
        if judged == 0 and gap != 0:
            out.append(
                f"一格未判（cells_judged=0）而「未定 {unknown:g} 格 + 接口封顶 {capped or 0:g} 格」"
                f"对不上可达区 {inside:g} 格（差 {abs(gap):g} 格既没判也没记）—— "
                "「判不了」被当成「不盲」"
            )
        if judged is not None and judge is not None and judge <= 0.0 and judged > 1:
            out.append(
                f"判定半径 0m 时最多只有中心一格可判，实测 cells_judged={judged:g} —— "
                "judged 掩码已退化为只看几何"
            )

    # B11 · 扣分口径与判定面一致（且新产物必带置信度）
    scores = lc.get("scores")
    scores = scores if isinstance(scores, dict) else {}
    conf = scores.get("confidence")
    if conf is None:
        out.append(
            f"声明 scope_policy_version={SCOPE_POLICY_VERSION} 的报告缺 scores.confidence"
            " —— 新产物必须自带置信度"
        )
    ev_block = scores.get("evidence")
    ev_block = ev_block if isinstance(ev_block, dict) else {}

    share: Optional[float] = None
    if inside and judged is not None and inside > 0:
        share = judged / inside
    if share is not None and "judged_share" in ev_block:
        declared_share = _num(ev_block.get("judged_share"))
        if declared_share is None or abs(declared_share - share) > 1e-3:
            out.append(
                f"scores.evidence.judged_share={ev_block.get('judged_share')!r} 与 caliber 分账"
                f"推出的 {share:.4f} 不符 —— 评分读到的判定面与报告声明的不是同一个"
            )
    if share is not None and conf == "full" and share < 1.0 - FULL_JUDGE_SHARE_TOL:
        out.append(f"判定覆盖率 {share:.1%} < 100% 却自称 confidence=full ——「没判的格」正在冒充「没问题」")
    if complete is False and conf == "full":
        out.append("evidence_complete=false（有词被截断/饿死/熔断）却自称 confidence=full")

    blindspots = lc.get("blindspots")
    if share is not None and isinstance(blindspots, list) and "penalty_applied" in ev_block:
        got = _num(ev_block.get("penalty_applied"))
        expected_pen = min(
            BLINDSPOT_PENALTY_CAP,
            max(0.0, len(blindspots) / max(min(share, 1.0), JUDGE_SHARE_FLOOR) - 1.0)
            * BLINDSPOT_PENALTY_PER_EXTRA,
        )
        if got is None or abs(got - expected_pen) > PENALTY_RECOMPUTE_TOL:
            out.append(
                f"scores.evidence.penalty_applied={ev_block.get('penalty_applied')!r} 无法由公式复算"
                f"（应为 {expected_pen:.1f}：实测 {len(blindspots)} 处 ÷ 覆盖率 {share:.1%}，"
                f"下限 {JUDGE_SHARE_FLOOR:g}、封顶 {BLINDSPOT_PENALTY_CAP:g}）—— 扣分口径被改回「只按条数」"
            )

    # B13 · 逐格台账（计划 cells-ledger-judge-scale §4.3）。
    # 门禁与上面几条同一条：`scope_policy_version == SCOPE_POLICY_VERSION` ⇒ **必须自带**。
    # 为什么这里不许"键缺席即跳过"（B12 对 `evidence_anchors` 那种写法）：版本号与键集是
    # 同一次发布的两半，"声明了 ev-2 却没发台账"正是本条要拦的形状 —— 而缺席跳过会让它
    # 永远查不出来。存量 ev-1 报告由上面第 264 行的版本门自动豁免，不会因此消失。
    ledger = cal.get("cells_ledger")
    if not isinstance(ledger, dict) or not ledger:
        out.append(
            f"声明了 scope_policy_version={SCOPE_POLICY_VERSION} 却缺 cells_ledger"
            " —— 逐格台账与新版本号是同一次发布的两半；缺它，读者复原不出「哪一格凭什么"
            "是这个结论」，而这条链三次被问的就是这件事"
        )
    else:
        out.extend(_cells_ledger_violations(cal, ledger))
        # 台账那把尺必须与**每条上屏盲区**声明的尺是同一把（两者同出 `Judgement.radius_m`）。
        # 上面几条查的是台账内部自洽，查不出"整张台账用了另一把尺"—— 而多模式分档后
        # `blind_radius_m` 不再恒为 1000，那一格写错的代价就是图上 800m 圆旁边标着 1km。
        lr = _num(ledger.get("radius_m"))
        for spot in (blindspots if isinstance(blindspots, list) else []):
            sr = _num(spot.get("radius_m")) if isinstance(spot, dict) else None
            if sr is not None and lr is not None and abs(sr - lr) > 1.0:
                out.append(
                    f"cells_ledger.radius_m={lr:g} ≠ 盲区 {spot.get('id')!r} 声明的 "
                    f"{sr:g} —— 台账与上屏结论吃的不是同一把尺"
                )
                break
    return out


#: 台账的字母表（与 `blindspot.LEDGER_YES/NO/UNKNOWN` 同一套，读侧不另定一套）。
LEDGER_CHARS = frozenset({"1", "0", "."})
#: `nearest.{类}` 的"无从知道"记号（与 `render_cells_ledger` 的渲染逐字对照）。
LEDGER_NO_DISTANCE = "-"


def _ledger_matrix(ledger: Dict[str, Any], key: str, n: int) -> Optional[List[str]]:
    """取台账的一张 ``n×n`` 字符矩阵；缺失/形状不符/字母表外 ⇒ ``None``（该条判不了）。

    ⚠️ 返回 ``None`` **不是**"跳过就算通过"：调用方必须把它变成一条违规。半截台账比没有台账
    更危险 —— 没有会被 B13 的"缺键即违规"拦住，半截若被跳过就等于当场放行一个错账。
    """
    rows = ledger.get(key)
    if not isinstance(rows, list) or len(rows) != n:
        return None
    for row in rows:
        if not isinstance(row, str) or len(row) != n or not set(row) <= LEDGER_CHARS:
            return None
    return list(rows)


def _ledger_distances(ledger: Dict[str, Any], key: str, n: int) -> Optional[List[List[Optional[float]]]]:
    """取一张最近距离表（空格分隔的 `n` 行，每格 `-` 或非负整数米）；不符 ⇒ ``None``。"""
    rows = ledger.get(key)
    if not isinstance(rows, list) or len(rows) != n:
        return None
    out: List[List[Optional[float]]] = []
    for row in rows:
        if not isinstance(row, str):
            return None
        toks = row.split(" ")
        if len(toks) != n:
            return None
        vals: List[Optional[float]] = []
        for tok in toks:
            if tok == LEDGER_NO_DISTANCE:
                vals.append(None)
                continue
            if not tok.isdigit():
                return None
            vals.append(float(int(tok)))
        out.append(vals)
    return out


def _cells_ledger_violations(cal: Dict[str, Any], ledger: Dict[str, Any]) -> List[str]:
    """B13 · 逐格台账与顶层分账、与不对称规则、与格阵必须三处都对得上。

    **效力上限（不写清就会被当成别的东西卖）**：台账与顶层计数**同源**（都出自同一次
    ``_verdict_masks``），所以本条防的是**渲染 / 截断 / 序列化**这一段的缺陷，
    不防"两处判定各算一遍" —— 后者由 γ 静态守卫 G-10（判定原语生产侧调用点计数）把守。
    B13 是兜底，G-10 才是阻止。

    但**不对称规则**这一半不是同义反复：结论（`blind`/`verdict`）与输入（`judge`/`present`）
    都在台账里，本函数按"判盲只需一类有据、说不盲要三类有据"**重抄一遍**再对表 —— 与 B11
    重抄扣分公式同理（写侧与读侧守卫必须是两份实现，否则规则被改回去时两边一起漂）。
    """
    out: List[str] = []
    n = ledger.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0 or n % 2 == 0:
        return [
            f"cells_ledger.n={n!r} 不是正的奇数 —— 判定格阵边长恒为奇数"
            "（分析中心必须恰好落在格心上，否则中心格被半格偏移污染）"
        ]
    if ledger.get("grid") != LEDGER_GRID:
        out.append(
            f"cells_ledger.grid={ledger.get('grid')!r} ≠ {LEDGER_GRID!r} —— 行字符串是方格专属"
            "表示法，换格制（如 H3）得连带换邻接关系，不许沿用同一 schema"
        )
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        out.append(
            f"cells_ledger.schema_version={ledger.get('schema_version')!r} ≠ "
            f"{LEDGER_SCHEMA_VERSION} —— 读侧与本函数的字母表/键名约定不是同一代"
        )
    radius = _num(ledger.get("radius_m"))
    if radius is None or radius <= 0:
        out.append(f"cells_ledger.radius_m={ledger.get('radius_m')!r} 不是正数米 —— 台账没带那把尺")

    # 格阵一致性排在矩阵校验**之前**：它只需要 `n` 与 `reach_circumradius_m`，不需要读格子。
    # 放在后面会让"n 被改错"这种变异先撞上形状不符、提前 return，报成"半截台账"而不是
    # "格阵不符" —— 失败种类被抢答，排查时会往错的方向走。
    # 复算走 `grid.grid_spec`（那套算术的唯一住所）而不是再抄一遍 ceil/linspace —— 抄的那份
    # 会在 `grid_m` 改动时先漂。center 只用于 `cell()`，n/step/scan 不读它 ⇒ 这里传零点是安全的。
    circum = _num(cal.get("reach_circumradius_m"))
    if circum is not None and circum > 0:
        spec = grid_spec((0.0, 0.0), circum, BLIND_GRID_M)
        if n != spec.n:
            out.append(
                f"cells_ledger.n={n} ≠ 由可达区外接圆 {circum:.0f}m 与格距 {BLIND_GRID_M:g}m "
                f"推出的 {spec.n} —— 台账不是这次判定那张格阵")
        for gkey, want in (("step_m", spec.step), ("scan_m", spec.scan)):
            got_g = _num(ledger.get(gkey))
            if got_g is None or abs(got_g - want) > 0.1:
                out.append(
                    f"cells_ledger.{gkey}={ledger.get(gkey)!r} ≠ 格阵复算 {want:.1f}m —— "
                    "格距一漂，两处的掩码就对不上（这正是 `JudgeMasks` 不许调用方重算格阵的理由）")
    else:
        out.append("caliber.reach_circumradius_m 缺失/非正 ⇒ 台账的格阵无从复算（B13 半边失效）")

    mats: Dict[str, Optional[List[str]]] = {
        name: _ledger_matrix(ledger, name, n)
        for name in ("inside", "capped", "blind", "verdict")
    }
    judge: Dict[str, Optional[List[str]]] = {
        k: _ledger_matrix(ledger, f"judge.{k}", n) for k in TRIAD_KEYS}
    present: Dict[str, Optional[List[str]]] = {
        k: _ledger_matrix(ledger, f"present.{k}", n) for k in TRIAD_KEYS}
    nearest: Dict[str, Optional[List[List[Optional[float]]]]] = {
        k: _ledger_distances(ledger, f"nearest.{k}", n) for k in TRIAD_KEYS}
    short = sorted(
        [name for name, m in mats.items() if m is None]
        + [f"{p}.{k}" for p, table in (("judge", judge), ("present", present), ("nearest", nearest))
           for k, m in table.items() if m is None]
    )
    if short:
        out.append(
            f"cells_ledger 有矩阵缺失或形状/字母不符（n={n}）：{short} —— "
            "半截台账比没有台账更危险，不许按『判不了即跳过』放行"
        )
        return out

    # 逐格：字母表纪律 + 不对称规则重抄 + 距离与三态同源
    rule_bad: List[str] = []
    state_bad: List[str] = []
    dist_bad: List[str] = []
    counts = dict.fromkeys(STAT_KEYS, 0)
    for i in range(n):
        for j in range(n):
            if mats["inside"][i][j] != LEDGER_YES:
                # 区外的格语义上不该判盲 ⇒ 四张结论位必须全是 `0`，逐类输入位必须全是 `.`。
                # 后半条不是洁癖：`judge.{类}` 是**几何事实**（盘盖没盖到那格的 1km 圆），
                # 区外也常为 `1`；若那里写出了 `0`/`1`，就是有人替从未求值的格编了结论。
                if any(m[i][j] != LEDGER_NO for m in (mats["capped"], mats["blind"], mats["verdict"])):
                    state_bad.append(f"({i},{j}) 区外却有结论位")
                if any(present[k][i][j] != LEDGER_UNKNOWN or nearest[k][i][j] is not None
                       for k in TRIAD_KEYS):
                    state_bad.append(f"({i},{j}) 区外却写了逐类结论/距离")
                continue
            counts["cells_inside"] += 1
            asked = [k for k in TRIAD_KEYS if judge[k][i][j] == LEDGER_YES]
            for k in TRIAD_KEYS:
                ch = present[k][i][j]
                if judge[k][i][j] == LEDGER_NO and ch != LEDGER_UNKNOWN:
                    state_bad.append(f"({i},{j}) {k} judge=0 却写了 present={ch}")
                if judge[k][i][j] == LEDGER_YES and ch == LEDGER_UNKNOWN:
                    state_bad.append(f"({i},{j}) {k} judge=1 却写 present=.（有据却没结论）")
                got_d = nearest[k][i][j]
                if ch == LEDGER_UNKNOWN and got_d is not None:
                    state_bad.append(f"({i},{j}) {k} 无从知道却带距离 {got_d:g}m")
                if ch == LEDGER_YES and (got_d is None or (radius is not None and got_d > radius + 1.0)):
                    dist_bad.append(f"({i},{j}) {k} 命中但最近距离={got_d!r}（尺 {radius:g}m）")
                if ch == LEDGER_NO and got_d is not None and radius is not None and got_d <= radius - 1.0:
                    dist_bad.append(
                        f"({i},{j}) {k} 判为没命中但最近距离 {got_d:g}m ≤ 尺 {radius:g}m")
            missing = [k for k in asked if present[k][i][j] == LEDGER_NO]
            derived_blind = bool(missing)
            derived_verdict = derived_blind or (
                len(asked) == len(TRIAD_KEYS)
                and all(present[k][i][j] == LEDGER_YES for k in TRIAD_KEYS)
            )
            if derived_blind != (mats["blind"][i][j] == LEDGER_YES):
                rule_bad.append(f"({i},{j}) 盲区位与规则不符")
            if derived_verdict != (mats["verdict"][i][j] == LEDGER_YES):
                rule_bad.append(f"({i},{j}) 结论位与规则不符")
            if mats["verdict"][i][j] == LEDGER_YES:
                counts["cells_judged"] += 1
            if mats["capped"][i][j] == LEDGER_YES:
                counts["cells_unjudgeable_by_cap"] += 1
            if derived_blind:
                counts["cells_blind"] += 1
    counts["cells_unknown"] = (
        counts["cells_inside"] - counts["cells_judged"] - counts["cells_unjudgeable_by_cap"])

    def _report(bad: List[str], why: str) -> None:
        out.append(f"{why}：{len(bad)} 格，前 {min(len(bad), 5)} 处 {bad[:5]}")

    if state_bad:
        _report(state_bad, "cells_ledger 的第三态被压成了二态（字母表纪律）")
    if rule_bad:
        _report(rule_bad, "cells_ledger 的结论位与不对称规则重抄不符")
    if dist_bad:
        _report(dist_bad, "cells_ledger 的最近距离与命中位互相打脸")

    for key, got in sorted(counts.items()):
        declared = _num(cal.get(key))
        if declared is None:
            out.append(f"台账能复算 {key}，但 caliber 没这个键 —— 分账与台账不是同一次判定")
        elif int(declared) != got:
            out.append(
                f"{key}：顶层报 {declared:g}，台账复算得 {got} —— 计数与逐格台账对不上账"
                "（同一把尺算出来的东西没有容差）"
            )

    # 格阵一致性已在上面（矩阵校验之前）查过 —— 那里报的是"台账不是这张格阵"，
    # 这里不再重复，免得一处缺陷刷两行。
    return out


# ── Tier A + Tier B：完整几何契约 ───────────────────────────────
def _reach_calibration_violations(lc: Dict[str, Any]) -> List[str]:
    """可达口径（`rc-*`）的版本号与 ``sampling.detour`` 键集必须同批发布（笔 3-B）。

    门禁**只看自己那把键**，不看 ``ev-*``：三根轴各自独立声明、独立拦。拿别人的版本号给
    自己作前提＝把一根轴塌进另一根（评分口径曾借 `ev-*` 表达，结果两份分母不同的报告被
    当成可比，那才是 `cov-1` 独立成键的原因）。
    存量件没有这把键 ⇒ 整套跳过 ⇒ 本次发布对既有报告的**可见性零影响**（可见性由
    :func:`assess_geometry` 管，这里只给它新增一条属于可达轴自己的违规）。
    """
    cal = lc.get("caliber") or {}
    if cal.get("reach_caliber_version") != REACH_CALIBER_VERSION:
        return []
    det = (lc.get("sampling") or {}).get("detour")
    if not isinstance(det, dict):
        return [
            f"声明了 reach_caliber_version={REACH_CALIBER_VERSION} 却缺 sampling.detour"
            " —— 版本号与键集是同一次发布的两半，没有标定读数就等于替一次没发生的解释举证"
        ]
    absent = [k for k in ("declared_detour_k", "detour_factor_measured",
                          "points_used", "excluded", "residual_min") if k not in det]
    absent += [f"excluded.{k}" for k in ("near_center", "untimed", "non_positive")
               if k not in (det.get("excluded") or {})]
    if absent:
        return [
            f"sampling.detour 缺 {absent} —— 声明了 {REACH_CALIBER_VERSION} 就得能举证"
            "样本口径（含三类剔除计数）与残差分位"
        ]
    used, k, res, declared = det.get("points_used"), det.get("detour_factor_measured"), \
        det.get("residual_min"), det.get("declared_detour_k")
    # 两半必须同进同退：标定值与残差分位是一套解释的两半，只发一半就是半吊子发布
    if k is None and res is not None:
        return ["没标定出常态绕行系数却报出残差分位 ⇒ 那几分钟不是这把尺量出来的"]
    if k is not None and not isinstance(res, dict):
        return ["标定出了常态绕行系数却报不出残差分位 —— 残差正是这把尺存在的理由"]
    if k is not None and not isfinite(float(k)):
        return [
            f"常态绕行系数 {k!r} 不是有限数 —— 标定被样本里非有限的测时值染污，这把尺整块不可信"
            "（剔除发生在源头 `detour_residual`，这里只是不让染污件签发出去）"
        ]
    if k is not None and float(k) <= 0:
        return [f"常态绕行系数 {k} ≤ 0 不可能来自实测（绕行只会让耗时变长，不会变短）"]
    if isinstance(res, dict):
        polluted = [name for name, v in res.items()
                    if not isinstance(v, (int, float)) or not isfinite(float(v))]
        if polluted:
            return [
                f"残差分位 {sorted(polluted)} 不是有限数 ⇒ 那几分钟不是量出来的，"
                "残差是披露位，非有限值一上屏就是把「没量到」伪装成一个读数"
            ]
    if k is not None and not used:
        return f"points_used={used} 却报出标定值 {k} ⇒ 标定不是从样本来的"
    if declared is not None and (not isfinite(float(declared)) or float(declared) <= 0):
        return f"声明的绕行系数 {declared} ≤ 0 或非有限数 —— 口径表本身错了，别让它伪装成实测标定"
    return []


def _interpolation_form_violations(lc: Dict[str, Any]) -> List[str]:
    """B15 · 说了场是怎么插出来的，就得说全（笔 4a 后续：IDW 的 p、k 从函数体字面量升为口径）。

    分档刻意照 B14 那条纪律走，**两半皆缺＝合法**：那是场形态口径生效之前冻结的存量件，
    判它违规等于把三十来份历史报告从列表里抹掉——可见性不是这条该管的事。
    四种真违规：
      ① 只有一半（有幂次没近邻数，或反之）：读者仍复不出这个场，而"看起来声明过"
         比明确没声明更误导；
      ② `interpolation` 已改口成非 IDW 却带着 IDW 的形态参数 —— 一份载荷同时说两种造法
         （离线链就是靠摘键来避免这一格的，见 `data_source.OfflineDataSource.compute`）；
      ③ 值不合法：`p ≤ 0`／非有限值会让 `1/d^p` 变成常数或发散，`k < 1` 是空加权，
         两者都会**静默**产出一个无意义的场；
      ④ `k` 不是整数：它是"取几个邻居"的个数，2.5 个近邻不存在。
    """
    sp = lc.get("sampling") or {}
    keys = set(interpolation_form_keys())
    present = keys & set(sp)
    if not present:
        return []                      # 存量件：整套跳过，不影响任何可见性
    if present != keys:
        return [
            f"sampling 只声明了场形态的一半（在场的是 {sorted(present)}）"
            " —— 幂次与近邻数缺一半就复不出这个场，半份声明比不声明更容易被误信"
        ]
    method = sp.get("interpolation")
    if method not in (None, "idw"):
        return [
            f"interpolation={method!r} 不是 idw，却带着 IDW 的场形态参数"
            "（sampling.interpolation_power / interpolation_neighbors）⇒ 同一份载荷说了两种造法"
        ]
    power = sp.get("interpolation_power")
    neigh = sp.get("interpolation_neighbors")
    try:
        pv = float(power)
    except (TypeError, ValueError):
        return [f"interpolation_power={power!r} 不是数 ⇒ 插值口径无法举证"]
    if not isfinite(pv) or pv <= 0:
        return [f"插值幂次 {power!r} ≤ 0 或非有限值 —— 1/距离^p 会退化成常数权重或发散"]
    if isinstance(neigh, bool) or not isinstance(neigh, int):
        return [f"近邻数 {neigh!r} 不是整数 —— 它是「取几个最近实测点」的个数，2.5 个近邻不存在"]
    if neigh < 1:
        return [f"近邻数 {neigh} < 1 ⇒ 没有任何实测点参与加权，这个场不是插值出来的"]
    return []


def _shape_caliber_violations(lc: Dict[str, Any]) -> List[str]:
    """B17 · 形状口径（第五把尺：只诊断，不入分）—— 发出来了就得自洽、可复算。

    与 B14/B15/B16 同一分档：**缺席＝合法**（存量件、离线件、骑行/驾车档、5/10min
    都不发这个键，一套都不该被这条打死），只罚"说了但说不圆"。罚五格：

      ① 半份发布 —— `shape` 里七件（bins_m / bin_deg / bin_phase / origin /
         azimuth_fn / circularity / weak_ratio）缺任一件。半份比不发更误导：读者拿到
         一串米数却不知道怎么分的箱、相对谁量的，而自己复算必然复不出同一个数。
      ② 口径漂移 —— 分箱必须是 45°、分相必须是 `center`、原点必须是 `scene.center`、
         方位角实现必须是球面 `bearing()`。这四件不是实现细节而是**口径**：用生产
         `shape_of` 实算，只把原点换成质心，凯里 15min 圆度 0.713→0.684（动 0.029，
         而两城之间总共只差 0.082）、最弱读数 438→553m，劲松 15min 的最弱方位直接改口
         （正西→东北）；只把分相换成 floor，最弱读数从 438m 虚高到 571m
         —— 缺口被相邻方向的最大值掩盖 133m。判据在 `tests/test_shape_caliber.py`。
      ③ 值不合法 —— `bins_m` 必须是 8 个正的有限值；比值/圆度必须是 (0,1] 内的有限值。
         NaN 或 0 会让"最弱方位"变成一个指不到任何方向的数。
      ④ 派生自洽 —— 两颗标量必须由这一档自己的数推出：
         `circularity == sqrt(area_km2·1e6/π)/max(bins_m)`、`weak_ratio == min/max`。
         面积的出处是 `area_km2`（**不许由 bins_m 反推面积**，那是第二个面积真源）。
      ⑤ 外接半径不重复定义（**条件式**）—— 当且仅当这一档就是可达档
         （`minutes == caliber.reach_full_min` 且该分钟数在 `caliber.iso_minutes` 里），
         恒有 `max(bins_m) == caliber.reach_circumradius_m`（同式同点，`scope.py:530`）。
         前提守卫必须写在判据里：满分线一旦挪到不在四档内的值，这条要自动失效，
         否则就是拿配置漂移制造假红。
    """
    shape_key = next(iter(shape_zone_keys()))   # 键名取自发射口，不在判据里抄第二份
    zones = lc.get("isochrones") or []
    with_shape = [z for z in zones if isinstance(z, dict) and shape_key in z]
    if not with_shape:
        return []                                   # 这套载荷没声明形状口径 ⇒ 整套跳过
    cal = lc.get("caliber") or {}
    need = {"bins_m", "bins_word", "bin_deg", "bin_phase", "origin", "azimuth_fn",
            "circularity", "weak_ratio"}
    out: List[str] = []
    minutes_present = {float(z.get("minutes") or -1) for z in zones if isinstance(z, dict)}
    # 档位集合**只准引发射口**：今天这里是 `SHAPE_MINUTES=(15,20)`，判据若抄字面 (15.0, 20.0)，
    # 口径收窄成只发 15min 就会假红、放宽时新档又完全不校验（键名那一条已经按同源做过，见上面）。
    for m in (float(x) for x in SHAPE_MINUTES):
        if m in minutes_present and m not in {float(z.get("minutes") or -1) for z in with_shape}:
            out.append(f"{m:g}min 档缺 {shape_key} 键，但同载荷另有档带它 ⇒ 形状口径半代发（漏发的那档屏上会整块缺席）")
    for z in with_shape:
        m = z.get("minutes")
        sh = z.get(shape_key)
        tag = f"isochrones[{m}min].{shape_key}"
        if not isinstance(sh, dict):
            out.append(f"{tag} 不是对象（{type(sh).__name__}）⇒ 形状读数无法举证")
            continue
        miss = need - set(sh)
        if miss:
            out.append(f"{tag} 缺 {sorted(miss)} —— 半份形状声明比不发更容易被误信")
            continue
        bins = sh["bins_m"]
        if not isinstance(bins, (list, tuple)) or len(bins) != 8:
            out.append(f"{tag}.bins_m 必须是 8 个方位的最远可达半径，拿到 {bins!r}")
            continue
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bins):
            out.append(f"{tag}.bins_m 含非数值 ⇒ 无法比对分箱")
            continue
        if any((not isfinite(float(v))) or float(v) <= 0 for v in bins):
            out.append(f"{tag}.bins_m 含 0/负数/非有限值 ⇒ 有方位被当成「一步都出不去」，那不是测量")
            continue
        words = sh.get("bins_word")
        if not isinstance(words, (list, tuple)) or len(words) != 8 or any(not str(w) for w in words):
            out.append(f"{tag}.bins_word 必须是 8 个方位词（与 bins_m 同序）—— 词表只有一份，"
                       "随键下发；渲染面各自抄一份就会在「正北/北」这种地方分叉")
            continue
        if [str(w) for w in words] != list(_DIRECTIONS):
            out.append(f"{tag}.bins_word 与生产 8 词表不同序（拿到 {list(words)}，口径 {list(_DIRECTIONS)}）"
                       " —— 整体转一格（或任何换序）会让每一箱都配上错的方位词，"
                       "屏上把「最弱方向：正北」念成别的方向，而这在载荷上看不出任何异常")
            continue
        # 四件口径声明逐字段各判各的，**文案里必须点出字段名**：合并成一条"分箱/分相"
        # 会让运维只看到"口径不符"却不知道该改哪一位（S28 元判据就是按"能不能点名"逼出来的）。
        caliber_checks = (
            ("bin_deg", float(sh["bin_deg"]) != SHAPE_BIN_DEG, "分箱宽度",
             f"口径 {SHAPE_BIN_DEG} —— 换分箱宽度等于换分箱个数，词表与楔形都会错位"),
            ("bin_phase", sh["bin_phase"] != SHAPE_BIN_PHASE, "分相",
             f"口径 {SHAPE_BIN_PHASE!r} —— 换 floor 分相会把缺口并进相邻方向取最大值（实测掩盖 133m）"),
            ("origin", sh["origin"] != SHAPE_ORIGIN, "原点",
             f"口径 {SHAPE_ORIGIN!r} —— 换原点圆度会动 0.029（球面实算），最弱方位还可能改口"),
            ("azimuth_fn", sh["azimuth_fn"] != SHAPE_AZIMUTH_FN, "方位角实现",
             f"口径 {SHAPE_AZIMUTH_FN!r} —— 平面 atan2 与球面 bearing 确有差，不声明就靠运气"),
        )
        caliber_drift = False
        for field, bad, cname, why in caliber_checks:
            if bad:
                out.append(f"{tag}.{field}（{cname}）与生产口径不符（拿到 {sh[field]!r}）—— {why}")
                caliber_drift = True
                break
        if caliber_drift:
            continue
        try:
            circ, weak = float(sh["circularity"]), float(sh["weak_ratio"])
        except (TypeError, ValueError):
            out.append(f"{tag} 的两颗标量不是数 ⇒ 无法复算")
            continue
        if not all(isfinite(v) and 0.0 < v <= 1.0 for v in (circ, weak)):
            out.append(f"{tag} 圆度/最弱方位比必须落在 (0,1]，拿到 {circ}/{weak}")
            continue
        area = z.get("area_km2")
        if area is None or not isfinite(float(area)) or float(area) <= 0:
            out.append(f"{tag} 所在档没有可举证的 area_km2 ⇒ 圆度的面积出处断了")
            continue
        want_c = math.sqrt(float(area) * 1_000_000.0 / math.pi) / max(float(v) for v in bins)
        if abs(want_c - circ) > SHAPE_SCALAR_TOL:
            out.append(f"{tag}.circularity={circ} 与 sqrt(area_km2·1e6/π)/max(bins_m)={want_c:.3f} 对不上"
                       " —— 面积只准取本档 area_km2，不许由 bins_m 反推")
        want_w = min(float(v) for v in bins) / max(float(v) for v in bins)
        if abs(want_w - weak) > SHAPE_SCALAR_TOL:
            out.append(f"{tag}.weak_ratio={weak} 与 min(bins_m)/max(bins_m)={want_w:.3f} 对不上")
        try:
            iso_minutes = [float(x) for x in (cal.get("iso_minutes") or [])]
            reach_min = float(cal.get("reach_full_min") or -1)
        except (TypeError, ValueError):
            continue
        if m is not None and abs(float(m) - reach_min) < 1e-6 and reach_min in iso_minutes:
            cr = cal.get("reach_circumradius_m")
            if cr is not None and isfinite(float(cr)) and abs(max(float(v) for v in bins) - float(cr)) > SHAPE_CIRCUMRADIUS_TOL_M:
                out.append(f"{tag}: 可达档的 max(bins_m)={max(float(v) for v in bins)} 与 "
                           f"caliber.reach_circumradius_m={cr} 不是同一个数（同式同点应相等）"
                           " ⇒ 外接半径出现了两个真源")
    return out


def _iso_compare_violations(lc: Dict[str, Any]) -> List[str]:
    """B16 · 口径对比环（笔 B）：发出来了就得是"另一把尺的对照"，不能是第五条等值线。

    缺席＝合法（骑行/驾车档本来不声明这个阈值、离线链刻意不接、几何退化时也切不出环），
    与 B14/B15 同一分档：**这条不罚"没说"，只罚"说了但说不圆"**。四件必须自洽的事：

      ① 键齐 —— `minutes` / `geojson` / `area_km2` / `basis` / `claim` 少一个都是半吊子发布；
      ② 断言边界 —— `claim` 必须是 `caliber_comparison_only`。这一位是给机器读的：
         文献量的是**群体有效窗口**，把它写成对具体居民的能力判断就越过了证据；
         文案守卫能拦字面，拦不住"载荷里带着一个可以被误读的数字"，所以边界要进载荷。
      ③ 与四档互斥 —— 它的分钟数不许出现在 `caliber.iso_minutes` 里（那叫第五档等值线，
         而前端配色表、面积单调性、图例都按"恰好四档"钉），并且必须等于**当前口径表**
         给该出行方式声明的值 ⇒ 手改的、或从别的档搬来的环在这里现形。
      ④ 几何自洽 —— 环闭合且 ≥4 点；面积可举证且**落在相邻两档面积之间**
         （同一条耗时场切出来的环，分钟数居中而面积越界 ⇒ 那条环不是这个场切的）。
    """
    cmp_zone = lc.get("iso_compare")
    if cmp_zone is None:
        return []
    if not isinstance(cmp_zone, dict):
        return [f"iso_compare 不是对象（{type(cmp_zone).__name__}）⇒ 口径对比环无法举证"]

    missing = [k for k in ("minutes", "geojson", "area_km2", "basis", "claim")
               if k not in cmp_zone]
    if missing:
        return [f"iso_compare 缺 {missing} —— 阈值、几何、面积、依据、断言边界是同一次发布的五半"]
    if cmp_zone.get("claim") != "caliber_comparison_only":
        return [f"iso_compare.claim={cmp_zone.get('claim')!r} 不是 caliber_comparison_only "
                "⇒ 这条环被当成能力断言发出去了；文献量的是群体有效窗口，不是具体居民"]
    basis = (cmp_zone.get("basis") or "").strip()
    if len(basis) < 12:
        return [f"iso_compare 的依据只写了 {len(basis)} 字 ⇒ 一个没有出处的阈值不该上屏"]

    minutes = cmp_zone.get("minutes")
    try:
        level = float(minutes)
    except (TypeError, ValueError):
        return [f"iso_compare.minutes={minutes!r} 不是数"]
    if not isfinite(level) or level <= 0:
        return [f"iso_compare.minutes={minutes!r} ≤ 0 或非有限值 ⇒ 这不是一个可比的阈值"]

    cal = lc.get("caliber") or {}
    iso_minutes = [float(m) for m in (cal.get("iso_minutes") or [])]
    if level in iso_minutes:
        return [f"iso_compare.minutes={minutes} 与四档等值线重合 ⇒ 它是第五条线，不是口径对照"]
    travel_mode = cal.get("travel_mode") or "walking"
    declared = get_caliber(travel_mode).iso_compare_min
    if declared is None:
        return [f"{travel_mode} 档没有声明口径对比阈值，载荷却发了 iso_compare ⇒ 这条尺只属于步行档"]
    if abs(level - float(declared)) > 1e-6:
        return [f"iso_compare.minutes={minutes} 与当前口径表声明的 {declared} 不一致 "
                "⇒ 环不是按这把尺切的（手改或从别处搬来）"]

    coords = ((cmp_zone.get("geojson") or {}).get("coordinates") or [[]])[0]
    if len(coords) < 4:
        return [f"iso_compare 环只有 {len(coords)} 个点 ⇒ 连一条闭合边界都撑不起来"]
    if coords[0] != coords[-1]:
        return ["iso_compare 环未闭合（首尾不同点）⇒ 前端取 coordinates[0] 画多边形会开出缺口"]
    area = cmp_zone.get("area_km2")
    try:
        av = float(area)
    except (TypeError, ValueError):
        return [f"iso_compare.area_km2={area!r} 不是数"]
    if not isfinite(av) or av <= 0:
        return [f"iso_compare.area_km2={area!r} ≤ 0 ⇒ 闭合环有面积才可比"]

    zones = lc.get("isochrones") or []
    below = [z for z in zones if float(z.get("minutes") or 0) < level and z.get("area_km2") is not None]
    above = [z for z in zones if float(z.get("minutes") or 0) > level and z.get("area_km2") is not None]
    if below:
        lo = max(below, key=lambda z: float(z["minutes"]))
        if av < float(lo["area_km2"]):
            return [f"iso_compare 面积 {av} km² 小于 {lo['minutes']}min 档的 {lo['area_km2']} km² "
                    "⇒ 阈值更大却圈更小，这条环不是同一份耗时场切出来的"]
    if above:
        hi = min(above, key=lambda z: float(z["minutes"]))
        if av > float(hi["area_km2"]):
            return [f"iso_compare 面积 {av} km² 大于 {hi['minutes']}min 档的 {hi['area_km2']} km² "
                    "⇒ 阈值更小却圈更大，与同批四档不自洽"]
    return []


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

    # B5/B10/B11/B12 · 证据相四条（只读 payload 数值，不吃几何参照系 ⇒ 必须在 center 早退之前）
    violations.extend(_evidence_phase_violations(lc))
    # B14 · 可达口径那把轴（同样只读 payload，与上面三根轴互不顶替）
    violations.extend(_reach_calibration_violations(lc))
    # B15 · 实测场的形态参数（幂次与近邻数）—— 也是只读 payload，必须在 center 早退之前
    violations.extend(_interpolation_form_violations(lc))
    # B16 · 口径对比环（笔 B）—— 同样只读 payload；缺席即整套跳过，存量件零影响
    violations.extend(_iso_compare_violations(lc))
    # B17 · 形状口径（第五把尺，只诊断不入分）—— 缺席即整套跳过，存量件零影响
    violations.extend(_shape_caliber_violations(lc))

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
            # B8 · footprint_meta（可选，旧报告缺它不违规；存在时校验自洽）
            meta = b.get("footprint_meta")
            if meta is not None:
                if not isinstance(meta, dict):
                    violations.append(f"盲区 {b.get('id')} footprint_meta 非对象")
                else:
                    for k_key, k_type in (
                        ("resolution_m", (int, float)),
                        ("grid_m", (int, float)),
                        ("cells", int),
                        ("refine", int),
                    ):
                        v = meta.get(k_key)
                        if v is not None and not isinstance(v, k_type):
                            violations.append(f"盲区 {b.get('id')} footprint_meta.{k_key} 类型非法（{v!r}）")
                    if not isinstance(meta.get("undersampled"), bool):
                        violations.append(f"盲区 {b.get('id')} footprint_meta.undersampled 必须为布尔")
            # B9 · polygon_raw（可选，双边界解耦的 raw 档）：存在时须为合法的闭合 Polygon
            raw = b.get("polygon_raw")
            if raw is not None:
                raw_ring = _ring({"polygon": raw})
                if raw_ring is None:
                    violations.append(f"盲区 {b.get('id')} polygon_raw 不是合法闭合 Polygon")
                else:
                    got = _max_abs_offset(center, raw_ring)
                    if got > cr * GEOM_TOL:
                        violations.append(
                            f"盲区 {b.get('id')} polygon_raw 最远点 {got:.0f}m 越出可达区外接圆 {cr:.0f}m"
                        )

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


# ── 复用门：口径版本 ────────────────────────────────────────────
# 口径版本轴的**归属登记表**（三根轴，每根必须在这里二选一）
#
# 这张表回答的是一个以前只能靠读代码才知道的问题：**一根口径轴换代，到底该不该让旧报告
# 停止复用？** 判据不是"它是不是版本号"，而是这条门自己的那句 ——「换我重跑一次，答案会不会
# 不同」。答"会"的进 `_GATED_CALIBER_VERSIONS`（旧报告 miss、重跑），答"不会、只是多了一段
# 解释"的进 `_UNGATED_CALIBER_VERSIONS`（照常复用，换代由**对比页横幅 + 契约 B14 + 残差句按
# presence 上不出现**这三条披露路径负责）。
#
# 为什么做成表而不是散在注释里：加第四根轴时，"忘了决定"和"决定错边"都必须是**红**的，
# 而不是靠下一个人读到哪条注释。判据：
# `tests/test_living_circle_api.py::test_caliber_axes_are_registered_everywhere_they_must_be`
# 钉「`_GAP_CLAUSES` 的轴集 == 这两张表的键集（不重不漏）＋每张表的字段名与门内实际读的字段
# 一致＋`_UNGATED` 每条都把理由写成了数据」。
#
# ⚠️ 刻意**不加 `__all__` 导出**：它们是登记表而不是公开 API。判据用
# `vars(report_contract)["_GATED_CALIBER_VERSIONS"]` 读，读得到＝私有但存在，
# 而任何生产代码想拿它当"该不该拦"的旁证都拿不到（那是本仓最典型的旁路形状）。
_GATED_CALIBER_VERSIONS: Dict[str, str] = {
    # 证据域/判盲算法变更 ⇒ 盲区数与判定覆盖率本身就是另一把尺量的（凯里旧口径实测只判 5/97 格）
    "ev": "scope_policy_version",
    # 覆盖度**分子**变更 ⇒ 同一批点位算出不同的分（第 21 轮 P1-3：凯里那 3 分落差全来自换代）
    "cov": "coverage_caliber_version",
}
# ⚠️ `_UNGATED` 的值是**二元组 (字段名, 理由)**：理由必须是数据而不是注释 —— 注释会随下一次
# 重构漂走，而"为什么不进门"恰恰是最需要被下一个人读到、并且由判据强制填写的东西
# （`len(理由) > 80` 那条判据在第一版里就抓到了我自己：我把理由写进了注释、表里只留字段名，
# 于是那条判据量的是一串 21 个字符的键名，恒真）。
_UNGATED_CALIBER_VERSIONS: Dict[str, Tuple[str, str]] = {
    "rc": (
        "reach_caliber_version",
        "rc-1 只新增对实测耗时场的解释（标定常态绕行系数 + 残差耗时分钟），盲区数、综合评分、"
        "等时圈面积、可达点数一个都没改 ⇒ 重跑一次的答案与它逐位相同，不满足这条门自己的问题。"
        "拦它的代价是实测的：27 份存量与每次 500m 邻近复用全部 miss，全部重打 1049 点距离矩阵"
        "与逐类检索（真配额），而换来的正确性是零 —— 与 10-01 拒绝「判定覆盖率低于 ⇒ 不可复用」"
        "是同一条判断。它的换代由三条披露路径负责：对比页横幅（`_GAP_CLAUSES` 的 rc 子句）、"
        "契约 B14（声明却缺键即红）、残差句的 presence 判据（没有 `sampling.detour` 就不印，"
        "与逐格台账/取证账同一条纪律）。⚠️ 残差进评分那一档（rc-2）必须把 `rc` 从这里挪进 "
        "`_GATED_CALIBER_VERSIONS` —— 那时答案真的会不同，而前端 `staleCaliberNotices` 也要"
        "同批接上那句「建议重新体检」（现在不接，是因为重跑并不会让分数变好）。",
    ),
}


def _radius_key(value: Any) -> Any:
    """研究半径的比较键：数值归一（`2500` 与 `2500.0` 是同一个档，不是两个）。

    解析不了就**原样返回**：比较自然不成立 ⇒ 判不可复用、去重算。两个都写坏的半径不会因此
    互相"相等"而蒙过门，也不会有 `ValueError` 抛到读接口上（库里躺着一份半径字段被写坏的
    报告，正确行为是不复用，不是 500）。
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def reuse_policy(
    lc: Dict[str, Any],
    wanted: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """该载荷能否作为**本次**体检的答案被复用 → ``(可否复用, 原因)``。

    `wanted` 是**本次请求的口径三元组** ``{travel_mode, study_radius_m, sample_profile}``。
    它必填才能过这道门（缺 ⇒ 判不可复用，不是"跳过比较"）：`find_recent_report_near`
    按中心点距离取最近一份，不比较口径就会把别的档/别的半径/别的采样档的答案卖成本次结果。
    非 `live` 载荷在函数早期就返回，不经这一步 —— 它们没有实测采集口径可谈。

    与 :func:`report_is_presentable` **刻意分开**，两者回答的不是一个问题：

      - presentable ——「这份报告还能不能给用户看」→ 历史列表用；
      - reuse_policy ——「用户刚点了一次体检，这份旧报告能不能冒充答案」→ 缓存用。

    一份旧口径报告**仍然是用户的历史**（该看得见、不该被隐藏），但它的判定覆盖率
    与新体检不同（旧：可达区 5% 的格有完整证据；新：证据域独立），拿它当新答案就是
    把「只看了 5%」的结论重新卖一遍。⇒ **只拦复用，不拦可见性。**

    版本读自载荷（``caliber.scope_policy_version``），**不进缓存键** —— 理由见
    ``scope.SCOPE_POLICY_VERSION``：那个键同时是 DB 的 ``scene_key`` 列，加版本段会让
    同一地点裂成两条历史，而邻近复用走键前缀扫 + 值里的 ``scene.center``，换键拦不住。

    非 ``live`` 载荷（演示夹具 / offline 骨架）不受判盲口径版本约束 —— 它们没有实测
    采集半径可谈，且演示链的可用性由 presentability 那道门负责，这里不越权。

    **几何判据刻意不折进来。** 本函数回答的是同一个问题的两半：「这份报告的口径是不是本次
    这一套」（版本）与「它是不是**这一次请求**的答案」（三元组，批 A③）。而「这份报告能不能
    给用户看」由 :func:`assess_geometry` 回答，且已在写路径
    （``pipeline/living_circle.py`` 缓存命中处）与 DB 读路径各就一处 ——
    把两者再合成第三道门，等于让同一个谓词有三份实现，正是本模块反复要消灭的形态。
    """
    if not isinstance(lc, dict) or not lc:
        return False, "报告载荷为空（living_circle 节点缺失）"
    if (lc.get("data_origin") or "") != "live":
        return True, ""

    declared = (lc.get("caliber") or {}).get("scope_policy_version")
    if declared != SCOPE_POLICY_VERSION:
        return False, (
            f"判盲口径版本不符（报告 {declared or '未声明'} ≠ 当前 {SCOPE_POLICY_VERSION}）"
            "—— 证据域定义已变更，旧结论的判定覆盖率不可作为本次体检的答案"
        )

    # 批 A③ · 口径三元组必须与**本次请求**一致（邻近复用的真窟窿）。
    # `repository.find_recent_report_near` 扫的是 `{mode}:report:` 整个命名空间、只按中心点
    # 距离取最近的一份（`repository.py:267-298`，键前缀里**没有**出行方式/半径/采样档），
    # 于是「骑行 3000m precise」的体检可以被 400m 外那份「步行 2500m quick」的报告答掉 ——
    # 版本门拦不住它（两份都是 ev-1）。这不是理论风险：`NEARBY_CACHE_M=500` 覆盖的正是
    # 同一社区里换档/换半径的二次体检。
    #
    # 为什么这里**不**用「判定覆盖率低于下限 ⇒ 不可复用」（批 A③ 落地前的原方案）：
    # 覆盖率回答的是「这份报告的结论有多厚」，复用门要回答的是「换我重跑一次，答案会不会不同」。
    # 同版本 + 同口径参数下答案是确定的（薄也是这次该有的答案），拦下来只会把每次体检都推去
    # 重跑取证 —— `U22/U39` 那条「二次命中零新增调用」的不变式与真实配额都是它的代价，
    # 而换来的正确性是零。存量 27 份实测：唯一带 ev-1 的那份 share=21/99=21.2%，
    # 刚好在 `JUDGE_SHARE_FLOOR=20%` 之上 ⇒ 那条规则今天既不拦存量、将来也只拦掉"我自己的产物"。
    # 证据面薄的账由评分侧外推封顶（`scoring`）与 `confidence=limited` 负责，不由缓存门负责。
    if wanted is None:
        return False, (
            "复用门未收到本次请求的口径（travel_mode/study_radius/sample_profile）"
            " —— 缺了比较对象，邻近复用无从判断这是不是同一次体检的答案"
        )
    # 三个数各按**请求侧出处**读：`caliber.travel_mode` / `caliber.sample_profile` 由组装层
    # 从 `check` 落笔，而研究半径必须读 `scene.study_radius_m`（那次请求的半径）——
    # `caliber.study_radius_m` 是**档位**的半径，两者在用户改半径时不相等，拿它比会把
    # 「当前编排刚产出的报告」判成不可复用（每次都重跑取证，零复用）。
    cal = lc.get("caliber") or {}
    scene = lc.get("scene") or {}
    checks = (
        ("出行方式", str, cal.get("travel_mode"), wanted["travel_mode"]),
        ("采样档", str, cal.get("sample_profile"), wanted["sample_profile"]),
        # 半径按数值归一后再比：payload 落的是 `int(...)` 而请求侧是 float ⇒ 逐字串比会把
        # 2500 与 2500.0 判成两个档（自家产物拦自家，每次体检都白跑一遍取证）。
        ("研究半径", _radius_key, scene.get("study_radius_m"), wanted["study_radius_m"]),
        # **第二把版本键**（评分口径 `cov-*`）。它的 `want` 与前三行**不同源**：前三行比的是
        # 「本次请求要什么档」，这一行比的是「当前代码是哪一档分子」—— 用户没有"要哪一档分子"
        # 这个选项，请求侧也就带不来它。⇒ 比较对象必须是模块常量，**不许**从 `wanted` 里取
        # （10-01 全量实测：从 `wanted` 取会让所有自带三元组的调用方当场 KeyError，
        #  包括 `tests/test_caching_datasource.py::test_reuse_gate_requires_the_request_caliber_triple`，
        #  并逼着 `data_source.wanted_caliber` 长出一个"假装用户请求了 cov-1"的假键）。
        # 不写这条会怎样：改造后第一次体检产出的新分数落库，第二次体检从库里捞出**改造前**
        # 那份 88.6/68.7 当作本次答案上屏，而页面上没有任何一处能看出它是旧分子算的。
        ("评分口径", str, cal.get("coverage_caliber_version"),
         COVERAGE_CALIBER_VERSION),
        # ⚠️ **第三根轴 `rc-*` 有意不进来**（归边决定与理由都写在上面 `_UNGATED_CALIBER_VERSIONS`
        # 那条数据里，不在注释里）。
        # 判据是这条门自己的问题 ——「换我重跑一次，答案会不会不同」：rc-1 不改盲区数、不改
        # 分数、不改面积，重跑的答案与它逐位相同，只是多了一段解释。把它拦进门里 ⇒ 27 份存量
        # 与每次邻近复用全部 miss、全部重跑取证（真配额），换来的正确性是零 —— 与 10-01 那次
        # 拒绝「判定覆盖率低于下限 ⇒ 不可复用」是同一条判断，也正是
        # `test_pages_returned.test_new_key_does_not_move_the_reuse_gate` 与
        # `test_subkind_caliber.test_second_caliber_version_gate_three_shapes` ③ 在守的不变式
        # （本笔第一版把它放进了 checks，这两条当场红：红的是我，不是它们）。
    )
    for label, coerce, got, want in checks:
        if got is None:
            return False, f"报告没有声明{label} —— 邻近复用不能猜口径"
        if coerce(got) != coerce(want):
            return False, (
                f"{label}不符（报告 {got} ≠ 本次 {want}）"
                " —— 邻近命中按中心点距离取最近一份，口径不同的两份不是同一个问题的答案"
            )
    return True, ""


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
    "reuse_policy",
    "staleness_reason",
]
