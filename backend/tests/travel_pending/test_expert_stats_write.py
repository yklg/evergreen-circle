"""专家使用统计落库与 /api/experts 端点契约（TC-E17 / TC-E18）。

背景：`expert_stats` 表是「48 位专家里只用过 6 位」这一症状的**取证现场**——
本次排查正是靠它只有 6 行、missions 各 7 而锁定硬编码兜底名单。
但该表与两个只读端点此前**没有任何测试**：统计写错、看板排序错、
端点空库 500 都会直接影响判断，却无人守护。

钉住的契约：
- DATA-01 `bump_expert_stats` 三类计数（任务数/论点数/证据数）按 id 精确累加，
  且只出现在参数字里的专家也必须建行（多采集者归因的前提，Stage B2 依赖它）；
- CT-02 `GET /api/experts` 返回全量名册（48）；`/api/experts/workload` 空库返回
  稳定结构不 500，排序按任务数降序；
- CT-01 `GET /api/experts/{eid}` 未知 id 的**当前契约是 200 + ok:false**（不是 404），
  如实记录，防误以为已按 REST 规范实现。

种子：test_subscriptions.py::test_api_create_list_delete_flow（端点直测写法）、
      test_dashboard_stats.py（统计聚合断言写法）。
运行：backend/ 下 `pytest tests/test_expert_stats_write.py -q`
"""
from fastapi.testclient import TestClient
import pytest

import app.core.db as db
from app.main import app
from app.data import load_experts

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_expert_stats():
    """逐用例清空 expert_stats。

    注意：`conftest._isolate` 只清 settings/prefs/discovery_cache，**不清 expert_stats**，
    而本表按 expert_id 累加（`bump_expert_stats` 是 ON CONFLICT DO UPDATE）。
    不本地清表的话，missions 会跨用例累积（实测 L1-012 一路涨到 7），
    「计数精确性」这类断言必然假红。这是排查中撞到的既有测试基建缺口，
    改 conftest 会影响全部 42 个测试文件，故先在本文件内自洁。
    """
    db._connect().execute("DELETE FROM expert_stats")
    db._connect().commit()
    yield

# 刻意选 3 位**从未在真实调研里出镜**的专家（兜底 6 人之外）：
# 若统计链路正常，它们应该能建行 —— 这也是 Stage B1/B2 落地后的验收抓手。
OUTSIDERS = ["L1-012", "L1-003", "L2-003"]
LEGACY_FALLBACK_6 = ["L3-001", "L2-001", "L2-002", "L1-025", "L1-030", "L3-003"]


def _workload_map():
    return {r["expert_id"]: r for r in db.expert_workload()}


# ── ① DATA-01 计数精确性 ────────────────────────────────────
def test_tc_e17_stats_accumulate_per_expert():
    """三类计数必须落在各自专家身上，不得串号、不得漏建行。"""
    db.bump_expert_stats(
        ["L3-001", "L1-012"],
        claims_by_author={"L1-012": 3, "L2-003": 5},
        evidence_by_collector={"L1-012": 40, "L1-003": 7},
    )
    w = _workload_map()
    # L1-012 同时是成员/作者/采集者 → 三个维度各自精确
    assert w["L1-012"]["missions"] == 1
    assert w["L1-012"]["claims_authored"] == 3
    assert w["L1-012"]["evidence_collected"] == 40
    # 只出现在 evidence_by_collector 里的人也要建行（B2 多采集者依赖该行为）
    assert w["L1-003"]["evidence_collected"] == 7
    assert w["L1-003"]["missions"] == 0, "未参与任务却记了任务数"
    # 只当过作者的人同理
    assert w["L2-003"]["claims_authored"] == 5
    assert w["L2-003"]["missions"] == 0
    # 纯成员只 +1 任务
    assert w["L3-001"] == {**w["L3-001"], "missions": 1, "claims_authored": 0,
                           "evidence_collected": 0}


def test_tc_e17b_bump_is_incremental_not_overwriting():
    """重复调用累加而非覆盖（一轮一轮攒出来的真实看板）。"""
    db.bump_expert_stats(["L1-012"])
    db.bump_expert_stats(["L1-012"])
    assert _workload_map()["L1-012"]["missions"] == 2


def test_tc_e17c_outsider_experts_are_recordable():
    """兜底 6 人之外的专家**在统计层完全可写**——排除「表结构只认那 6 个」。

    本 bug 的原因确定不在落库侧；留这一钉是为了让下一次同类排查不必重走这条路。
    """
    db.bump_expert_stats(OUTSIDERS)
    w = _workload_map()
    assert all(eid in w for eid in OUTSIDERS)
    assert not any(eid in LEGACY_FALLBACK_6 for eid in OUTSIDERS), "样本选错：这 3 位应是局外人"


# ── ② CT-02 /api/experts 全量名册 ───────────────────────────
def test_tc_e18_list_experts_returns_full_pool():
    r = client.get("/api/experts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == len(load_experts()) == 48, "端点漏项 → 前端专家页永远看不到这些人"
    assert {i["id"] for i in items} == {e["id"] for e in load_experts()}


def test_tc_e18b_workload_empty_db_is_stable():
    """空库时看板必须返回 48 行全零，而不是 500 或空数组。

    全空数组会让「谁被用过」看起来像「系统没有专家」，与本 bug 的症状难以区分。
    """
    r = client.get("/api/experts/workload")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 48
    assert all(x["missions"] == 0 and x["evidence_collected"] == 0 for x in rows)
    assert all(x["last_active"] == "" for x in rows), "空态必须给出可渲染的缺省值"


def test_tc_e18c_workload_reflects_stats_and_sorts_desc():
    db.bump_expert_stats(["L1-012"])
    db.bump_expert_stats(["L1-012", "L2-003"])
    db.bump_expert_stats(["L1-012", "L2-003", "L3-001"])
    rows = client.get("/api/experts/workload").json()
    order = [x["missions"] for x in rows]
    assert order == sorted(order, reverse=True), "看板排序失效"
    by_id = {x["id"]: x for x in rows}
    assert by_id["L1-012"]["missions"] == 3
    assert by_id["L2-003"]["missions"] == 2
    assert by_id["L3-001"]["missions"] == 1


def test_tc_e18d_unknown_expert_current_contract_is_200_not_404():
    """如实记录当前契约：未知 id → 200 + ok:false。

    这不是理想设计（应为 404），但改它属于接口契约变更，需单独确认；
    本钉的作用是先让「它现在长什么样」有据可查，避免下游按 404 分支写代码。
    """
    r = client.get("/api/experts/L9-999")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    ok = client.get("/api/experts/L1-012")
    assert ok.status_code == 200
    assert ok.json()["id"] == "L1-012"
    assert ok.json()["stats"]["missions"] == 0, "无记录时必须给零值统计而非缺键"
