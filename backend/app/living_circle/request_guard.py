"""百度调用韧性层（并发信号量 + 级间限速 + 指数退避 + 失败率监控）。

职责边界（A3 数据源与韧性分离）：
  - 只负责「真实调用的并发/限速/重试/监控」，**不含业务快照或 fixture 回退**；
    数据源选择（live/fixture）与回退由 `data_source.py` 决定。
  - 重试判定依据百度协议：HTTP 层异常、status!=0、显式 429/配额类错误码。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# 百度 place/v2/search 的配额类状态码（个人免费额度）：
# 401 AK 无效 / 402 AK 被禁用 /403 配额超限 / 4xx 权限, 另有 100~ 业务码。
RATE_LIMIT_STATUS = {401, 402, 403, 404, 429}


@dataclass
class GuardStats:
    """调用总览（成功/失败/重试/退避次数），供可观测性面板与诊断。"""

    ok: int = 0
    fail: int = 0
    retried: int = 0
    backed_off: int = 0
    last_error: str = ""
    started_at: float = field(default_factory=time.time)

    def success_rate(self) -> float:
        total = self.ok + self.fail
        return self.ok / total if total else 1.0


class CallGuard:
    """包装异步 HTTP 工作单元：限并发 + 限速 + 退避重试。

    用法：
        guard = CallGuard(max_concurrency=4, min_interval_s=0.05, max_retries=2)
        resp = await guard.call(lambda: client.get_place(...))   # resp 为 dict
    判定重试：callable 返回 dict 时按 status 字段（0=成功/非 0=业务错误）判定；
    抛异常（网络/超时）也可选重试。
    """

    def __init__(
        self,
        max_concurrency: int = 4,
        min_interval_s: float = 0.25,
        max_retries: int = 4,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 12.0,
        timeout_s: float = 12.0,
    ) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)
        self.min_interval = min_interval_s
        self.max_retries = max_retries
        self.backoff_base = backoff_base_s
        self.backoff_max = backoff_max_s
        self.timeout_s = timeout_s
        self.stats = GuardStats()
        self._last_call_ts: float = 0.0
        self._interval_lock = asyncio.Lock()

    async def _pace(self) -> None:
        """级间最小间隔（限速），防止瞬时打爆个人免费额度。"""
        async with self._interval_lock:
            now = time.monotonic()
            wait = self._last_call_ts + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = time.monotonic()

    @staticmethod
    def _is_biz_error(resp: Any) -> Optional[str]:
        """按百度协议判定业务层是否失败；返回错误信息（无则 None）。"""
        if not isinstance(resp, dict):
            return None
        status = resp.get("status")
        if status in (0,):
            return None
        if status in RATE_LIMIT_STATUS:
            return f"配额类错误 status={status}"
        if status:
            return f"业务错误 status={status}"
        return None

    def _should_retry(self, err: Exception) -> bool:
        """哪些异常值得重试：网络/超时类（瞬时）。"""
        return isinstance(err, (TimeoutError, ConnectionError, OSError))

    async def call(self, work: Callable[[], Awaitable[Any]]) -> Optional[dict]:
        try:
            async with self._sem:
                await self._pace()
        except RuntimeError:
            # 无运行中的事件循环（如纯同步调用链）——退化为不限制
            pass

        attempt = 0
        while True:
            await self._pace()
            try:
                resp = await asyncio.wait_for(work(), timeout=self.timeout_s)
                biz_err = self._is_biz_error(resp)
            except Exception as e:  # noqa: BLE001 —— 所有异常统一按失败/重试路径处理
                biz_err = str(e)[:160]
                if not self._should_retry(e):
                    self.stats.fail += 1
                    self.stats.last_error = biz_err
                    return None

            if biz_err is None:
                self.stats.ok += 1
                return resp if isinstance(resp, dict) else None

            self.stats.last_error = biz_err
            if attempt >= self.max_retries or resp is None and attempt >= self.max_retries:
                self.stats.fail += 1
                return None
            attempt += 1
            self.stats.retried += 1
            self.stats.backed_off += 1
            delay = min(self.backoff_max, self.backoff_base * (2 ** (attempt - 1)))
            delay *= 0.5 + random.random() * 0.5  # 抖动，避免惊群
            if biz_err.startswith("配额类错误"):
                logger.warning("[living_circle] 百度配额紧张，退避 %.1fs 重试", delay)
            await asyncio.sleep(delay)