"""M2 · 生活圈体检 API：任务创建 / 独立报告读取 / 双样例对比。"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.pipeline.living_circle import create_living_circle_task, living_circle_pipeline
from app.main import app

client = TestClient(app)

# 数值断言一律**锚定夹具**而不是硬编码数字：夹具是"真实实跑快照"，
# 一旦重算（AK 复跑），硬编码会让整组用例假红，掩盖真正想守的「接口搬运链路」语义。
FIXTURES = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
KAILI_FX = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
JINSONG_FX = json.loads((FIXTURES / "beijing-jinsong.json").read_text(encoding="utf-8"))


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
    assert via_reports["living_circle"]["scores"]["total"] == JINSONG_FX["scores"]["total"]
    # 空间口径举证字段必须活到接口层（适配器不得吞掉可观测性出口）
    cal = via_reports["living_circle"]["caliber"]
    for k in ("reach_full_min", "reach_circumradius_m", "collect_radius_m", "cells_judged", "cells_unknown"):
        assert k in cal, f"接口层丢掉了 caliber.{k}"
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
    assert metric["综合评分"]["a_value"] == KAILI_FX["scores"]["total"]  # 凯里
    assert metric["综合评分"]["b_value"] == JINSONG_FX["scores"]["total"]  # 劲松
    assert metric["服务盲区"]["a_value"] == len(KAILI_FX["blindspots"])
    assert metric["服务盲区"]["b_value"] == len(JINSONG_FX["blindspots"])


def test_compare_requires_two_ids():
    assert client.get("/api/life-circle/compare?ids=onlyone").status_code == 422
    assert client.get("/api/life-circle/compare").status_code == 422


def test_map_config_endpoint():
    """C7 · 地图配置端点：浏览器 AK + 个性化 styleId 明文下发（公开键，供 BMapGL）。"""
    resp = client.get("/api/life-circle/map-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "browser_ak" in body
    assert "map_style_id" in body
    # 本地 .env 已配浏览器 AK → 非空；styleId 有值则透传（测试环境空值也允许）
    assert isinstance(body["browser_ak"], str)
    assert isinstance(body["map_style_id"], str)


# ── I3/I4 · regions 端点 + 分享端点（T1/E1，无 AK 依赖）───────────────

def test_regions_endpoint_tree_structure():
    resp = client.get("/api/life-circle/regions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    regions = body["regions"]
    assert len(regions) >= 34  # 省 ≥34
    prov = next((p for p in regions if p["province"] == "上海市"), None)
    assert prov is not None
    sh = next((c for c in prov["cities"] if c["name"] == "上海市"), None)
    assert sh is not None
    assert "浦东新区" in sh["districts"]
    # 纯名称树（无坐标，体积可控）
    for p in regions[:3]:
        assert isinstance(p["cities"], list)


def test_share_endpoint_ok_and_404():
    rid = _make_record("凯里老街", [107.9758, 26.5734], "贵州·凯里")
    resp = client.get(f"/api/life-circle/{rid}/share")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["url"] == f"/report/{rid}?share=1"
    assert body["scene_name"] == "凯里老街"
    assert body["title"]
    assert client.get("/api/life-circle/nope/share").status_code == 404


# ── I5/I6 · 离线报告：对比不可比 + 历史 total_score=NULL ──────────────

def _make_offline_record(scene_name: str, monkeypatch) -> str:
    """无 AK 跑 offline 流水线（monkeypatch 清空 AK）→ 落库离线报告，返回 report_id。"""
    import app.core.pipeline.living_circle as lc_mod
    from app.core.config import Settings

    monkeypatch.setattr(lc_mod, "get_settings", lambda: Settings(baidu_server_ak=""))

    tid = create_living_circle_task({
        "scene_name": scene_name, "city": "", "address": "",
        "center": None, "study_radius_m": 2500.0, "mode": "standard", "data_mode": "live",
    })

    async def run():
        rid = ""
        async for ev in living_circle_pipeline(tid):
            if ev["type"] == "done":
                rid = ev["data"]["report_id"]
        return rid

    return asyncio.run(run())


def test_offline_report_center_resolves_via_region_index(monkeypatch):
    """I2 · 无 AK「上海市浦东新区陆家嘴」→ 区划定位命中浦东（非凯里兜底）。"""
    rid = _make_offline_record("上海市浦东新区陆家嘴", monkeypatch)
    rep = client.get(f"/api/life-circle/{rid}").json()
    lc = rep["living_circle"]
    assert lc["data_origin"] == "offline"
    assert lc["scene"]["center"][0] > 121.0  # 浦东（非凯里 107.9）
    assert lc["blindspots"] == []
    assert lc["scores"]["note"]


def test_offline_history_has_null_score(monkeypatch):
    """I6 · 历史列表：offline 行 total_score=None + data_origin=offline。"""
    rid = _make_offline_record("贵州省遵义市红花岗区", monkeypatch)
    rows = client.get("/api/life-circle").json()
    row = next((r for r in rows if r["id"] == rid), None)
    assert row is not None
    assert row["total_score"] is None
    assert row["data_origin"] == "offline"


def test_offline_compare_marks_not_comparable(monkeypatch):
    """I5 · live + offline 对比：offline 侧标注「离线估算」，不出现 0 分。"""
    rid_a = _make_record("凯里老街", [107.9758, 26.5734], "贵州·凯里")
    rid_b = _make_offline_record("上海市浦东新区陆家嘴", monkeypatch)
    resp = client.get(f"/api/life-circle/compare?ids={rid_a},{rid_b}")
    assert resp.status_code == 200
    metric = {r["metric"]: r for r in resp.json()["diff"]}
    assert metric["综合评分"]["b_value"] == "离线估算"
    assert metric["综合评分"]["desc"] == "不可比 · 离线估算"
    assert metric["服务盲区"]["b_value"] == "离线估算"
    assert metric["POI 采集"]["desc"] == "离线估算未采集 POI"
    assert metric["综合评分"]["a_value"] == KAILI_FX["scores"]["total"]  # 凯里实时分不受影响


# ── T6 · 入口校验与时间戳格式契约（I12/I13）──────────────────────────

MS_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
SEC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _clarifications(resp):
    return db.get_task_full(resp.json()["taskId"])["clarifications"]


def _post_living_circle(**body):
    payload = {"query": "凯里老街", "type": "living_circle"}
    payload.update(body)
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 200
    return resp


@pytest.mark.parametrize("mode", ["quick", "standard", "precise"])
def test_t6_sampling_mode_whitelist_passes_through(mode):
    assert _clarifications(_post_living_circle(mode=mode))["sample_profile"] == mode


def test_t6_illegal_mode_silently_falls_back_currently():
    """**记录当前行为 + TODO**（评审 P0 之一 / I12）：非法 mode 不报错，静默按 standard 跑。

    `main.py:316` 的白名单兜底让「打错的档位」变成一次成功但口径不同的体检：
    用户请求 quick 拼成 quik，拿到的是 standard 的结果与耗时，全程无提示。
    TODO（B1）：改显式校验并返回 422；届时本用例翻红，改成断言 422。
    """
    assert _clarifications(_post_living_circle(mode="quik"))["sample_profile"] == "standard"
    assert _clarifications(_post_living_circle(mode=""))["sample_profile"] == "standard"
    assert _clarifications(_post_living_circle(mode="DRIVING"))["sample_profile"] == "standard"


def test_t6_research_mode_values_are_not_valid_for_living_circle():
    """**记录当前行为**：research 的 mode 取值（deep/expert）在生活圈入口同样静默回落。

    同名参数两套取值域（quick|deep|expert 与 quick|standard|precise）共用一个字段名，
    是 R5「一名四义」的入口侧实例。
    """
    for m in ("deep", "expert", "auto"):
        assert _clarifications(_post_living_circle(mode=m))["sample_profile"] == "standard"


def test_t6_study_radius_is_not_a_client_parameter():
    """**记录当前行为 + TODO**（B1）：客户端传 study_radius_m 一律被丢弃，恒为 2500。

    「按出行方式分档半径」的前置阻断项就在这行硬编码上——不报错、不可配。
    TODO（B1）：入口按 travel_mode 取 `caliber.study_radius_m` 并校验。
    """
    cl = _clarifications(_post_living_circle(study_radius_m=9000))
    assert cl["study_radius_m"] == 2500.0


def test_t6_sampling_mode_leaks_into_user_visible_text():
    """**记录当前行为 + TODO**（R5/B5）：采样档位以「模式 X」混入用户文案。

    文案里的「模式 standard」会被读成出行方式（步行/骑行），而它其实是网格采样档位。
    TODO（R5）：改名 `sampling_profile`，文案改「采样精度：标准」。
    """
    tid = create_living_circle_task({
        "scene_name": "凯里老街", "city": "贵州·凯里", "address": "", "center": [107.9758, 26.5734],
        "study_radius_m": 2500.0, "mode": "quick", "data_mode": "fixture",
    })
    texts = asyncio.run(_collect_messages(tid))
    assert any("模式 quick" in t for t in texts), texts


async def _collect_messages(task_id: str):
    out = []
    async for ev in living_circle_pipeline(task_id):
        if ev["type"] == "message":
            out.append(ev["data"]["text"])
    return out


def test_t6_illegal_data_mode_does_not_route_to_fixture():
    """**记录当前行为 + TODO**（I13）：未知 data_mode 不报错，落到 live/offline 分支。

    工厂只认 `fixture`，其它值（含拼错的 `liv`、`Offlin e`）都按「有 AK 走实时」处理，
    即一次打字错误就会真实消耗百度配额。
    TODO：`get_data_source` 显式白名单（fixture|live|offline|''），未知值抛 ValueError。
    """
    from app.living_circle.data_source import CachingDataSource, LiveDataSource, OfflineDataSource, get_data_source

    assert get_data_source("bogus", ak="").source.__class__ is OfflineDataSource  # 无 AK：离线估算
    src = get_data_source("bogus", ak="fake-ak")
    assert isinstance(src, CachingDataSource) and src.source.__class__ is LiveDataSource  # 有 AK：真调百度
    assert get_data_source("fixture", ak="fake-ak").__class__.__name__ == "FixtureDataSource"


def test_t6_timestamp_formats():
    """generated_at 毫秒 Z / cached_at 秒 Z：两套精度（前端 new Date 可解析，但不可字符串比较）。"""
    import asyncio as _aio
    import datetime as _dt

    from app.living_circle.data_source import CachingDataSource, OfflineDataSource
    from app.living_circle.data_source import CheckParams as CP

    r = _aio.run(OfflineDataSource().compute(CP(scene_name="凯里老街", center=(107.9758, 26.5734))))
    assert MS_Z.match(r["generated_at"]), r["generated_at"]
    _dt.datetime.strptime(r["generated_at"], "%Y-%m-%dT%H:%M:%S.%fZ")

    class Static:
        async def compute(self, params):
            return {"scene": {"name": params.scene_name}, "data_origin": "live"}

    ds = CachingDataSource(Static(), data_mode="live")
    p = CP(scene_name="时戳", center=(107.9758, 26.5734))
    _aio.run(ds.compute(p))
    hit = _aio.run(ds.compute(p))
    assert hit["served_from"] == "cache"
    assert SEC_Z.match(hit["cached_at"]), hit["cached_at"]
    _dt.datetime.strptime(hit["cached_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert MS_Z.match(hit["cached_at"]) is None  # 精度不同源（记录）
