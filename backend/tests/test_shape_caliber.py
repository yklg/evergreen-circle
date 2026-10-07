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
    SHAPE_CALIBER_VERSION,
    SHAPE_EMIT,
    SHAPE_MINUTES,
    shape_emit_for,
    shape_zone_keys,
)
from app.living_circle.report_contract import (
    SHAPE_CIRCUMRADIUS_TOL_M,
    _shape_caliber_violations,
)

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
    """离线件是数学正圆：圆度≈1.000 必须不发，否则"猜的那份"会排在真测件前面。

    S20 之后这一位也要**同批缺席**：只摘块、留戳 ⇒ B17 的缺席分支会把离线件判成"声明却缺键"，
    整份报告变得不可展示；只留块、摘戳 ⇒ 缺席分支放行了正圆假件。两半必须一起没有。
    """
    from app.living_circle.data_source import CheckParams, OfflineDataSource

    rep = asyncio.run(OfflineDataSource().compute(
        CheckParams(scene_name="凯里老街", center=CENTER)))
    assert rep["data_origin"] == "offline"
    assert all("shape" not in z for z in rep["isochrones"]), "离线正圆带着形状读数＝把兜底冒充成测量"
    assert "shape_caliber_version" not in rep["caliber"], (
        "没有键集却声明版本号 = B17 会把离线件打死（与 `rc-*`/`detour` 那条同一条纪律）")
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


def _strip_all(rep):
    """把所有档的形状键摘干净 —— 造「整套缺席」那份载荷（缺席分支的唯一入口）。"""
    for x in rep["isochrones"]:
        x.pop("shape", None)
    return rep


def _stamped(rep):
    """盖上这一代的戳。生产端唯一写点是 `scope.payload()`，这里只造**载荷状态**。"""
    rep["caliber"]["shape_caliber_version"] = SHAPE_CALIBER_VERSION
    return rep


def _drop_tiers_from_iso(rep, drop):
    """把某些分钟数从口径声明的档位组合里挪走（`caliber.py` 里它是**按模式可配**的）。"""
    rep["caliber"]["iso_minutes"] = [m for m in rep["caliber"]["iso_minutes"]
                                     if int(m) not in drop]
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


def test_b17_flags_two_sources_of_circumradius():
    """**S33 补的那格**：该报时必须报 —— 把可达档的外接半径改歪，判据必须说「两个真源」。

    2026-10-07 实测：把整支外接半径恒等检查摘掉（`if False:`）后，`test_shape_caliber.py`
    **22 条仍全绿** —— 因为已有的三格全在测"什么时候不该报"，没有一格测"该报时真报"。
    一条从不验证自身会响的守卫，和没有这条守卫等价（与 §九 S28 那条同族）。
    """
    rep = _with_shape()
    z20 = [x for x in rep["isochrones"] if int(x["minutes"]) == 20][0]
    assert _shape_caliber_violations(rep) == []                 # 正对照：同式同点时干净
    cr = max(z20["shape"]["bins_m"])
    # **断言用绝对量，不用常量去乘自己**：否则有人把 `SHAPE_CIRCUMRADIUS_TOL_M` 放宽到 1e9
    # （名义上判据还在、实际永不触发），跟着常量走的两端会一起搬家、变异照样绿。
    # 第一版就犯了这条 —— 台架实测"容差改 1e9"那一刀仍全绿，改成下面这样才被抓住。
    rep["caliber"]["reach_circumradius_m"] = round(cr + 5.0, 1)
    hits = _shape_caliber_violations(rep)
    assert any("两个真源" in x for x in hits), f"外接半径被改歪 5m 却零违规 ⇒ 这条恒等检查是摆设：{hits}"
    # 边界另一侧：0.2m 不许报。依据（2026-10-07 全样实测，非抽样）：6 份真夹具（后端 3 + 前端镜像 3）
    # 可达档的 max(bins_m) 与 reach_circumradius_m **偏差全为 0.000**（两者同出 0.1m 步长取整）
    # ⇒ 0.6 不是迁就既有漂移的容差；这里用字面量而不是 k·常量，理由见上面那段。
    rep2 = _with_shape()
    rep2["caliber"]["reach_circumradius_m"] = round(cr + 0.2, 3)
    assert _shape_caliber_violations(rep2) == [], "0.2m 的取整噪声被误判成两个真源"
    assert SHAPE_CIRCUMRADIUS_TOL_M < 5.0, "容差不许放宽到吞掉 5m 级别的真漂移（上面那格会假绿）"


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
    assert max(z20["shape"]["bins_m"]) == pytest.approx(
        rep["caliber"]["reach_circumradius_m"], abs=SHAPE_CIRCUMRADIUS_TOL_M)
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
    assert (caliber_index.resolve("report_contract::SHAPE_CIRCUMRADIUS_TOL_M").value
            == str(SHAPE_CIRCUMRADIUS_TOL_M)), "名册里的外接半径容差与判据用的不是同一个数"


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


# ── ⑤ 正向"该发必发"（S20 · B17 的缺席分支，计划 §三.10 那张六格验收表）──

@pytest.mark.parametrize("build, expected", (
    pytest.param(lambda r: _stamped(r), 0, id="① 有戳+该发+有键 绿"),
    pytest.param(lambda r: _stamped(_strip_all(r)), 2, id="② 有戳+该发+缺键 红（本条要抓的那件事）"),
    pytest.param(lambda r: _strip_all(r), 0, id="③ 无戳+缺键 绿（库存全部存量件靠它）"),
    pytest.param(lambda r: r, 0, id="④ 无戳+有键 绿（回算过的夹具，不许反过来打死自己）"),
    pytest.param(lambda r: _stamped(_drop_tiers_from_iso(_strip_all(r), (15, 20))), 0,
                 id="⑥ 有戳+该发但 iso_minutes 不含 绿（档位组合可按模式配）"),
))
def test_s20_requires_the_keys_a_stamped_live_walking_report_should_emit(build, expected):
    """整套缺席分两态：**没声明这一代 ⇒ 合法**，声明了这一代却整批不发 ⇒ 违规。

    落地前这里只有前一半（`if not with_shape: return []`），于是"忘了发键"被前端的
    `shapeOfZone ⇒ null` 静默吃掉 —— 屏上看不出是「这座城市八面都不缺」还是「这台机器没量」。
    ⑤（停发阀）与另外两格（模式 / 整档不在载荷）在
    `test_s20_exemptions_are_each_load_bearing` 里**成对**写 —— 那三格必须自证"撤掉它就红"，
    塞进这张表会让它们看起来像恒真。③ 与上面 `test_b17_absent_is_legal_on_a_stripped_payload`
    同形，这里刻意再列一次：这张表是这条判据的验收口径，一格都不许缺。
    """
    hits = _shape_caliber_violations(build(_with_shape()))
    if not expected:
        assert hits == [], f"不该报却报了：{hits}"
        return
    assert len(hits) == expected, f"应报 {expected} 条（两档各一条），拿到：{hits}"
    for m in SHAPE_MINUTES:
        assert any(f"{m}min" in h for h in hits), f"{m}min 档没被点名 ⇒ 违规句无法定位：{hits}"
    assert all("shape_caliber_version" in h for h in hits), (
        f"违规句里没写出是谁声明的这一代 ⇒ 读者无从核对豁免：{hits}")


@pytest.mark.parametrize("case", ("valve_closed", "mode_riding", "mode_missing",
                                  "tier_absent_from_payload"))
def test_s20_exemptions_are_each_load_bearing(case, monkeypatch):
    """豁免表与缺省归属每一档都要**自证它今天真的在挡什么**：撤掉那一档，同一份载荷必须转红。

    只测"豁免时绿"是不够的 —— 那等于测了一条永不触发的前提（本仓 S27/S33 两次都栽在这上面）。
    所以每格都成对写：该豁免 ⇒ 绿，把那个条件撤掉 ⇒ 立刻红。
    """
    if case == "valve_closed":
        # ⑤ 停发阀优先于戳：本代不产这把尺 ⇒ 不发键不算违规
        monkeypatch.setattr(iso_mod, "SHAPE_EMIT", False)
        assert _shape_caliber_violations(_stamped(_strip_all(_with_shape()))) == []
        monkeypatch.setattr(iso_mod, "SHAPE_EMIT", True)
        assert len(_shape_caliber_violations(_stamped(_strip_all(_with_shape())))) == 2, (
            "撤掉停发阀后那一格没让它变红 ⇒ 上面的绿是恒真，停发阀这条豁免根本没生效")
        return

    if case == "mode_riding":
        # 骑行档：发键条件不成立（§三.6，那句屏上诊断在车速下会撒谎）⇒ 缺键合法
        rep = _stamped(_strip_all(_with_shape()))
        rep["caliber"]["travel_mode"] = "riding"
        assert _shape_caliber_violations(rep) == []
        rep["caliber"]["travel_mode"] = "walking"
        assert len(_shape_caliber_violations(rep)) == 2, "模式这一维没在挡 ⇒ 上面的绿是恒真"
        return

    if case == "mode_missing":
        # 载荷没写 travel_mode ⇒ 按 walking 判（与 `report_contract:966` 同一颗缺省，不是第二套规矩）。
        # 这一格钉的是**缺省的方向**：缺省成"跳过"就等于给"漏写模式"开了一个免检通道。
        no_mode = _stamped(_strip_all(_with_shape()))
        no_mode["caliber"].pop("travel_mode", None)
        walking = _stamped(_strip_all(_with_shape()))
        assert len(_shape_caliber_violations(no_mode)) == len(_shape_caliber_violations(walking)) == 2, (
            "缺 travel_mode 时这把尺应当照 walking 要求键集，而不是静默放行")
        return

    # 这一档**根本不在载荷里**（环退化时整档缺席）：那是另一条缺陷，不该由这把尺报成
    # "缺形状键" —— 报出去会把人引向错的地方（判据自己撒谎）。
    rep = _stamped(_with_shape())
    rep["isochrones"] = [z for z in rep["isochrones"] if int(z["minutes"]) != 15]
    _strip_all(rep)
    hits = _shape_caliber_violations(rep)
    assert len(hits) == 1 and "20min" in hits[0], (
        f"15min 档整档不在载荷里，判据却该只说 20min：{hits}")


def test_s20_valve_gate_reads_the_emission_valve_not_the_stamp_alone():
    """把 `shape_emit_for` 换成"只看戳"（草案里那版）会立刻打死骑行档与本代 —— 这条钉住前置。"""
    rep = _stamped(_strip_all(_with_shape()))
    rep["caliber"]["travel_mode"] = "cycling"
    assert _shape_caliber_violations(rep) == []
    assert shape_emit_for("cycling", 15.0) is False


def test_scope_payload_is_the_only_emission_point_for_the_shape_stamp():
    """戳的唯一写点在 `scope.payload()` —— 删掉那一行，本条必须红（不是靠名册恒绿）。

    与 `test_reach_calibration.py::test_scope_payload_declares_the_reach_caliber_version` 同形。
    """
    from app.living_circle import caliber as caliber_mod
    from app.living_circle import scope

    s = scope.SpatialScope(
        travel_mode="walking", reach_min=20.0,
        reach_ring=((107.97, 26.57), (107.98, 26.57), (107.98, 26.58), (107.97, 26.58)),
        reach_circumradius_m=1367.2, collect_radius_m=1367.2 + 1000.0, study_radius_m=2500.0,
    )
    out = s.payload(caliber_mod.get_caliber("walking"), {"cells_inside": 72, "cells_judged": 66})
    assert out["shape_caliber_version"] == SHAPE_CALIBER_VERSION, (
        "生产产出没有这一位 ⇒ 发射行被删或改了名，B17 的缺席分支会退化成今天这种无闸状态")


def test_shape_stamp_does_not_move_the_reuse_gate():
    """`reuse_policy` 逐字不看这一位 ⇒ 带着它和不带它必须同判（照 `test_pages_returned` 那三行）。

    这一位进了 `caliber` 载荷，而缓存与邻近复用吃的就是那份载荷。它是**解释层代次**：换它只是
    多一把诊断尺（`scoring.WEIGHTS` 不动、盲区数/分数/面积都不动），重跑一次的答案逐位相同。
    若哪天有人把它变成复用判据，本条先红 —— 那种降级应当由 `evidence_complete` 那条链负责，
    而代价是实测的：存量件与每次 500m 邻近复用全部 miss、全部重打距离矩阵与逐类检索（真配额）。
    """
    from app.living_circle.report_contract import reuse_policy
    from app.living_circle.scope import COVERAGE_CALIBER_VERSION, SCOPE_POLICY_VERSION

    base = {
        "data_origin": "live",
        "scene": {"name": "凯里老街", "center": [107.9758, 26.5734], "study_radius_m": 2500},
        "caliber": {"scope_policy_version": SCOPE_POLICY_VERSION,
                    "coverage_caliber_version": COVERAGE_CALIBER_VERSION,
                    "travel_mode": "walking", "sample_profile": "standard"},
    }
    wanted = {"travel_mode": "walking", "sample_profile": "standard", "study_radius_m": 2500.0}
    assert reuse_policy(base, wanted) == (True, ""), (
        "前提不成立：这份基准载荷本来就不给复用，比不出「新增键没改变判定」")

    with_key = {**base, "caliber": dict(base["caliber"],
                                        shape_caliber_version=SHAPE_CALIBER_VERSION)}
    without_key = {**base, "caliber": {k: v for k, v in base["caliber"].items()
                                      if k != "shape_caliber_version"}}
    assert reuse_policy(with_key, wanted) == reuse_policy(without_key, wanted) == (True, "")
