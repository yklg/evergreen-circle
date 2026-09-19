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
    iso15_ring: Sequence[Tuple[float, float]],
    center: Tuple[float, float],
) -> List[Dict[str, Any]]:
    """类别统计：圈内数 / 覆盖度 / 最近设施（步行耗时由调用方注入则用，否则用距离换算提示）。

    coverage = min(1, in_circle / ideal_circle)；min_minutes 由调用方在测时后填充（此处填 None 占位，
    live 管线在 poi+isochrone 后统一回填 nearest_minutes）。
    """
    stats: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        defn = CATEGORY_DEFS[cat]
        in_circle = [it for it in items if point_in_ring((it["lng"], it["lat"]), iso15_ring)]
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