"""章级自有亮点的契约（2026-10-08 方案 C 档）—— 反「把同一句话平播到各章」。

治的缺陷：预览包那份「激进档」的 13 条亮点里 8 条是生成脚本 `hl[:1]` / `hl[:2]` 把概览
那两句全局句广播到医疗/教育/菜市/养老/等时圈五章（`gen_preview.py:569/573-574`）。
照抄进生产 = 同一句话在一份报告里出现五遍。落地形态改成**每章从本章数据派生自己的句子**，
本文件就是钉住这件事的判据集。

判据分层（编号接在计划 `plain-islet-karp.md` 的「判据」节）：
 ① 章级自有句互不相同，且都不等于三条全局句 —— 反平播主闸；
 ② 归属锚：每条自有句必须命中本章 `_HIGHLIGHT_ANCHORS` 里的词；
 ③ 不复述本章正文：亮点不许是本章任一paragraphs 的子串；
 ④ 不重述全局句的类目对（**纯结构判据，不解析任何句子**）；
 ⑤ 缺席分支：并列满分 / 并列垫底 / 全体相等 / 取不到最近点 / 缺等时圈档 ⇒ 该条不产；
 ⑥ 每章 ≤2 条上限；
 ⑦ 三集合登记（该登记必登记）；
 ⑮ 亮点里"长得像测量值"的数字必须能回溯到载荷；
 ⑯ 每条亮点是非空 str。

⚠️ 判据 ① 的范围刻意**不含**三条全局句彼此：概览章与结论章共用 `spread` 句是 nar-1
   就存在的设计（概览报全局对比、结论再引一次），把它算进来会把既有形态判红。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.pipeline.diagnosis_templates import (
    _HIGHLIGHT_ANCHORS, _chapter_highlight_items, _highlight_items,
    _section_highlights, assemble_report,
)

FIXTURE = (Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures" / "kaili.json")
KAILI: Dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))

# 有自有亮点的章（其余章走全局键，不在本文件的归属锚范围内）
CHAPTER_SIDS = ("medical", "education", "market", "elderly", "isochrone")


def _items(lc: Dict[str, Any]) -> Dict[str, List[str]]:
    return _chapter_highlight_items(lc)


def _all_chapter_sentences(lc: Dict[str, Any]) -> List[str]:
    return [s for sid in CHAPTER_SIDS for s in _items(lc).get(sid, [])]


def _global_sentences(lc: Dict[str, Any]) -> List[str]:
    return list(_highlight_items(lc).values())


# ── ① ②  ⑥  在真实夹具上逐条过 ────────────────────────────────────
@pytest.fixture(scope="module")
def report():
    return assemble_report(json.loads(json.dumps(KAILI)), "lc-hl", "k", "")


def test_1_chapter_sentences_are_never_the_broadcast_global_ones(report):
    got = _all_chapter_sentences(KAILI)
    assert got, "一份凯里载荷连一条自有亮点都没产 ⇒ 下面全是恒真断言，本文件白写"
    assert len(set(got)) == len(got), f"章级自有句内部重复：{got}"
    clash = [s for s in got if s in _global_sentences(KAILI)]
    assert not clash, f"章级句与全局句逐字相同 ⇒ 又回到平播：{clash}"


def test_2_every_chapter_sentence_hits_its_own_anchor(report):
    items = _items(KAILI)
    assert set(items) == set(_HIGHLIGHT_ANCHORS), "注册表与归属表的章集不一致（见判据 7）"
    for sid in CHAPTER_SIDS:
        anchors = _HIGHLIGHT_ANCHORS[sid]
        for sentence in items[sid]:
            assert any(a in sentence for a in anchors), (
                f"{sid} 章的亮点「{sentence}」不含本章任何一个归属锚 {anchors} ⇒ 它讲的不是本章的事，"
                "或者就是又从别处抄来的")


def test_3_no_chapter_sentence_repeats_this_chapter_prose(report):
    for sec in report["sections"]:
        sid = sec["id"]
        if sid not in CHAPTER_SIDS:
            continue
        for sentence in sec.get("highlights") or []:
            assert not any(sentence in p for p in sec.get("paragraphs") or []), (
                f"{sid} 章的亮点是本章正文某段的子串 ⇒ 同一件事在一章里说两遍")


def test_4_no_chapter_sentence_restates_a_global_category_pair():
    """纯结构判据：比的是「句子里出现了哪几个类目名」这个集合，不解析任何句子的措辞。

    为什么不能写成"不得含 spread 句的两个极值类目名"：那要先去解析那句全局句子，
    正面撞 `_highlight_items` 自己定的规矩 —— 按主题返回、各章按键取，不用字符串嗅探挑归属。
    为什么只拿全局句当禁令、不拿"概览 vs 结论"开刀：那两章共用 `spread` 句是 nar-1 就有的
    设计（概览报全局对比、结论再引一次），把它算进来会把既有形态判红，而本文件只管新加的这族。
    """
    labels = [b.get("label", "") for b in (KAILI.get("scores") or {}).get("bars") or []]

    def pair_of(sentence: str) -> frozenset:
        return frozenset(l for l in labels if l in sentence)

    banned = {p for p in (pair_of(s) for s in _global_sentences(KAILI)) if len(p) >= 2}
    seen: Dict[frozenset, str] = {}
    checked = 0
    for sid in CHAPTER_SIDS:
        for sentence in _items(KAILI)[sid]:
            pair = pair_of(sentence)
            if len(pair) < 2:
                continue                     # 单类目或无类目：没有"对"可撞
            checked += 1
            assert pair not in banned, (
                f"{sid} 章的亮点含全局句已用过的类目对 {sorted(pair)} ⇒ 同一件事换个地方再说一遍")
            assert pair not in seen, (
                f"{sid} 章与 {seen[pair]} 章的亮点含同一对类目名 {sorted(pair)} ⇒ 一句话被讲了两遍")
            seen[pair] = sid
    assert checked, "一条含类目对的句子都没扫到 ⇒ 本条对它是恒真"


def test_6_at_most_two_highlights_per_chapter(report):
    for sec in report["sections"]:
        assert len(sec.get("highlights") or []) <= 2, f"{sec['id']} 章亮点超过 2 条"


def test_16_every_highlight_is_a_non_empty_string(report):
    for sec in report["sections"]:
        for h in sec.get("highlights") or []:
            assert isinstance(h, str) and h.strip(), (
                f"{sec['id']} 章有亮点不是非空字符串（{h!r}）⇒ 前端会渲染出 [object Object] 或空气泡")


def test_7_registration_is_closed_across_three_sets():
    """该登记必登记：三处集合两两相等，漏一处就是静默漏报。

    抄本仓现成范式 `test_living_circle_api.py::test_caliber_axes_are_registered_everywhere_they_must_be`。
    没有这条，日后加一个专题章却忘了给归属表加键 ⇒ 那章的亮点**没有锚可判**，
    判据 ② 对它静默放行，屏幕上看起来一切正常。
    """
    produced = set(_items(KAILI))
    assert produced == set(_HIGHLIGHT_ANCHORS), (
        f"注册表键集 {sorted(produced)} ≠ 归属表键集 {sorted(_HIGHLIGHT_ANCHORS)}")
    wired = {s["id"] for s in assemble_report(json.loads(json.dumps(KAILI)), "r", "k", "")["sections"]
             if s["id"] in CHAPTER_SIDS}
    assert wired == produced, f"装配器里在场的章 {sorted(wired)} 与注册表 {sorted(produced)} 不闭合"


# ── ⑮ 数字必须能回溯到载荷 ───────────────────────────────────────────
def _payload_number_atoms(lc: Dict[str, Any]) -> List[float]:
    out: List[float] = []
    for b in (lc.get("scores") or {}).get("bars") or []:
        out.append(float(b.get("value", 0)))
    for c in (lc.get("poi") or {}).get("categories") or []:
        for key in ("min_minutes", "in_circle", "total", "required_in_circle"):
            if c.get(key) is not None:
                out.append(float(c[key]))
    for z in lc.get("isochrones") or []:
        if z.get("area_km2") is not None:
            out.append(float(z["area_km2"]))
        if z.get("minutes") is not None:
            out.append(float(z["minutes"]))
    for t in (lc.get("scores") or {}).get("triads") or []:
        if t.get("nearest_minutes") is not None:
            out.append(float(t["nearest_minutes"]))
    for b in lc.get("blindspots") or []:
        est = (b.get("affected") or {}).get("estimated_residents")
        if est is not None:
            out.append(float(est))
    return out


def _allowed_numbers(lc: Dict[str, Any]) -> List[float]:
    """载荷原子 ∪ 两两差 ∪ 两两商 —— 句子里允许出现的"测量值"闭包。"""
    atoms = _payload_number_atoms(lc)
    allowed = list(atoms)
    for a in atoms:
        for b in atoms:
            allowed.append(abs(a - b))
            if b:
                allowed.append(round(a / b, 1))
    return allowed


def test_15_measurement_numbers_in_chapter_sentences_trace_back_to_the_payload():
    """只查"长得像测量值"的数（带小数点或两位以上整数）；个位整数按计数放行。

    为什么放个位整数：名次、类数、"其余 7 类"这类计数是派生事实，不是测量值；
    把它们也钉进闭包只会逼着判据越长越像实现，反而没人敢改措辞。
    为什么这条值得存在：报告是"实体产出的信息"（IPE），屏上每个测量值都要能回算到源数据 ——
    这类不变量最适合 property-based，但本仓 hypothesis 未安装（见
    `test_evidence_digest_pinned.py` 头注），故沿用该文件先例用**参数化穷举**替代。
    """
    allowed = _allowed_numbers(KAILI)
    for sentence in _all_chapter_sentences(KAILI):
        for token in re.findall(r"\d+\.\d+|\d{2,}", sentence):
            value = float(token)
            assert any(abs(value - a) < 0.006 for a in allowed), (
                f"亮点「{sentence}」里的 {token} 既不是载荷里的数，也不是两数之差/商 ⇒ 编造读数")


# ── ⑤ 缺席分支：无据可讲时必须**不产**该条 ────────────────────────────
def _bars(lc: Dict[str, Any], values: List[float]) -> Dict[str, Any]:
    lc = copy.deepcopy(lc)
    lc["scores"]["bars"] = [{"category": b["category"], "label": b["label"], "value": v}
                            for b, v in zip(lc["scores"]["bars"], values)]
    return lc


def _drop_minutes(lc: Dict[str, Any], category: str) -> Dict[str, Any]:
    lc = copy.deepcopy(lc)
    for c in lc["poi"]["categories"]:
        if c["category"] == category:
            c["min_minutes"] = None
    return lc


def test_5_absence_branches_produce_no_sentence_rather_than_a_false_one():
    """五种"没据可讲"的形态，逐一确认该条**不产**，而不是产出一句假话。

    判据只数条数会放过假话，所以每条都点名它该闭嘴的那句话：并列满分不许说「唯一最高」、
    并列垫底不许说「唯一垫底」、全体相等不许谈位置、取不到最近点不许排名次、缺档不许算倍率。
    """
    values = [float(b["value"]) for b in KAILI["scores"]["bars"]]
    assert len({v for v in values if v == max(values)}) == 1 and values.count(max(values)) > 1, (
        "前提：凯里本来就是多类并列满分 ⇒ 「不许说唯一最高」这条在真实夹具上就有牙")
    assert not [s for s in _chapter_highlight_items(KAILI)["medical"] if "最高" in s], (
        "六类并列 100 分却仍产「唯一最高」句 ⇒ 假话")

    all_equal = _bars(KAILI, [77.0] * len(values))
    for sid in ("medical", "education", "elderly"):
        assert not [s for s in _chapter_highlight_items(all_equal)[sid] if "序列" in s], (
            f"8 类覆盖度全相等时 {sid} 章仍谈序列位置 ⇒ 位置没有任何信息")

    tied_bottom = _bars(KAILI, [0.0 if b["category"] in ("elderly", "medical") else float(b["value"])
                                for b in KAILI["scores"]["bars"]])
    assert not [s for s in _chapter_highlight_items(tied_bottom)["elderly"] if "垫底" in s], (
        "两类并列最低却写「唯一垫底」⇒ 假话")

    no_minutes = _drop_minutes(KAILI, "medical")
    assert not [s for s in _chapter_highlight_items(no_minutes)["medical"] if "排第" in s], (
        "取不到最近点仍报耗时位次 ⇒ 位次是从没测过的东西")

    no_iso = copy.deepcopy(KAILI)
    no_iso["isochrones"] = [z for z in no_iso["isochrones"] if z.get("minutes") != 5]
    assert len(no_iso["isochrones"]) < len(KAILI["isochrones"]), "前提：这份载荷确实缺 5 分钟档"
    assert not [s for s in _chapter_highlight_items(no_iso)["isochrone"] if "倍" in s], (
        "缺 5 分钟档却仍算倍率 ⇒ 除零或凭空造数")
