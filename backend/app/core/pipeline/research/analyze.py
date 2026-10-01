"""结构化分析与清洗（M3 自 engine.py 原文迁出 · 行为零变化）。

_analyze/_analyze_structured + 10 个 typed sanitizer + 目的地行收口 + claims 兜底
+ 结构诊断 _diag/_diag_of（writer 共享，engine re-export）。
依赖：runtime + collect._evidence_digest + schemas/models/llm/RT + _util；不反向依赖 engine。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core import llm, research_types as RT
from app.core.models import Evidence, make_claim
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core.schemas import _filter_eids, coerce_structured

from . import runtime
from ._util import _clamp_int, _num_or_none, _row_dest_ok, _row_name, _sid
from .collect import _evidence_digest, digest_limit_for


# 分析产出各键的 JSON 片段：提示词按 spec["analysis_keys"] 动态拼装，
# 新增/替换分析对象只需改注册表 + 在此加一条片段，分析与图表链路无需改代码。
_ANALYSIS_KEY_SCHEMA: Dict[str, str] = {
    "comparison": '"comparison":{"dimensions":["对比维度,5-6个"],"scores":[{"destination":"目的地","values":[0-100整数,与dimensions等长]}]}',
    "livability": '"livability":{"dimensions":["评估维度,5-6个"],"scores":[{"destination":"目的地","values":[0-100整数,与dimensions等长]}]}',
    "budget": '"budget":[{"destination":"目的地","per_capita_3d":数字或null,"tier":"经济|舒适|品质|高端","note":"花费结构与省钱空间一句话","evidence_ids":["真实id"]}]',
    "cost": '"cost":[{"destination":"目的地","monthly_rent":数字或null,"monthly_living":数字或null,"note":"居住成本结构一句话","evidence_ids":["真实id"]}]',
    "safety_index": '"safety_index":[{"destination":"目的地","safety_score":0-100整数,"note":"治安/灾害/医疗风险研判一句话","evidence_ids":["真实id"]}]',
    "livelihood_cost": '"livelihood_cost":[{"destination":"目的地","items":[{"category":"房租|餐饮|交通|日常消费|其他","amount":月支出数字或null,"unit":"元/月","evidence_ids":["真实id"]}]}]',
    "action_priorities": '"action_priorities":{"items":[{"action":"一句话行动建议","tier":"high|mid|low","evidence_ids":["真实id"]}]}',
    "consensus_split": '"consensus_split":{"orthodox":{"label":"主流共识","summary":"一句话概括主流观点","share":占比整数或null,"evidence_ids":["真实id"]},"contrarian":{"label":"反共识判断","summary":"一句话概括与主流相反但有证据的判断","share":占比整数或null,"evidence_ids":["真实id"]}}',
    "season": '"season":{"best_months":["最佳月份"],"avoid":["需避开的时段"],"matrix":[{"destination":"目的地","values":[12个0-100整数,依次对应1月到12月的出行适宜度]}]}',
    "share_estimate": '"share_estimate":[{"name":"目的地","value":百分比整数}]',
    "trends": '"trends":{"x":["时间点,如2022/2023/2024等"],"unit":"指标单位,如 接待游客(万人次)/热度指数/房价(元/㎡)","series":[{"name":"目的地","values":[数字,与x等长]}],"note":"趋势研判一句话"}',
    "contradictions": '"contradictions":[{"claim_text":"来源间存在分歧的陈述","evidence_ids":["真实id"],"note":"为什么存疑/尚未证实"}]}',
}


# spots 实体阶段产出的 structured 键：不进 LLM 结构化提示——榜单分数由
# scoring 规则算出（可复现），实体表由 spots 阶段冻结后覆盖回写；
# 路线卡（spot_routes）M2 起改为百度 direction 真实数据批量落库（缺 AK/失败 → 空表占位，
# 绝不让 LLM 编造换乘细节）。
_ENTITY_STAGE_KEYS = frozenset({"spot_ranking", "spot_routes"})


# 结构化键 → JSON 片段（提示词按 spec["structured_keys"] 拼装，与 schemas.coerce_structured 同键）
_STRUCTURED_SCHEMA: Dict[str, str] = {
    "spot_ranking": '"spot_ranking":[{"destination":"目的地","items":[{"name":"景点名","area":"所在区域","signals":{"mentions":提及次数整数,"positive_ratio":正面口碑占比0-1,"value_score":性价比0-1},"score":综合分,"rank":排名整数,"ticket":"门票与预约","stay_minutes":建议停留分钟整数,"off_peak":"避峰时段","reason":"一句话入选理由","evidence_ids":["真实id"]}]}]',
    "food_ranking": '"food_ranking":[{"destination":"目的地","items":[{"name":"美食/菜品名","category":"品类","reason":"推荐理由","price_range":"人均价格区间","evidence_ids":["真实id"]}]}]',
    "spot_routes": '"spot_routes":[{"destination":"目的地","items":[{"spot_id":"实体表给定的spot_id","spot_name":"实体表给定的景点名","routes":[{"mode":"地铁|公交|打车|自驾","duration":"耗时","cost":"费用","transfer":"换乘站点/路线名","note":"实操要点","evidence_ids":["真实id"]}]}]}]',
    "shop_list": '"shop_list":[{"destination":"目的地","items":[{"food":"对应的榜上美食名","name":"商铺名","area":"所在区域","price_per_person":人均价数字或null,"queue_note":"排队情况","evidence_ids":["真实id"]}]}]',
    "route_plan": '"route_plan":[{"destination":"目的地","days":[{"day":第几天整数,"spots":[{"name":"景点/活动","transport":"交通方式","duration":"建议停留","tip":"实操提示","evidence_ids":["真实id"]}]}]}]',
    "stay_options": '"stay_options":[{"destination":"目的地","areas":[{"area":"住宿区域","price_range":"价格区间","price_min":区间最低价整数或null,"price_max":区间最高价整数或null,"for_whom":"适合人群","pros":["优点"],"cons":["缺点"],"evidence_ids":["真实id"]}]}]',
    "cost_breakdown": '"cost_breakdown":[{"destination":"目的地","items":[{"category":"交通|住宿|餐饮|门票|购物|其他","amount":数字或null,"unit":"元/人","share":占比百分数或null,"note":"说明","evidence_ids":["真实id"]}]}]',
    "access_matrix": '"access_matrix":[{"destination":"目的地","routes":[{"mode":"飞机|高铁|自驾|大巴|轮渡","duration":"耗时","cost":"费用区间","frequency":"班次频次","note":"换乘/购票要点","duration_minutes":耗时分钟数字,"cost_yuan":单程费用元数字,"evidence_ids":["真实id"]}]}]',
    "amenity_checklist": '"amenity_checklist":[{"destination":"目的地","items":[{"category":"医疗|教育|商业|政务|网络","item":"具体配套","coverage":"full|partial|none","note":"说明","evidence_ids":["真实id"]}]}]',
    "risk_profile": '"risk_profile":[{"destination":"目的地","items":[{"dimension":"治安|自然灾害|医疗应急|其他","level":"low|medium|high","note":"说明","evidence_ids":["真实id"]}]}]',
}


# 写稿诊断：记录「这一章是怎么写出来的」，供写后结构补齐与 structure_status 归类判定。
# 该键不在 _section 的字段白名单内，因此不会进 reports.data（有单测钉住）。
DIAG_KEY = "_diag"


def _enforce_dest_rows(analysis: Dict[str, Any], destinations: List[str]) -> Dict[str, Any]:
    """按注册表剔除不属于本次目的地的行：analysis ∪ structured 的行主键 ⊆ destinations。

    为什么必须存在：这些键由 LLM 自由产出，提示里给了目的地却管不住它顺手加对照城市
    （真机单目的地大理，雷达里冒出丽江/香格里拉）。只剔行、不剔键：整组被剔空时
    该键仍保留为空列表，让下游按「无数据」降级而不是 KeyError。
    destinations 为空时不过滤（没有可信白名单可比，宁可不动）。
    """
    if not destinations or not isinstance(analysis, dict):
        return analysis
    for path, _field in RT.DEST_KEYED_ROWS:
        segs = path.split(".")
        holder: Any = analysis
        for seg in segs[:-1]:
            holder = holder.get(seg) if isinstance(holder, dict) else None
        leaf = segs[-1]
        if not isinstance(holder, dict):
            continue
        rows = holder.get(leaf)
        if not isinstance(rows, list):
            continue
        holder[leaf] = [r for r in rows
                        if isinstance(r, dict) and _row_dest_ok(_row_name(r), destinations)]
    return analysis


def _sanitize_radar(raw, spec: Dict[str, Any]) -> Dict[str, Any]:
    """雷达对比：维度与各目的地分值必须等长；维度非法时回落注册表维度。"""
    data = raw if isinstance(raw, dict) else {}
    raw_dims = data.get("dimensions")
    dims = [str(d).strip() for d in raw_dims if str(d).strip()] if isinstance(raw_dims, list) else []
    if len(dims) < 3:
        dims = list(spec["radar_dims"])
    scores: List[Dict[str, Any]] = []
    for s in (data.get("scores") or []):
        if not isinstance(s, dict):
            continue
        name = _row_name(s)
        vals = s.get("values")
        vals = [_clamp_int(v) for v in vals] if isinstance(vals, list) else []
        if not name or len(vals) != len(dims) or any(v is None for v in vals):
            continue
        scores.append({"destination": name, "values": vals})
    return {"dimensions": dims, "scores": scores[:4]}


def _sanitize_evidence_rows(raw, valid_ids: set, fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """数据型行（花费/成本/安全分）：`fields` 的数值字段保留原名，**无有效证据则丢行**。"""
    out: List[Dict[str, Any]] = []
    for it in (raw if isinstance(raw, list) else []):
        if not isinstance(it, dict):
            continue
        name = _row_name(it)
        eids = _filter_eids(it.get("evidence_ids"), valid_ids)
        if not name or not eids:
            continue
        row: Dict[str, Any] = {"destination": name}
        for f in fields:
            row[f] = _clamp_int(it.get(f)) if f.endswith("_score") else _num_or_none(it.get(f))
        if all(row[f] is None for f in fields):
            continue
        row["note"] = str(it.get("note") or "")[:200]
        row["evidence_ids"] = eids
        out.append(row)
    return out[:6]


def _sanitize_season(raw) -> Dict[str, Any]:
    """季节矩阵：逐月适宜度必须 12 个整数（1-12 月），否则丢该行（不猜月份）。"""
    data = raw if isinstance(raw, dict) else {}
    matrix: List[Dict[str, Any]] = []
    for m in (data.get("matrix") or []):
        if not isinstance(m, dict):
            continue
        name = _row_name(m)
        vals = m.get("values")
        vals = [_clamp_int(v) for v in vals] if isinstance(vals, list) else []
        if not name or len(vals) != 12 or any(v is None for v in vals):
            continue
        matrix.append({"destination": name, "values": vals})

    def _months(key: str) -> List[str]:
        return [str(x)[:20] for x in (data.get(key) or []) if str(x).strip()][:8]

    return {"best_months": _months("best_months"), "avoid": _months("avoid"), "matrix": matrix[:6]}


def _sanitize_trends(raw) -> Dict[str, Any]:
    """趋势序列：x 轴与各序列必须等长且为数值，否则整块留空（不编造）。"""
    tr = raw if isinstance(raw, dict) else {}
    tx = tr.get("x") if isinstance(tr.get("x"), list) else []
    series: List[Dict[str, Any]] = []
    for s in (tr.get("series") or []):
        if not isinstance(s, dict):
            continue
        name = _row_name(s)
        vals = s.get("values")
        if not name or not tx or not isinstance(vals, list) or len(vals) != len(tx):
            continue
        nums = [_num_or_none(v) for v in vals]
        if any(n is None for n in nums):
            continue
        series.append({"name": name, "values": nums})
    if not tx or not series:
        return {}
    return {"x": [str(x)[:20] for x in tx], "unit": str(tr.get("unit") or "")[:40],
            "series": series[:5], "note": str(tr.get("note") or "")[:200]}


def _sanitize_contradictions(raw, valid_ids: set) -> List[Dict[str, Any]]:
    """矛盾检测容错：非 list 置空，防单条坏输出拖垮整章。"""
    out: List[Dict[str, Any]] = []
    for ct in (raw if isinstance(raw, list) else [])[:8]:
        if not isinstance(ct, dict) or not ct.get("claim_text"):
            continue
        out.append({
            "claim_text": str(ct["claim_text"])[:200],
            "evidence_ids": _filter_eids(ct.get("evidence_ids"), valid_ids),
            "note": str(ct.get("note", ""))[:200],
        })
    return out


def _analyze(query, destinations, focus, evidences: List[Evidence], members: List[str],
             research_type: str = DEFAULT_RESEARCH_TYPE,
             max_tokens_param: int = 8000, review_feedback: str = "") -> Dict[str, Any]:
    spec = RT.type_spec(research_type)
    # 分析对象随目的地数自适应：单目的地剔除只在多目的地才有意义的键（如占比分布）
    keys = [k for k in RT.analysis_keys_for(research_type, len(destinations))
            if k in _ANALYSIS_KEY_SCHEMA]
    schema = ",\n".join(_ANALYSIS_KEY_SCHEMA[k] for k in keys)
    allowed_fields = set(RT.claim_fields_for(research_type))
    cb = spec.get("cost_bar") or {}
    cost_line = (f"成本/花费数组放在 {cb['key']} 键，金额字段用 {cb['value_field']}"
                 f"（单位 {cb['unit']}）。" if cb else "")
    share_line = "share_estimate 各项之和不得超过 100；" if "share_estimate" in keys else ""
    digest = _evidence_digest(evidences, limit=digest_limit_for(evidences, 28))
    ev_ids = [e.evidence_id for e in evidences]
    valid_ids = set(ev_ids)
    # v2.1 客观性：独立信源以「信源组」计（同质转载归并为一组，杜绝冒充多源）
    _sg_of = {e.evidence_id: (e.source_group or e.evidence_id) for e in evidences}
    authors = [m for m in members if m.startswith(("L1", "L2"))] or ["L2-001"]
    # 返工时把质检官的具体意见注入提示，让重分析真正针对短板调优（而非重抽一遍）
    rework_directive = ""
    if review_feedback:
        rework_directive = (
            "\n\n【质检官返工要求 —— 必须逐条针对性改进】\n" + review_feedback +
            "\n请据此：①对低置信/缺交叉验证的结论补充第二个独立信源后再下判断，"
            "尽量提升 high 置信论点占比；②补全被指缺失的维度，确保每个重点维度都有"
            "至少一条有证据支撑的结论；③让结论更精准、更有区分度。"
        )

    fallback: Dict[str, Any] = {
        "claims": _fallback_claims(destinations, ev_ids, _sg_of, authors),
        "trends": {},
        "contradictions": [],
    }
    for k in keys:
        if k in ("comparison", "livability"):
            fallback[k] = {"dimensions": list(spec["radar_dims"]),
                           "scores": [{"destination": d, "values": []} for d in destinations[:4]]}
        elif k == "season":
            fallback[k] = {"best_months": [], "avoid": [], "matrix": []}
        elif k in ("action_priorities", "consensus_split"):
            fallback[k] = {}  # 对象型产出：空对象即「无料」，图侧据此降级不出图
        else:
            fallback[k] = []
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是顶尖旅游研究机构（对标 Lonely Planet、马蜂窝研究院、文旅数据中心）的资深旅游调研分析师。"
                    f"本次调研类型是「{spec['label']}」（{spec['subtitle']}）。"
                    "基于给定证据（每条带 evidence_id），提炼结构化、有锋芒、敢下判断的调研洞察。"
                    "严格要求：每条结论的 evidence_ids 必须来自给定证据的真实 id；无证据支撑的结论不要输出；数字尽量带来源。"
                    f"claims 的 field 只能取：{'|'.join(RT.claim_fields_for(research_type))}。"
                    "输出 JSON：{"
                    '"claims":[{"text":"一句话锐利结论（要有判断不要套话）","field":"见上述枚举","evidence_ids":["真实id"],"author":"专家id","claim_type":"fact|opinion|mixed"}],'
                    + schema + ","
                    "claim_type 定义与客观性铁律：fact=证据可直接支撑的客观事实；opinion=分析判断（用词体现观点）；mixed=事实与推断混合。"
                    "每条 claim 必须明确 claim_type；不得把单一信源或存在矛盾的资讯写成定论；"
                    "当不同证据对同一事实说法不一致时，如实输出到 contradictions 而非掩盖。"
                    f"{RT.radar_title(research_type, len(destinations))}的维度请围绕本次类型的重点：{'、'.join(spec['radar_dims'])}。" + cost_line +
                    "trends 给出可比的时间序列（客流/热度/房价/成本等任一可由证据支撑的维度），无依据则留空对象 {}，不要编造。"
                    "所有数组/对象必须基于证据合理推断，无依据则留空数组或 null；每项数据型结论都要挂 evidence_ids。"
                    "【数据真实性铁律】所有评分/数值必须精确、可信、有区分度：严禁清一色用 5 或 10 的整数倍（如 80/85/90），"
                    "要给出精确到个位的真实评分（如 83、77、91、68），不同目的地、不同维度的分数要有真实差异，"
                    "体现你基于证据的细腻判断；"
                    f"{share_line}任何百分比不得超过 100。只输出 JSON。"
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}\n"
                    f"可用作者专家id：{authors}\n证据：\n{digest}{rework_directive}"
                )},
            ],
            max_tokens=max_tokens_param,
            temperature=0.4,
            model=runtime._model("core"),
            purpose="交叉验证产出论点与结构化对比数据",
        )
        if isinstance(data, dict) and data.get("claims"):
            claims = []
            for c in data["claims"]:
                if not isinstance(c, dict) or not c.get("text"):
                    continue
                eids = _filter_eids(c.get("evidence_ids"), valid_ids)
                # v2.1 独立信源 = 所属「信源组」去重计数（同质转载只算一组）
                indep = len({_sg_of.get(i, i) for i in eids}) if eids else 0
                author = c.get("author") if c.get("author") in members else authors[0]
                ct = c.get("claim_type", "mixed") if c.get("claim_type") in ("fact", "opinion", "mixed") else "mixed"
                fld = str(c.get("field") or "overview").strip()
                if fld not in allowed_fields:
                    fld = "overview"
                claims.append(make_claim(_sid("c"), c["text"], fld, eids, author, indep, ct).to_dict())
            if claims:
                result: Dict[str, Any] = {"claims": claims}
                for k in keys:
                    raw_k = data.get(k)
                    if k in ("comparison", "livability"):
                        result[k] = _sanitize_radar(raw_k, spec)
                    elif k in ("budget", "cost", "safety_index"):
                        fields = ("per_capita_3d",) if k == "budget" else (
                            ("safety_score",) if k == "safety_index" else ("monthly_rent", "monthly_living"))
                        result[k] = _sanitize_evidence_rows(raw_k, valid_ids, fields)
                        if k == "budget":  # 档位标签非数值，单独带上
                            tiers = {_row_name(x): str(x.get("tier") or "")[:20]
                                     for x in (raw_k if isinstance(raw_k, list) else [])
                                     if isinstance(x, dict)}
                            for row in result[k]:
                                row["tier"] = tiers.get(row["destination"], "")
                    elif k == "season":
                        result[k] = _sanitize_season(raw_k)
                    elif k == "share_estimate":
                        result[k] = _sanitize_share(raw_k or [])
                    elif k == "livelihood_cost":
                        result[k] = _sanitize_livelihood_cost(raw_k, valid_ids)
                    elif k == "action_priorities":
                        result[k] = _sanitize_action_priorities(raw_k, valid_ids)
                    elif k == "consensus_split":
                        result[k] = _sanitize_consensus_split(raw_k, valid_ids)
                    elif k == "trends":
                        result[k] = _sanitize_trends(raw_k)
                    elif k == "contradictions":
                        result[k] = _sanitize_contradictions(raw_k, valid_ids)
                    else:
                        result[k] = raw_k if isinstance(raw_k, (list, dict)) else []
                return {**fallback, **result}
    except Exception:
        pass
    return fallback


def _analyze_structured(query, destinations, focus, evidences: List[Evidence],
                        research_type: str = DEFAULT_RESEARCH_TYPE,
                        max_tokens_param: int = 8000,
                        entity_hint: str = "",
                        trunc_report: Optional[List[bool]] = None) -> Dict[str, Any]:
    """产出结构化目的地知识（严格 Schema + 引用强制）。

    对象集来自 spec["structured_keys"]，但剔除 _ENTITY_STAGE_KEYS（景点榜等由
    spots 实体阶段冻结后覆盖回写，不交 LLM 算分）。提示词片段同样按类型查表。
    entity_hint：已冻结的景点实体表（spot_id+名），供 shop_list 等下游挂接同一批实体。
    trunc_report（L2 可见降级）：调用方传入的单元素列表，本函数在**工作线程内**
    写入「本次结构化调用被截断且产物全空」判定——last_finish_reason 是 ContextVar，
    经 asyncio.to_thread 单向 copy，await 之后在父上下文里读恒为空，只能这样传回。
    """
    spec = RT.type_spec(research_type)
    keys = [k for k in spec["structured_keys"] if k not in _ENTITY_STAGE_KEYS]
    fragments = [_STRUCTURED_SCHEMA.get(k) for k in keys]
    if any(f is None for f in fragments):
        if trunc_report is not None:
            trunc_report.append(False)
        return {k: [] for k in spec["structured_keys"]}
    digest = _evidence_digest(evidences, limit=digest_limit_for(evidences, 24))
    valid_eids = {e.evidence_id for e in evidences}
    out: Dict[str, Any] = {k: [] for k in spec["structured_keys"]}
    entity_block = (f"\n已冻结景点实体表（spot_id 与景点名必须原样引用，禁止改名或新增景点）：\n{entity_hint}"
                    if entity_hint else "")
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是旅游知识结构化专家。基于给定证据（每条带 evidence_id），为每个目的地输出严格结构化的 JSON。"
                    "字段必须完整、格式一致。evidence_ids 必须来自给定证据真实 id（无则留空数组）；"
                    "每个叶子项都必须挂载支撑它的 evidence_ids，无证据的项不要输出。"
                    "【数值铁律】耗时/费用等数值字段（duration_minutes/cost_yuan）无法从证据确证时必须省略该键，"
                    "严禁估算或用「约」填充——缺失即未知，系统按缺失降级处理。输出 JSON：{"
                    + ",".join(fragments) + "}。只输出 JSON，不要解释。"
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}{entity_block}\n证据：\n{digest}"
                )},
            ],
            max_tokens=max_tokens_param,
            temperature=0.3,
            model=runtime._model("core"),
            purpose=f"结构化目的地知识（{'/'.join(keys)}）",
        )
        if isinstance(data, dict):
            coerced = coerce_structured(data, research_type, valid_eids)
            out.update({k: v for k, v in coerced.items() if k not in _ENTITY_STAGE_KEYS})
    except Exception:
        pass
    if trunc_report is not None:
        trunc_report.append(llm.last_finish_reason() == "length"
                            and all(not out.get(k) for k in keys))
    return out


def _sanitize_share(share: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """热度/客流份额估算防越界：剔除非法值，总和 >100 时按比例归一化。"""
    clean = [s for s in share
             if isinstance(s, dict) and isinstance(s.get("value"), (int, float)) and s["value"] > 0]
    total = sum(s["value"] for s in clean)
    if total > 100 and total > 0:
        for s in clean:
            s["value"] = round(s["value"] / total * 100, 1)
    return clean


def _sanitize_livelihood_cost(raw: Any, valid_ids: set) -> List[Dict[str, Any]]:
    """生活成本分项（livelihood 章图源）：逐目的地行，items 只留「类别非空 + 金额正数」项。

    与 cost_breakdown 同形但语义不同（居住成本 vs 旅行花费），故独立产出。
    金额容忍 ￥/¥/元/千分位等符号漂移（_num_or_none 同口径），但缺金额/非正数不计。
    行内无有效项则整行剔除；全空返回 []——降级契约：调用方据此不出图，不报错。
    """
    out: List[Dict[str, Any]] = []
    for it in (raw if isinstance(raw, list) else []):
        if not isinstance(it, dict):
            continue
        dest = _row_name(it)
        if not dest:
            continue
        items = []
        for i in (it.get("items") or []):
            if not isinstance(i, dict):
                continue
            cat = str(i.get("category") or "").strip()
            raw_amt = i.get("amount")
            amt = None if isinstance(raw_amt, bool) else _num_or_none(raw_amt)
            if not cat or amt is None or amt <= 0:
                continue
            items.append({"category": cat[:20], "amount": round(float(amt), 1),
                          "unit": str(i.get("unit") or "元/月").strip()[:12],
                          "evidence_ids": _filter_eids(i.get("evidence_ids"), valid_ids)})
        if items:
            out.append({"destination": dest, "items": items})
    return out


def _sanitize_action_priorities(raw: Any, valid_ids: set) -> Dict[str, Any]:
    """行动优先级清单（conclusion 章图源）：tier 枚举收敛，未知档按 mid 计。

    无有效行动（缺 action 文本）→ 空对象（降级：不出图）。
    """
    src = raw if isinstance(raw, dict) else {}
    items = []
    for i in (src.get("items") or []):
        if not isinstance(i, dict):
            continue
        action = str(i.get("action") or "").strip()
        if not action:
            continue
        tier = str(i.get("tier") or "").strip().lower()
        items.append({"action": action[:80],
                      "tier": tier if tier in ("high", "mid", "low") else "mid",
                      "evidence_ids": _filter_eids(i.get("evidence_ids"), valid_ids)})
    return {"items": items} if items else {}


def _sanitize_consensus_split(raw: Any, valid_ids: set) -> Dict[str, Any]:
    """共识 vs 反共识（contrarian 章图源）：两侧各自收敛为 {label,summary,[share],eids}。

    单侧缺失只保留存在的一侧（图按实际有料的一侧降级）；两侧皆无 → 空对象。
    """
    src = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    for key, default_label in (("orthodox", "主流共识"), ("contrarian", "反共识判断")):
        side = src.get(key)
        if not isinstance(side, dict):
            continue
        summary = str(side.get("summary") or "").strip()
        if not summary:
            continue
        entry: Dict[str, Any] = {"label": str(side.get("label") or default_label).strip()[:20],
                                 "summary": summary[:200],
                                 "evidence_ids": _filter_eids(side.get("evidence_ids"), valid_ids)}
        share = side.get("share")
        if (isinstance(share, (int, float)) and not isinstance(share, bool)
                and 0 < share <= 100):
            entry["share"] = round(float(share), 1)
        out[key] = entry
    return out


def _fallback_claims(destinations, ev_ids, groups_by_id, authors) -> List[Dict[str, Any]]:
    """LLM 不可用时，仍只输出挂真实证据的结论（不编造内容主张，仅做归纳陈述）。

    groups_by_id（v2.1）：evidence_id → source_group（空组按证据自身），
    用于独立信源组数判定。
    """
    indep = len({groups_by_id.get(i, i) for i in ev_ids[:3]})
    out = [make_claim(_sid("c"),
                      f"已就 {'、'.join(destinations)} 采集到多源公开证据，下列结论均挂载真实来源以供溯源。",
                      "overview", ev_ids[:3], authors[0], indep, "mixed").to_dict()]
    return out


def _diag(recovered: str, truncated: bool = False) -> Dict[str, Any]:
    """写稿路径诊断。recovered ∈ json / text_retry / failed / repaired。"""
    return {DIAG_KEY: {"recovered": recovered, "truncated": bool(truncated)}}


def _diag_of(st: Any) -> Dict[str, Any]:
    """取章节文本里的诊断块（缺失时返回空 dict，兼容旧数据与外部注入）。"""
    return (st or {}).get(DIAG_KEY) or {} if isinstance(st, dict) else {}
