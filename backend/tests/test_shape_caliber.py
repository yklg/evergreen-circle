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
    方位角仍用生产的球面 `bearing()`：反事实只准动"分相"这一个变量，
    换成平面 atan2 会同时动方位角实现（实测最弱 571m vs 546m），差值就不再是纯分相的账。
    """
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    center_phase = shape_of(ring, c, z["area_km2"])["bins_m"]
    floor_bins = [0.0] * 8
    for p in ring:
        k = int(gu.bearing(c, p) // 45.0) % 8
        floor_bins[k] = max(floor_bins[k], haversine_m(c, p))
    assert min(center_phase) < min(floor_bins) - 100.0, (
        f"中心分相最弱 {min(center_phase)}m、floor 分相最弱 {min(floor_bins)}m —— 两者接近说明"
        "这条正对照失效了（环形状变了？），而它正是分相判据的判别力所在")


def test_origin_swap_changes_weakest_direction_word_on_another_site():
    """**正对照**：换原点不只动小数 —— 在劲松它直接改写"最弱方向是哪个"的结论。

    凯里只动数值（正北 438→553m），劲松连方位都改口（正西→东北）。同一颗 `shape_of`，
    只换第三个入参 ⇒ 屏上那句"最弱方向"完全由原点口径决定，原点必须钉死并进键。
    """
    d = json.loads((FIXTURES / "beijing-jinsong.json").read_text(encoding="utf-8"))
    z = [x for x in d["isochrones"] if x["minutes"] == 15][0]
    ring = [tuple(p) for p in z["geojson"]["coordinates"][0]]
    c = tuple(d["scene"]["center"])
    at_scene = shape_of(ring, c, z["area_km2"])
    at_centroid = shape_of(ring, polygon_centroid(ring, c), z["area_km2"])
    weak_at = lambda sh: sh["bins_word"][sh["bins_m"].index(min(sh["bins_m"]))]
    assert weak_at(at_scene) != weak_at(at_centroid), (
        f"两原点都念 {weak_at(at_scene)} ⇒ 这条改口判据失去判别力（AGENTS §7.4 第 1 条的依据）")
    assert at_scene["bins_word"][at_scene["bins_m"].index(min(at_scene["bins_m"]))] == "正西"


def test_origin_choice_moves_circularity_more_than_city_difference():
    """**正对照**：换一次原点带来的位移，和城市之间的真实差距同量级 ⇒ 原点必须钉死。"""
    d, ring, z = _live_ring()
    c = tuple(d["scene"]["center"])
    at_scene = shape_of(ring, c, z["area_km2"])["circularity"]
    at_centroid = shape_of(ring, polygon_centroid(ring, c), z["area_km2"])["circularity"]
    assert abs(at_scene - at_centroid) > 0.02, (
        "换原点几乎不动圆度 ⇒ 这条判据失去判别力（也意味着可以把原点当实现细节，"
        "但球面实算它能动 0.029，而两城之间总共只差 0.082）")


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
    """恒等式只在"这一档就是可达档"时成立；满分线挪出四档 ⇒ 判据必须自动失效，不假红。

    第三格是 **S27 补的**：前两格挪的是"满分线不在任何档里"，那种情况下即使把
    `reach_min in iso_minutes` 这道前提守卫摘掉，判据也不会走进去 ⇒ 守卫没被测到（变异台架
    实测：摘掉守卫后目标用例仍全绿）。这一格把满分线挪到**真有一档等于它、但那档不在
    `iso_minutes` 里**的位置，并要求 `max(bins_m)` 与外接半径**故意不相等** ⇒ 守卫在则绿、
    守卫被摘即红。前提守卫只有这么测才算有测。
    """
    rep = _with_shape()
    z20 = [x for x in rep["isochrones"] if int(x["minutes"]) == 20][0]
    assert max(z20["shape"]["bins_m"]) == pytest.approx(rep["caliber"]["reach_circumradius_m"], abs=0.6)
    rep["caliber"]["reach_full_min"] = 25.0               # 满分线挪到四档之外
    assert _shape_caliber_violations(rep) == []

    rep2 = _with_shape()
    rep2["caliber"]["iso_minutes"] = [5.0, 10.0, 20.0]    # 15min 档还在载荷里，却已不在口径四档内
    rep2["caliber"]["reach_full_min"] = 15.0
    rep2["caliber"]["reach_circumradius_m"] = 1.0        # 故意与 15min 档的 max(bins) 不等
    z15 = [x for x in rep2["isochrones"] if int(x["minutes"]) == 15][0]
    assert max(z15["shape"]["bins_m"]) > 100.0
    assert _shape_caliber_violations(rep2) == [], (
        "前提守卫失效：满分线指向一个不在 iso_minutes 里的档，判据却仍然去比外接半径 ⇒ 配置漂移假红")


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

# ── ④ 笔九第一笔（S21 / S23 / S28）：词表顺序、档位同源、字段级元判据 ──────

def test_b17_catches_word_table_rotated_out_of_order():
    """**S21**：`bins_word` 整体转一格（无重复、八项齐全）也必须被拒。

    第七笔审查实测的洞：旧判据只验"8 个、非空"⇒ 把词表转一格，每箱都配上错方位，
    载荷上看不出任何异常，而屏上那句"最弱方向：正北 438 m"会念成别的方向。
    """
    rep = _with_shape()
    sh = rep["isochrones"][2]["shape"]
    assert _shape_caliber_violations(rep) == []                 # 正对照：原样必须干净
    sh["bins_word"] = sh["bins_word"][1:] + sh["bins_word"][:1]  # 整体转一格
    hits = _shape_caliber_violations(rep)
    assert any("bins_word" in s for s in hits), f"转序没被抓到：{hits}"
    assert "正序" in " ".join(hits) or "不同序" in " ".join(hits)


def test_b17_tier_set_is_read_from_the_emission_valve():
    """**S23**：半代发那条判据的档位集合必须引 `SHAPE_MINUTES`，不许抄字面 (15, 20)。

    反例两格（本轮实测）：口径收窄成只发 15min ⇒ 旧写法**假红**；放宽到 10min 也发 ⇒
    旧写法对新档**完全不校验**。档位只该有一个真源。
    """
    from app.living_circle import report_contract as rc_mod

    only15 = _with_shape(minutes=(15,))                          # 20min 整档没发
    monkey_values = tuple(rc_mod.SHAPE_MINUTES)
    try:
        rc_mod.SHAPE_MINUTES = (15,)                             # 口径收窄
        assert _shape_caliber_violations(only15) == [], "收窄后仍要求 20min ⇒ 这是配置漂移假红"
        rc_mod.SHAPE_MINUTES = (15, 20)                          # 口径如今天
        assert any("20min" in s for s in _shape_caliber_violations(only15)), \
            "半代发没抓到（漏发那档屏上会整块缺席）"
        rc_mod.SHAPE_MINUTES = (10, 15, 20)                      # 口径放宽
        widened = _with_shape(minutes=(10, 15, 20))
        assert _shape_caliber_violations(widened) == [], f"放宽后新档本该被接受：{_shape_caliber_violations(widened)}"
        dropped = _with_shape(minutes=(10, 15, 20))
        [z for z in dropped["isochrones"] if int(z["minutes"]) == 10][0].pop("shape")
        assert any("10min" in s for s in _shape_caliber_violations(dropped)), \
            "新档进了发键口径却没人校验 ⇒ 档位集合还是两份真源"
    finally:
        rc_mod.SHAPE_MINUTES = monkey_values


def test_every_declared_shape_field_moves_a_gate():
    """**S28 字段级元判据**：八个声明字段，每个都被人为破坏一次 ⇒ 每次都必须有闸红。

    这条是本轮三条审查共同的收口：上一版四条缺口（忘发键、词表转序、两端容差、档位字面）
    全属同一形状 —— **字段随键下发了，却没有任何判据消费它**。逐格用例只能证明"当时想到的
    那一格"有人守，这一条证明"每个声明字段"都必须有人守；将来加第五个字段，漏配闸当场现形。
    """
    field_breakers = {
        "bins_m":      lambda sh: sh.__setitem__("bins_m", [0.0] * 8),
        "bins_word":   lambda sh: sh.__setitem__("bins_word", sh["bins_word"][1:] + sh["bins_word"][:1]),
        "bin_deg":     lambda sh: sh.__setitem__("bin_deg", 30.0),
        "bin_phase":   lambda sh: sh.__setitem__("bin_phase", "floor"),
        "origin":      lambda sh: sh.__setitem__("origin", "polygon_centroid"),
        "azimuth_fn":  lambda sh: sh.__setitem__("azimuth_fn", "atan2"),
        "circularity": lambda sh: sh.__setitem__("circularity", round(sh["circularity"] + 0.005, 3)),
        "weak_ratio":  lambda sh: sh.__setitem__("weak_ratio", 0.99),
    }
    # 腿一：生产者发出的字段集合 == 判据消费的字段集合（少一边就是幽灵字段）
    d, ring, z = _live_ring()
    produced = set(shape_of(ring, tuple(d["scene"]["center"]), z["area_km2"]))
    assert produced == set(field_breakers), (
        f"字段集合不对齐 —— 生产 {sorted(produced)} vs 判据 {sorted(field_breakers)}")
    # 腿二：逐字段破坏 ⇒ 至少一条违规，且文案点得出这个字段
    for field, break_it in field_breakers.items():
        rep = _with_shape()
        sh = rep["isochrones"][2]["shape"]
        assert _shape_caliber_violations(rep) == []
        break_it(sh)
        hits = _shape_caliber_violations(rep)
        assert hits, f"字段 {field} 被人为改坏却零违规 ⇒ 它没有闸消费（幽灵字段）"
        assert any(field in s for s in hits), f"{field} 的违规文案没点名它：{hits}"


@pytest.mark.xfail(reason="**S20 未落地**（计划 §三.10 / §九 TC-04）：live×walking 该发键却整套不发时，"
                          "B17 现在 `if not with_shape: return []` 直接放行 ⇒ 这条按设计必红。"
                          "S20 落地（代次戳 sh-1 三条件与）后请删掉本钉，strict 会在它转绿时先报 XPASS。",
                   strict=True)
def test_b17_requires_the_keys_a_live_walking_report_should_emit():
    """红钉：钉住"该发必发"这条**尚未存在**的正向判据（第七笔审查打穿的第一条）。"""
    rep = _with_shape()
    for x in rep["isochrones"]:
        x.pop("shape", None)
    rep["data_origin"] = "live"
    rep["caliber"]["travel_mode"] = "walking"
    assert _shape_caliber_violations(rep), "整套没发键却全绿 ⇒ 停发阀坏了没人报警"
