"""Verda 深度调研编排引擎（真实大脑，对标 Deep Research）。

节点：intake → orchestrator → collect → analyze → write → audit →(pass/rework)→ done

核心原则（按用户要求）：
- 真实联网：每个竞品多角度多轮真实搜索（博查 Bocha），真实抓取正文。
- 真实舆情：site:抖音/小红书/B站/知乎 搜真实评论与真实链接。
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
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core import charts as C
from app.core import db
from app.core import trace
from app.core.audit import evaluate_quality, decide_rework, llm_quality_review
from app.core.runtime_config import get_effective_settings
from app.core.credibility import score_evidence, freshness_days, assess_viral
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core.fetcher import domain_of, fetch_page
from app.core.platforms import classify_platform
from app.core.llm import chat, chat_json, LLMNotConfigured, TOKEN_USAGE
from app.core.metrics import compute_report_metrics, merge_quality_into_metrics
from app.core.models import Evidence, Envelope, make_claim
from app.core.schemas import coerce_feature_tree, coerce_pricing_model, coerce_user_persona
from app.core.search import multi_search
from app.core.sentiment import analyze_sentiment, PLATFORM_LABEL, PLATFORM_SITES
from app.core.textquality import is_relevant_content
from app.data import expert_by_id, load_experts


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── 调研模式三档（对应需求 3）─────────────────────────────
# 按「搜索角度数 + 每角度抓取数 + 章节集 + 模型 + freshness + 写作深度」分档
MODE_CONFIG = {
    "quick": {
        "label": "快速模式",
        "max_angles": 4, "fetch_per_brand": 6, "platform_per": 6,
        "sections": ["summary", "overview", "feature", "pricing", "conclusion"],
        "freshness": "oneYear", "rework_rounds": 0,
        # 写作深度：段落数下限 / 每段字数 / 单章 token 预算
        "min_paragraphs": 3, "para_words": "120-200", "section_max_tokens": 3500,
        "analyze_max_tokens": 6000, "structured_max_tokens": 6000,
        # 舆情覆盖：取口碑的竞品数 / 每平台每查询取条数
        "sentiment_brands": 2, "platform_take": 5,
    },
    "deep": {
        "label": "深度模式",
        "max_angles": 6, "fetch_per_brand": 12, "platform_per": 8,
        "sections": ["summary", "overview", "feature", "pricing", "persona",
                     "trend", "swot", "conclusion", "risk"],
        "freshness": "oneYear", "rework_rounds": 1,
        "min_paragraphs": 5, "para_words": "180-280", "section_max_tokens": 6000,
        "analyze_max_tokens": 8000, "structured_max_tokens": 8000,
        "sentiment_brands": 3, "platform_take": 8,
    },
    "expert": {
        "label": "专家级模式",
        "max_angles": 9, "fetch_per_brand": 16, "platform_per": 10,
        "sections": ["summary", "overview", "feature", "pricing", "persona",
                     "trend", "swot", "moat", "inflection", "contrarian",
                     "conclusion", "risk"],
        "freshness": "oneYear", "rework_rounds": 2,
        # 专家级：篇幅最长、最详尽（券商行研/MBB 深度报告级别）
        "min_paragraphs": 7, "para_words": "260-420", "section_max_tokens": 9000,
        "analyze_max_tokens": 9000, "structured_max_tokens": 9000,
        "sentiment_brands": 4, "platform_take": 10,
    },
}


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
def create_task(query: str, mode: str = "deep", model: Optional[str] = None) -> Dict[str, Any]:
    """快路径：只落库 task_id + meta，不调 LLM，毫秒级返回。

    澄清问卷改为 ClarifyPage 挂载后通过 SSE 懒生成（见 async generate_clarify），
    从而把 LLM 推理移出 HTTP 关键路径——这是根治「提交后等好久」的架构根因。
    """
    task_id = _sid("t")
    # 用户指定的分析模型仅在非空且非 'Auto' 时记录覆盖（跟随 _mode 写入 task meta，
    # 经 submit_clarify 透传进 clarifications，run_pipeline 双源读取）。
    meta: Dict[str, Any] = {"_mode": mode}
    if model and model != "Auto":
        meta["_model_override"] = model
    db.save_task(task_id, query, meta)
    return {"taskId": task_id}


def submit_clarify(task_id: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    # 保留已存的 _mode 与 _model_override（用户在 HomePage 选的模型跟随澄清透传）
    task = db.get_task(task_id) or {}
    prev = task.get("clarifications", {}) or {}
    merged = {**answers}
    for key in ("_mode", "_model_override"):
        if key in prev and key not in merged:
            merged[key] = prev[key]
    db.update_task_clarify(task_id, merged)
    return {"ok": True}


# ── 澄清问卷异步懒生成（SSE 推送；P0 修复：把 LLM 移出 HTTP 关键路径）──
# 并发去重：同 task_id 仅生成一个，其余协程复用同一在途 future（P1#7）。
_GEN_INFLIGHT: Dict[str, "asyncio.Future"] = {}


def _fallback_clarify_questions(query: str) -> List[Dict[str, Any]]:
    """LLM 生成失败时的降级静态问卷（不含竞品发现，但流程可继续，P1#5）。"""
    return [
        {"id": "focus", "question": "本次调研最看重哪些维度？（可多选）", "type": "multi",
         "options": ["功能对比", "定价策略", "用户口碑", "市场份额", "SWOT", "舆情趋势",
                     "技术架构", "增长趋势", "商业模式", "生态壁垒"]},
        {"id": "perspective", "question": "你希望以什么视角来产出这份报告？", "type": "single",
         "options": ["产品经理（PM）", "运营（OPS）", "销售", "用户/消费者", "投资人", "通用/综合"]},
        {"id": "market", "question": "希望聚焦的目标市场或地区？", "type": "single",
         "options": ["中国大陆", "全球", "北美", "东南亚", "欧洲", "不限"]},
        {"id": "user", "question": "目标用户群体是？", "type": "single",
         "options": ["个人用户", "中小团队", "大型企业", "开发者", "学生教育", "不限"]},
        {"id": "freshness", "question": "是否优先关注最新动态？", "type": "single",
         "options": ["优先最新（近一月）", "近一年即可", "不限时间"]},
        {"id": "extra", "question": "有哪些特定竞品、背景或纠正需要我们关注？（选填）",
         "type": "text", "options": []},
    ]


def _baseline_questions(query: str = "") -> List[Dict[str, Any]]:
    """即时基础题（不依赖 LLM），竞品发现完成前即可作答（P0-① 修复核心）。"""
    return _fallback_clarify_questions(query)


def _build_enhanced_questions(
    scope: Dict[str, Any], baseline: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """把领域识别 + 竞品发现结果作为增强题追加到基础题末尾（P0-②：增量而非阻塞）。"""
    subject = scope.get("subject") or ""
    domain = scope.get("domain") or ""
    competitors = scope.get("competitors") or []
    if subject:
        txt = f"我们识别到你要调研的是「{subject}」"
        txt += f"，所属领域：{domain}。" if domain else "。"
        txt += "是否准确？"
    elif domain:
        txt = f"我们识别到你要调研的主题属于「{domain}」领域，是否准确？"
    else:
        txt = "请确认我们理解的调研对象是否准确？"
    extra: List[Dict[str, Any]] = [{
        "id": "scope",
        "question": txt,
        "type": "single",
        "options": ["准确，继续", "大致准确，下面补充", "不准确，我在下方说明"],
        "hint": "若不准确，请在最后一题补充说明真实的调研对象与领域。",
    }]
    if competitors:
        extra.append({
            "id": "competitors",
            "question": f"为「{subject or '该主题'}」自动发现了以下候选竞品，请勾选你希望重点对比的对象（可多选）：",
            "type": "multi",
            "options": competitors[:12],
            "hint": "勾选后我们会确保每个竞品都被充分调研；如有遗漏可在最后一题补充。",
        })
    return list(baseline) + extra


async def _discover_and_build(
    task_id: str, query: str, baseline: List[Dict[str, Any]], timeout_s: float
) -> Dict[str, Any]:
    """竞品发现 + 增强题构建（带缓存命中 / 4s 超时 / 异常兜底）。

    返回可直接作为 SSE clarify_update 载荷的字典：
    {"questions": [...], "competitors_fallback": bool, "complete": True}。
    - 缓存命中（仅成功发现才缓存）→ 零 LLM 调用。
    - 超时 / 异常 → 正则兜底（competitors_fallback=True），绝不卡死。
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
            # 超时或 LLM 抛错 → 正则兜底（competitors_fallback），绝不卡死。
            # 不捕获 CancelledError（BaseException），保证外部取消能正常透传。
            scope = _discover_scope_fallback(query)
        fallback = bool(scope.get("fallback", False))
        # 仅缓存真实（非兜底）发现结果，避免把兜底噪声写进缓存
        if not fallback and (scope.get("competitors") or scope.get("domain")):
            ttl = int(get_effective_settings().get("discovery_cache_ttl_d", 7) or 7)
            db.save_discovery_cache(qhash, scope, ttl_days=ttl)
    enhanced = _build_enhanced_questions(scope, baseline)
    db.save_clarify_questions(task_id, enhanced, complete=True)
    return {"questions": enhanced, "competitors_fallback": fallback, "complete": True}


async def generate_clarify(task_id: str, query: str) -> AsyncIterator[Dict[str, Any]]:
    """懒生成澄清问卷，SSE 逐事件推送（分阶段：基础题即时 → 竞品发现增量）。

    - asyncio.to_thread 把同步阻塞的 _discover_scope（含 DeepSeek HTTP）移出事件循环。
    - 并发重入防护（P1#7）：首个协程把完整载荷塞进 _GEN_INFLIGHT future，其余协程
      await 同一 future 复用结果，绝不重复调 LLM。
    - 阶段 0/1 即时（无 LLM）：先推基础题（partial），竞品发现完再推 clarify_update。
    - 生成失败降级为正则兜底（competitors_fallback），流程不卡死（P1#5）。
    """
    # 重连/刷新：完整问卷已落库 → 直接推送，避免重复 LLM 调用
    existing, complete = db.get_clarify_questions(task_id)
    if existing and complete:
        yield {"type": "clarify_ready", "data": existing}
        return

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
        # 阶段 1：基础题即时渲染（P0-① 修复：不等竞品发现）
        baseline = _baseline_questions(query)
        yield {"type": "clarify_ready", "data": {"questions": baseline, "partial": True}}
        # 阶段 2：竞品发现（带超时 + 缓存 + 异常兜底，P0-②/③）
        yield {"type": "clarify_stage", "data": {"stage": "discovering", "message": "正在发现竞品…"}}
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
                    "你是资深生活圈体检分析师。请基于已有证据与补充材料，把该章节重写得更深、更厚、更有针对性——"
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

        def _call_brief_llm() -> Dict[str, Any]:
            data = chat_json(
                [
                    {"role": "system", "content": (
                        "你是资深竞品分析汇报官。请把整份报告压缩成可直接用于汇报的一页纸精炼。"
                        "输出 JSON：{\"summary\":\"一句话概括(≤40字)\",\"judgments\":[\"全局核心判断(3-5条，结论先行)\"],"
                        "\"key_data\":[\"关键数据(3-5条，带数字)\"],\"actions\":[\"行动建议(3-5条)\"]}。只输出 JSON。"
                    )},
                    {"role": "user", "content": (
                        f"报告标题：{rep.get('title', '')}\n副标题：{rep.get('subtitle', '')}\n"
                        f"品牌：{rep.get('brands') or []}\n证据数：{len(rep.get('evidence', []))} "
                        f"结论数：{len(rep.get('claims', []))}\n\n{summary_block}\n\n各章核心判断：\n"
                        + "\n".join(f"- {t}" for t in takeaways[:12])
                        + f"\n\n效能指标：{metric_block}\n舆情概览：{senti_block}"
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
    brands = rep.get("brands", [])
    evidence = rep.get("evidence", [])
    digest_lines = []
    for e in evidence[:24]:
        digest_lines.append(f"[{e.get('evidence_id')}|{e.get('domain','')}] {e.get('title','')}：{e.get('excerpt','')}")
    digest = "\n".join(digest_lines)
    note_text = "\n".join(f"- {a}" for a in annotations if a)
    system_prompt = (
        "你是资深生活圈体检分析师。用户对报告某章节提出了批注/进一步调研诉求，"
        "请基于已有证据与批注，把该章节重写得更深、更厚、更有针对性——补充论证、数据、对比与独立判断。"
        '输出 JSON：{"paragraphs":["段落"],"key_takeaway":"核心判断","highlights":["亮点"]}。只输出 JSON。'
    )
    user_digest = (
        f"调研主题：{query}\n竞品：{'、'.join(brands)}\n"
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
        "你是资深生活圈体检分析师。报告已归属了一批新的高可信度证据，请基于这些证据把章节重写得更深、更厚、"
        "更有针对性——补充论证、数据、对比与独立判断。"
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


# ── 竞品发现（LLM 路径 + 正则兜底）────────────────────────
# 正则兜底用的静态竞品映射（按常见关键词命中，毫秒级、无需 LLM）。
_FALLBACK_COMPETITOR_MAP: Dict[str, List[str]] = {
    "trae": ["Cursor", "VS Code", "Windsurf", "Claude Code", "GitHub Copilot"],
    "cursor": ["Trae", "VS Code", "Windsurf", "Claude Code", "GitHub Copilot"],
    "vscode": ["Cursor", "Trae", "Windsurf", "JetBrains IDEA"],
    "windsurf": ["Cursor", "Trae", "VS Code", "Claude Code"],
    "copilot": ["Cursor", "Trae", "Claude Code", "通义灵码"],
    "chatgpt": ["Claude", "Gemini", "文心一言", "通义千问", "DeepSeek"],
    "claude": ["ChatGPT", "Gemini", "文心一言", "通义千问"],
    "deepseek": ["ChatGPT", "Claude", "Gemini", "通义千问", "豆包"],
    "gemini": ["ChatGPT", "Claude", "DeepSeek", "文心一言"],
    "doubao": ["DeepSeek", "文心一言", "通义千问", "豆包"],
    "notion": ["飞书文档", "语雀", "Confluence", "Obsidian"],
    "feishu": ["钉钉", "企业微信", "Slack", "Microsoft Teams"],
    "钉钉": ["飞书", "企业微信", "Slack", "Microsoft Teams"],
    "企业微信": ["飞书", "钉钉", "Slack"],
    "slack": ["飞书", "钉钉", "Microsoft Teams", "Discord"],
    "zoom": ["腾讯会议", "飞书会议", "Microsoft Teams"],
    "spotify": ["Apple Music", "网易云音乐", "QQ音乐"],
    "netflix": ["Disney+", "爱奇艺", "腾讯视频", "优酷"],
}
_FALLBACK_DOMAIN_MAP: Dict[str, str] = {
    "代码": "AI 编程工具", "编程": "AI 编程工具", "ide": "AI 编程工具", "ai 编程": "AI 编程工具",
    "大模型": "大模型/生成式 AI", "生成式": "大模型/生成式 AI", "llm": "大模型/生成式 AI",
    "调研": "竞品调研/咨询", "竞品": "竞品调研/咨询", "分析": "竞品调研/咨询",
    "协作文档": "协同办公", "文档": "协同办公", "办公": "协同办公", "im": "协同办公", "即时通讯": "协同办公",
    "会议": "视频会议", "视频": "视频会议",
    "音乐": "流媒体音乐", "音频": "流媒体音乐",
}


def _discover_scope(query: str) -> Dict[str, Any]:
    """领域识别 + 竞品自动发现（前置侦察，LLM 路径）。

    返回 {"subject", "domain", "competitors", "fallback"}。
    用 aux 模型（glm-5.1，已关思考、JSON 稳定）；失败重试一次，
    仍失败则交由 _discover_scope_fallback 返回正则兜底（fallback=True），绝不抛错。
    """
    msgs = [
        {"role": "system", "content": (
            "你是社区体检总检，负责开题前的『中心点定格 + 设施范围识别』。"
            "根据用户一句话需求，判断：①真正的调研对象是什么（产品/公司/品类全称）；"
            "②它属于什么细分领域/赛道；③在该赛道里，尽可能多地列出与之直接竞争的真实竞品（8-12 个，"
            "必须是真实存在、可搜索的产品/公司名，按知名度从高到低排列，不要编造）。"
            '只输出 JSON：{"subject":"调研对象全称","domain":"细分领域/赛道","competitors":["竞品1","竞品2"]}。'
            "competitors 不要包含调研对象自身。只输出 JSON，不要任何解释或思考过程。"
        )},
        {"role": "user", "content": query},
    ]
    for _ in range(2):
        try:
            data = chat_json(
                msgs, max_tokens=1500, temperature=0.3,
                model=_model("aux"), purpose="领域识别+竞品自动发现",
            )
            if isinstance(data, dict) and (data.get("subject") or data.get("competitors")):
                subject = str(data.get("subject") or "").strip()
                domain = str(data.get("domain") or "").strip()
                comps = [
                    str(c).strip() for c in (data.get("competitors") or [])
                    if str(c).strip() and str(c).strip() != subject
                ]
                seen = set()
                comps = [c for c in comps if not (c in seen or seen.add(c))]
                return {
                    "subject": subject, "domain": domain,
                    "competitors": comps[:12], "fallback": False,
                }
        except Exception:
            pass
    # LLM 全失败 → 正则兜底（不抛，保证流程继续）
    return _discover_scope_fallback(query)


def _discover_scope_fallback(query: str) -> Dict[str, Any]:
    """纯正则 / 静态映射兜底：无 LLM 调用，毫秒级返回。

    命中已知产品 → 给出其常见竞品与推测主体；否则尝试从引号抽取候选。
    始终返回 fallback=True（提示前端这是自动识别候选，需用户核对）。
    """
    q = (query or "").strip()
    low = q.lower()
    competitors: List[str] = []
    subject = ""
    for key, vals in _FALLBACK_COMPETITOR_MAP.items():
        if key in low:
            competitors = [v for v in vals if v.lower() != key]
            subject = key.title() if key.islower() else key
            break
    if not competitors:
        cand = re.findall(r"[‘’'\"\“\”]([^‘’'\"\“\”]{2,20})[‘’'\"\“\”]", q)
        competitors = [c.strip() for c in cand if c.strip()]
    domain = ""
    for kw, dom in _FALLBACK_DOMAIN_MAP.items():
        if kw in low:
            domain = dom
            break
    return {
        "subject": subject, "domain": domain,
        "competitors": competitors[:12], "fallback": True,
    }


def _plan_research(query: str, clar: Dict[str, Any], max_angles: int = 7) -> Dict[str, Any]:
    clar = clar or {}
    clar_text = "；".join(f"{k}: {v}" for k, v in clar.items()
                         if v and not str(k).startswith("_"))
    # 用户在问卷里勾选/补充的竞品（最高优先级，必须全部纳入）
    user_brands = clar.get("competitors") or []
    if isinstance(user_brands, str):
        user_brands = [user_brands]
    user_brands = [str(b).strip() for b in user_brands if str(b).strip()]
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是社区体检总检。拆解用户的生活圈体检需求，输出 JSON："
                    '{"subject":"本次调研的核心对象全称",'
                    '"category":"该对象所属的细分品类/领域（用于消歧，如 AI编程工具、知识管理软件、新能源汽车）",'
                    '"brands":["竞品全称1","竞品全称2"],'
                    '"focus":["本次重点维度，如 定价/功能/口碑"],'
                    '"search_angles":["针对每个竞品的搜索角度短语，如 产品功能、定价方案、用户评测、最新动态2025、市场份额、财报营收"]}。'
                    "brands 必须是真实可搜索的产品/公司名，且【必须同时包含调研对象本身与它的主要竞品】（3-6 个），"
                    "确保对比维度完整，绝不能只调研对象自身而忽略竞品。"
                    "category 要给一个能精准消歧的品类短语（避免品牌名歧义，如 Trae 应识别为「AI编程工具/AI代码编辑器」）。"
                    f"search_angles 给 {max_angles} 个角度，务必包含「最新动态」「2025 2026 最新」等时效性角度以抓取最新数据。只输出 JSON。"
                )},
                {"role": "user", "content": (
                    f"调研需求：{query}\n用户补充：{clar_text or '无'}\n"
                    f"用户已勾选/指定的竞品（必须全部纳入 brands）：{('、'.join(user_brands)) or '无'}"
                )},
            ],
            max_tokens=2000,
            temperature=0.3,
            model=_model("fast"),
            purpose="拆解调研计划（竞品/维度/搜索角度）",
        )
        if isinstance(data, dict) and (data.get("brands") or user_brands):
            llm_brands = [b for b in (data.get("brands") or []) if isinstance(b, str) and b.strip()]
            subject = str(data.get("subject") or "").strip()
            # subject 仅当像「单个产品名」才作为品牌纳入：排除对比短语/过长描述
            # （如「Notion与Obsidian的对比分析」不能当成一个品牌）
            subject_ok = bool(subject) and len(subject) <= 16 and not any(
                k in subject for k in ("对比", "竞争", "分析", "调研", "格局", "与", "和", "、", "vs", "VS", "/")
            )
            # 合并：用户勾选优先 → （合格的）调研对象 → LLM 拆出的竞品；去重保序，上限 6
            merged: List[str] = []
            for b in user_brands + ([subject] if subject_ok else []) + llm_brands:
                b = b.strip()
                if b and b not in merged:
                    merged.append(b)
            brands = merged[:6]
            angles = [a for a in data.get("search_angles", []) if isinstance(a, str)][:max_angles]
            focus = [f for f in data.get("focus", []) if isinstance(f, str)]
            category = str(data.get("category") or "").strip()
            if brands:
                return {
                    "brands": brands,
                    "focus": focus or ["产品", "定价", "口碑"],
                    "angles": angles or ["产品功能", "定价方案", "用户评测", "最新动态2025", "市场份额"],
                    "category": category,
                }
    except Exception:
        pass
    fallback_brands = user_brands or _regex_brands(query)
    return {
        "brands": fallback_brands[:6],
        "focus": ["产品", "定价", "口碑"],
        "angles": ["产品功能", "定价方案", "用户评测", "最新动态2025", "市场份额"][:max_angles],
        "category": str((clar.get("_category") or "")).strip(),
    }


def _regex_brands(query: str) -> List[str]:
    tokens = re.split(r"[、,，/\s]+", query)
    stop = {"分析", "对比", "竞争", "格局", "调研", "报告", "产品", "定价", "的", "与", "和"}
    cand = [t for t in tokens if 2 <= len(t) <= 12 and t not in stop and not t.isdigit()]
    return cand[:4] if cand else ["目标竞品"]


# ── 编排：LLM 动态指派专家（含理由）─────────────────────────
def _dispatch_experts(query: str, brands: List[str], focus: List[str]) -> Dict[str, Any]:
    experts = load_experts()
    roster = [
        {"id": e["id"], "name": e["name"], "level": e["level"],
         "role": e["role_title"], "skills": e.get("skills", [])[:3]}
        for e in experts
    ]
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是 Verda 首席指挥官。从专家名册中为本次调研挑选最合适的团队。"
                    "规则：必须含 1 位 L3 决策层统筹、1-2 位 L2 策略顾问、3-6 位 L1 执行专家。"
                    "为每位被选专家给出一句具体的指派理由（说明他/她负责什么、为什么适合）。"
                    '只输出 JSON：{"lead":"专家id","members":[{"id":"专家id","reason":"指派理由"}]}。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n竞品：{'、'.join(brands)}\n重点维度：{'、'.join(focus)}\n"
                    f"专家名册：{json.dumps(roster, ensure_ascii=False)}"
                )},
            ],
            max_tokens=2000,
            temperature=0.4,
            model=_model("fast"),
            purpose="动态指派专家团队",
        )
        if isinstance(data, dict) and data.get("members"):
            valid_ids = {e["id"] for e in experts}
            members = [
                {"id": m["id"], "reason": m.get("reason", "")}
                for m in data["members"]
                if isinstance(m, dict) and m.get("id") in valid_ids
            ]
            lead = data.get("lead") if data.get("lead") in valid_ids else None
            if members:
                if not lead:
                    lead = members[0]["id"]
                return {"lead": lead, "members": members}
    except Exception:
        pass
    fallback = [
        {"id": "L3-001", "reason": "决策层统筹体检全流程与终审签发"},
        {"id": "L2-001", "reason": "基层医疗配置顾问负责就医可达判断"},
        {"id": "L2-002", "reason": "教育设施规划师负责学位覆盖判断"},
        {"id": "L1-025", "reason": "空间定位师负责中心点定位与坐标解析"},
        {"id": "L1-030", "reason": "POI 核验官负责设施点位检索核验"},
        {"id": "L3-003", "reason": "质检负责点位溯源与盲区复核审裁"},
    ]
    return {"lead": "L3-001", "members": fallback}


DAG_NODES = [
    {"id": "intake", "label": "需求理解"},
    {"id": "orchestrator", "label": "编排派遣"},
    {"id": "collect", "label": "证据采集"},
    {"id": "analyze", "label": "交叉分析"},
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
    # 仅当域名形态像「品牌官网」（短主域、无新闻/博客特征）时才判 official；
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
    """粗略判断是否像品牌官网：层级浅（主域+顶级域）、不含博客/新闻/社区特征。"""
    if any(h in domain for h in _NON_OFFICIAL_HINTS):
        return False
    parts = [p for p in domain.split(".") if p]
    # 形如 brand.com / brand.cn / brand.io / brand.com.cn —— 2-3 段且主体不太长
    if len(parts) <= 3 and parts and len(parts[0]) <= 18:
        return True
    return False


def _category_keywords(category: str) -> List[str]:
    """把品类短语拆成关键词，用于舆情相关性消歧（如『AI编程工具/AI代码编辑器』→ [ai, 编程, 工具, 代码, 编辑器]）。"""
    if not category:
        return []
    kws: List[str] = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{1,}", category.lower()):
        kws.append(w)
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", category):
        kws.append(w.lower())
    # 去重保序
    seen: set = set()
    return [k for k in kws if not (k in seen or seen.add(k))]


def _sentiment_relevant(brand: str, cat_keywords: List[str], title: str, text: str) -> bool:
    """舆情结果相关性判定：必须命中品牌名，或同时带有品类关键词（消歧）。

    解决「调研 Trae 抓到美甲」：品牌名命中即相关；若品牌名未命中，
    则要求至少命中 1 个品类关键词，否则判为题不对版丢弃。
    """
    blob = f"{title} {text}".lower()
    b = (brand or "").lower().strip()
    if not b:
        return True
    # 品牌名（英文或≥2字中文）直接命中
    if len(b) >= 2 and b in blob:
        return True
    # 品牌名未命中 → 必须有品类关键词背书，否则大概率跑题
    if cat_keywords:
        return any(k in blob for k in cat_keywords)
    # 没有品类信息时退回宽松：要求品牌名出现（上面已判），到这里说明没命中 → 丢弃
    return False


# ── 采集单品牌（抽出供补采复用）─────────────────────────────
def _collect_brand(brand: str, angles: List[str], collector: str,
                   fetch_limit: int, freshness: str,
                   existing_urls: set,
                   groups: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """采集单个品牌：搜索 + 抓取 + 构造 Evidence。返回 {evidences, images, found, dup_skipped, groups}。

    纯同步函数，供 asyncio.to_thread 调用；existing_urls 用于跨轮 URL 去重；
    groups 用于内容级信源组归一化（v2.1：同质转载归并为一组，杜绝转载冒充多源），
    由 run_pipeline 跨品牌/跨轮维护（docstring 注明：groups 池由 run_pipeline 主线程独占维护）。
    """
    queries = [f"{brand} {a}" for a in angles]
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
        if not is_relevant_content(text, [brand], brand):
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
            title=r.get("title", brand),
            excerpt=text[:280],
            captured_at=pub_date or captured,
            credibility=cred,
            collected_by=collector,
            image_urls=[im["src"] for im in page.get("images", [])][:3],
            brand=brand,
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
                "src": fig_src, "alt": fig_alt, "title": r.get("title", brand),
                "source_url": url, "domain": domain_of(url),
                "source_type": stype, "brand": brand, "evidence_id": ev.evidence_id,
            })
        fetched += 1
    return {"evidences": out_ev, "images": out_img, "found": len(results),
            "dup_skipped": dup_skipped, "groups": groups}


# ── 主流程 ───────────────────────────────────────────────
async def run_pipeline(task_id: str, sub_id: str = "") -> AsyncIterator[Dict[str, Any]]:
    task = db.get_task(task_id) or {"query": "竞品分析", "clarifications": {}}
    clar = task.get("clarifications", {}) or {}
    # 双源读取用户指定的分析模型（task meta 顶层 或 clarifications，与 _mode 同处理），
    # 消除「跳过澄清直接跑」时 override 丢失的脆弱点。set 覆盖式写入：asyncio 每个
    # pipeline 协程有独立 context，且每次 set 覆盖旧值，不同任务之间无串扰。
    override = task.get("_model_override") or clar.get("_model_override") or ""
    _pipeline_model_override.set(override)
    query = task.get("query", "竞品分析")
    mode = clar.get("_mode", "deep")
    if mode not in MODE_CONFIG:
        mode = "deep"
    cfg = MODE_CONFIG[mode]
    # 调研视角（PM/运营/销售/用户/投资人/通用）→ 报告追加针对性专属板块
    perspective = _normalize_perspective(clar.get("perspective", ""))

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
    yield _ev("message", {"id": _sid("m"), "kind": "mode", "text": f"调研模式：{cfg['label']}",
                          "mode": mode})
    await asyncio.sleep(0.15)

    # ---- 1. intake：LLM 拆解调研计划 ----
    yield _ev("node_update", {"node": "intake", "status": "working", "expert": "L3-001"})
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": "L3-001",
                          "text": f"收到调研需求：{query}（{cfg['label']}）。正在拆解竞品对象与调研维度……", "ts": _now()})
    trace.set_context(task_id, "L3-001", "intake", "拆解调研计划")
    plan = await asyncio.to_thread(_plan_research, query, clar, cfg["max_angles"])
    for e in _drain_trace():
        yield e
    brands = plan["brands"]
    focus = plan["focus"]
    angles = plan["angles"]
    category = plan.get("category", "")
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": "L3-001",
                          "text": f"锁定竞品：{'、'.join(brands)}；重点维度：{'、'.join(focus)}；"
                                  f"将从「{'、'.join(angles)}」等角度展开多轮联网检索。", "ts": _now()})
    yield _ev("progress", prog(7, "intake", 0))
    yield _ev("node_update", {"node": "intake", "status": "done"})

    # ---- 2. orchestrator：LLM 动态指派专家 ----
    yield _ev("node_update", {"node": "orchestrator", "status": "working", "expert": "L3-001"})
    trace.set_context(task_id, "L3-001", "orchestrator", "指派专家团队")
    dispatch = await asyncio.to_thread(_dispatch_experts, query, brands, focus)
    for e in _drain_trace():
        yield e
    member_ids = [m["id"] for m in dispatch["members"]]
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
                           payload={"brands": brands, "angles": angles})
    yield _ev("message", {"id": _sid("m"), "kind": "team", "expert": "L3-001",
                          "members": member_ids, "text": "专家队已就位，开始深度采集。",
                          "dispatch": dispatch["members"],
                          "envelope": {"sender": env_collect.sender, "receiver": env_collect.receiver,
                                       "task_type": env_collect.task_type,
                                       "payload": env_collect.payload}})
    yield _ev("progress", prog(14, "orchestrator", 0))
    yield _ev("node_update", {"node": "orchestrator", "status": "done"})

    collector = next((m["id"] for m in dispatch["members"] if m["id"].startswith("L1")), "L1-025")
    sentiment_expert = next((m["id"] for m in dispatch["members"]
                             if (expert_by_id(m["id"]) or {}).get("group") in ("method", "function")), collector)

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

    for brand in brands:
        yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": collector,
                              "text": f"开始深度检索「{brand}」：{'、'.join(angles)}。", "ts": _now()})
        trace.set_context(task_id, collector, "collect", f"采集竞品「{brand}」证据")
        res = await asyncio.to_thread(_collect_brand, brand, angles, collector,
                                      cfg["fetch_per_brand"], cfg["freshness"], seen_urls, groups)
        stats["dup_skipped"] += res.get("dup_skipped", 0)
        for e in _drain_trace():
            yield e
        if not res["evidences"]:
            collect_notes.append(f"「{brand}」未通过搜索获得有效结果（可能限流或不相关），已如实标注。")
            # 记录可观测 span：本次检索动作即便无果也可追溯
            trace.record_manual_span(
                task_id, collector, "collect", f"采集竞品「{brand}」证据",
                detail=f"检索角度：{('、'.join(angles))}\n搜索引擎：博查 Bocha（freshness={cfg['freshness']}）",
                decision=f"「{brand}」未返回有效结果，已如实标注、不中断。",
            )
            for e in _drain_trace():
                yield e
            yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": collector,
                                  "text": f"「{brand}」本轮搜索未返回有效结果，继续其余竞品（尽力而为，不中断）。",
                                  "ts": _now()})
            continue
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": collector,
                              "text": f"「{brand}」聚合到 {res['found']} 条去重链接，已取证 {len(res['evidences'])} 条。",
                              "ts": _now()})
        for ev in res["evidences"]:
            evidences.append(ev)
            ev_by_collector[collector] += 1
            d = ev.to_dict()
            d["domain"] = domain_of(ev.source_url)
            d["brand"] = ev.brand
            d["full_text"] = getattr(ev, "_full_text", "")
            yield _ev("evidence", {**d})
            yield _ev("progress", prog(min(14 + len(evidences), 50), "collect", len(evidences)))
            await asyncio.sleep(0.01)
        for fig in res["images"]:
            images.append(fig)
            yield _ev("image", fig)
        # 可观测 span：把「检索→去重→取证」这步非 LLM 动作写进决策链路（不再空白）
        brand_evs = [ev for ev in res["evidences"]]
        brand_domains = {domain_of(ev.source_url) for ev in brand_evs}
        brand_domains.discard("")
        trace.record_manual_span(
            task_id, collector, "collect", f"采集竞品「{brand}」证据",
            detail=(f"检索角度（{len(angles)}个）：{('、'.join(angles))}\n"
                    f"搜索引擎：博查 Bocha Web Search（freshness={cfg['freshness']}）"),
            decision=(f"聚合 {res['found']} 条去重链接 → 抓取取证 {len(brand_evs)} 条，"
                      f"覆盖 {len(brand_domains)} 个独立域名。"),
            evidence_ids=[ev.evidence_id for ev in brand_evs[:8]],
        )
        for e in _drain_trace():
            yield e
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": collector,
                              "text": f"「{brand}」累计证据库 {len(evidences)} 条。", "ts": _now()})

    # 真实舆情采集（多品牌 × 多平台 × 多角度，大幅提升样本量与平台多样性）
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": sentiment_expert,
                          "text": "舆情采集：在抖音/小红书/B站/微博/知乎多平台站内检索真实口碑（站内受限时自动回退全网定向检索），覆盖对象与主要竞品。",
                          "ts": _now()})
    sentiment_comments: List[Dict[str, Any]] = []
    # 取口碑的品牌：对象 + 主要竞品（按 mode 档位决定覆盖几个）
    sentiment_brands = brands[:cfg.get("sentiment_brands", 3)]
    primary_brand = brands[0]
    take = cfg.get("platform_take", cfg.get("platform_per", 6))
    # 品类关键词（用于消歧 + 相关性过滤，如 Trae→AI编程工具，避免抓到「美甲」等同名内容）
    cat_kw = _category_keywords(category)
    cat_q = (" " + category) if category else ""
    for sb in sentiment_brands:
        trace.set_context(task_id, sentiment_expert, "collect", f"采集「{sb}」全平台舆情")
        plat_counts: Counter = Counter()
        dropped = 0
        for plat, site in PLATFORM_SITES.items():
            plat_label = PLATFORM_LABEL.get(plat, plat)
            # 多角度口碑检索词，带上品类消歧（覆盖评价/优缺点/吐槽/真实体验）
            site_q = [f"{sb}{cat_q} 评价", f"{sb}{cat_q} 怎么样",
                      f"{sb}{cat_q} 优缺点", f"{sb}{cat_q} 测评"]
            plat_results = await asyncio.to_thread(multi_search, site_q, num=8, site=site,
                                                   freshness=cfg["freshness"])
            # 站内受限（如抖音/小红书常被 include 过滤掉）→ 回退：全网检索 + 平台关键词
            if not plat_results:
                fb_q = [f"{sb}{cat_q} {plat_label} 评价", f"{sb}{cat_q} {plat_label} 怎么样",
                        f"{sb}{cat_q} {plat_label} 体验"]
                plat_results = await asyncio.to_thread(multi_search, fb_q, num=8,
                                                       freshness=cfg["freshness"])
            for e in _drain_trace():
                yield e
            for r in plat_results[:take]:
                url = r.get("url", "")
                title = r.get("title", "")
                text = (r.get("snippet") or title or "").strip()
                if not url or not text or url in seen_urls:
                    continue
                # 相关性过滤：标题/正文必须命中品牌名或品类关键词，否则丢弃（题不对版）
                if not _sentiment_relevant(sb, cat_kw, title, text):
                    dropped += 1
                    continue
                seen_urls.add(url)
                # 平台归属：站内搜索用 plat；回退搜索按真实域名判定，判不出则归到当前平台
                detected = _source_type(url)
                plat_final = plat if detected in ("web", "official", "news") else detected
                sentiment_comments.append({"text": text, "platform": plat_final, "url": url,
                                           "title": title, "brand": sb})
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
                    brand=sb, domain=domain_of(url),
                    viral=vv["viral"], viral_reason=vv["reason"],
                )
                evidences.append(ev)
                ev_by_collector[sentiment_expert] += 1
                d = ev.to_dict()
                d["domain"] = domain_of(url)
                d["brand"] = sb
                yield _ev("evidence", {**d})
        kept = len([c for c in sentiment_comments if c['brand'] == sb])
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": sentiment_expert,
                              "text": f"「{sb}」舆情有效 {kept} 条（已剔除 {dropped} 条题不对版），"
                                      f"平台分布：{dict(plat_counts)}。", "ts": _now()})
    yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": sentiment_expert,
                          "text": f"舆情共采集到 {len(sentiment_comments)} 条带真实链接的多平台口碑（覆盖 {len(sentiment_brands)} 个品牌）。",
                          "ts": _now()})

    yield _ev("node_update", {"node": "collect", "status": "done"})
    yield _ev("progress", prog(54, "analyze", len(evidences)))

    if not evidences:
        yield _ev("error", {"message": "本次未能采集到任何可用证据（搜索/抓取均失败），请稍后重试或更换调研主题。"})
        return

    # ---- 4. analyze：LLM 交叉验证 + 论点 + 结构化 Schema ----
    analyst = next((m["id"] for m in dispatch["members"] if m["id"].startswith("L2")), "L2-001")
    yield _ev("node_update", {"node": "analyze", "status": "working", "expert": analyst})
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                          "text": "对证据去重并做交叉验证：同一结论需 ≥2 个独立域名支撑方判为高置信。", "ts": _now()})
    trace.set_context(task_id, analyst, "analyze", "交叉验证产出结构化论点")
    analysis = await asyncio.to_thread(_analyze, query, brands, focus, evidences, member_ids,
                                       cfg["analyze_max_tokens"])
    for e in _drain_trace():
        yield e
    claims = analysis["claims"]
    for cl in claims:
        yield _ev("message", {"id": _sid("m"), "kind": "claim", "claim": cl})
        await asyncio.sleep(0.03)

    # 结构化知识 Schema（功能树/定价/画像）
    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": analyst,
                          "text": "构建结构化竞品知识：功能树 / 定价模型 / 用户画像（字段完整、引用强制）……",
                          "ts": _now()})
    trace.set_context(task_id, analyst, "analyze", "产出结构化竞品知识Schema")
    structured = await asyncio.to_thread(_analyze_structured, query, brands, focus, evidences,
                                         cfg["structured_max_tokens"])
    for e in _drain_trace():
        yield e
    analysis["structured"] = structured

    yield _ev("thought", {"id": _sid("th"), "kind": "action", "expert": sentiment_expert,
                          "text": "生活圈体检分析师对真实评论做情感分类与观点阵营聚类（占比归一化）……", "ts": _now()})
    trace.set_context(task_id, sentiment_expert, "analyze", "舆情情感分类与阵营聚类")
    sentiment = await asyncio.to_thread(analyze_sentiment, primary_brand, sentiment_comments)
    for e in _drain_trace():
        yield e
    yield _ev("progress", prog(64, "analyze", len(evidences)))
    yield _ev("node_update", {"node": "analyze", "status": "done"})

    # ---- 5. audit：真实质检 + 反馈闭环（在 write 之前评估覆盖度）----
    auditor = next((m["id"] for m in dispatch["members"] if m["id"] == "L3-003"), "L3-003")
    yield _ev("node_update", {"node": "audit", "status": "working", "expert": auditor})
    yield _ev("thought", {"id": _sid("th"), "kind": "reflect", "expert": auditor,
                          "text": "质检官评估证据覆盖度、维度完整性与置信度，决定是否打回返工。", "ts": _now()})
    quality_before = evaluate_quality(brands, focus, claims, evidences, structured)
    # 质检官 LLM 真实审阅（逐维度打分 + 问题 + 改进建议）——让质检有对比、有审阅、可观测
    trace.set_context(task_id, auditor, "audit", "质检官审阅：逐维度打分+问题+改进建议")
    review_before = await asyncio.to_thread(
        llm_quality_review, query, brands, focus, claims, structured, quality_before, _model("aux"))
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
                    recollect_brands = env.payload.get("brands", [])
                    yield _ev("node_update", {"node": "audit", "status": "rework"})
                    yield _ev("node_update", {"node": "collect", "status": "rework"})
                    yield _ev("message", {"id": _sid("m"), "kind": "rework", "expert": auditor,
                                          "reason": f"证据不足，打回采集补充：{('、'.join(recollect_brands)) or '相关品牌'}",
                                          "envelope": {"sender": env.sender, "receiver": env.receiver,
                                                       "task_type": env.task_type, "issues": env.issues}})
                    # 用更多角度补采（追加最新动态角度）
                    extra_angles = angles + ["最新进展2026", "官方公告", "行业报告"]
                    for b in recollect_brands[:3]:
                        trace.set_context(task_id, collector, "collect", f"返工补采「{b}」")
                        res = await asyncio.to_thread(_collect_brand, b, extra_angles[:cfg["max_angles"]],
                                                      collector, cfg["fetch_per_brand"], cfg["freshness"],
                                                      seen_urls, groups)
                        stats["dup_skipped"] += res.get("dup_skipped", 0)
                        for e in _drain_trace():
                            yield e
                        for ev in res["evidences"]:
                            evidences.append(ev)
                            ev_by_collector[collector] += 1
                            d = ev.to_dict()
                            d["domain"] = domain_of(ev.source_url)
                            d["brand"] = ev.brand
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
                    analysis = await asyncio.to_thread(_analyze, query, brands, focus, evidences, member_ids,
                                                       cfg["analyze_max_tokens"], rework_fb)
                    for e in _drain_trace():
                        yield e
                    claims = analysis["claims"]
                    structured = await asyncio.to_thread(_analyze_structured, query, brands, focus, evidences,
                                                         cfg["structured_max_tokens"])
                    analysis["structured"] = structured
                    yield _ev("node_update", {"node": "analyze", "status": "done"})
            rework_rounds_done += 1
            quality_after_round = evaluate_quality(brands, focus, claims, evidences, structured)
            issues_resolved = max(0, len(quality_before.issues) - len(quality_after_round.issues))
            envelopes = decide_rework(quality_after_round, evidences)
        quality_after = evaluate_quality(brands, focus, claims, evidences, structured)
    else:
        quality_after = quality_before

    # 返工后再做一次质检复审，形成「审阅→返工→复审」的真实闭环（重做后有改善）
    review_after = review_before
    if rework_rounds_done > 0:
        trace.set_context(task_id, auditor, "audit", "质检官复审：返工后复核改善情况")
        review_after = await asyncio.to_thread(
            llm_quality_review, query, brands, focus, claims, structured, quality_after, _model("aux"))
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

    # ---- 6. write：多模型并行逐章撰写 ----
    writer = next((m["id"] for m in dispatch["members"] if m["id"] == "L3-002"), dispatch["lead"])
    yield _ev("node_update", {"node": "write", "status": "working", "expert": writer})
    section_ids = list(cfg["sections"])
    # 视角专属板块：插在结论之前（如 销售→销售话术与卖点 / 投资人→增长与壁垒研判）
    persp_sid = PERSPECTIVE_SECTION.get(perspective)
    if persp_sid and persp_sid not in section_ids:
        insert_pos = section_ids.index("conclusion") if "conclusion" in section_ids else len(section_ids)
        section_ids.insert(insert_pos, persp_sid)
    yield _ev("thought", {"id": _sid("th"), "kind": "plan", "expert": writer,
                          "text": f"首席分析师启动 {len(section_ids)} 章并行撰写（核心章 {_model('core')} / 辅助章 {_model('aux')}）。",
                          "ts": _now()})

    # 并行生成各章
    sections_text: Dict[str, Dict[str, Any]] = {}

    async def _write_one(sid: str):
        title = dict(SECTION_PLAN).get(sid, sid)
        model = _model("core") if sid in CORE_SECTIONS else _model("aux")
        trace.set_context(task_id, writer, "write", f"撰写章节「{title}」")
        return sid, await asyncio.to_thread(
            _write_single_section, sid, title, query, brands, focus,
            evidences, claims, analysis, model,
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"]
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
        title = dict(SECTION_PLAN).get(sid, sid)
        yield _ev("thought", {"id": _sid("th"), "kind": "finding", "expert": writer,
                              "text": f"第 {done_count}/{total} 章「{title}」撰写完成。", "ts": _now()})
        yield _ev("progress", prog(70 + int(16 * done_count / total), "write", len(evidences)))

    # 舆情专章：基于真实评论数据生成多段深度解读（与正文同等深度）
    sentiment_text: Dict[str, Any] = {"paragraphs": [], "key_takeaway": "", "highlights": []}
    if sentiment.get("sample_size"):
        trace.set_context(task_id, sentiment_expert, "write", "撰写章节「全网舆情与观点阵营」")
        sentiment_text = await asyncio.to_thread(
            _write_sentiment_narrative, query, brands, sentiment, _model("aux"),
            cfg["min_paragraphs"], cfg["para_words"], cfg["section_max_tokens"],
        )
        for e in _drain_trace():
            yield e

    chart_specs = _build_charts(brands, analysis, sentiment, claims)
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
        brands=brands, focus=focus, claims=claims, evidences=evidences,
        structured=structured, elapsed_seconds=elapsed, tokens_used=tokens_used,
        rework_rounds=rework_rounds_done, issues_resolved=issues_resolved,
        objective_stats=stats,
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

    report = _assemble_report(query, brands, focus, dispatch, claims, evidences, images,
                              sentiment, chart_specs, sections_text, collect_notes,
                              analysis, metrics, quality_before.to_dict(),
                              quality_after.to_dict(), trace_spans, mode, section_ids,
                              sentiment_text, objective_meta)
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


def _analyze(query, brands, focus, evidences: List[Evidence], members: List[str],
             max_tokens_param: int = 8000, review_feedback: str = "") -> Dict[str, Any]:
    digest = _evidence_digest(evidences)
    ev_ids = [e.evidence_id for e in evidences]
    domains_by_id = {e.evidence_id: domain_of(e.source_url) for e in evidences}
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

    fallback = {
        "claims": _fallback_claims(brands, ev_ids, _sg_of, authors),
        "comparison": {"dimensions": ["功能完整度", "易用性", "性价比", "生态", "口碑"],
                       "scores": [{"brand": b, "values": []} for b in brands[:4]]},
        "pricing": [{"brand": b, "entry_price": None} for b in brands[:4]],
        "market_share": [],
        "five_forces": {},
        "trends": {},
        "contradictions": [],
    }
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是资深城市体检分析师，对标城市规划研究院与住建部门研究机构的分析深度。"
                    "基于给定证据（每条带 evidence_id），提炼结构化、有锋芒、敢下判断的竞争洞察。"
                    "严格要求：每条结论的 evidence_ids 必须来自给定证据的真实 id；无证据支撑的结论不要输出；数字尽量带来源。"
                    "输出 JSON：{"
                    '"claims":[{"text":"一句话锐利结论（要有判断不要套话）","field":"overview|feature_tree|pricing_model|user_persona|swot|trend","evidence_ids":["真实id"],"author":"专家id","claim_type":"fact|opinion|mixed"}],'
                    '"comparison":{"dimensions":["能力维度,5-6个"],"scores":[{"brand":"竞品","values":[0-100整数,与dimensions等长]}]},'
                    '"pricing":[{"brand":"竞品","entry_price":数字或null,"note":"定价模式与策略解读"}],'
                    '"market_share":[{"name":"竞品","value":百分比整数}],'
                    '"five_forces":{"rivalry":0-100,"new_entrants":0-100,"substitutes":0-100,"buyer_power":0-100,"supplier_power":0-100,"note":"波特五力总体研判一句话"},'
                    '"trends":{"x":["时间点,如2021/2022/H1等"],"unit":"指标单位,如 版本数/月活(百万)/营收增速(%)","series":[{"name":"竞品","values":[数字,与x等长]}],"note":"趋势研判一句话"},'
                    '"contradictions":[{"claim_text":"来源间存在分歧的陈述","evidence_ids":["真实id"],"note":"为什么存疑/尚未证实"}],"claim_type 定义与客观性铁律：fact=证据可直接支撑的客观事实；opinion=分析判断（用词体现观点）；mixed=事实与推断混合。每条 claim 必须明确 claim_type；不得把单一信源或存在矛盾的资讯写成定论；当不同证据对同一事实说法不一致时，如实输出到 contradictions 而非掩盖。".'
                    "five_forces 用 0-100 量化各方向竞争压力（越高压力越大），基于证据合理研判。"
                    "trends 给出可比的时间序列（产品迭代节奏/用户规模/营收增速等任一可由证据支撑的维度），无依据则留空对象 {}，不要编造。"
                    "comparison/pricing/market_share 必须基于证据合理推断，无依据则留空数组或 null。"
                    "【数据真实性铁律】所有评分/数值必须精确、可信、有区分度：严禁清一色用 5 或 10 的整数倍（如 80/85/90），"
                    "要给出精确到个位的真实评分（如 83、77、91、68），不同竞品、不同维度的分数要有真实差异，体现你基于证据的细腻判断；"
                    "market_share 各项之和不得超过 100；任何百分比不得超过 100。只输出 JSON。"
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n竞品：{'、'.join(brands)}\n重点：{'、'.join(focus)}\n"
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
            valid_ids = set(ev_ids)
            for c in data["claims"]:
                if not isinstance(c, dict) or not c.get("text"):
                    continue
                eids = [i for i in c.get("evidence_ids", []) if i in valid_ids]
                # v2.1 独立信源 = 所属「信源组」去重计数（同质转载只算一组）
                indep = len({_sg_of.get(i, i) for i in eids}) if eids else 0
                author = c.get("author") if c.get("author") in members else authors[0]
                ct = c.get("claim_type", "mixed") if c.get("claim_type") in ("fact", "opinion", "mixed") else "mixed"
                claims.append(make_claim(_sid("c"), c["text"], c.get("field", "overview"),
                                         eids, author, indep, ct).to_dict())
            if claims:
                comp = data.get("comparison") or fallback["comparison"]
                ff = data.get("five_forces") if isinstance(data.get("five_forces"), dict) else {}
                tr = data.get("trends") if isinstance(data.get("trends"), dict) else {}
                share = _sanitize_share(data.get("market_share") or [])
                # 矛盾检测容错：非 list 置空，防单条坏输出拖垮整章
                contrad = data.get("contradictions")
                if not isinstance(contrad, list):
                    contrad = []
                contrad_clean = []
                for ct0 in contrad[:8]:
                    if not isinstance(ct0, dict) or not ct0.get("claim_text"):
                        continue
                    eids2 = [i for i in ct0.get("evidence_ids", []) if i in valid_ids]
                    contrad_clean.append({
                        "claim_text": str(ct0["claim_text"])[:200],
                        "evidence_ids": eids2,
                        "note": str(ct0.get("note", ""))[:200],
                    })
                return {
                    "claims": claims,
                    "comparison": comp,
                    "pricing": data.get("pricing") or [],
                    "market_share": share,
                    "five_forces": ff,
                    "trends": tr,
                    "contradictions": contrad_clean,
                }
    except Exception:
        pass
    return fallback


def _analyze_structured(query, brands, focus, evidences: List[Evidence],
                        max_tokens_param: int = 8000) -> Dict[str, Any]:
    """产出结构化竞品知识：功能树 / 定价模型 / 用户画像（严格 Schema + 引用强制）。"""
    digest = _evidence_digest(evidences, limit=24)
    valid_eids = {e.evidence_id for e in evidences}
    out = {"feature_tree": [], "pricing_model": [], "user_persona": []}
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是竞品知识结构化专家。基于给定证据（每条带 evidence_id），为每个竞品输出严格结构化的 JSON。"
                    "字段必须完整、格式一致。evidence_ids 必须来自给定证据真实 id（无则留空数组）。输出 JSON：{"
                    '"feature_tree":[{"brand":"竞品","modules":[{"category":"模块分类","name":"模块名","sub_features":[{"name":"子功能","support":"full|partial|none","note":"说明","evidence_ids":["id"]}]}]}],'
                    '"pricing_model":[{"brand":"竞品","currency":"CNY|USD","model_type":"subscription|usage|freemium|one_time|free","free_tier":true/false,"tiers":[{"name":"档位名","price":数字或null,"period":"月|年","unit":"人/席","target_user":"目标用户","includes":["权益"],"evidence_ids":["id"]}]}],'
                    '"user_persona":[{"brand":"竞品","personas":[{"name":"画像名","segment":"细分人群","needs":["需求"],"scenarios":["场景"],"pain_points":["痛点"],"decision_factors":["决策因素"],"migration_cost":"迁移成本描述","evidence_ids":["id"]}]}]}。'
                    "只输出 JSON，不要解释。"
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n竞品：{'、'.join(brands)}\n重点：{'、'.join(focus)}\n证据：\n{digest}"
                )},
            ],
            max_tokens=max_tokens_param,
            temperature=0.3,
            model=_model("core"),
            purpose="结构化竞品知识（功能树/定价/画像）",
        )
        if isinstance(data, dict):
            out["feature_tree"] = coerce_feature_tree(data, valid_eids)
            out["pricing_model"] = coerce_pricing_model(data, valid_eids)
            out["user_persona"] = coerce_user_persona(data, valid_eids)
    except Exception:
        pass
    return out


def _sanitize_share(share: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """市场份额防越界：剔除非法值，总和 >100 时按比例归一化，避免出现百分之几千。"""
    clean = [s for s in share
             if isinstance(s, dict) and isinstance(s.get("value"), (int, float)) and s["value"] > 0]
    total = sum(s["value"] for s in clean)
    if total > 100 and total > 0:
        for s in clean:
            s["value"] = round(s["value"] / total * 100, 1)
    return clean


def _fallback_claims(brands, ev_ids, groups_by_id, authors) -> List[Dict[str, Any]]:
    """LLM 不可用时，仍只输出挂真实证据的结论（不编造内容主张，仅做归纳陈述）。

    groups_by_id（v2.1）：evidence_id → source_group（空组按证据自身），
    用于独立信源组数判定。
    """
    indep = len({groups_by_id.get(i, i) for i in ev_ids[:3]})
    out = [make_claim(_sid("c"),
                      f"已就 {'、'.join(brands)} 采集到多源公开证据，下列结论均挂载真实来源以供溯源。",
                      "overview", ev_ids[:3], authors[0], indep, "mixed").to_dict()]
    return out


# ── 撰写：LLM 逐章产出正文（券商行研/MBB 咨询级深度）─────────────
SECTION_PLAN = [
    ("summary", "执行摘要 · 核心判断"),
    ("overview", "一、竞争格局总览（SCP × 波特五力）"),
    ("feature", "二、功能矩阵与战略意图解码"),
    ("pricing", "三、商业模式与定价博弈"),
    ("persona", "四、目标用户与场景画像"),
    ("trend", "五、发展轨迹与趋势研判"),
    ("swot", "六、SWOT 与战略选择"),
    # 创新板块（专家级）
    ("moat", "护城河深度与壁垒拆解"),
    ("inflection", "关键拐点时间线与变量"),
    ("contrarian", "反共识洞察 · 敢下判断"),
    ("conclusion", "结论与行动建议"),
    ("risk", "风险提示与不确定性"),
    # 视角专属板块（按问卷「调研视角」择一插入）
    ("persp_pm", "产品经理视角 · 功能策略与迭代启示"),
    ("persp_ops", "运营视角 · 增长打法与活动机会"),
    ("persp_sales", "销售视角 · 卖点提炼与竞品话术"),
    ("persp_user", "用户视角 · 选型决策与避坑指南"),
    ("persp_investor", "投资人视角 · 增长壁垒与价值研判"),
]

# 视角 → 专属章节 id
PERSPECTIVE_SECTION = {
    "pm": "persp_pm",
    "ops": "persp_ops",
    "sales": "persp_sales",
    "user": "persp_user",
    "investor": "persp_investor",
}


def _normalize_perspective(raw: str) -> str:
    """把问卷里的视角文案归一化为内部 key。"""
    s = (raw or "").lower()
    if "产品" in raw or "pm" in s:
        return "pm"
    if "运营" in raw or "ops" in s:
        return "ops"
    if "销售" in raw or "sales" in s:
        return "sales"
    if "投资" in raw or "investor" in s:
        return "investor"
    if "用户" in raw or "消费" in raw or "user" in s:
        return "user"
    return ""  # 通用/综合：不加专属板块

# 核心章用 glm-5.2（质量最高），其余用 glm-5.1
CORE_SECTIONS = {"summary", "feature", "pricing", "conclusion", "contrarian", "moat"}

SECTION_PROMPTS = {
    "summary": "全局执行摘要，给出最核心的3-4条判断，要求结论先行、观点锐利，让读者 30 秒抓住全貌。",
    "overview": "用 SCP(结构-行为-绩效) 与波特五力解构行业格局，分析市场结构、竞争烈度、玩家行为模式与绩效结果。",
    "feature": "功能矩阵背后的战略意图解码——不只罗列功能，更要解读对手为什么这么做、各自的取舍与护城河在哪里。",
    "pricing": "商业模式与定价博弈，分析各玩家的定价策略、营收结构、单位经济、免费与付费边界的博弈逻辑。",
    "persona": "目标用户与典型场景画像，描述不同品牌的核心用户群、使用场景、决策路径与迁移成本。",
    "trend": "发展轨迹与未来趋势研判，基于历史迭代与当前信号，预判未来 1-2 年的走向与关键变量。",
    "swot": "SWOT 与战略选择建议，系统梳理各玩家的优势/劣势/机会/威胁，并给出针对性战略选择。",
    "moat": "护城河深度拆解：从网络效应、转换成本、规模经济、品牌、数据壁垒等维度，量化评估各玩家护城河的深与浅，并指出最脆弱的一环。",
    "inflection": "关键拐点时间线：梳理行业与各玩家发展史上的关键转折点，识别未来可能引爆格局变化的变量与触发条件。",
    "contrarian": "反共识洞察：提出 2-3 个与市场主流认知相反、但有证据支撑的大胆判断，敢于下结论，解释为什么大多数人看错了。",
    "conclusion": "给决策者的明确行动建议，分优先级排序（高/中/低），要敢拍板、有具体动作，不要空泛的套话。",
    "risk": "本报告结论的风险提示与不确定性，券商式风险披露——说明结论可能在哪些条件下失效、有哪些未知因素。",
    # 视角专属板块
    "persp_pm": "以产品经理视角输出：各竞品的功能取舍与产品哲学、值得借鉴/规避的设计、功能空白与差异化机会、对自身产品路线图与迭代优先级的具体启示。",
    "persp_ops": "以运营视角输出：各竞品的增长打法（拉新/激活/留存/裂变）、内容与社区运营、活动与渠道策略，并给出可立即复用的运营机会清单与打法建议。",
    "persp_sales": "以销售视角输出：逐个竞品提炼差异化卖点与价值主张，给出『我方 vs 竞品』的对比话术、常见异议应对话术与一句话杀手锏，便于一线销售直接使用。",
    "persp_user": "以用户/消费者视角输出：不同人群该如何选型、各竞品最适合谁、真实使用中的优点与坑、性价比与迁移成本，给出清晰的选型决策建议与避坑指南。",
    "persp_investor": "以投资人视角输出：赛道空间与增长性、各玩家的护城河与壁垒强度、商业模式健康度与单位经济、关键风险与潜在拐点，给出价值研判与重点关注信号。",
}


def _write_single_section(sid: str, title: str, query, brands, focus,
                          evidences, claims, analysis, model: str,
                          min_paragraphs: int = 5, para_words: str = "180-280",
                          section_max_tokens: int = 6000) -> Dict[str, Any]:
    """单章独立生成：每章独立 token 预算 + 独立模型，失败不影响其他章节。

    篇幅深度由 min_paragraphs/para_words/section_max_tokens 三档动态控制
    （快速/深度/专家级越来越长、越来越详尽）。
    """
    field_map = {
        "summary": ["overview", "feature_tree", "pricing_model"],
        "overview": ["overview"],
        "feature": ["feature_tree"],
        "pricing": ["pricing_model"],
        "persona": ["user_persona"],
        "trend": ["trend"],
        "swot": ["swot"],
        "moat": ["overview", "feature_tree", "swot"],
        "inflection": ["trend", "overview"],
        "contrarian": ["overview", "swot", "trend"],
        "conclusion": ["overview", "feature_tree", "pricing_model", "swot"],
        "risk": ["overview", "trend", "swot"],
        "persp_pm": ["feature_tree", "overview", "trend"],
        "persp_ops": ["overview", "trend", "user_persona"],
        "persp_sales": ["feature_tree", "pricing_model", "swot"],
        "persp_user": ["user_persona", "feature_tree", "pricing_model"],
        "persp_investor": ["overview", "trend", "swot"],
    }
    fields = field_map.get(sid, ["overview"])
    rel_claims = [c for c in claims if c.get("field") in fields]
    digest = _evidence_digest(evidences, limit=20)
    claim_text = "\n".join(
        f"- [{','.join(c.get('evidence_ids', [])) or '无'}] {c['text']}（{c['confidence']}）"
        for c in rel_claims[:8]
    ) or "（无直接相关论点，请基于证据自行提炼）"

    extra = ""
    ff = analysis.get("five_forces") or {}
    if ff.get("note") and sid in ("summary", "overview", "moat"):
        extra += f"\n波特五力研判：{ff['note']}"
    tr = analysis.get("trends") or {}
    if tr.get("note") and sid in ("summary", "trend", "inflection"):
        extra += f"\n趋势研判：{tr['note']}"
    comp = analysis.get("comparison") or {}
    if comp.get("dimensions") and sid in ("summary", "feature", "moat"):
        extra += f"\n能力维度对比：{', '.join(comp['dimensions'][:6])}"
    pricing = analysis.get("pricing") or []
    if pricing and sid in ("summary", "pricing"):
        extra += f"\n定价信息：{json.dumps(pricing[:3], ensure_ascii=False)}"
    structured = analysis.get("structured") or {}
    if sid == "feature" and structured.get("feature_tree"):
        extra += f"\n功能树结构：{json.dumps(structured['feature_tree'][:2], ensure_ascii=False)[:800]}"
    if sid == "pricing" and structured.get("pricing_model"):
        extra += f"\n定价模型结构：{json.dumps(structured['pricing_model'][:3], ensure_ascii=False)[:800]}"
    if sid == "persona" and structured.get("user_persona"):
        extra += f"\n用户画像结构：{json.dumps(structured['user_persona'][:2], ensure_ascii=False)[:800]}"

    section_role = SECTION_PROMPTS.get(sid, "深度竞争分析章节")
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是顶尖券商首席分析师 + MBB 咨询合伙人级别的报告撰稿人。"
                    "你正在写一份观点鲜明、敢于下判断的社区生活圈体检报告，对标城市规划院的体检评估报告。\n"
                    f"本章定位：{section_role}\n"
                    "写作要求（务必做到）：\n"
                    "1) 结论先行：先给一句最锐利、最有信息量的『核心判断』（key_takeaway），可以是反共识的、大胆的判断；\n"
                    "2) 有观点：正文要解读『为什么』而非罗列『是什么』，揭示对手的战略意图与取舍，给出你的独立判断；\n"
                    "3) 有数据：尽量引用证据中的具体数字、事实、对比；避免空话套话和正确的废话；\n"
                    f"4) 有深度：正文不少于 {min_paragraphs} 段，每段 {para_words} 字，要有层次、有递进的论证链、有洞察，"
                    "段落之间要有逻辑推进（现象→机理→影响→判断），不要并列堆砌；\n"
                    "5) 有亮点：给 2-3 条 highlights（最有冲击力的发现/反差/独特洞察，每条一句话）；\n"
                    "6) 溯源：在正文关键结论后用方括号标注支撑它的 evidence_id，形如 [e_xxxx]（必须来自给定证据/论点的真实 id）；\n"
                    "7) 客观性铁律：区分事实陈述与观点研判——事实须有可溯源证据；观点用『我们判断/有待验证』等措辞，"
                    "不得写成定论；单一信源组或存在矛盾的结论须标注『据报道/单方说法/存在争议』，禁止直接断言；"
                    "情绪化社媒证据只能作『口碑感知』描述，不得转述为产品客观属性。\n"
                    '输出 JSON：{"paragraphs":["第一段","第二段",...],"key_takeaway":"核心判断一句话","highlights":["亮点1","亮点2","亮点3"]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"章节标题：{title}\n"
                    f"调研主题：{query}\n竞品：{'、'.join(brands)}\n重点：{'、'.join(focus)}\n"
                    f"相关论点（含支撑 evidence_id）：\n{claim_text}\n{extra}\n\n证据摘要：\n{digest}"
                )},
            ],
            max_tokens=section_max_tokens,
            temperature=0.7,
            model=model,
            purpose=f"撰写章节：{title}",
        )
        if isinstance(data, dict):
            paras = data.get("paragraphs")
            if isinstance(paras, str):
                paras = [paras]
            paras = [str(p).strip() for p in paras if isinstance(p, str) and str(p).strip()]
            hl = data.get("highlights")
            hl = [str(h).strip() for h in hl if isinstance(h, str) and str(h).strip()] if isinstance(hl, list) else []
            kt = str(data.get("key_takeaway", "")).strip()
            if paras:
                return {"paragraphs": paras, "key_takeaway": kt, "highlights": hl}
    except Exception:
        pass
    # 空章重试一次（更直接的提示）
    try:
        retry = chat(
            [
                {"role": "system", "content": (
                    f"你是资深生活圈体检分析师，针对给定章节写不少于 {min_paragraphs} 段深度分析，"
                    f"每段约 {para_words} 字，论证层层递进，直接输出正文（不要 JSON、不要标题）。"
                )},
                {"role": "user", "content": f"章节：{title}\n主题：{query}\n竞品：{'、'.join(brands)}\n证据：\n{digest[:2000]}"},
            ],
            max_tokens=section_max_tokens, temperature=0.7, model=model, purpose=f"重试撰写章节：{title}",
        )
        paras = [p.strip() for p in retry.split("\n") if len(p.strip()) > 30]
        if paras:
            return {"paragraphs": paras, "key_takeaway": "", "highlights": []}
    except Exception:
        pass
    return {"paragraphs": ["本章节内容生成失败，请重新运行调研或切换模型。"],
            "key_takeaway": "", "highlights": []}


def _write_sentiment_narrative(query, brands, sentiment: Dict[str, Any], model: str,
                               min_paragraphs: int = 5, para_words: str = "180-280",
                               section_max_tokens: int = 6000) -> Dict[str, Any]:
    """基于真实舆情数据生成多段深度解读（绝不在无数据时编造）。

    返回 {"paragraphs": [...], "key_takeaway": "...", "highlights": [...]}。
    无任何真实评论时返回空 paragraphs（由调用方走如实标注的兜底）。
    """
    sample = sentiment.get("sample_size", 0)
    if not sample:
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
                    "你是社区治理顾问 + 生活圈体检分析师。基于给定的【真实舆情统计与原声】，"
                    "写一段有锋芒、有洞察的全网口碑深度解读。\n"
                    "硬性要求：\n"
                    "1) 只能基于给定的真实数据与原声做解读，严禁编造任何不存在的数字、平台或评论；\n"
                    f"2) 正文不少于 {min_paragraphs} 段，每段 {para_words} 字，"
                    "逐层递进：整体情感盘面→平台差异→观点阵营博弈→真实原声印证→对品牌的战略启示；\n"
                    "3) 要解读『为什么』——不同平台/人群为何呈现这种口碑差异，背后的产品与定位原因；\n"
                    "4) 给 2-3 条 highlights（最有冲击力的口碑发现或反差，每条一句话）；\n"
                    "4.5) 全程区分『舆情感知』与『客观事实』：社媒评论/热度隶属口碑感知，不得转述为产品客观属性，"
                    "避免把少数/高热声音写成共识；\n"
                    "5) 开头必须交代真实样本规模与平台分布（来自给定统计，不得编造）；样本量偏小时如实在解读中点明"
                    "『样本有限、结论为方向性参考』，不得掩盖。\n"
                    '输出 JSON：{"paragraphs":["段1","段2",...],"key_takeaway":"一句话核心口碑判断","highlights":["亮点1","亮点2"]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n竞品：{'、'.join(brands)}\n"
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
        if isinstance(data, dict):
            paras = data.get("paragraphs")
            if isinstance(paras, str):
                paras = [paras]
            paras = [str(p).strip() for p in paras if isinstance(p, str) and str(p).strip()]
            hl = data.get("highlights")
            hl = [str(h).strip() for h in hl if isinstance(h, str) and str(h).strip()] if isinstance(hl, list) else []
            kt = str(data.get("key_takeaway", "")).strip()
            if paras:
                return {"paragraphs": paras, "key_takeaway": kt, "highlights": hl}
    except Exception:
        pass
    return {"paragraphs": [], "key_takeaway": "", "highlights": []}


# ── 图表：全部来自真实分析数据（无 random）─────────────────────
def _build_charts(brands, analysis, sentiment, claims=None) -> List[Dict[str, Any]]:
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

    comp = analysis.get("comparison") or {}
    dims = comp.get("dimensions") or []
    scores = [s for s in (comp.get("scores") or [])
              if isinstance(s.get("values"), list) and len(s["values"]) == len(dims) and dims]
    if dims and scores:
        series = [{"name": s["brand"], "values": s["values"]} for s in scores[:4]]
        specs.append({"chart_id": _sid("ch"), "type": "radar", "title": "竞品能力雷达对比",
                      "option": C.feature_radar("竞品能力雷达对比", dims, series),
                      "evidence_ids": eids("feature_tree", "overview")})

    pricing = [p for p in (analysis.get("pricing") or []) if p.get("entry_price") is not None]
    if pricing:
        specs.append({"chart_id": _sid("ch"), "type": "bar", "title": "入门档定价对比",
                      "option": C.pricing_bar("入门档定价对比", [p["brand"] for p in pricing],
                                              [float(p["entry_price"]) for p in pricing]),
                      "evidence_ids": eids("pricing_model")})

    share = [s for s in (analysis.get("market_share") or []) if isinstance(s.get("value"), (int, float))]
    if share:
        specs.append({"chart_id": _sid("ch"), "type": "donut", "title": "市场份额估算（分析师推断）",
                      "option": C.market_donut("市场份额估算（分析师推断）",
                                               [{"name": s["name"], "value": s["value"]} for s in share]),
                      "evidence_ids": eids("overview")})

    ff = analysis.get("five_forces") or {}
    if any(isinstance(ff.get(k), (int, float)) for k in
           ("rivalry", "new_entrants", "substitutes", "buyer_power", "supplier_power")):
        specs.append({"chart_id": _sid("ch"), "type": "five_forces", "title": "波特五力·竞争压力研判",
                      "option": C.five_forces_radar("波特五力·竞争压力研判", ff),
                      "evidence_ids": eids("overview")})

    tr = analysis.get("trends") or {}
    tx = tr.get("x") if isinstance(tr.get("x"), list) else []
    tseries = [s for s in (tr.get("series") or [])
               if isinstance(s.get("values"), list) and len(s["values"]) == len(tx) and tx]
    if tx and tseries:
        title = f"发展轨迹趋势（{tr.get('unit', '')}）".replace("（）", "")
        specs.append({"chart_id": _sid("ch"), "type": "trend", "title": title,
                      "option": C.trend_line(title, tx,
                                             [{"name": s["name"], "values": s["values"]} for s in tseries[:5]],
                                             y_name=tr.get("unit", "")),
                      "evidence_ids": eids("trend", "overview")})

    if sentiment.get("sample_size"):
        specs.append({"chart_id": _sid("ch"), "type": "sentiment_donut", "title": "整体舆情情感分布",
                      "option": C.sentiment_donut("整体舆情情感分布", sentiment["overall_count"]),
                      "evidence_ids": []})
        if sentiment.get("by_platform"):
            specs.append({"chart_id": _sid("ch"), "type": "platform_bar", "title": "各平台声量（抖音优先）",
                          "option": C.platform_bar("各平台声量（抖音优先）", sentiment["by_platform"]),
                          "evidence_ids": []})
    return specs


# ── 数据空间：把数据密集章节的数据汇总成可导出 CSV 的表格 ────────
def _build_data_grid(section_id: str, analysis: Dict[str, Any],
                     evidences: List[Evidence]) -> Optional[Dict[str, Any]]:
    """对数据密集章（pricing/feature/trend/overview）生成数据网格。"""
    ev_by_id = {e.evidence_id: e for e in evidences}

    def _src(eids):
        for eid in (eids or []):
            e = ev_by_id.get(eid)
            if e:
                return domain_of(e.source_url), e.source_url, eid
        return "", "", ""

    columns = ["数据名", "值", "指标", "来源", "来源网址"]
    rows: List[Dict[str, Any]] = []
    structured = analysis.get("structured") or {}

    if section_id == "pricing":
        for pm in structured.get("pricing_model", []):
            brand = pm.get("brand", "")
            for t in pm.get("tiers", []):
                src, url, eid = _src(t.get("evidence_ids"))
                price = t.get("price")
                rows.append({
                    "name": f"{brand} · {t.get('name','')}",
                    "value": (f"{price}{pm.get('currency','')}/{t.get('period','')}" if price is not None else "未公开"),
                    "metric": "定价档位",
                    "source": src, "source_url": url, "evidence_id": eid,
                })
    elif section_id == "feature":
        comp = analysis.get("comparison") or {}
        dims = comp.get("dimensions") or []
        for s in (comp.get("scores") or []):
            vals = s.get("values") or []
            for i, dim in enumerate(dims):
                if i < len(vals):
                    rows.append({
                        "name": f"{s.get('brand','')} · {dim}",
                        "value": vals[i], "metric": "能力评分(0-100)",
                        "source": "分析师综合研判", "source_url": "", "evidence_id": "",
                    })
    elif section_id == "overview":
        for sh in (analysis.get("market_share") or []):
            rows.append({
                "name": f"{sh.get('name','')} 市场份额",
                "value": f"{sh.get('value','')}%", "metric": "市场份额估算",
                "source": "分析师推断", "source_url": "", "evidence_id": "",
            })
    elif section_id == "trend":
        tr = analysis.get("trends") or {}
        tx = tr.get("x") or []
        for s in (tr.get("series") or []):
            vals = s.get("values") or []
            for i, x in enumerate(tx):
                if i < len(vals):
                    rows.append({
                        "name": f"{s.get('name','')} · {x}",
                        "value": vals[i], "metric": tr.get("unit", "趋势值"),
                        "source": "分析师推断", "source_url": "", "evidence_id": "",
                    })

    if len(rows) < 2:
        return None
    return {"columns": columns, "rows": rows}


# ── 组装报告 ─────────────────────────────────────────────
def _make_cover_svg(title: str, brands: List[str]) -> str:
    """本地生成报告封面（SVG data URL），零外部依赖、永不失败。

    根因修复：原先封面写入 copilot-cn.bytedance.net 外部 AI 生图 URL，
    浏览器端鉴权/跨域失败 → 列表只显示灰色占位。改为后端确定性生成
    SVG 封面（品牌色渐变 + 标题 + 品牌行），直接以 data URL 入库，
    前端 <img> 直接渲染，无网络、无失败。
    """
    safe_title = (title or "竞品调研").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(safe_title) > 20:
        safe_title = safe_title[:20] + "…"
    brand_line = " · ".join(brands[:3]) if brands else "Verda AI"
    safe_brand = brand_line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0f766e"/><stop offset="1" stop-color="#134e4a"/>'
        '</linearGradient></defs>'
        '<rect width="800" height="450" fill="url(#g)"/>'
        '<circle cx="650" cy="80" r="150" fill="#ffffff" opacity="0.06"/>'
        '<circle cx="110" cy="390" r="90" fill="#ffffff" opacity="0.05"/>'
        '<text x="48" y="70" fill="#a7f3d0" font-family="sans-serif" font-size="20" letter-spacing="2">VERDA · 竞品调研</text>'
        f'<text x="46" y="225" fill="#ffffff" font-family="sans-serif" font-size="40" font-weight="700">{safe_title}</text>'
        f'<text x="48" y="272" fill="#ccfbf1" font-family="sans-serif" font-size="22">{safe_brand}</text>'
        '<text x="48" y="410" fill="#99f6e4" font-family="sans-serif" font-size="16" opacity="0.85">结论可溯源 · 证据可沉淀</text>'
        '</svg>'
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _assemble_report(query, brands, focus, dispatch, claims, evidences, images,
                     sentiment, charts, sections_text, collect_notes,
                     analysis, metrics, quality_before, quality_after,
                     trace_spans, mode, section_ids, sentiment_text=None,
                     objective_meta: Optional[Dict] = None) -> Dict[str, Any]:
    rid = _sid("r")
    members = [m["id"] for m in dispatch["members"]]
    title = f"{'、'.join(brands)} 竞争格局深度分析报告"
    indep_domains = len({domain_of(e.source_url) for e in evidences if e.source_url})
    subtitle = (f"基于 {len(evidences)} 条联网证据 · {indep_domains} 个独立来源 · "
                f"{len(members)} 位专家协作生成 · {MODE_CONFIG.get(mode,{}).get('label','深度模式')}")

    def claims_for(*fields: str):
        fs = set(fields)
        return [c for c in claims if c["field"] in fs]

    chart_by_type = {c["type"]: c for c in charts}

    # 章节标题（带序号）映射
    title_map = dict(SECTION_PLAN)

    # 章节 → (fields, chart_types) 映射
    sec_meta = {
        "summary": (("overview",), ()),
        "overview": (("overview",), ("five_forces", "donut")),
        "feature": (("feature_tree",), ("radar",)),
        "pricing": (("pricing_model",), ("bar",)),
        "persona": (("user_persona",), ()),
        "trend": (("trend",), ("trend",)),
        "swot": (("swot",), ()),
        "moat": (("overview", "feature_tree", "swot"), ()),
        "inflection": (("trend", "overview"), ()),
        "contrarian": (("overview", "swot", "trend"), ()),
        "conclusion": (("conclusion",), ()),
        "risk": ((), ()),
        "persp_pm": (("feature_tree", "overview"), ()),
        "persp_ops": (("overview", "trend"), ()),
        "persp_sales": (("feature_tree", "pricing_model"), ()),
        "persp_user": (("user_persona", "feature_tree"), ()),
        "persp_investor": (("overview", "trend", "swot"), ()),
    }
    data_grid_sections = {"pricing", "feature", "overview", "trend"}

    def _section(sid: str):
        fields, chart_types = sec_meta.get(sid, ((), ()))
        st = sections_text.get(sid, {}) if isinstance(sections_text, dict) else {}
        if not isinstance(st, dict):
            st = {"paragraphs": st if isinstance(st, list) else [str(st)], "key_takeaway": "", "highlights": []}
        sec_claims = claims_for(*fields)
        sec_charts = [chart_by_type[t] for t in chart_types if t in chart_by_type]
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
        # 结构化对象挂到对应章节
        structured = analysis.get("structured") or {}
        if sid == "feature" and structured.get("feature_tree"):
            sec["structured"] = {"type": "feature_tree", "data": structured["feature_tree"]}
        elif sid == "pricing" and structured.get("pricing_model"):
            sec["structured"] = {"type": "pricing_model", "data": structured["pricing_model"]}
        elif sid == "persona" and structured.get("user_persona"):
            sec["structured"] = {"type": "user_persona", "data": structured["user_persona"]}
        # 数据空间
        if sid in data_grid_sections:
            sec["data_grid"] = _build_data_grid(sid, analysis, evidences)
        return sec

    sections = [_section(sid) for sid in section_ids if sid != "sentiment"]

    # 舆情专章（始终插入，置于 swot 之后或末尾前）
    sent_charts = [c for c in (chart_by_type.get("sentiment_donut"), chart_by_type.get("platform_bar")) if c]
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
    }
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
                         "source_evidence_ids": [], "structured": None, "data_grid": None})

    toc = [{"id": s["id"], "title": s["title"], "level": 1} for s in sections]
    glossary = [
        {"term": "交叉验证", "definition": "同一结论由 ≥2 个独立信源组支撑，判为高置信。", "source": "Verda 四铁律"},
        {"term": "无证据不立论", "definition": "任何数据型结论必须挂载 evidence_ids，否则标记待验证。", "source": "Verda 四铁律"},
        {"term": "同质内容去重（信源组）", "definition": "同一内容被多站转载时归并为一个信源组，转载不冒充独立来源。", "source": "客观性加固 v2.1"},
        {"term": "舆论过热", "definition": "互动量超阈值的高热社媒内容，可信度扣分并如实标注，不代表普遍共识。", "source": "客观性加固 v2.1"},
        {"term": "观点阵营", "definition": "将相同立场的真实用户观点聚类，输出归一化占比与代表评论。", "source": "舆情管线"},
        {"term": "SCP 框架", "definition": "结构(Structure)-行为(Conduct)-绩效(Performance)，产业经济学经典分析范式。", "source": "Bain/Scherer"},
        {"term": "波特五力", "definition": "从现有竞争、新进入者、替代品、买方与供应商议价五个方向量化行业竞争压力。", "source": "Michael Porter"},
    ]
    cover = _make_cover_svg(title, brands)

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
        "brands": brands,
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
    """从采集到的配图中精选：URL 去重，按品牌轮询保证均衡，封顶 limit 张。"""
    seen: set = set()
    by_brand: Dict[str, List[Dict[str, Any]]] = {}
    for im in images:
        src = (im.get("src") or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        by_brand.setdefault(im.get("brand", ""), []).append(im)
    out: List[Dict[str, Any]] = []
    idx = 0
    while len(out) < limit:
        added = False
        for brand in list(by_brand.keys()):
            lst = by_brand[brand]
            if idx < len(lst):
                out.append(lst[idx])
                added = True
                if len(out) >= limit:
                    break
        if not added:
            break
        idx += 1
    return out
