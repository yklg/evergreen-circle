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

_STRUCT = {"route_plan": [], "stay_options": [], "cost_breakdown": []}


def _ev(eid: str, destination: str = "目的地A", group: str = "g1", viral: bool = False,
        domain: str = "example.com") -> Evidence:
    return Evidence(
        evidence_id=eid,
        source_url=f"https://{domain}/{eid}",
        source_type="web",
        title="证据",
        excerpt="证据摘要内容，用于质检指标统计。",
        captured_at="2026-01-01",
        credibility=50.0,
        collected_by="tester",
        destination=destination,
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
    qr = evaluate_quality(["目的地A"], ["overview"], claims, evs, _STRUCT)
    assert qr.single_source_ratio == 0.5   # c1 单组；c2 双组
    assert qr.opinion_ratio == 0.5         # opinion 1/2
    assert any(i["target"].startswith("claim:c1") for i in qr.issues)


def test_viral_metrics_and_issue():
    evs = [_ev("e1", group="g1", viral=True), _ev("e2", group="g2", viral=True),
           _ev("e3", group="g3")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "high",
               "evidence_ids": ["e1", "e2"], "claim_type": "mixed"}]
    qr = evaluate_quality(["目的地A"], ["overview"], claims, evs, _STRUCT)
    assert qr.viral_evidence_count == 2
    assert qr.viral_evidence_ratio == round(2 / 3, 3)
    assert any("舆论过热" in i["reason"] for i in qr.issues)


def test_decide_rework_single_source_triggers_collect():
    """单源占比 >0.5 且目的地仅有 1 个信源组 → collect 补采信封。"""
    evs = [_ev("e1", destination="目的地A", group="g1"), _ev("e2", destination="目的地A", group="g1")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "medium",
               "evidence_ids": ["e1"], "claim_type": "mixed"}]
    qr = evaluate_quality(["目的地A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr, evs)
    collect = [e for e in envs if e.receiver == "collect"]
    assert collect, "单源占比过高应触发 collect 信封"
    assert "目的地A" in collect[0].payload.get("destinations", [])


def test_decide_rework_viral_only_no_rework():
    """仅过热披露（多信源组）→ 不产生返工信封（避免死循环）。"""
    evs = [_ev("e1", destination="A", group="g1", viral=True), _ev("e2", destination="A", group="g2", viral=True)]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "high",
               "evidence_ids": ["e1", "e2"], "claim_type": "fact"}]
    qr = evaluate_quality(["A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr, evs)
    reasons = " ".join(i.get("reason", "") for e in envs for i in e.issues)
    assert "单源占比过高" not in reasons


def test_decide_rework_without_evidences_back_compat():
    """不传 evidences（旧调用）→ 跳过单源目的地判定，不崩溃。"""
    evs = [_ev("e1", destination="目的地A", group="g1")]
    claims = [{"claim_id": "c1", "field": "overview", "confidence": "medium",
               "evidence_ids": ["e1"], "claim_type": "mixed"}]
    qr = evaluate_quality(["目的地A"], ["overview"], claims, evs, _STRUCT)
    envs = decide_rework(qr)  # 无 evidences 参数
    # 不触发「单源补采」信封；但仍可能因目的地覆盖 issue 触发 collect（断言不崩即可）
    assert isinstance(envs, list)


# ── 目的地语义契约（R4：产出键 / 筛选参数 / 返工载荷键成对）─────
def test_coverage_by_destination_and_issue_target():
    """每个目的地的证据数/独立域名数按新键名产出，issue target 为 destination:{d}。"""
    evs = [
        _ev("e1", destination="大理", group="g1", domain="a.com"),
        _ev("e2", destination="大理", group="g2", domain="b.com"),
        _ev("e3", destination="丽江", group="g1", domain="c.com"),   # 仅 1 个独立域名 → 触发 issue
    ]
    qr = evaluate_quality(["大理", "丽江"], ["overview"], [], evs, _STRUCT)
    assert set(qr.coverage_by_destination) == {"大理", "丽江"}
    assert qr.coverage_by_destination["大理"] == {"evidence": 2, "domains": 2}
    assert qr.coverage_by_destination["丽江"] == {"evidence": 1, "domains": 1}
    assert qr.destination_coverage_rate == 0.5      # 2 个目的地中仅「大理」达标（独立域名 ≥2）
    targets = [i["target"] for i in qr.issues if i["target"].startswith("destination:")]
    assert "destination:丽江" in targets
    assert not any(t.startswith("brand:") for t in targets), "旧 issue 前缀不得回潮"


def test_quality_report_keys_use_destination_wording():
    qr = evaluate_quality(["目的地A"], ["overview"], [], [], _STRUCT)
    d = qr.to_dict()
    assert "coverage_by_destination" in d and "destination_coverage_rate" in d
    assert "coverage_by_brand" not in d and "brand_coverage_rate" not in d
    assert set(qr.summary()) >= {"destination_coverage", "dimension_coverage"}
    assert "brand_coverage" not in qr.summary()


def test_rework_payload_key_roundtrips_with_collect_consumer():
    """返工信封 payload 键必须与编排层 collect 的消费键一致（两侧同键，防单侧改名）。"""
    import re
    from pathlib import Path

    from app.core.pipeline.research import engine

    evs = [_ev("e1", destination="大理", group="g1"), _ev("e2", destination="大理", group="g1")]
    qr = evaluate_quality(["大理"], ["overview"], [], evs, _STRUCT)
    envs = decide_rework(qr, evs)
    collect = [e for e in envs if e.receiver == "collect"]
    assert collect, "单源占比过高应触发 collect 信封"
    assert "destinations" in collect[0].payload and "brands" not in collect[0].payload

    src = Path(engine.__file__).read_text(encoding="utf-8")
    assert 'payload.get("destinations"' in src, "collect 消费键必须同为 destinations"
    assert 'payload.get("brands"' not in src, "旧消费键不得回潮"
    # 返工补采调用的采集函数按目的地取参（键名同源）
    assert re.search(r"_collect_destination\(\s*b", src) or "for b in recollect" in src


def test_evaluate_quality_signature_has_no_brand_params():
    """签名层防回潮：不得再接受 brands / brand 参数（重命名彻底性）。"""
    import inspect

    params = list(inspect.signature(evaluate_quality).parameters)
    assert params[0] == "destinations", "首个位置参数须为 destinations"
    assert not [p for p in params if p.startswith("brand")], f"残留旧参数：{params}"
    assert list(inspect.signature(decide_rework).parameters) == ["qr", "evidences"]