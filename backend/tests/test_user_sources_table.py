"""`user_sources` 实例表（实施计划 v3 §二 U0 · §八 TC-22 / TC-41 / ST-01）。

守护的契约
----------
用户手填的网址在这里是**业务数据**（参与覆盖率计算、写作入池、派生路径重放），
不是偏好 blob。因此它有一张自己的表，与 prefs（用户偏好）语义分工明确：
prefs 存"下次默认引用哪几条"，本表存"这一次任务里这几条网址各自走到哪一步"。

本文件钉四件事，判据来源逐条标注：
  1. **建表走既有初始化路径**（`db._init_schema` 的 `CREATE TABLE IF NOT EXISTS`），
     存量库文件上加表、旧数据仍可读（TC-41，形状照 `test_db_migration.py:214-243`）。
  2. **新表已登记进测试隔离清理**（TC-22）：`conftest._isolate` 不补 `clear_user_sources()`
     的话，第二条用例就会读到第一条用例留下的行 —— 跨用例污染是这个形状。
  3. **`fetch_state` 的词表是契约**：非法状态名与未知列名必须**当场抛错**。
     静默写入一个拼错的态，它既不进覆盖率分子也不进分母，那条网址就"消失了"
     （计划 §四.6 要求报告里"用户指定 N · 已引用 M · 未读取 K…" 各态可清点）。
  4. **删除报告不留孤儿行**：本表按 `task_id` 归属而级联清单按 `report_id`
     （`db._REPORT_SCOPED_TABLES`），所以 `_delete_report_scoped_rows` 必须先查 task_id。
     这条不是洁癖：孤儿行会被 `evidence_facets` 之外的口径重复计入。

`kind` 的期望值不手写：取自 `app.core.source_type` 注册表的 key 集，
注册表里没有的类别一律视为脏数据。
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

import app.core.db as db
from app.core import source_type as ST

TASK = "t-us-01"

# 记录"前一条用例写过哪些 uid"，供下一条用例验证 autouse 夹具真的清了表。
_SEEN_BY_PREVIOUS_CASE: list[str] = []


# ── 1. 建表与基本读写（走生产写路径，不手写 SQL）──────────────────

def test_table_exists_after_normal_init():
    """正常启动路径下表必须已在（不手工建表、不跑迁移脚本）。"""
    cols = [r[1] for r in db._connect().execute("PRAGMA table_info(user_sources)").fetchall()]
    assert cols, "user_sources 表不存在 —— _init_schema 的 CREATE 段没生效"
    assert {"uid", "task_id", "seq", "url", "url_canonical", "kind", "fetch_state",
            "evidence_id", "group_id", "cited_by", "attempt_reason",
            "bytes", "ms", "updated_at"} <= set(cols), f"列缺失：{cols}"


def test_add_then_list_orders_by_seq():
    """报告界面要显示「正在读取第 k/N 条」⇒ 读取顺序必须等于用户填入顺序，不是 uid 序。"""
    for i, u in enumerate(["https://b.gov.cn/a", "https://a.gov.cn/b", "https://c.gov.cn/c"]):
        db.add_user_source(TASK, u, u, i)
    rows = db.list_user_sources(TASK)
    assert [r["seq"] for r in rows] == [0, 1, 2], f"顺序被打乱：{[(r['seq'], r['uid']) for r in rows]}"
    assert [r["url"] for r in rows] == ["https://b.gov.cn/a", "https://a.gov.cn/b", "https://c.gov.cn/c"]


def test_new_rows_start_as_pending_with_registered_kind():
    """登记态的初值必须是 pending，且 kind 落在注册表里（不手写合法类别清单）。"""
    db.add_user_source(TASK, "https://p.gov.cn/1", "https://p.gov.cn/1", 0)
    db.add_user_source(TASK, "https://p.gov.cn/2", "https://p.gov.cn/2", 1)
    rows = db.list_user_sources(TASK)
    assert rows, "写入后读不到行"
    assert {r["fetch_state"] for r in rows} == {"pending"}
    assert {r["kind"] for r in rows} == {"user_supplied"}
    # kind 的合法集来自注册表，不来自本文件的字面量
    assert {r["kind"] for r in rows} <= set(ST.SOURCE_KINDS), (
        f"写进了注册表没有的类别：{ {r['kind'] for r in rows} - set(ST.SOURCE_KINDS) }"
    )


def test_uid_is_deterministic_so_re_registering_is_idempotent():
    """复跑/重放会再次登记同一份清单 ⇒ 同 (任务, 归一化网址) 必须落回同一行。

    幂等失效的后果不是"多一行"，而是覆盖率分母按重复计数虚高。
    """
    first = db.add_user_source(TASK, "https://dup.gov.cn/x", "https://dup.gov.cn/x", 9)
    again = db.add_user_source(TASK, "https://dup.gov.cn/x", "https://dup.gov.cn/x", 9)
    assert first == again
    assert sum(1 for r in db.list_user_sources(TASK) if r["url_canonical"] == "https://dup.gov.cn/x") == 1


def test_canonical_form_is_what_dedupes_not_the_raw_string():
    """`/a` 与 `/a ` 这类同址异写必须归到一行：归一化在入口层（B1）做完，本表只认 url_canonical。"""
    u1 = db.add_user_source(TASK, "https://x.gov.cn/a", "https://x.gov.cn/a", 20)
    u2 = db.add_user_source(TASK, "HTTPS://X.GOV.CN/a", "https://x.gov.cn/a", 21)
    assert u1 == u2, "归一化网址相同却建了两行 ⇒ 覆盖率把一条网址算成两条"


# ── 2. 状态机词表（ST-01 的"非法值必被拒"这一半；非法跳转的驱动用例待 B2）──

def test_update_accepts_declared_states_and_records_reason():
    uid = db.add_user_source(TASK, "https://s.gov.cn/1", "https://s.gov.cn/1", 30)
    db.update_user_source(uid, fetch_state="fetched", evidence_id="e_1",
                          group_id="g_1", bytes=2048, ms=310)
    row = [r for r in db.list_user_sources(TASK) if r["uid"] == uid][0]
    assert row["fetch_state"] == "fetched"
    assert (row["evidence_id"], row["group_id"], row["bytes"], row["ms"]) == ("e_1", "g_1", 2048, 310)
    db.update_user_source(uid, fetch_state="unread", attempt_reason="HTTP 404")
    row = [r for r in db.list_user_sources(TASK) if r["uid"] == uid][0]
    assert row["fetch_state"] == "unread" and row["attempt_reason"] == "HTTP 404"


@pytest.mark.parametrize("bad_state", ["fail", "Pending", "", "blocked_by_firewall", "cited "])
def test_unknown_fetch_state_is_rejected_not_silently_stored(bad_state):
    """拼错的状态名必须当场炸。

    静默入库的话这条网址在 `{total, cited, uncited, unread, gated_off_query, merged}`
    的清点里两边都不出现 ⇒ 计划 §八 INV-01 的"分母恒等"直接破，而且没人报错。
    """
    uid = db.add_user_source(TASK, f"https://n.gov.cn/{bad_state.strip() or 'x'}", f"https://n.gov.cn/{bad_state.strip() or 'x'}", 40)
    with pytest.raises(ValueError):
        db.update_user_source(uid, fetch_state=bad_state)


def test_unknown_column_is_rejected():
    uid = db.add_user_source(TASK, "https://c.gov.cn/1", "https://c.gov.cn/1", 41)
    with pytest.raises(ValueError):
        db.update_user_source(uid, featch_state="fetched")     # 手滑写错列名


def test_stored_states_and_derived_buckets_are_two_separate_vocabularies():
    """读取态（存储）与覆盖率桶（派生）词表必须**分开声明**，且两者都可枚举。

    B4/B5 落地时定下的分工：collect 写 `fetch_state`、audit 写 `cited_by`，
    `cited`/`uncited` 是由两者算出来的指标，不是第三种存储态。
    本例钉的是"两套词表都存在、互不重叠、且派生桶都能被存储态解释"——
    把 cited 塞回 fetch_state 会让两个写者抢一列，返工轮/复跑必然漂出
    "已引用却仍是 fetched"，而那种不一致没人报错。
    期望值来源：`db.USER_SOURCE_STATES` 与 `audit.USER_SOURCE_COVERAGE_BUCKETS`。
    """
    from app.core import audit

    stored = set(db.USER_SOURCE_STATES)
    buckets = set(audit.USER_SOURCE_COVERAGE_BUCKETS)
    assert stored == {"pending", "fetched", "unread", "blocked", "gated_off_query", "merged"}
    assert buckets == {"cited", "uncited", "unread", "blocked", "gated_off_query", "merged"}
    # 派生桶里除 cited/uncited 之外的每一个都必须是一个真实存储态（不能凭空造词）
    assert (buckets - {"cited", "uncited"}) <= stored, sorted(buckets - {"cited", "uncited"} - stored)
    # 引用结果不进存储词表（写进去即双写漂移）
    assert not (stored & {"cited", "uncited"})


# ── 3. 跨用例污染（TC-22）──────────────────────────────────────────

def test_rows_from_the_previous_case_are_gone():
    """autouse `_isolate` 必须把本表纳入清理；这一条是对它登记与否的直接判据。

    形状：前面所有用例都往同一个 `TASK` 写行，进到本用例必须一行都查不到。
    夹具漏清即红 —— 这条不是"顺手加的断言"，而是 TC-22 要求的判据本身。
    """
    assert db.list_user_sources(TASK) == [], (
        "读到了前面用例写的行 ⇒ conftest._isolate 没调 db.clear_user_sources()，"
        "本表成了跨用例污染源"
    )


# ── 4. 存量库文件上加表（TC-41）────────────────────────────────────

def test_new_table_appears_on_an_existing_database_file():
    """旧 schema 的库文件（没有 user_sources）启动后：新表自动建、旧数据仍可读、无迁移报错。

    形状照 `test_db_migration.py:214-243`：直接换 `db._DB_PATH` 并重置 `_SCHEMA_READY`
    与线程本地连接，走真实读路径而不是手工建表。
    """
    old_db = Path(tempfile.mkdtemp(prefix="verda-old-")) / "legacy.db"
    c = sqlite3.connect(old_db)
    c.executescript(
        """
        CREATE TABLE tasks (task_id TEXT PRIMARY KEY, query TEXT, clarifications TEXT,
                            status TEXT, created_at TEXT, report_id TEXT);
        CREATE TABLE reports (report_id TEXT PRIMARY KEY, task_id TEXT, title TEXT,
                              data TEXT, created_at TEXT);
        """
    )
    c.execute("INSERT INTO tasks(task_id,query,clarifications,status,created_at,report_id)"
              " VALUES('t-legacy','旧任务','{}','created','2026-01-01T00:00:00','r-legacy')")
    c.commit()
    c.close()

    saved_path, saved_ready = db._DB_PATH, db._SCHEMA_READY
    db._DB_PATH, db._SCHEMA_READY = old_db, False
    db._LOCAL.__dict__.pop("conn", None)
    try:
        assert db.get_task("t-legacy")["query"] == "旧任务", "旧数据读不到"
        uid = db.add_user_source("t-legacy", "https://legacy.gov.cn/x", "https://legacy.gov.cn/x", 0)
        assert [r["uid"] for r in db.list_user_sources("t-legacy")] == [uid], (
            "新表在存量库上没建出来，或写入读不回"
        )
    finally:
        db._DB_PATH, db._SCHEMA_READY = saved_path, False
        db._LOCAL.__dict__.pop("conn", None)
        db.invalidate_aggregates()


# ── 5. 级联删除不留孤儿 ────────────────────────────────────────────

def test_delete_report_also_removes_the_task_user_sources():
    """报告删除后，按 task_id 归属的实例行不能留下。

    `user_sources` 没有 report_id 列，加不进 `_REPORT_SCOPED_TABLES` 那套按 report_id
    删的清单 ⇒ 必须在删 tasks **之前**先查 task_id（顺序反了就永远查不到归属）。
    """
    db.save_task("t-cascade", "级联验证", {}, kind="research")
    db.mark_task_done("t-cascade", "r-cascade")
    uid = db.add_user_source("t-cascade", "https://k.gov.cn/1", "https://k.gov.cn/1", 0)

    assert db.delete_report("r-cascade") is True
    assert db.list_user_sources("t-cascade") == [], (
        f"报告删了却留下孤儿实例行（uid={uid}）⇒ _delete_report_scoped_rows 的 task 归属清理失效"
    )


def test_delete_report_does_not_touch_another_tasks_sources():
    """隔离性：级联只认被删报告对应的那个 task_id，别的任务一行都不能少。"""
    db.save_task("t-keep-a", "甲", {}, kind="research")
    db.mark_task_done("t-keep-a", "r-keep-a")
    db.add_user_source("t-keep-a", "https://a.gov.cn/1", "https://a.gov.cn/1", 0)
    db.save_task("t-keep-b", "乙", {}, kind="research")
    db.mark_task_done("t-keep-b", "r-keep-b")
    db.add_user_source("t-keep-b", "https://b.gov.cn/1", "https://b.gov.cn/1", 0)

    assert db.delete_report("r-keep-a") is True
    assert len(db.list_user_sources("t-keep-b")) == 1, "删过头：误伤了另一个任务的实例行"
