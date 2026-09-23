"""阶段 1 · POI 装配层单一出口 + 点数守恒契约（``build_poi_block``）。

## 这批用例要证明的三件事

1. **两条口径不再互相污染**（计划 §6 阶段 1.2 / 审查 R1）：
   `in_circle` 从 `points` 派生（可达口径），`total` 仍从 `per_category` 派生（采集口径）。
   反例是旧实现——同一个 `poi` 对象的 4 个字段由两条独立链路装配，
   一条截断一条不截断，产出「面板写圈内 104 / 图上 98」且无人发现。

2. **截断必然被披露**（阶段 1.3 / §8-D3）：触发 200 上限时 `poi.truncated.dropped > 0`，
   且 `poi.total`（采集口径）**不被展示上限压小** —— 这正是「采集侧不该截断」的理由。

3. **守恒自检是唯一的护栏，且它真的会响**（阶段 3 验收 #3）：
   把「派生收敛」这一步摘掉（模拟一次忘记调用 `derive_stats_from_points` 的重构），
   测试**必须变红**。护栏不会响 = 没有护栏。
"""
from __future__ import annotations

import logging
from typing import Dict, List

import pytest

from app.living_circle import assemble as asm
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.poi import (
    POI_CAP_PER_CAT,
    PoiConservationError,
    check_poi_conservation,
    to_stats,
)
from app.living_circle.scope import SpatialScope

CENTER = (107.9758, 26.5734)


def _ll(x: float, y: float) -> Dict[str, float]:
    lng, lat = xy_to_lnglat(CENTER, x, y)
    return {"lng": lng, "lat": lat}


def _scope(half: float = 1000.0) -> SpatialScope:
    """±half 米方环做可达区（默认 ±1000m：环内半径 ~1414m）。"""
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
    return [{**_ll(x, 0.0), "name": f"{cat}{i}"} for i, x in enumerate(xs)]


def _block(per_category: Dict[str, list]):
    stats = to_stats(per_category, {}, SCOPE, CENTER)
    return asm.build_poi_block(per_category, {}, SCOPE, CENTER, stats)


# ── 1. 两条口径不再互相污染 ─────────────────────────────────────


def test_two_calibers_are_not_conflated():
    """`total` = 采集口径（含圈外）；`in_circle` = 可达口径（= 图上点数）。"""
    per_category = {"market": _items("菜市场", [300.0, -300.0, 3000.0, -3000.0])}
    block = _block(per_category)
    assert block["total"] == 4, "采集口径含圈外两点，必须仍是 4（不得从 points 反算塌成 2）"
    assert block["in_circle"] == 2
    assert len(block["points"]) == 2
    assert check_poi_conservation(block) is None


def test_in_circle_derives_from_points_across_categories():
    per_category = {cat: _items(cat, [200.0, 400.0, 5000.0]) for cat in ("market", "medical", "shopping")}
    block = _block(per_category)
    by = {c["category"]: c for c in block["categories"]}
    for cat in ("market", "medical", "shopping"):
        assert by[cat]["in_circle"] == 2
        assert by[cat]["total"] == 3
    assert block["in_circle"] == 6 == len(block["points"])
    assert block["total"] == 9


def test_coverage_recomputed_from_derived_in_circle():
    """coverage 也必须由派生后的 in_circle 重算，否则它与 in_circle 又成两条链。"""
    block = _block({"market": _items("菜市场", [200.0, 300.0])})
    cat = block["categories"][0]
    ideal = 3  # market 的 ideal_circle
    assert cat["in_circle"] == 2
    assert cat["coverage"] == pytest.approx(min(1.0, 2 / ideal), abs=1e-4)


# ── 2. 截断必然被披露（且不污染采集口径）─────────────────────────


def test_truncation_field_always_present():
    block = _block({"market": _items("菜市场", [200.0])})
    assert block["truncated"] == {"cap_per_cat": POI_CAP_PER_CAT, "dropped": 0, "categories": []}


def test_truncation_disclosed_and_total_untouched():
    """单类 205 条（圈内）→ 展示 200、披露 dropped=5，而**采集口径仍是 205**。"""
    block = _block({"shopping": _items("超市", [100.0 + i for i in range(205)])})
    assert len(block["points"]) == POI_CAP_PER_CAT == 200
    assert block["truncated"]["dropped"] == 5
    assert block["truncated"]["categories"] == [
        {"category": "shopping", "kept": 200, "dropped": 5}
    ]
    # §8-D3 的核心：展示上限**不得**把「抓回多少」也一起改掉
    assert block["total"] == 205
    assert block["in_circle"] == 200
    assert check_poi_conservation(block) is None


# ── 3. 分环境处置（§8-D5）────────────────────────────────────────


def test_policy_is_strict_under_pytest_and_respects_explicit_env(monkeypatch):
    # 测试环境（pytest 注入 PYTEST_CURRENT_TEST）默认硬失败
    assert asm.conservation_policy() == "strict"
    monkeypatch.setenv("LC_POI_CONSERVATION", "degrade")
    assert asm.conservation_policy() == "degrade"
    monkeypatch.setenv("LC_POI_CONSERVATION", "STRICT")
    assert asm.conservation_policy() == "strict"


def test_strict_raises_when_derivation_is_skipped(monkeypatch):
    """**护栏会响**：摘掉「派生收敛」这一步（模拟忘记调用 `derive_stats_from_points` 的重构），
    守恒必然破裂，strict 口径下必须抛 `PoiConservationError`。

    这条同时是阶段 3 验收 #3 的证据：自检确实是**唯一**的护栏 ——
    旧实现里 `categories` 与 `points` 由两条链各自产出，没有任何一层能发现差额。
    """
    per_category = {"shopping": _items("超市", [100.0 + i for i in range(205)])}
    stats = to_stats(per_category, {}, SCOPE, CENTER)
    monkeypatch.setattr(asm, "derive_stats_from_points", lambda s, p: s)  # 退回「两条链」
    with pytest.raises(PoiConservationError) as ei:
        asm.build_poi_block(per_category, {}, SCOPE, CENTER, stats)
    assert "205" in str(ei.value) and "200" in str(ei.value)


def test_degrade_marks_report_and_logs_loudly(monkeypatch, caplog):
    """生产/演示口径：报告照出，但**必须留痕**（`ok=false` + detail + ERROR 日志），不静默。"""
    per_category = {"shopping": _items("超市", [100.0 + i for i in range(205)])}
    stats = to_stats(per_category, {}, SCOPE, CENTER)
    monkeypatch.setattr(asm, "derive_stats_from_points", lambda s, p: s)
    monkeypatch.setenv("LC_POI_CONSERVATION", "degrade")
    with caplog.at_level(logging.ERROR, logger="app.living_circle.assemble"):
        block = asm.build_poi_block(per_category, {}, SCOPE, CENTER, stats)
    assert block["conservation"]["ok"] is False
    assert block["conservation"]["declared_in_circle"] == 205
    assert block["conservation"]["actual_points"] == 200
    assert "205" in block["conservation"]["detail"]
    assert any(r.levelno == logging.ERROR for r in caplog.records), "degrade 分支必须打 ERROR 日志"


def test_conservation_ok_true_on_healthy_block():
    block = _block({"market": _items("菜市场", [200.0, 300.0])})
    assert block["conservation"] == {
        "ok": True,
        "declared_in_circle": 2,
        "actual_points": 2,
    }


# ── 4. 阶段 3.7 · 软上限告警必须一路走到**用户可见的地方** ─────────────
# 装配层写进 `poi.truncated` 只是"留痕"；若文案层不引用它，用户照样看不到截断。
# 本组把「装配 → 披露文案」这条链端到端钉住（单测 `poi_metric_label` 只覆盖后半段）。


def test_soft_cap_truncation_reaches_the_visible_label():
    """单类 205 → `poi.truncated.dropped=5`，且**指标文案**必须出现第四段披露。"""
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    block = _block({"shopping": _items("超市", [100.0 + i for i in range(205)])})
    assert block["truncated"]["dropped"] == 5

    label = poi_metric_label(block)
    assert label == "采集 205 · 圈内 200 · 已展示 200 · 另有 5 处未展示（shopping 5，每类上限 200）", label


def test_no_truncation_means_no_fourth_segment():
    """反例护栏：没触发上限时**不得**出现第四段（披露过量会退化成噪声、进而被忽略）。"""
    from app.core.pipeline.diagnosis_templates import poi_metric_label

    block = _block({"shopping": _items("超市", [100.0 + i for i in range(30)])})
    assert block["truncated"]["dropped"] == 0
    label = poi_metric_label(block)
    assert label == "采集 30 · 圈内 30 · 已展示 30", label
    assert "另有" not in label
