"""章节撰写与写后修复（M3 自 engine.py 原文迁出 · 行为零变化）。

逐章 LLM 生成（独立 token 预算/模型，JSON 优先 + 纯文本重试）、写稿诊断块
_diag（json/text_retry/failed/repaired）、结构丢失极小补齐、舆情叙事、
精修路径的证据吸收式重写。章节标题/提示/字段归属全部查 research_types。
依赖：runtime + analyze(_diag)/collect(_evidence_digest) + llm/sentiment 叶子；
不反向依赖 engine。符号由 engine re-export。
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from app.core import llm, research_types as RT
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core.sentiment import PLATFORM_LABEL

from . import runtime
from .analyze import _ENTITY_STAGE_KEYS, _diag, _diag_of
from .collect import _evidence_digest


# 结构化键 → 展示用中文名（写入章节提示时给 LLM 一个可读标签）
_STRUCTURED_LABEL: Dict[str, str] = {
    "spot_ranking": "景点综合评分榜", "food_ranking": "美食Top榜",
    "spot_routes": "逐景点路线", "shop_list": "美食商铺清单",
    "route_plan": "逐日路线", "stay_options": "住宿选项", "cost_breakdown": "花费拆解",
    "access_matrix": "可达性矩阵", "amenity_checklist": "配套清单", "risk_profile": "风险画像",
}


# ── 撰写：LLM 逐章产出正文（行研/咨询级深度）─────────────
# 章节标题 / 章节提示 / 视角映射 / 字段归属全部由 research_types 单一真相源提供，
# 本模块只做渲染与编排（新增调研类型无需改这里）。


def _structureless(st: Any) -> bool:
    """该章是否「有正文、但结构字段全空」——即前端章节导图会降级成一行正文计数的状态。

    同时用于两处：写后补齐的筛选条件，以及结构完整性观测的计数口径（同一口径，不漂移）。
    """
    if not isinstance(st, dict) or not st.get("paragraphs"):
        return False
    return not (str(st.get("key_takeaway") or "").strip() or st.get("highlights"))


def _structure_status(st: Any, has_material: bool) -> str:
    """章节结构状态：ok / repaired / lost / by_design（前端据此决定导图还是如实标注）。

    写稿诊断优先于材料推断：实测 9/11 章「有材料却没结构」是预算被推理 token 吃光造成的，
    若只看材料会被误判成 by_design，丢失真相。
    """
    if not isinstance(st, dict):
        return "by_design" if not has_material else "lost"
    if str(st.get("key_takeaway") or "").strip() or st.get("highlights"):
        return "repaired" if _diag_of(st).get("recovered") == "repaired" else "ok"
    if _diag_of(st).get("recovered") in ("text_retry", "failed"):
        return "lost"
    return "lost" if has_material else "by_design"


def _summarize_structure(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """结构完整性台账（随报告落库）：让「这轮有几章丢了结构」可事后核对，不靠翻 trace。"""
    counts = Counter(s.get("structure_status", "unknown") for s in sections)
    return {
        "total": len(sections),
        "ok": counts.get("ok", 0),
        "repaired": [s["id"] for s in sections if s.get("structure_status") == "repaired"],
        "lost": [s["id"] for s in sections if s.get("structure_status") == "lost"],
        "by_design": counts.get("by_design", 0),
    }


def _write_single_section(sid: str, title: str, query, destinations, focus,
                          evidences, claims, analysis, model: str, research_type: str = DEFAULT_RESEARCH_TYPE,
                          min_paragraphs: int = 5, para_words: str = "180-280",
                          section_max_tokens: int = 6000,
                          sentiment: Optional[Dict[str, Any]] = None,
                          persp_line: str = "") -> Dict[str, Any]:
    """单章独立生成：每章独立 token 预算 + 独立模型，失败不影响其他章节。

    篇幅深度由 min_paragraphs/para_words/section_max_tokens 三档动态控制
    （快速/深度/专家级越来越长、越来越详尽）。
    """
    spec = RT.type_spec(research_type)
    fields, chart_types = RT.section_fields(sid)
    rel_claims = [c for c in claims if c.get("field") in set(fields)]
    digest = _evidence_digest(evidences, limit=20)
    claim_text = "\n".join(
        f"- [{','.join(c.get('evidence_ids', [])) or '无'}] {c['text']}（{c['confidence']}）"
        for c in rel_claims[:8]
    ) or "（无直接相关论点，请基于证据自行提炼）"

    extra = ""
    tr = analysis.get("trends") or {}
    if tr.get("note") and ("trend" in chart_types or "trend" in fields):
        extra += f"\n趋势研判：{tr['note']}"
    comp = analysis.get(spec["radar_key"]) or {}
    if comp.get("dimensions") and "radar" in chart_types:
        extra += f"\n对比维度：{', '.join(comp['dimensions'][:6])}"
    cb = spec.get("cost_bar") or {}
    cost_rows = analysis.get(cb.get("key")) or []
    if cost_rows and "cost_bar" in chart_types:
        extra += f"\n成本数据：{json.dumps(cost_rows[:3], ensure_ascii=False)}"
    if sid == "season":
        season = analysis.get("season") or {}
        if season.get("note") or season.get("best_months"):
            extra += f"\n季节研判：{json.dumps(season, ensure_ascii=False)[:600]}"
    structured = analysis.get("structured") or {}
    # 章节挂载的结构化对象：SECTION_FIELDS 的 claim 字段 + SECTION_STRUCTURED 的实体表。
    # 实体表是下游章节的唯一景点/美食真相源——正文只能引用表内名称与 spot_id。
    mount_keys = [k for k in spec["structured_keys"] if k in set(fields)]
    mount_keys += [k for k in RT.section_structured_keys(sid) if k not in mount_keys]
    for key in mount_keys:
        if not structured.get(key):
            continue
        label = _STRUCTURED_LABEL.get(key, key)
        if key in _ENTITY_STAGE_KEYS:
            extra += (f"\n【{label}·唯一实体表】以下条目是本次调研锁定的景点实体（含规则算出的评分与明细）。"
                      "本章只能引用表内的景点名与 spot_id，禁止改名、合并或补充表外景点；"
                      f"排序以 score 为准。{json.dumps(structured[key][:1], ensure_ascii=False)[:1200]}")
        else:
            extra += f"\n{label}结构：{json.dumps(structured[key][:2], ensure_ascii=False)[:800]}"
    # 攻略信息密度硬约束（编辑规则，声明在类型注册表；assessment 无此键则不注入）
    if spec.get("density"):
        extra += f"\n【信息密度铁律】{spec['density']}"
    # 视角专属章硬约束（rough-cliff-vole P4）：问卷答案是生成约束，不是装饰——
    # 超约束建议必须显式条件句；核查表已结构化，正文不得逐格复述（同 spots 契约）。
    if persp_line:
        extra += ("\n【本次问卷硬约束】" + persp_line +
                  " ——超约束的建议不得出现，或显式标注「若延长行程/上浮预算」条件句；"
                  "核查表与铁律清单已由系统结构化产出并随本章展示，"
                  "正文只写表格装不下的判断与机理，禁止逐格复述表格内容。")
    # 舆情章节：注入真实统计（占比/样本量/平台分布），只准解读统计，禁止编造或引用评论原句
    if sentiment and "sentiment" in set(fields):
        if sentiment.get("sample_size"):
            extra += ("\n【舆情实测统计（唯一数据源，只能引用这些数字）】"
                      + json.dumps({
                          "sample_size": sentiment.get("sample_size"),
                          "overall": sentiment.get("overall"),
                          "by_platform": sentiment.get("by_platform"),
                          "camps": [{"title": c.get("title"), "ratio": c.get("ratio")}
                                    for c in (sentiment.get("camps") or [])[:4]],
                          # (spot×platform) 双维：逐景点小表/舆情卡的真实统计（勿复述，图表呈现）
                          "by_spot": [{"spot_name": s.get("spot_name"), "sample": s.get("sample"),
                                       "pos": s.get("pos"), "neg": s.get("neg")}
                                      for s in (sentiment.get("by_spot") or [])[:10]],
                      }, ensure_ascii=False)[:1600])
        else:
            extra += "\n【舆情实测统计】本次未采集到足量真实评论，请如实说明缺口，不得给出定量口碑结论。"

    section_role = RT.SECTION_PROMPTS.get(sid, "深度旅游调研章节")
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是顶尖旅游媒体主编 + 资深旅行顾问级别的报告撰稿人。"
                    f"你正在写一份「{spec['label']}」（{spec['subtitle']}）报告，"
                    "要求有锋芒、有独到观点、敢于下判断，对标 Lonely Planet 深度指南与专业调研报告。\n"
                    f"本章定位：{section_role}\n"
                    "写作要求（务必做到）：\n"
                    "1) 结论先行：key_takeaway 必须是 JSON 的第一个字段，给一句最锐利、最有信息量的『核心判断』，可以直接给出推荐/劝退结论；\n"
                    "2) 有观点：正文要解读『为什么』而非罗列『是什么』，给出行程/居住的取舍与你的独立判断；\n"
                    "3) 有数据：尽量引用证据中的具体数字、价格、班次、耗时、对比；避免空话套话和正确的废话；\n"
                    f"4) 有深度：正文不少于 {min_paragraphs} 段，每段 {para_words} 字，要有层次、有递进的论证链、有洞察，"
                    "段落之间要有逻辑推进（现象→机理→影响→建议），不要并列堆砌；\n"
                    "5) 有亮点：给 2-3 条 highlights（最有冲击力的发现/反差/独特洞察，每条一句话）；\n"
                    "6) 溯源：在正文关键结论后用方括号标注支撑它的 evidence_id，形如 [e_xxxx]（必须来自给定证据/论点的真实 id）；\n"
                    "7) 客观性铁律：区分事实陈述与观点研判——事实须有可溯源证据；观点用『我们建议/有待验证』等措辞，"
                    "不得写成定论；单一信源组或存在矛盾的结论须标注『据报道/单方说法/存在争议』，禁止直接断言；"
                    "情绪化社媒证据只能作『口碑感知』描述，不得转述为客观事实（如把单条差评写成『普遍宰客』）。\n"
                    '输出 JSON（字段顺序固定：先结构、后正文，便于截断时结构字段已落盘）：'
                    '{"key_takeaway":"核心判断一句话","highlights":["亮点1","亮点2","亮点3"],"paragraphs":["第一段","第二段",...]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"章节标题：{title}\n"
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}\n"
                    f"相关论点（含支撑 evidence_id）：\n{claim_text}\n{extra}\n\n证据摘要：\n{digest}"
                )},
            ],
            max_tokens=section_max_tokens,
            temperature=0.7,
            model=model,
            purpose=f"撰写章节：{title}",
        )
        truncated = llm.last_finish_reason() == "length"
        if isinstance(data, dict):
            paras = data.get("paragraphs")
            if isinstance(paras, str):
                paras = [paras]
            paras = [str(p).strip() for p in paras if isinstance(p, str) and str(p).strip()]
            hl = data.get("highlights")
            hl = [str(h).strip() for h in hl if isinstance(h, str) and str(h).strip()] if isinstance(hl, list) else []
            kt = str(data.get("key_takeaway", "")).strip()
            if paras:
                return {"paragraphs": paras, "key_takeaway": kt, "highlights": hl,
                        **_diag("json", truncated)}
    except Exception:
        pass
    # 空章重试一次（更直接的提示）
    try:
        retry = llm.chat(
            [
                {"role": "system", "content": (
                    f"你是资深旅游调研分析师，针对给定章节写不少于 {min_paragraphs} 段深度分析，"
                    f"每段约 {para_words} 字，论证层层递进，直接输出正文（不要 JSON、不要标题）。"
                )},
                {"role": "user", "content": f"章节：{title}\n主题：{query}\n目的地：{'、'.join(destinations)}\n证据：\n{digest[:2000]}"},
            ],
            max_tokens=section_max_tokens, temperature=0.7, model=model, purpose=f"重试撰写章节：{title}",
        )
        paras = [p.strip() for p in retry.split("\n") if len(p.strip()) > 30]
        if paras:
            # 纯文本重试天然拿不到结构字段，交写后补齐（_repair_missing_structure）
            return {"paragraphs": paras, "key_takeaway": "", "highlights": [],
                    **_diag("text_retry", truncated or llm.last_finish_reason() == "length")}
    except Exception:
        pass
    return {"paragraphs": ["本章节内容生成失败，请重新运行调研或切换模型。"],
            "key_takeaway": "", "highlights": [], **_diag("failed", truncated)}


def _repair_missing_structure(sid: str, title: str, st: Dict[str, Any],
                              claims: List[Dict[str, Any]], model: str) -> Optional[Dict[str, Any]]:
    """给「有正文、无结构」的章节补一次极小结构请求（key_takeaway + highlights）。

    为什么需要它：单章输出预算被服务商上限（8192）夹住，而推理模型的思考 token 与正文共享
    该预算——单次调用无法保证结构字段一定落盘（实测 9/11 章因此丢了结构，导致前端章节导图
    全部降级成一行正文计数）。这里以极小输出（~200 token）二次提炼，成功即标 repaired，
    失败返回 None 由上层保持 lost（绝不静默）。

    只喂本章已成稿的正文 + 该章相关论点，不重发全部证据摘要：省 token，也避免与既成正文漂移。
    """
    paras = [str(p).strip() for p in (st.get("paragraphs") or []) if str(p).strip()]
    if not paras:
        return None
    fields, _ = RT.section_fields(sid)
    rel = "\n".join(f"- {c['text']}" for c in claims if c.get("field") in set(fields))[:800]
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是资深旅游调研主编。下面是一章已成稿的正文，只做『提炼』，不得改写正文。\n"
                    '输出 JSON（字段顺序固定）：{"key_takeaway":"本章核心判断一句话",'
                    '"highlights":["亮点1","亮点2","亮点3"]}。只输出 JSON。\n'
                    "要求：key_takeaway 必须有信息量、可下判断（可直接给推荐/劝退结论）；"
                    "highlights 给 2-3 条最有冲击力的发现或反差，每条一句话；"
                    "只依据给定正文提炼，不得引入正文之外的新事实、新数字。"
                )},
                {"role": "user", "content": (
                    f"章节标题：{title}\n" + (f"相关论点：\n{rel}\n" if rel else "")
                    + "正文：\n" + "\n".join(paras)[:1500]
                )},
            ],
            max_tokens=600,
            temperature=0.3,
            model=model,
            purpose=f"补齐章节结构：{title}",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    kt = str(data.get("key_takeaway", "")).strip()
    hl = data.get("highlights")
    hl = [str(h).strip() for h in hl if isinstance(h, str) and str(h).strip()] if isinstance(hl, list) else []
    if not kt and not hl:
        return None
    return {"key_takeaway": kt, "highlights": hl[:3],
            **_diag("repaired", _diag_of(st).get("truncated", False))}


def _write_sentiment_narrative(query, destinations, sentiment: Dict[str, Any], model: str,
                               min_paragraphs: int = 5, para_words: str = "180-280",
                               section_max_tokens: int = 6000) -> Dict[str, Any]:
    """基于真实舆情数据生成多段深度解读（绝不在无数据时编造）。

    返回 {"paragraphs": [...], "key_takeaway": "...", "highlights": [...]}。
    无任何真实评论时返回空 paragraphs（由调用方走如实标注的兜底）。
    """
    sample = sentiment.get("sample_size", 0)
    if not sample:
        # 无样本时不写诊断块：这不是「写失败」，归 by_design（本就无可结构化材料）
        return {"paragraphs": [], "key_takeaway": "", "highlights": []}

    overall = sentiment.get("overall", {})
    by_platform = sentiment.get("by_platform", {})
    camps = sentiment.get("camps", [])
    voices = sentiment.get("voices", [])
    # 组装真实数据摘要喂给 LLM（只用真实计数/原声，不许 LLM 自造数字）
    plat_lines = "；".join(
        f"{PLATFORM_LABEL.get(p, p)} 正{v.get('pos',0)}/中{v.get('neu',0)}/负{v.get('neg',0)}"
        for p, v in by_platform.items()
    ) or "（暂无平台分布）"
    camp_lines = "\n".join(
        f"- {c.get('title','')}（占比 {c.get('ratio',0)}%）：{c.get('summary','')}"
        for c in camps
    ) or "（暂无明显阵营分化）"
    voice_lines = "\n".join(
        f"- [{v.get('platform_label','')}|{v.get('sentiment','')}] {v.get('text','')}"
        for v in voices[:12]
    ) or "（暂无代表性原声）"

    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是顶尖社媒舆情分析师 + 旅游目的地顾问。基于给定的【真实舆情统计与原声】，"
                    "写一段有锋芒、有洞察的全网口碑深度解读。\n"
                    "硬性要求：\n"
                    "1) 只能基于给定的真实数据与原声做解读，严禁编造任何不存在的数字、平台或评论；\n"
                    f"2) 正文不少于 {min_paragraphs} 段，每段 {para_words} 字，"
                    "逐层递进：整体情感盘面→平台差异→观点阵营博弈→真实原声印证→对出行/居住决策的启示；\n"
                    "3) 要解读『为什么』——不同平台/人群为何呈现这种口碑差异，背后的体验与客流原因；\n"
                    "4) 给 2-3 条 highlights（最有冲击力的口碑发现或反差，每条一句话）；\n"
                    "4.5) 全程区分『舆情感知』与『客观事实』：社媒评论/热度隶属口碑感知，不得转述为客观属性"
                    "（如把个别吐槽写成『普遍宰客』），避免把少数/高热声音写成共识；\n"
                    "5) 开头必须交代真实样本规模与平台分布（来自给定统计，不得编造）；样本量偏小时如实在解读中点明"
                    "『样本有限、结论为方向性参考』，不得掩盖。\n"
                    '输出 JSON（字段顺序固定：先结构、后正文）：'
                    '{"key_takeaway":"一句话核心口碑判断","highlights":["亮点1","亮点2"],"paragraphs":["段1","段2",...]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n"
                    f"真实样本量：{sample} 条带链接评论\n"
                    f"整体情感占比：正面 {overall.get('pos',0)}% / 中性 {overall.get('neu',0)}% / 负面 {overall.get('neg',0)}%\n"
                    f"平台分布：{plat_lines}\n"
                    f"观点阵营：\n{camp_lines}\n"
                    f"代表性真实原声：\n{voice_lines}"
                )},
            ],
            max_tokens=section_max_tokens,
            temperature=0.6,
            model=model,
            purpose="撰写章节：全网舆情与观点阵营",
        )
        truncated = llm.last_finish_reason() == "length"
        if isinstance(data, dict):
            paras = data.get("paragraphs")
            if isinstance(paras, str):
                paras = [paras]
            paras = [str(p).strip() for p in paras if isinstance(p, str) and str(p).strip()]
            hl = data.get("highlights")
            hl = [str(h).strip() for h in hl if isinstance(h, str) and str(h).strip()] if isinstance(hl, list) else []
            kt = str(data.get("key_takeaway", "")).strip()
            if paras:
                return {"paragraphs": paras, "key_takeaway": kt, "highlights": hl,
                        **_diag("json", truncated)}
    except Exception:
        pass
    return {"paragraphs": [], "key_takeaway": "", "highlights": [], **_diag("failed")}


def _rewrite_section(section: Dict[str, Any], extra_context: Dict[str, Any],
                     system_prompt: Optional[str] = None) -> Dict[str, Any]:
    """基于补充材料（extra_context['digest']）重写单个章节段落，就地标注 refined + absorbed。

    纯同步（内含阻塞 llm.chat_json）；调用方在异步管线里须用 `await asyncio.to_thread(_rewrite_section, ...)`
    包裹，避免冻结事件循环（P1-2，与 run_pipeline 的 to_thread 惯例一致）。
    """
    digest = extra_context.get("digest", "")
    absorbed = extra_context.get("absorbed_evidence_ids", [])
    existing = "\n".join(section.get("paragraphs", []))
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    system_prompt or
                    "你是资深旅游调研分析师。请基于已有证据与补充材料，把该章节重写得更深、更厚、更有针对性——"
                    "补充论证、数据、对比与独立判断。"
                    '输出 JSON：{"paragraphs":["段落"],"key_takeaway":"核心判断","highlights":["亮点"]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"章节标题：{section.get('title','')}\n"
                    f"补充证据：\n{digest}\n\n现有章节内容：\n{existing}"
                )},
            ],
            max_tokens=6000, temperature=0.7,
            model=runtime._model("core"), purpose=f"基于新证据重写章节：{section.get('title','')}",
        )
        if isinstance(data, dict) and data.get("paragraphs"):
            paras = [str(p).strip() for p in data["paragraphs"] if str(p).strip()]
            if paras:
                section["paragraphs"] = paras
                if data.get("key_takeaway"):
                    section["key_takeaway"] = str(data["key_takeaway"])
                hl = data.get("highlights")
                if isinstance(hl, list):
                    section["highlights"] = [str(h) for h in hl if str(h).strip()]
                section["refined"] = True
                section["absorbed_evidence_ids"] = absorbed
    except Exception:  # noqa: BLE001
        # 单章失败不阻断其余章节；report 级错误由调用方处理
        pass
    return section
