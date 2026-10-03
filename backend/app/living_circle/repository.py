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
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.living_circle.geo_utils import haversine_m

logger = logging.getLogger(__name__)

# 默认缓存 TTL（T2：实时报告 30 天 → 任意地区离线可查；采样/POI 7 天）
DEFAULT_REPORT_TTL_S = 30 * 24 * 3600.0
DEFAULT_AUX_TTL_S = 7 * 24 * 3600.0

# 缓存库落盘位置：默认 `app/lc_cache.db`（现役行为），可用 LC_CACHE_PATH 指向别处。
# 为什么要有这颗开关 —— 报告缓存的键只含「场景名 + 中心 + 半径 + 档位 + 出行方式」，
# **不含检索词表**，所以改 `CATEGORY_RULES` 的词表不会让它自动失效：同参重跑必命中 30 天
# 内的旧载荷（`snapshot_live` 重采演示夹具时就撞上过：一次外呼都不发、把补词前的数据写回夹具）。
# 空串按「没设」处理，与 `core.db` 的 VERDA_DB_PATH 同形状。
CACHE_PATH_ENV = "LC_CACHE_PATH"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "lc_cache.db"


def resolve_cache_path() -> Path:
    """本次进程该用哪个缓存库文件（不设 `LC_CACHE_PATH` 时 = :data:`DEFAULT_CACHE_PATH`）。"""
    override = os.environ.get(CACHE_PATH_ENV)
    return Path(override) if override else DEFAULT_CACHE_PATH


class CacheBackend(ABC):
    """存储后端协议（注入点）：get/set/delete/scan。"""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl_s: float) -> None:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def scan(self, prefix: str) -> List[Tuple[str, Dict[str, Any]]]:
        """按键前缀扫未过期条目（邻近缓存 R5/D25：SQL 预过滤，JSON 只解析候选行）。"""


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

    def scan(self, prefix: str) -> List[Tuple[str, Dict[str, Any]]]:
        now = time.time()
        out: List[Tuple[str, Dict[str, Any]]] = []
        expired: List[str] = []
        for key, val in self._store.items():
            if not key.startswith(prefix):
                continue
            exp = self._expiry.get(key)
            if exp is not None and exp < now:
                expired.append(key)
                continue
            out.append((key, val))
        # 惰性清理推迟到迭代结束后执行，避免"dict changed size during iteration"
        for key in expired:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
        return out


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

    def scan(self, prefix: str) -> List[Tuple[str, Dict[str, Any]]]:
        """SQL 预过滤（key LIKE + 未过期），JSON 仅解析候选行（D25/R5）。

        邻近缓存查询变高频后，不能全表拉 value 再逐个 json.loads ——
        LIKE 前缀 + expire_at 下推给 SQLite，返回的已是候选行。
        """
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT key, value FROM lc_cache WHERE key LIKE ? AND expire_at>?",
                    (prefix + "%", now),
                ).fetchall()
                out: List[Tuple[str, Dict[str, Any]]] = []
                for r in rows:
                    try:
                        out.append((r["key"], json.loads(r["value"])))
                    except (json.JSONDecodeError, TypeError):  # noqa: BLE001
                        continue
                return out
            except sqlite3.Error:  # noqa: BLE001
                return []
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
        """写整份报告缓存。

        ⚠️ **全项目唯一出口**：「live 命名空间不得装 offline 报告」这条不变量**只在这里拦**。
        起因（架构评审 P0-2）：三个入口（pipeline backfill / LiveDataSource.compute /
        refine_live_with_profile）各抄了一份 `if data_origin != "offline"` —— 三份**全是死代码**
        （降级分支都提前 return，永远走不到），却让人误以为「已有三道门」。收敛到唯一写入者后：
        ① 规则只有一份；② 任何**新入口**（不只这三个）一旦把离线产物塞进 live，都会被拦。
        拒绝而非抛错：抛错会让「已经降级的任务」再崩一次；ERROR 日志保证不静默（D9 诚实性）。
        """
        if data_mode == "live" and (report or {}).get("data_origin") == "offline":
            logger.error(
                "拒绝把离线报告写进 live 缓存（key=%s）：后续同中心/邻近请求会命中离线口径",
                scene_payload,
            )
            return
        key = CacheKey(data_mode, "report", scene_payload).key()
        self._backend.set(key, {"report": report}, self.default_ttl)

    def get_report(self, data_mode: str, scene_payload: str) -> Optional[Dict[str, Any]]:
        key = CacheKey(data_mode, "report", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("report") if hit else None

    # ── 邻近报告检索（O1/D25：SQL 预过滤 + 距离过滤，取最近）──
    def find_recent_report_near(
        self,
        data_mode: str,
        center: Tuple[float, float],
        radius_m: float,
    ) -> Optional[Dict[str, Any]]:
        """按中心点找**最近**一份未过期实时报告（距离 < radius_m）。

        - 键前缀 + 过期时间下推给后端（`scan`，D25：SQL 预过滤，JSON 只解析候选行）；
        - 候选行里取 haversine 距离最小者——邻近缓存命中保持「原中心语义」
          （报告的 center 是原中心，横幅明示，D9）。
        - 无候选 / 全部超距 → None。
        """
        best: Optional[Dict[str, Any]] = None
        best_d = radius_m
        for _key, val in self._backend.scan(f"{data_mode}:report:"):
            report = val.get("report") if isinstance(val, dict) else None
            if not isinstance(report, dict):
                continue
            sc = report.get("scene") or {}
            c = sc.get("center")
            if not c or len(c) != 2:
                continue
            try:
                d = haversine_m((float(c[0]), float(c[1])), center)
            except (TypeError, ValueError):  # noqa: BLE001  脏中心不阻断邻近检索
                continue
            if d < best_d:
                best_d = d
                best = report
        return best