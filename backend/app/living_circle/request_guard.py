"""百度调用韧性层（并发信号量 + 级间限速 + 指数退避 + 失败率监控）。

职责边界（A3 数据源与韧性分离）：
  - 只负责「真实调用的并发/限速/重试/监控」，**不含业务快照或 fixture 回退**；
    数据源选择（live/fixture）与回退由 `data_source.py` 决定。
  - 重试判定依据百度协议：HTTP 层异常、status!=0、显式 429/配额类错误码。

⚠️ B1/B2 并发契约（延迟优化，防复发）：**限速/并发闸门内建于此，调用方必须并发
发出调用** —— 串行循环会把墙钟变成「次数×间隔」，白白浪费闸门容量；并发只用足
预算内并发度，总调用数/QPS 不变。新增调用点时同样必须并发发出（见
`baidu_client._measure_matrix` / `poi_collector.collect_poi` A 阶段）。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# 百度 place/v2/search 的配额类状态码（个人免费额度）：
# 401 AK 无效 / 402 AK 被禁用 /403 配额超限 / 4xx 权限, 另有 100~ 业务码。
RATE_LIMIT_STATUS = {401, 402, 403, 404, 429}

# ── 配额日口径（K3 裁决 B）───────────────────────────────
# 百度免费档按「中国本地自然日」结算（北京时间 00:00 解封）。
# 容器未设 TZ ⇒ 默认 UTC，`date.today()` 会在北京 08:00 滚动 ⇒ 与百度解封点错 8h，
# 使同一百度日可被两个连续进程窗口各吃满一次（最多 2×cap）。
# 中国自 1991 年起无夏令时 ⇒ 固定 +8 偏移即**精确解**，且不依赖容器内 tzdata
# （`ZoneInfo("Asia/Shanghai")` 在 python:*-slim 上会 ZoneInfoNotFoundError）。
QUOTA_TZ = timezone(timedelta(hours=8))


def quota_day_default() -> str:
    """当前「配额日」标签（北京自然日）。

    **唯一出口**：所有配额周期判定都必须经过它（此前 `date.today()` 在 :117 / :123
    写了两遍 —— 本项目反复出现的「第二权威」雏形）。

    ⚠️ 测试纪律（E13）：本函数是 `clock` 的**默认参数值**，在函数定义时即绑定到
    `GlobalDailyBudget.clock` ⇒ `monkeypatch.setattr(模块, "quota_day_default", fake)`
    **对它无效**（会得到一条假绿的负对照）。要改口径只有三条路：
    ① 构造时显式传 `clock=`；② patch 本函数**体内**读取的模块常量 `QUOTA_TZ`；
    ③ 负对照走「改源码 → 跑 → 还原」四步法。
    """
    return datetime.now(QUOTA_TZ).date().isoformat()


@dataclass
class GuardStats:
    """调用总览（成功/失败/重试/退避次数），供可观测性面板与诊断。"""

    ok: int = 0
    fail: int = 0
    retried: int = 0
    backed_off: int = 0
    # 命中配额类错误（401/402/403/404/429）的次数 —— 供上层区分「配额被限」与「该地真空」
    quota_hits: int = 0
    last_error: str = ""
    started_at: float = field(default_factory=time.time)

    def success_rate(self) -> float:
        total = self.ok + self.fail
        return self.ok / total if total else 1.0


# ── 全局（进程级、按 AK 共享）限流抽象（R1–R6 / R7）────────────────
# 根因：旧 `CallGuard` 的 `_sem` / `_pace` 每实例私有 → 多任务并发相乘超免费档、
# 且无进程级日调用预算。下面两个抽象把「并发/QPS 闸」与「每日总量预算」上升为
# 进程级、按 AK 注册的资源，所有 `BaiduClient(ak=ak)`（经 `_default_guard`）共享同一份。

class SharedGuardLoopConflict(RuntimeError):
    """同一个共享闸被**两个事件循环并发**使用 —— 当前设计不支持。

    `GlobalRateLimiter` 的同步原语（`sem` / `pace_lock`）按 loop 绑定、换 loop 时就地重建
    （P0-2 修复）。该重建**只对「跨 loop 顺序复用」成立**：若旧 loop 上仍有调用方
    持有/排队（那次 `asyncio.run()` 尚未跑完），重建会把信号量交给新 loop，
    而旧 loop 的持有者仍握着**旧对象** ⇒ 两个 loop 各自以为独占了共享闸、互相不知情，
    **共享闸退化为「自己跟自己打架」**，比不加闸更糟。

    ⇒ 明确拒绝：请保证**同一时刻只用一个事件循环**；不要把同一把闸丢进多个线程，
    也不要在上一次 `asyncio.run()` 未结束时启动下一次。确需并发多 loop 时，
    为每个 loop 各自建立 `BaiduClient`（各自独立闸）。
    """


# `getattr` 哨兵：必须区分「属性不存在」与「属性存在但为 None」——
# 实测（CPython 3.13）`Semaphore._waiters` / `Lock._waiters` **初值就是 None**，
# 有排队者时才是 deque ⇒ 直接用 `getattr(x, "_waiters", None)` 会把两种情况混为一谈。
_WAITERS_MISSING = object()


@dataclass
class GlobalRateLimiter:
    """按 AK 共享的并发信号量 + 级间限速锁（替代 CallGuard 每实例私有闸门）。

    语义对齐旧 `CallGuard._sem`+`_pace`：``acquire`` 闸「限速入口」，HTTP 工作本身
    仍并发执行（见 test_baidu_client.U37 注记），故共享后全局 QPS/并发被统一约束，
    但调用数与预算数学不变。

    ⚠️ **事件循环亲和性（P0-2 修复）**：`asyncio.Semaphore` / `asyncio.Lock` 在**首次使用**时
    绑定当时的 loop（`_LoopBoundMixin`），而本对象是**进程级长生命周期**的、会被缓存跨越
    多次 `asyncio.run()`。故每次入闸先校验 loop，**换了 loop 就重建原语** —— 对象身份不变
    ⇒「同 AK 共享同一把闸」的语义不变，只是同步原语跟随当前 loop。
    注意：无竞争时 `Semaphore.acquire` 走快路径**根本不查 loop** ⇒ 该缺陷只在**有竞争**时暴露。

    ⚠️ **前置条件（B-6 / K9）**：**同一时刻原则上只有一个活动 loop**。
    跨 loop **顺序**复用被支持；跨 loop **并发**使用**不支持** —— 后者抛
    `SharedGuardLoopConflict`（而不是让 asyncio 原语在别处抛一句没有上下文的
    `RuntimeError: … is bound to a different event loop`）。
    """

    sem: asyncio.Semaphore
    pace_lock: asyncio.Lock
    min_interval_s: float
    last_call_ts: float = 0.0
    # 重建原语用的并发度（`get_rate_limiter` 恒传入真实值）；0 = 未知，按 1 兜底。
    concurrency: int = 0
    _loop: Any = None

    def _bind_loop(self) -> None:
        """确保 `sem` / `pace_lock` 绑定「当前」事件循环；跨 loop **顺序**复用时就地重建。

        ⚠️ 前置条件（B-6 / K9）：同一时刻只有一个活动 loop。跨 loop **顺序**复用被支持；
        跨 loop **并发**使用**不支持** ⇒ 抛 `SharedGuardLoopConflict`。
        """
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self._loop is not None:
            # K9：判据依赖 CPython 私有属性 `_waiters` ⇒ 必须用哨兵区分「缺失」与「存在但为空」；
            # 缺失时**降级为 WARNING 而不是静默通过**（否则属性改名即静默恒不抛 = 又一条假护栏）。
            waiters = getattr(self.sem, "_waiters", _WAITERS_MISSING)
            lock_waiters = getattr(self.pace_lock, "_waiters", _WAITERS_MISSING)
            if waiters is _WAITERS_MISSING or lock_waiters is _WAITERS_MISSING:
                logger.warning(
                    "[living_circle] 无法判定共享闸（并发=%s）上一事件循环是否仍在排队："
                    "asyncio 原语缺少 `_waiters` 属性（CPython 实现细节变动？）。"
                    "本次**照常重建原语**，但该保护已降级 —— 跨 loop 并发使用将不被拦截。",
                    self.concurrency,
                )
            elif waiters or lock_waiters:
                raise SharedGuardLoopConflict(
                    f"共享闸（并发={self.concurrency}）仍被上一个事件循环的调用方持有/排队，"
                    "不能在本循环重建。根治办法：不要在多个线程 / 多次 asyncio.run() 之间"
                    "共享同一把闸；或为每个 loop 各自建立 BaiduClient。"
                )
            # 旧原语已绑定旧 loop，继续使用会抛 RuntimeError → 必须重建
            self.sem = asyncio.Semaphore(max(1, int(self.concurrency or 1)))
            self.pace_lock = asyncio.Lock()
            self.last_call_ts = 0.0  # 新 loop 的节拍从零起算，不背旧 loop 的间隔债
        self._loop = loop

    async def acquire(self) -> None:
        self._bind_loop()
        async with self.sem:
            async with self.pace_lock:
                now = time.monotonic()
                wait = self.last_call_ts + self.min_interval_s - now
                if wait > 0:
                    await asyncio.sleep(wait)
                self.last_call_ts = time.monotonic()


@dataclass
class GlobalDailyBudget:
    """按 AK 共享的「当日百度调用总量」预算（R7）。

    - ``cap<=0`` ⇒ 禁用（``exhausted`` 恒 False），由 ``.env`` 的 ``baidu_daily_quota`` 控制；
    - 每次真实调用（含失败/4xx/5xx/重试，因百度按请求计费）``consume(1)``；
    - 跨午夜按日期滚动归零（进程内，长驻 uvicorn 不会永久降级）。

    ⚠️ **三个公开读口全是只读属性（P0-1 + B-4 修复）**：滚动判定挂在**读取路径**上。
    原因：`CallGuard.call()` 在预算耗尽时会**直接短路 `return None`**，若滚动只写在
    `consume()` 里，那么「已耗尽 且 已跨日」这一**唯一需要滚动**的时刻，`consume()`
    恰恰永远不会被调用 ⇒ 解封分支不可达 ⇒ 进程**永久降级**（比收到超额短信更隐蔽）。
    ⇒ 顺带效果：`budget.exhausted = True` / `budget.calls = 99` / `budget.date_key = "…"`
    这类**直置**写法现在**全部** `AttributeError`（此前只锁了 `exhausted`，另两个仍是裸字段，
    纪律只覆盖同族成员里的一个 ⇒ 全部收口），逼调用方/测试走真实累加或**推进注入的 clock**。

    ⚠️ **配额日口径（K3 裁决 B）**：唯一出口是 `quota_day_default()`，通过可注入的 `clock`
    取值 ⇒ 口径**不随宿主机 TZ 漂移**，且**可判别**（测试可注入固定口径）。

    ⚠️ **契约（B-7 / K10）**：
    1. 本对象是**节流状态**，**不是计量真源** —— 跨日滚动会**不可逆丢弃**前一日的 `_calls`。
       任何「今日已用 N 次」的展示 / 审计需求**必须另行持久化**。
       （另：`CallGuard` 的豁免流量**不计入**本计数，见 `baidu_client._attach_shared_gates`。）
    2. 配额口径在仓内**三处分散**：静态额度＝`quota.py`，运行时状态＝本模块，
       消费点＝`baidu_client._default_guard()`。**唯一衔接点**是 `get_daily_budget()` /
       `get_rate_limiter()`。
    """

    cap: int
    # K3 / B-3：配额日口径**可注入**（默认北京自然日）。
    # ⚠️ 这是**默认参数**，函数定义时即绑定 ⇒ 测试**不得** patch `quota_day_default` 这个名字
    # （会静默失效、产出假绿负对照，见 E13）；只能显式传 `clock=`，
    # 或 patch 它**函数体内**读取的 `QUOTA_TZ`。
    clock: Callable[[], str] = quota_day_default
    _calls: int = 0
    _date_key: str = ""
    _exhausted: bool = False
    _logged: bool = False

    def __post_init__(self) -> None:
        """把首建时的口径固化为当日 `_date_key`（避免把「未初始化」误判成「昨天」）。"""
        if not self._date_key:
            self._date_key = self.clock()

    def roll_over_if_needed(self) -> None:
        """③ 跨午夜滚动归零 —— **由读取方触发**（见类 docstring 的 P0-1 说明）。

        B-5：这是**状态跃迁**（耗尽 → 解封），必须留痕 —— 此前完全静默，
        正是「口径错位 8h」这类缺陷在生产上**没有任何可发现路径**的成因。
        """
        today = self.clock()
        if today == self._date_key:
            return
        if not self._date_key:
            # J9（2026-09-22 裁决）：`_date_key` 为空 ⇒ 已有计数**属于哪一天未知** ⇒ 一律作废，
            # 不得凭空归给「今天」。`__post_init__` 是唯一合法初始化路径，绕过它
            # （`object.__new__` / dict 反序列化重建）属**异常状态** ⇒ 必须可观测（WARNING），
            # 而不是静默丢数（B-5：状态跃迁不得静默 —— 哪怕这次跃迁是「丢弃」）。
            logger.warning(
                "[living_circle] 日预算对象缺少初始日期（绕过 __post_init__？"
                "如 object.__new__ / dict 反序列化重建）：已有计数 %d 的归属日未知，作废归零 → %s",
                self._calls, today,
            )
        else:
            logger.info(
                "[living_circle] 日预算跨日解封：%s → %s（上一日已用 %d / 上限 %d，计数归零）",
                self._date_key, today, self._calls, self.cap,
            )
        self._calls = 0
        self._date_key = today
        self._exhausted = False
        self._logged = False  # 新的一日重新获得「最多告警一次」的额度

    # ── 三个公开读口：**每次读取都先滚动**，且**均无 setter**（P0-1 + B-4 收口）──
    @property
    def calls(self) -> int:
        """当日已用次数（只读）。**注意**：节流计数，非计量真源（见类 docstring）。"""
        self.roll_over_if_needed()
        return self._calls

    @property
    def date_key(self) -> str:
        """当前配额日标签（只读）。"""
        self.roll_over_if_needed()
        return self._date_key

    @property
    def exhausted(self) -> bool:
        """**只读**：任何一次读取都先做跨日滚动 ⇒「耗尽」不会跨自然日滞留。"""
        self.roll_over_if_needed()
        return self._exhausted

    def take_log_credit(self) -> bool:
        """B-5：短路告警的**一次性额度** —— 首次返回 True（该打日志），此后 False；
        跨日解封时重置（见 `roll_over_if_needed`）。

        把这个状态机收口成方法，而不是让 `CallGuard` 去碰 `_logged` 私有字段。
        """
        if self._logged:
            return False
        self._logged = True
        return True

    def consume(self, n: int = 1) -> None:
        if self.cap <= 0:
            self._exhausted = False
            return
        self.roll_over_if_needed()  # ③ 跨午夜滚动归零
        self._calls += n  # ④ 纯同步自增（无 await），asyncio 单线程下原子
        if self._calls >= self.cap:
            self._exhausted = True


# ⚠️ B-2/K8：两个缓存**键只含身份（ak）** —— 并发/间隔/cap/clock 都**不参与身份**。
# 把可变配置写进键，等于允许同一 AK 分裂出多把「自称按 AK 共享」的闸 ⇒ 限流被静默腰斩。
# 取舍：**共享 > 定制**（首建为准），冲突时 WARNING 留痕，见两个工厂。
_limiter_cache: Dict[str, "GlobalRateLimiter"] = {}
_daily_cache: Dict[str, "GlobalDailyBudget"] = {}


def _mask_ak(ak: str) -> str:
    """AK 的日志展示形态 —— 完整 AK 是凭证，但全掩码（`***`）又让 WARNING 无法定位是哪个 AK。
    折中：留前 4 位作可区分的指纹。"""
    if not ak:
        return "空AK"
    return f"{ak[:4]}***" if len(ak) > 4 else "短AK"


def get_rate_limiter(ak: str, concurrency: int, min_interval_s: float) -> "GlobalRateLimiter":
    """按 **AK** 取进程级共享限速器 —— **键只含身份（ak）**，同一 AK 恒为同一把闸。

    ⚠️ B-2：此前键是 `(ak, concurrency, min_interval_s)` —— **把可变配置写进了身份**
    ⇒ 同一 AK 只要有人传入不同并发/间隔，就会拿到**第二把闸**，而两把闸都自称「按 AK 共享」
    ⇒ 限流被静默腰斩、原缺陷（多任务并发相乘超免费档）原样复发。
    生产侧只有 `baidu_client._default_guard()` 一个调用方、参数由 `Settings` 常量派生，
    故该情形此前不可见；一旦新增调用点就必然踩上。**以首建为准**（共享 > 定制），不一致时 WARNING。
    """
    concurrency = max(1, int(concurrency))
    min_interval_s = round(float(min_interval_s), 3)
    rl = _limiter_cache.get(ak)
    if rl is None:
        rl = GlobalRateLimiter(
            sem=asyncio.Semaphore(concurrency),
            pace_lock=asyncio.Lock(),
            min_interval_s=min_interval_s,
            concurrency=concurrency,  # 供跨 loop 重建原语（P0-2）
        )
        _limiter_cache[ak] = rl
        return rl
    if (rl.concurrency, rl.min_interval_s) != (concurrency, min_interval_s):
        logger.warning(
            "[living_circle] 同一 AK(%s) 请求了不同的闸参数：已建 (并发=%s, 间隔=%ss)，"
            "本次 (并发=%s, 间隔=%ss) —— **以首建为准**（共享 > 定制）。"
            "若确需不同参数，请改用不同的 AK 维度。",
            _mask_ak(ak), rl.concurrency, rl.min_interval_s, concurrency, min_interval_s,
        )
    return rl


def get_daily_budget(
    ak: str, cap: int, clock: Callable[[], str] = quota_day_default,
) -> "GlobalDailyBudget":
    """按 **AK** 取进程级共享日预算 —— **键只含身份（ak）**；cap<=0 仍返回对象但 exhausted 永 False。

    ⚠️ **K8 裁决（首建为准）**：`cap` 与 `clock` 都**不参与缓存身份** ⇒ 同一 AK 的第二个
    调用方传来的 `cap` / `clock` **被忽略**（此处以 WARNING 显式留痕，与 B-2 同构：共享 > 定制）。
    ⇒ **口径注入必须用「还没建过的新 AK」，或先清 `_daily_cache`** —— 这是 E13 之外
    第二条会让 `clock` 静默失效的陷阱，写用例时尤其当心（见 J2）。
    """
    cap = int(cap)
    db = _daily_cache.get(ak)
    if db is None:
        db = GlobalDailyBudget(cap=cap, clock=clock)
        _daily_cache[ak] = db
        return db
    if db.cap != cap:
        logger.warning(
            "[living_circle] 同一 AK(%s) 请求了不同的日预算上限：已建 %s，本次 %s —— "
            "**以首建为准**（共享 > 定制）。",
            _mask_ak(ak), db.cap, cap,
        )
    if db.clock is not clock:
        logger.warning(
            "[living_circle] 同一 AK(%s) 再次注入了不同的 clock（内存 %s ≠ 本次 %s）—— "
            "**以首建为准**，本次注入被忽略。需要独立口径请改用不同的 AK 或先清缓存。",
            _mask_ak(ak),
            getattr(db.clock, "__name__", db.clock), getattr(clock, "__name__", clock),
        )
    return db


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
        max_total_calls: int = 0,
        rate_limiter: "Optional[GlobalRateLimiter]" = None,
        daily_budget: "Optional[GlobalDailyBudget]" = None,
    ) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)
        self.min_interval = min_interval_s
        self.max_retries = max_retries
        self.backoff_base = backoff_base_s
        self.backoff_max = backoff_max_s
        self.timeout_s = timeout_s
        self.max_total_calls = max_total_calls  # 0 = 不启用总量熔断（默认向后兼容）
        self._total_calls = 0
        self.stats = GuardStats()
        self._last_call_ts: float = 0.0
        self._interval_lock = asyncio.Lock()
        # 每实例闸的跨 loop 重建参数（P0-2 同族形态；见 `_ensure_primitives`）
        self._max_concurrency = max_concurrency
        self._loop: Any = None
        # R1–R6：全局并发/QPS 闸（None 时回退每实例闸门，行为=现状）
        self.rate_limiter = rate_limiter
        # R7：全局每日总量预算（None 时不做日预算约束）
        self.daily_budget = daily_budget
        # 最近一次响应是否为配额类错误（401/402/403/404/429）。
        # 供数据源/流水线区分「配额被限」与「该地本来就没有数据」——是降级决策的一等前提。
        self.quota_blocked: bool = False
        self.total_meltdown: bool = False  # 累计调用超预算 → 熔断置位（v3 §3.5）

    def _ensure_primitives(self) -> None:
        """每实例闸（`_sem` / `_interval_lock`）也必须跟随当前事件循环（P0-2 同族形态）。

        `CallGuard` 的生命周期可能长于一次 `asyncio.run()`（如被缓存的 datasource 持有），
        而这两个原语在 `__init__` 创建 ⇒ 跨 loop 复用时在**有竞争**的路径抛 `RuntimeError`。
        无运行中的 loop 时 `get_running_loop()` 自身抛 `RuntimeError`，由调用方既有
        `except RuntimeError` 兜住 = 原语义（退化为不限制），不会改变既有行为。
        """
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self._loop is not None:
            self._sem = asyncio.Semaphore(max(1, int(self._max_concurrency)))
            self._interval_lock = asyncio.Lock()
            self._last_call_ts = 0.0
        self._loop = loop

    async def _pace(self) -> None:
        """级间最小间隔（限速），防止瞬时打爆个人免费额度。"""
        self._ensure_primitives()
        async with self._interval_lock:
            now = time.monotonic()
            wait = self._last_call_ts + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = time.monotonic()

    async def _acquire_and_pace(self) -> None:
        """入口限速闸：优先进程级共享闸（R1–R6），否则回退每实例闸门（=现状）。

        共享闸内部已做「并发信号量 + 级间 QPS」双重约束，HTTP 工作本身仍并发执行
        （与旧每实例模式同语义），故共享后全局并发/QPS 被统一约束、调用数不变。
        """
        if self.rate_limiter is not None:
            await self.rate_limiter.acquire()
            return
        try:
            self._ensure_primitives()
            async with self._sem:
                await self._pace()
        except RuntimeError:
            # 无运行中的事件循环（如纯同步调用链）——退化为不限制
            pass

    @property
    def budget_exhausted(self) -> bool:
        """R7：进程级「当日百度调用总量」预算是否耗尽（区别于 per-task 的 total_meltdown）。

        - 无 ``daily_budget``（未注入日预算）时恒 ``False``，等价于「不约束日预算」；
        - 真实耗尽由共享 ``GlobalDailyBudget.exhausted`` 反映，流水线据此外部降级。
        """
        if self.daily_budget is None:
            return False
        return self.daily_budget.exhausted

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

    @staticmethod
    def _is_quota_status(resp: Any) -> bool:
        """响应是否为**配额类**错误（与「业务空结果」区分，供上层降级决策）。"""
        return isinstance(resp, dict) and resp.get("status") in RATE_LIMIT_STATUS

    def _should_retry(self, err: Exception) -> bool:
        """哪些异常值得重试：网络/超时类（瞬时）。"""
        return isinstance(err, (TimeoutError, ConnectionError, OSError))

    def _at_capacity(self) -> bool:
        """总量熔断判定的**唯一实现**（`call()` 入口与重试循环内各调一次）。

        ⚠️ 只在入口判一次**不够**：一次 `call()` 内最多发 ``1 + max_retries`` 次真实请求，
        计数却在循环内递增 ⇒ 硬上限被重试超支（实测 53 ≥ 45）。故循环内每次 attempt 前都要判。
        """
        if self.max_total_calls <= 0 or self._total_calls < self.max_total_calls:
            return False
        if not self.total_meltdown:
            logger.warning(
                "[living_circle] CallGuard 总量熔断：累计 %d 次 ≥ 预算 %d，停止发请求",
                self._total_calls, self.max_total_calls,
            )
            self.total_meltdown = True
        return True

    async def call(self, work: Callable[[], Awaitable[Any]]) -> Optional[dict]:
        # R7c：进程级日预算已耗尽 → 直接短路降级，不再发起任何请求。
        if self.daily_budget is not None and self.daily_budget.exhausted:
            # B-5：本分支会被**每一次** `call()` 命中，故必须门控 —— 与**相邻**的
            # total_meltdown 分支（下方 `if not self.total_meltdown`）纪律对齐。
            # 此前无门控：一次体检上百次调用 ⇒ 上百条重复 WARNING，把真实信号淹没。
            if self.daily_budget.take_log_credit():
                logger.warning(
                    "[living_circle] CallGuard 日预算耗尽：当日已用 %d 次 ≥ 上限 %d，停止发请求",
                    self.daily_budget.calls, self.daily_budget.cap,
                )
            return None
        # 总量熔断（v3 §3.5）：累计调用已达到预算上限 → 直接熔断，不再发起请求
        if self._at_capacity():
            return None

        # 入口限速：优先进程级共享闸（R1–R6），否则回退每实例闸门（=现状）
        await self._acquire_and_pace()

        attempt = 0
        while True:
            # R-6：每次 attempt 前**重判**上限 —— 只在入口判一次是不够的：
            # 一次 `call()` 内部最多发 `1 + max_retries` 次真实请求，而计数在循环内递增
            # ⇒ 硬上限会被重试超支（实测：预算 45 实际发到 53，超 18%）。
            if self._at_capacity():
                return None
            if self.rate_limiter is None:
                # 每实例模式保留现状语义（共享模式已由全局闸统一控，不重复限速）
                await self._pace()
            self._total_calls += 1
            is_quota = False
            try:
                resp = await asyncio.wait_for(work(), timeout=self.timeout_s)
                biz_err = self._is_biz_error(resp)
                is_quota = self._is_quota_status(resp)
            except Exception as e:  # noqa: BLE001 —— 所有异常统一按失败/重试路径处理
                biz_err = str(e)[:160]
                if self.daily_budget is not None:
                    self.daily_budget.consume(1)  # ⑨ 失败/超时请求同样计费
                if not self._should_retry(e):
                    self.stats.fail += 1
                    self.stats.last_error = biz_err
                    return None
            else:
                if self.daily_budget is not None:
                    self.daily_budget.consume(1)  # ⑨ 成功请求计费

            if biz_err is None:
                self.stats.ok += 1
                self.quota_blocked = False
                return resp if isinstance(resp, dict) else None

            self.stats.last_error = biz_err
            if is_quota:
                self.quota_blocked = True
                self.stats.quota_hits += 1
            if attempt >= self.max_retries:
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