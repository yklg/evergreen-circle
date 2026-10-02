"""#81 · 封顶名单那道闸的**对照面**必须是「有实测举证行」而不是「有实测边界」。

毛病的确切形状：`invariant` 里那条 `if c not in self.evidence_frontier_m` 拿逐类边界表的
键集当"这一类量过没有"的替身。但两张表在标量路径上**定义域不同** ——
`bind_evidence` 只把**三要素那三类**的边界交进 `evidence_frontier_m`（判定吃三类合取，
`degenerate_evidence_region` 也只遍历 `TRIAD_KEYS`），而 `capped` 按**所有类**收集
（`CollectionEvidence.capped_categories` 过 `per_term`）。⇒ 任何一个非三要素关键词类
（`shopping`/`education`/…）撞上接口封顶，都会在绑定期抛 `ValueError`、整份 live 报告失败。
错误信息说的是"类名写错"，而类名没写错 —— 那是闸把**自己的定义域不足**伪装成了调用方的错。

原意要拦的两件事一条都不许松，本文件用两条反向对照钉住：
①类名真写错（没有任何举证行）⇒ 照样红；②在绑定证据之前就声明封顶（无原因表）⇒ 照样红。

⚠️ 第 1 条与第 5 条都**显式断言**该类不在 `evidence_frontier_m` 里、只在
`evidence_stop_reasons` 里。这两行是本文件能当回归判据的原因：没有它们，载荷换个形状
（比如哪天边界表也铺满全类）用例就会在改前的代码上照样绿，测的就不再是这道闸。
"""
from __future__ import annotations

import asyncio
from typing import Sequence

import pytest

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import (
    PlaceSearchOut, STOP_COMPLETE, STOP_SERVER_CAP,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.data_source import bind_evidence
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import TRIAD_KEYS, SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
# 非三要素的关键词类 —— 正是那张边界表今天不含、而封顶事实会含的那一档
OUTSIDE = "shopping"
assert OUTSIDE not in TRIAD_KEYS, "前提不成立：这个类已是三要素，本文件的靶子就没了"


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _row(cat: str, term: str, stop: str = STOP_COMPLETE) -> pc.TermEvidence:
    return pc.TermEvidence(category=cat, term=term, requested_radius_m=2000.0,
                           pages_fetched=1, returned=3, total=3, stop_reason=stop,
                           farthest_m=None if stop == STOP_COMPLETE else 900.0)


def _triad_rows(scope: SpatialScope) -> Sequence[pc.TermEvidence]:
    """三要素那三行（全是查全）：让 `evidence_radius_m` 量得到东西，不参与任何被断言的位。"""
    return [_row(c, f"{c}·三要素") for c in TRIAD_KEYS]


def _bound(rows: Sequence[pc.TermEvidence]) -> SpatialScope:
    """把（可能带封顶事实的）采集结果走**唯一绑定点** `bind_evidence` 绑进去。"""
    collected = pc.PoiCollection(
        per_category={}, triads={},
        evidence=pc.CollectionEvidence(requested_radius_m=2000.0, per_term=tuple(rows)))
    return bind_evidence(_scope(), collected)


# ──────────── 1. 主判据：非三要素类撞封顶 ⇒ 绑得进去，且两位都在载荷里 ────────────

def test_non_triad_capped_category_binds_and_both_keys_reach_the_payload():
    scope = _bound([*_triad_rows(_scope()), _row(OUTSIDE, "超市", STOP_SERVER_CAP)])
    cal = scope.payload(get_caliber("walking"))
    # 两张表定义域确实不同 ⇒ 这条断言让本用例在改前代码上是**红**的（不是恒绿）
    assert OUTSIDE not in cal["evidence_frontier_m"], (
        f"{OUTSIDE} 竟有实测边界条目 ⇒ 载荷形状变了，本文件的对照面论证要重核")
    assert OUTSIDE in cal["evidence_stop_reasons"], (
        f"{OUTSIDE} 不在原因表 ⇒ 闸的新对照面也拦不住它，那才叫真写错了")
    assert cal["evidence_capped_categories"] == [OUTSIDE], cal["evidence_capped_categories"]
    assert cal["evidence_capped_terms"] == [f"{OUTSIDE}:超市"], cal["evidence_capped_terms"]


# ──────────── 2. 反向对照①：类名真写错（没有任何举证行）⇒ 照样红 ────────────

def _full_frontier(scope: SpatialScope) -> dict:
    """三要素边界都顶到**本次请求值**：让「声称查全 ⇒ 边界必须够到请求」那道闸先放行，
    这样下面两条反向对照里真正抛错的只可能是封顶那道闸。

    ⚠️ 第一版这里手填 `2000.0`，于是先撞上的是完整性那道闸（`实测边界 2000m < 请求 3825m`），
    断到的根本不是被测的那一条 —— 前置条件本身也要核。
    """
    return {k: scope.required_radius_m(k) for k in TRIAD_KEYS}


def test_capped_class_without_any_evidence_row_still_raises():
    scope = _scope()
    with pytest.raises(ValueError, match="封顶名单里的") as exc:
        scope.with_evidence(_full_frontier(scope), complete=False,
                            capped=("no_such_category",),
                            stop_reasons={k: STOP_COMPLETE for k in TRIAD_KEYS})
    assert "no_such_category" in str(exc.value), exc.value


# ──────────── 3. 反向对照②：绑定之前就声明封顶（无原因表）⇒ 照样红 ────────────

def test_capping_declared_before_any_evidence_still_raises():
    """`stop_reasons` 缺席 = 还没绑过采集侧事实却先报了封顶 —— 正是闸要拦的那件。"""
    scope = _scope()
    with pytest.raises(ValueError, match="封顶名单里的"):
        scope.with_evidence(_full_frontier(scope), complete=False, capped=(OUTSIDE,))


# ──────────── 4. 区域路径不受影响（capped 从盘上读，与原因表天然同域）────────────

def test_region_path_still_derives_capped_without_the_gate_firing():
    from app.living_circle.scope import EvidenceDisc, EvidenceRegion

    reg = EvidenceRegion([
        EvidenceDisc(category=OUTSIDE, anchor=(float(CENTER[0]), float(CENTER[1])),
                     request_radius_m=2000.0, exhausted_radius_m=900.0,
                     stop_reason=STOP_SERVER_CAP),
        *[EvidenceDisc(category=k, anchor=(float(CENTER[0]), float(CENTER[1])),
                       request_radius_m=2000.0, exhausted_radius_m=2000.0,
                       stop_reason=STOP_COMPLETE) for k in TRIAD_KEYS],
    ])
    scope = _scope().with_evidence(complete=False, region=reg)
    assert scope.evidence_capped_categories == (OUTSIDE,), scope.evidence_capped_categories
    assert OUTSIDE in scope.evidence_frontier_m, "区域路径下边界表覆盖全部类别 —— 这是它与标量路径的差别"


# ──────────── 5. 端到端：真实采集器 + 桩客户端（零 HTTP），即 #81 的复现 ────────────

class _ShoppingCapped:
    """只在 `超市` 那一词回 `server_cap`（百度自称还有货却断页），其余词给一颗点。"""

    def _point(self, dx: float, name: str, uid: str):
        lng, lat = xy_to_lnglat(CENTER, dx, 0.0)
        return {"name": name, "lng": lng, "lat": lat, "address": "友好路",
                "tag": "超市", "type": "supermarket", "uid": uid}

    async def place_search(self, query, center, **kw):
        if query == "超市":
            return PlaceSearchOut([self._point(400.0, "某超市", "u-cap")], 60, 1, STOP_SERVER_CAP)
        return PlaceSearchOut([self._point(300.0, "某店", "u-one")], 1, 1, STOP_COMPLETE)


def test_live_chain_collect_then_bind_does_not_crash():
    """复现链路 = live 分支走的链路：`collect_poi` → `bind_evidence`。

    改前这里抛 `ValueError("封顶名单里的 ('shopping',) 没有对应的实测边界")`；
    改前它**没被任何测试撞到**，是因为全部带封顶的测试用例都恰好用三要素类（`pharmacy`）。
    """
    collected = asyncio.run(pc.collect_poi(
        _ShoppingCapped(), CENTER, 2000.0, scope=_scope(),
        budget_snapshot=pc.POIBudget(total=40)))
    ev = collected.evidence
    assert OUTSIDE in ev.capped_categories, (
        f"前置不成立：桩没能造出非三要素类的封顶事实，实测 capped={ev.capped_categories}")
    assert OUTSIDE not in ev.triad_frontier_m(TRIAD_KEYS), "前置不成立：该类竟在边界表里"
    bound = bind_evidence(_scope(), collected)
    cal = bound.payload(get_caliber("walking"))
    assert cal["evidence_capped_terms"], "端到端跑通了却没把词级封顶发进载荷 ⇒ 上屏那句是空的"
