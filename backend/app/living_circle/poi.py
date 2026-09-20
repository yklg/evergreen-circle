"""民生 POI：类别表 / 多关键词采集 / 清洗去重 / 分类覆盖统计。

三大口径（与前端 F0 契约 / 赛题一致）：
  - 8 类民生类别 → `FacilityCategoryStat[]`（category/total/in_circle/coverage/min_minutes/nearest）
  - 盲区三要素（菜市场/药店/小学）→ 独立 POI 点集，供 blindspot.py 做 1km 判定
采集策略：每类多关键词查全率（百度 place/v2/search），名称归一 + 50m 聚簇去重。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.living_circle.geo_utils import haversine_m, point_in_ring, round_lnglat
from app.living_circle.scope import SpatialScope

# ── 民生类别表（category 键与前端 fixture 保持一致）───────
# keywords：百度 place 检索关键词组（多词查全率）；ideal_circle：圈内理想阈值（评分基准）
CATEGORY_DEFS: Dict[str, Dict[str, Any]] = {
    "market": {
        "label": "菜市场",
        "keywords": ["菜市场", "农贸市场", "生鲜市场"],
        "is_market": True,
        "ideal_circle": 3,
    },
    "medical": {
        "label": "医疗",
        "keywords": ["社区医院", "诊所", "社区卫生服务中心"],
        "ideal_circle": 3,
    },
    "education": {
        "label": "教育",
        "keywords": ["小学", "中学", "幼儿园"],
        "ideal_circle": 3,
    },
    "shopping": {
        "label": "购物",
        "keywords": ["超市", "便利店", "综合商场"],
        "ideal_circle": 3,
    },
    "elderly": {"label": "养老", "keywords": ["养老院", "日间照料中心"], "ideal_circle": 1},
    "finance": {"label": "金融", "keywords": ["银行"], "ideal_circle": 1},
    "recreation": {"label": "文体", "keywords": ["公园", "健身中心"], "ideal_circle": 1},
    "service": {"label": "政务", "keywords": ["政务服务中心", "邮政所"], "ideal_circle": 1},
}

# 盲区三要素（赛题硬判口径：1km 内无菜市场/药店/小学）
TRIAD_KEYWORDS: Dict[str, str] = {
    "market": "菜市场",
    "pharmacy": "药店",
    "primary": "小学",
}


def norm_name(name: str) -> str:
    """名称归一：去空白/停用后缀/全角转半角 → 用作聚簇主键辅助。"""
    if not name:
        return ""
    s = re.sub(r"[\s\u3000]+", "", name)
    s = re.sub(r"（.*?）|\(.*?\)", "", s)
    return s.lower()


def _dedupe(items: List[Dict[str, Any]], radius_m: float = 50.0) -> List[Dict[str, Any]]:
    """坐标聚簇去重：o(n²) 在小样本下足够（每类 ≤ 几十条）；半径内保留先到者。"""
    kept: List[Dict[str, Any]] = []
    for it in items:
        dup = False
        for k in kept:
            if haversine_m((it["lng"], it["lat"]), (k["lng"], k["lat"])) < radius_m:
                dup = True
                break
        if not dup:
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
    return _dedupe(out, dedupe_radius_m)


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
    cap_per_cat: int = 25,
) -> List[Dict[str, Any]]:
    """原始 POI → 报告点位（真实坐标，供前端 BMapGL 渲染，对齐 PoiPoint 契约）。

    - **只输出可达区内的点**（圈外不展示、不进报告）：旧实现把 2km 采集圈内的点全量输出，
      实测 151 条里只有 18 条在圈内（88% 圈外），展示层只按条数截断 ⇒ 用户看到「圈外地点被检索出来」。
    - 每类排序键 = 「圈内有耗时优先 → 有耗时优先 → **距离近**优先」后截断 ``cap_per_cat`` 条。
      旧实现第三键是**名称字母序** ⇒ 留下的是「按名字挑的点」而不是「离得近的点」。
    - ``center`` 是**查询中心**（必传）：距离以它为参照，不能用可达区环的顶点（环顶点顺序随
      ``linspace`` 行进方向而定，拿 `ring[0]` 当圆心会让「最近的设施」变成「离某个顶点最近的设施」）。
    - ``id`` 稳定可溯源（``poi-{category}-{idx}``）；``lnglat`` 输出 BD-09 ``[lng, lat]``。
    """
    reach_ring = scope.reach_ring
    points: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        times = times_by_cat.get(cat, [])
        entries: List[Dict[str, Any]] = []
        for idx, it in enumerate(items):
            t = times[idx] if idx < len(times) else None
            in_reach = point_in_ring((it["lng"], it["lat"]), reach_ring)
            if not in_reach:
                continue  # 圈外点：不展示、不进报告、不计分
            entries.append({
                "id": f"poi-{cat}-{idx}",
                "name": it.get("name") or (CATEGORY_DEFS.get(cat, {}).get("label", cat)),
                "category": cat,
                "lnglat": [round(it["lng"], 6), round(it["lat"], 6)],
                "minutes": round(t, 1) if t is not None else None,
                "in_circle": True,
                "_distance_m": haversine_m((it["lng"], it["lat"]), center),
            })
        entries.sort(key=lambda p: (p["minutes"] is None, p["_distance_m"]))
        for p in entries[:cap_per_cat]:
            p.pop("_distance_m", None)
            points.append(p)
    return points


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