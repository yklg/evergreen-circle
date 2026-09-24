"""存量库迁移 brand → destination —— B3（R2 迁移三件套）。

守护的不变量（backend/app/core/db.py::_migrate_brand_to_destination）：
- 旧形态库（列名 brands / brand、表 competitor_discovery_cache）→ 迁移后新列在、旧列消失、
  行数与数据原样保全；
- **幂等**：重复执行结果不变（PRAGMA 列集合相等）；
- **备份**：首次实际改名才生成 `<db>.pre-migration.bak`，重复执行不覆盖；
- 已是新形态 → 跳过且不产生备份；
- **失败可观测**：任一步 sqlite3.Error → raise（不半迁移静默运行），且 _SCHEMA_READY 保持 False。

种子：test_clarify_async.py::db2_alter_migration（自建旧表 + PRAGMA 断言）、
      test_refine_evidence.py::tasks_kind_migration_idempotent（幂等重跑）。
运行：backend/ 下 `pytest tests/test_db_migration.py -q`
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

import app.core.db as db

_OLD_SCHEMA = """
CREATE TABLE reports (
    report_id TEXT PRIMARY KEY, task_id TEXT, title TEXT, subtitle TEXT, query TEXT,
    brands TEXT, experts TEXT, cover_image TEXT, data TEXT,
    evidence_count INTEGER, claim_count INTEGER, high_conf_count INTEGER, created_at TEXT
);
CREATE TABLE evidences (
    evidence_id TEXT PRIMARY KEY, report_id TEXT, source_url TEXT, source_type TEXT,
    domain TEXT, title TEXT, excerpt TEXT, credibility REAL, collected_by TEXT,
    brand TEXT, captured_at TEXT
);
CREATE TABLE subscriptions (
    sub_id TEXT PRIMARY KEY, query TEXT, brands TEXT, created_at TEXT,
    last_run_at TEXT, last_report_id TEXT, run_count INTEGER
);
CREATE TABLE competitor_discovery_cache (
    qhash TEXT PRIMARY KEY, payload TEXT, expires_at TEXT, created_at TEXT
);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, query TEXT, clarifications TEXT, status TEXT,
    created_at TEXT, report_id TEXT
);
"""


@pytest.fixture()
def old_db():
    """建一个旧形态库（含中文数据行），返回 (path, 原始行快照)。"""
    d = Path(tempfile.mkdtemp(prefix="verda-mig-"))
    p = d / "old.db"
    c = sqlite3.connect(str(p))
    c.executescript(_OLD_SCHEMA)
    c.execute(
        "INSERT INTO reports(report_id,task_id,title,subtitle,query,brands,experts,cover_image,"
        "data,evidence_count,claim_count,high_conf_count,created_at)"
        " VALUES('r1','t1','旧报告','副标题','大理调研','[\"洱海\",\"古城\"]','[]','',"
        "'{\"brands\":[\"洱海\",\"古城\"]}',2,3,1,'2026-01-01T00:00:00')"
    )
    c.execute(
        "INSERT INTO evidences(evidence_id,report_id,source_url,source_type,domain,title,excerpt,"
        "credibility,collected_by,brand,captured_at) VALUES"
        "('e1','r1','https://a.com/1','web','a.com','标题','摘要',0.9,'L1-025','洱海','2026-01-01T00:00:00'),"
        "('e2','r1','https://b.com/2','web','b.com','标题2','摘要2',0.8,'L1-025','古城','2026-01-01T00:00:00')"
    )
    c.execute(
        "INSERT INTO subscriptions(sub_id,query,brands,created_at,last_run_at,last_report_id,run_count)"
        " VALUES('s1','大理','[\"洱海\"]','2026-01-01T00:00:00','',NULL,0)"
    )
    c.execute(
        "INSERT INTO competitor_discovery_cache(qhash,payload,expires_at,created_at)"
        " VALUES('h1','{\"subject\":\"大理\"}','2099-01-01T00:00:00','2026-01-01T00:00:00')"
    )
    c.commit()
    c.close()
    return p


def _migrate(path: Path) -> sqlite3.Connection:
    """对指定库跑一次完整 schema 初始化（内部含迁移），返回仍打开的连接。"""
    c = sqlite3.connect(str(path))
    db._init_schema(c)
    return c


def _cols(c: sqlite3.Connection, table: str):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _tables(c: sqlite3.Connection):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


# ① 列/表改名 + 行数不变 ────────────────────────────────
def test_migration_renames_columns_and_table(old_db):
    c = _migrate(old_db)
    assert "destinations" in _cols(c, "reports") and "brands" not in _cols(c, "reports")
    assert "destination" in _cols(c, "evidences") and "brand" not in _cols(c, "evidences")
    assert "destinations" in _cols(c, "subscriptions") and "brands" not in _cols(c, "subscriptions")
    tables = _tables(c)
    assert "destination_discovery_cache" in tables and "competitor_discovery_cache" not in tables
    # 新列补齐
    assert "research_type" in _cols(c, "reports")
    assert "type" in _cols(c, "subscriptions")
    # 行数不变
    assert c.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM evidences").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM destination_discovery_cache").fetchone()[0] == 1
    c.close()


# ② 数据保全：中文值原样落到新列 ─────────────────────────
def test_migration_preserves_values(old_db):
    c = _migrate(old_db)
    assert c.execute("SELECT destinations FROM reports WHERE report_id='r1'").fetchone()[0] == '["洱海","古城"]'
    dests = {r[0] for r in c.execute("SELECT destination FROM evidences").fetchall()}
    assert dests == {"洱海", "古城"}
    assert c.execute("SELECT destinations FROM subscriptions WHERE sub_id='s1'").fetchone()[0] == '["洱海"]'
    c.close()


# ③ 幂等：再跑一次列集合与数据不变 ───────────────────────
def test_migration_idempotent(old_db):
    c = _migrate(old_db)
    before = {t: _cols(c, t) for t in ("reports", "evidences", "subscriptions")}
    rows_before = c.execute("SELECT destinations FROM reports").fetchall()
    db._init_schema(c)  # 同连接重跑（_SCHEMA_READY 在真实路径下会短路，这里直调）
    assert {t: _cols(c, t) for t in ("reports", "evidences", "subscriptions")} == before
    assert c.execute("SELECT destinations FROM reports").fetchall() == rows_before
    c.close()


# ④ 备份：首次迁移生成，重复执行不覆盖 ───────────────────
def test_migration_backup_created_once(old_db):
    bak = Path(str(old_db) + ".pre-migration.bak")
    assert not bak.exists()
    c = _migrate(old_db)
    c.close()
    assert bak.exists(), "实际发生改名必须先生成 .pre-migration.bak"
    # 备份内容是**迁移前**的旧形态（含 brands 列）
    b = sqlite3.connect(str(bak))
    assert "brands" in _cols(b, "reports")
    b.close()
    # 人为篡改标记 → 重跑迁移（先回退列名）不得覆盖既有备份
    bak.write_text("sentinel", encoding="utf-8")
    c = sqlite3.connect(str(old_db))
    c.execute("ALTER TABLE reports RENAME COLUMN destinations TO brands")
    c.commit()
    db._init_schema(c)
    c.close()
    assert bak.read_text(encoding="utf-8") == "sentinel", "既有备份不得被覆盖"


# ⑤ 已是新形态 → 跳过且不产生备份 ───────────────────────
def test_migration_skipped_on_new_shape(tmp_path):
    p = tmp_path / "fresh.db"
    c = _migrate(p)  # 全新库：CREATE 即新形态
    c.close()
    assert not Path(str(p) + ".pre-migration.bak").exists()
    c = _migrate(p)  # 再跑一次仍是空转
    c.close()
    assert not Path(str(p) + ".pre-migration.bak").exists()


# ⑥ 失败可观测：迁移异常必须 raise，不得半迁移静默 ──────────
def test_migration_failure_raises_and_keeps_schema_unready(old_db):
    class _FailingConn:
        """代理连接：RENAME 语句抛 sqlite3.Error（sqlite3.Connection 不可 monkeypatch）。"""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **kw):
            if "RENAME COLUMN" in sql or "RENAME TO" in sql:
                raise sqlite3.Error("boom")
            return self._real.execute(sql, *a, **kw)

        def executescript(self, script):
            return self._real.executescript(script)

        def commit(self):
            return self._real.commit()

        def backup(self, target):
            return self._real.backup(target)

    db._SCHEMA_READY = False
    c = sqlite3.connect(str(old_db))
    try:
        with pytest.raises(RuntimeError):
            db._init_schema(_FailingConn(c))
    finally:
        db._SCHEMA_READY = False
    assert db._SCHEMA_READY is False, "迁移失败必须中止启动，不得标记 schema 就绪"
    # 半迁移态未被放行：reports 仍是旧列
    assert "brands" in _cols(c, "reports")
    c.close()
    # 失败前已落备份（改名动作即将发生）
    assert Path(str(old_db) + ".pre-migration.bak").exists()


# ⑦ 旧订阅行默认 type='guide' ──────────────────────────
def test_migration_subscription_type_default(old_db):
    c = _migrate(old_db)
    assert c.execute("SELECT type FROM subscriptions WHERE sub_id='s1'").fetchone()[0] == "guide"
    assert c.execute("SELECT research_type FROM reports WHERE report_id='r1'").fetchone()[0] == "guide"
    c.close()


# ⑧ 迁移后读路径：旧 data JSON 键归一并可读回 ────────────
def test_post_migration_read_normalizes_legacy_json(old_db):
    c = _migrate(old_db)
    c.close()
    # 把全局 db 指向迁移后的库（含线程本地连接），走真实读路径
    old_path, db._DB_PATH, db._SCHEMA_READY = db._DB_PATH, old_db, False
    db._LOCAL.__dict__.pop("conn", None)
    try:
        rep = db.get_report("r1")
        assert rep is not None
        assert rep["destinations"] == ["洱海", "古城"]
        assert "brands" not in rep
        assert rep["research_type"] == "guide"
        assert {e["destination"] for e in rep["evidence"]} == {"洱海", "古城"}
        card = [r for r in db.list_reports() if r["id"] == "r1"][0]
        assert card["destinations"] == ["洱海", "古城"] and "brands" not in card
        subs = db.list_subscriptions()
        assert subs[0]["destinations"] == ["洱海"] and subs[0]["type"] == "guide"
        assert db.query_evidences(destination="洱海")[0]["evidence_id"] == "e1"
        assert db.query_evidences(destination="不存在") == []
        assert db.evidence_facets()["by_destination"] == {"洱海": 1, "古城": 1}
        dash = db.dashboard_stats()
        assert dash["destination_distribution"] == {"洱海": 1, "古城": 1}
        assert dash["research_cards"][0]["destinations"] == ["洱海", "古城"]
    finally:
        db._DB_PATH, db._SCHEMA_READY = old_path, False
        db._LOCAL.__dict__.pop("conn", None)
        db.invalidate_aggregates()


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
