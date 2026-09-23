"""民生 POI：类别表 / 多关键词采集 / 清洗去重 / 分类覆盖统计。

三大口径（与前端 F0 契约 / 赛题一致）：
  - 8 类民生类别 → `FacilityCategoryStat[]`（category/total/in_circle/coverage/min_minutes/nearest）
  - 盲区三要素（菜市场/药店/小学）→ 独立 POI 点集，供 blindspot.py 做 1km 判定
判表唯一事实源 = `category_rule.CATEGORY_RULES`：本模块的 `CATEGORY_DEFS` /
`TRIAD_KEYWORDS` 由它**派生**（仅补 is_market），不再双写两套判表（rev3 §四A/P1-1）。
采集策略：每类多关键词查全率（百度 place/v2/search），名称归一 + 50m 聚簇去重。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES, evaluate_category
from app.living_circle.geo_utils import haversine_m, point_in_ring, round_lnglat
from app.living_circle.scope import SpatialScope

# ── 每类点位**展示**上限（唯一共享常量）──────────────────────────
# 计划 §8-D3：25 → 200。当前最大类别（shopping 圈内 31）永不触发，
# 但**保留最后一道防线**：某天某城市抓回 500 个点时，报告体积与前端页面不至于被压垮。
#
# ⚠️ 语义边界（两条口径不可混）：
#   - 本值决定「**展示多少**」，**不决定「抓回多少」**（那是 `quota` 的职责）⇒ **不消耗检索额度**；
#   - 因此采集出口（`poi_collector.merge_all`）**不得**再用它截一次 —— 在采集侧截断会把
#     `poi.total`（采集口径，含圈外）一并压小，等于让「展示上限」篡改了「采集事实」。
#   - **唯一截断点 = 本模块 `to_points`**，且必须产出 `truncated` 披露（阶段 1.3）。
POI_CAP_PER_CAT = 200


class PoiConservationError(RuntimeError):
    """点数守恒 `sum(categories[].in_circle) == len(points)` 被打破（阶段 1.4）。

    只在**测试 / CI** 抛出（`conservation_policy() == 'strict'`）；生产 / 演示走
    「照出报告 + `poi.conservation.ok=false` 留痕」，但**任何环境都不静默**。
    """


class PoiPointsOut(NamedTuple):
    """`to_points` 的返回：点位 + **截断披露**（阶段 1.3）。

    `truncated` 逐类记录 `{"category", "kept", "dropped"}`，**只含真的发生截断的类别**
    （无截断即 `[]`）。用 NamedTuple 而非裸 list：截断信息**无法被顺手丢掉**，
    而调用方仍可 `points, truncated = to_points(...)` 解包。

    调用方必须把它落进 ``poi.truncated`` ——「静默截断」正是本阶段要消灭的缺陷
    （旧实现在 `poi.py:237` 无声无息地砍掉 6 条购物点，报告里看不出任何痕迹）。
    """
    points: List[Dict[str, Any]]
    truncated: List[Dict[str, Any]]


def _build_category_defs() -> Dict[str, Dict[str, Any]]:
    """从 `category_rule.CATEGORY_RULES` 派生（键/词表/阈值单一来源，仅补 poi 专有 is_market）。"""
    defs: Dict[str, Dict[str, Any]] = {}
    for key, rule in CATEGORY_RULES.items():
        d: Dict[str, Any] = {
            "label": rule["label"],
            "keywords": list(rule["keywords"]),
            "ideal_circle": rule["ideal_circle"],
        }
        if key == "market":
            d["is_market"] = True
        defs[key] = d
    return defs


def _build_triad_keywords() -> Dict[str, str]:
    """从 `category_rule.TRIAD_RULES` 派生 `{key: 检索词}`（盲区三要素兼容视图）。"""
    out: Dict[str, str] = {}
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_"):
            continue
        kw = ""
        if isinstance(ref, dict):
            kw = (ref.get("keywords") or [""])[0]
        elif isinstance(ref, str):
            kw = ref
        if kw:
            out[key] = kw
    return out


# ── 民生类别表（category 键与前端 fixture 保持一致）───────
# keywords：百度 place 检索关键词组（多词查全率）；ideal_circle：圈内理想阈值（评分基准）
CATEGORY_DEFS = _build_category_defs()

# 盲区三要素（赛题硬判口径：1km 内无菜市场/药店/小学）
TRIAD_KEYWORDS = _build_triad_keywords()


def norm_name(name: str) -> str:
    """名称归一：去空白/停用后缀/全角转半角 → 用作聚簇主键辅助。"""
    if not name:
        return ""
    s = re.sub(r"[\s\u3000]+", "", name)
    s = re.sub(r"（.*?）|\(.*?\)", "", s)
    return s.lower()


# 「坐标重合」的强合并阈值（米）：不同名但贴脸同址（同一门牌）视为重复。
# 10m 量级 ≈ 临街店铺门面宽度，避免把「同一家店被不同名重复返回」漏掉，
# 同时绝不误伤同一街区的相邻不同名设施（金马/瑞霖便利店，>10m）。
DUPLICATE_NEAR_M = 10.0


def is_duplicate(a: Dict[str, Any], b: Dict[str, Any], radius_m: float = 50.0) -> bool:
    """两条 POI 是否判重（v5 D3 单一实现）：
    （同名 且 距离 < radius_m） 或 （距离 < DUPLICATE_NEAR_M）。

    - 同名 <50m：同一家店被多关键词重复返回 → 合并；
    - 不同名 ≥10m：相邻同类型设施（金马/瑞霖便利店）→ **保留**；
    - 不同名 <10m：贴脸同址（名称只是别称/店招差异）→ 合并。
    """
    d = haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"]))
    if d < DUPLICATE_NEAR_M:
        return True
    return norm_name(a.get("name", "")) == norm_name(b.get("name", "")) and d < radius_m


def dedupe_pois(items: List[Dict[str, Any]], radius_m: float = 50.0) -> List[Dict[str, Any]]:
    """聚簇去重（o(n²) 在小样本下足够，每类 ≤ 几十条）；半径内保留先到者。

    去重判据唯一实现 = `is_duplicate`（D3），`clean` 与 `poi_collector` 共用，
    消除两处 50m 逻辑双份漂移（R3/问题 3 根因）。
    """
    kept: List[Dict[str, Any]] = []
    for it in items:
        if not it or it.get("lat") is None or it.get("lng") is None:
            continue
        if any(is_duplicate(it, k, radius_m) for k in kept):
            continue
        kept.append(it)
    return kept


def clean(items: List[Dict[str, Any]], dedupe_radius_m: float = 50.0) -> List[Dict[str, Any]]:
    """清洗管道：过滤无坐标 → 坐标落点规整 → 聚簇去重（保先到者优先）。"""
    valid = [it for it in items if it.get("lat") is not None and it.get("lng") is not None]
    seen_names: set = set()
    out: List[Dict[str, Any]] = []
    for it in valid:
        key = f"{norm_name(it.get('name', ''))}|{round(it['lng'], 5)}|{round(it['lat'], 5)}"
        if key in seen_names:
            continue
        seen_names.add(key)
        out.append({**it, "lng": round(it["lng"], 6), "lat": round(it["lat"], 6)})
    return dedupe_pois(out, dedupe_radius_m)


def to_stats(
    per_category: Dict[str, List[Dict[str, Any]]],
    triads: Dict[str, List[Dict[str, Any]]],
    scope: SpatialScope,
    center: Tuple[float, float],
) -> List[Dict[str, Any]]:
    """类别统计：圈内数 / 覆盖度 / 最近设施（步行耗时由调用方注入则用，否则用距离换算提示）。

    coverage = min(1, in_circle / ideal_circle)；min_minutes 由调用方在测时后填充（此处填 None 占位，
    live 管线在 poi+isochrone 后统一回填 nearest_minutes）。

    「圈内」= **可达区**（``scope.reach_ring``）。形参从 ``iso15_ring`` 改为 ``scope``：
    旧形参名承诺 15min 圈、实收 20min 圈、文档又写 15min，**三处不一致且没有任何一层能发现**；
    现在圈从 ``scope`` 取，而 ``scope`` 的构造已校验过环的 ``minutes == caliber.reach_full_min``。
    """
    reach_ring = scope.reach_ring
    stats: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        defn = CATEGORY_DEFS[cat]
        in_circle = [it for it in items if point_in_ring((it["lng"], it["lat"]), reach_ring)]
        ideal = defn["ideal_circle"]
        coverage = min(1.0, len(in_circle) / ideal)
        nearest = None
        nearest_d = float("inf")
        for it in items:
            d = haversine_m((it["lng"], it["lat"]), center)
            if d < nearest_d:
                nearest_d = d
                nearest = it
        stats.append({
            "category": cat,
            "label": defn["label"],
            "total": len(items),
            "in_circle": len(in_circle),
            "coverage": round(coverage, 4),
            "min_minutes": None,  # 测时后回填
            "nearest_name": nearest.get("name") if nearest else None,
        })
    # 盲区三要素点集归一化输出（供 blindspot 复用，避免重复检索）
    return stats


def backfill_nearest_minutes(
    stats: List[Dict[str, Any]],
    per_category: Dict[str, List[Dict[str, Any]]],
    field_fn,
) -> List[Dict[str, Any]]:
    """按 IDW 耗时场回填各类别 min_minutes/nearest_name（live 管线统一通道）。

    field_fn(point) -> 分钟数（不可达返回 None）。
    """
    for s in stats:
        cat = s["category"]
        items = per_category.get(cat, [])
        best: Optional[Dict[str, Any]] = None
        best_m = None
        for it in items:
            m = field_fn((it["lng"], it["lat"]))
            if m is None:
                continue
            if best_m is None or m < best_m:
                best_m = m
                best = it
        s["min_minutes"] = round(best_m, 1) if best_m is not None else None
        if best is not None:
            s["nearest_name"] = best.get("name")
    return stats


def triad_point_sets(triads: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Tuple[float, float]]]:
    """三要素 POI → 坐标集。"""
    return {
        k: [round_lnglat(it["lng"], it["lat"]) for it in v]
        for k, v in triads.items()
        if v
    }


def to_points(
    per_category: Dict[str, List[Dict[str, Any]]],
    times_by_cat: Dict[str, List[Optional[float]]],
    scope: SpatialScope,
    center: Tuple[float, float],
    cap_per_cat: int = POI_CAP_PER_CAT,
) -> PoiPointsOut:
    """原始 POI → 报告点位（真实坐标，供前端 BMapGL 渲染，对齐 PoiPoint 契约）。

    - **只输出可达区内的点**（圈外不展示、不进报告）：旧实现把 2km 采集圈内的点全量输出，
      实测 151 条里只有 18 条在圈内（88% 圈外），展示层只按条数截断 ⇒ 用户看到「圈外地点被检索出来」。
    - 每类排序键 = 「圈内有耗时优先 → 有耗时优先 → **距离近**优先」后截断 ``cap_per_cat`` 条。
      旧实现第三键是**名称字母序** ⇒ 留下的是「按名字挑的点」而不是「离得近的点」。
    - ``center`` 是**查询中心**（必传）：距离以它为参照，不能用可达区环的顶点（环顶点顺序随
      ``linspace`` 行进方向而定，拿 `ring[0]` 当圆心会让「最近的设施」变成「离某个顶点最近的设施」）。
    - ``id`` 稳定可溯源（``poi-{category}-{idx}``）；``lnglat`` 输出 BD-09 ``[lng, lat]``。

    **返回值是 :class:`PoiPointsOut`（点位 + 截断披露），不是裸 list**（阶段 1.3）：
    截断必须随点位一起交回调用方，让它**没法「顺手」把 6 条被砍掉的购物点变没**。
    判定「截断是否发生」只看 `len(entries) > cap_per_cat`，与排序键无关。
    """
    reach_ring = scope.reach_ring
    points: List[Dict[str, Any]] = []
    truncated: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        times = times_by_cat.get(cat, [])
        entries: List[Dict[str, Any]] = []
        for idx, it in enumerate(items):
            t = times[idx] if idx < len(times) else None
            in_reach = point_in_ring((it["lng"], it["lat"]), reach_ring)
            if not in_reach:
                continue  # 圈外点：不展示、不进报告、不计分
            conf = _point_confidence(it)
            entries.append({
                "id": f"poi-{cat}-{idx}",
                "name": it.get("name") or (CATEGORY_DEFS.get(cat, {}).get("label", cat)),
                "category": cat,
                "lnglat": [round(it["lng"], 6), round(it["lat"], 6)],
                "minutes": round(t, 1) if t is not None else None,
                "in_circle": True,
                "_distance_m": haversine_m((it["lng"], it["lat"]), center),
                "_confidence": conf,
            })
        # 排序键 = 可达→minutes 非空→confidence 高→距中心近（rev3 P1-2 单一排序键；
        # confidence 由 category_rule 派生，杜绝名称字母序，也不在别处再做一轮排序）。
        entries.sort(key=lambda p: (p["minutes"] is None, -p["_confidence"], p["_distance_m"]))
        kept = entries[:cap_per_cat]
        dropped = len(entries) - len(kept)
        if dropped > 0:
            truncated.append({"category": cat, "kept": len(kept), "dropped": dropped})
        for p in kept:
            p.pop("_distance_m", None)
            p.pop("_confidence", None)  # 排序键属内部元数据，不进报告点位契约
            points.append(p)
    return PoiPointsOut(points, truncated)


def derive_stats_from_points(
    stats: List[Dict[str, Any]], points: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """把 `categories[].in_circle` / `coverage` **收敛到 `points` 这个唯一真身**（阶段 1.2）。

    这是本计划的核心动作：报告里「圈内 N 处」与「图上 M 个点」从此**只有一个真身**
    （`points`），面板数字由它派生 ⇒ 二者不可能再对不上。

    - ``in_circle`` = 该类别在 `points` 里的条数（可达口径 = 图上实际画了几个）；
    - ``coverage`` = ``min(1, in_circle / ideal_circle)`` **重算** —— 不重算的话
      `coverage` 与 `in_circle` 又成两条链（截断后 coverage 仍按截断前算）；
    - ``total`` **不动**：它是**采集口径**（含圈外的 `per_category` 计数）。
      审查 R1 修正 —— 若也从 points 反算，「采集 217」会塌成 98，信息永久丢失。
    - ``min_minutes`` / ``nearest_name`` **不动**：由 IDW 耗时场回填，与点数无关。

    就地更新并入参 `stats`（调用方已持有该 list），返回同一对象便于链式使用。
    """
    counts: Dict[str, int] = {}
    for p in points:
        key = str(p.get("category"))
        counts[key] = counts.get(key, 0) + 1
    for s in stats:
        cat = str(s.get("category"))
        n = counts.get(cat, 0)
        s["in_circle"] = n
        ideal = (CATEGORY_DEFS.get(cat) or {}).get("ideal_circle") or 1
        s["coverage"] = round(min(1.0, n / ideal), 4)
    return stats


def check_poi_conservation(poi: Dict[str, Any]) -> Optional[str]:
    """点数守恒判据：``sum(categories[].in_circle) == len(points)``。合规返回 ``None``。

    **唯一实现**（阶段 1.4 / 阶段 3 的契约测试与 `lc_healthcheck` D 段都走它），
    避免「判据在生产侧和测试侧各写一份」——`sum(in_circle)` 此前只出现在
    `assemble.py` 与体检脚本里，测试侧 0 处，100+ 条生活圈测试全部绕开了真正会坏的不变量。

    违规时返回**可读**的差异描述（含逐类差额）：只说「不相等」不够，
    必须让「哪个类被砍掉了多少」一眼可见，否则排查又回到数点位上。
    """
    cats = poi.get("categories") or []
    pts = poi.get("points") or []
    declared = sum(int(c.get("in_circle") or 0) for c in cats)
    actual = len(pts)
    if declared == actual:
        return None
    by_cat: Dict[str, int] = {}
    for p in pts:
        key = str(p.get("category"))
        by_cat[key] = by_cat.get(key, 0) + 1
    diff = [
        f"{c.get('category')}: 声明 {int(c.get('in_circle') or 0)} / 实到 {by_cat.get(str(c.get('category')), 0)}"
        for c in cats
        if int(c.get("in_circle") or 0) != by_cat.get(str(c.get("category")), 0)
    ]
    detail = "；".join(diff) if diff else "逐类求和自洽但总数不符（类别键不匹配？）"
    return (
        f"汇总 {declared} ≠ 点位数 {actual}（差 {actual - declared}）；"
        f"逐类不一致：{detail}"
    )


def _point_confidence(it: Dict[str, Any]) -> float:
    """点位置信度：偏好采集方显式写入的 ``_confidence``，缺省用判表 `evaluate_category` 派生。

    返回 0..1 数值作为排序键；异常值收敛到 0.5 中性档，保证排序稳定不抛。
    """
    raw = it.get("_confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    try:
        _cat, conf = evaluate_category(it)
        return float(conf)
    except Exception:  # noqa: BLE001  判表异常不应让展示层崩溃
        return 0.5


def nearest_for(point: Tuple[float, float], points: Sequence[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    """点到点集最近距离（米），无点返回 None。"""
    best_d = None
    best_p = None
    for p in points:
        d = haversine_m(point, p)
        if best_d is None or d < best_d:
            best_d = d
            best_p = p
    if best_d is None:
        return None
    return {"distance_m": best_d, "point": best_p}