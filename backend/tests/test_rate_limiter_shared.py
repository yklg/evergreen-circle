"""M3 · 进程级共享限流/日预算抽象（R1–R6 / R7）单元测试。

覆盖 test-coverage-expander 方案 G1–G8（G9 融合进 test_pipeline_living_circle.py
的 live 分支降级契约，G10 落在 test_config_contract.py），
以及**第二轮覆盖评估**追加的 H1 / H2（P0-1 / P0-2 回归护栏，见计划 §9/§10）。

关键不变量（验收口径）：
- G1  同 **AK** 共享同一份 GlobalRateLimiter 对象（**键只含身份**：异参**仍共享**、
      以首建为准 + WARNING；异 AK 不复用）—— 旧文案「同 (ak,并发,间隔) 共享…异参不复用」
      把缺陷讲成了规范，2026-09-22 已订正；
- G2  共享闸只约束「**入闸**（并发 + 级间 QPS）」，**不改变调用总数**；
      ⚠️ 早期版本此处写「in-flight ≤ 并发度」—— **那是错的**（闸在 entry 后即释放，
      HTTP 工作仍并发；见 test_baidu_client.U37 的语义注记），已删除该错误表述；
- G3  共享闸与 per-task 总量熔断（max_total_calls）正交：A 熔断不影响 B；
- G4  共享 GlobalDailyBudget 跨 guard 累加 calls；
- G5  calls ≥ cap → exhausted=True → 下次 call 被 R7c 短路返回 None；
- G6  ⑨ 真实请求无论「成功 / 配额失败(403) / 异常」都 consume(1)（百度按请求计费）；
- G7  cap<=0 ⇒ consume 为 no-op、exhausted 永 False（默认禁用，零行为变化）；
- G8  跨日滚动归零（长驻 uvicorn 不会永久降级）——**经 consume 路径**；
- H1  跨日滚动**必须经 `call()` 真实入口可解封**（P0-1：滚动曾只在 consume 内、
      而耗尽时 call() 先短路 ⇒ 解封分支不可达 ⇒ 进程永久降级）；
- H2  进程级闸缓存**跨事件循环复用**必须可用（P0-2：同步原语首次使用时绑定 loop）。

⚠️ 纪律：本文件禁止用 `budget.exhausted = True` 直置状态位（现在会 AttributeError）——
凡「恢复 / 解封 / 跨周期」类不变量，必须经真实入口推进，否则断言是在替实现说话。

运行：backend/ 下 `pytest tests/test_rate_limiter_shared.py -q`
"""
import asyncio
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.living_circle.request_guard as rg
from app.living_circle.request_guard import (
    CallGuard,
    GlobalDailyBudget,
    GlobalRateLimiter,
    SharedGuardLoopConflict,
    get_daily_budget,
    get_rate_limiter,
    quota_day_default,
)

_BACKEND = Path(__file__).resolve().parents[1]  # backend/ —— 子进程跑 `-c` 时的 cwd


def _quota_day_in_tzs(code: str, tzs=("Etc/GMT+12", "Pacific/Kiritimati", "Asia/Shanghai")):
    """在**三个独立进程**里以不同 `TZ` 跑同一段 `code`，返回 stdout 列表（J1a/J1b 共用）。

    ⭐ 为什么必须是**独立进程**：`TZ` 只在进程**启动时**被 `time`/`datetime` 读取，
    同进程内改 `os.environ["TZ"]` 对已导入的 `time` 模块无效 ⇒ 同进程测不出漂移。
    """
    outs = []
    for tz in tzs:
        env = {**os.environ, "TZ": tz}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_BACKEND), env=env, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"TZ={tz} 子进程失败：{proc.stderr[-400:]}"
        outs.append(proc.stdout.strip().splitlines()[-1])
    return outs


@pytest.fixture(autouse=True)
def _clear_global_caches():
    """G11：每个用例前后清空进程级共享缓存，保证 GlobalRateLimiter / GlobalDailyBudget
    的计数状态不被前序用例污染（它们是模块级单例，跨用例持久）。

    ⚠️ 复核（P0-2）：这个夹具曾经**只作用于本文件** —— 作用域过窄本身就是一条隐性断言，
    本文件内的污染被抹平、其他文件与真实环境里同一缺陷完全不可见。
    现已**同时**挂到全局 `tests/conftest.py::_isolate`；此处保留为冗余双保险。
    """
    rg._limiter_cache.clear()
    rg._daily_cache.clear()
    yield
    rg._limiter_cache.clear()
    rg._daily_cache.clear()


# ── G1 · 同 AK 共享（**键只含身份**）──────────────────────
def test_g01_same_ak_shared_limiter(caplog):
    """G1（2026-09-22 收紧）：**键只含身份（ak）** ⇒ 同 AK 恒为同一把闸。

    ⚠️ **旧版本断言错了方向**（把缺陷制度化）：原标题「同 AK 共享，**异参不复用**」+
    `assert d is not a` —— 把「同一 AK 因参数不同而分裂成**两把**闸」这条**缺陷**写成了期望值；
    而两把闸都自称「按 AK 共享」⇒ 限流被静默腰斩、原症状（并发预警 / 算力超额）复发。
    判据 B-2：**身份 = ak，配置不参与身份**；冲突时「首建为准」。
    日志侧只断言**条数**（每条被拒绝的定制 = 1 条 WARNING），**不锚文案** —— 否则日志措辞
    会变成第二真源，改个措辞就把测试改红。
    """
    with caplog.at_level(logging.WARNING, logger="app.living_circle.request_guard"):
        a = get_rate_limiter("ak1", 2, 0.333)
        b = get_rate_limiter("ak1", 2, 0.333)
        assert a is b, "同 AK 同参必须返回同一对象（共享闸）"
        c = get_rate_limiter("ak2", 2, 0.333)
        assert c is not a, "不同 AK 必须不复用"
        d = get_rate_limiter("ak1", 4, 0.333)  # 异参：**仍是同一把闸**（键只含 ak）
        assert d is a, "同 AK 异参必须仍复用同一把闸 —— 旧版此处断言 `is not`，方向错了"
        e = get_rate_limiter("ak1", 2, 0.25)  # 异参：同上
        assert e is a, "同 AK 异参必须仍复用同一把闸"
    assert (d.concurrency, d.min_interval_s) == (2, 0.333), "闸参数以首建为准，后到的定制被忽略"
    assert len(caplog.records) == 2, (
        f"两次定制被拒 ⇒ 恰应留 2 条 WARNING（可观测性），实际 {len(caplog.records)} 条；"
        "0 条说明「首建为准」是**静默**的（本仓反复踩过的形态）"
    )


# ── G2 · 共享闸统一 QPS：聚合 entry 被级间限速串行化 ──────
def test_g02_shared_limiter_paces_aggregate_qps():
    """G2（R1–R6 核心不变量）：多 guard / 多任务共享同一份闸 → 聚合 entry 被级间限速
    串行化，总墙钟随调用数线性增长、不随「调用方并发度」放大。

    这正是根治「并发预警 / 算路超额」的机制：旧每实例闸门下，3 个并发任务各持 QPS=3
    的闸 → 聚合可冲到 9 QPS；共享后全进程统一到单条 QPS 线。work 本身仍并发（与
    test_u37 注记一致），故此处只断言「entry 被限速」+「调用总数不变」。
    """
    import time

    min_i = 0.03
    rl = get_rate_limiter("g2", concurrency=4, min_interval_s=min_i)
    guard = CallGuard(rate_limiter=rl, min_interval_s=0)
    state = {"total": 0}

    async def work():
        state["total"] += 1
        return {"status": 0}

    n = 10

    async def impl():
        t0 = time.monotonic()
        await asyncio.gather(*[guard.call(work) for _ in range(n)])
        return time.monotonic() - t0

    dt = asyncio.run(impl())
    # 10 次 entry 经 pace_lock 串行 → 至少 9 个间隔（留足余量防 CI 抖动）
    assert dt >= (n - 1) * min_i * 0.5, (
        f"聚合 QPS 应被限速，墙钟 ≥ {(n - 1) * min_i * 0.5:.3f}s，实际 {dt:.3f}s"
    )
    assert state["total"] == n, "共享闸不改变调用总数（预算数学守恒）"


# ── G3 · per-task 总量熔断与共享闸正交 ───────────────────
def test_g03_per_task_budget_independent_of_shared_gate():
    rl = get_rate_limiter("g3", concurrency=4, min_interval_s=0)
    g_a = CallGuard(rate_limiter=rl, max_total_calls=3, min_interval_s=0)
    g_b = CallGuard(rate_limiter=rl, min_interval_s=0)  # 无 per-task 预算

    async def work():
        return {"status": 0}

    async def impl():
        for _ in range(5):
            await g_a.call(work)
        # g_a 已熔断，但 g_b 应不受共享闸外的任何影响（预算是 per-guard 的）
        return await g_b.call(work)

    res = asyncio.run(impl())
    assert g_a.total_meltdown is True, "g_a 达到 per-task 预算后熔断"
    assert res == {"status": 0}, "g_b 不被 g_a 的 per-task 熔断影响（共享的是闸不是预算）"


# ── G4 · 共享日预算跨 guard 累加 ─────────────────────────
def test_g04_shared_daily_budget_counts_across_guards():
    budget = get_daily_budget("g4", 100)
    g1 = CallGuard(daily_budget=budget, min_interval_s=0)
    g2 = CallGuard(daily_budget=budget, min_interval_s=0)

    async def work():
        return {"status": 0}

    async def impl():
        for _ in range(3):
            await g1.call(work)
            await g2.call(work)

    asyncio.run(impl())
    assert budget.calls == 6, "两个 guard 共享同一份日预算 → 累加计数"
    assert budget.exhausted is False


# ── G5 · 耗尽后短路 ─────────────────────────────────────
def test_g05_exhaustion_short_circuits():
    budget = get_daily_budget("g5", 3)
    g = CallGuard(daily_budget=budget, min_interval_s=0)

    async def work():
        return {"status": 0}

    async def impl():
        return [await g.call(work) for _ in range(4)]

    out = asyncio.run(impl())
    assert out[:3] == [{"status": 0}] * 3, "预算内 3 次正常返回"
    assert out[3] is None, "第 4 次（已耗尽）被 R7c 短路返回 None"
    assert budget.exhausted is True
    assert g.budget_exhausted is True


# ── G6 · ⑨ 成功/配额失败/异常 均计费 ────────────────────
def test_g06_counts_failed_and_exception_calls():
    """⑨：百度按请求计费（成功 AND 失败/4xx/5xx/重试），故 consume 必须在每次真实
    work() 执行后发生，无论成败。"""
    budget = get_daily_budget("g6", 100)
    g = CallGuard(daily_budget=budget, min_interval_s=0, max_retries=0, backoff_base_s=0.001)

    async def ok():
        return {"status": 0}

    async def quota403():
        return {"status": 403, "message": "over quota"}

    async def boom():
        raise ConnectionError("net down")

    async def impl():
        await g.call(ok)        # 成功 → 计费 1
        await g.call(quota403)  # 配额错误（失败）→ 计费 2
        await g.call(boom)      # 异常 → 计费 3

    asyncio.run(impl())
    assert budget.calls == 3, "⑨ 成功/配额失败/异常 三种真实请求均 consume(1)"
    assert g.stats.ok == 1
    assert g.stats.quota_hits == 1


# ── G7 · cap=0 禁用：consume 为 no-op，exhausted 永 False ──
def test_g07_cap_zero_disables_budget():
    budget = get_daily_budget("g7", 0)
    g = CallGuard(daily_budget=budget, min_interval_s=0)

    async def work():
        return {"status": 0}

    async def impl():
        for _ in range(10):
            await g.call(work)

    asyncio.run(impl())
    assert budget.calls == 0, "cap=0 时 consume 为 no-op（不计数）"
    assert budget.exhausted is False, "cap=0 ⇒ exhausted 永 False（默认禁用，零行为变化）"
    assert g.budget_exhausted is False


# ── G8 · 跨日按日期滚动归零（consume 路径）───────────────
def test_g08_date_rollover_resets():
    """G8：跨日滚动归零（经 `consume` 路径）。

    ⚠️ 本用例只覆盖「**未耗尽**时跨日」。`exhausted` 已改为只读属性（不可直置），
    而「**已耗尽**时跨日解封」正是 P0-1 的现场，必须经 `call()` 真实入口验证 → 见 H1。

    ⚠️ 2026-09-22 改造（S-1）：`calls` / `date_key` 已是**无 setter 的只读属性**，
    原 `budget.calls = 99` / `budget.date_key = "2000-01-01"` 会直接 `AttributeError`。
    改为**推进注入的 clock**（这是「贴场景写」——模拟时间前进，而不是篡改状态）。
    口径注入必须**显式传 `clock=`**（E13：`clock` 是默认参数、定义时即绑定，
    patch `quota_day_default` 这个名字**无效**）。
    """
    now = {"d": "2000-01-01"}
    budget = get_daily_budget("g8", 4, clock=lambda: now["d"])
    budget.consume(1)
    budget.consume(1)
    budget.consume(1)  # 累计 3 < 4：接近上限但**未耗尽**
    assert budget.calls == 3 and budget.exhausted is False
    now["d"] = "2026-09-22"  # 推进口径模拟跨日（不碰任何状态位）
    budget.consume(1)  # 触发跨日归零 → 归零后计 1
    assert budget.calls == 1, "跨日归零：从 3 重新计到 1"
    assert budget.exhausted is False, "归零后不再 exhausted"
    assert budget.date_key == "2026-09-22", "date_key 滚动到注入的今日（字面量锚定）"


# ── H1 · P0-1：耗尽后跨日必须**经真实入口**解封 ──────────
def test_h01_exhausted_budget_recovers_after_date_rollover():
    """H1（P0-1 回归护栏）：日预算耗尽 + 跨日 ⇒ `call()` 必须真正恢复发请求。

    **修复前的现场**：日期滚动只写在 `GlobalDailyBudget.consume()` 内，而
    `CallGuard.call()` 在 `budget_exhausted` 为真时**先短路 `return None`**
    ⇒「已耗尽 且 已跨日」这一**唯一需要滚动**的时刻，`consume()` 恰好永不执行
    ⇒ 解封分支**不可达**、进程**永久降级**（实测 `date_key` 停在昨日、永不滚动）。

    本用例**不经任何直置状态位**推进：先经 `call()` 用满预算，再**推进注入的 clock**
    模拟跨日，然后仍经 `call()` 断言恢复。修复前此处必红。

    ⚠️ 2026-09-22 改造（S-1）：原 `budget.date_key = "2000-01-01"` 会 `AttributeError`
    （`date_key` 已成无 setter 的只读属性）⇒ 改为推进注入的 `clock`。
    """
    now = {"d": "2026-09-22"}
    budget = get_daily_budget("h1", 2, clock=lambda: now["d"])
    guard = CallGuard(daily_budget=budget, min_interval_s=0)
    invoked = []

    async def work():
        invoked.append(1)
        return {"status": 0}

    async def impl():
        a = await guard.call(work)
        b = await guard.call(work)
        c = await guard.call(work)  # 第 3 次：已耗尽 → 短路，work 不被调用
        now["d"] = "2026-09-23"  # 只推进口径模拟跨日，不碰任何状态位
        d = await guard.call(work)  # ← 修复前必为 None（永久降级）
        return a, b, c, d

    a, b, c, d = asyncio.run(impl())
    assert a == b == {"status": 0}
    assert c is None, "预算用满后第 3 次应被 R7c 短路"
    assert d == {"status": 0}, "跨日必须解封（修复前：永久返回 None）"
    assert len(invoked) == 3, "work 实际被调用 3 次（2 次预算内 + 1 次解封后）"
    assert budget.calls == 1, "解封后从零重新计数"
    assert budget.date_key == "2026-09-23", "date_key 已滚动到注入的今日（字面量锚定）"
    assert budget.exhausted is False


# ── H2 · P0-2：进程级闸跨事件循环复用 ────────────────────
def test_h02_shared_limiter_survives_new_event_loop():
    """H2（P0-2 回归护栏）：缓存里的闸换一个事件循环后仍必须可用。

    `asyncio.Semaphore` / `asyncio.Lock` **首次使用时**绑定 loop（`_LoopBoundMixin`），
    而本闸是**进程级长生命周期**对象、会被缓存跨越多次 `asyncio.run()`。

    ⚠️ **触发条件必须刻意制造**（实测踩出来的，前两版 H2 都是**假护栏**）：

    1. `Semaphore.acquire` 只在 **`locked()`**（`_value == 0`）时才调 `_get_loop()`；
       **空闲态走快路径、根本不查 loop**；
    2. 更隐蔽的是：`wait <= 0` 时 `GlobalRateLimiter.acquire()` 的 `async with` 全程
       **没有任何 await 点** ⇒ 调用方**顺序跑完、根本不排队** ⇒ 永远走快路径；
    3. ⇒ 必须**两个条件同时满足**：① 新 loop 上出现**排队**（`min_interval_s > 0` +
       **≥3 个并发调用方**，第 3 个才会在第 2 个持锁睡着时撞上 `sem.locked()`）；
       ② **旧 loop 上已经排过队**（否则原语从未绑定旧 loop，新 loop 上绑定是"第一次绑定"，
       不构成 loop 不匹配）。
       实测：`n=2` 恒绿（假护栏）；`n=3` 稳定抛 `RuntimeError`；`n=5` 同。
    """
    rl = get_rate_limiter("h2", concurrency=1, min_interval_s=0.05)
    calls = {"n": 0}

    async def caller():
        await rl.acquire()
        calls["n"] += 1

    async def probe():
        await asyncio.gather(*[caller() for _ in range(3)])

    asyncio.run(probe())  # loop #1：第 3 个调用方排队 ⇒ sem 绑定 loop #1
    asyncio.run(probe())  # loop #2：← 修复前必抛 RuntimeError（bound to a different event loop）
    assert calls["n"] == 6, "跨 loop 重建原语不得丢调用"
    assert get_rate_limiter("h2", 1, 0.05) is rl, "重建的是原语；闸对象仍同一份（同 AK 共享语义不变）"


# ── 直接单测 dataclass 构造（防御性）─────────────────────
def test_guard_dataclasses_construct():
    rl = GlobalRateLimiter(
        sem=asyncio.Semaphore(2), pace_lock=asyncio.Lock(), min_interval_s=0.3, concurrency=2,
    )
    assert rl.min_interval_s == 0.3 and rl.concurrency == 2
    db = GlobalDailyBudget(cap=50, clock=lambda: "2026-09-22")
    assert db.cap == 50 and db.calls == 0 and db.exhausted is False
    # 三个公开读口现在**全是只读属性**：直置状态位必须报错 —— 把「贴着实现写的假绿」变难。
    for attr in ("exhausted", "calls", "date_key"):
        with pytest.raises(AttributeError):
            setattr(db, attr, True)


# ── H12 · 配额日口径（K3）───────────────────────────────
def test_h12_quota_day_caliber_literal_anchored(monkeypatch):
    """H12（B-3 改写 · 🟠）：配额日口径的**字面量锚定**。

    ⚠️ 旧写法（§9.3 原版）是「断言滚动使用的时区口径 = 配置里的口径」—— 那是
    **自己等于自己**（恒绿、测不到任何口径错误）。本版锚一个**由夹具算出的字面量**：
    把模块的 `datetime` 换成返回固定瞬间的替身，`quota_day_default()` 必须产出该瞬间
    在北京（+8）区下的**次日**。

    E12 注记：patch 必须**替换模块属性** `rg.datetime`（安全）；
    不得写 `monkeypatch.setattr("datetime.datetime", …)`（`from … import datetime` 是按值绑定，
    打不到本模块 ⇒ 静默空转），也不得 patch `rg.quota_day_default`（E13：默认参数已冻结）。
    """

    class _FixedDatetime:
        """假 `datetime`：`now(tz)` 恒返回 2026-09-22T23:30Z（= 北京 2026-09-23 07:30）。"""

        @staticmethod
        def now(tz=None):
            base = datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc)
            return base.astimezone(tz) if tz is not None else base.replace(tzinfo=None)

    monkeypatch.setattr(rg, "datetime", _FixedDatetime)
    assert quota_day_default() == "2026-09-23", (
        "23:30Z 在北京（+8）已是次日 —— 若实现退回宿主机本地 `date.today()`、"
        "或偏移写错（如留 UTC），此处必红"
    )


def test_j01a_daily_budget_caliber_is_host_tz_invariant():
    """J1a（🔴 行为红 · 修复前今日即红）：**敌意 TZ 下口径必须逐字相同**。

    ⭐ 这条测的是 K3 的**真实承诺**（口径不随宿主机漂移），而不是「patch 到 23:59
    断言字面量」—— 后者是在测**时钟**：`QUOTA_TZ` 换成任何固定偏移它都照样绿。
    只依赖**现有符号** `GlobalDailyBudget`，故在 A-1 落地前就能跑（= 对 🟠 的**行为型替身**）。
    实测（修复前）三值分别为 `2026-09-21` / `2026-09-23` / `2026-09-22`。
    """
    outs = _quota_day_in_tzs(
        "from app.living_circle.request_guard import GlobalDailyBudget;"
        "print(GlobalDailyBudget(cap=10).date_key)"
    )
    labels = ("Etc/GMT+12(UTC-12)", "Pacific/Kiritimati(UTC+14)", "Asia/Shanghai(UTC+8)")
    assert len(set(outs)) == 1, "口径随宿主机 TZ 漂移 ⇒ K3 未生效：" + str(dict(zip(labels, outs)))
    # 🔵 配对哨兵：否则「恒返回一个常量（如 1970-01-01）」也能过
    assert outs[0] == quota_day_default(), "子进程口径必须与本进程一致（不是随便一个常量）"


def test_j01b_quota_day_default_matches_independent_beijing_calendar():
    """J1b（🟠 存在红 · 需新符号）：`quota_day_default()` 必须等于**独立机制**算出的北京自然日。

    ⭐ 判据不得由被测方自己产出（否则「自己等于自己」）：此处独立机制 = `zoneinfo.ZoneInfo("Asia/Shanghai")`
    （走系统 tzdata），而被测实现走**固定 +8 偏移** —— 两条互不相同的路径，故有判别力。
    宿主无 tzdata 时**跳过并显式标注**（不得静默通过）。
    """
    try:
        from zoneinfo import ZoneInfo

        expected = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    except Exception as exc:  # pragma: no cover —— 依赖宿主 tzdata
        pytest.skip(f"宿主无 tzdata，独立机制不可用：{exc!r}")
    assert quota_day_default() == expected, "固定 +8 偏移必须与 Asia/Shanghai 日历一致"
    outs = _quota_day_in_tzs(
        "from app.living_circle.request_guard import quota_day_default;"
        "print(quota_day_default())"
    )
    assert len(set(outs)) == 1, f"quota_day_default() 随宿主机 TZ 漂移：{outs}"
    assert outs[0] == expected, "子进程口径必须等于独立机制算出的北京自然日"


def test_j02_daily_budget_factory_first_built_wins(caplog):
    """J2（🟠 · K8 裁决）：`get_daily_budget` **键只含身份** ⇒ 同 AK 二次注入 `cap`/`clock` 被忽略。

    ⚠️ 这是 E13 之外的**第二条静默陷阱**：`clock` 注入若撞上已存在的 AK，会**无声无效**。
    本用例把这条纪律钉死：对象必须同一、生效的必须是**首建**的 clock/cap、且两条冲突各留一条 WARNING。
    """
    c1 = lambda: "2026-01-01"  # noqa: E731
    c2 = lambda: "2026-02-02"  # noqa: E731
    with caplog.at_level(logging.WARNING, logger="app.living_circle.request_guard"):
        b1 = get_daily_budget("j2", 100, clock=c1)
        b2 = get_daily_budget("j2", 50, clock=c2)
    assert b1 is b2, "同 AK 必须返回同一份（键只含身份）"
    assert b2.clock is c1, "clock 以**首建**为准，第二个注入被忽略"
    assert b2.cap == 100, "cap 以**首建**为准"
    assert b1.date_key == "2026-01-01", "生效的是首建 clock"
    n = len([r for r in caplog.records if "以首建为准" in r.getMessage()])
    assert n == 2, f"cap 与 clock 两条冲突各应留 1 条 WARNING，实际 {n} 条"
    # 正确姿势：换一个**还没建过**的 AK ⇒ clock 生效
    b3 = get_daily_budget("j2-new", 100, clock=c2)
    assert b3.clock is c2 and b3.date_key == "2026-02-02"


def test_j08_rollover_is_idempotent_and_logs_once(caplog):
    """J8（🟢 幂等）：同一时刻连续读三个属性 + consume ⇒ 只滚动一次、解封日志**恰 1 条**。

    ⚠️ 必须**同时**断言日志条数：若只断言 `calls`，一个「每次读都归零」的非幂等实现同样能过。
    """
    now = {"d": "2026-09-22"}
    db = GlobalDailyBudget(cap=100, clock=lambda: now["d"])
    db.consume(5)
    now["d"] = "2026-09-23"
    with caplog.at_level(logging.INFO, logger="app.living_circle.request_guard"):
        assert db.date_key == "2026-09-23"
        assert db.calls == 0
        assert db.exhausted is False
        db.consume(2)
        assert db.calls == 2
    n = len([r for r in caplog.records if "跨日解封" in r.getMessage()])
    assert n == 1, f"解封日志应恰 1 条（幂等），实际 {n} 条"


def test_j09_missing_initial_date_discards_count(caplog):
    """J9（🟢 特征化 · 已裁决 2026-09-22）：绕过 `__post_init__` 的对象，**首读即作废计数**。

    ⚠️ 语义裁决：`_date_key` 为空 ⇒ 那批计数**属于哪一天未知** ⇒ 一律作废（不得凭空归给「今天」）。
    `__post_init__` 是**唯一合法初始化路径**；绕过它（`object.__new__` / dict 反序列化重建）
    属异常状态 ⇒ 必须**可观测**（WARNING），而不是静默丢数（B-5）。
    """
    db = GlobalDailyBudget.__new__(GlobalDailyBudget)
    db.cap = 100
    db.clock = lambda: "2026-09-22"
    db._calls = 7
    db._date_key = ""
    db._exhausted = True
    db._logged = False
    with caplog.at_level(logging.WARNING, logger="app.living_circle.request_guard"):
        assert db.calls == 0, "未知日的计数必须作废，不得归给今天"
        assert db.exhausted is False
    assert any("缺少初始日期" in r.getMessage() for r in caplog.records), \
        "绕过 __post_init__ 属异常状态，必须留 WARNING（否则静默丢数）"


def test_j10_consume_boundaries():
    """J10（🟢）：`cap` 边界 —— ① `cap=1` 首次 consume 立即耗尽；② 耗尽后**不得翻回**未耗尽。

    注：`calls` 是**节流计数**（不是计量真源，见类 docstring），耗尽后继续 consume 仍会累加 ——
    故②的正确不变量是「`exhausted` 保持 True」，而不是「计数不再增长」。
    """
    db = GlobalDailyBudget(cap=1, clock=lambda: "2026-09-22")
    assert db.exhausted is False
    db.consume(1)
    assert db.exhausted is True and db.calls == 1, "cap=1：首次 consume 即达上限（>= 语义）"
    db.consume(3)
    assert db.exhausted is True, "耗尽后继续 consume 不得把 exhausted 翻回 False"
    assert db.calls == 4


# ── J5 · A-5：跨 loop **并发**使用共享闸必须被具名拒绝 ────────
def test_j05_shared_guard_rejects_concurrent_multi_loop():
    """J5（🔴 · P1）：跨 loop **并发**使用同一把闸 ⇒ 抛具名 `SharedGuardLoopConflict`。

    ⚠️ **触发条件必须刻意制造**（与 H2 同一个坑）：`_bind_loop` 只在「旧原语上**仍有排队者**」
    时才拒绝；**顺序**复用（旧 loop 已跑完、`_waiters` 为空）是**合法**的（H2 就是那种）。
    故本用例若不制造排队者 ⇒ 恒绿**假护栏**。

    做法：loop A 起在**独立线程**里，用 `min_interval_s=10.0` 让第 2 个调用方在**持有 `sem` 时
    长睡 10s** ⇒ 第 3 个调用方只能排队 ⇒ `sem._waiters` **持续非空**（不是转瞬即空，故确定性）。
    然后**卡住不让 loop A 收工**；此时主线程在 loop B 上调 `acquire()`。

    ⚠️ 不能用 `min_interval_s=0`：那样 `acquire()` 立即返回并**释放** `sem`，`_waiters` 恒为 `None`
    （实测踩过一次）—— 本用例随即退化成假护栏。
    """
    rl = get_rate_limiter("j5", concurrency=1, min_interval_s=10.0)
    ready = threading.Event()
    stop = threading.Event()

    def loop_a():
        async def main():
            tasks = [asyncio.create_task(rl.acquire()) for _ in range(3)]
            for _ in range(400):  # 限时等排队者出现（第 2 个会持有 sem 睡满 10s ⇒ 稳定可等）
                await asyncio.sleep(0.005)
                if rl.sem._waiters:
                    break
            assert rl.sem._waiters, "前置条件不成立：旧 loop 上必须有排队者（否则本用例是假护栏）"
            ready.set()
            await asyncio.get_running_loop().run_in_executor(None, stop.wait)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(main())

    t = threading.Thread(target=loop_a, daemon=True)
    t.start()
    assert ready.wait(10), "loop A 未能在 10s 内造出排队者"
    try:
        async def loop_b():
            await rl.acquire()  # ← 必须抛具名异常（而非 asyncio 原始 RuntimeError）

        with pytest.raises(SharedGuardLoopConflict):
            asyncio.run(loop_b())
    finally:
        # 🔵 配对哨兵：清理必须做完，否则本用例会把「闸仍被旧 loop 持有」泄漏给后续用例
        stop.set()
        t.join(timeout=10)
        assert not t.is_alive(), "loop A 未收工 —— 共享闸仍在被旧 loop 持有（用例隔离失败）"


# ── J7 · A-4 / B-5：耗尽短路告警的门控 + 跨日重置 ──────────
def test_j07_exhausted_warning_gated_and_reset_by_rollover(caplog):
    """J7（🟠 + 🔵 配对哨兵）：耗尽短路的 WARNING **当日只打 1 次**，且**跨日解封后能再打**。

    ⚠️ 两个方向互为哨兵：只测 ① 会漏掉「跨日后仍静默」；只测 ② 会漏掉「当日重复刷屏」。
    修复前是**每次 `call()` 都打**（一次体检上百条 WARNING，把真实信号淹没）；
    而**相邻**的 `total_meltdown` 分支早有 `if not self.total_meltdown` 门控 —— 同族纪律不一致。
    """
    now = {"d": "2026-09-22"}
    budget = GlobalDailyBudget(cap=2, clock=lambda: now["d"])
    guard = CallGuard(daily_budget=budget, min_interval_s=0)

    async def work():
        return {"status": 0}

    async def drain():
        for _ in range(2):
            await guard.call(work)   # 用满预算
        for _ in range(3):
            await guard.call(work)   # 3 次短路（每次都命中告警分支）

    with caplog.at_level(logging.WARNING, logger="app.living_circle.request_guard"):
        asyncio.run(drain())
        n1 = len([r for r in caplog.records if "日预算耗尽" in r.getMessage()])
        assert n1 == 1, f"① 当日连续 3 次短路只应告警 1 次，实际 {n1} 次"

        caplog.clear()
        now["d"] = "2026-09-23"      # 跨日解封 ⇒ `_logged` 必须随之重置
        asyncio.run(drain())
        n2 = len([r for r in caplog.records if "日预算耗尽" in r.getMessage()])
        assert n2 == 1, (
            f"② 跨日解封后应**重新获得** 1 次告警额度，实际 {n2} 次"
            "（= 0 说明 `roll_over_if_needed` 未重置 `_logged`：解封静默）"
        )
