"""目的地情报图谱（`db.destination_graph` / `evidence_facets` 派生）契约测试。

为什么单独一个文件：图谱是本轮新立的那份**唯一聚合实现**（评审 R1）——
`evidence_facets` 的目的地分布从它派生，`/api/intel` 的图谱段也出自它。
钉的正是"这一份实现"的口径，与仪表盘/情报概览的字段契约（`test_dashboard_stats.py`）分开。

守护的不变量：
- 全库口径：不受 `query_evidences` 的 `limit` 影响（客户端截断样本冒充全量是本轮根因）。
- 空归属显式报数：不再靠 SQL 排除 + 前端 continue 两层各自抹掉。
- 值域：`avg_credibility` 直读库内 0–100，不在任何一层再乘 100。
- 形状：节点带 `domain`/`source`，为「生活圈 POI 是否进 evidences」留换源形状。
- 名次确定性：并列计数按目的地名升序，截断结果可预测。
- 单一事实源：facets 传图或不传图，结果必须一致。

运行：backend/ 下 `pytest tests/test_destination_graph.py -q`
"""
import pytest

import app.core.db as db


@pytest.fixture(autouse=True)
def _clean_business_tables():
    """逐用例清空业务表，避免聚合 COUNTS 跨用例累积。"""
    c = db._connect()
    for t in ("evidences", "traces", "report_feedback", "tasks", "reports"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    yield


def _make_report(rid, *, evidence=None, claims=None, metrics=None):
    report = {
        "id": rid, "title": f"报告 {rid}", "subtitle": "", "query": "测试查询",
        "destinations": ["目的地A"], "experts": [], "cover_image": "",
        "created_at": db._now(),
        "evidence": evidence or [], "claims": claims or [], "metrics": metrics or {},
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


def test_graph_is_full_library_not_truncated_sample():
    """图谱口径 = 全库：证据列表受 limit 约束，图谱不受（两者别混）。"""
    evs = [_ev(f"e_g_{i}", "douyin", "目的地A" if i % 2 else "目的地B", 60 + i) for i in range(30)]
    _make_report("r_graph", evidence=evs)
    assert db.destination_graph()["scanned"] == 30
    assert {n["destination"]: n["count"] for n in db.destination_graph()["nodes"]} == {
        "目的地A": 15, "目的地B": 15,
    }
    assert len(db.query_evidences(limit=5)) == 5, "证据列表仍受 limit 约束"
    assert db.destination_graph()["scanned"] == 30, "图谱不随 limit 变化"


def test_graph_reports_unattributed_instead_of_dropping_it():
    """空归属显式报数：过去它被两层各自 continue 抹掉，UI 上根本不存在。"""
    _make_report("r_unattr", evidence=[
        _ev("e_u1", "news", "", 70),
        _ev("e_u2", "news", "大理", 70),
        _ev("e_u3", "web", "", 55),
    ])
    g = db.destination_graph()
    assert g["unattributed"] == 2
    assert g["scanned"] == 3
    assert [n["destination"] for n in g["nodes"]] == ["大理"]


def test_graph_node_shape_and_credibility_range():
    """值域与形状：0–100 直读；节点带 domain/source 供未来换源。"""
    _make_report("r_shape", evidence=[_ev("e_s1", "douyin", "目的地A", 98),
                                      _ev("e_s2", "zhihu", "目的地A", 60)])
    node = db.destination_graph()["nodes"][0]
    assert 0 <= node["avg_credibility"] <= 100
    assert node["avg_credibility"] == 79.0
    assert node["domain"] == "travel" and node["source"] == "evidences"
    assert node["source_types"] == ["douyin", "zhihu"]
    assert node["last_at"]
    assert node["count"] == 2


def test_graph_tie_break_is_deterministic():
    """并列名次的截断必须可预测（评审 T5）：同计数时按目的地名升序进前 12。

    `test_dashboard_stats.py` 的 Top12 用例刻意用唯一计数回避了并列；生产里有并列，
    换实现就会换出另外几个目的地而测试不红 —— 那是行为契约静默变更。
    """
    evs = []
    for i in range(11):
        for j in range(2):
            evs.append(_ev(f"e_tie_{i}_{j}", "douyin", f"地{i:02d}"))
    for name in ("tie-C", "tie-B", "tie-A"):  # 乱序落库，防插入顺序左右结果
        evs.append(_ev(f"e_tie_x_{name}", "douyin", name))
    _make_report("r_tie", evidence=evs)

    assert [n["destination"] for n in db.destination_graph()["nodes"]] == (
        [f"地{i:02d}" for i in range(11)] + ["tie-A", "tie-B", "tie-C"]
    ), "图谱排序 = count DESC 后 destination ASC"
    by = db.evidence_facets()["by_destination"]
    assert len(by) == 12
    assert "tie-A" in by, "并列第 12 名应留下名字最小者"
    assert "tie-B" not in by and "tie-C" not in by
    assert by == db.evidence_facets()["by_destination"], "两次调用结果必须一致"


def test_facets_derives_from_graph_single_source():
    """facets 的目的地分布由图谱派生：两份 SQL 会漂成两个口径（评审 R1）。"""
    _make_report("r_eq", evidence=[
        _ev("e_q1", "douyin", "目的地A", 90), _ev("e_q2", "weibo", "目的地A", 80),
        _ev("e_q3", "news", "目的地B", 70), _ev("e_q4", "news", "", 60),
    ])
    g = db.destination_graph()
    facets = db.evidence_facets(graph=g)
    assert facets["by_destination"] == {n["destination"]: n["count"] for n in g["nodes"]}
    assert facets["by_type"] == {"douyin": 1, "weibo": 1, "news": 2}
    assert facets["total"] == 4
    assert db.evidence_facets() == facets, "不传 graph 时自算，结果必须一致"


def test_facets_truncates_to_12_from_full_graph():
    """14 个目的地 → facets 仍只给 12，而图谱给全 14（截断只在展示层）。"""
    evs = [_ev(f"e_tr_{i}", "douyin", f"目的地{i:02d}", 70) for i in range(14)]
    _make_report("r_tr", evidence=evs)
    assert len(db.evidence_facets()["by_destination"]) == 12
    assert len(db.destination_graph()["nodes"]) == 14


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
