"""质检与反馈闭环（对应需求 12：真实可触发的返工闭环）。

evaluate_quality：基于 claims/evidences/structured 计算可量化质量指标 + 暴露问题（Issue）。
decide_rework：根据质量指标决定是否打回 collect（补采）或 analyze（重分析），产出 Envelope。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.fetcher import domain_of
from app.core.models import Envelope
from app.core import research_types as RT
from app.core.research_types import DEFAULT_RESEARCH_TYPE


@dataclass
class QualityReport:
    coverage_by_dimension: Dict[str, bool] = field(default_factory=dict)
    coverage_by_destination: Dict[str, Dict[str, int]] = field(default_factory=dict)
    confidence_ratio: float = 0.0
    schema_completeness: float = 0.0
    dimension_coverage_rate: float = 0.0
    destination_coverage_rate: float = 0.0
    # v2.1 客观性指标（只读 Evidence.source_group / viral / claim_type，不重算相似度）
    single_source_ratio: float = 0.0
    viral_evidence_count: int = 0
    viral_evidence_ratio: float = 0.0
    opinion_ratio: float = 0.0
    # 视角核查表**格级**产出台账（批次 0 前置测度）：块级 schema_completeness 把「全表
    # 待核验」读成满分，产出率门槛必须另立这三个数。非视角卷保持默认值（不破既有卷口径）。
    persp_verified_ratio: float = 0.0
    persp_probed_spots: int = 0
    # ∈ ok / truncated / error / skipped / ""（未装配）。**不可**从 structured 反推：
    # LLM 抛错、返回空、真无证据、反造数守卫全拒 —— 四者在载荷里长得一模一样。
    persp_llm_outcome: str = ""
    # 用户指定信源覆盖率（计划 v3 §二 B5）。缺省 {} = 本次任务没填清单，
    # 与"填了但一条都没被引用"是两件事，不能都塌成 0。
    user_source_coverage: Dict[str, Any] = field(default_factory=dict)
    issues: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coverage_by_dimension": self.coverage_by_dimension,
            "coverage_by_destination": self.coverage_by_destination,
            "confidence_ratio": self.confidence_ratio,
            "schema_completeness": self.schema_completeness,
            "dimension_coverage_rate": self.dimension_coverage_rate,
            "destination_coverage_rate": self.destination_coverage_rate,
            "single_source_ratio": self.single_source_ratio,
            "viral_evidence_count": self.viral_evidence_count,
            "viral_evidence_ratio": self.viral_evidence_ratio,
            "opinion_ratio": self.opinion_ratio,
            # ⚠️ 手写枚举：新字段不进这里就**不落库**（quality_before/after 是 to_dict 的产物），
            # 门槛随后读到的是缺键而非 0 —— 静默缺指标比缺指标本身更难查。
            "persp_verified_ratio": self.persp_verified_ratio,
            "persp_probed_spots": self.persp_probed_spots,
            "persp_llm_outcome": self.persp_llm_outcome,
            "user_source_coverage": self.user_source_coverage,
            "issues": self.issues,
        }

    def summary(self) -> Dict[str, Any]:
        """供前端返工卡片展示的精简指标。"""
        out = {
            "confidence_ratio": round(self.confidence_ratio * 100),
            "dimension_coverage": round(self.dimension_coverage_rate * 100),
            "destination_coverage": round(self.destination_coverage_rate * 100),
            "schema_completeness": round(self.schema_completeness * 100),
        }
        # 视角卷才追加格级两项：非视角卷凭空多两个 0 会被读成「测了且为零」而非「没测」
        if self.persp_probed_spots or self.persp_llm_outcome:
            out["persp_verified_ratio"] = round(self.persp_verified_ratio * 100)
            out["persp_probed_spots"] = self.persp_probed_spots
        return out


# v2.1 单源占比触发返工补采的阈值
SINGLE_SOURCE_REWORK_RATIO = 0.5


# ── 用户指定信源覆盖率（计划 v3 §二 B4/B5）─────────────────────────
# 语义分工（这是本维度唯一的设计难点，写清楚免得日后被"顺手合并成一根"）：
#   · `user_sources.fetch_state` = **读取生命周期**，唯一写点是 collect
#     （fetched / unread / blocked / gated_off_query / merged / pending）；
#   · `user_sources.cited_by`    = **引用事实**，唯一写点是本函数（结论 id 列表）；
#   · 覆盖率 = 由上面两者**派生**的指标，不是第三个存储状态。
#   把 cited/uncited 也存成 fetch_state 会造出两个写者抢一根列：collect 与 audit 的
#   时序一变（返工轮、复跑）就会出现"已引用却仍是 fetched"的漂移，而没人会报错。
USER_SOURCE_COVERAGE_BUCKETS = ("cited", "uncited", "unread", "blocked", "gated_off_query", "merged")


def compute_user_source_coverage(rows: List[Dict[str, Any]],
                                 claims: List[Dict[str, Any]],
                                 evidences: List[Any]) -> Dict[str, Any]:
    """按**信源组**核的用户指定信源覆盖率。

    为什么按组核（§一 A-3）：用户钉的三个站若转载同一篇通稿，会被去重机制归并成一组
    （`fetch_state=merged`），只有代表证据独立成行。按"这一条网址自己有没有被引用"核，
    会把归并掉的三条一律判成"未引用"——那是这套归并机制本要消灭的判据形状。
    判据改成：**它所在组被任何结论引用 ⇒ 该条算已引用**。

    分母口径（§四.3 + 待确认 2）：
      · `unread` / `blocked` 是"没读到"，不进分母 —— 一个 404 不该卡住报告签发；
      · `merged` / `gated_off_query` / `fetched` 都是"读到了"，进分母，按引用情况分 cited/uncited；
      · 分母恒等：cited + uncited + unread + blocked + pending == total（TC-25 守这条）。
    """
    # 被任何结论引用的证据 id（Claim.evidence_ids 是唯一判据来源）
    cited_eids = {eid for c in claims for eid in (c.get("evidence_ids") or []) if eid}
    # 证据 id → 所在信源组：归并条与代表证据靠这一层连起来
    group_of = {getattr(e, "evidence_id", ""): (getattr(e, "source_group", "")
                                                or getattr(e, "evidence_id", ""))
                for e in evidences}
    hit_groups = {group_of.get(eid, eid) for eid in cited_eids if group_of.get(eid, eid)}

    buckets = {k: 0 for k in USER_SOURCE_COVERAGE_BUCKETS}
    pending = 0
    details: List[Dict[str, Any]] = []
    for row in rows:
        state = str(row.get("fetch_state") or "")
        group = str(row.get("group_id") or "")
        evidence_id = str(row.get("evidence_id") or "")
        # 一条网址"被用上"的三种等价形态：自己独立成行被引 / 所在组被引 / 地址即代表证据
        cited = (evidence_id in cited_eids) or (group and group in hit_groups)
        if state == "pending":
            pending += 1
            outcome = "pending"
        elif state in ("unread", "blocked"):
            buckets["unread" if state == "unread" else "blocked"] += 1
            outcome = state
        else:
            outcome = "cited" if cited else "uncited"
            buckets[outcome] += 1
        if state == "gated_off_query":
            buckets["gated_off_query"] += 1
        elif state == "merged":
            buckets["merged"] += 1
        details.append({**row, "coverage": outcome, "cited_by_claims": sorted(
            {str(c.get("claim_id") or c.get("id") or "")
             for c in claims if evidence_id and evidence_id in (c.get("evidence_ids") or [])})})

    denominator = buckets["cited"] + buckets["uncited"]
    return {
        "total": len(rows),
        "cited": buckets["cited"],
        "uncited": buckets["uncited"],
        "unread": buckets["unread"],
        "blocked": buckets["blocked"],
        "gated_off_query": buckets["gated_off_query"],
        "merged": buckets["merged"],
        "pending": pending,
        "denominator": denominator,
        "rate": round(buckets["cited"] / denominator, 3) if denominator else None,
        "rows": details,
    }


def user_source_issues(coverage: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把"读到了却没引用"与"没读到"都摊成可见 issue。

    target 前缀**只用 `user_source:`**（§二 B5 硬约束）：`decide_rework` 按
    `destination:` / `dimension:` / `schema` 三种前缀分流，沿用它们会让一条用户网址
    变成"补采某个目的地"的 REWORK —— 空转烧预算、流水线变长，且没有现存测试会因此变红。
    该隔离由 `tests/test_audit_user_source_envelope.py` 冻结。
    """
    out: List[Dict[str, Any]] = []
    for row in coverage.get("rows") or []:
        outcome = row.get("coverage")
        if outcome == "uncited":
            out.append({
                "issue_id": "is_" + uuid.uuid4().hex[:8],
                "target": f"user_source:{row.get('uid', '')}",
                "severity": "low",
                "reason": f"用户指定信源「{row.get('url_canonical') or row.get('url', '')}」"
                          f"已读取进证据链，但本次报告的结论未引用它（不阻断签发，如实披露）。",
                "raised_by": "L3-003",
            })
        elif outcome in ("unread", "blocked"):
            out.append({
                "issue_id": "is_" + uuid.uuid4().hex[:8],
                "target": f"user_source:{row.get('uid', '')}",
                "severity": "low",
                "reason": f"用户指定信源「{row.get('url_canonical') or row.get('url', '')}」"
                          f"未读取成功：{row.get('attempt_reason') or '原因未记录'}（不计入覆盖率分母）。",
                "raised_by": "L3-003",
            })
    return out


def evaluate_quality(
    destinations: List[str],
    focus: List[str],
    claims: List[Dict[str, Any]],
    evidences: List[Any],
    structured: Dict[str, Any],
    *,
    min_indep_domains: int = 2,
    research_type: str = DEFAULT_RESEARCH_TYPE,
    perspective_section_id: str = "",
    persp_llm_outcome: str = "",
    user_source_rows: Optional[List[Dict[str, Any]]] = None,
) -> QualityReport:
    qr = QualityReport()

    # 1. 置信度比
    total = len(claims) or 1
    high = sum(1 for c in claims if c.get("confidence") == "high")
    qr.confidence_ratio = round(high / total, 3)

    # 2. 维度覆盖：每个 focus 维度是否有 ≥1 条 medium/high claim
    fields_present = {c.get("field") for c in claims
                      if c.get("confidence") in ("high", "medium")}
    for dim in focus:
        low = str(dim).lower()
        covered = any(f in fields_present and any(k in low for k in RT.field_keywords(f))
                      for f in fields_present)
        # 兜底：只要有任意有效 claim 即视为该维度有所触及
        if not covered and fields_present:
            covered = True
        qr.coverage_by_dimension[dim] = covered
    covered_dims = sum(1 for v in qr.coverage_by_dimension.values() if v)
    qr.dimension_coverage_rate = round(covered_dims / (len(focus) or 1), 3)

    # 3. 目的地覆盖：每个目的地的证据数与独立域名数
    dest_ok = 0
    for b in destinations:
        evs = [e for e in evidences if getattr(e, "destination", "") == b]
        domains = {domain_of(getattr(e, "source_url", "")) for e in evs}
        domains.discard("")
        qr.coverage_by_destination[b] = {"evidence": len(evs), "domains": len(domains)}
        if len(domains) >= min_indep_domains:
            dest_ok += 1
        else:
            qr.issues.append({
                "issue_id": "is_" + uuid.uuid4().hex[:8],
                "target": f"destination:{b}",
                "severity": "high" if len(evs) == 0 else "medium",
                "reason": f"「{b}」独立信源仅 {len(domains)} 个（<{min_indep_domains}），证据不足，建议补充采集。",
                "raised_by": "L3-003",
            })
    qr.destination_coverage_rate = round(dest_ok / (len(destinations) or 1), 3)

    # 4. 维度缺失 issue
    for dim, ok in qr.coverage_by_dimension.items():
        if not ok:
            qr.issues.append({
                "issue_id": "is_" + uuid.uuid4().hex[:8],
                "target": f"dimension:{dim}",
                "severity": "medium",
                "reason": f"维度「{dim}」缺少有效论点支撑，建议重新分析。",
                "raised_by": "L3-003",
            })

    # 5. Schema 完整度
    from app.core.schemas import schema_completeness, persp_cell_stats
    qr.schema_completeness = schema_completeness(structured, research_type,
                                                 perspective_section_id)
    # 5b. 视角核查表格级台账（块级满分 ≠ 格子里有证据）
    qr.persp_llm_outcome = persp_llm_outcome or ""
    if perspective_section_id:
        _pc = persp_cell_stats(structured, perspective_section_id)
        qr.persp_probed_spots = _pc["rows"]
        qr.persp_verified_ratio = (round(_pc["verified"] / _pc["cells"], 3)
                                   if _pc["cells"] else 0.0)
    if qr.schema_completeness < 0.34:
        qr.issues.append({
            "issue_id": "is_" + uuid.uuid4().hex[:8],
            "target": "schema",
            "severity": "low",
            "reason": "结构化知识（路线/住宿/花费或可达性/配套/风险）填充不足，建议重新分析补全。",
            "raised_by": "L3-003",
        })

    # 6. 客观性指标（v2.1）：单源占比 / 过热证据 / 观点密度
    #    只读 Evidence.source_group / viral / claim_type，不重算相似度。
    def _claim_group_count(c: Dict[str, Any]) -> int:
        ids = set(c.get("evidence_ids") or [])
        grp = {getattr(e, "source_group", "") or getattr(e, "evidence_id", "")
               for e in evidences if getattr(e, "evidence_id", None) in ids}
        return len(grp)

    single_sourced = [c for c in claims if _claim_group_count(c) < 2]
    qr.single_source_ratio = round(len(single_sourced) / (len(claims) or 1), 3)
    for c in single_sourced[:8]:
        qr.issues.append({
            "issue_id": "is_" + uuid.uuid4().hex[:8],
            "target": f"claim:{c.get('claim_id') or c.get('id', '')}",
            "severity": "medium",
            "reason": "结论仅单一信源组支撑，建议补充采集以完成交叉验证。",
            "raised_by": "L3-003",
        })

    viral_evs = [e for e in evidences if getattr(e, "viral", False)]
    qr.viral_evidence_count = len(viral_evs)
    qr.viral_evidence_ratio = round(len(viral_evs) / (len(evidences) or 1), 3)
    if viral_evs:
        qr.issues.append({
            "issue_id": "is_" + uuid.uuid4().hex[:8],
            "target": "task",
            "severity": "low",
            "reason": f"存在 {len(viral_evs)} 条舆论过热来源，结论易受情绪引导，已如实披露（不阻塞）。",
            "raised_by": "L3-003",
        })

    op_n = sum(1 for c in claims if c.get("claim_type", "mixed") in ("opinion", "mixed"))
    qr.opinion_ratio = round(op_n / (len(claims) or 1), 3)

    # 7. 用户指定信源覆盖率（计划 v3 §二 B5）：只有**本次真填过清单**才计算。
    #    不带清单的任务在这里保持 `{}` 且一条 issue 都不追加 —— 这是 §四.2 零回归基线
    #    要求的形状（QualityReport 全字段逐值等改前），不是"顺手兼容旧数据"。
    if user_source_rows:
        qr.user_source_coverage = compute_user_source_coverage(
            user_source_rows, claims, evidences)
        qr.issues.extend(user_source_issues(qr.user_source_coverage))

    return qr


def llm_quality_review(
    query: str,
    destinations: List[str],
    focus: List[str],
    claims: List[Dict[str, Any]],
    structured: Dict[str, Any],
    qr: "QualityReport",
    model: str = None,
    research_type: str = DEFAULT_RESEARCH_TYPE,
    persp_constraints: str = "",
) -> Dict[str, Any]:
    """质检官用 LLM 对当前分析做真实『审阅』（非纯规则）：逐维度打分 + 指出问题 + 给改进建议。

    产出结构化评审意见，让「质检审裁」阶段有真实的对比、审阅与可执行的调优建议
    （对应评分维度：反馈闭环真实可触发、重做后有改善）。失败时退回基于规则指标的兜底意见。
    """
    from app.core.llm import chat_json

    claim_lines = "\n".join(
        f"- [{c.get('confidence','?')}|{c.get('field','')}] {c.get('text','')}"
        for c in claims[:18]
    ) or "（暂无论点）"
    sc_dims = "、".join(f"{k}:{'已覆盖' if v else '缺失'}"
                       for k, v in qr.coverage_by_dimension.items()) or "无"
    dest_cov = "、".join(f"{b}({v.get('domains',0)}域/{v.get('evidence',0)}证据)"
                        for b, v in qr.coverage_by_destination.items()) or "无"
    fallback = {
        "verdict": "pass" if not qr.issues else "rework",
        "scores": {
            "证据充分性": round(qr.destination_coverage_rate * 100),
            "维度完整性": round(qr.dimension_coverage_rate * 100),
            "结论置信度": round(qr.confidence_ratio * 100),
            "结构化完整度": round(qr.schema_completeness * 100),
            "客观性与多源互证": round((1 - qr.single_source_ratio) * 100),
        },
        "review": f"基于规则指标：维度覆盖 {round(qr.dimension_coverage_rate*100)}%、"
                  f"目的地覆盖 {round(qr.destination_coverage_rate*100)}%、"
                  f"高置信占比 {round(qr.confidence_ratio*100)}%。",
        "issues": [i.get("reason", "") for i in qr.issues[:6]],
        "suggestions": [],
    }
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是旅游调研报告（游玩攻略 / 目的地评估）的质检官（L3 决策层）。"
                    "请对下面这份『分析中间产物』做严格的质量审阅，像资深主编终审一样，"
                    "逐维度打分（0-100 整数，要有真实差异、不要清一色整十），"
                    "指出具体问题，并给出可执行的改进建议。最后给整体结论 pass（达标）或 rework（需返工）。"
                    '只输出 JSON：{"verdict":"pass|rework",'
                    '"scores":{"证据充分性":int,"维度完整性":int,"结论置信度":int,"结构化完整度":int,"交叉验证":int,"客观性与多源互证":int},'
                    '"review":"一段总体评审意见（点明亮点与短板）",'
                    '"issues":["具体问题1","具体问题2"],'
                    '"suggestions":["可执行改进建议1","改进建议2"]}。只输出 JSON。'
                    + ("\n【问卷硬约束越界检查】用户问卷约束：" + persp_constraints +
                       " ——论点或结构化产出与其冲突（如给 1-2 天行程排 3 天玩法、"
                       "预算档位与实际推荐不符）、或核查表之外出现无参数的套话建议，"
                       "必须逐条计入 issues。" if persp_constraints else "")
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n调研类型：{RT.type_spec(research_type)['label']}\n"
                    f"目的地：{'、'.join(destinations)}\n重点维度：{'、'.join(focus)}\n"
                    f"规则侧指标 → 维度覆盖：{sc_dims}；目的地证据覆盖：{dest_cov}；"
                    f"高置信占比：{round(qr.confidence_ratio*100)}%；结构化完整度：{round(qr.schema_completeness*100)}%\n"
                    f"已提炼论点：\n{claim_lines}"
                )},
            ],
            max_tokens=2000, temperature=0.3, model=model,
            purpose="质检官审阅：逐维度打分+问题+改进建议",
        )
        if isinstance(data, dict) and data.get("scores"):
            scores = {str(k): _clamp_score(v) for k, v in (data.get("scores") or {}).items()}
            return {
                "verdict": "rework" if str(data.get("verdict")) == "rework" else "pass",
                "scores": scores or fallback["scores"],
                "review": str(data.get("review") or fallback["review"]),
                "issues": [str(x) for x in (data.get("issues") or []) if str(x).strip()][:8],
                "suggestions": [str(x) for x in (data.get("suggestions") or []) if str(x).strip()][:8],
            }
    except Exception:
        pass
    return fallback


def _clamp_score(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def decide_rework(qr: QualityReport,
                  evidences: Optional[List[Any]] = None) -> List[Envelope]:
    """根据质量报告决定返工动作，产出结构化 Envelope 消息。

    evidences（v2.1，可选）：用于「单源占比过高 → 按目的地补采独立信源组」判定；
    不传则跳过该判定（兼容旧调用）。
    """
    envelopes: List[Envelope] = []

    # 证据不足 → 打回 collect 补采
    collect_targets = [iss for iss in qr.issues if iss["target"].startswith("destination:")]
    if collect_targets:
        destinations_to_recollect = [iss["target"].split(":", 1)[1] for iss in collect_targets]
        envelopes.append(Envelope(
            msg_id="env_" + uuid.uuid4().hex[:8],
            sender="L3-003",
            receiver="collect",
            task_type="REWORK",
            payload={"destinations": destinations_to_recollect, "reason": "证据不足，补充采集"},
            issues=collect_targets,
        ))

    # 维度缺失 / schema 不足 → 打回 analyze 重分析
    analyze_targets = [iss for iss in qr.issues
                       if iss["target"].startswith("dimension:") or iss["target"] == "schema"]
    if analyze_targets:
        envelopes.append(Envelope(
            msg_id="env_" + uuid.uuid4().hex[:8],
            sender="L3-003",
            receiver="analyze",
            task_type="REWORK",
            payload={"reason": "维度/结构覆盖不足，重新分析补全"},
            issues=analyze_targets,
        ))

    # v2.1 单源占比过高 → 按目的地补采独立信源组（避免死循环：viral_heavy 不触发返工）
    if qr.single_source_ratio > SINGLE_SOURCE_REWORK_RATIO and evidences is not None:
        single_group_destinations = []
        for b in {getattr(e, "destination", "") for e in evidences if getattr(e, "destination", "")}:
            groups_b = {getattr(e, "source_group", "") or getattr(e, "evidence_id", "")
                        for e in evidences if getattr(e, "destination", "") == b}
            if len(groups_b) < 2:
                single_group_destinations.append(b)
        if single_group_destinations:
            envelopes.append(Envelope(
                msg_id="env_" + uuid.uuid4().hex[:8],
                sender="L3-003",
                receiver="collect",
                task_type="REWORK",
                payload={"destinations": single_group_destinations[:3], "reason": "单源占比过高，补充独立信源组"},
                issues=[{"target": f"destination:{b}", "severity": "medium",
                         "reason": f"「{b}」有效信源组 < 2，单源占比过高。", "raised_by": "L3-003"}
                        for b in single_group_destinations[:3]],
            ))

    return envelopes
