"""逐章产出的不变量四类（EXT-1，附录 G-20，第二片 E1，TC-26）。

第二片要把体检报告从 ~900 字加到逐章撰写。测非确定性 LLM 输出的唯一可行做法是
**不写死期望文本**，改为断言四类不变量（外部经验 EXT-1）：

| 类别 | 判据 | 抓的是哪类事故 |
|---|---|---|
| ① 可解析 | 结构存在、层级正确 | 章节丢失 / 空壳报告 |
| ② Schema 合法 | 字段类型与枚举闭集 | 前端渲染崩、跨端契约漂移 |
| ③ 业务范围 | 数值落在合法区间且**口径自洽** | 覆盖率 37%、分钟数负数 |
| ④ 禁止内容 | 不出现编造指标、不出现无源引用 | 幻觉进正文、进而进导出与答辩 |

本文件把四类写成**可复用的检查器** `assert_chapter_invariants()`，今天先套在
`diagnosis_templates.assemble_report` 产出的确定性报告上（跑通即证明检查器本身可用，
不是等 E1 落地才有测试）。E1 的 LLM 逐章产出必须过同一个检查器 —— 该接线登记为 xfail。

注意：检查器只断言**形状、闭集与区间**，绝不比对具体措辞；这正是 EXT-1 的用意，
否则每次改文案都要改测试，测试就会退化成被删掉的那个断言。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.pipeline.diagnosis_templates import assemble_report
from app.living_circle import caliber_index

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"

# 跨端契约的必填集只有这三格（`types.ts:202-222 ReportSection`，其余全为可选）
# ⇒ ① 的判据只能是「必填在 + 本章有实质内容」，不得把可选件当成必填（否则
#   检查器会把一份合规报告判成违规，E1 落地时只会被人改掉而不是被绕过）。
REQUIRED_SECTION_KEYS = {"id", "title", "level"}
CLAIM_KEYS = {"claim_id", "text", "field", "evidence_ids", "confidence", "cross_validated", "author"}
CONFIDENCE_CLOSED = {"unverified", "low", "medium", "high"}
CHART_KEYS = {"chart_id", "type", "title", "option"}


def _report() -> Dict[str, Any]:
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    return assemble_report(lc, "lc-invariants", "key:lc-invariants", "不变量用例")


def assert_chapter_invariants(report: Dict[str, Any]) -> None:
    """四类不变量检查器（E1 逐章产出必须过这里，不另立一套口径）。"""
    sections: List[Dict[str, Any]] = report.get("sections") or []
    # ① 可解析
    assert sections, "报告没有任何章节 ⇒ 空壳产物，一律不接受"
    eids = {e["evidence_id"] for e in (report.get("evidence") or [])}
    assert eids, "报告无证据集 ⇒ 无从校验引用，检查器会空转"
    chart_ids: set = set()

    for s in sections:
        missing = REQUIRED_SECTION_KEYS - set(s)
        assert not missing, f"章节 {s.get('id')!r} 缺必填字段 {sorted(missing)}（① 可解析）"
        assert isinstance(s["level"], int) and 1 <= s["level"] <= 4
        substance = bool(s.get("paragraphs")) or bool(s.get("key_takeaway")) or bool(
            s.get("structured") or s.get("data_grid") or s.get("charts")
        )
        assert substance, f"章节 {s['id']} 无任何实质内容 ⇒ 空壳章节（①）"
        # ② Schema 合法（可选件出现时必须类型正确）
        paragraphs = s.get("paragraphs")
        if paragraphs is not None:
            assert isinstance(paragraphs, list) and all(
                isinstance(p, str) and p.strip() for p in paragraphs
            ), f"章节 {s['id']} 的 paragraphs 不是非空 str 列表（②）"
        highlights = s.get("highlights")
        if highlights is not None:
            assert isinstance(highlights, list) and all(
                isinstance(h, str) and h.strip() for h in highlights
            ), f"章节 {s['id']} 的 highlights 不是非空 str 列表（②）"
        charts = s.get("charts") or []
        # 每章 ≤2 图：这是**生产侧构造约束**，不在渲染层截断 —— 本仓已反复拆掉
        # "渲染侧静默第二权威"（见 LifeCircleReportView.tsx:113-114 那段 cap 撤除记录），
        # 所以超了就该红，而不是悄悄丢几张图让读者以为报告只有这些。
        assert len(charts) <= 2, f"章节 {s['id']} 挂了 {len(charts)} 张图（>2）⇒ 单章图数失控"
        for chart in charts:
            assert CHART_KEYS <= set(chart), f"图表缺字段 {sorted(CHART_KEYS - set(chart))}（②）"
            # chart_id 是前端 React key（LifeCircleReportView.tsx:765）⇒ 重复会复用错图
            cid = chart["chart_id"]
            assert cid not in chart_ids, f"chart_id {cid!r} 重复（②）⇒ 渲染层 key 碰撞"
            chart_ids.add(cid)
            # 图的 evidence_ids 驱动 VChart.tsx:38-45 的「跳转证据」按钮，悬空即点了没反应
            for bad in set(chart.get("evidence_ids") or []) - eids:
                raise AssertionError(f"图表 {cid} 引用了不存在于证据集的 {bad!r}（④）")
        for bad in set(s.get("source_evidence_ids") or []) - eids:
            raise AssertionError(f"章节 {s['id']} 引用了不存在于证据集的 {bad!r}（④ 禁止内容）")

        # ④ 禁止内容：编造指标名不得出现在正文。
        # ⚠️ highlights 必须一起扫：它是报告新上的字段，漏在扫描外就等于亮点可以随便写
        #    未授权指标名，而闸门对整份报告"全绿"（评审 P0-4）。
        prose = " ".join(list(paragraphs or []) + [s.get("key_takeaway") or ""] + list(highlights or []))
        problems = caliber_index.validate_vocabulary(prose)
        assert not problems, f"章节 {s['id']} 含未授权指标术语（④）：{problems}"

        for c in s.get("claims") or []:
            assert CLAIM_KEYS <= set(c), f"论点缺字段 {sorted(CLAIM_KEYS - set(c))}（②）"
            assert c["confidence"] in CONFIDENCE_CLOSED, (
                f"confidence={c['confidence']!r} 不在闭集 {sorted(CONFIDENCE_CLOSED)}（②）"
            )
            dangling = set(c["evidence_ids"]) - eids
            assert not dangling, f"论点 {c['claim_id']} 无源引用 {sorted(dangling)}（④）"

    # ③ 业务范围
    lc = report["living_circle"]
    scores = lc.get("scores") or {}
    if scores:
        assert 0.0 <= float(scores["total"]) <= 100.0, f"总分越界 {scores['total']}（③）"
        for r in scores.get("radar") or []:
            assert 0.0 <= float(r["score"]) <= 100.0, f"维度分越界 {r}（③）"
    for cat in (lc.get("poi") or {}).get("categories") or []:
        cov = cat.get("coverage")
        assert cov is None or 0.0 <= float(cov) <= 1.0, f"coverage={cov} 越界（③）"
        mm = cat.get("min_minutes")
        assert mm is None or float(mm) >= 0, f"min_minutes={mm} 为负（③）"
        assert int(cat["in_circle"]) <= int(cat["total"]), "圈内数大于采集总数（③ 口径不自洽）"
    assert (lc.get("poi") or {}).get("in_circle") == sum(
        int(c["in_circle"]) for c in (lc.get("poi") or {}).get("categories") or []
    ), "POI 守恒被破坏（③）"


def test_deterministic_report_passes_the_four_invariant_classes():
    """检查器可用：今天的确定性报告已过四类（说明判据没有过严到不可实现）。"""
    assert_chapter_invariants(_report())


def test_checker_is_sensitivity_tested_not_a_no_op():
    """反向对照：检查器必须真的会红。四类各造一个违规样本，逐个必须被抓。

    没有这条，上面那条可以靠"什么都不检查"轻松通过 —— EXT-1 的四类若无一有牙，
    就等于把断言注释掉了。
    """
    base = _report()

    hollow = json.loads(json.dumps(base))
    for k in ("paragraphs", "key_takeaway", "charts", "source_evidence_ids"):
        hollow["sections"][0].pop(k, None)
    with pytest.raises(AssertionError, match="空壳章节"):
        assert_chapter_invariants(hollow)

    bad_schema = json.loads(json.dumps(base))
    bad_schema["sections"][0]["paragraphs"] = "段落写成了裸字符串"
    with pytest.raises(AssertionError, match="非空 str 列表"):
        assert_chapter_invariants(bad_schema)

    bad_range = json.loads(json.dumps(base))
    bad_range["living_circle"]["scores"]["total"] = 137.0
    with pytest.raises(AssertionError, match="总分越界"):
        assert_chapter_invariants(bad_range)

    bad_caliber = json.loads(json.dumps(base))
    cat0 = bad_caliber["living_circle"]["poi"]["categories"][0]
    cat0["in_circle"] = int(cat0["total"]) + 5
    with pytest.raises(AssertionError, match="圈内数大于采集总数|守恒"):
        assert_chapter_invariants(bad_caliber)

    bad_dangling = json.loads(json.dumps(base))
    for s in bad_dangling["sections"]:
        for c in s.get("claims") or []:
            c["evidence_ids"] = ["ev-does-not-exist"]
            break
    with pytest.raises(AssertionError, match="无源引用"):
        assert_chapter_invariants(bad_dangling)

    bad_vocab = json.loads(json.dumps(base))
    bad_vocab["sections"][0]["paragraphs"][0] = "本次体检的测时成功率达 98%。"
    with pytest.raises(AssertionError, match="未授权指标术语"):
        assert_chapter_invariants(bad_vocab)


def _writer_call_sites() -> List[str]:
    """AST 扫生产代码里调用检查器的位置（接线判据）。"""
    app_root = Path(__file__).resolve().parents[1] / "app"
    sites: List[str] = []
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in {"assert_chapter_invariants", "check_chapter_invariants"}:
                    sites.append(f"{path.relative_to(app_root)}:{node.lineno}")
    return sites


def test_invariant_checker_has_no_production_caller_yet():
    """**现状记录**：检查器只存在于测试里，撰写路径未接。"""
    assert _writer_call_sites() == [], (
        "检查器已接入生产 ⇒ 本用例须改为正向断言，"
        "并补一条「桩 LLM 输出过不了四类即被打回」的端到端用例"
    )


@pytest.mark.xfail(
    strict=True,
    reason="E1：逐章撰写必须以四类不变量为闸（违规打回或降 unverified），当前生产路径无调用者",
)
def test_writer_path_enforces_the_invariant_checker():
    """缺口登记：扫描范围限定 `app/**` ⇒ E1 落地时必须把检查器**移进生产侧**（如
    `core/pipeline/` 的章节校验模块），测试从那里 import，而不是各自复刻一份判据
    ——「判据在生产侧和测试侧各写一份」正是本仓 `poi.py` 守恒自检曾经踩过的坑。
    """
    assert _writer_call_sites(), "撰写/签发路径未接四类不变量检查器"
