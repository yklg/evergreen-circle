"""assessment 体验层契约（glacial-vale-sparrow 批次③ · T-11/T-13′/T-14）。

批次② 把每章都配上了图，批次③ 解决「图没有的时候怎么说话」：

- **T-11 信息密度铁律**：`density` 必须真进写稿提示注入链路（登记了不注入 = 静默失效），
  且按类型各用各的文案（guide 讲实体表，assessment 讲结构化表）。
- **缺口标注**：算分图不出图分两种——「没有材料」（采集缺口，既有结构状态管）与
  「有材料但缺可核验数值」（算分输入缺口，本批新增 `score_gap`）。两者语义不同，
  不得复用同一字段或同一状态值；缺口只在 builder 同一次产出里记，装配层不反推。
- **T-14 算法可审计**：glossary 覆盖全部评分类图，且术语文本里的权重/映射值必须
  与 `scoring.py` 常量一致（声明即公式：改公式忘改文案 → 本文件红）。

运行：backend/ 下 `pytest tests/test_assessment_experience.py -q`
"""
import pytest

from app.core import orchestrator as O
from app.core import research_types as RT
from app.core import scoring as SC

_EIDS = ("ev_acc", "ev_ame", "ev_saf", "ev_liv")

_EVIDENCES = [{"evidence_id": e, "domain": f"src{i}.example.com", "source_type": "web"}
              for i, e in enumerate(_EIDS)]

_CLAIMS = [
    {"text": "成都东站至市区约 30 分钟。", "field": "accessibility", "evidence_ids": ["ev_acc"]},
    {"text": "两地三甲医院数量充足。", "field": "amenities", "evidence_ids": ["ev_ame"]},
    {"text": "夜间治安总体可控。", "field": "safety", "evidence_ids": ["ev_saf"]},
]

_ROUTES_3 = [{"mode": m, "duration": "2 小时", "cost": "180 元",
              "duration_minutes": 120, "cost_yuan": 180}
             for m in ("高铁", "飞机", "自驾")]


def _capture(payload, holder):
    def _fake(messages, **kwargs):
        holder.append((messages, kwargs))
        return payload
    return _fake


def _gaps(analysis, *, dests=("成都", "杭州"), rtype="assessment"):
    """跑一次 builder 链，返回缺口台账（同时断言图与缺口都从同一次产出里来）。"""
    specs, gaps = O._build_charts_and_gaps(list(dests), analysis, {}, [], rtype,
                                           mode="deep", evidences=_EVIDENCES)
    return specs, gaps


# ── T-11 信息密度铁律进提示链路 ───────────────────────────
@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_density_injected_into_section_prompt(monkeypatch, rtype):
    holder = []
    monkeypatch.setattr(O, "chat_json",
                        _capture({"key_takeaway": "判断", "highlights": [], "paragraphs": ["段"]},
                                 holder))
    O._write_single_section("accessibility", "二、交通可达性", "成都和杭州宜居吗",
                            ["成都", "杭州"], ["交通"], [], [], {}, "test-model", rtype,
                            4, "200-300", 8000)
    user = holder[0][0][1]["content"]
    density = RT.type_spec(rtype)["density"]
    assert density and "【信息密度铁律】" in user
    assert density in user, "登记了却不注入写稿提示 = 静默失效"


def test_density_text_is_per_type():
    """两类型的密度铁律各讲各的口径：guide 锁实体表，assessment 锁结构化表。"""
    guide = RT.type_spec("guide")["density"]
    assess = RT.type_spec("assessment")["density"]
    assert guide != assess
    assert "spot_id" in guide
    assert "可达性矩阵" in assess and "风险画像" in assess


# ── 缺口台账：有材料但算不出 ──────────────────────────────
def test_access_radar_gap_when_routes_lack_numeric_fields():
    """可达性矩阵有路线但无耗时/费用数值 → 不出图，且如实记缺口。"""
    analysis = {"structured": {"access_matrix": [
        {"destination": "成都", "routes": [{"mode": "高铁", "duration": "1.5 小时",
                                            "cost": "180 元"}]}]}}
    specs, gaps = _gaps(analysis)
    assert specs == []
    assert gaps == [{"sections": ("accessibility",),
                     "reason": "可达性矩阵未给出「耗时/费用」数值"}]


def test_access_radar_gap_when_shared_modes_below_three():
    """仅 2 种共有交通方式：两轴雷达画成折线，不出图并记「维度不足」缺口。"""
    analysis = {"structured": {"access_matrix": [
        {"destination": d, "routes": _ROUTES_3[:2]} for d in ("成都", "杭州")]}}
    specs, gaps = _gaps(analysis)
    assert specs == []
    assert gaps[0]["sections"] == ("accessibility",)
    assert "交通方式不足 3 种（当前 2 种）" in gaps[0]["reason"]


def test_access_radar_chart_present_means_no_gap():
    """有 3 种共有方式 → 出图，同一路径不留缺口（缺口与图互斥）。"""
    analysis = {"structured": {"access_matrix": [
        {"destination": d, "routes": _ROUTES_3} for d in ("成都", "杭州")]}}
    specs, gaps = _gaps(analysis)
    assert any(s["type"] == "radar" for s in specs)
    assert not [g for g in gaps if g["sections"] == ("accessibility",)]


def test_risk_heat_gap_when_shared_dims_below_two():
    analysis = {"structured": {"risk_profile": [
        {"destination": d, "items": [{"dimension": "气候", "level": "low", "note": ""}]}
        for d in ("成都", "杭州")]}}
    specs, gaps = _gaps(analysis)
    assert not [s for s in specs if s["type"] == "season_heat"]
    assert gaps[0]["sections"] == ("safety",)
    assert "共有风险维度不足 2 个（当前 1 个）" in gaps[0]["reason"]


def test_livelihood_gap_when_amounts_missing():
    analysis = {"livelihood_cost": [
        {"destination": "成都", "items": [{"category": "房租", "unit": "元/月"}]}]}
    specs, gaps = _gaps(analysis)
    assert not [s for s in specs if s["type"] == "cost_bar"]
    assert gaps == [{"sections": ("livelihood",), "reason": "生活成本分项未给出金额"}]


@pytest.mark.parametrize("analysis", [{}, {"structured": {}}, {"structured": {"access_matrix": []}}])
def test_no_material_means_no_gap(analysis):
    """没有任何材料属采集缺口（由既有结构状态表达），不得冒充算分输入缺口。"""
    _, gaps = _gaps(analysis)
    assert gaps == []


def test_guide_never_records_gaps():
    """guide 无评估算分图：材料齐或缺都不得产出缺口（类型边界不越界）。"""
    specs, gaps = O._build_charts_and_gaps(
        ["大理"], {"structured": {"access_matrix": [
            {"destination": "大理", "routes": [{"mode": "飞机", "duration": "2 小时"}]}]}},
        {}, [], "guide", mode="deep", evidences=_EVIDENCES)
    assert specs == [] and gaps == []


def test_gaps_do_not_leak_into_chart_specs():
    """`_build_charts` 契约不变：扁平 List[spec]，台账不得混进图列表（T-16 回归）。"""
    analysis = {"structured": {"access_matrix": [
        {"destination": "成都", "routes": [{"mode": "高铁", "duration": "1.5 小时"}]}]}}
    specs = O._build_charts(["成都"], analysis, {}, [], "assessment",
                            mode="deep", evidences=_EVIDENCES)
    assert isinstance(specs, list) and specs == []


# ── 缺口落章：_assemble_report 如实标注 ───────────────────
_SENT_TEXT = {"paragraphs": ["段"], "key_takeaway": "成都更宜居", "highlights": []}


def _assemble(chart_gaps):
    return O._assemble_report(
        "成都和杭州宜居吗", ["成都", "杭州"], ["交通"],
        {"members": [{"id": "L3-002"}], "lead": "L3-002"},
        [], [], [], {}, [], {"accessibility": _SENT_TEXT}, [],
        {}, {}, {}, {}, [], "deep", ["accessibility", "conclusion"], None, {},
        "assessment", chart_gaps=chart_gaps,
    )


def test_score_gap_lands_on_its_section_only():
    report = _assemble([{"sections": ("accessibility",), "reason": "可达性矩阵未给出「耗时/费用」数值"}])
    sec = next(s for s in report["sections"] if s["id"] == "accessibility")
    assert sec["score_gap"] == {"kind": "insufficient_input",
                               "reason": "可达性矩阵未给出「耗时/费用」数值"}
    other = next(s for s in report["sections"] if s["id"] == "conclusion")
    assert other["score_gap"] is None, "缺口只落在声明章，不得广播"


def test_score_gap_is_orthogonal_to_structure_status():
    """同一章可以「结构完好」（ok）同时「算分输入不足」——两条轴不互相冒充。"""
    report = _assemble([{"sections": ("accessibility",), "reason": "生活成本分项未给出金额"}])
    sec = next(s for s in report["sections"] if s["id"] == "accessibility")
    assert sec["structure_status"] == "ok"
    assert sec["score_gap"]["kind"] == "insufficient_input"
    assert sec["structure_status"] != "lost", "算分缺口不得复用 lost 语义"


def test_no_gaps_means_null_key_everywhere():
    report = _assemble(None)
    assert all(s["score_gap"] is None for s in report["sections"])


# ── T-14 glossary 覆盖评分类图表（声明即公式）─────────────
_SCORING_BUILDERS = ("_chart_access_radar", "_chart_amenity_bar",
                     "_chart_risk_heat", "_chart_evidence_strength")


def test_scoring_builder_types_are_declared_by_assessment():
    by_name = {fn.__name__: fn for fn in O.CHART_BUILDERS}
    charts = RT.type_spec("assessment")["charts"]
    for name in _SCORING_BUILDERS:
        assert by_name[name].CHART_TYPE in charts, f"{name} 的图类型未登记，永远不出图"


def test_glossary_covers_all_scoring_charts():
    terms = {g["term"]: g for g in RT.type_spec("assessment")["glossary"]}
    for term in ("可达性打分", "配套完善度", "风险画像", "证据强度"):
        assert term in terms, f"评分类图缺术语条目：{term}"
        assert "scoring.py" in terms[term]["source"], "术语来源必须指向确定性算分模块"
        assert "LLM 不参与打分" in terms[term]["definition"] or "计数" in terms[term]["definition"]


def test_glossary_numbers_match_scoring_constants():
    """声明即公式：改 scoring 的权重/映射值而不改 glossary 文案 → 本用例红。"""
    terms = {g["term"]: g for g in RT.type_spec("assessment")["glossary"]}
    acc = SC.SCORE_FORMULAS["accessibility"]
    assert f"{acc['duration']}/{acc['cost']}" in terms["可达性打分"]["definition"]
    amen = SC.SCORE_FORMULAS["amenity"]
    assert (f"{amen['full'] * 100:.0f}/{amen['partial'] * 100:.0f}/{amen['none'] * 100:.0f}"
            in terms["配套完善度"]["definition"])
    risk = SC.SCORE_FORMULAS["risk"]
    assert (f"{risk['low']:.0f}/{risk['medium']:.0f}/{risk['high']:.0f}"
            in terms["风险画像"]["definition"])


# ── 图内公式注记（可审计：图自己说清怎么算的）─────────────
def _graphic_text(spec) -> str:
    texts = [g.get("style", {}).get("text", "") for g in spec["option"].get("graphic", [])]
    return " ".join(texts)


def test_access_radar_carries_formula_note():
    analysis = {"structured": {"access_matrix": [
        {"destination": d, "routes": _ROUTES_3} for d in ("成都", "杭州")]}}
    specs, _ = _gaps(analysis)
    spec = next(s for s in specs if s["type"] == "radar")
    note = _graphic_text(spec)
    assert f"{SC.WEIGHT_DURATION}" in note and f"{SC.WEIGHT_COST}" in note
    assert "LLM 不参与打分" in note


def test_amenity_bar_carries_enum_mapping_note():
    analysis = {"structured": {"amenity_checklist": [
        {"destination": "成都", "items": [{"category": "医疗", "item": "三甲医院",
                                           "coverage": "full", "note": ""}]}]}}
    specs, _ = _gaps(analysis)
    spec = next(s for s in specs if s["type"] == "cost_bar")
    assert "full 100 / partial 50 / none 0" in _graphic_text(spec)


def test_risk_heat_note_is_generated_from_formula_table():
    levels = SC.SCORE_FORMULAS["risk"]
    analysis = {"structured": {"risk_profile": [
        {"destination": d, "items": [{"dimension": "气候", "level": "low", "note": ""},
                                     {"dimension": "治安", "level": "high", "note": ""}]}
        for d in ("成都", "杭州")]}}
    specs, _ = _gaps(analysis)
    spec = next(s for s in specs if s["type"] == "season_heat")
    note = _graphic_text(spec)
    for k, v in levels.items():
        assert f"{k}={int(v)}" in note


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
