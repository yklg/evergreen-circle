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
from app.living_circle.isochrone import _flag_of, reach_flags
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


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_blindspot_judged_coverage_disclosed(path):
    """T-BE-15 · 判盲覆盖度必须可审（阶段 −1.5 后端半）。

    为什么需要：`cells_judged=9 / cells_inside=72` 说明**只有 12.5% 的可达区被判定过**，
    但 UI 只写「服务盲区 0 处」，读起来像「全圈都没问题」。`cells_unknown` 是设计好的
    可观测性出口（`blindspot.py:111`、`scope.py:136`），**出口存在不等于被使用**——
    本用例锁住「后端确实把三个数写进报告了」，前端披露断言见
    `frontend/src/__tests__/livingCircleContract.test.ts`（同一判据两端各锁一次）。

    说明：本仓两份 fixture 的 `cells_unknown` 均 > 0（kaili 63/72、jinsong 90/99），
    因此前端披露路径有真实输入、不是空转；此处**不**断言 unknown 的具体占比，
    以免将来修好判盲半径（unknown→0，见计划 §9）时误报。
    """
    lc = _load(path)
    cal = lc.get("caliber") or {}
    inside = cal.get("cells_inside")
    judged = cal.get("cells_judged")
    unknown = cal.get("cells_unknown")
    assert inside is not None, f"{path.name}: caliber 缺 cells_inside（判盲覆盖率无从计算）"
    assert judged is not None, f"{path.name}: caliber 缺 cells_judged"
    assert unknown is not None, (
        f"{path.name}: caliber 缺 cells_unknown —— 「0 处盲区」将无法解读"
        "（可能是全扫完真没有，也可能是大半没判）"
    )
    assert judged + unknown == inside, (
        f"{path.name}: 判盲分账不闭合 {judged}+{unknown}={judged + unknown} ≠ {inside}"
    )
    assert 0 <= judged <= inside, f"{path.name}: cells_judged={judged} 越界 [0,{inside}]"
    # 盲区数不可能超过「判定过的格数」——上界由可判定面决定，不由扫描面决定
    n_bs = len(lc.get("blindspots") or [])
    assert n_bs <= judged, f"{path.name}: 盲区数 {n_bs} > 可判定格数 {judged}"


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
            minutes = dist / 80.0
            is_timed, is_in_reach = _flag_of(minutes)
            points.append(
                {
                    "lng": lng, "lat": lat, "minutes": minutes,
                    "timed": is_timed, "in_reach": is_in_reach,
                }
            )
    flags = reach_flags(points)
    return {
        "isochrones": rings, "sampling": {"points": points},
        "sample_count": len(points),
        "timed_count": flags.timed_count, "in_reach_count": flags.in_reach_count,
    }


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


def test_assemble_poi_conservation_holds_end_to_end():
    """阶段 1 核心不变量（端到端）：``sum(categories[].in_circle) == len(points)``。

    合成输入每类 2 个圈内（±300m）+ 2 个圈外（±3000m）⇒ 采集口径 32、可达口径 16。
    两条口径**必须各自成立且互不污染**：`total` 保留圈外（32），`in_circle` = 图上点数（16）。

    为什么单独端到端测一遍（单测已在 `test_poi_conservation.py`）：装配层还有
    「`stats` 先被 IDW 回填、后被派生收敛、再交给 compute_scores」的时序耦合，
    只在 `build_poi_block` 单元里测是看不到这条链的。pytest 下 strict 口径生效
    ⇒ 本用例变红即装配层真的破了守恒。
    """
    lc = _build_report(triads_near_center=False)
    poi = lc["poi"]
    declared = sum(int(c["in_circle"]) for c in poi["categories"])
    assert declared == len(poi["points"]) == int(poi["in_circle"])
    assert poi["total"] > poi["in_circle"], "夹具须含圈外点，否则「两条口径之别」测不出来"
    assert poi["truncated"] == {"cap_per_cat": 200, "dropped": 0, "categories": []}
    assert poi["conservation"] == {
        "ok": True,
        "declared_in_circle": declared,
        "actual_points": declared,
    }


def test_assemble_scoring_sees_derived_in_circle():
    """派生收敛必须发生在 `compute_scores` **之前**（否则评分仍按截断前的覆盖度算）。

    判据：每个类别的 ``coverage`` 与其**派生后**的 ``in_circle`` 自洽 ——
    ``coverage == min(1, in_circle / ideal_circle)``。若时序颠倒，
    ``in_circle`` 会被覆盖而 ``coverage`` 保持旧值，二者立刻对不上。
    """
    from app.living_circle.category_rule import CATEGORY_RULES

    lc = _build_report(triads_near_center=False)
    for c in lc["poi"]["categories"]:
        ideal = int(CATEGORY_RULES[c["category"]]["ideal_circle"])
        assert c["coverage"] == pytest.approx(min(1.0, c["in_circle"] / ideal), abs=1e-4), c


# ── 副标题：口径 + 分隔符（读者会照抄这两个东西） ──────────────────────


def _all_text(node: Any) -> str:
    """把 Report 里所有字符串拼成一个平面文本（用于全文断言，避免逐字段找）。"""
    if isinstance(node, str):
        return node + "\n"
    if isinstance(node, dict):
        return "".join(_all_text(v) for v in node.values())
    if isinstance(node, (list, tuple)):
        return "".join(_all_text(v) for v in node)
    return ""


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_narrative_reach_count_is_not_silently_zero(path):
    """T-BE-13 · 叙述文案的「可达」数必须等于采样汇总数，且**不得静默为 0**。

    为什么必须专门锁：`diagnosis_templates` 原有 5 处
    ``sum(1 for p in points if p.get("reachable"))``。字段更名为 ``timed``/``in_reach`` 后，
    ``dict.get`` 遇到旧名**不报错、只返回 None** ⇒ 文案静默变成「0/1049 个采样点可达」——
    全量测试当时没有任何一条会失败（阶段 −1 实测，804 passed 全绿）。
    这类「改名后靠 .get 静默归零」是本项目最贵的一类缺陷，故把等式钉成契约。
    """
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _load(path)
    s = lc["sampling"]
    n = len(s["points"])
    in_reach = int(s["in_reach_count"])
    assert in_reach > 0, f"{path.name}: 夹具的 in_reach_count={in_reach}，断言将失去判别力"

    text = _all_text(assemble_report(lc, "lc-test", "syn", ""))
    assert f"{in_reach}/{n} 个采样点圈内可达" in text, (
        f"{path.name}: 叙述文案未出现真实可达数 {in_reach}/{n}\n{text[:1200]}"
    )
    assert f"0/{n} 个采样点" not in text, (
        f"{path.name}: 叙述文案出现 0/{n} —— 汇总数被静默归零（读到了已废字段名？）"
    )


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


def test_subtitle_count_equals_rendered_point_count():
    """阶段 3.3 · 副标题「共 N 处设施」必须 == **图上实际能数出来的点数**（``len(poi.points)``）。

    `in_circle` 与 `len(points)` 在阶段 1 之后恒等，但把「读者在图上数得出来的那个数」
    直接钉进文案契约，才是用户最初的诉求（「地图上看到的点必须能追到报告里的数字」）：
    只钉 `in_circle` 的话，一旦两个字段**一起**算错，文案与图会一起漂移而无人发现。
    """
    from app.core.pipeline.diagnosis_templates import assemble_report

    lc = _build_report(triads_near_center=False)
    rendered = len(lc["poi"]["points"])
    assert rendered > 0, "夹具未产出点位，断言将失去判别力"
    sub = assemble_report(lc, "lc-test", "syn", "")["subtitle"]
    assert f"共 {rendered} 处设施" in sub, sub


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


# ── 阶段 2.5 · POI 指标文案（`采集 N · 圈内 M · 已展示 K`）────────────────────
# 为什么要专门锁：旧文案 `N 个（圈内 M）` 只讲两个数，而「图上到底画了几个点」是第三个、
# 也是读者唯一能**亲眼数出来**的数。三者不对账时，用户原始诉求（点必须能追到数字）就不成立。
# ⚠️ 本组与前端 `src/lib/__tests__/livingCirclePoiRender.test.ts` 断言**同一批字面量**
#    （`采集 217 · 圈内 98 · 已展示 98` / `采集 175 · 圈内 104 · 已展示 104`）——
#    文案在 Py/TS 各有一份实现，靠「同一份夹具 + 同一串期望值」把两端口径钉在一起。


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_poi_metric_label_three_segments_match_data(path):
    """三段必须各来自自己的来源：采集=total / 圈内=Σcategories.in_circle / 已展示=len(points)。"""
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    lc = _load(path)
    poi = lc["poi"]
    declared = sum(int(c["in_circle"]) for c in poi["categories"])
    label = poi_metric_label(poi)
    assert label == f"采集 {int(poi['total'])} · 圈内 {declared} · 已展示 {len(poi['points'])}", label
    assert "另有" not in label, f"{path.name}: 未截断却出现了截断披露 → {label}"


def test_poi_metric_label_pins_cross_language_literals():
    """与前端测试断言**同一串**字面量 —— 两端口径漂移时必有一侧变红。"""
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    kaili = _load(FIXTURES / "kaili.json")
    jinsong = _load(FIXTURES / "beijing-jinsong.json")
    assert poi_metric_label(kaili["poi"]) == "采集 217 · 圈内 98 · 已展示 98"
    assert poi_metric_label(jinsong["poi"]) == "采集 175 · 圈内 104 · 已展示 104"


def test_poi_metric_label_discloses_truncation_with_category_detail():
    """真的截断过 ⇒ 必须出现第四段，且带类别明细与上限（静默截断 = 本计划要消灭的缺陷）。"""
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    label = poi_metric_label(
        {
            "categories": [{"category": "shopping", "in_circle": 25}],
            "total": 500,
            "in_circle": 25,
            "points": [{}] * 25,
            "truncated": {
                "cap_per_cat": 200,
                "dropped": 6,
                "categories": [{"category": "shopping", "kept": 25, "dropped": 6}],
            },
        }
    )
    assert label == "采集 500 · 圈内 25 · 已展示 25 · 另有 6 处未展示（shopping 6，每类上限 200）", label


def test_poi_metric_label_ignores_redundant_in_circle_field():
    """冗余的 ``poi.in_circle`` 谎报时必须无视 —— 一律重算 ``categories``。

    `total`/`in_circle` 是**派生冗余字段**（阶段 1 定稿：`points` 才是唯一真身）。
    文案若读它们，就等于把「自我声明的数字」当真，两个数各算各的老毛病会在文案层复发。
    """
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    label = poi_metric_label(
        {
            "categories": [{"category": "shopping", "in_circle": 25}],
            "total": 500,
            "in_circle": 999,  # ← 谎报
            "points": [{}] * 25,
            "truncated": {"cap_per_cat": 200, "dropped": 0, "categories": []},
        }
    )
    assert label == "采集 500 · 圈内 25 · 已展示 25", label


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_overview_takeaway_carries_the_same_label(path):
    """概览章结论必须带上与 `poi_metric_label` **逐字一致**的三段式文案。

    ⚠️ 这里**同时**断言「函数产物」与「由夹具算出的字面量」，而不是只断言前者：
    只断言 `f"设施 {poi_metric_label(poi)}" in text` 的话，一旦有人把函数本身改回旧文案，
    等号两边**一起变**、测试照样绿（负对照实测：模板接线版 2/2 全绿，只有字面量版红）。
    判据必须锚在**不随实现移动的常量**上，否则它校验的是「自己等于自己」。
    """
    from app.core.pipeline.diagnosis_templates import assemble_report, poi_metric_label

    lc = _load(path)
    poi = lc["poi"]
    declared = sum(int(c["in_circle"]) for c in poi["categories"])
    literal = f"设施 采集 {int(poi['total'])} · 圈内 {declared} · 已展示 {len(poi['points'])}"

    text = _all_text(assemble_report(lc, "lc-test", "syn", ""))
    assert literal in text, text[:1500]
    assert f"设施 {poi_metric_label(poi)}" in text, text[:1500]
    # 旧文案形态不得残留（注意：`设施 总量` 与 `设施总量` 两种写法都要拦 ——
    # 只拦不带空格的那种时，负对照实测漏掉过一次）
    assert "设施总量" not in text and "设施 总量" not in text, "旧文案「设施总量 N 处（圈内 M）」残留"
    assert "个（圈内" not in text, "旧文案「N 个（圈内 M）」残留"
