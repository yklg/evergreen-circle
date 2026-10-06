"""笔 3-B · 常态绕行标定与残差耗时（`rc-1`）的产出侧判据。

这组用例守的是四件事，都是本域已经犯过或明确警告过的形态：

① **标定测的是它说要测的东西**。无障碍的合成径向场必须标出 `speed_声明 / speed_实测`
   那个比值、残差处处 ≈ 0；单点障碍必须在**中位反标定之后仍然活下来**（中位数只扣常态，
   不许把尾巴抹平）。
② **「没量到」不许塌成 0**。样本为空 ⇒ `detour_factor_measured` / `residual_min` 发 `None`。
   这与逐格台账 `present` 用 int8 `-1/0/1`、`within_blind_radius` 用三态是同一条纪律；
   发 0 会被读成"量到了 0 分钟残差"，那是个有含义的结论。
③ **剔除要点名计数**，不静默丢。中心点（预期场在此坍缩为 0）、未测时点、零耗时点三类
   各自计数上屏 —— 否则读者无法判断那个中位数是从多少个点里来的。
④ **量纲纪律**：残差只有分钟。任何 `pct` / `ratio` 形态的键都是"把减法重新变成除法"，
   这里按键名钉死。

版本号与键集是同一次发布的两半（`report_contract` 的 B14）也在这里验：声明 `rc-1` 却没发
`sampling.detour` 必须红，而**从没声明过 `rc` 的存量件必须整套跳过**（否则每次加轴都要重烘
历史，正是本仓反复警告的假阳性）。
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.living_circle import caliber as caliber_mod
from app.living_circle import category_rule, scope
from app.living_circle.geo_utils import haversine_m
from app.living_circle.isochrone import IsochroneEngine, detour_residual
from app.living_circle.report_contract import (
    _reach_calibration_violations,
    reuse_policy,
)

CENTER = (107.9758, 26.5734)
SPEED = 80.0          # 步行档声明速度（caliber 的唯一事实源）
DECLARED_K = 1.3      # 声明的绕行系数 —— 与实测标定值是两回事，必须并存

FIXTURES = Path(__file__).resolve().parents[2] / "frontend/src/mocks/fixtures/livingCircle"


def _pts(n: int, step_m: float = 100.0) -> List[tuple]:
    """沿纬度方向排开的点列（1° ≈ 111.19km ⇒ 用米换纬度）。"""
    return [(CENTER[0], CENTER[1] + (i + 1) * step_m / 111194.8) for i in range(n)]


def _at(dist_m: float) -> tuple:
    return (CENTER[0], CENTER[1] + dist_m / 111194.8)


def _calibrate(points: List[tuple], minutes: List[Optional[float]], **over):
    kw = dict(speed_m_per_min=SPEED, declared_k=DECLARED_K)
    kw.update(over)
    return detour_residual(CENTER, points, minutes, **kw)


# ── ① 标定本身 ──────────────────────────────────────────────────────────────

def test_clean_field_calibrates_to_the_declared_speed_ratio():
    """无障碍径向场：实测按 75 m/min 走，声明 80 m/min ⇒ 隐含系数恒为 80/75、残差处处 0。

    这条是"标定测的是它说要测的东西"的基准面：一个都没有障碍的场面，必须标出一个确定的
    系数、且残差不 exceed 浮点噪声。若哪天有人把预期场写成 `距离 × 声明 k`（而不是本次
    标定的 k），这一条会立刻红 —— 那等于把没扣掉的常态绕行当成残差报出去。
    """
    pts = _pts(40, step_m=200.0)
    mins = [haversine_m(CENTER, p) / 75.0 for p in pts]
    out = _calibrate(pts, mins)
    assert out["detour_factor_measured"] == pytest.approx(SPEED / 75.0, abs=0.01), (
        f"径向场标出 {out['detour_factor_measured']}，理论 80/75=1.0667 ⇒ 预期场公式错了")
    res = out["residual_min"]
    assert abs(res["p50"]) < 0.1 and res["max"] - res["min"] < 0.2, (
        f"无障碍场不该有残差尾巴：{res}")
    assert out["points_used"] == 40, out["excluded"]


def test_isolated_barrier_survives_the_median_calibration():
    """中位反标定只扣**常态**：少数点的额外耗时必须留在残差里，而且按分钟说话。

    12 个点里 10 个是常态（1000m、12.5min ⇒ 隐含系数 1.0），2 个隔河（同距离 30min）。
    若标定用均值或被声明值 1.3 代替，那 2 个点会被常态吃掉或把整体抬歪。
    """
    pts = [_at(1000.0)] * 12
    mins = [12.5] * 10 + [30.0, 30.0]
    out = _calibrate(pts, mins)
    assert out["detour_factor_measured"] == pytest.approx(1.0, abs=0.01), out
    res = out["residual_min"]
    assert abs(res["p50"]) < 0.01, "常态那 10 个点必须被扣成 0"
    assert res["max"] == pytest.approx(17.5, abs=0.1), (
        f"障碍点的额外 17.5 分钟被抹掉了 ⇒ 残差场失去存在的理由：{res}")
    assert res["p90"] > 0, f"12 个点里 2 个受阻，p90 应该已经吃到尾巴：{res}"


def test_declared_and_measured_factors_stay_two_separate_numbers():
    """声明值（口径表里的 1.3）与本次实测标定值**必须并列**，不许互相覆盖。

    合成一个数就是"说错尺"的老形状：报告里既要说口径声明了多少，也要说这次量出多少，
    两者相差多少本身就是 `detour_k` 从未校准过的那笔账（文献 +14%≈1.14、仓内 1.3、
    凯里实测 1.620、劲松 1.529）。
    """
    pts = _pts(20, step_m=150.0)
    mins = [haversine_m(CENTER, p) / 80.0 * 1.9 for p in pts]
    out = _calibrate(pts, mins)
    assert out["declared_detour_k"] == DECLARED_K
    assert out["detour_factor_measured"] == pytest.approx(1.9, abs=0.01)
    assert out["declared_detour_k"] != out["detour_factor_measured"]


# ── ②③ 样本口径：剔除计数与"没量到" ────────────────────────────────────────

def test_excluded_points_are_counted_by_name_not_dropped_in_silence():
    """三类剔除各归各位：中心点（预期场坍缩）、未测时点、零耗时点。

    静默丢会让"入样 987 点标出 1.62"里的分母变成谜，而 20 点里 8 个被剔与 987 里 8 个被剔
    是两件完全不同的事。

    顺带钉住**归类顺序**：判据是「先看距离、再看耗时」，所以中心点上那个 `0.0` 记在
    `near_center` 而不是 `non_positive` —— 每个点只进一个桶，两桶都记就是把同一件事说两遍，
    分母也对不上账（下面那条 `used + Σexcluded == 总点数` 就是它的守恒式）。
    """
    pts = [CENTER] + _pts(6, step_m=300.0) + [_at(900.0), _at(1200.0), _at(1500.0)]
    mins: List[Optional[float]] = (
        [0.0] + [10.0, 12.0, 14.0, 16.0, 18.0, 20.0] + [None, 5.0, 0.0]
    )
    out = _calibrate(pts, mins)
    assert out["excluded"] == {"near_center": 1, "untimed": 1, "non_positive": 1}, out["excluded"]
    assert out["points_used"] == 7, "入样数必须等于总点数减三类剔除"
    assert out["points_used"] + sum(out["excluded"].values()) == len(pts)


def test_no_usable_sample_emits_null_and_never_zero():
    """全是未测时点 ⇒ 标定值与残差发 `None`。

    发 0 会被读成"量到了 0 分钟残差"（＝全场畅通），而那是一次根本没发生的测量。
    降级采样路径（`isochrone._budget_stage_points`）才会产出这类点，夹具里测不到，
    所以这条必须自造（计划 R5）。
    """
    out = _calibrate(_pts(5), [None] * 5)
    assert out["detour_factor_measured"] is None
    assert out["residual_min"] is None
    assert out["points_used"] == 0
    assert out["excluded"]["untimed"] == 5
    # 声明值仍然照发：口径声明与"这次有没有量到"是两件事
    assert out["declared_detour_k"] == DECLARED_K


def test_zero_minutes_point_is_not_a_sample():
    """`minutes=0` 不是"零耗时可达"，而是同点/测时异常 ⇒ 剔除并计入 non_positive。"""
    out = _calibrate([_at(500.0), _at(500.0)], [0.0, 6.25])
    assert out["excluded"]["non_positive"] == 1
    assert out["points_used"] == 1
    assert out["detour_factor_measured"] == pytest.approx(1.0, abs=0.01)


# ── ④ 量纲纪律 ──────────────────────────────────────────────────────────────

def test_residual_is_minutes_only_and_no_ratio_key_ever_appears():
    """残差只有分钟。任何百分比/比值形态的键＝把一次减法重新变成除法，一律钉死不许出现。"""
    out = _calibrate(_pts(10, step_m=250.0), [10.0] * 10)
    keys = set(out)
    assert keys == {"declared_detour_k", "detour_factor_measured", "implied_detour_p10",
                    "implied_detour_p90", "points_used", "excluded", "residual_min"}, keys
    assert not [k for k in keys if any(t in k.lower() for t in ("pct", "percent", "ratio"))]
    res = out["residual_min"]
    assert set(res) == {"p50", "p90", "p95", "max", "min"}, res
    assert all(abs(v) < 180 for v in res.values()), f"分钟数量级失真，像是被换算成了别的量纲：{res}"


def test_respect_the_distance_free_ordering_of_quantiles():
    """分位数单调：p50 ≤ p90 ≤ p95 ≤ max，且 min ≤ p50。写反了会把最堵的一档报小。"""
    pts = _pts(30, step_m=120.0)
    mins = [8.0 + i * 0.7 for i in range(30)]
    res = _calibrate(pts, mins)["residual_min"]
    assert res["min"] <= res["p50"] <= res["p90"] <= res["p95"] <= res["max"], res


# ── 产出链：真生产者发射 ─────────────────────────────────────────────────────

async def _radial_meter(pts, speed=75.0):
    return [haversine_m(CENTER, p) / speed for p in pts]


def test_compute_emits_the_detour_block_inside_sampling():
    """`IsochroneEngine.compute()` 必须在 `sampling` 段里发出那一份标定。

    放这里而不是让装配层从 `points` 反推：反推要把点集再遍历一遍、并把速度/绕行系数
    从第二条链读一遍 —— 那正是「实测场」与「对其的解释」分家的形态。
    """
    iso = asyncio.run(IsochroneEngine().compute(
        CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    det = iso["sampling"]["detour"]
    assert set(det) >= {"declared_detour_k", "detour_factor_measured", "points_used",
                        "excluded", "residual_min"}
    assert det["declared_detour_k"] == caliber_mod.get_caliber("walking").detour_k
    # 径向场（无障碍、且测时速度 ≠ 声明速度）⇒ 标定值 ≈ 声明速度/实测速度，残差 ≈ 0
    assert det["detour_factor_measured"] == pytest.approx(SPEED / 75.0, abs=0.01), det
    assert abs(det["residual_min"]["p95"]) < 0.2, det["residual_min"]
    # 中心点被剔、其余入样：分母与点数能对上账
    assert det["points_used"] + sum(det["excluded"].values()) == len(iso["sampling"]["points"])


def test_scope_payload_declares_the_reach_caliber_version():
    """版本键的唯一发射点在 `scope.payload()` —— 删掉那行，本条必须红（不是靠名册恒绿）。"""
    s = scope.SpatialScope(
        travel_mode="walking", reach_min=20.0,
        reach_ring=((107.97, 26.57), (107.98, 26.57), (107.98, 26.58), (107.97, 26.58)),
        reach_circumradius_m=1367.2, collect_radius_m=1367.2 + 1000.0, study_radius_m=2500.0,
    )
    out = s.payload(caliber_mod.get_caliber("walking"), {"cells_inside": 72, "cells_judged": 66})
    assert out["reach_caliber_version"] == caliber_mod.REACH_CALIBER_VERSION


# ── 契约 B14：版本号与键集同批发布 ───────────────────────────────────────────

def _lc_with(detour: Any, declare: bool = True) -> Dict[str, Any]:
    lc: Dict[str, Any] = {
        "data_origin": "live",
        "scene": {"center": list(CENTER), "study_radius_m": 2500},
        "caliber": {"scope_policy_version": scope.SCOPE_POLICY_VERSION,
                    "reach_full_min": 20.0, "collect_radius_m": 2367.2},
        "sampling": {"points": [{"lng": CENTER[0], "lat": CENTER[1], "minutes": None}]},
    }
    if declare:
        lc["caliber"]["reach_caliber_version"] = caliber_mod.REACH_CALIBER_VERSION
    if detour is not _OMIT:
        lc["sampling"]["detour"] = detour
    return lc


_OMIT = object()


def test_b14_declaring_rc_without_the_block_is_a_violation():
    """声明 `rc-1` 却没发 `sampling.detour` ⇒ 半吊子发布，必须红。"""
    issues = _reach_calibration_violations(_lc_with(_OMIT))
    assert any("sampling.detour" in s for s in issues), issues


def test_b14_missing_sample_or_exclusion_counters_is_a_violation():
    """键集不全也算半发布：剔除计数与残差分位都得在。"""
    bad = _lc_with({"declared_detour_k": 1.3, "detour_factor_measured": None,
                    "points_used": 0, "residual_min": None})
    issues = _reach_calibration_violations(bad)
    assert any("excluded" in s for s in issues), issues


def test_b14_half_published_values_are_violations():
    """标定值与残差分位必须同进同退；0 系数、0 样本却报数都不许过。"""
    assert _reach_calibration_violations(_lc_with({
        "declared_detour_k": 1.3, "detour_factor_measured": 1.62, "points_used": 900,
        "excluded": {"near_center": 1, "untimed": 0, "non_positive": 0}, "residual_min": None,
    }))
    assert _reach_calibration_violations(_lc_with({
        "declared_detour_k": 1.3, "detour_factor_measured": None, "points_used": 900,
        "excluded": {"near_center": 1, "untimed": 0, "non_positive": 0},
        "residual_min": {"p50": 0.0, "p90": 3.0, "p95": 5.0, "max": 9.0, "min": -2.0},
    }))
    assert _reach_calibration_violations(_lc_with({
        "declared_detour_k": 0.0, "detour_factor_measured": 1.62, "points_used": 900,
        "excluded": {"near_center": 1, "untimed": 0, "non_positive": 0},
        "residual_min": {"p50": 0.0, "p90": 3.0, "p95": 5.0, "max": 9.0, "min": -2.0},
    }))
    good = {
        "declared_detour_k": 1.3, "detour_factor_measured": 1.62, "points_used": 900,
        "excluded": {"near_center": 1, "untimed": 0, "non_positive": 0},
        "residual_min": {"p50": 0.0, "p90": 3.0, "p95": 5.0, "max": 9.0, "min": -2.0},
    }
    assert _reach_calibration_violations(_lc_with(good)) == [], "正对照必须真能过（否则上面三条恒红）"


def test_b14_skips_reports_that_never_declared_rc():
    """没声明 `rc` 的载荷 ⇒ 整套跳过 —— 用**合成件**验，不拿真夹具当样本（夹具已被烘进键）。

    这条的存在保证"加一根轴不重烘历史"仍然成立：读侧对没有这把键的载荷不加任何违规，
    否则 27 份存量会在页面上集体挂红字，把"这次没做过标定"说成"这份报告坏了"。
    """
    legacy = _lc_with(_OMIT, declare=False)
    assert _reach_calibration_violations(legacy) == []
    # 只缺半边的合成件也不能被跳过（那不是"旧件"，是"新件发坏了"）
    assert _reach_calibration_violations(_lc_with(_OMIT)) != []


@pytest.mark.parametrize("file", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_shipped_fixtures_carry_both_halves(file: str):
    """三份出厂夹具（`bcefdda` 之后）必须**两半同批**：声明 `rc-1` 且带 `sampling.detour`。

    烘法见 `scripts/backfill_fixture_detour.py`：标定值由生产函数从各份夹具自己的点集现算
    （零外呼），逐字段证明改动面恰好等于 `{caliber.reach_caliber_version, sampling.detour}`。
    这条同时是**正对照**：如果哪天有人只摘块、留键（或反之），B14 必须在这里咬住 ——
    合成件那两条只验"判定逻辑存在"，真夹具这条验"我们自己的出厂数据真合规"。
    """
    lc = json.loads((FIXTURES / file).read_text(encoding="utf-8"))
    cal = lc.get("caliber") or {}
    det = (lc.get("sampling") or {}).get("detour")
    assert cal.get("reach_caliber_version") == caliber_mod.REACH_CALIBER_VERSION, file
    assert isinstance(det, dict), f"{file}: 声明了 rc 却没有标定块 ⇒ B14 该判违规"
    assert det["detour_factor_measured"] and det["points_used"] > 0, det
    # 标定是从这份夹具自己的点集算的：分母要能与点数对上账
    assert det["points_used"] + sum(det["excluded"].values()) == len(lc["sampling"]["points"])
    assert _reach_calibration_violations(lc) == []


def test_rc_clause_is_composed_but_blocks_no_row():
    """第三根轴必须能拼出句、却**不拦差异表里任何一行**（今天）。

    两半都是判据：
      · 拼不出句 ⇒ 横幅漏报（读者以为只是"两份社区不同"）；
      · 拦得住行 ⇒ 撒谎 —— rc-1 不改任何一行的读数，把「不可比」挂到一行上就是
        #83 抓过的形态反过来重演一次（那次是评分轴去拦盲区行）。
    """
    from app.main import (
        _DIFF_DESC_ALL_GAP,
        _DIFF_DESC_BOTH_GAP,
        _DIFF_DESC_CALIBER_GAP,
        _DIFF_DESC_REACH_GAP,
        _REACH_GAP_ROWS,
        _gap_desc,
        _row_gap_desc,
    )

    assert _DIFF_DESC_REACH_GAP == "不可比 · 可达口径已升级（耗时场新增常态绕行与残差解释）"
    assert _REACH_GAP_ROWS == (), "rc 今天不该出现在任何一行的轴清单里"
    for metric in ("服务盲区", "综合评分", "POI 采集", "圈内 POI", "15min 等时圈面积 (km²)",
                   "可达采样点数"):
        assert _row_gap_desc(metric, ("rc",)) is None, f"{metric} 被 rc 拦下了"
    # 三轴都不同那一档：评分行仍只拿 `ev+cov` 那句 —— rc 不许渗进来
    assert _row_gap_desc("综合评分", ("ev", "cov", "rc")) == _DIFF_DESC_BOTH_GAP
    assert _row_gap_desc("服务盲区", ("ev", "cov", "rc")) == _DIFF_DESC_CALIBER_GAP
    # 而**横幅**那一句必须三段子句都在（组合式不许退化成"只报前两根"）
    assert _gap_desc(("ev", "cov", "rc")) == _DIFF_DESC_ALL_GAP
    assert _DIFF_DESC_ALL_GAP.count("已升级") == 3


def test_fixture_pipeline_publishes_the_rc_pair():
    """演示链（fixture 分支）必须**同批**发出这两半：`caliber.reach_caliber_version` 与
    `sampling.detour`，而且值是**按这份快照自己的点集现算**的，不是烘在文件里的那份。

    为什么不能只靠 B14 那几条：B14 是读侧判定，载荷整个不发这把键时它会当作"存量旧件"跳过。
    删掉 `pipeline/living_circle.py` 里那两行装配 ⇒ B14、名册、契约全都不说话，而屏幕上
    什么都没有 —— 正是本仓反复吃过的那种"机制就绪但没人消费"。
    顺带钉住演示报告的可见性不受这把轴影响（`assess_geometry.ok`）。
    """
    from app.core import db
    from app.core.pipeline.living_circle import create_living_circle_task, living_circle_pipeline
    from app.living_circle.report_contract import assess_geometry

    tid = create_living_circle_task({
        "scene_name": "凯里老街", "city": "黔东南苗族侗族自治州",
        "address": "凯里市西门街道老街片区", "center": [107.9758, 26.5734],
        "study_radius_m": 2500.0, "mode": "standard", "data_mode": "fixture",
    })

    async def _collect():
        return [ev async for ev in living_circle_pipeline(tid)]

    events = asyncio.run(_collect())
    done = next((e for e in events if e["type"] == "done"), None)
    assert done, f"管线没走到 done：{[e['type'] for e in events][-6:]}"
    row = db.get_living_circle_report(done["data"]["report_id"]) or {}
    # `get_living_circle_report` 返回的是**报告外壳**（title/sections/…），生活圈载荷在
    # `living_circle` 那一格 —— 直接拿外壳读 `caliber` 会得到 None，那条断言就会恒判"未发出"。
    lc = row.get("living_circle") or {}
    assert lc, f"报告外壳里没有 living_circle 载荷：{sorted(row)[:8]}"
    assert (lc.get("caliber") or {}).get("reach_caliber_version") == caliber_mod.REACH_CALIBER_VERSION
    det = (lc.get("sampling") or {}).get("detour")
    assert isinstance(det, dict) and det["points_used"] > 0, det
    # 现算而不是照抄：入样 + 三类剔除必须等于这份载荷自己的点数
    assert det["points_used"] + sum(det["excluded"].values()) == len(lc["sampling"]["points"])
    assert _reach_calibration_violations(lc) == []
    assert assess_geometry(lc).ok, "新增这把轴不该让演示报告变得不可展示"


def test_offline_reports_claim_neither_the_calibration_nor_the_version():
    """离线估算件必须**同时**缺席 `sampling.detour` 与 `caliber.reach_caliber_version`。

    离线的 `meter_fn` 是距离模型的恒等式（`直线 × detour_k ÷ 速度`，`data_source.py:266`）。
    拿它去标定必然得到 `detour_factor_measured ≡ 声明值`、残差处处 0 —— 那是代数量和自己在比，
    不是一次测量。留着它就会在屏幕上出现「按本次实测标定的常态绕行 1.3×…最堵的一档 0min」，
    等于替一次没发生的测量举证；只摘块、留版本号则会撞上 B14（声明却缺键 ⇒ 整份报告变不可展示）。
    所以这两半必须**同批缺席**，这条用例同时钉住两侧。
    """
    from app.living_circle.data_source import CheckParams, OfflineDataSource

    rep = asyncio.run(OfflineDataSource().compute(
        CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734))))
    assert rep["data_origin"] == "offline" and rep["sampling"]["interpolation"] == "circular_approx"
    assert "detour" not in rep["sampling"], "离线继承了实测标定块 ⇒ 屏幕会把距离模型的恒等式说成测量"
    assert "reach_caliber_version" not in rep["caliber"], "没有键集却声明版本号 = B14 会把离线件打死"
    assert _reach_calibration_violations(rep) == []
    # 其余采样读数照旧继承（只摘那一块，不许顺手把点数/分档也丢掉）
    assert rep["sampling"]["points"] and "timed_count" in rep["sampling"]


def test_pipeline_only_calibrates_measured_fields():
    """演示链的标定必须挂在 `interpolation == 'idw'` 条件里（源码扫描，防"以后有人搬出去"）。

    行为用例只能证明"今天这份夹具是 idw"；把这段从 `if` 里挪出来，所有夹具照样绿，
    而哪天挂上一份 `circular_approx` 的演示件就会开始播报"实测标定"。所以钉**结构**。
    """
    import inspect

    from app.core.pipeline import living_circle as pl

    src = inspect.getsource(pl)
    i_cal = src.index('fx_sampling["detour"]')
    i_if = src.rindex('== "idw"', 0, i_cal)
    assert i_cal - i_if < 400, "标定块离 `interpolation == 'idw'` 那道闸太远 ⇒ 条件可能被拆开或绕过"
    assert src.index("reach_caliber_version") > i_if, "版本键的声明不该在 idw 闸之外"


def test_offline_meter_is_a_tautology_so_it_cannot_be_a_calibration():
    """正面证明上面那条剥离为什么必须存在：**拿离线那个 `meter_fn` 去标定，量的是恒等式**。

    离线 `meter_fn` 是 `hour_to_minutes(直线距离 × caliber.detour_k, caliber.speed_m_per_min)`
    ⇒ 隐含系数 `minutes × speed / distance` 逐点**恒等于** `detour_k`，残差恒为 0。
    所以那份块若被继承出去，屏幕上「实测标定的常态绕行 1.3×…最堵的一档 0min」说的其实是
    "我把声明值乘回去再除了一遍"。这条用例不注入故障、只直调生产函数把这个恒等式量出来，
    比注释硬：哪天有人改离线的测时公式（不再是距离模型），这里当场红。
    """
    from app.living_circle.caliber import get_caliber
    from app.living_circle.data_source import hour_to_minutes

    cal = get_caliber("walking")
    pts = _pts(24, step_m=180.0)
    offline_minutes = [hour_to_minutes(haversine_m(CENTER, p) * cal.detour_k, cal.speed_m_per_min)
                       for p in pts]
    out = _calibrate(pts, offline_minutes)
    assert out["detour_factor_measured"] == pytest.approx(cal.detour_k, rel=1e-3), (
        "离线标定的中位数不再等于声明值 ⇒ 离线的测时公式变了，上面那条剥离的理由要重估")
    res = out["residual_min"]
    assert max(abs(res["max"]), abs(res["min"])) < 0.05, (
        f"距离模型本不该有任何残差，实测却给出 {res} ⇒ 恒等式的前提不再成立")


def test_rc_key_does_not_move_the_reuse_gate():
    """带不带 `rc` 声明，复用门必须**同判**。

    这条不是"没测到"：`rc-1` 有意登记在 `UNGATED_CALIBER_VERSIONS`（理由写在那张表里），
    判据本身由 `test_caliber_axes_are_registered_everywhere_they_must_be` 双向钉住。
    门若被移动，27 份存量与每次 500m 邻近复用都会 miss、重打 1049 点矩阵（真配额）。
    """
    wanted = {"travel_mode": "walking", "sample_profile": "standard", "study_radius_m": 2500.0}
    base = _lc_with({
        "declared_detour_k": 1.3, "detour_factor_measured": 1.62, "points_used": 900,
        "excluded": {"near_center": 1, "untimed": 0, "non_positive": 0},
        "residual_min": {"p50": 0.0, "p90": 3.0, "p95": 5.0, "max": 9.0, "min": -2.0},
    })
    base["caliber"]["coverage_caliber_version"] = category_rule.COVERAGE_CALIBER_VERSION
    base["caliber"]["travel_mode"] = "walking"
    base["caliber"]["sample_profile"] = "standard"
    without = copy.deepcopy(base)
    del without["caliber"]["reach_caliber_version"]
    assert reuse_policy(base, wanted) == (True, ""), "带 rc 的本次产物不该被自家门拒"
    assert reuse_policy(without, wanted) == reuse_policy(base, wanted), (
        "同一份载荷只多一把 rc 声明就换了判定 ⇒ 复用门被移动了")
