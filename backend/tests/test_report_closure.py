"""报告图文闭合契约（计划笔 6 的 B / 架构评审的"结构性防线"）。

为什么必须有这一条
──────────────────
用户最初的反馈是「生活圈报告没内容」。查下去根因不是字少，而是**数据算好了却没写进正文**：
  · `CATEGORY_RULES` 有 8 类、雷达图与 `scores.bars` 也是 8 类，而正文靠 `_cat(lc, key)`
    手工点取只覆盖 5 类 ⇒ 金融/文体/政务 三类有完整真实数据却一个字没写；
  · `scores.note`（哪一维被抬高、盲区外推扣了多少分）只被事件流消费，报告正文没引；
  · 每处盲区的 `affected`（受估户数/人数/采样点）、`reach.real_walk_min`、`fixes`
    （策略/优先级/替代点距离/可服务点数）全都躺在 payload 里，盲区章只有一句 61 字 + 一张表。

这三处都是**我这次肉眼查出来的**。没有一条测试会因为它们而红 —— 那下次数据面再扩张
（新类目、新盲区字段、新口径句）仍会以同样方式静默漏写。本文件把"漏写"变成 CI 会红。

判据口径
────────
只断「**该类目/该字段的标识或关键数值出现在正文里**」，**不断整句** —— 因为整句文案受
措辞红线与词汇闸门约束、会随评审改写，钉整句就会与 `test_fixture_mirror.py` 的逐字钉法
争真相源。轻量判据换来的是：改措辞不碰本文件，漏消费一定碰。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.pipeline.diagnosis_templates import (
    CATEGORY_CHAPTER, GAP_NOTE_CATEGORIES, assemble_report,
)

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"
# 带逐格台账的那一份（ev-2 起才有 cells_ledger）
LEDGER_FIXTURE = "kaili-ev2.json"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _all_prose(report: dict) -> str:
    """报告的全部人读文本：正文 + 核心判断 + 亮点 + 论点 + 表格单元格。

    表格也算消费：数据进了 `data_grid` 就是进了报告，不能因为它不在段落里就判"没用上"。
    """
    out: list[str] = []
    for s in report.get("sections") or []:
        out.extend(s.get("paragraphs") or [])
        out.append(s.get("key_takeaway") or "")
        out.extend(s.get("highlights") or [])
        for c in s.get("claims") or []:
            out.append(c.get("text") or "")
        g = s.get("data_grid") or {}
        for row in g.get("rows") or []:
            out.extend(str(v) for v in (row or {}).values())
        for ch in s.get("charts") or []:
            out.append(ch.get("title") or "")
    return "\n".join(out)


def _narrative(report: dict) -> str:
    """只取**叙述**（正文 / 核心判断 / 亮点），不含表格与图题。

    为什么单独要这一份：`data_grid` 表格从第一版就在，而用户仍然判「报告没内容」——
    所以"数字躺在表格里"不等于"报告把它说出来了"。受影响面这类必须进叙述才算消费。
    """
    out: list[str] = []
    for s in report.get("sections") or []:
        out.extend(s.get("paragraphs") or [])
        out.append(s.get("key_takeaway") or "")
        out.extend(s.get("highlights") or [])
    return "\n".join(out)


def _report(name: str) -> dict:
    return assemble_report(_payload(name), "lc-closure", f"key:{name}", "")


@pytest.mark.parametrize("fixture", ["kaili.json", LEDGER_FIXTURE, "beijing-jinsong.json"])
def test_every_populated_category_reaches_the_prose(fixture: str):
    """有数据的类目必须被正文引用 —— 这正是当初漏掉金融/文体/政务的那道口子。

    判据用类目 `label`（中文可读名）。label 不在正文出现 ⇒ 该类目对读者等于不存在，
    无论它背后有多少 POI。
    """
    lc = _payload(fixture)
    prose = _all_prose(_report(fixture))
    silent = [
        f"{c.get('category')}({c.get('label')}, 检索 {c.get('total')} / 圈内 {c.get('in_circle')})"
        for c in (lc.get("poi") or {}).get("categories") or []
        if int(c.get("total") or 0) > 0 and str(c.get("label") or "") not in prose
    ]
    assert not silent, (
        f"{fixture}：{len(silent)} 个类目有检索结果却没进正文 ⇒ 又是图 8 类、文 5 类那种漏写：{silent}"
    )


def test_score_note_is_surfaced_in_the_report():
    """`scores.note` 是评分口径的自证句，必须出现在报告正文里（此前只活在事件流）。

    逐字复制不改写：它的四条子分格式是承重结构，`test_living_circle_scoring.py` 与
    `eventFlowNumbersMatchFixture.test.ts` 都在解析同一份 note。
    """
    lc = _payload(LEDGER_FIXTURE)
    note = ((lc.get("scores") or {}).get("note") or "").strip()
    assert note, "夹具本身没有 scores.note ⇒ 本条会空转"
    prose = _narrative(_report(LEDGER_FIXTURE))
    assert note in prose, "评分口径句没进报告叙述 ⇒ 最有信息量的一句又留在没人看的地方"


def test_every_blindspot_surfaces_its_people_and_reach():
    """每处盲区的受影响面与实测步行耗时必须可见。

    ⚠️ 台账里**没有逐格步行分钟**（`nearest.{类}` 是直线米数，`real_walk_min` 只到
    盲区/POI 级）⇒ 任何"逐格耗时热力"都是编造，这条同时是造假红线。
    """
    lc = _payload(LEDGER_FIXTURE)
    bs = lc.get("blindspots") or []
    assert bs, "夹具没有盲区 ⇒ 本条会空转（换夹具或补夹具，不要放宽判据）"
    prose = _narrative(_report(LEDGER_FIXTURE))
    for b in bs:
        # 先钉"这一处被逐一点名"：只写"盲区合计受估 N 人"的汇总句也能过下面两条数值断言
        # （单盲区夹具下总数恰好等于该处），那样就分辨不出"逐处说了"与"只说了合计"。
        assert str(b.get("id")) in prose, (
            f"盲区 {b.get('id')} 未被逐一点名 ⇒ 正文只有汇总数，读者不知道哪一处压着多少人")
        aff = b.get("affected") or {}
        if aff.get("estimated_residents"):
            assert str(aff["estimated_residents"]) in prose, (
                f"盲区 {b['id']} 的受估人数 {aff['estimated_residents']} 没进正文")
            # 人数必须带"非真实人口"口径（report_contract 硬判据 provenance=proxy）
            assert "非真实人口数据" in prose, "受估人数缺少『非真实人口数据』限定 ⇒ 会被读成统计事实"
        reach = b.get("reach") or {}
        if reach.get("real_walk_min"):
            assert str(reach["real_walk_min"]) in prose, (
                f"盲区 {b['id']} 的实测步行 {reach['real_walk_min']}min 没进正文")


def test_every_fix_prescription_surfaces_priority_and_strategy():
    """补点处方的策略与优先级必须可见 —— 整改建议不能只剩一句"建议补建"。"""
    lc = _payload(LEDGER_FIXTURE)
    rows = [(fx, b) for b in (lc.get("blindspots") or []) for fx in (b.get("fixes") or [])]
    assert rows, "夹具没有处方 ⇒ 本条会空转"
    rep = _report(LEDGER_FIXTURE)
    prose = _all_prose(rep)
    for fx, b in rows:
        assert str(fx.get("priority")) in prose, f"{b['id']} 处方优先级 P{fx.get('priority')} 未进正文"
        assert str(fx.get("facility")) in prose, f"{b['id']} 处方设施 {fx.get('facility')} 未进正文"


def test_ledger_counts_are_surfaced_when_present():
    """有台账就必须报格数账：可达区内 / 出到结论 / 判盲 三个数都要在正文里。

    无台账的旧快照走另一条路（不印、也不印 0）—— 那由 `test_no_ledger_is_not_fabricated` 守。
    """
    lc = _payload(LEDGER_FIXTURE)
    led = (lc.get("caliber") or {}).get("cells_ledger") or {}
    assert led, "夹具没有台账 ⇒ 本条会空转"
    prose = _narrative(_report(LEDGER_FIXTURE))
    n = led["n"]
    assert f"{n}×{n}" in prose, "逐格台账的格阵规模没进叙述"
    assert "判盲" in prose and "未定" in prose, "台账五档里至少判盲/未定必须分别可见（不许合并成『没结论』）"


@pytest.mark.parametrize("fixture", ["kaili.json", "beijing-jinsong.json"])
def test_no_ledger_is_not_fabricated(fixture: str):
    """没有台账就不许出现格阵读数 —— 把"不知道"印成"0 格"是同一类造假。"""
    lc = _payload(fixture)
    assert not ((lc.get("caliber") or {}).get("cells_ledger")), (
        f"{fixture} 现在带台账了 ⇒ 本条判据失效，请改回/换一份无台账的载荷来守这条")
    prose = _all_prose(_report(fixture))
    assert "判定格阵" not in prose, "无台账载荷却印了格阵读数"


def test_chapter_registry_covers_every_category_or_it_goes_to_panorama():
    """`CATEGORY_CHAPTER` 与 `GAP_NOTE_CATEGORIES` 必须是 `CATEGORY_RULES` 的子集。

    防的是：注册表里写了个不存在的类目名（拼错/类目改名），于是那一类既没专项章、
    也不会被全景段正确点名 —— 漏写换了个地方复发。
    """
    from app.living_circle.category_rule import CATEGORY_RULES

    assert set(CATEGORY_CHAPTER) <= set(CATEGORY_RULES), (
        f"CATEGORY_CHAPTER 含未知类目：{sorted(set(CATEGORY_CHAPTER) - set(CATEGORY_RULES))}")
    assert set(GAP_NOTE_CATEGORIES) <= set(CATEGORY_RULES), (
        f"GAP_NOTE_CATEGORIES 含未知类目：{sorted(set(GAP_NOTE_CATEGORIES) - set(CATEGORY_RULES))}")
    # 缺口注记只能挂在有专项章的类目上：全景段不重复交代，专项章才有位置说它
    assert set(GAP_NOTE_CATEGORIES) <= {k for k, v in CATEGORY_CHAPTER.items() if v == k}, (
        "GAP_NOTE_CATEGORIES 必须是「自成一章」的那些类目，否则缺口注记没有落点")
