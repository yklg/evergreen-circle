"""仪表盘实时聚合（dashboard_stats / intel_overview / evidence_facets）正确性测试。

《同类项目对比与项目现状审查-测试覆盖方案》B-04（单元）/ B-05（API 契约）。
种子模式（test_refine_evidence / test_report_brief 归纳）：
- conftest 的 VERDA_DB_PATH 临时库隔离 + autouse _isolate；本文件另加逐用例清空业务表。
- 造数用 db.save_report 种子辅助（data 内嵌 metrics/claims/evidence 快照，evidences 表由 save_report 落库）。
- API 契约用 TestClient（main.py:472/478），断言 200 + 关键字段形状。

守护的聚合不变量（db.py:728-832）：
- 空库：全部 0 不崩（avg_ev/fact_rate/avg_efficiency 除零保护）。
- 计数正确：reports / evidence_total / claim_total / high_conf_total 与库中行统计一致。
- 比例口径：avg_ev = ev_total/reports；fact_rate = high/claim*100（round）。
- intel_overview 容错：坏 data JSON、缺 metrics/efficiency 字段 → 不抛、卡片仍含该报告。
- evidence_facets：by_type 含空串平台？——按值分组全部收录；by_brand 排除空品牌、Top12 降序。
运行：backend/ 下 `pytest tests/test_dashboard_stats.py -q`
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.main import app


@pytest.fixture(autouse=True)
def _clean_business_tables():
    """逐用例清空业务表，避免聚合 COUNTS 跨用例累积。"""
    c = db._connect()
    for t in ("evidences", "traces", "report_feedback", "tasks", "reports"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    yield


def _make_report(rid, *, claims=None, evidence=None, metrics=None, created_at=None,
                 title="报告"):
    """种子报告：claims/metrix 落 reports 列 + data 快照；evidence 一并写入 evidences 表。"""
    claims = claims or []
    evidence = evidence or []
    report = {
        "id": rid, "title": f"{title} {rid}", "subtitle": "", "query": "测试查询",
        "brands": ["品牌A"], "experts": [], "cover_image": "",
        "created_at": created_at or db._now(),
        "evidence": evidence, "claims": claims, "metrics": metrics or {},
    }
    db.save_report(report, task_id="")
    return report


def _ev(eid, source_type="douyin", brand="品牌A", credibility=80.0):
    return {
        "evidence_id": eid, "source_url": "https://example.com/" + eid,
        "source_type": source_type, "domain": "example.com", "title": "证据 " + eid,
        "excerpt": "内容", "credibility": credibility, "collected_by": "tester",
        "brand": brand, "captured_at": db._now(),
    }


def _metrics(manual=60.0, elapsed=10.0, mult=6.0, tokens=5000, cov=3.0):
    return {
        "efficiency": {"manual_estimate_minutes": manual, "elapsed_minutes": elapsed,
                       "efficiency_multiple": mult, "tokens_used": tokens},
        "coverage": {"coverage_multiple": cov},
    }


# ── B-04 单元：空库 / 造数 / 除零 / 容错 ─────────────────
def test_dashboard_stats_empty_db():
    s = db.dashboard_stats()
    assert s["reports"] == 0
    assert s["evidence_total"] == 0
    assert s["claim_total"] == 0
    assert s["high_conf_total"] == 0
    assert s["avg_evidence_per_report"] == 0
    assert s["fact_accuracy"] == 0
    assert s["platform_distribution"] == {}
    assert s["brand_distribution"] == {}
    assert s["minutes_saved"] == 0
    assert s["avg_efficiency"] == 0
    assert s["avg_coverage"] == 0
    assert s["total_tokens"] == 0
    assert s["research_cards"] == []


def test_dashboard_stats_with_data():
    _make_report("r_ds_1",
                 claims=[{"id": "c1", "confidence": "high"}, {"id": "c2", "confidence": "medium"},
                         {"id": "c3", "confidence": "medium"}],
                 evidence=[_ev("e1", "douyin", "品牌A"), _ev("e2", "weibo", "品牌A")],
                 metrics=_metrics(manual=60, elapsed=10, mult=6, tokens=5000, cov=3))
    _make_report("r_ds_2",
                 claims=[{"id": "c4", "confidence": "high"}, {"id": "c5", "confidence": "high"}],
                 evidence=[_ev("e3", "douyin", "品牌B", 90)],
                 metrics=_metrics(manual=30, elapsed=20, mult=1.5, tokens=1000, cov=2))

    s = db.dashboard_stats()
    assert s["reports"] == 2
    assert s["evidence_total"] == 3
    assert s["claim_total"] == 5
    assert s["high_conf_total"] == 3
    assert s["avg_evidence_per_report"] == 1.5          # round(3/2, 1)
    assert s["fact_accuracy"] == 60                     # round(3/5*100)
    assert s["platform_distribution"] == {"douyin": 2, "weibo": 1}
    assert s["brand_distribution"] == {"品牌A": 2, "品牌B": 1}
    # intel_overview 聚合：manual-elapsed 求和 50+10=60；avg = mean([6,1.5])=3.75→3.8；tokens=6000
    assert s["minutes_saved"] == 60
    assert s["avg_efficiency"] == 3.8
    assert s["avg_coverage"] == 2.5
    assert s["total_tokens"] == 6000
    assert len(s["research_cards"]) == 2


def test_dashboard_stats_zero_division_single_report():
    """仅 1 报告、无 evidence/claims：除零保护 → 0，不崩。"""
    _make_report("r_ds_3", metrics={})
    s = db.dashboard_stats()
    assert s["reports"] == 1
    assert s["evidence_total"] == 0
    assert s["claim_total"] == 0
    assert s["fact_accuracy"] == 0
    assert s["avg_evidence_per_report"] == 0
    assert s["minutes_saved"] == 0           # max(0, 0-0)
    assert s["research_cards"][0]["minutes_saved"] == 0


def test_intel_overview_bad_json_row():
    """reports.data 为损坏 JSON → intel_overview 不抛、该报告卡片 metrics 为空实体。"""
    _make_report("r_ds_bad")
    db._connect().execute("UPDATE reports SET data='{oops-not-json'" " WHERE report_id='r_ds_bad'")
    db._connect().commit()

    intel = db.intel_overview()
    assert intel["minutes_saved"] == 0
    assert intel["avg_efficiency"] == 0
    cards = {c["id"]: c for c in intel["cards"]}
    assert "r_ds_bad" in cards
    assert cards["r_ds_bad"]["minutes_saved"] == 0
    assert cards["r_ds_bad"]["tokens_used"] is None


def test_intel_overview_missing_metrics_fields():
    """data.metrics 缺 efficiency/coverage 字段或缺子键 → 各计数值按 0 处理，不抛。"""
    _make_report("r_ds_m1", metrics={"efficiency": {"manual_estimate_minutes": 50}})
    _make_report("r_ds_m2", metrics={"coverage": {"coverage_multiple": 4}})
    intel = db.intel_overview()
    cards = {c["id"]: c for c in intel["cards"]}
    assert cards["r_ds_m1"]["minutes_saved"] == 50      # elapsed 缺省 0
    assert cards["r_ds_m2"]["minutes_saved"] == 0       # manual 缺省 0
    assert intel["avg_coverage"] == 4                   # 仅 m2 有 echo
    assert intel["total_tokens"] == 0


def test_evidence_facets_grouping():
    _make_report("r_ds_f", evidence=[
        _ev("e_f1", "douyin", "品牌A", 70),
        _ev("e_f2", "douyin", "品牌A", 60),
        _ev("e_f3", "weibo", "", 90),    # 空品牌应被 by_brand 排除
    ])
    f = db.evidence_facets()
    assert f["total"] == 3
    assert f["by_type"] == {"douyin": 2, "weibo": 1}
    assert f["by_brand"] == {"品牌A": 2}                  # 空串不收录


# ── B-05 API 契约 ───────────────────────────────────────
def test_api_dashboard_empty():
    r = TestClient(app).get("/api/dashboard")
    assert r.status_code == 200
    j = r.json()
    assert j["reports"] == 0
    assert "evidence_total" in j and "fact_accuracy" in j and "research_cards" in j


def test_api_dashboard_with_data():
    _make_report("r_ds_api", claims=[{"id": "a1", "confidence": "high"}],
                 evidence=[_ev("e_api1", "douyin", "品牌A")],
                 metrics=_metrics(manual=30, elapsed=10, mult=3, tokens=2000))
    j = TestClient(app).get("/api/dashboard").json()
    assert j["reports"] == 1
    assert j["evidence_total"] == 1
    assert j["claim_total"] == 1
    assert j["high_conf_total"] == 1
    assert j["fact_accuracy"] == 100


def test_api_evidences_filters():
    _make_report("r_ds_ef", evidence=[
        _ev("e_f10", "douyin", "品牌A", 90),
        _ev("e_f20", "douyin", "品牌B", 50),
        _ev("e_f30", "weibo", "品牌A", 80),
    ])
    cli = TestClient(app)
    # 全量
    j = cli.get("/api/evidences").json()
    assert len(j["items"]) == 3
    assert j["facets"]["total"] == 3
    # report_id 过滤
    assert len(cli.get("/api/evidences", params={"report_id": "r_ds_ef"}).json()["items"]) == 3
    assert len(cli.get("/api/evidences", params={"report_id": "nope"}).json()["items"]) == 0
    # min_cred 边界：70 只留 90/80（59 与 70 的边界语义同 test_refine_pipeline_min_cred_boundary）
    cred = cli.get("/api/evidences", params={"min_cred": 70}).json()["items"]
    assert {i["evidence_id"] for i in cred} == {"e_f10", "e_f30"}
    # brand + source_type 组合
    combo = cli.get("/api/evidences", params={"brand": "品牌A", "source_type": "weibo"}).json()["items"]
    assert [i["evidence_id"] for i in combo] == ["e_f30"]
    # limit
    assert len(cli.get("/api/evidences", params={"limit": 2}).json()["items"]) == 2


def test_api_evidences_empty():
    j = TestClient(app).get("/api/evidences").json()
    assert j["items"] == []
    assert j["facets"]["total"] == 0


# ── B-13 聚合性能基线快照（宽松门禁，防无限回归）────────────
def test_dashboard_aggregation_under_loose_latency():
    """批量造数（3 报告 × 40 证据 + claims）后，dashboard_stats + 端点总耗时 < 2s。

    仅供回归快照（执行计划性能维度基线），不设硬性 SLO；真实 4s+ 说明聚合放大明显。
    """
    import time

    for i in range(3):
        _make_report(f"r_perf_{i}",
                     claims=[{"id": f"p{i}c{j}", "confidence": "high"} for j in range(20)],
                     evidence=[_ev(f"p{i}e{j}", "douyin" if j % 2 else "weibo", f"品牌{j % 3}") for j in range(40)],
                     metrics=_metrics(manual=30, elapsed=10, mult=3, tokens=2000))
    t0 = time.perf_counter()
    s = db.dashboard_stats()
    r = TestClient(app).get("/api/dashboard")
    elapsed = time.perf_counter() - t0
    assert s["reports"] == 3
    assert s["evidence_total"] == 120
    assert r.status_code == 200
    assert elapsed < 2.0, f"聚合耗时 {elapsed:.2f}s 超出宽松门禁（疑似聚合放大）"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))