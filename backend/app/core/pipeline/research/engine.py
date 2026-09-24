"""Verda 深度调研编排引擎（真实大脑，对标 Deep Research）。

节点：intake → orchestrator → collect → analyze → spots(景点实体) → write → audit →(pass/rework)→ done

调研类型（research_types 注册表，单一真相源）：
- guide 游玩攻略：交通 / 住宿 / 路线 / 美食 / 预算
- assessment 调研评估：可达性 / 配套 / 安全 / 性价比

核心原则（按用户要求）：
- 真实联网：每个目的地多角度多轮真实搜索（博查 Bocha），真实抓取正文。
- 真实舆情：site:抖音/小红书/B站/知乎/携程等（平台集按类型白名单）搜真实评论与真实链接。
- 真实 LLM 分析：调研计划、专家指派、论点、舆情、报告正文、图表数据全部由 LLM 基于真实证据生成。
- 绝不 demo：没有任何写死的假数据/假评论/假图表。搜不到就如实标注"未采集到"，尽力而为不中断。
- 真实持久化：任务/报告/证据/专家工作量/trace 全部落 SQLite。
- 全程 trace + 四铁律：无证据不立论 / 交叉验证 / 返工闭环 / 可观测。

模型分配（充分利用并发额度）：核心章 glm-5.2、辅助章 glm-5.1、杂务 glm-z1-air。
写作阶段 9-11 章并行（asyncio.gather），逐章实时进度。
调研模式三档（快速/深度/专家级）按搜索量+章节数+模型分档。
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import time
import urllib.parse
import uuid
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from app.core import charts as C
from app.core import db
from app.core import trace
from app.core import audit
from app.core.audit import decide_rework, llm_quality_review
from app.core.runtime_config import get_effective_settings
from app.core.credibility import score_evidence, freshness_days, assess_viral
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core import fetcher
from app.core.fetcher import domain_of
from app.core.platforms import PLATFORMS, classify_platform
from app.core import llm
from app.core.llm import (is_temporary_unavailable,
                          LLMModelUnavailable, LLMNotConfigured, TOKEN_USAGE)
from app.core.metrics import compute_report_metrics, merge_quality_into_metrics
from app.core.models import Evidence, Envelope, make_claim
from app.core import research_types as RT
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core import scoring as SC
from app.core.schemas import _filter_eids, coerce_spot_ranking, coerce_structured
from app.core import search
from app.core.search import SearchProviderError
from app.core.sentiment import analyze_sentiment, PLATFORM_LABEL
from app.core.textquality import is_relevant_content
from app.data import expert_by_id, load_experts
from app.services import baidu as baidu_client

# M3 提取：共享纯工具与图表构建子模块（保持 engine 命名空间兼容，测试 monkeypatch 接缝与内部调用点不变）
from app.core.pipeline.research._util import (  # noqa: E402,F401
    _clamp_int, _core_name, _name_hit, _norm_spot_name, _now, _num_or_none,
    _row_dest_ok, _row_name, _sid,
)
from app.core.pipeline.research.charts_build import (  # noqa: E402,F401
    CHART_BUILDERS, ChartContext, _build_charts, _build_charts_and_gaps,
    _build_data_grid, _chart_context, _charts_for_section, _ALGO_TAG, _SENT_SECTIONS,
)
from app.core.pipeline.research._util import _DAY_PATTERNS  # noqa: E402,F401
from app.core.pipeline.research.errors import (  # noqa: E402,F401
    ClarifyAnswerRequiredError, GuideSingleDestinationError,
)
from app.core.pipeline.research import runtime  # noqa: E402  (含 _model / ContextVar)
from app.core.pipeline.research.planning import (  # noqa: E402,F401
    _DEST_PLAN_STEP,
    _DEST_REJECT_PHRASES,
    _DEST_REJECT_WORDS,
    _DEST_RETRY_PURPOSE,
    _FALLBACK_DESTINATION_MAP,
    _FALLBACK_DOMAIN_MAP,
    _MAX_DESTINATIONS,
    _MAX_DEST_NAME_LEN,
    _NO_DESTINATION,
    _ORIGIN_SKIP_WORDS,
    _discover_scope,
    _discover_scope_fallback,
    _usable_destination,
    _mentioned_in_text,
    _days_from_text,
    _checked_destinations,
    _dedupe_names,
    locked_destination,
    origin_answer,
    _destination_set,
    _orthogonal_angles,
    _plan_trace,
    _fallback_destination,
    _retry_destination,
    _plan_research,
)
from app.core.pipeline.research.dispatch import (  # noqa: E402,F401
    _FALLBACK_PICK,
    _TEAM_QUOTA,
    _TEAM_QUOTA_DESC,
    _levels_of,
    _composition_violations,
    _coerce_dispatch,
    _fallback_team,
    _record_dispatch_span,
    _dispatch_experts,
)
from app.core.pipeline.research.collect import (  # noqa: E402,F401
    _NON_OFFICIAL_HINTS,
    DAG_NODES,
    _ev,
    _source_type,
    _looks_official,
    _region_keywords,
    _sentiment_relevant,
    _collect_destination,
    _evidence_digest,
)




# ── 调研模式三档（对应需求 3）─────────────────────────────
# 只管**规模**（搜索量/篇幅/返工轮次/模型档）；章节集属语义，查 research_types.sections_for()。
#
# section_max_tokens 是「正文 + 结构字段」共享的**单章**上限，且推理模型的思考 token 也算在里面
# （实测 deepseek 未关思考时，被截断章的推理约占 3.7–4.2k）。故三档都按「正文需求 + 推理余量」
# 给足，deep 6000→8000 正是为此。8192 是服务商（api.deepseek.com）单次输出上限，再高会被拒；
# 仍被截断的章由写稿后的 _repair_missing_structure 兜住（见该函数）。
MODE_CONFIG = {
    "quick": {
        "label": "快速模式",
        "max_angles": 4, "fetch_per_destination": 6, "platform_per": 6,
        "freshness": "oneYear", "rework_rounds": 0,
        # 写作深度：段落数下限 / 每段字数 / 单章 token 预算
        "min_paragraphs": 3, "para_words": "120-200", "section_max_tokens": 4500,
        "analyze_max_tokens": 6000, "structured_max_tokens": 6000,
        # 舆情覆盖：取口碑的目的地数 / 每平台每查询取条数
        "sentiment_destinations": 2, "platform_take": 5,
        # 逐景点舆情补充采集：每景点每平台取条数（0=不采集；quick 无舆情章故为 0）
        "spot_sent_take": 0,
        # 景点榜单实体规模（属规模配置，不进 research_types）
        "spot_topn": 4,
        # 商铺路线配额：每种榜上美食给前 N 家 matched 商铺配公交路线（0=不出；quick 无商铺章）
        "shop_route_topn": 0,
        # 视角专属采集配额（rough-cliff-vole）：槽位角度条数 / 逐景点二查前 N 名。
        # quick 全 0：核查表仍出（全行待核验），但不吃搜索预算——配额优先给主链路。
        "persp_slots": 0, "persp_probe_topn": 0,
    },
    "deep": {
        "label": "深度模式",
        "max_angles": 8, "fetch_per_destination": 12, "platform_per": 8,
        "freshness": "oneYear", "rework_rounds": 1,
        "min_paragraphs": 5, "para_words": "180-280", "section_max_tokens": 8000,
        "analyze_max_tokens": 8000, "structured_max_tokens": 8000,
        "sentiment_destinations": 3, "platform_take": 8,
        "spot_sent_take": 4,
        "spot_topn": 7,
        "shop_route_topn": 2,
        # 行程路线章（D2，deep 起出）：用户未写天数时按每天 N 景点推算行程跨度
        "spot_day_pace": 4,
        # 视角槽位 2 条 + 冻结榜前 7 名逐景点二查（≤16 次/deep 拍板口径）；
        # max_angles 6→8 保证 reserve（days/origin/视角 2）不再挤占模型角度（原 4 条保住）。
        "persp_slots": 2, "persp_probe_topn": 7,
    },
    "expert": {
        "label": "专家级模式",
        "max_angles": 11, "fetch_per_destination": 16, "platform_per": 10,
        "freshness": "oneYear", "rework_rounds": 2,
        # 专家级：篇幅最长、最详尽（券商行研/MBB 深度报告级别）
        "min_paragraphs": 7, "para_words": "260-420", "section_max_tokens": 8192,
        "analyze_max_tokens": 9000, "structured_max_tokens": 9000,
        "sentiment_destinations": 4, "platform_take": 10,
        "spot_sent_take": 6,
        "spot_topn": 10,
        "shop_route_topn": 2,
        # 一页视图节奏旋钮：用户未写天数时按每天 N 景点推算行程跨度（M3a）
        "spot_day_pace": 4,
        # 同 deep 的视角配额（二查按榜前 7，不为 expert 的 10 名榜放大搜索预算）
        "persp_slots": 2, "persp_probe_topn": 7,
    },
}

# 核心章用质量最高的模型档，其余用辅助档（属「模型分配」旋钮，与 MODE_CONFIG 同类，
# 故留在编排层而非语义注册表）。覆盖两类型各自最吃分析的章节。
CORE_SECTIONS = frozenset({
    "summary", "conclusion", "contrarian",
    "spots", "route", "budget",      # 游玩攻略
    "safety", "value", "verdict",    # 调研评估
})






# ── 任务创建 / 澄清（落库）─────────────────────────────────
def create_task(query: str, mode: str = "deep", model: Optional[str] = None,
                research_type: str = DEFAULT_RESEARCH_TYPE) -> Dict[str, Any]:
    """快路径：只落库 task_id + meta，不调 LLM，毫秒级返回。

    澄清问卷改为 ClarifyPage 挂载后通过 SSE 懒生成（见 async generate_clarify），
    从而把 LLM 推理移出 HTTP 关键路径——这是根治「提交后等好久」的架构根因。
    """
    task_id = _sid("t")
    # 用户指定的分析模型仅在非空且非 'Auto' 时记录覆盖（跟随 _mode/_type 写入 task meta，
    # 经 submit_clarify 透传进 clarifications，run_pipeline 双源读取）。
    meta: Dict[str, Any] = {"_mode": mode, "_type": RT.type_key(research_type)}
    if model and model != "Auto":
        meta["_model_override"] = model
    db.save_task(task_id, query, meta)
    return {"taskId": task_id, "researchType": meta["_type"]}






def _answer_destinations(answers: Dict[str, Any]) -> List[str]:
    raw = (answers or {}).get("destinations") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in raw if str(x).strip()]


def submit_clarify(task_id: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    # 结构性闸门先于落库：guide 多目的地直接拒，坏问卷不会被 runner 带进管线
    if _task_research_type(task_id) == "guide" and len(_answer_destinations(answers)) > 1:
        raise GuideSingleDestinationError(
            "游玩攻略报告目前仅支持单个目的地（地图、逐景点路线与评分配额都以单目的地为前提），"
            "请只保留一个城市/景区后重新提交。")
    # 条件题必答闸门：show_if 触发且缺答 → 结构化拒（判据源在注册表，不在这里散写）
    rtype = _task_research_type(task_id)
    missing = RT.missing_conditional_answers(rtype, answers or {})
    if missing:
        raise ClarifyAnswerRequiredError(
            f"请先回答已展开的追问（{'、'.join(missing)}）再提交——这些答案会作为报告的硬约束。")
    # 保留已存的 _mode / _type / _model_override（HomePage 选的类型与模型跟随澄清透传）
    task = db.get_task(task_id) or {}
    prev = task.get("clarifications", {}) or {}
    merged = {**answers}
    for key in ("_mode", "_type", "_model_override"):
        if key in prev and key not in merged:
            merged[key] = prev[key]
    db.update_task_clarify(task_id, merged)
    return {"ok": True}


# ── 澄清问卷异步懒生成（SSE 推送；P0 修复：把 LLM 移出 HTTP 关键路径）──
# 并发去重：同 task_id 仅生成一个，其余协程复用同一在途 future（P1#7）。
_GEN_INFLIGHT: Dict[str, "asyncio.Future"] = {}


def _fallback_clarify_questions(query: str, research_type: str = DEFAULT_RESEARCH_TYPE
                                ) -> List[Dict[str, Any]]:
    """LLM 生成失败时的降级静态问卷（不含目的地发现，但流程可继续，P1#5）。

    题目集来自类型注册表（spec["clarify"]）——本函数只做渲染，不写类型分支。
    """
    return [dict(q) for q in RT.type_spec(research_type)["clarify"]]


def _baseline_questions(query: str = "", research_type: str = DEFAULT_RESEARCH_TYPE
                        ) -> List[Dict[str, Any]]:
    """即时基础题（不依赖 LLM），目的地发现完成前即可作答（P0-① 修复核心）。"""
    return _fallback_clarify_questions(query, research_type)


def _build_enhanced_questions(
    scope: Dict[str, Any], baseline: List[Dict[str, Any]],
    budget: Optional[Dict[str, Any]] = None,
    research_type: str = DEFAULT_RESEARCH_TYPE,
    query: str = "",
) -> List[Dict[str, Any]]:
    """把领域识别 + 目的地发现结果作为增强题追加到基础题末尾（P0-②：增量而非阻塞）。

    budget 是随问卷下发的**工作量事实量**（见 _budget_facts），供目的地题旁渲染温和提示；
    缺失时该题不带 workload 键（旧前端/旧后端互相兼容）。
    guide 类型的目的地题是**单选**（单目的地结构性约束的预防位；旧缓存问卷仍可能是
    multi，由 submit_clarify 的后端闸门兜底）。
    guide 且需求原文已唯一点名目的地（`locked_destination`）→ **不出**目的地题：
    用户已说清的事不再追问；计划层同一判据保证两处不会一个锁定、一个反问。
    增强题同样按注册表挂 `consumer` 键（题-消费契约真相源，见 RT.CLARIFY_CONSUMERS）。
    """
    subject = scope.get("subject") or ""
    domain = scope.get("domain") or ""
    candidates = scope.get("candidates") or scope.get("competitors") or []
    rtype = RT.type_key(research_type)
    locked = locked_destination(query, candidates) if rtype == "guide" else ""
    if subject:
        txt = f"我们识别到你要调研的是「{subject}」"
        txt += f"，所属领域：{domain}。" if domain else "。"
        txt += "是否准确？"
    elif domain:
        txt = f"我们识别到你要调研的主题属于「{domain}」领域，是否准确？"
    else:
        txt = "请确认我们理解的调研对象是否准确？"
    if locked:
        txt += f"需求里已点名「{locked}」，本次攻略将围绕它展开。"
    extra: List[Dict[str, Any]] = [{
        "id": "scope",
        "question": txt,
        "type": "single",
        "options": ["准确，继续", "大致准确，下面补充", "不准确，我在下方说明"],
        "hint": "若不准确，请在最后一题补充说明真实的调研对象与领域。",
        "consumer": RT.consumer_of(rtype, "scope")["consumer"],
    }]
    if candidates and not locked:
        single = rtype == "guide"
        dest_q: Dict[str, Any] = {
            "id": "destinations",
            "question": (f"为「{subject or '该主题'}」自动发现了以下候选目的地，请选择重点调研的对象（攻略仅支持单个目的地）："
                         if single else
                         f"为「{subject or '该主题'}」自动发现了以下候选目的地，请勾选你希望重点调研的对象（可多选）："),
            "type": "single" if single else "multi",
            "options": candidates[:12],
            "hint": ("选定一个城市/景区后我们会把它调研透；如有遗漏可在最后一题补充。"
                      if single else
                      "勾选后我们会确保每个目的地都被充分调研；如有遗漏可在最后一题补充。"),
            "consumer": RT.consumer_of(rtype, "destinations")["consumer"],
        }
        if budget:
            dest_q["workload"] = dict(budget)
        extra.append(dest_q)
    return list(baseline) + extra


async def _discover_and_build(
    task_id: str, query: str, baseline: List[Dict[str, Any]], timeout_s: float
) -> Dict[str, Any]:
    """目的地发现 + 增强题构建（带缓存命中 / 超时 / 异常兜底）。

    返回可直接作为 SSE clarify_update 载荷的字典：
    {"questions": [...], "destinations_fallback": bool, "complete": True}。
    - 缓存命中（仅成功发现才缓存）→ 零 LLM 调用。
    - 超时 / 异常 → 正则兜底（destinations_fallback=True），绝不卡死。
    - 仅完整问卷落库（complete=1），绝不落 partial（P0-③ 重连完整性）。
    """
    qhash = db._query_hash(query)
    cached = db.get_discovery_cache(qhash)
    if cached:
        scope: Dict[str, Any] = cached
        fallback = False
    else:
        try:
            scope = await asyncio.wait_for(
                asyncio.to_thread(_discover_scope, query), timeout=timeout_s
            )
        except Exception:
            # 超时或 LLM 抛错 → 正则兜底（destinations_fallback），绝不卡死。
            # 不捕获 CancelledError（BaseException），保证外部取消能正常透传。
            scope = _discover_scope_fallback(query)
        fallback = bool(scope.get("fallback", False))
        # 仅缓存真实（非兜底）发现结果，避免把兜底噪声写进缓存
        if not fallback and (scope.get("candidates") or scope.get("domain")):
            ttl = int(get_effective_settings().get("discovery_cache_ttl_d", 7) or 7)
            db.save_discovery_cache(qhash, scope, ttl_days=ttl)
    rtype = _task_research_type(task_id)
    enhanced = _build_enhanced_questions(scope, baseline, _budget_facts(_task_mode(task_id)),
                                         research_type=rtype, query=query)
    locked = locked_destination(query, scope.get("candidates") or scope.get("competitors") or [])
    if rtype == "guide" and locked and (scope.get("candidates") or scope.get("competitors")):
        cands = "、".join(str(c) for c in (scope.get("candidates") or [])[:12]) or "无"
        _plan_trace(task_id, f"目的地已锁定为「{locked}」：需求原文唯一点名，问卷不再追问目的地。",
                    f"需求原文：{query}\n发现候选：{cands}")
    db.save_clarify_questions(task_id, enhanced, complete=True)
    return {"questions": enhanced, "destinations_fallback": fallback, "complete": True}


def _task_research_type(task_id: str) -> str:
    """从任务 meta 读调研类型（澄清问卷与发现都按类型渲染；缺失一律回落默认）。"""
    task = db.get_task(task_id) or {}
    clar = task.get("clarifications", {}) or {}
    return RT.type_key(task.get("_type") or clar.get("_type") or DEFAULT_RESEARCH_TYPE)


def _task_mode(task_id: str) -> str:
    """从任务 meta 读用户选定的规模档位（与 run_pipeline 同源；缺失一律回落 deep）。"""
    task = db.get_task(task_id) or {}
    clar = task.get("clarifications", {}) or {}
    mode = str(clar.get("_mode") or task.get("_mode") or "deep")
    return mode if mode in MODE_CONFIG else "deep"


def _budget_facts(mode: str) -> Dict[str, Any]:
    """下发给澄清问卷的工作量事实量：档位名 + 每目的地的角度数与取证数。

    刻意只给**事实**不给秒数——耗时受网络与服务商排队影响，编造数字比不写更易误导。
    """
    cfg = MODE_CONFIG[mode]
    return {
        "mode": mode,
        "mode_label": cfg["label"],
        "max_angles": cfg["max_angles"],
        "fetch_per_destination": cfg["fetch_per_destination"],
    }


async def generate_clarify(task_id: str, query: str) -> AsyncIterator[Dict[str, Any]]:
    """懒生成澄清问卷，SSE 逐事件推送（分阶段：基础题即时 → 目的地发现增量）。

    - asyncio.to_thread 把同步阻塞的 _discover_scope（含 LLM HTTP）移出事件循环。
    - 并发重入防护（P1#7）：首个协程把完整载荷塞进 _GEN_INFLIGHT future，其余协程
      await 同一 future 复用结果，绝不重复调 LLM。
    - 阶段 0/1 即时（无 LLM）：先推基础题（partial），目的地发现完再推 clarify_update。
    - 生成失败降级为正则兜底（destinations_fallback），流程不卡死（P1#5）。
    """
    # 重连/刷新：完整问卷已落库 → 直接推送，避免重复 LLM 调用
    existing, complete = db.get_clarify_questions(task_id)
    if existing and complete:
        yield {"type": "clarify_ready", "data": existing}
        return

    research_type = _task_research_type(task_id)
    loop = asyncio.get_running_loop()
    inflight = _GEN_INFLIGHT.get(task_id)
    if inflight is not None:
        # 并发重入：复用在途生成结果，不重复调 LLM
        payload = await inflight
        yield {"type": "clarify_ready", "data": payload}
        return

    fut: "asyncio.Future" = loop.create_future()
    _GEN_INFLIGHT[task_id] = fut  # 原子写入（其后无 await，其它协程必见）
    try:
        # 阶段 0：理解阶段（即时，无阻塞）
        yield {"type": "clarify_stage", "data": {"stage": "understanding", "message": "正在理解你的需求…"}}
        # 阶段 1：基础题即时渲染（P0-① 修复：不等目的地发现）
        baseline = _baseline_questions(query, research_type)
        yield {"type": "clarify_ready", "data": {"questions": baseline, "partial": True}}
        # 阶段 2：目的地发现（带超时 + 缓存 + 异常兜底，P0-②/③）
        yield {"type": "clarify_stage", "data": {"stage": "discovering", "message": "正在发现候选目的地…"}}
        timeout_s = float(get_effective_settings().get("clarify_discover_timeout_s", 4) or 4)
        payload = await _discover_and_build(task_id, query, baseline, timeout_s)
        if not fut.done():
            fut.set_result(payload)
        yield {"type": "clarify_update", "data": payload}
    except Exception as e:  # noqa: BLE001
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _GEN_INFLIGHT.pop(task_id, None)


def _refine_scope_line(destinations: List[str]) -> str:
    """精修提示的目的地约束：精修路径不经过 _analyze，拿不到行白名单，只能在提示层守。"""
    names = "、".join(str(d) for d in (destinations or []) if str(d).strip())
    return (f"本报告只调研 {names}，不得引入其它城市或目的地作为对比对象或举例。" if names else "")


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


def _brief_facts_block(sections: List[Dict[str, Any]]) -> str:
    """把报告结构化榜单压成少量数字事实行，喂给 brief 的 key_data。

    只读 sections[].structured（[{type,data}] 复数形状；旧报告为 {type,data} 单块），
    旧报告/assessment 无这些键时自然返回空串——不造假数字，也不影响旧精炼。"""
    by_type: Dict[str, Any] = {}
    for s in sections:
        st = s.get("structured")
        blocks = st if isinstance(st, list) else [st] if isinstance(st, dict) else []
        for b in blocks:
            if isinstance(b, dict) and b.get("data"):
                by_type.setdefault(str(b.get("type")), b["data"])

    def _rows(key: str, cap: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for g in by_type.get(key) or []:
            if isinstance(g, dict):
                rows.extend(x for x in (g.get("items") or g.get("areas") or [])
                            if isinstance(x, dict))
        return rows[:cap]

    lines: List[str] = []
    for r in _rows("spot_ranking", 5):
        bits = [f"景点「{r.get('name', '')}」综合分 {r.get('score', '—')}"]
        if r.get("ticket"):
            bits.append(f"门票 {r['ticket']}")
        if r.get("stay_minutes"):
            bits.append(f"建议停留 {int(r['stay_minutes'])} 分钟")
        lines.append("；".join(bits))
    for r in _rows("food_ranking", 4):
        if r.get("price_range"):
            lines.append(f"美食「{r.get('name', '')}」人均 {r['price_range']}")
    for r in _rows("shop_list", 5):
        if r.get("price_per_person"):
            lines.append(f"商铺「{r.get('name', '')}」（{r.get('food', '')}）人均参考价 {r['price_per_person']} 元")
    for r in _rows("cost_breakdown", 6):
        if r.get("amount"):
            lines.append(f"预算·{r.get('category', '')} {r['amount']}{r.get('unit', '元/人')}")
    for r in _rows("stay_options", 4):
        if r.get("price_range"):
            who = f"，适合 {r['for_whom']}" if r.get("for_whom") else ""
            lines.append(f"住宿「{r.get('area', '')}」{r['price_range']}{who}")
    # 视角铁律前 3 条进执行摘要（rough-cliff-vole：铁律是问卷硬约束驱动的可执行行）
    for r in _rows("persp_rules", 3):
        if r.get("text"):
            lines.append(f"视角铁律：{r['text']}")
    return "\n".join(lines)


def generate_brief(report_id: str) -> Optional[Dict[str, Any]]:
    """把报告压缩为一页纸精炼（派生数据）并落库 reports.data.brief。

    幂等：data.brief 已存在直接返回，不重复调 LLM（前端「AI 生成一页纸精炼」）。
    失败：普通异常记录 data.brief_failed_at（供前端 ≥30s 冷却防重）后返回 None；
         LLMNotConfigured 冒泡由 main 端点转 503。
    并发：整段持 db.locked()（RLock 可重入，save_report 内部再取锁不冲突），
         写回前重读校验 brief 仍为空才落盘，杜绝双写与"失效清除后被旧内容回填"。
    """
    with db.locked():
        rep = db.get_report(report_id)
        if not rep:
            return None
        if rep.get("brief"):
            return rep["brief"]

        sections = rep.get("sections", []) or []
        sum_sec = next((s for s in sections if s.get("id") == "summary"), None)
        takeaways = [s.get("key_takeaway") for s in sections if s.get("key_takeaway")]
        summary_block = ""
        if sum_sec:
            lines = [f"- {h}" for h in (sum_sec.get("highlights") or [])[:5]]
            summary_block = (
                f"执行摘要核心判断：{sum_sec.get('key_takeaway', '')}\n"
                f"执行摘要亮点：\n" + "\n".join(lines)
            )
        metrics = (rep.get("metrics") or {}).get("efficiency") or {}
        metric_block = json.dumps({
            "efficiency_multiple": metrics.get("efficiency_multiple"),
            "elapsed_minutes": metrics.get("elapsed_minutes"),
            "minutes_saved": metrics.get("minutes_saved"),
            "tokens_used": metrics.get("tokens_used"),
        }, ensure_ascii=False)
        senti_block = json.dumps((rep.get("sentiment") or {}).get("overall", {}), ensure_ascii=False)
        facts_block = _brief_facts_block(sections)

        def _call_brief_llm() -> Dict[str, Any]:
            data = llm.chat_json(
                [
                    {"role": "system", "content": (
                        "你是资深旅游调研汇报官。请把整份报告压缩成可直接用于汇报的一页纸精炼。"
                        "输出 JSON：{\"summary\":\"一句话概括(≤40字)\",\"judgments\":[\"全局核心判断(3-5条，结论先行)\"],"
                        "\"key_data\":[\"关键数据(3-5条，带数字)\"],\"actions\":[\"行动建议(3-5条)\"]}。只输出 JSON。"
                    )},
                    {"role": "user", "content": (
                        f"报告标题：{rep.get('title', '')}\n副标题：{rep.get('subtitle', '')}\n"
                        f"目的地：{rep.get('destinations') or []}\n证据数：{len(rep.get('evidence', []))} "
                        f"结论数：{len(rep.get('claims', []))}\n\n{summary_block}\n\n各章核心判断：\n"
                        + "\n".join(f"- {t}" for t in takeaways[:12])
                        + f"\n\n效能指标：{metric_block}\n舆情概览：{senti_block}"
                        + (f"\n\n结构化数据事实（key_data 优先引用其中的真实数字）：\n{facts_block}"
                           if facts_block else "")
                    )},
                ],
                max_tokens=2400, temperature=0.3,
                model=runtime._model("core"), purpose=f"生成一页纸精炼：{report_id}",
            )
            if not isinstance(data, dict):
                raise RuntimeError("LLM 未返回结构化精炼")
            brief = {
                "summary": str(data.get("summary", "")).strip(),
                "judgments": [str(j).strip() for j in data.get("judgments", []) if str(j).strip()],
                "key_data": [str(k).strip() for k in data.get("key_data", []) if str(k).strip()],
                "actions": [str(a).strip() for a in data.get("actions", []) if str(a).strip()],
            }
            if not brief["summary"] and not brief["judgments"]:
                raise RuntimeError("精炼结果为空")
            return brief

        try:
            brief = _call_brief_llm()
        except LLMNotConfigured:
            raise
        except Exception as e:  # noqa: BLE001
            # 可观测性：失败落 brief_failed_at 供前端冷却防重，同时留日志便于定位 LLM 层原因
            import logging
            logging.getLogger(__name__).warning("generate_brief 失败 report=%s: %s", report_id, e)
            cur = db.get_report(report_id)
            if cur and not cur.get("brief"):
                cur["brief_failed_at"] = _now()
                db.save_report(cur, task_id="")
            return None

        # 写回前重读校验：仍在锁内，若并发已生成则直接复用，避免覆盖
        cur = db.get_report(report_id)
        if cur.get("brief"):
            return cur["brief"]
        cur["brief"] = brief
        cur.pop("brief_failed_at", None)
        db.save_report(cur, task_id="")
        return brief


def refine_section(report_id: str, section_id: str, annotations: List[str]) -> Dict[str, Any]:
    """按用户批注对指定章节进行二次深化调研（对应需求 6）。

    基于报告已有证据 + 用户批注，让 LLM 把该章节写得更厚、更有针对性。
    """
    rep = db.get_report(report_id)
    if not rep:
        return {"ok": False, "message": "report not found"}
    sections = rep.get("sections", [])
    target = next((s for s in sections if s.get("id") == section_id), None)
    if not target:
        return {"ok": False, "message": "section not found"}

    query = rep.get("query", "")
    destinations = rep.get("destinations") or rep.get("brands") or []
    evidence = rep.get("evidence", [])
    digest_lines = []
    for e in evidence[:24]:
        digest_lines.append(f"[{e.get('evidence_id')}|{e.get('domain','')}] {e.get('title','')}：{e.get('excerpt','')}")
    digest = "\n".join(digest_lines)
    note_text = "\n".join(f"- {a}" for a in annotations if a)
    system_prompt = (
        "你是资深旅游调研分析师。用户对报告某章节提出了批注/进一步调研诉求，"
        "请基于已有证据与批注，把该章节重写得更深、更厚、更有针对性——补充论证、数据、对比与独立判断。"
        + _refine_scope_line(destinations) +
        '输出 JSON：{"paragraphs":["段落"],"key_takeaway":"核心判断","highlights":["亮点"]}。只输出 JSON。'
    )
    user_digest = (
        f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n"
        f"用户批注/诉求：\n{note_text}\n\n现有章节内容：\n"
        + "\n".join(target.get("paragraphs", []))
        + f"\n\n可用证据：\n{digest}"
    )
    _rewrite_section(
        target,
        {"digest": user_digest, "absorbed_evidence_ids": [e.get("evidence_id") for e in evidence[:24]]},
        system_prompt,
    )
    if target.get("refined"):
        db.save_report(rep, task_id="")
        return {"ok": True, "section": target}
    return {"ok": False, "message": "refine failed"}


def create_refine_task(report_id: str, evidence_ids: Optional[List[str]] = None,
                       min_cred: float = 70) -> Dict[str, Any]:
    """创建「基于新证据精修报告」的后台任务（kind='refine'）。

    复用 runner 的「任务即一等实体」机制：前端用返回的 taskId 订阅
    GET /api/tasks/{taskId}/stream 即可获得进度/取消/重连。
    """
    tid = _sid("rt")
    db.save_task(
        tid,
        query=report_id,
        clarifications={
            "report_id": report_id,
            "evidence_ids": evidence_ids,
            "min_cred": min_cred,
        },
        kind="refine",
    )
    return {"taskId": tid}


def create_brief_task(report_id: str) -> Dict[str, Any]:
    """创建「生成一页纸精炼」的后台任务（kind='brief'，G7）。

    复用 runner 的「任务即一等实体」机制：前端拿返回 taskId 订阅
    GET /api/tasks/{taskId}/stream，消解旧同步端点的 30s 冷却 hack。
    """
    tid = _sid("bt")
    db.save_task(
        tid,
        query=report_id,
        clarifications={"report_id": report_id},
        kind="brief",
    )
    return {"taskId": tid}


async def brief_report_pipeline(task_id: str) -> "AsyncIterator[Dict[str, Any]]":
    """异步生成器：生成/复用报告的一页纸精炼。

    幂等：data.brief 已存在 → progress(100) + done 快路径，不再调 LLM；
    失败 → DB failed 终态 + error 事件（前端显式展示、可随时重试）。
    阻塞 LLM 调用经 asyncio.to_thread 包裹，不冻结事件循环（与 refine 同策略）。
    """
    full = db.get_task_full(task_id) or {}
    clar = full.get("clarifications", {}) or {}
    report_id = clar.get("report_id") or full.get("query")
    try:
        rep = db.get_report(report_id)
        if not rep:
            msg = "报告不存在或未就绪"
            db.set_task_failed(task_id, msg)
            yield _ev("error", {"message": msg})
            return
        if rep.get("brief"):
            yield _ev("progress", {"percent": 100, "stage": "brief", "evidence_count": 0})
            yield _ev("done", {"reportId": report_id})
            return
        yield _ev("progress", {"percent": 10, "stage": "brief", "evidence_count": 0})
        brief = await asyncio.to_thread(generate_brief, report_id)
        if brief:
            yield _ev("done", {"reportId": report_id})
        else:
            msg = "生成失败，请稍后重试"
            db.set_task_failed(task_id, msg)
            yield _ev("error", {"message": msg})
    except LLMNotConfigured as e:
        msg = f"LLM 未配置：{e}"
        db.set_task_failed(task_id, msg)
        yield _ev("error", {"message": msg})
    except Exception as e:  # noqa: BLE001
        db.set_task_failed(task_id, str(e))
        yield _ev("error", {"message": str(e)})


async def refine_report_pipeline(task_id: str) -> "AsyncIterator[Dict[str, Any]]":
    """异步生成器：基于新补充的高可信度证据，逐章重写报告正文。

    与 run_pipeline 同一事件协议（progress / done / error）；由 runner._drive 驱动。
    阻塞的 LLM 调用经 asyncio.to_thread 包裹，不冻结事件循环（P1-2）。
    """
    task = db.get_task(task_id) or {}
    clar = task.get("clarifications", {}) or {}
    report_id = clar.get("report_id") or task.get("query")
    evidence_ids = clar.get("evidence_ids") or None
    min_cred = clar.get("min_cred", 70)
    rep = db.get_report(report_id)
    if not rep:
        yield _ev("error", {"message": "report not found"})
        return

    evs = rep.get("evidence", []) or []
    new_evs = [
        e for e in evs
        if (e.get("credibility") or 0) >= min_cred
        and (not evidence_ids or e.get("evidence_id") in set(evidence_ids))
    ]
    if not new_evs:
        yield _ev("error", {"message": "没有可吸收的高可信度证据"})
        return

    digest_lines = []
    absorbed = []
    for e in new_evs:
        absorbed.append(e.get("evidence_id"))
        digest_lines.append(
            f"[{e.get('evidence_id')}|{e.get('domain','')}] {e.get('title','')}：{e.get('excerpt','')}"
        )
    digest = "\n".join(digest_lines)[:3000]
    system_prompt = (
        "你是资深旅游调研分析师。报告已归属了一批新的高可信度证据，请基于这些证据把章节重写得更深、更厚、"
        "更有针对性——补充论证、数据、对比与独立判断。"
        + _refine_scope_line(rep.get("destinations") or []) +
        '输出 JSON：{"paragraphs":["段落"],"key_takeaway":"核心判断","highlights":["亮点"]}。只输出 JSON。'
    )
    sections = rep.get("sections", []) or []
    total = len(sections)
    for i, s in enumerate(sections, 1):
        yield _ev("progress", {
            "percent": round(i / total * 100) if total else 100,
            "stage": f"精修第{i}/{total}章",
            "evidence_count": 0,
        })
        await asyncio.to_thread(
            _rewrite_section,
            s,
            {"digest": digest, "absorbed_evidence_ids": absorbed},
            system_prompt,
        )
    db.save_report(rep, task_id="")
    # 派生数据失效钩子：正文已改写，简报/一页纸精炼随即作废（失效即淘汰）
    db.invalidate_report_brief(report_id)
    yield _ev("done", {"reportId": report_id})







































































# ── 主流程 ───────────────────────────────────────────────
async def research_pipeline(task_id: str, sub_id: str = "") -> AsyncIterator[Dict[str, Any]]:
    task = db.get_task(task_id) or {"query": "旅游调研", "clarifications": {}}
    clar = task.get("clarifications", {}) or {}
    # 双源读取用户指定的分析模型（task meta 顶层 或 clarifications，与 _mode 同处理），
    # 消除「跳过澄清直接跑」时 override 丢失的脆弱点。set 覆盖式写入：asyncio 每个
    # pipeline 协程有独立 context，且每次 set 覆盖旧值，不同任务之间无串扰。
    override = task.get("_model_override") or clar.get("_model_override") or ""
    runtime._pipeline_model_override.set(override)
    query = task.get("query", "旅游调研")
    mode = clar.get("_mode", "deep")
    if mode not in MODE_CONFIG:
        mode = "deep"
    cfg = MODE_CONFIG[mode]
    # 调研类型（guide 游玩攻略 / assessment 调研评估）：章节集/图表/结构化键/舆情平台全部查表
    rtype = RT.type_key(task.get("_type") or clar.get("_type") or DEFAULT_RESEARCH_TYPE)
    spec = RT.type_spec(rtype)
    # 调研视角（亲子/情侣/独行/摄影/长辈 或 自住/投资/求学/养老/数字游民）→ 追加专属板块
    persp_qid, persp_key = spec["perspective_source"]
    perspective = str(clar.get(persp_key) or clar.get(persp_qid) or "")
    section_ids = RT.sections_for(rtype, mode, perspective)
    # 视角专属链路总闸（rough-cliff-vole）：sid 为空 = 通用视角，采集/装配/约束全跳过
    persp_sid = RT.perspective_section(rtype, perspective)
    persp_constraints_line = ""
    _hp = RT.perspective_spec(persp_sid).get("hard_constraints") or ()
    _hv = "；".join(f"{q}={clar[q]}" for q in _hp if str(clar.get(q) or "").strip())
    if _hv:
        persp_constraints_line = _hv

    t_start = time.monotonic()
    token_start = TOKEN_USAGE["total"]
    progress = {"percent": 0, "evidence_count": 0, "token_used": 0, "stage": "intake"}

    def prog(percent: int, stage: str, ev_count: int) -> Dict[str, Any]:
        progress.update({
            "percent": percent, "stage": stage, "evidence_count": ev_count,
            "token_used": TOKEN_USAGE["total"] - token_start,
        })
        return dict(progress)

    def _drain_trace():
        """取出新 trace span 包装为 SSE 事件。"""
        return [_ev("trace", sp) for sp in trace.drain(task_id)]

    yield _ev("node_update", {"nodes": [{**n, "status": "idle"} for n in DAG_NODES]})
    yield _ev("message", {"id": _sid("m"), "kind": "mode",
                          "text": f"调研类型：{spec['label']} · {cfg['label']}",
                          "mode": mode, "research_type": rtype})
    await asyncio.sleep(0.15)

    # ---- 1. intake：LLM 拆解调研计划 ----
    yield _ev("node_update", {"node": "intake", "status": "working", "expert": "L3-001"})
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": "L3-001",
                          "text": f"收到调研需求：{query}（{spec['label']} · {cfg['label']}）。正在拆解目的地与调研维度……", "ts": _now()})
    trace.set_context(task_id, "L3-001", "intake", "拆解调研计划")
    plan = await asyncio.to_thread(_plan_research, query, clar, cfg["max_angles"], rtype, task_id,
                                   persp_slots=cfg["persp_slots"])
    for e in _drain_trace():
        yield e
    destinations = plan["destinations"]
    focus = plan["focus"]
    angles = plan["angles"]
    region = plan.get("region", "")
    if plan.get("degraded"):
        # 运行中温和横幅（非 error）：降级事实的持久来源是上面的 trace span，这里只解决醒目度。
        yield _ev("message", {"id": _sid("m"), "kind": "plan_fallback", "expert": "L3-001",
                              "text": f"目的地由自动识别得出（{'、'.join(destinations)}），"
                                      "建议核对后再采纳；如不符请在需求里写明城市名后重跑。"})
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": "L3-001",
                          "text": f"锁定目的地：{'、'.join(destinations)}；重点维度：{'、'.join(focus)}；"
                                  f"将从「{'、'.join(angles)}」等角度展开多轮联网检索。", "ts": _now()})
    yield _ev("progress", prog(7, "intake", 0))
    yield _ev("node_update", {"node": "intake", "status": "done"})

    # ---- 2. orchestrator：LLM 动态指派专家 ----
    yield _ev("node_update", {"node": "orchestrator", "status": "working", "expert": "L3-001"})
    trace.set_context(task_id, "L3-001", "orchestrator", "指派专家团队")
    dispatch = await asyncio.to_thread(_dispatch_experts, query, destinations, focus)
    for e in _drain_trace():
        yield e
    member_ids = [m["id"] for m in dispatch["members"]]
    # 降级可见：兜底队与真组队过去在前端长得一模一样（「48 位专家永远那几个」的
    # 直接观感来源）。标记只走运行流 thought/SSE，不进报告 payload（同 plan_fallback
    # 与 brisk L2 的既有约定）。
    if dispatch["degraded"]:
        yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": "L3-001",
                              "text": f"本次专家团队为规则兜底组队，未经 LLM 动态指派"
                                      f"（{dispatch['degraded_reason']}）——"
                                      f"专长匹配度低于正常轮次，建议核对模型配置后重跑。",
                              "ts": _now()})
    lead_expert = expert_by_id(dispatch["lead"]) or {}
    yield _ev("thought", {"id": _sid("th"), "kind": "dispatch", "expert": "L3-001",
                          "text": f"由 {lead_expert.get('name','决策层')} 领衔组建 {len(member_ids)} 人专家队，"
                                  f"按调研主题精准匹配专长。", "ts": _now()})
    for m in dispatch["members"]:
        ex = expert_by_id(m["id"]) or {}
        yield _ev("thought", {"id": _sid("th"), "kind": "dispatch", "expert": m["id"],
                              "text": f"指派 {ex.get('name', m['id'])}（{ex.get('role_title','')}）：{m['reason']}",
                              "ts": _now()})
        await asyncio.sleep(0.04)
    # 结构化消息：编排→采集 PRODUCE 信封
    env_collect = Envelope(msg_id="env_" + uuid.uuid4().hex[:8], sender="L3-001",
                           receiver="collect", task_type="PRODUCE",
                           payload={"destinations": destinations, "angles": angles})
    yield _ev("message", {"id": _sid("m"), "kind": "team", "expert": "L3-001",
                          "members": member_ids, "text": "专家队已就位，开始深度采集。",
                          "dispatch": dispatch["members"],
                          "degraded": dispatch["degraded"] or "",
                          "repairs": dispatch.get("repairs") or [],
                          "envelope": {"sender": env_collect.sender, "receiver": env_collect.receiver,
                                       "task_type": env_collect.task_type,
                                       "payload": env_collect.payload}})
    yield _ev("progress", prog(14, "orchestrator", 0))
    yield _ev("node_update", {"node": "orchestrator", "status": "done"})

    collector = next((m["id"] for m in dispatch["members"] if m["id"].startswith("L1")), "L1-025")
    sentiment_expert = next((m["id"] for m in dispatch["members"]
                             if (expert_by_id(m["id"]) or {}).get("group") == "function"), collector)

    # ---- 3. collect：深度多角度真实搜索 + 抓取 ----
    yield _ev("node_update", {"node": "collect", "status": "working", "expert": collector})
    evidences: List[Evidence] = []
    images: List[Dict[str, str]] = []
    ev_by_collector: Counter = Counter()
    collect_notes: List[str] = []
    seen_urls: set = set()
    # v2.1 客观性：信源组池（内容级去重唯一生产点）与客观性统计
    groups: List[Dict] = []  # [{"id","fingerprint","urls":[...]}]，主线程独占维护
    stats = {"dup_skipped": 0, "viral_count": 0, "viral_checked": 0}

    def _to_int(v) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    # 服务商级终态错误（欠费/Key 无效）：一条即止，不再烧剩余查询；零证据时硬失败
    provider_err: Optional[str] = None

    for destination in destinations:
        yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": collector,
                              "text": f"开始深度检索「{destination}」：{'、'.join(angles)}。", "ts": _now()})
        trace.set_context(task_id, collector, "collect", f"采集目的地「{destination}」证据")
        try:
            res = await asyncio.to_thread(_collect_destination, destination, angles, collector,
                                          cfg["fetch_per_destination"], cfg["freshness"], seen_urls, groups)
        except SearchProviderError as e:
            provider_err = str(e)
            break
        stats["dup_skipped"] += res.get("dup_skipped", 0)
        for e in _drain_trace():
            yield e
        if not res["evidences"]:
            collect_notes.append(f"「{destination}」未通过搜索获得有效结果（可能限流或不相关），已如实标注。")
            # 记录可观测 span：本次检索动作即便无果也可追溯
            trace.record_manual_span(
                task_id, collector, "collect", f"采集目的地「{destination}」证据",
                detail=f"检索角度：{('、'.join(angles))}\n搜索引擎：博查 Bocha（freshness={cfg['freshness']}）",
                decision=f"「{destination}」未返回有效结果，已如实标注、不中断。",
            )
            for e in _drain_trace():
                yield e
            yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": collector,
                                  "text": f"「{destination}」本轮搜索未返回有效结果，继续其余目的地（尽力而为，不中断）。",
                                  "ts": _now()})
            continue
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": collector,
                              "text": f"「{destination}」聚合到 {res['found']} 条去重链接，已取证 {len(res['evidences'])} 条。",
                              "ts": _now()})
        for ev in res["evidences"]:
            evidences.append(ev)
            ev_by_collector[collector] += 1
            d = ev.to_dict()
            d["domain"] = domain_of(ev.source_url)
            d["destination"] = ev.destination
            d["full_text"] = getattr(ev, "_full_text", "")
            yield _ev("evidence", {**d})
            yield _ev("progress", prog(min(14 + len(evidences), 50), "collect", len(evidences)))
            await asyncio.sleep(0.01)
        for fig in res["images"]:
            images.append(fig)
            yield _ev("image", fig)
        # 可观测 span：把「检索→去重→取证」这步非 LLM 动作写进决策链路（不再空白）
        destination_evs = [ev for ev in res["evidences"]]
        destination_domains = {domain_of(ev.source_url) for ev in destination_evs}
        destination_domains.discard("")
        trace.record_manual_span(
            task_id, collector, "collect", f"采集目的地「{destination}」证据",
            detail=(f"检索角度（{len(angles)}个）：{('、'.join(angles))}\n"
                    f"搜索引擎：博查 Bocha Web Search（freshness={cfg['freshness']}）"),
            decision=(f"聚合 {res['found']} 条去重链接 → 抓取取证 {len(destination_evs)} 条，"
                      f"覆盖 {len(destination_domains)} 个独立域名。"),
            evidence_ids=[ev.evidence_id for ev in destination_evs[:8]],
        )
        for e in _drain_trace():
            yield e
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": collector,
                              "text": f"「{destination}」累计证据库 {len(evidences)} 条。", "ts": _now()})

    # 真实舆情采集（多目的地 × 类型白名单平台 × 多角度，大幅提升样本量与平台多样性）
    sentiment_platforms = [p for p in spec["sentiment_platforms"] if p in PLATFORMS]
    platform_names = "、".join(PLATFORM_LABEL.get(p, p) for p in sentiment_platforms) or "主流平台"
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": sentiment_expert,
                          "text": f"舆情采集：在{platform_names}等平台站内检索真实口碑（站内受限时自动回退全网定向检索），覆盖对象与主要候选目的地。",
                          "ts": _now()})
    sentiment_comments: List[Dict[str, Any]] = []
    # 取口碑的目的地：对象 + 主要候选（按 mode 档位决定覆盖几个）
    sentiment_destinations = destinations[:cfg.get("sentiment_destinations", 3)]
    primary_destination = destinations[0]
    take = cfg.get("platform_take", cfg.get("platform_per", 6))
    # 地区关键词（用于消歧 + 相关性过滤，如 大理→云南省，避免抓到同名内容）
    region_kw = _region_keywords(region)
    region_q = (" " + region) if region else ""
    sentiment_angle_tpl = list(spec["sentiment_angles"])
    if provider_err:
        # 主采集已确认服务商终态错误（欠费/Key）：不再烧检索，如实标注后降级
        yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": sentiment_expert,
                              "text": f"舆情口碑采集中断：{provider_err}（搜索服务配额/密钥问题），"
                                      f"舆情按已得数据降级，跳过后续检索。", "ts": _now()})
        sentiment_destinations = []
    for sb in sentiment_destinations:
        trace.set_context(task_id, sentiment_expert, "collect", f"采集「{sb}」全平台舆情")
        plat_counts: Counter = Counter()
        dropped = 0
        for plat in sentiment_platforms:
            site = PLATFORMS[plat].search_site
            plat_label = PLATFORM_LABEL.get(plat, plat)
            # 多角度口碑检索词（查表渲染），带上地区消歧（覆盖体验/优缺点/踩坑/真实评价）
            site_q = [t.replace("{d}", sb) + region_q for t in sentiment_angle_tpl[:2]]
            try:
                plat_results = await asyncio.to_thread(search.multi_search, site_q, num=8, site=site,
                                                       freshness=cfg["freshness"])
                # 站内受限（如抖音/小红书常被 include 过滤掉）→ 回退：全网检索 + 平台关键词
                if not plat_results:
                    fb_q = [f"{t.replace('{d}', sb)}{region_q} {plat_label}" for t in sentiment_angle_tpl]
                    plat_results = await asyncio.to_thread(search.multi_search, fb_q, num=8,
                                                           freshness=cfg["freshness"])
            except SearchProviderError as e:
                # 中途欠费：可见 thought 如实送达真因，已完成的采集不炸掉（降级继续）
                provider_err = str(e)
                yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": sentiment_expert,
                                      "text": f"舆情口碑采集中断：{e}（搜索服务配额/密钥问题），"
                                              f"按已得样本降级，跳过后续检索。", "ts": _now()})
                break
            for e in _drain_trace():
                yield e
            for r in plat_results[:take]:
                url = r.get("url", "")
                title = r.get("title", "")
                text = (r.get("snippet") or title or "").strip()
                if not url or not text or url in seen_urls:
                    continue
                # 相关性过滤：标题/正文必须命中目的地名或地区关键词，否则丢弃（题不对版）
                if not _sentiment_relevant(sb, region_kw, title, text):
                    dropped += 1
                    continue
                seen_urls.add(url)
                # 平台归属：站内搜索用 plat；回退搜索按真实域名判定，判不出则归到当前平台
                detected = _source_type(url)
                plat_final = plat if detected in ("web", "official", "news") else detected
                sentiment_comments.append({"text": text, "platform": plat_final, "url": url,
                                           "title": title, "destination": sb})
                plat_counts[plat_final] += 1
                pub = r.get("captured_at", "")
                # 舆论过热单点判定（有信号才判；当前博查 snippet 无互动字段 → checked=False 如实标注）
                vv = assess_viral({"likes": _to_int(r.get("likes")),
                                   "comments": _to_int(r.get("comments"))})
                stats["viral_checked"] += 1 if vv["checked"] else 0
                stats["viral_count"] += 1 if vv["viral"] else 0
                cred = score_evidence(url, detected, captured_at=pub, has_publish_date=bool(pub),
                                      ok_fetch=False, excerpt=text[:280],
                                      signals={"platform": plat_final}, viral=vv["viral"])
                ev = Evidence(
                    evidence_id=_sid("e"), source_url=url, source_type=detected,
                    title=title or f"{sb} 口碑", excerpt=text[:280],
                    captured_at=pub or _now(), credibility=cred, collected_by=sentiment_expert,
                    destination=sb, domain=domain_of(url),
                    viral=vv["viral"], viral_reason=vv["reason"],
                )
                evidences.append(ev)
                ev_by_collector[sentiment_expert] += 1
                d = ev.to_dict()
                d["domain"] = domain_of(url)
                d["destination"] = sb
                yield _ev("evidence", {**d})
        kept = len([c for c in sentiment_comments if c['destination'] == sb])
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": sentiment_expert,
                              "text": f"「{sb}」舆情有效 {kept} 条（已剔除 {dropped} 条题不对版），"
                                      f"平台分布：{dict(plat_counts)}。", "ts": _now()})
        if provider_err:
            break
    yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": sentiment_expert,
                          "text": f"舆情共采集到 {len(sentiment_comments)} 条带真实链接的多平台口碑（覆盖 {len(sentiment_destinations)} 个目的地）。",
                          "ts": _now()})

    yield _ev("node_update", {"node": "collect", "status": "done"})
    yield _ev("progress", prog(54, "analyze", len(evidences)))

    if not evidences:
        if provider_err:
            msg = (f"本次未能采集到任何可用证据：{provider_err}"
                   f"（请检查搜索服务配额/密钥）")
        else:
            msg = "本次未能采集到任何可用证据（搜索/抓取均失败），请稍后重试或更换调研主题。"
        yield _ev("error", {"message": msg})
        return

    # ---- 4. analyze：LLM 交叉验证 + 论点 + 结构化 Schema ----
    analyst = next((m["id"] for m in dispatch["members"] if m["id"].startswith("L2")), "L2-001")
    yield _ev("node_update", {"node": "analyze", "status": "working", "expert": analyst})
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                          "text": "对证据去重并做交叉验证：同一结论需 ≥2 个独立域名支撑方判为高置信。", "ts": _now()})
    trace.set_context(task_id, analyst, "analyze", "交叉验证产出结构化论点")
    analysis = await asyncio.to_thread(_analyze, query, destinations, focus, evidences, member_ids,
                                       rtype, cfg["analyze_max_tokens"])
    for e in _drain_trace():
        yield e
    claims = analysis["claims"]
    for cl in claims:
        yield _ev("message", {"id": _sid("m"), "kind": "claim", "claim": cl})
        await asyncio.sleep(0.03)

    # ---- 4.5 spots：景点实体形成（LLM 只抽可数信号 → scoring 规则算分 → 冻结 TopN 实体表）----
    # 实体唯一来源：景点榜单/路线卡/商铺/舆情引用下游一律挂 spot_id，
    # 禁止各章用自由文本重新匹配景点名（实体一致性的结构性防线）。分数全部由规则算出，LLM 无评分话语权。
    # L2 可见降级：结构化产物「被截断致空」绝不静默——trunc_report 在线程内求值
    # 传回（ContextVar 单向 copy，await 后父上下文读不到），每任务至多出 1 条降级
    # thought（spots 抽取 / 首轮结构化 / 返工轮共享去重），报告 payload 不造假数据。
    trunc_notified = False

    def _trunc_degrade_evt(flag: List[bool]) -> Optional[Dict[str, Any]]:
        nonlocal trunc_notified
        if flag and flag[0] and not trunc_notified:
            trunc_notified = True
            return _ev("thought", {
                "id": _sid("th"), "kind": "reflect", "expert": analyst,
                "text": "模型输出被截断（思考未关或预算不足）：榜单/行程/价位带等"
                        "结构化可视化本次缺位——建议在「模型配置」改用支持关闭思考的"
                        "模型（或默认模型）后重新发起调研。",
                "ts": _now()})
        return None

    frozen_entities: Dict[str, Any] = {}
    spot_entities: List[Dict[str, Any]] = []
    # 视角二查证据映射（只活在编排期，不进报告 payload——评审 P1-2 不改 evidences schema）
    family_probes: Dict[str, List[str]] = {}
    if "spot_ranking" in spec["structured_keys"]:
        yield _ev("node_update", {"node": "spots", "status": "working", "expert": analyst})
        yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                              "text": f"景点实体阶段：从证据抽取可数信号（声量/口碑/性价比），规则算分冻结 Top{cfg['spot_topn']} 实体表……",
                              "ts": _now()})
        trace.set_context(task_id, analyst, "spots", "景点信号抽取与规则算分")
        spot_trunc: List[bool] = []
        spot_rows = await asyncio.to_thread(_extract_spot_signals, query, destinations, focus,
                                            evidences, cfg["spot_topn"], runtime._model("core"),
                                            trunc_report=spot_trunc)
        for e in _drain_trace():
            yield e
        evt = _trunc_degrade_evt(spot_trunc)
        if evt:
            yield evt
        ranked = SC.rank_spots(spot_rows, cfg["spot_topn"])
        frozen = coerce_spot_ranking(
            {"spot_ranking": [{"destination": primary_destination, "items": ranked}]},
            {ev.evidence_id for ev in evidences}) if ranked else []
        if frozen and not frozen[0].get("items"):
            frozen = []  # 规整后全被丢弃（如无合法目的地名）：不挂空表，避免下游误以为有实体
        frozen_entities["spot_ranking"] = frozen
        spot_entities = frozen[0]["items"] if frozen else []
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                              "text": (f"已冻结 Top{len(spot_entities)} 景点实体（评分=0.4×声量+0.4×口碑+0.2×性价比，规则可复现）："
                                       + "、".join(f"{r['name']} {r['score'] or 0}分" for r in spot_entities[:3]) + "……")
                                     if spot_entities else
                                     "未能从证据抽出有效景点信号，榜单实体表为空，相关章节如实留白。",
                              "ts": _now()})
        # M2：百度实体解析降级链（精确匹配→地理编码→matched=false）+ 真实路线批量落库。
        # 任何失败（缺 AK/超时/配额）只影响占位降级，不回滚已完成的 LLM 分析与榜单表。
        baidu_ok = await _resolve_spot_entities(primary_destination, spot_entities)
        real_routes = (await _build_spot_routes(primary_destination, spot_entities)
                       if baidu_ok else [])
        frozen_entities["spot_routes"] = real_routes
        if baidu_ok:
            matched_n = sum(1 for r in spot_entities if r.get("matched"))
            route_rows = real_routes[0]["items"] if real_routes else []
            routes_n = sum(1 for r in route_rows if r.get("routes"))
            yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                                  "text": f"百度实体解析：{matched_n}/{len(spot_entities)} 个景点命中坐标（未命中走地理编码兜底/占位），"
                                          f"已为 {routes_n}/{len(route_rows)} 个景点规划真实路线（公交/地铁 + 打车估算），"
                                          "其余景点保留占位卡。",
                                  "ts": _now()})
        elif spot_entities:
            yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                                  "text": "未配置百度服务端 AK：景点坐标与实际路线走占位降级，榜单表（LLM 证据版）照常产出。",
                                  "ts": _now()})
        # M2c：逐景点舆情补充采集（deep/expert）——评论挂 spot_id，喂 (spot×platform) 双维聚合；
        # 目的地级基础采集保持原样，全局面板/旧图不回归。
        if cfg.get("spot_sent_take", 0) and spot_entities:
            spot_errs: List[str] = []
            spot_comments = await _collect_spot_comments(
                spot_entities, sentiment_platforms, region_q, cfg["spot_sent_take"],
                cfg["freshness"], primary_destination, seen_urls, spot_errs)
            if spot_errs:
                provider_err = provider_err or spot_errs[0]
                yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": sentiment_expert,
                                      "text": f"景点口碑信号采集中断：{spot_errs[0]}（搜索服务配额/密钥问题），"
                                              f"逐景点舆情按已有样本降级。", "ts": _now()})
            sentiment_comments.extend(spot_comments)
            yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": sentiment_expert,
                                  "text": f"逐景点舆情补充：{len(spot_comments)} 条口碑已挂接 Top{len(spot_entities)} 景点实体"
                                          f"（每景点每平台 ≤{cfg['spot_sent_take']} 条，(spot×platform) 聚合数据源）。",
                                  "ts": _now()})
        # 视角专属逐景点二查（rough-cliff-vole）：视角配了核查表且模式有配额才发；
        # 判据全部查表（PERSPECTIVE_SPECS / MODE_CONFIG），非亲子视角零调用。
        persp_probe_tpls = tuple(RT.perspective_spec(persp_sid).get("spot_probe_tpls") or ())
        if persp_probe_tpls and spot_entities:
            probe_topn = int(cfg.get("persp_probe_topn") or 0)
            if not probe_topn:
                yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                                      "text": f"{cfg['label']}不做视角专项二查（搜索配额优先给主链路）："
                                              "核查表照常全行产出、参数列以「待核验」占位。",
                                      "ts": _now()})
            else:
                probe = await _probe_spot_family(
                    primary_destination, spot_entities, persp_probe_tpls,
                    cfg["freshness"], seen_urls, analyst, probe_topn)
                evidences.extend(probe["evidences"])
                family_probes.update(probe["by_spot"])
                if probe["quota_error"]:
                    provider_err = provider_err or probe["quota_error"]
                    yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": analyst,
                                          "text": f"专项二查中断：{probe['quota_error']}（搜索服务配额/密钥问题）——"
                                                  "降级为仅槽位角度，核查表缺列以「待核验」占位，不造数。",
                                          "ts": _now()})
                else:
                    n_targets = min(len([e for e in spot_entities if e.get("spot_id")]), probe_topn)
                    yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                                          "text": f"视角专项二查：{len(probe['by_spot'])}/{n_targets} 个景点"
                                                  f"采到票规/设施线索（共 {len(probe['evidences'])} 条证据），"
                                                  "未命中景点在核查表按「待核验」占位。",
                                          "ts": _now()})
        yield _ev("progress", prog(56, "spots", len(evidences)))
        yield _ev("node_update", {"node": "spots", "status": "done"})
    entity_hint = (json.dumps([{"spot_id": r.get("spot_id"), "name": r.get("name")}
                               for r in spot_entities], ensure_ascii=False)[:1600]
                   if spot_entities else "")

    # 结构化知识 Schema（对象集按调研类型查表；spot_ranking 属实体阶段产出，不在 LLM 结构化提示内）
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                          "text": f"构建结构化目的地知识：{' / '.join(k for k in spec['structured_keys'] if k not in _ENTITY_STAGE_KEYS)}（字段完整、引用强制）……",
                          "ts": _now()})
    trace.set_context(task_id, analyst, "analyze", "产出结构化目的地知识Schema")
    struct_trunc: List[bool] = []
    structured = await asyncio.to_thread(_analyze_structured, query, destinations, focus, evidences,
                                         rtype, cfg["structured_max_tokens"], entity_hint,
                                         trunc_report=struct_trunc)
    for e in _drain_trace():
        yield e
    evt = _trunc_degrade_evt(struct_trunc)
    if evt:
        yield evt
    structured.update(frozen_entities)  # 冻结表覆盖回写：实体单一真相源，LLM 返回也不采纳
    if "shop_list" in structured:
        # 商铺实体保真：百度 POI 回填坐标/区域（缺 AK 静默跳过 → matched 保持 False 占位）
        await _enrich_shops_with_poi(primary_destination, structured.get("shop_list") or [])
        # M3e：每种美食前 N 家 matched 商铺挂一条真实公交路线（配额见 MODE_CONFIG.shop_route_topn）
        shop_routes_n = await _attach_shop_routes(
            primary_destination, structured.get("shop_list") or [],
            cfg.get("shop_route_topn", 0))
        if shop_routes_n:
            yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                                  "text": f"已为 {shop_routes_n} 家美食商铺规划真实公交路线（自市中心锚定）。",
                                  "ts": _now()})
    if rtype == "guide" and mode in ("deep", "expert") and spot_entities:
        # M3a/D2 一页视图：guide 的 deep 与 expert 档 route_plan 整体由规则组装覆盖
        # （引用冻结实体表，LLM 版本不采纳）。天数双源判据（问卷 v2）：用户原文优先，
        # 原文无天数才认问卷 days 答案，两路都拿不到返回 0、由 pace 推算，不造数。
        structured["route_plan"] = _assemble_itinerary(
            primary_destination, spot_entities, frozen_entities.get("spot_routes") or [],
            structured.get("shop_list") or [],
            _days_count(query) or _days_count(str(clar.get("days") or "")),
            cfg.get("spot_day_pace", 4))
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": analyst,
                              "text": f"一页视图：Top{len(spot_entities)} 景点已按名次逐日组装"
                                      f"（{len(structured['route_plan'][0]['days']) if structured['route_plan'] else 0} 天，"
                                      "抵达交通引用真实路线、商铺按 spot_id/shop_id 挂接）。",
                              "ts": _now()})
    # 视角专属块装配（rough-cliff-vole）：行 seed 自冻结榜、LLM 只填格；
    # 时序钉死在质量评估之前（分母认键）、_write_one fan-out 之前（写作提示拿得到）。
    # 装配失败不炸管线：全「待核验」占位表照出（占位可见即正确终态）。
    if persp_sid and RT.perspective_spec(persp_sid).get("checklist_key") and spot_entities:
        structured.update(await asyncio.to_thread(
            _fill_persp_blocks, persp_sid, primary_destination, spot_entities,
            family_probes, evidences, clar, runtime._model("aux")))
    analysis["structured"] = structured

    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": sentiment_expert,
                          "text": "舆情专家对真实评论做情感分类与观点阵营聚类（占比归一化）……", "ts": _now()})
    trace.set_context(task_id, sentiment_expert, "analyze", "舆情情感分类与阵营聚类")
    sentiment = await asyncio.to_thread(analyze_sentiment, primary_destination, sentiment_comments)
    for e in _drain_trace():
        yield e
    yield _ev("progress", prog(64, "analyze", len(evidences)))
    yield _ev("node_update", {"node": "analyze", "status": "done"})

    # ---- 5. audit：真实质检 + 反馈闭环（在 write 之前评估覆盖度）----
    auditor = next((m["id"] for m in dispatch["members"] if m["id"] == "L3-003"), "L3-003")
    yield _ev("node_update", {"node": "audit", "status": "working", "expert": auditor})
    yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": auditor,
                          "text": "质检官评估证据覆盖度、维度完整性与置信度，决定是否打回返工。", "ts": _now()})
    quality_before = audit.evaluate_quality(destinations, focus, claims, evidences, structured,
                                      research_type=rtype, perspective_section_id=persp_sid)
    # 质检官 LLM 真实审阅（逐维度打分 + 问题 + 改进建议）——让质检有对比、有审阅、可观测
    trace.set_context(task_id, auditor, "audit", "质检官审阅：逐维度打分+问题+改进建议")
    review_before = await asyncio.to_thread(
        llm_quality_review, query, destinations, focus, claims, structured, quality_before,
        runtime._model("aux"), rtype, persp_constraints=persp_constraints_line)
    for e in _drain_trace():
        yield e
    yield _ev("message", {"id": _sid("m"), "kind": "audit_review", "expert": auditor,
                          "stage": "before",
                          "verdict": review_before.get("verdict"),
                          "scores": review_before.get("scores", {}),
                          "review": review_before.get("review", ""),
                          "issues": review_before.get("issues", []),
                          "suggestions": review_before.get("suggestions", [])})
    rework_rounds_done = 0
    issues_resolved = 0
    if cfg["rework_rounds"] > 0:
        envelopes = decide_rework(quality_before, evidences)
        # 规则未触发但质检官 LLM 判定需返工 → 合成一个 analyze 返工信封，
        # 让反馈闭环真实可触发（且复审后能看到改善），对齐评分维度。
        if not envelopes and review_before.get("verdict") == "rework":
            from app.core.models import Envelope as _Env
            envelopes = [_Env(
                msg_id="env_" + uuid.uuid4().hex[:8], sender="L3-003", receiver="analyze",
                task_type="REWORK", payload={"reason": "质检官审阅判定需补强论证与交叉验证"},
                issues=[{"target": "review", "severity": "medium",
                         "reason": r, "raised_by": "L3-003"}
                        for r in review_before.get("issues", [])[:4]],
            )]
        for _ in range(cfg["rework_rounds"]):
            if not envelopes:
                break
            for env in envelopes:
                if env.receiver == "collect":
                    recollect = env.payload.get("destinations", [])
                    yield _ev("node_update", {"node": "audit", "status": "rework"})
                    yield _ev("node_update", {"node": "collect", "status": "rework"})
                    yield _ev("message", {"id": _sid("m"), "kind": "rework", "expert": auditor,
                                          "reason": f"证据不足，打回采集补充：{('、'.join(recollect)) or '相关目的地'}",
                                          "envelope": {"sender": env.sender, "receiver": env.receiver,
                                                       "task_type": env.task_type, "issues": env.issues}})
                    # 用更多角度补采（追加类型化的时效性角度）
                    extra_angles = angles + list(spec["rework_angles"])
                    for b in recollect[:3]:
                        trace.set_context(task_id, collector, "collect", f"返工补采「{b}」")
                        res = await asyncio.to_thread(_collect_destination, b, extra_angles[:cfg["max_angles"]],
                                                      collector, cfg["fetch_per_destination"], cfg["freshness"],
                                                      seen_urls, groups)
                        stats["dup_skipped"] += res.get("dup_skipped", 0)
                        for e in _drain_trace():
                            yield e
                        for ev in res["evidences"]:
                            evidences.append(ev)
                            ev_by_collector[collector] += 1
                            d = ev.to_dict()
                            d["domain"] = domain_of(ev.source_url)
                            d["destination"] = ev.destination
                            d["full_text"] = getattr(ev, "_full_text", "")
                            yield _ev("evidence", {**d})
                        for fig in res["images"]:
                            images.append(fig)
                            yield _ev("image", fig)
                    yield _ev("node_update", {"node": "collect", "status": "done"})
                elif env.receiver == "analyze":
                    yield _ev("node_update", {"node": "audit", "status": "rework"})
                    yield _ev("node_update", {"node": "analyze", "status": "rework"})
                    yield _ev("message", {"id": _sid("m"), "kind": "rework", "expert": auditor,
                                          "reason": "维度/结构覆盖不足，打回重新分析补全。",
                                          "envelope": {"sender": env.sender, "receiver": env.receiver,
                                                       "task_type": env.task_type, "issues": env.issues}})
                    trace.set_context(task_id, analyst, "analyze", "返工：按质检意见针对性补全维度与交叉验证")
                    rework_fb = "\n".join(
                        f"- 问题：{x}" for x in review_before.get("issues", [])[:5]
                    )
                    if review_before.get("suggestions"):
                        rework_fb += "\n" + "\n".join(
                            f"- 建议：{x}" for x in review_before.get("suggestions", [])[:5]
                        )
                    analysis = await asyncio.to_thread(_analyze, query, destinations, focus, evidences,
                                                       member_ids, rtype, cfg["analyze_max_tokens"], rework_fb)
                    for e in _drain_trace():
                        yield e
                    claims = analysis["claims"]
                    rework_trunc: List[bool] = []
                    structured = await asyncio.to_thread(_analyze_structured, query, destinations, focus,
                                                         evidences, rtype, cfg["structured_max_tokens"],
                                                         entity_hint, trunc_report=rework_trunc)
                    structured.update(frozen_entities)
                    evt = _trunc_degrade_evt(rework_trunc)
                    if evt:
                        yield evt
                    # 返工轮 structured 整体重建：视角块必须重新装配（ST-01 不回潮）
                    if persp_sid and RT.perspective_spec(persp_sid).get("checklist_key") and spot_entities:
                        structured.update(await asyncio.to_thread(
                            _fill_persp_blocks, persp_sid, primary_destination, spot_entities,
                            family_probes, evidences, clar, runtime._model("aux")))
                    analysis["structured"] = structured
                    yield _ev("node_update", {"node": "analyze", "status": "done"})
            rework_rounds_done += 1
            quality_after_round = audit.evaluate_quality(destinations, focus, claims, evidences, structured,
                                                   research_type=rtype,
                                                   perspective_section_id=persp_sid)
            issues_resolved = max(0, len(quality_before.issues) - len(quality_after_round.issues))
            envelopes = decide_rework(quality_after_round, evidences)
        quality_after = audit.evaluate_quality(destinations, focus, claims, evidences, structured,
                                         research_type=rtype, perspective_section_id=persp_sid)
    else:
        quality_after = quality_before

    # 返工后再做一次质检复审，形成「审阅→返工→复审」的真实闭环（重做后有改善）
    review_after = review_before
    if rework_rounds_done > 0:
        trace.set_context(task_id, auditor, "audit", "质检官复审：返工后复核改善情况")
        review_after = await asyncio.to_thread(
            llm_quality_review, query, destinations, focus, claims, structured, quality_after,
            runtime._model("aux"), rtype)
        for e in _drain_trace():
            yield e
        # 解决问题数：综合「规则侧 issue 减少」「质检官 issue 减少」「评分提升的维度数」
        # 三者取最大，真实反映返工后的改善（LLM 每轮重新生成 issue 列表，单看条数会失真，
        # 故以『评分提升的维度数』作为最可靠的改善信号）。
        review_issues_resolved = max(0, len(review_before.get("issues", [])) - len(review_after.get("issues", [])))
        sc_b = review_before.get("scores", {}) or {}
        sc_a = review_after.get("scores", {}) or {}
        improved_dims = sum(1 for k in sc_a if k in sc_b and sc_a[k] > sc_b[k])
        issues_resolved = max(issues_resolved, review_issues_resolved, improved_dims)
        yield _ev("message", {"id": _sid("m"), "kind": "audit_review", "expert": auditor,
                              "stage": "after",
                              "verdict": review_after.get("verdict"),
                              "scores": review_after.get("scores", {}),
                              "review": review_after.get("review", ""),
                              "issues": review_after.get("issues", []),
                              "suggestions": review_after.get("suggestions", [])})
        yield _ev("message", {"id": _sid("m"), "kind": "rework_result", "expert": auditor,
                              "reason": "返工闭环完成，覆盖度与置信度提升。",
                              "metrics_before": quality_before.summary(),
                              "metrics_after": quality_after.summary(),
                              "issues_resolved": issues_resolved})
    yield _ev("node_update", {"node": "audit", "status": "done"})
    yield _ev("progress", prog(70, "audit", len(evidences)))

    # ---- 5.5 目的地行白名单收口（必须在质检/返工决策之后、任何消费者之前）----
    # 早于 quality：滤空会拉低 schema_completeness → 多触发一轮返工、压低 consistency；
    # 晚于 _write_one/_build_charts：写稿提示会把 analysis 行 json.dumps 注入，滤晚了正文照样引用别城。
    _enforce_dest_rows(analysis, destinations)

    # ---- 6. write：多模型并行逐章撰写 ----
    writer = next((m["id"] for m in dispatch["members"] if m["id"] == "L3-002"), dispatch["lead"])
    yield _ev("node_update", {"node": "write", "status": "working", "expert": writer})
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": writer,
                          "text": f"调研总监启动 {len(section_ids)} 章并行撰写（核心章 {runtime._model('core')} / 辅助章 {runtime._model('aux')}）。",
                          "ts": _now()})

    # 并行生成各章
    sections_text: Dict[str, Dict[str, Any]] = {}

    async def _write_one(sid: str):
        title = RT.SECTION_PLAN.get(sid, sid)
        model = runtime._model("core") if sid in CORE_SECTIONS else runtime._model("aux")
        trace.set_context(task_id, writer, "write", f"撰写章节「{title}」")
        return sid, await asyncio.to_thread(
            _write_single_section, sid, title, query, destinations, focus,
            evidences, claims, analysis, model, rtype,
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"], sentiment,
            persp_line=(persp_constraints_line if sid == persp_sid else "")
        )

    tasks = [asyncio.create_task(_write_one(sid)) for sid in section_ids]
    done_count = 0
    total = len(tasks)
    for coro in asyncio.as_completed(tasks):
        sid, st = await coro
        sections_text[sid] = st
        done_count += 1
        for e in _drain_trace():
            yield e
        title = RT.SECTION_PLAN.get(sid, sid)
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": writer,
                              "text": f"第 {done_count}/{total} 章「{title}」撰写完成。", "ts": _now()})
        yield _ev("progress", prog(70 + int(16 * done_count / total), "write", len(evidences)))

    # 写后结构补齐：只对「有正文、无结构」的章节补一次极小结构请求（原因见 _repair_missing_structure）
    repair_ids = [sid for sid in section_ids if _structureless(sections_text.get(sid))]
    if repair_ids:
        sem = asyncio.Semaphore(4)

        async def _repair_one(_sid: str):
            async with sem:
                _title = RT.SECTION_PLAN.get(_sid, _sid)
                return _sid, await asyncio.to_thread(
                    _repair_missing_structure, _sid, _title, sections_text[_sid],
                    claims, runtime._model("fast"),
                )

        for coro in asyncio.as_completed([_repair_one(s) for s in repair_ids]):
            sid, patch = await coro
            if patch:
                sections_text[sid].update(patch)
            for e in _drain_trace():
                yield e

    # 结构完整性：仍缺失的章节必须在决策回放里点名（静默降级不可接受）
    still = [sid for sid in section_ids if _structureless(sections_text.get(sid))]
    if still:
        trace.record_manual_span(task_id, writer, "write", "章节结构完整性",
                                 detail=f"{len(still)}/{len(section_ids)} 章无结构字段："
                                        + "、".join(RT.SECTION_PLAN.get(s, s) for s in still),
                                 model="—（规则统计，无 LLM）")
    yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": writer,
                          "text": f"章节结构完整性：{len(section_ids) - len(still)}/{len(section_ids)} 章结构字段就绪"
                                  + (f"（缺失：{'、'.join(RT.SECTION_PLAN.get(s, s) for s in still)}）"
                                     if still else "。"),
                          "ts": _now()})
    for e in _drain_trace():
        yield e

    # 舆情专章：基于真实评论数据生成多段深度解读（与正文同等深度）
    # —— 档位已把「全网舆情」立为正式章节（sentiment_report）时，改由普通章节管线撰写，不再走面板叙事
    sentiment_text: Dict[str, Any] = {"paragraphs": [], "key_takeaway": "", "highlights": []}
    if sentiment.get("sample_size") and "sentiment_report" not in section_ids:
        trace.set_context(task_id, sentiment_expert, "write", "撰写章节「全网舆情与观点阵营」")
        sentiment_text = await asyncio.to_thread(
            _write_sentiment_narrative, query, destinations, sentiment, runtime._model("aux"),
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"],
        )
        for e in _drain_trace():
            yield e

    chart_specs, chart_gaps = _build_charts_and_gaps(
        destinations, analysis, sentiment, claims, rtype,
        mode=mode, evidences=evidences)
    for ch in chart_specs:
        yield _ev("chart", ch)
        await asyncio.sleep(0.05)
    yield _ev("progress", prog(90, "write", len(evidences)))
    yield _ev("node_update", {"node": "write", "status": "done"})

    # ---- 7. done：组装 + 指标 + Trace 落库 ----
    yield _ev("node_update", {"node": "done", "status": "working", "expert": dispatch["lead"]})
    yield _ev("progress", prog(95, "done", len(evidences)))

    elapsed = time.monotonic() - t_start
    tokens_used = TOKEN_USAGE["total"] - token_start
    metrics = compute_report_metrics(
        destinations=destinations, focus=focus, claims=claims, evidences=evidences,
        structured=structured, elapsed_seconds=elapsed, tokens_used=tokens_used,
        rework_rounds=rework_rounds_done, issues_resolved=issues_resolved,
        objective_stats=stats, research_type=rtype, perspective_section_id=persp_sid,
    )
    metrics = merge_quality_into_metrics(metrics, quality_after.to_dict())

    trace_spans = trace.get_trace(task_id)

    # v2.1 客观性：把组内转载地址回填到代表证据（供溯源/披露），并组装 methodology 数据
    groups_by_id = {g["id"]: g for g in groups}
    for ev in evidences:
        g = groups_by_id.get(ev.source_group or "")
        if g:
            ev.republished_from = [u for u in g.get("urls", []) if u != ev.source_url]
    objective_meta = {
        "stats": stats,
        "unique_groups": len({ev.source_group for ev in evidences if ev.source_group}),
        "sentiment_samples": sentiment.get("sample_size", 0),
        "freshness": cfg["freshness"],
    }

    report = _assemble_report(query, destinations, focus, dispatch, claims, evidences, images,
                              sentiment, chart_specs, sections_text, collect_notes,
                              analysis, metrics, quality_before.to_dict(),
                              quality_after.to_dict(), trace_spans, mode, section_ids,
                              sentiment_text, objective_meta, rtype, clar=clar,
                              chart_gaps=chart_gaps)
    # 质检审阅意见（before/after）随报告下发，供报告页「质检审裁」展示
    report["audit_review"] = {"before": review_before, "after": review_after,
                              "rework_rounds": rework_rounds_done,
                              "issues_resolved": issues_resolved}
    db.save_report(report, task_id=task_id)
    db.save_traces(task_id, report["id"], trace_spans)
    db.mark_task_done(task_id, report["id"])
    claims_by_author = Counter(c.get("author", "") for c in claims if c.get("author"))
    db.bump_expert_stats(member_ids, dict(claims_by_author), dict(ev_by_collector))
    if sub_id:
        db.mark_subscription_run(sub_id, report["id"])
    trace.cleanup(task_id)

    yield _ev("progress", prog(100, "done", len(evidences)))
    yield _ev("node_update", {"node": "done", "status": "done"})
    yield _ev("report_ready", {"reportId": report["id"], "title": report["title"],
                               "cover_image": report["cover_image"]})
    yield _ev("done", {"reportId": report["id"]})




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

# 结构化键 → 展示用中文名（写入章节提示时给 LLM 一个可读标签）
_STRUCTURED_LABEL: Dict[str, str] = {
    "spot_ranking": "景点综合评分榜", "food_ranking": "美食Top榜",
    "spot_routes": "逐景点路线", "shop_list": "美食商铺清单",
    "route_plan": "逐日路线", "stay_options": "住宿选项", "cost_breakdown": "花费拆解",
    "access_matrix": "可达性矩阵", "amenity_checklist": "配套清单", "risk_profile": "风险画像",
}

# spots 实体阶段产出的 structured 键：不进 LLM 结构化提示——榜单分数由
# scoring 规则算出（可复现），实体表由 spots 阶段冻结后覆盖回写；
# 路线卡（spot_routes）M2 起改为百度 direction 真实数据批量落库（缺 AK/失败 → 空表占位，
# 绝不让 LLM 编造换乘细节）。
_ENTITY_STAGE_KEYS = frozenset({"spot_ranking", "spot_routes"})

# 百度批量 fan-out 的阶段级总预算（秒）：单调用另有 baidu_timeout，超时项走占位降级，
# 不回滚已完成的 LLM 分析。
_BAIDU_STAGE_BUDGET_S = 60.0

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
    digest = _evidence_digest(evidences)
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
    digest = _evidence_digest(evidences, limit=24)
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


def _extract_spot_signals(query, destinations, focus, evidences: List[Evidence],
                          top_n: int, model: str,
                          trunc_report: Optional[List[bool]] = None) -> List[Dict[str, Any]]:
    """景点实体阶段：LLM 只做**可数信号的事实抽取**（声量提及数/正面口碑占比/性价比档），
    排序与算分交给 scoring.rank_spots——数值可复现，LLM 无评分话语权。

    失败或无信号时返回空表（上层出「实体表为空」的如实提示），不影响已完成的其他分析。
    trunc_report：同 _analyze_structured 的 L2 线程内截断判定回传通道。
    """
    spec_digest = _evidence_digest(evidences, limit=24)
    valid_eids = {e.evidence_id for e in evidences}
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是旅游数据分析师。从给定证据中整理目的地热度最高的若干景点，"
                    "为每个景点抽取**可计数的事实信号**，禁止给景点排序或打分。字段口径："
                    "mentions=该景点在证据中被提及/打卡的次数（整数）；"
                    "positive_ratio=正面评价占该景点全部评价的比例（0-1 小数）；"
                    "value_score=性价比主观档位归一（0-1 小数，1 为极高性价比）。"
                    "所有信号都必须能追溯到给定证据，无证据支撑的景点不要编造。输出 JSON："
                    '{"spots":[{"name":"景点名","area":"所在区域","signals":{"mentions":数字,'
                    '"positive_ratio":0-1,"value_score":0-1},"ticket":"门票与预约方式",'
                    '"stay_minutes":建议停留分钟整数,"off_peak":"避峰时段","reason":"一句话入选理由",'
                    '"evidence_ids":["真实id"]}]}。只输出 JSON，不要解释。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}\n"
                    f"只需给出不超过 {top_n} 个景点。\n证据：\n{spec_digest}"
                )},
            ],
            max_tokens=6000,
            temperature=0.3,
            model=model,
            purpose="景点信号抽取（TopN 实体候选）",
        )
        rows = data.get("spots") if isinstance(data, dict) else data
        out: List[Dict[str, Any]] = []
        for r in (rows if isinstance(rows, list) else []):
            if isinstance(r, dict) and str(r.get("name") or "").strip():
                r["evidence_ids"] = _filter_eids(r.get("evidence_ids"), valid_eids)
                out.append(r)
        if trunc_report is not None:
            trunc_report.append(llm.last_finish_reason() == "length" and not out)
        return out
    except Exception:
        if trunc_report is not None:
            trunc_report.append(False)
        return []


# ── M2：百度实体解析 / 真实路线 / 商铺 POI（envelope 降级，任何失败不抛、不炸任务）──




async def _run_baidu_fanout(coros: List[Any]) -> None:
    """并发跑百度任务，阶段级总预算限时；超时任务取消（该项保持占位降级）。

    子任务体内部已吞异常（百度客户端本就 envelope 不抛），这里只兜住取消与预算。
    """
    if not coros:
        return
    tasks = [asyncio.create_task(c) for c in coros]
    _, pending = await asyncio.wait(tasks, timeout=_BAIDU_STAGE_BUDGET_S)
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _resolve_one_spot(dest: str, item: Dict[str, Any]) -> None:
    """单景点就地解析：地点检索精确匹配 → 地理编码兜底（置信度≥60）→ matched=False 占位。"""
    item["matched"] = False
    name = str(item.get("name") or "").strip()
    if not name:
        return
    r = baidu_client.place_search(name, dest)
    if r.get("ok"):
        hit = next((p for p in r["places"]
                    if _name_hit(name, p.get("name")) and p.get("lat") is not None
                    and p.get("lng") is not None), None)
        if hit:
            item.update({"lat": hit["lat"], "lng": hit["lng"], "matched": True})
            if hit.get("area") and not item.get("area"):
                item["area"] = hit["area"]
            return
    g = baidu_client.geocode(f"{dest}{name}", dest)
    if (g.get("ok") and g.get("lat") is not None
            and int(g.get("confidence") or 0) >= 60):
        item.update({"lat": g["lat"], "lng": g["lng"], "matched": True})


async def _resolve_spot_entities(dest: str, items: List[Dict[str, Any]]) -> bool:
    """并发解析冻结 TopN 景点坐标。返回百度通道是否可用（False→整体占位降级）。"""
    for it in items:
        it["matched"] = False
    if not items or not baidu_client.available():
        return False

    async def one(it: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(_resolve_one_spot, dest, it)
        except Exception:
            it["matched"] = False

    await _run_baidu_fanout([one(it) for it in items])
    return True


def _fmt_duration_sec(sec: Any) -> str:
    try:
        m = int(float(sec) / 60)
    except (TypeError, ValueError):
        return ""
    if m < 1:
        return "1分钟内"
    if m < 60:
        return f"约{m}分钟"
    return f"约{m // 60}小时{m % 60}分钟"


def _spot_routes_one(dest: str, origin: str, it: Dict[str, Any]) -> List[Dict[str, Any]]:
    """单景点逐条实际路线：公交/地铁（transit 最优）+ 打车（driving 里程估价，标「估算」）。"""
    coords = f"{it['lat']},{it['lng']}"
    routes: List[Dict[str, Any]] = []
    t = baidu_client.direction("transit", origin, coords, city=dest)
    if t.get("ok") and t["routes"]:
        best = t["routes"][0]
        vehicles = " → ".join(dict.fromkeys(
            s["vehicle"] for s in best["steps"] if s.get("vehicle"))) or "公交/地铁"
        try:
            km = f"，全程约{round(float(best.get('distance_m') or 0) / 1000, 1)}公里"
        except (TypeError, ValueError):
            km = ""
        routes.append({"mode": "公交/地铁", "duration": _fmt_duration_sec(best.get("duration_s")),
                       "cost": "", "transfer": vehicles[:80], "note": f"自市中心出发{km}",
                       "evidence_ids": []})
    d = baidu_client.direction("driving", origin, coords)
    if d.get("ok") and d["routes"]:
        best = d["routes"][0]
        est = baidu_client.taxi_estimate(best.get("distance_m"))
        cost = f"约{est['fare_yuan']}元（估算）" if est.get("ok") else ""
        routes.append({"mode": "打车", "duration": _fmt_duration_sec(best.get("duration_s")),
                       "cost": cost, "transfer": "", "note": "里程规则估价，实际以上车计价为准",
                       "evidence_ids": []})
    return routes


async def _build_spot_routes(dest: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为冻结榜每个景点规划真实路线（并发 + 阶段预算），产出 coerce_spot_routes 同形结构。

    行集由榜单决定、不由解析成功决定：没坐标或路线算不出的景点仍出一行、routes=[]，
    前端据此显示占位（旧实现按 matched 预筛，把未命中景点整行丢弃，
    真机表现为「Top7 只有 1 张路线卡」）。
    """
    targets = [it for it in items if it.get("spot_id")]
    if not targets or not baidu_client.available():
        return []
    g = await asyncio.to_thread(baidu_client.geocode, dest, "")
    if not g.get("ok"):
        return []
    origin = f"{g['lat']},{g['lng']}"
    results: Dict[str, List[Dict[str, Any]]] = {}

    async def one(it: Dict[str, Any]) -> None:
        if it.get("lat") is None or it.get("lng") is None:
            return  # 无坐标无从算路线：占位行，省掉必然失败的配额
        try:
            routes = await asyncio.to_thread(_spot_routes_one, dest, origin, it)
            if routes:
                results[it["spot_id"]] = routes
        except Exception:
            pass

    await _run_baidu_fanout([one(it) for it in targets])
    rows = [{"spot_id": it["spot_id"], "spot_name": it.get("name", ""),
             "routes": results.get(it["spot_id"], [])}
            for it in targets]  # 按榜单名次保序，可复现
    return [{"destination": dest, "items": rows}] if rows else []


_PROBE_STAGE_BUDGET_S = 90.0
_PROBE_CONCURRENCY = 4


def _probe_spot_family_one(dest: str, spot_name: str, tpls: Tuple[str, ...],
                           freshness: str, existing_urls: set,
                           collector: str) -> List["Evidence"]:
    """单景点定向二查（同步）：检索 → URL 去重 → 摘要构造 Evidence。

    不抓全文——二查供核查表填格，搜索摘要本身就是票规/设施的参数化事实源；
    配额/密钥类终态（SearchProviderError）原样冒泡给阶段层做整体降级，不吞。
    """
    queries = [f"{dest} {t.format(spot=spot_name)}" for t in tpls]
    results = search.multi_search(queries, num=5, freshness=freshness)
    out: List[Evidence] = []
    for r in results:
        if len(out) >= 4:
            break
        url = r.get("url", "")
        snippet = str(r.get("snippet") or "").strip()
        if not url or not snippet or url in existing_urls:
            continue
        existing_urls.add(url)
        stype = _source_type(url)
        pub = r.get("captured_at", "")
        cred = score_evidence(url, stype, captured_at=pub or _now(),
                              has_publish_date=bool(pub), ok_fetch=False,
                              excerpt=snippet[:280])
        out.append(Evidence(evidence_id=_sid("e"), source_url=url, source_type=stype,
                            title=r.get("title", spot_name), excerpt=snippet[:280],
                            captured_at=pub or _now(), credibility=cred,
                            collected_by=collector, destination=dest,
                            domain=domain_of(url),
                            freshness_days=freshness_days(pub or _now()),
                            content_hash=content_fingerprint(snippet)))
    return out


async def _probe_spot_family(dest: str, items: List[Dict[str, Any]],
                             tpls: Tuple[str, ...], freshness: str,
                             existing_urls: set, collector: str,
                             probe_topn: int) -> Dict[str, Any]:
    """冻结榜前 N 景点逐点二查（并发 ≤4 + 阶段预算，同百度 fan-out 两型）。

    返回 {by_spot: {spot_id: [evidence_ids]}, evidences, failed, quota_error}。
    单点失败只记 failed（核查表该格占位）；SearchProviderError 属服务商终态——
    中止剩余任务（不再烧配额），整阶段由调用方降级为「仅槽位」+ 可见 thought。
    证据归属：evidences 表无景点列，spot_id 映射只活在编排期内存（评审 P1-2），
    由装配层写入核查表格内 evidence_ids，不改 DB schema。
    """
    targets = [it for it in items if it.get("spot_id")][:max(0, probe_topn)]
    by_spot: Dict[str, List[str]] = {}
    collected: List[Evidence] = []
    failed: List[str] = []
    quota_error: Optional[str] = None
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def one(it: Dict[str, Any]) -> None:
        nonlocal quota_error
        if quota_error:
            return
        async with sem:
            if quota_error:
                return
            try:
                evs = await asyncio.to_thread(_probe_spot_family_one, dest,
                                              str(it.get("name") or ""), tpls,
                                              freshness, existing_urls, collector)
            except SearchProviderError as e:
                quota_error = str(e)
                return
            except Exception:
                failed.append(str(it["spot_id"]))
                return
        if evs:
            collected.extend(evs)
            by_spot[str(it["spot_id"])] = [e.evidence_id for e in evs]
        else:
            failed.append(str(it["spot_id"]))

    tasks = [asyncio.create_task(one(it)) for it in targets]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=_PROBE_STAGE_BUDGET_S)
        for t in pending:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"by_spot": by_spot, "evidences": collected, "failed": failed,
            "quota_error": quota_error}


def _fill_persp_blocks(persp_sid: str, dest: str, spot_entities: List[Dict[str, Any]],
                       probes: Dict[str, List[str]], evidences: List[Any],
                       clar: Dict[str, Any], model: str) -> Dict[str, Any]:
    """视角专属块装配（同步，to_thread 调用；rough-cliff-vole P3）。

    行集**由冻结榜 seed**（每个 spot_id 恰一行，LLM 只填格不造行——多报/漏报的
    行一律不采纳，缺失格走「待核验」占位）；不造数守卫：格/规则声称 verified 但
    引用不出真实证据 id → 强制降为待核验。LLM 整体失败不炸管线：照常产出全占位表
    （占位可见即正确终态，同 spot_routes 降级哲学）。
    返回 {checklist_key: [...], rules_key: [...], packing_key: [...]}（组级 destination 分组）。
    """
    p = RT.perspective_spec(persp_sid)
    ck = p.get("checklist_key")
    if not ck or not spot_entities:
        return {}
    cols = tuple(p.get("checklist_columns") or ())
    ev_ids = {getattr(e, "evidence_id", "") for e in evidences}
    ev_by_id = {getattr(e, "evidence_id", ""): e for e in evidences}
    hard_q = tuple(p.get("hard_constraints") or ())
    constraints = "；".join(f"{q}={clar.get(q)}" for q in hard_q if str(clar.get(q) or "").strip())
    ev_lines = []
    for it in spot_entities:
        eids = [x for x in (probes.get(str(it.get("spot_id"))) or []) if x in ev_ids]
        digest = "；".join(f"[{x}] {str(getattr(ev_by_id[x], 'excerpt', ''))[:110]}"
                           for x in eids[:4])
        ev_lines.append(f"{it.get('spot_id')}|{it.get('name', '')}|{digest or '（二查未采到证据）'}")
    payload: Dict[str, Any] = {}
    try:
        payload = llm.chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研「{RT.SECTION_PLAN.get(persp_sid, persp_sid)}」专项核查填格员。"
                    f"逐景点填以下列：{'、'.join(cols)}。铁律："
                    "①每格只能引用该景点行内给出的 [e_xxxx] 证据，text 里保留关键数字/规则原文；"
                    "②该景点没有对应证据时**省略该格**（系统会填「待核验」），严禁凭常识造参数；"
                    "③rules 是给该行程的可执行铁律（≤5 条），每条必须引用 ≥1 个真实证据 id，"
                    "并在 refs 里写出它所依据的问卷约束字段名（可选值：" +
                    ("、".join(hard_q) or "无") + "）；"
                    "④packing 只收与目的地事实挂钩的行前清单项（气候/票证/设施类），"
                    "通用到任何城市都成立的项不收。"
                    '输出 JSON：{"rows":[{"spot_id":"…","cells":{"列名":{"text":"…",'
                    '"evidence_ids":["e_…"],"verified":true}}}],'
                    '"rules":[{"text":"…","refs":["字段"],"evidence_ids":["e_…"]}],'
                    '"packing":[{"item":"…","reason":"…","evidence_ids":["e_…"]}]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"目的地：{dest}\n本次问卷硬约束：{constraints or '（无）'}\n"
                    "景点证据行（spot_id|名称|证据摘要）：\n" + "\n".join(ev_lines)[:6000]
                )},
            ],
            max_tokens=3600, temperature=0.3, model=model,
            purpose="视角专属核查表与铁律填格",
        ) or {}
    except Exception:
        payload = {}
    rows_in = {str(r.get("spot_id")): r for r in (payload.get("rows") or [])
               if isinstance(r, dict)}
    items: List[Dict[str, Any]] = []
    for it in spot_entities:  # 行守恒：冻结榜每行恰一行
        cells_in = (rows_in.get(str(it.get("spot_id"))) or {}).get("cells") or {}
        cells = []
        for col in cols:
            raw = cells_in.get(col) if isinstance(cells_in.get(col), dict) else {}
            eids = [x for x in (raw.get("evidence_ids") or []) if x in ev_ids]
            text = str(raw.get("text") or "").strip()
            if raw.get("verified") and eids and text:
                cells.append({"column": col, "text": text,
                              "evidence_ids": eids, "verified": True})
            else:
                cells.append({"column": col, "text": "待核验（本次未采到）",
                              "evidence_ids": [], "verified": False})
        items.append({"spot_id": it.get("spot_id"), "spot_name": it.get("name", ""),
                      "cells": cells})
    out: Dict[str, Any] = {ck: [{"destination": dest, "items": items}]}
    rules_key = p.get("rules_key")
    if rules_key:
        rules = []
        for r in (payload.get("rules") or [])[:5]:
            if not isinstance(r, dict):
                continue
            eids = [x for x in (r.get("evidence_ids") or []) if x in ev_ids]
            refs = [q for q in (r.get("refs") or []) if str(q) in hard_q]
            text = str(r.get("text") or "").strip()
            if text and eids and refs:
                rules.append({"text": text, "refs": refs, "evidence_ids": eids})
        out[rules_key] = [{"destination": dest, "items": rules}]
    packing_key = p.get("packing_key")
    if packing_key:
        pack = []
        for r in (payload.get("packing") or [])[:8]:
            if not isinstance(r, dict):
                continue
            eids = [x for x in (r.get("evidence_ids") or []) if x in ev_ids]
            item = str(r.get("item") or "").strip()
            if item and eids:
                pack.append({"item": item, "reason": str(r.get("reason") or "").strip(),
                             "evidence_ids": eids})
        out[packing_key] = [{"destination": dest, "items": pack}]
    return out


def _shop_poi_one(dest: str, row: Dict[str, Any]) -> None:
    """商铺实体保真：百度 POI 精确命中则回填坐标与区域；LLM 只供价格与排队口碑。"""
    name = str(row.get("name") or "").strip()
    if not name:
        return
    r = baidu_client.place_search(name, dest)
    if not r.get("ok"):
        return
    hit = next((p for p in r["places"]
                if _name_hit(name, p.get("name")) and p.get("lat") is not None), None)
    if hit:
        row.update({"lat": hit["lat"], "lng": hit["lng"], "matched": True})
        if hit.get("area") and not row.get("area"):
            row["area"] = hit["area"]


async def _enrich_shops_with_poi(dest: str, shop_groups: List[Dict[str, Any]]) -> None:
    """商铺清单 POI 富化（就地回填 lat/lng/matched）；缺 AK 时静默跳过，前端出占位。"""
    if not shop_groups or not baidu_client.available():
        return
    rows = [x for grp in shop_groups if isinstance(grp, dict)
            for x in (grp.get("items") or []) if isinstance(x, dict)]
    if not rows:
        return

    async def one(x: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(_shop_poi_one, dest, x)
        except Exception:
            pass

    await _run_baidu_fanout([one(x) for x in rows])


def _shop_route_one(dest: str, origin: str, x: Dict[str, Any]) -> List[Dict[str, Any]]:
    """单商铺一条真实公交路线（transit 最优）；打车配额不适用（计划待确认 #4 拍板 transit）。"""
    coords = f"{x['lat']},{x['lng']}"
    t = baidu_client.direction("transit", origin, coords, city=dest)
    if not (t.get("ok") and t["routes"]):
        return []
    best = t["routes"][0]
    vehicles = " → ".join(dict.fromkeys(
        s["vehicle"] for s in best["steps"] if s.get("vehicle"))) or "公交/地铁"
    try:
        km = f"，全程约{round(float(best.get('distance_m') or 0) / 1000, 1)}公里"
    except (TypeError, ValueError):
        km = ""
    return [{"mode": "公交/地铁", "duration": _fmt_duration_sec(best.get("duration_s")),
             "cost": "", "transfer": vehicles[:80],
             "note": f"自市中心出发{km}", "evidence_ids": []}]


async def _attach_shop_routes(dest: str, shop_groups: List[Dict[str, Any]],
                              top_per_food: int) -> int:
    """商铺路线：每种美食按清单顺序取前 top_per_food 家 matched 商铺，并发挂公交路线。

    配额是硬约束（每食物 ≤top_per_food 条 direction 调用）；缺 AK / 无 matched 商铺时
    返回 0，前端走「数据源暂不可用」占位，不影响商铺清单本身。返回成功挂线数量。
    """
    if top_per_food <= 0 or not shop_groups or not baidu_client.available():
        return 0
    per_food: Dict[str, int] = {}
    targets: List[Dict[str, Any]] = []
    for grp in shop_groups:
        if not isinstance(grp, dict):
            continue
        for x in (grp.get("items") or []):
            if not isinstance(x, dict) or not x.get("matched"):
                continue
            if x.get("lat") is None or x.get("lng") is None:
                continue
            food = str(x.get("food") or "").strip() or "_"
            if per_food.get(food, 0) >= top_per_food:
                continue
            per_food[food] = per_food.get(food, 0) + 1
            targets.append(x)
    if not targets:
        return 0
    g = await asyncio.to_thread(baidu_client.geocode, dest, "")
    if not g.get("ok"):
        return 0
    origin = f"{g['lat']},{g['lng']}"

    async def one(x: Dict[str, Any]) -> None:
        try:
            routes = await asyncio.to_thread(_shop_route_one, dest, origin, x)
            if routes:
                x["routes"] = routes
        except Exception:
            pass

    await _run_baidu_fanout([one(x) for x in targets])
    return sum(1 for x in targets if x.get("routes"))


_CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _days_count(text: str) -> int:
    """用户原文的天数短语转整数（与 _DAY_PATTERNS 同一准绳，拿不到返回 0，不推断）。"""
    phrase = _days_from_text(text)
    if not phrase:
        return 0
    if phrase == "周末":
        return 2
    stem = phrase.rstrip("天日 ").strip()
    if stem.isdigit():
        return int(stem)
    if "十" in stem:
        tens, _, ones = stem.partition("十")
        return (_CN_DIGITS.get(tens, 1) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return _CN_DIGITS.get(stem, 0)


def _stop_arrival_digest(routes: List[Dict[str, Any]]) -> str:
    """景点抵达交通摘要：优先公交/地铁，退化打车；无真实路线数据返回空（占位不编造）。"""
    for mode_label, fmt in (("公交/地铁", "公交：{transfer}·{duration}"), ("打车", "打车：{duration}")):
        r = next((x for x in routes if x.get("mode") == mode_label), None)
        if r:
            filled = fmt.format(transfer=r.get("transfer") or mode_label,
                                duration=r.get("duration") or "")
            return filled.replace("：·", "：").replace("··", "·")
    return ""


def _assemble_itinerary(dest: str, spot_items: List[Dict[str, Any]],
                        route_groups: List[Dict[str, Any]],
                        shop_groups: List[Dict[str, Any]], days: int,
                        pace: int) -> List[Dict[str, Any]]:
    """一页视图（M3a/D2，guide 的 deep+expert 档）：把冻结榜单按名次逐日切分，抵达交通
    引用真实路线，商铺按清单顺序每天均衡挂一家——全部引用 spot_id/shop_id，不做名称二次匹配。

    天数优先用户原文与问卷答案（_days_count 双源），拿不到按 pace 推算；LLM 自由发挥的
    route_plan 在本档被整体覆盖（实体单一真相源原则的延伸）。
    纯函数、可单测、结果可复现。
    """
    if not spot_items:
        return []
    n = len(spot_items)
    span = days if days > 0 else max(1, -(-n // max(1, pace)))
    span = max(1, min(span, n))
    per = -(-n // span)
    span = -(-n // per)
    route_by_id = {row.get("spot_id"): (row.get("routes") or [])
                   for grp in (route_groups or []) if isinstance(grp, dict)
                   for row in (grp.get("items") or []) if isinstance(row, dict)}
    shops = [x for grp in (shop_groups or []) if isinstance(grp, dict)
             for x in (grp.get("items") or []) if isinstance(x, dict) and x.get("name")]
    days_out: List[Dict[str, Any]] = []
    si = 0
    for di in range(span):
        chunk = spot_items[di * per:(di + 1) * per]
        if not chunk:
            break
        stops: List[Dict[str, Any]] = []
        for it in chunk:
            stay = it.get("stay_minutes")
            tip = "；".join(x for x in (
                f"门票：{it['ticket']}" if it.get("ticket") else "",
                f"避峰：{it['off_peak']}" if it.get("off_peak") else "",
                f"位置：{it['area']}" if it.get("area") else "") if x)
            stops.append({
                "name": str(it.get("name") or ""),
                "spot_id": str(it.get("spot_id") or ""),
                "lat": it.get("lat"),
                "lng": it.get("lng"),
                "transport": _stop_arrival_digest(route_by_id.get(it.get("spot_id"), [])),
                "duration": f"约{stay}分钟" if stay else "",
                "tip": tip, "shop_id": "",
                "evidence_ids": list(it.get("evidence_ids") or []),
            })
        if si < len(shops):
            s = shops[si]
            si += 1
            price = s.get("price_per_person")
            stops.append({
                "name": f"美食停靠：{s.get('name')}",
                "spot_id": "",
                "transport": "",
                "duration": "约1小时",
                "tip": "；".join(x for x in (
                    str(s.get("food") or ""),
                    f"人均约{price}元（参考）" if price is not None else "",
                    str(s.get("queue_note") or "")) if x),
                "shop_id": str(s.get("shop_id") or ""),
                "evidence_ids": list(s.get("evidence_ids") or []),
            })
        days_out.append({"day": di + 1, "spots": stops})
    return [{"destination": dest, "days": days_out}]


# 逐景点舆情补充采集的并发预算（秒）：景点数×平台数 一次 fan-out，超时项直接缺省。
_SPOT_SENT_BUDGET_S = 90.0


async def _collect_spot_comments(spot_entities: List[Dict[str, Any]], platforms: List[str],
                                 region_q: str, per_take: int, freshness: str, dest: str,
                                 seen_urls: set,
                                 provider_errs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """逐景点舆情补充采集（并发 fan-out + 阶段预算）：每条评论挂 spot_id/spot_name，
    供 analyze_sentiment 做 (spot × platform) 双维聚合。

    - 只喂舆情统计、不生成证据对象：spots 在 analyze 之后，证据库口径不追溯扩容。
    - 相关性硬门槛：标题/摘要必须命中景点名（括号与空白归一后），杜绝题不对版。
    - 展平顺序按（榜单名次 × 平台序）确定 → 舆情样本可复现。
    - 服务商终态错误（欠费/Key）经 provider_errs 出参上报，由调用点出可见 thought 后降级。
    """
    jobs = [(rank, pidx, ent, plat)
            for rank, ent in enumerate(spot_entities)
            for pidx, plat in enumerate(platforms)]
    if not jobs or per_take <= 0:
        return []
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    errs: List[str] = provider_errs if provider_errs is not None else []

    async def one(rank: int, pidx: int, ent: Dict[str, Any], plat: str) -> None:
        spot_name = str(ent.get("name") or "").strip()
        if not spot_name:
            return
        if errs:  # 已确认欠费：一条即止，剩余任务不再烧检索
            buckets[(rank, pidx)] = []
            return
        queries = [f"{spot_name} 真实评价{region_q}", f"{spot_name} 避坑 攻略{region_q}"]
        try:
            results = await asyncio.to_thread(search.multi_search, queries, num=per_take + 4,
                                              site=PLATFORMS[plat].search_site,
                                              freshness=freshness)
            if not results:  # 站内受限时回退：全网检索 + 平台关键词
                results = await asyncio.to_thread(
                    search.multi_search, [f"{spot_name} 评价 {PLATFORM_LABEL.get(plat, plat)}{region_q}"],
                    num=per_take + 4, freshness=freshness)
        except SearchProviderError as e:
            errs.append(str(e))
            buckets[(rank, pidx)] = []
            return
        picked: List[Dict[str, Any]] = []
        for r in results:
            url, title = r.get("url", ""), r.get("title", "")
            text = (r.get("snippet") or title or "").strip()
            if not url or not text or not _name_hit(spot_name, f"{title} {text}"):
                continue
            detected = _source_type(url)
            picked.append({
                "text": text[:280], "url": url, "title": title,
                "platform": plat if detected in ("web", "official", "news") else detected,
                "destination": dest,
                "spot_id": str(ent.get("spot_id") or ""), "spot_name": spot_name,
            })
        buckets[(rank, pidx)] = picked[:per_take]

    tasks = [asyncio.create_task(one(*j)) for j in jobs]
    _, pending = await asyncio.wait(tasks, timeout=_SPOT_SENT_BUDGET_S)
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for rank, pidx, _ent, _plat in jobs:
        for c in buckets.get((rank, pidx), []):
            if c["url"] in seen_urls:
                continue
            seen_urls.add(c["url"])
            out.append(c)
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


# ── 撰写：LLM 逐章产出正文（行研/咨询级深度）─────────────
# 章节标题 / 章节提示 / 视角映射 / 字段归属全部由 research_types 单一真相源提供，
# 本模块只做渲染与编排（新增调研类型无需改这里）。


# 写稿诊断：记录「这一章是怎么写出来的」，供写后结构补齐与 structure_status 归类判定。
# 该键不在 _section 的字段白名单内，因此不会进 reports.data（有单测钉住）。
DIAG_KEY = "_diag"


def _diag(recovered: str, truncated: bool = False) -> Dict[str, Any]:
    """写稿路径诊断。recovered ∈ json / text_retry / failed / repaired。"""
    return {DIAG_KEY: {"recovered": recovered, "truncated": bool(truncated)}}


def _diag_of(st: Any) -> Dict[str, Any]:
    """取章节文本里的诊断块（缺失时返回空 dict，兼容旧数据与外部注入）。"""
    return (st or {}).get(DIAG_KEY) or {} if isinstance(st, dict) else {}


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


# ── 图表：全部来自真实分析数据（无 random）─────────────────────
# 注册表式 builder（批次②）：一类图 = 一个函数 + 一行注册。builder 在自己的函数里
# **同时**声明「怎么造」（数据源与降级）与「属哪章」（sections）——实现与归属同处，
# 结构上杜绝「挂了没实现 / 实现了没挂」这类分居两处的漂移（图表串章的历史根因）。
# 舆情两图与词云的归属：正式舆情章（deep/expert 档）与旧报告级舆情面板（quick 档，
# 见 _assemble_report 的插入逻辑）双挂——两档各自只命中一个，不会重复。



# ── 组装报告 ─────────────────────────────────────────────
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
    data_grid_sections = set(spec["data_grid_sections"])

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
