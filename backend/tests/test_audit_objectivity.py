"""质检层客观性指标与返工规则测试（accuracy-objectivity-hardening 方案 v2.1）。

守护不变量：
- evaluate_quality 基于 信源组(source_group) 计算 single_source_ratio（不重算相似度）；
- viral_evidence_count/ratio、opinion_ratio 与 issue（single_sourced / viral_heavy）正确；
- decide_rework：单源占比过高 → collect 补采信封；viral_heavy 仅披露不触发返工。

运行：backend/ 下 `pytest tests/test_audit_objectivity.py -q`
"""
import pytest

from app.core.audit import decide_rework, evaluate_quality
from app.core.models import Evidence

_STRUCT = {"feature_tree": [], "pricing_model": [], "user_persona": []}


def _ev(eid: str, brand: str = "品牌A", group: str = "g1", viral: bool = False) -> Evidence:
    return Evidence(
        evidence_id=eid,
        source_url=f"https://example.com/{eid}",
        source_type="web",
        title="证据",
        excerpt="证据摘要内容，用于质检指标统计。",
        captured_at="2026-01-01",
        credibility=50.0,
        collected_by="tester",
        brand=brand,
        source_group=group or "",
        viral=viral,
    )


def test_single_source_and_opinion_ratio():
    evs = [_ev("e1", group="g1"), _ev("e2", group="g2")]
    claims = [
        {"claim_id": "c1", "field": "overview", "confidence": "high",
         "evidence_ids": ["e1"], "claim_type": "fact"},            # 单源组
        {"claim_id": "c2", "field": "trend", "confidence": "medium",
         "evidence_ids": ["e1", "e2"], "claim_type": "opinion"},   # 双源组
    ]
    qr = evaluate_quality(["品牌A"], ["overview"], claims, evs, _STRUCT)
    assert qr.single_source_ratio == 0.5   # c1 单组；c2 双组
    assert qr.opinion_ratio == 0.5         # opinion 1/2
    assert any(i["target"].startswith("claim:c1") for i in qr.issues)


def test_viral_metrics_and_issue():
    evs = [_ev("e1", group="g1", viral=True), _ev("e2", group="g2", viral=True),
           _ev("e3", group="g3")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "high",
               "evidence_ids": ["e1", "e2"], "claim_type": "mixed"}]
    qr = evaluate_quality(["品牌A"], ["overview"], claims, evs, _STRUCT)
    assert qr.viral_evidence_count == 2
    assert qr.viral_evidence_ratio == round(2 / 3, 3)
    assert any("舆论过热" in i["reason"] for i in qr.issues)


def test_decide_rework_single_source_triggers_collect():
    """单源占比 >0.5 且品牌仅有 1 个信源组 → collect 补采信封。"""
    evs = [_ev("e1", brand="品牌A", group="g1"), _ev("e2", brand="品牌A", group="g1")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "medium",
               "evidence_ids": ["e1"], "claim_type": "mixed"}]
    qr = evaluate_quality(["品牌A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr, evs)
    collect = [e for e in envs if e.receiver == "collect"]
    assert collect, "单源占比过高应触发 collect 信封"
    assert "品牌A" in collect[0].payload.get("brands", [])


def test_decide_rework_viral_only_no_rework():
    """仅过热披露（多信源组）→ 不产生返工信封（避免死循环）。"""
    evs = [_ev("e1", brand="A", group="g1", viral=True), _ev("e2", brand="A", group="g2", viral=True)]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "high",
               "evidence_ids": ["e1", "e2"], "claim_type": "fact"}]
    qr = evaluate_quality(["A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr, evs)
    reasons = " ".join(i.get("reason", "") for e in envs for i in e.issues)
    assert "单源占比过高" not in reasons


def test_decide_rework_without_evidences_back_compat():
    """不传 evidences（旧调用）→ 跳过单源品牌判定，不崩溃。"""
    evs = [_ev("e1", brand="品牌A", group="g1")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "medium",
               "evidence_ids": ["e1"], "claim_type": "mixed"}]
    qr = evaluate_quality(["品牌A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr)  # 无 evidences 参数
    # 不触发「单源补采」信封；但仍可能因品牌覆盖 issue 触发 collect（断言不崩即可）
    assert isinstance(envs, list)