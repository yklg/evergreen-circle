"""分章地图焦点（`sections[].map_focus`）与类目色表（`LC_CAT_COLOR`）的契约（2026-10-08 晚 nar-3）。

这族东西的两个失效模式都很安静，所以各有判据对着：

 **map_focus**
  ①「哪些章有图」如果由八个 `_sec_*` 各自临场决定，加一章忘了写就是**静默少一张**（屏幕上只是
     "这章没图"，没人报警）⇒ ②③ 两条把章集与登记表对齐，并对概览/结论下**负断言**。
  ② 字段脏值（不存在的类目、悬空的 `blind_id`）在前端只能"静默不画"，症状与①一模一样 ⇒ ④ 逐字段
     判合法，且在场／缺席两态都测（禁恒真）。
  ③ 图注若声称"放大到本类""只留这一处"，而画布其实只做灰化 ⇒ 那是本仓一直在消灭的"口径与数据分家"
     ⇒ ⑥ 用词表正面拦。

 **色表**
  色值同时住在后端 option 与前端点位／图例里，跨语言导不了常量 ⇒ 只能两端各留一份再钉它们相等。
  手法照 `test_fixture_mirror.py` 的「扫声明取名字集合 → 比值 → 数消费者处数」，不新造机制。
  另外禁掉"未知类目给个默认色"那条兜底：色就是类目的断言，猜色等于凭空造一个类目。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.pipeline.diagnosis_templates import (
    CATEGORY_CHAPTER,
    LC_CAT_COLOR,
    MAP_FOCUS_KINDS,
    _cat_color,
    _section_map_focus,
    assemble_report,
)
from app.living_circle.category_rule import CATEGORY_RULES

BACKEND = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BACKEND / "app" / "living_circle" / "fixtures"
TS_COLORS = BACKEND.parent / "frontend" / "src" / "lib" / "livingCircle.ts"
KAILI: Dict[str, Any] = json.loads((FIXTURE_DIR / "kaili.json").read_text(encoding="utf-8"))
PYTEST_FIXTURES = sorted(p.name for p in FIXTURE_DIR.glob("*.json"))

# 八章全表里"故意不发"的两章：概览的图就是页顶主图与它的打印替身，结论章没有焦点对象。
NOT_EMITTED = ("overview", "conclusion")
# 实测读数（三份夹具各跑一次装配得到，禁凭本表记忆改写）：盲区 0/1/0 ⇒ 两份走缺席态。
EXPECTED_EMITTED = {
    "beijing-jinsong.json": 5,
    "kaili-ev2.json": 6,
    "kaili.json": 5,
}


def _report(lc: Dict[str, Any]) -> Dict[str, Any]:
    return assemble_report(copy.deepcopy(lc), "lc-mapfocus", "k", "")


def _sections(rep: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {s["id"]: s for s in rep["sections"]}


def _emitted(rep: Dict[str, Any]) -> List[str]:
    return sorted(sid for sid, s in _sections(rep).items() if s.get("map_focus"))


@pytest.fixture(scope="module")
def report():
    return _report(KAILI)


# ── ① 前置自证：夹具真的两态齐备，否则下面的缺席判据全是空桩 ──────────────
def test_1_fixture_premises_are_measured_not_assumed():
    assert PYTEST_FIXTURES, "夹具目录扫不到 .json ⇒ 逐份遍历没走通"
    assert len(KAILI["blindspots"]) == 0, "kaili 的盲区数变了 ⇒ EXPECTED_EMITTED 那组实测数要重取"
    ev2 = json.loads((FIXTURE_DIR / "kaili-ev2.json").read_text(encoding="utf-8"))
    assert len(ev2["blindspots"]) >= 1, "ev2 没有盲区 ⇒ 盲区章的在场态没人测"
    assert len({b.get("category") for b in KAILI["poi"]["categories"]}) == 8
    assert len(KAILI["scores"]["bars"]) == 8


# ── ② 登记元判据：发出的章集 == 登记表里该发的那些（不重不漏） ────────────
def test_2_chapters_that_emit_are_exactly_the_registryminus_absent(report):
    got = set(_emitted(report))
    # 表里登记了、但因数据缺席而不发的章允许少发；反过来"表外却发了"一定是漏登记。
    assert got <= set(MAP_FOCUS_KINDS), f"表外章发了地图焦点：{sorted(got - set(MAP_FOCUS_KINDS))}"
    for sid in MAP_FOCUS_KINDS:
        if sid == "blindspot":
            assert sid not in got, "kaili 盲区 0 处 ⇒ 这一章应走缺席态，实在发就是没接住判据"
        else:
            assert sid in got, f"{sid} 章在登记表里却不发 ⇒ 加了一行登记而装配没消费（静默少一张）"


def test_2b_the_two_deliberately_unmapped_chapters_stay_empty(report):
    """概览与结论章的"不发"是登记过的决定 ⇒ 下一个人加图时这条会逼他改表，而不是悄悄多一张。"""
    for sid in NOT_EMITTED:
        assert sid in _sections(report), f"{sid} 章不在场 ⇒ 本条的空断言失去对象"
        assert _sections(report)[sid].get("map_focus") is None, (
            f"{sid} 章长出 map_focus ⇒ 与八章全表「故意不发」冲突；要么改表并说明，要么撤掉")


@pytest.mark.parametrize("name", PYTEST_FIXTURES)
def test_2c_emitted_counts_match_the_measured_reading(name: str):
    lc = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    got = len(_emitted(_report(lc)))
    assert got == EXPECTED_EMITTED[name], (
        f"{name} 发出 {got} 张分章地图、实测基线是 {EXPECTED_EMITTED[name]} "
        "⇒ 载荷字段或全表变了，先回数再改期望")


# ── ③④⑤ schema：逐字段合法，脏值不许混进载荷 ────────────────────────────
def test_3_schema_of_every_emitted_focus():
    """三份夹具逐份扫：脏值（不存在的类目、悬空的 blind_id）在前端只能静默不画，症状与"漏登记"
    一模一样，所以必须在签发侧就判红。"""
    for name in PYTEST_FIXTURES:
        lc = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        rep = _report(lc)
        bars = {b["category"] for b in (lc.get("scores") or {}).get("bars") or []}
        ids = {b["id"] for b in (lc.get("blindspots") or [])}
        cats_in_payload = {c.get("category") for c in (lc.get("poi") or {}).get("categories") or []}
        emitted = _emitted(rep)
        assert emitted, f"{name} 一章都没发焦点 ⇒ 本条扫不到任何东西（恒真）"
        for sid in emitted:
            mf = _sections(rep)[sid]["map_focus"]
            assert set(mf) <= {"kind", "categories", "blind_id", "title"}, f"{name}/{sid} 键越界：{sorted(mf)}"
            assert mf["kind"] in {"categories", "all", "blindspot"}, f"{name}/{sid} kind 不在闭集：{mf['kind']}"
            assert isinstance(mf["categories"], list) and all(c in LC_CAT_COLOR for c in mf["categories"]), (
                f"{name}/{sid} 的类目没全在色表里 ⇒ 前端取不到色只能静默不画")
            assert set(mf["categories"]) <= bars, f"{name}/{sid} 聚焦了序列里没有的类目：{mf['categories']}"
            assert set(mf["categories"]) <= cats_in_payload, f"{name}/{sid} 聚焦了载荷没有的类目"
            assert isinstance(mf["title"], str) and mf["title"].strip(), f"{name}/{sid} 图注是空的"
            if mf["kind"] == "blindspot":
                assert mf.get("blind_id") in ids, f"{name}/{sid} 的 blind_id 悬空：{mf.get('blind_id')!r}"
            else:
                assert "blind_id" not in mf, f"{name}/{sid} 不该带 blind_id"
            if mf["kind"] == "categories":
                expected = {c for c, owner in CATEGORY_CHAPTER.items() if owner == sid}
                assert set(mf["categories"]) == expected & cats_in_payload, (
                    f"{name}/{sid} 焦点类目与本章登记不一致")


def test_4_absence_branches_are_two_state_not_always_on():
    """三条缺席分支各造一次输入，断"该不发的真不发、其余照发"（禁恒真）。"""
    no_market = copy.deepcopy(KAILI)
    no_market["poi"]["categories"] = [c for c in no_market["poi"]["categories"]
                                      if c["category"] not in ("market", "shopping")]
    rep = _report(no_market)
    assert _sections(rep)["market"].get("map_focus") is None, "本章两类都取不到却仍发焦点 ⇒ 画一张没有主角的图"
    assert "medical" in _emitted(rep), "缺席分支把别的章一起带走了 ⇒ 判据写成了恒假"

    with_blind = json.loads((FIXTURE_DIR / "kaili-ev2.json").read_text(encoding="utf-8"))
    assert _sections(_report(with_blind))["blindspot"].get("map_focus"), "有盲区却不发"
    emptied = copy.deepcopy(with_blind)
    emptied["blindspots"] = []
    assert _sections(_report(emptied))["blindspot"].get("map_focus") is None, (
        "盲区清零仍发焦点 ⇒ 前端会去指一处不存在的东西")

    assert _section_or_none(with_blind, "isochrone"), "等时圈章应在场"
    assert _sections(_report(with_blind))["isochrone"]["map_focus"]["kind"] == "all"


def _section_or_none(lc: Dict[str, Any], sid: str) -> bool:
    return sid in _sections(_report(lc))


def test_4b_blind_id_follows_the_payload_not_a_hardcoded_name():
    lc = copy.deepcopy(json.loads((FIXTURE_DIR / "kaili-ev2.json").read_text(encoding="utf-8")))
    first = lc["blindspots"][0]
    renamed = dict(first, id="bs-改名后的第一处")
    lc["blindspots"] = [renamed] + list(lc["blindspots"][1:])
    mf = _sections(_report(lc))["blindspot"]["map_focus"]
    assert mf["blind_id"] == "bs-改名后的第一处", (
        f"blind_id 仍写着旧值 {mf['blind_id']!r} ⇒ 焦点是硬编码的，台账一改就指错处")


# ── ⑥ 图注用词：灰化的事就说灰化，不许声称裁剪或放大 ──────────────────────
# 图注里不许出现的**肯定式裁剪声称**。注意不用「放大」这类词做禁词：诚实句写的是
# 「也没有放大到本类」，那是否认而非声称，禁词表会把实话判红（第一版就踩了这一次）。
# 改成"必须把三句实话都说到"＋"不许出现肯定式裁剪词"，两条都是正向可判的。
BANNED_CROP_CLAIMS = ("只留", "仅显示", "已删除")
REQUIRED_DISCLAIMERS = {
    "categories": ("压到近透明", "没删", "没有放大到本类"),
    "blindspot": ("只强调", "同主图"),
    "all": ("不聚焦单一类", "不来自缩放"),
}


def test_6_captions_say_what_the_canvas_actually_does(report):
    for name in PYTEST_FIXTURES:
        lc = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        for sid in _emitted(_report(lc)):
            mf = _sections(_report(lc))[sid]["map_focus"]
            title = mf["title"]
            assert not title.startswith("局部视图："), (
                f"{name}/{sid} 图注用了「局部视图：」前缀 ⇒ 那是三处 strict 选择器的靶子，多一条就抛")
            for word in BANNED_CROP_CLAIMS:
                assert word not in title, (
                    f"{name}/{sid} 图注出现肯定式裁剪声称「{word}」，而画布只做灰化、点位一个都不删")
            for clause in REQUIRED_DISCLAIMERS[mf["kind"]]:
                assert clause in title, (
                    f"{name}/{sid} 的 {mf['kind']} 图注没交代「{clause}」"
                    "⇒ 读者会把压淡的当成没画的（口径与数据分家）")


def test_6b_geometry_never_leaks_into_the_focus_field(report):
    """`map_focus` 会原样进公开分享态的 JSON：经纬度与 gap 那类高粒度串一律不许出现（P0-5）。"""
    flat = json.dumps([_sections(report)[sid]["map_focus"] for sid in _emitted(report)],
                      ensure_ascii=False)
    assert not re.search(r"\d{2,3}\.\d{3,}\s*,\s*\d{2,3}\.\d{3,}", flat), "焦点里出现了经纬度对"
    assert not re.search(r"gap\s*[0-9]+(?:\.[0-9]+)?", flat, re.I), "焦点里出现了缺口指数"


# ── ⑦⑧⑨ 类目色表：三集合相等、值逐键相等、不许有兜底 ────────────────────
def test_7_color_table_keys_equal_the_three_category_sets():
    py_keys = set(LC_CAT_COLOR)
    rule_keys = set(CATEGORY_RULES)
    ts_src = TS_COLORS.read_text(encoding="utf-8")
    m = re.search(r"export const LC_CAT_COLOR: Record<string, string> = \{(.*?)\}", ts_src, re.S)
    assert m, "前端那张表扫不到（改了写法？本条会静默少比，必须红）"
    ts_keys = set(re.findall(r"^\s*(\w+):", m.group(1), re.M))
    assert py_keys == rule_keys, f"色表与类目规则分叉：只有色表有 {sorted(py_keys - rule_keys)}、" \
                                 f"只有规则有 {sorted(rule_keys - py_keys)}"
    assert py_keys == ts_keys, f"色表两端键集分叉：{sorted(py_keys ^ ts_keys)}"


def test_7b_values_match_key_by_key_across_languages():
    ts_src = TS_COLORS.read_text(encoding="utf-8")
    body = re.search(r"export const LC_CAT_COLOR: Record<string, string> = \{(.*?)\}", ts_src, re.S).group(1)
    ts_side = {k: v.strip().strip("'\"") for k, v in re.findall(r"^\s*(\w+):\s*([^,\n]+),?$", body, re.M)}
    for key, py_val in LC_CAT_COLOR.items():
        assert ts_side.get(key) == py_val, f"{key} 两端颜色分叉：后端 {py_val} vs 前端 {ts_side.get(key)}"


def test_8_colors_are_distinct_and_hex_shaped():
    assert len(set(LC_CAT_COLOR.values())) == len(LC_CAT_COLOR), "两色相同 ⇒「8 类各一色」是假话"
    for key, val in LC_CAT_COLOR.items():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", val), f"{key} 的颜色 {val!r} 不是 #RRGGBB 形态"


def test_9_no_default_color_escape_hatch():
    """取色只许经那颗函数；文件里对那张表的直接下标读只能有一处（就是函数体本身）。"""
    src = (BACKEND / "app" / "core" / "pipeline" / "diagnosis_templates.py").read_text(encoding="utf-8")
    direct = src.count("LC_CAT_COLOR[")
    assert direct == 1, (
        f"直接下标读色表 {direct} 处（应为 1：取色那颗函数内部）⇒ 又长出一个绕过闸门的取色点")
    assert _cat_color("medical") == LC_CAT_COLOR["medical"]
    with pytest.raises(KeyError):
        _cat_color("没有这个类目")


def test_9b_both_bar_charts_color_every_bar_from_the_table():
    rep = _report(KAILI)
    overview = next(c for c in _sections(rep)["overview"]["charts"]
                    if c["chart_id"] == "chart-overview-coverage")
    for bar, item in zip(reversed(KAILI["scores"]["bars"]), overview["option"]["series"][0]["data"]):
        assert item["itemStyle"]["color"] == LC_CAT_COLOR[bar["category"]]

    minutes = next(c for c in _sections(rep)["isochrone"]["charts"]
                   if c["chart_id"] == "chart-isochrone-minutes")
    cats = sorted((c for c in KAILI["poi"]["categories"] if c.get("min_minutes") is not None),
                  key=lambda c: c["min_minutes"])
    for cat, item in zip(reversed(cats), minutes["option"]["series"][0]["data"]):
        assert item["itemStyle"]["color"] == LC_CAT_COLOR[cat["category"]], (
            f"{cat['category']} 在耗时图上的色与覆盖度图不一致 ⇒ 同一个类目两张图两个颜色")


# ── ⑩ 焦点不进 charts：下游那几个数不许跟着漂 ────────────────────────────
def test_10_map_focus_is_not_a_chart(report):
    """`map_focus` 不是图件：`charts` 总数、每章图数上限、证据闭包都不该因它变化。"""
    chart_count = sum(len(s.get("charts") or []) for s in report["sections"])
    assert chart_count == 8, f"kaili 的图数从 8 变成 {chart_count} ⇒ 焦点被塞进 charts 了"
    for sid, s in _sections(report).items():
        assert len(s.get("charts") or []) <= 2, f"{sid} 章图数超上限"
        if s.get("map_focus"):
            assert "chart-map" not in json.dumps([c["chart_id"] for c in (s.get("charts") or [])])
    assert report["charts"] == [c for s in report["sections"] for c in (s.get("charts") or [])], (
        "报告顶层图清单与逐章图不一致 ⇒ 焦点被当成图并进了总表")


def test_11_offline_sections_call_no_map_focus_at_all():
    """离线骨架**不调**焦点构造器（test_13 在另一个文件里钉结果，这里钉机理）。"""
    offline = copy.deepcopy(KAILI)
    offline["data_origin"] = "offline"
    rep = _report(offline)
    assert not any("map_focus" in s for s in rep["sections"]), (
        "离线骨架开始带 map_focus 键 ⇒ 八章全表那两条缺席判据的基线要一起重看")
    assert _section_map_focus(offline, "medical") == _section_map_focus(KAILI, "medical"), (
        "焦点构造器读了 data_origin 却没人要求它读 ⇒ 两分支的行为差异没被登记")


def test_12_the_demo_mock_registers_the_same_two_tables():
    """演示态（`frontend/src/mocks/livingCircleReports.ts`）是这两张表在浏览器侧的第二份权威。
    跨语言导不了常量 ⇒ 两端各留一份就得有东西钉住它们相等 —— 手法照
    `test_fixture_mirror.py` 的「扫声明取名字集合再比」，不新造机制。

    为什么必须是永久闸而不是一次性探针：两端逐行 diff 的那种探针跑完就删，于是"后端加了章、
    演示态没跟"这条通道之后再也没有人守着，而它的症状只是演示态少一张图（屏幕上完全正常）。
    """
    ts = (BACKEND.parent / "frontend" / "src" / "mocks" / "livingCircleReports.ts").read_text(encoding="utf-8")

    def block(name: str) -> str:
        m = re.search(rf"const {name}: [^\n]*= \{{(.*?)\n\}}", ts, re.S)
        assert m, f"演示态里的 {name} 扫不到（改了写法？本条会静默少比，必须红）"
        return m.group(1)

    mock_kinds = set(re.findall(r"^\s+(\w+):", block("MAP_FOCUS_KINDS"), re.M))
    assert mock_kinds == set(MAP_FOCUS_KINDS), (
        f"分章地图的登记表两端分叉：只有后端有 {sorted(set(MAP_FOCUS_KINDS) - mock_kinds)}、"
        f"只有演示态有 {sorted(mock_kinds - set(MAP_FOCUS_KINDS))}")

    mock_chapter = dict(re.findall(r"^\s+(\w+):\s*'(\w+)',?$", block("CATEGORY_CHAPTER"), re.M))
    assert mock_chapter == CATEGORY_CHAPTER, (
        f"类目→章归属两端分叉：后端 {CATEGORY_CHAPTER} vs 演示态 {mock_chapter} "
        "⇒ 位置图与分章地图会各自挑一套类目")

    mock_chapter = dict(re.findall(r"^\s+(\w+):\s*'(\w+)',?$", block("CATEGORY_CHAPTER"), re.M))
    assert mock_chapter == CATEGORY_CHAPTER, (
        f"类目→章归属两端分叉：后端 {CATEGORY_CHAPTER} vs 演示态 {mock_chapter}")
