"""双类型流水线端到端契约（《测试覆盖方案》B9 / 执行计划 §5.4；规则 R6 事件协议 + R4 键名成对）。

守护的不变量（orchestrator.run_pipeline → _assemble_report → db）：
- 事件协议：首帧 node_update(idle) → … → report_ready → done{reportId}；无 error；percent 单调不减。
- 类型驱动：报告 research_type 与任务 meta `_type` 一致；章节集 == RT.sections_for(type, mode)
  （证伪「章节集写死」与「类型中途丢失」）。
- 图表集：实际产出图的 type 序列 == RT.charts_for(type, 目的地数)（注册表 ↔ 构建器逐项一致，非仅子集）。
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

from app.core import search
from app.core import llm
from app.core import fetcher
from app.core import audit
from app.core import db, runner
from app.core.pipeline.research import engine as O
from app.core import research_types as RT
from app.core import scoring as SC
from app.core import sentiment
from app.services import baidu as baidu_mod

# 统一走 quick（rework_rounds=0，章节 5 章），保持用例时长可控
MODE = "quick"
# 目的地集合政策（《目的地集合政策》M1）后：只有需求原文点过名的候选才会被采纳，
# 故 query 必须把 DEST 里的城市都写全，否则会被收敛成单目的地。
# guide 自本期起受单目的地闸门约束（M3c）：query 与 DEST 均收敛为一城，多目的地拒绝见
# test_guide_single_dest.py；assessment 保留多目的地对比路径不变。
QUERIES = {
    "guide": "大理 5 天亲子游攻略",
    "assessment": "评估成都和杭州哪个更适合长期居住",
}
# 一个目的地都没点名的 guide 需求（走三跳兜底 → 降级横幅）
DEGRADED_QUERY = "我想去个没去过的安静小城玩三天"
_QUERIES_BY_TYPE = {"guide": [QUERIES["guide"], DEGRADED_QUERY],
                    "assessment": [QUERIES["assessment"]]}
DEST = {"guide": ["大理"], "assessment": ["成都", "杭州"]}
# ── 组队夹具 ─────────────────────────────────────────────
# 一份**合法且非兜底**的团队（全部 id 真实存在于 experts.json）。
# 刻意包含 3 位从未在真实调研里出镜过的专家（L2-003 / L1-012 / L1-003），
# 使「节点出镜者是否真的跟随组队结果」成为可断言的事实 —— 见
# test_expert_lineup_follows_dispatch。
#
# 历史教训：本夹具此前填的是 orchestrator.py:1288-1295 的硬编码兜底 6 人，
# 于是这条流水线测试每次都把「真组队失败」验证成「通过」—— 测了等于没测。
_DISPATCH_TEAM = [
    {"id": "L3-001", "reason": "统筹拆解与终审"},
    {"id": "L2-003", "reason": "亲子客群画像与动机分析"},
    {"id": "L2-002", "reason": "成本拆解与预算建模"},
    {"id": "L1-012", "reason": "亲子项目采集与设施核查"},
    {"id": "L1-003", "reason": "古镇信息采集与门票核查"},
    {"id": "L1-030", "reason": "舆情采集与情感分析"},
]
# 已知病症样本：修复前 7 轮真实调研实际出镜的 6 人。保留它不是当作正确答案，
# 而是供断言「出镜集合不得恒等于它」（外部经验里的 golden-sample 回归思路）。
_LEGACY_FALLBACK_TEAM = ["L3-001", "L2-001", "L2-002", "L1-025", "L1-030", "L3-003"]
_EID_RE = re.compile(r"\[(e_[0-9a-f]{8})\|")


def _alpha(n: int) -> str:
    n = int(n) % 26
    return chr(97 + n)


def _install_fakes(monkeypatch) -> dict:
    """装齐全量假外部依赖；返回调用记录，供断言「确实走了 LLM/搜索路径」。

    TC-X0 契约：①未知 purpose 一律 raise（旧版静默 `return None` 会让新增调用点
    悄悄走兜底分支，用例照绿却什么都没测）；②记录每一次 multi_search 的检索词，
    供「检索词不含其它城市名」这类政策断言取数。
    """
    calls: dict = {"llm": [], "search": 0, "search_queries": [], "fetch": 0, "retry": 0}

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
        if purpose == "景点信号抽取（TopN 实体候选）":
            eids = _EID_RE.findall(content)[:2]
            assert eids, "景点信号抽取提示词必须携带真实证据 id"
            return _spot_signals_payload(_DEST_OF_CONTENT(content), eids)
        if purpose.startswith("结构化目的地知识"):
            eids = _EID_RE.findall(content)[:2] or []
            return _structured_payload(purpose, _DEST_OF_CONTENT(content), eids, content)
        if purpose == "视角专属核查表与铁律填格":
            # 亲子视角装配的假产物：空载荷 → 系统按行守恒产出全「待核验」表
            # （填格质量与守卫在 test_perspective_assembly.py 单测，不在此耦合）
            return {"rows": [], "rules": [], "packing": []}
        if purpose.startswith("撰写章节：") or purpose.startswith("重试撰写章节："):
            return {"paragraphs": ["第一段正文：基于证据给出的核心判断与取舍。",
                                   "第二段正文：展开论证链、给出可执行建议。"],
                    "key_takeaway": "核心判断：值得去但需错峰。",
                    "highlights": ["亮点一", "亮点二"]}
        if purpose.startswith("质检官审阅"):
            return {"verdict": "pass", "scores": {"证据充分性": 82, "维度完整性": 77},
                    "review": "证据链完整。", "issues": [], "suggestions": []}
        if purpose == O._DEST_RETRY_PURPOSE:
            # 兜底链第三跳：单独问一次小模型「这句需求里的目的地是谁」
            calls["retry"] += 1
            return {"destination": "候选小城"}
        if purpose == "":
            # 舆情逐条情感分类 / 金句提炼（sentiment.py 不传 purpose）：返非 list，
            # 让 sentiment 走规则兜底，避免用例耦合到具体情感分布
            return None
        raise AssertionError(
            f"未预期的 LLM 调用 purpose：{purpose!r}——新增调用点必须在此显式 mock")

    def fake_multi_search(queries, *, num=10, site=None, freshness="noLimit"):
        calls["search"] += 1
        calls["search_queries"].extend(queries)
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

    monkeypatch.setattr(llm, "chat_json", fake_chat_json, raising=False)
    monkeypatch.setattr(search, "multi_search", fake_multi_search, raising=False)
    monkeypatch.setattr(fetcher, "fetch_page", fake_fetch_page, raising=False)
    # 舆情/质检各自持有 chat_json 引用（module-level / 函数内 import），逐一覆盖
    monkeypatch.setattr(sentiment, "chat_json", fake_chat_json, raising=False)
    import app.core.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_json", fake_chat_json, raising=False)
    # 确定性隔离：所有管线用例默认把百度通道钉成「缺 AK」（TC-B03 等价类），
    # 防开发机 env 泄漏真实 BAIDU_SERVER_AK 让测试打真实网络；需要假百度的用例自行覆盖。
    monkeypatch.setattr(baidu_mod, "_server_config", lambda: ("", 8.0))
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
    for key, queries in _QUERIES_BY_TYPE.items():
        if any(q in content for q in queries):
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
             "evidence_ids": eids[:2], "author": "L2-003", "claim_type": "mixed"},
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
    if "livelihood_cost" in spec["analysis_keys"]:  # assessment 独有：生活成本分项 + 观点章数据
        payload["livelihood_cost"] = [
            {"destination": d, "items": [
                {"category": "房租", "amount": 1800 + i * 200, "unit": "元/月",
                 "evidence_ids": eids[:1]},
                # 带 ￥ 的字符串金额：钉死 sanitize 侧容忍符号漂移（_num_or_none 同口径）
                {"category": "餐饮", "amount": "￥900", "unit": "元/月",
                 "evidence_ids": eids[:1]}]}
            for i, d in enumerate(dests)]
        payload["action_priorities"] = {"items": [
            {"action": f"优先核验{dests[0]}核心区的居住成本", "tier": "high",
             "evidence_ids": eids[:1]}]}
        payload["consensus_split"] = {
            "orthodox": {"label": "主流共识", "summary": f"{dests[0]}性价比占优",
                         "share": 60, "evidence_ids": eids[:1]},
            "contrarian": {"label": "反共识判断", "summary": "旺季实际体验明显下滑",
                           "share": 18, "evidence_ids": eids[:1]}}
    if "budget" in payload:
        for i, row in enumerate(payload["budget"]):
            row["tier"] = ["经济", "舒适"][i % 2]
    return payload


def _spot_signals_payload(dests, eids):
    """spots 实体阶段假信号：只给**可数事实**（mentions/positive_ratio/value_score），
    不给名次与分数——排序与算分是 scoring.rank_spots 的职责（LLM 无评分话语权）。"""
    rows = []
    for i, d in enumerate(dests):
        for j in range(2):   # 每目的地两个候选，覆盖 TopN 截断与排序
            rows.append({
                "name": f"{d}古城" if j == 0 else f"{d}洱海廊道",
                "area": "城区" if j == 0 else "环海路",
                "signals": {"mentions": 30 - i * 8 - j * 5,
                            "positive_ratio": 0.8 - i * 0.1 - j * 0.05,
                            "value_score": 0.7 - i * 0.1},
                "ticket": "免费开放", "stay_minutes": 180 - j * 60,
                "off_peak": "工作日上午", "reason": "地标片区，证据高频提及",
                "evidence_ids": eids[:1],
            })
    return {"spots": rows}


def _structured_payload(purpose, dests, eids, content: str = ""):
    # 实体单一真相源守卫：guide 的结构化提示必须携带 spots 阶段冻结的实体表
    # （M2 起 shop_list 靠它对齐同一批实体；spot_routes 已移入实体阶段键，不再出自 LLM）
    if "shop_list" in purpose:
        assert "已冻结景点实体表" in content, "结构化提示必须注入冻结实体表"
    if "route_plan" in purpose:
        frozen = re.findall(r'"spot_id":\s*"([^"]+)",\s*"name":\s*"([^"]+)"', content)
        sid, sname = frozen[0] if frozen else ("", f"{dests[0]}古城")
        return {
            "food_ranking": [{"destination": d, "items": [
                {"name": f"{d}特色菜", "category": "地方菜", "reason": "口碑高频提及",
                 "price_range": "40-80 元", "evidence_ids": eids[:1]}]} for d in dests],
            # 毒值：spot_routes 属实体阶段键（百度真实路线落库），生产端必须整键丢弃、
            # 绝不采纳 LLM 编造的换乘细节（TC-B03/TC-P02 分别钉两种结局）。
            "spot_routes": [{"destination": d, "items": [
                {"spot_id": sid if d == dests[0] else "", "spot_name": sname if d == dests[0] else f"{d}古城",
                 "routes": [{"mode": "地铁", "duration": "25 分钟", "cost": "4 元",
                             "transfer": "1 次", "note": "古城东门站下",
                             "evidence_ids": eids[:1]}]}]} for d in dests],
            "shop_list": [{"destination": d, "items": [
                {"food": f"{d}特色菜", "name": f"{d}老字号餐馆", "area": "古城片区",
                 "price_per_person": "￥58", "queue_note": "饭点排队约 30 分钟",
                 "evidence_ids": eids[:1]}]} for d in dests],
            "route_plan": [{"destination": d, "days": [
                {"day": 1, "spots": [{"name": f"{d}古城", "transport": "步行", "duration": "3小时",
                                      "tip": "早去避人流", "evidence_ids": eids[:1]}]}]}
                for d in dests],
            "stay_options": [{"destination": d, "areas": [
                {"area": "古城片区", "price_range": "300-600 元/晚",
                 "price_min": 300, "price_max": 600, "for_whom": "亲子家庭",
                 "pros": ["逛街方便"], "cons": ["夜间偏吵"], "evidence_ids": eids[:1]}]}
                for d in dests],
            "cost_breakdown": [{"destination": d, "items": [
                {"category": "住宿", "amount": 1200, "unit": "元/人", "share": 45,
                 "note": "3 晚中档", "evidence_ids": eids[:1]}]} for d in dests],
        }
    if "access_matrix" in purpose:
        return {
            # 三种方式齐备是可达性雷达的**出图前提**（维度 = 各目的地共有方式，<3 维不出图）；
            # 真实 LLM 产出本就会覆盖高铁/飞机/自驾，夹具只给一种方式等于把「可达性章
            # 必然无图」固化成假事实。
            "access_matrix": [{"destination": d, "routes": [
                {"mode": mode, "duration": f"{mins // 60} 小时", "cost": f"{cost} 元",
                 "frequency": "每小时 2 班", "note": "直达市中心",
                 # 批次①：可选数值字段（供确定性算分）；文本 duration/cost 保留展示
                 "duration_minutes": mins + i * 40, "cost_yuan": cost + i * 60,
                 "evidence_ids": eids[:1]}
                for mode, mins, cost in (("高铁", 95, 180), ("飞机", 150, 520),
                                         ("自驾", 260, 320))]}
                for i, d in enumerate(dests)],
            "amenity_checklist": [{"destination": d, "items": [
                {"category": "医疗", "item": "三甲医院", "coverage": "full", "note": "3 家",
                 "evidence_ids": eids[:1]}]} for d in dests],
            "risk_profile": [{"destination": d, "items": [
                {"dimension": "气候", "level": "low", "note": "四季温和",
                 "evidence_ids": eids[:1]},
                # 第二维：风险热力网格要求各目的地**共有**维度 ≥2 才出图
                # （单维热力网格退化成一排色块，不出图是设计而非缺陷）
                {"dimension": "治安", "level": "medium", "note": "夜间人流密集区需留意",
                 "evidence_ids": eids[:1]}]} for d in dests],
        }
    raise AssertionError(f"未预期的结构化 purpose：{purpose}")


def _run_pipeline(rtype, query: str = None, clar: dict = None, mode: str = MODE):
    """建任务（可选注入澄清答案）→ 直接驱动 run_pipeline 到终态，返回 (events, report)。"""
    task_id = O.create_task(query or QUERIES[rtype], mode, "", rtype)["taskId"]
    if clar:
        O.submit_clarify(task_id, clar)

    async def _scenario():
        evs = []
        async for ev in O.research_pipeline(task_id):
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
    # guide 特有 spots 实体节点（assessment 无实体阶段，见下方类型章节用例）
    assert _node_sequence(evs) == ["intake", "orchestrator", "collect", "analyze",
                                   "spots", "audit", "write", "done"]

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
    """产出图序列 == charts_for(类型, 目的地数)（注册表增删图而构建器未跟上 → 此处失败）。"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline(rtype)
    expected = list(RT.charts_for(rtype, len(DEST[rtype])))

    chart_evs = [e["data"] for e in evs if e["type"] == "chart"]
    types = [c["type"] for c in chart_evs]
    # 注册表声明的是「类型集」，同一类型可由构建器产出多张（如 cost_bar 同时承载
    # 生活成本柱与安全评分柱）。原断言按类型序列逐项相等，隐含「一类型一张图」，
    # 与 3888 的按类型广播同源。改为比对**去重后的类型序列**：仍守住本用例原意
    # （注册表增删图而构建器未跟上 → 此处失败），但不 forbid 同类型多图。
    dedup = lambda seq: list(dict.fromkeys(seq))
    assert dedup(types) == dedup(expected), \
        "去重后的图表类型序列必须与注册表自适应图集一致且同序"
    assert [c["type"] for c in report["charts"]] == types

    # 每张图过基础契约（E1：wordcloud 走 words 语义载荷，其余走 echarts option）；成本图 y 轴单位按类型查表
    for c in chart_evs:
        if c["type"] == "wordcloud":
            assert c["words"] and "option" not in c
        else:
            assert c["option"]["title"]["text"] == c["title"]
            assert c["option"]["series"]
    # 成本图的 y 轴单位：按**注册表声明的标题**精确定位，而非 next(第一个 cost_bar)。
    # 后者取到哪张取决于构建器产出顺序（与 3926 的 c[0] 同类顺序依赖）——同类型
    # 已有 2 张 cost_bar 时，next() 一旦取到安全评分柱就会误判。
    cost_title = RT.cost_bar_title(rtype, len(DEST[rtype]))
    cost = next(c for c in chart_evs
                if c["type"] == "cost_bar" and c["title"] == cost_title)
    assert cost["option"]["yAxis"]["name"] == RT.type_spec(rtype)["cost_bar"]["unit"]

    # 章节挂图仅限本类型图集
    sec_charts = [ch["type"] for s in report["sections"] for ch in (s.get("charts") or [])]
    assert set(sec_charts) <= set(expected)


# ── T-03 图表章节归属唯一性（glacial-vale-sparrow 批次⓪）─────────────
# 既有 :391-392 只断言「章节挂的图类型 ⊆ 图集」，完全不校验归属唯一性——
# 装配层 orchestrator.py 旧实现是 `for t in chart_types for c in charts_by_type[t]`，
# 即按**类型**无差别广播全部；批次⓪ 已改为「归属优先」：声明了 sections 的图只按
# 归属匹配，未声明的图维持按类型广播。
#
# 不变量的精确边界（实测校准，勿放宽）：
#   assessment 现有三处跨章共用同一类型，其中 radar(summary+verdict) 与
#   trend(summary+trend) 是**有意的单图复用**——综合研判章复用宜居度雷达合理。
#   真正的缺陷只在「同类型产出 >1 张时仍整组广播」：此时每章都会拿到全部张数，
#   而非归属自己的那张。故本用例只钉 N>1 这一条件，不误伤单图复用。
def test_multi_chart_type_not_broadcast_wholesale(monkeypatch):
    """T-03：某类型产出多张图时，任一章不得拿到该类型的全部张数。

    刻意用 deep 而非模块默认 quick：quick 档 assessment 章节集不含 value，
    cost_bar 只有一章挂载，广播与精确匹配结果相同，用例会假绿。
    """
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("assessment", mode="deep")
    charts = [e["data"] for e in evs if e["type"] == "chart"]

    by_type = {}
    for c in charts:
        by_type.setdefault(c["type"], []).append(c["chart_id"])
    multi = {t: ids for t, ids in by_type.items() if len(ids) > 1}
    assert multi, (
        "本用例假设存在同类型多图（assessment 的 cost_bar 应有 2 张）；若已不存在，"
        "说明产出结构变了，请改测真实风险面而非留个空转用例"
    )

    for sec in report["sections"]:
        held = {c["chart_id"] for c in (sec.get("charts") or [])}
        for ctype, ids in multi.items():
            assert not (set(ids) <= held), (
                f"图表串章：{ctype!r} 实产 {len(ids)} 张，章节 {sec['id']!r} 却拿到了"
                f"全部 {len(ids)} 张——装配层按类型整组广播而非按归属精确匹配（根因③）"
            )


def test_same_type_multi_charts_declare_sections(monkeypatch):
    """T-03 前置契约：同一类型若产出多张图，各张必须带 sections 归属声明。

    单张时按类型广播恰好等价于按归属挂载，且这种「一图多章」是有意的复用
    （assessment 的 radar 同供 summary 与 verdict、trend 同供 summary 与 trend），
    所以真正的风险面只在「同类型 ≥2 张」——本用例只钉这个条件。
    归属用复数 sections 而非单数 section：一张图可能需要合法地出现在多章。
    """
    _install_fakes(monkeypatch)
    _, evs, _ = _run_pipeline("assessment", mode="deep")
    charts = [e["data"] for e in evs if e["type"] == "chart"]
    by_type = {}
    for c in charts:
        by_type.setdefault(c["type"], []).append(c)
    multi = {t: g for t, g in by_type.items() if len(g) > 1}
    assert multi, (
        "本用例假设存在同类型多图（assessment 的 cost_bar 应有 2 张）；若已不存在，"
        "说明产出结构变了，请改测真实风险面而非留个空转用例"
    )
    for ctype, group in multi.items():
        missing = [c["chart_id"] for c in group if not c.get("sections")]
        assert not missing, (
            f"类型 {ctype!r} 产出 {len(group)} 张图，其中 {len(missing)} 张缺 "
            f"sections 归属声明——按类型广播会串章"
        )


@pytest.mark.parametrize("mode", ["deep", "expert"])
def test_assessment_every_section_has_charts_end_to_end(monkeypatch, mode):
    """批次② 端到端：装配后的报告里 assessment **每个章节都挂着图**。

    与 test_assessment_charts.py 分层不同：那里测 `_build_charts` + 归属谓词，
    这里测 `_assemble_report` 真把图挂进了章节——两层之间的断点正是根因③的藏身处
    （builder 产出了、谓词也对，装配层却按类型广播/漏挂）。
    用户要求「2-11 章都需要可视化」，本用例是那句话在装配层的固化。
    """
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("assessment", mode=mode)
    assert not [e for e in evs if e["type"] == "error"]

    sections = report["sections"]
    # assessment 无 sentiment_report 章 → 装配层另插一处报告级舆情面板（既有行为）
    assert {s["id"] for s in sections} - {"sentiment"} == set(RT.sections_for("assessment", mode))
    missing = [s["id"] for s in sections if not (s.get("charts") or [])]
    assert not missing, f"{mode} 档装配后无图章节：{missing}"
    # 舆情章也必须配图（情感分布 + 平台声量）
    sent = next(s for s in sections if s["id"] == "sentiment")
    assert {c["type"] for c in sent["charts"]} == {"sentiment_donut", "platform_bar"}


# ── 结构化对象 ───────────────────────────────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_structured_keys_match_registry(monkeypatch, rtype):
    """report.structured 键集 == spec["structured_keys"]，全部键均非空且挂真实证据引用。"""
    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline(rtype)
    keys = list(RT.type_spec(rtype)["structured_keys"])

    assert set(report["structured"]) == set(keys)
    for k in keys:
        rows = report["structured"][k]
        if k == "spot_routes":
            # M2：路线卡只出自百度真实数据；本套件百度通道被钉成缺 AK → 空表占位是预期
            # 终态（LLM 毒值必须被整键丢弃），非空结局见 TC-P02 假百度用例。
            assert rows == [], f"缺 AK 时 spot_routes 必须降级为空表，实得：{rows}"
            continue
        assert rows and rows[0]["destination"], f"{k} 不应为空且主键为 destination"

    if "spot_ranking" in keys:
        # 实体阶段冻结表：名次由 scoring 降序回填、分数为规则算出（LLM 无评分话语权）；
        # spot_id 稳定生成，是下游路线卡/商铺/舆情的唯一挂接键。
        items = report["structured"]["spot_ranking"][0]["items"]
        assert [it["rank"] for it in items] == list(range(1, len(items) + 1))
        assert all(it["spot_id"] and it["score"] is not None and it["signals"] for it in items)
        assert items == sorted(items, key=lambda it: -it["score"])

    carried = [s for s in report["sections"] if s.get("structured")]
    assert carried, "结构化对象应挂载到承载章节"
    for s in carried:
        # 复数挂块契约（rough-cliff-vole）：sec["structured"] == [{type,data},…]
        blocks = s["structured"]
        assert isinstance(blocks, list), "挂块必须是复数列表（单块 break 契约已退役）"
        for b in blocks:
            assert b["type"] in keys
            assert b["data"]


def test_fake_analysis_payload_covers_all_analysis_keys():
    """假 LLM 载荷必须覆盖 spec["analysis_keys"] 全部键（批次① 三新键即在此钉住）。

    缺键的假载荷会让端到端用例悄悄跳过该键的清洗/装配链路——覆盖缺口不报错的
    静默失败，与 _analysis_payload 的 docstring 承诺相分离。
    """
    for rtype in ("guide", "assessment"):
        spec = RT.type_spec(rtype)
        payload = _analysis_payload(rtype, DEST[rtype], ["e1", "e2"])
        missing = set(spec["analysis_keys"]) - set(payload)
        assert not missing, f"{rtype} 假载荷缺分析键：{sorted(missing)}"


def test_assessment_numeric_route_fields_reach_report_structured(monkeypatch):
    """批次① 端到端：access_matrix 的可选数值字段经 coerce 落入报告 structured，
    且 scoring 能据此算出可达性分（数值由规则算出，LLM 无评分话语权）。"""
    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline("assessment")

    rows = report["structured"]["access_matrix"]
    routes = [r for row in rows for r in row["routes"]]
    assert routes and all("duration_minutes" in r and "cost_yuan" in r for r in routes), \
        "可选数值字段被 coerce_access_matrix 静默丢弃"

    scores = SC.score_accessibility(rows)
    assert [s["destination"] for s in scores] == report["destinations"]
    assert all(0.0 < s["score"] <= 100.0 for s in scores)
    assert all(s["modes"] for s in scores)


def test_spot_routes_and_entities_degrade_without_baidu_ak(monkeypatch):
    """TC-B03 / EX-D：缺百度服务端 AK 时实体解析/路线/商铺 POI 整体占位降级——
    榜单表（LLM 证据版）照常产出、报告不失败，且 LLM 编造的路线毒值不被采纳。
    （百度通道已由 _install_fakes 钉成缺 AK。）"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide")
    assert report and not [e for e in evs if e["type"] == "error"], "降级不得炸任务"
    items = report["structured"]["spot_ranking"][0]["items"]
    assert items and all(it["matched"] is False and it["lat"] is None for it in items)
    assert report["structured"]["spot_routes"] == []
    shops = report["structured"]["shop_list"][0]["items"]
    # 商铺未经 POI 核验时 matched 为 False/None（未核验占位），绝不为 True
    assert shops and all(s["matched"] is not True and s["lat"] is None for s in shops)
    assert any("未配置百度服务端 AK" in (e["data"].get("text") or "")
               for e in evs if e["type"] == "thought"), "降级必须留下可见的如实提示"


def _install_fake_baidu(monkeypatch):
    """假百度通道（envelope 形状与 services/baidu 契约一致）。
    客户端自身的失败等价类由 test_baidu_client.py 单测，这里只测编排接线。"""
    monkeypatch.setattr(baidu_mod, "available", lambda: True)
    monkeypatch.setattr(baidu_mod, "geocode",
                        lambda address, city="": {"ok": True, "lat": 25.70, "lng": 100.15,
                                                  "confidence": 90})
    monkeypatch.setattr(
        baidu_mod, "place_search",
        lambda query, region, **kw: {"ok": True, "places": [
            {"name": query, "lat": 25.69, "lng": 100.16,
             "area": "大理市", "address": "某路1号", "tag": ""}]})

    def _fake_direction(mode, origin, destination, city=None, city_limit=True):
        return {"ok": True, "routes": [{
            "distance_m": 8200, "duration_s": 2400,
            "steps": [{"instruction": "乘坐地铁1号线", "vehicle": "地铁1号线",
                       "distance_m": "1.2公里"}]}]}

    monkeypatch.setattr(baidu_mod, "direction", _fake_direction)


def test_spot_entity_ids_flow_into_downstream_structured(monkeypatch):
    """TC-P02 / INV-C：百度通道可用时，路线卡只引用冻结实体表的 spot_id，
    坐标真实回填、打车费为规则估算——「文字里的景点和地图上的景点对不上」
    这一架构根因的管线级防线。"""
    _install_fakes(monkeypatch)
    _install_fake_baidu(monkeypatch)
    _, _, report = _run_pipeline("guide")
    frozen_ids = {it["spot_id"] for g in report["structured"]["spot_ranking"] for it in g["items"]}
    assert frozen_ids, "冻结实体表不能为空（假工厂已提供信号）"
    items = report["structured"]["spot_ranking"][0]["items"]
    assert all(it["matched"] and it["lat"] == 25.69 for it in items), "实体解析应回填坐标"
    groups = report["structured"]["spot_routes"]
    assert groups and groups[0]["destination"]
    ref_ids = {it["spot_id"] for g in groups for it in g["items"]}
    assert ref_ids and ref_ids <= frozen_ids, \
        f"路线卡引用了表外 spot_id：{ref_ids - frozen_ids}"
    routes = [r for g in groups for it in g["items"] for r in it["routes"]]
    modes = {r["mode"] for r in routes}
    assert modes == {"公交/地铁", "打车"}, f"路线应出自百度真实通道而非 LLM 毒值：{modes}"
    taxi = next(r for r in routes if r["mode"] == "打车")
    assert "估算" in taxi["cost"], "打车费为里程规则估价，必须标「估算」"


# ── 问卷勾选是目的地集合的显式通道（P1-2）──────────────────
def test_clarify_checked_destinations_are_respected(monkeypatch):
    """最终集合 == 勾选 ∪ 原文提及（勾选在前），未勾选且未点名的候选一律不纳入。

    guide 单目的地闸门（M3c）后勾选通道不可能再产出两城集合，改由 assessment 守此不变量；
    guide 勾选单城的正常路径与多目的地拒绝见 test_guide_single_dest.py。
    """
    calls = _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("assessment", None, {"destinations": ["杭州"]})

    assert report["destinations"] == ["杭州", "成都"], "勾选项必须被纳入，且排在原文提及之前"
    assert not [e for e in evs if e["type"] == "message"
                and e["data"].get("kind") == "plan_fallback"], "走勾选路径不应判为降级"

    # 检索词只围绕这两个目的地：不引入第三座城市的名字
    others = ("大理", "丽江", "西双版纳")
    assert not [q for q in calls["search_queries"] if any(o in q for o in others)]


# ── C6 · 报告头部答题摘要（TC-S1/S3）────────────────────────
def test_family_perspective_end_to_end_placeholder_table_and_timing(monkeypatch):
    """亲子视角端到端（rough-cliff-vole VR-D3）：核查表行=冻结榜、装配先于质量评估、块挂章。"""
    _install_fakes(monkeypatch)
    seen_structured_keys_at_quality: list = []
    real_eq = audit.evaluate_quality

    def spy_eq(destinations, focus, claims, evidences, structured, **kw):
        seen_structured_keys_at_quality.append(set(structured))
        return real_eq(destinations, focus, claims, evidences, structured, **kw)

    monkeypatch.setattr(audit, "evaluate_quality", spy_eq)
    clar = {"party": "亲子家庭", "child_age": "3-6 岁", "days": "1-2 天",
            "budget_level": "经济实惠（人均 <1000）", "origin": "昆明"}
    _, evs, report = _run_pipeline("guide", None, clar)
    assert report

    structured = report["structured"]
    assert "persp_checklist" in structured and "persp_rules" in structured
    rows = structured["persp_checklist"][0]["items"]
    spot_rows = structured["spot_ranking"][0]["items"]
    assert [r["spot_id"] for r in rows] == [s["spot_id"] for s in spot_rows], \
        "核查表行集必须逐行等于冻结榜（行守恒 seed，LLM 不可造行/丢行）"
    assert all(len(r["cells"]) == 4 for r in rows)
    # 时序：第一次质量评估时视角键已在（装配先于质检——分母认键、质检看得到表）
    assert seen_structured_keys_at_quality and "persp_checklist" in seen_structured_keys_at_quality[0]
    # 块挂章：SECTION_STRUCTURED 通道把核查表挂到亲子视角章
    persp_sec = next(s for s in report["sections"] if s["id"] == "persp_family")
    mounted = {b["type"] for b in (persp_sec.get("structured") or [])}
    assert {"persp_checklist", "persp_rules", "persp_packing"} <= mounted


def test_report_answers_digest_whitelist_and_origin_exclusion(monkeypatch):
    """digest 行只来自注册表白名单；目的地取计划层终值；origin 是检索凭据、不进摘要。"""
    _install_fakes(monkeypatch)
    clar = {"days": "3-5 天", "party": "亲子家庭", "child_age": "3-6 岁", "origin": "北京",
            "focus": ["交通路线", "美食与商铺"], "budget_level": "舒适均衡（1000-3000）"}
    _, evs, report = _run_pipeline("guide", None, clar)
    assert evs[-1]["type"] == "done" and report

    digest = report["answers_digest"]
    assert [(d["label"], d["value"]) for d in digest] == [
        ("天数", "3-5 天"), ("人群", "亲子家庭"), ("娃龄", "3-6 岁"),
        ("侧重", "交通路线、美食与商铺"), ("目的地", "大理")], (
        "行集/顺序/展示名都必须与 CLARIFY_CONSUMERS 的 digest 登记逐项一致")
    flat = "".join(d["value"] for d in digest)
    assert "北京" not in flat, "出发地只进检索角度，不进答题摘要"
    assert "舒适均衡" not in flat, "plan_text 题不进摘要"
    # 目的地行来自计划层终值（本次勾选为空、由原文锁定），而非问卷原始答案
    assert report["destinations"] == ["大理"]


# ── 检索词与目的地正交（G11 / L2 根因直证）────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_search_queries_orthogonal_to_destination(monkeypatch, rtype):
    """每条检索词恰好含一个本地名、不含他城名、且地名不重复。

    这正是历史缺陷的直接症状：角度里夹带地名/其它城市 → 检索词重复、证据归属串城。
    """
    calls = _install_fakes(monkeypatch)
    _run_pipeline(rtype)
    names = DEST[rtype]
    queries = calls["search_queries"]
    assert queries, "应确实发出检索请求"
    for q in queries:
        hit = [d for d in names if d in q]
        assert len(hit) == 1, f"检索词必须恰好含一个目的地：{q}"
        assert q.count(hit[0]) == 1, f"目的地名不得在检索词里重复：{q}"


# ── 计划降级：温和横幅 + 协议不破（G14 / OBS-01）────────────
def test_plan_fallback_banner_keeps_protocol(monkeypatch):
    """需求里一个目的地都没点名 → 走兜底链：推 plan_fallback 温和帧，R6 协议照旧。"""
    calls = _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide", DEGRADED_QUERY)

    banners = [e for e in evs if e["type"] == "message"
               and e["data"].get("kind") == "plan_fallback"]
    assert len(banners) == 1, "降级只提示一次"
    assert "候选小城" in banners[0]["data"]["text"]
    assert calls["retry"] == 1, "三跳应落到第三跳且恰好一次"

    # 温和提示走 message 通道，不进 error 通道
    types = [e["type"] for e in evs]
    assert "error" not in types and types[-1] == "done"
    percents = [e["data"]["percent"] for e in evs if e["type"] == "progress"]
    assert percents == sorted(percents) and percents[-1] == 100

    # 单目的地：无 donut、标题无「对比」（图集与文案按 N 自适应）
    chart_types = [e["data"]["type"] for e in evs if e["type"] == "chart"]
    assert "donut" not in chart_types
    assert chart_types == list(RT.charts_for("guide", 1))
    for e in evs:
        if e["type"] == "chart":
            assert "对比" not in e["data"]["title"], e["data"]["title"]
    assert report["destinations"] == ["候选小城"]

    # 降级事实进决策日志（trace 是其持久来源），报告 payload 不带内部字段
    step = next(s for s in report["trace"] if s["stage"] == "intake"
                and s["purpose"] == O._DEST_PLAN_STEP)
    assert "降级" in step["decision"]
    assert "degraded" not in report and "dest_source" not in report


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


def test_expert_guide_one_page_view_assembled_from_frozen_entities(monkeypatch):
    """M3a/D2 / INV-C：guide 的 deep 与 expert 档 route_plan 被规则组装整体覆盖——
    逐日停靠全部引用冻结 spot_id（榜单名次保序、每实体恰好一次），抵达交通出自真实
    路线，商铺逐日挂 shop_id。（R-B1：deep 正例断言迁移自 expert 钉，两档同判据。）"""
    for mode in ("deep", "expert"):
        _install_fakes(monkeypatch)
        _install_fake_baidu(monkeypatch)
        _, evs, report = _run_pipeline("guide", mode=mode)
        assert report and not [e for e in evs if e["type"] == "error"]

        frozen_ids = [it["spot_id"] for g in report["structured"]["spot_ranking"] for it in g["items"]]
        assert frozen_ids, "假工厂应给出可冻结实体"
        rp = report["structured"]["route_plan"]
        assert rp and rp[0]["destination"] == "大理"
        stops = [s for d in rp[0]["days"] for s in d["spots"]]
        ref = [s["spot_id"] for s in stops if s.get("spot_id")]
        assert ref == frozen_ids, f"{mode} 档停靠点按榜单名次保序且每实体恰好一次"
        shop_refs = {s["shop_id"] for s in stops if s.get("shop_id")}
        shop_ids = {x["shop_id"] for g in report["structured"]["shop_list"] for x in g["items"]}
        assert shop_refs and shop_refs <= shop_ids, "美食停靠只引用商铺表内实体"
        first = next(s for s in stops if s.get("spot_id") == frozen_ids[0])
        assert "公交" in first["transport"], "抵达交通引用假百度的真实路线通道"
        assert first["lat"] == 25.69 and first["lng"] == 100.16, \
            "N6 分布图数据源：规则组装把冻结实体坐标随挂接透传"
        assert any("一页视图" in (e["data"].get("text") or "")
                   for e in evs if e["type"] == "thought"), "组装事实必须留下可观测 thought"
        # S-B2：stay_options 数值带字段注册联动——LLM 显式产出经 coerce 原样保留
        stay_area = report["structured"]["stay_options"][0]["areas"][0]
        assert (stay_area["price_min"], stay_area["price_max"]) == (300, 600)


def test_quick_guide_route_plan_keeps_llm_version(monkeypatch):
    """quick 档不触发一页视图覆盖（route 章只属 deep/expert）：structured 里的
    route_plan 仍是 LLM 自由发挥版，不带规则组装的实体挂接。（R-B2 反例）"""
    _install_fakes(monkeypatch)
    _install_fake_baidu(monkeypatch)
    _, evs, report = _run_pipeline("guide")
    assert not any("一页视图" in (e["data"].get("text") or "")
                   for e in evs if e["type"] == "thought")
    rp = report["structured"].get("route_plan") or []
    stops = [s for g in rp for d in g["days"] for s in d["spots"]]
    assert all(not s.get("spot_id") for s in stops), "quick 档不得注入规则组装的实体挂接"


# ── D2 · 行程路线章进 deep：章节集 / pace 声明 / 天数双源 ──
def test_guide_deep_sections_include_route_last():
    """R-B5：deep+guide 章节集**显式**含 route 且序为末位（8→9 章）——
    防章节集查表钉（sections_for 同表）静默跟错表。"""
    deep = RT.type_spec("guide")["sections"]["deep"]
    assert deep[-1] == "route", "route 必须挂在 deep 章末位"
    assert len(deep) == 9
    assert RT.sections_for("guide", "deep") == list(deep)
    assert "route" not in RT.type_spec("guide")["sections"]["quick"]


def test_deep_mode_declares_spot_day_pace():
    """R-B3：deep 档**显式**声明 spot_day_pace——不靠 cfg.get 兜底默认，
    与 expert 同为行程组装的规模旋钮。"""
    assert "spot_day_pace" in O.MODE_CONFIG["deep"]
    assert O.MODE_CONFIG["deep"]["spot_day_pace"] > 0


def test_itinerary_days_dual_source_query_then_clarify(monkeypatch):
    """R-B4（评审③）：组装入参天数双源——query 无天数时认问卷 days 答案；
    两路都缺才落 pace 推算，且不造空天。"""
    _install_fakes(monkeypatch)
    _install_fake_baidu(monkeypatch)
    no_days_query = "大理亲子游攻略"

    _, _, via_clar = _run_pipeline("guide", no_days_query,
                                   clar={"days": "3-5 天"}, mode="deep")
    days_clar = via_clar["structured"]["route_plan"][0]["days"]
    n_frozen = sum(len(g["items"]) for g in via_clar["structured"]["spot_ranking"])
    assert all(d["spots"] for d in days_clar), "逐日均有停靠，不造空天"
    assert len(days_clar) <= 5, "「3-5 天」按上限 5 天折算，跨度不超用户天数"
    assert len(days_clar) >= min(n_frozen, 5) or len(days_clar) > 2, \
        "问卷天数应拉开跨度（vs pace 推算）"

    _install_fakes(monkeypatch)
    _install_fake_baidu(monkeypatch)
    _, _, via_pace = _run_pipeline("guide", no_days_query, mode="deep")
    days_pace = via_pace["structured"]["route_plan"][0]["days"]
    assert len(days_clar) > len(days_pace), "query+问卷双缺 → pace 推算更短；问卷答案必须生效"

    _install_fakes(monkeypatch)
    _install_fake_baidu(monkeypatch)
    _, _, both = _run_pipeline("guide", "大理 5 天亲子游攻略", clar={"days": "2 天"}, mode="deep")
    days_both = both["structured"]["route_plan"][0]["days"]
    assert len(days_both) > len(days_pace), "query 原文优先于问卷答案（5 天而非 2 天）"


# ── 搜索服务商终态错误的调用点策略（修复计划 item3 / 覆盖评估 C 组）──
def test_provider_outage_hard_fails_with_real_reason(monkeypatch):
    """TC-P1：collect 首条即欠费 → 任务硬失败，error 帧文案携带真因（不再吞成 0 结果）。"""
    from app.core.search import SearchProviderError
    runner._running.clear()
    _install_fakes(monkeypatch)

    def _dead(queries, **kw):
        raise SearchProviderError("博查账户余额不足，请充值")
    monkeypatch.setattr(search, "multi_search", _dead, raising=False)
    task_id = O.create_task(QUERIES["guide"], MODE, "", "guide")["taskId"]

    async def _scenario():
        runner.ensure_running(task_id)
        evs = []
        async for ev in runner.subscribe(task_id):
            evs.append(ev)
            if ev["type"] in ("done", "error"):
                break
        return evs
    evs = asyncio.run(_scenario())

    errs = [e for e in evs if e["type"] == "error"]
    assert errs, "零证据 + 服务商欠费必须走 error 终态"
    msg = errs[0]["data"]["message"]
    assert "博查账户余额不足" in msg, f"文案必须送达真因：{msg}"
    assert "请检查搜索服务配额/密钥" in msg
    assert db.get_task_full(task_id)["status"] == "failed"


def test_midway_outage_degrades_with_visible_thought(monkeypatch):
    """TC-P2：collect 成功后中途欠费 → 报告照常产出（已完成的分析不炸掉），
    舆情位有含真因的可见 thought，全程不再白烧检索。"""
    from app.core.search import SearchProviderError
    calls = _install_fakes(monkeypatch)
    real_ms = search.multi_search

    def _flaky(queries, **kw):
        if calls["search"] <= 1:
            return real_ms(queries, **kw)   # 首过：collect 主采集正常
        raise SearchProviderError("博查账户余额不足，请充值")
    monkeypatch.setattr(search, "multi_search", _flaky, raising=False)

    _, evs, report = _run_pipeline("guide")
    assert report and evs[-1]["type"] == "done", "中途欠费必须降级继续出报告"
    thoughts = [e["data"].get("text") or "" for e in evs if e["type"] == "thought"]
    assert any("采集中断" in t and "博查账户余额不足" in t for t in thoughts), \
        "降级必须留下含真因的可见 thought"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_structured_truncation_emits_visible_degrade_once(monkeypatch):
    """LT-2 / LT-2b（brisk-pond-finch L2）：spots 与结构化双双「截断致空」时，
    全任务恰出 1 条 kind:reflect 降级 thought（共享去重）；事件协议不变
    （无新事件类型、progress 单调、done 收尾、无 error）。正常路径零误报。"""
    _install_fakes(monkeypatch)

    def fake_signals(query, destinations, focus, evidences, top_n, model, trunc_report=None):
        if trunc_report is not None:
            trunc_report.append(True)  # 模拟工作线程内「截断且产物空」求值
        return []

    monkeypatch.setattr(O, "_extract_spot_signals", fake_signals)
    real = llm.chat_json

    def wrapper(*a, **k):
        if str(k.get("purpose") or "").startswith("结构化目的地知识"):
            return None
        return real(*a, **k)

    monkeypatch.setattr(llm, "chat_json", wrapper)
    monkeypatch.setattr(llm, "last_finish_reason", lambda: "length")
    _, evs, report = _run_pipeline("guide")
    notes = [e for e in evs if e["type"] == "thought" and e["data"].get("kind") == "reflect"
             and "被截断" in (e["data"].get("text") or "")]
    assert len(notes) == 1, "两处触发点共享去重，降级提示恰一次"
    types = [e["type"] for e in evs]
    assert types[-1] == "done" and "error" not in types
    percents = [e["data"]["percent"] for e in evs if e["type"] == "progress"]
    assert percents == sorted(percents)
    assert report, "降级不崩：报告照常产出"


def test_normal_pipeline_has_no_truncation_degrade_note(monkeypatch):
    """LT-2 反例（防误报）：正常全量假 LLM（无截断）跑完，不得出现降级 thought。"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide")
    assert report and not [e for e in evs
                           if e["type"] == "thought"
                           and "被截断" in (e["data"].get("text") or "")]


# ── 组队 → 出镜者 契约（quiet-shore-pike R2）──────────────────
# 位置说明：本文件按定义顺序收集，且上方 LT-2/防误报两条对「多跑一轮完整流水线」
# 引入的 ContextVar/去重状态敏感。故新增用例一律追加在文件末尾，不插在中间。
def _node_expert(evs, node):
    """取某 DAG 节点 working 帧上的 expert（E5 外部经验：断言中间状态而非报告文本）。"""
    got = [e["data"].get("expert") for e in evs
           if e["type"] == "node_update" and e["data"].get("node") == node
           and e["data"].get("status") == "working"]
    return got[0] if got else None


def test_expert_lineup_follows_dispatch(monkeypatch):
    """节点出镜者必须来自本次组队结果，而不是文件序首位或硬编码。

    守护点：采集/分析的出镜者随 _DISPATCH_TEAM 变化。夹具里特意放进了
    L1-012 / L2-003 这两位「真实 7 轮调研从未出镜」的专家 —— 若选人逻辑退回旧的
    `startswith("L1")` 取首位，出镜者就会变回 L1-001 之类的文件序首位。
    """
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline("guide")
    assert report is not None
    assert sorted(report["experts"]) == sorted(m["id"] for m in _DISPATCH_TEAM), \
        "报告署名应等于组队结果"
    assert _node_expert(evs, "collect") == "L1-012", "采集出镜者未跟随组队（团队里首位 L1）"
    assert _node_expert(evs, "analyze") == "L2-003", "分析出镜者未跟随组队（团队里首位 L2）"
    assert report["experts"] != _LEGACY_FALLBACK_TEAM, \
        "出镜集合恒等于兜底名单，说明真组队从未生效"


@pytest.mark.xfail(strict=True, reason="quiet-shore-pike Stage B1 未实施："
                                       "auditor 的 `next(... id==\"L3-003\", \"L3-003\")` "
                                       "默认值即筛选条件，结构上永远得 L3-003，组队结果对它零影响")
def test_auditor_follows_team_not_literal(monkeypatch):
    """质检出镜者应由组队/能力解析决定，而不是被字面量钉死在 L3-003。

    注意本钉**不要求**换掉质检总监的人设（docs/AGENTS.md §3 规定 audit 由 L3
    决策层主导，这是设计意图）。它要求的是：当团队里没有 L3-003 时，出镜者应是
    解析出来的某位决策层专家，而不是悄悄用一个不在队里的 id 顶上。
    """
    _install_fakes(monkeypatch)
    _, evs, _ = _run_pipeline("guide")
    assert "L3-003" not in [m["id"] for m in _DISPATCH_TEAM]
    auditor = _node_expert(evs, "audit")
    assert auditor in [m["id"] for m in _DISPATCH_TEAM], \
        f"质检由队外专家出镜：{auditor}"


# ── 算分缺口接线（批次③ · 缺口台账端到端）────────────────────
def test_assessment_score_gap_reaches_report(monkeypatch):
    """缺口台账必须经生产接线走到报告章节，而不是只活在 builder 的局部变量里。

    夹具把 access_matrix 各 route 的 `duration_minutes`/`cost_yuan` 数值抹掉（保留
    文本 duration/cost）——「有矩阵但算不出」正是缺口的定义。**不能用健康夹具**：
    健康时 chart_gaps == []，与「接线断了、装配层拿到默认 None」的结果完全无法区分
    （`(chart_gaps or [])` 让两者都得到空集），那条测试测了等于没测。
    """
    _install_fakes(monkeypatch)
    base = llm.chat_json

    def _strip_numeric(messages, temperature=0.3, max_tokens=2048, model=None, *, purpose=""):
        payload = base(messages, temperature=temperature, max_tokens=max_tokens,
                       model=model, purpose=purpose)
        if purpose.startswith("结构化目的地知识") and "access_matrix" in purpose:
            for row in payload["access_matrix"]:
                for route in row["routes"]:
                    route.pop("duration_minutes", None)
                    route.pop("cost_yuan", None)
        return payload

    monkeypatch.setattr(llm, "chat_json", _strip_numeric, raising=False)
    _, _, report = _run_pipeline("assessment")
    assert report is not None
    secs = {s["id"]: s for s in report["sections"]}

    acc = secs["accessibility"]
    assert acc["score_gap"] == {"kind": "insufficient_input",
                                "reason": "可达性矩阵未给出「耗时/费用」数值"}, \
        "算分输入缺口未落章：builder 记录了却没有接线到装配层"
    assert not [c for c in acc["charts"] if c["type"] == "radar"], \
        "输入缺口下仍画出可达性雷达（相对分基准不存在，画出来的是编造的分数）"
    # 注意不能断言「报告里没有 radar」：分析阶段的宜居度雷达另有数据源（analysis），
    # 缺口只该影响可达性那张。这里钉的是「无源的可达性雷达不得改投别的章」。
    strays = [c for c in report["charts"]
              if c["type"] == "radar" and "accessibility" in (c.get("sections") or ())]
    assert not strays, "无源可达性雷达在报告里另找归属"

    gapped = [s["id"] for s in report["sections"] if s.get("score_gap")]
    assert gapped == ["accessibility"], f"缺口串到了别的章：{gapped}"
    # 正交性：缺口是算分输入问题，不得改写成结构状态
    assert acc["structure_status"] != "lost"
