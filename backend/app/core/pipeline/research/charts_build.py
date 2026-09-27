"""图表构建器注册表（M3 自 engine.py 提取 · 行为零变化）。

18 个 @_builder 注册的纯构建器 + ChartContext 装配 + 章节归属谓词 + 数据网格。
依赖方向：charts_build → _util / core 叶子（charts/scoring/research_types/sentiment/models），
**不反向依赖 engine**。CHART_BUILDERS 等符号由 engine re-export 保持既有接缝。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import charts as C
from app.core import research_types as RT
from app.core import scoring as SC
from app.core.fetcher import domain_of
from app.core.models import Evidence
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core.sentiment import MIN_SPOT_SENT_SAMPLE, PLATFORM_ORDER

from ._util import _row_dest_ok, _row_name, _sid

_ALGO_TAG = "（本报告算法推断）"

_SENT_SECTIONS: Tuple[str, ...] = ("sentiment_report", "sentiment")

@dataclass(frozen=True)
class ChartContext:
    """图表构建上下文：收拢原先散在 _build_charts 闭包里的依赖，builder 免长签名。

    builder 只读本对象：allowed=按目的地数过滤后的图集（charts_for）、own=目的地行兜底、
    eids=按 claim 字段收证据、new_id=chart_id 生成。新增一类图不动编排层。
    """
    destinations: List[str]
    analysis: Dict[str, Any]
    sentiment: Dict[str, Any]
    claims: List[Any]
    evidences: List[Any]
    spec: Dict[str, Any]
    allowed: frozenset
    mode: str
    research_type: str
    own: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    eids: Callable[..., List[str]]
    new_id: Callable[[str], str]
    # 缺口台账（③ 体验层）：builder 在「有材料但算不出」时记一条，装配层据此如实标注。
    # 与「无材料不出图」区分：无材料属数据采集缺口，有材料无值属算分输入缺口。
    gaps: List[Dict[str, Any]] = field(default_factory=list)

    def section_evidence(self, *sections: str) -> List[str]:
        """图挂哪章就挂哪章的结论证据：只吃 builder 自声明的 sections。

        不做「图表类型 → 全表反查」——那会把别的章（乃至别的类型）的证据混进来，
        且共享章节（conclusion/risk/contrarian 两类型都有）反查不出类型级归属。
        """
        fields: List[str] = []
        for sid in sections:
            fields.extend(RT.section_fields(sid)[0])
        return self.eids(*fields)

    def note_gap(self, *sections: str, reason: str) -> None:
        """记一条「有材料但算不出」的缺口（frozen 只锁属性重绑，台账是共享列表）。

        只有 builder 知道自己为什么没出图——把「判据」与「缺口文案」放在同一处，
        装配层不再反推（反推即第二处口径，改算分公式时必然漂移）。
        """
        self.gaps.append({"sections": tuple(sections), "reason": reason})

    def sections_exist(self, *sections: str) -> bool:
        """builder 自声明的章节是否属于本类型（跨类型 builder 的类型门）。

        `allowed` 只按目的地数过滤图类型，管不住「某类型根本没有这一章」：评估类图的
        数据源若落到 guide（如外部传入 access_matrix），会产出无人认领的图与缺口——
        装配层取不到（图消失），事件流里却多一张（图凭空出现）。
        """
        plan: set = set()
        for ids in (self.spec.get("sections") or {}).values():
            plan.update(ids)
        return all(s in plan for s in sections)


def _builder(chart_type: str, requires: Tuple[str, ...]):
    """注册元数据：图类型 + 候选数据源键（T-04 遍历 CHART_BUILDERS 校验，不再另维护映射表）。

    requires 词表见 tests/test_chart_contract.py：@radar_key/@cost_bar_key/@sentiment/@claims
    为派生键，`a.b` 指 structured 子键，其余为 analysis 顶层键。
    """
    def deco(fn):
        fn.CHART_TYPE = chart_type
        fn.REQUIRES = requires
        return fn
    return deco


def _cost_axis_labels(items: List[Dict[str, Any]]) -> List[str]:
    """同目的地多档位时把档位拼进 x 轴，否则三根柱子都叫「大理」，看不出差异。"""
    names = [_row_name(r) for r in items]
    same_dest_multi = len(names) > 1 and len(set(names)) < len(names)
    out: List[str] = []
    for r in items:
        dest_name = _row_name(r)
        tier = str(r.get("tier") or "").strip()
        out.append(f"{dest_name}·{tier}" if (same_dest_multi and tier) else (dest_name or "—"))
    return out


def _dest_prefixed(dest: str, name: str, multi: bool) -> str:
    """多目的地时把目的地拼进 x 轴标签，否则两个城市的「房租」两根柱子同名。"""
    return f"{dest}·{name}" if (multi and dest) else name


@_builder("radar", ("@radar_key",))
def _chart_radar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """宜居度/适配度雷达（summary/verdict 章）：数据源 spec["radar_key"] 的维度分。"""
    if "radar" not in ctx.allowed:
        return []
    sections = ("summary", "verdict")
    radar = ctx.analysis.get(ctx.spec["radar_key"]) or {}
    dims = radar.get("dimensions") or []
    scores = [s for s in ctx.own(radar.get("scores") or [])
              if dims and isinstance(s.get("values"), list) and len(s["values"]) == len(dims)]
    if not (dims and scores):
        return []
    title = RT.radar_title(ctx.research_type, len(ctx.destinations))
    series = [{"name": s["destination"], "values": s["values"]} for s in scores[:4]]
    return [{"chart_id": ctx.new_id("ch"), "type": "radar", "title": title,
             "sections": sections, "option": C.feature_radar(title, dims, series),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("cost_bar", ("@cost_bar_key",))
def _chart_cost_bar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """月均/人均成本柱：guide 挂预算章、assessment 挂性价比章。

    sections 声明取两类型章节的**并集**——两类型各自只含其一（guide 有 budget 无 value、
    assessment 反之），按归属匹配不会串章，也不必在编排层按类型分支。
    """
    cb = ctx.spec.get("cost_bar") or {}
    if "cost_bar" not in ctx.allowed or not cb:
        return []
    rows = [r for r in ctx.own(ctx.analysis.get(cb["key"]) or [])
            if isinstance(r.get(cb["value_field"]), (int, float))]
    if not rows:
        return []
    sections = ("budget", "value")
    title = RT.cost_bar_title(ctx.research_type, len(ctx.destinations))
    return [{"chart_id": ctx.new_id("ch"), "type": "cost_bar", "title": title,
             "sections": sections,
             "option": C.pricing_bar(title, _cost_axis_labels(rows),
                                     [float(r[cb["value_field"]]) for r in rows],
                                     y_name=cb["unit"]),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("cost_bar", ("safety_index",))
def _chart_safety_score(ctx: ChartContext) -> List[Dict[str, Any]]:
    """安全评分柱（safety 章）：数据源 analysis.safety_index[].safety_score（0-100 整数）。"""
    if "cost_bar" not in ctx.allowed:
        return []
    rows = [r for r in ctx.own(ctx.analysis.get("safety_index") or [])
            if isinstance(r.get("safety_score"), (int, float))]
    if not rows:
        return []
    sections = ("safety",)
    title = "目的地安全评分对比" if len(ctx.destinations) >= 2 else "目的地安全评分"
    return [{"chart_id": ctx.new_id("ch"), "type": "cost_bar", "title": title,
             "sections": sections,
             "option": C.pricing_bar(title, [_row_name(r) for r in rows],
                                     [float(r["safety_score"]) for r in rows],
                                     y_name="分（0-100）"),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("cost_compose", ("structured.cost_breakdown",))
def _chart_cost_compose(ctx: ChartContext) -> List[Dict[str, Any]]:
    """人均花费构成柱（budget 章 · SOLO_ONLY）：数据源 structured.cost_breakdown。"""
    if "cost_compose" not in ctx.allowed:
        return []
    items: List[Dict[str, Any]] = []
    for grp in ctx.own((ctx.analysis.get("structured") or {}).get("cost_breakdown") or []):
        items.extend(i for i in (grp.get("items") or []) if isinstance(i, dict))
    items = [i for i in items if isinstance(i.get("amount"), (int, float))
             and str(i.get("category") or "").strip()]
    if not items:
        return []
    sections = ("budget",)
    unit = str(items[0].get("unit") or "元/人").strip()
    title = f"人均花费构成（{unit}）"
    return [{"chart_id": ctx.new_id("ch"), "type": "cost_compose", "title": title,
             "sections": sections,
             "option": C.pricing_bar(title, [str(i["category"]).strip() for i in items],
                                     [float(i["amount"]) for i in items], y_name=unit),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("season_heat", ("season",))
def _chart_season_heat(ctx: ChartContext) -> List[Dict[str, Any]]:
    """逐月出行适宜度热力（season 章）：数据源 analysis.season.matrix（12 个月）。"""
    if "season_heat" not in ctx.allowed:
        return []
    season = ctx.analysis.get("season") or {}
    matrix = [m for m in ctx.own(season.get("matrix") or [])
              if isinstance(m.get("values"), list) and len(m["values"]) == 12]
    if not matrix:
        return []
    sections = ("season",)
    title = "逐月出行适宜度（1-12 月）"
    return [{"chart_id": ctx.new_id("ch"), "type": "season_heat", "title": title,
             "sections": sections,
             "option": C.season_heat(title, [f"{i}月" for i in range(1, 13)],
                                     [m["destination"] for m in matrix],
                                     [m["values"] for m in matrix],
                                     str(season.get("note") or "")),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("donut", ("share_estimate",))
def _chart_donut(ctx: ChartContext) -> List[Dict[str, Any]]:
    """热度/客流份额环图（summary 章 · MULTI_ONLY）：数据源 analysis.share_estimate。"""
    if "donut" not in ctx.allowed:
        return []
    share = [s for s in ctx.own(ctx.analysis.get("share_estimate") or [])
             if isinstance(s.get("value"), (int, float))]
    if not share:
        return []
    sections = ("summary",)
    title = ctx.spec["share_title"]
    return [{"chart_id": ctx.new_id("ch"), "type": "donut", "title": title,
             "sections": sections,
             "option": C.market_donut(title, [{"name": s["name"], "value": s["value"]}
                                              for s in share]),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("trend", ("trends",))
def _chart_trend(ctx: ChartContext) -> List[Dict[str, Any]]:
    """发展轨迹折线（summary/trend 章）：数据源 analysis.trends（x 与各序列等长才出图）。"""
    if "trend" not in ctx.allowed:
        return []
    tr = ctx.analysis.get("trends") or {}
    tx = tr.get("x") if isinstance(tr.get("x"), list) else []
    tseries = [s for s in ctx.own(tr.get("series") or [])
               if tx and isinstance(s.get("values"), list) and len(s["values"]) == len(tx)]
    if not (tx and tseries):
        return []
    sections = ("summary", "trend")
    title = f"发展轨迹趋势（{tr.get('unit', '')}）".replace("（）", "")
    return [{"chart_id": ctx.new_id("ch"), "type": "trend", "title": title,
             "sections": sections,
             "option": C.trend_line(title, tx,
                                    [{"name": s["name"], "values": s["values"]}
                                     for s in tseries[:5]],
                                    y_name=tr.get("unit", "")),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("sentiment_donut", ("@sentiment",))
def _chart_sentiment_donut(ctx: ChartContext) -> List[Dict[str, Any]]:
    """整体情感分布环图（舆情章）：数据源 sentiment.overall_count。

    小样本不出比例图：7 条口碑画成 67%/33% 就是伪精度。判据读 `low_sample`
    （阈值口径只在 sentiment.MIN_SENT_SAMPLE 一处），此处不另写数字。
    """
    if "sentiment_donut" not in ctx.allowed or not ctx.sentiment.get("sample_size"):
        return []
    if ctx.sentiment.get("low_sample"):
        return []
    title = "整体舆情情感分布"
    return [{"chart_id": ctx.new_id("ch"), "type": "sentiment_donut", "title": title,
             "sections": _SENT_SECTIONS,
             "option": C.sentiment_donut(title, ctx.sentiment["overall_count"]),
             "evidence_ids": []}]


@_builder("platform_bar", ("@sentiment",))
def _chart_platform_bar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """各平台声量柱（舆情章）：数据源 sentiment.by_platform。

    只吃平台键白名单（C.platform_bar 内部按 PLATFORM_ORDER 过滤）——非平台数据的
    对照条（共识/证据计数）走 growth_bar，不借用本图类型。

    小样本门与环图一致（读 `low_sample`，不另写阈值）：声量柱的占比读数同样
    建立在样本量上，7 条评论画「抖音 3 / 携程 2」的相对高度就是伪精度。
    """
    if "platform_bar" not in ctx.allowed or not ctx.sentiment.get("sample_size"):
        return []
    if ctx.sentiment.get("low_sample"):
        return []
    by_platform = ctx.sentiment.get("by_platform")
    if not by_platform:
        return []
    title = "各平台声量（抖音优先）"
    return [{"chart_id": ctx.new_id("ch"), "type": "platform_bar", "title": title,
             "sections": _SENT_SECTIONS,
             "option": C.platform_bar(title, by_platform), "evidence_ids": []}]


@_builder("wordcloud", ("@sentiment",))
def _chart_wordcloud(ctx: ChartContext) -> List[Dict[str, Any]]:
    """口碑词云（M2d · E1 语义载荷）：评价词 + 话题词分层为源；无词不产图。

    词表由 opinions.extract_opinions（评价词，带 kind/polarity）+ extract_topics
    （话题词，地名）分层产出，不再是 wordfreq 通用词频。

    expert 档在「全网口碑词云」之外逐景点各出一张（引用冻结实体名与行内真实词频）。
    """
    if "wordcloud" not in ctx.allowed:
        return []
    out: List[Dict[str, Any]] = []
    wc_words = C.wordcloud_words(ctx.sentiment.get("keywords") or [])
    if wc_words:
        title = "全网口碑热词词云"
        out.append({"chart_id": ctx.new_id("ch"), "type": "wordcloud", "title": title,
                    "sections": _SENT_SECTIONS, "words": wc_words, "evidence_ids": []})
        if ctx.mode == "expert":
            for g in ctx.sentiment.get("by_spot") or []:
                # 出图门读 review_sample（doc_kind==review 的条数），不是 sample：
                # 后者把攻略/票务/航班页一起算进来，用它等于绕过语料分流，
                # 拿 5 条票务 FAQ 也能凑出一张 3 词空壳云。
                if int(g.get("review_sample") or 0) < MIN_SPOT_SENT_SAMPLE:
                    continue
                gw = C.wordcloud_words(g.get("keywords") or [])
                if not gw:
                    continue
                t = f"「{g.get('spot_name') or g.get('spot_id')}」口碑词云"
                out.append({"chart_id": ctx.new_id("ch"), "type": "wordcloud", "title": t,
                            "sections": _SENT_SECTIONS, "words": gw, "evidence_ids": []})
    return out


@_builder("radar", ("structured.access_matrix",))
def _chart_access_radar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """可达性分项拆解雷达（accessibility 章）：交通方式为维度、目的地为序列。

    数据源 structured.access_matrix 经 SC.score_accessibility 确定性算分（方式内相对分）。
    维度取各目的地**共有**方式：雷达每序列必须等长，缺维度补 0 会把「未知」画成「0 分」。
    不足 3 维不出图（两轴雷达画出来是折线，三方式才是常态：高铁/飞机/自驾）。
    """
    if "radar" not in ctx.allowed or not ctx.sections_exist("accessibility"):
        return []
    rows = ctx.own((ctx.analysis.get("structured") or {}).get("access_matrix") or [])
    scored = SC.score_accessibility(rows)
    if not scored:
        if rows:   # 有矩阵却算不出：缺耗时/费用数值，属算分输入缺口（如实标注，不静默）
            ctx.note_gap("accessibility", reason="可达性矩阵未给出「耗时/费用」数值")
        return []
    dims = [m for m in scored[0]["modes"] if all(m in r["modes"] for r in scored)]
    if len(dims) < 3:
        ctx.note_gap("accessibility",
                     reason=f"各目的地可比的交通方式不足 3 种（当前 {len(dims)} 种）")
        return []
    sections = ("accessibility",)
    title = f"可达性分项{'对比' if len(scored) >= 2 else '拆解'}{_ALGO_TAG}"
    series = [{"name": r["destination"], "values": [r["modes"][d] for d in dims]}
              for r in scored[:4]]
    note = (f"分项分 = 耗时×{SC.WEIGHT_DURATION} + 费用×{SC.WEIGHT_COST}"
            f"（方式内相对分，最优=100）；LLM 不参与打分")
    return [{"chart_id": ctx.new_id("ch"), "type": "radar", "title": title,
             "sections": sections, "option": C.feature_radar(title, dims, series, note),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("cost_bar", ("structured.amenity_checklist",))
def _chart_amenity_bar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """配套覆盖度柱（amenities 章）：逐配套项按覆盖枚举映射 0/50/100。

    值走 SCORE_FORMULAS["amenity"]（full/partial/none → 1.0/0.5/0.0），与配套章算分
    同一张表——图上每根柱都是可复核的枚举映射，不是估的。
    """
    if "cost_bar" not in ctx.allowed or not ctx.sections_exist("amenities"):
        return []
    ratio = SC.SCORE_FORMULAS["amenity"]
    multi = len(ctx.destinations) >= 2
    labels: List[str] = []
    values: List[float] = []
    for grp in ctx.own((ctx.analysis.get("structured") or {}).get("amenity_checklist") or []):
        dest = str(grp.get("destination") or "").strip()
        for it in (grp.get("items") or []):
            name = str(it.get("item") or "").strip()
            if not name:
                continue
            cov = str(it.get("coverage") or "partial").strip().lower()
            labels.append(_dest_prefixed(dest, name, multi))
            values.append(ratio.get(cov, ratio["partial"]) * 100)
    if not values:
        return []
    sections = ("amenities",)
    title = f"配套覆盖度{'对比' if multi else ''}{_ALGO_TAG}"
    note = "覆盖分 = " + " / ".join(f"{k} {v * 100:.0f}" for k, v in ratio.items())
    return [{"chart_id": ctx.new_id("ch"), "type": "cost_bar", "title": title,
             "sections": sections,
             "option": C.pricing_bar(title, labels, values, y_name="覆盖度（满分 100）", note=note),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("season_heat", ("structured.risk_profile",))
def _chart_risk_heat(ctx: ChartContext) -> List[Dict[str, Any]]:
    """风险维度热力网格（safety 章）：y=目的地、x=风险维度、值=风险等级映射分。

    分档映射表与安全章算分同一张（SCORE_FORMULAS["risk"]：low=20/medium=50/high=80），
    注释文案由表生成——改表即改图，不存在第二处口径。维度取各目的地**共有**项：
    热力网格每行必须等长，缺格补 0 会把「未评估」画成「无风险」。不足 2 维不出图。
    """
    if "season_heat" not in ctx.allowed or not ctx.sections_exist("safety"):
        return []
    rows = ctx.own((ctx.analysis.get("structured") or {}).get("risk_profile") or [])
    levels = SC.SCORE_FORMULAS["risk"]
    order: List[str] = []
    per_dest: List[Tuple[str, Dict[str, float]]] = []
    for grp in rows:
        dest = str(grp.get("destination") or "").strip()
        lv: Dict[str, float] = {}
        for it in (grp.get("items") or []):
            dim = str(it.get("dimension") or "").strip()
            if not dim:
                continue
            lv[dim] = levels.get(str(it.get("level") or "").lower(), levels["medium"])
            if dim not in order:
                order.append(dim)
        if dest and lv:
            per_dest.append((dest, lv))
    dims = [d for d in order if all(d in lv for _, lv in per_dest)]
    if len(dims) < 2:
        if per_dest:   # 有风险行却凑不出 2 个共有维度：网格每行必须等长，如实标注
            ctx.note_gap("safety",
                         reason=f"各目的地的共有风险维度不足 2 个（当前 {len(dims)} 个）")
        return []
    sections = ("safety",)
    title = f"风险维度热力网格{_ALGO_TAG}"
    return [{"chart_id": ctx.new_id("ch"), "type": "season_heat", "title": title,
             "sections": sections,
             "option": C.season_heat(title, dims, [d for d, _ in per_dest],
                                     [[lv[d] for d in dims] for _, lv in per_dest],
                                     "风险分：" + " / ".join(f"{k}={int(v)}"
                                                            for k, v in levels.items())),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("cost_bar", ("livelihood_cost",))
def _chart_livelihood_bar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """生活成本分项柱（livelihood 章）：数据源 analysis.livelihood_cost（逐目的地分项）。"""
    if "cost_bar" not in ctx.allowed or not ctx.sections_exist("livelihood"):
        return []
    multi = len(ctx.destinations) >= 2
    unit = ""
    labels: List[str] = []
    values: List[float] = []
    groups = ctx.own(ctx.analysis.get("livelihood_cost") or [])
    for grp in groups:
        dest = str(grp.get("destination") or "").strip()
        for it in (grp.get("items") or []):
            cat = str(it.get("category") or "").strip()
            amt = it.get("amount")
            if not cat or not isinstance(amt, (int, float)) or isinstance(amt, bool):
                continue
            unit = unit or str(it.get("unit") or "元/月").strip()
            labels.append(_dest_prefixed(dest, cat, multi))
            values.append(float(amt))
    if not values:
        if any((g.get("items") for g in groups)):   # 有分项却全无金额：算分输入缺口
            ctx.note_gap("livelihood", reason="生活成本分项未给出金额")
        return []
    sections = ("livelihood",)
    title = f"生活成本分项{'对比' if multi else ''}{_ALGO_TAG}"
    return [{"chart_id": ctx.new_id("ch"), "type": "cost_bar", "title": title,
             "sections": sections,
             "option": C.pricing_bar(title, labels, values, y_name=unit or "元/月"),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("growth_bar", ("consensus_split",))
def _chart_consensus_bar(ctx: ChartContext) -> List[Dict[str, Any]]:
    """共识 vs 反共识对照条（contrarian 章）：数据源 analysis.consensus_split。

    只画**有占比**的一侧（share 缺失不补 0——「未给出占比」与「占比 0%」不是一回事）；
    两侧都无占比才不出图。
    """
    if "growth_bar" not in ctx.allowed or not ctx.sections_exist("contrarian"):
        return []
    split = ctx.analysis.get("consensus_split") or {}
    labels: List[str] = []
    values: List[float] = []
    for key, default_label in (("orthodox", "主流共识"), ("contrarian", "反共识判断")):
        side = split.get(key)
        if not isinstance(side, dict):
            continue
        share = side.get("share")
        if not isinstance(share, (int, float)) or isinstance(share, bool):
            continue
        labels.append(str(side.get("label") or default_label).strip()[:20])
        values.append(float(share))
    if not values:
        return []
    sections = ("contrarian",)
    title = f"共识 vs 反共识占比{_ALGO_TAG}"
    return [{"chart_id": ctx.new_id("ch"), "type": "growth_bar", "title": title,
             "sections": sections,
             "option": C.growth_bar(title, labels, values, y_name="占比（%）"),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("growth_bar", ("action_priorities",))
def _chart_action_priorities(ctx: ChartContext) -> List[Dict[str, Any]]:
    """行动优先级分档柱（conclusion 章）：按 tier 计数（高/中/低）。

    tier 收敛（未知档按 mid）在清洗层完成，这里只计数——「有几条高优先级行动」
    本身就是结论章要给决策者的信息。
    """
    if "growth_bar" not in ctx.allowed or not ctx.sections_exist("conclusion"):
        return []
    tiers = (("high", "高优先级"), ("mid", "中优先级"), ("low", "低优先级"))
    counts = {k: 0 for k, _ in tiers}
    for it in ((ctx.analysis.get("action_priorities") or {}).get("items") or []):
        if not isinstance(it, dict):
            continue
        tier = str(it.get("tier") or "").strip().lower()
        if tier in counts:
            counts[tier] += 1
    if not sum(counts.values()):
        return []
    sections = ("conclusion",)
    title = f"行动优先级分档{_ALGO_TAG}"
    return [{"chart_id": ctx.new_id("ch"), "type": "growth_bar", "title": title,
             "sections": sections,
             "option": C.growth_bar(title, [label for _, label in tiers],
                                    [float(counts[k]) for k, _ in tiers], y_name="条"),
             "evidence_ids": ctx.section_evidence(*sections)}]


@_builder("growth_bar", ("@claims",))
def _chart_evidence_strength(ctx: ChartContext) -> List[Dict[str, Any]]:
    """证据强度计数（risk 章）：结论总数/有据/无据 + 引用证据/独立信源。

    数据源是 claims/evidences（scoring.count_evidence_strength，确定性计数）。计数类
    无「输入不足」语义，0 条也是可展示的事实；但**无结论**时不画一排 0（无对象可数）。
    """
    if "growth_bar" not in ctx.allowed or not ctx.sections_exist("risk"):
        return []
    st = SC.count_evidence_strength(ctx.claims, ctx.evidences)
    if not st["claims_total"]:
        return []
    sections = ("risk",)
    title = f"证据强度计数{_ALGO_TAG}"
    labels = ["结论总数", "有据结论", "无据存疑", "引用证据", "独立信源"]
    values = [st["claims_total"], st["supported"], st["unsupported"],
              st["evidence_total"], st["domains"]]
    return [{"chart_id": ctx.new_id("ch"), "type": "growth_bar", "title": title,
             "sections": sections,
             "option": C.growth_bar(title, labels, [float(v) for v in values],
                                    y_name="条 / 个"),
             "evidence_ids": ctx.section_evidence(*sections)}]


# 注册表顺序 = 产出顺序：guide 既有图（前 10 个 builder）必须保持原序，
# test_chart_contract.py 的 T-05 基线逐项比对产出序列，挪动即红。
CHART_BUILDERS: Tuple[Callable[[ChartContext], List[Dict[str, Any]]], ...] = (
    _chart_radar, _chart_cost_bar, _chart_safety_score, _chart_cost_compose,
    _chart_season_heat, _chart_donut, _chart_trend,
    _chart_sentiment_donut, _chart_platform_bar, _chart_wordcloud,
    # assessment 批次② 新增 7 张
    _chart_access_radar, _chart_amenity_bar, _chart_risk_heat,
    _chart_livelihood_bar, _chart_consensus_bar, _chart_action_priorities,
    _chart_evidence_strength,
)


def _chart_context(destinations, analysis, sentiment, claims=None,
                   research_type: str = DEFAULT_RESEARCH_TYPE, mode: str = "deep",
                   evidences=None) -> ChartContext:
    """装配 ChartContext：闭包（own/eids/new_id）在此收拢，供 _build_charts 与单测共用。"""
    ev_by_field: Dict[str, List[str]] = {}
    for c in (claims or []):
        ev_by_field.setdefault(c.get("field", ""), []).extend(c.get("evidence_ids", []))

    def eids(*fields: str) -> List[str]:
        out: List[str] = []
        for f in fields:
            out.extend(ev_by_field.get(f, []))
        seen = set()
        return [x for x in out if not (x in seen or seen.add(x))][:6]

    def own(rows_iter: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """消费侧兜底：只取属于本次目的地的行（装配前已过滤，这里防新调用点漏过收口）。"""
        return [r for r in (rows_iter or []) if _row_dest_ok(_row_name(r), destinations)]

    dest_list = list(destinations or [])
    return ChartContext(
        destinations=dest_list, analysis=analysis or {}, sentiment=sentiment or {},
        claims=list(claims or []), evidences=list(evidences or []),
        spec=RT.type_spec(research_type),
        allowed=frozenset(RT.charts_for(research_type, len(dest_list))),
        mode=mode, research_type=research_type, own=own, eids=eids, new_id=_sid,
    )


def _build_charts_and_gaps(destinations, analysis, sentiment, claims=None,
                           research_type: str = DEFAULT_RESEARCH_TYPE,
                           mode: str = "deep", evidences=None,
                           ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """生产入口：出图之外，回传 builder 记下的「有材料但算不出」缺口台账。

    缺口只在**同一次** builder 运行里产生（判据与产出同处，见 ChartContext.note_gap），
    装配层据此在章节上如实标注；不重跑 builder、不反推原因。
    """
    ctx = _chart_context(destinations, analysis, sentiment, claims,
                         research_type, mode, evidences)
    specs: List[Dict[str, Any]] = []
    for build in CHART_BUILDERS:
        specs.extend(build(ctx) or [])
    return specs, ctx.gaps


def _build_charts(destinations, analysis, sentiment, claims=None,
                  research_type: str = DEFAULT_RESEARCH_TYPE,
                  mode: str = "deep", evidences=None) -> List[Dict[str, Any]]:
    """按 spec["charts"] 出图：类型决定图集，某图无真实数据则整图跳过（不占位造假）。

    实现 = 遍历 CHART_BUILDERS（每类图一个函数，自带 sections 归属与降级），本函数
    只做上下文装配与结果汇总——新增图不动这里。签名与扁平返回契约保持不变
    （test_charts_options 有 6 处位置调用、test_chart_contract T-16 守护）。
    """
    return _build_charts_and_gaps(destinations, analysis, sentiment, claims,
                                  research_type, mode, evidences)[0]


# ── 图表归属谓词（批次⓪ 契约）：章节装配与舆情面板的唯一取图入口 ──────
def _charts_for_section(sid: str, charts: List[Dict[str, Any]],
                        chart_types: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
    """按归属取图：spec 声明了 sections 的图**只按归属匹配**（sections 是权威，
    此时 chart_types 对它失效）；未声明（None）的图维持旧「按类型广播」行为，
    保证 guide 现有图（全部未声明）产出零变化。

    旧实现按 c["type"] 无差别广播，同类型多图时每章拿到全部张数（串章根因③）；
    舆情面板旧实现按类型取 c[0] 首张，取到哪张随产出顺序漂移——两处统一到本谓词后，
    图落在哪章由图自带的 sections 声明决定，与产出顺序、章节类型表皆解耦。
    """
    return [c for c in charts
            if sid in (c.get("sections") or ())
            or (c.get("sections") is None and c["type"] in chart_types)]


# ── 数据空间：把数据密集章节的数据汇总成可导出 CSV 的表格 ────────
def _build_data_grid(section_id: str, analysis: Dict[str, Any],
                     evidences: List[Evidence]) -> Optional[Dict[str, Any]]:
    """对数据密集章（section 集由 spec["data_grid_sections"] 决定）生成数据网格。"""
    ev_by_id = {e.evidence_id: e for e in evidences}

    def _src(eids):
        for eid in (eids or []):
            e = ev_by_id.get(eid)
            if e:
                return domain_of(e.source_url), e.source_url, eid
        return "", "", ""

    def _row(name: str, value: Any, metric: str, eids=None, fallback_src: str = ""):
        src, url, eid = _src(eids)
        return {"name": name, "value": value, "metric": metric,
                "source": src or fallback_src, "source_url": url, "evidence_id": eid}

    columns = ["数据名", "值", "指标", "来源", "来源网址"]
    rows: List[Dict[str, Any]] = []
    structured = analysis.get("structured") or {}

    if section_id == "spots":             # guide：景点分布调研（冻结实体表）
        for sr in structured.get("spot_ranking", []):
            dest = str(sr.get("destination", ""))
            for it in sr.get("items", []):
                sig = it.get("signals") or {}
                score = it.get("score")
                val = (f"评分 {score}" if score is not None else "评分 —")
                val += f"（声量 {sig.get('voice', 0)}·口碑 {sig.get('sentiment', 0)}·性价比 {sig.get('value', 0)}）"
                rows.append(_row(f"{dest} · {it.get('rank', '')}. {it.get('name', '')}", val,
                                 "景点综合评分", it.get("evidence_ids")))
    elif section_id == "food":            # guide：美食 Top 榜
        for fr in structured.get("food_ranking", []):
            dest = str(fr.get("destination", ""))
            for it in fr.get("items", []):
                rows.append(_row(f"{dest} · {it.get('name', '')}",
                                 it.get("price_range") or "人均未公开", "美食榜",
                                 it.get("evidence_ids")))
    elif section_id == "shops":           # guide：美食商铺调研（人均=参考价）
        for sl in structured.get("shop_list", []):
            dest = str(sl.get("destination", ""))
            for it in sl.get("items", []):
                price = it.get("price_per_person")
                val = f"{price}元/人（参考价）" if price is not None else "人均未公开"
                rows.append(_row(f"{dest} · {it.get('name', '')}", val,
                                 f"商铺·{it.get('food', '')}".strip("·"),
                                 it.get("evidence_ids")))
    elif section_id == "budget":            # guide：预算拆解
        for cb in structured.get("cost_breakdown", []):
            dest = str(cb.get("destination", ""))
            for it in cb.get("items", []):
                amount = it.get("amount")
                val = f"{amount}{it.get('unit') or '元/人'}" if amount is not None else "未公开"
                if isinstance(it.get("share"), (int, float)):
                    val += f"（占比 {it['share']}%）"
                rows.append(_row(f"{dest} · {it.get('category', '')}", val, "花费项",
                                 it.get("evidence_ids")))
    elif section_id == "route":           # guide：逐日路线
        for rp in structured.get("route_plan", []):
            dest = str(rp.get("destination", ""))
            for d in rp.get("days", []):
                day = d.get("day", "")
                for sp in d.get("spots", []):
                    plan = f"{sp.get('transport', '')} / {sp.get('duration', '')}".strip(" /")
                    rows.append(_row(f"{dest} · D{day} {sp.get('name', '')}", plan or "—",
                                     "行程安排", sp.get("evidence_ids")))
    elif RT.perspective_spec(section_id).get("checklist_key"):
        # 视角章逐景点核查表（一格一行，可溯源）。承载键与「指标」列文案都取自注册表：
        # 原先写死 `section_id == "persp_family"` + `family_checklist` + 「亲子核查项」，
        # 换群体时即便配了核查表数据也静默不出网格（评审 P0 的三处硬编码之一）。
        _pspec = RT.perspective_spec(section_id)
        _metric = _pspec.get("checklist_metric") or "视角核查项"
        for fc in structured.get(_pspec["checklist_key"], []):
            dest = str(fc.get("destination", ""))
            for it in fc.get("items", []):
                for c in it.get("cells", []):
                    val = str(c.get("text") or "待核验")
                    rows.append(_row(f"{dest} · {it.get('spot_name', '')} · {c.get('column', '')}",
                                     val, _metric if c.get("verified") else "待核验占位",
                                     c.get("evidence_ids")))
    elif section_id == "value":           # assessment：性价比与成本
        for c in (analysis.get("cost") or []):
            dest = str(c.get("destination", ""))
            if isinstance(c.get("monthly_rent"), (int, float)):
                rows.append(_row(f"{dest} 月租", f"{c['monthly_rent']}元/月", "居住成本",
                                 c.get("evidence_ids")))
            if isinstance(c.get("monthly_living"), (int, float)):
                rows.append(_row(f"{dest} 月均生活费", f"{c['monthly_living']}元/月", "生活成本",
                                 c.get("evidence_ids")))
    elif section_id == "livelihood":      # assessment：生活成本分项
        for lc in (analysis.get("livelihood_cost") or []):
            dest = str(lc.get("destination", ""))
            for it in lc.get("items", []):
                amount = it.get("amount")
                val = f"{amount}{it.get('unit') or '元/月'}" if amount is not None else "未公开"
                rows.append(_row(f"{dest} · {it.get('category', '')}", val, "生活成本项",
                                 it.get("evidence_ids")))
    elif section_id == "accessibility":   # assessment：可达性
        for am in structured.get("access_matrix", []):
            dest = str(am.get("destination", ""))
            for rt in am.get("routes", []):
                plan = f"{rt.get('duration', '')} / {rt.get('cost', '')}".strip(" /")
                rows.append(_row(f"{dest} · {rt.get('mode', '')}", plan or "—",
                                 "可达性", rt.get("evidence_ids")))
    elif section_id == "trend":
        tr = analysis.get("trends") or {}
        tx = tr.get("x") or []
        for s in (tr.get("series") or []):
            vals = s.get("values") or []
            for i, x in enumerate(tx):
                if i < len(vals):
                    rows.append(_row(f"{s.get('name', '')} · {x}", vals[i],
                                     tr.get("unit", "趋势值"), None, "分析师推断"))

    if len(rows) < 2:
        return None
    return {"columns": columns, "rows": rows}
