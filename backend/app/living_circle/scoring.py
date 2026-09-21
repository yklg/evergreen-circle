"""体检评分（可解释四维模型，全确定性计算）。

四大分项 → 0-100 综合：
  - 设施覆盖度（40%）：Σ min(1, in_circle/ideal) / 类别数 ×100
  - 可达性（25%）：各类别最近设施平均耗时的达标度（20min 线性）
  - 多样性（20%）：圈内有覆盖的类别占比
  - 均衡性（15%）：各类别覆盖与理想阈值的最大短板惩罚
输出契约 `LifeCircleScores`：total / radar[] / bars[] / triads[] / note。
M 阶段 LLM 仅做解读文案；本模块为无 Key 时的确定性分数来源（D4 规则模板）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.living_circle.caliber import get_caliber

WEIGHTS = {"coverage": 0.40, "reachability": 0.25, "diversity": 0.20, "balance": 0.15}
BLINDSPOT_PENALTY_CAP = 12.0  # 盲区扣分上限（赛题口径）

REACH_FULL_MIN = get_caliber("walking").reach_full_min  # 20min 内步行可达视为可达性满分


def _cat_score(coverage: float, min_minutes: float | None) -> float:
    """单类别维度分：覆盖 + 可达各半。"""
    cov = coverage * 100.0
    if min_minutes is None:
        reach = 0.0
    else:
        reach = max(0.0, (1.0 - max(0.0, min_minutes) / REACH_FULL_MIN) * 100.0)
    return round(0.7 * cov + 0.3 * reach, 1)


def compute_scores(
    categories: List[Dict[str, Any]],
    triads: List[Dict[str, Any]],
    blindspot_count: int,
) -> Dict[str, Any]:
    """由类别统计 + 三要素结论计算评分（纯函数，单测直接喂构造数据）。"""
    n = len(categories) or 1
    coverage_terms = [min(1.0, c.get("coverage", 0.0)) for c in categories]
    cov_dim = round(sum(coverage_terms) / n * 100.0, 1)

    reach_terms: List[float] = []
    for c in categories:
        mm = c.get("min_minutes")
        if mm is not None:
            reach_terms.append(max(0.0, (1.0 - max(0.0, float(mm)) / REACH_FULL_MIN) * 100.0))
    reach_dim = round(sum(reach_terms) / len(reach_terms), 1) if reach_terms else 0.0

    diversity_dim = round(len([1 for c in categories if c.get("in_circle", 0) > 0]) / n * 100.0, 1)

    worst_gap = max((1.0 - min(1.0, c.get("coverage", 0.0))) for c in categories) if categories else 1.0
    balance_dim = round((1.0 - worst_gap) * 100.0, 1)

    total = round(
        100.0
        * (
            WEIGHTS["coverage"] * (cov_dim / 100.0)
            + WEIGHTS["reachability"] * (reach_dim / 100.0)
            + WEIGHTS["diversity"] * (diversity_dim / 100.0)
            + WEIGHTS["balance"] * (balance_dim / 100.0)
        ),
        1,
    )
    # 盲区惩罚（赛题口径：盲区多则总分扣减，封顶 BLINDSPOT_PENALTY_CAP 分）
    total -= min(BLINDSPOT_PENALTY_CAP, max(0.0, blindspot_count - 1) * 4.0)
    total = max(0.0, min(100.0, round(total, 1)))

    radar = [
        {"dimension": c.get("label", c.get("category", "")), "score": _cat_score(c.get("coverage", 0.0), c.get("min_minutes"))}
        for c in categories
    ]
    bars = [
        {"category": c.get("category"), "label": c.get("label"), "value": round(min(1.0, c.get("coverage", 0.0)) * 100.0)}
        for c in categories
    ]
    note = (
        f"确定性评分：覆盖 {cov_dim} / 可达 {reach_dim} / 多样 {diversity_dim} / 均衡 {balance_dim}"
        + (f"；{blindspot_count} 处盲区扣分 {min(12.0, max(0.0, blindspot_count - 1) * 4.0):.1f}" if blindspot_count > 1 else "")
    )
    return {
        "total": total,
        "radar": radar,
        "bars": bars,
        "triads": triads,
        "note": note,
    }


def triad_from_points(
    market: List[Dict[str, Any]],
    pharmacy: List[Dict[str, Any]],
    primary: List[Dict[str, Any]],
    field_fn,
) -> List[Dict[str, Any]]:
    """三要素覆盖结论（供 live 管线）：最近设施名 + 耗时。"""
    out: List[Dict[str, Any]] = []
    for label, items in (
        ("菜市场", market),
        ("药店", pharmacy),
        ("小学", primary),
    ):
        best = None
        best_m = None
        for it in items:
            m = field_fn((it["lng"], it["lat"]))
            if m is None:
                continue
            if best_m is None or m < best_m:
                best_m = m
                best = it
        out.append({
            "facility": label,
            "covered": best_m is not None,
            "nearest_name": best.get("name") if best else None,
            "nearest_minutes": round(best_m, 1) if best_m is not None else None,
        })
    return out