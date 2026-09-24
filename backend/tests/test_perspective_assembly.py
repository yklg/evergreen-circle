"""rough-cliff-vole · 装配与双层硬约束钉（VR-D 组 + VR-E1/E3 提示侧）。

守护契约：
  VR-D1 不造数守卫：verified 声称但引用不出真实证据 id → 强制降「待核验」
  VR-D2 行守恒 seed：LLM 多报/漏报行一律不改行集（行=冻结榜，序=榜序）
  VR-D4 防回潮负钉：_enforce_dest_rows 不得动视角块行（组级 destination 匹配、行级不滤）
  VR-D5 matched=False 景点行也进表（行守恒覆盖长尾）
  VR-D6/D7 rules 必须引用问卷字段+真实证据、≤5；packing 无证据项剔除
  VR-E1 硬约束断言矩阵：每个问卷字段值逐个钉「出现在写稿提示」
  VR-E3 质检越约束检查段只随约束注入（非亲子零波及）
"""
import pytest

from app.core import llm
from app.core.pipeline.research import engine as O
from app.core import research_types as rt
from app.core import audit as AU
from app.core.models import Evidence

_DEST = "大理"
_SPOTS = [{"spot_id": f"大理_spot_{i}", "name": n, "matched": (i != 2)}
          for i, n in enumerate(["洱海", "大理古城", "喜洲古镇", "崇圣寺三塔"], start=1)]


def _ev(eid: str) -> Evidence:
    return Evidence(evidence_id=eid, source_url=f"https://x/{eid}", source_type="ugc",
                    title="t", excerpt="儿童免票线 1.2 米", captured_at="2026-09-01",
                    credibility=70, collected_by="L1-012", destination=_DEST, domain="x")


_EVID = [_ev("e_aaaa1111"), _ev("e_bbbb2222")]
_PROBES = {"大理_spot_1": ["e_aaaa1111"], "大理_spot_3": ["e_bbbb2222"]}
_CLAR = {"days": "1-2 天", "budget_level": "经济实惠（人均 <1000）",
         "origin": "昆明", "child_age": "3-6 岁"}


def _fake_chat(payload):
    def _f(messages, **kw):
        return payload
    return _f


def _fill(monkeypatch, payload):
    monkeypatch.setattr(llm, "chat_json", _fake_chat(payload))
    return O._fill_persp_blocks("persp_family", _DEST, _SPOTS, _PROBES, _EVID, _CLAR, "m")


# ── VR-D2/D5 行守恒 ─────────────────────────────────────────────

def test_rows_seeded_from_frozen_ranking_not_from_llm(monkeypatch):
    """LLM 漏报 2 行 + 多报 1 个表外景点：行集仍恰等冻结榜、序不变。"""
    out = _fill(monkeypatch, {"rows": [
        {"spot_id": "大理_spot_4", "cells": {}},
        {"spot_id": "大理_spot_99", "cells": {"儿童票规则": {
            "text": "表外景点也不采纳", "evidence_ids": ["e_aaaa1111"], "verified": True}}},
    ], "rules": [], "packing": []})
    rows = out["family_checklist"][0]["items"]
    assert [r["spot_id"] for r in rows] == [s["spot_id"] for s in _SPOTS]
    assert all(len(r["cells"]) == 4 for r in rows)
    assert not any(r.get("spot_name") == "表外景点" for r in rows)


def test_unmatched_spot_still_has_row(monkeypatch):
    """matched=False（spot_2）也占一行——行守恒覆盖长尾。"""
    out = _fill(monkeypatch, {"rows": [], "rules": [], "packing": []})
    rows = out["family_checklist"][0]["items"]
    assert {r["spot_id"] for r in rows} == {s["spot_id"] for s in _SPOTS}
    assert all(c["text"].startswith("待核验") and not c["verified"]
               for r in rows for c in r["cells"])


# ── VR-D1 不造数守卫 ────────────────────────────────────────────

def test_verified_without_real_evidence_is_downgraded(monkeypatch):
    out = _fill(monkeypatch, {"rows": [{
        "spot_id": "大理_spot_1",
        "cells": {
            "儿童票规则": {"text": "1.2 米以下免票", "evidence_ids": ["e_aaaa1111"], "verified": True},
            "推车可行/体力门槛": {"text": "凭常识编的坡度参数", "evidence_ids": [], "verified": True},
            "母婴室/家庭卫生间": {"text": "假引用", "evidence_ids": ["e_ffffffff"], "verified": True},
        }}], "rules": [], "packing": []})
    cells = {c["column"]: c for c in out["family_checklist"][0]["items"][0]["cells"]}
    ok = cells["儿童票规则"]
    assert ok["verified"] and ok["evidence_ids"] == ["e_aaaa1111"]
    fake1 = cells["推车可行/体力门槛"]
    assert not fake1["verified"] and fake1["text"].startswith("待核验")
    fake2 = cells["母婴室/家庭卫生间"]
    assert not fake2["verified"], "引用不存在的证据 id 等同无证据"


def test_llm_total_failure_still_emits_placeholder_table(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("模型不可用")
    monkeypatch.setattr(llm, "chat_json", boom)
    out = O._fill_persp_blocks("persp_family", _DEST, _SPOTS, _PROBES, _EVID, _CLAR, "m")
    rows = out["family_checklist"][0]["items"]
    assert len(rows) == len(_SPOTS)
    assert out["persp_rules"][0]["items"] == []
    assert out["persp_packing"][0]["items"] == []


# ── VR-D6/D7 rules & packing 守卫 ───────────────────────────────

def test_rules_require_refs_and_real_evidence_capped(monkeypatch):
    good = [{"text": f"规则{i}", "refs": ["days"], "evidence_ids": ["e_aaaa1111"]}
            for i in range(7)]
    bad = [{"text": "没引用问卷字段", "refs": [], "evidence_ids": ["e_aaaa1111"]},
           {"text": "引用假证据", "refs": ["days"], "evidence_ids": ["e_ffffffff"]},
           {"text": "无证据", "refs": ["days"], "evidence_ids": []}]
    out = _fill(monkeypatch, {"rows": [], "rules": good + bad, "packing": []})
    rules = out["persp_rules"][0]["items"]
    assert len(rules) == 5, "铁律 ≤5 条截断"
    assert all(r["refs"] == ["days"] and r["evidence_ids"] == ["e_aaaa1111"] for r in rules)


def test_packing_drops_items_without_evidence(monkeypatch):
    out = _fill(monkeypatch, {"rows": [], "rules": [], "packing": [
        {"item": "户口本/身份证原件", "reason": "免票核验看年龄", "evidence_ids": ["e_bbbb2222"]},
        {"item": "防晒霜", "reason": "哪都要", "evidence_ids": []},
    ]})
    pack = out["persp_packing"][0]["items"]
    assert [p["item"] for p in pack] == ["户口本/身份证原件"]


def test_unconfigured_perspective_assembles_nothing(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", _fake_chat({"rows": []}))
    assert O._fill_persp_blocks("persp_couple", _DEST, _SPOTS, {}, _EVID, _CLAR, "m") == {}


# ── VR-D4 防回潮负钉：目的地行过滤不得动视角块行 ────────────────

def test_enforce_dest_rows_keeps_persp_rows():
    checklist = {"destination": _DEST, "items": [
        {"spot_id": "大理_spot_1", "spot_name": "洱海", "cells": []},
        {"spot_id": "大理_spot_2", "spot_name": "大理古城", "cells": []}]}
    payload = {"family_checklist": [checklist]}
    out = O._enforce_dest_rows(payload, [_DEST])
    assert out["family_checklist"][0]["items"] == checklist["items"], \
        "景点名不是目的地——把洱海当 foreign 目的地行剔掉即 calm-reef-pigeon P0-1 事故回潮"


# ── VR-E1 写稿提示硬约束断言矩阵 ────────────────────────────────

def _write_capture(monkeypatch, sid: str, persp_line: str):
    seen: dict = {}

    def fake_chat(messages, **kw):
        seen["all"] = "\n".join(m["content"] for m in messages)
        return {"paragraphs": ["段一。" * 40, "段二。" * 40, "段三。" * 40,
                               "段四。" * 40, "段五。" * 40],
                "key_takeaway": "核心判断", "highlights": ["亮点"]}

    monkeypatch.setattr(llm, "chat_json", fake_chat)
    O._write_single_section(sid, "标题", "大理攻略", [_DEST], [], [], [], {},
                            "model-x", "guide", persp_line=persp_line)
    return seen["all"]


@pytest.mark.parametrize("field,value", [
    ("days", "1-2 天"),
    ("budget_level", "经济实惠（人均 <1000）"),
    ("origin", "昆明"),
    ("child_age", "3-6 岁"),
])
def test_persp_prompt_carries_each_constraint_field(monkeypatch, field, value):
    line = "；".join(f"{k}={v}" for k, v in
                    [("days", "1-2 天"), ("budget_level", "经济实惠（人均 <1000）"),
                     ("origin", "昆明"), ("child_age", "3-6 岁")])
    prompt = _write_capture(monkeypatch, "persp_family", line)
    assert "本次问卷硬约束" in prompt
    assert value in prompt, f"{field} 的答案必须逐值进提示（断言注入）"
    assert "禁止逐格复述" in prompt


def test_non_persp_sections_get_no_constraint_line(monkeypatch):
    prompt = _write_capture(monkeypatch, "budget", "")
    assert "本次问卷硬约束" not in prompt


# ── VR-E3 质检越约束检查段 ──────────────────────────────────────

def _review_capture(monkeypatch, constraints: str):
    seen: dict = {}

    def fake_chat(messages, **kw):
        seen["all"] = "\n".join(m["content"] for m in messages)
        return {"verdict": "pass", "scores": {}, "review": "r", "issues": [], "suggestions": []}

    monkeypatch.setattr(AU, "chat_json", fake_chat) if hasattr(AU, "chat_json") \
        else monkeypatch.setattr("app.core.llm.chat_json", fake_chat)
    qr = AU.QualityReport()
    AU.llm_quality_review("q", [_DEST], [], [], {}, qr, "m", "guide",
                          persp_constraints=constraints)
    return seen["all"]


def test_qa_review_carries_overconstraint_check(monkeypatch):
    prompt = _review_capture(monkeypatch, "days=1-2 天；child_age=3-6 岁")
    assert "问卷硬约束越界检查" in prompt and "days=1-2 天" in prompt


def test_qa_review_without_perspective_unchanged(monkeypatch):
    prompt = _review_capture(monkeypatch, "")
    assert "问卷硬约束越界检查" not in prompt


# ── RV-7 视角章 CSV 数据网格（一格一行、待核验如实入表）────────────
_CHECKLIST = {"family_checklist": [{
    "destination": _DEST,
    "items": [
        {"spot_id": "大理_spot_1", "spot_name": "洱海", "cells": [
            {"column": "儿童票规则", "text": "1.2 米以下免票", "evidence_ids": ["e_aaaa1111"],
             "verified": True},
            {"column": "母婴室/家庭卫生间", "text": "待核验（本次未采到）",
             "evidence_ids": [], "verified": False}]},
        {"spot_id": "大理_spot_2", "spot_name": "大理古城", "cells": [
            {"column": "儿童票规则", "text": "免费开放", "evidence_ids": ["e_bbbb2222"],
             "verified": True},
            {"column": "母婴室/家庭卫生间", "text": "待核验（本次未采到）",
             "evidence_ids": [], "verified": False}]},
    ],
}]}


def test_guide_registry_puts_perspective_section_on_csv_channel():
    """元钉：视角章登记在章节级 CSV 注册表里（漏登记＝前端 CSV 按钮静默缺失）。"""
    assert "persp_family" in rt.type_spec("guide")["data_grid_sections"]


def test_persp_grid_one_row_per_cell_with_traceability():
    grid = O._build_data_grid("persp_family", {"structured": _CHECKLIST}, _EVID)
    assert grid and len(grid["rows"]) == 4, "行=景点行×列格，一格一行才可 CSV 全量导出"
    by_name = {r["name"]: r for r in grid["rows"]}
    hit = by_name[f"{_DEST} · 洱海 · 儿童票规则"]
    assert hit["value"] == "1.2 米以下免票" and hit["evidence_id"] == "e_aaaa1111"
    assert hit["source"] == "x" and hit["metric"] == "亲子核查项"
    gap = by_name[f"{_DEST} · 洱海 · 母婴室/家庭卫生间"]
    assert gap["metric"] == "待核验占位" and not gap["evidence_id"], \
        "占位格必须如实标注且不带假来源（不造数契约延伸到 CSV）"


def test_persp_grid_absent_when_no_checklist():
    """非亲子/无核查表 → 短路为 None（零波及，不产空网格）。"""
    assert O._build_data_grid("persp_family", {"structured": {}}, _EVID) is None
