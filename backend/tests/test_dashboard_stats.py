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
- evidence_facets：by_type 含空串平台？——按值分组全部收录；by_destination 排除空目的地、Top12 降序。
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
        "destinations": ["目的地A"], "experts": [], "cover_image": "",
        "created_at": created_at or db._now(),
        "evidence": evidence, "claims": claims, "metrics": metrics or {},
    }
    db.save_report(report, task_id="")
    return report


def _ev(eid, source_type="douyin", destination="目的地A", credibility=80.0):
    return {
        "evidence_id": eid, "source_url": "https://example.com/" + eid,
        "source_type": source_type, "domain": "example.com", "title": "证据 " + eid,
        "excerpt": "内容", "credibility": credibility, "collected_by": "tester",
        "destination": destination, "captured_at": db._now(),
    }


def _metrics(manual=60.0, elapsed=10.0, mult=6.0, tokens=5000, cov=3.0):
    return {
        "efficiency": {"manual_estimate_minutes": manual, "elapsed_minutes": elapsed,
                       "efficiency_multiple": mult, "tokens_used": tokens},
        "coverage": {"coverage_multiple": cov},
    }


# ── B-04 单元：空库 / 造数 / 除零 / 容错 ─────────────────
# 本轮真分家：`dashboard_stats()` 只留侧栏真正消费的两键，其余口径的断言逐条
# 重锚到 `intel_overview()` —— 一条不删，只是钉在键真正所在的那份契约上。
def test_dashboard_stats_exposes_only_sidebar_two_keys():
    """仪表盘契约收缩到两键：多一个键就是又一次"侧栏轮询付整包聚合"。"""
    assert set(db.dashboard_stats()) == {"reports", "evidence_total"}
    assert db.dashboard_stats() == {"reports": 0, "evidence_total": 0}


def test_intel_overview_empty_db():
    """空库：全部 0 不崩（除零保护），图谱与卡片为空集合而非 None。"""
    s = db.intel_overview()
    assert s["report_total"] == 0
    assert s["evidence_total"] == 0
    assert s["claim_total"] == 0
    assert s["high_conf_total"] == 0
    assert s["avg_evidence_per_report"] == 0
    assert s["fact_accuracy"] == 0
    assert s["platform_distribution"] == {}
    assert s["minutes_saved"] == 0
    assert s["avg_efficiency"] == 0
    assert s["avg_coverage"] == 0
    assert s["total_tokens"] == 0
    assert s["cards"] == []
    assert s["cards_truncated"] is False
    assert s["destination_graph"] == {"nodes": [], "unattributed": 0, "scanned": 0}


def test_intel_overview_with_data():
    _make_report("r_ds_1",
                 claims=[{"id": "c1", "confidence": "high"}, {"id": "c2", "confidence": "medium"},
                         {"id": "c3", "confidence": "medium"}],
                 evidence=[_ev("e1", "douyin", "目的地A"), _ev("e2", "weibo", "目的地A")],
                 metrics=_metrics(manual=60, elapsed=10, mult=6, tokens=5000, cov=3))
    _make_report("r_ds_2",
                 claims=[{"id": "c4", "confidence": "high"}, {"id": "c5", "confidence": "high"}],
                 evidence=[_ev("e3", "douyin", "目的地B", 90)],
                 metrics=_metrics(manual=30, elapsed=20, mult=1.5, tokens=1000, cov=2))

    s = db.intel_overview()
    assert s["report_total"] == 2
    assert s["evidence_total"] == 3
    assert s["claim_total"] == 5
    assert s["high_conf_total"] == 3
    assert s["avg_evidence_per_report"] == 1.5          # round(3/2, 1)
    assert s["fact_accuracy"] == 60                     # round(3/5*100)
    assert s["platform_distribution"] == {"douyin": 2, "weibo": 1}
    assert {n["destination"]: n["count"] for n in s["destination_graph"]["nodes"]} == {
        "目的地A": 2,
        "目的地B": 1,
    }
    # intel_overview 聚合：manual-elapsed 求和 50+10=60；avg = mean([6,1.5])=3.75→3.8；tokens=6000
    assert s["minutes_saved"] == 60
    assert s["avg_efficiency"] == 3.8
    assert s["avg_coverage"] == 2.5
    assert s["total_tokens"] == 6000
    assert len(s["cards"]) == 2


def test_intel_overview_zero_division_single_report():
    """仅 1 报告、无 evidence/claims：除零保护 → 0，不崩。"""
    _make_report("r_ds_3", metrics={})
    s = db.intel_overview()
    assert s["report_total"] == 1
    assert s["evidence_total"] == 0
    assert s["claim_total"] == 0
    assert s["fact_accuracy"] == 0
    assert s["avg_evidence_per_report"] == 0
    assert s["minutes_saved"] == 0           # max(0, 0-0)
    assert s["cards"][0]["minutes_saved"] == 0


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
        _ev("e_f1", "douyin", "目的地A", 70),
        _ev("e_f2", "douyin", "目的地A", 60),
        _ev("e_f3", "weibo", "", 90),    # 空目的地应被 by_destination 排除
    ])
    f = db.evidence_facets()
    assert f["total"] == 3
    assert f["by_type"] == {"douyin": 2, "weibo": 1}
    assert f["by_destination"] == {"目的地A": 2}          # 空串不收录


# ── destination 语义契约（R4 键名 / R5 边界截断）─────────────
def test_intel_cards_sorted_by_created_at_desc():
    """概览卡必须按 `created_at` 降序发 —— 前端「仅列最近 N 份」这句话的唯一前提。

    报告中心把 25 份压成 9 张时屏上写的是「仅列**最近** 9 份（库内共 25 份）」，
    而"最近"完全由这条 SQL 的排序决定（`ORDER BY created_at DESC LIMIT 60`）。
    排序哪天被改掉，页面不会报错、数字也全都对，只有那句"最近"会静默变假话 ——
    正是本轮在概览卡上专门消灭的那类缺陷，所以判据钉在**返回序列**上而非 SQL 文本。
    """
    _make_report("r_old", created_at="2026-09-01T09:00:00")
    _make_report("r_new", created_at="2026-09-20T09:00:00")
    _make_report("r_mid", created_at="2026-09-10T09:00:00")

    cards = db.intel_overview()["cards"]
    assert [c["id"] for c in cards] == ["r_new", "r_mid", "r_old"], "cards 顺序即前端「最近」的定义"
    assert [c["created_at"] for c in cards] == sorted(
        [c["created_at"] for c in cards], reverse=True
    )


def test_facets_top12_truncation_boundary():
    """by_destination Top12：13 个目的地取 12，且按证据数降序（第 13 名被截断）。"""
    evs = []
    for i in range(13):
        # 第 i 个目的地证据数 = 13 - i（目的地0 最多），保证名次可判定
        for j in range(13 - i):
            evs.append(_ev(f"e_top_{i}_{j}", "douyin", f"目的地{i:02d}"))
    _make_report("r_ds_top", evidence=evs)
    by_dest = db.evidence_facets()["by_destination"]
    assert len(by_dest) == 12, "Top12 必须截断（前端标签云只渲染前 12）"
    counts = list(by_dest.values())
    assert counts == sorted(counts, reverse=True), "必须按证据数降序"
    assert "目的地12" not in by_dest, "第 13 名（证据数最少）应被截断"
    assert by_dest["目的地00"] == 13


def test_destination_distribution_keys_and_empty_excluded():
    """目的地口径的键名契约（R4）：叫 destination，不叫 brand；空目的地不进图谱。"""
    _make_report("r_ds_d1", evidence=[_ev("e_d1", "douyin", "大理", 80),
                                      _ev("e_d2", "weibo", "", 70)])
    intel = db.intel_overview()
    nodes = intel["destination_graph"]["nodes"]
    assert [n["destination"] for n in nodes] == ["大理"]
    assert "brand_distribution" not in intel
    assert all("brand" not in n for n in nodes)
    # 空目的地不隐式消失：作为 unattributed 显式报数（评审 R1 的双层丢弃形状）
    assert intel["destination_graph"]["unattributed"] == 1
    assert intel["destination_graph"]["scanned"] == 2
    cards = intel["cards"]
    assert "destinations" in cards[0] and "brands" not in cards[0]


# ── B-05 API 契约 ───────────────────────────────────────
def test_api_dashboard_contract_is_two_keys():
    """`/api/dashboard` 与 `/api/intel` 真分家：仪表盘多吐一个重字段即红。"""
    j = TestClient(app).get("/api/dashboard").json()
    assert set(j) == {"reports", "evidence_total"}
    assert j == {"reports": 0, "evidence_total": 0}


def test_api_intel_empty_and_with_data():
    cli = TestClient(app)
    empty = cli.get("/api/intel")
    assert empty.status_code == 200
    assert empty.json()["cards"] == []
    assert set(empty.json()) >= {
        "report_total", "evidence_total", "claim_total", "high_conf_total",
        "fact_accuracy", "platform_distribution", "destination_graph", "cards",
    }

    _make_report("r_ds_api", claims=[{"id": "a1", "confidence": "high"}],
                 evidence=[_ev("e_api1", "douyin", "目的地A")],
                 metrics=_metrics(manual=30, elapsed=10, mult=3, tokens=2000))
    j = cli.get("/api/intel").json()
    assert j["report_total"] == 1
    assert j["evidence_total"] == 1
    assert j["claim_total"] == 1
    assert j["high_conf_total"] == 1
    assert j["fact_accuracy"] == 100
    assert j["destination_graph"]["nodes"][0]["count"] == 1


def test_api_evidences_never_triggers_whole_aggregate(monkeypatch):
    """成本判据（评审 T1）：查证据不得付一次整包聚合。

    `evidence_facets()` 每请求都跑，若它的派生链走到 `intel_overview()`，
    就等于每次翻证据库都反序列化 ≤60 份报告 JSON —— 这条只能钉在调用次数上，
    写在注释里的"不许进缓存"约束将来一定会漂。
    """
    calls: list = []
    real = db._agg_compute

    def spy():
        calls.append(1)
        return real()

    monkeypatch.setattr(db, "_agg_compute", spy)
    db.invalidate_aggregates()
    _make_report("r_cost", evidence=[_ev("e_cost", "douyin", "目的地A", 88)])

    j = TestClient(app).get("/api/evidences").json()
    assert j["facets"]["by_destination"] == {"目的地A": 1}   # facets 仍要算对
    assert calls == [], "/api/evidences 触发了整包聚合（_agg_compute）"

    # 正对照：spy 确实接得上，否则上面那条断言会空过
    TestClient(app).get("/api/dashboard")
    assert calls, "对照失效：_agg_compute 未被监视"


def test_api_evidences_filters():
    _make_report("r_ds_ef", evidence=[
        _ev("e_f10", "douyin", "目的地A", 90),
        _ev("e_f20", "douyin", "目的地B", 50),
        _ev("e_f30", "weibo", "目的地A", 80),
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
    # destination + source_type 组合
    combo = cli.get("/api/evidences", params={"destination": "目的地A", "source_type": "weibo"}).json()["items"]
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
                     evidence=[_ev(f"p{i}e{j}", "douyin" if j % 2 else "weibo", f"目的地{j % 3}") for j in range(40)],
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