"""测时 / POI 缓存抽象（A5 repository 收敛）。

原则：存储介质由调用方（M2 pipeline 接线）注入 —— 本模块只定义协议与两种可测实现：
  - MemoryCache：进程级内存缓存（默认，演示/单测够用）
  - SqliteCache：可选落盘实现（注入 sqlite3 连接/路径，供 M 阶段使用）
缓存键一律带 `data_mode` 前缀（A3：防 live/fixture 串数据）。
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


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
    """测时 / POI 结果仓库（data_mode 前缀隔离）。"""

    def __init__(self, backend: Optional[CacheBackend] = None, default_ttl_s: float = 86400.0) -> None:
        self._backend = backend or MemoryCache()
        self.default_ttl = default_ttl_s

    # ── 采样测时缓存 ────────────────────────────────────
    def cache_samples(self, data_mode: str, scene_payload: str, points: list) -> None:
        key = CacheKey(data_mode, "sampling", scene_payload).key()
        self._backend.set(key, {"points": points}, self.default_ttl)

    def get_samples(self, data_mode: str, scene_payload: str) -> Optional[list]:
        key = CacheKey(data_mode, "sampling", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("points") if hit else None

    # ── POI 分类缓存 ────────────────────────────────────
    def cache_poi(self, data_mode: str, scene_payload: str, categories: list) -> None:
        key = CacheKey(data_mode, "poi", scene_payload).key()
        self._backend.set(key, {"categories": categories}, self.default_ttl)

    def get_poi(self, data_mode: str, scene_payload: str) -> Optional[list]:
        key = CacheKey(data_mode, "poi", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("categories") if hit else None

    # ── 整份体检结果缓存（同中心秒开 + 强制重算）─────────
    def cache_report(self, data_mode: str, scene_payload: str, report: Dict[str, Any]) -> None:
        key = CacheKey(data_mode, "report", scene_payload).key()
        self._backend.set(key, {"report": report}, self.default_ttl)

    def get_report(self, data_mode: str, scene_payload: str) -> Optional[Dict[str, Any]]:
        key = CacheKey(data_mode, "report", scene_payload).key()
        hit = self._backend.get(key)
        return hit.get("report") if hit else None