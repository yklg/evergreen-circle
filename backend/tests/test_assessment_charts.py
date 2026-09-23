"""assessment 图表层契约（glacial-vale-sparrow 批次② · T-09/T-03/T-07/T-08/T-10）。

批次② 把 `_build_charts` 拆成 builder 注册表并新增 7 张图，本文件钉住随之而来的
四条不变量：

- **T-09 builder 可独立测**：每张新图喂 `ChartContext` 即断言产出，不必构造整条
  流水线——「一类图 = 一个函数」的收益必须体现在可测性上，否则拆分只是换了个写法。
- **T-03 归属唯一性**：图只落在自己声明的章节；同类型多图不得共享归属。assessment
  的 cost_bar 现在有 4 张（价值/安全/配套/生活成本），串一处即回到根因③。
- **T-07 降级契约**：输入不足 → 该 builder 返回 `[]`（不出空图、不抛错），与
  scoring 的「不足即 None」同一契约精神。
- **T-10 可溯源**：每张新图挂 `evidence_ids` 且指向真实证据。

另有三条覆盖断言：
- T-08 N=1/N≥2：`charts_for` 的 MULTI_ONLY / SOLO_ONLY 剔除不破坏新图；
- assessment deep/expert **每个章节都有配图**（用户要求「2-11 章都需要可视化」的直接固化）；
- guide 回归：新图不越类型边界。

运行：backend/ 下 `pytest tests/test_assessment_charts.py -q`
"""
import pytest

from app.core import orchestrator as O
from app.core import research_types as RT

_EIDS = ("ev_acc", "ev_ame", "ev_saf", "ev_liv", "ev_ovr", "ev_rsk")

_CLAIMS = [
    {"text": "成都东站至市区约 30 分钟。", "field": "accessibility", "evidence_ids": ["ev_acc"]},
    {"text": "两地三甲医院数量充足。", "field": "amenities", "evidence_ids": ["ev_ame"]},
    {"text": "夜间治安总体可控。", "field": "safety", "evidence_ids": ["ev_saf"]},
    {"text": "核心区月租约 2500 元。", "field": "livelihood", "evidence_ids": ["ev_liv"]},
    {"text": "两地生活节奏差异明显。", "field": "overview", "evidence_ids": ["ev_ovr"]},
    {"text": "旺季客流带来居住体验波动。", "field": "risk", "evidence_ids": ["ev_rsk"]},
]

_EVIDENCES = [{"evidence_id": e, "domain": f"src{i}.example.com", "source_type": "web"}
              for i, e in enumerate(_EIDS)]

_SENTIMENT = {"sample_size": 12, "overall_count": {"pos": 6, "neu": 4, "neg": 2},
              "by_platform": {"xiaohongshu": {"pos": 3, "neu": 1, "neg": 1},
                              "zhihu": {"pos": 2, "neu": 1, "neg": 0}},
              "keywords": [{"word": "宜居", "weight": 5}, {"word": "通勤", "weight": 3}]}

_NEW_TITLES = ("可达性分项", "配套覆盖度", "风险维度热力网格", "生活成本分项",
               "共识 vs 反共识占比", "行动优先级分档", "证据强度计数")


def _builder(name):
    return next(fn for fn in O.CHART_BUILDERS if fn.__name__ == name)


def _ctx(analysis, *, dests=("成都", "杭州"), mode="deep", rtype="assessment", claims=None):
    return O._chart_context(list(dests), analysis, {}, _CLAIMS if claims is None else claims,
                            rtype, mode, _EVIDENCES)


def _radar_scores(spec) -> dict:
    """从 radar option 取「目的地 → {方式: 分}」。"""
    dims = [d["name"] for d in spec["option"]["radar"]["indicator"]]
    return {row["name"]: dict(zip(dims, row["value"]))
            for row in spec["option"]["series"][0]["data"]}


# ── T-09 可达性拆解雷达 ────────────────────────────────────
def test_access_radar_shared_modes_and_relative_scores():
    """维度 = 各目的地**共有**方式；分数 = 方式内相对分（同方式最优路线 = 100）。"""
    rows = [
        {"destination": "成都", "routes": [
            {"mode": "高铁", "duration_minutes": 120, "cost_yuan": 200},
            {"mode": "飞机", "duration_minutes": 90, "cost_yuan": 600},
            {"mode": "自驾", "duration_minutes": 300, "cost_yuan": 350}]},
        {"destination": "杭州", "routes": [
            {"mode": "高铁", "duration_minutes": 180, "cost_yuan": 400},
            {"mode": "飞机", "duration_minutes": 150, "cost_yuan": 800},
            {"mode": "自驾", "duration_minutes": 300, "cost_yuan": 350}]},
    ]
    specs = _builder("_chart_access_radar")(_ctx({"structured": {"access_matrix": rows}}))
    assert len(specs) == 1
    s = specs[0]
    assert s["type"] == "radar" and s["sections"] == ("accessibility",)
    assert "对比" in s["title"] and s["title"].endswith(O._ALGO_TAG)
    assert [d["name"] for d in s["option"]["radar"]["indicator"]] == ["高铁", "飞机", "自驾"]
    scores = _radar_scores(s)
    # 自驾耗时/费用两地持平 → 双方均为满分（相对分语义，不做绝对阈值）
    assert scores["成都"]["自驾"] == 100.0 and scores["杭州"]["自驾"] == 100.0
    # 高铁耗时 120 vs 180：快者时间分更高，慢者不应是满分
    assert scores["成都"]["高铁"] > scores["杭州"]["高铁"]
    assert scores["杭州"]["高铁"] < 100


def test_access_radar_skips_modes_missing_numeric_fields():
    """缺 duration_minutes / cost_yuan 的方式整条不计分：不足 3 个共有方式即不出图。"""
    rows = [{"destination": d, "routes": [
        {"mode": "高铁", "duration_minutes": 100, "cost_yuan": 200},
        {"mode": "飞机", "duration_minutes": 80, "cost_yuan": 500},
        # 自驾只有文本耗时/费用（LLM 未给数值）→ 该方式不计分
        {"mode": "自驾", "duration": "5 小时", "cost": "350 元"},
    ]} for d in ("成都", "杭州")]
    assert _builder("_chart_access_radar")(_ctx({"structured": {"access_matrix": rows}})) == [], \
        "仅 2 个可算分方式 < 3 维，应整图跳过而非画个两轴折线"


def test_access_radar_dims_are_intersection_across_destinations():
    """某方式只在一地有 → 不进驻留维度（雷达每序列必须等长，缺维补 0 = 把「未知」当 0 分）。"""
    rows = [
        {"destination": "成都", "routes": [
            {"mode": "高铁", "duration_minutes": 100, "cost_yuan": 200},
            {"mode": "飞机", "duration_minutes": 80, "cost_yuan": 500},
            {"mode": "自驾", "duration_minutes": 300, "cost_yuan": 350}]},
        {"destination": "杭州", "routes": [
            {"mode": "高铁", "duration_minutes": 160, "cost_yuan": 300},
            {"mode": "飞机", "duration_minutes": 120, "cost_yuan": 700}]},
    ]
    assert _builder("_chart_access_radar")(_ctx({"structured": {"access_matrix": rows}})) == []


# ── T-09 配套覆盖度柱 ─────────────────────────────────────
def test_amenity_bar_maps_coverage_enum_through_score_formula():
    """柱高 = SCORE_FORMULAS["amenity"] 枚举映射（full/partial/none → 100/50/0）。"""
    from app.core import scoring as SC

    rows = [{"destination": d, "items": [
        {"item": "三甲医院", "coverage": "full"},
        {"item": "大型商超", "coverage": "partial"},
        {"item": "地铁", "coverage": "none"},
    ]} for d in ("成都", "杭州")]
    specs = _builder("_chart_amenity_bar")(_ctx({"structured": {"amenity_checklist": rows}}))
    ratio = SC.SCORE_FORMULAS["amenity"]
    assert specs[0]["sections"] == ("amenities",)
    opt = specs[0]["option"]
    assert opt["xAxis"]["data"] == ["成都·三甲医院", "成都·大型商超", "成都·地铁",
                                    "杭州·三甲医院", "杭州·大型商超", "杭州·地铁"]
    assert opt["series"][0]["data"] == [ratio["full"] * 100, ratio["partial"] * 100,
                                        ratio["none"] * 100] * 2
    assert opt["yAxis"]["name"] == "覆盖度（满分 100）"


def test_amenity_bar_solo_axis_has_no_destination_prefix():
    """N=1 时 x 轴不拼目的地（单城语境下「成都·三甲医院」是噪声）。"""
    rows = [{"destination": "成都", "items": [{"item": "三甲医院", "coverage": "full"}]}]
    specs = _builder("_chart_amenity_bar")(
        _ctx({"structured": {"amenity_checklist": rows}}, dests=("成都",)))
    assert specs[0]["option"]["xAxis"]["data"] == ["三甲医院"]
    assert "对比" not in specs[0]["title"]


# ── T-09 风险热力网格 ─────────────────────────────────────
def test_risk_heat_uses_score_formula_levels_and_shared_dims():
    """值 = 等级映射分（与安全章算分同一张表）；未知等级按 medium；维度取共有项。"""
    from app.core import scoring as SC

    rows = [
        {"destination": "成都", "items": [
            {"dimension": "气候", "level": "low"},
            {"dimension": "治安", "level": "high"},
            {"dimension": "医疗", "level": "medium"}]},
        {"destination": "杭州", "items": [
            {"dimension": "气候", "level": "medium"},
            {"dimension": "治安", "level": "low"},
            {"dimension": "医疗", "level": "未知档"}]},
    ]
    specs = _builder("_chart_risk_heat")(_ctx({"structured": {"risk_profile": rows}}))
    levels = SC.SCORE_FORMULAS["risk"]
    assert specs[0]["type"] == "season_heat" and specs[0]["sections"] == ("safety",)
    assert specs[0]["title"].endswith(O._ALGO_TAG)
    opt = specs[0]["option"]
    assert opt["xAxis"]["data"] == ["气候", "治安", "医疗"]
    assert opt["yAxis"]["data"] == ["成都", "杭州"]
    assert opt["series"][0]["data"] == [
        [0, 0, levels["low"]], [1, 0, levels["high"]], [2, 0, levels["medium"]],
        [0, 1, levels["medium"]], [1, 1, levels["low"]], [2, 1, levels["medium"]],
    ]
    # 注释文案由同一张映射表生成：改表即改图，不存在第二处口径
    note = opt["graphic"][0]["style"]["text"]
    for level, val in levels.items():
        assert f"{level}={int(val)}" in note


def test_risk_heat_needs_two_shared_dims():
    """单维热力网格退化成一排色块 → 不出图；维度取交集（缺格不补 0）。"""
    one = [{"destination": d, "items": [{"dimension": "气候", "level": "low"}]}
           for d in ("成都", "杭州")]
    assert _builder("_chart_risk_heat")(_ctx({"structured": {"risk_profile": one}})) == []
    disjoint = [
        {"destination": "成都", "items": [{"dimension": "气候", "level": "low"},
                                          {"dimension": "医疗", "level": "low"}]},
        {"destination": "杭州", "items": [{"dimension": "气候", "level": "low"},
                                          {"dimension": "治安", "level": "low"}]},
    ]
    assert _builder("_chart_risk_heat")(_ctx({"structured": {"risk_profile": disjoint}})) == [], \
        "两地共有维度仅「气候」1 个，应整图跳过"


# ── T-09 生活成本分项柱 ───────────────────────────────────
def test_livelihood_bar_multi_destination_prefix_and_unit():
    rows = [{"destination": "成都", "items": [
        {"category": "房租", "amount": 2500, "unit": "元/月"},
        {"category": "餐饮", "amount": 1200, "unit": "元/月"}]},
        {"destination": "杭州", "items": [{"category": "房租", "amount": 3200, "unit": "元/月"}]}]
    specs = _builder("_chart_livelihood_bar")(_ctx({"livelihood_cost": rows}))
    assert specs[0]["sections"] == ("livelihood",)
    opt = specs[0]["option"]
    assert opt["xAxis"]["data"] == ["成都·房租", "成都·餐饮", "杭州·房租"]
    assert opt["series"][0]["data"] == [2500.0, 1200.0, 3200.0]
    assert opt["yAxis"]["name"] == "元/月"


def test_livelihood_bar_filters_invalid_amount_rows():
    """builder 侧只判「能不能画」：类别非空 + 金额是数值。

    非数值金额与空类别在此剔除（装配漏过时也不画空白柱）；`amount: 0` 保留——
    金额正负是清洗层职责（`_sanitize_livelihood_cost` 已保证 amount>0 才落
    analysis），两处各管一段、不重复清洗（与 `_chart_cost_compose` 同约定）。
    """
    rows = [{"destination": "成都", "items": [
        {"category": "房租", "amount": 2500},
        {"category": "", "amount": 999},
        {"category": "餐饮", "amount": "未知"},
        {"category": "交通", "amount": 0}]}]
    specs = _builder("_chart_livelihood_bar")(_ctx({"livelihood_cost": rows}, dests=("成都",)))
    assert specs[0]["option"]["series"][0]["data"] == [2500.0, 0.0]
    assert specs[0]["option"]["xAxis"]["data"] == ["房租", "交通"]
    assert _builder("_chart_livelihood_bar")(_ctx({"livelihood_cost": []})) == []


def test_livelihood_bar_drops_rows_of_other_destinations():
    """装配层兜底：非本次目的地的行不进图（防上游过滤漏过导致串城）。"""
    rows = [{"destination": "成都", "items": [{"category": "房租", "amount": 2500}]},
            {"destination": "拉萨", "items": [{"category": "房租", "amount": 1800}]}]
    specs = _builder("_chart_livelihood_bar")(_ctx({"livelihood_cost": rows}, dests=("成都",)))
    assert specs[0]["option"]["xAxis"]["data"] == ["房租"]


# ── T-09 共识对照条 / 行动优先级 / 证据强度（growth_bar 族）──
def test_consensus_bar_plots_only_sides_with_share():
    """只画有占比的一侧：share 缺失 ≠ 0%，不补 0 不造半边假数据。"""
    both = {"orthodox": {"label": "主流共识", "summary": "性价比占优", "share": 60},
            "contrarian": {"label": "反共识判断", "summary": "旺季体验下滑", "share": 18}}
    specs = _builder("_chart_consensus_bar")(_ctx({"consensus_split": both}))
    assert specs[0]["type"] == "growth_bar" and specs[0]["sections"] == ("contrarian",)
    assert specs[0]["title"].endswith(O._ALGO_TAG)
    assert specs[0]["option"]["xAxis"]["data"] == ["主流共识", "反共识判断"]
    assert [d["value"] for d in specs[0]["option"]["series"][0]["data"]] == [60.0, 18.0]

    one = {"contrarian": {"summary": "旺季体验下滑", "share": 18}}
    one_spec = _builder("_chart_consensus_bar")(_ctx({"consensus_split": one}))
    assert one_spec[0]["option"]["xAxis"]["data"] == ["反共识判断"]
    assert [d["value"] for d in one_spec[0]["option"]["series"][0]["data"]] == [18.0]
    # 两侧都无占比 → 不出图（不是画两根 0 高柱子）
    assert _builder("_chart_consensus_bar")(_ctx({"consensus_split": {
        "orthodox": {"summary": "性价比占优"}, "contrarian": {"summary": "体验下滑"}}})) == []


def test_action_priorities_counts_by_tier():
    """按 tier 计数（高/中/低），三档恒在 x 轴——「0 条高优先级」也是给决策者的信息。"""
    pri = {"items": [{"action": "a", "tier": "high"}, {"action": "b", "tier": "high"},
                     {"action": "c", "tier": "mid"}]}
    specs = _builder("_chart_action_priorities")(_ctx({"action_priorities": pri}))
    assert specs[0]["sections"] == ("conclusion",)
    opt = specs[0]["option"]
    assert opt["xAxis"]["data"] == ["高优先级", "中优先级", "低优先级"]
    assert [d["value"] for d in opt["series"][0]["data"]] == [2.0, 1.0, 0.0]
    assert _builder("_chart_action_priorities")(_ctx({"action_priorities": {"items": []}})) == []


def test_evidence_strength_uses_scoring_counts():
    """计数来自 scoring.count_evidence_strength（确定性），不是 LLM 自报。"""
    from app.core import scoring as SC

    claims = [{"text": "x", "field": "risk", "evidence_ids": ["ev_rsk"]},
              {"text": "y", "field": "risk", "evidence_ids": []}]
    st = SC.count_evidence_strength(claims, _EVIDENCES)
    specs = _builder("_chart_evidence_strength")(_ctx({"x": 1}, claims=claims))
    assert specs[0]["sections"] == ("risk",)
    values = [d["value"] for d in specs[0]["option"]["series"][0]["data"]]
    assert values == [float(st["claims_total"]), float(st["supported"]),
                      float(st["unsupported"]), float(st["evidence_total"]),
                      float(st["domains"])]
    assert specs[0]["option"]["xAxis"]["data"] == ["结论总数", "有据结论", "无据存疑",
                                                  "引用证据", "独立信源"]
    # 无结论可数 → 不画一排 0（与「有 0 条证据」的可展示事实相区分）
    assert _builder("_chart_evidence_strength")(_ctx({"x": 1}, claims=[])) == []


# ── T-07 降级契约 ────────────────────────────────────────
@pytest.mark.parametrize("name", ["_chart_access_radar", "_chart_amenity_bar",
                                  "_chart_risk_heat", "_chart_livelihood_bar",
                                  "_chart_consensus_bar", "_chart_action_priorities"])
def test_new_builders_degrade_to_empty(name):
    """analysis 空 → 每个新 builder 返回 []，不抛错、不产空图。

    证据强度图不在本参数化内：它的数据源是 claims/evidences 而非 analysis，
    见 test_evidence_strength_not_gated_by_analysis。
    """
    assert _builder(name)(_ctx({})) == []


def test_evidence_strength_not_gated_by_analysis():
    """计数类无「输入不足」语义：analysis 空但有结论 → 照常出图（0 条证据也可展示）。"""
    specs = _builder("_chart_evidence_strength")(_ctx({}))
    assert specs[0]["sections"] == ("risk",)
    assert specs[0]["option"]["series"][0]["data"][1]["value"] >= 0.0


@pytest.mark.parametrize("name", ["_chart_consensus_bar", "_chart_action_priorities",
                                  "_chart_evidence_strength"])
def test_growth_bar_family_gated_by_allowed_set(name):
    """growth_bar 不在 guide 图集内 → 即便数据齐备也必须零产出（类型边界不靠上游自觉）。"""
    data = {"consensus_split": {"orthodox": {"summary": "s", "share": 60}},
            "action_priorities": {"items": [{"action": "a", "tier": "high"}]}}
    assert _builder(name)(_ctx(data, rtype="guide")) == []


# ── T-10 归属与可溯源 ────────────────────────────────────
def _assessment_fixture(dests=("成都", "杭州")):
    """「每张图都有真实原料」的 assessment 载荷（与 test_charts_options 同型）。"""
    def both(items_of):
        return [{"destination": d, **items_of(i)} for i, d in enumerate(dests)]

    modes = [("高铁", 95, 180), ("飞机", 150, 520), ("自驾", 260, 320)]
    return {
        "livability": {"dimensions": ["可达性", "配套完善", "安全", "成本"],
                       "scores": [{"destination": d, "values": [80 - i * 5, 70, 88, 65]}
                                  for i, d in enumerate(dests)]},
        "cost": [{"destination": d, "monthly_living": 3200 + i * 400,
                  "monthly_rent": 2400 + i * 300} for i, d in enumerate(dests)],
        "safety_index": both(lambda i: {"safety_score": 88 - i * 5}),
        "livelihood_cost": both(lambda i: {"items": [
            {"category": "房租", "amount": 2400 + i * 300, "unit": "元/月"},
            {"category": "餐饮", "amount": 1100 + i * 150, "unit": "元/月"}]}),
        "action_priorities": {"items": [{"action": "优先核验核心区居住成本", "tier": "high"},
                                        {"action": "补充通勤实测", "tier": "mid"}]},
        "consensus_split": {"orthodox": {"label": "主流共识", "summary": "性价比占优", "share": 60},
                            "contrarian": {"label": "反共识判断", "summary": "旺季体验下滑",
                                           "share": 18}},
        "share_estimate": [{"name": d, "value": v} for d, v in zip(dests, (60, 40))],
        "trends": {"x": ["2023", "2024"], "unit": "万人",
                   "series": [{"name": d, "values": [100, 120]} for d in dests]},
        "structured": {
            "access_matrix": both(lambda i: {"routes": [
                {"mode": m, "duration_minutes": mins + i * 40, "cost_yuan": yuan + i * 60}
                for m, mins, yuan in modes]}),
            "amenity_checklist": both(lambda i: {"items": [
                {"category": "医疗", "item": "三甲医院", "coverage": "full"},
                {"category": "商业", "item": "大型商超", "coverage": "partial"}]}),
            "risk_profile": both(lambda i: {"items": [
                {"dimension": "气候", "level": "low"},
                {"dimension": "治安", "level": "medium"}]}),
        },
    }


def _assessment_specs(mode="expert", dests=("成都", "杭州")):
    return O._build_charts(list(dests), _assessment_fixture(dests), _SENTIMENT, _CLAIMS,
                           "assessment", mode=mode, evidences=_EVIDENCES)


def test_new_charts_land_only_in_their_sections():
    """T-03：图只落在自己声明的章节；同类型多图不得共享归属（根因③回归）。"""
    specs = _assessment_specs()
    new = [s for s in specs if s["title"].startswith(_NEW_TITLES)]
    assert len(new) == 7, f"新增图应恰好 7 张，实得 {[s['title'] for s in new]}"

    for s in new:
        assert s["sections"], f"{s['title']} 缺 sections 归属声明"
        for sid in s["sections"]:
            assert O._charts_for_section(sid, [s], ()) == [s], \
                f"{s['title']} 未落在声明章节 {sid!r}"
    # 同类型多图的归属两两不相交（cost_bar 4 张 / radar 2 张 / growth_bar 3 张）
    by_type = {}
    for s in specs:
        by_type.setdefault(s["type"], []).append(s)
    for ctype, group in by_type.items():
        seen = set()
        for s in group:
            owned = set(s["sections"] or ())
            assert not (owned & seen), \
                f"类型 {ctype!r} 的多张图共享归属 {sorted(owned & seen)}——回到根因③"
            seen |= owned


@pytest.mark.parametrize("mode", ["deep", "expert"])
def test_every_assessment_section_has_charts(mode):
    """用户要求「2-11 章都需要可视化」的直接固化：该档每个章节都得有图。"""
    specs = _assessment_specs(mode)
    allowed = RT.charts_for("assessment", 2)
    missing = [sid for sid in RT.sections_for("assessment", mode)
               if not O._charts_for_section(sid, specs, allowed)]
    assert not missing, f"{mode} 档无图章节：{missing}"


def test_assessment_section_chart_map():
    """逐章锁定图归属（映射表目标态：串章或漏挂在此处直接失败）。"""
    specs = _assessment_specs()
    allowed = RT.charts_for("assessment", 2)

    def titles(sid):
        return [c["title"] for c in O._charts_for_section(sid, specs, allowed)]

    assert titles("summary") == ["目的地宜居度雷达对比",
                                 RT.type_spec("assessment")["share_title"],
                                 "发展轨迹趋势（万人）"]
    assert titles("accessibility") == ["可达性分项对比（本报告算法推断）"]
    assert titles("amenities") == ["配套覆盖度对比（本报告算法推断）"]
    assert titles("safety") == ["目的地安全评分对比", "风险维度热力网格（本报告算法推断）"]
    assert titles("value") == ["月均生活成本对比"]
    assert titles("livelihood") == ["生活成本分项对比（本报告算法推断）"]
    assert titles("trend") == ["发展轨迹趋势（万人）"]
    assert titles("verdict") == ["目的地宜居度雷达对比"]
    assert titles("contrarian") == ["共识 vs 反共识占比（本报告算法推断）"]
    assert titles("conclusion") == ["行动优先级分档（本报告算法推断）"]
    assert titles("risk") == ["证据强度计数（本报告算法推断）"]


def test_new_charts_carry_real_evidence_ids():
    """T-10：新图 evidence_ids 非空且 ⊆ 真实证据集合（图可点开溯源）。"""
    new = [s for s in _assessment_specs() if s["title"].startswith(_NEW_TITLES)]
    for s in new:
        assert s["evidence_ids"], f"{s['title']} 未挂证据（图不可溯源）"
        assert set(s["evidence_ids"]) <= set(_EIDS)


# ── T-08 N=1 / N≥2 ──────────────────────────────────────
@pytest.mark.parametrize("dests,n", [(("成都",), 1), (("成都", "杭州"), 2)])
def test_new_charts_follow_destination_count(dests, n):
    """N 自适应：单城不出份额环图，但拆解型新图照常产出（新图不受 MULTI_ONLY 误伤）。"""
    specs = _assessment_specs(mode="deep", dests=dests)
    types = [s["type"] for s in specs]
    assert set(types) == set(RT.charts_for("assessment", n)), \
        f"N={n} 出图类型集与注册表不符（差集 {set(types) ^ set(RT.charts_for('assessment', n))}）"
    assert ("donut" in types) is (n >= 2)
    assert types.count("growth_bar") == 3, "三张计数/对照图在任何 N 下都应产出"
    solo_new = [s for s in specs if s["title"].startswith(_NEW_TITLES)]
    assert len(solo_new) == 7, "N=1 时七张新图同样齐备（均非 MULTI_ONLY）"


def test_guide_gets_no_new_chart_types():
    """guide 回归：新图类型（growth_bar）不得越界，guide 产出与声明逐项一致。"""
    guide_analysis = {
        "comparison": {"dimensions": ["交通便利", "住宿性价比"],
                       "scores": [{"destination": "大理", "values": [80, 70]}]},
        "budget": [{"destination": "大理", "per_capita_3d": 1800}],
        "season": {"matrix": [{"destination": "大理", "values": [70] * 12}], "note": "气象数据"},
        "share_estimate": [{"name": "大理", "value": 40}, {"name": "丽江", "value": 60}],
        "trends": {"x": ["2024"], "unit": "万人次",
                   "series": [{"name": "大理", "values": [100]}]},
    }
    specs = O._build_charts(["大理", "丽江"], guide_analysis, _SENTIMENT, _CLAIMS,
                            "guide", mode="expert")
    assert [s["type"] for s in specs] == list(RT.charts_for("guide", 2))
    assert not [s for s in specs if s["title"].startswith(_NEW_TITLES)]
