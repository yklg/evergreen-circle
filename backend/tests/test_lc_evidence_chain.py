"""生活圈证据链地基（附录 G-16 / G-21 / G-22，第二片 E0-1，TC-22 / TC-28 / TC-29）。

第二片要「逐章撰写」，前提是**证据链是真的**。今天的地基有三处空洞，本文件把它们
钉成可执行事实（前两条今天即为真，第三条起为登记缺口）：

1. **LC 证据不落库**：调研侧 `db.save_report` 会逐条 `INSERT INTO evidences`
   （`db.py:711-723`），而生活圈侧 `db.save_living_circle_report`（`db.py:1326`）
   **只写 `living_circle_reports.data` 一个 JSON**，证据随正文一起躺在快照里。
   ⇒ `GET /api/evidences` 查不到任何一份体检报告的出处。
2. **引用强制过滤器对 LC 是"全清"**：`schemas._filter_eids(raw, valid)` 只保留
   `valid` 里的 eid（`schemas.py:49-50`，注释自陈"引用强制 = 幻觉抑制"）。
   `valid` 由证据表构造 ⇒ LC 的 `ev-lc-poi-*` 一个都不在里面 ⇒ 一旦接调研 machinery，
   所有 LC 引用被清空 ⇒ 论点全判 unverified。**不是"少了几条引用"，是整份报告失去论证。**
3. **置信度阶梯不看数据来源**：`make_claim` 只看 eid 数与独立信源组
   （`models.py:95-104`），`data_origin` / `caliber.measured` / `degraded` 均不在参数里
   ⇒ 一份离线估算或中途降级的报告可以名正言顺出 high。E0-1 要求 `computed` 证据的
   置信度由口径实测状态与数据来源决定。

顺带钉住本项目**已有**的诚实法（D9 正是引它为先例）：离线报告 `total_score` 存 NULL，
不伪造 0 分（`db.py:1329-1336`）—— 同一条法在游客档上要落到 `scores | null`。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.core import db
from app.core import schemas as S
from app.core.models import make_claim
from app.core.pipeline.diagnosis_templates import assemble_report

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"


def _lc_report(report_id: str = "lc-evidence-chain") -> dict:
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    return assemble_report(lc, report_id, f"key:{report_id}", "证据链地基用例")


def _lc_eids(report: dict) -> set:
    return {e["evidence_id"] for e in report["evidence"]}


# ── 1. 现状事实：LC 证据不落证据表 ────────────────────────────────


def test_lc_evidences_never_reach_the_evidence_table():
    """**现状记录（E0-1 的根因）**：体检报告落库后，证据表里一条都查不到。

    报告快照里明明有 9+ 条 `ev-lc-*` 证据，`evidences` 表却为空 ⇒ 全局证据库、
    溯源检索、`/api/evidences` 对体检报告全部无从谈起。
    """
    report = _lc_report("lc-chain-absent")
    db.save_living_circle_report(report, scene_key="key:lc-chain-absent")
    assert _lc_eids(report), "样本报告应带 ev-lc-* 证据，否则本用例空转"
    rows = db.query_evidences(report_id="lc-chain-absent")
    assert rows == [], (
        f"证据表已能收到 LC 证据（{len(rows)} 行）—— E0-1 已落地，"
        "请把本用例改为「必须落库」的正向断言，并删除配套的 xfail"
    )


def test_reference_filter_clears_every_lc_eid():
    """**现状记录（第二片阻断项）**：引用过滤器会把 LC 的 eid 全量清空。

    `valid` 按既有做法由证据表构造；LC 证据不在表里 ⇒ 交集为空。这条与上一条
    成对，说明"接调研 machinery"不是免费的：不先修证据底座，逐章撰写产出的
    每一个引用都会被幻觉抑制机制判为无源。
    """
    report = _lc_report("lc-chain-filter")
    db.save_living_circle_report(report, scene_key="key:lc-chain-filter")
    valid = {r["evidence_id"] for r in db.query_evidences(report_id="lc-chain-filter")}
    eids = sorted(_lc_eids(report))
    kept = S._filter_eids(eids, valid)
    assert kept == [], (
        f"过滤器已能保留 LC 引用（{kept}）⇒ E0-1 已落地，本用例须重指为「引用必须全保留」"
    )


def test_offline_report_stores_null_total_score_not_zero():
    """既有诚实法（P0-2）：离线估算不落可比评分，`total_score` 必须是 NULL。

    D9 选 `scores | null` 表达「本档未评」正是引这条为先例 —— 先把先例钉牢，
    游客档的"未评"才有同源依据，而不是新发明一套。
    """
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    lc["data_origin"] = "offline"
    report = assemble_report(lc, "lc-chain-offline", "key:lc-offline", "离线诚实性用例")
    db.save_living_circle_report(report, scene_key="key:lc-offline")
    row = db.get_living_circle_report("lc-chain-offline")
    assert row is not None
    brief = next(
        # include_incomplete=True：本用例只管「未评不得伪造成分数」，
        # 不把几何契约（另一套判据，见 report_contract.assess_geometry）混进来当干扰项。
        (r for r in db.list_living_circle_reports(limit=200, include_incomplete=True)
         if r.get("id") == "lc-chain-offline"),
        None,
    )
    assert brief is not None, "离线报告应在审计全量列表里（只隐藏评分，不隐藏记录）"
    assert brief["data_origin"] == "offline"
    assert brief["total_score"] is None, f"离线报告不得有评分，实得 {brief['total_score']!r}"


# ── 2. 登记缺口：E0-1 落地后自动转绿 ─────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="E0-1：computed 证据必须写入既有 evidences 表（不新建第二张证据表）",
)
def test_lc_computed_evidences_are_queryable_by_report():
    """体检报告的每条证据都应能按 report_id 查回，并带 `computed` 语义的类型标记。"""
    report = _lc_report("lc-chain-written")
    db.save_living_circle_report(report, scene_key="key:lc-chain-written")
    rows = db.query_evidences(report_id="lc-chain-written")
    assert {r["evidence_id"] for r in rows} == _lc_eids(report)
    assert any(r["source_type"] == "api_measure" for r in rows)


@pytest.mark.xfail(
    strict=True,
    reason="E0-1：测量值不该套网页来源的 credibility 公式，置信度须由 caliber.measured + data_origin 决定",
)
def test_offline_or_degraded_report_cannot_produce_high_confidence_claims():
    """降级/离线报告的论点必须降为 low / unverified，不得出 high。"""
    claim = make_claim(
        "c-offline", "15 分钟内有 25 处医疗设施", "coverage",
        ["ev-lc-poi-medical", "ev-lc-measure"], "L3-001", independent_groups=2,
        data_origin="offline",   # ← E0-1 要求阶梯看见来源
    )
    assert claim.confidence in {"low", "unverified"}, f"离线报告出出了 {claim.confidence}"


def test_current_ladder_takes_no_data_origin_signal():
    """**现状记录**：置信度阶梯的入参里没有任何"数据从哪来"的信号。

    与上一条配对：先证明 high 与降级无关（不是某次调用写错，而是函数**看不见**降级），
    修好阶梯后本用例应红并提示重指判据 —— 而不是让 xfail 标记长住。
    """
    params = set(inspect.signature(make_claim).parameters)
    assert not ({"data_origin", "caliber", "measured", "degraded"} & params), (
        f"阶梯已能接收来源信号 {sorted(params)}，请把本用例改为正向断言"
    )
    claim = make_claim(
        "c-blind", "同一结论", "coverage", ["ev-a", "ev-b"], "L3-001", independent_groups=2
    )
    assert claim.confidence == "high", "阶梯语义若已变，须同步重指上一条缺口用例"
