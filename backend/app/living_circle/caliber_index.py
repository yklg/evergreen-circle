"""生活圈口径索引层：将真实代码常量映射为机器可校验的标识符。

架构纪律：本模块只 import 生活圈子域内部模块（caliber/scoring/poi/blindspot/isochrone/report_contract），
绝不 import app.core.*；中文可读名归属各自模块，索引只做结构化组装。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# ── 视图数据结构 ────────────────────────────────────────
@dataclass(frozen=True)
class CaliberView:
    ref: str      # 规范键，如 "scoring::WEIGHTS.coverage"
    kind: str     # param | weight | category | triad | profile | field | callable | derived
    module: str   # 溯源模块
    label: str    # 中文可读名
    value: str    # 渲染后的实际值


# ── 命名空间集合（启动期注册用）──────────────────────────
NAMESPACES: FrozenSet[str] = frozenset({
    "caliber", "scoring", "poi", "blindspot", "isochrone", "report",
})

# ── 内部存储 ────────────────────────────────────────────
_INDEX: Dict[str, CaliberView] = {}


def _build_index() -> None:
    """从各模块遍历容器构建索引（不硬编码任何数值）。"""
    from app.living_circle import (
        blindspot,
        caliber,
        isochrone,
        poi,
        report_contract,
        scoring,
    )

    # 1. caliber :: DEFAULT_CALIBERS（出行方式 × 字段 + 派生属性）
    for mode, c in caliber.DEFAULT_CALIBERS.items():
        ns = f"caliber::{mode}"
        # 基础字段
        for fname in ("speed_m_per_min", "detour_k", "study_radius_m",
                       "iso_minutes", "reach_full_min", "basis"):
            val = getattr(c, fname, None)
            if val is not None:
                label = _caliber_field_label(fname)
                _INDEX[f"{ns}.{fname}"] = CaliberView(
                    ref=f"{ns}.{fname}", kind="param", module="caliber",
                    label=label, value=_fmt_caliber_value(fname, val),
                )
        # 派生属性
        for dname in ("innermost_radius_m", "reach_radius_bound_m",
                       "fine_band", "grid_n_for_standard"):
            val = getattr(c, dname, None)
            if val is not None:
                label = _caliber_derived_label(dname)
                _INDEX[f"{ns}.{dname}"] = CaliberView(
                    ref=f"{ns}.{dname}", kind="derived", module="caliber",
                    label=label, value=str(val),
                )

    # 2. scoring :: WEIGHTS
    for dim, w in scoring.WEIGHTS.items():
        _INDEX[f"scoring::WEIGHTS.{dim}"] = CaliberView(
            ref=f"scoring::WEIGHTS.{dim}", kind="weight", module="scoring",
            label=_scoring_dim_label(dim), value=str(w),
        )
    # BLINDSPOT_PENALTY_CAP
    cap = getattr(scoring, "BLINDSPOT_PENALTY_CAP", None)
    if cap is not None:
        _INDEX["scoring::BLINDSPOT_PENALTY_CAP"] = CaliberView(
            ref="scoring::BLINDSPOT_PENALTY_CAP", kind="param", module="scoring",
            label="盲区扣分上限", value=str(cap),
        )

    # 3. poi :: CATEGORY_DEFS / TRIAD_KEYWORDS
    for cat, defn in poi.CATEGORY_DEFS.items():
        _INDEX[f"poi::CATEGORY_DEFS.{cat}"] = CaliberView(
            ref=f"poi::CATEGORY_DEFS.{cat}", kind="category", module="poi",
            label=defn.get("label", cat),
            value=f"ideal_circle={defn.get('ideal_circle', '—')}",
        )
    for key, kw_list in poi.TRIAD_KEYWORDS.items():
        _INDEX[f"poi::TRIAD_KEYWORDS.{key}"] = CaliberView(
            ref=f"poi::TRIAD_KEYWORDS.{key}", kind="triad", module="poi",
            label=f"三要素·{key}", value=", ".join(kw_list),
        )
    # norm_name 作为 callable
    _INDEX["poi::norm_name"] = CaliberView(
        ref="poi::norm_name", kind="callable", module="poi",
        label="POI 名称归一", value="poi.norm_name()",
    )

    # 4. blindspot :: 常量
    for cname in ("BLIND_RADIUS_M", "BLIND_GRID_M", "SEV_HEAVY", "SEV_MEDIUM"):
        val = getattr(blindspot, cname, None)
        if val is not None:
            _INDEX[f"blindspot::{cname}"] = CaliberView(
                ref=f"blindspot::{cname}", kind="param", module="blindspot",
                label=_blindspot_label(cname), value=str(val),
            )
    # EFFORT_BY_DIST
    ebd = getattr(blindspot, "EFFORT_BY_DIST", None)
    if ebd:
        _INDEX["blindspot::EFFORT_BY_DIST"] = CaliberView(
            ref="blindspot::EFFORT_BY_DIST", kind="param", module="blindspot",
            label="补点努力系数", value=str(ebd),
        )

    # 5. isochrone :: MODE_PARAMS
    for mode, params in isochrone.MODE_PARAMS.items():
        for pname in ("grid_n", "smooth"):
            val = params.get(pname)
            if val is not None:
                _INDEX[f"isochrone::{mode}.{pname}"] = CaliberView(
                    ref=f"isochrone::{mode}.{pname}", kind="param",
                    module="isochrone", label=f"{mode}·{pname}", value=str(val),
                )

    # 6. report :: 契约字段 + reachable_count/sample_count
    live_required = getattr(report_contract, "_LIVE_REQUIRED", ())
    for fname in live_required:
        _INDEX[f"report::{fname}"] = CaliberView(
            ref=f"report::{fname}", kind="field", module="report_contract",
            label=f"报告字段·{fname}", value=f"living_circle.{fname}",
        )
    _INDEX["report::reachable_count"] = CaliberView(
        ref="report::reachable_count", kind="field", module="report_contract",
        label="可达采样点数", value="living_circle.reachable_count",
    )
    _INDEX["report::sample_count"] = CaliberView(
        ref="report::sample_count", kind="field", module="report_contract",
        label="总采样点数", value="living_circle.sample_count",
    )


def view(ref: str) -> Optional[CaliberView]:
    """按 ref 查视图；未知返回 None（由 expert_prompt._resolve_ref 兜底）。"""
    return _INDEX.get(ref)


def resolve(ref: str) -> CaliberView:
    """按 ref 查视图；未知抛 KeyError（由 expert_prompt.try/except 兜住）。"""
    v = _INDEX.get(ref)
    if v is None:
        raise KeyError(ref)
    return v


def all_refs() -> FrozenSet[str]:
    return frozenset(_INDEX.keys())


# 政策术语表：通用领域指标术语（不绑定具体代码常量，但属合法词汇）。
POLICY_TERMS: FrozenSet[str] = frozenset({
    "覆盖率", "可达率", "多样性", "均衡性", "密度", "配额", "占比",
    "采样点可达率", "名称归一与聚簇去重口径",
    "便捷度", "丰富度", "严谨性", "可复现性", "连续性", "烟火气", "韧性",
})


def terms() -> FrozenSet[str]:
    """词表闸：所有口径标识符的中文可读名集合 ∪ 政策术语。

    画像 prose 中出现的指标术语必须 ∈ terms()，否则视为编造。
    """
    return frozenset(v.label for v in _INDEX.values()) | POLICY_TERMS


def owning_experts(ref: str, experts: List[dict]) -> List[str]:
    """反向查：哪些专家的 caliber_refs 包含此 ref。"""
    return [e["id"] for e in experts if any(r["ref"] == ref for r in e.get("caliber_refs", []))]


def validate_vocabulary(text: str) -> List[str]:
    """词表闸校验：检查文本中的指标术语是否都在允许词表中。

    返回问题清单（空列表 = 通过）。
    允许词表 = terms() ∪ POLICY_TERMS（已由 terms() 合并）。

    注意：只校验明确的指标术语，不校验普通描述性文字。
    """
    problems: List[str] = []
    allowed = terms()

    # 精确匹配已知指标术语模式（避免误报普通描述）
    # 这些是真正的指标术语，而非包含"度/性/率"等字的普通词汇
    known_metric_patterns = {
        "覆盖率", "可达率", "多样性", "均衡性", "采样点可达率",
        "名称归一与聚簇去重口径", "测时成功率", "POI去重率", "数据完整率",
        "密度", "配额", "占比", "便捷度", "丰富度", "严谨性",
        "可复现性", "连续性", "烟火气", "韧性",
    }

    # 提取文本中出现的已知指标术语
    found_metrics = [m for m in known_metric_patterns if m in text]

    for term in sorted(found_metrics):
        if term not in allowed:
            problems.append(f"发现未授权指标术语：{term!r}（不在允许词表中）")

    return problems


# ── 辅助：中文标签映射（归属各自模块，不在索引里硬编码）───
def _caliber_field_label(fname: str) -> str:
    labels = {
        "speed_m_per_min": "步行速度",
        "detour_k": "绕行系数",
        "study_radius_m": "研究半径",
        "iso_minutes": "等时圈档位",
        "reach_full_min": "最大可达时间",
        "basis": "政策依据",
    }
    return labels.get(fname, fname)


def _caliber_derived_label(dname: str) -> str:
    labels = {
        "innermost_radius_m": "最内圈半径",
        "reach_radius_bound_m": "可达半径上界",
        "fine_band": "精细档位",
        "grid_n_for_standard": "标准网格数",
    }
    return labels.get(dname, dname)


def _fmt_caliber_value(fname: str, val: Any) -> str:
    if fname == "speed_m_per_min":
        return f"{val} m/min"
    if fname == "detour_k":
        return f"×{val}"
    if fname == "study_radius_m":
        return f"{val} m"
    if fname == "iso_minutes":
        return " / ".join(str(m) + "min" for m in val)
    if fname == "basis":
        return str(val)
    return str(val)


def _scoring_dim_label(dim: str) -> str:
    labels = {"coverage": "覆盖度", "reachability": "可达性",
              "diversity": "多样性", "balance": "均衡性"}
    return labels.get(dim, dim)


def _blindspot_label(cname: str) -> str:
    labels = {
        "BLIND_RADIUS_M": "盲区判定半径",
        "BLIND_GRID_M": "盲区网格间距",
        "SEV_HEAVY": "重度阈值",
        "SEV_MEDIUM": "中度阈值",
    }
    return labels.get(cname, cname)


# ── 启动期构建 ──────────────────────────────────────────
_build_index()
