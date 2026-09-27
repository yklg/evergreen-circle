"""设施实体判表 `facility_rule.py` —— 以**黄金样本夹具**为唯一期望来源。

夹具 `tests/fixtures/facility_merge_golden.json` 里的 11 组配对来自 2026-09-26/27
对真实采集报告的两两核对（官渡区那份现已从 `lc_cache.db` 过期消失，夹具是其唯一留存）。
本文件的期望值一律**写在测试里**，不从实现反推 —— 归并是「少输出」型改动，
守恒不变量对它完全免疫（老数字自洽地虚高着 8 个 ATM），实现写错不会让任何既有
测试变红，只有这批样本能钉住。
"""
import json
import math
import pathlib

import pytest

from app.living_circle.facility_rule import (
    FACILITY_MERGE_M,
    facility_core,
    pick_display_name,
    pick_representative,
    promote_display_name,
    same_facility,
    sub_point_labels,
)
from app.living_circle.geo_utils import haversine_m

GOLDEN = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "facility_merge_golden.json").read_text(
        encoding="utf-8"
    )
)
PAIRS = GOLDEN["pairs"]


def _distance(p):
    a, b = p["a"], p["b"]
    return haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"]))


@pytest.mark.parametrize("p", PAIRS, ids=[p["id"] for p in PAIRS])
def test_golden_pair_verdict(p):
    """每组真实配对的判定必须与人工核对结论一致。"""
    assert same_facility(p["a"], p["b"], _distance(p)) is (p["expect"] == "merge")


@pytest.mark.parametrize("p", PAIRS, ids=[p["id"] for p in PAIRS])
def test_golden_distance_field_not_stale(p):
    """夹具里的 `distance_m` 必须与坐标重算一致（防止有人改坐标不改距离、留下自相矛盾样本）。"""
    assert _distance(p) == pytest.approx(p["distance_m"], abs=0.05)


def test_golden_fixture_covers_both_verdicts():
    """夹具不得退化成单边样本 —— 只测「该合」会让误合判据永远无人守。"""
    expects = {p["expect"] for p in PAIRS}
    assert expects == {"merge", "keep"}
    assert sum(1 for p in PAIRS if p["expect"] == "keep") >= 3


# ── 机构主体归一：词表驱动，期望值逐条写死 ─────────────────────────

@pytest.mark.parametrize(
    "name, institution, is_sub, suffix",
    [
        ("中国建设银行24小时自助银行(昆明官渡支行)", "中国建设银行", True, "24小时自助银行"),
        ("中国建设银行(昆明兴关支行)", "中国建设银行", False, ""),
        ("中国建设银行第五个贷中心(昆明兴关支行)", "中国建设银行", True, "个贷中心"),
        ("北京广仁中西医结合医院-发热门诊", "北京广仁中西医结合医院", True, "发热门诊"),
        ("潘家园旧货市场-西2门", "潘家园旧货市场", True, "西2门"),
        ("美宜佳便利店", "美宜佳便利店", False, ""),
        ("", "", False, ""),
    ],
)
def test_facility_core(name, institution, is_sub, suffix):
    core = facility_core(name)
    assert core.institution == institution
    assert core.is_sub_point is is_sub
    assert core.matched_suffix == suffix


def test_银行_itself_is_not_a_sub_point():
    """「银行」绝不能进子点词表 —— 否则每一家支行都被判成附属点，归并会吞掉整个金融类。"""
    core = facility_core("中国工商银行(昆明关上支行)")
    assert core.is_sub_point is False


# ── 限定语相容：真实数据全是城市名前缀不对称 ────────────────────────

@pytest.mark.parametrize(
    "qa, qb, compatible",
    [
        ("关上支行", "昆明关上支行", True),      # 后缀相容（官渡真实样本）
        ("潘家园支行", "北京潘家园支行", True),   # 前缀相容（劲松真实样本，方向相反）
        ("", "昆明关上支行", True),              # 一侧无限定语 ⇒ 相容
        ("关上支行", "北京路支行", False),        # 互不包含 ⇒ 拒合
        ("城东支行", "城西支行", False),
    ],
)
def test_qualifier_compatibility(qa, qb, compatible):
    a = {"name": f"中国建设银行({qa})" if qa else "中国建设银行", "lng": 0.0, "lat": 0.0}
    b = {"name": f"中国建设银行24小时自助银行({qb})" if qb else "中国建设银行24小时自助银行",
         "lng": 0.0, "lat": 0.0}
    assert same_facility(a, b, 12.0) is compatible


# ── 显式父子字段优先于名称推断 ──────────────────────────────────────

def test_explicit_parent_field_wins_over_name():
    """有 `parent_uid` 就直接信字段，不看名称 —— 多源 POI 接入时的优先通道。"""
    parent = {"name": "某某网点", "uid": "U-1", "lng": 0.0, "lat": 0.0}
    child = {"name": "毫不相干的名字", "parent_uid": "U-1", "lng": 0.0, "lat": 0.0}
    assert same_facility(parent, child, 20.0) is True


def test_explicit_parent_still_respects_radius():
    parent = {"name": "A", "uid": "U-1", "lng": 0.0, "lat": 0.0}
    child = {"name": "B", "parent_uid": "U-1", "lng": 0.01, "lat": 0.0}
    assert same_facility(parent, child, 900.0) is False


# ── 代表点与升格名 ──────────────────────────────────────────────────

CENTER = (102.75000, 25.01800)


def _at(x, y):
    lng = CENTER[0] + x / (111320.0 * math.cos(math.radians(CENTER[1])))
    lat = CENTER[1] + y / 110540.0
    return {"lng": round(lng, 6), "lat": round(lat, 6)}


def test_representative_is_nearest_to_center():
    far = {**_at(300, 0), "name": "中国工商银行(昆明关上支行)"}
    near = {**_at(20, 0), "name": "中国工商银行24小时自助银行(关上支行)"}
    assert pick_representative([far, near], CENTER) is near


def test_promote_display_name_strips_sub_suffix_keeps_qualifier():
    assert (
        promote_display_name("中国建设银行24小时自助银行(昆明官渡支行)")
        == "中国建设银行(昆明官渡支行)"
    )
    assert promote_display_name("潘家园旧货市场-西2门") == "潘家园旧货市场"


def test_promotion_abandons_when_name_would_collide():
    """升格名与同类别既有点位撞名 ⇒ 保留原名（劲松「潘家园旧货市场」主点距其子点 171m）。"""
    group = [{"name": "潘家园旧货市场-立体停车场", **_at(0, 0)}]
    assert pick_display_name(group, group[0], ["潘家园旧货市场"]) == "潘家园旧货市场-立体停车场"


def test_group_with_parent_uses_parent_name_not_sub_name():
    parent = {**_at(40, 0), "name": "中国工商银行(昆明关上支行)"}
    child = {**_at(20, 0), "name": "中国工商银行24小时自助银行(关上支行)"}
    # 代表点是更近的 ATM，但展示名必须用主点名
    assert pick_display_name([parent, child], child, []) == "中国工商银行(昆明关上支行)"


def test_sub_point_labels_dedup_and_order():
    group = [
        {"name": "中国建设银行(昆明兴关支行)"},
        {"name": "中国建设银行24小时自助银行(兴关支行)"},
        {"name": "中国建设银行第五个贷中心(昆明兴关支行)"},
    ]
    assert sub_point_labels(group) == ["24小时自助银行", "个贷中心"]


def test_merge_radius_constant_is_the_documented_50m():
    """半径是口径的一部分，被 `caliber_index` 登记、被报告文案引用 ⇒ 钉死值防手滑。"""
    assert FACILITY_MERGE_M == 50.0
