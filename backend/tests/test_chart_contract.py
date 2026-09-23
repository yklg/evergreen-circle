"""图表契约一致性防线（glacial-vale-sparrow 批次⓪ · 测试评估 T-04/T-05/T-16）。

守护的不变量：
- T-16 `_build_charts` 的公开签名与「扁平 List[spec]」返回契约不得变更——
  批次② 要把内部拆成 builder 注册表，但 test_charts_options.py 有 6 处按位置
  直接调用它，签名一动即连带变红。
- T-04 「声明↔数据源键」一致性：某类型一旦进 spec["charts"]，其在 _build_charts
  中所读的数据源键必须已在该类型 analysis_keys / structured_keys 登记。
  补的是既有三层声明校验（test_research_types.py:139/146/152 全部止于「类型」
  抽象层级、且以 set 比对）之外的静默失败面：挂了类型但无数据源 → 永远不出图，
  而三层校验全绿。
- T-05 拆分等价 characterization：固化 guide 在当前实现下的产出基线（归一化后
  剔除随机 chart_id），批次② 拆分前后必须逐字节一致。手法复用仓内既有先例
  test_runner_terminal.py:196 的 _bare() 归一化比对思路。

过渡说明（诚实标注）：CHART_SOURCE_KEYS 是一张「类型 → 允许的数据源键」手工
登记表，本身构成第五处需人工对齐的声明源。批次② 落地 builder 注册表后，本表
应由每个 builder 自带的 REQUIRES 元组取代，测试改为遍历 CHART_BUILDERS——
届时删除本表。当前以「任一候选键命中即通过」放宽，只为先挡住「完全无数据源」。

运行：backend/ 下 `pytest tests/test_chart_contract.py -q`
"""
import inspect

import pytest

from app.core import orchestrator
from app.core import research_types as RT

_TYPES = list(RT.RESEARCH_TYPES)

# ── T-04：图表类型 → 在 _build_charts 中所读的数据源键 ──────────────
# 语义：
#   "@radar_key"      读 spec["radar_key"] 指向的 analysis 键
#   "@cost_bar_key"   读 spec["cost_bar"]["key"] 指向的 analysis 键
#   "@sentiment"      数据来自 sentiment 对象，不经 analysis/structured
#   "a.b"             analysis 顶层键 a；structured.<b> 表示 structured 子键
# 值为「候选键元组」：同一类型可由不同原料驱动（如 season_heat 既读 season
# 也读 structured.risk_profile），任一已在该类型登记即视为有源。
CHART_SOURCE_KEYS = {
    "radar": ("@radar_key",),
    "cost_bar": ("@cost_bar_key",),
    "cost_compose": ("structured.cost_breakdown",),
    "season_heat": ("season", "structured.risk_profile"),
    "donut": ("share_estimate",),
    "trend": ("trends",),
    "sentiment_donut": ("@sentiment",),
    "platform_bar": ("@sentiment",),
    "wordcloud": ("@sentiment",),
    "growth_bar": ("action_priorities",),
}


def _registered_keys(rtype):
    """该类型已登记的全部数据源键（analysis + structured 同一命名空间）。"""
    spec = RT.type_spec(rtype)
    keys = set(spec["analysis_keys"]) | set(spec["structured_keys"])
    return keys, spec


def _resolve(candidate, spec):
    """把候选键描述解析成实际登记名；@sentiment 类返回 None 表示无需 analysis。"""
    if candidate == "@radar_key":
        return spec["radar_key"]
    if candidate == "@cost_bar_key":
        return (spec.get("cost_bar") or {}).get("key")
    if candidate == "@sentiment":
        return None
    if candidate.startswith("structured."):
        return candidate.split(".", 1)[1]
    return candidate


@pytest.mark.parametrize("rtype", _TYPES)
def test_declared_chart_types_have_data_source(rtype):
    """T-04：spec["charts"] 里每个类型，必须至少有一个候选数据源键已登记。

    防线场景：给某类型 charts 加了 season_heat，却没把 season 加进 analysis_keys
    ——既有三层校验全绿，但该图永远生不出来（静默失败）。
    """
    spec = RT.type_spec(rtype)
    registered, _ = _registered_keys(rtype)
    for ctype in spec["charts"]:
        assert ctype in CHART_SOURCE_KEYS, \
            f"{rtype}: 图表类型 {ctype!r} 未在 CHART_SOURCE_KEYS 登记其数据源键"
        candidates = CHART_SOURCE_KEYS[ctype]
        resolved = [_resolve(c, spec) for c in candidates]
        # @sentiment 解析为 None：只要声明了该候选即视为有源（舆情链路另行校验）
        if None in resolved:
            continue
        hit = [k for k in resolved if k and k in registered]
        assert hit, (
            f"{rtype}: charts 声明了 {ctype!r}，但其候选数据源 {candidates} "
            f"无一登记于 analysis_keys/structured_keys —— 该图将永远生不出来"
        )


def test_chart_source_keys_table_covers_whitelist():
    """T-04 自身防漂移：CHART_TYPES 白名单里每个类型都得在登记表有条目。

    否则新增图表类型时会悄悄绕过 T-04 校验。
    """
    missing = set(RT.CHART_TYPES) - set(CHART_SOURCE_KEYS)
    assert not missing, f"CHART_SOURCE_KEYS 缺登记：{sorted(missing)}"


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
