"""双类型流水线端到端契约（《测试覆盖方案》B9 / 执行计划 §5.4；规则 R6 事件协议 + R4 键名成对）。

守护的不变量（orchestrator.run_pipeline → _assemble_report → db）：
- 事件协议：首帧 node_update(idle) → … → report_ready → done{reportId}；无 error；percent 单调不减。
- 类型驱动：报告 research_type 与任务 meta `_type` 一致；章节集 == RT.sections_for(type, mode)
  （证伪「章节集写死」与「类型中途丢失」）。
- 图表集：实际产出图的 type 序列 == spec["charts"]（注册表 ↔ 构建器逐项一致，非仅子集）。
- 结构化：report.structured 键 == spec["structured_keys"] 且均非空；承载章 structured.type 合法。
- runner 透传：`ensure_running` 驱动的任务，报告类型 == 建任务时选的类型（B-03 分发路径）。

做法：全量 mock（chat_json / multi_search / fetch_page，零 token 零网络），
沿用 test_report_brief.py 的 monkeypatch 手法；证据 id 从 analyze 提示词里正则回收，
使 claims/结构化对象挂的是真实 id（不被 _filter_eids 清空）。
运行：backend/ 下 `pytest tests/test_two_type_pipeline.py -q`
"""
import asyncio
import re

import pytest

from app.core import db, runner
from app.core import orchestrator as O
from app.core import research_types as RT
from app.core import sentiment

# 统一走 quick（rework_rounds=0，章节 5 章），保持用例时长可控
MODE = "quick"
QUERIES = {
    "guide": "大理 5 天亲子游攻略",
    "assessment": "评估成都和杭州哪个更适合长期居住",
}
DEST = {"guide": ["大理", "丽江"], "assessment": ["成都", "杭州"]}
_DISPATCH_TEAM = [
    {"id": "L3-001", "reason": "决策层统筹全局与终审"},
    {"id": "L2-001", "reason": "策略顾问负责目的地横向对比研判"},
    {"id": "L2-002", "reason": "预算与合规顾问负责成本拆解"},
    {"id": "L1-025", "reason": "通用采集专家负责联网取证"},
    {"id": "L1-030", "reason": "舆情专家负责口碑与情感分析"},
    {"id": "L3-003", "reason": "质检负责四铁律审裁"},
]
_EID_RE = re.compile(r"\[(e_[0-9a-f]{8})\|")


def _alpha(n: int) -> str:
    n = int(n) % 26
    return chr(97 + n)


def _install_fakes(monkeypatch) -> dict:
    """装齐全量假外部依赖；返回调用记录，供断言「确实走了 LLM/搜索路径」。"""
    calls: dict = {"llm": [], "search": 0, "fetch": 0}

    def fake_chat_json(messages, temperature=0.3, max_tokens=2048, model=None, *, purpose=""):
        calls["llm"].append(purpose)
        content = messages[-1]["content"]
        if purpose == "拆解调研计划（目的地/维度/搜索角度）":
            rtype = _rtype_of(content)
            return {"subject": DEST[rtype][0], "region": "云南省",
                    "destinations": list(DEST[rtype]),
                    "focus": ["交通", "住宿", "预算", "口碑"],
                    "search_angles": [f"角度{i}" for i in range(4)]}
        if purpose == "动态指派专家团队":
            return {"lead": "L3-001", "members": list(_DISPATCH_TEAM)}
        if purpose == "交叉验证产出论点与结构化对比数据":
            eids = _EID_RE.findall(content)[:2]
            assert eids, "分析阶段提示词必须携带真实证据 id（否则用例的引用断言失去意义）"
            return _analysis_payload(_rtype_of(content), _DEST_OF_CONTENT(content), eids)
        if purpose.startswith("结构化目的地知识"):
            eids = _EID_RE.findall(content)[:2] or []
            return _structured_payload(purpose, _DEST_OF_CONTENT(content), eids)
        if purpose.startswith("撰写章节：") or purpose.startswith("重试撰写章节："):
            return {"paragraphs": ["第一段正文：基于证据给出的核心判断与取舍。",
                                   "第二段正文：展开论证链、给出可执行建议。"],
                    "key_takeaway": "核心判断：值得去但需错峰。",
                    "highlights": ["亮点一", "亮点二"]}
        if purpose.startswith("质检官审阅"):
            return {"verdict": "pass", "scores": {"证据充分性": 82, "维度完整性": 77},
                    "review": "证据链完整。", "issues": [], "suggestions": []}
        # 无 purpose 的调用（舆情逐条情感分类 / 金句提炼）→ 返非 dict/非 list，
        # 让 sentiment 走规则兜底，避免用例耦合到具体情感分布
        return None

    def fake_multi_search(queries, *, num=10, site=None, freshness="noLimit"):
        calls["search"] += 1
        out = []
        for q in queries:
            per = 2 if site else 3
            for i in range(per):
                uid = f"{_alpha(calls['search'])}{_alpha(calls['search'] // 26)}{_alpha(i)}{_alpha(i * 3)}"
                out.append({
                    "url": f"https://news{uid}.example.com/p/{uid}",
                    "title": f"{q}｜公开资料 {uid}",
                    "snippet": f"{q} 的公开资料摘要：交通、住宿与预算信息 {uid}",
                    "captured_at": "2026-08-01",
                })
        return out

    def fake_fetch_page(url, *, fallback_snippet=""):
        calls["fetch"] += 1
        uid = f"{_alpha(calls['fetch'])}{_alpha(calls['fetch'] // 26)}{_alpha(calls['fetch'] * 7)}"
        # 正文唯一化：共享片段只留 20 字，其余由该页专属 token 撑起，确保信源组不误归并
        words = " ".join(f"{uid}{_alpha(j)}" for j in range(26))
        text = f"{fallback_snippet[:20]}。{words}。"
        return {"text": text, "images": [], "ok": True, "degraded": False,
                "captured_at": "2026-08-01", "url": url}

    monkeypatch.setattr(O, "chat_json", fake_chat_json, raising=False)
    monkeypatch.setattr(O, "multi_search", fake_multi_search, raising=False)
    monkeypatch.setattr(O, "fetch_page", fake_fetch_page, raising=False)
    # 舆情/质检各自持有 chat_json 引用（module-level / 函数内 import），逐一覆盖
    monkeypatch.setattr(sentiment, "chat_json", fake_chat_json, raising=False)
    import app.core.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_json", fake_chat_json, raising=False)
    return calls


def _DEST_OF_CONTENT(content: str):
    """从提示词的「目的地：A、B」行回收目的地，保证假数据与真实入参同名。"""
    m = re.search(r"目的地：([^\n]+)", content)
    if not m:
        return ["大理"]
    out = [x.strip() for x in re.split(r"[、,]", m.group(1)) if x.strip()]
    return out or ["大理"]


def _rtype_of(content: str) -> str:
    """提示词回显调研主题，据此判定类型（提示词与注册表同源，故不写死类型分支）。"""
    for key, query in QUERIES.items():
        if query in content:
            return key
    raise AssertionError("假 LLM 无法从提示词识别调研类型")


def _analysis_payload(rtype, dests, eids):
    """覆盖 spec["analysis_keys"] 全部键，且形状能过对应 _sanitize_*（否则图会被整图跳过）。"""
    spec = RT.type_spec(rtype)
    radar_key = spec["radar_key"]
    cost_key = spec["cost_bar"]["key"]
    cost_field = spec["cost_bar"]["value_field"]
    scores = [{"destination": d, "values": [83, 77, 91, 68, 74, 88]} for d in dests]
    payload = {
        "claims": [
            {"text": f"{dests[0]} 的交通便利度与住宿性价比均优于同类目的地。", "field": "overview",
             "evidence_ids": eids[:2], "author": "L2-001", "claim_type": "mixed"},
        ],
        "trends": {"x": ["2024", "2025", "2026"], "unit": "万人次",
                   "series": [{"name": d, "values": [12, 18, 27]} for d in dests]},
        "contradictions": [],
        "share_estimate": [{"name": d, "value": v}
                           for d, v in zip(dests, [60, 40][:len(dests)])],
        radar_key: {"dimensions": ["交通", "住宿", "景点", "美食", "花费", "季节"], "scores": scores},
        cost_key: [{"destination": d, cost_field: 1680 + i * 120, "note": "按公开价格估算",
                    "evidence_ids": eids[:2]} for i, d in enumerate(dests)],
    }
    if "season" in spec["analysis_keys"]:      # guide 独有：季节适配矩阵（12 个月）
        payload["season"] = {"best_months": ["3月", "4月"], "avoid": ["7月"],
                             "matrix": [{"destination": d, "values": [70 + i for i in range(12)]}
                                        for d in dests],
                             "note": "雨季出行体验下降"}
    if "safety_index" in spec["analysis_keys"]:  # assessment 独有：安全分
        payload["safety_index"] = [{"destination": d, "safety_score": 88 - i * 5,
                                    "note": "治安良好", "evidence_ids": eids[:2]}
                                   for i, d in enumerate(dests)]
    if "budget" in payload:
        for i, row in enumerate(payload["budget"]):
            row["tier"] = ["经济", "舒适"][i % 2]
    return payload


def _structured_payload(purpose, dests, eids):
    if "route_plan" in purpose:
        return {
            "route_plan": [{"destination": d, "days": [
                {"day": 1, "spots": [{"name": f"{d}古城", "transport": "步行", "duration": "3小时",
                                      "tip": "早去避人流", "evidence_ids": eids[:1]}]}]}
                for d in dests],
            "stay_options": [{"destination": d, "areas": [
                {"area": "古城片区", "price_range": "300-600 元/晚", "for_whom": "亲子家庭",
                 "pros": ["逛街方便"], "cons": ["夜间偏吵"], "evidence_ids": eids[:1]}]}
                for d in dests],
            "cost_breakdown": [{"destination": d, "items": [
                {"category": "住宿", "amount": 1200, "unit": "元/人", "share": 45,
                 "note": "3 晚中档", "evidence_ids": eids[:1]}]} for d in dests],
        }
    if "access_matrix" in purpose:
        return {
            "access_matrix": [{"destination": d, "routes": [
                {"mode": "高铁", "duration": "1.5 小时", "cost": 180, "frequency": "每小时 2 班",
                 "note": "直达市中心", "evidence_ids": eids[:1]}]} for d in dests],
            "amenity_checklist": [{"destination": d, "items": [
                {"category": "医疗", "item": "三甲医院", "coverage": "full", "note": "3 家",
                 "evidence_ids": eids[:1]}]} for d in dests],
            "risk_profile": [{"destination": d, "items": [
                {"dimension": "气候", "level": "low", "note": "四季温和",
                 "evidence_ids": eids[:1]}]} for d in dests],
        }
    raise AssertionError(f"未预期的结构化 purpose：{purpose}")


def _run_pipeline(rtype):
    """建任务 → 直接驱动 run_pipeline 到终态，返回 (events, report)。"""
    task_id = O.create_task(QUERIES[rtype], MODE, "", rtype)["taskId"]

    async def _scenario():
        evs = []
        async for ev in O.run_pipeline(task_id):
            evs.append(ev)
            if ev["type"] in ("done", "error"):
                break
        return evs

    evs = asyncio.run(_scenario())
    rid = next((e["data"].get("reportId") for e in evs if e["type"] == "done"), None)
    return task_id, evs, (db.get_report(rid) if rid else None)


def _node_sequence(evs):
    return [e["data"]["node"] for e in evs
            if e["type"] == "node_update" and e["data"].get("status") == "working"
            and "node" in e["data"]]


# ── R6 事件协议 ──────────────────────────────────────────
def test_pipeline_event_sequence_travel_types(monkeypatch):
    """node_update 按 DAG 顺序推进到 done；末尾 report_ready → done{reportId}；无 error。"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide")

    assert evs[0]["type"] == "node_update"
    assert all(n["status"] == "idle" for n in evs[0]["data"]["nodes"])
    assert _node_sequence(evs) == ["intake", "orchestrator", "collect", "analyze",
                                   "audit", "write", "done"]

    types = [e["type"] for e in evs]
    assert "error" not in types
    assert types[-1] == "done"
    assert types.index("report_ready") < types.index("done")
    assert evs[-1]["data"]["reportId"] == report["id"]

    percents = [e["data"]["percent"] for e in evs if e["type"] == "progress"]
    assert percents == sorted(percents), f"percent 应单调不减：{percents}"
    assert percents[-1] == 100

    # 类型经 mode 帧对外声明（前端与订阅方据此渲染）
    mode_ev = next(e for e in evs if e["type"] == "message" and e["data"].get("kind") == "mode")
    assert mode_ev["data"]["research_type"] == "guide"

    # 证据事件带 destination（键名成对，R4），且不含旧键 brand
    ev_events = [e for e in evs if e["type"] == "evidence"]
    assert ev_events, "应产出证据事件"
    assert all(e["data"]["destination"] for e in ev_events)
    assert not any("brand" in e["data"] for e in ev_events)


# ── 类型驱动章节集 ───────────────────────────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_report_sections_and_type_match_registry(monkeypatch, rtype):
    """报告 research_type == 所选类型；章节集 == sections_for(type, quick)（舆情/附录章除外）。"""
    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline(rtype)

    assert report["research_type"] == rtype
    assert report["mode"] == MODE
    assert report["query"] == QUERIES[rtype]

    ids = [s["id"] for s in report["sections"] if s["id"] not in ("sentiment", "trace_note")]
    assert ids == RT.sections_for(rtype, MODE), "章节集必须查表而来（写死即失败）"
    # 舆情专章恒在：有结论/风险章时插在其前，否则收尾（quick 档两类型均无 conclusion 章）
    all_ids = [s["id"] for s in report["sections"]]
    assert "sentiment" in all_ids
    closing = [x for x in ("conclusion", "risk") if x in all_ids]
    if closing:
        assert all_ids.index("sentiment") < all_ids.index(closing[0])
    else:
        assert all_ids[-1] == "sentiment"
    # 章节标题来自注册表（numbered 白名单加中文序号）
    by_id = {s["id"]: s["title"] for s in report["sections"]}
    assert by_id["summary"].endswith(RT.SECTION_PLAN["summary"])
    numbered = RT.numbered_titles(RT.sections_for(rtype, MODE), rtype)
    for sid, title in numbered.items():
        assert by_id[sid] == title


# ── 图表集与注册表逐项一致 ───────────────────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_charts_match_registry_exactly(monkeypatch, rtype):
    """产出图序列 == spec["charts"]（注册表增删图而构建器未跟上 → 此处失败）。"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline(rtype)
    spec = RT.type_spec(rtype)

    chart_evs = [e["data"] for e in evs if e["type"] == "chart"]
    types = [c["type"] for c in chart_evs]
    assert types == list(spec["charts"]), "图表集必须与注册表逐项一致且同序"
    assert [c["type"] for c in report["charts"]] == types

    # 每张图的 option 过基础契约；成本图 y 轴单位按类型查表
    for c in chart_evs:
        assert c["option"]["title"]["text"] == c["title"]
        assert c["option"]["series"]
    cost = next(c for c in chart_evs if c["type"] == "cost_bar")
    assert cost["option"]["yAxis"]["name"] == spec["cost_bar"]["unit"]

    # 章节挂图仅限本类型图集
    sec_charts = [ch["type"] for s in report["sections"] for ch in (s.get("charts") or [])]
    assert set(sec_charts) <= set(spec["charts"])


# ── 结构化对象 ───────────────────────────────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_structured_keys_match_registry(monkeypatch, rtype):
    """report.structured 键集 == spec["structured_keys"]，三类对象均非空且挂真实证据引用。"""
    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline(rtype)
    keys = list(RT.type_spec(rtype)["structured_keys"])

    assert set(report["structured"]) == set(keys)
    for k in keys:
        rows = report["structured"][k]
        assert rows and rows[0]["destination"], f"{k} 不应为空且主键为 destination"

    carried = [s for s in report["sections"] if s.get("structured")]
    assert carried, "结构化对象应挂载到承载章节"
    for s in carried:
        assert s["structured"]["type"] in keys
        assert s["structured"]["data"]


# ── runner 分发路径把类型送达流水线 ──────────────────────
def test_runner_drive_delivers_type_to_pipeline(monkeypatch):
    """经 runner.ensure_running 驱动的任务：报告类型 == 建任务所选（_type 落库并透传）。"""
    runner._running.clear()
    _install_fakes(monkeypatch)
    rtype = "assessment"
    task_id = O.create_task(QUERIES[rtype], MODE, "", rtype)["taskId"]

    async def _scenario():
        runner.ensure_running(task_id)
        evs = []
        async for ev in runner.subscribe(task_id):
            evs.append(ev)
            if ev["type"] in ("done", "error"):
                break
        return evs

    evs = asyncio.run(_scenario())
    full = db.get_task_full(task_id)
    assert full["status"] == "done"
    report = db.get_report(full["report_id"])
    assert report["research_type"] == rtype
    assert [s["id"] for s in report["sections"] if s["id"] != "sentiment"] == \
        RT.sections_for(rtype, MODE)
    mode_ev = next(e for e in evs if e["type"] == "message" and e["data"].get("kind") == "mode")
    assert mode_ev["data"]["research_type"] == rtype


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
