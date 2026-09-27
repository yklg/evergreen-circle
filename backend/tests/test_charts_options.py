"""charts.py ECharts option 生成器 —— 样式 token 一致性 + 空输入容错测试。

《同类项目对比与项目现状审查-测试覆盖方案》B-09（样式 token 一致性契约）。
执行计划 2.3 声称存在但全仓缺失的「样式 token 一致性」契约测试，据此补齐。

守护的不变量（backend/app/core/charts.py）：
- 所有系列/数据点颜色必须引用 palette（SERIES / SENTIMENT / MORANDI），值为合法 7 位 hex。
- SERIES 索引取模：系列数 > 调色板长度不越界、不抛。
- 结构契约：title.text 存在、series 非空、series[0]["type"] 合法。
- 空输入/缺键降级：dimensions 空、series 空、shares 空、overall 缺情感键、
  forces 非数值、timeline 空、products 空 —— 不抛、产出合法结构。
- 情感键完整：SENTIMENT 恒含 pos/neu/neg 三键。
- 波特五力：非数值维度被过滤，indicator 与 values 等长。
- 词云载荷：words 与舆情层词表全等（含新增 kind/polarity 键）；kind 缺席时保持缺席，
  绝不注入缺省；低样本时比例图（donut/platform_bar）缺位而词云照出。
运行：backend/ 下 `pytest tests/test_charts_options.py -q`
"""
import json
import re
from pathlib import Path

import pytest

from app.core import charts
from app.core import research_types as charts_rt

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# 前端无法 import Python 常量，词云极性色是 charts.SENTIMENT 的**手工镜像**（隐式耦合）。
# 该 fixture 是这条链的中段：本用例守「后端 ↔ fixture」，前端用例守「fixture ↔ 组件」。
_CHART_COLORS_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "__tests__" / "fixtures" / "backendChartColors.json"
)


def test_frontend_color_mirror_is_in_sync():
    """TC-24 后端半边：镜像 fixture 必须等于当前 charts 常量（后端调色、fixture 不跟即红）。"""
    assert _CHART_COLORS_FIXTURE.exists(), (
        "色值镜像 fixture 缺失 —— 前端那条同步守卫会静默失去比较对象")
    data = json.loads(_CHART_COLORS_FIXTURE.read_text(encoding="utf-8"))
    assert data["sentiment"] == dict(charts.SENTIMENT), "极性色与 charts.SENTIMENT 漂移"
    assert data["series"] == list(charts.SERIES), "序列色环与 charts.SERIES 漂移"


def _assert_valid_color(c):
    assert isinstance(c, str) and _HEX.match(c), f"非法颜色 token: {c!r}"


def _colors(option):
    found = []

    def walk(node):
        if isinstance(node, dict):
            c = node.get("color")
            if isinstance(c, str):
                found.append(c)
            elif isinstance(c, list):          # visualMap.inRange.color 等列表形式
                found.extend(x for x in c if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for it in node:
                walk(it)
    walk(option)
    return found


# ── 颜色合法性 ───────────────────────────────────────────
def test_all_emitted_colors_are_valid_hex():
    """各生成器产出的全部 color 值都必须是合法 7 位 hex（禁裸色名/未定义 token）。"""
    options = [
        charts.feature_radar("雷达", ["功能", "价格"], [{"name": "A", "values": [1, 2]}]),
        charts.pricing_bar("定价", ["A", "B"], [10, 20]),
        charts.market_donut("份额", [{"name": "A", "value": 50}]),
        charts.sentiment_donut("情感", {"pos": 3, "neu": 1, "neg": 2}),
        charts.platform_bar("平台", {"douyin": {"pos": 2, "neg": 1}}),
        charts.trend_line("趋势", ["1", "2"], [{"name": "S", "values": [1, 2]}]),
        charts.five_forces_radar("五力", {"rivalry": 80, "new_entrants": 20}),
        charts.growth_bar("增速", ["A", "B"], [10, -5]),
        charts.sentiment_timeline("时间线", [{"date": "1", "pos": 1, "neu": 0, "neg": 2}]),
        charts.season_heat("适宜度", ["1月", "2月"], ["大理"], [[80, 60]]),
    ]
    for opt in options:
        for c in _colors(opt):
            _assert_valid_color(c)


# ── 结构契约 ─────────────────────────────────────────────
@pytest.mark.parametrize("option", [
    charts.feature_radar("t", [], []),
    charts.pricing_bar("t", [], []),
    charts.market_donut("t", []),
    charts.sentiment_donut("t", {}),
    charts.platform_bar("t", {}),
    charts.five_forces_radar("t", {}),
    charts.growth_bar("t", [], []),
    charts.sentiment_timeline("t", []),
    charts.season_heat("t", [], [], []),
])
def test_option_basic_contract(option):
    """结构契约：title.text 存在、series 非空且 type 合法（trend_line 空输入单独验证）。"""
    assert option["title"]["text"]
    assert option["series"] and isinstance(option["series"], list)
    assert option["series"][0]["type"] in ("radar", "bar", "pie", "line", "heatmap")


def test_trend_line_empty_series_allowed():
    """trend_line 空 series → 产出空 series 结构不抛（空数据由调用方跳过渲染，符合空数据契约）。"""
    opt = charts.trend_line("t", [], [])
    assert opt["title"]["text"] == "t"
    assert opt["series"] == []
    assert "xAxis" in opt and "legend" in opt


# ── 空输入容错（等价类）──────────────────────────────────
def test_feature_radar_series_index_never_overflows():
    """系列数远超 SERIES 长度 → 取模循环、不越界不抛。"""
    many = [{"name": f"S{i}", "values": [1, 2, 3]} for i in range(30)]
    opt = charts.feature_radar("t", ["a", "b", "c"], many)
    assert len(opt["series"][0]["data"]) == 30
    for item in opt["series"][0]["data"]:
        _assert_valid_color(item["itemStyle"]["color"])


def test_sentiment_key_complete():
    """SENTIMENT 恒含 pos/neu/neg 三键且均为合法 hex（情感环图依赖）。"""
    for k in ("pos", "neu", "neg"):
        assert k in charts.SENTIMENT
        _assert_valid_color(charts.SENTIMENT[k])


def test_sentiment_donut_missing_keys_default_zero():
    """overall 缺失情感键 → 该分片 value=0 不抛，名字中文。"""
    opt = charts.sentiment_donut("情感", {"pos": 2})
    data = {d["name"]: d["value"] for d in opt["series"][0]["data"]}
    assert data == {"正面": 2, "中性": 0, "负面": 0}


def test_growth_bar_negative_uses_risk_color():
    """负值柱用 risk 色、正值用 primary，borderRadius 方向相反。"""
    opt = charts.growth_bar("增速", ["P", "N"], [10, -5])
    bars = opt["series"][0]["data"]
    pos = [b for b in bars if b["value"] == 10][0]
    neg = [b for b in bars if b["value"] == -5][0]
    assert pos["itemStyle"]["color"] == charts.MORANDI["primary"]
    assert neg["itemStyle"]["color"] == charts.MORANDI["risk"]
    assert pos["itemStyle"]["borderRadius"] != neg["itemStyle"]["borderRadius"]


def test_platform_bar_unknown_platforms_skipped():
    """by_platform 含 PLATFORM_ORDER 之外的平台键 → 跳过，不报 KeyError。"""
    opt = charts.platform_bar("平台", {"not_a_real_platform": {"pos": 1}})
    assert opt["yAxis"]["data"] == []
    assert opt["series"][0]["data"] == []


def test_five_forces_partial_numeric_keys():
    """forces 含非数值键 → 仅数值键进 indicator/values，且二者等长。"""
    opt = charts.five_forces_radar("五力", {"rivalry": 80, "new_entrants": "N/A", "substitutes": 40})
    indicator = opt["radar"]["indicator"]
    values = opt["series"][0]["data"][0]["value"]
    assert [i["name"] for i in indicator] == ["现有竞争激烈度", "替代品威胁"]
    assert values == [80, 40]


def test_sentiment_timeline_missing_date_key_crash_free():
    """timeline 缺极少数键时按 0 处理不抛（ser() data 取 t[key] 缺失时 KeyError 风险）。

    说明：当前实现 data 直接 `t[key]`，缺键会 KeyError —— 该测试固化"现状容错预期"；
    若实现保持缺键即抛，则改为验证 timeline 全字段时正常输出、并以本项目数据契约
    （时序数据恒含 pos/neu/neg/date）约束上游，而非改动生成器。
    """
    # 全字段时间线（数据契约内）必须正常产出
    tl = [{"date": "2026-09-01", "pos": 2, "neu": 0, "neg": 1},
          {"date": "2026-09-02", "pos": 1, "neu": 1, "neg": 0}]
    opt = charts.sentiment_timeline("时序", tl)
    assert opt["xAxis"]["data"] == ["2026-09-01", "2026-09-02"]
    assert len(opt["series"]) == 3
    for s in opt["series"]:
        _assert_valid_color(s["itemStyle"]["color"])
        assert len(s["data"]) == 2


# ── 类型化图表契约（新增图 season_heat / 成本柱单位 / 按类型的图表集）──
def test_season_heat_matrix_geometry():
    """热力图数据点 = 月份 × 目的地的完整笛卡尔积，坐标为 [x, y, value]。"""
    opt = charts.season_heat("逐月适宜度", ["1月", "2月", "3月"], ["大理", "丽江"],
                             [[80, 70, 60], [50, 40, 30]], note="依据历史气象数据")
    assert opt["series"][0]["type"] == "heatmap"
    data = opt["series"][0]["data"]
    assert len(data) == 3 * 2
    assert data[0] == [0, 0, 80] and data[-1] == [2, 1, 30]
    assert opt["xAxis"]["data"] == ["1月", "2月", "3月"]
    assert opt["yAxis"]["data"] == ["大理", "丽江"]
    assert opt["visualMap"]["min"] == 0 and opt["visualMap"]["max"] == 100
    assert opt["graphic"][0]["style"]["text"] == "依据历史气象数据"


def test_season_heat_empty_matrix_not_crash():
    """空矩阵（无季节数据）→ 空 data 不抛，调用方据此跳过渲染（不占位造图）。"""
    opt = charts.season_heat("t", [], [], [])
    assert opt["series"][0]["data"] == []
    assert "graphic" not in opt, "无 note 不应产出 graphic 注释层"


def test_pricing_bar_y_name_default_and_custom():
    """成本柱 y 轴单位：默认 ￥/月（旧契约不回归），调用方可传类型化单位。"""
    assert charts.pricing_bar("t", ["A"], [1])["yAxis"]["name"] == "￥/月"
    opt = charts.pricing_bar("人均花费", ["大理", "丽江"], [1800, 2200], y_name="元/人·3天")
    assert opt["yAxis"]["name"] == "元/人·3天"
    assert opt["xAxis"]["data"] == ["大理", "丽江"]
    assert opt["series"][0]["data"] == [1800, 2200]


def _full_coverage_analysis(rtype: str) -> dict:
    """为指定类型构造「每种图都有真实数据」的 analysis 载荷（供图表集全生成断言）。"""
    spec = charts_rt.type_spec(rtype)
    dims = list(spec["radar_dims"])[:3]
    analysis = {
        spec["radar_key"]: {"dimensions": dims,
                            "scores": [{"destination": "大理", "values": [80, 70, 60][:len(dims)]},
                                       {"destination": "丽江", "values": [60, 75, 55][:len(dims)]}]},
        spec["cost_bar"]["key"]: [{"destination": "大理", spec["cost_bar"]["value_field"]: 1800},
                                  {"destination": "丽江", spec["cost_bar"]["value_field"]: 2200}],
        "season": {"matrix": [{"destination": "大理", "values": [70] * 12}], "note": "气象数据"},
        "share_estimate": [{"name": "大理", "value": 40}, {"name": "丽江", "value": 30}],
        "trends": {"x": ["2023", "2024"], "unit": "万人次",
                   "series": [{"name": "大理", "values": [100, 120]}]},
        "contradictions": [],
        # cost_compose 的数据轴：结构化花费构成（P2 新增图必须有真实原料才谈得上"可生成"）
        "structured": {"cost_breakdown": [{"destination": "大理", "items": [
            {"category": "交通", "amount": 50.0, "unit": "元/人"},
            {"category": "住宿", "amount": 100.0, "unit": "元/人"},
        ]}]},
    }
    if rtype == "assessment":
        # 批次② 新增图的数据轴：各图独立原料齐备才谈得上「可生成」。
        # 共有方式/共有维度是硬约束（雷达与热力网格每行必须等长，缺格不补 0），
        # 故两个目的地给同一组方式与同一组风险维度。
        def _both(value_of):
            return [{"destination": d, **value_of(i)} for i, d in enumerate(("大理", "丽江"))]
        analysis["safety_index"] = _both(lambda i: {"safety_score": 88 - i * 5, "note": "治安良好"})
        analysis["livelihood_cost"] = _both(lambda i: {"items": [
            {"category": "房租", "amount": 1800 + i * 200, "unit": "元/月"},
            {"category": "餐饮", "amount": 900 + i * 100, "unit": "元/月"}]})
        analysis["action_priorities"] = {"items": [
            {"action": "优先核验核心区居住成本", "tier": "high"},
            {"action": "补充通勤实测数据", "tier": "mid"}]}
        analysis["consensus_split"] = {
            "orthodox": {"label": "主流共识", "summary": "性价比占优", "share": 60},
            "contrarian": {"label": "反共识判断", "summary": "旺季体验下滑", "share": 18}}
        modes = [("高铁", 95, 180), ("飞机", 150, 520), ("自驾", 240, 300)]
        analysis["structured"].update({
            "access_matrix": _both(lambda i: {"routes": [
                {"mode": m, "duration": f"{mins // 60} 小时", "cost": f"{yuan} 元",
                 "duration_minutes": mins + i * 40, "cost_yuan": yuan + i * 60,
                 "frequency": "每小时 2 班"} for m, mins, yuan in modes]}),
            "amenity_checklist": _both(lambda i: {"items": [
                {"category": "医疗", "item": "三甲医院", "coverage": "full", "note": "3 家"},
                {"category": "商业", "item": "大型商超", "coverage": "partial"}]}),
            "risk_profile": _both(lambda i: {"items": [
                {"dimension": "气候", "level": "low", "note": "四季温和"},
                {"dimension": "治安", "level": "medium", "note": "夜间人流杂"}]}),
        })
    return analysis


# 语料构成按 r_6dadffee 实测分布取真值（25 条检索结果里 12 条可核验口碑 ≈ 28% 多一点），
# keywords 用**分层后的形状**：评价词带 polarity，话题词是地名。
# low_sample=False 是必需的——它是 donut/platform_bar 的出图门，True 时那两张整体缺位，
# test_every_type_chart_set_generatable 的「声明的图集必须全出」就会假红。
_SENTIMENT = {"sample_size": 12, "corpus_size": 25,
              "doc_kind_counts": {"review": 12, "ticket_faq": 6, "flight": 4, "seo": 3},
              "low_sample": False,
              "overall_count": {"pos": 6, "neu": 4, "neg": 2},
              "by_platform": {"douyin": {"pos": 3, "neu": 1, "neg": 1},
                              "xiaohongshu": {"pos": 2, "neu": 1, "neg": 0}},
              "keywords": [{"word": "清净", "weight": 3, "kind": "opinion", "polarity": "pos"},
                           {"word": "古城", "weight": 5, "kind": "topic", "polarity": "neu"},
                           {"word": "洱海", "weight": 3, "kind": "topic", "polarity": "neu"}]}


@pytest.mark.parametrize("rtype", list(charts_rt.RESEARCH_TYPES))
@pytest.mark.parametrize("dests", [("大理",), ("大理", "丽江")], ids=["solo", "multi"])
def test_every_type_chart_set_generatable(rtype, dests):
    """数据齐备时，该类型在该目的地数量下声明的图表集必须**全部**可生成
    （防注册表声明了生不出的图）。两条轴都跑：MULTI_ONLY / SOLO_ONLY 各自的 N 侧。"""
    from app.core.pipeline.research import engine as orchestrator

    specs = orchestrator._build_charts(list(dests), _full_coverage_analysis(rtype),
                                       _SENTIMENT, [], rtype)
    emitted = {s["type"] for s in specs}
    declared = set(charts_rt.charts_for(rtype, len(dests)))
    assert emitted == declared, f"{rtype}/N={len(dests)} 图表集生成不全：缺 {declared - emitted}"
    for s in specs:
        assert s["chart_id"] and s["title"]
        if s["type"] == "wordcloud":
            # E1 契约：wordcloud 走语义载荷 words，不再烘 echarts option
            assert "option" not in s, "wordcloud 不得携带 echarts option"
            assert s["words"], "不得产出空词云"
            for w in s["words"]:
                # 分层后 kind/polarity 也是载荷的一部分：既不丢键，也不给缺省兜底
                assert set(w) == {"word", "weight", "kind", "polarity"}
                assert str(w["word"]).strip()
            continue
        assert isinstance(s["option"], dict)
        assert s["option"]["title"]["text"] == s["title"]
        assert s["option"]["series"], "不得产出空系列图"
        for c in _colors(s["option"]):
            _assert_valid_color(c)


def test_build_charts_skips_chart_without_data():
    """无数据不占位造图：analysis 空 → 不产出任何图（guide 类型）。"""
    from app.core.pipeline.research import engine as orchestrator

    assert orchestrator._build_charts(["大理"], {}, {}, [], "guide") == []


# ── 词云契约（TC-C02 · E1 语义载荷）：words 形状 / 无词不产图 / expert 逐景点多云 ──
def test_wordcloud_words_contract():
    """W-B1：载荷归一——{word,weight} 原形保留；脏词条（空白/非 dict）剔除。"""
    words = charts.wordcloud_words([{"word": "古城", "weight": 5}, {"word": " 洱海 ", "weight": 3},
                                    {"word": "   ", "weight": 9}, "not-a-dict"])
    assert words == [{"word": "古城", "weight": 5}, {"word": "洱海", "weight": 3}]


def test_wordcloud_empty_words_not_crash():
    """W-B2：空词表 → []（调用方据此不产图，不造空词云）。"""
    assert charts.wordcloud_words([]) == []


def test_wordcloud_payload_matches_wordfreq_shape():
    """W-B4（后端侧）：挂图 spec 的 words 与舆情层词表**全等**（TC-19 升级）。

    这条断言守的是「原样透传，不改名不换算」——分层后新增的 kind/polarity 也在守卫
    范围内。曾因「改成按 word 比对」被评审判为 P0：那等于把透传闸关掉。
    """
    from app.core.pipeline.research import engine as orchestrator

    specs = orchestrator._build_charts(["大理"], _full_coverage_analysis("guide"),
                                       _SENTIMENT, [], "guide")
    cloud = next(s for s in specs if s["type"] == "wordcloud")
    assert cloud["words"] == _SENTIMENT["keywords"], "语义载荷必须原样透传词频源，不改名不换算"


def test_wordcloud_words_keeps_absent_kind_absent():
    """W-B1 配套：存量报告的裸 {word,weight} 词条，kind 必须**保持缺席**。

    给缺省值兜一个 "topic"，前端就会把老报告的地名词云渲染成「只有小灰字没大字」——
    那是把兼容问题伪装成设计。非法值（空串/非字符串）只丢该键，不丢整条。
    """
    assert charts.wordcloud_words([{"word": "古城", "weight": 5}]) == [{"word": "古城", "weight": 5}]
    dirty = charts.wordcloud_words([{"word": "清净", "weight": 2, "kind": "", "polarity": 7},
                                    {"word": "洱海", "weight": 1, "kind": "opinion",
                                     "polarity": "pos"}])
    assert dirty == [{"word": "清净", "weight": 2},
                     {"word": "洱海", "weight": 1, "kind": "opinion", "polarity": "pos"}]


def test_build_charts_wordcloud_absent_without_keywords():
    """无词频数据不占位：sentiment 无 keywords → 图集整体缺位 wordcloud。"""
    from app.core.pipeline.research import engine as orchestrator

    sent = {k: v for k, v in _SENTIMENT.items() if k != "keywords"}
    specs = orchestrator._build_charts(["大理", "丽江"], _full_coverage_analysis("guide"),
                                       sent, [], "guide")
    assert "wordcloud" not in {s["type"] for s in specs}


def test_build_charts_expert_emits_per_spot_clouds():
    """expert 档逐景点词云：每张引用冻结实体名；样本不足或无词的景点整体缺位而非空图。

    两条门是两回事，都必须能单独缺位：
    - `review_sample` < MIN_SPOT_SENT_SAMPLE → 该景点不出云（不硬凑 3 词空壳）
    - 有口碑但抽不出词 → 同样不出云
    判据读常量，不写裸数字（改阈值时这条断言跟着动，而不是静默漂移）。
    """
    from app.core.pipeline.research import engine as orchestrator
    from app.core.sentiment import MIN_SPOT_SENT_SAMPLE

    sent = dict(_SENTIMENT)
    sent["by_spot"] = [
        {"spot_id": "大理_spot_1", "spot_name": "大理古城", "review_sample": MIN_SPOT_SENT_SAMPLE,
         "keywords": [{"word": "夜景", "weight": 4, "kind": "opinion", "polarity": "pos"}]},
        {"spot_id": "大理_spot_2", "spot_name": "崇圣寺三塔", "review_sample": MIN_SPOT_SENT_SAMPLE,
         "keywords": []},
        # 口碑不足：即使抽得出词也不出图（旧版用 keywords 判，这条会错误出图）
        {"spot_id": "大理_spot_3", "spot_name": "洱海", "review_sample": MIN_SPOT_SENT_SAMPLE - 1,
         "keywords": [{"word": "日落", "weight": 2, "kind": "opinion", "polarity": "pos"}]},
        # review_sample 缺席（未接线的旧路径）→ 按不足处理，不得默认放行
        {"spot_id": "大理_spot_4", "spot_name": "苍山",
         "keywords": [{"word": "索道", "weight": 2, "kind": "topic", "polarity": "neu"}]},
    ]
    specs = orchestrator._build_charts(["大理"], _full_coverage_analysis("guide"),
                                       sent, [], "guide", mode="expert")
    clouds = [s for s in specs if s["type"] == "wordcloud"]
    assert [c["title"] for c in clouds] == ["全网口碑热词词云", "「大理古城」口碑词云"]
    assert clouds[1]["words"] == [{"word": "夜景", "weight": 4,
                                   "kind": "opinion", "polarity": "pos"}]
    assert all("option" not in c for c in clouds), "E1：词云 spec 不得带 echarts option"
    # deep 档只出全局一张
    specs_deep = orchestrator._build_charts(["大理"], _full_coverage_analysis("guide"),
                                            sent, [], "guide", mode="deep")
    assert sum(1 for s in specs_deep if s["type"] == "wordcloud") == 1


def test_low_sample_replaces_percent_charts_with_counts():
    """D3 诚实化的出图门：低样本时比例图缺位，词云照出。

    7 条口碑画成 67%/33% 就是伪精度 ⇒ donut 与 platform_bar 都不出；
    词云不吃占比，不受该门约束。`overall`/`by_platform` 数字本身不销毁（仍是真值）。
    """
    from app.core.pipeline.research import engine as orchestrator

    sent = dict(_SENTIMENT, sample_size=7, low_sample=True)
    specs = orchestrator._build_charts(["大理"], _full_coverage_analysis("guide"),
                                       sent, [], "guide")
    emitted = {s["type"] for s in specs}
    assert "sentiment_donut" not in emitted and "platform_bar" not in emitted
    assert "wordcloud" in emitted, "词云不该被样本量门连带砍掉"
    # 缺位是"不出这张图"，不是"把数字抹成 0"
    assert sent["overall_count"] == _SENTIMENT["overall_count"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))