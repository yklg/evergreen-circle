"""图表契约一致性防线（glacial-vale-sparrow 批次⓪ · 测试评估 T-04/T-05/T-16）。

守护的不变量：
- T-16 `_build_charts` 的公开签名与「扁平 List[spec]」返回契约不得变更——
  批次② 要把内部拆成 builder 注册表，但 test_charts_options.py 有 6 处按位置
  直接调用它，签名一动即连带变红。
- T-04 「声明↔数据源键」一致性：某类型一旦进 spec["charts"]，其在 builder
  中所读的数据源键必须已在该类型 analysis_keys / structured_keys 登记。
  补的是既有三层声明校验（test_research_types.py:139/146/152 全部止于「类型」
  抽象层级、且以 set 比对）之外的静默失败面：挂了类型但无数据源 → 永远不出图，
  而三层校验全绿。数据源键的来源 = 每个 builder 自带的 REQUIRES 元组——第五处
  人工对齐的登记表已被消除，声明与实现同处一函数（批次②）。
- T-05 拆分等价 characterization：固化 guide 在当前实现下的产出基线（归一化后
  剔除随机 chart_id），批次② 拆分前后必须逐字节一致。手法复用仓内既有先例
  test_runner_terminal.py:196 的 _bare() 归一化比对思路。

运行：backend/ 下 `pytest tests/test_chart_contract.py -q`
"""
import inspect

import pytest

from app.core.pipeline.research import engine as orchestrator
from app.core import research_types as RT

_TYPES = list(RT.RESEARCH_TYPES)


# ── T-04：图表类型 → 在 builder 中所读的数据源键 ───────────────────
# 语义（REQUIRES 词表，由 orchestrator._builder 声明）：
#   "@radar_key"      读 spec["radar_key"] 指向的 analysis 键
#   "@cost_bar_key"   读 spec["cost_bar"]["key"] 指向的 analysis 键
#   "@sentiment"      数据来自 sentiment 对象，不经 analysis/structured
#   "@claims"         数据来自 claims/evidences（算分图），不经 analysis/structured
#   "a.b"             analysis 顶层键 a；structured.<b> 表示 structured 子键
def _builders_by_type():
    """类型 → 该类型全部 builder（同类型可有多个：cost_bar 有 5 个、growth_bar 有 3 个）。"""
    out = {}
    for fn in orchestrator.CHART_BUILDERS:
        out.setdefault(fn.CHART_TYPE, []).append(fn)
    return out


def _registered_keys(rtype):
    """该类型已登记的全部数据源键（analysis + structured 同一命名空间）。"""
    spec = RT.type_spec(rtype)
    keys = set(spec["analysis_keys"]) | set(spec["structured_keys"])
    return keys, spec


def _resolve(candidate, spec):
    """把候选键描述解析成实际登记名；@sentiment/@claims 返回 None 表示无需 analysis。"""
    if candidate == "@radar_key":
        return spec["radar_key"]
    if candidate == "@cost_bar_key":
        return (spec.get("cost_bar") or {}).get("key")
    if candidate in ("@sentiment", "@claims"):
        return None
    if candidate.startswith("structured."):
        return candidate.split(".", 1)[1]
    return candidate


@pytest.mark.parametrize("rtype", _TYPES)
def test_declared_chart_types_have_data_source(rtype):
    """T-04：spec["charts"] 里每个类型，至少要有一个 builder 的数据源键已登记。

    防线场景：给某类型 charts 加了 season_heat，却没把 season 加进 analysis_keys
    ——既有三层校验全绿，但该图永远生不出来（静默失败）。允许「部分 builder 无源」
    是有意的：同类型的别的 builder 可能只服务另一类型（如 cost_bar 族里
    safety_index 只在 assessment 登记），那些 builder 对该类型自然降级为不出图。
    """
    spec = RT.type_spec(rtype)
    registered, _ = _registered_keys(rtype)
    by_type = _builders_by_type()
    for ctype in spec["charts"]:
        assert ctype in by_type, f"{rtype}: 图表类型 {ctype!r} 没有任何 builder 实现"
        ok = False
        for fn in by_type[ctype]:
            resolved = [_resolve(c, spec) for c in fn.REQUIRES]
            # @sentiment/@claims 解析为 None：声明了该候选即视为有源（舆情链路另行校验）
            if None in resolved or any(k and k in registered for k in resolved):
                ok = True
                break
        assert ok, (
            f"{rtype}: charts 声明了 {ctype!r}，但其 builder（{fn.__name__} 等）的候选数据源 "
            f"无一登记于 analysis_keys/structured_keys —— 该图将永远生不出来"
        )


def test_chart_type_whitelist_covered_by_builders():
    """T-04 自身防漂移：CHART_TYPES 白名单与 builder 注册表必须互相覆盖。

    缺 builder → 声明了类型却永远生不出；builder 类型不在白名单 → 出图越出
    契约面（前端也可能没渲染分派）。两侧都钉住。
    """
    by_type = _builders_by_type()
    assert set(RT.CHART_TYPES) <= set(by_type), \
        f"CHART_TYPES 有类型无 builder 实现：{sorted(set(RT.CHART_TYPES) - set(by_type))}"
    assert set(by_type) <= set(RT.CHART_TYPES), \
        f"builder 产出了契约面外的类型：{sorted(set(by_type) - set(RT.CHART_TYPES))}"
    for fn in orchestrator.CHART_BUILDERS:
        assert fn.REQUIRES, f"{fn.__name__} 未声明 REQUIRES（T-04 将无从校验）"


def test_batch1_new_source_keys_are_registered():
    """批次① 三个新分析键必须三重登记齐备，否则批次② 挂图即静默失败：

    ① 进 assessment analysis_keys（LLM 产出契约）；② 按目的地分行的进 DEST_KEYED_ROWS
    （装配层据此剔除不属于本次目的地的行）；③ 作为 builder 的 REQUIRES 登记（T-04
    据此判「该类型有源」，缺登记则批次② 一致性测试直接红）。
    """
    spec = RT.type_spec("assessment")
    for key in ("livelihood_cost", "action_priorities", "consensus_split"):
        assert key in spec["analysis_keys"], f"{key} 未进 assessment analysis_keys"
    assert ("livelihood_cost", "destination") in RT.DEST_KEYED_ROWS, \
        "livelihood_cost 按目的地分行，未登记进 DEST_KEYED_ROWS"
    by_name = {fn.__name__: fn for fn in orchestrator.CHART_BUILDERS}
    # 三张新图统一走 growth_bar（共识/优先级/证据计数都不是平台数据，
    # platform_bar 内部按 PLATFORM_ORDER 过滤会出空图）——故断言 growth_bar 侧。
    requires = {fn.__name__: set(fn.REQUIRES) for fn in orchestrator.CHART_BUILDERS}
    assert "livelihood_cost" in requires["_chart_livelihood_bar"], \
        "生活成本分项柱的 REQUIRES 未登记 livelihood_cost"
    assert "consensus_split" in requires["_chart_consensus_bar"], \
        "共识vs反共识对照条的 REQUIRES 未登记 consensus_split"
    assert "action_priorities" in requires["_chart_action_priorities"], \
        "行动优先级分档柱的 REQUIRES 未登记 action_priorities"
    assert by_name["_chart_consensus_bar"].CHART_TYPE == "growth_bar", \
        "共识对照条须走 growth_bar（platform_bar 会按平台白名单滤空）"
    assert by_name["_chart_action_priorities"].CHART_TYPE == "growth_bar"
    assert by_name["_chart_evidence_strength"].CHART_TYPE == "growth_bar"


# ── T-03：归属谓词（章节装配与舆情面板的唯一取图入口）─────────────
def test_ownership_predicate_declared_charts_match_by_sections_only():
    """声明了 sections 的图只按归属匹配：同类多图互不串章（根因③最小复现）。

    这正是 assessment deep 档 cost_bar 两图（价值章成本柱 / 安全章评分柱）的
    最小形态——旧实现两章各拿 2 张完全相同的图。
    """
    charts = [
        {"chart_id": "cost", "type": "cost_bar", "sections": ("value",)},
        {"chart_id": "safety", "type": "cost_bar", "sections": ("safety",)},
    ]
    pick = lambda sid: [c["chart_id"] for c in
                        orchestrator._charts_for_section(sid, charts, ("cost_bar",))]
    assert pick("value") == ["cost"]
    assert pick("safety") == ["safety"]


def test_ownership_predicate_declared_overrides_chart_types():
    """sections 是权威：即便章节类型表未声明该类型，归属命中即挂。

    这是批次② builder 自声明「图属哪章」的方向——不必再同步改 SECTION_FIELDS。
    """
    charts = [{"chart_id": "x", "type": "cost_bar", "sections": ("safety",)}]
    assert [c["chart_id"] for c in
            orchestrator._charts_for_section("safety", charts, ())] == ["x"]


def test_ownership_predicate_undeclared_keeps_type_broadcast():
    """sections 缺省 → 旧「按类型广播」行为保留（guide 现有图零变化的结构性保证）。

    未声明的同类型多张会被整组挂出——这是旧行为的事实语义（expert 逐景点词云依赖它），
    故不能把缺省解释成单张。批次② 全量迁移 builder 后此分支应随之消失。
    """
    charts = [{"chart_id": "r1", "type": "radar"}, {"chart_id": "r2", "type": "radar"},
              {"chart_id": "d1", "type": "donut"}]
    assert [c["chart_id"] for c in
            orchestrator._charts_for_section("summary", charts,
                                             ("radar", "donut"))] == ["r1", "r2", "d1"]


def test_sentiment_panel_pick_is_order_independent():
    """打乱产出顺序，舆情专章取图集合不变（旧「按类型取 c[0] 首张」会漂移）。

    批次② 给 contrarian/risk 各配 platform_bar 后，旧实现取到哪张将随产出顺序
    漂移——本用例把该顺序依赖钉死在集合层面。
    """
    charts = [
        {"chart_id": "donut", "type": "sentiment_donut",
         "sections": ("sentiment_report", "sentiment")},
        {"chart_id": "bar-a", "type": "platform_bar",
         "sections": ("sentiment_report", "sentiment")},
        {"chart_id": "bar-other", "type": "platform_bar", "sections": ("contrarian",)},
    ]

    def pick(seq):
        return {c["chart_id"] for c in orchestrator._charts_for_section(
            "sentiment", seq, ("sentiment_donut", "platform_bar"))}

    assert pick(charts) == {"donut", "bar-a"}
    assert pick(list(reversed(charts))) == {"donut", "bar-a"}


# ── T-16：_build_charts 公开签名与返回契约 ────────────────────────
def test_build_charts_signature_is_stable():
    """T-16：签名不得变更——test_charts_options.py 有 6 处按位置调用。

    位置参数顺序 (destinations, analysis, sentiment, claims, research_type)
    是既有契约；批次② 拆分只允许动函数体内部结构。
    """
    sig = inspect.signature(orchestrator._build_charts)
    params = list(sig.parameters)
    assert params[:5] == ["destinations", "analysis", "sentiment", "claims",
                          "research_type"], f"前五个位置参数被改动：{params}"
    assert "mode" in sig.parameters, "mode 关键字参数必须保留"
    assert sig.parameters["claims"].default is not inspect.Parameter.empty, \
        "claims 必须保持有默认值（既有位置调用依赖它可省）"


def test_build_charts_returns_flat_list_of_specs():
    """T-16：返回契约是扁平 List[spec]，不得改为按章节分组的 dict。

    装配层 orchestrator.py:3874-3876 依赖 c["type"] 逐项分组；若批次② 把返回
    结构改掉，3888 的归属逻辑与既有测试会同时崩。
    """
    specs = orchestrator._build_charts(["大理"], {}, {}, [], "guide")
    assert isinstance(specs, list), f"返回类型应为 list，实际 {type(specs)}"
    for s in specs:
        assert isinstance(s, dict) and {"chart_id", "type", "title"} <= set(s)


# ── T-05：guide 产出基线（characterization，拆分前后须逐字节一致）────
def _bare(specs):
    """归一化：剔除随机 chart_id，只留可比较的稳定语义字段。

    chart_id 由 _sid("ch") 生成、含运行时随机性，不剔除则基线永远不稳定。
    """
    out = []
    for s in specs:
        opt = s.get("option") or {}
        series = opt.get("series") or []
        y_axis = opt.get("yAxis")
        out.append({
            "type": s["type"],
            "title": s["title"],
            "y_axis_name": y_axis.get("name") if isinstance(y_axis, dict) else None,
            "series_count": len(series),
            "series_kind": series[0].get("type") if series else None,
            "word_count": len(s.get("words") or []),
        })
    return out


# 当前实现下 guide 的真实产出基线（批次② 拆分前固化；拆分后必须仍然相等）
_GUIDE_BASELINE_SOLO = [
    {"type": "radar", "title": "目的地适配雷达", "y_axis_name": None,
     "series_count": 1, "series_kind": "radar", "word_count": 0},
    {"type": "cost_bar", "title": "人均花费拆解（3 天）", "y_axis_name": "元/人·3天",
     "series_count": 1, "series_kind": "bar", "word_count": 0},
    {"type": "cost_compose", "title": "人均花费构成（元/人）", "y_axis_name": "元/人",
     "series_count": 1, "series_kind": "bar", "word_count": 0},
    {"type": "season_heat", "title": "逐月出行适宜度（1-12 月）", "y_axis_name": None,
     "series_count": 1, "series_kind": "heatmap", "word_count": 0},
    {"type": "trend", "title": "发展轨迹趋势（万人次）", "y_axis_name": "万人次",
     "series_count": 1, "series_kind": "line", "word_count": 0},
    {"type": "sentiment_donut", "title": "整体舆情情感分布", "y_axis_name": None,
     "series_count": 1, "series_kind": "pie", "word_count": 0},
    {"type": "platform_bar", "title": "各平台声量（抖音优先）", "y_axis_name": None,
     "series_count": 1, "series_kind": "bar", "word_count": 0},
    {"type": "wordcloud", "title": "全网口碑热词词云", "y_axis_name": None,
     "series_count": 0, "series_kind": None, "word_count": 2},
]

_GUIDE_BASELINE_MULTI = [
    {"type": "radar", "title": "目的地适配雷达对比", "y_axis_name": None,
     "series_count": 1, "series_kind": "radar", "word_count": 0},
    {"type": "cost_bar", "title": "人均花费对比（3 天）", "y_axis_name": "元/人·3天",
     "series_count": 1, "series_kind": "bar", "word_count": 0},
    {"type": "season_heat", "title": "逐月出行适宜度（1-12 月）", "y_axis_name": None,
     "series_count": 1, "series_kind": "heatmap", "word_count": 0},
    {"type": "donut", "title": "热度/客流份额估算（分析师推断）", "y_axis_name": None,
     "series_count": 1, "series_kind": "pie", "word_count": 0},
    {"type": "trend", "title": "发展轨迹趋势（万人次）", "y_axis_name": "万人次",
     "series_count": 1, "series_kind": "line", "word_count": 0},
    {"type": "sentiment_donut", "title": "整体舆情情感分布", "y_axis_name": None,
     "series_count": 1, "series_kind": "pie", "word_count": 0},
    {"type": "platform_bar", "title": "各平台声量（抖音优先）", "y_axis_name": None,
     "series_count": 1, "series_kind": "bar", "word_count": 0},
    {"type": "wordcloud", "title": "全网口碑热词词云", "y_axis_name": None,
     "series_count": 0, "series_kind": None, "word_count": 2},
]


def _guide_analysis():
    """构造「每种图都有真实数据」的 guide analysis 载荷。

    与 test_charts_options._full_coverage_analysis 同型，但刻意自带一份：
    本仓无跨测试文件 import 先例，且基线夹具若与被测夹具同源，拆分时会同时
    漂移而失去检出力。
    """
    spec = RT.type_spec("guide")
    dims = list(spec["radar_dims"])[:3]
    return {
        spec["radar_key"]: {"dimensions": dims, "scores": [
            {"destination": "大理", "values": [80, 70, 60][:len(dims)]},
            {"destination": "丽江", "values": [60, 75, 55][:len(dims)]}]},
        spec["cost_bar"]["key"]: [
            {"destination": "大理", spec["cost_bar"]["value_field"]: 1800},
            {"destination": "丽江", spec["cost_bar"]["value_field"]: 2200}],
        "season": {"matrix": [{"destination": "大理", "values": [70] * 12}],
                   "note": "气象数据"},
        "share_estimate": [{"name": "大理", "value": 40}, {"name": "丽江", "value": 30}],
        "trends": {"x": ["2023", "2024"], "unit": "万人次",
                   "series": [{"name": "大理", "values": [100, 120]}]},
        "structured": {"cost_breakdown": [{"destination": "大理", "items": [
            {"category": "交通", "amount": 50.0, "unit": "元/人"},
            {"category": "住宿", "amount": 100.0, "unit": "元/人"}]}]},
    }


_GUIDE_SENTIMENT = {
    "sample_size": 12, "overall_count": {"pos": 6, "neu": 4, "neg": 2},
    "by_platform": {"douyin": {"pos": 3, "neu": 1, "neg": 1},
                    "xiaohongshu": {"pos": 2, "neu": 1, "neg": 0}},
    "keywords": [{"word": "古城", "weight": 5}, {"word": "洱海", "weight": 3}],
}


@pytest.mark.parametrize("dests,expected", [
    (["大理"], _GUIDE_BASELINE_SOLO),
    (["大理", "丽江"], _GUIDE_BASELINE_MULTI),
], ids=["solo", "multi"])
def test_guide_chart_output_baseline_unchanged(dests, expected):
    """T-05：guide 产出基线。批次② 把 _build_charts 拆成 builder 注册表后，
    本断言必须仍然通过——guide 一张图都不许多产、少产、换序、换标题、换单位。

    SOLO/MULTI 两侧都钉：cost_compose 与 donut 的 N 侧剔除逻辑（SOLO_ONLY_CHARTS
    / MULTI_ONLY_CHARTS）是拆分时最易写错的一段。
    """
    specs = orchestrator._build_charts(dests, _guide_analysis(), _GUIDE_SENTIMENT,
                                       [], "guide")
    assert _bare(specs) == expected, (
        "guide 图表产出偏离基线——拆分 _build_charts 改变了既有行为"
    )


def test_baseline_covers_all_declared_guide_chart_types():
    """T-05 自检：两份基线**合起来**必须覆盖 guide 声明的每个类型。

    单侧不可能覆盖全——N=1 由 MULTI_ONLY_CHARTS 剔除 donut、N≥2 由 SOLO_ONLY_CHARTS
    剔除 cost_compose，故按并集校验；并顺带把这两处剔除本身钉死（它们正是拆分时
    最易写错的一段，只靠主用例的逐字段比对不够直白）。
    """
    declared = set(RT.type_spec("guide")["charts"])
    solo = {e["type"] for e in _GUIDE_BASELINE_SOLO}
    multi = {e["type"] for e in _GUIDE_BASELINE_MULTI}

    assert solo | multi == declared, (
        f"基线并集与 guide 声明不符，差集：{sorted((solo | multi) ^ declared)}"
    )
    assert "donut" not in solo and "donut" in multi, \
        "MULTI_ONLY_CHARTS 语义漂移：份额环形图只应在多目的地时产出"
    assert "cost_compose" in solo and "cost_compose" not in multi, \
        "SOLO_ONLY_CHARTS 语义漂移：同城花费构成柱只应在单目的地时产出"
