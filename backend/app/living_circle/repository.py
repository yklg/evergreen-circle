"""测时 / POI 缓存抽象（A5 repository 收敛）。

原则：存储介质由调用方（M2 pipeline 接线）注入 —— 本模块只定义协议与两种可测实现：
  - MemoryCache：进程级内存缓存（默认，演示/单测够用）
  - SqliteCache：SQLite 落盘实现（独立 `lc_cache.db`，WAL + busy_timeout，跨进程/重启持久，
    T2 实时结果沉淀离线复用；参考标准 PRAGMA：journal_mode=WAL / synchronous=NORMAL / busy_timeout=5000）
缓存键一律带 `data_mode` 前缀（A3：防 live/fixture 串数据）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# 默认缓存 TTL（T2：实时报告 30 天 → 任意地区离线可查；采样/POI 7 天）
DEFAULT_REPORT_TTL_S = 30 * 24 * 3600.0
DEFAULT_AUX_TTL_S = 7 * 24 * 3600.0


class CacheBackend(ABC):
    """存储后端协议（注入点）：get/set/delete。"""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl_s: float) -> None:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...


class MemoryCache(CacheBackend):
    """进程级内存缓存（默认实现）。"""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._expiry: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        exp = self._expiry.get(key)
        if exp is not None and exp < time.time():
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._store.get(key)

    def set(self, key: str, value: Dict[str, Any], ttl_s: float) -> None:
        self._store[key] = value
        self._expiry[key] = time.time() + max(ttl_s, 0.0)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._expiry.pop(key, None)


class SqliteCache(CacheBackend):
    """SQLite 落盘缓存（T2，P0-3 并发安全）。

    - 独立库文件 `lc_cache.db`（不混入业务库，缓存可随时删除）；
    - 每操作短连接（sqlite 连接不可跨线程）+ WAL/busy_timeout/synchronous=NORMAL（标准并发配置）；
    - 值以 JSON 序列化落 TEXT 列，expire_at 过期惰性清理。
    """

    def __init__(self, path: str | Path = "lc_cache.db") -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS lc_cache("
                    " key TEXT PRIMARY KEY, value TEXT NOT NULL, expire_at REAL NOT NULL)"
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT value FROM lc_cache WHERE key=? AND expire_at>?", (key, now)
                ).fetchone()
                if row is None:
                    # 惰性清理过期行
                    conn.execute("DELETE FROM lc_cache WHERE expire_at<=?", (now,))
                    conn.commit()
                    return None
                return json.loads(row["value"])
            except (json.JSONDecodeError, sqlite3.Error):  # noqa: BLE001
                return None
            finally:
                conn.close()

    def set(self, key: str, value: Dict[str, Any], ttl_s: float) -> None:
        expire_at = time.time() + max(ttl_s, 0.0)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO lc_cache(key,value,expire_at) VALUES(?,?,?)",
                    (key, json.dumps(value, ensure_ascii=False), expire_at),
                )
                conn.commit()
            except sqlite3.Error:  # noqa: BLE001
                pass
            finally:
                conn.close()

    def delete(self, key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM lc_cache WHERE key=?", (key,))
                conn.commit()
            except sqlite3.Error:  # noqa: BLE001
                pass
            finally:
                conn.close()


@dataclass(frozen=True)
class CacheKey:
    """缓存键（业务语义 → 散列）。"""

    data_mode: str  # 'live' | 'fixture'
    kind: str
    payload: str  # 场景/参数序列化（center+study_radius+模式）

    def key(self) -> str:
        digest = hashlib.sha256(self.payload.encode("utf-8")).hexdigest()[:16]
        return f"{self.data_mode}:{self.kind}:{digest}"


class Repository:
    """测时 / POI 结果仓库（data_mode 前缀隔离）。

    TTL 按数据价值分级：整份报告 30 天（离线可查）、采样/POI 7 天。
    """

    def __init__(self, backend: Optional[CacheBackend] = None, default_ttl_s: float = DEFAULT_REPORT_TTL_S) -> None:
        self._backend = backend or MemoryCache()
        self.default_ttl = default_ttl_s

    # ── 采样测时缓存（7 天）────────────────────────────
    def cache_samples(self, data_mode: str, scene_payload: str, points: list) -> None:
        key = CacheKey(data_mode, "sampling", scene_payload).key()
        self._backend.set(key, {"points": points}, DEFAULT_AUX_TTL_S)

    def get_samples(self, data_mode: str, scene_payload: str) -> Optional[list]:
        key = CacheKey(data_mode, "sampling", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("points") if hit else None

    # ── POI 分类缓存（7 天）────────────────────────────
    def cache_poi(self, data_mode: str, scene_payload: str, categories: list) -> None:
        key = CacheKey(data_mode, "poi", scene_payload).key()
        self._backend.set(key, {"categories": categories}, DEFAULT_AUX_TTL_S)

    def get_poi(self, data_mode: str, scene_payload: str) -> Optional[list]:
        key = CacheKey(data_mode, "poi", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("categories") if hit else None

    # ── 整份体检结果缓存（30 天：同中心秒开 + 离线可查 + 强制重算）──
    def cache_report(self, data_mode: str, scene_payload: str, report: Dict[str, Any]) -> None:
        key = CacheKey(data_mode, "report", scene_payload).key()
        self._backend.set(key, {"report": report}, self.default_ttl)

    def get_report(self, data_mode: str, scene_payload: str) -> Optional[Dict[str, Any]]:
        key = CacheKey(data_mode, "report", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("report") if hit else None