"""P1 笔 2 · 三要素措辞的出处守卫。

守两件事：
  1. **状态只判一次**：`_triad_state` 是 `within_blind_radius` 的唯一读者，措辞由它派生；
  2. **「1km」这个字面量只许出现在三要素渲染器里** —— 章节函数自己写"1km 内缺失"，
     就等于把可达尺的产物重新说成 1km 尺，那正是本次要根治的形状
     （`diagnosis_templates.py` 原 :623 那句"这一句判的是小学 1km 三要素事实"就是它的前科）。

不测盲区章 —— 那里的「1km」是 `blindspots[].missing_facilities` 驱动的**真** 1km 判定，合法。
"""
from __future__ import annotations

import inspect

import pytest

from app.core.pipeline import diagnosis_templates as dt

# ── 1. 状态判定：五态互斥，"未查全"不许塌成"没有" ──────────────────────

CASES = [
    # (条目, 期望状态)
    (None, "missing"),
    ({"in_reach": True, "within_blind_radius": True, "nearest_minutes": 4.7}, "reachable"),
    ({"in_reach": True, "within_blind_radius": None, "nearest_minutes": 12.0}, "reachable"),
    ({"in_reach": False, "within_blind_radius": True, "nearest_m": 950.0}, "blocked"),
    ({"in_reach": False, "within_blind_radius": False, "nearest_m": 2200.0}, "absent"),
    ({"in_reach": False, "within_blind_radius": None}, "unknown"),
    ({"in_reach": False}, "unknown"),                 # 旧快照没这一格 ⇒ 无从知道
    ({}, "missing"),                                   # 空条目＝什么都没产出，与 None 同义
]


@pytest.mark.parametrize("entry,want", CASES, ids=[str(c[1]) for c in CASES])
def test_state_is_decoded_once(entry, want):
    assert dt._triad_state(entry) == want


def test_legacy_covered_alias_still_decodes_as_in_reach():
    """旧载荷只有 `covered`：读它当 `in_reach`，但 1km 那一半必须落 unknown，不许猜。"""
    got = dt._triad_state({"covered": True, "nearest_minutes": 7.4})
    assert got == "reachable"
    assert dt._triad_state({"covered": False}) == "unknown"


# ── 2. 出处守卫：章节函数里不许再出现「1km」字面量 ────────────────────

SECTION_FNS = ("_sec_overview", "_sec_medical", "_sec_education", "_sec_market")
TRIAD_RENDERERS = ("_triad_state", "_triad_takeaway", "_triad_claim",
                   "_triad_overview", "_triad_school_para")


@pytest.mark.parametrize("fn", SECTION_FNS)
def test_sections_never_hand_write_a_1km_claim(fn):
    src = inspect.getsource(getattr(dt, fn))
    assert "1km" not in src, f"{fn} 里出现了「1km」字面量 —— 1km 的说法只能出自 _triad_* 渲染器"


def test_within_blind_radius_is_read_only_by_the_triad_renderers():
    """`within_blind_radius` 的读者集合必须封闭在那几个渲染器里。

    多一个读者＝多一处可能把两把尺弄反的地方，而这次修的就是"没人能发现弄反"。
    """
    readers = set()
    for name in dir(dt):
        if not name.startswith("_"):
            continue
        obj = getattr(dt, name)
        if not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue                       # 常量/字典成员没有源码可扫
        try:
            src = inspect.getsource(obj)
        except (TypeError, OSError):       # 导入进来的对象源码不在本文件
            continue
        if "within_blind_radius" in src:
            readers.add(name)
    assert readers <= set(TRIAD_RENDERERS), f"越界读者：{sorted(readers - set(TRIAD_RENDERERS))}"


def test_every_triad_state_renders_a_distinct_sentence():
    """五态各说一句真话，不许两态共用一句（共用＝其中一态在撒谎）。"""
    phrases = {
        s: (dt._triad_takeaway({"in_reach": s == "reachable", "within_blind_radius":
                                {"reachable": True, "blocked": True, "absent": False,
                                 "unknown": None, "missing": None}[s],
                                "nearest_minutes": 4.7, "nearest_m": 950.0})
            if s != "missing" else dt._triad_takeaway(None))
        for s in dt.TRIAD_STATES
    }
    assert len(set(phrases.values())) == len(dt.TRIAD_STATES), phrases
    # 「未查全」与「确实没有」必须是两句不同的话
    assert phrases["unknown"] != phrases["absent"]
    # 受阻那一格不许被说成"1km 内没有"（它恰恰有，只是走不到）
    assert "1km 内没有" not in phrases["blocked"]


def test_overview_buckets_the_three_bad_news_separately():
    """概览句：absent / blocked / unknown 三件事分开报，unknown 不许并进"均可达"。"""
    all_good = [{"facility": f, "in_reach": True} for f in ("菜市场", "药店", "小学")]
    assert "可达区内均有" in dt._triad_overview(all_good)

    mixed = dt._triad_overview([
        {"facility": "药店", "in_reach": False, "within_blind_radius": True, "nearest_m": 950.0},
        {"facility": "菜市场", "in_reach": False, "within_blind_radius": False, "nearest_m": 2200.0},
        {"facility": "小学", "in_reach": False, "within_blind_radius": None},
    ])
    assert "药店" in mixed and "1km 内有但步行到不了" in mixed
    assert "菜市场" in mixed and "中心 1km 内没有" in mixed
    assert "小学" in mixed and "未查全" in mixed
    assert "均可达" not in mixed and "可达区内均有" not in mixed


def test_claim_wording_matches_the_ruler_that_produced_it():
    """论断要挂证据 ID：措辞与尺不符，整条 claim 的可信度就作废。"""
    blocked = {"in_reach": False, "within_blind_radius": True, "nearest_m": 950.0}
    text = dt._triad_claim(blocked)
    assert "步行到不了" in text and "1km 内有" in text
    assert "覆盖缺位" not in text                 # 不许塌成"确实没有"
    assert dt._triad_claim({"in_reach": False, "within_blind_radius": None}).startswith("无法判定")


def test_school_paragraph_says_what_the_rulers_actually_saw():
    assert "绕行" in dt._triad_school_para(
        {"in_reach": False, "within_blind_radius": True, "nearest_m": 950.0})
    assert "1km 内没有小学" in dt._triad_school_para(
        {"in_reach": False, "within_blind_radius": False})
    assert "先补取证" in dt._triad_school_para({"in_reach": False, "within_blind_radius": None})
