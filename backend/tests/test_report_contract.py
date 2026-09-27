"""几何契约（``app.living_circle.report_contract``）的**判别力**测试。

## 为什么要单独测「契约本身」

``test_report_invariants.py`` 是**数据层的 oracle**：它自己算几何（外接圆、鞋带面积、
点在环内），对夹具与组装产物断言 —— 那是「数据对不对」。
本文件问的是另一个问题：**契约这个仪器准不准**。

两者不能合并：若测试直接 ``assert assess_geometry(lc).ok``，契约里写错一条判据
（阈值反了、字段取错、漏了一个 in_circle=False 的点）测试依然会绿 —— 因为它和被测
对象共用同一份实现。所以这里用**变异样本**：拿真实夹具当底，注入一类缺陷，断言命中的
是**那一条**判据（而不是笼统地 ``not ok``）。

## 覆盖的缺陷类别（每一类都对应一次真实事故）

===========================  ==================================  ==========================
变异                          对应事故                            期望命中的判据
===========================  ==================================  ==========================
盲区放大到可达区外（±5000m）    Q1：判定网格铺满研究区               盲区最远点越出外接圆
多个贴边大盲区                  Q1：整片判盲                        盲区总面积 > 可达区×2
POI 标 ``in_circle=False`` 送达  Q2：圈外点进报告                    圈外点不应展示
POI 标 True 但坐标在 3km 外     Q2 变体：标记与几何矛盾              越出外接圆（首个点名）
删掉 ``caliber``               存量 7 份旧算法 live 报告             未声明可达区口径
``isochrones=[]``              P6：迤栖村静默空壳                    缺件「路网等时圈数据」
``collect_radius_m`` 调小       采集区盖不住可达区                    采集半径 < 外接圆
口径 20min 但只有 5/10/15 圈     口径与数据不一致                     可达区口径不存在
删掉环的 ``geojson``           判不了（信息不足）                    **不得误报**
===========================  ==================================  ==========================

 rev2 追加三条（证据相，底本先把夹具升格成 ``ev-1`` 自洽口径）：

===========================  ==================================  ==========================
余量改回 0 / collect≠外接圆+余量   D2 回退 ⇒ 判盲面塌回 5%          B5 余量≤0、关系复算不符
实测边界 > 请求 / 带缺口称完整     「没查完」被省略                B5
judge_radius 未减判定半径 /      判定域与证据脱钩；「判不了」冒充    B10
judged=0 却非全未定               「不盲」
缺 confidence / 低覆盖称 full /   扣分口径被改回「只按条数」        B11
penalty 复算不符
旧口径报告（无版本号）             存量 26 次历史体检              **不得误报、不得隐藏**
===========================  ==================================  ==========================
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from app.living_circle.geo_utils import haversine_m, ring_area_km2, xy_to_lnglat
from app.living_circle.report_contract import (
    BLINDSPOT_AREA_RATIO_MAX,
    GEOM_TOL,
    assess_geometry,
    report_is_presentable,
    staleness_reason,
)
from app.living_circle.scope import (
    BLIND_RADIUS_M,
    EVIDENCE_MARGIN_M,
    SCOPE_POLICY_VERSION,
    TRIAD_KEYS,
)
from app.living_circle.scoring import (
    BLINDSPOT_PENALTY_CAP,
    BLINDSPOT_PENALTY_PER_EXTRA,
    compute_scores,
)

FIXTURES = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))


def _base() -> dict:
    """以真实夹具为底（保证字段形状与产线一致）—— 变异测试的前提。"""
    return copy.deepcopy(json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8")))


def _center(lc: dict):
    return tuple(lc["scene"]["center"])


def _reach_ring(lc: dict):
    target = lc["caliber"]["reach_full_min"]
    zone = next(z for z in lc["isochrones"] if z["minutes"] == target)
    return [(float(p[0]), float(p[1])) for p in zone["geojson"]["coordinates"][0]]


def _circumradius_m(lc: dict) -> float:
    c = _center(lc)
    return max(haversine_m(c, p) for p in _reach_ring(lc))


def _reach_area_km2(lc: dict) -> float:
    return ring_area_km2(_reach_ring(lc), _center(lc))


def _square(center, half: float):
    """以 center 为中心、半边 ``half`` 米的方形闭环。"""
    return [xy_to_lnglat(center, x, y) for x, y in
            [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]]


def _blindspot(bid: str, center, half: float) -> dict:
    return {"id": bid, "polygon": {"type": "Polygon",
                                   "coordinates": [[list(p) for p in _square(center, half)]]}}


# ── 正向：现行产物必须全绿 ──────────────────────────────────────
@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_current_fixtures_are_presentable(path):
    """现行夹具（= 现行组装实现的冻结快照）必须逐条合规。"""
    lc = json.loads(path.read_text(encoding="utf-8"))
    issues = assess_geometry(lc)
    assert issues.ok, f"{path.name} 不合几何契约：{issues.reason}"


def test_kaili_fixture_is_blindspot_free():
    """变异设计的前提：凯里夹具必须**无盲区**（否则「越出可达区」的变异无从下手）。"""
    assert _base()["blindspots"] == [], "凯里夹具无盲区是本文件变异设计的前提"


def test_fixture_caliber_declares_reach_and_collect():
    """变异设计的前提之二：夹具带口径声明，且采集半径盖住可达区。"""
    cal = _base()["caliber"]
    assert cal["reach_full_min"] == 20.0
    assert cal["collect_radius_m"] >= _circumradius_m(_base()) * 0.999


# ── B1：盲区越出可达区（Q1 本体）────────────────────────────────
def test_blindspot_outside_reach_is_flagged():
    lc = _base()
    lc["blindspots"] = [_blindspot("bs-mutated", _center(lc), 5000.0)]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("越出可达区外接圆" in v and "bs-mutated" in v for v in issues.violations), issues.reason
    assert "越出可达区外接圆" in (staleness_reason(lc) or "")


def test_blindspot_inside_reach_is_clean():
    """反例护栏：盲区在可达区内 ⇒ 不得报违规（防止「一律判违规」的假修复）。"""
    lc = _base()
    lc["blindspots"] = [_blindspot("bs-inside", _center(lc), 500.0)]
    assert assess_geometry(lc).ok, assess_geometry(lc).reason


# ── B2：盲区总面积上限（Q1 的「整片判盲」形态）──────────────────
def test_blindspot_total_area_bound_is_flagged():
    """贴边的多个大盲区：每个都不越界（B1 不响），但总面积远超可达区 ×2（B2 响）。"""
    lc = _base()
    c = _center(lc)
    cr = _circumradius_m(lc)
    # 方形半边 h ⇒ 角点偏移 h·√2；取 h = 0.9·cr/√2 保证角点 0.9cr < cr（B1 沉默）
    half = 0.9 * cr / math.sqrt(2.0)
    lc["blindspots"] = [_blindspot(f"bs-area-{i}", c, half) for i in range(4)]

    issues = assess_geometry(lc)
    assert not any("越出可达区外接圆" in v for v in issues.violations), (
        f"变异样本不应触发 B1（越界），实际：{issues.reason}"
    )
    assert any("盲区总面积" in v for v in issues.violations), issues.reason
    assert BLINDSPOT_AREA_RATIO_MAX == 2.0


# ── B3/B4：圈外点（Q2 本体）────────────────────────────────────
def test_point_marked_out_of_circle_is_flagged():
    lc = _base()
    far = xy_to_lnglat(_center(lc), 3000.0, 0.0)
    lc["poi"]["points"] = [{"id": "p-far", "name": "圈外点", "in_circle": False,
                            "lnglat": [far[0], far[1]]}] + lc["poi"]["points"]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("in_circle=False" in v for v in issues.violations), issues.reason


def test_point_marked_in_circle_but_geometrically_outside_is_flagged():
    """标记与几何矛盾（Q2 的另一种形态）：标 True 却在 3km 外。"""
    lc = _base()
    far = xy_to_lnglat(_center(lc), 3000.0, 0.0)
    lc["poi"]["points"] = lc["poi"]["points"] + [
        {"id": "p-liar", "name": "谎报点", "in_circle": True, "lnglat": [far[0], far[1]]}
    ]
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("越出可达区外接圆" in v and "谎报点" in v for v in issues.violations), issues.reason


def test_tolerance_boundary():
    """容差常数必须真的参与判定：1.01×外接圆放行，1.10×外接圆判违规。"""
    c = _center(_base())
    cr = _circumradius_m(_base())

    inside = _base()
    p = xy_to_lnglat(c, 0.0, cr * 1.01)
    inside["poi"]["points"] = [{"id": "p1", "in_circle": True, "lnglat": [p[0], p[1]]}]
    assert assess_geometry(inside).ok, assess_geometry(inside).reason
    assert cr * 1.01 <= cr * GEOM_TOL

    outside = _base()
    p = xy_to_lnglat(c, 0.0, cr * 1.10)
    outside["poi"]["points"] = [{"id": "p2", "in_circle": True, "lnglat": [p[0], p[1]]}]
    assert not assess_geometry(outside).ok


# ── B0：口径可举证（存量 7 份旧算法 live 报告的判据）─────────────
def test_live_report_without_caliber_is_flagged():
    lc = _base()
    lc.pop("caliber")
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("reach_full_min" in v for v in issues.violations), issues.reason
    assert any("collect_radius_m" in v for v in issues.violations), issues.reason


def test_non_live_report_without_caliber_only_skips_b0():
    """非 live 报告不要求口径声明（历史夹具没有 ⇒「判不了」而非「有罪」）。"""
    lc = _base()
    lc.pop("caliber")
    lc["data_origin"] = "fixture_sample"
    lc["blindspots"] = [_blindspot("bs-far", _center(lc), 5000.0)]
    issues = assess_geometry(lc)
    assert not any("reach_full_min" in v for v in issues.violations), issues.reason
    # 但几何判据照旧生效（老夹具快照正是这样被认出来的）
    assert any("越出可达区外接圆" in v for v in issues.violations), issues.reason


# ── B6：采集区必须盖住可达区 ───────────────────────────────────
def test_collect_radius_smaller_than_reach_is_flagged():
    lc = _base()
    lc["caliber"]["collect_radius_m"] = 100.0
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("采集半径" in v for v in issues.violations), issues.reason


# ── 口径与数据不一致 ───────────────────────────────────────────
def test_caliber_reach_minute_absent_from_isochrones_is_flagged():
    lc = _base()
    lc["caliber"]["reach_full_min"] = 25.0
    issues = assess_geometry(lc)
    assert not issues.ok
    assert any("口径与数据不一致" in v for v in issues.violations), issues.reason


# ── Tier A：内容缺件 ───────────────────────────────────────────
@pytest.mark.parametrize(
    "origin,empty_iso,empty_poi,expect_missing",
    [
        ("live", True, True, ["路网等时圈数据", "设施点位数据（POI）"]),
        ("live", False, True, ["设施点位数据（POI）"]),
        ("live", True, False, ["路网等时圈数据"]),
        ("fixture", True, False, ["路网等时圈数据"]),
        ("fixture_sample", True, False, ["路网等时圈数据"]),
    ],
)
def test_content_missing(origin, empty_iso, empty_poi, expect_missing):
    lc = _base()
    lc["data_origin"] = origin
    if empty_iso:
        lc["isochrones"] = []
    if empty_poi:
        lc["poi"]["points"] = []
    assert list(assess_geometry(lc).missing) == expect_missing


def test_offline_blank_is_exempt():
    """``offline`` 的空白是**有意降级**（P0-2 已在 UI 标注）⇒ 不得被隐藏。

    这条与 ``test_report_invariants`` 的「isochrones 非空」并不矛盾：不变量管的是
    「声称做过完整体检的报告」，而 offline 明确声称自己没做（无网络）。
    区分二者靠 ``data_origin`` —— 一个字段就够，不需要两套判据。
    """
    lc = _base()
    lc["data_origin"] = "offline"
    lc["isochrones"] = []
    lc["poi"]["points"] = []
    lc.pop("caliber", None)
    issues = assess_geometry(lc)
    assert issues.ok, issues.reason
    assert report_is_presentable(lc) is True
    assert staleness_reason(lc) is None


def test_empty_payload_is_missing():
    issues = assess_geometry({})
    assert not issues.ok
    assert any("载荷为空" in m for m in issues.missing), issues.reason


# ── 判不了 ≠ 违规（防假阳性）───────────────────────────────────
@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda lc: lc["isochrones"][0].pop("geojson"), "等时圈无 geojson"),
        (lambda lc: [z.pop("geojson") for z in lc["isochrones"]], "全部等时圈无 geojson"),
        (lambda lc: lc["scene"].pop("center"), "无中心点"),
        (lambda lc: lc["scene"].__setitem__("center", [1.0]), "中心点长度非法"),
        (lambda lc: lc["poi"]["points"][0].pop("in_circle"), "点位无 in_circle 标记"),
        (lambda lc: lc.__setitem__("poi", {}), "poi 为空对象(live 会命中 Tier A)"),
        (lambda lc: lc.__setitem__("blindspots", [{"id": "b", "polygon": {}}]), "盲区无坐标"),
        (lambda lc: lc["scene"].__setitem__("center", [11440230.81, 2860409.52]), "墨卡托米当经纬度"),
    ],
)
def test_insufficient_input_is_not_a_violation(mutate, label):
    """输入不足 ⇒ 该判据跳过，**不得**因此判违规（假阳性比漏报更难排查）。

    例外：``poi`` 整块缺失在 live 报告里是 Tier A 缺件（missing 而非 violations），
    本用例只钉「不得凭空判 violations」。
    """
    lc = _base()
    mutate(lc)
    issues = assess_geometry(lc)
    assert issues.violations == (), f"{label} 不该被当成几何违规，实际：{issues.reason}"


# ── B5 / B10 / B11：证据相三条 ──────────────────────────────────
# 这三条守的不是几何，而是「我实际查到哪儿」与「我据此敢下多大结论」之间的那条链。
# 底本必须先把夹具升格成 **ev-1 自洽产物**：新口径下不合规的报告会让任何一条恒真命中，
# 变异样本也就失去判别力（与 B1/B2 用「凯里夹具无盲区」当前提是同一纪律）。

def _ev1_caliber(lc: dict, **over) -> dict:
    """把夹具的旧 D2 口径（余量 0、collect == 外接圆）升格成 ev-1 自洽口径。"""
    cal = lc["caliber"]
    circum = float(cal["reach_circumradius_m"])
    collect = circum + EVIDENCE_MARGIN_M
    inside = int(cal["cells_inside"])
    cal.update({
        "collect_radius_m": round(collect, 1),
        "collect_margin_m": round(EVIDENCE_MARGIN_M, 1),
        "scope_policy_version": SCOPE_POLICY_VERSION,
        "evidence_margin_m": round(EVIDENCE_MARGIN_M, 1),
        "evidence_radius_m": round(collect, 1),
        "evidence_frontier_m": {k: round(collect, 1) for k in TRIAD_KEYS},
        "evidence_complete": True,
        "evidence_bound_source": "measured",
        "judge_radius_m": round(collect - BLIND_RADIUS_M, 1),
        "cells_judged": inside,
        "cells_unknown": 0,
    })
    cal.update(over)
    return cal


def _rescore(lc: dict) -> dict:
    """按**当前** caliber/blindspots 用真公式重算 confidence/evidence（保持一致底）。"""
    cal = lc["caliber"]
    inside = int(cal.get("cells_inside") or 0)
    share = (int(cal.get("cells_judged") or 0) / inside) if inside else None
    fresh = compute_scores(
        lc["poi"]["categories"], lc["scores"].get("triads") or [], len(lc["blindspots"]),
        judged_share=share, evidence_complete=bool(cal.get("evidence_complete")),
    )
    lc["scores"]["confidence"] = fresh["confidence"]
    lc["scores"]["evidence"] = fresh["evidence"]
    return lc


def _ev1(**over) -> dict:
    """ev-1 自洽底本（默认判满可达区 ⇒ share=1、confidence=full）。"""
    lc = _base()
    _ev1_caliber(lc, **over)
    return _rescore(lc)


def test_ev1_consistent_report_is_clean():
    """反「一律判违规」护栏：新口径下自洽的报告，三条都不得响。"""
    lc = _ev1()
    issues = assess_geometry(lc)
    assert issues.ok, issues.reason
    assert lc["caliber"]["cells_judged"] == lc["caliber"]["cells_inside"]


def test_legacy_report_without_version_is_not_flagged():
    """存量报告（无 ``scope_policy_version``）⇒ 三条整体跳过，**不得**被隐藏。

    这正是 D-4「只拦复用、不拦可见性」的读侧落点：旧口径的 88.4 分仍是用户的历史。
    """
    lc = _base()
    assert "scope_policy_version" not in lc["caliber"], "夹具须停留在旧口径，本用例才有判别力"
    assert lc["caliber"]["collect_margin_m"] == 0.0, "夹具应是 D2（余量 0）形状"
    assert assess_geometry(lc).ok, assess_geometry(lc).reason


# ── B5 · 证据域自洽 ─────────────────────────────────────────────
def test_evidence_margin_zero_is_flagged():
    """余量被偷偷改回 0（D2 回退）⇒ 采集区不再为 1km 证据兜底。"""
    lc = _ev1()
    cal = lc["caliber"]
    cal["evidence_margin_m"] = 0.0
    cal["collect_radius_m"] = cal["evidence_radius_m"] = float(cal["reach_circumradius_m"])
    cal["judge_radius_m"] = 0.0
    assert any("余量" in v and "≤ 0" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_collect_radius_not_derived_from_margin_is_flagged():
    """余量声明 1000 却只外扩一半 ⇒ 关系被写死而不是导出。"""
    lc = _ev1()
    lc["caliber"]["collect_radius_m"] = round(
        float(lc["caliber"]["reach_circumradius_m"]) + EVIDENCE_MARGIN_M / 2, 1
    )
    assert any("≠ 可达区外接圆" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_measured_evidence_beyond_request_is_flagged():
    """实测边界大于请求半径在物理上不可能 ⇒ 只能是没有校验的换算/绑定顺序错。"""
    lc = _ev1()
    lc["caliber"]["evidence_radius_m"] = round(float(lc["caliber"]["collect_radius_m"]) + 300, 1)
    assert any("实测不可能大于请求" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_complete_flag_with_short_frontier_is_flagged():
    """声称「证据完整」却承认只查到边内 400m ⇒ 「没查完」被省略的那条路。"""
    lc = _ev1()
    lc["caliber"]["evidence_radius_m"] = round(float(lc["caliber"]["collect_radius_m"]) - 400, 1)
    assert any("不得称完整" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_short_frontier_marked_incomplete_is_clean():
    """反例：同样只查到边内 400m，但如实标 complete=false 并同步缩判定域 ⇒ 不得判违规。

    「判不了 ≠ 有罪」在证据相的落点：诚实承认证据有缺口是合规的，谎称完整才不是。
    """
    short = round(float(_ev1()["caliber"]["collect_radius_m"]) - 400, 1)
    lc = _ev1(evidence_complete=False, evidence_radius_m=short,
              judge_radius_m=round(short - BLIND_RADIUS_M, 1))
    issues = assess_geometry(_rescore(lc))
    assert issues.ok, issues.reason


def test_declared_version_without_evidence_keys_is_flagged():
    """版本号与键集是同一次发布的两半：只发版本不发键 ⇒ 无从举证。"""
    lc = _ev1()
    for k in ("evidence_margin_m", "evidence_frontier_m", "evidence_complete",
              "evidence_bound_source", "judge_radius_m"):
        lc["caliber"].pop(k, None)
    assert any("却缺" in v and "举证" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


# ── B10 · 判定域由证据域导出 ────────────────────────────────────
def test_judge_radius_not_derived_from_evidence_is_flagged():
    """忘了减判定半径（judge == 证据边界）⇒ 外沿的格会被当成可判。"""
    lc = _ev1()
    lc["caliber"]["judge_radius_m"] = round(float(lc["caliber"]["evidence_radius_m"]), 1)
    assert any("判定域不再由证据域导出" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_zero_judged_cells_must_all_be_unknown():
    """一格未判却有 5 格没记未定 ⇒ 「判不了」正在被当成「不盲」。"""
    lc = _ev1()
    inside = int(lc["caliber"]["cells_inside"])
    lc["caliber"].update({"cells_judged": 0, "cells_unknown": inside - 5})
    assert any("判不了」被当成「不盲" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_judged_mask_cannot_survive_zero_judge_radius():
    """判定半径 0m ⇒ 物理上最多中心一格可判；报出 10 格即掩码退化。"""
    lc = _ev1()
    cal = lc["caliber"]
    cal["evidence_radius_m"] = round(BLIND_RADIUS_M, 1)   # 只查到 1000m ⇒ judge=0
    cal["judge_radius_m"] = 0.0
    cal["evidence_complete"] = False
    cal.update({"cells_judged": 10, "cells_unknown": int(cal["cells_inside"]) - 10})
    assert any("judged 掩码已退化" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


# ── B11 · 扣分与判定面一致 ──────────────────────────────────────
def test_new_report_without_confidence_is_flagged():
    lc = _ev1()
    lc["scores"].pop("confidence")
    assert any("缺 scores.confidence" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_full_confidence_with_partial_coverage_is_flagged():
    """覆盖率 82% 却自称 full ⇒ 「没判的 17 格」冒充「没问题」。"""
    lc = _ev1()
    inside = int(lc["caliber"]["cells_inside"])
    lc["caliber"].update({"cells_judged": inside - 17, "cells_unknown": 17})
    lc["scores"]["confidence"] = "full"
    assert any("冒充「没问题」" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_full_confidence_with_incomplete_evidence_is_flagged():
    lc = _ev1(evidence_complete=False)
    lc["scores"]["confidence"] = "full"
    assert any("证据不完整" in v or "截断/饿死/熔断" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_penalty_reverted_to_count_only_is_flagged():
    """本条是 D-3 的守门人：把扣分改回「只按条数」必须被复算判据抓住。

    构造：判定面覆盖 8 成 + 2 处有据盲区 ⇒ 外推 2.5 处 ⇒ 扣 ≈5.9 分；按条数只扣 4.0 分。
    两侧都必须在封顶线以下，比较才有判别力（触顶时两种口径都得 12 分，等于没测）。
    """
    lc = _ev1()
    c = _center(lc)
    inside = int(lc["caliber"]["cells_inside"])
    judged = round(inside * 0.8)
    lc["caliber"].update({"evidence_complete": False, "cells_judged": judged, "cells_unknown": inside - judged})
    lc["blindspots"] = [_blindspot("bs-a", c, 300.0), _blindspot("bs-b", c, 300.0)]
    _rescore(lc)
    assert assess_geometry(lc).ok, assess_geometry(lc).reason
    share = judged / inside
    extrapolated = min(BLINDSPOT_PENALTY_CAP, max(0.0, len(lc["blindspots"]) / share - 1.0) * BLINDSPOT_PENALTY_PER_EXTRA)
    count_only = max(0.0, len(lc["blindspots"]) - 1.0) * BLINDSPOT_PENALTY_PER_EXTRA
    assert extrapolated > count_only > 0, "变异样本须让两种口径真的分岔"

    lc["scores"]["evidence"]["penalty_applied"] = round(count_only, 1)   # 变异：回退成按条数
    assert any("无法由公式复算" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason


def test_judged_share_must_match_the_cells_accounting():
    """评分读到的判定面与报告声明的不是同一个数 ⇒ 两处账本必须对齐。"""
    lc = _ev1()
    lc["scores"]["evidence"]["judged_share"] = 0.99
    assert any("与 caliber 分账" in v for v in assess_geometry(lc).violations), assess_geometry(lc).reason
