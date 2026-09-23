"""降级链路专项测试（计划 §14 · M 系列｜2026-09-22）。

**被测范围（决定红灯档位，复核必读）**：本文件走的都是**完整流水线 / 真实入口**
（`living_circle_pipeline` → `scope_or_degrade` → `degrade_policy` → `CallGuard`），
不是只调某个服务函数 —— 否则「降级是否真的发生」无法观测，用例会**假绿**。

为什么需要这一组（既有 U18/G9 不够）：
- U18 的 stub guard 是 `SimpleNamespace(total_meltdown=...)`，**没有** `budget_exhausted` 属性
  ⇒ 恰好绕过「真 `CallGuard` 上 `budget_exhausted` 恒 False 把老信号短路」这一缺陷（根因 A）。
- 精报链路（`refine_live_with_profile` / `_schedule_refine`）此前**零测试**，而 P0-1 就在那里。

档位：🟢 特征化绿 / 🔴 行为红 / 🔵 负向哨兵（本轮落地后全部转为 🟢/🔵，🔴 已随修复转绿）。
"""

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.core import db
from app.core.pipeline.living_circle import (
    _scene_key,
    _schedule_refine,
    create_living_circle_task,
)
from app.living_circle.caliber import caliber_payload_key
from app.living_circle.data_source import (
    CheckParams,
    LiveDataSource,
    Repository,
    refine_live_with_profile,
)
from app.living_circle.degrade_policy import (
    DETAIL_LABELS,
    degraded_block,
    DEGRADE_REASON_QUOTA_EXHAUSTED,
    DEGRADE_REASONS,
    degrade_reason,
    degraded_block,
    detail_label,
)
from app.living_circle.request_guard import CallGuard, get_daily_budget

# 复用同目录既有的 live 分支驱动件（stub / 工厂顶替 / 参数构造）—— 与 U18/U36 同一套，
# 避免第二套驱动件漂移。
from test_pipeline_living_circle import (
    KAILI_CENTER,
    PipelineStubBaidu,
    _live_params,
    _live_source,
    _run_pipeline,
)


# ── 驱动件 ──────────────────────────────────────────────────────

class GuardedStub(PipelineStubBaidu):
    """POI 调用**经真实 `guard.call()`** 发起 —— 让熔断真的发生在 guard 上。

    ⚠️ 与 U18 的关键差别：U18 的 stub 是**直置** `guard.total_meltdown = True`，
    且 guard 是 `SimpleNamespace`。真 `CallGuard` 上有 `budget_exhausted` 这个 `@property`
    （恒返回 bool、**永不缺失**）⇒ 旧实现的「缺失才回落」短路会**永久忽略** `total_meltdown`
    ⇒ 只有换成本 stub 才测得到（M3 的全部价值就在这里）。
    """

    def __init__(self, center, guard, flaky_first=False, **kw):
        super().__init__(center, **kw)
        self.guard = guard
        self.work_calls = 0
        self.flaky_first = flaky_first
        self._flaky_used = False

    async def _via_guard(self, factory):
        async def work():
            self.work_calls += 1
            return factory()

        return await self.guard.call(work)

    async def place_search(self, query, center, radius_m=2000, scope=2, page_size=20, max_pages=1):
        self.poi_calls += 1
        if self.flaky_first and not self._flaky_used:
            # 首次返回配额类错误（302/403/429）⇒ guard 内部重试 ⇒ 第二次成功
            def _factory():
                if self._flaky_used:
                    return {"status": 0}
                self._flaky_used = True
                return {"status": 403}

            await self._via_guard(_factory)
        else:
            await self._via_guard(lambda: {"status": 0})
        return self._poi_set(query, center)


class NullMeasureStub(PipelineStubBaidu):
    """测时全部失败（`None`）⇒ 等时圈族为空 —— 报障现场的最小复现（M5）。"""

    async def _measure_impl(self, travel_mode, origins, destination):
        self.max_pts = max(self.max_pts, len(origins))
        return [None for _ in origins]


class MeltedMeasureStub(PipelineStubBaidu):
    """测时经**已熔断**的 guard 发起 ⇒ 全部 `None`（供 M1/M2 造出「精报降级」前置）。"""

    def __init__(self, center, guard, **kw):
        super().__init__(center, **kw)
        self.guard = guard

    async def _measure_impl(self, travel_mode, origins, destination):
        async def work():
            return {"status": 0}

        await self.guard.call(work)  # 已熔断 ⇒ 返回 None
        return [None for _ in origins]


def _melted_guard(cap: int = 1, **kw):
    """造一个**经真实入口熔断**的 guard（不直置状态位 —— 直置是「贴着实现写」）。"""
    guard = CallGuard(max_total_calls=cap, min_interval_s=0, backoff_base_s=0.001, **kw)

    async def _burn():
        async def work():
            return {"status": 0}

        for _ in range(cap):
            await guard.call(work)

    asyncio.run(_burn())
    return guard


def _check(scene_name: str) -> CheckParams:
    return CheckParams(
        scene_name=scene_name,
        city="贵州·凯里",
        address="凯里市西门街道老街片区",
        center=KAILI_CENTER,
        study_radius_m=2500.0,
        sample_profile="standard",
        travel_mode="walking",
    )


def _done(events):
    return next(e for e in events if e["type"] == "done")


# ── M3 · 真 CallGuard 熔断 ⇒ 必须降级（根因 A 的真正判据）───────

def test_m3_real_callguard_meltdown_must_degrade(monkeypatch):
    """M3（P0）：真 `CallGuard(max_total_calls=N)` 在 POI 采集中途熔断 ⇒ 必须诚实降级。

    **被测范围**：完整流水线（含 `load_poi` → `degrade_if_incomplete`）。
    档位：修复前 🔴 行为红（真红 —— 存在正确实现可使其绿）；修复后 🟢。
    """
    guard = CallGuard(max_total_calls=3, min_interval_s=0, backoff_base_s=0.001)
    stub = GuardedStub(KAILI_CENTER, guard)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M3"))
    events = _run_pipeline(tid)

    # 前置守卫：熔断确实在 guard 上发生了（否则本用例空转）
    assert guard.total_meltdown is True, "前置不成立：guard 未熔断，本用例将假绿"
    assert _done(events)["data"].get("status") != "failed"
    rid = _done(events)["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    assert rep["living_circle"]["data_origin"] == "offline", "真 guard 熔断后必须降级（根因 A）"
    assert rep["living_circle"]["degraded"]["reason"] == DEGRADE_REASON_QUOTA_EXHAUSTED
    assert rep["living_circle"]["degraded"]["detail"] == "total_meltdown"
    assert db.get_task_full(tid)["status"] == "done"


# ── M4 · 抖动 + 重试成功 ⇒ 不降级（🔵 负向哨兵）──────────────

def test_m4_transient_quota_hiccup_must_not_degrade(monkeypatch):
    """M4（P0）：一次配额类错误 + guard 内部重试成功 ⇒ **照常出实时报告**。

    防的是「拿 `stats.quota_hits > 0` 当触发条件」的过度降级（架构评审 P1-1）：
    `quota_hits` 计在重试**内**，抖动后自愈也会 +1。

    **被测范围**：完整流水线。档位 🔵 —— 当前绿，新实现若过度动作则变红。
    """
    # ⚠️ 抖动码必须是 **403** —— `RATE_LIMIT_STATUS = {401,402,403,404,429}`，
    # 302 会被判成「业务错误」而不是配额类（实测踩到：quota_hits 恒 0 ⇒ 探针空转）。
    guard = CallGuard(
        max_total_calls=200, min_interval_s=0, max_retries=1, backoff_base_s=0.001
    )
    stub = GuardedStub(KAILI_CENTER, guard, flaky_first=True)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M4"))
    events = _run_pipeline(tid)

    # 探针有效性：抖动确实发生过（否则「没降级」可能是根本没抖动 ⇒ 空转）
    assert guard.stats.quota_hits >= 1, "探针失效：未制造出配额抖动，本用例空转"
    assert _done(events)["data"].get("status") != "failed"
    rid = _done(events)["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    # 核心：数据完整 ⇒ 不许降级
    assert rep["living_circle"]["data_origin"] == "live", "抖动后自愈不得降级（过度降级）"
    assert rep["living_circle"]["poi"]["points"], "数据完整性对照：POI 必须非空"
    assert "degraded" not in rep["living_circle"]


# ── M5 · 空等时圈 ⇒ 降级而非失败（报障现场）───────────────

def test_m5_empty_isochrone_degrades_instead_of_failing(monkeypatch):
    """M5（P0）：测时全部失败 ⇒ 等时圈族为空 ⇒ 降级，**不是**任务失败。

    修复前 `SpatialScope.from_iso` 先 raise（`scope.py:111`）⇒ 降级代码不可达 ⇒ 任务 failed
    （生产实测：`lc-112be580655a` 停在 measure 48%）。修复后 🟢。
    """
    stub = NullMeasureStub(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M5"))
    events = _run_pipeline(tid)

    done = _done(events)
    assert done["data"].get("status") != "failed", "空等时圈不得演变成调研失败（根因 B）"
    rep = db.get_living_circle_report(done["data"]["report_id"])
    assert rep["living_circle"]["data_origin"] == "offline"
    assert rep["living_circle"]["degraded"]["detail"] == "isochrone_empty"
    assert db.get_task_full(tid)["status"] == "done"


# ── M1 · 降级产物不得写进 live 缓存（P0-2）─────────────────

def test_m1_degraded_report_not_written_to_live_cache():
    """M1-a（P0 · 端到端）：精报降级后，live 缓存里**不得**出现 offline 报告。

    ⚠️ 假绿防线：本用例的断言在「没造出降级」时恒真 ⇒ 必须先断言降级**确实发生**。
    ⚠️ 本用例守的是**整条降级路径**（含「降级分支必须提前 return」）。它守**不住**
       「某个新入口直接 cache_report('live', 离线报告)」——那条由 M1-b 在唯一出口守。
    """
    guard = _melted_guard()
    stub = MeltedMeasureStub(KAILI_CENTER, guard)
    repo = Repository()
    check = _check("凯里老街-M1")

    report = asyncio.run(refine_live_with_profile(check, stub, repo, "standard"))
    assert report["data_origin"] == "offline", "前置不成立：没造出降级，断言将空转"

    key = caliber_payload_key(
        check.scene_name, tuple(check.center), check.study_radius_m, "standard", check.travel_mode
    )
    cached = repo.get_report("live", key)
    assert cached is None or cached.get("data_origin") != "offline", (
        "降级产物被写进 live 缓存 ⇒ 后续所有同中心/邻近请求都会命中离线口径（P0-2）"
    )


def test_m1b_live_cache_refuses_offline_report():
    """M1-b（P0 · 唯一出口）：`cache_report('live', …)` 直接喂离线报告 ⇒ **必须被拒**。

    为什么必须有这条：M1-a 是端到端的，而三个入口在降级分支都**提前 return** ⇒
    曾经那三份 `if data_origin != "offline"` 全是**死代码**，删掉它们 M1-a 照样绿
    （负对照实测 NC-m2：`failed=0` ⇒ M1-a 是假绿）。真正能判别的地方是唯一写入者
    `Repository.cache_report`：把守卫放那儿之后，**任何**新入口都跑不掉。
    """
    repo = Repository()
    key = "m1b-offline-refused"

    # 正对照：实时报告照写不误（守卫不能误伤）
    repo.cache_report("live", key + "-live", {"data_origin": "live"})
    assert repo.get_report("live", key + "-live") is not None, "守卫误伤：实时报告也被拒了"

    # 负对照：离线报告必须进不去
    repo.cache_report("live", key, {"data_origin": "offline"})
    assert repo.get_report("live", key) is None, (
        "live 缓存收下了离线报告 ⇒ 后续同中心/邻近请求会命中离线口径（P0-2）"
    )

    # 同一份离线报告在**自己的**命名空间里不受影响（不许把规则扩大化）
    repo.cache_report("offline", key, {"data_origin": "offline"})
    assert repo.get_report("offline", key) is not None, "规则被扩大化：offline 域也不让写了"


# ── M2 · 精报降级 ⇒ 不落库、不替换粗报（P0-1）────────────

def test_m2_degraded_refine_does_not_replace_coarse_report(monkeypatch):
    """M2（P0）：精报若降级为离线估算 ⇒ **保留粗报**，绝不先删后存。

    现场：`_schedule_refine` 传 `replace_scene=True` ⇒ `_finalize_living_report` 先
    `delete_living_circle_reports_for_scene`，而 `assess_geometry` 对 offline 整段豁免
    ⇒ 用离线骨架覆盖并删除已交付的实时报告。
    """
    # ① 先跑出一份**实时**粗报
    coarse_stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(coarse_stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M2"))
    events = _run_pipeline(tid)
    rid = _done(events)["data"]["report_id"]
    assert db.get_living_circle_report(rid)["living_circle"]["data_origin"] == "live"

    # ⚠️ tasks 表**没有** `scene_key` 列 ⇒ 用流水线自己的 `_scene_key` 现算（与粗报落库同键）
    scene_key = _scene_key(_live_params(scene_name="凯里老街-M2"))

    def _count():
        conn = db._connect()
        return conn.execute(
            "SELECT COUNT(*) FROM living_circle_reports WHERE scene_key=?", (scene_key,)
        ).fetchone()[0]

    before = _count()
    assert before >= 1

    # ② 精报用「已熔断」的 client ⇒ 产出离线报告
    guard = _melted_guard()
    melted = MeltedMeasureStub(KAILI_CENTER, guard)
    check = _check("凯里老街-M2")

    async def _drive():
        task = _schedule_refine(melted, check, Repository(), scene_key, [], "standard")
        await task

    asyncio.run(_drive())

    # ③ 粗报必须还在，且没被离线产物替换
    assert _count() == before, "精报降级后行数变化 ⇒ 粗报被删了（P0-1）"
    still = db.get_living_circle_report(rid)
    assert still is not None and still["living_circle"]["data_origin"] == "live", (
        "粗报被离线精报覆盖（P0-1）"
    )


# ── M6 · 熔断是 per-task 语义（不跨任务）──────────────────

def test_m6_guard_is_per_task_not_process_wide():
    """M6（P1）：两个数据源各自持有**独立的** `CallGuard`；共享的只有 rate_limiter / daily_budget。

    外部旁证（breaker 状态机「test every transition」的等价物）：本系统没有「半开/恢复」态，
    「恢复」靠的就是**每任务一个新 guard** —— 这条断言钉住这个隐含契约（见契约缺口 K14）。
    """
    a = LiveDataSource(ak="m6-ak")
    b = LiveDataSource(ak="m6-ak")
    try:
        assert a.client.guard is not b.client.guard, "两个数据源共用了同一个 guard ⇒ 熔断会跨任务传染"
        # 共享闸仍然共享（β 的不变量，防「为了隔离而把闸也拆了」）
        assert a.client.guard.rate_limiter is b.client.guard.rate_limiter
    finally:
        asyncio.run(a.aclose())
        asyncio.run(b.aclose())


# ── M7 · 默认禁用态（cap=0）不误降 ────────────────────────

def test_m7_disabled_daily_budget_does_not_degrade():
    """M7（P1）：默认 `baidu_daily_quota=0`（禁用）时，即便命中配额错误也**不得**降级。"""
    # max_retries=0：只发一次，quota_hits 恰为 1（默认 4 次重试会把它推到 5，且退避拖慢 6s）
    guard = CallGuard(
        daily_budget=get_daily_budget("m7", 0), min_interval_s=0, max_retries=0
    )
    assert guard.budget_exhausted is False, "cap=0 时禁用（G7 同款不变量）"

    async def _hit():
        async def quota():
            return {"status": 403}

        await guard.call(quota)

    asyncio.run(_hit())
    assert guard.stats.quota_hits == 1, "探针有效性：配额错误确实被计到"
    # 数据完整（等时圈与 POI 都有）⇒ 不降级
    assert degrade_reason(guard, has_isochrones=True, has_poi=True) is None


# ── M8 · degraded.reason 取值闭集（K11）───────────────────

def test_m8_reason_is_a_closed_set():
    """M8（P1）：`degraded.reason` 取值必须落在闭集内（U18/G9 钉住的字面量 ∈ 闭集）。"""
    assert DEGRADE_REASONS == ("baidu_quota_exhausted",)
    assert DEGRADE_REASON_QUOTA_EXHAUSTED in DEGRADE_REASONS
    block = degraded_block(None, isochrone_empty=True)
    assert block["reason"] in DEGRADE_REASONS
    assert block["detail"] == "isochrone_empty"
    # detail → 文案标签：每个标签都能解析（未知取值回落 unknown，不抛异常）
    assert detail_label("total_meltdown") == "总量熔断"  # U18 断言文案含「熔断」
    assert detail_label("不存在的取值") == detail_label("unknown")


# ── M10 · 硬上限不被重试超支（R-6）────────────────────────

def test_m10_total_call_ceiling_is_not_overspent_by_retries():
    """M10（P1）：`max_total_calls=K` 时，实际发出的请求数 **≤ K**（重试也算）。

    修复前上限只在 `call()` 入口判一次，而计数在重试循环内递增 ⇒ 一次调用最多发
    `1 + max_retries` 次 ⇒ 实测预算 45 发到 53（超 18%）。
    """
    cap, attempts = 3, 0
    guard = CallGuard(
        max_total_calls=cap, min_interval_s=0, max_retries=4, backoff_base_s=0.001
    )

    async def _impl():
        nonlocal attempts

        async def work():
            nonlocal attempts
            attempts += 1
            raise ConnectionError("net down")  # 可重试 ⇒ 会走满重试循环

        await guard.call(work)

    asyncio.run(_impl())
    assert attempts <= cap, f"硬上限被重试超支：发了 {attempts} 次 > {cap}"
    assert guard.total_meltdown is True


# ── M9 · G-4 守卫自测（AST，非正则）───────────────────────

def _load_guard_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_guard_construction.py"
    spec = importlib.util.spec_from_file_location("_cgguard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_m9_g4_flags_a_new_from_iso_call_site():
    """M9（P1）：在白名单之外新增一处 `SpatialScope.from_iso(` ⇒ G-4 必须报违例。"""
    mod = _load_guard_script()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rogue = root / "app" / "living_circle"
        rogue.mkdir(parents=True)
        (rogue / "new_entry.py").write_text(
            "from app.living_circle.scope import SpatialScope\n"
            "def somewhere(iso):\n"
            "    return SpatialScope.from_iso(None, (0, 0), 2500, iso)\n",
            encoding="utf-8",
        )
        bad, _ = mod.scan(root)
        assert any("G-4" in line for line in bad), f"新增调用点未被告发（守卫有洞）：{bad}"


def test_m9b_g4_accepts_the_allowlisted_entry():
    """M9 的**合法必绿**对照：白名单内的 `scope_or_degrade` 调用点不得被告发。"""
    mod = _load_guard_script()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ds = root / "app" / "living_circle"
        ds.mkdir(parents=True)
        (ds / "data_source.py").write_text(
            "from app.living_circle.scope import SpatialScope\n"
            "async def scope_or_degrade(iso):\n"
            "    return SpatialScope.from_iso(None, (0, 0), 2500, iso)\n",
            encoding="utf-8",
        )
        bad, _ = mod.scan(root)
        assert not [line for line in bad if "G-4" in line], f"合法入口被误报：{bad}"


def test_m9c_guard_script_passes_on_this_repo():
    """M9 的守门用例：本仓当前**必须**合法（它才是把脚本变成纪律的那一步，同 J3/J6）。"""
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_guard_construction.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"γ 守卫在本仓判红：\n{r.stderr}"


# ── M12 · G9（日预算）侧的事件序列镜像 U36 ────────────────

def test_m12_budget_exhausted_keeps_event_sequence_complete(monkeypatch):
    """M12（P2）：日预算耗尽 ⇒ 在**首个分流点**降级，事件序列仍须 1..7 完整（U36 的 G9 侧镜像）。"""
    budget = get_daily_budget("m12-ak", 2)
    guard = CallGuard(daily_budget=budget, min_interval_s=0)

    async def _exhaust():
        async def work():
            return {"status": 0}

        for _ in range(2):
            await guard.call(work)

    asyncio.run(_exhaust())
    assert budget.exhausted is True, "前置不成立：日预算未耗尽"

    stub = PipelineStubBaidu(KAILI_CENTER)
    stub.guard = guard
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M12"))
    events = _run_pipeline(tid)

    seqs = [e["data"]["stage_seq"] for e in events if e["type"] == "progress"]
    assert seqs == list(range(1, 8)), f"进度阶段序列必须完整 1..7：{seqs}"
    rep = db.get_living_circle_report(_done(events)["data"]["report_id"])
    assert rep["living_circle"]["data_origin"] == "offline"
    assert rep["living_circle"]["degraded"]["detail"] == "daily_budget_exhausted"


# ── M11（后端侧）· 降级成因标签的跨语言契约 ──────────────────────
# 与前端 `frontend/src/__tests__/degradeDisclosure.test.ts` 读**同一份**夹具
# （范式同 compareDiffContract.json）：改标签必须同时改夹具 + 两侧表。
_DEGRADE_CONTRACT = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "__tests__" / "fixtures" / "degradeDetailContract.json"
)


def test_m11_degrade_labels_match_contract():
    """M11（后端侧）：`degrade_policy.DETAIL_LABELS` 必须与跨语言夹具逐字一致。

    ⚠️ 假绿防线：断言锚的是**夹具里读出来的字面量**，不是 `detail_label(x)` 的返回值
    （后者在把函数改坏时等号两边一起变）。
    """
    assert _DEGRADE_CONTRACT.is_file(), f"契约夹具缺失：{_DEGRADE_CONTRACT}"
    contract = json.loads(_DEGRADE_CONTRACT.read_text(encoding="utf-8"))

    assert DETAIL_LABELS == contract["labels"], (
        "后端标签表与跨语言夹具不一致 ⇒ 前端会显示另一套归因（同一口径两处实现）"
    )
    for case in contract["_cases"]:
        assert detail_label(case["detail"]) == case["label"], case
    # 未知/缺失一律回落，且**不抛异常**
    for bad in ("", None, "NO_SUCH_DETAIL", "total-meltdown"):
        assert detail_label(bad) == contract["_fallback"], bad


def test_m11_degraded_node_reaches_the_report(monkeypatch):
    """M11：`degraded` 节点必须随报告**完整送达**（不被 `assemble_report` 过滤）。

    前端靠它区分「未联网离线」与「配额熔断降级」；节点丢了 ⇒ 披露全盘失效且**静默**
    （报告照出、横幅照显示「离线估算」，只是成因永远看不见）。
    """
    budget = get_daily_budget("m11-ak", 2)
    guard = CallGuard(daily_budget=budget, min_interval_s=0)

    async def _exhaust():
        async def work():
            return {"status": 0}

        for _ in range(2):
            await guard.call(work)

    asyncio.run(_exhaust())
    assert budget.exhausted is True, "前置不成立：日预算未耗尽"

    stub = PipelineStubBaidu(KAILI_CENTER)
    stub.guard = guard
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-M11"))
    events = _run_pipeline(tid)
    rep = db.get_living_circle_report(_done(events)["data"]["report_id"])
    lc = rep["living_circle"]

    assert lc["data_origin"] == "offline", "前置不成立：没造出降级"
    dg = lc.get("degraded")
    assert dg, "降级节点没进报告 ⇒ 前端无法区分成因（R-7 全盘失效且静默）"
    # 三个字段一个都不能少：reason 机器读、detail 出文案、note 是给用户看的完整一句
    assert dg["reason"] == DEGRADE_REASON_QUOTA_EXHAUSTED
    assert dg["detail"] == "daily_budget_exhausted"
    assert dg["note"]


def test_m11_history_item_carries_degraded():
    """M11(q-3)：历史列表项必须带上 `degraded`，否则用户翻旧报告时看不到成因。"""
    dg_block = degraded_block(guard=None, isochrone_empty=True)
    # 直接构造一条 offline + degraded 的报告落库，再走列表接口
    params = _live_params(scene_name="凯里老街-M11H")
    events = _run_pipeline(create_living_circle_task(params))
    rid = _done(events)["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    rep["living_circle"]["degraded"] = dg_block
    db.save_living_circle_report(rep, _scene_key(params))

    items = db.list_living_circle_reports(limit=50, include_incomplete=True)
    hit = [i for i in items if i["id"] == rid]
    assert hit, "报告未出现在历史列表（前置不成立 ⇒ 断言会空转）"
    assert hit[0]["degraded"] == dg_block, (
        "历史列表丢了 degraded ⇒ 列表里「离线估算」分不清成因（R-7 q-3）"
    )
