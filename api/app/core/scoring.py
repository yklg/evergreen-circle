"""景点榜单与评估维度评分（stdlib 叶子模块）：LLM 只抽信号，分数全部由本模块公式算出。

设计约束（与 research_types 同一层规约）：
- **纯函数、确定性**：同一输入两次调用结果全等（可复现、可审计），禁止 random/time/网络。
- **sanitize 在边界**：LLM 抽取的信号可能含负数/None/非数值/越界占比，统一收敛到
  [0, +inf)（占比类收敛到 [0,1]），非法值按 0 计——不抛错、不遮盖（清洗结果随
  `signals_clean` 回传，榜单可展示计算明细）。
- 权重是模块常量：声量 0.4 / 口碑 0.4 / 性价比 0.2；归一化用 max 缩放（榜内相对分）。
- **评估类算分同一范式**：枚举（full/none、low/high…）与权重全部声明在 SCORE_FORMULAS，
  LLM 不得参与打分；任一维度输入不足 → 不出分（None），调用方据此跳过图表。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WEIGHT_VOICE = 0.4
WEIGHT_SENTIMENT = 0.4
WEIGHT_VALUE = 0.2

# 三类信号 → (原始字段, 是否占比类[0,1])。占比类不做 max 缩放，直接加权。
_SIGNAL_DEFS: Tuple[Tuple[str, str, bool], ...] = (
    ("voice", "mentions", False),
    ("sentiment", "positive_ratio", True),
    ("value", "value_score", False),
)

SCORE_MIN = 0.0
SCORE_MAX = 100.0


def _to_number(raw: Any) -> float:
    """非法/缺失/负数一律按 0 计（bool 视为非法——True 不该等于 1 分信号）。"""
    if isinstance(raw, bool) or raw is None:
        return 0.0
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if val != val:  # NaN
        return 0.0
    return max(0.0, val)


def _clamp_ratio(val: float) -> float:
    return min(max(val, 0.0), 1.0)


def sanitize_signals(row: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    """把一条榜单原始信号收敛为三类规范信号 {"voice","sentiment","value"} → float。

    输入兼容两种形状：row["signals"] 嵌套字典，或 row 顶层直接给字段（LLM 常见漂移）。
    """
    src: Dict[str, Any] = {}
    nested = row.get("signals")
    if isinstance(nested, Mapping):
        src.update(dict(nested))
    for _, field, _ in _SIGNAL_DEFS:
        src.setdefault(field, row.get(field))

    out: Dict[str, float] = {}
    voice = _to_number(src.get("mentions"))
    positive = _clamp_ratio(_to_number(src.get("positive_ratio")))
    value = _clamp_ratio(_to_number(src.get("value_score")))
    out["voice"] = voice
    out["sentiment"] = positive
    out["value"] = value
    return out


def rank_spots(rows: Sequence[Mapping[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    """对景点原始行（含 signals）做归一化加权评分并降序截断。

    返回行 = 原行浅拷贝 + signals_clean（三类规范信号）+ dims（归一化后各维分）
    + score（0-100，保留 1 位小数）。平局按归一化名称再按原序升序，保证稳定。

    归一化规则：
    - voice / value 中 value 视为 [0,1] 相对分直接缩放；voice 按榜内 max 缩放（max=0 时全体 0）。
    - sentiment / value 已是占比，直接 ×100。
    """
    cleaned: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        item = dict(row)
        item["signals_clean"] = sanitize_signals(row)
        item["_orig_idx"] = idx
        cleaned.append(item)

    max_voice = max((c["signals_clean"]["voice"] for c in cleaned), default=0.0)
    for c in cleaned:
        sig = c["signals_clean"]
        voice_norm = (sig["voice"] / max_voice) if max_voice > 0 else 0.0
        dims = {
            "voice": round(voice_norm * 100.0, 1),
            "sentiment": round(sig["sentiment"] * 100.0, 1),
            "value": round(sig["value"] * 100.0, 1),
        }
        score = (WEIGHT_VOICE * dims["voice"]
                 + WEIGHT_SENTIMENT * dims["sentiment"]
                 + WEIGHT_VALUE * dims["value"])
        c["dims"] = dims
        c["score"] = round(min(max(score, SCORE_MIN), SCORE_MAX), 1)
        c["rank"] = 0  # 排序后回填

    cleaned.sort(key=lambda c: (-c["score"], str(c.get("name") or ""), c["_orig_idx"]))
    out: List[Dict[str, Any]] = []
    for rank, c in enumerate(cleaned[:max(0, top_n)], start=1):
        c["rank"] = rank
        c.pop("_orig_idx", None)
        out.append(c)
    return out


# ── 评估类算分（assessment）────────────────────────────────
# 权重与枚举映射表都是模块常量（与榜单三权同一写法）：图表文案、glossary 与测试
# 都引用这些常量——改数值必须先改文案，由测试钉死「声明即公式」。
WEIGHT_DURATION = 0.6   # 可达性：耗时权重（耗时比票价更决定出行体验）
WEIGHT_COST = 0.4       # 可达性：费用权重

COVERAGE_RATIO: Dict[str, float] = {"full": 1.0, "partial": 0.5, "none": 0.0}
RISK_LEVEL_SCORE: Dict[str, float] = {"low": 20.0, "medium": 50.0, "high": 80.0}

SCORE_FORMULAS: Dict[str, Dict[str, Any]] = {
    "accessibility": {"duration": WEIGHT_DURATION, "cost": WEIGHT_COST},
    "amenity": dict(COVERAGE_RATIO),
    "risk": dict(RISK_LEVEL_SCORE),
}


def _optional_number(raw: Any) -> Optional[float]:
    """与 _to_number 同款清洗，但**非法即 None**——用于「输入不足不出分」判定。

    区别是刻意的：_to_number 把非法值按 0 计（信号缺省不拉低榜单），而评估类算分
    里「未知」与「0」语义不同（未知耗时不得按 0 分钟参与，否则用假数据抬高得分）。
    只收敛下界不收敛上界：原始量各带量纲（分钟/元），值域收敛由评分侧负责。
    """
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN
        return None
    return max(0.0, val)


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 与 dataclass 两类入参（claims 是 dict、evidences 是 Evidence）。"""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def weighted_score(signals: Mapping[str, Any], weights: Mapping[str, float],
                   ) -> Tuple[Optional[float], Dict[str, Dict[str, float]]]:
    """通用加权入口：score = Σ(weight_i × value_i)，value 先收敛到 [0, 100]。

    只对 signals 与 weights **同时具备且值合法**的维度计分：缺维度/非法值不计分、
    也不按 0 拉低（「未知」与「0」语义不同）；无任何可用维度 → (None, {})。
    breakdown 逐维返回 {value, weight, contribution} 明细，供图内展开与审计。
    权重是否归一由调用方负责——声明的公式就是公式，本函数不做重归一。
    """
    breakdown: Dict[str, Dict[str, float]] = {}
    total = 0.0
    for dim, weight in (weights or {}).items():
        if not isinstance(signals, Mapping) or dim not in signals:
            continue
        value = _optional_number(signals.get(dim))
        if value is None:
            continue
        value = min(value, SCORE_MAX)   # 信号是分数，越界值收敛到评分域
        w = _to_number(weight)
        total += value * w
        breakdown[str(dim)] = {"value": round(value, 1), "weight": round(w, 4),
                               "contribution": round(value * w, 1)}
    if not breakdown:
        return None, {}
    return round(min(max(total, SCORE_MIN), SCORE_MAX), 1), breakdown


def score_accessibility(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """按交通方式拆解可达性并合成 0-100 分（assessment 可达性章算分）。

    输入 = access_matrix 全量行 [{destination, routes:[{mode, duration_minutes, cost_yuan}]}]。
    - 一个交通方式须**同时**具备 duration_minutes 与 cost_yuan 才计分；任一缺失该方式
      整条跳过（不按 0 参与，「未知」不得当假数据用）；同方式多条路线取各自最优（min）。
    - 耗时/费用越小越好，按**方式内报告相对分**折算：min/x × 100（该方式在本次报告内的
      最优路线即 100 分），与 rank_spots 的榜内 max 缩放同一相对分语义。
    - 方式分 = 时间分与费用分按 SCORE_FORMULAS["accessibility"] 经 weighted_score 合成。
    返回 [{destination, score, modes:{方式:分}, breakdown:{方式:{score,dims,原始值}}}]，
    按输入序；全部方式被跳过者整行省略；全无 → []（调用方据此不出图，降级契约）。
    """
    dest_names: List[str] = []
    per_dest: List[Dict[str, Dict[str, float]]] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        dest = str(row.get("destination") or "").strip()
        if not dest:
            continue
        modes: Dict[str, Dict[str, float]] = {}
        for route in (row.get("routes") or []):
            if not isinstance(route, Mapping):
                continue
            mode = str(route.get("mode") or "").strip()
            dur = _optional_number(route.get("duration_minutes"))
            cost = _optional_number(route.get("cost_yuan"))
            if not mode or not dur or not cost:
                continue
            cur = modes.setdefault(mode, {"duration": dur, "cost": cost})
            cur["duration"] = min(cur["duration"], dur)
            cur["cost"] = min(cur["cost"], cost)
        dest_names.append(dest)
        per_dest.append(modes)

    # 方式内基线：该方式在本次报告中的最小耗时/最低费用（= 100 分基准）
    base: Dict[str, Dict[str, float]] = {}
    for modes in per_dest:
        for mode, val in modes.items():
            b = base.setdefault(mode, dict(val))
            b["duration"] = min(b["duration"], val["duration"])
            b["cost"] = min(b["cost"], val["cost"])

    weights = SCORE_FORMULAS["accessibility"]
    out: List[Dict[str, Any]] = []
    for dest, modes in zip(dest_names, per_dest):
        mode_scores: Dict[str, float] = {}
        breakdown: Dict[str, Any] = {}
        for mode, val in modes.items():
            b = base[mode]
            signals = {"duration": b["duration"] / val["duration"] * 100.0,
                       "cost": b["cost"] / val["cost"] * 100.0}
            score, dims = weighted_score(signals, weights)
            if score is None:
                continue
            mode_scores[mode] = score
            breakdown[mode] = {"score": score, "dims": dims,
                               "duration_minutes": round(val["duration"], 1),
                               "cost_yuan": round(val["cost"], 1)}
        if not mode_scores:
            continue
        out.append({
            "destination": dest,
            "score": round(sum(mode_scores.values()) / len(mode_scores), 1),
            "modes": mode_scores,
            "breakdown": breakdown,
        })
    return out


def score_amenity_coverage(items: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """配套覆盖度：full|partial|none 计数 → 覆盖率 0-100（assessment 配套章算分）。

    覆盖率 = Σ(COVERAGE_RATIO[coverage]) / 条目数 × 100——枚举→比例是**确定性映射**
    （表在 SCORE_FORMULAS["amenity"]），不是估算；未知/缺失 coverage 按 partial 计
    （与 schemas.coerce_amenity_checklist 的收敛口径一致）。空清单 → None（不出分）。
    """
    counts = {"full": 0, "partial": 0, "none": 0}
    for it in items or []:
        if not isinstance(it, Mapping):
            continue
        cov = str(it.get("coverage") or "").strip().lower()
        counts[cov if cov in counts else "partial"] += 1
    total = sum(counts.values())
    if not total:
        return None
    ratio = sum(COVERAGE_RATIO[k] * n for k, n in counts.items()) / total
    return {"total": total, "counts": counts, "coverage": round(ratio * 100.0, 1)}


def _risk_band(score: float) -> str:
    """综合风险分 → 分档标签（阈值取映射表相邻档中点，改表即改档，不另立常量）。"""
    lo = RISK_LEVEL_SCORE["low"]
    mid = RISK_LEVEL_SCORE["medium"]
    hi = RISK_LEVEL_SCORE["high"]
    if score < (lo + mid) / 2:
        return "low"
    if score < (mid + hi) / 2:
        return "medium"
    return "high"


def score_risk_level(items: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """风险画像 → 综合风险分 0-100（越高风险越大；assessment 安全章算分）。

    逐条按 RISK_LEVEL_SCORE（low|medium|high → 20|50|80，表在 SCORE_FORMULAS["risk"]；
    未知 level 按 medium，与 coerce 收敛口径一致）取值；同一维度多条先取均值，再按
    **等权**经 weighted_score 合成。空清单/条目全无 dimension → None（不出分）。
    返回 {score, level, counts, breakdown}：level 为综合分分档标签，breakdown 逐维给
    {level, value, weight, contribution}，供图内展开明细。
    """
    acc: Dict[str, List[float]] = {}
    levels: Dict[str, str] = {}
    counts = {"low": 0, "medium": 0, "high": 0}
    for it in items or []:
        if not isinstance(it, Mapping):
            continue
        dim = str(it.get("dimension") or "").strip()
        if not dim:
            continue
        lvl = str(it.get("level") or "").strip().lower()
        if lvl not in RISK_LEVEL_SCORE:
            lvl = "medium"
        counts[lvl] += 1
        acc.setdefault(dim, []).append(RISK_LEVEL_SCORE[lvl])
        levels.setdefault(dim, lvl)
    if not acc:
        return None
    signals = {dim: sum(vs) / len(vs) for dim, vs in acc.items()}
    equal_weight = 1.0 / len(signals)
    score, breakdown = weighted_score(signals, {dim: equal_weight for dim in signals})
    if score is None:
        return None
    for dim, row in breakdown.items():
        row["level"] = levels[dim]
    return {"score": score, "level": _risk_band(score), "counts": counts,
            "breakdown": breakdown}


def count_evidence_strength(claims: Sequence[Any], evidences: Sequence[Any],
                            ) -> Dict[str, Any]:
    """证据强度三指标（risk 章「证据强度计数」图数据源）。

    - evidence_total：被结论引用的**去重**证据条数（只计真实存在的 id，脏引用不计）
    - domains：被引用证据的独立域名数（domain 为空回退 source_type——同一信源不得
      因缺域名被拆成多条计数）
    - supported / unsupported / support_ratio：结论按「有据（正）· 无据存疑（反）」计

    计数类无「输入不足」语义——0 条证据本身就是可展示的事实，故恒返回完整字典
    （与算分函数「不足即 None」的降级契约相区分）。
    """
    ev_list = list(evidences.values()) if isinstance(evidences, Mapping) else list(evidences or [])
    by_id: Dict[str, Any] = {}
    for ev in ev_list:
        eid = str(_field(ev, "evidence_id") or "").strip()
        if eid:
            by_id[eid] = ev

    claims = list(claims or [])
    used: List[str] = []
    supported = 0
    for c in claims:
        valid = [str(e) for e in (_field(c, "evidence_ids") or [])
                 if str(e).strip() and str(e) in by_id]
        if valid:
            supported += 1
            used.extend(valid)

    used_ids = set(used)
    domains = {str(_field(by_id[i], "domain") or "").strip()
               or str(_field(by_id[i], "source_type") or "").strip() or i
               for i in used_ids}
    total = len(claims)
    return {
        "claims_total": total,
        "evidence_total": len(used_ids),
        "domains": len(domains),
        "supported": supported,
        "unsupported": total - supported,
        "support_ratio": round(supported / total, 4) if total else 0.0,
    }
