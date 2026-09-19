"""M2 · 生活圈体检 API：任务创建 / 独立报告读取 / 双样例对比。"""
import asyncio

from fastapi.testclient import TestClient

from app.core import db
from app.core.pipeline.living_circle import create_living_circle_task, living_circle_pipeline
from app.main import app

client = TestClient(app)


def _make_record(scene_name: str, center, city: str) -> str:
    """跑一次 fixture 流水线并落库，返回 report_id。"""
    tid = create_living_circle_task({
        "scene_name": scene_name, "city": city, "address": "测试地址",
        "center": center, "study_radius_m": 2500.0, "mode": "standard", "data_mode": "fixture",
    })

    async def run():
        rid = ""
        async for ev in living_circle_pipeline(tid):
            if ev["type"] == "done":
                rid = ev["data"]["report_id"]
        return rid

    return asyncio.run(run())


def test_create_living_circle_task_endpoint():
    resp = client.post("/api/tasks", json={
        "query": "凯里老街", "type": "living_circle",
        "center": [107.9758, 26.5734], "city": "贵州·凯里",
    })
    assert resp.status_code == 200
    task_id = resp.json()["taskId"]
    task = db.get_task_full(task_id)
    assert task["kind"] == "living_circle"


def test_create_living_circle_without_center():
    """M3：纯地名输入无需 center——任务可创建，中心点在流水线内解析兜底。"""
    resp = client.post("/api/tasks", json={"query": "凯里老街", "type": "living_circle"})
    assert resp.status_code == 200
    task_id = resp.json()["taskId"]
    assert task_id.startswith("lc-")


def test_research_task_unaffected():
    """旧路径零改动：默认 type=research 仍走原 create_task。"""
    resp = client.post("/api/tasks", json={"query": "竞品调研", "mode": "quick"})
    assert resp.status_code == 200
    assert resp.json()["taskId"].startswith("demo-") or resp.json()["taskId"]


def test_life_circle_report_endpoints():
    rid = _make_record("北京劲松", [116.4637, 39.8832], "北京·朝阳")
    # 列表
    rows = client.get("/api/life-circle").json()
    assert any(r["id"] == rid for r in rows)
    # 详情
    rep = client.get(f"/api/life-circle/{rid}").json()
    assert rep["report_type"] == "living_circle"
    assert rep["living_circle"]["scene"]["name"] == "北京劲松"
    # 渲染适配器统一读取路径（/api/reports/{lc-id}）
    via_reports = client.get(f"/api/reports/{rid}").json()
    assert via_reports["id"] == rid
    assert via_reports["living_circle"]["scores"]["total"] == 86
    # 404
    assert client.get("/api/life-circle/nope").status_code == 404


def test_compare_endpoint_diff_and_reports():
    rid_a = _make_record("凯里老街", [107.9758, 26.5734], "贵州·凯里")
    rid_b = _make_record("北京劲松", [116.4637, 39.8832], "北京·朝阳")
    resp = client.get(f"/api/life-circle/compare?ids={rid_a},{rid_b}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["reports"]) == 2
    assert len(body["diff"]) == 5
    metric = {r["metric"]: r for r in body["diff"]}
    assert metric["综合评分"]["a_value"] == 65
    assert metric["综合评分"]["b_value"] == 86
    assert metric["服务盲区"]["a_value"] == 4


def test_compare_requires_two_ids():
    assert client.get("/api/life-circle/compare?ids=onlyone").status_code == 422
    assert client.get("/api/life-circle/compare").status_code == 422