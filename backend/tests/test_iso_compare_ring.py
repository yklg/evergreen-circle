"""口径对比环（笔 B）：同一份实测耗时场按文献阈值再切一刀，作为**两把尺的对照**而非能力断言。

赛题痛点段点了养老，文献又指出"80 m/min 的基准步速是健康成年人、高龄有效步行窗口可能仅
5–8min"。工程上能诚实做的是：**把同一个场按 8min 重切一条线**，让读者看见"我们选的满分线"
与"文献那把尺"差多少 —— 而不是宣称某个社区的老人走不到哪里。所以这一族的每条判据都在守两件事：
① 它是**对照**（不进 `isochrones` 那四档：配色表钉 `length === 4`、面积单调性、图例都按四档跑）；
② 它**不越证据**（断言边界写进载荷、依据必须带出处、估算链一律不发）。

判据分组：产出侧（引擎/装配/离线各自的行为）、口径重建（`get_caliber` 不许把新字段打回默认值）、
契约 B16 的十种形状、名册登记。
"""
import asyncio
from typing import Any, Dict

import pytest

from app.living_circle.caliber import (
    DEFAULT_CALIBERS,
    ISO_COMPARE_BASIS,
    get_caliber,
    ReachCaliber,
)
from app.living_circle.isochrone import IsochroneEngine
from app.living_circle.report_contract import _iso_compare_violations

CENTER = (107.9758, 26.5734)


def _meter(mode: str = "walking"):
    """规则径向场（分钟 ∝ 到中心距离）：四档与对照档的面积因此可比。"""
    import math

    async def m(pts):
        out = []
        for i, p in enumerate(pts):
            d = math.hypot((p[0] - CENTER[0]) * 111000 * math.cos(math.radians(CENTER[1])),
                           (p[1] - CENTER[1]) * 111000)
            out.append(None if i % 97 == 0 else round(d / 80.0, 1))
        return out
    return m


def _compute(mode: str = "walking") -> Dict[str, Any]:
    return asyncio.run(IsochroneEngine().compute(
        CENTER, _meter(mode), study_radius_m=2500, mode="quick", travel_mode=mode))


# ── ① 产出侧 ────────────────────────────────────────────────

def test_walking_field_produces_the_compare_ring_alongside_four_zones():
    """步行档：四档照旧**恰好四条**，对照环单独发一块，且面积落在 5min 与 10min 之间。"""
    iso = _compute("walking")
    assert [z["minutes"] for z in iso["isochrones"]] == [5, 10, 15, 20], "对照环混进了四档"
    cmp_zone = iso.get("iso_compare")
    assert cmp_zone, "步行档声明了阈值却没切出环 ⇒ 这一笔的产出侧空转"
    assert set(cmp_zone) == {"minutes", "geojson", "area_km2", "basis", "claim"}
    assert cmp_zone["minutes"] == get_caliber("walking").iso_compare_min == 8.0
    areas = {z["minutes"]: z["area_km2"] for z in iso["isochrones"]}
    assert areas[5] < cmp_zone["area_km2"] < areas[10], (areas, cmp_zone["area_km2"])
    ring = cmp_zone["geojson"]["coordinates"][0]
    assert len(ring) >= 4 and ring[0] == ring[-1], "环必须 ≥4 点且闭合（前端直接取这串画多边形）"
    assert cmp_zone["claim"] == "caliber_comparison_only"
    assert _iso_compare_violations({"data_origin": "live", "caliber": iso_caliber(),
                                    "isochrones": iso["isochrones"],
                                    "iso_compare": cmp_zone}) == []


def iso_caliber() -> Dict[str, Any]:
    """一份与产出同代次的 caliber 声明（B16 用它判"这条尺属不属于该档"）。"""
    cal = get_caliber("walking")
    return {"travel_mode": "walking", "iso_minutes": list(cal.iso_minutes)}


@pytest.mark.parametrize("mode", ["riding", "driving"])
def test_non_walking_modes_declare_nothing_and_emit_nothing(mode):
    """骑行/驾车：口径表不声明这个阈值 ⇒ 引擎也不发环。

    8min 出自"高龄有效步行窗口"，同一个数放在骑行/驾车档量的是完全不同的东西；
    留着它，屏幕上就会出现"骑行口径下 8 分钟覆盖 X km²"这种把步行文献贴到车速上的话。
    """
    assert get_caliber(mode).iso_compare_min is None
    assert "iso_compare" not in _compute(mode)


def test_assemble_passes_it_through_only_when_produced():
    """装配层只透传、不重算、也不补 null：切不出就整位缺席。

    钉的是形态而不是数据：写成 `"iso_compare": iso.get(...)` 在**有**环时的结果与现在逐字节
    相同，红不了；而它会把"缺席"发成一个 null，于是读侧每一处都得自己防，且那个 null 会
    冒充"量过了但没有环"（三态纪律）。所以这里按源码判。
    """
    import inspect

    from app.living_circle.assemble import assemble_living_circle

    body = inspect.getsource(assemble_living_circle)
    assert 'if iso.get("iso_compare")' in body, "透传不再是条件写入 ⇒ 缺席会被发成 null"
    assert '"iso_compare": iso.get' not in body
    # 装配层若自己再切环，必然要动几何原语（注释里提到那颗函数的名字不算）
    assert "trace_exterior" not in body and "mask_connect_center" not in body, \
        "装配层自己重切了一遍环 ⇒ 两条环的连通域判据迟早分叉"


def test_offline_report_carries_no_compare_ring():
    """离线估算件**不接**这条环：那个场是恒等式，再切一刀是"用估算对照估算"。"""
    from app.living_circle.data_source import CheckParams, OfflineDataSource

    rep = asyncio.run(OfflineDataSource().compute(
        CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734))))
    assert rep["data_origin"] == "offline"
    assert "iso_compare" not in rep, "离线发了对照环 ⇒ 屏幕会报「按文献阈值实测对照出 …」"
    assert _iso_compare_violations(rep) == []          # 缺席即合法，不因这条打死离线件


# ── ② 口径重建：新字段不许在 manifest 应用时被打回默认值 ──────

def test_manifest_application_touches_only_api_and_measured():
    """manifest 重建**必须带走全部字段**（这一格今天真漏了两次，且第一次没人发现）。

    判据的形状换了两次，第二版才对：
      · 第一版比 `DEFAULT_CALIBERS[mode]` ↔ `get_caliber(mode)` —— 恒真。前者正是被那圈
        重建**就地替换**过的对象，两边同一份，怎么漏抄都不会红（我自己写的
        "别在比同一份对象"那句警告，只防了 chunk 那一半，没防住这一半）。
      · 现在走**纯函数往返**：拿一份每个字段都填了哨兵值的 caliber 过一遍
        `_apply_manifest_caliber`，除 `api`/`measured` 外任何字段回落成 dataclass 默认值
        ⇒ 红。漏抄不必等到真数据出问题，一个哨兵就能撞出来。
    这样也不用 `importlib.reload` 去取"原始表"——重载会在 `sys.modules` 里留下第二份模块，
    同一次 pytest 会话里先导入的模块仍持有旧对象，那种"值相同、身份不同"的状态本身就是污染。
    """
    import dataclasses as _dc

    from app.living_circle.caliber import _apply_manifest_caliber

    base = get_caliber("walking")
    defaults = {f.name: f.default for f in _dc.fields(ReachCaliber)}
    sentinel = {
        "travel_mode": "walking",              # 必须是合法值：manifest 按它查表
        "speed_m_per_min": 91113.5,
        "detour_k": 9.111,
        "study_radius_m": 911135,
        "iso_minutes": (91, 191),
        "reach_full_min": 911.5,
        "api": base.api,                       # 这一半就是给 manifest 覆盖的
        "basis": "哨兵依据（不该被任何重建路径改写）",
        "measured": True,                      # 给 True，让"覆盖成 False"这一路也可观测
        "blind_radius_m": 911.5,
        "iso_compare_min": 91.5,
    }
    probe = ReachCaliber(**sentinel)
    out = _apply_manifest_caliber(probe, {"capacity": {"walking": {"measured": False,
                                                                  "chunk_max_origins": 100}}})
    for name, want in sentinel.items():
        if name in ("api", "measured"):
            continue
        got = getattr(out, name)
        assert got == want, (name, want, got, defaults.get(name))
        if name != "travel_mode":
            assert got != defaults[name] or want == defaults[name], (
                f"{name} 回落到 dataclass 默认值 ⇒ 这一格可能压根没被带走")
    assert out.measured is False and out.api is not None
    assert out.api.chunk == 100, "manifest 的实测 chunk 没生效 ⇒ 覆盖路径没跑，上面比的是空转"


def test_source_no_longer_rebuilds_the_caliber_by_hand():
    """结构判据：不许再出现手抄的 `ReachCaliber(...)` 重建（把纪律换成机制）。"""
    import inspect

    from app.living_circle import caliber as cal

    body = inspect.getsource(cal._apply_manifest_caliber)
    # 判"手抄清单"要认它的指纹（逐字段 `x=caliber.x`），不能认 `ReachCaliber(` 这个词 ——
    # 这个词现在只出现在解释为什么不用它的注释里，拿词当锚点会让判据去罚自己的说明。
    assert "travel_mode=caliber.travel_mode" not in body, \
        "又回到逐字段手抄 ⇒ 下一个新增字段仍会静默掉默认值"
    assert "replace(caliber" in body


# ── ③ 契约 B16 ─────────────────────────────────────────────

def _lc(cmp_zone: Any, iso_minutes=(5, 10, 15, 20), mode="walking") -> Dict[str, Any]:
    good = {"minutes": 8.0, "geojson": {"type": "Polygon",
                                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "area_km2": 0.5, "basis": ISO_COMPARE_BASIS, "claim": "caliber_comparison_only"}
    lc = {"data_origin": "live",
          "caliber": {"travel_mode": mode, "iso_minutes": list(iso_minutes)},
          "isochrones": [{"minutes": 5, "area_km2": 0.3}, {"minutes": 10, "area_km2": 1.2},
                         {"minutes": 15, "area_km2": 2.0}],
          "iso_compare": good if cmp_zone is _DEFAULT else cmp_zone}
    return lc


_DEFAULT = object()


def test_absent_compare_ring_is_legal():
    """缺席＝合法：骑行/驾车不声明、离线刻意不接、几何退化切不出 ⇒ 都不能因此不可展示。"""
    assert _iso_compare_violations({"caliber": {}, "isochrones": []}) == []


def test_good_block_adds_no_violation():
    assert _iso_compare_violations(_lc(_DEFAULT)) == []


@pytest.mark.parametrize("drop", ["minutes", "geojson", "area_km2", "basis", "claim"])
def test_incomplete_block_is_a_violation(drop):
    """五半缺一即违规：阈值、几何、面积、依据、断言边界是同一次发布。"""
    zone = _lc(_DEFAULT)["iso_compare"]
    zone.pop(drop)
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and drop in issues[0], issues


def test_capability_claim_is_rejected():
    """`claim` 写错（或被删换成能力断言）⇒ 红：这条尺不指认具体居民能走多远。"""
    zone = dict(_lc(_DEFAULT)["iso_compare"], claim="elderly_capability")
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and "caliber_comparison_only" in issues[0], issues


def test_basis_without_provenance_is_rejected():
    zone = dict(_lc(_DEFAULT)["iso_compare"], basis="8 分钟")
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and "依据" in issues[0], issues


def test_level_that_collides_with_the_four_zones_is_rejected():
    """把对照档写成 15min ⇒ 那就是一条**第五条等值线**，前端四档契约与图例都会误读。"""
    zone = dict(_lc(_DEFAULT)["iso_compare"], minutes=15.0)
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and ("四档" in issues[0] or "第五条" in issues[0]), issues


def test_level_not_matching_the_declared_caliber_is_rejected():
    zone = dict(_lc(_DEFAULT)["iso_compare"], minutes=6.0)
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and "口径表声明" in issues[0], issues


def test_riding_mode_cannot_carry_a_walking_provenance_ring():
    issues = _iso_compare_violations(_lc(_DEFAULT, mode="riding"))
    assert len(issues) == 1 and "只属于步行档" in issues[0], issues


@pytest.mark.parametrize("ring,expect", [
    ([[0, 0], [1, 0], [1, 1], [2, 2]], "未闭合"),           # 四点齐但首尾不接
    ([[0, 0], [1, 0], [0, 0]], "个点"),                     # 闭合却只有三点，撑不出边界
])
def test_degenerate_ring_is_rejected(ring, expect):
    zone = _lc(_DEFAULT)["iso_compare"]
    zone["geojson"]["coordinates"][0] = ring
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and expect in issues[0], issues


@pytest.mark.parametrize("area,needle", [(0.0, "≤ 0"), (2.5, "阈值更小却圈更大"), (0.1, "阈值更大却圈更小")])
def test_area_must_sit_between_the_bracketing_zones(area, needle):
    """同一条场切出来的环，分钟居中而面积越界 ⇒ 那条环不是这个场切的。"""
    zone = dict(_lc(_DEFAULT)["iso_compare"], area_km2=area)
    issues = _iso_compare_violations(_lc(zone))
    assert len(issues) == 1 and needle in issues[0], issues


# ── ④ 名册 ─────────────────────────────────────────────────

def test_compare_ring_is_registered_as_a_block():
    """登记的是块本身：浅一层到 `iso_compare.minutes` 会让"ref 指向的键真在产出对象里"恒绿。"""
    from app.living_circle import caliber_index

    view = caliber_index.view("report::iso_compare")
    assert view is not None, "iso_compare 发射了却没登记 ⇒ prose 提到就撞词表闸"
    assert view.value == "living_circle.iso_compare", view.value
