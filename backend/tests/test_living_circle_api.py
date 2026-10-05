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
from conftest import live_payload

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
    # ⭐ 本用例只管「接口把两份真实快照原样搬进差异表」。**方向**与**口径不可比**两条
    #    判据原本挂在这对出厂快照的字面数值上（0 vs 1），重刷快照就会失去判别样本 ——
    #    已挪到下面两条自带样本的用例里：
    #    `test_compare_endpoint_blindspot_direction_negative_control`（方向）、
    #    `test_caliber_gap_blocks_only_the_verdict_rows`（口径不可比，④ 顺带覆盖真实代际）。


def _store_payload_record(suffix: str, payload: dict) -> str:
    """把一份现成 living_circle 载荷落成报告（不走流水线），返回 report_id。

    给「判据需要**特定数值**当载体」的用例用：数值由测试自己拼装，与出厂快照的代际解耦
    （快照重刷只会改快照，不会让这些用例悄悄失去判别力）。
    """
    rid = f"lc-syn-{suffix}"
    db.save_living_circle_report(
        {"id": rid, "title": payload["scene"]["name"], "living_circle": payload},
        scene_key=f"syn-{suffix}",
    )
    return rid


def test_compare_endpoint_blindspot_direction_negative_control():
    """盲区行方向负对照：0 vs 1 必须说「A盲区更少」，倒过来必须说「B盲区更少」。

    为什么是负对照：盲区越小越好，若误用「大者胜」（旧实现按字符串字典序比较时的形态）
    就会输出「B盲区更少」—— 事实相反。契约夹具里 `服务盲区 a=0 b=1` 那条用例的期望串
    直接拿来用，串本身由 `test_compare_diff_desc_table_matches_contract_fixture` 守。
    """
    import copy

    zero_case = next(c for c in CONTRACT["desc_cases"]
                     if c["row"] == "服务盲区" and (c["a"], c["b"]) == (0, 1))
    flip_case = next(c for c in CONTRACT["desc_cases"]
                     if c["row"] == "服务盲区" and (c["a"], c["b"]) == (1, 0))
    # 两份载荷同源（都取自劲松快照 ⇒ `scope_policy_version` 一致，不会撞口径不可比分支），
    # 唯一的差别就是盲区条数：这才是方向判据要的**受控**变量。
    with_one = copy.deepcopy(JINSONG_FX)
    with_one["blindspots"] = list(with_one["blindspots"]) + [{
        "id": "bs-方向载体-1", "center": JINSONG_FX["scene"]["center"], "radius_m": 1000,
        "missing_facilities": ["菜市场"],
        "nearest": [{"facility": "market", "name": "载体", "distance_m": 1450.0, "direction": "正东"}],
        "polygon": {"type": "Polygon", "coordinates": [[
            [116.4570, 39.8790], [116.4680, 39.8790], [116.4680, 39.8870],
            [116.4570, 39.8870], [116.4570, 39.8790],
        ]]},
    }]
    with_zero = copy.deepcopy(JINSONG_FX)
    with_zero["blindspots"] = []
    rid_zero = _store_payload_record("dir-zero", with_zero)
    rid_one = _store_payload_record("dir-one", with_one)

    rows = {r["metric"]: r for r in
            client.get(f"/api/life-circle/compare?ids={rid_zero},{rid_one}").json()["diff"]}
    assert (rows["服务盲区"]["a_value"], rows["服务盲区"]["b_value"]) == (0, 1)
    assert rows["服务盲区"]["desc"] == zero_case["desc"]

    rows = {r["metric"]: r for r in
            client.get(f"/api/life-circle/compare?ids={rid_one},{rid_zero}").json()["diff"]}
    assert (rows["服务盲区"]["a_value"], rows["服务盲区"]["b_value"]) == (1, 0)
    assert rows["服务盲区"]["desc"] == flip_case["desc"]


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


def test_caliber_gap_blocks_only_the_verdict_rows():
    """P0-3 · 判盲口径版本不同 ⇒ 只拦「服务盲区 / 综合评分」两行的**结论**，不动数值。

    为什么只拦结论不拦数值：88.4 与 80.4 都是各自口径下真实算出来的分数（事实没被改），
    坏的是「A 比 B 高 8 分 ⇒ A 社区更好」这条推理 —— 旧口径只判了可达区一角的格
    （凯里实测 5/97），盲区天然少报、分数天然偏高。
    """
    import copy

    from app.main import _DIFF_DESC_CALIBER_GAP, _lc_diff
    from app.living_circle.scope import SCOPE_POLICY_VERSION

    gap_rows = CONTRACT["caliber_incomparable"]["applies_to"]

    def by_metric(rows):
        return {r["metric"]: r for r in rows}

    # ① 两侧版本相同 ⇒ 同一把尺，不得谎报不可比。版本一律由测试自己拼装（不读出厂
    #    快照的现值）：出厂快照目前是「凯里旧口径 / 劲松 ev-1」的混代际，若直接拿它们
    #    当"同版本"样本，这一档就会在测②那件事 —— 两档必须各测各的。
    a, b = copy.deepcopy(KAILI_FX), copy.deepcopy(JINSONG_FX)
    for fx in (a, b):
        fx["caliber"].pop("scope_policy_version", None)   # 都当成升级前的旧快照
    rows = by_metric(_lc_diff(a, b))
    assert rows["综合评分"]["desc"] != _DIFF_DESC_CALIBER_GAP, (
        "两侧同版本（均未声明）应视为可比 —— 否则存量报告两两对比全部失明")
    a["caliber"]["scope_policy_version"] = SCOPE_POLICY_VERSION
    b["caliber"]["scope_policy_version"] = SCOPE_POLICY_VERSION   # 双双升到当前版本
    rows = by_metric(_lc_diff(a, b))
    assert rows["综合评分"]["desc"] != _DIFF_DESC_CALIBER_GAP, (
        "两侧都声明了同一版本 ⇒ 可比；若这里红成『不可比』，说明守卫把『声明过版本』"
        "当成了『版本不同』（存量报告两两对比会全部失明，只是换了个触发路径）")

    # ② 版本错配 ⇒ 两行结论被拦，其余四行照常判胜负。两种错配形态都要过：
    #    『一侧升到当前版本、另一侧仍是旧口径』与『一侧根本没声明』（存量 26 次体检的真实形态）
    for legacy_b in ("ev-0-legacy", None):
        a, b = copy.deepcopy(KAILI_FX), copy.deepcopy(JINSONG_FX)
        a["caliber"]["scope_policy_version"] = SCOPE_POLICY_VERSION
        if legacy_b is None:
            b["caliber"].pop("scope_policy_version", None)
        else:
            b["caliber"]["scope_policy_version"] = legacy_b
        rows = by_metric(_lc_diff(a, b))
        for metric in gap_rows:
            assert rows[metric]["desc"] == _DIFF_DESC_CALIBER_GAP, f"{legacy_b}/{metric}"
            assert isinstance(rows[metric]["a_value"], (int, float)), (
                f"{metric} 的数值必须**原样给出**（事实没被改），拦的只是结论句")
        for metric in ("15min 等时圈面积 (km²)", "可达采样点数", "POI 采集", "圈内 POI"):
            assert rows[metric]["desc"] != _DIFF_DESC_CALIBER_GAP, f"{legacy_b}/{metric}"

    # ③ 离线优先：连 POI 都没采，谈不上口径版本 ⇒ 仍走「不可比 · 离线估算」
    #    （两行既有口径错配又离线时，离线文案赢 —— 那是更根本的不可比）
    a, b = copy.deepcopy(KAILI_FX), copy.deepcopy(JINSONG_FX)
    b["caliber"].pop("scope_policy_version", None)
    a["data_origin"] = "offline"
    rows = by_metric(_lc_diff(a, b))
    for metric in gap_rows:
        assert rows[metric]["desc"] == CONTRACT["offline_backend_only"]["not_comparable_desc"], metric

    # ④ 真数据自检（不合成）：出厂两份快照现在的版本关系决定守卫该不该亮
    shipped = by_metric(_lc_diff(copy.deepcopy(KAILI_FX), copy.deepcopy(JINSONG_FX)))
    mismatched = (KAILI_FX["caliber"].get("scope_policy_version")
                  != JINSONG_FX["caliber"].get("scope_policy_version"))
    for metric in gap_rows:
        if mismatched:
            assert shipped[metric]["desc"] == _DIFF_DESC_CALIBER_GAP, (
                f"两份出厂快照版本不同（kaili="
                f"{KAILI_FX['caliber'].get('scope_policy_version')} / jinsong="
                f"{JINSONG_FX['caliber'].get('scope_policy_version')}）却在真实报告对上"
                "没拦住结论 ⇒ 守卫只在合成输入上生效，真链路是空的")
        else:
            assert shipped[metric]["desc"] != _DIFF_DESC_CALIBER_GAP, (
                "两份出厂快照已同代际，守卫必须随之收起 —— 否则演示态永远显示不可比")


def test_caliber_gap_literals_match_contract_fixture():
    """P0-3 的字面量单一真源是契约夹具：后端常量 + 判盲口径版本必须与它逐字相同。

    `policy_version_current` 与前端 `SCOPE_POLICY_VERSION` 各自钉向同一份夹具 ⇒ 换版本
    只改 `scope.SCOPE_POLICY_VERSION` + 夹具，两侧测试同时报警（不会一边新一边旧）。
    """
    from app.main import (
        _DIFF_DESC_BOTH_GAP,
        _DIFF_DESC_CALIBER_GAP,
        _DIFF_DESC_COVERAGE_GAP,
        _CALIBER_GAP_ROWS,
        _COVERAGE_GAP_ROWS,
    )
    from app.living_circle.category_rule import COVERAGE_CALIBER_VERSION
    from app.living_circle.scope import SCOPE_POLICY_VERSION

    gap = CONTRACT["caliber_incomparable"]
    assert _DIFF_DESC_CALIBER_GAP == gap["desc"]
    assert list(_CALIBER_GAP_ROWS) == gap["applies_to"]
    # #83：`applies_to` 是「受**某根**轴影响的行并集」，评分轴单独一行钉 ⇒ 并集与子集都由夹具
    # 说话，代码里那两张表（`_GAP_AXES` 派生）不许再各抄一份行名。
    assert list(_COVERAGE_GAP_ROWS) == gap["coverage_applies_to"], (
        "评分轴的行级作用面与契约分叉 ⇒ 「只评分轴不同」那一档会重新拦掉它影响不到的行")
    assert "服务盲区" not in _COVERAGE_GAP_ROWS, (
        "盲区数只由判盲那把尺决定，评分轴拦不到它（这条就是 #83 本身）")
    assert set(_COVERAGE_GAP_ROWS) <= set(_CALIBER_GAP_ROWS), (
        "评分轴作用的行必须是「受口径影响行」的子集，否则并集键在说谎")
    assert SCOPE_POLICY_VERSION == gap["policy_version_current"], (
        "判盲口径版本换了却没改契约夹具 ⇒ 前端的「建议重新体检」提示会静默失灵")
    # 第二根轴（片 1c-β C3）：三句 + 版本各钉一次
    assert _DIFF_DESC_COVERAGE_GAP == gap["coverage_desc"]
    assert _DIFF_DESC_BOTH_GAP == gap["both_desc"]
    assert COVERAGE_CALIBER_VERSION == gap["coverage_version_current"], (
        "评分口径版本换了却没改契约夹具 ⇒ 前端那句「这份是点数口径算的分」会静默失灵")
    # 三句必须互不相同：写成同一句 = 只有一根轴在守（两把键互相顶替的机器形态）
    assert len({gap["desc"], gap["coverage_desc"], gap["both_desc"]}) == 3
    assert "判盲" not in gap["coverage_desc"]
    assert "评分口径" not in gap["desc"]


def test_caliber_axes_are_registered_everywhere_they_must_be():
    """措辞改成按轴子句组合后，加一根轴要同时登记三处 —— 漏一处就是静默漏报，这里全钉住。

    原来"不可比"那句是按**轴子集**枚举的（2 轴 3 句），加第三根轴得写 7 句 × 两端。改成组合式
    之后子集常量消失了，于是冒出一个**新的**失败模式：有人在 `_GAP_CLAUSES` 加了一行措辞，
    却忘了给 `reuse_policy` 加那道门 —— 措辞会报"口径已升级"，旧报告却照样被当成本次答案复用。
    那比原来的漏报更难发现，因为屏幕上看起来是对的。

    三处 = ① 契约夹具 `axes`/`axis_fields`；② 后端 `_GAP_CLAUSES`；③ 复用门 `checks`。
    （第 ④ 处在前端 `CALIBER_AXES`，由 `compareDiffContract.test.ts` 钉同一份夹具。）
    """
    import inspect

    from app.living_circle import report_contract
    from app.main import _GAP_CLAUSES, _gap_desc

    gap = CONTRACT["caliber_incomparable"]
    axes = [axis for axis, _clause in _GAP_CLAUSES]

    # ① 轴清单：顺序与内容都必须与夹具一致（顺序也钉，因为组合句的词序是用户可见的）
    assert gap["axes"] == axes, f"措辞表的轴清单与契约分叉：{axes} vs {gap['axes']}"
    assert set(gap["axis_fields"]) == set(axes), "`axis_fields` 与轴清单不是一批轴"

    # ② 组合式本身：单轴子句必须原样出现在单轴结论句里，多轴句必须含全部子句
    for axis, clause in _GAP_CLAUSES:
        single = _gap_desc((axis,))
        assert single == f"不可比 · {clause}", f"{axis} 轴的子句没被原样拼进结论句：{single}"
    both = _gap_desc(tuple(axes))
    for _axis, clause in _GAP_CLAUSES:
        assert clause in both, f"多轴结论句丢了 {clause}"
    assert _gap_desc(()) is None, "零根轴不同必须返回 None（可比），不许拼出一句空话"

    # ③ 复用门：每根轴的版本字段都必须真的被 `reuse_policy` 读 —— 只加措辞不加门即红
    gate_src = inspect.getsource(report_contract.reuse_policy)
    for axis in axes:
        field = gap["axis_fields"][axis]
        assert field in gate_src, (
            f"{axis} 轴有措辞（`_GAP_CLAUSES`）但 `reuse_policy` 不读 `{field}` ⇒ "
            "旧报告会继续被当成本次体检的答案复用，而屏幕上已经写了「口径已升级」")

    # ④ 枚举式不得复活：那三行 `if ev and cov: return _DIFF_DESC_BOTH_GAP` 的形态
    row_src = inspect.getsource(report_contract.reuse_policy) + "\n"
    from app.main import _row_gap_desc
    row_src += inspect.getsource(_row_gap_desc)
    assert "_DIFF_DESC_BOTH_GAP" not in row_src, (
        "结论句又回到按子集枚举了 —— 组合式的意义就是加轴不增加子集常量")


def test_coverage_gap_blocks_only_the_verdict_rows():
    """第二根轴：只有 `coverage_caliber_version` 不同 ⇒ 只拦**评分轴管得着的那些行**的结论。

    第 21 轮 P1-3 抓到的洞：判盲轴相同、评分轴一边缺键 ⇒ 旧实现判**可比**，而凯里那 3 分
    落差全部来自分子换代（圈内点数 → 门槛项数）。两根轴独立 ⇒ 三句结论句各说各的事。

    ⚠️ #83 补的半边：上面那句"各说各的"当时只落在**横幅**上，行级仍是一把共用句喂两行 ⇒
    「服务盲区」被评分轴拦下，而分子换代影响不到盲区数（10-03 真库三档配对实测现形）。
    本用例因此改成**逐行**断言，并用"抹平评分轴后的同一对样本"当参照 —— 盲区行的结论
    必须一字不变（不是"不等于某句"那种会被任意别的句子白送的断言）。
    """
    import copy

    from app.main import (
        _DIFF_DESC_BOTH_GAP,
        _DIFF_DESC_CALIBER_GAP,
        _DIFF_DESC_COVERAGE_GAP,
        _lc_diff,
    )
    from app.living_circle.category_rule import COVERAGE_CALIBER_VERSION
    from app.living_circle.scope import SCOPE_POLICY_VERSION

    gap_rows = CONTRACT["caliber_incomparable"]["applies_to"]
    cov_rows = CONTRACT["caliber_incomparable"]["coverage_applies_to"]
    plain_rows = ("15min 等时圈面积 (km²)", "可达采样点数", "POI 采集", "圈内 POI")
    ALL_GAP_SENTENCES = (_DIFF_DESC_CALIBER_GAP, _DIFF_DESC_COVERAGE_GAP, _DIFF_DESC_BOTH_GAP)

    def stamp(fx: dict, ev, cov) -> dict:
        f = copy.deepcopy(fx)
        cal = f.setdefault("caliber", {})
        for key, val in (("scope_policy_version", ev), ("coverage_caliber_version", cov)):
            if val is None:
                cal.pop(key, None)
            else:
                cal[key] = val
        return f

    def by_metric(rows):
        return {r["metric"]: r for r in rows}

    # ① 判盲轴两边相同、评分轴不同（两种形态：另一侧根本没声明 / 另一侧是别的号）
    for legacy_cov in (None, "cov-0"):
        a = stamp(KAILI_FX, SCOPE_POLICY_VERSION, COVERAGE_CALIBER_VERSION)
        b = stamp(JINSONG_FX, SCOPE_POLICY_VERSION, legacy_cov)
        rows = by_metric(_lc_diff(a, b))
        # 参照：同一对样本、把评分轴抹平（两边都不声明）⇒ 除评分行外每行结论都必须相同
        ref = by_metric(_lc_diff(stamp(KAILI_FX, SCOPE_POLICY_VERSION, None),
                                 stamp(JINSONG_FX, SCOPE_POLICY_VERSION, None)))
        for metric in cov_rows:
            assert rows[metric]["desc"] == _DIFF_DESC_COVERAGE_GAP, f"{legacy_cov}/{metric}"
            assert isinstance(rows[metric]["a_value"], (int, float)), (
                f"{metric} 数值必须原样给出（拦结论不拦事实）")
        for metric in gap_rows:
            if metric in cov_rows:
                continue
            assert ref[metric]["desc"] not in ALL_GAP_SENTENCES, (
                f"参照本身就被拦了 ⇒ 下面那条相等断言会恒真（{metric}）")
            assert rows[metric]["desc"] == ref[metric]["desc"], (
                f"{legacy_cov}/{metric}：评分轴不同，却改写了判盲轴才管得着的行（#83）")
        for metric in plain_rows:
            assert rows[metric]["desc"] != _DIFF_DESC_COVERAGE_GAP, metric

    # ② 两份都缺 cov 键 ⇒ 彼此可比，不得谎报不可比（否则存量报告两两对比全部失明）
    a = stamp(KAILI_FX, SCOPE_POLICY_VERSION, None)
    b = stamp(JINSONG_FX, SCOPE_POLICY_VERSION, None)
    rows = by_metric(_lc_diff(a, b))
    for metric in gap_rows:
        assert rows[metric]["desc"] not in (_DIFF_DESC_COVERAGE_GAP, _DIFF_DESC_BOTH_GAP), metric

    # ③ 两根轴同时不同 ⇒ **两句不同**：评分行拿第三句，盲区行仍只拿判盲句
    a = stamp(KAILI_FX, SCOPE_POLICY_VERSION, COVERAGE_CALIBER_VERSION)
    b = stamp(JINSONG_FX, "ev-0-legacy", None)
    rows = by_metric(_lc_diff(a, b))
    for metric in cov_rows:
        assert rows[metric]["desc"] == _DIFF_DESC_BOTH_GAP, metric
    for metric in gap_rows:
        if metric in cov_rows:
            continue
        assert rows[metric]["desc"] == _DIFF_DESC_CALIBER_GAP, (
            f"{metric} 在两轴都不同那档拿了第三句 ⇒ 把评分账记到了判盲头上")
    assert rows["服务盲区"]["desc"] != rows["综合评分"]["desc"], (
        "两行又共用一句 ⇒ 行级按轴分派没生效（#83 的机器形态）")

    # ④ 真数据自检（不合成）：出厂两份快照的评分轴关系决定第二句该不该亮
    shipped = by_metric(_lc_diff(copy.deepcopy(KAILI_FX), copy.deepcopy(JINSONG_FX)))
    same_cov = (KAILI_FX["caliber"].get("coverage_caliber_version")
                == JINSONG_FX["caliber"].get("coverage_caliber_version"))
    for metric in gap_rows:
        if same_cov:
            assert shipped[metric]["desc"] != _DIFF_DESC_COVERAGE_GAP, (
                f"两份出厂快照评分轴相同（都是 "
                f"{KAILI_FX['caliber'].get('coverage_caliber_version')}）却亮了评分句 ⇒ "
                "守卫把「声明过」当成了「版本不同」")
        elif metric in cov_rows:
            assert shipped[metric]["desc"] in (_DIFF_DESC_COVERAGE_GAP, _DIFF_DESC_BOTH_GAP), (
                f"两份出厂快照评分轴不同（{KAILI_FX['caliber'].get('coverage_caliber_version')}"
                f" vs {JINSONG_FX['caliber'].get('coverage_caliber_version')}）却没拦结论")


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
    """**契约变更（片 0b）**：客户端带 `study_radius_m` 现在在入口就被 422 拒。

    历史：`extra="ignore"` 时代这个键是"被静默丢弃、恒为 2500" —— 本条当时是在替缺陷
    背书（不报错、不可配）。forbid 之后"客户端改不动口径"这条不变量更强：连请求都进不来。

    正向半仍保留（不带该键时口径由服务端定），因为**拒收客户端键 ≠ 半径已按出行方式分档**。
    TODO（B1）不变：入口应按 `travel_mode` 取 `caliber.study_radius_m` 并校验。
    """
    rejected = client.post("/api/tasks", json={
        "query": "凯里老街", "type": "living_circle", "study_radius_m": 9000,
    })
    assert rejected.status_code == 422, rejected.text
    assert any(
        e.get("type") == "extra_forbidden" and "study_radius_m" in (e.get("loc") or ())
        for e in rejected.json()["detail"]
    ), f"422 不是因为该键未声明：{rejected.json()['detail']}"

    assert _clarifications(_post_living_circle())["study_radius_m"] == 2500.0


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
        """live 载荷必须带**当前判盲口径版本**，否则 `reuse_policy` 视为旧口径不予复用
        （盖版本的唯一实现 = `conftest.live_payload`，负对照见 `test_caching_datasource`
        末尾 `test_stale_policy_*`）—— 本用例测的是两套时戳精度。"""

        async def compute(self, params):
            return live_payload({
                "scene": {"name": params.scene_name},
                "data_origin": "live",
            })

    ds = CachingDataSource(Static(), data_mode="live")
    p = CP(scene_name="时戳", center=(107.9758, 26.5734))
    _aio.run(ds.compute(p))
    hit = _aio.run(ds.compute(p))
    assert hit["served_from"] == "cache"
    assert SEC_Z.match(hit["cached_at"]), hit["cached_at"]
    _dt.datetime.strptime(hit["cached_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert MS_Z.match(hit["cached_at"]) is None  # 精度不同源（记录）


# ── T7 · 删除端点（报告中心唯一归档 + 记录删除，波次 A 第 1 步）──────────
# 为什么要专门一组：`DELETE /api/life-circle/{report_id}` 的语义不是"返 200"，
# 而是三件事同时成立 —— 报告行没了、派生行也没了、别的域不许被牵连。
# 调研报告侧早有同名能力（main.py:551），生活圈侧此前只有读端点，归档面因此
# 无法在报告中心完成「删掉一条体检记录」这件用户可观察的事。


def _seed_lc_row(rid: str, scene: str = "劲松") -> None:
    db.save_living_circle_report(
        {"id": rid, "created_at": "2026-09-27T00:00:00Z",
         "living_circle": {"scene": {"name": scene}, "scores": {"total": 72},
                           "blindspots": [], "data_origin": "live"}},
        scene_key=f"t7-{rid}")


def test_t7_delete_removes_report_and_feedback_rows():
    """删除一份体检报告 ⇒ 列表读不到它，且不分报告类型写来的反馈行也一并清掉。"""
    _seed_lc_row("t7-1")
    db.save_report_feedback("t7-1", 2, 5, {"edits": {}})
    resp = client.delete("/api/life-circle/t7-1")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "deleted": True}
    c = db._connect()
    assert c.execute("SELECT COUNT(*) n FROM living_circle_reports WHERE report_id='t7-1'").fetchone()["n"] == 0
    assert c.execute("SELECT COUNT(*) n FROM report_feedback WHERE report_id='t7-1'").fetchone()["n"] == 0


def test_t7_delete_of_absent_report_reports_deleted_false():
    """库里本就没有 ⇒ `deleted:false`（而不是 200 空成功，也不必走 404 异常分支）。

    钉的是可观察区分：UI 靠这个字段把「我删掉了」和「这条已经不在」分开显示。
    与所摘归档层 `RecordRow` 的消费契约同源，形状一旦分叉本用例即刻红。
    """
    resp = client.delete("/api/life-circle/t7-nope")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "deleted": False}


def test_t7_delete_does_not_touch_research_domain():
    """跨域隔离：生活圈删除端点不得动调研报告（两张主表、一个 id 空间）。"""
    _seed_lc_row("t7-shared-id")
    db.save_report({"id": "t7-shared-id", "title": "调研报告", "query": "q",
                    "destinations": ["目的地A"], "experts": [], "cover_image": "",
                    "created_at": "2026-09-27T00:00:00Z",
                    "evidence": [], "claims": [], "metrics": {}}, task_id="")
    assert client.delete("/api/life-circle/t7-shared-id").status_code == 200
    c = db._connect()
    assert c.execute("SELECT COUNT(*) n FROM reports WHERE report_id='t7-shared-id'").fetchone()["n"] == 1
