"""B17 · 形状口径（等时圈"第五把尺"，只诊断不入分）的判据集。

每条都带**正对照**：不只验"没报错"，而是验"把它改坏会红"。分相/原点这两件事
尤其如此 —— 它们今天看起来不影响结果，是因为恰好没有顶点压在箱界上。
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.living_circle import caliber_index
from app.living_circle import geo_utils as gu
from app.living_circle import isochrone as iso_mod
from app.living_circle.geo_utils import (
    SHAPE_AZIMUTH_FN,
    SHAPE_BIN_DEG,
    SHAPE_BIN_PHASE,
    SHAPE_ORIGIN,
    haversine_m,
    polygon_centroid,
    ring_area_km2,
    shape_of,
    to_local_xy,
)
from app.living_circle.isochrone import (
    IsochroneEngine,
    SHAPE_EMIT,
    SHAPE_MINUTES,
    shape_emit_for,
    shape_zone_keys,
)
from app.living_circle.report_contract import _shape_caliber_violations

FIXTURES = Path(gu.__file__).parent / "fixtures"
CENTER = (107.9758, 26.5734)


def _radial_meter(pts):
    """各向同性场（直线距离模型）：切出来的环在数学上就是正圆 —— 兼作退化告警的正对照。"""
    async def _m(ps):
        return [haversine_m(CENTER, p) / 75.0 for p in ps]
    return _m(ps)


async def _radial(ps):
    return [haversine_m(CENTER, p) / 75.0 for p in ps]


def _live_ring(minutes=15):
    d = json.loads((FIXTURES / "kaili-ev2.json").read_text(encoding="utf-8"))
    z = [x for x in d["isochrones"] if x["minutes"] == minutes][0]
    return d, [tuple(p) for p in z["geojson"]["coordinates"][0]], z


# ── ① 生产者本体 ────────────────────────────────────────────

def test_shape_of_matches_manual_control():
    """直调生产函数，与按定义手算的 8 箱逐一对账（防"实现与声明各说一套"）。"""
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    got = shape_of(ring, c, z["area_km2"])
    manual = [0.0] * 8
    for p in ring:
        x, y = to_local_xy(c, p[0], p[1])
        az = math.degrees(math.atan2(x, y)) % 360.0
        k = int(((az + 22.5) % 360.0) // 45.0) % 8
        manual[k] = max(manual[k], haversine_m(c, p))
    assert got["bins_m"] == [round(v, 1) for v in manual]
    from app.living_circle.geo_utils import _DIRECTIONS
    assert got["bins_word"] == list(_DIRECTIONS)   # 词表唯一出处：随键下发，前端不许另抄
    assert len(got["bins_m"]) == 8
    assert got["bin_deg"] == SHAPE_BIN_DEG == 45.0
    assert (got["bin_phase"], got["origin"], got["azimuth_fn"]) == (
        SHAPE_BIN_PHASE, SHAPE_ORIGIN, SHAPE_AZIMUTH_FN) == ("center", "scene.center", "bearing")


def test_shape_scalars_are_derived_from_this_zone_only():
    """圆度只能用本档 `area_km2`，比值只能用 `bins_m` —— 不许有第二个面积真源。"""
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    sh = shape_of(ring, c, z["area_km2"])
    eq_r = math.sqrt(z["area_km2"] * 1e6 / math.pi)
    assert sh["circularity"] == pytest.approx(eq_r / max(sh["bins_m"]), abs=1e-3)
    assert sh["weak_ratio"] == pytest.approx(min(sh["bins_m"]) / max(sh["bins_m"]), abs=1e-3)


def test_shape_of_rejects_unusable_area():
    """面积是圆度的分母来源：None/0/负/NaN 必须炸，不能静默产出一个看起来正常的比值。"""
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    for bad in (None, 0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            shape_of(ring, c, bad)
    with pytest.raises(ValueError):
        shape_of([], c, 1.0)


def test_bin_phase_is_a_caliber_not_an_implementation_detail():
    """**正对照**：同一颗环只把分相从"中心"换成"floor"，最弱读数就虚高 ≥100m。

    这条是"分相必须进键"的全部理由：floor 分相把北面缺口并进相邻方向取最大值，
    缺口被算法掩盖掉 —— 而载荷上看不出任何异常。
    """
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    center_phase = shape_of(ring, c, z["area_km2"])["bins_m"]
    floor_bins = [0.0] * 8
    for p in ring:
        x, y = to_local_xy(c, p[0], p[1])
        az = math.degrees(math.atan2(x, y)) % 360.0
        floor_bins[int(az // 45.0) % 8] = max(floor_bins[int(az // 45.0) % 8], haversine_m(c, p))
    assert min(center_phase) < min(floor_bins) - 100.0, (
        f"中心分相最弱 {min(center_phase)}m、floor 分相最弱 {min(floor_bins)}m —— 两者接近说明"
        "这条正对照失效了（环形状变了？），而它正是分相判据的判别力所在")


def test_origin_choice_moves_circularity_more_than_city_difference():
    """**正对照**：换一次原点带来的位移，和城市之间的真实差距同量级 ⇒ 原点必须钉死。"""
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    at_scene = shape_of(ring, c, z["area_km2"])["circularity"]
    cen = polygon_centroid(ring, c)
    at_centroid = math.sqrt(z["area_km2"] * 1e6 / math.pi) / max(
        haversine_m(cen, p) for p in ring)
    assert abs(at_scene - at_centroid) > 0.02, (
        "换原点几乎不动圆度 ⇒ 这条判据失去判别力（也意味着可以把原点当实现细节，"
        "但实测它能动 0.056，而城市之间总共只差 0.082）")


# ── ② 发键条件 ─────────────────────────────────────────────

def test_engine_emits_shape_only_for_walking_15_and_20():
    """引擎真跑：15/20 带键、5/10 不带、骑行/驾车一档都不带。"""
    engine = IsochroneEngine()
    iso = asyncio.run(engine.compute(CENTER, _radial, study_radius_m=2500, mode="quick"))
    zones = {int(z["minutes"]): z for z in iso["isochrones"]}
    assert set(zones) == {5, 10, 15, 20}
    for m in (15, 20):
        assert "shape" in zones[m], f"{m}min 该发形状键却没发"
    for m in (5, 10):
        assert "shape" not in zones[m], f"{m}min 内圈受网格控制（B8），不该发形状键"
    iso_ride = asyncio.run(engine.compute(
        CENTER, _radial, study_radius_m=5000, mode="quick", travel_mode="riding"))
    assert all("shape" not in z for z in iso_ride["isochrones"]), "骑行档的出不去指高速，不发比发错便宜"
    assert shape_emit_for("walking", 15) is True and shape_emit_for("walking", 5) is False
    assert shape_emit_for("riding", 15) is False


def test_shape_can_be_stopped_at_one_place():
    """回滚阀：`SHAPE_EMIT=False` ⇒ 一处关掉，所有渲染面因拿不到键而自动整块缺席。"""
    engine = IsochroneEngine()
    original = iso_mod.SHAPE_EMIT
    try:
        iso_mod.SHAPE_EMIT = False
        iso = asyncio.run(engine.compute(CENTER, _radial, study_radius_m=2500, mode="quick"))
        assert all("shape" not in z for z in iso["isochrones"])
    finally:
        iso_mod.SHAPE_EMIT = original
    assert iso_mod.SHAPE_EMIT is original is SHAPE_EMIT


def test_offline_report_carries_no_shape_keys():
    """离线件是数学正圆：圆度≈1.000 必须不发，否则"猜的那份"会排在真测件前面。"""
    from app.living_circle.data_source import CheckParams, OfflineDataSource

    rep = asyncio.run(OfflineDataSource().compute(
        CheckParams(scene_name="凯里老街", center=CENTER)))
    assert rep["data_origin"] == "offline"
    assert all("shape" not in z for z in rep["isochrones"]), "离线正圆带着形状读数＝把兜底冒充成测量"
    assert _shape_caliber_violations(rep) == []          # 整套缺席，契约不该响
    for z in rep["isochrones"]:
        assert z["area_km2"] > 0                          # 摘键不能把整档摘坏


# ── ③ 契约判据 B17 的六格 ──────────────────────────────────

def _with_shape(minutes=(15, 20)):
    """从真件出发，**先剥掉所有已有 shape 再按参数挂** —— 夹具已补键（笔二 S9），
    不剥就会让"只发一档"的用例其实两档齐发，判据被静默测成假绿。"""
    d, _, _ = _live_ring()
    c = tuple(d["scene"]["center"])
    rep = json.loads(json.dumps(d))
    for x in rep["isochrones"]:
        x.pop("shape", None)
        if int(x["minutes"]) in minutes:
            r = [tuple(p) for p in x["geojson"]["coordinates"][0]]
            x["shape"] = shape_of(r, c, x["area_km2"])
    return rep


def test_b17_absent_is_legal_on_a_stripped_payload():
    """剥干净后必须整套跳过（这条守住"缺席＝合法"，与存量件同形）。"""
    rep = _with_shape(minutes=())
    assert all("shape" not in z for z in rep["isochrones"])
    assert _shape_caliber_violations(rep) == []


def test_b17_absent_is_legal_and_complete_is_clean():
    d, _, _ = _live_ring()
    assert _shape_caliber_violations(d) == []            # 存量件：整套跳过
    assert _shape_caliber_violations(_with_shape()) == []  # 补齐两档：干净


def test_b17_catches_half_emission():
    rep = _with_shape(minutes=(15,))                     # 只发一档
    v = _shape_caliber_violations(rep)
    assert any("20min" in s and "半代发" in s for s in v), v


def test_b17_catches_phase_and_origin_drift():
    for field, bad, kw in (("bin_phase", "floor", "分相"),
                           ("origin", "centroid", "原点"),
                           ("azimuth_fn", "atan2", "方位角")):
        rep = _with_shape()
        rep["isochrones"][2]["shape"][field] = bad
        assert any(kw in s for s in _shape_caliber_violations(rep)), (field, bad)


def test_b17_catches_scalar_that_is_not_derived():
    rep = _with_shape()
    rep["isochrones"][2]["shape"]["circularity"] = 0.95   # 与 area/bins 对不上
    assert any("circularity" in s for s in _shape_caliber_violations(rep))
    rep2 = _with_shape()
    rep2["isochrones"][2]["shape"]["weak_ratio"] = 0.99
    assert any("weak_ratio" in s for s in _shape_caliber_violations(rep2))


def test_b17_catches_illegal_bin_values_and_missing_halves():
    rep = _with_shape()
    rep["isochrones"][2]["shape"]["bins_m"] = [0.0] * 8
    assert any("bins_m" in s for s in _shape_caliber_violations(rep))
    rep2 = _with_shape()
    rep2["isochrones"][2]["shape"]["bins_m"] = [
        float("nan") if i == 3 else v for i, v in enumerate(rep2["isochrones"][2]["shape"]["bins_m"])]
    assert any("bins_m" in s for s in _shape_caliber_violations(rep2))
    rep3 = _with_shape()
    del rep3["isochrones"][2]["shape"]["bin_phase"]
    assert any("缺" in s for s in _shape_caliber_violations(rep3))


def test_b17_circumradius_identity_is_conditional():
    """恒等式只在"这一档就是可达档"时成立；满分线挪出四档 ⇒ 判据必须自动失效，不假红。"""
    rep = _with_shape()
    z20 = [x for x in rep["isochrones"] if int(x["minutes"]) == 20][0]
    assert max(z20["shape"]["bins_m"]) == pytest.approx(rep["caliber"]["reach_circumradius_m"], abs=0.6)
    rep["caliber"]["reach_full_min"] = 25.0               # 满分线挪到四档之外
    assert _shape_caliber_violations(rep) == []


# ── ④ 名册与边界 ───────────────────────────────────────────

def test_shape_caliber_is_registered_in_the_index():
    refs = caliber_index.all_refs()
    for ref in ("isochrone::SHAPE_EMIT", "isochrone::SHAPE_MINUTES",
                "geo_utils::SHAPE_BIN_DEG", "geo_utils::SHAPE_BIN_PHASE",
                "geo_utils::SHAPE_ORIGIN", "geo_utils::SHAPE_AZIMUTH_FN"):
        assert ref in refs, f"{ref} 没进名册 —— 登记与落地必须同笔，否则它就是幻影条目"
    assert caliber_index.resolve("isochrone::SHAPE_MINUTES").value == str(SHAPE_MINUTES)


def test_shape_key_name_has_a_single_source():
    """键名只准出自发射口；判据与离线摘键都引它，抄字面就会两边各自漂移。"""
    assert set(shape_zone_keys()) == {"shape"}


def test_polygon_centroid_still_has_no_production_consumer():
    """质心这颗仍只被测试用：把它接进生产链就等于换了原点，而那条链上有三处旧判据。"""
    root = Path(gu.__file__).parent.parent               # app/
    hits = []
    for py in root.rglob("*.py"):
        if "test" in py.name:
            continue
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "polygon_centroid(" in line and "def polygon_centroid" not in line:
                hits.append(f"{py.name}:{i}")
    assert hits == [], f"polygon_centroid 出现了新消费者 {hits} —— 形状口径的原点是 scene.center"
