"""SQLite 持久化层（真实落盘，切页面/刷新/重启都在）。

存储：调研任务 / 报告 / 证据溯源 / 目的地监控订阅 / 专家工作量
      + 系统级运行时配置覆盖（settings 表）/ 用户级偏好（prefs 表）
      + 用户指定信源的实例状态（user_sources 表）。
所有读写都走这里，绝不再用内存 dict 当真相源。

`settings` 与 `prefs` 是**两张表、两套语义**，不可互换：
- `settings`：系统级运行时配置（env 默认 + 运维覆盖），键为 CONFIG_SCHEMA 白名单，
  对外 GET 必须经 `runtime_config.mask_effective()` 脱敏（含密钥）。
- `prefs`：用户级偏好（昵称/公司/界面选择），明文无密钥，原样返回。
  两表合并会让脱敏判断与启动迁移（migrate_legacy_settings）互相误伤，故刻意分表。
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.research_types import DEFAULT_RESEARCH_TYPE


def _resolve_db_path() -> Path:
    """选择数据库落盘位置。

    本地：app/data/verda.db（持久）。
    Vercel：文件系统只读，唯一可写目录是 /tmp（函数生命周期内有效，
    用户已接受刷新/重启后不持久化）。可用 VERDA_DB_PATH 覆盖。
    """
    override = os.environ.get("VERDA_DB_PATH")
    if override:
        return Path(override)
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/verda.db")
    return Path(__file__).resolve().parent.parent / "data" / "verda.db"


_DB_PATH = _resolve_db_path()
# 写锁：SQLite 单写多读，写操作串行化以避免 "database is locked"。
_LOCK = threading.RLock()
# 线程本地连接：FastAPI 同步端点跑在线程池里，编排阶段又用 asyncio.to_thread
# 派生大量工作线程。绝不能多线程共用同一个 sqlite3.Connection（会触发
# "Recursive use of cursors"/句柄竞争，表现为后端卡死、读到空数据）。
# 每个线程持有自己的连接 + WAL 模式 + busy_timeout，实现真正的并发安全。
_LOCAL = threading.local()
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _connect() -> sqlite3.Connection:
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        return conn
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # WAL：读写并发不互相阻塞（读不挡写、写不挡读）；busy_timeout 让并发写排队而非报错。
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.Error:
        pass
    _ensure_schema(conn)
    _LOCAL.conn = conn
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """整库 schema 只需初始化一次；后续线程连接复用已建好的表。"""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        _init_schema(conn)
        _SCHEMA_READY = True


def _init_schema(conn: sqlite3.Connection) -> None:
    # 迁移必须先于 CREATE：否则 `CREATE TABLE IF NOT EXISTS destination_discovery_cache`
    # 会先把新表建出来，使「目标表已存在 → 跳过」的幂等判定误判为已迁移，旧表数据成为孤儿。
    _migrate_brand_to_destination(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            query TEXT,
            clarifications TEXT,
            status TEXT,
            created_at TEXT,
            report_id TEXT,
            clarify_questions TEXT
        );
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            task_id TEXT,
            title TEXT,
            subtitle TEXT,
            query TEXT,
            destinations TEXT,
            research_type TEXT,
            experts TEXT,
            cover_image TEXT,
            data TEXT,
            evidence_count INTEGER,
            claim_count INTEGER,
            high_conf_count INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS evidences (
            evidence_id TEXT PRIMARY KEY,
            report_id TEXT,
            source_url TEXT,
            source_type TEXT,
            domain TEXT,
            title TEXT,
            excerpt TEXT,
            credibility REAL,
            collected_by TEXT,
            destination TEXT,
            captured_at TEXT
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            sub_id TEXT PRIMARY KEY,
            query TEXT,
            destinations TEXT,
            type TEXT,
            created_at TEXT,
            last_run_at TEXT,
            last_report_id TEXT,
            run_count INTEGER,
            source_urls TEXT
        );
        CREATE TABLE IF NOT EXISTS expert_stats (
            expert_id TEXT PRIMARY KEY,
            missions INTEGER DEFAULT 0,
            claims_authored INTEGER DEFAULT 0,
            evidence_collected INTEGER DEFAULT 0,
            last_active TEXT
        );
        CREATE TABLE IF NOT EXISTS traces (
            span_id TEXT PRIMARY KEY,
            task_id TEXT,
            report_id TEXT,
            seq INTEGER,
            agent_id TEXT,
            stage TEXT,
            purpose TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            latency_ms INTEGER,
            decision TEXT,
            evidence_ids TEXT,
            ts TEXT
        );

        CREATE TABLE IF NOT EXISTS living_circle_reports (
            report_id TEXT PRIMARY KEY,
            scene_key TEXT,
            scene_name TEXT,
            data TEXT,
            data_origin TEXT,
            total_score REAL,
            blindspot_count INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS report_feedback (
            report_id TEXT PRIMARY KEY,
            edited_blocks INTEGER,
            total_blocks INTEGER,
            data TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS destination_discovery_cache (
            qhash TEXT PRIMARY KEY,
            payload TEXT,
            expires_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prefs (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS user_sources (
            uid TEXT PRIMARY KEY,
            task_id TEXT,
            seq INTEGER,
            url TEXT,
            url_canonical TEXT,
            kind TEXT,
            fetch_state TEXT,
            evidence_id TEXT,
            group_id TEXT,
            cited_by TEXT,
            attempt_reason TEXT,
            bytes INTEGER,
            ms INTEGER,
            updated_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_user_sources_task_url
            ON user_sources(task_id, url_canonical);
        """
    )
    conn.commit()
    # 迁移：存量库 tasks 表可能缺 clarify_questions 列（旧库不自动加列）。
    # CREATE TABLE IF NOT EXISTS 不会给已存在的表加列，这里显式 ALTER 补齐，
    # 带列存在性检查，可重复执行（幂等）。
    try:
        # 按位置取列名（cid,name,type,...），不依赖调用方的 row_factory，兼容任意连接
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "clarify_questions" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN clarify_questions TEXT")
            conn.commit()
        # 运行态扩展列（后台常驻重构）：让「运行中的任务」成为一等实体。
        # 幂等补齐，旧库重复执行无副作用。
        for col, coltype in (
            ("stage", "TEXT"),
            ("percent", "INTEGER"),
            ("evidence_count", "INTEGER"),
            ("started_at", "TEXT"),
            ("updated_at", "TEXT"),
            ("error", "TEXT"),
            ("kind", "TEXT"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {coltype}")
        conn.commit()
    except sqlite3.Error:
        pass

    # 迁移：存量库 evidences 表可能缺 report_id 列（旧库不自动加列）。
    # 证据归属依赖该列（INSERT 显式写 report_id）。带列存在性检查，幂等。
    try:
        ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(evidences)").fetchall()]
        if "report_id" not in ev_cols:
            conn.execute("ALTER TABLE evidences ADD COLUMN report_id TEXT")
            conn.commit()
    except sqlite3.Error:
        pass

    # 迁移：存量库 subscriptions 表可能缺 source_urls 列（计划 v3 §二 B8）。
    # 订阅复跑要靠它带上用户指定信源清单；缺列会让复跑悄悄少一批信源而界面看不出差别。
    try:
        sub_cols = [r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()]
        if sub_cols and "source_urls" not in sub_cols:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN source_urls TEXT")
            conn.commit()
    except sqlite3.Error:
        pass

    # 启动回填：存量报告证据写进 evidences 表（单一真相源），幂等。
    # 注意：必须先置 _SCHEMA_READY=True 再调 backfill——否则 backfill 内部的
    # _connect() 会再次触发 _ensure_schema → 重入 _init_schema → 无限递归卡死。
    global _SCHEMA_READY
    _SCHEMA_READY = True
    try:
        backfill_evidences_from_reports()
    except sqlite3.Error:
        pass


# ── 迁移：竞品语义（brand）→ 目的地语义（destination）──────────
# 存量库改列名/表名；新库由 _init_schema 的 CREATE 段直接建新形态，本函数为空转。
_RENAME_COLUMNS = (
    ("reports", "brands", "destinations"),
    ("evidences", "brand", "destination"),
    ("subscriptions", "brands", "destinations"),
)
_ADD_COLUMNS = (
    ("reports", "research_type", "TEXT", "'guide'"),
    ("subscriptions", "type", "TEXT", "'guide'"),
)
# 旧表名（存量库迁移时按此名查找，勿改为新名）
_OLD_CACHE_TABLE = "competitor_discovery_cache"
_NEW_CACHE_TABLE = "destination_discovery_cache"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _conn_db_path(conn: sqlite3.Connection) -> Path:
    """连接实际指向的库文件（不依赖全局 _DB_PATH，容忍直接传入临时连接）。"""
    for r in conn.execute("PRAGMA database_list").fetchall():
        if r[1] == "main" and r[2]:
            return Path(r[2])
    return _DB_PATH


def _backup_db(conn: sqlite3.Connection, bak: "Path") -> None:
    """用 SQLite 在线备份 API 落一份原始库快照（WAL 安全，不受未检查点影响）。"""
    dst = sqlite3.connect(str(bak))
    try:
        conn.backup(dst)
    finally:
        dst.close()


def _migrate_brand_to_destination(conn: sqlite3.Connection) -> None:
    """把竞品语义的列/表改名为目的地语义（幂等；失败中止启动，绝不半迁移静默运行）。

    幂等靠**前置存在性判定**（目标列/表已在 → 跳过），不靠 `except: pass` 吞异常：
    - 无可改名项（全新库或已迁移库）→ 直接返回，不产生备份。
    - 本轮将实际发生改名 → 先把原始库备份为 `<db>.pre-migration.bak`（已存在则不覆盖）。
    - 任一步 sqlite3.Error → 打印明确日志并 raise，中止启动（半迁移态绝不放行）。
    """
    rename_table = (
        _table_exists(conn, _OLD_CACHE_TABLE)
        and not _table_exists(conn, _NEW_CACHE_TABLE)
    )
    rename_cols: List[tuple] = []
    for table, old, new in _RENAME_COLUMNS:
        if not _table_exists(conn, table):
            continue
        cols = _table_columns(conn, table)
        if old in cols and new not in cols:
            rename_cols.append((table, old, new))
    add_cols = [(t, c, ty, dflt) for t, c, ty, dflt in _ADD_COLUMNS
                if _table_exists(conn, t) and c not in _table_columns(conn, t)]

    if not (rename_table or rename_cols or add_cols):
        return

    bak = Path(str(_conn_db_path(conn)) + ".pre-migration.bak")
    if rename_table or rename_cols:
        try:
            if not bak.exists():
                _backup_db(conn, bak)
        except sqlite3.Error as exc:
            import sys
            print(f"[verda] 迁移前备份失败：{exc}", file=sys.stderr)
            raise RuntimeError("schema 迁移前备份失败，已中止启动") from exc

    try:
        with _LOCK:
            for table, old, new in rename_cols:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
            if rename_table:
                conn.execute(
                    f"ALTER TABLE {_OLD_CACHE_TABLE} RENAME TO {_NEW_CACHE_TABLE}"
                )
            for table, col, coltype, dflt in add_cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype} DEFAULT {dflt}")
            conn.commit()
    except sqlite3.Error as exc:
        import sys
        print(f"[verda] schema 迁移失败（brand → destination）：{exc}\n"
              f"[verda] 原始库已备份至 {bak}，请修复后重启（不会以半迁移态运行）。",
              file=sys.stderr)
        raise RuntimeError("schema 迁移失败，原始库已备份") from exc


# ── 运行时配置（DB 覆盖层）──────────────────────────────
# 只存「用户在界面上改过的键」；未改的键回落 env 默认值（见 core/runtime_config.py）。
def get_setting(key: str) -> Optional[str]:
    """读取单个键的运行时覆盖值；不存在返回 None（表示「未覆盖」）。"""
    c = _connect()
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """写入/更新单个键的运行时覆盖值。value 一律以字符串落库，类型由 SCHEMA 负责还原。"""
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)",
            (key, str(value), _now()),
        )
        c.commit()


def get_all_settings() -> Dict[str, str]:
    """一次性取出全部覆盖值（避免逐键查询的 N 次往返）。"""
    c = _connect()
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")}


def clear_settings() -> None:
    """清空所有运行时覆盖，完全回落 env 默认。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM settings")
        c.commit()


def delete_setting(key: str) -> None:
    """删除单个键的运行时覆盖。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM settings WHERE key=?", (key,))
        c.commit()


def migrate_settings(mapping: Dict[str, str]) -> int:
    """运行时配置键迁移（如键名泛化 zhipu_* → llm_*）：单事务把旧键搬到新键。

    - 新键已存在（用户已在新键名下保存过）→ **跳过不覆盖**，仅删除旧键。
    - 幂等：可重复执行，无旧键时 no-op。
    返回：本次处理的旧键数。
    """
    moved = 0
    with _LOCK:
        c = _connect()
        try:
            for old, new in mapping.items():
                row = c.execute(
                    "SELECT value FROM settings WHERE key=?", (old,)
                ).fetchone()
                if row is None:
                    continue
                exists = c.execute(
                    "SELECT 1 FROM settings WHERE key=?", (new,)
                ).fetchone()
                if exists is None:
                    c.execute(
                        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)",
                        (new, row["value"], _now()),
                    )
                c.execute("DELETE FROM settings WHERE key=?", (old,))
                moved += 1
            c.commit()
        except Exception:
            c.rollback()
            raise
    return moved


# ── 用户级偏好（prefs 表）───────────────────────────────
# 与 settings 表刻意分离（见模块 docstring）。域层白名单/校验见 core/user_prefs.py；
# 本层只做「键值裸存取」，不含业务语义（与 settings 的分层一致）。
def get_prefs_all() -> Dict[str, str]:
    """一次性取出全部用户偏好（避免逐键 N 次往返）。"""
    c = _connect()
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM prefs")}


def set_prefs(patch: Dict[str, str]) -> None:
    """批量写入用户偏好：**单事务**，任一键失败整体回滚（不做半写）。

    value 一律以字符串落库；类型还原由 core/user_prefs.py 依据 PREF_SCHEMA 负责。
    """
    if not patch:
        return
    with _LOCK:
        c = _connect()
        try:
            for k, v in patch.items():
                c.execute(
                    "INSERT OR REPLACE INTO prefs(key,value,updated_at) VALUES(?,?,?)",
                    (k, str(v), _now()),
                )
            c.commit()
        except Exception:
            c.rollback()
            raise


def delete_pref(key: str) -> None:
    """删除单个偏好键（回落前端默认值）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM prefs WHERE key=?", (key,))
        c.commit()


def clear_prefs() -> None:
    """清空全部用户偏好（供测试隔离 / 显式重置使用；业务读路径不得调用）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM prefs")
        c.commit()


# ── 用户指定信源（实例级运行时状态 · 计划 v3 §二 U0）────────────────
# 语义分工：prefs 表存「默认引用列表」（用户偏好），本表存「某一次任务里这几条网址的
# 运行时实例状态」（业务数据）。任务记录因此是**唯一可复现凭据**——复跑 / 精炼 / 简报
# 都从这里重放同一份清单，派生报告不会丢信源。
#
# 状态机（fetch_state 的唯一合法取值集）—— **只描述"读没读到"**，不含引用情况：
#   pending          已登记，尚未尝试
#   fetched          抓取成功、已入证据链
#   unread           抓取失败（404/403/超时…）；attempt_reason 分档记录
#   blocked          被内网闸门拒绝（安全判定，不是抓取失败）
#   gated_off_query  已抓取但正文与任务 query 不相关（仅诊断，仍入链）
#   merged           内容与既有信源组同质，归并而非独立成行
# 「有没有被引用」记在 `cited_by`（唯一写点是 audit 覆盖率计算），**不挤进这根列**：
# fetch_state 由 collect 写、cited_by 由 audit 写，两个写者抢一列必然在返工轮/复跑时
# 漂出"已引用却仍是 fetched"，而那种不一致没人报错。覆盖率是派生指标，不是第三种存储态。
USER_SOURCE_STATES = (
    "pending", "fetched", "unread", "blocked", "gated_off_query", "merged",
)
_USER_SOURCE_COLUMNS = (
    "url", "url_canonical", "seq", "kind", "fetch_state", "evidence_id",
    "group_id", "cited_by", "attempt_reason", "bytes", "ms",
)


def _user_source_uid(task_id: str, url_canonical: str) -> str:
    """确定性 uid：同一 (任务, 归一化网址) 恒等 ⇒ 复跑/重放可幂等，且能给审计当 target。"""
    digest = hashlib.sha1(f"{task_id}|{url_canonical}".encode("utf-8")).hexdigest()
    return f"us_{digest[:16]}"


def add_user_source(task_id: str, url: str, url_canonical: str, seq: int,
                    kind: str = "user_supplied") -> str:
    """登记一条用户指定网址（幂等：同任务同归一化网址只有一行，重复登记回落同一 uid）。"""
    uid = _user_source_uid(task_id, url_canonical)
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO user_sources"
            "(uid,task_id,seq,url,url_canonical,kind,fetch_state,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (uid, task_id, seq, url, url_canonical, kind, "pending", _now()),
        )
        c.commit()
    return uid


def update_user_source(uid: str, **fields: Any) -> None:
    """按 uid 更新实例状态（写入单点收口：collect 写抓取态，audit 写引用态）。

    未知列名与非法 fetch_state 直接抛错——状态词表是本表的契约，
    写错必须当场炸，不能让一个拼错的态静默入库、再到覆盖率里凭空消失。
    """
    unknown = [k for k in fields if k not in _USER_SOURCE_COLUMNS]
    if unknown:
        raise ValueError(f"user_sources 无这些列：{unknown}")
    state = fields.get("fetch_state")
    if state is not None and state not in USER_SOURCE_STATES:
        raise ValueError(f"非法 fetch_state：{state!r}（合法集见 USER_SOURCE_STATES）")
    sets = ", ".join(f"{k}=?" for k in fields)
    with _LOCK:
        c = _connect()
        c.execute(
            f"UPDATE user_sources SET {sets}{', ' if fields else ''}updated_at=? WHERE uid=?",
            (*fields.values(), _now(), uid),
        )
        c.commit()


def list_user_sources(task_id: str) -> List[Dict[str, Any]]:
    """读取某任务的全部用户指定信源，按登记顺序（seq）返回。"""
    c = _connect()
    return [dict(r) for r in c.execute(
        "SELECT * FROM user_sources WHERE task_id=? ORDER BY seq", (task_id,)
    ).fetchall()]


def clear_user_sources() -> None:
    """清空用户指定信源实例（供测试隔离使用；业务读路径不得调用）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM user_sources")
        c.commit()


# ── 任务 ────────────────────────────────────────────────
def save_task(task_id: str, query: str, clarifications: Dict[str, Any], kind: str = "research") -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO tasks(task_id,query,clarifications,status,created_at,report_id,kind)"
            " VALUES(?,?,?,?,?,COALESCE((SELECT report_id FROM tasks WHERE task_id=?),NULL),?)",
            (task_id, query, json.dumps(clarifications, ensure_ascii=False), "created", _now(), task_id, kind),
        )
        c.commit()


def update_task_clarify(task_id: str, clarifications: Dict[str, Any]) -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE tasks SET clarifications=?, status='clarified' WHERE task_id=?",
            (json.dumps(clarifications, ensure_ascii=False), task_id),
        )
        c.commit()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    c = _connect()
    row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["clarifications"] = json.loads(d.get("clarifications") or "{}")
    return d


def mark_task_done(task_id: str, report_id: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE tasks SET status='done', report_id=? WHERE task_id=?",
            (report_id, task_id),
        )
        c.commit()


def set_task_running(task_id: str) -> None:
    """任务进入执行态（后台常驻重构：与 SSE 连接生命周期解耦）。"""
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE tasks SET status='running', started_at=?, updated_at=? WHERE task_id=?",
            (_now(), _now(), task_id),
        )
        c.commit()


def patch_task_progress(task_id: str, percent: int, stage: str, evidence_count: int) -> None:
    """滚动更新进度（由 runner 从 progress 事件抽取落库，执行引擎不感知传输层）。"""
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE tasks SET percent=?, stage=?, evidence_count=?, updated_at=? WHERE task_id=?",
            (percent, stage, evidence_count, _now(), task_id),
        )
        c.commit()


def set_task_failed(task_id: str, error: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE tasks SET status='failed', error=?, updated_at=? WHERE task_id=?",
            (error[:500], _now(), task_id),
        )
        c.commit()


def get_task_full(task_id: str) -> Optional[Dict[str, Any]]:
    """含运行态扩展列；缺列时回落默认值，兼容未迁移的旧库。"""
    c = _connect()
    row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["clarifications"] = json.loads(d.get("clarifications") or "{}")
    return d


def list_running_tasks() -> List[Dict[str, Any]]:
    """进行中的任务（供侧栏/悬浮条入口），不含长文。"""
    c = _connect()
    rows = c.execute(
        "SELECT task_id, query, status, percent, stage, evidence_count, started_at, updated_at"
        " FROM tasks WHERE status IN ('running') ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def reconcile_orphan_runs() -> int:
    """进程重启后，DB 里仍标记 running 但内存已无句柄的任务 → 标 failed，避免悬浮条永久转圈。

    返回被修正的条数。
    """
    with _LOCK:
        c = _connect()
        cur = c.execute(
            "UPDATE tasks SET status='failed', error=?, updated_at=? WHERE status='running'",
            ("进程重启，任务已中断，请重新发起调研", _now()),
        )
        n = cur.rowcount
        c.commit()
        return n


# ── 目的地发现缓存（按 query 哈希，TTL 过期；仅缓存成功发现，兜底结果不缓存）──
def _query_hash(query: str) -> str:
    """归一化（去空白、转小写）后 sha256，作为发现缓存键。"""
    import hashlib

    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()


def get_discovery_cache(qhash: str) -> Optional[Dict[str, Any]]:
    """读取未过期的目的地发现缓存；过期/缺失返回 None。"""
    c = _connect()
    row = c.execute(
        "SELECT payload, expires_at FROM destination_discovery_cache WHERE qhash=?",
        (qhash,),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < _now():
        return None
    try:
        return json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError):
        return None


def save_discovery_cache(qhash: str, scope: Dict[str, Any], ttl_days: int = 7) -> None:
    """写入目的地发现缓存（带过期时间）。幂等（INSERT OR REPLACE）。"""
    from datetime import timedelta

    exp = (_dt.datetime.now() + timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = json.dumps(scope, ensure_ascii=False)
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO destination_discovery_cache(qhash,payload,expires_at,created_at)"
            " VALUES(?,?,?,?)",
            (qhash, payload, exp, _now()),
        )
        c.commit()


def clear_discovery_cache() -> None:
    """清空目的地发现缓存（测试隔离 / 手动刷新用）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM destination_discovery_cache")
        c.commit()


# ── 澄清问卷（懒生成，SSE 推送给前端）─────────────────────
def save_clarify_questions(
    task_id: str, questions: List[Dict[str, Any]], complete: bool = True
) -> None:
    """落库懒生成的澄清问卷；payload 统一为 {"questions": [...], "complete": bool}。

    complete 仅当整份问卷（含目的地发现）已就绪时为 True；partial（仅基础题）绝不落库，
    避免重连时只推回半份问卷（P0-③ 重连完整性）。
    """
    payload = json.dumps(
        {"questions": questions, "complete": bool(complete)}, ensure_ascii=False
    )
    with _LOCK:
        c = _connect()
        cur = c.execute(
            "UPDATE tasks SET clarify_questions=? WHERE task_id=?",
            (payload, task_id),
        )
        if cur.rowcount == 0:
            # 极端情况：task 尚未落库（理论 create_task 先于 SSE 调用，这里兜底）
            c.execute(
                "INSERT INTO tasks(task_id,query,clarifications,status,created_at,report_id,clarify_questions)"
                " VALUES(?,?,?,?,?,?,?)",
                (task_id, "", "{}", "created", _now(), None, payload),
            )
        c.commit()


def get_clarify_questions(task_id: str) -> "tuple[Optional[Dict[str, Any]], bool]":
    """读取已生成的澄清问卷。

    返回 (payload_dict, complete)：
    - 未生成/为空 → (None, False)（SSE 据此重新生成）。
    - 已落库 → (payload, complete)；旧库无 complete 字段视为完整（向后兼容）。
    仅当 complete=True 才视为可直推的完整问卷（重连完整性守卫）。
    """
    c = _connect()
    row = c.execute(
        "SELECT clarify_questions FROM tasks WHERE task_id=?", (task_id,)
    ).fetchone()
    if not row:
        return None, False
    raw = row["clarify_questions"]
    if not raw:
        return None, False
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, False
    if not isinstance(d, dict) or not d.get("questions"):
        return None, False
    return d, bool(d.get("complete", True))


# ── 报告 + 证据 ─────────────────────────────────────────
def save_report(report: Dict[str, Any], task_id: str = "") -> None:
    evidence = report.get("evidence", [])
    claims = report.get("claims", [])
    high = sum(1 for c in claims if c.get("confidence") == "high")
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO reports(report_id,task_id,title,subtitle,query,destinations,"
            "research_type,experts,cover_image,data,evidence_count,claim_count,high_conf_count,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                report["id"], task_id, report.get("title", ""), report.get("subtitle", ""),
                report.get("query", ""),
                json.dumps(report.get("destinations", []), ensure_ascii=False),
                report.get("research_type", DEFAULT_RESEARCH_TYPE),
                json.dumps(report.get("experts", []), ensure_ascii=False),
                report.get("cover_image", ""), json.dumps(report, ensure_ascii=False),
                len(evidence), len(claims), high, report.get("created_at", _now()),
            ),
        )
        # 证据溯源单独入库，供全局证据库检索
        for ev in evidence:
            c.execute(
                "INSERT OR REPLACE INTO evidences(evidence_id,report_id,source_url,source_type,"
                "domain,title,excerpt,credibility,collected_by,destination,captured_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev.get("evidence_id"), report["id"], ev.get("source_url", ""),
                    ev.get("source_type", ""), ev.get("domain", ""), ev.get("title", ""),
                    ev.get("excerpt", "")[:500], ev.get("credibility", 0.0),
                    ev.get("collected_by", ""), ev.get("destination", ""),
                    ev.get("captured_at", _now()),
                ),
            )
        c.commit()
        # G5 失效钩子：报告/证据写路径 → 聚合缓存淘汰
        invalidate_aggregates()


# --------------------------------------------------------------------------- #
# 证据读取
# --------------------------------------------------------------------------- #
def get_evidence(evidence_id: str) -> Optional[Dict[str, Any]]:
    """按 evidence_id 读取单条证据（含 report_id 归属）。"""
    c = _connect()
    row = c.execute("SELECT * FROM evidences WHERE evidence_id=?", (evidence_id,)).fetchone()
    return dict(row) if row else None


def backfill_evidences_from_reports() -> None:
    """启动一次性回填：把存量报告的 data.evidence 写进 evidences 表（单一真相源）。

    幂等（INSERT OR REPLACE，按 evidence_id 主键）。在 _init_schema 末尾调用，
    使旧库/旧报告的证据进入 evidences 表，让 Option B 的 get_report 实时派生生效。
    """
    with _LOCK:
        c = _connect()
        rows = c.execute("SELECT report_id, data FROM reports").fetchall()
        for r in rows:
            rid = r["report_id"]
            try:
                data = json.loads(r["data"]) if r["data"] else {}
            except Exception:
                data = {}
            for ev in data.get("evidence", []) or []:
                eid = ev.get("evidence_id")
                if not eid:
                    continue
                c.execute(
                    "INSERT OR REPLACE INTO evidences("
                    "evidence_id,report_id,source_url,source_type,domain,title,excerpt,"
                    "credibility,collected_by,destination,captured_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        eid, rid, ev.get("source_url", ""), ev.get("source_type", ""),
                        ev.get("domain", ""), ev.get("title", ""),
                        (ev.get("excerpt", "") or "")[:500], ev.get("credibility", 0.0),
                        ev.get("collected_by", ""),
                        ev.get("destination") or ev.get("brand", ""),
                        ev.get("captured_at", _now()),
                    ),
                )
        c.commit()
        invalidate_aggregates()


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    """统一报告读取入口（旅游 reports 表 + 生活圈 living_circle_reports 表）。

    - 先查 reports 表，走 brands→destinations 读时归一；
    - 未命中且 report_id 以 "lc-" 开头时查生活圈表，并幂等补齐旧盲区表征。
    """
    c = _connect()
    row = c.execute("SELECT data FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if row:
        data = _normalize_report_keys(json.loads(row["data"]))
        # evidence 实时查 evidences 表覆盖快照（Option B 单一真相）；异常兜底不丢证据
        try:
            evs = list(query_evidences(report_id=report_id))
        except Exception:
            evs = []
        if evs:
            data["evidence"] = evs
        return data

    # 生活圈体检报告（独立表，不经过 destination 归一）
    row = c.execute(
        "SELECT data FROM living_circle_reports WHERE report_id=?", (report_id,)
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return None
    try:
        from app.living_circle.assemble import annotate_blindspots
        lc = data.get("living_circle") or {}
        blindspots = lc.get("blindspots", [])
        sampling_points = (lc.get("sampling") or {}).get("points", [])
        if blindspots and sampling_points:
            annotated = annotate_blindspots(blindspots, sampling_points)
            if annotated:
                lc["blindspots"] = annotated
                data["living_circle"] = lc
    except Exception:
        pass  # 补齐失败不影响报告主体返回
    return data


# 旧契约键 → 新契约键（存量 reports.data 快照里的竞品语义；M2-flip brands→destinations）
_LEGACY_REPORT_KEYS = (("brands", "destinations"), ("brand", "destination"))
_LEGACY_QUALITY_KEYS = (
    ("coverage_by_brand", "coverage_by_destination"),
    ("brand_coverage_rate", "destination_coverage_rate"),
)
# 视角核查表承载键：亲子行曾叫 family_checklist，注册表收敛单名后统一为 persp_checklist。
# 存量报告里已实测存在旧键（r_6dadffee，2026-09-26 起持续新增），故只做**读时归一**：
# 不改写 reports.data、不做迁移——渲染层只认新键，漏归一的失败模式是核查表静默消失。
_LEGACY_STRUCTURED_KEYS = (("family_checklist", "persp_checklist"),)


def _normalize_structured_keys(container: Any) -> None:
    """就地归一报告快照里的结构化键（顶层 structured 字典 + 各章 structured 块列表）。"""
    if not isinstance(container, dict):
        return
    top = container.get("structured")
    if isinstance(top, dict):
        for old, new in _LEGACY_STRUCTURED_KEYS:
            if old in top:
                top.setdefault(new, top.pop(old))
    secs = container.get("sections")
    if isinstance(secs, list):
        for sec in secs:
            blocks = sec.get("structured") if isinstance(sec, dict) else None
            if isinstance(blocks, dict):          # 旧报告：单块 dict
                blocks = [blocks]
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                for old, new in _LEGACY_STRUCTURED_KEYS:
                    if b.get("type") == old:
                        b["type"] = new


def _normalize_report_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """读时归一：存量报告快照里的旧键名就地换成新契约键（幂等，新报告零改动）。

    RENAME COLUMN 只改列名，不改 reports.data 里的 JSON 键；旧报告仍带
    brands / brand 键。这里在读路径统一归一，使上层（前端/精炼/简报）只见新键。
    旧 `structured.type`（feature_tree 等）保留不动——前端分支删除后自动不渲染。
    """
    if not isinstance(data, dict):
        return data
    for old, new in _LEGACY_REPORT_KEYS:
        if old in data and new not in data:
            data[new] = data.pop(old)
        else:
            data.pop(old, None)
    data.setdefault("research_type", DEFAULT_RESEARCH_TYPE)
    evs = data.get("evidence")
    if isinstance(evs, list):
        for ev in evs:
            if isinstance(ev, dict) and "brand" in ev and "destination" not in ev:
                ev["destination"] = ev.pop("brand")
    for qk in ("quality_before", "quality_after"):
        q = data.get(qk)
        if isinstance(q, dict):
            for old, new in _LEGACY_QUALITY_KEYS:
                if old in q and new not in q:
                    q[new] = q.pop(old)
    _normalize_structured_keys(data)
    return data


def list_reports() -> List[Dict[str, Any]]:
    """报告卡片列表（不含全文 data，省带宽）。"""
    c = _connect()
    rows = c.execute(
        "SELECT report_id,title,subtitle,query,destinations,research_type,experts,cover_image,"
        "evidence_count,claim_count,high_conf_count,created_at FROM reports ORDER BY created_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = d["report_id"]
        d["destinations"] = json.loads(d.get("destinations") or "[]")
        d["research_type"] = d.get("research_type") or DEFAULT_RESEARCH_TYPE
        d["experts"] = json.loads(d.get("experts") or "[]")
        out.append(d)
    return out


# 按 report_id 弱关联的派生表：删除任一报告都必须一并清理，否则留孤儿行。
# 单一真相源 —— 调研报告与生活圈体检报告**共用**这一份清单，两条删除路径不得各写一遍 SQL。
_REPORT_SCOPED_TABLES = ("evidences", "traces", "report_feedback", "tasks")


def _delete_report_scoped_rows(c, report_id: str) -> None:
    """清掉一份报告的派生数据（证据溯源 / 决策链路 / 人工反馈 / 关联任务）。

    不在此 commit：由调用方与主表删除同处一个 `_LOCK` 临界区、一次提交，保证
    「级联 + 主表」原子，中途失败不会留下半张表。

    `user_sources` 按 **task_id** 归属（不在 `_REPORT_SCOPED_TABLES` 那套 report_id 列里），
    所以必须先查 task_id 再删 tasks —— 顺序反过来就永远查不到归属，留下清不掉的孤儿行。
    """
    task_ids = [r[0] for r in c.execute(
        "SELECT task_id FROM tasks WHERE report_id=?", (report_id,)
    ).fetchall()]
    for tid in task_ids:
        c.execute("DELETE FROM user_sources WHERE task_id=?", (tid,))
    for table in _REPORT_SCOPED_TABLES:
        c.execute(f"DELETE FROM {table} WHERE report_id=?", (report_id,))


def delete_report(report_id: str) -> bool:
    """删除报告并级联清理关联数据（单一真相源，避免孤儿行）。

    级联表及关联列（均按 report_id 弱关联）：
      - evidences(report_id)   证据溯源
      - traces(report_id)      决策链路
      - report_feedback(report_id) 人工修正反馈
      - tasks(report_id)       关联任务（标记完成的那条）
    订阅表 last_report_id 仅引用、不阻断删除，故不联动。
    """
    with _LOCK:
        c = _connect()
        _delete_report_scoped_rows(c, report_id)
        c.execute("DELETE FROM reports WHERE report_id=?", (report_id,))
        c.commit()
        # G5 失效钩子：级联删除改变聚合口径
        invalidate_aggregates()
    return True


@contextmanager
def locked():
    """暴露写锁临界区（RLock，可重入）。供派生数据读-算-写回需要整体串行的调用方使用。"""
    with _LOCK:
        yield


def invalidate_report_brief(report_id: str) -> None:
    """派生数据失效即淘汰：清除 data 中的 brief / brief_failed_at（幂等，不存在不报错）。

    报告内容变更通道（refine / refine-evidence / feedback）成功后必须调用，
    保证简报/一页纸精炼永远反映最新正文，不呈现陈旧结论。
    """
    with _LOCK:
        c = _connect()
        row = c.execute("SELECT data FROM reports WHERE report_id=?", (report_id,)).fetchone()
        if not row:
            return
        data = json.loads(row["data"])
        changed = False
        if "brief" in data:
            data.pop("brief", None)
            changed = True
        if "brief_failed_at" in data:
            data.pop("brief_failed_at", None)
            changed = True
        if not changed:
            return
        c.execute(
            "UPDATE reports SET data=?, evidence_count=?, claim_count=?, high_conf_count=? WHERE report_id=?",
            (
                json.dumps(data, ensure_ascii=False),
                len(data.get("evidence", [])),
                len(data.get("claims", [])),
                sum(1 for cl in data.get("claims", []) if cl.get("confidence") == "high"),
                report_id,
            ),
        )
        c.commit()
        # G5 失效钩子：data 已变（brief 淘汰），聚合口径可能变化
        invalidate_aggregates()


# ── 全局证据溯源库 ──────────────────────────────────────
def query_evidences(
    destination: Optional[str] = None,
    source_type: Optional[str] = None,
    min_cred: float = 0.0,
    limit: int = 200,
    report_id: Optional[str] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """全局证据溯源库查询。

    report_id 过滤语义：
      - None（默认）→ 全部证据（证据统一归属报告，无收件箱状态）
      - '<rid>'     → 仅返回该报告证据
    """
    c = _connect()
    sql = "SELECT * FROM evidences WHERE credibility>=?"
    args: List[Any] = [min_cred]
    if report_id is not None:
        sql += " AND report_id=?"
        args.append(report_id)
    if destination:
        sql += " AND destination=?"
        args.append(destination)
    if source_type:
        sql += " AND source_type=?"
        args.append(source_type)
    sql += " ORDER BY credibility DESC, captured_at DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def destination_graph() -> Dict[str, Any]:
    """目的地情报图谱：全库按 `destination` 聚合，**无缓存纯 SQL**。

    调用形状是硬约束，不要"顺手"改成走 `_AGG_CACHE` / `intel_overview()`：
    `/api/evidences` 每个请求都要 facets 的目的地分布，一旦这里去取整包聚合，
    等于每次查证据都反序列化 ≤60 份报告 JSON（`_agg_compute` 的 cards 段）。
    反向复用由调用方传参完成 —— `evidence_facets(graph=...)`。

    `unattributed` 显式报数：证据行没有目的地归属时，过去是两处各自 `continue`
    把它隐式抹掉（facets 的 SQL 排除空 + 情报页跳过空键），于是"63% 证据无目的地"
    这件事在 UI 上根本不存在。图谱把它算成一个字段，消费方再也藏不住。
    """
    c = _connect()
    rows = c.execute(
        "SELECT destination, COUNT(*) AS n, GROUP_CONCAT(DISTINCT source_type) AS st,"
        " AVG(credibility) AS avg_cred, MAX(captured_at) AS last_at"
        " FROM evidences GROUP BY destination"
    ).fetchall()
    nodes: List[Dict[str, Any]] = []
    scanned = 0
    unattributed = 0
    for r in rows:
        scanned += r["n"]
        if not r["destination"]:
            unattributed = r["n"]
            continue
        nodes.append(
            {
                "destination": r["destination"],
                # domain/source 是给「生活圈 POI 要不要进 evidences」留的形状：
                # 换输入源时节点形状与消费方都不动，不必二次重构。
                "domain": "travel",
                "source": "evidences",
                "count": r["n"],
                "source_types": sorted((r["st"] or "").split(",")),
                "avg_credibility": round(float(r["avg_cred"] or 0.0), 1),
                "last_at": r["last_at"],
            }
        )
    # 确定性名次：并列计数按目的地名升序，截断结果不随实现换血
    nodes.sort(key=lambda n: (-n["count"], n["destination"]))
    return {"nodes": nodes, "unattributed": unattributed, "scanned": scanned}


def evidence_facets(graph: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """证据库聚合：平台分布 / 目的地分布 / 总量。

    目的地分布**从 `destination_graph()` 派生**，不再自己写第二条 GROUP BY ——
    同一事实两份 SQL 会漂成两个口径（评审 R1）。`graph` 由 `_agg_compute()` 传入
    以复用整包已算好的那份；独立调用时自算一次（一条 GROUP BY 的成本，不触缓存）。
    """
    c = _connect()
    total = c.execute("SELECT COUNT(*) n FROM evidences").fetchone()["n"]
    by_type = {
        r["source_type"]: r["n"]
        for r in c.execute(
            "SELECT source_type, COUNT(*) n FROM evidences GROUP BY source_type"
        ).fetchall()
    }
    g = graph if graph is not None else destination_graph()
    by_destination = {n["destination"]: n["count"] for n in g["nodes"][:12]}
    return {"total": total, "by_type": by_type, "by_destination": by_destination}


# ── 调研统计（真实仪表盘）─────────────────────────────────
# G5：只读聚合缓存。dashboard_stats/intel_overview 每次调用都做全表 COUNT +
# 全量 intel 概览（读取全部报告 data 反序列化），高频读会放大 SQLite 读写放大。
# 加进程级只读缓存：写路径（save_report/delete_report/invalidate_report_brief/backfill）
# 经失效钩子 invalidate_aggregates() 淘汰，读命中直接返回深拷贝。缓存与库文件路径
# 无耦合——测试隔离库切换由 conftest autouse 夹具显式失效（B-06 契约守护）。
_AGG_CACHE: Optional[Dict[str, Any]] = None
_AGG_LOCK = threading.RLock()


def invalidate_aggregates() -> None:
    """聚合读缓存失效（幂等：无缓存时 no-op）。

    报告/证据写路径成功后必须调用，保证 dashboard_stats / intel_overview
    永远反映最新库状态；测试隔离夹具亦调用，防跨用例串库脏缓存。
    """
    global _AGG_CACHE
    with _AGG_LOCK:
        _AGG_CACHE = None


def _agg_compute() -> Dict[str, Any]:
    """一次算齐 intel 聚合（缓存缺失时重建；返回新结构，不耦合缓存本体）。

    dashboard 段自本轮起只剩侧栏真正消费的两个数（`layout/VSidebar.tsx` 读
    `reports` + `evidence_total`）：其余 11 个键此前没有任何生产消费者，却每次都
    拖着全量报告反序列化 —— 真分家就是把"仪表盘"和"情报中心"两份口径拆开。
    """
    c = _connect()
    reports = c.execute("SELECT COUNT(*) n FROM reports").fetchone()["n"]
    ev_total = c.execute("SELECT COUNT(*) n FROM evidences").fetchone()["n"]
    claim_total = c.execute("SELECT COALESCE(SUM(claim_count),0) n FROM reports").fetchone()["n"]
    high_total = c.execute("SELECT COALESCE(SUM(high_conf_count),0) n FROM reports").fetchone()["n"]
    graph = destination_graph()
    facets = evidence_facets(graph=graph)

    # intel_overview：跨报告聚合真实业务指标 + 每次调研的概览卡（供情报中心）
    rows = c.execute(
        "SELECT report_id,title,query,destinations,research_type,evidence_count,claim_count,"
        "high_conf_count,created_at,data FROM reports ORDER BY created_at DESC LIMIT 60"
    ).fetchall()
    cards: List[Dict[str, Any]] = []
    minutes_saved = 0.0
    eff_list: List[float] = []
    cov_list: List[float] = []
    total_tokens = 0
    for r in rows:
        try:
            data = json.loads(r["data"]) if r["data"] else {}
        except Exception:
            data = {}
        m = data.get("metrics") or {}
        eff = (m.get("efficiency") or {})
        cov = (m.get("coverage") or {})
        manual_min = float(eff.get("manual_estimate_minutes") or 0)
        elapsed_min = float(eff.get("elapsed_minutes") or 0)
        saved = max(0.0, manual_min - elapsed_min)
        minutes_saved += saved
        if eff.get("efficiency_multiple"):
            eff_list.append(float(eff["efficiency_multiple"]))
        if cov.get("coverage_multiple"):
            cov_list.append(float(cov["coverage_multiple"]))
        total_tokens += int(eff.get("tokens_used") or 0)
        cards.append({
            "id": r["report_id"],
            "title": r["title"],
            "query": r["query"],
            "destinations": json.loads(r["destinations"] or "[]"),
            "research_type": r["research_type"] or DEFAULT_RESEARCH_TYPE,
            "evidence_count": r["evidence_count"],
            "claim_count": r["claim_count"],
            "high_conf_count": r["high_conf_count"],
            "created_at": r["created_at"],
            "efficiency_multiple": eff.get("efficiency_multiple"),
            "coverage_multiple": cov.get("coverage_multiple"),
            "elapsed_minutes": eff.get("elapsed_minutes"),
            "minutes_saved": round(saved, 1),
            "tokens_used": eff.get("tokens_used"),
        })
    intel = {
        "report_total": reports,
        "evidence_total": ev_total,
        "claim_total": claim_total,
        "high_conf_total": high_total,
        "avg_evidence_per_report": round(ev_total / reports, 1) if reports else 0,
        # 真实事实准确率 = 高置信结论占比
        "fact_accuracy": round(high_total / claim_total * 100) if claim_total else 0,
        "minutes_saved": round(minutes_saved, 1),
        "avg_efficiency": round(sum(eff_list) / len(eff_list), 1) if eff_list else 0,
        "avg_coverage": round(sum(cov_list) / len(cov_list), 1) if cov_list else 0,
        "total_tokens": total_tokens,
        "cards": cards,
        # 概览卡受 LIMIT 60 约束：总数与卡片数同源报出，截断必须对用户可见，
        # 否则"共 26 份 / 表只 60 行"这类自相矛盾会重演本轮要消灭的截断样本形状。
        "cards_truncated": len(cards) < reports,
        "destination_graph": graph,
        "platform_distribution": facets["by_type"],
        # 口径变动必须可见：新类别一进库就改变整张饼图（全表实时聚合，不重算历史）。
        # 说明行只在真有用户指定信源时出现 —— 没填清单的任务不该看到一句无关的话。
        "user_source_evidence": facets["by_type"].get("user_supplied", 0),
        "distribution_note": (
            f"信源分布含用户指定信源 {facets['by_type'].get('user_supplied', 0)} 条"
            "（由调研时手填的网址直接抓取入库，计入占比与可信度口径）。"
            if facets["by_type"].get("user_supplied") else ""
        ),
    }
    return {
        "dashboard": {
            "reports": reports,
            "evidence_total": ev_total,
        },
        "intel": intel,
    }


def dashboard_stats() -> Dict[str, Any]:
    global _AGG_CACHE
    with _AGG_LOCK:
        if _AGG_CACHE is None:
            _AGG_CACHE = _agg_compute()
        return copy.deepcopy(_AGG_CACHE["dashboard"])


def intel_overview() -> Dict[str, Any]:
    global _AGG_CACHE
    with _AGG_LOCK:
        if _AGG_CACHE is None:
            _AGG_CACHE = _agg_compute()
        return copy.deepcopy(_AGG_CACHE["intel"])




# ── 目的地持续追踪订阅 ──────────────────────────────────
def create_subscription(sub_id: str, query: str, destinations: List[str],
                        research_type: str = DEFAULT_RESEARCH_TYPE,
                        source_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """建一条订阅。

    `source_urls` 是这条订阅的**用户指定信源清单**（计划 v3 §二 B8）：复跑必须带着它，
    否则同一主题第二次跑出来的报告不含用户钉的文档，两次的口径就不可比 ——
    而界面上看起来是同一个订阅。
    """
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO subscriptions(sub_id,query,destinations,type,created_at,"
            "last_run_at,last_report_id,run_count,source_urls) VALUES(?,?,?,?,?,?,?,?,?)",
            (sub_id, query, json.dumps(destinations, ensure_ascii=False),
             research_type or DEFAULT_RESEARCH_TYPE, _now(), "", "", 0,
             json.dumps(list(source_urls or []), ensure_ascii=False)),
        )
        c.commit()
    return get_subscription(sub_id) or {}


def _row_to_subscription(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["destinations"] = json.loads(d.get("destinations") or "[]")
    d["type"] = d.get("type") or DEFAULT_RESEARCH_TYPE
    # 旧库这一列可能为 NULL（建列之前已有的订阅）：回落成空清单，语义是"这条订阅没填过清单"
    raw = d.get("source_urls")
    d["source_urls"] = json.loads(raw) if raw else []
    return d


def list_subscriptions() -> List[Dict[str, Any]]:
    c = _connect()
    rows = c.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    return [_row_to_subscription(r) for r in rows]


def get_subscription(sub_id: str) -> Optional[Dict[str, Any]]:
    c = _connect()
    row = c.execute("SELECT * FROM subscriptions WHERE sub_id=?", (sub_id,)).fetchone()
    if not row:
        return None
    return _row_to_subscription(row)


def delete_subscription(sub_id: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM subscriptions WHERE sub_id=?", (sub_id,))
        c.commit()


def mark_subscription_run(sub_id: str, report_id: str) -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "UPDATE subscriptions SET last_run_at=?, last_report_id=?, run_count=run_count+1 WHERE sub_id=?",
            (_now(), report_id, sub_id),
        )
        c.commit()


# ── 专家工作量看板 ──────────────────────────────────────
def bump_expert_stats(
    expert_ids: List[str],
    claims_by_author: Optional[Dict[str, int]] = None,
    evidence_by_collector: Optional[Dict[str, int]] = None,
) -> None:
    claims_by_author = claims_by_author or {}
    evidence_by_collector = evidence_by_collector or {}
    ids = set(expert_ids) | set(claims_by_author) | set(evidence_by_collector)
    with _LOCK:
        c = _connect()
        for eid in ids:
            c.execute(
                "INSERT INTO expert_stats(expert_id,missions,claims_authored,evidence_collected,last_active)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(expert_id) DO UPDATE SET"
                " missions=missions+excluded.missions,"
                " claims_authored=claims_authored+excluded.claims_authored,"
                " evidence_collected=evidence_collected+excluded.evidence_collected,"
                " last_active=excluded.last_active",
                (
                    eid,
                    1 if eid in expert_ids else 0,
                    claims_by_author.get(eid, 0),
                    evidence_by_collector.get(eid, 0),
                    _now(),
                ),
            )
        c.commit()


def expert_workload() -> List[Dict[str, Any]]:
    c = _connect()
    rows = c.execute(
        "SELECT * FROM expert_stats ORDER BY missions DESC, claims_authored DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Trace（可观测性）──────────────────────────────────────
def save_traces(task_id: str, report_id: str, spans: List[Dict[str, Any]]) -> None:
    if not spans:
        return
    with _LOCK:
        c = _connect()
        for s in spans:
            c.execute(
                "INSERT OR REPLACE INTO traces(span_id,task_id,report_id,seq,agent_id,stage,"
                "purpose,model,prompt,response,prompt_tokens,completion_tokens,total_tokens,"
                "latency_ms,decision,evidence_ids,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    s.get("span_id"), task_id, report_id, s.get("seq", 0),
                    s.get("agent_id", ""), s.get("stage", ""), s.get("purpose", ""),
                    s.get("model", ""), (s.get("prompt", "") or "")[:2000],
                    (s.get("response", "") or "")[:2000],
                    s.get("prompt_tokens", 0), s.get("completion_tokens", 0),
                    s.get("total_tokens", 0), s.get("latency_ms", 0),
                    s.get("decision", ""), json.dumps(s.get("evidence_ids", []), ensure_ascii=False),
                    s.get("ts", _now()),
                ),
            )
        c.commit()


def get_traces_by_task(task_id: str) -> List[Dict[str, Any]]:
    c = _connect()
    rows = c.execute("SELECT * FROM traces WHERE task_id=? ORDER BY seq", (task_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence_ids"] = json.loads(d.get("evidence_ids") or "[]")
        out.append(d)
    return out


def get_traces_by_report(report_id: str) -> List[Dict[str, Any]]:
    c = _connect()
    rows = c.execute("SELECT * FROM traces WHERE report_id=? ORDER BY seq", (report_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence_ids"] = json.loads(d.get("evidence_ids") or "[]")
        out.append(d)
    return out


# ── 报告反馈（人工修正率）────────────────────────────────
def save_report_feedback(report_id: str, edited_blocks: int, total_blocks: int,
                         data: Dict[str, Any]) -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO report_feedback(report_id,edited_blocks,total_blocks,data,updated_at)"
            " VALUES(?,?,?,?,?)",
            (report_id, edited_blocks, total_blocks,
             json.dumps(data, ensure_ascii=False), _now()),
        )
        c.commit()


def get_report_feedback(report_id: str) -> Optional[Dict[str, Any]]:
    c = _connect()
    row = c.execute("SELECT * FROM report_feedback WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    return d


# ────────────────────────────────────────────────────────────── #
# 生活圈体检报告（living_circle 域独立表；M2-flip 自 skip 摘取合并）
# ────────────────────────────────────────────────────────────── #

def get_report_legacy(report_id: str) -> Optional[Dict[str, Any]]:
    """[已废弃] 旧版 get_report，仅查 reports 表。保留用于向后兼容。"""
    c = _connect()
    row = c.execute("SELECT data FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    try:
        evs = list(query_evidences(report_id=report_id))
    except Exception:
        evs = []
    if evs:
        data["evidence"] = evs
    return data



def save_living_circle_report(report: Dict[str, Any], scene_key: str = "") -> None:
    """落库一份生活圈体检报告（幂等：按 report_id INSERT OR REPLACE）。

    P0-2：离线估算报告（data_origin='offline'）不产出可比评分 → total_score 存 NULL，
    历史/对比对 offline 显示「离线估算」而非 0 分。
    """
    lc = report.get("living_circle") or {}
    scene = lc.get("scene") or {}
    scores = lc.get("scores") or {}
    is_offline = lc.get("data_origin") == "offline"
    total_score = None if is_offline else float(scores.get("total", 0) or 0)
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO living_circle_reports(report_id,scene_key,scene_name,data,"
            "data_origin,total_score,blindspot_count,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                report["id"],
                scene_key,
                scene.get("name", ""),
                json.dumps(report, ensure_ascii=False),
                lc.get("data_origin", ""),
                total_score,
                len(lc.get("blindspots") or []),
                report.get("created_at", _now()),
            ),
        )
        c.commit()


def get_living_circle_report(report_id: str) -> Optional[Dict[str, Any]]:
    """读取完整体检报告（含 living_circle 挂载的 Report 结构）。

    读路径幂等归一化（盲区表征契约升级的架构兜底，见「盲区表征重构-实施计划」§8）：
    当报告中盲区为**旧 schema**（缺 ``severity/gap_score/fixes/reach/affected``）时，
    用 ``annotate_blindspots`` 按报告中已实测的采样点补齐——让历史存量报告与新建报告
    呈现一致的严重度分档/连续缺口/补点处方/真实可达/受估人群，避免演示与实时口径断裂。
    新 schema 报告已是全量，重放幂等（仅按当前采样态重算 reach/affected，语义不变）。
    """
    c = _connect()
    row = c.execute("SELECT data FROM living_circle_reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return None
    lc = data.get("living_circle")
    if isinstance(lc, dict):
        bs = lc.get("blindspots")
        need = isinstance(bs, list) and any(
            not isinstance(b, dict) or not b.get("severity") for b in bs
        )
        if need:
            from app.living_circle.assemble import annotate_blindspots

            data["living_circle"] = annotate_blindspots(lc)
    return data


def list_living_circle_reports(limit: int = 50, include_incomplete: bool = False) -> List[Dict[str, Any]]:
    """历史体检记录列表（短字段，对齐前端 LifeCircleRecord）。

    ``include_incomplete=False``（默认）时**跳过不合几何契约的报告** —— 两类会被挡住：

    - **内容缺件**：如 ``lc-c796c62d``（迤栖村）``isochrones`` 空 / POI 空 / 0 分；
    - **几何不自洽**：如 ``lc-d3cfa371`` 盲区 29.13km²（= 整张 5.4km 判定网格）、
      151 个点位里 133 个在圈外；以及 3 份 ``fixture_sample`` 老快照。

    这些报告在库中**保留**（只隐藏，不删除），只是不再出现在用户可见列表里
    （旧版代码签发过它们，读路径必须挡住）。

    判据与写路径**同源**（``living_circle.report_contract.assess_geometry``），
    避免「写路径收紧了、读路径还按老口径放行」的漂移。审计/体检脚本可传
    ``include_incomplete=True`` 全量取。

    > 「陈旧快照」不需要额外状态位：老夹具几何必违反「盲区 ⊆ 可达区」、旧算法 live
    > 报告必缺 ``caliber`` 口径声明 —— 隐藏与否是**几何契约的派生结论**。
    """
    from app.living_circle.report_contract import assess_geometry

    c = _connect()
    rows = c.execute(
        "SELECT report_id, scene_key, scene_name, data_origin, total_score, blindspot_count, created_at"
        # 二级排序 rowid DESC：`created_at` 只到秒（`_now()`），同秒落库的多份报告没有可比
        # 时间键 ⇒ 单按 created_at 排时 SQLite 退化成 rowid 升序，`LIMIT` 窗口会把**刚签发的
        # 那份**挤出去（历史列表看不见最新报告）。补上后"后落的排前面"才是确定的。
        " FROM living_circle_reports ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    hidden: List[str] = []
    for r in rows:
        d = dict(r)
        data = get_living_circle_report(d["report_id"]) or {}
        lc = data.get("living_circle") or {}
        scene = lc.get("scene") or {}
        if not include_incomplete:
            issues = assess_geometry(lc)
            if not issues.ok:
                hidden.append(f"{d['report_id']}({issues.reason})")
                continue
        out.append({
            "id": d["report_id"],
            "title": data.get("title", f"{d['scene_name']} · 生活圈体检报告"),
            "scene_name": d["scene_name"] or scene.get("name", ""),
            "city": scene.get("city", ""),
            "checked_at": d["created_at"],
            # P0-2：offline 报告 total_score 为 NULL → 透传 null（前端显示「离线估算」），不伪造 0 分
            "total_score": d["total_score"],
            "blindspot_count": int(d["blindspot_count"] or 0),
            "data_origin": d["data_origin"] or lc.get("data_origin", ""),
            "interpolation": (lc.get("sampling") or {}).get("interpolation", "circular_approx"),
            # R-7(q-3)：降级成因必须随列表下发。否则历史列表里「离线估算」同样分不清
            # 「本来就没联网」和「配额被掐断」，用户在找旧报告的地方反而看不到成因。
            # 整节点透传（前端用 `degradeDetailLabel()` 取标签，不在消费点自己 switch）。
            "degraded": lc.get("degraded") or None,
        })
    if hidden:
        # 不静默：隐藏了哪些、为什么，逐条留痕（数据仍在库中，可用 include_incomplete=True 取回）
        logging.getLogger(__name__).warning(
            "list_living_circle_reports 隐藏 %d 条不合几何契约的报告（保留未删除）：%s",
            len(hidden),
            "; ".join(hidden),
        )
    return out


def delete_living_circle_report(report_id: str) -> bool:
    """删除一份生活圈体检报告，并按 `delete_report` 同一份级联清单清理派生行。

    级联不是"以后才有用"：`POST /api/reports/{id}/feedback`（main.py:582）不按报告类型
    分流，生活圈报告 id 同样会写出 `report_feedback` 行 —— 今天删报告就会留孤儿。
    `evidences` / `traces` 目前只有调研流水线写（engine.py:1595、save_report:711-723），
    但生活圈证据一旦入库（计划 v4 待拍板⑤），缺了这条级联会让 `evidence_total` 与
    `by_destination` 永久虚高，而"计数随报告单调增长"那类断言照样会绿。
    """
    with _LOCK:
        c = _connect()
        _delete_report_scoped_rows(c, report_id)
        cur = c.execute("DELETE FROM living_circle_reports WHERE report_id=?", (report_id,))
        c.commit()
        # G5 失效钩子：与 delete_report 对称 —— 级联删的是聚合的输入
        invalidate_aggregates()
        return cur.rowcount > 0


def delete_living_circle_reports_for_scene(scene_key: str) -> int:
    """删除同一 scene_key 的全部旧报告（v5 D21/R1 补实现）。

    ``_finalize_living_report(replace_scene=True)``（精报替换粗报）依赖此函数，
    但此前全库无定义 → 潜伏 AttributeError。与 save/list 同锁、逐行清关联任务，
    保证「同场景仅保留最新」的写路径语义与并发安全一致。
    """
    with _LOCK:
        c = _connect()
        rows = c.execute("SELECT report_id FROM living_circle_reports WHERE scene_key=?", (scene_key,)).fetchall()
        ids = [r["report_id"] for r in rows]
        for rid in ids:
            # 与单份删除同一份级联清单：精报替换粗报每轮都跑这里，
            # 只清 tasks 会让 feedback（以及将来的证据行）按替换次数线性泄漏。
            _delete_report_scoped_rows(c, rid)
        cur = c.execute("DELETE FROM living_circle_reports WHERE scene_key=?", (scene_key,))
        c.commit()
        if ids:
            invalidate_aggregates()   # 幂等：没删到行就不必惊动缓存
        return cur.rowcount


def get_latest_report_id_for_scene(scene_key: str) -> Optional[str]:
    """解析 scene_key 下**最新**报告 id（v5 D22/R2 新增，E2 缓存命中幂等收尾用）。

    读路径唯一收口：不把 report_id 塞进缓存条目（避免缓存/落库两处维护 id），
    db 为唯一事实源。无记录返回 None。
    """
    if not scene_key:
        return None
    c = _connect()
    row = c.execute(
        "SELECT report_id FROM living_circle_reports WHERE scene_key=? ORDER BY created_at DESC LIMIT 1",
        (scene_key,),
    ).fetchone()
    return row["report_id"] if row else None
