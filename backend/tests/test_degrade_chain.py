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
from types import SimpleNamespace

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
    live_forensic_steps,
    Repository,
    refine_live_with_profile,
    RoundOutcome,
    STEP_COLLECT,
    STEP_DEGRADED,
    STEP_JUDGE,
    STEP_MEASURE,
    STEP_REPORT,
    STEP_ROUND,
)
from app.living_circle.isochrone import IsochroneEngine
from app.living_circle.degrade_policy import (
    DEGRADE_REASON_QUOTA_EXHAUSTED,
    DEGRADE_REASONS,
    DETAIL_LABELS,
    PARTIAL_NOTE,
    degrade_detail,
    degrade_reason,
    degraded_block,
    detail_label,
    partial_for,
)
from app.living_circle.judgement import STAT_KEYS
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


class EmptyPoiStub(PipelineStubBaidu):
    """测时**正常**、但 8 类 POI 全空 ⇒ 第二条降级出路（`poi_empty`）的最小前置（M14-c）。

    与 `NullMeasureStub` 刻意分开：那支断在测时阶段（等时圈族为空，第一条出路），
    这支走过了 `scope_or_degrade` 与 `load_poi`，是在**采集之后**被残缺判定拦下的 ——
    两条出路的 step 载荷形状不同（这支带 `scope`/`collected`），判据也得分开钉。
    """

    def _poi_set(self, query, center):
        return []


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
    """M3（P0）：真 `CallGuard(max_total_calls=N)` 在 POI 采集中途熔断 ⇒ 任务照以 done 收尾。

    **被测范围**：完整流水线（含 `load_poi` → `degrade_if_incomplete`）。
    档位：修复前 🔴 行为红（真红 —— 存在正确实现可使其绿）；修复后 🟢。

    ⚠️ 判据随 **D1①（计划 v4 阶段 4）重指**：这条用例原本钉的是「熔断 ⇒ 整份 offline」。
    实测 N=3 时矩阵只占掉前 1~2 次调用，熔断发生在**取证途中** —— 等时圈是真测过的，
    把它打回 detour_k 正圆等于「用一定不出错换掉本来已经算出来的东西」。本用例保留的
    是它真正要守的那件事：**绝不因百度配额演成「调研失败」**。offline 那条路另有
    `test_d1_isochrone_stage_abort_still_degrades` 守着（测时阶段中止，几何没拿到）。
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
    lc = rep["living_circle"]
    assert lc["data_origin"] == "live", "取证途中熔断不许丢掉已测过的实时几何（D1①）"
    assert "degraded" not in lc, f"partial 不是降级：{lc.get('degraded')}"
    assert lc["partial"]["detail"] == "total_meltdown", (
        f"残缺必须可归因到配额信号：{lc.get('partial')}"
    )
    assert lc["isochrones"], "保留 live 几何不是空壳：等时圈族得真在报告里"
    assert lc["sampling"]["interpolation"] != "circular_approx", (
        "熔断产出正圆 = 已知 P1 答辩反证据，D1 就是为了堵掉它"
    )
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
        task = _schedule_refine(melted, check, Repository(), scene_key, [], [], "standard")
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


# ── M13/M14 · G-9 取证编排单实现（计划 v6.1 片 0）────────────────
#
# 片 0 收拢掉的是**三份**同构编排（pipeline live 分支 / `LiveDataSource.compute` /
# `refine_live_with_profile`）。收拢这件事本身没有运行时症状可测：三份都跑得过、
# 事件都发得出 —— 缺陷的形状是「以后改一份、漏两份」。所以判据只能是**静态**的
# （谁还在别处串这些原语）+ **接缝契约**（唯一那份按什么顺序交出事实）。
# M13 系列守前者，M14 系列守后者。

# 合法形态：**六个**取证原语各调一次，且全部落在 `live_forensic_steps` 函数体内。
# 第六名 `collect_triad_evidence` 是片 4（取证回合）加进 G-9 的 —— 这份桩必须跟着长，
# 否则 M13b 会替"新原语其实没人守"背书（它报的就是 `{'collect_triad_evidence': 0}`）。
_G9_LEGAL_SOURCE = (
    "from app.living_circle.data_source import (bind_evidence, degrade_if_incomplete,\n"
    "                                           load_poi, scope_or_degrade)\n"
    "from app.living_circle.poi_collector import POIBudget, collect_triad_evidence\n"
    "async def live_forensic_steps(client, engine, check):\n"
    "    scope, degraded = await scope_or_degrade(iso={}, params=check)\n"
    "    if degraded is not None:\n"
    "        return degraded\n"
    "    collected = await load_poi(client, check.center, 2000, scope=scope)\n"
    "    scope = bind_evidence(scope, collected)\n"
    "    degraded = await degrade_if_incomplete(per_category=collected.per_category,\n"
    "                                           params=check)\n"
    "    if degraded is not None:\n"
    "        return degraded\n"
    "    round1 = await collect_triad_evidence(client, scope, {}, POIBudget(total=0),\n"
    "                                          round_no=1)\n"
    "    return assemble_living_circle(check, {}, collected.per_category,\n"
    "                                  collected.triads, scope)\n"
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_m13_g9_flags_a_second_forensic_orchestration(tmp_path):
    """M13（P1 · 敏感性对照）：在唯一入口之外再串一遍原语 ⇒ G-9 必红。

    桩里那段就是被删掉的 pipeline live 分支的形状（自己调 `load_poi`）。
    合成树里没有 `data_source.py` ⇒ 计数那半边判据不参与 ⇒ 应当**恰好一条**违例。
    """
    mod = _load_guard_script()
    _write(
        tmp_path / "app/core/pipeline/rogue.py",
        "from app.living_circle.data_source import load_poi\n"
        "async def live_branch(client, scope):\n"
        "    return await load_poi(client, (0, 0), 2000, scope=scope)\n",
    )
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-9" in line]
    assert len(hits) == 1, f"新增的第二份取证编排未被告发（守卫有洞）：{bad}"
    assert "rogue.py" in hits[0] and "load_poi" in hits[0], hits[0]


def test_m13b_g9_accepts_the_allowlisted_orchestration(tmp_path):
    """M13 的**合法必绿**对照：五步各一次、都在 `live_forensic_steps` 内 ⇒ 不报。

    没有这条，M13 可能只是「任何树都红」的噪声门（那种门的下场是被关掉）。
    """
    mod = _load_guard_script()
    _write(tmp_path / "app/living_circle/data_source.py", _G9_LEGAL_SOURCE)
    bad, _ = mod.scan(tmp_path)
    assert not [line for line in bad if "G-9" in line], f"唯一入口被误报：{bad}"


def test_m13c_g9_fires_when_the_orchestration_drops_a_step(tmp_path):
    """M13c（P1 · **少做一步**也要红）：从生成器里删掉 `bind_evidence` 那一步 ⇒ G-9 报计数。

    这条是 M13 的另一半：只拦「多抄一份」的门守不住「这一份自己漏了一步」，
    而「三份各自漏一点」正是收拢前真实存在的病根。
    """
    mut = _G9_LEGAL_SOURCE.replace(
        "    scope = bind_evidence(scope, collected)\n", ""
    )
    assert len(mut.splitlines()) == len(_G9_LEGAL_SOURCE.splitlines()) - 1, (
        "变异没落到桩源码上（那行字面量已被改走）⇒ 本用例会退化成 M13b 的恒绿"
    )
    mod = _load_guard_script()
    _write(tmp_path / "app/living_circle/data_source.py", mut)
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-9" in line]
    assert len(hits) == 1, f"掉一步未被告发（只守「多抄」的门）：{bad}"
    assert "bind_evidence" in hits[0], hits[0]


# ── M14 · 唯一编排的**步骤顺序**契约（回合循环要接的接缝）────────

async def _collect_steps(client, check, **kw) -> list:
    return [s async for s in live_forensic_steps(client, IsochroneEngine(), check, **kw)]


def test_m14_forensic_steps_emit_the_frozen_order_on_the_happy_path():
    """M14-a：完整取证 ⇒ **骨架**序列恰为 `measure → collect → judge → report`，
    而 `round` 只许插在 `collect` 与 `judge` 之间（片 4 之后这条才成立）。

    钉顺序而不是钉内容，是因为 pipeline 的事件文本、`stage_seq` 与 `evidence_count`
    都是**按这些时刻**长的（`test_u36`/`test_m12` 守上屏那一面）。取证回合（片 4）
    把这个序列包进循环里 ⇒ 顺序一旦漂，事件就会在没人改 pipeline 的情况下变样。

    ⚠️ 片 4 把这条从「四步逐字等长」重指成「骨架等长 + 插入点受限」，两件事各守一半：
    骨架那条一字未改（四类仍在、相对次序不许动）；新增的是"回合步只能落在这个缝里"，
    因为 `round` 步交的是"补采之后的新判定"，跑到 `judge` 之后或 `collect` 之前都是分家。
    这份 stub 现在**确实**会打一个回合（凯里那三类的实测边界落在可扩的档位上），
    所以这条同时也是"回合进了唯一编排"的顺序证据 —— 不许有人为了让它变四步而砍回合。

    ⚠️ 片 1a 改的是**两个数**，别把它们混成一句（第十一轮 P1：原文写「四步升到五步」，
    与下面那条四元素断言自相矛盾）：kind **名册**从四类升到五类（新增 `judge`，与既有
    `degraded` 一样是分支类，happy path 走不到它），而本用例这条 happy path 的**步骤序列**
    从三步升到四步。片 4 再加一名 `round`（它是分支类：只在真打了回合的那次跑动里出现）。
    上屏事件序列仍是三步的量 —— `judge` 一步**不发事件**，那句由 `test_u36` 守逐字节相同。
    """
    steps = asyncio.run(_collect_steps(PipelineStubBaidu(KAILI_CENTER), _check("凯里老街-M14")))
    kinds = [s.kind for s in steps]
    by_kind = {s.kind: s for s in steps}

    assert [k for k in kinds if k != STEP_ROUND] == [
        STEP_MEASURE, STEP_COLLECT, STEP_JUDGE, STEP_REPORT
    ], f"取证步骤骨架漂了：{kinds}"
    _judge_at = kinds.index(STEP_JUDGE)
    _collect_at = kinds.index(STEP_COLLECT)
    assert all(_collect_at < i < _judge_at for i, k in enumerate(kinds) if k == STEP_ROUND), (
        f"`round` 步跑到了 collect/judge 之外：{kinds}")
    # `measure` 必须**先于**采集流出：这是 SSE「边跑边出」的唯一保证，
    # 用「一把协程返回末值」的写法实现同一编排就会在这里红。
    first = by_kind[STEP_MEASURE]
    assert first.iso.get("isochrones"), "首步没带等时圈 ⇒ measure 事件将无事实可发"
    assert first.collected is None and first.report is None, "首步就交报告 = 事件后置"
    collect = by_kind[STEP_COLLECT]
    assert collect.collected.per_category, "collect 步必须交出采集事实（POI 计数吃它）"
    assert collect.partial is None, (
        "健康 stub 不该在**采集那一刻**带残缺声明 —— 回合的缺口晚一步才成形（`round`/`judge` 步上）"
    )
    assert collect.judgement is None, "判定不许发生在采集步（它在 bind_evidence 之后）"
    judged = by_kind[STEP_JUDGE]
    assert judged.judgement is not None, "judge 步必须把判定产物交出去（回合读的就是它）"
    assert judged.report is None, "judge 步不许顺手把报告也交了 —— 组装在它之后"
    assert by_kind[STEP_REPORT].report["data_origin"] == "live"
    assert by_kind[STEP_REPORT].report["poi"]["points"], "组装步的报告须已含点位"


# ── M15 · G-10 判定唯一入口（片 1a 的结构闸）──────────────────

# 合法形状：唯一入口在编排层，三个视图壳与 `_verdict_masks` 全在 blindspot 内部按表互调。
_G10_LEGAL_BLINDSPOT = (
    "def _verdict_masks():\n"
    "    return 1\n"
    "def cover_matrix():\n"
    "    return _verdict_masks()\n"
    "def undecided_mask():\n"
    "    return _verdict_masks()\n"
    "def judge_once():\n"
    "    return _verdict_masks()\n"
    "def find_blindspots_with_stats():\n"
    "    return judge_once()\n"
    "def find_blindspots():\n"
    "    return judge_once()\n"
)
_G10_LEGAL_DATA_SOURCE = (
    "from app.living_circle.blindspot import judge_once\n"
    "async def live_forensic_steps():\n"
    "    return judge_once()\n"
)


def _g10_tree(root: Path, blindspot_src: str = _G10_LEGAL_BLINDSPOT) -> None:
    _write(root / "app/living_circle/blindspot.py", blindspot_src)
    _write(root / "app/living_circle/data_source.py", _G10_LEGAL_DATA_SOURCE)


def test_m15_g10_flags_a_second_judging_entry(tmp_path):
    """M15（P1）：在登记表之外调 `judge_once` ⇒ G-10 必红。

    桩里那段是「第四份取证编排」的**判定半边**：新入口自己判盲，产物就与线上那份无关，
    回合与报告各吃一块证据区域 —— G-9 拦不住它（G-9 只数取证步骤原语）。
    """
    mod = _load_guard_script()
    _g10_tree(tmp_path)
    _write(
        tmp_path / "app/core/pipeline/rogue.py",
        "from app.living_circle.blindspot import judge_once\n"
        "def somewhere(center, scope, triads):\n"
        "    return judge_once(center, scope, triads)\n",
    )
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-10" in line]
    assert len(hits) == 1, f"第二处判定入口未被告发（守卫有洞）：{bad}"
    assert "rogue.py" in hits[0] and "judge_once" in hits[0], hits[0]
    # 这里只钉**文本不串号**：M13 系列按 `"G-9" in line` 过滤，所以 G-10 的违例文案里
    # 不许出现 `G-9` 字样。⚠️ 第一次写这条时我把它写成了「整棵树滤不出 G-9」—— 那是错的：
    # 这棵合成树里的 `data_source.py` 不含取证编排，G-9 的计数判据**本来就该红**
    # （实测这次全量就是这么报的）。合成树里别的规则合法作响，不是污染。
    assert "G-9" not in hits[0], hits[0]


def test_m15b_g10_flags_production_use_of_the_old_view(tmp_path):
    """M15b（P1）：生产侧调旧报告视图 `cover_matrix` ⇒ 也必红（期望 0 那一类）。

    这是片 1a 之后最省事的回退形状 —— 「先拿现成的三元组用着」，一步之后就是第二处
    逐格判定，而它不会出现在任何一条事件序列用例里。
    """
    mod = _load_guard_script()
    _g10_tree(tmp_path)
    _write(
        tmp_path / "app/core/pipeline/rogue2.py",
        "from app.living_circle.blindspot import cover_matrix\n"
        "def somewhere(center, scope, point_sets):\n"
        "    return cover_matrix(center, scope, point_sets)\n",
    )
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-10" in line]
    assert len(hits) == 1, f"生产侧旧视图调用未被告发：{bad}"
    assert "cover_matrix" in hits[0], hits[0]


def test_m15c_g10_accepts_the_registered_layout(tmp_path):
    """M15 的**合法必绿**对照：登记表里那套形状不许误报。

    没有这条，M15/M15b 可能只是「任何树都红」的噪声门。
    桩里的计数与 `JUDGE_EXPECTED_CALLS` 逐名相等：`judge_once` 3（编排 1 + 两壳 2）、
    `_verdict_masks` 3（三个视图各 1）、其余四名 0。
    """
    mod = _load_guard_script()
    _g10_tree(tmp_path)
    bad, _ = mod.scan(tmp_path)
    assert not [line for line in bad if "G-10" in line], f"登记表内的形状被误报：{bad}"


def test_m15d_g10_fires_when_a_registered_call_site_disappears(tmp_path):
    """M15d（P1）：登记表里的调用点**掉了**也要红 —— 只拦「多一处」的闸会留下过期豁免。

    形状：把 `find_blindspots` 改成自己 `_verdict_masks`（不再走唯一入口）⇒
    `judge_once` 从 3 掉到 2。这正是片 0 那三份编排的起点形状：各走各的、没人报错。
    """
    mut = _G10_LEGAL_BLINDSPOT.replace(
        "def find_blindspots():\n    return judge_once()\n",
        "def find_blindspots():\n    return _verdict_masks()\n",
    )
    assert mut != _G10_LEGAL_BLINDSPOT, "变异没落到桩源码上 ⇒ 本用例退化成 M15c 的恒绿"
    mod = _load_guard_script()
    _g10_tree(tmp_path, mut)
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-10" in line]
    assert len(hits) == 1, f"调用点掉出一处未被告发：{bad}"
    assert "'judge_once': (2, 3)" in hits[0], hits[0]


def test_m15e_g10_fires_through_an_import_alias(tmp_path):
    """M15-e（第十一轮 P0-3）：`import judge_once as probe` 再调 `probe(...)` ⇒ 仍必红。

    G-10 的登记表是**按名字**匹配的：别名把名字换掉、调用照旧，改前这棵树在闸下**全绿**
    —— 那意味着「第二处逐格判定」只要改一行导入写法就能重新开张，而片 1a 的全部立论
    （判定只有一处、掩码与账目同源）就只剩约定没有闸。这条用例的红点判据是**报文里
    出现原名 `judge_once`**：只有做了归一才会出现，不归一时命中数是 0。
    """
    mod = _load_guard_script()
    _g10_tree(tmp_path)
    _write(
        tmp_path / "app/core/pipeline/rogue_alias.py",
        "from app.living_circle.blindspot import judge_once as probe\n"
        "def somewhere(center, scope, triads):\n"
        "    return probe(center, scope, triads)\n",
    )
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-10" in line]
    assert len(hits) == 1, f"别名调用点未被告发（名字匹配可被 `as` 绕过）：{bad}"
    assert "rogue_alias.py" in hits[0] and "judge_once" in hits[0], hits[0]


def test_m15f_g10_fires_through_getattr(tmp_path):
    """M15-f（第十一轮 P0-3 的另一半）：`getattr(mod, "judge_once")(...)` ⇒ 必红。

    别名好歹要改导入；getattr 用字符串取函数，导入行一字不动。生产侧没有任何理由
    动态取用登记表成员，所以这条**不并入计数**（并入就等于给它一间合法房间），直接判红。
    """
    mod = _load_guard_script()
    _g10_tree(tmp_path)
    _write(
        tmp_path / "app/core/pipeline/rogue_dyn.py",
        "import app.living_circle.blindspot as bs\n"
        "def somewhere(center, scope, triads):\n"
        "    return getattr(bs, 'judge_once')(center, scope, triads)\n",
    )
    bad, _ = mod.scan(tmp_path)
    hits = [line for line in bad if "G-10" in line]
    assert len(hits) == 1, f"getattr 动态取用未被告发：{bad}"
    assert "rogue_dyn.py" in hits[0] and "getattr" in hits[0], hits[0]



def test_m14b_forensic_steps_exit_with_degraded_at_the_first_branch():
    """M14-b：测时阶段中止（等时圈族为空）⇒ 只交 `measure` 再交 `degraded`，**没有** collect。

    两条降级出路都以 `STEP_DEGRADED` 交出（调用方据此只发一条「降级为离线估算」消息，
    `evidence_count=0`）。这里守的是「降级步之后编排必须提前收尾」—— P0-6 那两份旧抄本
    各自漏过的正是这一步的 return。
    """
    steps = asyncio.run(
        _collect_steps(NullMeasureStub(KAILI_CENTER), _check("凯里老街-M14b"))
    )

    assert [s.kind for s in steps] == [STEP_MEASURE, STEP_DEGRADED], (
        f"降级出路不该再走采集：{[s.kind for s in steps]}"
    )
    degraded = steps[-1].report
    assert degraded["data_origin"] == "offline"
    assert degraded["degraded"]["detail"] == "isochrone_empty"
    assert steps[-1].collected is None, "降级步不该假装采到过东西"


def test_m14c_forensic_steps_exit_with_degraded_when_poi_is_empty():
    """M14-c（第十一轮 P1）：**第二条**降级出路（等时圈有、POI 全空）也要在生成器级钉住。

    改前只有 M14-b 一条：那条走的是**测时阶段**分流（`scope_or_degrade` 之前就断了），
    而 POI 全空这支要一路走过 `load_poi` + `bind_evidence` 才被 `degrade_if_incomplete`
    拦下 —— 载荷形状不同（这支**带** `scope`/`collected`），`judge`/`report` 两步都在它之后。
    这条缺着，「采集之后 return 掉」就只由 `degrade_if_incomplete` 自己保证：而片 1a 把
    判定挪到了编排里，一旦有人把 `judge_once` 提到这段之前，全空盘会拿着**空 triads**
    跑一遍逐格判定并交出一个 `Judgement`（判不动≠判过），本用例正是它的最小反证。
    """
    steps = asyncio.run(
        _collect_steps(EmptyPoiStub(KAILI_CENTER), _check("凯里老街-M14c"))
    )

    assert [s.kind for s in steps] == [STEP_MEASURE, STEP_DEGRADED], (
        f"POI 全空的出路不该走到判定/组装：{[s.kind for s in steps]}"
    )
    degraded = steps[-1]
    assert degraded.judgement is None, "降级出路没有判定产物（判定在它 return 之后才发生）"
    assert degraded.report["data_origin"] == "offline"
    assert degraded.report["degraded"]["detail"] == "poi_empty"
    assert degraded.scope is not None, "这支出路已过 `bind_evidence`，scope 是事实的一部分"
    assert degraded.collected is not None and not any(
        bool(v) for v in degraded.collected.per_category.values()
    ), "collected 必须是「真的没采到」，不是 stub 写歪"


# ── M16 · 回合载荷 `RoundOutcome` 定死（批 A②，计划 v6.1⑦）──────

def test_m16_round_outcome_is_one_bundle_from_judging_to_report():
    """M16-a：一轮的整包载荷一次性交出，且 REPORT 步吃的是**同一次判定**的那份。

    批 A② 的独立判据（计划 v6.1⑦ 说「载荷不定死，B1/B3 与逐回合 trace 就无原料」）。
    钉四件事，各自精确到失败种类：
      ① `judge` 步带载荷、`report` 步带**同一 round_no** 的载荷 ⇒ 回合循环接得上；
      ② `report` 步载荷里的 report 与步上那份是**同一个对象**（不是重算/复制）；
      ③ 五键账目由 `judgement.stats` 与 `report["caliber"]` 逐键相等 ⇒ 上屏账目=这次判定的账目；
      ④ `measure`/`collect`/`degraded` 三类步**没有**载荷 ⇒ 判定前不存在"回合产物"，
         降级出路也没有（M14-c 已钉它不判定，这里钉它不交产物）。
    """
    steps = asyncio.run(_collect_steps(PipelineStubBaidu(KAILI_CENTER), _check("凯里老街-M16")))
    by_kind = {s.kind: s for s in steps}
    assert [s.kind for s in steps if s.kind != STEP_ROUND] == [
        STEP_MEASURE, STEP_COLLECT, STEP_JUDGE, STEP_REPORT
    ], f"骨架漂了（M14-a 同一条，这里钉的是载荷挂在哪几步上）：{[s.kind for s in steps]}"
    assert by_kind[STEP_MEASURE].outcome is None, "measure 步在判定之前，没有回合产物可言"
    assert by_kind[STEP_COLLECT].outcome is None, "同上"

    judged = by_kind[STEP_JUDGE].outcome
    reported = by_kind[STEP_REPORT].outcome
    assert isinstance(judged, RoundOutcome) and isinstance(reported, RoundOutcome)
    # `round_no` 从批 A② 那个"恒 0 的占位"变成**循环给的数**：末轮趟号 == 派发过的回合数
    # == `forensic.rounds`。断的是两个来源相等，不是断它等于某个字面量 —— 所以输入换成
    # "一个回合都不用打"时它仍然成立（那时两边都是 0）。
    _rounds = reported.report["caliber"]["forensic"]["rounds"]
    assert judged.round_no == reported.round_no == _rounds, (
        f"载荷的趟号 {judged.round_no}/{reported.round_no} 与回合账目里的 {_rounds} 分家")
    assert judged.report is None, "judge 步不许顺手把报告也交了 —— 组装在它之后"
    assert reported.judgement is judged.judgement, (
        "REPORT 载荷换了判定对象 ⇒ 回合读到的掩码与上屏账目来自两次判定（片 1a 收掉的那个形状）"
    )
    assert reported.report is by_kind[STEP_REPORT].report, (
        "载荷里的报告与步上的报告不是同一对象 ⇒ 消费方会各拿一份，分家回来了"
    )
    assert reported.scope is by_kind[STEP_JUDGE].scope
    assert reported.collected is by_kind[STEP_JUDGE].collected
    assert len(STAT_KEYS) == 5, f"名册缩水成 {STAT_KEYS} ⇒ 下面那个 for 会空转"
    for key in STAT_KEYS:
        assert int(reported.report["caliber"][key]) == int(reported.judgement.stats[key]), (
            f"{key} 两份数不同源（报告 {reported.report['caliber'][key]} vs "
            f"判定 {reported.judgement.stats[key]}）"
        )

    deg = asyncio.run(_collect_steps(EmptyPoiStub(KAILI_CENTER), _check("凯里老街-M16b")))
    assert deg[-1].kind == STEP_DEGRADED and deg[-1].outcome is None, (
        "降级出路交出了回合载荷 —— 那条根本没有判定，产物是空的"
    )


def test_m16b_round_outcome_refuses_a_report_that_changed_the_books():
    """M16-b（反向，能红的那半）：载荷必须拒绝「报告账目与本次判定不符」的构造。

    这条是 ③ 的反证：把报告里的 `cells_blind` 改成别的数再 `replace` 进载荷，
    `__post_init__` 必须当场抛 —— 否则载荷就只是个传声筒，拦不住组装层换账目。
    顺带钉 `round_no` 非负与缺键两种违规形状（三种失败种类各自一条消息，不许合并）。
    """
    import dataclasses

    steps = asyncio.run(_collect_steps(PipelineStubBaidu(KAILI_CENTER), _check("凯里老街-M16c")))
    outcome = [s for s in steps if s.kind == STEP_REPORT][0].outcome

    tampered = dict(outcome.report)
    tampered["caliber"] = dict(outcome.report["caliber"], cells_blind=999)
    with pytest.raises(ValueError, match="上屏的账目不是这次判定的账目"):
        dataclasses.replace(outcome, report=tampered)

    stripped = {k: v for k, v in outcome.report["caliber"].items() if k != "cells_blind"}
    with pytest.raises(ValueError, match="缺三态键"):
        dataclasses.replace(outcome, report=dict(outcome.report, caliber=stripped))

    with pytest.raises(ValueError, match="回合序号必须非负"):
        dataclasses.replace(outcome, round_no=-1)


# ── P1a · 判定只跑一遍，且吃的就是绑过实测证据的那一块 ──────────

def test_p1a_judging_runs_once_per_forensic_pass_and_never_through_a_shell(monkeypatch):
    """一次体检的**每一趟取证**只判一遍（`judge_once` 次数 == 账目里的趟数），三个旧视图壳 0 次。

    为什么行为判据与 G-10 两条都要：G-10 数的是**代码里的调用点**（谁能调），这条数的是
    **一次真实跑动执行了几次**（`undecided_mask` 也合法存在，所以"能调"不等于"会跑"）。
    只有这条能抓住「编排里顺手多判了一遍」或「壳在生产路径上被偷偷执行」。

    ⚠️ 片 4 把它从 `== 1` 重指成 `== 回合账目里的 judging_passes`，这不是放宽 —— 原来那句
    「恰 1 遍」的真实含义是「一次取证=一遍判定，没有第二把尺再判一次」，而回合天然要多判
    几遍（每补一轮区域就重判一遍，第五轮复审 P0-1 的"点位方向不单调"要求的正是这个）。
    所以新判据把**两个来源**钉在一起：运行期实际执行次数 与 上屏那份账目。少判一趟、
    多判一趟、或账目与实际分家，三种都红；而把它改回 `== 1` 会在今天这份输入上直接红
    （凯里那三类实测边界落在可扩档位上 ⇒ 真会打一个回合）。
    壳必须恒 0 这半条**一个字都没动** —— 那才是这条用例从片 1a 继承下来的承重部分。
    """
    import app.living_circle.blindspot as bs
    import app.living_circle.data_source as ds

    counts = {"judge_once": 0, "cover_matrix": 0, "undecided_mask": 0,
              "find_blindspots_with_stats": 0, "find_blindspots": 0}
    real = {k: getattr(bs, k) for k in counts}

    def _wrap(name):
        target = real[name]

        def _f(*a, **kw):
            counts[name] += 1
            return target(*a, **kw)

        return _f

    for name, fn in ((k, _wrap(k)) for k in counts):
        monkeypatch.setattr(bs, name, fn)
    monkeypatch.setattr(ds, "judge_once", _wrap("judge_once"))

    steps = asyncio.run(_collect_steps(PipelineStubBaidu(KAILI_CENTER), _check("凯里老街-P1a")))

    report = steps[-1].report
    passes = report["caliber"]["forensic"]["judging_passes"]
    assert counts["judge_once"] == passes, (
        f"实际判了 {counts['judge_once']} 遍，上屏的账目却写 {passes} 趟 ⇒ 有一个数不是跑出来的")
    assert counts["judge_once"] >= 1
    assert report and report.get("blindspots") is not None, "前置：这条跑动确实产出了盲区/报告"
    assert {k: v for k, v in counts.items() if k != "judge_once"} == dict.fromkeys(
        ("cover_matrix", "undecided_mask", "find_blindspots_with_stats", "find_blindspots"), 0
    ), f"旧视图壳在生产路径上被执行了：{counts}"


def test_p1a_judge_eats_the_scope_that_bind_evidence_returned(monkeypatch):
    """判定吃的 scope **必须就是** `bind_evidence` 的返回值，且报告举证与它同源（片 1a）。

    替代 v6.4 那句写不出来的判据（「`Judgement.region` 与绑定后的证据域是同一对象」——
    生产只绑标量 ⇒ `evidence_region` 恒 None ⇒ `judge_region` 每次现造一块退化区域，
    `is` 恒假、改 `==` 就成了同义反复。第九轮 P0-4）。
    换成两句可执行的：① scope **对象身份**（判在 bind 之前 ⇒ 立刻红）；
    ② 报告里那两个数是**这一次**判定给的（`caliber.cells_inside` 与 `Judgement.stats` 同源、
    `blindspots` 就是移交出去的那批条目 —— 富化只许就地补 reach/affected，不许换账）。
    """
    import app.living_circle.data_source as ds

    seen = {}
    real_bind, real_judge = ds.bind_evidence, ds.judge_once

    def _bind(scope, collected):
        out = real_bind(scope, collected)
        seen["bound"] = out
        return out

    def _judge(center, scope, triads, *a, **kw):
        j = real_judge(center, scope, triads, *a, **kw)
        seen["judged_with"] = scope
        seen["judgement"] = j
        return j

    monkeypatch.setattr(ds, "bind_evidence", _bind)
    monkeypatch.setattr(ds, "judge_once", _judge)

    steps = asyncio.run(_collect_steps(PipelineStubBaidu(KAILI_CENTER), _check("凯里老街-P1a2")))
    report = steps[-1].report

    assert "bound" in seen and "judged_with" in seen, "前置没凑起来：bind/judge 有一处没被走到"
    assert seen["judged_with"] is seen["bound"], (
        "判定吃的不是绑过实测证据的那个 scope ⇒ 判盲与举证各吃一块区域（判在 bind 之前）"
    )
    j = seen["judgement"]
    assert j.stats["cells_inside"] > 0, "判定空转：一格都没进判定网格"
    # ⚠️ 五个键**逐个**钉，不是只钉 `cells_inside`（第十一轮 P0-2）：判定侧算出五档，
    # 报告侧只落三档的话，`cells_unjudgeable_by_cap` / `cells_blind` 就在报告里静默消失，
    # 而 `caliber_index` 已把它们登记成可引用口径键 ⇒ 专家卡引用得到、载荷里读不到（空值）。
    # 只数键名还不够，值也要对上 —— 否则「写了同名 0」这类形状照样溜过去。
    cal = report["caliber"]
    assert len(STAT_KEYS) == 5, (
        f"名册本身缩水了（{STAT_KEYS}）⇒ 下面那个 for 会空转，五键落点等于没钉"
    )
    for key in STAT_KEYS:
        assert key in cal, f"判定账目 {key!r} 没进报告 caliber（登记与发射脱钩）"
        assert cal[key] == j.stats[key], (
            f"报告 caliber.{key} = {cal[key]} 与判定产物 {j.stats[key]} 不符 ⇒ 两处各算一遍"
        )
    assert report["blindspots"] is j.spots, (
        "盲区条目被换了一份 ⇒ 移交契约破了（装配层该就地富化，不该另造一批）"
    )
    assert set(j.stats) == set(STAT_KEYS), (
        f"判定快照的键集变了（报告侧就读这五个）：{sorted(j.stats)}"
    )




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


# ── D1 · 降级分级（计划 v4 阶段 4）：T1 边界桩 + T2 挂账对 ─────────

def test_d1_isochrone_branch_is_independent_of_guard_branch():
    """C2（T1）· 三条触发分支必须互相独立，成因在 `detail` 里不混。

    D1 落地后的分工（本用例就是把这张表钉住，少一条都不行）：
      · 等时圈缺失 ⇒ 降级（建制级失败，没有判定面）；
      · **测时阶段**中止 ⇒ 降级（几何本身可能是残缺的一批点插出来的）；
      · **取证阶段**中止而几何与点位都在 ⇒ **不降级**，只标 partial；
      · POI 全空 ⇒ 降级（盲区没有输入）。
    `reason` 是闭集单值（K11），分级路由只能靠 `detail` ⇒ 成因可分辨性一并锁死。
    """
    clean = SimpleNamespace(total_meltdown=False, budget_exhausted=False, stats=SimpleNamespace(quota_hits=0))
    melted = SimpleNamespace(total_meltdown=True, budget_exhausted=False, stats=SimpleNamespace(quota_hits=1))

    # ① 等时圈缺失：guard 再干净也必须降级（没有可达区就没有判定面）
    assert degrade_reason(clean, has_isochrones=False, has_poi=True) == DEGRADE_REASON_QUOTA_EXHAUSTED
    # ② 测时阶段中止（`has_poi=None` = 还没走到采集）：几何随时可能残缺 ⇒ 仍整份降级
    assert degrade_reason(melted, has_isochrones=True, has_poi=None) == DEGRADE_REASON_QUOTA_EXHAUSTED
    # ③ 取证阶段中止而几何与点位都在 ⇒ **不降级**（D1①）：残缺由 `partial_for` 承载
    assert degrade_reason(melted, has_isochrones=True, has_poi=True) is None
    # ④ POI 全空：盲区没有输入 ⇒ 降级，与 guard 是否中止无关
    assert degrade_reason(clean, has_isochrones=True, has_poi=False) == DEGRADE_REASON_QUOTA_EXHAUSTED
    # ⑤ 两条都不触发 ⇒ None（不许因为「有抖动痕迹」就降级，那是 M4 防的过度降级）
    assert degrade_reason(clean, has_isochrones=True, has_poi=True) is None
    # 成因在 detail 里各归各，且都能翻成中文标签
    assert degrade_detail(clean, isochrone_empty=True) == "isochrone_empty"
    assert degrade_detail(melted) == "total_meltdown"
    assert degrade_detail(SimpleNamespace(total_meltdown=False, budget_exhausted=True,
                                         stats=SimpleNamespace(quota_hits=0))) == "daily_budget_exhausted"
    assert detail_label("isochrone_empty") == "测时失败"
    assert detail_label("total_meltdown") == "总量熔断"
    # 未知取值回落而不抛（前端拿到的永远是可读文案）
    assert detail_label("forensic_cap") == DETAIL_LABELS["unknown"]
    assert degrade_reason(melted, has_isochrones=True, has_poi=None) in DEGRADE_REASONS

    # partial 侧同源同归因：同一个 guard，两个节点说同一件事，不许出现两套成因
    block = partial_for(melted)
    assert block is not None and block["stage"] == "forensic"
    assert block["detail"] == degrade_detail(melted) == "total_meltdown"
    # 没中止过 ⇒ 不发射 partial 节点（一份完整跑完的报告不该带着「部分完成」的暗示）
    assert partial_for(clean) is None


class _ForensicCapGuard:
    """guard 桩：只声明「闸落下了」，不声明落在哪个阶段。

    这正是 D1 原挂账抱怨的「无从区分」—— 落地答案是**不该由 guard 来区分**：
    阶段由调用点已持有的数据决定，编码在 `has_poi` 的三态里（``None``=采集前）。
    给 guard 加一个「我是取证阶段中止的」字段，等于让被切断的一方自己声明切断地点，
    漏填一次就回到整份降级。
    """

    total_meltdown = True
    budget_exhausted = False
    stats = SimpleNamespace(quota_hits=1)


def test_d1_forensic_quota_exhaustion_keeps_live_report():
    """C1（原 T2 挂账）· **已随阶段 4 转正**：取证配额耗尽是「部分完成」，不是「整份不可信」。"""
    assert degrade_reason(_ForensicCapGuard(), has_isochrones=True, has_poi=True) is None, (
        "取证侧主动收手 ≠ 数据残缺；降级后报告里既没有盲区、等时圈又退成正圆，"
        "等于用「一定不出错」换掉了「本来已经算出来的东西」"
    )
    block = partial_for(_ForensicCapGuard())
    assert block is not None and block["note"] == PARTIAL_NOTE, (
        "不降级还得**说得出来**：残缺不留痕，就等于把没查的演成查完了"
    )


def test_d1_isochrone_stage_abort_still_degrades():
    """C1 的配偶 · 判据随阶段 4 **重指**：还剩哪一半该整份打回离线。

    原形态是「只要 guard 中止，数据再齐也整份降级」的现状记录 —— D1 把它打红后，
    留在这里守的是**没松动的那一半**：采集还没开始（`has_poi=None`）时中止，
    拿到的环族随时可能是残缺点插出来的，那才是建制级失败。
    若哪天有人把 partial 一路扩到测时阶段，本用例必须先红并显式回答「残缺的几何凭什么算数」。
    """
    assert degrade_reason(_ForensicCapGuard(), has_isochrones=True, has_poi=None) \
        == DEGRADE_REASON_QUOTA_EXHAUSTED
    # 而几何压根没拿到时，guard 干不干净都不许走 live
    clean = SimpleNamespace(total_meltdown=False, budget_exhausted=False, stats=SimpleNamespace(quota_hits=0))
    assert degrade_reason(clean, has_isochrones=False, has_poi=None) == DEGRADE_REASON_QUOTA_EXHAUSTED


def _thin_evidence_scope(bound_m: float, capped=(), bounds=None):
    """证据边界短于判定半径的口径 ⇒ 外沿的格 1km 圆查不全（判不出结论）。

    `capped` 决定这些「判不出」归谁：留空 = 我们的页深没给够（记 `unknown`），
    给了类名 = 服务端自称还欠一整页却断了货（记 `unjudgeable_by_cap`）。
    两态的分界正是阶段 3-f 要钉的东西，所以这里必须能分开造。

    `bounds` 可逐类给不同边界（缺省三类同为 `bound_m`）—— 用来造「稠密类被卡住、
    稀疏类却查全了」这种真实形状（`capability_manifest.json` 凯里实测：药店 60 条要 3 页，
    菜市场与小学一页就穷尽）。

    ⚠️ #81 之后本助手必须**同时**给 `stop_reasons`：那道封顶闸的对照面从"有实测边界的类"
    换成了"有实测举证行的类"（= `evidence_stop_reasons` 的键集，与 `capped` 同源），
    只报封顶却不报原因的载荷在真接口上根本产不出来（`bind_evidence` 两件一起交）。
    原因按本助手已声明的事实给，不新编：`capped` 里的类 = 接口断页，其余 = 我们页深不够
    —— 正是上面那段分界说的两件事。
    """
    from app.living_circle.baidu_client import STOP_PAGE_CAP, STOP_SERVER_CAP
    from app.living_circle.caliber import get_caliber
    from app.living_circle.geo_utils import xy_to_lnglat
    from app.living_circle.scope import TRIAD_KEYS, SpatialScope

    ring = [
        xy_to_lnglat(KAILI_CENTER, -1000, -1000),
        xy_to_lnglat(KAILI_CENTER, 1000, -1000),
        xy_to_lnglat(KAILI_CENTER, 1000, 1000),
        xy_to_lnglat(KAILI_CENTER, -1000, 1000),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(get_caliber("walking"), KAILI_CENTER, 2500.0, zone)
    fr = dict(bounds) if bounds else {k: float(bound_m) for k in TRIAD_KEYS}
    capped = tuple(capped)
    scope = scope.with_evidence(fr, complete=False, capped=capped,
                                stop_reasons={k: (STOP_SERVER_CAP if k in capped
                                                  else STOP_PAGE_CAP) for k in fr})
    scope.invariant()
    return scope


def _all_blind_triads():
    """三要素一个都不给 ⇒ 可判格必然判盲，永不可判格才是本用例关心的那批。"""
    return {"market": [], "pharmacy": [], "primary": []}


def test_d1_capability_cap_neither_degrades_nor_counts_as_unknown():
    """C3（原 T2 挂账）· **已随阶段 3-f 转正**：能力封顶既不触发降级，也不混进 unknown。

    转正理由：这条判据缺的两样原料都到位了 —— `place_search` 以 `STOP_SERVER_CAP`
    回传「服务端自称还欠一整页却断了货」，`with_evidence(capped=…)` 把它绑进逐圆盘。
    仍挂在别处的只有 D1 的降级分级（`test_d1_forensic_budget_*` 那两条），本用例不替它作证。
    """
    from app.living_circle.blindspot import find_blindspots_with_stats
    from app.living_circle.scope import TRIAD_KEYS

    _spots, stats = find_blindspots_with_stats(
        KAILI_CENTER,
        _thin_evidence_scope(900.0, capped=TRIAD_KEYS),
        _all_blind_triads(),
        prefix="d1",
    )
    # 证据边界 900m < 判定半径 1000m 且三类全封顶 ⇒ 判不出的格属「接口封顶」而非「没查」
    assert stats["cells_unjudgeable_by_cap"] > 0
    assert stats["cells_unknown"] == 0, "三类全封顶后仍记 unknown ⇒ 我们在替百度认领漏查"
    assert stats["cells_inside"] == (
        stats["cells_judged"] + stats["cells_unknown"] + stats["cells_unjudgeable_by_cap"]
    ), "三态分账不闭合 ⇒ 答辩里等于自己认领一次漏采"
    assert set(stats) == {
        "cells_inside", "cells_judged", "cells_unknown",
        "cells_unjudgeable_by_cap", "cells_blind",
    }, "分账键集变了 ⇒ 报告侧与 B11 复算的读键要同批改"
    assert degrade_reason(None, has_isochrones=True, has_poi=True) is None

    # 反证（不许凭空作伪证）：同一片薄证据、**没有**封顶事实时，第三态必须是 0。
    _spots, bare = find_blindspots_with_stats(
        KAILI_CENTER, _thin_evidence_scope(900.0), _all_blind_triads(), prefix="d0"
    )
    assert bare["cells_unjudgeable_by_cap"] == 0
    assert bare["cells_unknown"] == stats["cells_inside"] - stats["cells_judged"]


def test_capability_cap_is_attributed_per_cell_not_per_report():
    """一类封顶不赦免另两类的缺口：挡住一格的**每一个**类都封顶，才许记「百度的上限」。

    判盲只需一类有据（`blindspot` 文件头那条不对称规则）⇒ 只要还有一类是「我们多给预算
    就判得动」，那格的缺口就仍记在我们头上。写成 `any(封顶)` 会把我们的失职推给接口，
    写成「全片开关」会让与封顶无关的格也集体改姓 —— 两个方向都朝「好看」。
    """
    from app.living_circle.blindspot import find_blindspots_with_stats
    from app.living_circle.scope import TRIAD_KEYS

    # ① 三类边界同样短，只有药店是接口封顶、另两类是我们没翻 ⇒ 全部仍记 unknown
    _s, only_one = find_blindspots_with_stats(
        KAILI_CENTER,
        _thin_evidence_scope(900.0, capped=("pharmacy",)),
        _all_blind_triads(),
        prefix="c1",
    )
    assert only_one["cells_unjudgeable_by_cap"] == 0, (
        f"一类封顶就赦免了另两类的漏查：{only_one}"
    )
    assert only_one["cells_unknown"] > 0

    # ② 稠密类被接口卡死、稀疏类真查全 ⇒ 每一格照样能出「缺哪一类」的结论，第三态为 0
    #    （`capability_manifest.json` 凯里实测的形状：药店要 3 页，菜市场/小学 1 页穷尽）
    _s, others_full = find_blindspots_with_stats(
        KAILI_CENTER,
        _thin_evidence_scope(
            900.0,
            capped=("pharmacy",),
            bounds={"pharmacy": 900.0, "market": 2500.0, "primary": 2500.0},
        ),
        _all_blind_triads(),
        prefix="c2",
    )
    assert others_full["cells_unjudgeable_by_cap"] == 0
    assert others_full["cells_judged"] == others_full["cells_inside"], (
        f"另有两类有据却整片判不动 ⇒ 封顶归因越界：{others_full}"
    )
    assert others_full["cells_blind"] == others_full["cells_inside"]
    assert set(TRIAD_KEYS) == {"market", "pharmacy", "primary"}   # 前置：上面按这三类造


@pytest.mark.xfail(
    strict=True,
    reason="批次二（阶段 2b）待落地：`judged_share` 的分母仍是 `cells_inside` ⇒ 第三态"
           "格继续按「我们没查」参与盲区扣分外推，接口封顶的账面代价落回我们头上",
)
def test_b11_extrapolation_excludes_the_interface_cap():
    """计划验收：`unjudgeable_by_cap` 不得进外推分母（B11 分母 = inside − unjudgeable）。"""
    from app.living_circle.judgement import judged_share
    from app.living_circle.blindspot import find_blindspots_with_stats
    from app.living_circle.scope import TRIAD_KEYS

    _s, stats = find_blindspots_with_stats(
        KAILI_CENTER,
        _thin_evidence_scope(900.0, capped=TRIAD_KEYS),
        _all_blind_triads(),
        prefix="b11",
    )
    inside = stats["cells_inside"]
    assert stats["cells_unjudgeable_by_cap"] > 0, "前置不成立：第三态没出数，本用例会空转"
    assert judged_share(stats) == pytest.approx(
        stats["cells_judged"] / (inside - stats["cells_unjudgeable_by_cap"])
    )


def test_b11_current_share_still_divides_by_the_whole_reach():
    """上一条的配偶 · **现状记录**：分账键已能出数，评分侧仍把封顶格摊进分母。

    阶段 3-f 只负责让「封顶」与「没查」**可分**；把它们分开的账面后果（少外推、
    `confidence` 不再 full）属批次二 —— 那里动的是 B11 复算与前端第二份复算，跨端 6 份
    副本必须同批，所以此刻**不许**只改后端这一处。本用例就是把这条没做的账钉在这儿。
    批次二落地时它必须转红，判据重指到上一条，不许直接删。
    """
    from app.living_circle.judgement import judged_share

    stats = {
        "cells_inside": 121, "cells_judged": 1,
        "cells_unknown": 0, "cells_unjudgeable_by_cap": 120, "cells_blind": 1,
    }
    assert judged_share(stats) == pytest.approx(1 / 121), (
        "封顶格已从分母里剔出去了 ⇒ 本现状记录该转红，请把判据重指到 B11 的新分母上"
    )
