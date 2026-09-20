"""阶段 0c · 报告几何不变量（先红后绿）。

这一组断言是 Q1（灰方框 = 整张判定网格）、Q2（88% 点位在圈外）、
P6（静默空壳报告）的**统一判据**。它们此前全部缺失：
既有防线只查「顶层字段是否齐全」，所以一份 `isochrones=[]`、`blindspots=29km²`
的**空壳报告逐条通过**。

不变量（对每份夹具 + 对 live 组装路径的合成输入各断言一遍）：

====================  ====================================  ==================
不变量                 含义                                  修复前实测
====================  ====================================  ==================
isochrones 非空        没有等时圈就没有「可达区」可言          迤栖村 = 0 ❌
面积随 minutes 递增     圈族自洽                              ✅
盲区 ⊆ reach 外接圆      判定网格必须限定在可达区内              2900m vs 1249m ❌
Σ盲区面积 ≤ reach×2     盲区不能比可达区还大                    29.12 vs 3.23 ❌
poi.points 全 in_reach  圈外点不展示、不进报告                  14 条中大量圈外 ❌
collect ≥ reach 外接圆   采集区必须覆盖判定所需的最远点（D2 取等） 未声明 ❌
====================  ====================================  ==================

跑红纪律：本文件在当前（未修复）代码上必须出现红色。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.living_circle.geo_utils import haversine_m, ring_area_km2, to_local_xy
from app.living_circle.poi import CATEGORY_DEFS, TRIAD_KEYWORDS

FIXTURES = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))

# 外接半径的容差：环是多边形逼近，其顶点已在圆上，只留浮点误差余量
TOL = 1.02


def _load(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _reach_zone(lc: Dict[str, Any]) -> Dict[str, Any]:
    """按**口径**取可达区环，而不是按位置取 ``[-1]``。

    口径唯一来源：``caliber.reach_full_min``（缺字段时退化为 iso_minutes 的最大值，
    仅为兼容旧夹具，新报告必须带该字段）。
    """
    iso = lc["isochrones"]
    assert iso, "isochrones 为空 ⇒ 没有可达区（P6 静默空壳报告的判据）"
    target = (lc.get("caliber") or {}).get("reach_full_min")
    if target is None:
        target = max(z["minutes"] for z in iso)
    matches = [z for z in iso if z["minutes"] == target]
    assert matches, f"等时圈族里找不到 minutes=={target} 的可达区环（口径与数据不一致）"
    return matches[0]


def _ring(zone: Dict[str, Any]) -> List[Tuple[float, float]]:
    return [(a, b) for a, b in zone["geojson"]["coordinates"][0]]


def _circumradius(center: Tuple[float, float], ring) -> float:
    return max(haversine_m(center, p) for p in ring)


def _max_coord(center: Tuple[float, float], ring) -> float:
    """环上所有点相对中心的最大单轴偏移（米）——「bbox 是否越出可达区」的度量。"""
    xs, ys = [], []
    for lng, lat in ring:
        x, y = to_local_xy(center, lng, lat)
        xs.append(abs(x))
        ys.append(abs(y))
    return max(max(xs), max(ys))


def _collect_radius(lc: Dict[str, Any]) -> float:
    cal = lc.get("caliber") or {}
    assert "collect_radius_m" in cal, (
        "报告未声明采集半径 `caliber.collect_radius_m` —— "
        "采集区与可达区的关系必须可举证，否则「圈外有没有数据」无从判定"
    )
    return float(cal["collect_radius_m"])


# ── A. 夹具（冻结快照）───────────────────────────────────────
@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_isochrones_non_empty_and_monotonic(path):
    lc = _load(path)
    assert lc["isochrones"], f"{path.name}: isochrones 为空"
    areas = [z["area_km2"] for z in sorted(lc["isochrones"], key=lambda z: z["minutes"])]
    assert areas == sorted(areas), f"{path.name}: 等时圈面积未随 minutes 单调递增 {areas}"
    assert all(a > 0 for a in areas), f"{path.name}: 存在面积为 0 的圈 {areas}"


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_blindspots_within_reach(path):
    """Q1 核心判据：盲区必须落在可达区内（判定网格不得越过可达区）。"""
    lc = _load(path)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    cr = _circumradius(center, _ring(reach))
    for b in lc["blindspots"]:
        ring = [(a, c) for a, c in b["polygon"]["coordinates"][0]]
        got = _max_coord(center, ring)
        assert got <= cr * TOL, (
            f"{path.name}/{b['id']}: 盲区最远点 {got:.0f}m 越出可达区外接圆 {cr:.0f}m —— "
            f"判定网格跑到可达区外了（「没查到」被当成「没有」）"
        )


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_blindspot_total_area_bounded(path):
    lc = _load(path)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    reach_area = ring_area_km2(_ring(reach), center)
    total = 0.0
    for b in lc["blindspots"]:
        total += ring_area_km2([(a, c) for a, c in b["polygon"]["coordinates"][0]], center)
    assert total <= reach_area * 2, (
        f"{path.name}: 盲区总面积 {total:.3f}km² 超过可达区面积 {reach_area:.3f}km² 的 2 倍"
    )


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_poi_points_all_in_reach(path):
    """Q2 核心判据：送到前端的点位必须全部在可达区内（圈外不展示、不进报告）。"""
    lc = _load(path)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    cr = _circumradius(center, _ring(reach))
    for pt in lc["poi"]["points"]:
        assert pt["in_circle"] is True, (
            f"{path.name}: 点位 {pt.get('name')!r} in_circle=False 却出现在报告点位里"
        )
        lnglat = pt.get("lnglat") or [pt.get("lng"), pt.get("lat")]
        dist = haversine_m(center, (lnglat[0], lnglat[1]))
        assert dist <= cr * TOL, (
            f"{path.name}: 点位 {pt.get('name')!r} 距中心 {dist:.0f}m，越出可达区外接圆 {cr:.0f}m"
        )


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_collect_covers_reach(path):
    """采集半径必须 ≥ 可达区外接圆（否则可达区内的判盲数据必然缺失）。"""
    lc = _load(path)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    cr = _circumradius(center, _ring(reach))
    collect = _collect_radius(lc)
    assert collect >= cr * 0.999, (
        f"{path.name}: 采集半径 {collect:.0f}m < 可达区外接圆 {cr:.0f}m —— 可达区内存在无数据格"
    )


# ── B. live 组装路径（合成输入，不依赖网络）────────────────────
def _synthetic_iso(center: Tuple[float, float]):
    """同心方环 5/10/15/20min（半径 200/400/700/1000m）+ 5×5 采样点。"""
    from app.living_circle.geo_utils import xy_to_lnglat

    rings = []
    for minutes, half in ((5, 200.0), (10, 400.0), (15, 700.0), (20, 1000.0)):
        corners = [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]
        ring = [xy_to_lnglat(center, x, y) for x, y in corners]
        rings.append(
            {
                "minutes": minutes,
                "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
                "area_km2": ring_area_km2(ring, center),
            }
        )
    points = []
    for i in range(5):
        for j in range(5):
            x = (i - 2) * 750.0
            y = (j - 2) * 750.0
            lng, lat = xy_to_lnglat(center, x, y)
            dist = (x * x + y * y) ** 0.5
            points.append(
                {"lng": lng, "lat": lat, "minutes": dist / 80.0, "reachable": True}
            )
    return {"isochrones": rings, "sampling": {"points": points}, "sample_count": len(points), "reachable_count": len(points)}


def _build_report(triads_near_center: bool):
    """调用**唯一组装实现** ``assemble_living_circle``（合成输入，不依赖网络）。

    ``triads_near_center=True`` → 三要素点全在中心 ⇒ 不应产盲区；
    ``False`` → 三要素点全在可达区外（2.2km 处）⇒ 可达区内应整片判盲，
    但盲区**必须**被限定在可达区内。

    另注入「圈内 + 圈外」各两个 POI：让 ``poi.points`` 的圈外过滤断言**有判别力**
    （此前 per_category 全空 ⇒ 该断言恒真，等于没测）。
    """
    from app.living_circle.assemble import assemble_living_circle
    from app.living_circle.caliber import get_caliber
    from app.living_circle.data_source import CheckParams
    from app.living_circle.geo_utils import xy_to_lnglat
    from app.living_circle.scope import SpatialScope

    center = (107.9758, 26.5734)
    off = 0.0 if triads_near_center else 2200.0

    def _pt(x: float, y: float, name: str):
        lng, lat = xy_to_lnglat(center, x, y)
        return {"lng": lng, "lat": lat, "name": name}

    # 圈内（±300m，20min 方环是 ±1000m）+ 圈外（±3000m，远超可达区）
    per_category: Dict[str, list] = {
        cat: [
            _pt(300.0, 0.0, f"{cat}-in-1"),
            _pt(0.0, -300.0, f"{cat}-in-2"),
            _pt(3000.0, 0.0, f"{cat}-out-1"),
            _pt(0.0, -3000.0, f"{cat}-out-2"),
        ]
        for cat in CATEGORY_DEFS
    }
    triads: Dict[str, list] = {}
    for key in TRIAD_KEYWORDS:
        lng, lat = xy_to_lnglat(center, off, 0.0)
        triads[key] = [{"lng": lng, "lat": lat, "name": f"{key}-far"}]

    check = CheckParams(
        scene_name="合成场景",
        city="测试",
        address="",
        center=center,
        study_radius_m=2500.0,
        sample_profile="standard",
        travel_mode="walking",
    )
    iso = _synthetic_iso(center)
    scope = SpatialScope.from_iso(get_caliber("walking"), center, check.study_radius_m, iso)
    scope.invariant()
    return assemble_living_circle(check, iso, per_category, triads, scope)


def test_assemble_blindspots_confined_to_reach():
    """Q1 回归护栏：可达区外无数据 ⇒ 盲区仍必须被可达区裁住（不是整张判定网格）。"""
    lc = _build_report(triads_near_center=False)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    cr = _circumradius(center, _ring(reach))
    assert lc["blindspots"], "三要素全在可达区外，可达区内应当判出盲区"
    for b in lc["blindspots"]:
        ring = [(a, c) for a, c in b["polygon"]["coordinates"][0]]
        got = _max_coord(center, ring)
        assert got <= cr * TOL, (
            f"盲区 {b['id']} 最远点 {got:.0f}m 越出可达区外接圆 {cr:.0f}m "
            f"（判定网格未按可达区限定 —— Q1 本体）"
        )


def test_assemble_blindspot_area_bounded():
    lc = _build_report(triads_near_center=False)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    reach_area = ring_area_km2(_ring(reach), center)
    total = sum(
        ring_area_km2([(a, c) for a, c in b["polygon"]["coordinates"][0]], center)
        for b in lc["blindspots"]
    )
    assert total <= reach_area * 2, f"盲区总面积 {total:.3f}km² 超过可达区 {reach_area:.3f}km² 的 2 倍"


def test_assemble_no_blindspot_when_triads_present():
    """反例护栏：三要素点就在中心 ⇒ 不得判盲（防止「一律判盲」的假修复）。"""
    lc = _build_report(triads_near_center=True)
    assert lc["blindspots"] == [], f"三要素齐备时不应产盲区，实际 {len(lc['blindspots'])} 处"


def test_assemble_poi_points_all_in_reach():
    lc = _build_report(triads_near_center=False)
    center = tuple(lc["scene"]["center"])
    reach = _reach_zone(lc)
    cr = _circumradius(center, _ring(reach))
    for pt in lc["poi"]["points"]:
        assert pt["in_circle"] is True
        lnglat = pt.get("lnglat") or [pt.get("lng"), pt.get("lat")]
        assert haversine_m(center, (lnglat[0], lnglat[1])) <= cr * TOL


def test_assemble_declares_collect_and_reach_caliber():
    lc = _build_report(triads_near_center=False)
    cal = lc.get("caliber") or {}
    assert "reach_full_min" in cal, "报告口径缺少 reach_full_min（可达区无法被唯一确定）"
    center = tuple(lc["scene"]["center"])
    cr = _circumradius(center, _ring(_reach_zone(lc)))
    assert cal["collect_radius_m"] >= cr * 0.999


# ── 副标题：口径 + 分隔符（读者会照抄这两个东西） ──────────────────────


def test_subtitle_counts_in_circle_not_total():
    """「共 N 处设施」必须数**可达区内**（``poi.in_circle``），不是采集区内（``poi.total``）。

    旧实现引 ``poi.total``，同一份报告里「POI 采集（圈内 N）」与副标题会互相对不上 ——
    读者据此高估本区设施密度。故这里同时断言"该出现"和"不该出现"两个数。
    """
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    in_circle = int(lc["poi"]["in_circle"])
    total = int(lc["poi"]["total"])
    assert in_circle != total, "夹具未构造出 in_circle ≠ total，断言将失去判别力"

    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert f"共 {in_circle} 处设施" in sub, sub
    assert f"共 {total} 处设施" not in sub, sub


def test_subtitle_separator_spacing_is_intact():
    """分隔符的**空格**也要钉住：f-string 跨行拼接最容易吞掉 ``· `` 前的空格。

    实测踩过：把副标题拆成多行 f-string 后产出「1 处服务盲区· 共 53 处设施」——
    数字全对、口径全对，只有空格没了。故这里用一条正则把**整段版式**钉死，
    而不是只断言数字（只断言数字的话，这类缺陷会静默通过）。
    """
    import re

    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    n = len(lc["blindspots"])
    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert re.search(rf"综合 [\d.]+ 分（[优中良差]）· {n} 处服务盲区 · 共 \d+ 处设施（可达区内）$", sub), sub


def test_subtitle_has_no_dangling_separator_when_address_empty():
    """``address`` 为空时不得产出「城市 · ｜综合 …」这种悬空分隔符。"""
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    assert lc["scene"]["city"] and not lc["scene"]["address"], "夹具前提：有城市、无地址"

    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert " · ｜" not in sub, f"出现悬空分隔符：{sub}"
    assert sub.startswith("测试｜"), f"前缀应只保留非空片段：{sub}"


def test_subtitle_omits_whole_prefix_when_location_unknown():
    """地点全未知时，连 ``｜`` 一起省略 —— 否则会留下一个孤立的分隔符开头。"""
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    lc["scene"]["city"] = ""
    lc["scene"]["address"] = ""

    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert not sub.startswith("｜"), f"孤立分隔符开头：{sub}"
    assert sub.startswith("综合 "), sub


def test_subtitle_keeps_address_when_present():
    """反例护栏：有地址时必须照常保留（防止"一律省略前缀"的假修复）。"""
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    lc["scene"]["address"] = "西门街道老街片区"

    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert sub.startswith("测试 · 西门街道老街片区｜综合 "), sub
