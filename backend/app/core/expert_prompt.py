"""专家知识 → LLM Prompt 的唯一载荷层。

架构纪律：本模块位于通用引擎层，绝不 import app.living_circle.*。
口径值解析由子域启动期注册；未注册 ⇒ 只渲染 ref/label，不渲染 value。
旅行/竞品域拿不到生活圈口径 value —— 这是期望的隔离，不是缺陷。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

# ── 反转注册表（子域在启动期填入）──────────────────────
_RESOLVERS: Dict[str, Callable[[str], Optional[Dict[str, str]]]] = {}


def register_caliber_resolver(namespace: str, fn: Callable[[str], Optional[Dict[str, str]]]) -> None:
    """子域注册自己的口径解析器。

    fn(ref) → {"ref": ..., "kind": ..., "module": ..., "label": ..., "value": ...}
    未知 ref 返回 None（由 expert_directive 兜底）。
    """
    assert namespace not in _RESOLVERS, f"namespace {namespace!r} already registered"
    _RESOLVERS[namespace] = fn


def is_registered(namespace: str) -> bool:
    return namespace in _RESOLVERS


def roster_brief(e: dict) -> dict:
    """组队用紧凑画像。刻意省略 avatar/badge_color/gender/status/stats（纯展示字段）。

    全程 .get() 带默认值 —— test_research_pipeline.py:297-310 会喂缺字段的假名册。
    """
    return {
        "id": e.get("id", ""),
        "name": e.get("name", ""),
        "level": e.get("level", ""),
        "group": e.get("group", ""),
        "role": (e.get("role_title") or "").split(" / ")[0],
        "tags": e.get("knowledge_tags", []),
        "calibers": [r["ref"] for r in e.get("caliber_refs", [])],
    }


def roster_payload(experts: Sequence[dict] | None = None, domain: str = "travel") -> str:
    """生成组队用的 roster 文本块。domain 选择域名册（travel/living_circle）。"""
    from app.data import load_experts

    if experts is None:
        experts = load_experts(domain)
    lines = ["=== 专家名册 ==="]
    for e in experts:
        b = roster_brief(e)
        cal_str = ", ".join(b["calibers"]) if b["calibers"] else "无"
        lines.append(
            f"- {b['id']} {b['name']}（{b['level']}·{b['group']}）"
            f" | {b['role']} | 标签: {', '.join(b['tags'])} | 口径: {cal_str}"
        )
    lines.append("=== 名册结束 ===")
    return "\n".join(lines)


def _resolve_ref(ref: str) -> Optional[Dict[str, str]]:
    """按 namespace 分发到对应 resolver。未知 ref 返回 None。"""
    if "::" not in ref:
        return None
    ns = ref.split("::")[0]
    resolver = _RESOLVERS.get(ns)
    if resolver is None:
        logger.warning("caliber resolver 未注册 [ns=%s]，口径数值未注入", ns)
        return None
    try:
        return resolver(ref)
    except KeyError:
        logger.warning("口径 ref=%r 解析失败（可能名册与代码独立漂移），已省略", ref)
        return None


def render_for_prompt(refs: list[str]) -> str:
    """将一组 caliber_refs 渲染为可读文本，用于 expert_directive。"""
    parts = []
    for ref in refs:
        view = _resolve_ref(ref)
        if view:
            # view 可能是 CaliberView dataclass 或 dict（兼容两种返回类型）
            if hasattr(view, "label"):
                # CaliberView dataclass
                parts.append(f"{view.label}={view.value}")
            else:
                # dict (backward compatibility)
                parts.append(f"{view['label']}={view['value']}")
        else:
            # 未注册或解析失败时仍保留 ref 标识符，让模型知道有这项但值缺失
            parts.append(f"{ref}（待补采）")
    return "；".join(parts)


def expert_directive(eid: str, domain: str = "travel") -> str:
    """单人深度画像：身份 + 职责 + knowledge_base + 技能 + 口径实际值。

    未知 id ⇒ 返回 ""（绝不用假口径污染 Prompt）；domain 选域名册。
    末尾固定附加约束句，防止模型编造指标名称。
    """
    from app.data import expert_by_id

    e = expert_by_id(eid, domain)
    if not e:
        return ""

    role = (e.get("role_title") or "").split(" / ")[0] or e.get("name") or "专家"
    skills = "、".join(e.get("skills", []))
    kb = e.get("knowledge_base", "")
    refs = e.get("caliber_refs", [])
    cal_text = render_for_prompt([r["ref"] for r in refs]) if refs else ""

    directive = f"""你是 {e.get('name', eid)}（{role}）。
职责：{e.get('one_liner', '')}
技能：{skills}
知识库：{kb}"""
    if cal_text:
        directive += f"\n负责口径：{cal_text}"
    directive += "\n\n约束：只能引用上述口径与随附证据中的数值；不足处写「待补采」，不得编造指标名称。"
    return directive
