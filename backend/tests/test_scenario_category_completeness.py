"""类别集完整性守卫（附录 G-06 / TC-07，第一片 D1「守恒优先规则」+ D7「加键不建表」）。

写这批用例时实测出一件与计划正文**相反**的事实，必须留档：

计划 D1 断言「在 assemble 侧丢类别会立刻把报告自判成不守恒（`in_circle ==
sum(categories) == points.length`）」，并据此认为 POI 守恒不变量会自动拦住
「把场景子集实现在组装层」。实测**不成立** —— 守恒的两条边都由同一份
`per_category` 派生，整类被裁时两边**同步变小**，自检照样 `ok=true`。
见 `test_conservation_is_blind_to_dropping_whole_categories`。

⇒ D1 依赖的这道保护并不存在。游客档若真要按场景裁类别，必须另有一道
「落库类别集 == 判表全集」的完整性守卫，即 `test_single_outlet_...` 所登记的缺口。
本片验收标准 ⑤「POI 守恒在游客档下仍成立」**不足以**支撑放行，须同条补完整性。

另一个方向的事实是**有利**的：判表唯一不是口号，`to_stats` 对表外类别键直接
`KeyError`（见 `test_category_key_outside_the_global_table_is_refused`）
⇒ 新增游客类别只能进 `CATEGORY_RULES`，"另建一份游客判表" 走不到组装层。
"""
from __future__ import annotations

from typing import Dict, List

import pytest

from app.living_circle import assemble as asm
from app.living_circle.caliber import get_caliber
from app.living_circle.category_rule import CATEGORY_RULES
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import check_poi_conservation, to_stats
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)
ALL_CATS = list(CATEGORY_RULES.keys())


def _scope(half: float = 1000.0) -> SpatialScope:
    ring = [
        xy_to_lnglat(CENTER, -half, -half),
        xy_to_lnglat(CENTER, half, -half),
        xy_to_lnglat(CENTER, half, half),
        xy_to_lnglat(CENTER, -half, half),
    ]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


SCOPE = _scope()


def _items(cat: str, xs: List[float]) -> List[Dict[str, object]]:
    out = []
    for i, x in enumerate(xs):
        lng, lat = xy_to_lnglat(CENTER, x, 0.0)
        out.append({"lng": lng, "lat": lat, "name": f"{cat}{i}"})
    return out


def _block(per_category: Dict[str, list]):
    """走 POI 段的**唯一出口** `build_poi_block`（与 test_poi_conservation 同一接缝）。"""
    stats = to_stats(per_category, {}, SCOPE, CENTER)
    return asm.build_poi_block(per_category, {}, SCOPE, CENTER, stats)


def test_full_category_set_is_conservation_clean():
    """对照组：全集入参时守恒自洽，且落库类别数 == 判表类别数。"""
    block = _block({cat: _items(cat, [200.0, 400.0]) for cat in ALL_CATS})
    assert check_poi_conservation(block) is None
    assert len(block["categories"]) == len(CATEGORY_RULES)


def test_conservation_is_blind_to_dropping_whole_categories():
    """**实测记录（与计划 D1 的断言相反）**：整类被裁时守恒自检仍判"健康"。

    三缺一类（8 → 3）：`sum(categories[].in_circle)` 与 `len(points)` 同时按同一份
    `per_category` 缩小 ⇒ 二者仍然相等 ⇒ `conservation.ok=true`。
    这条不是"该修的失败"，而是把**保护伞的实际覆盖面**钉成可读事实，防止后续
    以「守恒会拦住组装层裁类别」为放行依据。
    """
    subset = {cat: _items(cat, [200.0, 400.0]) for cat in ALL_CATS[:3]}
    block = _block(subset)
    assert len(block["categories"]) == 3 < len(CATEGORY_RULES)
    assert check_poi_conservation(block) is None, "守恒若已能抓整类被裁，须重指本用例"
    assert block["conservation"]["ok"] is True, "同上：degrade/strict 处置未变，勿在此放宽"


@pytest.mark.xfail(
    strict=True,
    reason="D1 需要的完整性守卫尚不存在：POI 出口不声明「应然类别全集」，整类被裁无从发现",
)
def test_single_outlet_declares_the_expected_category_set():
    """POI 段唯一出口必须让「少了一类」在报告里机器可读，而不是只靠基线 fixture 兜。

    要求的形状（这是规格，不是猜测既有 API）：
    * ``categories_complete`` —— 落库类别集是否等于应然全集；
    * ``missing_categories`` —— 缺了哪些类（按判表顺序）。

    有这两格，「场景子集只作用于展示投影层」才可证伪；没有它们，游客档把类别
    裁在组装层还是投影层，从产物上**看不出区别** —— 那正是计划点名的 P0-4 事故面。
    """
    block = _block({cat: _items(cat, [200.0]) for cat in ALL_CATS[:3]})
    assert block["categories_complete"] is False
    assert block["missing_categories"] == ALL_CATS[3:]


def test_category_key_outside_the_global_table_is_refused():
    """D7 的结构保证：判表外的类别键到不了组装层（`to_stats` 直接 KeyError）。

    ⇒ 「加键不建表」由生产路径强制：新游客类别**必须**进 `CATEGORY_RULES`，
    另起一份 `category_rule_tourist.py` 的产物会在第一格统计上炸掉，而不是静默出一份
    只有游客类别的报告。这也是 `test_guard` 里「出现第二份 CATEGORY_RULES 即红」的
    运行时对应物。
    """
    unknown = "tourist_site"
    assert unknown not in CATEGORY_RULES
    with pytest.raises(KeyError) as ei:
        to_stats({unknown: _items(unknown, [200.0])}, {}, SCOPE, CENTER)
    assert unknown in str(ei.value)
