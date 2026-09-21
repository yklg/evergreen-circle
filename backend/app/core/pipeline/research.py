"""目的地调研流水线（独立于竞品编排的中性调研链路）。

`research_pipeline(task_id)`：async generator，被 runner 的封闭注册表按 kind 分发到
research / travel_guide / travel_assess。本模块**不 import orchestrator**——竞品对比
的编排、品牌采集、对比雷达统统不在这里，从架构上杜绝竞品 DNA 回流。

流程（intake→orchestrator→collect→sentiment→write→audit→done）：
  1.  intake      LLM 拆解目的地调研计划（subject/focus），失败回退纯文本角度表
  2.  orchestrator LLM 从专家名册动态建队（逐成员分工理由叙事），失败回退展示层名单
  3.  collect     多轮批次采集：每批 thought(action→finding) + 逐条 evidence + 进度渐进
  4.  sentiment   多平台舆情（PLATFORM_SITES site: 检索）+ 中性 aggregate_sentiment，
                  只在这个模块输出 platform 分布；绝不调用品牌型 analyze_sentiment
  5.  write       逐章并行成稿（report_voice 章节集）+ persona，失败模板兜底
  6.  audit       中性质检：evaluate_quality 规则侧 + 目的地中立 LLM 审阅 -> audit_review

事件契约对齐前端 useTaskStream：node_update / progress / report_ready / done / error；
节点状态统一用 working/done/idle（前端 taskStore 依赖 working 判 activeNode）。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.core import db
from app.core.audit import evaluate_quality
from app.core.credibility import score_evidence
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core.fetcher import domain_of, fetch_page
from app.core.llm import chat, chat_json
from app.core.platforms import classify_platform
from app.core.research_profile import REPORT_PROFILES, report_voice
from app.core.search import multi_search
from app.core.sentiment import (
    PLATFORM_LABEL,
    PLATFORM_SITES,
    aggregate_sentiment,
    category_keywords,
    sentiment_relevant,
)
from app.core.source_type import source_type

# 中性守卫：本模块绝不 import orchestrator 编排，也不调用品牌型 analyze_sentiment（brand 语义）。

logger = logging.getLogger(__name__)

# 节点 id / label（前端工作台画节点）；其中「orchestrator」为规划阶段（沿用既有流水线节点命名）。
RESEARCH_NODES = [
    ("intake", "解析任务"),
    ("orchestrator", "规划角度与专家"),
    ("collect", "逐角采集证据"),
    ("sentiment", "聚合口碑舆情"),
    ("write", "并行成稿"),
    ("audit", "质量与落库"),
    ("done", "完成"),
]
STAGE_PERCENT = {
    "intake": 5, "orchestrator": 16, "collect": 62,
    "sentiment": 76, "write": 90, "audit": 96, "done": 99,
}

# 各产出体裁的角度表（collect 逐角检索 + write 章节取材）
ANGLE_MAP = {
    "guide": ["交通与票务", "餐饮住宿", "路线与错峰", "安全与物资", "预算花费", "口碑与游客评价"],
    "assess": ["可达性", "配套完善度", "性价比", "安全性", "承载力", "口碑与风评"],
}

_SECTION_TITLES = {
    "summary": "报告概览",
    "guide_overview": "目的地概览",
    "guide_transport": "交通与票务",
    "guide_food_stay": "餐饮住宿",
    "guide_route": "路线与错峰",
    "guide_safe": "安全与物资",
    "guide_budget": "预算花费",
    "guide_voice": "口碑与游客评价",
    "assess_access": "可达性",
    "assess_amenity": "配套完善度",
    "assess_price": "性价比",
    "assess_safety": "安全性",
    "assess_voice": "口碑与风评",
    "assess_conclusion": "评估小结",
    "conclusion": "总结",
}

# 目的地调研专家种（旅行域人设，无任何竞品语义）
TRAVEL_EXPERTS = {
    "guide": [
        {"id": "ex_planner", "name": "攻略顾问", "role": "资深旅游策划", "tasks": ["路线", "错峰"]},
        {"id": "ex_voice", "name": "口碑分析师", "role": "游客舆情", "tasks": ["口碑与评价"]},
    ],
    "assess": [
        {"id": "ex_planner", "name": "评估专家", "role": "城市规划 + 旅经", "tasks": ["可达", "配套", "性价比", "安全"]},
        {"id": "ex_voice", "name": "口碑分析师", "role": "游客舆情", "tasks": ["口碑与风评"]},
    ],
}
_EXPERTS_UNION = [
    {"id": "ex_planner", "name": "攻略 + 评估双栖", "role": "文旅研究 + 策划", "tasks": ["攻略", "评估"]},
    {"id": "ex_voice", "name": "口碑分析师", "role": "游客舆情", "tasks": ["口碑与评价"]},
]


def _ev(type_: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": type_, "data": data}


# 展示层专家 id（锚定 app/data/experts.json 真实库 → 工作台专家队/头像可解析，杜绝悬空）。
# 亦作为 LLM 动态建队失败时的保底名单。前端演示流 mocks/researchStream.ts 的 members 与本表须保持同构。
_SSE_EXPERTS = ["L3-001", "L3-002", "L1-003", "L1-004"]


def _thought(kind: str, expert: str, text: str) -> Dict[str, Any]:
    """预构 thought 展示事件载荷（工作台思维流渲染：id/kind/expert/text/ts）。"""
    return {"id": _nid(), "kind": kind, "expert": expert, "text": text, "ts": time.time()}


def _band(lo: int, hi: int, frac: float) -> int:
    """在阶段进度区间内线性内插（用于 collect/write 的逐批增量），保证随 frac 单调不掉头。"""
    return round(lo + (hi - lo) * max(0.0, min(frac, 1.0)))


def _nid() -> str:
    return f"{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# 阶段：intake（任务参数解析 + LLM 计划增强）
# --------------------------------------------------------------------------- #
def _task(task_id: str) -> Dict[str, Any]:
    return db.get_task_full(task_id) or {}


def _task_purpose(task: Dict[str, Any]) -> str:
    p = (task.get("purpose") or "").strip().lower()
    return p if p in REPORT_PROFILES else "guide"


def _task_subject(task: Dict[str, Any]) -> str:
    q = (task.get("query") or "").strip()
    cls = task.get("clarifications") or {}
    return str(cls.get("destination") or cls.get("subject") or q or "目的地")


def _task_data_mode(task: Dict[str, Any]) -> str:
    cls = task.get("clarifications") or {}
    md = (cls.get("data_mode") or task.get("data_mode") or "live").lower()
    return md if md in ("live", "fixture") else "live"


def _plan_travel(task_id: str) -> Dict[str, Any]:
    """确定性基线计划：纯角度表（无 LLM，离线可跑）。"""
    task = _task(task_id)
    purpose = _task_purpose(task)
    subj = _task_subject(task)
    if purpose == "research":
        angles = list(dict.fromkeys(ANGLE_MAP["guide"] + ANGLE_MAP["assess"]))
    else:
        angles = list(ANGLE_MAP.get(purpose, ANGLE_MAP["guide"]))
    return {"subject": subj, "purpose": purpose, "angles": angles}


def _plan_destination(task_id: str) -> Dict[str, Any]:
    """intake：LLM 拆解目的地调研计划（subject/focus），失败回退 `_plan_travel`。

    仅用于“质感”增强（重点维度叙事），角度表仍以基线 ANGLE_MAP 为准，避免 LLM 胡诌角度。
    """
    base = _plan_travel(task_id)
    subj, purpose = base["subject"], base["purpose"]
    focus = None
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是目的地调研策划。输入目的地与产出体裁，输出 JSON："
                    '{"subject":"规范化后的目的地名称","focus":"2-3 个最关键调研维度（中文、顿号分隔）"}。'
                    "只输出 JSON。" 
                )},
                {"role": "user", "content": f"目的地：{subj}\n体裁：{purpose}\n基线角度：{'、'.join(base['angles'])}"},
            ],
            temperature=0.3, purpose=f"research/plan/{purpose}",
        )
        if isinstance(data, dict):
            focus = str(data.get("focus") or "").strip() or None
            _ns = str(data.get("subject") or "").strip()
            if _ns and _ns != subj:
                subj = _ns[:40]
    except Exception as e:  # noqa: BLE001
        logger.warning("目的地计划 LLM 增强失败，回退基线: %s", e)
    plan = {"subject": subj, "purpose": purpose, "angles": base["angles"]}
    if focus:
        plan["focus"] = focus
    return plan


# --------------------------------------------------------------------------- #
# 阶段：orchestrator（LLM 动态建队 + 名册校验）
# --------------------------------------------------------------------------- #
def _roster_index() -> Dict[str, dict]:
    from app.data import load_experts  # 中性工具层，非 orchestrator
    return {e.get("id"): e for e in load_experts()}


def _fallback_team(subject: str) -> Tuple[List[str], List[str]]:
    """保底专家队：取展示层真实名单，reason 由名册角色 + 目的地派生（离线可用）。"""
    roster = _roster_index()
    ids: List[str] = []
    reasons: List[str] = []
    for eid in _SSE_EXPERTS:
        e = roster.get(eid)
        if not e:
            continue
        label = ((e.get("role_title") or "").split(" / ")[0] or e.get("name") or "调研专家").strip()
        reason = f"承担「{subject}」调研的{label}分工与线索核查。"
        ids.append(eid)
        reasons.append(reason)
    if not ids:
        ids, reasons = list(_SSE_EXPERTS), ["承担目的地调研的专家分工与线索核查。"] * len(_SSE_EXPERTS)
    return ids, reasons


def _dispatch_destination(subject: str, angles: List[str], purpose: str) -> Tuple[List[str], List[str]]:
    """从专家名册中 LLM 挑选调研小组（1 领队 + 执行），逐成员分工理由；失败/无效回退。

    返回 (member_ids, reasons)；ids 均经 load_experts() 名册校验，杜绝悬空头像。
    """
    from app.core.expert_prompt import roster_payload

    roster = _roster_index()
    picked: List[Tuple[str, str]] = []
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是任务编排官（L3 决策层）。为一次『目的地调研』从专家名册中选 3 位专家组成调研小组："
                    "1 位领队（尽量选 Level 高者）+ 2 位领域执行专家，各给一句分工理由。"
                    '只输出 JSON：{"team":[{"id":"专家id","reason":"分工理由"}]}，id 必须取自名册，不得编造。'
                )},
                {"role": "user", "content": (
                    f"目的地：{subject}\n调研体裁：{purpose}\n重点角度：{'、'.join(angles)}\n"
                    f"{roster_payload(list(roster.values()))}"
                )},
            ],
            temperature=0.3, purpose="目的地调研编排专家团",
        )
        if isinstance(data, dict):
            seen: set = set()
            for it in (data.get("team") or []):
                eid = str(it.get("id") or "").strip()
                if eid in roster and eid not in seen and len(picked) < 3:
                    seen.add(eid)
                    reason = str(it.get("reason") or "").strip() or "分工"
                    picked.append((eid, reason))
    except Exception as e:  # noqa: BLE001
        logger.warning("专家团 LLM 编排失败，回退名册保底: %s", e)
    if len(picked) < 2:
        return _fallback_team(subject)
    # 领队优先：让 Level 最高（如 L3）的成员排第一
    def _lv(eid: str) -> int:
        return {"L3": 3, "L2": 2, "L1": 1}.get((eid or "").split("-")[0], 0)
    picked.sort(key=lambda pair: -_lv(pair[0]))
    ids = [p[0] for p in picked]
    reasons = [p[1] for p in picked]
    return ids, reasons


# --------------------------------------------------------------------------- #
# 阶段：collect（多轮批次采集，制造节奏感 + 逐批叙事）
# --------------------------------------------------------------------------- #
def _normalize_hit(r: Dict[str, Any]) -> Dict[str, str]:
    return {
        "url": r.get("url") or "",
        "title": r.get("title") or "",
        "text": (r.get("snippet") or r.get("content") or r.get("excerpt") or "").strip(),
    }


def _fixture_evidence(subject: str, angles: List[str]) -> List[Dict[str, Any]]:
    """演示（fixture）模式：返回可离线的样例证据（不联网、不编造成真实用户原声）。"""
    known = {"黄山": [("景区官网出行提示", "官方公众号今日发布登山安全与预约提示"),
                     ("游客实测分享", "实测云谷索道需排队两小时，山顶风景为最亮点")],
             "成都": [("文旅局发布", "成都是美食之都，餐饮配套密集"),
                     ("游客攻略", "淡季住宿性价比高，市区交通便利")]}
    rows = []
    for i, (t, body) in enumerate((known.get(subject) or [])[:2]):
        rows.append({
            "evidence_id": f"e_fx_{i}", "source_url": f"https://demo.local/{i}",
            "title": t, "text": body, "excerpt": body, "source_type": "web",
            "domain": "demo.local", "source_group": f"g_fx_{i}",
            "credibility": 60.0, "collected_by": f"fixture/{angles[0] if angles else 'all'}",
            "appraisal": "", "theme": angles[0] if angles else "整体",
        })
    return rows


class _Collector:
    """单目的地实时采集器：跨角度共享去重/分群状态，各角度搜索放线程池并发。

    only the post-await (main-loop) part touches `self.seen/self.groups`，
    因此同一事件循环内串行执行，无需额外加锁，同时不阻塞 uvicorn 单事件循环。
    """

    def __init__(self, subject: str):
        self.subject = subject
        self.groups: list = []
        self.seen: set = set()
        self.kws = category_keywords(subject)

    def _search(self, angle: str):  # 同步阻塞，调用处必须包 to_thread
        return multi_search([f"{self.subject} {angle}",
                             f"{self.subject} {angle} 攻略", f"{self.subject} 去吗"], num=5)

    async def one(self, angle: str) -> List[Dict[str, Any]]:
        try:
            hits = await asyncio.to_thread(self._search, angle)
        except Exception as e:  # noqa: BLE001
            logger.warning("角度 %s 搜索失败，跳过: %s", angle, e)
            return []
        batch: List[Dict[str, Any]] = []
        for r in hits:
            url = r.get("url", "")
            if not url or url in self.seen:
                continue
            norm = _normalize_hit(r)
            if not sentiment_relevant(self.subject, self.kws, norm["title"], norm["text"]):
                continue
            try:
                page = await asyncio.to_thread(fetch_page, url,
                                                fallback_snippet=norm["text"][:120])
                text = (page or {}).get("text") or norm["text"]
                title = (page or {}).get("title") or norm["title"]
            except Exception:
                text, title = norm["text"], norm["title"]
            if not text:
                continue
            self.seen.add(url)
            gid, _ = group_new_text(text, self.groups)
            if gid is None:
                gid = f"g_{content_fingerprint(text)}" if content_fingerprint(text) else f"g_{_nid()}"
            self.groups.append({"id": gid, "tokens": tokenize(text), "urls": [url]})
            st = source_type(url)
            cred = score_evidence(url, st, excerpt=text[:200])
            batch.append({
                "evidence_id": f"e_{_nid()}", "source_url": url,
                "title": title[:200], "text": text[:800], "excerpt": text[:200],
                "source_type": st, "domain": domain_of(url), "source_group": gid,
                "credibility": float(cred), "collected_by": f"research/{angle}",
                "appraisal": "", "theme": angle,
            })
        return batch


def _chunked(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i + n] for i in range(0, len(seq), n)]


async def _collect_batches(task_id: str, subject: str, angles: List[str],
                           batch_size: int = 3) -> AsyncIterator[Tuple[List[str], List[Dict[str, Any]]]]:
    """多轮批次采集：每批并行取该批全部角度后逐批产出（(chunk, rows)），让 collect 可分批推进度。"""
    task = _task(task_id)
    if _task_data_mode(task) == "fixture":
        rows = _fixture_evidence(subject, angles)
        yield (angles if angles else ["综合"]), rows
        return
    c = _Collector(subject)
    chunks = _chunked(list(angles), batch_size)
    if not chunks:
        chunks = [list(angles)]
    for chunk in chunks:
        results = await asyncio.gather(*(c.one(a) for a in chunk), return_exceptions=True)
        rows: List[Dict[str, Any]] = []
        for a, res in zip(chunk, results):
            if isinstance(res, Exception):
                logger.warning("角度 %s 采集失败，跳过: %s", a, res)
                continue
            rows.extend(res or [])
        yield chunk, rows


# --------------------------------------------------------------------------- #
# 阶段：sentiment（多平台舆情 + 中性聚合，绝不调用品牌型 analyze_sentiment）
# --------------------------------------------------------------------------- #
async def _platform_opinion(subject: str, kws: List[str]) -> Optional[Dict[str, Any]]:
    """多平台站内检索（site: 域名）采集目的地口碑，返回平台分布与代表样本。失败单平台降级。"""
    samples: List[Dict[str, Any]] = []
    for key, site in PLATFORM_SITES.items():
        try:
            hits = await asyncio.to_thread(
                multi_search,
                [f"{subject} 评价 site:{site}", f"{subject} 怎么样 site:{site}",
                 f"{subject} 优缺点 site:{site}"],
                num=4)
        except Exception as e:  # noqa: BLE001
            logger.warning("平台 %s 舆情检索失败，跳过: %s", key, e)
            continue
        for r in hits:
            text = (r.get("snippet") or r.get("content") or "").strip()
            url = r.get("url", "")
            title = r.get("title") or ""
            if not text or not sentiment_relevant(subject, kws, str(title), text):
                continue
            plat = classify_platform(url) or key
            samples.append({
                "text": text[:160], "platform": plat,
                "platform_label": PLATFORM_LABEL.get(plat, key),
                "url": url, "title": str(title)[:80],
            })
    if not samples:
        return None
    counts: Dict[str, int] = {}
    for s in samples:
        counts[s["platform"]] = counts.get(s["platform"], 0) + 1
    order = [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])]
    return {"samples": samples[:12], "counts": counts, "platform_count": len(order),
            "top": order[0] if order else None}


async def _sentiment(task_id: str, evidences: List[Dict[str, Any]], subject: str) -> Optional[Dict[str, Any]]:
    """双轨：中性 aggregate_sentiment 聚合 + 多平台舆情平台分布（fixture/离线不联网）。"""
    if not evidences:
        return None
    agg = aggregate_sentiment(evidences, subject)
    result = {"topic": subject, "positive": agg["positive"], "neutral": agg["neutral"],
              "negative": agg["negative"], "themes": agg["themes"], "quotes": agg["quotes"],
              "platform": None}
    if _task_data_mode(_task(task_id)) == "fixture":
        return result  # 离线检测零网络
    try:
        platform = await _platform_opinion(subject, category_keywords(subject))
        if platform:
            result["platform"] = platform
    except Exception as e:  # noqa: BLE001
        logger.warning("平台舆情增强失败，跳过: %s", e)
    return result


# --------------------------------------------------------------------------- #
# 阶段：write（LLM 并行成稿，失败模板兜底）
# --------------------------------------------------------------------------- #
def _split_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n{2,}", text) if p.strip()]
    return (paras or [text.strip()])[:5]


_FALLBACK = {
    "guide_overview": "该目的地区位与特色明确，是一个适合短程或深度游的目的地。",
    "guide_transport": "交通方式多元（高铁/自驾/大巴），市内接驳较为成熟。",
    "guide_food_stay": "餐饮与住宿配套沿中心区集中，丰俭由人，旺季需提前预订。",
    "guide_route": "建议错峰出行：把热门点排在平峰时段，主线路与备选线路搭配。",
    "guide_safe": "常规区域安全；山区/涉水等特殊场景需备好相应物资并关注官方提示。",
    "guide_budget": "全程预算可做一个中高档计划，淡旺季价差明显。",
    "guide_voice": "游客整体口碑偏正面，主要槽点是排队与旺季拥挤。",
    "assess_access": "可达性好坏取决于枢纽接驳与市内交通密度，需据证据进一步核实。",
    "assess_amenity": "食宿、医疗、应急等配套的完善度是本评估关注的重点维度。",
    "assess_price": "性价比处于中位，淡旺季分化明显。",
    "assess_safety": "常规安全可控，需关注特殊时段的承载与保障情况。",
    "assess_voice": "口碑总体偏正面，负面集中于拥堵与体验一致性。",
    "assess_conclusion": "综合维度看，该目的地适合作为目的地/宜居的候选。",
    "conclusion": "综合以上调研，结论已给出并附证据支撑。",
    "summary": "本报告综合检索与口碑证据，对目的地给出可执行结论。",
}


def _draft_section(task_id: str, subject: str, sid: str, digest: str, voice: Dict[str, Any]) -> List[str]:
    title = _SECTION_TITLES.get(sid, sid)
    persona = voice.get("persona", "")
    prompt = (
        f"{persona}\n调研目的地「{subject}」，本章「{title}」。\n\n"
        f"可用证据摘要：\n{digest}\n\n"
        f"请基于以上证据，用 2-4 个短段落撰写本章正文：给出现实判断、观点与可操作建议，"
        f"不编造网页里没有的细节。仅输出正文，勿加标题。"
    )
    try:
        text = chat([{"role": "system", "content": "你是严谨调研报告的章节撰稿人。"},
                     {"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=900, purpose=f"research/{sid}")
        text = (text or "").strip()
        if len(text) < 10:
            raise ValueError("章节过短")
        return _split_paragraphs(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("章节 %s 草稿失败，使用模板兜底: %s", sid, e)
        return [_FALLBACK.get(sid, "综合调研证据，给出本章结论。")]


async def _write_sections(task_id: str, subject: str, angles: List[str],
                          evidences: List[Dict[str, Any]], purpose: str
                          ) -> AsyncIterator[Dict[str, Any]]:
    voice = report_voice(purpose) if purpose in REPORT_PROFILES else report_voice("guide")
    sections_ids = voice.get("sections", [])
    digest = "\n".join(
        f"[{e.get('source_type')}|{e.get('domain')}] {e.get('title')}: {(e.get('text') or '')[:100]}"
        for e in evidences[:20]
    )
    tasks = {
        sid: asyncio.create_task(asyncio.to_thread(
            _draft_section, task_id, subject, sid, digest, voice))
        for sid in sections_ids
    }
    todo = list(tasks.values())
    while todo:
        done, _ = await asyncio.wait(todo, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            sid = next(s for s, tt in tasks.items() if tt is t)
            paras = await t
            title = _SECTION_TITLES.get(sid, sid)
            todo.remove(t)
            yield {
                "id": sid, "title": title, "paragraphs": paras,
                "key_takeaway": title, "highlights": [p[:40] for p in paras[:3]],
            }


# --------------------------------------------------------------------------- #
# 阶段：audit（中性质检：规则侧 evaluate_quality + 目的地中立 LLM 审阅）
# --------------------------------------------------------------------------- #
def _audit_claims(evidences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for e in evidences:
        cred = e.get("credibility") or 0
        conf = "high" if cred >= 70 else ("medium" if cred >= 45 else "low")
        out.append({
            "text": e.get("title") or (e.get("text") or "")[:60],
            "field": e.get("theme") or "综合",
            "confidence": conf,
            "evidence_ids": [e.get("evidence_id", "")],
            "source_type": e.get("source_type", ""),
        })
    return out


def _clamp_score(v: Any) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


async def _audit_review(subject: str, purpose: str, angles: List[str],
                        evidences: List[Dict[str, Any]]) -> Dict[str, Any]:
    """质检：evaluate_quality 规则侧 + 目的地中立 LLM 审阅（prompt 不出现竞品/品牌措辞）。

    产出 {verdict, scores, review, issues, suggestions}；LLM 失败/离线回退规则侧意见。
    """
    claims = _audit_claims(evidences)
    qr = None
    try:
        qr = await asyncio.to_thread(evaluate_quality,
                                     [subject], angles, claims, evidences, {})
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluate_quality 失败，仅走 LLM 审阅或规则兜底: %s", e)

    def _dim(key: str) -> int:
        return qr and _clamp_score(getattr(qr, key, None)) or 0

    fallback_scores = {"证据充分性": _dim("brand_coverage_rate"),
                       "维度完整性": _dim("dimension_coverage_rate"),
                       "结论置信度": _dim("confidence_ratio"),
                       "结构化完整度": _dim("schema_completeness")}
    fallback = {
        "verdict": "pass" if not (qr and qr.issues) else "rework",
        "scores": fallback_scores,
        "review": (f"基于规则指标：维度覆盖 {fallback_scores['维度完整性']}%、"
                   f"高置信占比 {fallback_scores['结论置信度']}%、证据充分性 {fallback_scores['证据充分性']}%。")
        if qr else "证据不足，仅给出保守审阅意见。",
        "issues": [i.get("reason", "") for i in (qr.issues if qr else [])][:6],
        "suggestions": [],
    }
    claim_lines = "\n".join(f"- [{c.get('confidence','?')}|{c.get('field','')}] {c.get('text','')}"
                            for c in claims[:18]) or "（暂无论点）"
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是目的地调研报告的质检官（L3 决策层）。对下面这份调研中间产物做严格质量审阅："
                    "逐维度打分（0-100 整数，要有真实差异），指出具体问题，给出可执行改进建议，"
                    "最后整体结论 pass（达标）或 rework（信息不足需补充）。"
                    '只输出 JSON：{"verdict":"pass|rework","scores":{"证据充分性":int,"维度完整性":int,'
                    '"结论置信度":int,"结构化完整度":int,"交叉验证":int},'
                    '"review":"一段总体评审意见",'
                    '"issues":["具体问题..."],"suggestions":["可执行改进..."]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{subject}\n调研体裁：{purpose}\n重点维度：{'、'.join(angles)}\n"
                    f"证据条目数：{len(evidences)}；去重可信度达标（source_group 唯一）由规则侧给出。"
                    f"已提炼论点：\n{claim_lines}"
                )},
            ],
            max_tokens=1600, temperature=0.3, purpose="目的地调研质检官审阅",
        )
        if isinstance(data, dict) and (data.get("scores") or data.get("review")):
            scores = {str(k): _clamp_score(v) for k, v in (data.get("scores") or {}).items()}
            return {
                "verdict": "rework" if str(data.get("verdict")) == "rework" else "pass",
                "scores": scores or fallback_scores,
                "review": str(data.get("review") or fallback["review"]),
                "issues": [str(x) for x in (data.get("issues") or []) if str(x).strip()][:8],
                "suggestions": [str(x) for x in (data.get("suggestions") or []) if str(x).strip()][:8],
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("质检 LLM 审阅失败，回退规则侧意见: %s", e)
    return fallback


# --------------------------------------------------------------------------- #
# audit（组装 + 落库）
# --------------------------------------------------------------------------- #
def _confidence(evidences: List[Dict[str, Any]], claims: List[Dict[str, Any]]) -> Any:
    if not evidences:
        return 0
    cred = [e.get("credibility") or 0 for e in evidences]
    evidence_score = sum(cred) / len(cred)
    claim_score = sum(1 for c in claims if c.get("confidence") == "high") / max(len(claims), 1)
    return round(evidence_score * 0.7 + claim_score * 100 * 0.3, 1)


def _experts_of(purpose: str) -> List[Dict[str, Any]]:
    if purpose == "research":
        return _EXPERTS_UNION
    return list(TRAVEL_EXPERTS.get(purpose, TRAVEL_EXPERTS["guide"]))


# 证据主题(angle)关键词 → 章节 id：把逐 evidence 的 claims 挂到对应章节卡片
_ANGLE_TO_SECTION = {
    "guide": {
        "交通": "guide_transport", "票务": "guide_transport", "高铁": "guide_transport",
        "餐饮": "guide_food_stay", "美食": "guide_food_stay", "住宿": "guide_food_stay",
        "路线": "guide_route", "错峰": "guide_route", "行程": "guide_route", "游玩": "guide_route",
        "安全": "guide_safe", "物资": "guide_safe", "海拔": "guide_safe",
        "预算": "guide_budget", "花费": "guide_budget", "门票": "guide_budget", "价格": "guide_budget",
        "口碑": "guide_voice", "游客": "guide_voice", "评价": "guide_voice", "演出": "guide_voice",
    },
    "assess": {
        "可达": "assess_access", "交通": "assess_access", "枢纽": "assess_access", "接驳": "assess_access",
        "配套": "assess_amenity", "食宿": "assess_amenity", "医疗": "assess_amenity", "应急": "assess_amenity",
        "性价比": "assess_price", "价格": "assess_price", "成本": "assess_price", "花费": "assess_price",
        "安全": "assess_safety", "治安": "assess_safety", "承载": "assess_safety", "灾害": "assess_safety",
        "口碑": "assess_voice", "风评": "assess_voice", "评价": "assess_voice", "舆情": "assess_voice",
    },
}


def _section_for_evidence(e: Dict[str, Any], purpose: str, section_ids: List[str]) -> str:
    text = f"{e.get('theme') or ''} {e.get('title') or ''} {e.get('excerpt') or ''}"
    table = _ANGLE_TO_SECTION.get(purpose) or _ANGLE_TO_SECTION.get("guide", {})
    for kw, sid in table.items():
        if kw in text and sid in section_ids:
            return sid
    for pref in ("guide_overview", "assess_access"):
        if pref in section_ids:
            return pref
    return section_ids[0] if section_ids else "summary"


def _attach_section_claims(sections: List[Dict[str, Any]],
                           evidences: List[Dict[str, Any]], purpose: str) -> None:
    """把逐 evidence 的 conversation 挂到命中的章节（sections[i].claims），供正文 VClaimCard 渲染。"""
    ids = [s["id"] for s in sections]
    buckets: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in ids}
    for e in evidences:
        sid = _section_for_evidence(e, purpose, ids)
        cred = e.get("credibility") or 0
        conf = "high" if cred >= 70 else ("medium" if cred >= 45 else "low")
        buckets.setdefault(sid, []).append({
            "claim_id": f"c_{_nid()}",
            "text": e.get("title") or (e.get("text") or "")[:60],
            "field": _SECTION_TITLES.get(sid, sid),
            "evidence_ids": [e.get("evidence_id", "")],
            "confidence": conf,
            "cross_validated": cred >= 70,
            "author": "travel",
            "source_type": e.get("source_type", ""),
        })
    for s in sections:
        s["claims"] = buckets.get(s["id"], [])


def _assemble_report(task: Dict[str, Any], plan: Dict[str, Any],
                     evidences: List[Dict[str, Any]], sentiment: Optional[Dict[str, Any]],
                     sections: List[Dict[str, Any]], purpose: str,
                     report_id: str, review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    subject = plan.get("subject") or "目的地"
    claims = []
    for e in evidences:
        cred = e.get("credibility") or 0
        conf = "high" if cred >= 70 else ("medium" if cred >= 45 else "low")
        claims.append({
            "evidence_id": e.get("evidence_id", ""),
            "claim": (e.get("title") or (e.get("text") or "")[:60]),
            "confidence": conf,
            "evidence_ids": [e.get("evidence_id", "")],
            "source_type": e.get("source_type", ""),
            "authors": ["travel"],
        })
    voice = report_voice(purpose) if purpose else {}
    sections = sections or []
    _attach_section_claims(sections, evidences, purpose)  # 逐证据 claims → 章节卡片
    toc = [{"id": s.get("id", sid), "title": s.get("title") or sid, "level": 1}
           for sid, s in enumerate(sections)]
    _tb = db._now()
    return {
        "id": report_id,
        "title": subject,
        "subtitle": voice.get("label", "目的地调研"),
        "query": task.get("query", ""),
        "type": "travel",
        "purpose": purpose,
        "kind": task.get("kind", "research"),
        "report_type": "research",  # 渲染适配器：research=目的地调研
        "mode": task.get("mode", "quick"),
        "brands": [],  # 目的地调研：不产出任何竞品对比
        "experts": _experts_of(purpose),
        "dispatch": [{"id": e.get("id"), "reason": (e.get("role") or e.get("tasks") or "")} for e in _experts_of(purpose)],
        "toc": toc,          # ReportPage 目录侧栏（r.toc.map 无守卫，缺失即白屏）
        "sections": sections or [],
        "charts": [],        # 目的地调研不产对比雷达图，恒定空
        "glossary": [],      # 术语表占位（r.glossary 无守卫）
        "figures": [],       # 配图占位
        "evidence": evidences,
        "claims": claims,
        "metrics": {
            "evidence_count": len(evidences),
            "unique_sources": len({e.get("domain") for e in evidences}),
            "section_count": len(sections),
        },
        "confidence": _confidence(evidences, claims),
        "sentiment": sentiment if sentiment else None,
        "plan": {"subject": subject, "angles": plan.get("angles", []), "purpose": purpose},
        "audit_review": review,
        "quality_before": review,
        "quality_after": None,
        "trace": [
            {"span_id": "infra/" + str(i), "stage": s.get("id"), "decision": s.get("title"),
             "agent_id": "research", "ts": _tb}
            for i, s in enumerate(sections[:6])
        ],
        "created_at": _tb,
        "cover_image": "",
    }


async def research_pipeline(task_id: str) -> AsyncIterator[Dict[str, Any]]:
    """目的地调研流水线主入口（async generator）。

    展示事件契约（与前端工作台/演示流同构）：
      - node_update 数组：流开头的权威 DAG 节点集（工作台按 id 渲染全阶段初始形态）
      - node_update 单节点：`{node, id, status, expert}`（node 供前端 taskStore、id 供既有断言双读）
      - thought / message(team｜audit_review) / evidence：驱动思维流/专家队/证据库三栏实时填充
    状态取值统一 working / done / idle（前端 taskStore 靠 working 判活、done 打勾）。
    """
    task = _task(task_id)
    purpose = _task_purpose(task)
    yield _ev("node_update", {"nodes": [
        {"id": nid, "label": label, "status": "idle"} for nid, label in RESEARCH_NODES
    ]})
    yield _ev("node_update", {"node": "intake", "id": "intake", "status": "working",
                              "expert": _SSE_EXPERTS[0]})
    try:
        plan = _plan_destination(task_id)
        subject = (plan.get("subject") or _task_subject(task) or "目的地")
        angles = plan.get("angles", [])
        focus = plan.get("focus")

        yield _ev("thought", _thought("plan", _SSE_EXPERTS[0],
                  f"解析任务目标：围绕目的地「{subject}」梳理「{purpose}」产出的调研范围"
                  f"（重点维度{focus or '…'}）。"))
        yield _ev("progress", {"percent": STAGE_PERCENT["intake"], "stage": "intake", "evidence_count": 0})
        yield _ev("node_update", {"node": "intake", "id": "intake", "status": "done",
                                  "expert": _SSE_EXPERTS[0]})

        # orchestrator：动态建队 + 逐成员分工叙事
        yield _ev("node_update", {"node": "orchestrator", "id": "orchestrator", "status": "working",
                                  "expert": _SSE_EXPERTS[0]})
        team_ids, team_reasons = _dispatch_destination(subject, angles, purpose)
        yield _ev("thought", _thought("dispatch", team_ids[0],
                  f"组建目的地调研小组：按「{purpose}」体裁划分工，领队统筹推进。"))
        for eid, reason in zip(team_ids[1:], team_reasons[1:]):
            yield _ev("thought", _thought("dispatch", eid, reason))
        yield _ev("message", {"id": _nid(), "kind": "team",
                              "text": f"专家队集结完毕，按「{purpose}」体裁分角色取证。",
                              "members": list(team_ids),
                              "dispatch": [{"id": i, "reason": r} for i, r in zip(team_ids, team_reasons)]})
        yield _ev("thought", _thought("dispatch", team_ids[0],
                  f"已规划 {len(angles)} 个调研角度，指派专家分线取证。"))
        yield _ev("progress", {"percent": STAGE_PERCENT["orchestrator"], "stage": "orchestrator",
                               "evidence_count": 0})
        yield _ev("node_update", {"node": "orchestrator", "id": "orchestrator", "status": "done",
                                  "expert": team_ids[0]})

        # collect：多轮批次采集（action→finding 逐批叙事 + 进度渐进）
        yield _ev("node_update", {"node": "collect", "id": "collect", "status": "working",
                                  "expert": team_ids[1] if len(team_ids) > 1 else team_ids[0]})
        chunks = _chunked(list(angles), 3) or [list(angles)]
        n_chunks = max(len(chunks), 1)
        yield _ev("thought", _thought("action", team_ids[1] if len(team_ids) > 1 else team_ids[0],
                  f"统筹 {len(angles)} 个调研角度，分 {n_chunks} 批联网取证。"))
        evidences: list = []
        done = 0
        async for chunk, batch in _collect_batches(task_id, subject, angles, batch_size=3):
            yield _ev("thought", _thought("action",
                      team_ids[1] if len(team_ids) > 1 else team_ids[0],
                      f"开始第 {min(done + 1, n_chunks)} 批：{('、'.join(chunk))[:40]}"))
            evidences.extend(batch or [])
            for _evd in batch or []:
                if isinstance(_evd, dict) and _evd.get("evidence_id"):
                    yield _ev("evidence", _evd)
            done += 1
            yield _ev("thought", _thought("finding",
                      team_ids[1] if len(team_ids) > 1 else team_ids[0],
                      f"第 {min(done, n_chunks)} 批完成，命中 {len(batch or [])} 条有效取证。"))
            frac = min(done / n_chunks, 1.0)
            yield _ev("progress",
                      {"percent": _band(17, STAGE_PERCENT["collect"], frac), "stage": "collect",
                       "evidence_count": len(evidences)})
        yield _ev("node_update", {"node": "collect", "id": "collect", "status": "done",
                                  "expert": team_ids[1] if len(team_ids) > 1 else team_ids[0]})

        # sentiment：多平台舆情 + 中性聚合叙述
        yield _ev("node_update", {"node": "sentiment", "id": "sentiment", "status": "working",
                                  "expert": team_ids[2] if len(team_ids) > 2 else team_ids[-1]})
        sentiment = await _sentiment(task_id, evidences, subject)
        if sentiment:
            _plat = sentiment.get("platform") or {}
            _top = _plat.get("top")
            _pc = _plat.get("platform_count")
            yield _ev("thought", _thought("finding",
                      team_ids[2] if len(team_ids) > 2 else team_ids[-1],
                      ("口碑聚合：正向 {pos} · 中立 {neu} · 负向 {neg}。".format(
                          pos=sentiment.get('positive', 0), neu=sentiment.get('neutral', 0),
                          neg=sentiment.get('negative', 0))
                       + (f" 多平台舆情覆盖 {_pc} 家，热度以「{_top}」居首。" if _pc else ""))))
        else:
            yield _ev("thought", _thought("finding",
                      team_ids[2] if len(team_ids) > 2 else team_ids[-1], "口碑证据不足，暂不强制聚合。"))
        yield _ev("progress", {"percent": STAGE_PERCENT["sentiment"], "stage": "sentiment",
                               "evidence_count": len(evidences)})
        yield _ev("node_update", {"node": "sentiment", "id": "sentiment", "status": "done",
                                  "expert": team_ids[2] if len(team_ids) > 2 else team_ids[-1]})

        # write：逐章并行成稿
        yield _ev("node_update", {"node": "write", "id": "write", "status": "working",
                                  "expert": team_ids[2] if len(team_ids) > 2 else team_ids[-1]})
        profile_sids = (report_voice(purpose) if purpose in REPORT_PROFILES
                        else report_voice("guide")).get("sections", [])
        n_secs = max(len(profile_sids), 1)
        sections: list = []
        async for sec in _write_sections(task_id, subject, angles, evidences, purpose):
            sections.append(sec)
            frac = min(len(sections) / n_secs, 1.0)
            yield _ev("thought", _thought("finding",
                      team_ids[2] if len(team_ids) > 2 else team_ids[-1],
                      f"章节「{sec.get('title') or sec.get('id')}」已成稿。"))
            yield _ev("progress",
                      {"percent": _band(77, STAGE_PERCENT["write"], frac), "stage": "write",
                       "evidence_count": len(evidences)})
        order = {sid: i for i, sid in enumerate(profile_sids)}
        sections.sort(key=lambda s: order.get(s.get("id"), 999))  # 并行完成，落库按 profile 顺序
        yield _ev("node_update", {"node": "write", "id": "write", "status": "done",
                                  "expert": team_ids[2] if len(team_ids) > 2 else team_ids[-1]})

        # audit：中性质检（evaluate_quality + 中立 LLM 审阅 -> audit_review）
        yield _ev("node_update", {"node": "audit", "id": "audit", "status": "working",
                                  "expert": team_ids[3] if len(team_ids) > 3 else team_ids[0]})
        yield _ev("thought", _thought("reflect",
                  team_ids[3] if len(team_ids) > 3 else team_ids[0],
                  "质检官复核证据溯源与章节口径，进入审裁。"))
        review = await _audit_review(subject, purpose, angles, evidences)
        if review:
            yield _ev("message", {"id": _nid(), "kind": "audit_review",
                                  "text": (f"质检{('通过' if review.get('verdict') == 'pass' else '需复核')}"
                                           f"（{review.get('scores') or {}}）"),
                                  "audit": review})
            yield _ev("thought", _thought("reflect",
                      team_ids[3] if len(team_ids) > 3 else team_ids[0],
                      f"审裁结论：{review.get('review') or '（无评审意见）'}"))

        report_id = f"r_{uuid.uuid4().hex[:12]}"
        report = _assemble_report(task, plan, evidences, sentiment, sections, purpose,
                                  report_id, review=review)
        db.save_report(report, task_id)
        db.mark_task_done(task_id, report_id)

        yield _ev("node_update", {"node": "audit", "id": "audit", "status": "done",
                                  "expert": team_ids[3] if len(team_ids) > 3 else team_ids[0]})
        yield _ev("progress", {"percent": STAGE_PERCENT["audit"], "stage": "audit",
                               "evidence_count": len(evidences)})
        yield {"type": "report_ready", "data": {"reportId": report_id, "report_id": report_id}}
        yield _ev("node_update", {"node": "done", "id": "done", "status": "working",
                                  "expert": team_ids[0]})
        yield _ev("thought", _thought("reflect", team_ids[0], "调研完成，报告已签发交付。"))
        yield _ev("progress", {"percent": STAGE_PERCENT["done"], "stage": "done",
                               "evidence_count": len(evidences)})
        yield _ev("node_update", {"node": "done", "id": "done", "status": "done",
                                  "expert": team_ids[0]})
        # done 须为该事件流的最后一个事件（前端以此判定成功收尾）
        yield {"type": "done", "data": {"reportId": report_id, "report_id": report_id,
                                        "purpose": purpose, "stage": "done"}}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        logger.exception("research 流水线失败: %s", msg)
        db.set_task_failed(task_id, msg)
        yield _ev("error", {"message": msg})