"""M2 · 生活圈体检流水线：A4 事件契约 / 落库独立文档 / D4 完整报告结构。

以 fixture 数据模式驱动（无网络），覆盖：
  - 事件序列（intake→…→audit 阶段顺序单调；report_ready/done 双字段）
  - 报告落库（living_circle_reports 独立文档，report_type 弱关联）
  - assemble_report 结构（章节/结论/证据/专家队/渲染适配器判据）

v5 U17-U19/U22/U27/U30/U31/U36：live 分支（stub client + 内存缓存）驱动 ——
  预算感知采样 / 配额计数 / 熔断降级 / 缓存命中幂等。
"""
import asyncio
import math
from types import SimpleNamespace

import pytest

from app.core import db
from app.core.pipeline.living_circle import (
    STAGES,
    _scene_key,
    create_living_circle_task,
    living_circle_pipeline,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.data_source import CachingDataSource, CheckParams, LiveDataSource
from app.living_circle.geo_utils import haversine_m, xy_to_lnglat
from app.living_circle.isochrone import IsochroneEngine
from app.living_circle.quota import (
    forensic_budget,
    mat_budget_for,
    max_matrix_origins,
    quota_budget,
)
from app.living_circle.repository import Repository

KAILI = {
    "scene_name": "凯里老街",
    "city": "贵州·凯里",
    "address": "凯里市西门街道老街片区",
    "center": [107.9758, 26.5734],
    "study_radius_m": 2500.0,
    "mode": "standard",
    "data_mode": "fixture",  # 测试无网络：fixture 分支
}

KAILI_CENTER = (107.9758, 26.5734)


def _run_pipeline(task_id: str) -> list:
    async def _impl():
        events = []
        async for ev in living_circle_pipeline(task_id):
            events.append(ev)
        return events

    return asyncio.run(_impl())


# ── v5 live 分支驱动件：stub client + CachingDataSource（内存缓存，测试隔离）──

class PipelineStubBaidu:
    """live 分支管线用 stub：计数矩阵分块 / POI 调用，测时用线性步行模型。

    - `measure_matrix`/`_measure_matrix` 都走同一实现（两面同真实客户端一致：片 0 收拢后
      编排只调**公开**那面，私有面只是这个 fake 内部共用的实现体）；
    - 分块计数**模拟** BaiduClient 的 chunk 行为：一次整批调用按 chunk 折算批次数；
    - `guard.total_meltdown` 由测试控制（熔断用例置位，真实 guard 语义由 CallGuard 单测覆盖）。
    """

    def __init__(self, center, speed=75.0, meltdown_after=None):
        self.center = center
        self.speed = speed
        self.poi_calls = 0
        self.matrix_batches = 0
        self.max_pts = 0
        # 延迟优化 A 测试桩：逆地理/地理编码计数器（U39 零调用不变式、U40 miss 侧锚）
        self.reverse_calls = 0
        self.geocode_calls = 0
        self._melt_after = meltdown_after
        self.guard = SimpleNamespace(total_meltdown=False)

    async def geocoding(self, address):
        """中心解析兜底用（U39/U40 显式中心不触达；存在即可，防 AttributeError）。"""
        self.geocode_calls += 1
        return self.center

    async def reverse_geocoding(self, location):
        """逆地理（A 计划 miss 路径城市补全用）：返回固定 city + 社区名。"""
        self.reverse_calls += 1
        return {"city": "贵州·凯里", "name": "凯里老街", "address": "凯里市西门街道老街片区"}

    def _poi_set(self, query, center):
        pts = []
        for idx, (dx, dy) in enumerate([(300, 300), (-900, -900), (1400, 0)]):
            lng, lat = xy_to_lnglat(center, dx, dy)
            pts.append({"name": f"{query}-{idx}", "lng": round(lng, 6), "lat": round(lat, 6), "address": ""})
        return pts

    async def place_search(self, query, center, radius_m=2000, scope=2, page_size=20, max_pages=1):
        self.poi_calls += 1
        if self._melt_after is not None and self.poi_calls >= self._melt_after:
            self.guard.total_meltdown = True
        return self._poi_set(query, center)

    async def _measure_impl(self, travel_mode, origins, destination):
        self.max_pts = max(self.max_pts, len(origins))
        chunk = get_caliber(travel_mode).api.chunk or 25
        self.matrix_batches += math.ceil(len(origins) / chunk)
        return [
            round((haversine_m(destination, p) / self.speed), 1) if haversine_m(destination, p) < 2200 else None
            for p in origins
        ]

    async def measure_matrix(self, travel_mode, origins, destination):
        return await self._measure_impl(travel_mode, origins, destination)

    async def _measure_matrix(self, travel_mode, origins, destination, chunk_size=None):
        return await self._measure_impl(travel_mode, origins, destination)

    async def aclose(self):
        pass


def _live_source(stub, monkeypatch):
    """构造 Caching(Live) 数据源并顶替管线工厂（内存缓存：不落盘 lc_cache.db）。"""
    repo = Repository()
    live = LiveDataSource(ak="stub", client=stub, engine=IsochroneEngine(), repo=repo)
    src = CachingDataSource(live, repo=repo, data_mode="live")
    monkeypatch.setattr(
        "app.living_circle.data_source.get_data_source",
        lambda mode, ak, repo: src,
    )
    return src, stub


def _live_params(**over):
    p = {
        "scene_name": "凯里老街",
        "city": "贵州·凯里",
        "address": "凯里市西门街道老街片区",
        "center": [107.9758, 26.5734],
        "study_radius_m": 2500.0,
        "sample_profile": "standard",
        "travel_mode": "walking",
        "data_mode": "live",
    }
    p.update(over)
    return p


def _done_id(events) -> str:
    return next(e for e in events if e["type"] == "done")["data"]["report_id"]


def _row_count_for_scene(scene_key: str) -> int:
    # 注意：db 连接是线程本地缓存的（_LOCAL.conn），绝不能在此 close ——
    # 关闭会让同线程后续所有 db 操作报 "Cannot operate on a closed database"。
    conn = db._connect()
    return conn.execute("SELECT COUNT(*) FROM living_circle_reports WHERE scene_key=?", (scene_key,)).fetchone()[0]


# ── v5 U17/U19 · 预算感知采样 + 配额计数（B2/B3：矩阵 ≤ mat_budget、POI ≤ poi_budget）──

def test_u17_live_pipeline_respects_budget(monkeypatch):
    """U17：live 管线 + mock client 计数 → 矩阵分块 ≤ mat_budget、POI 调用 ≤ poi_budget。"""
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-U17", sample_profile="standard"))
    events = _run_pipeline(tid)
    # 矩阵：采样点数 ≤ max_matrix_origins（D5 反向导出：standard/步行 需求 1049 点 →
    # 11 批，额度贴着需求给，不再虚占 4 批），折算分块（ceil(点数/chunk)）≤ mat_budget
    mat, poi = quota_budget("standard", "walking")
    mp = max_matrix_origins("standard", "walking")
    assert 0 < stub.max_pts <= mp, f"采样 {stub.max_pts} 点超出矩阵预算 {mp}"
    assert math.ceil(stub.max_pts / 100) == mat == 11, (
        f"分块数 {math.ceil(stub.max_pts / 100)} 与额度 {mat} 不等 ⇒ 要么虚占、要么被降级"
    )
    assert stub.matrix_batches <= mat == 11
    # POI：矩阵不再虚占后多出来的 4 次回到取证（27 → 31），三要素与 S8 扩词因此不饿死。
    # ⚠️ 片 4（取证回合）之后这条从"一个上限"拆成**两个**，各拦一种坏形状（计划 v6.1⑧ 原话）：
    #   ① 首轮仍须 ≤ 31 —— 回合不许把首轮喂胖（那会挤掉 8 类展示计数与 S8 扩词的额度）；
    #   ② 总额 ≤ 31 + `forensic_budget()` —— 回合只能花自己那一格，不许回头动首轮池子。
    # 拆分用的"回合花了多少次"取自**落库那份披露**（`caliber.forensic.calls`），不是测试自己
    # 数的 —— 于是这条同时是"账目与实际对得上"的证据：谁改了计数口径，①② 会朝相反方向红。
    rid = _done_id(events)
    _round_calls = (db.get_living_circle_report(rid)["living_circle"]["caliber"]["forensic"]
                    ["calls"])
    assert stub.poi_calls - _round_calls <= poi == 31, (
        f"首轮用了 {stub.poi_calls - _round_calls} 次（回合另花 {_round_calls} 次），"
        f"而首轮额度只有 {poi}")
    assert stub.poi_calls <= poi + forensic_budget(), (
        f"总计 {stub.poi_calls} 次越过 首轮 {poi} + 取证 {forensic_budget()}")
    # 任务正常完成（非熔断、非失败）
    assert _done_id(events) is not None
    assert db.get_task_full(tid)["status"] == "done"


def test_u19_budget_limited_sampling_geometry_ok(monkeypatch):
    """U19：预算感知采样后的报告通过几何质检（done 而非 failed）。

    walking 档 chunk=100（capability manifest 实测）→ D5 反向导出 max_origins=1100 ≥ 旧双阶段
    1049 点 → 全精度双阶段（11 批 = 额度，不虚占）；driving 档 chunk=25 → 需求 505 批被份额闸
    削到 15 → max_origins=375 → 触发预算受限单阶段（~346 点、14 批 ≤ 15）。两条路径都必须
    IDW 出完整等时圈族，`assess_geometry` 必须 ok（done 而非 failed）。
    """
    for tm, scene in (("walking", "凯里老街-U19w"), ("driving", "凯里老街-U19d")):
        stub = PipelineStubBaidu(KAILI_CENTER)
        _live_source(stub, monkeypatch)
        tid = create_living_circle_task(_live_params(scene_name=scene, travel_mode=tm))
        events = _run_pipeline(tid)
        mp = max_matrix_origins("standard", tm)
        chunk = get_caliber(tm).api.chunk or 25
        assert 0 < stub.max_pts <= mp, f"{tm}: 采样 {stub.max_pts} 点超出矩阵预算 {mp}"
        assert math.ceil(stub.max_pts / chunk) <= mat_budget_for("standard", tm), \
            f"{tm}: 分块数超矩阵额度"
        rid = _done_id(events)
        assert rid is not None, f"{tm}: 几何质检未通过（done 缺失）"
        rep = db.get_living_circle_report(rid)
        assert rep["living_circle"]["data_origin"] == "live"
        assert rep["living_circle"]["scores"]["total"] > 0  # 几何质检通过 → 已落库签发


# ── v5 U18/U36 · 熔断接线（R2b）+ D1 分级：中断在哪一段决定后果有多重 ──

def test_u18_forensic_meltdown_keeps_live_partial_done(monkeypatch):
    """U18（判据随阶段 4 重指）：取证途中熔断 ⇒ **live + partial**，任务仍以 done 收尾。

    本桩的熔断是由 `place_search` 计数触发的 ⇒ 天然发生在**采集途中**：等时圈那时已经
    真测完了。旧判据钉的是「熔断 ⇒ offline」，而 D1① 之后那等于把已算出的几何与盲区丢掉、
    换一张 detour_k 正圆。这里守的仍是这条用例真正的不变量：**绝不因百度配额演成调研失败**，
    外加一条 —— 残缺必须说得出（partial 节点 + 面向用户的熔断文案）。
    """
    stub = PipelineStubBaidu(KAILI_CENTER, meltdown_after=5)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-U18"))
    events = _run_pipeline(tid)
    done = next(e for e in events if e["type"] == "done")
    assert done["data"].get("status") != "failed"
    rid = done["data"]["report_id"]
    assert rid is not None
    rep = db.get_living_circle_report(rid)
    lc = rep["living_circle"]
    assert lc["data_origin"] == "live", f"取证途中熔断不许丢几何：{lc.get('degraded')}"
    assert lc["partial"]["detail"] == "total_meltdown"
    assert "degraded" not in lc
    assert lc["blindspots"] is not None and lc["sampling"]["interpolation"] != "circular_approx"
    assert db.get_task_full(tid)["status"] == "done"  # mark_task_done 正确
    assert db.get_task_full(tid)["report_id"] == rid
    # collect 阶段出现熔断明示（文案里不许再写「降级为离线估算」）
    melt_msgs = [
        e for e in events
        if e["type"] == "message" and e["data"].get("stage") == "collect" and "熔断" in e["data"].get("text", "")
    ]
    assert melt_msgs, "必须向用户明示配额熔断"
    assert not any("离线" in e["data"].get("text", "") for e in melt_msgs), (
        f"报告还是 live，文案却说离线估算：{[m['data']['text'] for m in melt_msgs]}"
    )


def test_u18_measure_stage_meltdown_still_degrades_offline(monkeypatch):
    """测时阶段就熔断 ⇒ 仍旧整份打回离线，并守住 K11 那个 `reason` 字面量。

    U18 原本一条用例同时钉着两件事：「熔断不失败」与 `reason == baidu_quota_exhausted`
    （前端映射表与 test_g09 都读这个闭集）。D1 分级后前者归到 partial 那条，
    这条把它原本顺带覆盖的 offline 路径**显式**接管起来 —— 不然 K11 契约就只剩单元测试、
    端到端一条都不再经过。
    """
    stub = PipelineStubBaidu(KAILI_CENTER)
    stub.guard.total_meltdown = True          # 采集开始前闸就已落下 ⇒ 测时阶段中止
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-U18m"))
    events = _run_pipeline(tid)
    done = next(e for e in events if e["type"] == "done")
    assert done["data"].get("status") != "failed"
    rep = db.get_living_circle_report(done["data"]["report_id"])
    lc = rep["living_circle"]
    assert lc["data_origin"] == "offline"
    assert lc["degraded"]["reason"] == "baidu_quota_exhausted"   # K11 闭集字面量
    assert lc["degraded"]["detail"] == "total_meltdown"
    assert "partial" not in lc, "整份降级与部分完成互斥：同时出现就是两条路都在跑"


def test_u36_meltdown_event_sequence_complete(monkeypatch):
    """U36：降级路径事件时序 —— stage_seq 1..7 单调完整（含 collect=4）、percent 单调、done 收尾。"""
    stub = PipelineStubBaidu(KAILI_CENTER, meltdown_after=5)
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-U36"))
    events = _run_pipeline(tid)
    progress = [e["data"] for e in events if e["type"] == "progress"]
    seqs = [p["stage_seq"] for p in progress]
    assert seqs == list(range(1, 8)), f"进度阶段序列必须完整 1..7：{seqs}"
    percents = [p["percent"] for p in progress]
    assert percents == sorted(percents), "percent 单调不减"
    stage_idx = {s: i for i, s in enumerate(STAGES)}
    for prev, cur in zip(progress, progress[1:]):
        assert stage_idx[cur["stage"]] >= stage_idx[prev["stage"]]
    assert progress[-1]["percent"] == 100
    types = [e["type"] for e in events]
    assert "report_ready" in types and "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["data"].get("status") != "failed"


# ── R7f/C1 · 仅 budget_exhausted（无 total_meltdown）也必须降级 ──

def test_g09_degrade_via_budget_exhausted(monkeypatch):
    """G9（R7f/C1）：guard 仅有 ``budget_exhausted`` 信号（无 ``total_meltdown``）也必须触发
    `baidu_quota_exhausted` 诚实降级 → ``data_origin='offline'``、``done`` 非 ``failed``。

    这钉死 R7f 的「优先读 budget_exhausted、缺失回落 total_meltdown」契约：日预算耗尽
    是 R7 新增信号，旧 stub（仅 total_meltdown）经回落仍可用，新 guard 走 budget_exhausted
    路径同样能降级。stub 的 measure_matrix/place_search 不依赖 guard，故测时/采集照常成功，
    降级判定纯看 guard.budget_exhausted 读取。

    ⚠️ 复核（见计划 §9/§10）：初版**直置** ``budget.exhausted = True`` 是「贴着实现写」，
    正好掩盖了 P0-1（耗尽后跨日不解封）。现改为**经真实 ``call()`` 入口**累加至耗尽：
    既覆盖「累加 → 耗尽 → 降级读取」全接缝，也不再依赖任何直置状态位（``exhausted``
    已是只读属性）。
    """
    from app.living_circle.request_guard import CallGuard, get_daily_budget

    budget = get_daily_budget("g9-ak", 3)
    guard = CallGuard(daily_budget=budget)

    async def _exhaust_via_entry() -> None:
        async def work():
            return {"status": 0}

        for _ in range(3):
            await guard.call(work)

    asyncio.run(_exhaust_via_entry())
    assert budget.exhausted is True, "经真实入口累加至 cap 后必须已耗尽"
    stub = PipelineStubBaidu(KAILI_CENTER)
    stub.guard = guard  # 真实 guard，仅 budget_exhausted 信号
    _live_source(stub, monkeypatch)
    tid = create_living_circle_task(_live_params(scene_name="凯里老街-G9"))
    events = _run_pipeline(tid)
    done = next(e for e in events if e["type"] == "done")
    assert done["data"].get("status") != "failed"
    rid = done["data"]["report_id"]
    assert rid is not None
    rep = db.get_living_circle_report(rid)
    assert rep["living_circle"]["data_origin"] == "offline"
    assert rep["living_circle"]["degraded"]["reason"] == "baidu_quota_exhausted"
    assert db.get_task_full(tid)["status"] == "done"


# ── v5 U22/U27/U30 · 缓存命中幂等（E1/E2：peek 单一入口、report_id 复用、无重复行）──

def test_u22_pipeline_cache_hit_zero_client_calls(monkeypatch):
    """U22：同 `_scene_key` 已有缓存（经 `peek`）→ 直接返回，**client 零调用**。"""
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-U22")
    # 首次：全量体检 + 回填缓存
    tid1 = create_living_circle_task(params)
    _run_pipeline(tid1)
    calls_after_first = (stub.matrix_batches, stub.poi_calls)
    assert calls_after_first != (0, 0)
    # 二次：同 scene_key → peek 命中，client 零调用
    tid2 = create_living_circle_task(params)
    events2 = _run_pipeline(tid2)
    assert (stub.matrix_batches, stub.poi_calls) == calls_after_first
    hits = [e for e in events2 if e["type"] == "message" and "缓存命中" in e["data"].get("text", "")]
    assert hits, "二次体检必须走缓存命中文案"
    assert _done_id(events2) is not None
    assert db.get_task_full(tid2)["status"] == "done"


def test_force_param_makes_重新体检_actually_remeasure(monkeypatch):
    """4b：`force` 一路传到 `peek` ⇒ 用户点名重测时**真的重测**（U22 相反的那一半）。

    U22 钉"默认路径必须零新增调用"（省配额是既定设计，不许被削弱）；这条钉"点名要重测时
    那条省钱路径必须让路"。两条合起来才是完整语义：**默认省、点名重**。
    顺带钉脏值：读法用 `params.get("force") is True` 而不是 `bool(...)` —— 一个字符串或 `1`
    就能把省配额那条路静默关掉、每次体检都重打 1049 点矩阵，那是要花真钱的方向性错误。
    """
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    _run_pipeline(create_living_circle_task(_live_params(scene_name="凯里老街-4b")))
    after_first = (stub.matrix_batches, stub.poi_calls)
    assert after_first != (0, 0)

    # 先确认默认路径仍然零新增（否则下面"force 让计数涨了"没有对照意义）
    _run_pipeline(create_living_circle_task(_live_params(scene_name="凯里老街-4b")))
    assert (stub.matrix_batches, stub.poi_calls) == after_first

    for dirty in ("yes", 1, None, 0):
        _run_pipeline(create_living_circle_task(_live_params(scene_name="凯里老街-4b", force=dirty)))
        assert (stub.matrix_batches, stub.poi_calls) == after_first, (
            f"脏值 {dirty!r} 把复用关掉了 ⇒ 每次体检都重打配额")

    _run_pipeline(create_living_circle_task(_live_params(scene_name="凯里老街-4b", force=True)))
    assert (stub.matrix_batches, stub.poi_calls) > after_first, (
        "force=True 没带来重测 ⇒ 「重新体检」还是拿的旧快照")


def test_signed_report_carries_the_reuse_window(monkeypatch):
    """4b：每条签发的载荷都带 `reuse_window`，三个数**引用真常量**（不是抄一份）。

    屏上那句"什么条件会被复用"只能读这里 —— 数字写成两份，阈值改一次屏幕上的话就说一次谎
    （本仓把这类"文案与数据分家"记过至少三次）。两条路都要有：第一次实跑、以及复用别人那份
    的命中路径，因为读这句话的人是拿到答复的那个人。
    """
    from app.living_circle.data_source import NEARBY_CACHE_M
    from app.living_circle.repository import DEFAULT_AUX_TTL_S, DEFAULT_REPORT_TTL_S

    expect = {
        "report_ttl_s": DEFAULT_REPORT_TTL_S,
        "aux_ttl_s": DEFAULT_AUX_TTL_S,
        "nearby_radius_m": NEARBY_CACHE_M,
    }
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-窗口")

    rid1 = _done_id(_run_pipeline(create_living_circle_task(params)))
    fresh = db.get_living_circle_report(rid1)["living_circle"]
    assert fresh["reuse_window"] == expect, fresh.get("reuse_window")

    rid2 = _done_id(_run_pipeline(create_living_circle_task(params)))
    hit = db.get_living_circle_report(rid2)["living_circle"]
    assert hit["reuse_window"] == expect, "命中路径没带 ⇒ 屏上那句在最常见的情况下不出现"


def test_fixture_mode_does_not_claim_a_reuse_window():
    """演示态**不发** `reuse_window`：那条链路里没有 `CachingDataSource`、没有任何复用可言。

    ⚠️ 这条**不能**并进上面那条 live 用例：本文件的 `_live_source(stub, monkeypatch)` 把
    `get_data_source` 整个换成了带缓存的源，在它的作用域里跑 fixture 模式，拿到的是
    `served_from='nearby_cache'` 的 live 件 —— 那不是产品行为，是我的台架。
    （第一版就并进去过，红得完全合理，红的是用例。）演示态的真实产品形状是：
    `get_data_source('fixture')` 返回裸 `FixtureDataSource`，没有 peek，也就没有复用。
    前端对缺这一位的降级是"只报时点与年龄"（`freshnessNote`），所以不发不等于功能坏掉。
    """
    rid = _done_id(_run_pipeline(create_living_circle_task({
        "scene_name": "凯里老街-窗口fx", "city": "黔东南苗族侗族自治州",
        "address": "凯里市西门街道老街片区", "center": [107.9758, 26.5734],
        "study_radius_m": 2500.0, "mode": "standard", "data_mode": "fixture",
    })))
    lc = db.get_living_circle_report(rid)["living_circle"]
    assert lc.get("served_from") is None, "演示态不该有缓存命中标识 ⇒ 台架又被 live 源替换了？"
    assert "reuse_window" not in lc, (
        f"演示态发出了复用窗口 ⇒ 屏上会承诺一条该模式下不存在的规则（scene={lc['scene']['name']!r}）")
    assert lc.get("generated_at"), "前提：演示件要有时间戳，否则『只报时点』那半也没了"


def test_u27_u30_cache_hit_idempotent_report_id_and_rows(monkeypatch):
    """U27+U30：同一 scene 两次缓存命中（幂等全链路）→ report_id 相同、报告表行数不变、事件顺序完整。"""
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-U27")
    scene_key = _scene_key(params)
    tid1 = create_living_circle_task(params)
    rid1 = _done_id(_run_pipeline(tid1))
    rows_after_first = _row_count_for_scene(scene_key)
    assert rows_after_first == 1
    # 再次命中：report_id 复用、无新增行
    tid2 = create_living_circle_task(params)
    events2 = _run_pipeline(tid2)
    rid2 = _done_id(events2)
    assert rid2 == rid1, "缓存命中必须复用既有 report_id（D19/D22）"
    assert _row_count_for_scene(scene_key) == rows_after_first, "报告表不得新增重复行（I1b）"
    assert db.get_latest_report_id_for_scene(scene_key) == rid1
    # 事件顺序完整（缓存命中分支也按 STAGES 发满 progress）
    progress = [e["data"] for e in events2 if e["type"] == "progress"]
    assert [p["stage_seq"] for p in progress] == list(range(1, 8))
    ready = next(e for e in events2 if e["type"] == "report_ready")
    assert ready["data"]["report_id"] == rid1


def test_u31_cache_hit_but_db_missing_falls_back(monkeypatch):
    """U31：缓存有数据但落库缺失（异常态）→ 兜底 `_finalize_living_report` 且**不触 replace_scene** → 新 id 落库、行数 +1。"""
    stub = PipelineStubBaidu(KAILI_CENTER)
    src, _ = _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-U31")
    scene_key = _scene_key(params)
    tid1 = create_living_circle_task(params)
    rid1 = _done_id(_run_pipeline(tid1))
    assert _row_count_for_scene(scene_key) == 1
    # 人为制造「缓存有、落库缺」：删掉库行，缓存（peek 层）仍在
    assert db.delete_living_circle_reports_for_scene(scene_key) == 1
    assert db.get_latest_report_id_for_scene(scene_key) is None
    assert src.peek(CheckParams(
        scene_name=params["scene_name"], city=params["city"], address=params["address"],
        center=tuple(params["center"]), study_radius_m=params["study_radius_m"],
        sample_profile=params["sample_profile"], travel_mode=params["travel_mode"],
    )) is not None
    # 二次体检：peek 命中 → 落库缺失 → 兜底重算落库（不 replace_scene → 无重复清扫）
    tid2 = create_living_circle_task(params)
    events2 = _run_pipeline(tid2)
    rid2 = _done_id(events2)
    assert rid2 != rid1  # 新 id 落库
    assert _row_count_for_scene(scene_key) == 1  # 仅新增 1 行（非 replace 语义，不误删）
    assert db.get_latest_report_id_for_scene(scene_key) == rid2
    assert db.get_task_full(tid2)["status"] == "done"
    rep = db.get_living_circle_report(rid2)
    assert rep["living_circle"]["data_origin"] == "live"


def test_u39_cache_hit_zero_network_invariant_no_city(monkeypatch):
    """U39（延迟优化 A，补全 U22 的零调用不变式）：显式中心 + **无 city** → 二次命中四类计数器全为 0。

    U22 参数自带 city → 从未触达逆地理，A 改动的正/反两侧都是新覆盖：
      - 首次（miss）：无 city → 逆地理补城市恰 1 次（A 契约的 miss 侧）；
      - 二次（hit）：`matrix_batches == 0 and poi_calls == 0 and reverse_calls == 0
        and geocode_calls == 0` —— 含**安全属性**：命中路径连逆地理/地理编码都不发，
        缓存报告自带 city/address，不依赖任何网络富化。
    """
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-U39", city="", address="")
    tid1 = create_living_circle_task(params)
    _run_pipeline(tid1)
    after_first = (stub.matrix_batches, stub.poi_calls, stub.reverse_calls, stub.geocode_calls)
    assert after_first != (0, 0, 0, 0)
    assert stub.reverse_calls == 1, "miss 路径必须经逆地理补城市（A 契约 miss 侧）"
    assert stub.geocode_calls == 0, "显式中心不得触发地理编码"
    # 二次：同 scene_key（_payload 5 段不含 city）→ peek 命中，四类计数器零新增
    tid2 = create_living_circle_task(params)
    events2 = _run_pipeline(tid2)
    assert (
        stub.matrix_batches,
        stub.poi_calls,
        stub.reverse_calls,
        stub.geocode_calls,
    ) == after_first, "缓存命中必须零新增百度调用（含逆地理/地理编码）"
    hits = [e for e in events2 if e["type"] == "message" and "缓存命中" in e["data"].get("text", "")]
    assert hits, "二次体检必须走缓存命中文案"
    assert _done_id(events2) is not None
    assert db.get_task_full(tid2)["status"] == "done"


def test_u40_miss_path_reverse_geocode_message_and_stage_order(monkeypatch):
    """U40（延迟优化 A 的 miss 侧顺序锚）：无 city + 显式中心 → 新体检 miss 路径行为契约。

    A 把逆地理从 peek 前移到 miss 后 —— 本用例钉住 miss 侧**不因重排而丢行为**：
      - 「中心点逆地理定位」消息仍发出（文案位置在缓存判定之后，属纯顺序变化）；
      - stage 进度序列（intake→measure→collect→diagnose→report→audit，stage_seq 1..7）不变。
    """
    stub = PipelineStubBaidu(KAILI_CENTER)
    _live_source(stub, monkeypatch)
    params = _live_params(scene_name="凯里老街-U40", city="", address="")
    tid = create_living_circle_task(params)
    events = _run_pipeline(tid)
    texts = [e["data"]["text"] for e in events if e["type"] == "message"]
    assert any("中心点逆地理定位" in t for t in texts), "miss 路径必须仍发逆地理定位消息（A 重排不得丢行为）"
    assert stub.reverse_calls == 1
    progress = [e["data"] for e in events if e["type"] == "progress"]
    assert [p["stage_seq"] for p in progress] == list(range(1, 8)), "miss 路径 stage 序列必须保持 intake→…→audit"
    assert _done_id(events) is not None
    assert db.get_task_full(tid)["status"] == "done"


def test_pipeline_event_contract():
    """A4：事件类型白名单 + 阶段顺序单调 + 收尾 report_ready/done 双字段。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    types = [e["type"] for e in events]
    # warn 补进白名单：`living_circle.py:198` 的名称/坐标不同源告警一直在发，
    # 此前只是恰好没在 fixture 路径上触发才没红（`test_intake_and_shell.py` 反而依赖它存在）。
    allowed = {"node_update", "message", "progress", "evidence", "report_ready", "done", "warn"}
    assert set(types) <= allowed
    assert "report_ready" in types and "done" in types

    # progress 阶段序列：与 STAGES 顺序一致且单调
    progress = [e["data"] for e in events if e["type"] == "progress"]
    assert progress, "必须产生进度事件"
    stage_idx = {s: i for i, s in enumerate(STAGES)}
    for prev, cur in zip(progress, progress[1:]):
        assert stage_idx[cur["stage"]] >= stage_idx[prev["stage"]]
        assert cur["percent"] >= prev["percent"]
    # 尾进度 100
    assert progress[-1]["percent"] == 100

    ready = next(e for e in events if e["type"] == "report_ready")
    done = next(e for e in events if e["type"] == "done")
    # 双字段兼容（runner 传统 reportId + 前端 A4 report_id）
    assert ready["data"]["reportId"] == ready["data"]["report_id"]
    assert done["data"]["report_id"] == ready["data"]["report_id"]


def test_pipeline_persists_independent_document():
    """A1：落库 living_circle_reports（独立文档，report_type 弱关联）。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    assert rep is not None
    assert rep["report_type"] == "living_circle"
    # 断言**快照性质与内部自洽**，而不是钉死具体分值：夹具是真实实跑快照，
    # 一旦用真实 AK 重算（AK 配额 / 路网变化），硬编码分值会把这条"落库链路"用例带成假红。
    lc = rep["living_circle"]
    assert lc["scene"]["name"] == "凯里老街"
    assert lc["data_origin"] == "live"
    assert 0 <= lc["scores"]["total"] <= 100
    assert len(lc["scores"]["triads"]) == 3
    assert len(lc["isochrones"]) == 4
    # 空间口径举证随报告一起落库（Q1/Q2 的可判据化必须活到持久层）
    cal = lc["caliber"]
    assert cal["collect_radius_m"] >= cal["reach_circumradius_m"] * 0.999
    assert cal["cells_judged"] + cal["cells_unknown"] == cal["cells_inside"]
    assert len(lc["blindspots"]) <= cal["cells_judged"], "盲区数不可能超过可判定格数"
    records = db.list_living_circle_reports()
    assert any(r["id"] == rid for r in records)
    # task 终态完成
    task = db.get_task_full(tid)
    assert task["status"] == "done"
    assert task["report_id"] == rid


def test_pipeline_assemble_report_structure():
    """D4：8 章节 / 结论带专家署名 / 证据闭环 / toc 对齐。"""
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)

    assert len(rep["sections"]) >= 8
    for need in ["overview", "medical", "education", "market", "elderly", "isochrone", "blindspot", "conclusion"]:
        assert any(s["id"] == need for s in rep["sections"])
    assert [t["id"] for t in rep["toc"]] == [s["id"] for s in rep["sections"]]
    # 结论专家署名 + 证据引用可解析
    ev_ids = {e["evidence_id"] for e in rep["evidence"]}
    assert len(rep["claims"]) > 5
    for c in rep["claims"]:
        assert c.get("author"), "结论必须带专家署名（D4）"
        for eid in c["evidence_ids"]:
            assert eid in ev_ids
    # 盲区章节表格与盲区数一致
    bs_sec = next(s for s in rep["sections"] if s["id"] == "blindspot")
    assert bs_sec["data_grid"]["rows"] == [] or len(bs_sec["data_grid"]["rows"]) == len(rep["living_circle"]["blindspots"])
    # dispatch 与专家表闭合
    assert any(d["id"] == "L3-001" for d in rep["dispatch"])


def test_pipeline_report_has_caliber_field():
    """R2/R6：报告顶层包含 caliber 举证对象，记录出行方式、速度、绕行系数等口径。

    注：`sample_profile` 断言的是**夹具自述的采样档**——权威快照由
    `scripts/snapshot_live.py` 以 `mode="standard"` 实跑生成，两者必须一致。
    """
    tid = create_living_circle_task(KAILI)
    events = _run_pipeline(tid)
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    rep = db.get_living_circle_report(rid)
    
    lc = rep["living_circle"]
    assert "caliber" in lc, "生活圈报告必须包含 caliber 字段"
    cal = lc["caliber"]
    assert cal["travel_mode"] == "walking"
    assert isinstance(cal["speed_m_per_min"], (int, float))
    assert isinstance(cal["detour_k"], (int, float))
    assert isinstance(cal["study_radius_m"], int)
    assert isinstance(cal["iso_minutes"], list)
    assert isinstance(cal["basis"], str) and len(cal["basis"]) > 0
    assert cal["measured"] is True  # walking 是实测
    assert cal["sample_profile"] == "standard"
    # ── 空间口径三概念（可达区 / 采集区 / 研究区）必须显式举证 ──
    assert cal["reach_full_min"] == 20.0
    assert cal["reach_radius_bound_m"] > 0
    assert cal["reach_circumradius_m"] > 0
    assert cal["collect_radius_m"] >= cal["reach_circumradius_m"] * 0.999
    assert cal["collect_margin_m"] >= 0
    assert cal["cells_judged"] + cal["cells_unknown"] == cal["cells_inside"]


def test_create_task_requires_pipeline_kind():
    tid = create_living_circle_task(KAILI)
    task = db.get_task_full(tid)
    assert task["kind"] == "living_circle"
    assert (task["clarifications"] or {}).get("center") == [107.9758, 26.5734]


def test_pipeline_resolves_center_without_coordinates():
    """M3：纯地名输入（无 center）→ 按场景名匹配 fixture 样例中心（凯里老街兜底）。"""
    params = {k: v for k, v in KAILI.items() if k != "center"}
    tid = create_living_circle_task(params)
    assert not (db.get_task_full(tid)["clarifications"] or {}).get("center")
    events = _run_pipeline(tid)
    intake = next(e for e in events if e["type"] == "message" and e["data"]["stage"] == "intake")
    assert "107.9758, 26.5734" in intake["data"]["text"]
    # 未匹配样例名的场景回退默认样区
    tid2 = create_living_circle_task({**params, "scene_name": "不存在的小区"})
    events2 = _run_pipeline(tid2)
    intake2 = next(e for e in events2 if e["type"] == "message" and e["data"]["stage"] == "intake")
    assert "107.9758, 26.5734" in intake2["data"]["text"]