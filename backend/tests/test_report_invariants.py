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
    """T-BE-15 · 判盲覆盖度必须可审，且**低覆盖率必须留下代价**（阶段 −1.5 → 本轮 D-3 升级）。

    为什么需要：`cells_judged=9 / cells_inside=72` 说明**只有 12.5% 的可达区被判定过**，
    但 UI 只写「服务盲区 0 处」，读起来像「全圈都没问题」。`cells_unknown` 是设计好的
    可观测性出口（`blindspot.py:111`、`scope.py:136`），**出口存在不等于被使用**——
    本用例锁住「后端确实把三个数写进报告了」，前端披露断言见
    `frontend/src/__tests__/livingCircleContract.test.ts`（同一判据两端各锁一次）。

    本轮升级拆掉了旧版那句护身符（「此处**不**断言 unknown 的具体占比，以免将来修好
    判盲半径时误报」）。它当时挡住的正是本次要修的缺陷：只披露数字、不追究数字太低，
    等于允许「判不了」继续冒充「没有盲区」。现在低覆盖率报告必须落在三条出路之一：
      - 判定面完整（share ≥ 1）——本用例不适用；
      - 打了折扣：`scores.confidence == "limited"`（新口径产物，扣分按覆盖率外推）；
      - 没打折扣（口径升级前冻结的快照）：**必须已被复用门拦下**，不得再被当作当前答案复用。
    将来夹具被 `scripts/snapshot_live.py` 重刷后，出路自动收敛到前两条；第三条同时把
    「存量报告不可复用」（D-4）钉在这里，而不是只靠 `reuse_policy` 的单测自证。
    """
    from app.living_circle.report_contract import reuse_policy
    from app.living_circle.scoring import JUDGE_SHARE_FLOOR

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

    share = (judged / inside) if inside else 0.0
    if share >= 1.0 - 1e-6:
        return
    conf = (lc.get("scores") or {}).get("confidence")
    if conf is not None:
        assert conf == "limited", (
            f"{path.name}: 判定覆盖率 {share:.1%} < 1 却自称 {conf!r} —— "
            "「没判的格」正在冒充「没问题」，D-3 的折扣被旁路了"
        )
    else:
        reusable, why = reuse_policy(lc)
        assert not reusable, (
            f"{path.name}: 覆盖率 {share:.1%}（< 外推下限 {JUDGE_SHARE_FLOOR:.0%}）"
            f"且无置信度标注，却仍被判为可复用 —— 旧口径的乐观分数会被继续引用"
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


def _build_report(triads_near_center: bool, evidence_frontier_m: float | Dict[str, float] | None = None):
    """调用**唯一组装实现** ``assemble_living_circle``（合成输入，不依赖网络）。

    ``triads_near_center=True`` → 三要素**按 ≤1km 间距铺满可达区** ⇒ 不应产盲区
    （反「一律判盲」假修复的护栏）；
    ``False`` → 三要素点全在可达区外（2.2km 处）⇒ 可达区内应整片判盲，
    但盲区**必须**被限定在可达区内。

    ``evidence_frontier_m`` → 把必达要素的**实测证据边界**绑到给定值（模拟「一页查不完」
    的薄证据）。传 ``float`` = 三类同值；传 ``dict`` = 逐类各异（合并算子的判别前提）。
    缺省 ``None`` 表示不绑定 ⇒ `SpatialScope` 退回几何口径（判满可达区）。
    给了它，可达区外沿就会落进 `cells_unknown` ⇒ 这才是活管线在凯里的真实形状。

    另注入「圈内 + 圈外」各两个 POI：让 ``poi.points`` 的圈外过滤断言**有判别力**
    （此前 per_category 全空 ⇒ 该断言恒真，等于没测）。
    """
    from app.living_circle.assemble import assemble_living_circle
    from app.living_circle.caliber import get_caliber
    from app.living_circle.data_source import CheckParams
    from app.living_circle.geo_utils import xy_to_lnglat
    from app.living_circle.scope import SpatialScope

    center = (107.9758, 26.5734)

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
    # 三要素布点。
    #   True  ⇒ 3×3 格网，间距 750m < 1000/√2 ⇒ 方环内**任意一点**的 1km 圆都至少盖到
    #           一个同类点 ⇒ 零盲区。这是「反一律判盲」护栏的**本意**。
    #           旧实现只放中心 1 个点，在证据余量修好之前那是等价的（只有中心 5 格参与
    #           判定）；余量修正后可达区全境可判 ⇒ 单点会**诚实地**判出外围盲区。
    #   False ⇒ 全放到 2.2km 外（可达区之外）⇒ 区内应判盲。
    _COVER = [(x, y) for x in (-750.0, 0.0, 750.0) for y in (-750.0, 0.0, 750.0)]
    triads: Dict[str, list] = {}
    for key in TRIAD_KEYWORDS:
        if triads_near_center:
            triads[key] = [_pt(x, y, f"{key}-cover-{i}") for i, (x, y) in enumerate(_COVER)]
        else:
            triads[key] = [_pt(2200.0, 0.0, f"{key}-far")]

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
    if evidence_frontier_m is not None:
        if isinstance(evidence_frontier_m, dict):
            fr = {k: float(v) for k, v in evidence_frontier_m.items()}
        else:
            fr = {k: float(evidence_frontier_m) for k in TRIAD_KEYWORDS}
        scope = scope.with_evidence(fr, complete=False)
    scope.invariant()
    # 片 1a：判定不住在组装层了 —— 组装层吃的是编排层交下来的 `Judgement`。
    # 这里补的一行正是线上那一行（`data_source.live_forensic_steps`），入参逐字相同。
    from app.living_circle.blindspot import judge_once

    j = judge_once(center, scope, triads, prefix=check.scene_name)
    return assemble_living_circle(check, iso, per_category, triads, scope, judgement=j)


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


def test_g1_out_of_polygon_point_must_not_set_min_minutes():
    """G1 · 「圈内 0 处」的类别不得同时报「最近 X 分钟」。

    2026-09-27 重刷劲松时现形：``elderly total=2 / in_circle=0 / min_minutes=19.9``。
    泄漏 A 的第一版修复只把 `to_stats` 的最近点改成只看 `in_circle`，但
    `backfill_nearest_minutes` 走的是 `field_fn`，而 `field_fn` 当时**只卡时间** ——
    IDW 是平滑插值场，20min 等时圈是按同一场描边+简化出来的，凹口处必然出现
    「场值 ≤ 20min 却在多边形外」的点 ⇒ 同一份报告里两套「可达」判据互相打脸。

    样本刻意做成**能分岔**的：方环半边 1000m，点放在 (1200, 0) ⇒ 多边形外 200m，
    但径向 IDW = 1200/80 = 15min ≤ 20 ⇒ 只看时间就会误判它可达。
    """
    from app.living_circle.assemble import assemble_living_circle
    from app.living_circle.caliber import get_caliber
    from app.living_circle.data_source import CheckParams
    from app.living_circle.geo_utils import xy_to_lnglat
    from app.living_circle.scope import SpatialScope

    center = (107.9758, 26.5734)

    def _pt(x: float, y: float, name: str):
        lng, lat = xy_to_lnglat(center, x, y)
        return {"lng": lng, "lat": lat, "name": name}

    per_category: Dict[str, list] = {
        cat: [_pt(300.0, 0.0, f"{cat}-in")] for cat in CATEGORY_DEFS
    }
    per_category["elderly"] = [_pt(1200.0, 0.0, "elderly-出域但时间够")]   # 唯一判据点
    triads: Dict[str, list] = {k: [_pt(0.0, 0.0, f"{k}-c")] for k in TRIAD_KEYWORDS}

    check = CheckParams(scene_name="合成场景", city="测试", address="", center=center,
                        study_radius_m=2500.0, sample_profile="standard", travel_mode="walking")
    iso = _synthetic_iso(center)
    scope = SpatialScope.from_iso(get_caliber("walking"), center, check.study_radius_m, iso)
    from app.living_circle.blindspot import judge_once

    lc = assemble_living_circle(
        check, iso, per_category, triads, scope,
        judgement=judge_once(center, scope, triads, prefix=check.scene_name),
    )

    cats = {c["category"]: c for c in lc["poi"]["categories"]}
    assert cats["elderly"]["in_circle"] == 0, "前提：该点确实在可达区外"
    assert cats["elderly"]["min_minutes"] is None, (
        "多边形外 200m 的点被 IDW 判成 15min ⇒ 「圈内 0 处」与「最近 15min」并存（G1 复发）")
    assert cats["elderly"].get("nearest_name") is None or cats["elderly"].get("nearest_name") == ""
    assert cats["market"]["min_minutes"] is not None, "对照组：圈内点必须照常给出最近耗时"


@pytest.mark.xfail(strict=True, reason=(
    "出厂劲松快照是 G1 修复**之前**跑的：`elderly in_circle=0` 仍带 `min_minutes=19.9`。"
    "代码已修（见上一条用例），下一次重刷（ev-2 代际）会把它变成 None —— 那时本用例转 XPASS 而"
    "报错，就是提醒你把这条 xfail 删掉、并把 `test_residential_category_baseline.py` 里"
    "elderly 那一行的注释一并清掉。禁止改成 skip 或放宽断言。"))
def test_g1_residual_in_shipped_jinsong_snapshot():
    """把「出厂快照仍带 G1 残留」这一事实钉成机器可查的账，而不是散在注释里。"""
    jinsong = _load(FIXTURES / "beijing-jinsong.json")
    leaks = [
        (c["category"], c["in_circle"], c.get("min_minutes"))
        for c in jinsong["poi"]["categories"]
        if int(c["in_circle"]) == 0 and c.get("min_minutes") is not None
    ]
    assert not leaks, f"圈内 0 处却报出最近耗时：{leaks}"


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


def test_assemble_thin_evidence_discounts_the_score():
    """薄证据必须**端到端**打折：绑一条 1500m 的证据边界（模拟单页查不完）后 ——

    1. 可达区外沿落进 `cells_unknown` ⇒ `share < 1`、`confidence == "limited"`；
    2. 扣分**严格大于**旧口径的按条数扣分 ⇒ 证明「少采集换高分」这条路被堵死。

    第 2 条才是本用例的判别点：上一条用例的 `share` 恰为 1（未绑定证据 ⇒ 退回几何口径），
    外推在那里是恒等变换，公式若被改回按条数计扣它也不会红。
    """
    from app.living_circle.scoring import BLINDSPOT_PENALTY_CAP

    lc = _build_report(triads_near_center=False, evidence_frontier_m=1500.0)
    cal, sc = lc["caliber"], lc["scores"]
    share = cal["cells_judged"] / cal["cells_inside"]
    n_bs = len(lc["blindspots"])

    assert share < 1.0, f"证据边界 1500m < 外接圆+判定半径，却仍判满了 {cal['cells_inside']} 格"
    assert cal["cells_unknown"] > 0 and cal["evidence_complete"] is False
    assert sc["confidence"] == "limited"
    assert sc["evidence"]["judged_share"] == pytest.approx(share, abs=1e-4)

    count_only = min(BLINDSPOT_PENALTY_CAP, max(0.0, n_bs - 1) * 4.0)
    assert count_only < BLINDSPOT_PENALTY_CAP, (
        f"按条数扣分已封顶（{n_bs} 处）⇒ 本比较失去判别力，请改用更少盲区的合成输入"
    )
    assert sc["evidence"]["penalty_applied"] > count_only, (
        f"外推扣分 {sc['evidence']['penalty_applied']} 未超过按条数扣分 {count_only}"
        f"（share={share:.2%}、实测 {n_bs} 处）—— 证据面缩小仍在给分数让利"
    )


def test_assemble_evidence_merge_is_min_not_max_nor_union():
    """证据**整体**边界必须是登记类边界的**最小值** —— 合并算子的判别守卫。

    此前所有喂 `evidence_frontier_m` 的用例都广播同一个值 ⇒ min == max == union，
    把 `scope.with_evidence` 的 `min()` 换成 `max()` 或并集，**没有一条测试会红**。
    本用例喂三类各异的边界，把「保守合取」这个选择钉成可失败断言。

    ⚠️ 取证-判盲同源改造（批次二）会把整体边界从标量换成**圆盘并集**；届时本判据必须
    重指到新的合并语义接缝上，**不得就地放宽或删掉**（无样本空过是本仓最贵一类缺陷）。
    """
    # market 1600 / primary 1800 ⇒ 可判定半径只有 800m，够不到 ±1000m 方环的外沿，
    # 于是 unknown 真的有样本（三类都给到 ≥外接圆+1km 的话本用例会空过）。
    fr = {"market": 1600.0, "pharmacy": 1200.0, "primary": 1800.0}
    lc = _build_report(triads_near_center=False, evidence_frontier_m=fr)
    cal = lc["caliber"]

    assert cal["evidence_radius_m"] == pytest.approx(1200.0, abs=0.2), (
        f"整体证据边界 {cal['evidence_radius_m']} 不是登记类边界的最小值 1200 —— "
        f"合并算子被改成 max/并集了，短板让位给了长板"
    )
    assert cal["evidence_radius_m"] != pytest.approx(max(fr.values()), abs=1.0)
    assert cal["judge_radius_m"] == pytest.approx(200.0, abs=0.2)
    # 逐类边界必须各留各的（判盲是逐类门控，不被整体标量抹平）
    assert cal["evidence_frontier_m"]["market"] == pytest.approx(1600.0, abs=0.2)
    assert cal["evidence_frontier_m"]["pharmacy"] == pytest.approx(1200.0, abs=0.2)
    # 判别力前提：确实判出了一些格，也有格落进 unknown（否则上面几条是空过）
    assert cal["cells_judged"] > 0 and cal["cells_unknown"] > 0
    assert cal["cells_judged"] < cal["cells_inside"]


def test_assemble_scores_discount_uses_the_same_cells_accounting():
    """评分扣的分与报告口径里的判定面**必须是同一个数**（D-3 的接线守卫）。

    单测（`test_living_circle_scoring.py`）只证明「给了 share 就会打折」；这条证明的是
    「活管线真的把 share 给了出去」。两者缺一：公式对但没接线 ⇒ 分数照旧虚高
    （正是本次缺陷的形状 —— `backfill_nearest_minutes` 也是写了、测了、没接）。

    判据取**比值**而非绝对分：绝对分随合成输入漂移，比值才是可复算的关系。
    """
    from app.living_circle.scoring import BLINDSPOT_PENALTY_CAP, JUDGE_SHARE_FLOOR

    lc = _build_report(triads_near_center=False)
    cal, sc = lc["caliber"], lc["scores"]
    share = cal["cells_judged"] / cal["cells_inside"]
    assert sc["evidence"]["judged_share"] == pytest.approx(share, abs=1e-4)

    expected = len(lc["blindspots"]) / max(min(share, 1.0), JUDGE_SHARE_FLOOR)
    penalty = min(BLINDSPOT_PENALTY_CAP, max(0.0, expected - 1.0) * 4.0)
    # 容差放宽到 0.1：报告里的 share 保留 4 位、扣分保留 1 位，两次舍入最多漂半个最小位
    assert sc["evidence"]["penalty_applied"] == pytest.approx(penalty, abs=0.1)
    assert sc["confidence"] == ("full" if share >= 1.0 - 1e-6 and cal["evidence_complete"] else "limited")


def test_assemble_zero_judged_cells_yields_no_share_not_full_confidence():
    """一格都没判 ⇒ 覆盖率 0（不是「没有盲区」），且 `cells_inside>0` 时 share 仍是实数 0.0。

    `judged_share` 只在 `cells_inside == 0`（可达区退化，连格子都铺不出来）时才是 ``None``；
    这两种「判不了」在算术上不同（0% 有下限可放大，None 无从放大），必须分开表达。
    """
    from app.living_circle.judgement import judged_share

    assert judged_share({"cells_inside": 97, "cells_judged": 0}) == 0.0
    assert judged_share({"cells_inside": 0, "cells_judged": 0}) is None
    assert judged_share({"cells_inside": 97, "cells_judged": 5}) == pytest.approx(5 / 97)


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
    # 206/150 = jinsong 的 `ev-1` 重刷代际（采集域逐类外扩）；kaili 仍是旧快照 ⇒ 217/98。
    assert poi_metric_label(jinsong["poi"]) == "采集 206 · 圈内 150 · 已展示 150"


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
