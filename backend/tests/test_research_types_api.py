"""调研类型端到端透传与选择器数据源契约 —— B2（R4 契约键名成对断言 / R6 事件协议）。

守护的不变量：
- `GET /api/research-types` 逐字段等于注册表（前端卡片单一真相源，后端不得两份文案）；
- `POST /api/tasks` 的 `type` 落 task meta `_type`；未知类型一律回落 guide 且不报错；
- `submit_clarify` 保留 `_type`（与 `_mode` 同路径透传，防「澄清后类型丢失」）；
- 澄清 SSE 载荷键名 = `destinations_fallback`（旧键 competitors_fallback 不得回潮）。

种子：test_clarify_async.py::test_gc2_fallback_on_discover_error（澄清 SSE 兜底载荷）、
      test_subscriptions.py::test_api_create_list_delete_flow（端点契约直测）。
运行：backend/ 下 `pytest tests/test_research_types_api.py -q`
"""
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core.pipeline.research import engine as O
from app.core import research_types as rt
from app.main import app


@pytest.fixture(autouse=True)
def _clear_gen_lock():
    yield
    O._GEN_INFLIGHT.clear()


# ── ① 选择器数据源与注册表逐字段一致 ─────────────────────
def test_api_research_types_matches_registry():
    r = TestClient(app).get("/api/research-types")
    assert r.status_code == 200
    items = r.json()
    assert [i["key"] for i in items] == list(rt.RESEARCH_TYPES)
    for it in items:
        spec = rt.RESEARCH_TYPES[it["key"]]
        assert it["label"] == spec["label"]
        assert it["subtitle"] == spec["subtitle"]
    # 默认类型必须是列表首项（前端 `setRtype(cur => cur || items[0].key)` 依赖此序）
    assert items[0]["key"] == rt.DEFAULT_RESEARCH_TYPE


# ── ②③ 类型落库：未知回落、已知原样 ───────────────────────
def test_api_create_task_unknown_type_falls_back_to_guide():
    cli = TestClient(app)
    r = cli.post("/api/tasks", json={"query": "大理 5 天", "mode": "deep", "type": "不存在的类型"})
    assert r.status_code == 200, "未知类型不得报错（回落而非拒绝）"
    j = r.json()
    assert j["researchType"] == rt.DEFAULT_RESEARCH_TYPE
    assert (db.get_task(j["taskId"])["clarifications"] or {}).get("_type") == rt.DEFAULT_RESEARCH_TYPE


def test_api_create_task_assessment_type_roundtrip():
    cli = TestClient(app)
    j = cli.post("/api/tasks", json={"query": "评估成都和杭州", "mode": "expert",
                                     "type": "assessment"}).json()
    assert j["researchType"] == "assessment"
    assert db.get_task(j["taskId"])["clarifications"]["_type"] == "assessment"


def test_create_task_type_normalized_and_defaulted():
    """无 type 参数 → guide；带空串/None → guide（服务端归一，不留空值）。"""
    assert O.create_task("q")["researchType"] == "guide"
    assert O.create_task("q", research_type="")["researchType"] == "guide"
    assert O.create_task("q", research_type=" Assessment ")["researchType"] == "assessment"


# ── ④ 澄清提交保留类型（与 _mode 同路径）──────────────────
def test_submit_clarify_preserves_type_and_mode():
    tid = O.create_task("大理 5 天", mode="quick", research_type="assessment")["taskId"]
    O.submit_clarify(tid, {"days": "5", "party": "亲子"})
    clar = db.get_task(tid)["clarifications"]
    assert clar["_type"] == "assessment", "澄清后类型丢失 → 报告会退回 guide 章节集"
    assert clar["_mode"] == "quick"
    assert clar["days"] == "5"


def test_submit_clarify_explicit_type_overrides_meta():
    """用户在前端改选类型后重新提交 → 以显式值为准（不得被旧 meta 覆盖）。"""
    tid = O.create_task("q", research_type="guide")["taskId"]
    O.submit_clarify(tid, {"_type": "assessment"})
    assert db.get_task(tid)["clarifications"]["_type"] == "assessment"


def test_research_type_flows_to_run_pipeline(tmp_path):
    """任务 meta `_type` → run_pipeline 解析出同一类型（防中途静默降级为 guide）。"""
    tid = O.create_task("评估成都", mode="quick", research_type="assessment")["taskId"]
    O.submit_clarify(tid, {})
    seen = {}

    async def impl():
        gen = O.research_pipeline(tid)
        async for ev in gen:
            if ev["type"] == "message" and ev["data"].get("kind") == "mode":
                seen["research_type"] = ev["data"].get("research_type")
                break

    asyncio.run(impl())
    assert seen.get("research_type") == "assessment"


# ── ④b 旧客户端 purpose 别名归一（部署窗口兼容：旧 bundle 只发 purpose）────
def test_api_create_task_legacy_purpose_aliases_roundtrip():
    """BE-1：不发 type、只发旧 purpose 方言 → 归一到权威 research_type。

    assess（旧前端 ResearchWizard 方言）必须落 assessment——这是「真实态选评估
    静默建成攻略」线上 bug 的后端回归钉；travel_assess/travel_guide 同源归一。
    """
    cli = TestClient(app)
    cases = {"assess": "assessment", "travel_assess": "assessment",
             "guide": "guide", "travel_guide": "guide"}
    for purpose, expected in cases.items():
        j = cli.post("/api/tasks", json={"query": f"q-{purpose}", "purpose": purpose}).json()
        assert j["researchType"] == expected, f"purpose={purpose!r} 应归一为 {expected}"
        assert (db.get_task(j["taskId"])["clarifications"] or {}).get("_type") == expected


def test_api_create_task_explicit_type_wins_over_purpose():
    """BE-2：type 与 purpose 冲突时显式 type 权威优先。"""
    cli = TestClient(app)
    j = cli.post("/api/tasks", json={"query": "q", "type": "assessment",
                                     "purpose": "guide"}).json()
    assert j["researchType"] == "assessment"


def test_api_create_task_no_type_no_purpose_defaults_guide():
    """边界：type/purpose 皆缺省（或皆非法）→ guide，200 不报错。"""
    cli = TestClient(app)
    j = cli.post("/api/tasks", json={"query": "q"}).json()
    assert j["researchType"] == rt.DEFAULT_RESEARCH_TYPE
    j2 = cli.post("/api/tasks", json={"query": "q", "purpose": "什么都不是"}).json()
    assert j2["researchType"] == rt.DEFAULT_RESEARCH_TYPE


# ── ⑤ 澄清 SSE 载荷键名（新键在、旧键不得回潮）─────────────
def test_clarify_fallback_payload_key_is_destinations():
    async def impl():
        tid = O._sid("t")
        db.save_task(tid, "三亚亲子游", {"_type": "guide"})
        with patch.object(O, "_discover_scope", side_effect=RuntimeError("boom")):
            return [ev async for ev in O.generate_clarify(tid, "三亚亲子游")]

    events = asyncio.run(impl())
    upd = [e for e in events if e["type"] == "clarify_update"]
    assert upd, "兜底仍应产出 clarify_update"
    data = upd[0]["data"]
    assert data["destinations_fallback"] is True
    assert "competitors_fallback" not in data, "旧键不得回潮（前端已改读 destinations_fallback）"
    qids = [q["id"] for q in data["questions"]]
    assert "destinations" in qids and "competitors" not in qids


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))


# ──  跨端结构化块契约镜像（D6b 的门禁强度）────────────────────
# 前端 crossEndBlockTypes.test.ts 读的是 checked-in 快照、不联网（CI 里后端不在线）。
# 若没人钉「快照 ≡ 注册表」，那道门守的就是一份可能过期的冻结文件而非真相源——
# 加一个块类型只改注册表、忘了重跑生成器，前端门照样全绿。

def _front_fixture_types():
    import json
    from pathlib import Path
    p = (Path(__file__).resolve().parent.parent.parent
         / "frontend" / "src" / "mocks" / "researchTypes.json")
    return {t["key"]: t for t in json.loads(p.read_text(encoding="utf-8"))["types"]}


def test_fixture_snapshot_matches_registry_block_types():
    snap = _front_fixture_types()
    assert set(snap) == set(rt.RESEARCH_TYPES), "快照类型集与注册表漂移"
    for opt in rt.research_type_options():
        key = opt["key"]
        assert key in snap, f"{key} 不在快照里——重跑 gen-research-types-fixture.mjs"
        assert snap[key].get("structured_block_types") == opt["structured_block_types"], \
            (f"{key} 快照里的 structured_block_types 已落后于注册表："
             f"快照={snap[key].get('structured_block_types')} 注册表={opt['structured_block_types']}")


def test_frontend_retired_block_list_matches_backend_deprecated_fields():
    """前端 VStructured 的退役清单必须覆盖后端 DEPRECATED_CLAIM_FIELDS。

    两边各自维护一份「哪些块已死」，漂移的后果是：后端已停产的旧块在前端被当成
    「版本错位的未知块」，在用户会分享的报告里画出「数据暂不可用」——噪声而非信号。
    """
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent.parent / "frontend" / "src"
           / "components" / "VStructured.tsx").read_text(encoding="utf-8")
    m = re.search(r"RETIRED_BLOCK_TYPES[^=]*=\s*new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "前端找不到 RETIRED_BLOCK_TYPES 定义（改名或删了？退役块的静默契约随之失效）"
    retired = set(re.findall(r"'([^']*)'", m.group(1)))
    assert set(rt.DEPRECATED_CLAIM_FIELDS) <= retired, \
        f"后端已废弃但前端未列入退役清单：{set(rt.DEPRECATED_CLAIM_FIELDS) - retired}"
