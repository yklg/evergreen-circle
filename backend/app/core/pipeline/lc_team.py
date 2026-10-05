"""生活圈体检专家团动态编排（Phase 6）。

从 48 位专家名册中 LLM 挑选适合生活圈体检的团队，替代硬编码的 13 人列表。
失败时回退到保底名单，并把**降级原因带出去**（第三个返回值）—— 旧实现是静默换人：
调用方与用户都分不清"这次是模型挑的人"还是"兜底凑的人"，而这两者的可信度不是一回事。

`degraded` 取值：`""`（正常）/ `"llm_error"`（编排调用抛错）/ `"team_too_small"`（返回不足 5 人）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── 保底团队（决策层 2 ＋ 四领域顾问 ＋ 四方法专家）─────────────────
# 刻意**不按设施类别裁剪**：原先有一张「类别→顾问」的映射表，但它依赖的
# `facility_categories` 参数前端从未传过、`TaskParams` 里也没这个字段，且组队排在
# POI 采集之前（类别那时还没确定）⇒ 那条分支线上永远走不到，只有测试在跑。
# 同时它还有席位错位（elderly 挂的 L1-019/L1-020 其实是「无障碍环境顾问」
# 「儿童友好规划师」，机构养老顾问是 L1-008）。与其留一份假装在工作的表，
# 不如把保底名单写成一份确定的、与名册职位对得上的组合。
_FALLBACK_SEATS: Tuple[Tuple[str, str], ...] = (
    ("L3-001", "统筹体检全流程、统一指标口径并终审签发"),
    ("L3-002", "把控设施覆盖与评分建模的逻辑严谨性"),
    ("L2-001", "负责医疗类设施的配置密度与就医可达性评估"),
    ("L2-002", "负责教育类设施的学位与就近入学情况评估"),
    ("L2-003", "负责养老与托育设施的配置评估"),
    ("L2-004", "负责菜市场与商业配套的覆盖评估"),
    ("L1-025", "负责中心点定位与坐标解析"),
    ("L1-030", "负责设施点位检索与核验"),
    ("L1-027", "负责步行耗时测时与可达性测算"),
    ("L1-032", "负责四维体检评分计算与建模"),
)


def _all_categories_text() -> str:
    """体检覆盖的设施类别：从唯一真相源 `CATEGORY_RULES` 遍历取，不手工点取。

    与报告侧「图 8 类、文 5 类」那次根因同源 —— 类别一旦增删，这里自动跟上，
    不需要任何人记得改第二处。
    """
    from app.living_circle.category_rule import CATEGORY_RULES

    return "、".join(str(v.get("label") or k) for k, v in CATEGORY_RULES.items())


def _roster_index() -> Dict[str, dict]:
    """构建 id → expert 索引（从生活圈域名册 load_experts('living_circle')）。"""
    from app.data import load_experts
    return {e["id"]: e for e in load_experts("living_circle")}


def select_living_circle_team(
    scene_name: str = "",
    travel_mode: str = "walking",
) -> Tuple[List[str], List[str], str]:
    """为生活圈体检动态选择专家团队。

    参数：
        scene_name: 场景名称（如"XX社区"）
        travel_mode: 出行方式（walking/riding/driving）

    返回：
        `(expert_ids, reasons, degraded)` 三元组；ids 均经名册校验，
        `degraded` 为空串表示这次是 LLM 挑的人，非空表示换了保底名单及其原因。

    刻意**没有** `facility_categories` 形参：那个参数从来没有调用方会传（见文件头注释），
    留着它比删掉更危险 —— 读代码的人会以为"按类别配顾问"这件事在发生。
    """
    roster = _roster_index()

    # 尝试 LLM 编排
    picked: List[Tuple[str, str]] = []
    llm_failed = False
    try:
        from app.core.expert_prompt import roster_payload
        from app.core.llm import chat_json

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
                    f"体检类别（全部 8 类都要评）：{_all_categories_text()}\n"
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
        llm_failed = True
        logger.warning("生活圈体检 LLM 编排失败，回退保底名单: %s", e)

    # 若 LLM 选人不足，换保底团队 —— 且要把"为什么换"带出去，不能静默
    if len(picked) < 5:
        ids, reasons = _fallback_team()
        return ids, reasons, "llm_error" if llm_failed else "team_too_small"

    # 领队优先：让 Level 最高（L3）的成员排第一
    def _lv(eid: str) -> int:
        return {"L3": 3, "L2": 2, "L1": 1}.get((eid or "").split("-")[0], 0)

    picked.sort(key=lambda pair: -_lv(pair[0]))
    ids = [p[0] for p in picked]
    reasons = [p[1] for p in picked]
    return ids, reasons, ""


def _fallback_team() -> Tuple[List[str], List[str]]:
    """保底团队：决策层 2 ＋ 四领域顾问 ＋ 四方法专家（席位与理由见 `_FALLBACK_SEATS`）。

    名册里查不到的席位直接跳过并记 warning —— 保底名单自己绝不能交出一个悬空 id，
    否则报告署名会退化成裸 id（`diagnosis_templates._expert` 的回落路径）。
    """
    roster = _roster_index()
    pairs = [(eid, reason) for eid, reason in _FALLBACK_SEATS if eid in roster]
    dropped = [eid for eid, _ in _FALLBACK_SEATS if eid not in roster]
    if dropped:
        logger.warning("保底名单有席位不在生活圈名册，已跳过：%s", "、".join(dropped))
    return [eid for eid, _ in pairs], [reason for _, reason in pairs]
