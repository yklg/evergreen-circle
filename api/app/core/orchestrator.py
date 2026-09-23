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
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.core import charts as C
from app.core import db
from app.core import trace
from app.core.audit import evaluate_quality, decide_rework, llm_quality_review
from app.core.runtime_config import get_effective_settings
from app.core.credibility import score_evidence, freshness_days, assess_viral
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core.fetcher import domain_of, fetch_page
from app.core.platforms import PLATFORMS, classify_platform
from app.core.llm import (chat, chat_json, last_finish_reason, is_temporary_unavailable,
                          LLMModelUnavailable, LLMNotConfigured, TOKEN_USAGE)
from app.core.metrics import compute_report_metrics, merge_quality_into_metrics
from app.core.models import Evidence, Envelope, make_claim
from app.core import research_types as RT
from app.core.research_types import DEFAULT_RESEARCH_TYPE
from app.core import scoring as SC
from app.core.schemas import _filter_eids, coerce_spot_ranking, coerce_structured
from app.core.search import multi_search, SearchProviderError
from app.core.sentiment import analyze_sentiment, PLATFORM_LABEL
from app.core.textquality import is_relevant_content
from app.data import expert_by_id, load_experts
from app.services import baidu as baidu_client


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


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
    },
    "deep": {
        "label": "深度模式",
        "max_angles": 6, "fetch_per_destination": 12, "platform_per": 8,
        "freshness": "oneYear", "rework_rounds": 1,
        "min_paragraphs": 5, "para_words": "180-280", "section_max_tokens": 8000,
        "analyze_max_tokens": 8000, "structured_max_tokens": 8000,
        "sentiment_destinations": 3, "platform_take": 8,
        "spot_sent_take": 4,
        "spot_topn": 7,
        "shop_route_topn": 2,
        # 行程路线章（D2，deep 起出）：用户未写天数时按每天 N 景点推算行程跨度
        "spot_day_pace": 4,
    },
    "expert": {
        "label": "专家级模式",
        "max_angles": 9, "fetch_per_destination": 16, "platform_per": 10,
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
    },
}

# 核心章用质量最高的模型档，其余用辅助档（属「模型分配」旋钮，与 MODE_CONFIG 同类，
# 故留在编排层而非语义注册表）。覆盖两类型各自最吃分析的章节。
CORE_SECTIONS = frozenset({
    "summary", "conclusion", "contrarian",
    "spots", "route", "budget",      # 游玩攻略
    "safety", "value", "verdict",    # 调研评估
})


# 单条调研任务的「用户指定分析模型」覆盖（仅 core/aux 档生效，fast 杂务不动）。
# ContextVar 随每个 asyncio pipeline 协程隔离；run_pipeline 入口 set 覆盖式写入，
# 不同任务之间无串扰（且每次 set 覆盖旧值，无累积）。
_pipeline_model_override: ContextVar[str] = ContextVar("_pipeline_model_override", default="")


def _model(tier: str) -> str:
    """tier: 'core' | 'aux' | 'fast' → 实际模型名。

    每次调用都读运行时有效配置（env 默认 + 界面覆盖），
    因此用户在「模型配置」改了模型矩阵后下一次调研立即生效，无需重启。

    override：若本次调研用户在 HomePage 指定了分析模型（core/aux 档），
    则核心章与辅助章统一用该模型；fast 杂务（intake/情感分类/专家指派）
    始终走 settings.fast，不被覆盖。返回**永远是纯模型名**（直接作 LLM API
    的 model 参数），绝不带任何后缀——(override) 标注只在 trace 展示层加。
    """
    override = _pipeline_model_override.get()
    s = get_effective_settings()
    if tier == "fast":
        # 杂务快速档不受 override 影响，始终按 settings
        return s.get("llm_model_fast") or ""
    if override:
        # 核心章 / 辅助章统一用用户指定的分析模型
        return override
    if tier == "core":
        return s.get("llm_model_core") or ""
    return s.get("llm_model_aux") or ""


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


class GuideSingleDestinationError(ValueError):
    """guide 档位结构性约束：地图/路线/评分配额均以单目的地为前提（计划待确认 #7 拍板硬拒绝）。"""


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

    纯同步（内含阻塞 chat_json）；调用方在异步管线里须用 `await asyncio.to_thread(_rewrite_section, ...)`
    包裹，避免冻结事件循环（P1-2，与 run_pipeline 的 to_thread 惯例一致）。
    """
    digest = extra_context.get("digest", "")
    absorbed = extra_context.get("absorbed_evidence_ids", [])
    existing = "\n".join(section.get("paragraphs", []))
    try:
        data = chat_json(
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
            model=_model("core"), purpose=f"基于新证据重写章节：{section.get('title','')}",
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

    只读 sections[].structured（{"type","data"} 形状），旧报告/assessment 无这些键时
    自然返回空串——不造假数字，也不影响旧精炼。"""
    by_type: Dict[str, Any] = {}
    for s in sections:
        st = s.get("structured")
        if isinstance(st, dict) and st.get("data"):
            by_type.setdefault(str(st.get("type")), st["data"])

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
            data = chat_json(
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
                model=_model("core"), purpose=f"生成一页纸精炼：{report_id}",
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


# ── 目的地发现（LLM 路径 + 正则兜底）──────────────────────
# 正则兜底用的静态候选目的地映射（按常见关键词命中，毫秒级、无需 LLM）。
_FALLBACK_DESTINATION_MAP: Dict[str, List[str]] = {
    "三亚": ["海口", "陵水", "万宁", "厦门"],
    "大理": ["丽江", "香格里拉", "腾冲", "西双版纳"],
    "丽江": ["大理", "香格里拉", "泸沽湖", "腾冲"],
    "成都": ["重庆", "西安", "昆明", "长沙"],
    "重庆": ["成都", "贵阳", "西安", "武汉"],
    "杭州": ["苏州", "南京", "绍兴", "上海"],
    "上海": ["杭州", "苏州", "南京", "厦门"],
    "北京": ["西安", "南京", "洛阳", "天津"],
    "西安": ["洛阳", "南京", "北京", "成都"],
    "厦门": ["泉州", "福州", "平潭", "青岛"],
    "青岛": ["大连", "威海", "烟台", "厦门"],
    "广州": ["深圳", "佛山", "珠海", "厦门"],
    "深圳": ["广州", "珠海", "香港", "厦门"],
    "长沙": ["武汉", "南昌", "重庆", "广州"],
    "昆明": ["大理", "贵阳", "南宁", "成都"],
    "桂林": ["阳朔", "贵阳", "张家界", "黔东南"],
    "贵阳": ["昆明", "重庆", "桂林", "黔东南"],
    "哈尔滨": ["长春", "沈阳", "漠河", "雪乡"],
    "乌鲁木齐": ["喀纳斯", "伊犁", "敦煌", "兰州"],
    "拉萨": ["林芝", "日喀则", "西宁", "香格里拉"],
    "西宁": ["兰州", "张掖", "敦煌", "拉萨"],
    "东京": ["大阪", "京都", "札幌", "首尔"],
    "大阪": ["东京", "京都", "福冈", "首尔"],
    "首尔": ["釜山", "济州", "东京", "大阪"],
    "曼谷": ["清迈", "普吉岛", "吉隆坡", "新加坡"],
    "新加坡": ["吉隆坡", "曼谷", "巴厘岛", "香港"],
    "巴厘岛": ["普吉岛", "长滩岛", "苏梅岛", "龙目岛"],
    "香港": ["澳门", "深圳", "台北", "新加坡"],
    "巴黎": ["罗马", "巴塞罗那", "伦敦", "柏林"],
    "伦敦": ["巴黎", "阿姆斯特丹", "柏林", "爱丁堡"],
    "纽约": ["洛杉矶", "芝加哥", "多伦多", "波士顿"],
    "悉尼": ["墨尔本", "奥克兰", "布里斯班", "黄金海岸"],
}
_FALLBACK_DOMAIN_MAP: Dict[str, str] = {
    "海岛": "海岛度假", "海滩": "海岛度假", "冲浪": "海岛度假",
    "古镇": "古镇水乡", "水乡": "古镇水乡", "古城": "古镇水乡",
    "自驾": "自驾公路", "公路": "自驾公路",
    "宜居": "移居/宜居", "移居": "移居/宜居", "长居": "移居/宜居", "养老": "移居/宜居",
    "徒步": "山岳徒步", "登山": "山岳徒步", "雪山": "山岳徒步",
    "亲子": "亲子研学", "带娃": "亲子研学", "研学": "亲子研学",
    "美食": "美食之旅", "小吃": "美食之旅",
    "滑雪": "冰雪运动", "冰雪": "冰雪运动",
    "摄影": "摄影采风", "出片": "摄影采风", "机位": "摄影采风",
    "温泉": "康养温泉", "康养": "康养温泉",
    "避暑": "避暑度假", "避寒": "避寒度假",
    "古建": "古建人文", "人文": "古建人文", "博物馆": "古建人文",
    "出境": "出境游", "签证": "出境游", "海外": "出境游",
    "预算": "预算与成本", "性价比": "预算与成本",
    "交通": "交通可达性", "高铁": "交通可达性", "航班": "交通可达性",
}


def _discover_scope(query: str) -> Dict[str, Any]:
    """领域识别 + 目的地自动发现（前置侦察，LLM 路径）。

    返回 {"subject", "domain", "candidates", "fallback"}。
    用 aux 模型（已关思考、JSON 稳定）；失败重试一次，
    仍失败则交由 _discover_scope_fallback 返回正则兜底（fallback=True），绝不抛错。
    """
    msgs = [
        {"role": "system", "content": (
            "你是旅游调研总监，负责开题前的『主题识别 + 候选目的地发现』。"
            "根据用户一句话需求，判断：①真正要调研的目的地/主题是什么（城市/景区/区域全称）；"
            "②它属于什么旅游细分领域（如 海岛度假、古镇水乡、自驾公路、移居宜居、亲子研学）；"
            "③围绕该主题，尽可能多地列出值得一并调研的真实候选目的地（8-12 个，"
            "必须是真实存在、可搜索的城市/景区，按可对比性与知名度从高到低排列，不要编造）。"
            '只输出 JSON：{"subject":"目的地/主题全称","domain":"细分领域","candidates":["候选目的地1","候选目的地2"]}。'
            "candidates 不要包含调研对象自身。只输出 JSON，不要任何解释或思考过程。"
        )},
        {"role": "user", "content": query},
    ]
    for _ in range(2):
        try:
            data = chat_json(
                msgs, max_tokens=1500, temperature=0.3,
                model=_model("aux"), purpose="主题识别+目的地自动发现",
            )
            if isinstance(data, dict) and (data.get("subject") or data.get("candidates")):
                subject = str(data.get("subject") or "").strip()
                domain = str(data.get("domain") or "").strip()
                comps = [
                    str(c).strip() for c in (data.get("candidates") or [])
                    if str(c).strip() and str(c).strip() != subject
                ]
                seen = set()
                comps = [c for c in comps if not (c in seen or seen.add(c))]
                return {
                    "subject": subject, "domain": domain,
                    "candidates": comps[:12], "fallback": False,
                }
        except Exception:
            pass
    # LLM 全失败 → 正则兜底（不抛，保证流程继续）
    return _discover_scope_fallback(query)


def _discover_scope_fallback(query: str) -> Dict[str, Any]:
    """纯正则 / 静态映射兜底：无 LLM 调用，毫秒级返回。

    命中已知目的地 → 给出其常见候选对比目的地与推测主体；否则尝试从引号抽取候选。
    始终返回 fallback=True（提示前端这是自动识别候选，需用户核对）。
    """
    q = (query or "").strip()
    low = q.lower()
    candidates: List[str] = []
    subject = ""
    for key, vals in _FALLBACK_DESTINATION_MAP.items():
        if key in low:
            candidates = [v for v in vals if v.lower() != key]
            subject = key
            break
    if not candidates:
        cand = re.findall(r"[‘’'\"\“\”]([^‘’'\"\“\”]{2,20})[‘’'\"\“\”]", q)
        candidates = [c.strip() for c in cand if c.strip()]
    domain = ""
    for kw, dom in _FALLBACK_DOMAIN_MAP.items():
        if kw in low:
            domain = dom
            break
    return {
        "subject": subject, "domain": domain,
        "candidates": candidates[:12], "fallback": True,
    }


# ── 目的地集合政策：唯一判据 + 唯一来源 + 三跳兜底 ──────────────
# 历史缺陷：模型被提示词命令「必须凑够 3-6 个对比目的地」，用户只说「我想去上海玩三天」
# 也会产出五城报告。根治办法是把「谁是目的地」的判定权收回给用户原文与勾选，
# 模型只当候选提供者；判据与取数路径各只有一处实现。
_MAX_DEST_NAME_LEN = 16
_MAX_DESTINATIONS = 6
# 只拒绝「一眼不是地名」的需求短语；不加字符白名单，否则「乌镇」「Lake Como」类真实地名会被误杀。
_DEST_REJECT_WORDS = ("对比", "比较", "评估", "调研", "攻略", "路线", "与", "和", "、", "/", "vs")
# 需求句里常见的动词/疑问短语：命中即说明这串是「一句话」而不是地名（历史缺陷：整句需求被当目的地）。
_DEST_REJECT_PHRASES = ("我想", "想去", "帮我", "推荐", "规划", "怎么玩", "多久", "多少钱", "最好")

# 行程天数的**准绳**正则：只认用户原文写法（阿拉伯数字 / 中文数词 / 周末），按序取首个命中。
# 计划提示词不再向模型索取天数——没有通道就没有自扩。
_DAY_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\d+\s*[天日]"),
    re.compile(r"[一两二三四五六七八九十]{1,2}\s*天"),
    re.compile("周末"),
)

# 三跳都拿不到目的地时的占位名：宁可带着降级横幅空跑并在报告里如实标注，也不编造城市。
_NO_DESTINATION = "目的地"
# trace 里的固定 step 名（前端「决策日志」按它检索降级事实）
_DEST_PLAN_STEP = "目的地集合判定"
_DEST_RETRY_PURPOSE = "识别目的地（兜底重试）"


def _usable_destination(name: Any) -> bool:
    """「这串字符能不能当一个目的地名」的唯一判据（四条取数路径共用）。"""
    s = str(name or "").strip()
    if not (2 <= len(s) <= _MAX_DEST_NAME_LEN) or s.isdigit():
        return False
    low = s.lower()
    return not any(w in low for w in _DEST_REJECT_WORDS + _DEST_REJECT_PHRASES)


def _core_name(name: Any) -> str:
    """比对用的核心名：**只剥「市」**。剥「省/自治区/特别行政区」会把「吉林省」并到「吉林市」；
    剩余不足 2 字不剥（「市」本身不是地名）。"""
    s = str(name or "").strip()
    if s.endswith("市") and len(s) >= 3:
        return s[:-1]
    return s


def _mentioned_in_text(name: Any, text: str) -> bool:
    """目的地名是否出现在需求原文里（「上海」↔「上海市」等价，ASCII 大小写不敏感）。
    只做「候选名 ⊆ 原文」的单向判定；反向包含会让「海」这类短串误命中「上海」。"""
    core = _core_name(name)
    if len(core) < 2:
        return False
    return core.lower() in str(text or "").lower()


def _days_from_text(text: str) -> str:
    """抽取用户原文里的行程时长短语；命中即返回**原文片段本身**，保证天数角度必有出处。"""
    s = str(text or "")
    for pat in _DAY_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(0).strip()
    return ""


def _checked_destinations(clar: Dict[str, Any]) -> List[str]:
    """问卷里勾选/填写的目的地（兼容单字符串答案），仅过判据、不看原文。"""
    raw = (clar or {}).get("destinations") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in raw if _usable_destination(x)]


def _dedupe_names(names: List[str]) -> List[str]:
    """按核心名去重保序（「上海」与「上海市」算同一个）。"""
    out: List[str] = []
    seen = set()
    for n in names:
        key = _core_name(n).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n.strip())
    return out


def locked_destination(query: str, candidates: Any) -> str:
    """需求原文是否**唯一点名**了候选池里的一个目的地——问卷层与计划层共用的锁定判据。

    问卷据此跳过目的地题（用户已说清的事不再追问），计划层据此保证「不出题 ⇔ 集合
    就是锁定名」；两处必须同一函数，否则会出现问卷锁定了大理、计划却反问/扩城的分叉。
    候选池只认目的地发现给出的 candidates：subject 可能只是主题短语（「亲子游哪里好」
    的兜底 subject 是「亲子游」），并入会把提问句误判成锁定。
    """
    pool = [str(c).strip() for c in (candidates or [])]
    mentioned = [c for c in _dedupe_names(pool)
                 if _usable_destination(c) and _mentioned_in_text(c, query)]
    return mentioned[0] if len(mentioned) == 1 else ""


# 出发地题允许留空或写模糊语；这些短语穿透 `_usable_destination`（「本地」是合法 2 字串），
# 必须在消费点整串精确匹配跳过，否则会生成「还没定出发 城际交通方式…」这类脏检索角度。
_ORIGIN_SKIP_WORDS = ("还没定", "待定", "不确定", "不知道", "还没想好", "再说",
                      "本地", "本地出发", "无所谓", "随便")


def origin_answer(clar: Dict[str, Any]) -> str:
    """出发地答案 → 城际交通检索凭据；仅当整串是一个可用地名时生效，否则视为未填。"""
    s = str((clar or {}).get("origin") or "").strip()
    if not s or s in _ORIGIN_SKIP_WORDS or not _usable_destination(s):
        return ""
    return s


def _destination_set(query: str, clar: Dict[str, Any],
                     plan_candidates: List[str]) -> Tuple[List[str], str]:
    """目的地集合的**唯一**来源：问卷勾选 ∪ 需求原文点过名的候选（并集只增不减，上限 6）。

    计划 LLM 给的候选只作为「待验证的池子」——用户没提的一律不纳入，这是防自扩的关键闸门。
    返回 (destinations, source)；source ∈ clarify/query/…，空列表表示需要走兜底链。
    """
    checked = [d for d in _checked_destinations(clar) if _usable_destination(d)]
    mentioned = [c for c in plan_candidates
                 if _usable_destination(c) and _mentioned_in_text(c, query)]
    merged = _dedupe_names(checked + mentioned)
    if not merged:
        return [], ""
    source = "clarify" if checked else "query"
    return merged[:_MAX_DESTINATIONS], source


def _orthogonal_angles(raw_angles: Any, destinations: List[str], days_phrase: str,
                       spec: Dict[str, Any], max_angles: int,
                       origin_phrase: str = "",
                       focus_keywords: Tuple[str, ...] = ()) -> List[str]:
    """把计划给出的角度整形成与目的地**正交**、且体现用户显式答题的角度集。

    规则（顺序即优先级）：
    1. 剔掉含任一目的地名的角度——采集层按 `f"{destination} {angle}"` 拼检索词，
       角度里再带地名会重复、带别的城市名会污染证据归属（历史缺陷的直接根因）；
    2. 剔掉含具体天数的角度——天数只许来自用户原文；注册表维度词「行程路线」不含天数，不受影响；
    3. 用户勾选了侧重维度（`focus_keywords`）→ 命中的角度**稳定排序前置**，
       截断时优先保住它们；未命中的原有相对次序不变；
    4. 原文/答案确证了天数且该类型配了 `days_angle_tpl` → 追加**恰好 1 条**天数角度；
       出发地答案可用且配了 `origin_angle_tpl` → 同样**恰好 1 条**城际交通角度；
    5. 全被剔空 → 回落注册表角度（用已知可靠的角度，不送空集）；
    6. 夹到 max_angles，并为天数/出发地两条确定性角度预留格子，保证不被挤掉。
    始终返回新列表，绝不改动注册表里的共享元组。
    """
    names = [_core_name(d) for d in destinations]

    def _conflicting(angle: str) -> bool:
        low = angle.lower()
        if any(n and n.lower() in low for n in names):
            return True
        return any(p.search(angle) for p in _DAY_PATTERNS)

    kept: List[str] = []
    for a in (raw_angles if isinstance(raw_angles, (list, tuple)) else []):
        if not isinstance(a, str):
            continue
        s = a.strip()
        if s and not _conflicting(s) and s not in kept:
            kept.append(s)

    if focus_keywords:
        lows = [k.lower() for k in focus_keywords if k]
        # sorted 稳定：命中侧重关键词的前置，其余保持模型给出的相对次序
        kept = sorted(kept, key=lambda a: 0 if any(k in a.lower() for k in lows) else 1)

    tpl = str(spec.get("days_angle_tpl") or "")
    days_angle = tpl.format(days=days_phrase).strip() if (days_phrase and tpl) else ""
    optpl = str(spec.get("origin_angle_tpl") or "")
    origin_angle = optpl.format(origin=origin_phrase).strip() if (origin_phrase and optpl) else ""
    reserve = (1 if days_angle else 0) + (1 if origin_angle else 0)
    kept = kept[:max(0, max_angles - reserve)]
    if origin_angle and origin_angle not in kept:
        kept.append(origin_angle)
    if days_angle and days_angle not in kept:
        kept.append(days_angle)
    if not kept:
        kept = [str(a) for a in spec["angles"]][:max_angles]
    return kept


def _plan_trace(task_id: str, decision: str, detail: str = "") -> None:
    """把「目的地是谁、从哪条路径来」写进决策日志（trace 本身持久化到 DB）。"""
    trace.record_manual_span(task_id, "L3-001", "intake", _DEST_PLAN_STEP,
                             detail=detail, decision=decision)


def _fallback_destination(query: str, research_type: str, task_id: str) -> Tuple[str, str]:
    """计划没拿到任何「用户点过名」的目的地时的三跳兜底，按序取第一个过判据的结果。

    三跳全部复用既有能力，不新写第四套地名识别：
    hop1 发现阶段缓存的 subject（零 LLM）→ hop2 静态地名表（`_discover_scope_fallback`）
    → hop3 一次 fast 档小模型专问。全 miss 则返回 ("", "fallback")。
    **模型不可用/限速类异常一律原样上抛**：把 404 伪装成「目的地自动识别」就是遮盖症状。
    """
    try:
        cached = db.get_discovery_cache(db._query_hash(query)) or {}
        subject = str(cached.get("subject") or "").strip()
    except Exception as e:  # noqa: BLE001 —— 缓存读失败必须留痕后继续下跳，不静默
        _plan_trace(task_id, "hop1 读发现缓存失败，改用静态地名表。",
                    f"{type(e).__name__}: {e}")
        subject = ""
    if _usable_destination(subject):
        return subject, "cache"

    subject = str((_discover_scope_fallback(query) or {}).get("subject") or "").strip()
    if _usable_destination(subject):
        return subject, "static"

    subject = _retry_destination(query, research_type, task_id)
    return (subject, "retry") if _usable_destination(subject) else ("", "fallback")


def _retry_destination(query: str, research_type: str, task_id: str) -> str:
    """最后一跳：单独问一次小模型「这句需求里的目的地是谁」（不做其它拆解，尽量便宜）。"""
    spec = RT.type_spec(research_type)
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研开题助手，本次任务类型是「{spec['label']}」。"
                    "只做一件事：从用户这句需求里**抽取**它提到的目的地名称。"
                    "不要推荐、不要补充用户没提到的城市/景区。"
                    '只输出 JSON：{"destination":"目的地名（城市/景区/区域，不要写成短语或整句）"}。'
                )},
                {"role": "user", "content": query},
            ],
            max_tokens=200, temperature=0.0, model=_model("fast"),
            purpose=_DEST_RETRY_PURPOSE,
        )
    except Exception as e:  # noqa: BLE001
        # 模型本身不可用/没配 → 按既有契约上抛（runner 有对应报错分支），不降级
        if isinstance(e, (LLMNotConfigured, LLMModelUnavailable)) or is_temporary_unavailable(e):
            raise
        _plan_trace(task_id, "hop3 小模型重试失败，目的地降级为占位。", f"{type(e).__name__}: {e}")
        return ""
    if isinstance(data, dict):
        return str(data.get("destination") or data.get("subject") or "").strip()
    return str(data or "").strip()


def _plan_research(query: str, clar: Dict[str, Any], max_angles: int = 7,
                   research_type: str = DEFAULT_RESEARCH_TYPE,
                   task_id: str = "") -> Dict[str, Any]:
    """拆解调研计划：目的地只认用户点过名的，角度与目的地正交，天数只取原文。

    政策（详见改造计划 §4/§6）：
    - 模型只负责抽取与补全，**不得自扩调研范围**；它给出的候选只有出现在需求原文里
      （或被问卷勾选）才被采纳，其余丢弃。
    - 检索角度里不许夹带地名或具体天数；行程天数只来自用户原文（`_DAY_PATTERNS` 准绳）。
    - 拿不到目的地时走三跳兜底，并把降级事实写进 trace 与运行中横幅。
    - 返回 dict 的 `degraded` / `dest_source` 属**内部字段**：只供编排层推 SSE 与写 trace，不进报告 payload。
    """
    clar = clar or {}
    spec = RT.type_spec(research_type)
    clar_text = "；".join(f"{k}: {v}" for k, v in clar.items()
                         if v and not str(k).startswith("_"))
    checked = _checked_destinations(clar)
    region = str(clar.get("_region") or "").strip()
    candidates: List[str] = []
    focus: List[str] = []
    raw_angles: List[str] = []
    plan_error = ""
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研总监，本次任务类型是「{spec['label']}」（{spec['subtitle']}）。"
                    "从用户的调研需求里**抽取**信息，不要扩大范围、不要替换用户提到的对象、"
                    "不要补充用户没提的目的地。输出 JSON："
                    '{"subject":"用户要调研的目的地全称（单个城市/景区名，不要写成短语）",'
                    '"region":"目的地所属省份/国家（用于消歧，如 云南省、海南省、日本）",'
                    '"destinations":["你判断用户可能一并关心的候选目的地"],'
                    '"focus":["本次重点维度，如 交通/住宿/预算/口碑"],'
                    '"search_angles":["针对每个目的地的搜索角度短语"]}。'
                    "destinations 只是**候选**：只有用户在需求里点过名或勾选过的才会被采纳，"
                    "其余会被系统丢弃——绝不要为了凑齐对比对象而塞进用户没提的城市。"
                    "search_angles 每条只写维度短语（如 交通攻略、住宿推荐、门票与价格、避坑指南）："
                    "①不得含任何城市/景区名（检索词会自动带上目的地，重复地名会污染结果）；"
                    "②不得含具体天数（行程时长只依用户原文，不接受你推断的天数）。"
                    f"region 要给一个能精准消歧的行政区/国家短语（避免同名地歧义，如「凤凰」应识别为「湖南省湘西州」）。"
                    f"search_angles 给 {max_angles} 个，务必包含「最新攻略2026」「官方公告」等时效性角度以抓取最新信息。"
                    "只输出 JSON。"
                )},
                {"role": "user", "content": (
                    f"调研需求：{query}\n用户补充：{clar_text or '无'}\n"
                    f"用户已勾选的目的地（这些一定会被纳入，你只需补全维度与角度）："
                    f"{('、'.join(checked)) or '无'}"
                )},
            ],
            max_tokens=2000,
            temperature=0.3,
            model=_model("fast"),
            purpose="拆解调研计划（目的地/维度/搜索角度）",
        )
        if isinstance(data, dict):
            candidates = [str(x).strip() for x in (data.get("destinations") or [])
                          if isinstance(x, str) and x.strip()]
            subject = str(data.get("subject") or "").strip()
            if subject:
                candidates.insert(0, subject)   # subject 也只当候选，同样过判据与原文校验
            focus = [f for f in data.get("focus", []) if isinstance(f, str)]
            region = str(data.get("region") or "").strip() or region
            raw_angles = [a for a in (data.get("search_angles") or []) if isinstance(a, str)]
    except Exception as e:  # noqa: BLE001
        if isinstance(e, (LLMNotConfigured, LLMModelUnavailable)) or is_temporary_unavailable(e):
            raise                          # 模型不可用不是「识别不到目的地」，必须如实报错
        plan_error = f"{type(e).__name__}: {e}"

    destinations, source = _destination_set(query, clar, candidates)
    degraded = False
    if not destinations:
        name, source = _fallback_destination(query, research_type, task_id)
        degraded = True
        destinations = [name] if name else [_NO_DESTINATION]

    # 终点闸门：问卷题已改单选、submit_clarify 也已拒，这里兜住「原文点名多目的地」
    # 与旧缓存问卷两条漏网路径——在采集/算分之前拒，不浪费后续预算。
    if research_type == "guide" and len([d for d in destinations if d != _NO_DESTINATION]) > 1:
        _plan_trace(task_id, f"guide 多目的地被拒（{'、'.join(destinations)}）。",
                    f"来源={source}\n需求原文：{query}\n勾选：{('、'.join(checked)) or '无'}")
        raise GuideSingleDestinationError(
            f"游玩攻略报告目前仅支持单个目的地，识别到 {len(destinations)} 个"
            f"（{'、'.join(destinations)}）。请改为单个城市/景区，或改用「调研评估」类型做对比。")

    # 天数判据双源：用户原文优先（显式说过就以它为准），原文没有才认问卷答案。
    days_phrase = _days_from_text(query) or _days_from_text(str(clar.get("days") or ""))
    origin_phrase = origin_answer(clar)
    focus_qid = str(spec.get("focus_qid") or "")
    sel_raw = clar.get(focus_qid) if focus_qid else None
    selected = [str(x).strip() for x in
                (sel_raw if isinstance(sel_raw, (list, tuple)) else ([sel_raw] if sel_raw else []))
                if str(x).strip()]
    kw_map = spec.get("focus_angle_keywords") or {}
    focus_keywords: List[str] = []
    for opt in selected:
        for k in kw_map.get(opt, ()):
            if k not in focus_keywords:
                focus_keywords.append(k)

    angles = _orthogonal_angles(raw_angles, destinations, days_phrase, spec, max_angles,
                                origin_phrase, tuple(focus_keywords))
    if degraded or plan_error:
        detail = (f"计划候选：{('、'.join(candidates)) or '无'}\n"
                  f"需求原文：{query}\n勾选：{('、'.join(checked)) or '无'}")
        if plan_error:
            detail += f"\n计划 LLM 异常：{plan_error}"
        _plan_trace(task_id, f"目的地降级为「{'、'.join(destinations)}」（来源={source}）；"
                             "已在运行中提示用户核对。", detail)
    merged_focus = selected + [f for f in focus if f not in selected]
    return {
        "destinations": destinations,
        "focus": merged_focus or ["交通", "住宿", "预算", "口碑"],
        "angles": angles,
        "region": region,
        "degraded": degraded,
        "dest_source": source,
    }


# ── 编排：LLM 动态指派专家（含理由 + 降级三态）────────────────
# 团队配额：(职级, 下限, 上限, 名册里的角色称呼)。同一份常量既拼进指派 prompt、
# 又驱动 _composition_violations —— 此前「1×L3 + 1-2×L2 + 3-6×L1」只是 prompt 里的
# 口头承诺，代码一行没校验（TC-E07 钉的就是这个洞）。
_TEAM_QUOTA = (("L3", 1, 1, "决策层统筹"), ("L2", 1, 2, "策略顾问"), ("L1", 3, 6, "执行专家"))
_TEAM_QUOTA_DESC = "、".join(
    (f"{lo}-{hi} 位 {lvl} {name}" if lo != hi else f"{lo} 位 {lvl} {name}")
    for lvl, lo, hi, name in _TEAM_QUOTA)
# 兜底组队按职级从名册现算（不再写死 id 清单）；函数组优先，保住舆情位的语义。
_FALLBACK_PICK = {"L3": 1, "L2": 2, "L1": 3}


def _levels_of(ids, level_of: Dict[str, str]) -> Counter:
    return Counter(level_of.get(i, "?") for i in ids)


def _composition_violations(member_ids: List[str], level_of: Dict[str, str]) -> List[str]:
    """按 _TEAM_QUOTA 检查层级配比，返回违规说明（空列表即合规）。"""
    n = _levels_of(member_ids, level_of)
    out = []
    for lvl, lo, hi, _name in _TEAM_QUOTA:
        c = n.get(lvl, 0)
        if not lo <= c <= hi:
            out.append(f"{lvl} 期望 {lo}-{hi} 位，实得 {c} 位")
    return out


def _coerce_dispatch(raw: Any, valid_ids: set, level_of: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """把指派产出规整成 {lead, members, repairs}；形状不符一律 None（交调用方判降级）。

    三道处理都必须留痕，旧实现是三道无痕兜底：
      - 幻觉/非法 id：丢弃（旧实现已有）；
      - 重复 id：去重保序（旧实现会虚增 missions）；
      - lead 悬空或非法：归一到队内决策层（旧实现直接 `members[0]`，无声换人）。
    """
    if not isinstance(raw, dict):
        return None
    members: List[Dict[str, str]] = []
    seen: set = set()
    dropped = 0
    for m in raw.get("members") or []:
        if not isinstance(m, dict):
            dropped += 1
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or mid not in valid_ids:
            dropped += 1
            continue
        if mid in seen:
            dropped += 1
            continue
        seen.add(mid)
        members.append({"id": mid, "reason": str(m.get("reason") or "").strip()})
    if not members:
        return None
    repairs: List[str] = []
    if dropped:
        repairs.append(f"丢弃 {dropped} 个非法/重复指派项")
    lead = raw.get("lead")
    if not (isinstance(lead, str) and lead in seen):
        if isinstance(lead, str) and lead:
            repairs.append(f"lead {lead} 不在队内，已归一")
        lead = next((m["id"] for m in members if level_of.get(m["id"]) == "L3"),
                    members[0]["id"])
    return {"lead": lead, "members": members, "repairs": repairs}


def _fallback_team(experts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """规则兜底组队：按职级从名册取，函数组 L1 排在行业组之前。

    注意它**只在 LLM 完全不可用时**才到这里，且调用方必然同时给出 degraded ——
    「兜底」与「真组队」在下游必须可区分，否则症状会伪装成业务决策。
    """
    def pick(level: str, want: int) -> List[Dict[str, Any]]:
        pool = [e for e in experts if e["level"] == level]
        # 函数组（采集/舆情）优先，保证降级轮里 collect/舆情两位仍有对口人
        pool.sort(key=lambda e: 0 if e.get("group") == "function" else 1)
        return pool[:want]

    chosen = pick("L3", _FALLBACK_PICK["L3"]) + pick("L2", _FALLBACK_PICK["L2"]) \
        + pick("L1", _FALLBACK_PICK["L1"])
    return [{"id": e["id"], "reason": f"规则兜底：按 {e['level']} 职级配额选入"}
            for e in chosen]


def _record_dispatch_span(msgs: List[Dict[str, str]], decision: str) -> None:
    """把降级原因写进 trace，让决策回放看得见「这次不是真组队」。

    观测不得变成新的失败面：不在调研流程内（无 task_id）时 record_span 自行短路。
    """
    try:
        trace.record_span(model=_model("fast"), messages=msgs, response="",
                          decision=decision)
    except Exception:  # noqa: BLE001  —— 观测失败不得带崩编排
        pass


def _dispatch_experts(query: str, destinations: List[str], focus: List[str]) -> Dict[str, Any]:
    """动态指派专家团队，返回 {lead, members, degraded, degraded_reason, repairs}。

    `degraded` 恒存在（成功为 None）：让「LLM 挑出来的队」与「规则凑出来的队」
    在契约层可区分。三态取值见 _dispatch_experts 内注释。
    降级标记只走 trace 与运行中 SSE，不进报告 payload（见 test_report_read_compat 的
    plan_fallback 同源约定）。
    """
    experts = load_experts()
    valid_ids = {e["id"] for e in experts}
    level_of = {e["id"]: e["level"] for e in experts}
    roster = [
        {"id": e["id"], "name": e["name"], "level": e["level"],
         "role": e["role_title"], "skills": e.get("skills", [])[:3]}
        for e in experts
    ]
    msgs = [
        {"role": "system", "content": (
            "你是 Verda 首席指挥官。从专家名册中为本次旅游调研挑选最合适的团队。"
            f"规则：必须含 {_TEAM_QUOTA_DESC}。"
            "为每位被选专家给出一句指派理由（说明负责什么、为何适合），理由不超过 20 字。"
            '只输出 JSON：{"lead":"专家id","members":[{"id":"专家id","reason":"指派理由"}]}。'
        )},
        {"role": "user", "content": (
            f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点维度：{'、'.join(focus)}\n"
            f"专家名册：{json.dumps(roster, ensure_ascii=False)}"
        )},
    ]
    # max_tokens 从 2000 提到 3600：2000 在「8 位 × 长中文理由 + 思考未可关」下必被
    # 截空（实测 span sp_dc3935abad：completion=1999、推理占 1835、response 为空）。
    # 理由上界已同时下发，二者一起构成该调用点的输出预算契约。
    try:
        data = chat_json(msgs, max_tokens=3600, temperature=0.4,
                         model=_model("fast"), purpose="动态指派专家团队")
    except Exception as e:  # noqa: BLE001
        # 旧实现是 `except Exception: pass` —— 有 typed error（LLMModelUnavailable /
        # LLMNotConfigured）却无人消费，故障被伪装成「指挥官选了这 6 个人」。
        detail = f"{type(e).__name__}: {e}"
        _record_dispatch_span(msgs, f"动态指派专家团队· 指派调用失败（{detail[:120]}）")
        fb = _fallback_team(experts)
        return {"lead": fb[0]["id"], "members": fb, "repairs": [],
                "degraded": "llm_error", "degraded_reason": detail}

    team = _coerce_dispatch(data, valid_ids, level_of)
    if team is None:
        # 拿到了回复但不可用（截断 / 非 JSON / 形状不符 / id 全非法）。
        # 判据复用 brisk L2 的同一读数，避免两套「是不是截断」。
        trunc = last_finish_reason() == "length"
        detail = ("输出被截断（思考未关或预算不足），无可用团队" if trunc
                  else "指派产出不可解析或全部指派非法")
        _record_dispatch_span(msgs, f"动态指派专家团队· {detail}")
        fb = _fallback_team(experts)
        return {"lead": fb[0]["id"], "members": fb, "repairs": [],
                "degraded": "llm_output_unusable",
                "degraded_reason": detail + f"（finish_reason={last_finish_reason()}）"}

    ids = [m["id"] for m in team["members"]]
    bad = _composition_violations(ids, level_of)
    if bad:
        # 形状可用但配比违约：保留 LLM 的团队（它仍能干活），只把违约显性化。
        # 不静默重挑，避免「谁在选人」又从 LLM 手里滑回规则。
        detail = "团队层级配比不符：" + "；".join(bad)
        _record_dispatch_span(msgs, f"动态指派专家团队· {detail}")
        return {**team, "degraded": "spec_violation", "degraded_reason": detail}
    return {**team, "degraded": None, "degraded_reason": ""}


DAG_NODES = [
    {"id": "intake", "label": "需求理解"},
    {"id": "orchestrator", "label": "编排派遣"},
    {"id": "collect", "label": "证据采集"},
    {"id": "analyze", "label": "交叉分析"},
    {"id": "spots", "label": "景点实体"},
    {"id": "write", "label": "报告撰写"},
    {"id": "audit", "label": "质检审裁"},
    {"id": "done", "label": "签发交付"},
]


def _ev(type_: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": type_, "data": data}


def _source_type(url: str) -> str:
    d = domain_of(url)
    plat = classify_platform(url)        # 注册表驱动：社媒平台自动识别
    if plat:
        return plat
    if "tieba.baidu" in d or "douban" in d or "v2ex" in d or "reddit" in d or "quora" in d:
        return "zhihu"  # 论坛/问答类归到社区口碑
    # 财报/投关页
    if any(k in (d + url) for k in ("ir.", "investor", "annualreport", "sec.gov", "10-k", "财报", "年报")):
        return "financial_report"
    # 新闻媒体（含国内主流与科技财经媒体的常见域名）
    if any(k in d for k in ("news", "36kr", "sina", "163.com", "qq.com", "ifeng", "sohu",
                            "huxiu", "tmtpost", "caixin", "yicai", "people.com", "xinhuanet",
                            "thepaper", "cls.cn", "stcn", "eastmoney", "cnbeta", "leiphone",
                            "iyiou", "geekpark", "techcrunch", "theverge", "bloomberg")):
        return "news"
    if not d:
        return "web"
    # 仅当域名形态像「官方站点」（短主域、无新闻/博客特征）时才判 official；
    # 其余一律归为普通网页，避免把不权威的新闻/博客误判为官网（对应需求：置信度修正）。
    if _looks_official(d):
        return "official"
    return "web"


# 明显非官网的特征（命中则不可能是 official）
_NON_OFFICIAL_HINTS = (
    "blog", "news", "wiki", "csdn", "jianshu", "juejin", "zhihu", "baijiahao",
    "toutiao", "medium", "wordpress", "cnblogs", "segmentfault", "oschina",
)


def _looks_official(domain: str) -> bool:
    """粗略判断是否像官方站点：层级浅（主域+顶级域）、不含博客/新闻/社区特征。"""
    if any(h in domain for h in _NON_OFFICIAL_HINTS):
        return False
    parts = [p for p in domain.split(".") if p]
    # 形如 gov.cn / dali.gov.cn / example.com —— 2-3 段且主体不太长
    if len(parts) <= 3 and parts and len(parts[0]) <= 18:
        return True
    return False


def _region_keywords(region: str) -> List[str]:
    """把行政区/国家短语拆成关键词，用于舆情相关性消歧（如『云南省大理州』→ [云南省, 大理州, 云南, 大理]）。"""
    if not region:
        return []
    kws: List[str] = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{1,}", region.lower()):
        kws.append(w)
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", region):
        kws.append(w.lower())
    # 去重保序
    seen: set = set()
    return [k for k in kws if not (k in seen or seen.add(k))]


def _sentiment_relevant(destination: str, region_keywords: List[str], title: str, text: str) -> bool:
    """舆情结果相关性判定：必须命中目的地名，或同时带有地区关键词（消歧）。

    解决「调研大理抓到同名内容」：目的地名命中即相关；若目的地名未命中，
    则要求至少命中 1 个地区关键词，否则判为题不对版丢弃。
    """
    blob = f"{title} {text}".lower()
    b = (destination or "").lower().strip()
    if not b:
        return True
    # 目的地名（英文或≥2字中文）直接命中
    if len(b) >= 2 and b in blob:
        return True
    # 目的地名未命中 → 必须有地区关键词背书，否则大概率跑题
    if region_keywords:
        return any(k in blob for k in region_keywords)
    # 没有地区信息时退回宽松：要求目的地名出现（上面已判），到这里说明没命中 → 丢弃
    return False


# ── 采集单目的地（抽出供补采复用）───────────────────────────
def _collect_destination(destination: str, angles: List[str], collector: str,
                         fetch_limit: int, freshness: str,
                         existing_urls: set,
                         groups: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """采集单个目的地：搜索 + 抓取 + 构造 Evidence。返回 {evidences, images, found, dup_skipped, groups}。

    纯同步函数，供 asyncio.to_thread 调用；existing_urls 用于跨轮 URL 去重；
    groups 用于内容级信源组归一化（v2.1：同质转载归并为一组，杜绝转载冒充多源），
    由 run_pipeline 跨目的地/跨轮维护（docstring 注明：groups 池由 run_pipeline 主线程独占维护）。
    """
    queries = [f"{destination} {a}" for a in angles]
    results = multi_search(queries, num=10, freshness=freshness)
    out_ev: List[Evidence] = []
    out_img: List[Dict[str, Any]] = []
    fetched = 0
    dup_skipped = 0
    groups = groups or []
    seen_gids = {g["id"] for g in groups if g.get("id")}
    for r in results:
        if fetched >= fetch_limit:
            break
        url = r.get("url", "")
        if not url or url in existing_urls:
            continue
        page = fetch_page(url, fallback_snippet=r.get("snippet", ""))
        ok = page.get("ok")
        text = (page.get("text") or r.get("snippet", "")).strip()
        if not text:
            continue
        # 正文二次相关性校验（剔除题不对版）
        if not is_relevant_content(text, [destination], destination):
            continue
        # 内容级信源组归一化：同质转载 → 归并既有组、跳过取证（不冒充独立信源）
        gid, _rep = group_new_text(text, groups)
        if gid:
            dup_skipped += 1
            for g in groups:
                if g.get("id") == gid:
                    g.setdefault("urls", []).append(url)
                    break
            continue
        existing_urls.add(url)
        stype = _source_type(url)
        captured = page.get("captured_at", _now())
        # 用 search 返回的 datePublished（captured_at）做时效性判断更准
        pub_date = r.get("captured_at", "")
        cred = score_evidence(
            url, stype, captured_at=pub_date or captured,
            has_publish_date=bool(pub_date), ok_fetch=bool(ok), excerpt=text[:280],
        )
        fdays = freshness_days(pub_date or captured)
        # 开新信源组（指纹为空/短文本也独立成组）
        gid2 = _sid("g")
        while gid2 in seen_gids:
            gid2 = _sid("g")
        seen_gids.add(gid2)
        groups.append({"id": gid2, "tokens": tokenize(text), "urls": [url]})
        ev = Evidence(
            evidence_id=_sid("e"),
            source_url=url,
            source_type=stype,
            title=r.get("title", destination),
            excerpt=text[:280],
            captured_at=pub_date or captured,
            credibility=cred,
            collected_by=collector,
            image_urls=[im["src"] for im in page.get("images", [])][:3],
            destination=destination,
            domain=domain_of(url),
            freshness_days=fdays,
            content_hash=content_fingerprint(text),
            source_group=gid2,
        )
        ev._full_text = text[:1500]  # type: ignore[attr-defined]
        out_ev.append(ev)
        # 配图
        og = (page.get("og_image") or "").strip()
        pics = page.get("images", []) or []
        fig_src = og or (pics[0]["src"] if pics else "")
        if fig_src:
            fig_alt = "" if og else (pics[0].get("alt", "") if pics else "")
            out_img.append({
                "src": fig_src, "alt": fig_alt, "title": r.get("title", destination),
                "source_url": url, "domain": domain_of(url),
                "source_type": stype, "destination": destination, "evidence_id": ev.evidence_id,
            })
        fetched += 1
    return {"evidences": out_ev, "images": out_img, "found": len(results),
            "dup_skipped": dup_skipped, "groups": groups}


# ── 主流程 ───────────────────────────────────────────────
async def run_pipeline(task_id: str, sub_id: str = "") -> AsyncIterator[Dict[str, Any]]:
    task = db.get_task(task_id) or {"query": "旅游调研", "clarifications": {}}
    clar = task.get("clarifications", {}) or {}
    # 双源读取用户指定的分析模型（task meta 顶层 或 clarifications，与 _mode 同处理），
    # 消除「跳过澄清直接跑」时 override 丢失的脆弱点。set 覆盖式写入：asyncio 每个
    # pipeline 协程有独立 context，且每次 set 覆盖旧值，不同任务之间无串扰。
    override = task.get("_model_override") or clar.get("_model_override") or ""
    _pipeline_model_override.set(override)
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
    plan = await asyncio.to_thread(_plan_research, query, clar, cfg["max_angles"], rtype, task_id)
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
                plat_results = await asyncio.to_thread(multi_search, site_q, num=8, site=site,
                                                       freshness=cfg["freshness"])
                # 站内受限（如抖音/小红书常被 include 过滤掉）→ 回退：全网检索 + 平台关键词
                if not plat_results:
                    fb_q = [f"{t.replace('{d}', sb)}{region_q} {plat_label}" for t in sentiment_angle_tpl]
                    plat_results = await asyncio.to_thread(multi_search, fb_q, num=8,
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
    if "spot_ranking" in spec["structured_keys"]:
        yield _ev("node_update", {"node": "spots", "status": "working", "expert": analyst})
        yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                              "text": f"景点实体阶段：从证据抽取可数信号（声量/口碑/性价比），规则算分冻结 Top{cfg['spot_topn']} 实体表……",
                              "ts": _now()})
        trace.set_context(task_id, analyst, "spots", "景点信号抽取与规则算分")
        spot_trunc: List[bool] = []
        spot_rows = await asyncio.to_thread(_extract_spot_signals, query, destinations, focus,
                                            evidences, cfg["spot_topn"], _model("core"),
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
    quality_before = evaluate_quality(destinations, focus, claims, evidences, structured,
                                      research_type=rtype)
    # 质检官 LLM 真实审阅（逐维度打分 + 问题 + 改进建议）——让质检有对比、有审阅、可观测
    trace.set_context(task_id, auditor, "audit", "质检官审阅：逐维度打分+问题+改进建议")
    review_before = await asyncio.to_thread(
        llm_quality_review, query, destinations, focus, claims, structured, quality_before,
        _model("aux"), rtype)
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
                    analysis["structured"] = structured
                    yield _ev("node_update", {"node": "analyze", "status": "done"})
            rework_rounds_done += 1
            quality_after_round = evaluate_quality(destinations, focus, claims, evidences, structured,
                                                   research_type=rtype)
            issues_resolved = max(0, len(quality_before.issues) - len(quality_after_round.issues))
            envelopes = decide_rework(quality_after_round, evidences)
        quality_after = evaluate_quality(destinations, focus, claims, evidences, structured,
                                         research_type=rtype)
    else:
        quality_after = quality_before

    # 返工后再做一次质检复审，形成「审阅→返工→复审」的真实闭环（重做后有改善）
    review_after = review_before
    if rework_rounds_done > 0:
        trace.set_context(task_id, auditor, "audit", "质检官复审：返工后复核改善情况")
        review_after = await asyncio.to_thread(
            llm_quality_review, query, destinations, focus, claims, structured, quality_after,
            _model("aux"), rtype)
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
                          "text": f"调研总监启动 {len(section_ids)} 章并行撰写（核心章 {_model('core')} / 辅助章 {_model('aux')}）。",
                          "ts": _now()})

    # 并行生成各章
    sections_text: Dict[str, Dict[str, Any]] = {}

    async def _write_one(sid: str):
        title = RT.SECTION_PLAN.get(sid, sid)
        model = _model("core") if sid in CORE_SECTIONS else _model("aux")
        trace.set_context(task_id, writer, "write", f"撰写章节「{title}」")
        return sid, await asyncio.to_thread(
            _write_single_section, sid, title, query, destinations, focus,
            evidences, claims, analysis, model, rtype,
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"], sentiment
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
                    claims, _model("fast"),
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
            _write_sentiment_narrative, query, destinations, sentiment, _model("aux"),
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"],
        )
        for e in _drain_trace():
            yield e

    chart_specs = _build_charts(destinations, analysis, sentiment, claims, rtype, mode=mode)
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
        objective_stats=stats, research_type=rtype,
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
                              sentiment_text, objective_meta, rtype, clar=clar)
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


# ── 分析：LLM 基于真实证据产出论点 + 结构化对比 ───────────────
def _evidence_digest(evidences: List[Evidence], limit: int = 28) -> str:
    lines = []
    for e in evidences[:limit]:
        d = domain_of(e.source_url)
        lines.append(f"[{e.evidence_id}|{e.source_type}|{d}] {e.title}：{e.excerpt}")
    return "\n".join(lines)


# 分析产出各键的 JSON 片段：提示词按 spec["analysis_keys"] 动态拼装，
# 新增/替换分析对象只需改注册表 + 在此加一条片段，分析与图表链路无需改代码。
_ANALYSIS_KEY_SCHEMA: Dict[str, str] = {
    "comparison": '"comparison":{"dimensions":["对比维度,5-6个"],"scores":[{"destination":"目的地","values":[0-100整数,与dimensions等长]}]}',
    "livability": '"livability":{"dimensions":["评估维度,5-6个"],"scores":[{"destination":"目的地","values":[0-100整数,与dimensions等长]}]}',
    "budget": '"budget":[{"destination":"目的地","per_capita_3d":数字或null,"tier":"经济|舒适|品质|高端","note":"花费结构与省钱空间一句话","evidence_ids":["真实id"]}]',
    "cost": '"cost":[{"destination":"目的地","monthly_rent":数字或null,"monthly_living":数字或null,"note":"居住成本结构一句话","evidence_ids":["真实id"]}]',
    "safety_index": '"safety_index":[{"destination":"目的地","safety_score":0-100整数,"note":"治安/灾害/医疗风险研判一句话","evidence_ids":["真实id"]}]',
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
    "access_matrix": '"access_matrix":[{"destination":"目的地","routes":[{"mode":"飞机|高铁|自驾|大巴|轮渡","duration":"耗时","cost":"费用区间","frequency":"班次频次","note":"换乘/购票要点","evidence_ids":["真实id"]}]}]',
    "amenity_checklist": '"amenity_checklist":[{"destination":"目的地","items":[{"category":"医疗|教育|商业|政务|网络","item":"具体配套","coverage":"full|partial|none","note":"说明","evidence_ids":["真实id"]}]}]',
    "risk_profile": '"risk_profile":[{"destination":"目的地","items":[{"dimension":"治安|自然灾害|医疗应急|其他","level":"low|medium|high","note":"说明","evidence_ids":["真实id"]}]}]',
}


def _clamp_int(v, lo: int = 0, hi: int = 100) -> Optional[int]:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _num_or_none(v) -> Optional[float]:
    if isinstance(v, str):
        v = (v.replace("￥", "").replace("¥", "").replace("元", "")
             .replace(",", "").replace("/月", "").strip())
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_name(it: Dict[str, Any]) -> str:
    """行主键：目的地名（兼容 LLM 偶发写成 name/brand 的情况，避免整行丢失）。"""
    return str(it.get("destination") or it.get("brand") or it.get("name") or "").strip()


def _row_dest_ok(name: Any, destinations: List[str]) -> bool:
    """行主键是否属于本次调研目的地（兼容「大理↔大理市」这类行政名变体）。"""
    core = _core_name(str(name or "").strip())
    if not core:
        return False
    return any(_name_hit(core, _core_name(d)) for d in destinations)


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
        else:
            fallback[k] = []
    try:
        data = chat_json(
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
            model=_model("core"),
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
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是旅游知识结构化专家。基于给定证据（每条带 evidence_id），为每个目的地输出严格结构化的 JSON。"
                    "字段必须完整、格式一致。evidence_ids 必须来自给定证据真实 id（无则留空数组）；"
                    "每个叶子项都必须挂载支撑它的 evidence_ids，无证据的项不要输出。输出 JSON：{"
                    + ",".join(fragments) + "}。只输出 JSON，不要解释。"
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}{entity_block}\n证据：\n{digest}"
                )},
            ],
            max_tokens=max_tokens_param,
            temperature=0.3,
            model=_model("core"),
            purpose=f"结构化目的地知识（{'/'.join(keys)}）",
        )
        if isinstance(data, dict):
            coerced = coerce_structured(data, research_type, valid_eids)
            out.update({k: v for k, v in coerced.items() if k not in _ENTITY_STAGE_KEYS})
    except Exception:
        pass
    if trunc_report is not None:
        trunc_report.append(last_finish_reason() == "length"
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
        data = chat_json(
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
            trunc_report.append(last_finish_reason() == "length" and not out)
        return out
    except Exception:
        if trunc_report is not None:
            trunc_report.append(False)
        return []


# ── M2：百度实体解析 / 真实路线 / 商铺 POI（envelope 降级，任何失败不抛、不炸任务）──


def _norm_spot_name(name: Any) -> str:
    return re.sub(r"[（(].*?[）)]|[\s・·\-—]", "", str(name or "")).lower()


def _name_hit(want: str, got: Any) -> bool:
    a, b = _norm_spot_name(want), _norm_spot_name(got)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


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
            results = await asyncio.to_thread(multi_search, queries, num=per_take + 4,
                                              site=PLATFORMS[plat].search_site,
                                              freshness=freshness)
            if not results:  # 站内受限时回退：全网检索 + 平台关键词
                results = await asyncio.to_thread(
                    multi_search, [f"{spot_name} 评价 {PLATFORM_LABEL.get(plat, plat)}{region_q}"],
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
                          sentiment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        data = chat_json(
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
        truncated = last_finish_reason() == "length"
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
        retry = chat(
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
                    **_diag("text_retry", truncated or last_finish_reason() == "length")}
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
        data = chat_json(
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
        data = chat_json(
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
        truncated = last_finish_reason() == "length"
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
def _fields_for_chart(chart_type: str) -> List[str]:
    """章节字段表反查：哪些 claim 字段支撑该图表（图表挂 evidence_ids 用）。"""
    out: List[str] = []
    for fields, ctypes in RT.SECTION_FIELDS.values():
        if chart_type in ctypes:
            out.extend(fields)
    return out


def _build_charts(destinations, analysis, sentiment, claims=None,
                  research_type: str = DEFAULT_RESEARCH_TYPE,
                  mode: str = "deep") -> List[Dict[str, Any]]:
    """按 spec["charts"] 出图：类型决定图集，某图无真实数据则整图跳过（不占位造假）。

    图集与标题随目的地数自适应：单目的地不出占比环图，雷达/花费条改用无「对比」措辞的标题。
    mode=expert 时词云在「全网口碑词云」之外，逐景点各出一张（by_spot 行内真实词频）。
    """
    spec = RT.type_spec(research_type)
    allowed = set(RT.charts_for(research_type, len(destinations)))
    radar_title = RT.radar_title(research_type, len(destinations))
    specs: List[Dict[str, Any]] = []
    ev_by_field: Dict[str, List[str]] = {}
    for c in (claims or []):
        ev_by_field.setdefault(c.get("field", ""), []).extend(c.get("evidence_ids", []))

    def eids(*fields: str) -> List[str]:
        out: List[str] = []
        for f in fields:
            out.extend(ev_by_field.get(f, []))
        seen = set()
        return [x for x in out if not (x in seen or seen.add(x))][:6]

    def chart_eids(chart_type: str) -> List[str]:
        return eids(*_fields_for_chart(chart_type))

    def own(rows_iter: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """消费侧兜底：只取属于本次目的地的行（装配前已过滤，这里防新调用点漏过收口）。"""
        return [r for r in rows_iter if _row_dest_ok(_row_name(r), destinations)]

    radar = analysis.get(spec["radar_key"]) or {}
    dims = radar.get("dimensions") or []
    scores = [s for s in own(radar.get("scores") or [])
              if dims and isinstance(s.get("values"), list) and len(s["values"]) == len(dims)]
    if "radar" in allowed and dims and scores:
        series = [{"name": s["destination"], "values": s["values"]} for s in scores[:4]]
        specs.append({"chart_id": _sid("ch"), "type": "radar", "title": radar_title,
                      "option": C.feature_radar(radar_title, dims, series),
                      "evidence_ids": chart_eids("radar")})

    cb = spec.get("cost_bar") or {}
    rows = ([r for r in own(analysis.get(cb["key"]) or [])
             if isinstance(r.get(cb["value_field"]), (int, float))] if cb else [])

    def cost_labels(items: List[Dict[str, Any]]) -> List[str]:
        """同目的地多档位时把档位拼进 x 轴，否则三根柱子都叫「大理」，看不出差异。"""
        names = [_row_name(r) for r in items]
        same_dest_multi = len(names) > 1 and len(set(names)) < len(names)
        out: List[str] = []
        for r in items:
            dest_name = _row_name(r)
            tier = str(r.get("tier") or "").strip()
            out.append(f"{dest_name}·{tier}" if (same_dest_multi and tier) else (dest_name or "—"))
        return out

    if "cost_bar" in allowed and rows:
        bar_title = RT.cost_bar_title(research_type, len(destinations))
        specs.append({"chart_id": _sid("ch"), "type": "cost_bar", "title": bar_title,
                      "option": C.pricing_bar(bar_title, cost_labels(rows),
                                              [float(r[cb["value_field"]]) for r in rows],
                                              y_name=cb["unit"]),
                      "evidence_ids": chart_eids("cost_bar")})

    # 安全评分柱状图：数据源是 analysis.safety_index[].safety_score（0-100 整数）
    safety_rows = [r for r in own(analysis.get("safety_index") or [])
                   if isinstance(r.get("safety_score"), (int, float))]
    if "cost_bar" in allowed and safety_rows:
        safety_title = "目的地安全评分对比" if len(destinations) >= 2 else "目的地安全评分"
        specs.append({"chart_id": _sid("ch"), "type": "cost_bar", "title": safety_title,
                      "option": C.pricing_bar(safety_title,
                                              [_row_name(r) for r in safety_rows],
                                              [float(r["safety_score"]) for r in safety_rows],
                                              y_name="分（0-100）"),
                      "evidence_ids": chart_eids("safety_score")})

    # 花费构成柱：数据源是结构化 cost_breakdown（交通/住宿/餐饮…），此前有数据无图。
    # 是否产出由图集声明决定（SOLO_ONLY_CHARTS 已在 charts_for 里按目的地数剔除）。
    cb_items: List[Dict[str, Any]] = []
    for grp in own((analysis.get("structured") or {}).get("cost_breakdown") or []):
        cb_items.extend(i for i in (grp.get("items") or []) if isinstance(i, dict))
    cb_items = [i for i in cb_items if isinstance(i.get("amount"), (int, float))
                and str(i.get("category") or "").strip()]
    if "cost_compose" in allowed and cb_items:
        compose_unit = str(cb_items[0].get("unit") or "元/人").strip()
        compose_title = f"人均花费构成（{compose_unit}）"
        specs.append({"chart_id": _sid("ch"), "type": "cost_compose", "title": compose_title,
                      "option": C.pricing_bar(compose_title,
                                              [str(i["category"]).strip() for i in cb_items],
                                              [float(i["amount"]) for i in cb_items],
                                              y_name=compose_unit),
                      "evidence_ids": chart_eids("cost_compose")})

    season = analysis.get("season") or {}
    matrix = [m for m in own(season.get("matrix") or [])
              if isinstance(m.get("values"), list) and len(m["values"]) == 12]
    if "season_heat" in allowed and matrix:
        title = "逐月出行适宜度（1-12 月）"
        specs.append({"chart_id": _sid("ch"), "type": "season_heat", "title": title,
                      "option": C.season_heat(title, [f"{i}月" for i in range(1, 13)],
                                              [m["destination"] for m in matrix],
                                              [m["values"] for m in matrix],
                                              str(season.get("note") or "")),
                      "evidence_ids": chart_eids("season_heat")})

    share = [s for s in own(analysis.get("share_estimate") or [])
             if isinstance(s.get("value"), (int, float))]
    if "donut" in allowed and share:
        specs.append({"chart_id": _sid("ch"), "type": "donut", "title": spec["share_title"],
                      "option": C.market_donut(spec["share_title"],
                                               [{"name": s["name"], "value": s["value"]} for s in share]),
                      "evidence_ids": chart_eids("donut")})

    tr = analysis.get("trends") or {}
    tx = tr.get("x") if isinstance(tr.get("x"), list) else []
    tseries = [s for s in own(tr.get("series") or [])
               if tx and isinstance(s.get("values"), list) and len(s["values"]) == len(tx)]
    if "trend" in allowed and tx and tseries:
        title = f"发展轨迹趋势（{tr.get('unit', '')}）".replace("（）", "")
        specs.append({"chart_id": _sid("ch"), "type": "trend", "title": title,
                      "option": C.trend_line(title, tx,
                                             [{"name": s["name"], "values": s["values"]} for s in tseries[:5]],
                                             y_name=tr.get("unit", "")),
                      "evidence_ids": chart_eids("trend")})

    if "sentiment_donut" in allowed and sentiment.get("sample_size"):
        specs.append({"chart_id": _sid("ch"), "type": "sentiment_donut", "title": "整体舆情情感分布",
                      "option": C.sentiment_donut("整体舆情情感分布", sentiment["overall_count"]),
                      "evidence_ids": []})
        if "platform_bar" in allowed and sentiment.get("by_platform"):
            specs.append({"chart_id": _sid("ch"), "type": "platform_bar", "title": "各平台声量（抖音优先）",
                          "option": C.platform_bar("各平台声量（抖音优先）", sentiment["by_platform"]),
                          "evidence_ids": []})
    # 口碑词云（M2d · E1 语义载荷）：wordfreq 真实词频为源；无词不产图。expert 逐景点各一张（引用冻结实体名）。
    if "wordcloud" in allowed:
        wc_words = C.wordcloud_words(sentiment.get("keywords") or [])
        if wc_words:
            wc_title = "全网口碑热词词云"
            specs.append({"chart_id": _sid("ch"), "type": "wordcloud", "title": wc_title,
                          "words": wc_words, "evidence_ids": []})
            if mode == "expert":
                for g in sentiment.get("by_spot") or []:
                    gw = C.wordcloud_words(g.get("keywords") or [])
                    if not gw:
                        continue
                    t = f"「{g.get('spot_name') or g.get('spot_id')}」口碑词云"
                    specs.append({"chart_id": _sid("ch"), "type": "wordcloud", "title": t,
                                  "words": gw, "evidence_ids": []})
    return specs


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
    elif section_id == "value":           # assessment：性价比与成本
        for c in (analysis.get("cost") or []):
            dest = str(c.get("destination", ""))
            if isinstance(c.get("monthly_rent"), (int, float)):
                rows.append(_row(f"{dest} 月租", f"{c['monthly_rent']}元/月", "居住成本",
                                 c.get("evidence_ids")))
            if isinstance(c.get("monthly_living"), (int, float)):
                rows.append(_row(f"{dest} 月均生活费", f"{c['monthly_living']}元/月", "生活成本",
                                 c.get("evidence_ids")))
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
                     clar: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rid = _sid("r")
    spec = RT.type_spec(research_type)
    members = [m["id"] for m in dispatch["members"]]
    title = RT.report_title(destinations, research_type)
    indep_domains = len({domain_of(e.source_url) for e in evidences if e.source_url})
    subtitle = (f"基于 {len(evidences)} 条联网证据 · {indep_domains} 个独立来源 · "
                f"{len(members)} 位专家协作生成 · {MODE_CONFIG.get(mode,{}).get('label','深度模式')}")

    # 同类型可能有多张图（expert 档逐景点词云），按类型挂全部而非仅末张
    charts_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for c in charts:
        charts_by_type.setdefault(c["type"], []).append(c)

    # 章节标题（类型白名单内的章节加中文序号）
    title_map = {**RT.SECTION_PLAN, **RT.numbered_titles(section_ids, research_type)}
    data_grid_sections = set(spec["data_grid_sections"])

    def _section(sid: str):
        fields, chart_types = RT.section_fields(sid)
        st = sections_text.get(sid, {}) if isinstance(sections_text, dict) else {}
        if not isinstance(st, dict):
            st = {"paragraphs": st if isinstance(st, list) else [str(st)], "key_takeaway": "", "highlights": []}
        sec_claims = [c for c in claims if c["field"] in set(fields)]
        sec_charts = [c for t in chart_types for c in charts_by_type.get(t, [])]
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
        }
        # 结构化对象挂到承载它的章节：claim 字段命中的键，或 SECTION_STRUCTURED 声明的实体表
        structured = analysis.get("structured") or {}
        mount_keys = [k for k in spec["structured_keys"] if k in set(fields)]
        mount_keys += [k for k in RT.section_structured_keys(sid) if k not in mount_keys]
        for key in mount_keys:
            if structured.get(key):
                sec["structured"] = {"type": key, "data": structured[key]}
                break
        # 数据空间
        if sid in data_grid_sections:
            sec["data_grid"] = _build_data_grid(sid, analysis, evidences)
        # 结构状态：前端据此决定画导图还是如实标注（本就没有材料 vs 写稿失败丢了结构）
        sec["structure_status"] = _structure_status(
            st, bool(sec_claims) or sec.get("structured") is not None)
        return sec

    sections = [_section(sid) for sid in section_ids if sid != "sentiment"]

    # 舆情专章（始终插入，置于结论章之前）
    sent_charts = [c[0] for t in ("sentiment_donut", "platform_bar")
                   if (c := charts_by_type.get(t))]
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
        "structured": None, "data_grid": None,
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
                         "structure_status": "by_design"})

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
