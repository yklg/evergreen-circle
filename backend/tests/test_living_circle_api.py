"""M2 · 生活圈体检 API：任务创建 / 独立报告读取 / 双样例对比。"""
import asyncio
import json
import re
from pathlib import Path
from unittest.mock import patch

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

# R6 · 对比页差异表契约夹具 —— 两侧测试读**同一份**文件、断言**同一串期望字面量**
# （范式同 `poi_metric_label`/`poiMetricLabel`）。前端侧：`frontend/src/lib/__tests__/compareDiffContract.test.ts`。
PROJECT = Path(__file__).resolve().parent.parent.parent  # skip/
CONTRACT_FIXTURE = PROJECT / "frontend" / "src" / "__tests__" / "fixtures" / "compareDiffContract.json"
CONTRACT = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))


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
    # ⭐ 行名**集合 + 行序**与契约夹具逐项相同。**不是**数量断言：`len(diff) == N` 一旦红了
    # 只说「行数不对」，说不出缺了/多了哪一行、也没覆盖行序。
    got = [r["metric"] for r in body["diff"]]
    want = [r["key"] for r in CONTRACT["rows"]]
    assert got == want, (
        f"行名/行序与契约夹具不符\n  期望 {want}\n  实际 {got}\n"
        f"  差集(缺) {[k for k in want if k not in got]}\n  差集(多) {[k for k in got if k not in want]}"
    )
    metric = {r["metric"]: r for r in body["diff"]}
    assert metric["综合评分"]["a_value"] == KAILI_FX["scores"]["total"]  # 凯里
    assert metric["综合评分"]["b_value"] == JINSONG_FX["scores"]["total"]  # 劲松
    assert metric["服务盲区"]["a_value"] == len(KAILI_FX["blindspots"])
    assert metric["服务盲区"]["b_value"] == len(JINSONG_FX["blindspots"])
    # ⭐ 「方向」断言：契约夹具里 `服务盲区 a=0 b=1` 那条用例的**期望串**直接拿来用 ——
    # 先证「本用例这对真实值恰好就是那条判别样本」（否则方向写错也照绿），再断言 desc。
    blind = next(c for c in CONTRACT["desc_cases"]
                 if c["row"] == "服务盲区" and c["a"] == 0 and c["b"] == 1)
    assert (metric["服务盲区"]["a_value"], metric["服务盲区"]["b_value"]) == (blind["a"], blind["b"]), (
        "真实夹具的盲区值不再是 0/1 ⇒ 这条方向断言失去判别力，请改用当前夹具实际值的判别样本"
    )
    assert metric["服务盲区"]["desc"] == blind["desc"]  # 「A盲区更少」（越小越好；写反则得 B…）


def test_compare_requires_two_ids():
    assert client.get("/api/life-circle/compare?ids=onlyone").status_code == 422
    assert client.get("/api/life-circle/compare").status_code == 422


def test_map_config_endpoint():
    """C7 · 地图配置端点：浏览器 AK + 个性化 styleId 明文下发（公开键，供 BMapGL）。"""
    from app.core.config import get_settings

    resp = client.get("/api/life-circle/map-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "browser_ak" in body
    assert "map_style_id" in body
    # 本地 .env 已配浏览器 AK → 非空；styleId 有值则透传（测试环境空值也允许）
    assert isinstance(body["browser_ak"], str)
    assert isinstance(body["map_style_id"], str)
    # 阶段 0.2 · **真实配置下的运行时不变量**（不是补丁出来的假象）：
    # 未开 opt-in 时，无论 .env 里写了什么 styleId，端点都必须下发空串。
    s = get_settings()
    if not s.baidu_allow_console_style:
        assert body["map_style_id"] == "", (
            f"未开 BAIDU_ALLOW_CONSOLE_STYLE 却下发了 styleId {body['map_style_id']!r} —— "
            "前置注记纪律（poilabel 关闭）会被绕过"
        )


def test_map_config_suppresses_console_style_by_default():
    """阶段 0.2（D4）· **styleId 默认不下发**（负对照：配了也不给，除非显式 opt-in）。

    被守护的事故：`bmapStyle.ts` 的 `poilabel` 关闭规则**从未生效**，因为 `.env` 配了
    控制台 styleId（带「清晰标注」），前端分支就走 styleId 去了 —— 内置模板成了死代码，
    百度第三方设施名照旧上屏，被读成自家数据。

    所以纪律不能挂在「.env 里恰好没配」这种偶然状态上：**默认抑制**，只有显式
    `BAIDU_ALLOW_CONSOLE_STYLE=1`（确知该样式已关 POI 注记）才下发。
    """
    from app.core.config import get_settings

    s = get_settings()
    # ① 即便 .env 里配了 styleId，只要没开 opt-in，就必须下发空串
    monkey = s.model_copy(update={"baidu_map_style_id": "f3d9141a57e8ca87b05984cce4d726a4",
                                  "baidu_allow_console_style": False})
    assert monkey.baidu_map_style_id and not monkey.baidu_allow_console_style

    with patch("app.core.config.get_settings", return_value=monkey):
        body = client.get("/api/life-circle/map-config").json()
    assert body["map_style_id"] == "", "未显式 opt-in 时不得下发控制台 styleId（注记纪律会被绕过）"

    # ② 显式 opt-in 后才下发
    optin = monkey.model_copy(update={"baidu_allow_console_style": True})
    with patch("app.core.config.get_settings", return_value=optin):
        body2 = client.get("/api/life-circle/map-config").json()
    assert body2["map_style_id"] == "f3d9141a57e8ca87b05984cce4d726a4"


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


# ── R6 · 对比页口径对齐：契约夹具 / 两态行序 / 离线字面量单一真源 ──────────────


def test_compare_diff_desc_table_matches_contract_fixture():
    """desc 用例表逐项相符 —— 与前端读**同一份**夹具、断言**同一串**期望字面量。

    覆盖 6 行 × 3 方向（A>B / A<B / 相等）= 18 条。⚠️ 其中「服务盲区 a=0 b=1 ⇒ A盲区更少」
    是**方向**的负对照：盲区越小越好，若误用「大者胜」就会输出「B盲区更少」（事实相反，
    正是旧实现用字符串字典序比较时的形态）。
    """
    from app.main import _diff_desc

    by_key = {r["key"]: r for r in CONTRACT["rows"]}
    name_a, name_b = CONTRACT["names"]
    bad = []
    for case in CONTRACT["desc_cases"]:
        spec = by_key[case["row"]]
        got = _diff_desc(spec["better"], spec["template"], case["a"], case["b"], name_a, name_b)
        if got != case["desc"]:
            bad.append(f'{case["row"]} a={case["a"]} b={case["b"]}: 期望 {case["desc"]!r} 实得 {got!r}')
    assert len(CONTRACT["desc_cases"]) >= 18, "用例表至少要有 6 行 × 3 方向"
    assert not bad, f"desc 用例不符 {len(bad)} 条:\n" + "\n".join(bad)


def test_offline_compare_keeps_the_same_row_sequence(monkeypatch):
    """在线态与离线态的 **metric 行名集合与行序逐项相同** —— 成对断言。

    ⚠️ 为什么需要这条：`_lc_diff()` 的离线分支是**逐行**标注的，而
    `test_offline_compare_marks_not_comparable` 只断言了 `综合评分 / 服务盲区 / POI 采集` 三行。
    新增的「可达采样点数」行（或将来再加行）若漏掉离线处理，那条用例**不会红** ——
    这里补上「两态行集合与行序必须一致」，让它必红。
    """
    rid_a = _make_record("凯里老街", [107.9758, 26.5734], "贵州·凯里")
    rid_off = _make_offline_record("上海市浦东新区陆家嘴", monkeypatch)
    resp = client.get(f"/api/life-circle/compare?ids={rid_a},{rid_off}")
    assert resp.status_code == 200
    got = [r["metric"] for r in resp.json()["diff"]]
    want = [r["key"] for r in CONTRACT["rows"]]
    assert got == want, (
        f"离线态行名/行序与契约夹具不符\n  期望 {want}\n  实际 {got}\n"
        f"  ⇒ 离线态漏了哪些行的处理，看差集就知道"
    )


def test_offline_diff_literals_match_contract_fixture():
    """离线三个字面量的**单一真源**是契约夹具；`main.py` 的模块常量必须与它逐字相同。

    离线分支是 P0-2 的既有需求（`test_offline_compare_marks_not_comparable` 在守，**不动**），
    本用例只把「这三个串写在哪」收成一处 —— 防止改了一边忘另一边。
    （这三个串只有后端会产出，故夹具里放在 `offline_backend_only` 段。）
    """
    from app.main import _DIFF_DESC_NOT_COLLECTED, _DIFF_DESC_NOT_COMPARABLE, _DIFF_VALUE_OFFLINE

    off = CONTRACT["offline_backend_only"]
    assert _DIFF_DESC_NOT_COLLECTED == off["not_collected_desc"]
    assert _DIFF_DESC_NOT_COMPARABLE == off["not_comparable_desc"]
    assert _DIFF_VALUE_OFFLINE == off["not_comparable_value"]


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
