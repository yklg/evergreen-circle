"""竞品监控订阅 CRUD 契约测试（执行计划 G1 前置基线；方案 B-11 单元 + B-12 API）。

种子模式：test_bulk_assign / test_collect_endpoint 的端点契约（200 + 响应 JSON）与
db._make_report 矿种辅助；此处直接对 subscriptions 表断言 DB 终态 + HTTP 契约。

守护的不变量（db.py:838-906）：
- create：INSERT OR REPLACE，幂等（同 sub_id 再建覆盖，行数不增）且 brands 数组 round-trip。
- list：按 created_at 倒序。
- get：不存在 → None。
- delete：无权限语义，重复删除不抛；接口恒 {"ok": true}。
- mark_subscription_run：last_run_at/last_report_id 更新、run_count 自增。
运行：backend/ 下 `pytest tests/test_subscriptions.py -q`
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.main import app


@pytest.fixture(autouse=True)
def _clean_subscriptions():
    db._connect().execute("DELETE FROM subscriptions")
    db._connect().commit()
    yield


# ── B-11 单元 ────────────────────────────────────────────
def test_create_roundtrip_and_get():
    sub = db.create_subscription("sub_x", "新势力车企", ["品牌A", "品牌B"])
    assert sub["sub_id"] == "sub_x"
    assert sub["query"] == "新势力车企"
    assert sub["brands"] == ["品牌A", "品牌B"]
    assert sub["run_count"] == 0
    got = db.get_subscription("sub_x")
    assert got and got["query"] == "新势力车企"
    assert db.get_subscription("nope") is None


def test_create_idempotent_replace():
    db.create_subscription("sub_x", "q1", ["A"])
    db.create_subscription("sub_x", "q2", ["B", "C"])
    rows = db.list_subscriptions()
    assert len(rows) == 1
    assert rows[0]["query"] == "q2"
    assert rows[0]["brands"] == ["B", "C"]


def test_list_ordering_desc():
    db.create_subscription("sub_1", "first", [])
    db.create_subscription("sub_2", "second", [])
    # 同秒创建 created_at 相同：用 update 显式错开时间再断言倒序
    c = db._connect()
    c.execute("UPDATE subscriptions SET created_at='2026-09-01T09:00:00' WHERE sub_id='sub_1'")
    c.execute("UPDATE subscriptions SET created_at='2026-09-02T09:00:00' WHERE sub_id='sub_2'")
    c.commit()
    ids = [s["sub_id"] for s in db.list_subscriptions()]
    assert ids == ["sub_2", "sub_1"]  # created_at 倒序


def test_delete_removes_and_idempotent():
    db.create_subscription("sub_x", "q", [])
    db.delete_subscription("sub_x")
    assert db.get_subscription("sub_x") is None
    db.delete_subscription("sub_x")  # 重复删除不抛
    assert db.list_subscriptions() == []


def test_mark_subscription_run_updates():
    db.create_subscription("sub_x", "q", [])
    db.mark_subscription_run("sub_x", "r_9001")
    sub = db.get_subscription("sub_x")
    assert sub["last_report_id"] == "r_9001"
    assert sub["run_count"] == 1
    assert sub["last_run_at"]
    db.mark_subscription_run("sub_x", "r_9002")
    assert db.get_subscription("sub_x")["run_count"] == 2


def test_create_null_query_ok():
    """缺省 query 空字符串入库不崩（服务端契约宽容）。"""
    sub = db.create_subscription("sub_null", "", [])
    assert sub["query"] == ""


# ── B-12 API 契约 ────────────────────────────────────────
def test_api_create_list_delete_flow():
    cli = TestClient(app)
    r = cli.post("/api/subscriptions", json={"query": "定价行为", "brands": ["A公司"]})
    assert r.status_code == 200
    sub = r.json()
    assert sub["sub_id"].startswith("sub_")
    assert sub["brands"] == ["A公司"]

    listing = cli.get("/api/subscriptions").json()
    assert len(listing) == 1
    assert listing[0]["sub_id"] == sub["sub_id"]

    d = cli.delete(f"/api/subscriptions/{sub['sub_id']}")
    assert d.status_code == 200
    assert d.json() == {"ok": True}
    assert cli.get("/api/subscriptions").json() == []


def test_api_delete_missing_ok():
    """删除不存在的订阅 → 仍 200（现状语义：幂等无异常）。"""
    r = TestClient(app).delete("/api/subscriptions/sub_ghost")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_api_create_default_brands_empty():
    """brands 缺省 → 服务端默认 []（SubscriptionBody 默认值契约），200。"""
    r = TestClient(app).post("/api/subscriptions", json={"query": "q"})
    assert r.status_code == 200
    assert r.json()["brands"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))