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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.living_circle.geo_utils import LngLat, haversine_m, ring_area_km2, to_local_xy
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
    inside, judged, unknown = (_num(cal.get(k)) for k in ("cells_inside", "cells_judged", "cells_unknown"))

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
        if judged == 0 and unknown != inside:
            out.append(
                f"一格未判（cells_judged=0）却只把 {unknown:g}/{inside:g} 记为未定 —— "
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
