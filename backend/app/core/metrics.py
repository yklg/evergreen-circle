"""量化提升 + 业务闭环指标（对应需求 17/19）。

所有指标基于真实运行数据计算，公式透明、基线可配置并标注，便于向评委解释。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.fetcher import domain_of

# ── 可配置基线（披露为「行业经验值」，演示时透明说明）──────────
# 人工对每个信息源做竞品分析的平均耗时（分钟）
MANUAL_MIN_PER_SOURCE = 8
# 人工竞品分析通常覆盖的独立信息源数（基线）
BASELINE_MANUAL_SOURCES = 6


def compute_report_metrics(
    *,
    brands: List[str],
    focus: List[str],
    claims: List[Dict[str, Any]],
    evidences: List[Any],
    structured: Dict[str, Any],
    elapsed_seconds: float,
    tokens_used: int,
    rework_rounds: int = 0,
    issues_resolved: int = 0,
    objective_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    indep_domains = len({domain_of(getattr(e, "source_url", "")) for e in evidences
                         if getattr(e, "source_url", "")} - {""})
    platforms = len({getattr(e, "source_type", "") for e in evidences} - {""})
    total_claims = len(claims) or 1
    high_conf = sum(1 for c in claims if c.get("confidence") == "high")
    cross_validated = sum(1 for c in claims if c.get("cross_validated"))
    claims_with_evidence = sum(1 for c in claims if c.get("evidence_ids"))

    elapsed_min = max(0.1, elapsed_seconds / 60.0)
    manual_min = max(1, len(brands) * max(1, len(focus)) * MANUAL_MIN_PER_SOURCE)

    # v2.1 客观性指标（只读组字段；与 audit.evaluate_quality 口径一致）
    ev_by_id = {getattr(e, "evidence_id", ""): e for e in evidences}
    single_source = 0
    for c in claims:
        ids = c.get("evidence_ids") or []
        groups_ = {getattr(ev_by_id.get(i), "source_group", "") or i
                   for i in ids if i in ev_by_id}
        if len(groups_) < 2:
            single_source += 1
    single_source_ratio = round(single_source / total_claims, 3)
    viral_n = sum(1 for e in evidences if getattr(e, "viral", False))
    viral_ratio = round(viral_n / (len(evidences) or 1), 3)
    ost = objective_stats or {}
    viral_checked_ratio = round((ost.get("viral_checked", 0) or 0) / (len(evidences) or 1), 3)

    # 效率提升倍数（人工估时 / 实际耗时）
    efficiency_multiple = round(manual_min / elapsed_min, 1)

    # 覆盖度倍数（实际独立信源 / 人工基线信源）
    coverage_multiple = round(indep_domains / BASELINE_MANUAL_SOURCES, 1) if BASELINE_MANUAL_SOURCES else 0

    # 一致性（结构化程度）= 0.5×挂证据claim比 + 0.5×schema填充率
    from app.core.schemas import schema_completeness
    sc = schema_completeness(structured)
    consistency = round(0.5 * (claims_with_evidence / total_claims) + 0.5 * sc, 3)

    # 准确率 = 高置信占比
    accuracy = round(high_conf / total_claims, 3)
    cross_ratio = round(cross_validated / total_claims, 3)

    return {
        # 效率
        "efficiency": {
            "elapsed_seconds": round(elapsed_seconds, 1),
            "elapsed_minutes": round(elapsed_min, 1),
            "manual_estimate_minutes": manual_min,
            "efficiency_multiple": efficiency_multiple,
            "tokens_used": tokens_used,
            "formula": "人工估时(品牌数×维度数×8分钟/源) ÷ 实际耗时",
            "baseline_note": f"基线：人工每信息源约 {MANUAL_MIN_PER_SOURCE} 分钟（行业经验值，可配置）",
        },
        # 覆盖度
        "coverage": {
            "independent_sources": indep_domains,
            "platforms_covered": platforms,
            "evidence_total": len(evidences),
            "coverage_multiple": coverage_multiple,
            "baseline_sources": BASELINE_MANUAL_SOURCES,
            "formula": "实际独立信源数 ÷ 人工基线信源数(6)",
        },
        # 一致性（结构化）
        "consistency": {
            "value": consistency,
            "claims_with_evidence_ratio": round(claims_with_evidence / total_claims, 3),
            "schema_completeness": sc,
            "formula": "0.5×挂证据论点比 + 0.5×结构化Schema填充率",
        },
        # 业务闭环指标
        "business": {
            "accuracy": accuracy,                       # 准确率=高置信占比
            "cross_validated_ratio": cross_ratio,        # 交叉验证占比
            "dimension_coverage": None,                  # 由 quality 注入
            "brand_coverage": None,                      # 由 quality 注入
            "correction_rate": None,                     # 由人工反馈注入
            "rework_rounds": rework_rounds,
            "issues_resolved": issues_resolved,
            # v2.1 客观性指标
            "single_source_ratio": single_source_ratio,
            "viral_ratio": viral_ratio,
            "viral_checked_ratio": viral_checked_ratio,
            "formula": "准确率=高置信论点÷总论点；人工修正率=被编辑块÷可编辑块（用户反馈后更新）；"
                       "单源占比=信源组<2 的结论占比；过热占比=viral 证据÷证据总数",
        },
    }


def merge_quality_into_metrics(metrics: Dict[str, Any], quality: Dict[str, Any]) -> Dict[str, Any]:
    """把质检报告的覆盖率合并进 metrics.business。"""
    if not metrics or not quality:
        return metrics
    biz = metrics.setdefault("business", {})
    biz["dimension_coverage"] = quality.get("dimension_coverage_rate")
    biz["brand_coverage"] = quality.get("brand_coverage_rate")
    return metrics


def apply_feedback(metrics: Dict[str, Any], edited_blocks: int, total_blocks: int) -> Dict[str, Any]:
    """用户反馈后更新人工修正率。"""
    biz = metrics.setdefault("business", {})
    if total_blocks > 0:
        biz["correction_rate"] = round(edited_blocks / total_blocks, 3)
        biz["edited_blocks"] = edited_blocks
        biz["total_blocks"] = total_blocks
    return metrics
