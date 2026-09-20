"""目的地调研流水线 `app.core.pipeline.research`（计划 §3.1/§3.4，对齐源项目增强）。

TDD 目标规格：本文件 import `app.core.pipeline.research`（实现前 collection 报错标识未落地，落地后转绿）。
通过 stub 各内部阶段（_plan_destination/_collect_batches/_sentiment/_write_sections/
_dispatch_destination/_audit_review），让真实 _assemble_report 与审计(write)运行，从而对
**事件契约 + 落库报告不变量**做黑盒断言：
- F1 成功流以 done 收尾、全流无 error、report_ready 带报告 id；
- F2 阶段节点 id 合法、progress 单调；
- C1 报告 brands==[]、sections 非空、claims.evidence_ids⊆evidence、含 metrics/confidence、无竞品键；
- C2 无舆情数据时 sentiment 字段可空安全；
- D6 舆情聚合写入 report.sentiment、口碑/舆情章由 READY_PROFILES 定位；
- G* 展示事件契约（thought/message(team)/audit_review/evidence/node_update 数组/状态契约/建队校验）。

运行：backend/ 下 `pytest tests/test_research_pipeline.py -q`。
"""
import asyncio
import os
import pathlib
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["VERDA_DB_PATH"] = _TMP.name

from app.core import db, runner
from app.core.pipeline import research

RESEARCH_NODE_IDS = {"intake", "orchestrator", "collect", "sentiment", "write", "audit", "done"}


def _conn():
    return db._connect()


def _insert_task(task_id, purpose="guide", kind="travel_guide"):
    _conn().execute(
        "INSERT INTO tasks(task_id,query,clarifications,status,created_at,kind,purpose)"
        " VALUES(?,?,?,?,?,?,?)",
        (task_id, "黄山", "{}", "created", db._now(), kind, purpose),
    )
    _conn().commit()


def _evidence(text, eid, url=None):
    _url = url or f"https://x/{eid}"
    # 与真实 _Collector 证据 schema 同构（source_url 为前端证据库渲染所需）
    return {"evidence_id": eid, "url": _url, "source_url": _url, "credibility": 0.6,
            "title": text[:10], "text": text, "appraisal": "neutral", "source_type": "web",
            "domain": "x", "source_group": f"g_{eid}"}


def _section(sid, title, body):
    return {"id": sid, "title": title, "paragraphs": [body],
            "key_takeaway": title, "highlights": [body[:20]]}


_DEFAULT_SENT = object()  # 哨兵：未指定 → 默认带舆情；显式 None → 舆情缺席


def _stub_stages(monkeypatch, *, sentiment=_DEFAULT_SENT, plans=None, angles=None):
    """桩掉网络/LLM 阶段，保留真实 _assemble_report 与审计。"""
    def _plan(task_id):
        return {"subject": "黄山", "purpose": "guide",
                "angles": angles or ["交通与票务", "餐饮住宿"]}
    async def _collect(task_id, subject, angles, batch_size=3):
        # 分两批产出（对应两个角度），验证 collect 阶段进度逐批攀升
        yield ["交通与票务"], [_evidence("实测缆车要排队两小时", "e_collect_1")]
        yield ["餐饮住宿"], [_evidence("官方公众号今日出行提示", "e_collect_2")]
    async def _wri(task_id, subject, angles, evidences, purpose):
        yield _section("guide_overview", "概览", "黄山概况")
        yield _section("guide_voice", "口碑与评价", "游客普遍好评，排队是主要槽点")
    async def _sent(task_id, evidences, subject):
        if sentiment is _DEFAULT_SENT:
            return {"topic": subject, "positive": 8, "neutral": 2, "negative": 1,
                    "themes": ["缆车"], "quotes": [{"evidence_id": "e_collect_1", "text": "实测缆车要排队两小时"}]}
        return sentiment  # 显式传 None → 舆情缺席；传 dict → 直接回填
    def _dispatch(subject, angles, purpose):
        return (["L3-001", "L3-002", "L1-003"],
                ["领队统筹推进", "口碑与游客评价取证", "路线与错峰取证"])
    async def _audit(subject, purpose, angles, evidences):
        return {"verdict": "pass", "scores": {"证据充分性": 72, "维度完整性": 68},
                "review": "证据较充分，结论可信。", "issues": [], "suggestions": []}
    monkeypatch.setattr(research, "_plan_destination", _plan, raising=False)
    monkeypatch.setattr(research, "_collect_batches", _collect, raising=False)
    monkeypatch.setattr(research, "_sentiment", _sent, raising=False)
    monkeypatch.setattr(research, "_write_sections", _wri, raising=False)
    monkeypatch.setattr(research, "_dispatch_destination", _dispatch, raising=False)
    monkeypatch.setattr(research, "_audit_review", _audit, raising=False)


async def _scenario(task_id):
    out = []
    async for e in runner.subscribe(task_id):
        out.append(e)
    return out, db.get_report(db.get_task_full(task_id).get("report_id"))


def _run(task_id):
    return asyncio.run(_scenario(task_id))


# ── F1 / F2：事件契约 ───────────────────────────────────
def test_success_stream_done_no_error(monkeypatch):
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_rp_ok")
    events, rep = _run("t_rp_ok")
    types = [e["type"] for e in events]
    assert types[-1] == "done", "成功流须以 done 收尾"
    assert "error" not in types, "成功流不得出现 error"


def test_stage_nodes_role_and_monotonic_progress(monkeypatch):
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_rp_nodes")
    events, _ = _run("t_rp_nodes")
    # node_update 双形均须合法：数组事件的 nodes[].id 与单节点事件的 id
    node_ids: set = set()
    for e in events:
        if e["type"] != "node_update":
            continue
        if isinstance(e["data"].get("nodes"), list):
            node_ids |= {n.get("id") for n in e["data"]["nodes"] if isinstance(n, dict)}
        elif e["data"].get("id"):
            node_ids.add(e["data"]["id"])
    assert node_ids and node_ids <= RESEARCH_NODE_IDS, "节点 id 须来自 deadline 的 RESEARCH_NODES"
    progs = [e["data"]["percent"] for e in events if e["type"] == "progress"]
    assert progs == sorted(progs), "progress 单调不回落"


# ── C1 / C2 / D6：落库报告不变量 ─────────────────────────
def test_report_brands_empty_and_no_competitor_keys(monkeypatch):
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_rp_c1", purpose="guide")
    _, rep = _run("t_rp_c1")
    assert rep["brands"] == [], "travel 报告 brands 必须为空"
    assert rep.get("sections") and all(s.get("paragraphs") for s in rep["sections"]), "章节非空"
    claim_ids = {c["evidence_id"] for c in rep.get("claims", [])}
    evidence_ids = {e["evidence_id"] for e in rep.get("evidence", [])}
    assert claim_ids <= (evidence_ids or {""}), "claims 必须回溯到证据"
    assert "metrics" in rep and "confidence" in rep
    for comp in ("comparison", "market_share", "five_forces"):
        assert comp not in rep, f"不得残留竞品键: {comp}"


def test_sentiment_absent_is_null_safe(monkeypatch):
    runner._running.clear()
    _stub_stages(monkeypatch, sentiment=None)
    _insert_task("t_rp_c2", purpose="assess")
    _, rep = _run("t_rp_c2")
    assert rep.get("sentiment") in (None, {}), "无舆情时 sentiment 应可空安全"


def test_aggregated_sentiment_written_and_voice_section(monkeypatch):
    runner._running.clear()
    _stub_stages(monkeypatch)  # 默认带舆情
    _insert_task("t_rp_d6", purpose="guide")
    _, rep = _run("t_rp_d6")
    assert rep.get("sentiment", {}).get("positive") == 8, "舆情聚合应写入 report.sentiment"
    section_ids = {s["id"] for s in rep.get("sections", [])}
    assert "guide_voice" in section_ids, "口碑/舆情章应出现在攻略报告"


def test_collect_and_write_progress_incremental(monkeypatch):
    """增量进度契约：collect 至少两批、write 至少两章，且全程 percent 单调不回落。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_rp_inc")
    events, _ = _run("t_rp_inc")
    coll = [e["data"]["percent"] for e in events
            if e["type"] == "progress" and e["data"]["stage"] == "collect"]
    wr = [e["data"]["percent"] for e in events
          if e["type"] == "progress" and e["data"]["stage"] == "write"]
    assert len(coll) >= 2, "collect 应按角度分批推进度"
    assert list(coll) == sorted(coll) and coll[-1] >= coll[0], "collect 进度须单调攀升"
    assert len(wr) >= 2, "write 应按章节分批推进度"
    assert list(wr) == sorted(wr), "write 进度须单调攀升"
    allp = [e["data"]["percent"] for e in events if e["type"] == "progress"]
    assert allp == sorted(allp), "全程 progress 不可掉头"


def test_section_claims_mapped_and_linked(monkeypatch):
    """claims→章节：sections[i].claims 命中对应章节，evidence_ids 全部回溯到证据。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_rp_sc", purpose="guide")
    _, rep = _run("t_rp_sc")
    evidence_ids = {e["evidence_id"] for e in rep.get("evidence", [])}
    all_claims = [c for s in rep.get("sections", []) for c in s.get("claims", [])]
    assert all_claims, "至少部分章节应带 claims 卡片"
    assert all(c["confidence"] in ("high", "medium", "low") for c in all_claims)
    assert all(c["text"] and c["evidence_ids"] for c in all_claims), "卡片须含文本与证据引用"
    for c in all_claims:
        assert set(c["evidence_ids"]) <= (evidence_ids or {""}), "卡片 evidence_ids 必须回溯到证据"
    assert len(all_claims) == len(rep.get("evidence", [])), "每条证据应映射为一张结论卡"


# ── G1 / G2 / G3 / G4 / G5：展示事件契约（同构修复守卫）──────────────────
# 注：以下用例定义「修复后」目标契约，与真实流水线事件发射解耦（经 stub 阶段运行）。
# 在展示事件层落地前为红（TDD led），发射层落地后转绿。

def test_g1_real_flow_emits_rich_display_events(monkeypatch):
    """G1 同构：真实成功流须含 thought / message(team) / evidence / node_update 数组。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g1_disp")
    events, _ = _run("t_g1_disp")
    types = [e["type"] for e in events]
    for t in ("thought", "message", "evidence"):
        assert t in types, f"成功流缺展示事件 {t}"
    arrays = [e for e in events
              if e["type"] == "node_update" and isinstance(e["data"].get("nodes"), list)]
    assert arrays, "须至少一个 node_update 数组（权威节点集）"


def test_g3_thought_field_schema(monkeypatch):
    """G3 thought 字段 schema：id/kind/expert/text/ts 齐全。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g3_thought")
    events, _ = _run("t_g3_thought")
    thoughts = [e["data"] for e in events if e["type"] == "thought"]
    assert thoughts, "成功流须发 thought"
    for th in thoughts:
        for f in ("id", "kind", "expert", "text", "ts"):
            assert f in th, f"thought 缺字段 {f}"


def test_g4_team_message_members_nonempty(monkeypatch):
    """G4 message(team)：kind=team 且 members 非空（专家队可渲染）。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g4_team")
    events, _ = _run("t_g4_team")
    teams = [e["data"] for e in events
             if e["type"] == "message" and e["data"].get("kind") == "team"]
    assert teams, "成功流须发 message(team)"
    assert teams[0].get("members"), "message(team) 须带非空 members"


def test_g5_evidence_field_schema(monkeypatch):
    """G5 evidence schema：evidence_id/source_url/credibility/title 齐全。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g5_evi")
    events, _ = _run("t_g5_evi")
    evs = [e["data"] for e in events if e["type"] == "evidence"]
    assert evs, "成功流须发 evidence"
    for ev in evs:
        for f in ("evidence_id", "source_url", "credibility", "title"):
            assert f in ev, f"evidence 缺字段 {f}"


def test_g2_single_node_domain_subset_of_array(monkeypatch):
    """G2-数组域：单节点更新 id ⊆ node_update 数组 id（防 DAG 静默停滞）。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g2_domain")
    events, _ = _run("t_g2_domain")
    array_ids: set = set()
    for e in events:
        if e["type"] == "node_update" and isinstance(e["data"].get("nodes"), list):
            for n in e["data"]["nodes"]:
                if isinstance(n, dict) and n.get("id"):
                    array_ids.add(n["id"])
    single_ids = {e["data"]["id"] for e in events
                  if e["type"] == "node_update" and e["data"].get("id")}
    assert single_ids and single_ids <= array_ids, (
        "单节点更新 id 须 ⊆ 数组 id，否则对应 DAG 动画会被静默丢弃")


def test_g2_stages_mirror_demo_no_analyze():
    """G2-同构守卫：RESEARCH_NODES 与前端演示 STAGES 镜像一致，且无 analyze。"""
    ids = [i for i, _ in research.RESEARCH_NODES]
    assert ids == ["intake", "orchestrator", "collect", "sentiment", "write", "audit", "done"], (
        "RESEARCH_NODES 须与演示 STAGES 镜像一致（含 sentiment、无 analyze）")
    assert "sentiment" in ids and "analyze" not in ids


# ── 增强新契约（对齐源项目：动态建队／多轮节奏／多平台舆情／中性质检／状态契约/架构守卫）──────
def test_g6_audit_review_message_emitted(monkeypatch):
    """质检：成功流须发 message(kind=audit_review)，报告落 audit_review/quality_before。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g6_audit")
    events, rep = _run("t_g6_audit")
    reviews = [e["data"] for e in events
               if e["type"] == "message" and e["data"].get("kind") == "audit_review"]
    assert reviews, "成功流须发 message(audit_review)"
    assert "verdict" in reviews[0].get("audit", {}), "audit_review 须带 verdict"
    assert rep.get("audit_review"), "报告须落 audit_review"
    assert rep.get("quality_before"), "报告须落 quality_before"


def test_g7_team_message_dispatch_and_roster_valid(monkeypatch):
    """建队：message(team) 带 dispatch reasons，且 members 均为名册有效 id（幻觉 id 被过滤）。"""
    monkeypatch.setattr(research, "_roster_index", lambda: {
        "L3-001": {"id": "L3-001", "role": "领队"},
        "L3-002": {"id": "L3-002", "role": "口碑分析师"},
        "L1-003": {"id": "L1-003", "role": "路线策划"},
    })
    monkeypatch.setattr(research, "chat_json", lambda *a, **k: {
        "team": [{"id": "L3-001", "reason": "领队统筹"},
                 {"id": "GHOST-X", "reason": "幻觉专家"},   # 不在名册 → 须被过滤
                 {"id": "L1-003", "reason": "路线与错峰取证"}]})
    ids, reasons = research._dispatch_destination("黄山", ["线路"], "guide")
    assert "GHOST-X" not in ids, "幻觉/无效专家 id 必须被过滤"
    assert len(ids) >= 2 and len(ids) == len(reasons)
    assert all(i in {"L3-001", "L3-002", "L1-003"} for i in ids), "成员须限定在名册内"
    # 领队优先：L3 级应排在首位
    assert ids[0].startswith("L3"), "领队（L3）应排在专家队首位"


def test_g8_collect_multi_batch_rhythm(monkeypatch):
    """多轮节奏：collect 阶段出现多个 action 与 finding thought（逐批叙事），进度逐批攀升。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g8_rhythm")
    events, _ = _run("t_g8_rhythm")
    actions = [e["data"] for e in events
               if e["type"] == "thought" and e["data"].get("kind") == "action"]
    findings = [e["data"] for e in events
                if e["type"] == "thought" and e["data"].get("kind") == "finding"]
    assert len(actions) >= 2, "collect 应分多批（每批一条 action 叙事）"
    assert len(findings) >= 2, "collect 应逐批产出 finding 叙事"
    assert any("批" in e["data"].get("text", "") for e in events
               if e["type"] == "thought" and e["data"].get("kind") == "action")


def test_g9_node_status_contract(monkeypatch):
    """状态契约：所有单节点 node_update 的 status ∈ {working,done,rework,idle}（前端 taskStore 依赖 working/done）。"""
    runner._running.clear()
    _stub_stages(monkeypatch)
    _insert_task("t_g9_status")
    events, _ = _run("t_g9_status")
    statuses = {e["data"].get("status") for e in events
                if e["type"] == "node_update" and e["data"].get("id")
                and not isinstance(e["data"].get("nodes"), list)}
    assert statuses and statuses <= {"working", "done", "rework", "idle"}, (
        f"node_update 状态须为前端契约取值，实际: {statuses}")
    assert "working" in statuses and "done" in statuses, "既要有 working（判活）也要有 done（打勾）"


def test_g10_sentiment_neutral_no_brand_key(monkeypatch):
    """中性守卫：_sentiment 产出 platform 不引入品牌型 analyze_sentiment；fixture 模式 platform=None（离线零网络）。"""
    _insert_task("t_g10_fx", purpose="guide")
    async def _call():
        return await research._sentiment("t_g10_fx", [_evidence("官方提示预约", "e1")], "黄山")
    res = asyncio.run(_call())
    assert res and res.get("platform") is None, "fixture(离线) 不得发起平台检索"
    assert set(res) >= {"topic", "positive", "neutral", "negative", "themes", "quotes", "platform"}


def test_g11_audit_neutral_review(monkeypatch):
    """质检：中性审阅走 evaluate_quality 规则侧 + 目的地中立 LLM，不含竞品/brand 措辞。"""
    def _fake_chat_json(*a, **k):
        return {"verdict": "pass", "scores": {"证据充分性": 80, "维度完整性": 75, "结论置信度": 70},
                "review": "检索覆盖较全，结论有证据支撑。", "issues": [], "suggestions": ["补充官方信源"]}
    monkeypatch.setattr(research, "chat_json", _fake_chat_json)
    evs = [_evidence("官方发布预约与安全提示", "e_a1")]
    res = asyncio.run(research._audit_review("黄山", "guide", ["交通"], evs))
    assert res.get("verdict") in ("pass", "rework")
    assert set(res) >= {"verdict", "scores", "review", "issues", "suggestions"}
    assert all("brand" not in str(k).lower() and "竞争" not in str(k)
               for k in res.get("scores", {})), "质检维度须为中性（无竞品维度）"


def test_arch_guard_research_not_import_orchestrator():
    """架构守卫：research.py 不得 import orchestrator 编排，也不得 import 品牌型 analyze_sentiment。"""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    for tok in ["from app.core.orchestrator import", "_collect_brand", "_dispatch_experts"]:
        assert tok not in src, f"research.py 禁止出现竞品编排符号: {tok}"
    # 仅检查 import 语句：注释/文档允许解释性提及，但不允许实际导入品牌型 analyzer
    import_lines = [ln for ln in src.splitlines()
                    if ln.lstrip().startswith(("import ", "from "))]
    assert not any("analyze_sentiment" in ln for ln in import_lines), (
        "research.py 不得 import 品牌型 analyze_sentiment（保持中性聚合）")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))