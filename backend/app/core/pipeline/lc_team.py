"""生活圈体检专家团动态编排（Phase 6）。

从 48 位专家名册中 LLM 挑选适合生活圈体检的团队，替代硬编码的 13 人列表。
失败时回退到领域保底名单（基于设施类别与体检维度自动匹配）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── 保底团队：按生活圈体检的核心域划分 ─────────────────────
_FACILITY_DOMAINS = {
    "medical": ["L2-001", "L1-003", "L1-004"],       # 医疗顾问 + 医院/诊所核验
    "education": ["L2-002", "L1-006", "L1-007"],     # 教育规划师 + 幼儿园/中小学核验
    "shopping": ["L2-004", "L1-001", "L1-002"],      # 商业顾问 + 菜场/超市核验
    "elderly": ["L2-003", "L1-019", "L1-020"],       # 养老顾问 + 养老/助餐核验
}

_FALLBACK_TEAM = [
    "L3-001", "L3-002", "L3-003",  # 决策层统筹
    "L2-001", "L2-002", "L2-003", "L2-004", "L2-005", "L2-008",  # 核心策略顾问
    "L1-001", "L1-004", "L1-005", "L1-008",  # 关键执行专家
]


def _roster_index() -> Dict[str, dict]:
    """构建 id → expert 索引（从生活圈域名册 load_experts('living_circle')）。"""
    from app.data import load_experts
    return {e["id"]: e for e in load_experts("living_circle")}


def select_living_circle_team(
    scene_name: str = "",
    facility_categories: List[str] | None = None,
    travel_mode: str = "walking",
) -> Tuple[List[str], List[str]]:
    """为生活圈体检动态选择专家团队。

    参数：
        scene_name: 场景名称（如"XX社区"）
        facility_categories: 涉及的设施类别（如 ["医疗", "教育", "购物"]）
        travel_mode: 出行方式（walking/riding/driving）

    返回：
        (expert_ids, reasons) 元组，ids 均经名册校验
    """
    roster = _roster_index()

    # 尝试 LLM 编排
    picked: List[Tuple[str, str]] = []
    try:
        from app.core.expert_prompt import roster_payload
        from app.core.llm import chat_json

        # 构建上下文：哪些设施类别需要评估
        categories_text = "、".join(facility_categories) if facility_categories else "全类别民生设施"

        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是常青圈生活圈体检编排官（L3 决策层）。从 48 位专家名册中为一次『15 分钟生活圈体检』"
                    "挑选最合适的团队（建议 8-13 人），覆盖以下职责："
                    "1. 决策层（L3）：1-2 位统筹体检全流程与终审签发；"
                    "2. 策略层（L2）：医疗/教育/商业/养老/交通等各领域顾问各 1 位；"
                    "3. 执行层（L1）：空间定位、POI 核验、步行测时、评分建模等方法专家若干。"
                    "为每位被选专家给出一句具体的指派理由（说明他/她负责什么、为什么适合本次体检）。"
                    '只输出 JSON：{"team":[{"id":"专家id","reason":"指派理由"}]}，id 必须取自名册，不得编造。'
                )},
                {"role": "user", "content": (
                    f"体检场景：{scene_name or '未命名社区'}\n"
                    f"重点设施：{categories_text}\n"
                    f"出行方式：{travel_mode}\n"
                    f"{roster_payload(list(roster.values()))}"
                )},
            ],
            temperature=0.3, purpose="生活圈体检编排专家团",
        )

        if isinstance(data, dict):
            seen: set = set()
            for it in (data.get("team") or []):
                eid = str(it.get("id") or "").strip()
                if eid in roster and eid not in seen:
                    seen.add(eid)
                    reason = str(it.get("reason") or "").strip() or "分工"
                    picked.append((eid, reason))

    except Exception as e:  # noqa: BLE001
        logger.warning("生活圈体检 LLM 编排失败，回退领域保底: %s", e)

    # 若 LLM 选人不足，使用保底团队
    if len(picked) < 5:
        return _fallback_team_for_categories(facility_categories or [])

    # 领队优先：让 Level 最高（L3）的成员排第一
    def _lv(eid: str) -> int:
        return {"L3": 3, "L2": 2, "L1": 1}.get((eid or "").split("-")[0], 0)

    picked.sort(key=lambda pair: -_lv(pair[0]))
    ids = [p[0] for p in picked]
    reasons = [p[1] for p in picked]
    return ids, reasons


def _fallback_team_for_categories(categories: List[str]) -> Tuple[List[str], List[str]]:
    """根据设施类别生成保底团队。"""
    ids: List[str] = []
    reasons: List[str] = []

    # 始终包含决策层
    ids.extend(["L3-001", "L3-002"])
    reasons.extend([
        "决策层统筹体检全流程与终审签发",
        "把控设施覆盖与评分建模的逻辑严谨性",
    ])

    # 根据设施类别添加对应策略顾问
    added_domains = set()
    for cat in categories:
        domain = _map_category_to_domain(cat)
        if domain and domain not in added_domains:
            domain_experts = _FACILITY_DOMAINS.get(domain, [])
            if domain_experts:
                ids.append(domain_experts[0])  # 取策略顾问
                reasons.append(f"负责{cat}设施的配置密度与可达性评估")
                added_domains.add(domain)

    # 若没有特定类别，添加默认核心顾问
    if not added_domains:
        default_advisors = ["L2-001", "L2-002", "L2-004"]
        for eid in default_advisors:
            if eid not in ids:
                ids.append(eid)
                reasons.append("核心领域顾问负责基础民生设施评估")

    # 添加关键方法专家
    method_experts = {
        "L1-025": "空间定位师负责中心点定位与坐标解析",
        "L1-030": "POI 核验官负责设施点位检索核验",
        "L1-027": "可达性测算师负责步行耗时测时",
        "L1-032": "评分建模师负责四维体检评分计算",
    }
    for eid, reason in method_experts.items():
        if eid not in ids:
            ids.append(eid)
            reasons.append(reason)

    # 去重并保持顺序
    seen = set()
    unique_ids = []
    unique_reasons = []
    for eid, reason in zip(ids, reasons):
        if eid not in seen:
            seen.add(eid)
            unique_ids.append(eid)
            unique_reasons.append(reason)

    return unique_ids, unique_reasons


def _map_category_to_domain(category: str) -> str | None:
    """将设施类别映射到领域标识。"""
    mapping = {
        "医疗": "medical", "医院": "medical", "诊所": "medical", "药店": "medical",
        "教育": "education", "小学": "education", "幼儿园": "education", "中学": "education",
        "购物": "shopping", "菜市场": "shopping", "超市": "shopping", "便利店": "shopping",
        "养老": "elderly", "养老院": "elderly", "助餐": "elderly", "日间照料": "elderly",
    }
    for keyword, domain in mapping.items():
        if keyword in category:
            return domain
    return None
