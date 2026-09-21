"""SQLite 持久化层（真实落盘，切页面/刷新/重启都在）。

存储：调研任务 / 报告 / 证据溯源 / 竞品监控订阅 / 专家工作量
      + 系统级运行时配置覆盖（settings 表）/ 用户级偏好（prefs 表）。
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
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


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
            brands TEXT,
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
            brand TEXT,
            captured_at TEXT
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            sub_id TEXT PRIMARY KEY,
            query TEXT,
            brands TEXT,
            created_at TEXT,
            last_run_at TEXT,
            last_report_id TEXT,
            run_count INTEGER
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
        CREATE TABLE IF NOT EXISTS competitor_discovery_cache (
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
            ("purpose", "TEXT"),
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

    # 启动回填：存量报告证据写进 evidences 表（单一真相源），幂等。
    # 注意：必须先置 _SCHEMA_READY=True 再调 backfill——否则 backfill 内部的
    # _connect() 会再次触发 _ensure_schema → 重入 _init_schema → 无限递归卡死。
    global _SCHEMA_READY
    _SCHEMA_READY = True
    try:
        backfill_evidences_from_reports()
    except sqlite3.Error:
        pass


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


# ── 任务 ────────────────────────────────────────────────
def save_task(task_id: str, query: str, clarifications: Dict[str, Any], kind: str = "research", purpose: str = "") -> None:
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO tasks(task_id,query,clarifications,status,created_at,report_id,kind,purpose)"
            " VALUES(?,?,?,?,?,COALESCE((SELECT report_id FROM tasks WHERE task_id=?),NULL),?,?)",
            (task_id, query, json.dumps(clarifications, ensure_ascii=False), "created", _now(), task_id, kind, purpose),
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


# ── 竞品发现缓存（按 query 哈希，TTL 过期；仅缓存成功发现，兜底结果不缓存）──
def _query_hash(query: str) -> str:
    """归一化（去空白、转小写）后 sha256，作为发现缓存键。"""
    import hashlib

    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()


def get_discovery_cache(qhash: str) -> Optional[Dict[str, Any]]:
    """读取未过期的竞品发现缓存；过期/缺失返回 None。"""
    c = _connect()
    row = c.execute(
        "SELECT payload, expires_at FROM competitor_discovery_cache WHERE qhash=?",
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
    """写入竞品发现缓存（带过期时间）。幂等（INSERT OR REPLACE）。"""
    from datetime import timedelta

    exp = (_dt.datetime.now() + timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = json.dumps(scope, ensure_ascii=False)
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO competitor_discovery_cache(qhash,payload,expires_at,created_at)"
            " VALUES(?,?,?,?)",
            (qhash, payload, exp, _now()),
        )
        c.commit()


def clear_discovery_cache() -> None:
    """清空竞品发现缓存（测试隔离 / 手动刷新用）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM competitor_discovery_cache")
        c.commit()


# ── 澄清问卷（懒生成，SSE 推送给前端）─────────────────────
def save_clarify_questions(
    task_id: str, questions: List[Dict[str, Any]], complete: bool = True
) -> None:
    """落库懒生成的澄清问卷；payload 统一为 {"questions": [...], "complete": bool}。

    complete 仅当整份问卷（含竞品发现）已就绪时为 True；partial（仅基础题）绝不落库，
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
            "INSERT OR REPLACE INTO reports(report_id,task_id,title,subtitle,query,brands,experts,"
            "cover_image,data,evidence_count,claim_count,high_conf_count,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                report["id"], task_id, report.get("title", ""), report.get("subtitle", ""),
                report.get("query", ""), json.dumps(report.get("brands", []), ensure_ascii=False),
                json.dumps(report.get("experts", []), ensure_ascii=False),
                report.get("cover_image", ""), json.dumps(report, ensure_ascii=False),
                len(evidence), len(claims), high, report.get("created_at", _now()),
            ),
        )
        # 证据溯源单独入库，供全局证据库检索
        for ev in evidence:
            c.execute(
                "INSERT OR REPLACE INTO evidences(evidence_id,report_id,source_url,source_type,"
                "domain,title,excerpt,credibility,collected_by,brand,captured_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev.get("evidence_id"), report["id"], ev.get("source_url", ""),
                    ev.get("source_type", ""), ev.get("domain", ""), ev.get("title", ""),
                    ev.get("excerpt", "")[:500], ev.get("credibility", 0.0),
                    ev.get("collected_by", ""), ev.get("brand", ""), ev.get("captured_at", _now()),
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
                    "credibility,collected_by,brand,captured_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        eid, rid, ev.get("source_url", ""), ev.get("source_type", ""),
                        ev.get("domain", ""), ev.get("title", ""),
                        (ev.get("excerpt", "") or "")[:500], ev.get("credibility", 0.0),
                        ev.get("collected_by", ""), ev.get("brand", ""),
                        ev.get("captured_at", _now()),
                    ),
                )
        c.commit()
        invalidate_aggregates()


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    """统一报告读取入口（Phase 8：双引擎合并到单源）。

    行为：
      - 先查 reports 表（竞品调研报告）；
      - 若未找到且 report_id 以 "lc-" 开头，查 living_circle_reports 表（生活圈体检报告）；
      - 实时派生 evidence 数组（单一真相源）；
      - 生活圈报告自动补齐盲区表征（annotate_blindspots）。
      
    此函数是唯一的报告读取入口，所有 API 路由应调用它而非分别调用 get_report/get_living_circle_report。
    """
    c = _connect()
    
    # 1. 先查通用报告表
    row = c.execute("SELECT data FROM reports WHERE report_id=?", (report_id,)).fetchone()
    if row:
        data = json.loads(row["data"])
        try:
            evs = list(query_evidences(report_id=report_id))
        except Exception:
            evs = []
        if evs:
            data["evidence"] = evs
        return data
    
    # 2. 若未找到，尝试生活圈体检报告表
    row = c.execute("SELECT data FROM living_circle_reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        return None
    
    try:
        data = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return None
    
    # 生活圈报告：补齐盲区表征（幂等，仅对旧 schema 生效）
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


def list_reports() -> List[Dict[str, Any]]:
    """报告卡片列表（不含全文 data，省带宽）。"""
    c = _connect()
    rows = c.execute(
        "SELECT report_id,title,subtitle,query,brands,experts,cover_image,"
        "evidence_count,claim_count,high_conf_count,created_at FROM reports ORDER BY created_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = d["report_id"]
        d["brands"] = json.loads(d.get("brands") or "[]")
        d["experts"] = json.loads(d.get("experts") or "[]")
        out.append(d)
    return out


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
        c.execute("DELETE FROM evidences WHERE report_id=?", (report_id,))
        c.execute("DELETE FROM traces WHERE report_id=?", (report_id,))
        c.execute("DELETE FROM report_feedback WHERE report_id=?", (report_id,))
        c.execute("DELETE FROM tasks WHERE report_id=?", (report_id,))
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
    brand: Optional[str] = None,
    source_type: Optional[str] = None,
    min_cred: float = 0.0,
    limit: int = 200,
    report_id: Optional[str] = None,
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
    if brand:
        sql += " AND brand=?"
        args.append(brand)
    if source_type:
        sql += " AND source_type=?"
        args.append(source_type)
    sql += " ORDER BY credibility DESC, captured_at DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def evidence_facets() -> Dict[str, Any]:
    """证据库聚合：平台分布 / 品牌分布 / 总量。"""
    c = _connect()
    total = c.execute("SELECT COUNT(*) n FROM evidences").fetchone()["n"]
    by_type = {
        r["source_type"]: r["n"]
        for r in c.execute(
            "SELECT source_type, COUNT(*) n FROM evidences GROUP BY source_type"
        ).fetchall()
    }
    by_brand = {
        r["brand"]: r["n"]
        for r in c.execute(
            "SELECT brand, COUNT(*) n FROM evidences"
            " WHERE brand!='' GROUP BY brand ORDER BY n DESC LIMIT 12"
        ).fetchall()
    }
    return {"total": total, "by_type": by_type, "by_brand": by_brand}


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
    """一次算齐 dashboard + intel 聚合（缓存缺失时重建；返回新结构，不耦合缓存本体）。"""
    c = _connect()
    reports = c.execute("SELECT COUNT(*) n FROM reports").fetchone()["n"]
    ev_total = c.execute("SELECT COUNT(*) n FROM evidences").fetchone()["n"]
    claim_total = c.execute("SELECT COALESCE(SUM(claim_count),0) n FROM reports").fetchone()["n"]
    high_total = c.execute("SELECT COALESCE(SUM(high_conf_count),0) n FROM reports").fetchone()["n"]
    avg_ev = round(ev_total / reports, 1) if reports else 0
    # 真实事实准确率 = 高置信结论占比
    fact_rate = round(high_total / claim_total * 100) if claim_total else 0
    facets = evidence_facets()

    # intel_overview：跨报告聚合真实业务指标 + 每次调研的概览卡（供情报中心）
    rows = c.execute(
        "SELECT report_id,title,query,brands,evidence_count,claim_count,"
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
            "brands": json.loads(r["brands"] or "[]"),
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
        "minutes_saved": round(minutes_saved, 1),
        "avg_efficiency": round(sum(eff_list) / len(eff_list), 1) if eff_list else 0,
        "avg_coverage": round(sum(cov_list) / len(cov_list), 1) if cov_list else 0,
        "total_tokens": total_tokens,
        "cards": cards,
    }
    return {
        "dashboard": {
            "reports": reports,
            "evidence_total": ev_total,
            "claim_total": claim_total,
            "high_conf_total": high_total,
            "avg_evidence_per_report": avg_ev,
            "fact_accuracy": fact_rate,
            "platform_distribution": facets["by_type"],
            "brand_distribution": facets["by_brand"],
            "minutes_saved": intel["minutes_saved"],
            "avg_efficiency": intel["avg_efficiency"],
            "avg_coverage": intel["avg_coverage"],
            "total_tokens": intel["total_tokens"],
            "research_cards": intel["cards"],
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




# ── 竞品监控订阅 ────────────────────────────────────────
def create_subscription(sub_id: str, query: str, brands: List[str]) -> Dict[str, Any]:
    with _LOCK:
        c = _connect()
        c.execute(
            "INSERT OR REPLACE INTO subscriptions(sub_id,query,brands,created_at,last_run_at,last_report_id,run_count)"
            " VALUES(?,?,?,?,?,?,?)",
            (sub_id, query, json.dumps(brands, ensure_ascii=False), _now(), "", "", 0),
        )
        c.commit()
    return get_subscription(sub_id) or {}


def list_subscriptions() -> List[Dict[str, Any]]:
    c = _connect()
    rows = c.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["brands"] = json.loads(d.get("brands") or "[]")
        out.append(d)
    return out


def get_subscription(sub_id: str) -> Optional[Dict[str, Any]]:
    c = _connect()
    row = c.execute("SELECT * FROM subscriptions WHERE sub_id=?", (sub_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["brands"] = json.loads(d.get("brands") or "[]")
    return d


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


# ── 生活圈体检报告（A1 独立文档，report_type 弱关联回 Report）───────────
# 与 reports 表刻意分离：体检报告 body 整体序列化进本表 data 列；
# 前端 ReportPage 用渲染适配器（report_type）分发，不出现在旧 reports 列表。
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
        " FROM living_circle_reports ORDER BY created_at DESC LIMIT ?",
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
    """删除体检报告并级联清理关联任务（report_id 弱关联）。"""
    with _LOCK:
        c = _connect()
        c.execute("DELETE FROM tasks WHERE report_id=?", (report_id,))
        cur = c.execute("DELETE FROM living_circle_reports WHERE report_id=?", (report_id,))
        c.commit()
        return cur.rowcount > 0
