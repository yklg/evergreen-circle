"""派生路径重放用户指定信源（计划 v3 §二 B8 · §八 TC-41/TC-42 与 TC-30 的后端半边）。

守护的契约（每条都能回溯到实现落点，判据不靠记忆）：
1. `subscriptions` 表带 `source_urls` 列，**旧库缺列时自动 ALTER**（db.py CREATE 段 + 迁移段）。
   缺这一列的后果不是报错而是"复跑悄悄少一批信源"——两次报告口径不可比而界面看不出差别。
2. `POST /api/subscriptions` 与 `POST /api/tasks` 对同一个键用**同一份**入口卫生
   （`fetcher.normalize_user_url_list`）：归一、剥凭据、超限截断且**回报**截断数。
3. 复跑＝把订阅里存的那份清单再交一次 `create_task` ⇒ `user_sources` 逐条登记为 pending 行。
4. 精修（`refine_report_pipeline`）与批注精修（`refine_section`）**不得把正文引用着的必读
   条目挤出上下文**：前者不受 `min_cred` 门槛筛掉，后者在 `[:24]` 位置截断前先重排。
5. 一页纸精炼（`generate_brief`）写回报告时不丢 `report["user_sources"]` 举证块。

判据来源：`db.py` subscriptions 建表/迁移段、`db.query_evidences` 的
`ORDER BY credibility DESC`（所以用例给**互不相同**的可信度来钉住读回顺序）、
`fetcher.canonicalize_user_url` 的归一顺序、`source_type.SOURCE_KINDS["user_supplied"].must_read`。
mock 策略沿用 test_refine_evidence.py / test_report_brief.py：patch orchestrator 与 llm 的模块
属性，不调真实 LLM；用例内嵌 asyncio.run。
运行：backend/ 下 `pytest tests/test_user_source_replay.py -q`
"""
import asyncio
import importlib
import json
import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core import llm
from app.core.pipeline.research import engine as orchestrator
from app.main import app

SUB_COLS_OLD = ("sub_id TEXT PRIMARY KEY, query TEXT, destinations TEXT, type TEXT,"
                " created_at TEXT, last_run_at TEXT, last_report_id TEXT, run_count INTEGER")


@pytest.fixture(autouse=True)
def _clean_subs():
    """conftest 的 _isolate 不清 subscriptions（历史约定），本文件逐用例自清。"""
    _wipe_reports()
    db._connect().execute("DELETE FROM subscriptions")
    db._connect().commit()
    yield
    _wipe_reports()


def _wipe_reports() -> None:
    """本文件写的报告/证据（含 user_supplied 一类）对**全表实时聚合**可见。

    不清就会污染同会话后面按绝对计数断言饼图的用例（`test_user_source_stats_and_labels`
    的 `== 1` 读到 6 就是这么来的）——按本文件的 report_id 前缀精确删，不动别人的行。
    """
    c = db._connect()
    c.execute("DELETE FROM evidences WHERE report_id LIKE 'r_replay_%'")
    c.execute("DELETE FROM reports WHERE report_id LIKE 'r_replay_%'")
    c.commit()
    db.invalidate_aggregates()


def _fake_rewrite(section, extra_context, system_prompt):
    """替换 `_rewrite_section`：记录上下文并就地标 refined，不调 LLM。"""
    section["paragraphs"] = ["重写段落"]
    section["refined"] = True
    section["absorbed_evidence_ids"] = list(extra_context.get("absorbed_evidence_ids", []))
    section["context_digest"] = extra_context.get("digest", "")
    return section


def _make_report(rid, evidence_specs):
    """evidence_specs: [(eid, source_type, credibility), ...] → 落 reports + evidences。

    credibility 必须逐条不同：`get_report` 的 evidence 由 `query_evidences` 实时覆盖，
    排序是 `credibility DESC`，同分则顺序不可依赖（位置截断类用例会被顺序噪声打红）。
    """
    evidence = [{
        "evidence_id": eid,
        "source_url": f"https://src.example/{eid}",
        "source_type": stype,
        "domain": "src.example",
        "title": f"证据 {eid}",
        "excerpt": "正文摘要内容",
        "credibility": cred,
        "collected_by": "tester",
        "destination": "目的地A",
        "captured_at": db._now(),
    } for eid, stype, cred in evidence_specs]
    db.save_report({
        "id": rid, "title": f"报告 {rid}", "subtitle": "", "query": "云南深度游",
        "destinations": ["目的地A"], "experts": [], "cover_image": "",
        "created_at": db._now(), "evidence": evidence, "claims": [], "metrics": {},
        "sections": [{"id": "s1", "title": "核心判断", "paragraphs": ["原段落"], "refined": False}],
    }, task_id="")
    return evidence


def _gov_specs(count: int, top_cred: int = 200) -> list:
    """count 条检索证据，可信度互不相同且**递减**（读回顺序 == 传入顺序）。"""
    return [(f"e_{i:02d}", "gov", float(top_cred - i)) for i in range(count)]


def _drain(gen):
    out = []
    asyncio.run(_collect(gen, out))
    return out


async def _collect(gen, out):
    async for ev in gen:
        out.append(ev)


# ── 1. 订阅存清单：单元层 round-trip ────────────────────────────
def test_subscription_roundtrips_its_source_list():
    urls = ["https://www.gov.cn/a", "https://news.example.com/b"]
    sub = db.create_subscription("sub_list", "云南深度游", ["大理"], "guide", source_urls=urls)
    assert sub["source_urls"] == urls
    assert db.get_subscription("sub_list")["source_urls"] == urls
    assert db.list_subscriptions()[0]["source_urls"] == urls


def test_subscription_without_list_reads_empty_not_none():
    """未填清单 ⇒ 空清单（语义是「这条订阅没填过」），不得是 None：
    前端拿 None 做 `sub.source_urls.length` 会当场崩，复跑也没法区分「没填」与「读失败」。"""
    sub = db.create_subscription("sub_none", "云南深度游", ["大理"])
    assert sub["source_urls"] == []
    sub2 = db.create_subscription("sub_explicit_empty", "云南深度游", ["大理"], source_urls=[])
    assert sub2["source_urls"] == []


# ── 2. 旧库补列（TC-41）────────────────────────────────────────
def test_old_subscription_db_gets_the_column_and_existing_rows_read_empty():
    """旧 schema 库文件（无 source_urls 列）启动 ⇒ 列自动补上、旧行读为空清单、不报错。

    期望值来源：db.py 的 `PRAGMA table_info(subscriptions)` 迁移段。这条若红，说明复跑
    会在存量库上静默丢清单 —— 建表语句改对但迁移漏掉，正是最容易漏的一半。
    """
    fresh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fresh.close()
    saved = os.environ.get("VERDA_DB_PATH")
    conn = sqlite3.connect(fresh.name)
    conn.execute(f"CREATE TABLE subscriptions ({SUB_COLS_OLD})")
    conn.execute(
        "INSERT INTO subscriptions(sub_id,query,destinations,type,created_at,"
        "last_run_at,last_report_id,run_count) VALUES(?,?,?,?,?,?,?,?)",
        ("s_old", "旧订阅", '["大理"]', "guide", "2026-09-01T00:00:00", "", "", 3))
    conn.commit()
    conn.close()
    os.environ["VERDA_DB_PATH"] = fresh.name
    try:
        importlib.reload(db)
        cols = [r[1] for r in db._connect().execute("PRAGMA table_info(subscriptions)").fetchall()]
        assert "source_urls" in cols, "旧库未补 source_urls 列 ⇒ 复跑会静默丢清单"
        got = db.get_subscription("s_old")
        assert got["source_urls"] == []          # 旧行 NULL ⇒ 空清单，不是 None
        assert got["query"] == "旧订阅"           # 旧数据仍可读
        assert got["destinations"] == ["大理"]
        db._init_schema(db._connect())           # 幂等：再跑一次迁移不得报错、不得改数据
        assert db.get_subscription("s_old")["source_urls"] == []
        assert db.get_subscription("s_old")["run_count"] == 3
    finally:
        os.environ["VERDA_DB_PATH"] = saved
        importlib.reload(db)
        try:
            os.unlink(fresh.name)
        except OSError:
            pass


# ── 3. 端点入口卫生：与 POST /api/tasks 同键同形状 ───────────────
def test_post_subscription_normalizes_and_strips_credentials():
    cli = TestClient(app)
    r = cli.post("/api/subscriptions", json={
        "query": "云南深度游", "destinations": ["大理"],
        "source_urls": ["gov.cn/doc", "http://user:pass@news.example.com/a#sec", "  ",
                        "https://gov.cn/doc"],
    })
    assert r.status_code == 200
    accepted = r.json()["sourceUrls"]["accepted"]
    # 判据逐条对应 canonicalize_user_url 的归一顺序：补协议 / 剥凭据 / 去 fragment / 归一后去重
    assert accepted == ["https://gov.cn/doc", "http://news.example.com/a"], accepted
    assert "pass" not in json.dumps(accepted, ensure_ascii=False), \
        "凭据进了订阅清单 ⇒ 复跑每次都会把它带进任务与渲染出的链接"
    assert r.json()["sourceUrls"]["truncated"] == 0
    assert r.json()["source_urls"] == accepted, "存的必须就是归一后的那份，不是原始输入"


def test_post_subscription_over_cap_reports_the_truncation_instead_of_dropping_silently():
    """11 条唯一网址 ⇒ 存 10 条且**回报** truncated=1（与任务入口同一口径）。"""
    cli = TestClient(app)
    urls = [f"https://a.example/{i}" for i in range(11)]
    r = cli.post("/api/subscriptions", json={"query": "q", "destinations": ["大理"],
                                             "source_urls": urls})
    body = r.json()
    assert len(body["source_urls"]) == 10
    assert body["sourceUrls"]["truncated"] == 1
    assert body["source_urls"] == urls[:10]


def test_post_subscription_response_shape_unchanged_when_no_list():
    """不填清单 ⇒ 响应里不出现 sourceUrls 键（改前形状逐键不变，计划 §四.2 零回归基线）。"""
    cli = TestClient(app)
    r = cli.post("/api/subscriptions", json={"query": "q", "destinations": ["大理"]})
    assert "sourceUrls" not in r.json()
    assert r.json()["source_urls"] == []


# ── 4. 复跑重放：订阅清单交回 create_task ⇒ 实例行逐条落地 ────────
def test_rerun_replays_the_stored_list_into_task_instance_rows():
    sub = db.create_subscription("sub_rerun", "云南深度游", ["大理"], "guide",
                                 source_urls=["https://www.gov.cn/a", "https://b.example/c"])
    stored = sub["source_urls"]

    tid = orchestrator.create_task("云南深度游", research_type="guide",
                                   source_urls=stored)["taskId"]
    rows = db.list_user_sources(tid)
    assert [r["url_canonical"] for r in rows] == stored
    assert [r["seq"] for r in rows] == [0, 1]
    assert all(r["fetch_state"] == "pending" for r in rows), \
        "复跑登记后必须是待抓态：抓取的唯一写点是 collect，不能在建任务时就假装读过"


def test_rerun_without_the_list_produces_no_rows_and_the_guarantee_is_not_tautological():
    """反证配对：不带清单 ⇒ 零行。没有这条，上一条可能只是在测「无论如何都有行」的废机制。"""
    tid = orchestrator.create_task("云南深度游", research_type="guide")["taskId"]
    assert db.list_user_sources(tid) == []


# ── 5. 精修不丢必读（min_cred 不得筛掉正文引用着的用户文档）────────
def test_refine_keeps_must_read_evidence_below_the_credibility_bar(monkeypatch):
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _make_report("r_replay_1", [
        ("e_user_low", "user_supplied", 20.0),   # 用户钉的文档，可信度低于门槛
        ("e_search_low", "gov", 20.0),           # 门槛之外的低分检索证据，仍应被筛掉
        ("e_search_hi", "gov", 90.0),
    ])

    tid = orchestrator.create_refine_task("r_replay_1", None, 70)["taskId"]
    _drain(orchestrator.refine_report_pipeline(tid))

    sec = db.get_report("r_replay_1")["sections"][0]
    assert "e_user_low" in sec["absorbed_evidence_ids"], \
        "必读条目被 min_cred 挤出池 ⇒ 改写后的段落引用着上下文里看不见的信源（悬空引用）"
    assert "e_search_low" not in sec["absorbed_evidence_ids"], \
        "门槛只对必读类别失效；把它放宽成「全部保留」就是拿零回归换省事"
    assert "e_search_hi" in sec["absorbed_evidence_ids"]
    assert "e_user_low" in sec["context_digest"]


def test_refine_reports_error_when_there_is_nothing_at_all(monkeypatch):
    """边界：低分普通证据被筛完后池空 ⇒ 仍走 error 事件（不能因新分支变成静默空改写）。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _make_report("r_replay_2", [("e_search_only", "gov", 10.0)])
    tid = orchestrator.create_refine_task("r_replay_2", None, 70)["taskId"]
    events = _drain(orchestrator.refine_report_pipeline(tid))
    assert any(e["type"] == "error" for e in events)
    assert not db.get_report("r_replay_2")["sections"][0].get("refined")


def test_refine_keeps_the_explicit_subset_when_the_user_checks_ids(monkeypatch):
    """用户显式勾选 evidence_ids 时仍然生效：必读豁免不等于「无视勾选」。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _make_report("r_replay_6", [
        ("e_user_a", "user_supplied", 90.0),
        ("e_user_b", "user_supplied", 80.0),
    ])
    tid = orchestrator.create_refine_task("r_replay_6", ["e_user_a"], 70)["taskId"]
    _drain(orchestrator.refine_report_pipeline(tid))
    ids = db.get_report("r_replay_6")["sections"][0]["absorbed_evidence_ids"]
    assert ids == ["e_user_a"], "勾选是用户主动缩小的范围，必读豁免不能把它放大回去"


def test_refine_section_annotation_reorders_before_the_position_cut(monkeypatch):
    """批注精修按 `evidence[:24]` 截断：读回顺序里排在第 30 位的必读条目必须先排位。

    这是 A-1（「覆盖率测的是列表顺序」）在派生路径上的同型缺口 —— 主流水线的保留槽修好了，
    改稿这一步没修，用户就会看到「正文引用着、精修后却丢了」。
    """
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    specs = _gov_specs(29)
    specs.append(("e_pinned_tail", "user_supplied", 1.0))   # 最低分 ⇒ 自然顺序里在末尾
    _make_report("r_replay_3", specs)

    orchestrator.refine_section("r_replay_3", "s1", ["再写深一点"])
    sec = db.get_report("r_replay_3")["sections"][0]
    assert "e_pinned_tail" in sec["absorbed_evidence_ids"]
    assert "e_pinned_tail" in sec["context_digest"]
    assert sec["absorbed_evidence_ids"][0] == "e_pinned_tail", \
        "必读条目必须排在最前，否则 [:24] 的位置截断照旧把它挤出"
    assert "e_24" not in sec["absorbed_evidence_ids"], "加必读不等于把截断整体放宽"


def test_refine_section_without_must_read_keeps_the_positional_cut(monkeypatch):
    """零回归：没有必读条目时按原序截断，第 25 位仍然进不了上下文。"""
    monkeypatch.setattr(orchestrator, "_rewrite_section", _fake_rewrite, raising=False)
    _make_report("r_replay_4", _gov_specs(26))
    orchestrator.refine_section("r_replay_4", "s1", ["再写深一点"])
    ids = db.get_report("r_replay_4")["sections"][0]["absorbed_evidence_ids"]
    assert ids == [f"e_{i:02d}" for i in range(24)]
    assert "e_25" not in ids


# ── 6. 一页纸精炼写回不丢举证块 ────────────────────────────────
def test_brief_writeback_keeps_the_user_sources_block(monkeypatch):
    """`generate_brief` 会重读报告并 `save_report` 落 brief ⇒ 同一次写回不得丢掉
    `report["user_sources"]`，否则生成一页纸之后，报告上「用户指定 N · 已引用 M」那块就消失了。"""
    def _fake(messages, **kwargs):
        return {"summary": "一句话", "judgments": ["判断1"], "key_data": ["数据1"],
                "actions": ["建议1"]}

    monkeypatch.setattr(llm, "chat_json", _fake)
    _make_report("r_replay_5", [("e_user", "user_supplied", 90.0)])
    rep = db.get_report("r_replay_5")
    block = {"label": "用户指定", "summary": {"total": 1, "cited": 1},
             "items": [{"url": "https://www.gov.cn/a"}], "note": "口径说明"}
    rep["user_sources"] = block
    db.save_report(rep, task_id="")

    brief = orchestrator.generate_brief("r_replay_5")
    assert brief and brief["summary"] == "一句话"
    after = db.get_report("r_replay_5")
    assert after["brief"] == brief
    assert after["user_sources"] == block, "精炼写回丢了这个块 ⇒ 报告不再举证读了哪些用户网址"
