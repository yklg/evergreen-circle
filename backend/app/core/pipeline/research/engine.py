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
import json
import time
import urllib.parse
import uuid
from collections import Counter
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core import db
from app.core import trace
from app.core import audit
from app.core.audit import decide_rework, llm_quality_review
from app.core.runtime_config import get_effective_settings
from app.core.credibility import score_evidence, assess_viral
from app.core.fetcher import domain_of
from app.core.platforms import PLATFORMS
from app.core import llm
from app.core.llm import LLMNotConfigured, TOKEN_USAGE
from app.core.metrics import compute_report_metrics, merge_quality_into_metrics
from app.core.models import Evidence, Envelope
from app.core import research_types as RT
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core import scoring as SC
from app.core.schemas import coerce_spot_ranking
from app.core import search
from app.core.search import SearchProviderError
from app.core.sentiment import analyze_sentiment, PLATFORM_LABEL
from app.data import expert_by_id

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
from app.core.pipeline.research.analyze import (  # noqa: E402,F401
    _ANALYSIS_KEY_SCHEMA,
    _ENTITY_STAGE_KEYS,
    _STRUCTURED_SCHEMA,
    DIAG_KEY,
    _enforce_dest_rows,
    _sanitize_radar,
    _sanitize_evidence_rows,
    _sanitize_season,
    _sanitize_trends,
    _sanitize_contradictions,
    _analyze,
    _analyze_structured,
    _sanitize_share,
    _sanitize_livelihood_cost,
    _sanitize_action_priorities,
    _sanitize_consensus_split,
    _fallback_claims,
    _diag,
    _diag_of,
)
from app.core.pipeline.research.spots import (  # noqa: E402,F401
    _BAIDU_STAGE_BUDGET_S,
    _PROBE_STAGE_BUDGET_S,
    _PROBE_CONCURRENCY,
    _SPOT_SENT_BUDGET_S,
    _CN_DIGITS,
    _extract_spot_signals,
    _run_baidu_fanout,
    _resolve_one_spot,
    _resolve_spot_entities,
    _fmt_duration_sec,
    _spot_routes_one,
    _build_spot_routes,
    _probe_spot_family_one,
    _probe_spot_family,
    _shop_poi_one,
    _enrich_shops_with_poi,
    _shop_route_one,
    _attach_shop_routes,
    _days_count,
    _stop_arrival_digest,
    _assemble_itinerary,
    _collect_spot_comments,
)
from app.core.pipeline.research.perspective import (  # noqa: E402,F401
    _fill_persp_blocks,
)
from app.core.pipeline.research.writer import (  # noqa: E402,F401
    _STRUCTURED_LABEL,
    _structureless,
    _structure_status,
    _summarize_structure,
    _write_single_section,
    _repair_missing_structure,
    _write_sentiment_narrative,
    _rewrite_section,
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
