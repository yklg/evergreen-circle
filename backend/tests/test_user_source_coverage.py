"""用户指定信源覆盖率与返工隔离（实施计划 v3 §二 B4/B5 · §八 TC-25 / TC-36 / TC-44）。

守护的契约
----------
1. **按组核**（§一 A-3）：用户钉三站同一篇通稿会被去重机制归并成一组，只有代表证据
   独立成行。按"这条网址自己有没有被引用"核会把归并掉的判成未引用 —— 那正是归并机制
   本要消灭的判据形状。真判据是「所在信源组被任何结论引用」。
2. **分母守恒**（§八 INV-01 / TC-25）：
   `cited + uncited + unread + blocked + pending == total`，
   且 `unread` / `blocked` **不进分母**（§四.3 明写"404 不进覆盖率分母"）。
   漏一条不是数字小一点，而是覆盖率算错方向。
3. **不产生返工 envelope**（§一 B-P0-3）：新维度的 issue 只允许 `user_source:` 前缀，
   而 `decide_rework` 按 `destination:` / `dimension:` / `schema` 分流。这里用
   **生产真实产出的 issue** 来钉（`test_audit_user_source_envelope.py` 是手工造 target
   的那一半）—— 生产代码若改用别的 target 形状，只有走真实路径的这条会红。
4. **零回归形状**：不带清单时 `user_source_coverage == {}` 且不追加任何 issue。

期望值来源
----------
分母口径取自计划 §四.3 与待确认 2（"计入质量分但不阻断"）；
bucket 词表取自 `audit.USER_SOURCE_COVERAGE_BUCKETS`（import，不抄数）；
fetch_state 词表取自 `db.USER_SOURCE_STATES`（本文件用它钉"派生态不入存储词表"）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core import audit
from app.core.audit import QualityReport, compute_user_source_coverage, decide_rework
from app.core.db import USER_SOURCE_STATES
from app.core.models import Evidence


def _row(uid: str, state: str, *, evidence_id: str = "", group_id: str = "") -> Dict[str, Any]:
    """行形状取自 `db.list_user_sources` 的 SELECT *（列名一致，便于换真库读数）。"""
    return {
        "uid": uid, "url": f"https://{uid}.gov.cn/doc", "url_canonical": f"https://{uid}.gov.cn/doc",
        "fetch_state": state, "evidence_id": evidence_id, "group_id": group_id,
        "cited_by": "", "attempt_reason": "", "bytes": 100, "ms": 50,
    }


def _ev(eid: str, group: str) -> Evidence:
    return Evidence(
        evidence_id=eid, source_url=f"https://{eid}.gov.cn/doc",
        source_type="user_supplied", title=eid, excerpt="x",
        captured_at="2026-01-01T00:00:00Z", credibility=60.0, collected_by="L1-025",
        image_urls=[], republished_from="", destination="", source_group=group,
    )


def _claim(cid: str, eids: List[str]) -> Dict[str, Any]:
    return {"claim_id": cid, "id": cid, "text": "结论", "confidence": "high",
            "field": "cost", "evidence_ids": eids}


# ── 1. 按组核 ──────────────────────────────────────────────────────

def test_merged_rows_are_judged_by_their_group_not_by_themselves():
    """代表证据被引用 ⇒ 同组的归并条一律算已引用。"""
    rows = [_row("u1", "fetched", evidence_id="e_1", group_id="gA"),
            _row("u2", "merged", group_id="gA"),
            _row("u3", "merged", group_id="gA")]
    cov = compute_user_source_coverage(rows, [_claim("c1", ["e_1"])], [_ev("e_1", "gA")])

    assert cov["cited"] == 3, cov
    assert cov["uncited"] == 0
    assert cov["merged"] == 2, "归并条数要单独可数（§四.6 报告文案要显示「归并 J」）"
    assert cov["rate"] == 1.0


def test_same_group_not_cited_counts_every_member_as_uncited():
    rows = [_row("u1", "fetched", evidence_id="e_1", group_id="gA"),
            _row("u2", "merged", group_id="gA")]
    cov = compute_user_source_coverage(rows, [_claim("c1", ["e_9"])],
                                       [_ev("e_1", "gA"), _ev("e_9", "gB")])
    assert cov["cited"] == 0 and cov["uncited"] == 2, cov


def test_direct_citation_of_the_row_own_evidence_also_counts():
    rows = [_row("u1", "fetched", evidence_id="e_1", group_id="gSolo")]
    cov = compute_user_source_coverage(rows, [_claim("c1", ["e_1"])], [_ev("e_1", "gSolo")])
    assert cov["cited"] == 1


def test_cited_by_claims_are_listed_per_row_for_the_evidence_chain():
    """报告要能指出"哪条结论引用了哪条用户网址"，否则"已引用 M"仍是不可核的数字。"""
    rows = [_row("u1", "fetched", evidence_id="e_1", group_id="gA"),
            _row("u2", "fetched", evidence_id="e_2", group_id="gB")]
    cov = compute_user_source_coverage(
        rows, [_claim("c1", ["e_1"]), _claim("c2", ["e_1", "e_2"])],
        [_ev("e_1", "gA"), _ev("e_2", "gB")])
    by_uid = {r["uid"]: r for r in cov["rows"]}
    assert by_uid["u1"]["cited_by_claims"] == ["c1", "c2"]
    assert by_uid["u2"]["cited_by_claims"] == ["c2"]


# ── 2. 分母守恒 ────────────────────────────────────────────────────

def test_denominator_identity_holds_for_a_mixed_batch():
    """cited+uncited+unread+blocked+pending == total（TC-25 的恒等式）。"""
    rows = [_row("a", "fetched", evidence_id="e_a", group_id="gA"),
            _row("b", "fetched", evidence_id="e_b", group_id="gB"),
            _row("c", "unread"), _row("d", "unread"),
            _row("e", "blocked"), _row("f", "pending"),
            _row("g", "gated_off_query", evidence_id="e_g", group_id="gG"),
            _row("h", "merged", group_id="gA")]
    cov = compute_user_source_coverage(rows, [_claim("c1", ["e_a"]), _claim("c2", ["e_g"])],
                                       [_ev("e_a", "gA"), _ev("e_b", "gB"), _ev("e_g", "gG")])

    assert cov["total"] == len(rows)
    assert (cov["cited"] + cov["uncited"] + cov["unread"] + cov["blocked"] + cov["pending"]
            == cov["total"]), cov
    assert cov["denominator"] == cov["cited"] + cov["uncited"]
    assert cov["pending"] == 1, "复跑/中断留下的未处理条也要数得出来"


def test_failed_reads_are_outside_the_denominator():
    """§四.3：404 属"没读到"，不进分母 —— 一个反爬站不该把覆盖率拽低并卡住签发。"""
    rows = [_row("a", "fetched", evidence_id="e_a", group_id="gA"),
            _row("b", "unread"), _row("c", "blocked")]
    cov = compute_user_source_coverage(rows, [_claim("c1", ["e_a"])], [_ev("e_a", "gA")])
    assert cov["denominator"] == 1 and cov["rate"] == 1.0, cov
    assert cov["unread"] == 1 and cov["blocked"] == 1


def test_rate_is_none_when_nothing_was_read():
    """全失败 ⇒ 分母为 0 时 rate 必须是 None（"没测出来"）而非 0.0（"测了且为零"）。

    这两种语义在答辩口径上完全不同：0.0 会被读成"用户信源一条都没用上"。
    """
    cov = compute_user_source_coverage([_row("a", "unread"), _row("b", "blocked")], [], [])
    assert cov["rate"] is None and cov["denominator"] == 0


def test_off_topic_rows_are_counted_and_stay_in_the_denominator():
    """跑题是**诊断**不是丢弃：正文入了链就按引用情况计分，同时单独可数。"""
    rows = [_row("a", "gated_off_query", evidence_id="e_a", group_id="gA")]
    cov = compute_user_source_coverage(rows, [], [_ev("e_a", "gA")])
    assert cov["gated_off_query"] == 1 and cov["uncited"] == 1 and cov["denominator"] == 1


def test_bucket_names_come_from_the_declared_vocabulary():
    """桶名必须来自 `USER_SOURCE_COVERAGE_BUCKETS`，不能飘出第二个词表。"""
    cov = compute_user_source_coverage([_row("a", "fetched")], [], [])
    for bucket in audit.USER_SOURCE_COVERAGE_BUCKETS:
        assert bucket in cov, f"声明的桶 {bucket} 没出现在结果里"
    counted = {k for k, v in cov.items() if isinstance(v, int)}
    allowed = set(audit.USER_SOURCE_COVERAGE_BUCKETS) | {"total", "pending", "denominator"}
    assert counted <= allowed, f"多出未登记的计数字段：{sorted(counted - allowed)}"


def test_coverage_outcomes_are_not_stored_states():
    """`cited`/`uncited` 是派生指标，**不在** fetch_state 的合法词表里。

    钉这条的理由是两个写者抢一列迟早漂：collect 写读取态、audit 写 cited_by。
    一旦有人把引用情况塞进 fetch_state，返工轮就会写出"已引用却仍是 fetched"，
    而那种不一致不会让任何东西变红。
    """
    assert "cited" not in USER_SOURCE_STATES and "uncited" not in USER_SOURCE_STATES
    assert set(USER_SOURCE_STATES) == {"pending", "fetched", "unread", "blocked",
                                       "gated_off_query", "merged"}


# ── 3. issue 前缀与返工隔离（走生产 evaluate_quality）────────────────

def _evaluate(rows: List[Dict[str, Any]], claims: List[Dict[str, Any]],
              evs: List[Evidence]) -> QualityReport:
    return audit.evaluate_quality(["大理"], ["cost"], claims, evs, {"route_plan": []},
                                  user_source_rows=rows)


def test_real_issues_from_the_new_dimension_use_only_the_user_source_prefix():
    qr = _evaluate([_row("a", "fetched", evidence_id="e_a", group_id="gA"),
                    _row("b", "unread"), _row("c", "blocked")],
                   [_claim("c1", ["e_z"])], [_ev("e_a", "gA")])
    targets = [i["target"] for i in qr.issues if str(i["target"]).startswith("user_source:")]
    assert targets == ["user_source:a", "user_source:b", "user_source:c"], qr.issues


def test_user_source_issues_are_low_severity_so_signing_is_not_blocked():
    """待确认 2 已拍板：计入质量分但不阻断签发。"""
    qr = _evaluate([_row("a", "fetched", evidence_id="e_a", group_id="gA"), _row("b", "blocked")],
                   [_claim("c1", ["e_z"])], [_ev("e_a", "gA")])
    us = [i for i in qr.issues if str(i["target"]).startswith("user_source:")]
    assert us and all(i["severity"] == "low" for i in us), us


def test_new_dimension_never_produces_a_recollect_envelope_end_to_end():
    """**B-P0-3 的结构性防线**：拿生产真实 issue 喂 decide_rework。

    判据形状：允许 decide_rework 因**原有**原因（单源占比超阈）发补采，但它的目的地
    必须还是真目的地「大理」——既不能是哨兵 `"*"`，也不能是空串。
    """
    evs = [_ev("e_a", "gA"), _ev("e_b", "gB"), _ev("e_c", "gC")]
    qr = _evaluate([_row("a", "fetched", evidence_id="e_a", group_id="gA"),
                    _row("b", "unread"), _row("c", "blocked")],
                   [_claim("c1", ["e_a"])], evs)
    assert any(str(i["target"]).startswith("user_source:") for i in qr.issues)

    envelopes = decide_rework(qr, evidences=evs)
    for e in envelopes:
        if e.receiver == "collect":
            assert "*" not in e.payload["destinations"], e.payload
            assert "" not in e.payload["destinations"], e.payload
            assert all(d == "大理" for d in e.payload["destinations"]), e.payload


def test_evaluate_quality_without_a_manifest_stays_byte_for_byte_the_old_shape():
    """零回归：不带清单 ⇒ 该维度为 `{}`，且不追加任何 issue。"""
    qr = audit.evaluate_quality(["大理"], ["cost"], [_claim("c1", ["e_a"])],
                                [_ev("e_a", "gA")], {"route_plan": []})
    assert qr.user_source_coverage == {}
    assert not any(str(i["target"]).startswith("user_source:") for i in qr.issues)


def test_quality_report_adds_exactly_one_key_and_keeps_the_old_ones():
    """`to_dict()` 新增键不得改动旧键集合（下游 metrics/前端按旧键读）。"""
    legacy = {"coverage_by_dimension", "coverage_by_destination", "confidence_ratio",
              "schema_completeness", "dimension_coverage_rate", "destination_coverage_rate",
              "single_source_ratio", "viral_evidence_count", "viral_evidence_ratio",
              "opinion_ratio", "persp_verified_ratio", "persp_probed_spots",
              "persp_llm_outcome", "issues"}
    keys = set(QualityReport().to_dict())
    assert legacy <= keys, f"旧键被删：{sorted(legacy - keys)}"
    assert keys - legacy == {"user_source_coverage"}, f"多出的键要与计划一致：{sorted(keys - legacy)}"
