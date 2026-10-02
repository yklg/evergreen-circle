"""R23-B2 · 采集**收手单位**必须与覆盖度分子同一个（门槛项优先，点数兜底）。

改之前的形状：B 阶段两处闸都拿 `_in_circle_count(...) >= ideal_circle` 判达标，而自 `cov-1`
起覆盖度的分子是**门槛项数**（`poi.required_count_from_points`）⇒ 医疗类只要凑够 3 颗就停止扩词，
哪怕那 3 颗全是**不计分的诊所**（门槛项 0 处）。报告于是写"门槛项不足"，读者读成"社区没有"，
真实原因是我们自己先停了手 —— 单位不同导致的是**归因错**，不是算错分。

本文件钉四件事（顺序即取证顺序）：
1. `_at_target` 在**建了子类表的两类**上按门槛项判，且与点数判法**给出不同答案**（差分才是修复）；
2. 在**没建表的六类**上与点数判法**逐格同值**（换单位不许顺手改掉那六类的收手行为，计划 §0③）；
3. 端到端：3 颗诊所的医疗类**必须真的多扩一轮词**，3 颗门槛项的医疗类**必须不扩**（反向对照）；
4. 收手闸与覆盖度分子**逐格等值**（两处一旦分叉，报告里的分数与"为什么停"就说的不是同一件事）。

⚠️ 第 3 条的前置是"额度多到没有类被饿着" —— 少了这句，"没扩词"可能只是没钱，
测的就不是闸而是预算。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import STOP_COMPLETE, PlaceSearchOut
from app.living_circle.caliber import get_caliber
from app.living_circle.category_rule import CATEGORY_RULES, SUB_KIND_TABLE
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import coverage_from_points, required_count_from_raw_points, stamp_sub_kind
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
N_KEYWORDS = sum(len(d["keywords"]) for d in CATEGORY_RULES.values())
A_PLUS_TRIAD = N_KEYWORDS + 3
# 三颗点各在东向 300/400/500m ⇒ 都在可达区内，又不会互相被 50m 去重吃掉。
OFFSETS = (300.0, 400.0, 500.0)
# 每个类都要跑到"没词可扩"才谈得上比"闸"，所以额度给到宽（首跑按 +40 被这条拦下过）。
FAT = A_PLUS_TRIAD + 160

MEDICINE = [("仁和诊所", "诊所"), ("康泰诊所", "诊所"), ("同和诊所", "诊所")]
MEDICINE_OK = [("社区卫生服务中心", "社区卫生服务中心"), ("新村卫生站", "卫生服务站"), ("一心堂药店", "药店")]
# 两类各自的「算门槛项 / 不算门槛项」样本（名单来自 `SUB_KIND_TABLE`，不是猜的）
GOOD_BAD = {"medical": ("康泰大药房", "药店", "仁和诊所", "诊所"),
            "education": ("中心小学", "小学", "新村幼儿园", "幼儿园")}
TABLES = sorted(SUB_KIND_TABLE)                     # 今天 = ['education', 'medical']
NO_TABLE = sorted(set(CATEGORY_RULES) - set(TABLES))


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _pt(name: str, kind: str, off: float) -> Dict[str, Any]:
    lng, lat = xy_to_lnglat(CENTER, off, 0.0)
    return {"name": name, "lng": lng, "lat": lat, "address": "关兴路",
            "tag": kind, "type": kind, "uid": f"u-{name}-{int(off)}"}


def _three(spec: List[Any]) -> List[Dict[str, Any]]:
    return [_pt(n, k, o) for (n, k), o in zip(spec, OFFSETS)]


def _mix(cat: str, good: int) -> List[Dict[str, Any]]:
    """`good` 颗算门槛项 + 其余不算 —— 点数恒为 3，只有门槛项数在动。"""
    gn, gk, bn, bk = GOOD_BAD[cat]
    return _three([(gn, gk)] * good + [(bn, bk)] * (3 - good))


class Stub:
    """**每一次调用都回同一批点**（与查询词无关）。

    为什么这样造：本文件要比的是"闸在什么条件下放行扩词"，与"哪个词带回什么"无关；
    让每类拿到同一批点，没建表的六类会直接判达标而退出，只剩两类在扩 —— 局面可判定。
    """

    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items
        self.n = 0

    async def place_search(self, query, center, **kw):
        self.n += 1
        return PlaceSearchOut([dict(p) for p in self.items], len(self.items), 1, STOP_COMPLETE)


def _run(total: int, items: List[Dict[str, Any]]):
    scope = _scope()
    stub = Stub(items)
    col = asyncio.run(pc.collect_poi(stub, CENTER, 2000.0, scope=scope,
                                     budget_snapshot=pc.POIBudget(total=total)))
    return col, stub, scope


def _expanded_categories(ev: pc.CollectionEvidence) -> set:
    """某类举证行数 > 它的关键词数 ⇒ 这一类**至少扩过一次词**（不硬编字典序）。"""
    per: Dict[str, int] = {}
    for row in ev.per_term:
        per[row.category] = per.get(row.category, 0) + 1
    return {c for c, n in per.items() if c in CATEGORY_RULES and n > len(CATEGORY_RULES[c]["keywords"])}


# ───────────────────────── 1. 有门槛口径的两类：判法必须**与点数不同** ─────────────────────────

def test_gate_follows_required_items_where_points_would_lie():
    """三颗全是诊所 ⇒ 点数说「够了」、门槛项说「还差 3」—— 本刀修的就是这一格。"""
    scope = _scope()
    items = _three(MEDICINE)
    ideal = CATEGORY_RULES["medical"]["ideal_circle"]
    in_circle = pc._in_circle_items(items, scope)
    assert len(in_circle) == 3, f"前置不成立：圈内只有 {len(in_circle)} 颗，比不出两种单位"
    assert required_count_from_raw_points(in_circle, "medical") == 0, (
        "这三颗被判成了门槛项 ⇒ 载荷不对，下面的差分什么都测不出")
    assert len(in_circle) >= ideal, "点数那一侧本来该判「达标」，否则这条在比两个 False"
    assert pc._at_target("medical", items, scope, ideal) is False, (
        "点数已满、门槛项为 0 却判成达标 ⇒ 收手单位还是点数，缺陷仍在")


def test_gate_still_stops_when_required_items_are_full():
    """反向对照：三颗都是门槛项 ⇒ 必须**照样收手**（换单位不是「永远扩下去」）。"""
    scope = _scope()
    items = _three(MEDICINE_OK)
    ideal = CATEGORY_RULES["medical"]["ideal_circle"]
    assert required_count_from_raw_points(pc._in_circle_items(items, scope), "medical") == ideal
    assert pc._at_target("medical", items, scope, ideal) is True


def test_gate_is_monotone_in_required_items_for_every_table_class():
    """两类各跑一遍 0..3 颗门槛项：判「达标」必须正好从门槛项数 == 满分线那一格开始。"""
    scope = _scope()
    for cat in TABLES:
        ideal = CATEGORY_RULES[cat]["ideal_circle"]
        for k in range(ideal + 1):
            items = _mix(cat, k)
            got = pc._at_target(cat, items, scope, ideal)
            assert got == (k >= ideal), f"{cat} 在门槛项 {k}/{ideal} 处判错 ⇒ 分子与收手闸不同源"


# ───────────────────────── 2. 没建表的六类：收手行为必须**逐格同值** ─────────────────────────

def test_classes_without_a_table_keep_the_point_rule_unchanged():
    """`required_count_from_raw_points` 返回 None 的类别 ⇒ 兜回点数，一格都不许变。

    这条是「通用换单位会让六类永不收手」的防线（计划 §0③）：那六类没有门槛口径可言，
    若实现写成「门槛项为 None 就当 0」，它们会一路扩到额度耗尽。
    """
    scope = _scope()
    assert len(NO_TABLE) == 6, f"没建表的类别数变了（实测 {NO_TABLE}）⇒ 这条的覆盖面要重算"
    for cat in NO_TABLE:
        ideal = CATEGORY_RULES[cat]["ideal_circle"]
        assert required_count_from_raw_points([_pt("某某设施", "某某类型", OFFSETS[0])], cat) is None, \
            f"{cat} 什么时候建了表？"
        for k in range(0, ideal + 2):
            items = [_pt(f"{cat}设施{i}", "某某类型", OFFSETS[0] + i) for i in range(k)]
            assert pc._at_target(cat, items, scope, ideal) == (k >= ideal), (
                f"{cat} 在 {k} 颗点上收手行为与改前不同")


# ───────────────────────── 3. 端到端：闸改了之后，采集真的多走一轮 ─────────────────────────

def test_all_clinic_medical_gets_one_more_expansion_round():
    col, _, scope = _run(FAT, _three(MEDICINE))
    ev = col.evidence
    assert ev.expansion_unfunded == (), (
        f"额度不够用了（没扩词的类：{list(ev.expansion_unfunded)}）⇒ 下面两条比的是「没钱」不是「闸」")
    expanded = _expanded_categories(ev)
    assert "medical" in expanded, (
        f"三颗诊所的医疗类没被扩过词（扩过的类={sorted(expanded)}）⇒ 收手闸仍按点数")
    # 这一格能扩词的**唯一**原因是单位换了：点数已满、门槛项为零（旧闸在这一格会直接 continue）
    med = col.per_category.get("medical", [])
    ideal = CATEGORY_RULES["medical"]["ideal_circle"]
    assert pc._in_circle_count(med, scope) >= ideal, (
        f"圈内点数 {pc._in_circle_count(med, scope)} < 满分线 {ideal} ⇒ 旧闸也会扩词，这条测不到本刀")
    assert required_count_from_raw_points(pc._in_circle_items(med, scope), "medical") == 0, (
        "这批点被判出了门槛项 ⇒ 载荷不对，旧闸与新闸会给出同一个答案")


def test_medical_with_full_required_items_does_not_expand():
    col, _, _ = _run(FAT, _three(MEDICINE_OK))
    ev = col.evidence
    assert ev.expansion_unfunded == (), f"额度不够 ⇒ 反向对照失去意义：{list(ev.expansion_unfunded)}"
    expanded = _expanded_categories(ev)
    assert "medical" not in expanded, (
        "门槛项已计满的医疗类还在扩词 ⇒ 收手闸反向失效（换单位不是永远扩下去）")


# ───────────────────────── 4. 闸与分数同源：逐格等值，不许两处分叉 ─────────────────────────

def test_gate_agrees_with_the_coverage_numerator_cell_by_cell():
    """同一批点：`_at_target` 判「达标」当且仅当 `coverage_from_points(...) == 1.0`。

    为什么值得单独钉：报告里「覆盖度 X%」与「为什么停止扩词」是两句话，读侧会把它们当同一件事。
    两处一旦分叉（例如闸用 `>` 而分数用 `min(1, …)`），这条会红 —— 而前几条都可能还是绿的。
    """
    scope = _scope()
    for cat in TABLES:
        ideal = CATEGORY_RULES[cat]["ideal_circle"]
        for k in range(ideal + 1):
            items = _mix(cat, k)
            in_circle = pc._in_circle_items(items, scope)
            cov = coverage_from_points(stamp_sub_kind(in_circle, cat), ideal, cat)
            assert pc._at_target(cat, items, scope, ideal) == (cov >= 1.0), (
                f"{cat} 门槛项 {k}/{ideal}：覆盖度 {cov} 与收手闸不一致")
    for cat in NO_TABLE:
        ideal = CATEGORY_RULES[cat]["ideal_circle"]
        items = [_pt(f"{cat}设施{i}", "某某类型", OFFSETS[0] + i) for i in range(ideal)]
        in_circle = pc._in_circle_items(items, scope)
        cov = coverage_from_points(stamp_sub_kind(in_circle, cat), ideal, cat)
        assert pc._at_target(cat, items, scope, ideal) == (cov >= 1.0), (
            f"{cat}（无门槛口径）覆盖度 {cov} 与收手闸不一致")
