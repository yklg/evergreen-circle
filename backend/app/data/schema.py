"""专家名册 schema 定义与校验器。

本模块是名册结构的唯一权威来源；`load_experts(domain)` 只负责宽松加载，
所有结构性校验集中在此，返回问题清单而非抛异常。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 分组约束映射（让绑定有意义而非装饰）──────────────
GROUP_REQUIRED_KINDS: Dict[str, frozenset[str]] = {
    "decision": frozenset({"scoring", "caliber"}),
    "method":   frozenset({"scoring", "caliber"}),
    "strategy": frozenset({"poi"}),
    "facility": frozenset({"poi"}),
}

ALLOWED_ICONS: frozenset[str] = frozenset({
    "crown","scale","shield-check","chess","tag","chat-user","radar","candlestick",
    "circuit","funnel","bar-chart","shield-scale","cloud-code","robot","chip",
    "medical-cross","ev-bolt","cloud","brain-chip","cart","gamepad","chain","play",
    "truck","utensils","lipstick","house","graduation","shirt","wheat","plane-pin",
    "umbrella-shield","recycle-leaf","rocket","phone-chip","network","globe-chat",
    "checklist","chat-bubble","mood-wave","stars","lightbulb-shield","user-search",
    "doc-chart","line-bar","folder",
})

EXPECTED_IDS: Tuple[str, ...] = tuple(
    [f"L3-{i:03d}" for i in range(1, 4)]
    + [f"L2-{i:03d}" for i in range(1, 10)]
    + [f"L1-{i:03d}" for i in range(1, 37)]
)


@dataclass(frozen=True)
class CaliberRef:
    """专家与口径标识符的绑定关系。"""
    ref: str      # 规范键，如 "scoring::WEIGHTS.coverage"
    note: str     # 该专家与此标识符的关系说明（≤40 字符）


def validate_roster(experts: List[dict]) -> List[str]:
    """校验名册结构，返回问题清单（空列表 = 通过）。

    设计原则：
    - 数据问题不升级为可用性问题：loader 调用此函数时记录 warning 但不阻断；
    - CI / 生成脚本 / 自检端点据此判断是否放行。
    """
    problems: List[str] = []

    if not experts:
        return ["名册为空"]

    ids = {e.get("id") for e in experts}
    names_seen: Dict[str, str] = {}

    for idx, e in enumerate(experts):
        eid = e.get("id") or f"<index:{idx}>"
        prefix = f"[{eid}]"

        # ID 序列
        if eid not in EXPECTED_IDS:
            problems.append(f"{prefix} id={eid!r} 不在预期序列中")

        # 名称唯一性
        name = e.get("name", "")
        if name and name in names_seen:
            problems.append(f"{prefix} name={name!r} 与 {names_seen[name]} 重名")
        elif name:
            names_seen[name] = eid

        # skills / tags 数量
        skills = e.get("skills")
        if not isinstance(skills, list) or len(skills) != 3:
            problems.append(f"{prefix} skills 应为恰好 3 项，实际 {skills!r}")

        tags = e.get("knowledge_tags")
        if not isinstance(tags, list) or len(tags) != 4:
            problems.append(f"{prefix} knowledge_tags 应为恰好 4 项，实际 {tags!r}")

        # group 合法性
        group = e.get("group")
        if group not in GROUP_REQUIRED_KINDS:
            problems.append(f"{prefix} group={group!r} 不在允许集合中")

        # domain_icon 白名单
        icon = e.get("domain_icon")
        if icon not in ALLOWED_ICONS:
            problems.append(f"{prefix} domain_icon={icon!r} 不在白名单中")

        # caliber_refs 结构与分型约束
        refs_raw = e.get("caliber_refs", [])
        if not isinstance(refs_raw, list):
            problems.append(f"{prefix} caliber_refs 应为列表")
            continue

        if len(refs_raw) == 0:
            # caliber_refs 尚未填充时跳过长度与分型检查（Phase 4 完成后启用）
            continue

        if len(refs_raw) < 2 or len(refs_raw) > 5:
            problems.append(f"{prefix} caliber_refs 长度应在 2~5，实际 {len(refs_raw)}")

        seen_refs: set[str] = set()
        kinds_present: set[str] = set()
        for ri, r in enumerate(refs_raw):
            if not isinstance(r, dict):
                problems.append(f"{prefix} caliber_refs[{ri}] 应为对象")
                continue
            ref = r.get("ref", "")
            note = r.get("note", "")
            if not ref:
                problems.append(f"{prefix} caliber_refs[{ri}] 缺少 ref")
            if ref in seen_refs:
                problems.append(f"{prefix} caliber_refs 中 ref={ref!r} 重复")
            seen_refs.add(ref)
            if not note or len(note) > 40:
                problems.append(f"{prefix} caliber_refs[{ri}] note 应非空且 ≤40 字符，实际 {note!r}")
            # 提取 kind（ref 格式 "namespace::..."）
            if "::" in ref:
                kinds_present.add(ref.split("::")[0])

        # 分型约束（仅当 caliber_refs 非空时检查）
        if group in GROUP_REQUIRED_KINDS and kinds_present:
            required = GROUP_REQUIRED_KINDS[group]
            missing_kinds = required - kinds_present
            if missing_kinds:
                problems.append(
                    f"{prefix} group={group!r} 要求口径种类含 {required}，"
                    f"实际仅出现 {kinds_present}，缺 {missing_kinds}"
                )

    # 期望 id 完整性
    missing_ids = set(EXPECTED_IDS) - ids
    if missing_ids:
        problems.append(f"名册缺失以下 id：{sorted(missing_ids)}")

    return problems
