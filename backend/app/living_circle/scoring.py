"""体检评分（可解释四维模型，全确定性计算）。

四大分项 → 0-100 综合：
  - 设施覆盖度（40%）：Σ min(1, in_circle/ideal) / 类别数 ×100
  - 可达性（25%）：各类别最近设施平均耗时的达标度（20min 线性）
  - 多样性（20%）：圈内有覆盖的类别占比
  - 均衡性（15%）：各类别覆盖与理想阈值的最大短板惩罚
输出契约 `LifeCircleScores`：total / radar[] / bars[] / triads[] / note。
盲区惩罚按**判定覆盖率**外推条数后再扣（`judged_share`），并落 `confidence` + `evidence`
举证 —— 覆盖率低意味着「判不出盲区」不再等于「没有盲区」，分数必须为此付账。
M 阶段 LLM 仅做解读文案；本模块为无 Key 时的确定性分数来源（D4 规则模板）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.living_circle.caliber import get_caliber

WEIGHTS = {"coverage": 0.40, "reachability": 0.25, "diversity": 0.20, "balance": 0.15}
BLINDSPOT_PENALTY_CAP = 12.0  # 盲区扣分上限（赛题口径）
BLINDSPOT_PENALTY_PER_EXTRA = 4.0  # 每多一处（外推）盲区扣 4 分，首处不扣

# 判定覆盖率下限：外推倍数封顶 `1 / JUDGE_SHARE_FLOOR = 5`。
# 为什么要设下限而不是直接除：覆盖率可以低到 0（凯里实测 5/97 ≈ 5%），无下限则
# 「判不了」会被放大成无限扣分 —— 而「判不了」是**数据缺口**，不是「这里全是盲区」。
JUDGE_SHARE_FLOOR = 0.2

# 「判定面完整」的容差：浮点覆盖率 0.9999999 不该被降级成 limited。
FULL_JUDGE_SHARE_TOL = 1e-6

REACH_FULL_MIN = get_caliber("walking").reach_full_min  # 20min 内步行可达视为可达性满分


def _cat_score(coverage: float, min_minutes: float | None) -> float:
    """单类别维度分：覆盖 + 可达各半。"""
    cov = coverage * 100.0
    if min_minutes is None:
        reach = 0.0
    else:
        reach = max(0.0, (1.0 - max(0.0, min_minutes) / REACH_FULL_MIN) * 100.0)
    return round(0.7 * cov + 0.3 * reach, 1)


def _blindspot_penalty(
    blindspot_count: int, judged_share: Optional[float]
) -> Tuple[float, float]:
    """把「实测盲区数 + 判定覆盖率」换算成 (外推盲区数, 扣分)。

    外推 = 条数 / 覆盖率（比率估计）。它纠正的是一条**反向激励**：证据面越小，判出的
    盲区越少，而旧口径只按条数扣分 ⇒ 「少采集」直接奖励成「高分」。

    ⚠️ 已知偏置方向：比率估计假定**已判定面有代表性**。而判不了的都是可达区外沿，
    那里恰恰更稀疏 ⇒ 该估计**系统性偏乐观**。所以它只用于扣分，**绝不**写进
    `blindspot_count` / 盲区清单（清单严格证据有界，不伪造多边形）。
    """
    count = max(0, int(blindspot_count))
    if judged_share is None:
        expected = float(count)      # 覆盖率未知 ⇒ 退回按条数计（不猜、不放大）
    else:
        # 上限钳到 1：覆盖率若因调用方 bug >100%，只会让扣分变少 —— 正是本函数要防的方向
        share = min(float(judged_share), 1.0)
        expected = count / max(share, JUDGE_SHARE_FLOOR)
    penalty = min(BLINDSPOT_PENALTY_CAP, max(0.0, expected - 1.0) * BLINDSPOT_PENALTY_PER_EXTRA)
    return round(expected, 2), round(penalty, 1)


def compute_scores(
    categories: List[Dict[str, Any]],
    triads: List[Dict[str, Any]],
    blindspot_count: int,
    *,
    judged_share: Optional[float] = None,
    evidence_complete: bool = True,
) -> Dict[str, Any]:
    """由类别统计 + 三要素结论计算评分（纯函数，单测直接喂构造数据）。

    ``judged_share`` 是本次判盲的**判定覆盖率**（``cells_judged / cells_inside``）。
    缺省 ``None`` = 调用方没提供覆盖率 ⇒ 按条数计扣、``confidence="limited"``；既有单测
    零改动通过，但活管线必须传（`assemble.py`）。
    """
    n = len(categories) or 1
    coverage_terms = [min(1.0, c.get("coverage", 0.0)) for c in categories]
    cov_dim = round(sum(coverage_terms) / n * 100.0, 1)

    reach_terms: List[float] = []
    # 「圈内一个可达设施都没有」的类别 ⇒ `min_minutes is None` ⇒ **不进可达维度平均**。
    # 少掉的是 0 分项，所以这条会让 `reach_dim` 变好 —— 必须在 note 里说明，否则读起来像
    # 「修个 bug 把分修高了」（泄漏 A 修正的副产物，计划「会变动的数字」表已预判该方向）。
    no_reach_labels = [
        str(c.get("label") or c.get("category") or "")
        for c in categories
        if c.get("min_minutes") is None
    ]
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
    # 盲区惩罚（赛题口径：盲区多则总分扣减，封顶 BLINDSPOT_PENALTY_CAP 分）。
    # 条数先按**判定覆盖率**外推 —— 判了 5% 的面报出 2 处，不等于整片只该扣 2 处的分。
    expected_blindspots, penalty = _blindspot_penalty(blindspot_count, judged_share)
    total -= penalty
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
    )
    if no_reach_labels:
        joined = "、".join(lbl for lbl in no_reach_labels if lbl)
        note += f"；{len(no_reach_labels)} 类圈内无可达设施（{joined}）不计入可达维度 ⇒ 可达维度偏高"
    if penalty > 0:
        if judged_share is not None and expected_blindspots > blindspot_count:
            note += (
                f"；判定覆盖率 {judged_share:.0%} 内实测 {blindspot_count} 处盲区"
                f" ⇒ 外推约 {expected_blindspots:.1f} 处，扣分 {penalty:.1f}"
                f"（盲区清单仍只列有据的那 {blindspot_count} 处，外推值不参与清单；"
                f"未判定面多在可达区外沿、通常更稀疏 ⇒ 该外推偏乐观）"
            )
        else:
            note += f"；{blindspot_count} 处盲区扣分 {penalty:.1f}"

    # 置信度：判定面不完整，或采集证据本身有缺口（截断/饿死/熔断）⇒ limited。
    limited = (
        judged_share is None
        or judged_share < 1.0 - FULL_JUDGE_SHARE_TOL
        or not evidence_complete
    )
    return {
        "total": total,
        "radar": radar,
        "bars": bars,
        "triads": triads,
        "note": note,
        "confidence": "limited" if limited else "full",
        # 扣分口径的证据链：`penalty_applied` 必须能由
        # (blindspot_count, judged_share, JUDGE_SHARE_FLOOR) 精确复算 —— 契约判据 B11 读它，
        # 拦的就是「把扣分悄悄改回只按条数」这类回退。
        "evidence": {
            "judged_share": (None if judged_share is None else round(float(judged_share), 4)),
            "expected_blindspots": expected_blindspots,
            "penalty_applied": penalty,
        },
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