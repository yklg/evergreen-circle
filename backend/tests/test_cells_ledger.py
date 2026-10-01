"""逐格台账的**写侧**测试（计划 cells-ledger-judge-scale §4.2）。

分工：`test_report_contract.py` 问的是"读侧契约准不准"（变异样本 → 命中哪一条判据）；
本文件问的是"判定那一次有没有把逐格事实**如实带出来**"—— 三态的类型、字母表、
以及台账与 `_stats_from_masks` 那五个数是不是同一次判定的产物。

为什么单独一份：这三件事此前没有活入口。第 2 条（`present` 必须是 int8 三态而不是 bool）
是复审 P0-1 的落点 —— 用 bool 承载时"没查过"会塌成"查过且没有"，而那正是 `ev-1`
整套改造要消灭的形状；塌缩发生在渲染**之前**，所以只有在这里钉才钉得住。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.living_circle.baidu_client import STOP_COMPLETE
from app.living_circle.blindspot import (
    BLIND_RADIUS_M,
    LEDGER_NO,
    LEDGER_UNKNOWN,
    LEDGER_YES,
    _stats_from_masks,
    _verdict_masks,
    render_cells_ledger,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.judgement import STAT_KEYS, Judgement, JudgeMasks
from app.living_circle.scope import TRIAD_KEYS, EvidenceDisc, EvidenceRegion, SpatialScope

CENTER = (107.9758, 26.5734)
HALF_M = 1200.0


def _scope() -> SpatialScope:
    """±1200m 方形可达区（外接圆 ≈1697m ⇒ 19×19 的格阵，够摆出全部四种格态）。"""
    ring = [xy_to_lnglat(CENTER, x, y) for x, y in
            ((-HALF_M, -HALF_M), (HALF_M, -HALF_M), (HALF_M, HALF_M), (-HALF_M, HALF_M))]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    scope = SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, HALF_M, zone)
    scope.invariant()
    return scope


def _pt(x, y):
    """`_verdict_masks` 吃的是 `(lng, lat)` 二元组（`judge_once` 那层才收 dict）。"""
    return xy_to_lnglat(CENTER, x, y)


def _disc(cat, exhausted):
    return EvidenceDisc(cat, CENTER, exhausted, exhausted, STOP_COMPLETE)


def _scenario():
    """一块精心设计的证据区域 + 一簇只在中心点的设施，让四种格态各就各位：

      ≤600m      三类皆有据且皆命中   ⇒ 确认不盲
      600–1000m  小学缺据、另两类命中  ⇒ 未定（判不了 ≠ 不盲）
      >1000m     菜场/小学有据但没命中 ⇒ 判盲
      可达区外                        ⇒ 不判
    """
    scope = _scope()
    region = EvidenceRegion(discs=(
        _disc("market", 3000.0), _disc("pharmacy", 3000.0), _disc("primary", 1600.0)))
    triads = {
        "market": [_pt(0, 0)],
        "pharmacy": [_pt(0, 0)],
        "primary": [_pt(0, 0)],
    }
    masks = _verdict_masks(CENTER, scope, triads, region=region)
    return masks, region


MASKS, REGION = _scenario()


def _dist(i, j):
    """格 (i,j) 到分析中心的直线距离（米）。"""
    grid = MASKS.grid
    return float(np.hypot(grid.coords[j], grid.coords[i]))


def test_present_masks_are_int8_not_bool():
    """P0-1 的落点：`present` 必须是 int8 三态，且**从未求值的格保持 -1**。

    若有人改回 bool：`np.zeros(dtype=bool)` 的默认值 `False` 与"查过且没有"同值，
    第三态在渲染前就没了 —— 本用例的两个断言分别从类型与取值两头拦。
    """
    for key in TRIAD_KEYS:
        assert MASKS.present[key].dtype == np.int8, f"{key} 的 present 类型是 {MASKS.present[key].dtype}"
        assert set(np.unique(MASKS.present[key]).tolist()) <= {-1, 0, 1}
    # 小学的证据盘只到 600m（1600−1000）⇒ 更远的格**从未被求值**，必须是 -1 而不是 0
    prim = MASKS.present["primary"]
    far = [(i, j) for i in range(MASKS.grid.n) for j in range(MASKS.grid.n)
           if MASKS.inside[i, j] and _dist(i, j) > 700]
    assert far, "场景须真能摆出『区外内但小学判不了』的格"
    assert all(prim[i, j] == -1 for i, j in far), [
        (i, j, int(prim[i, j])) for i, j in far if prim[i, j] != -1][:5]
    # 而同一些格里菜场是**求过值**的（盘盖到 2000m）⇒ 不许也是 -1
    mk = MASKS.present["market"]
    assert all(mk[i, j] in (0, 1) for i, j in far if MASKS.judgeable["market"][i, j])


def test_three_states_all_appear_and_mean_what_they_say():
    """四种格态各就各位，且"未定"那一档确实是"有类没查过"而不是"查过说没事"。"""
    n = MASKS.grid.n
    states = {"not_blind": 0, "blind": 0, "unknown": 0}
    for i in range(n):
        for j in range(n):
            if not MASKS.inside[i, j]:
                continue
            asked = [k for k in TRIAD_KEYS if MASKS.judgeable[k][i, j]]
            if MASKS.blind[i, j]:
                states["blind"] += 1
                assert any(MASKS.present[k][i, j] == 0 for k in asked)
            elif MASKS.verdict[i, j]:
                states["not_blind"] += 1
                assert len(asked) == len(TRIAD_KEYS)
                assert all(MASKS.present[k][i, j] == 1 for k in TRIAD_KEYS)
            else:
                states["unknown"] += 1
                assert len(asked) < len(TRIAD_KEYS)
    assert min(states.values()) > 0, f"场景没摆全三种结论：{states}"


def test_nearest_distance_is_recorded_only_where_a_verdict_was_reached():
    """距离与命中**同一次算出**：`.` 的格不许带距离，命中的格距离必 ≤ 尺，
    判没命中的必 > 尺（差 1m 容差 = 发射端取整宽度）。"""
    radius = BLIND_RADIUS_M
    n = MASKS.grid.n
    seen_hit = seen_miss = 0
    for key in TRIAD_KEYS:
        pres, near = MASKS.present[key], MASKS.nearest_m[key]
        for i in range(n):
            for j in range(n):
                if pres[i, j] == -1:
                    assert near[i, j] == -1.0, f"({i},{j}) {key} 没求值却带距离 {near[i, j]}"
                elif pres[i, j] == 1:
                    seen_hit += 1
                    assert 0 <= near[i, j] <= radius + 1.0
                else:
                    seen_miss += 1
                    assert near[i, j] > radius - 1.0 or np.isinf(near[i, j])
    assert seen_hit and seen_miss


def test_rendered_ledger_uses_only_the_three_letter_alphabet():
    led = render_cells_ledger(MASKS, BLIND_RADIUS_M)
    n = led["n"]
    assert n == MASKS.grid.n and n % 2 == 1
    assert led["grid"] == "square" and led["schema_version"] == 1
    assert led["radius_m"] == int(round(BLIND_RADIUS_M))
    expected = ({"inside", "capped", "blind", "verdict"}
                | {f"{p}.{k}" for p in ("judge", "present", "nearest") for k in TRIAD_KEYS})
    assert {k for k in led if isinstance(led[k], list)} == expected | {"center"}, sorted(led)
    nearest_keys = {f"nearest.{k}" for k in TRIAD_KEYS}
    for key in expected - nearest_keys:
        rows = led[key]
        assert len(rows) == n and all(len(r) == n for r in rows), key
        assert set("".join(rows)) <= {LEDGER_YES, LEDGER_NO, LEDGER_UNKNOWN}, key
    for key in ("inside", "capped", "blind", "verdict"):
        assert set("".join(led[key])) <= {LEDGER_YES, LEDGER_NO}, f"{key} 不该有第三态"
    for row in led["nearest.market"]:
        toks = row.split(" ")
        assert len(toks) == n
        assert all(t == "-" or t.isdigit() for t in toks)


def test_ledger_recomputes_the_same_five_numbers_as_the_stats():
    """台账与 `_stats_from_masks` 必须同一次判定 —— 逐项相等，**没有容差**。

    这条是 B13 的写侧镜像：契约那边读落库件复算，这里读内存对象复算。两侧都留的理由：
    渲染层（bool→字符、inf→`-`、四舍五入）出错时只有这一条会红。
    """
    led = render_cells_ledger(MASKS, BLIND_RADIUS_M)
    n = led["n"]
    stats = _stats_from_masks(MASKS)
    inside = [[c == LEDGER_YES for c in row] for row in led["inside"]]
    verdict = [[c == LEDGER_YES for c in row] for row in led["verdict"]]
    capped = [[c == LEDGER_YES for c in row] for row in led["capped"]]
    judge = {k: [c == LEDGER_YES for c in "".join(led[f"judge.{k}"])] for k in TRIAD_KEYS}
    present = {k: list("".join(led[f"present.{k}"])) for k in TRIAD_KEYS}
    blind = recompute = 0
    for idx in range(n * n):
        i, j = divmod(idx, n)
        if not inside[i][j]:
            continue
        asked = [k for k in TRIAD_KEYS if judge[k][i * n + j]]
        if any(present[k][i * n + j] == LEDGER_NO for k in asked):
            blind += 1
        if verdict[i][j]:
            recompute += 1
    assert stats["cells_inside"] == sum(sum(r) for r in inside)
    assert stats["cells_blind"] == blind
    assert stats["cells_judged"] == recompute
    assert stats["cells_unjudgeable_by_cap"] == sum(sum(r) for r in capped)
    assert set(stats) == set(STAT_KEYS)


def test_judgement_refuses_a_bool_present_mask():
    """把 `present` 换回 bool 必须在**构造时**就抛 —— 等到渲染才发现，第三态已经丢了。"""
    broken = JudgeMasks(
        grid=MASKS.grid, region=MASKS.region, step=MASKS.step,
        inside=MASKS.inside, blind=MASKS.blind, verdict=MASKS.verdict, capped=MASKS.capped,
        judgeable={k: MASKS.judgeable[k] for k in TRIAD_KEYS},
        present={k: (MASKS.present[k] > 0) for k in TRIAD_KEYS},        # ← bool 化
        nearest_m={k: MASKS.nearest_m[k] for k in TRIAD_KEYS},
    )
    with pytest.raises(ValueError, match="int8"):
        Judgement(spots=[], stats=_stats_from_masks(MASKS), masks=broken,
                  grid_m=200.0, prefix="t", radius_m=BLIND_RADIUS_M)


def test_judgement_refuses_a_verdict_on_a_cell_that_was_never_asked():
    """在"小学判不了"的格上写 present=1 ⇒ 抛。这正是"没查过"被写成"查过且没有"的形状。"""
    prim = MASKS.present["primary"]
    spot = next((i, j) for i in range(MASKS.grid.n) for j in range(MASKS.grid.n)
                if MASKS.inside[i, j] and prim[i, j] == -1)
    forged = {k: MASKS.present[k].copy() for k in TRIAD_KEYS}
    forged["primary"][spot] = 1
    broken = JudgeMasks(
        grid=MASKS.grid, region=MASKS.region, step=MASKS.step,
        inside=MASKS.inside, blind=MASKS.blind, verdict=MASKS.verdict, capped=MASKS.capped,
        judgeable={k: MASKS.judgeable[k] for k in TRIAD_KEYS},
        present=forged, nearest_m={k: MASKS.nearest_m[k] for k in TRIAD_KEYS},
    )
    with pytest.raises(ValueError, match="从未求值"):
        Judgement(spots=[], stats=_stats_from_masks(MASKS), masks=broken,
                  grid_m=200.0, prefix="t", radius_m=BLIND_RADIUS_M)


def test_payload_omits_the_ledger_key_when_the_caller_has_none():
    """发射纪律（与 `forensic` / `evidence_anchors` 同条）：不传 ⇒ **不发这个键**。

    离线骨架从未走过逐格判定，给它补一张空台账等于替一次没发生的判定举证。
    """
    scope = _scope()
    caliber = get_caliber("walking")
    without = scope.payload(caliber, _stats_from_masks(MASKS))
    with_ledger = scope.payload(caliber, _stats_from_masks(MASKS),
                                cells_ledger=render_cells_ledger(MASKS, BLIND_RADIUS_M))
    assert "cells_ledger" not in without
    assert with_ledger["cells_ledger"]["n"] == MASKS.grid.n
    assert with_ledger["scope_policy_version"] == without["scope_policy_version"]


def _zero_facility_scenario(pharmacy_frontier: float):
    """三类都派了证据盘，但药店**一家都没查到**（接口查全、结果为空）。

    这条分支此前一次都没被测过：`_verdict_masks:196` 那句 `local.get(key)` 对空列表返回
    `None`，`_hit_and_nearest_m` 随之返回 `(False, inf)` —— 于是"这一类根本没有设施"落进
    台账的形状，完全取决于渲染层怎么处置那个 `inf`。
    """
    scope = _scope()
    region = EvidenceRegion(discs=(
        _disc("market", 3000.0), _disc("pharmacy", pharmacy_frontier), _disc("primary", 3000.0)))
    triads = {"market": [_pt(0, 0)], "pharmacy": [], "primary": [_pt(0, 0)]}
    return _verdict_masks(CENTER, scope, triads, region=region)


def test_a_class_with_zero_facilities_reads_as_no_not_unknown():
    """查遍了的零 ⇒ `present=0`（不是 `.`），`nearest` 那一格 ⇒ `-`（不是 `0`，也不是 `Infinity`）。

    两个方向都朝坏结果，所以两头都要钉：
      - 把"确实没有"写成"没查过"（`.`）：这一类的缺口就从 `cells_blind` 蒸发成"未定"，
        而"全城没有菜市场"恰恰是这份报告最该说出口的那句话；
      - 把 `inf` 写成距离：`0` 是最强的反义（"最近 0 米"），而原样写 `Infinity` 会让
        台账成为非法 JSON —— 落库那刻才炸。
    """
    masks = _zero_facility_scenario(3000.0)
    n = masks.grid.n
    pres, near = masks.present["pharmacy"], masks.nearest_m["pharmacy"]
    judged = [(i, j) for i in range(n) for j in range(n)
              if masks.judgeable["pharmacy"][i, j] and masks.inside[i, j]]
    assert judged, "场景须真能让药店类在可达区内的格上有据"
    for i, j in judged:
        assert pres[i, j] == 0, f"({i},{j}) 药店查全却一家没有 ⇒ 该写 0，实得 {int(pres[i, j])}"
        # 内部真值仍是 inf（"无从度量"），它只在渲染处塌成 `-`；这里不许它变成有限数
        assert not np.isfinite(float(near[i, j])), f"({i},{j}) 零设施类的最近距离被写成了 {near[i, j]}"
    # 存在性结论：一类有据且确实没有 ⇒ 判盲，一格都不许落进"未定"
    for i, j in judged:
        assert masks.blind[i, j] and masks.verdict[i, j], f"({i},{j}) 零设施没把这一格判盲"

    led = render_cells_ledger(masks, BLIND_RADIUS_M)
    assert set("".join(led["present.pharmacy"])) <= {LEDGER_NO, LEDGER_UNKNOWN}
    assert all(tok == "-" for row in led["nearest.pharmacy"] for tok in row.split(" ")), led["nearest.pharmacy"]
    # 发射面：允许 NaN/Infinity 的序列化会把上面的 `-` 纪律整个绕开
    json.loads(json.dumps(led, allow_nan=False))


def test_zero_facility_is_still_unknown_where_that_class_was_never_exhaustive():
    """同一类"没有设施"，在它**没查全**的那些格上必须回到 `.` —— 两个字符不许互相冒充。

    上一条钉的是"查全且为零 ⇒ 0"；本条钉反向：把盘缩到 1600m 后，距中心 >600m 的格
    药店无从下结论（1km 判定圆越了证据边界）。若那条默认值被改成 `0`，"我们没查全"
    就会被说成"这一带没有药店"—— 正是 `ev-1` 整套改造要消灭的形状。
    """
    masks = _zero_facility_scenario(1600.0)
    n = masks.grid.n
    pres = masks.present["pharmacy"]
    unasked = [(i, j) for i in range(n) for j in range(n)
               if masks.inside[i, j] and not masks.judgeable["pharmacy"][i, j]]
    assert unasked, "场景须真能摆出『药店没查全』的格"
    for i, j in unasked:
        assert pres[i, j] == -1, f"({i},{j}) 药店未查全却写成 {int(pres[i, j])} —— 没查的不能冒充查过"
    # 而同一些格里药店若是查全的（靠近中心那圈），必须是 0 —— 两个字符确实分得开
    asked = [(i, j) for i in range(n) for j in range(n)
             if masks.inside[i, j] and masks.judgeable["pharmacy"][i, j]]
    assert asked and all(pres[i, j] == 0 for i, j in asked)
