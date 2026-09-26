"""报告总装（M3 自 engine.py 原文迁出 · 行为零变化）。

章节挂载（claims/结构化块/图表按归属匹配，不做类型广播）、舆情专章插入与去重、
封面 SVG、答题摘要、证据/图集/trace 精简、方法论与局限披露、结构完整性台账。
图表 builder 注册表在 charts_build.py；舆情两图与词云在正式舆情章（deep/expert）
与旧报告级舆情面板（quick，本模块插入逻辑）双挂，两档各只命中一个，不会重复。
依赖：modes + writer(_structure_status/_summarize_structure) +
charts_build(_charts_for_section/_build_data_grid) + _util/fetcher/RT 叶子；
不反向依赖 engine。符号由 engine re-export。
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from app.core import research_types as RT
from app.core.fetcher import domain_of
from app.core.models import Evidence
from app.core.research_types import DEFAULT_RESEARCH_TYPE

from ._util import _now, _sid
from .charts_build import _build_data_grid, _charts_for_section
from .modes import MODE_CONFIG
from .writer import _structure_status, _summarize_structure


def _make_cover_svg(title: str, destinations: List[str],
                    research_type: str = DEFAULT_RESEARCH_TYPE) -> str:
    """本地生成报告封面（SVG data URL），零外部依赖、永不失败。

    根因修复：原先封面写入 copilot-cn.bytedance.net 外部 AI 生图 URL，
    浏览器端鉴权/跨域失败 → 列表只显示灰色占位。改为后端确定性生成
    SVG 封面（主题色渐变 + 标题 + 目的地行），直接以 data URL 入库，
    前端 <img> 直接渲染，无网络、无失败。
    """
    byline = RT.type_spec(research_type)["cover_byline"]
    safe_title = (title or "旅游调研").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(safe_title) > 20:
        safe_title = safe_title[:20] + "…"
    dest_line = " · ".join(destinations[:3]) if destinations else "Verda AI"
    safe_dest = dest_line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0f766e"/><stop offset="1" stop-color="#134e4a"/>'
        '</linearGradient></defs>'
        '<rect width="800" height="450" fill="url(#g)"/>'
        '<circle cx="650" cy="80" r="150" fill="#ffffff" opacity="0.06"/>'
        '<circle cx="110" cy="390" r="90" fill="#ffffff" opacity="0.05"/>'
        f'<text x="48" y="70" fill="#a7f3d0" font-family="sans-serif" font-size="20" letter-spacing="2">VERDA · {byline}</text>'
        f'<text x="46" y="225" fill="#ffffff" font-family="sans-serif" font-size="40" font-weight="700">{safe_title}</text>'
        f'<text x="48" y="272" fill="#ccfbf1" font-family="sans-serif" font-size="22">{safe_dest}</text>'
        '<text x="48" y="410" fill="#99f6e4" font-family="sans-serif" font-size="16" opacity="0.85">结论可溯源 · 证据可沉淀</text>'
        '</svg>'
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _answers_digest(clar: Optional[Dict[str, Any]], destinations: List[str],
                    research_type: str) -> List[Dict[str, str]]:
    """报告头部答题摘要：白名单**派生自** CLARIFY_CONSUMERS 的 digest 标记，不另写一份清单。

    destinations 一行取**计划层终值**（锁定/勾选后的权威集合），不取问卷原始勾选，
    防止「问卷题被条件跳过 ⇒ 摘要缺行」与两时点漂移。空值字段静默缺席。
    """
    out: List[Dict[str, str]] = []
    for qid, label in RT.clarify_digest_fields(research_type):
        if qid == "destinations":
            value = "、".join(str(d).strip() for d in (destinations or []) if str(d).strip())
        else:
            raw = (clar or {}).get(qid)
            if isinstance(raw, (list, tuple)):
                value = "、".join(str(x).strip() for x in raw if str(x).strip())
            else:
                value = str(raw or "").strip()
        if value:
            out.append({"label": label, "value": value})
    return out


def _assemble_report(query, destinations, focus, dispatch, claims, evidences, images,
                     sentiment, charts, sections_text, collect_notes,
                     analysis, metrics, quality_before, quality_after,
                     trace_spans, mode, section_ids, sentiment_text=None,
                     objective_meta: Optional[Dict] = None,
                     research_type: str = DEFAULT_RESEARCH_TYPE,
                     clar: Optional[Dict[str, Any]] = None,
                     chart_gaps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rid = _sid("r")
    spec = RT.type_spec(research_type)
    members = [m["id"] for m in dispatch["members"]]
    title = RT.report_title(destinations, research_type)
    indep_domains = len({domain_of(e.source_url) for e in evidences if e.source_url})
    subtitle = (f"基于 {len(evidences)} 条联网证据 · {indep_domains} 个独立来源 · "
                f"{len(members)} 位专家协作生成 · {MODE_CONFIG.get(mode,{}).get('label','深度模式')}")

    # 图表归属（批次⓪ 契约）：spec 声明了 sections 的图**只按归属匹配**（此时类型过滤
    # 失效，sections 是权威归属，供 builder 自声明「图属哪章」）；未声明（None）的图
    # 维持旧「按类型广播」行为——guide 现有图全部未声明，产出零变化。
    # 旧实现按 c["type"] 无差别广播，同类型多图时每章都会拿到全部张数（串章根因）。
    # 章节标题（类型白名单内的章节加中文序号）
    title_map = {**RT.SECTION_PLAN, **RT.numbered_titles(section_ids, research_type)}
    data_grid_sections = set(RT.data_grid_sections_for(research_type, section_ids))

    def _section(sid: str):
        fields, chart_types = RT.section_fields(sid)
        st = sections_text.get(sid, {}) if isinstance(sections_text, dict) else {}
        if not isinstance(st, dict):
            st = {"paragraphs": st if isinstance(st, list) else [str(st)], "key_takeaway": "", "highlights": []}
        sec_claims = [c for c in claims if c["field"] in set(fields)]
        sec_charts = _charts_for_section(sid, charts, chart_types)
        src: List[str] = []
        for c in sec_claims:
            src.extend(c.get("evidence_ids", []))
        for ch in sec_charts:
            src.extend(ch.get("evidence_ids", []))
        seen = set()
        src = [x for x in src if not (x in seen or seen.add(x))]
        sec = {
            "id": sid, "title": title_map.get(sid, sid), "level": 1,
            "key_takeaway": st.get("key_takeaway", ""),
            "highlights": st.get("highlights", []),
            "paragraphs": st.get("paragraphs", []),
            "claims": sec_claims,
            "charts": sec_charts,
            "source_evidence_ids": src,
            "structured": None,
            "data_grid": None,
            "score_gap": None,
        }
        # 结构化对象挂到承载它的章节：claim 字段命中的键，或 SECTION_STRUCTURED 声明的实体表。
        # 挂块为**复数**（rough-cliff-vole）：视角一章同挂核查表+铁律+清单项三块；
        # 既有章节本就一键，形状从 {type,data} 变 [{type,data}]，前端归一化两种形状读。
        structured = analysis.get("structured") or {}
        mount_keys = [k for k in spec["structured_keys"] if k in set(fields)]
        mount_keys += [k for k in RT.section_structured_keys(sid) if k not in mount_keys]
        blocks = [{"type": key, "data": structured[key]}
                  for key in mount_keys if structured.get(key)]
        if blocks:
            sec["structured"] = blocks
        # 数据空间
        if sid in data_grid_sections:
            sec["data_grid"] = _build_data_grid(sid, analysis, evidences)
        # 结构状态：前端据此决定画导图还是如实标注（本就没有材料 vs 写稿失败丢了结构）
        sec["structure_status"] = _structure_status(
            st, bool(sec_claims) or sec.get("structured") is not None)
        # 算分输入缺口（③ 体验层）：取 builder 同一次产出里记的台账，按归属落章。
        # 与 structure_status 是两条正交的轴（那条讲结构提炼，这条讲算分输入），
        # 故不复用同一字段与状态值——lost 是「写稿失败」，本字段是「材料缺可核验数值」。
        gap = next((g for g in (chart_gaps or []) if sid in g.get("sections", ())), None)
        if gap:
            sec["score_gap"] = {"kind": "insufficient_input", "reason": gap["reason"]}
        return sec

    sections = [_section(sid) for sid in section_ids if sid != "sentiment"]

    # 舆情专章（始终插入，置于结论章之前）。取图与 _section 同一谓词入口：
    # 舆情图已声明 sections，不再按产出顺序取首张（旧实现属隐蔽顺序依赖）。
    # 类型白名单保持两类（词云不在旧面板的展示面内，quick 档仍不挂）。
    sent_charts = _charts_for_section("sentiment", charts,
                                      ("sentiment_donut", "platform_bar"))
    st = sentiment_text or {}
    has_sample = bool(sentiment.get("sample_size"))
    # 优先使用 LLM 基于真实数据生成的多段深度解读；无则如实兜底说明
    sent_paras = [p for p in st.get("paragraphs", []) if str(p).strip()]
    if not sent_paras:
        if has_sample:
            sent_paras = [
                f"基于 {sentiment.get('sample_size', 0)} 条全网真实评论的情感与观点阵营分析（抖音优先），"
                f"每条代表性观点均附真实平台链接，可逐条溯源。下方为各平台情感分布、观点阵营占比与代表性原声墙。"
            ]
        else:
            sent_paras = ["本次未能在各社媒平台站内检索到带真实链接的有效评论，"
                          "故不对全网口碑做定量结论（坚持无证据不立论，绝不编造舆情数据）。"]
    sent_takeaway = st.get("key_takeaway") or (
        (f"全网 {sentiment.get('sample_size', 0)} 条真实评论显示，"
         f"正面 {sentiment.get('overall', {}).get('pos', 0)}% / "
         f"中性 {sentiment.get('overall', {}).get('neu', 0)}% / "
         f"负面 {sentiment.get('overall', {}).get('neg', 0)}%。") if has_sample else "")
    sentiment_sec = {
        "id": "sentiment", "title": "全网舆情与观点阵营", "level": 1,
        "key_takeaway": sent_takeaway,
        "highlights": [h for h in st.get("highlights", []) if str(h).strip()],
        "paragraphs": sent_paras,
        "claims": [], "charts": sent_charts, "source_evidence_ids": [],
        "structured": None, "data_grid": None, "score_gap": None,
        "structure_status": _structure_status(st, False),
    }
    # 报告已有正式的「全网舆情」章（sentiment_report 进了本档位章节集）时，
    # 不再插入旧的报告级舆情面板——避免双舆情章；quick 等无该章的档位维持原样。
    if "sentiment_report" not in section_ids:
        # 把舆情章插在 conclusion 之前
        insert_at = len(sections)
        for i, s in enumerate(sections):
            if s["id"] in ("conclusion", "risk"):
                insert_at = i
                break
        sections.insert(insert_at, sentiment_sec)

    if collect_notes:
        sections.append({"id": "trace_note", "title": "附：采集与方法说明", "level": 1,
                         "key_takeaway": "", "highlights": [],
                         "paragraphs": collect_notes, "claims": [], "charts": [],
                         "source_evidence_ids": [], "structured": None, "data_grid": None,
                         "score_gap": None, "structure_status": "by_design"})

    toc = [{"id": s["id"], "title": s["title"], "level": 1} for s in sections]
    glossary = [
        {"term": "交叉验证", "definition": "同一结论由 ≥2 个独立信源组支撑，判为高置信。", "source": "Verda 四铁律"},
        {"term": "无证据不立论", "definition": "任何数据型结论必须挂载 evidence_ids，否则标记待验证。", "source": "Verda 四铁律"},
        {"term": "同质内容去重（信源组）", "definition": "同一内容被多站转载时归并为一个信源组，转载不冒充独立来源。", "source": "客观性加固 v2.1"},
        {"term": "舆论过热", "definition": "互动量超阈值的高热社媒内容，可信度扣分并如实标注，不代表普遍共识。", "source": "客观性加固 v2.1"},
        {"term": "观点阵营", "definition": "将相同立场的真实用户观点聚类，输出归一化占比与代表评论。", "source": "舆情管线"},
    ]
    glossary += [dict(g) for g in spec.get("glossary", ())]
    cover = _make_cover_svg(title, destinations, research_type)

    evidence_dicts = []
    for e in evidences:
        d = e.to_dict()
        d["domain"] = domain_of(e.source_url)
        evidence_dicts.append(d)

    figures = _curate_figures(images, limit=12)
    if figures:
        toc.append({"id": "figures", "title": "实景图集 · 联网采集", "level": 1})

    # 精简 trace（去掉超长 prompt 原文，保留摘要+token+latency+decision+evidence_ids）
    trace_lite = [{
        "span_id": s["span_id"], "seq": s["seq"], "agent_id": s["agent_id"],
        "stage": s["stage"], "purpose": s["purpose"], "model": s["model"],
        "prompt": s["prompt"][:300], "response": s["response"][:300],
        "prompt_tokens": s["prompt_tokens"], "completion_tokens": s["completion_tokens"],
        "total_tokens": s["total_tokens"], "latency_ms": s["latency_ms"],
        "decision": s["decision"], "evidence_ids": s["evidence_ids"], "ts": s["ts"],
    } for s in trace_spans]

    return {
        "id": rid,
        "title": title,
        "subtitle": subtitle,
        "query": query,
        "destinations": destinations,
        "research_type": research_type,
        "answers_digest": _answers_digest(clar, destinations, research_type),
        "mode": mode,
        "created_at": _now(),
        "experts": members,
        "dispatch": dispatch["members"],
        "cover_image": cover,
        "toc": toc,
        "sections": sections,
        "charts": charts,
        "evidence": evidence_dicts,
        "claims": claims,
        "sentiment": sentiment,
        "glossary": glossary,
        "figures": figures,
        "structured": analysis.get("structured") or {},
        "metrics": metrics,
        "quality_before": quality_before,
        "quality_after": quality_after,
        "trace": trace_lite,
        # 结构完整性台账：lost 章节可供事后核对/回补（前端不依赖它渲染）
        "structure_report": _summarize_structure(sections),
        # v2.1 方法论与局限（正式契约字段；标准合规声明）
        "methodology": _build_methodology(objective_meta, evidences),
        "contradictions": [c for c in (analysis.get("contradictions") or []) if isinstance(c, dict)],
    }


def _build_methodology(objective_meta: Optional[Dict], evidences: List[Evidence]) -> Dict[str, Any]:
    """组装方法论与局限披露（v2.1）。objective_meta 缺失时返回空结构（兼容旧调用）。"""
    om = objective_meta or {}
    ost = om.get("stats") or {}
    total_ev = len(evidences) or 1
    checked_ratio = round((ost.get("viral_checked", 0) or 0) / total_ev, 4)
    return {
        "window": om.get("freshness", "noLimit"),
        "evidence_count": len(evidences),
        "unique_groups": int(om.get("unique_groups", 0)),
        "dup_skipped": int(ost.get("dup_skipped", 0)),
        "viral_evidence": int(ost.get("viral_count", 0)),
        "viral_checked_ratio": checked_ratio,
        "sentiment_samples": int(om.get("sentiment_samples", 0)),
        "note": ("信息来源于公开网络搜索，已做内容级去重（同质转载归并为信源组）与舆论过热标注；"
                 f"过热判定覆盖率 {round(checked_ratio * 100)}%（低覆盖率即多数证据无互动信号、未做过度推断）；"
                 "报告可能存在舆论偏好与时效局限，仅供参考，不作事实认证。"),
    }


def _curate_figures(images: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    """从采集到的配图中精选：URL 去重，按目的地轮询保证均衡，封顶 limit 张。"""
    seen: set = set()
    by_destination: Dict[str, List[Dict[str, Any]]] = {}
    for im in images:
        src = (im.get("src") or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        by_destination.setdefault(im.get("destination", ""), []).append(im)
    out: List[Dict[str, Any]] = []
    idx = 0
    while len(out) < limit:
        added = False
        for dest in list(by_destination.keys()):
            lst = by_destination[dest]
            if idx < len(lst):
                out.append(lst[idx])
                added = True
                if len(out) >= limit:
                    break
        if not added:
            break
        idx += 1
    return out
