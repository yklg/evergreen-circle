"""目的地调研的产出体裁（voice）单一真源：REPORT_PROFILES + report_voice。

把「目的地攻略 / 目的地评估 / 综合」三种产出的章节集、撰稿人设、标题语收敛到一处，
供目的地调研流水线（app.core.pipeline.research）与报告后处理共用。

设计要点：
  - 三档（按工作台用途三选项划分）：guide 攻略 / assess 评估 / research 综合（并集）。
  - 每一档都包含口碑/舆情章（guide_voice / assess_voice），不含任何「竞品」字眼与对比。
  - 未知/空 purpose 返回空 dict（等价类+边界），不抛、不污染。
"""
from __future__ import annotations

from typing import Any, Dict

_GUIDE = {
    "label": "目的地攻略",
    "persona": (
        "你是资深旅游策划 + 目的地攻略专栏作家级别的报告撰稿人。"
        "你在为真实出行者撰写一份『目的地攻略』报告——要能照做、有判断、有细节，"
        "不是泛泛的景点罗列。"
    ),
    "sections": [
        "summary", "guide_overview", "guide_transport", "guide_food_stay",
        "guide_route", "guide_safe", "guide_budget", "guide_voice", "conclusion",
    ],
}

_ASSESS = {
    "label": "目的地评估",
    "persona": (
        "你是资深城市规划 + 旅游经济评估专家级的报告撰稿人。"
        "你在撰写一份『目的地可行性/宜居评估』报告——从可达性、配套、性价比、安全"
        "多维度给出严谨评估与明确结论，敢下判断、有数据支撑。"
    ),
    "sections": [
        "summary", "assess_access", "assess_amenity", "assess_price",
        "assess_safety", "assess_voice", "assess_conclusion", "conclusion",
    ],
}

# research（综合）= 前两者章节并集：独立人设 + 去重后的章节序（口碑/舆情章保留两份词目）。
_RESEARCH = {
    "label": "目的地综合调研",
    "persona": (
        "你是资深文旅研究 + 项目策划双栖专家级的报告撰稿人。"
        "你在一份『目的地综合调研』报告里，既给出可供照做的攻略，也给出客观的宜居/可行性评估，"
        "攻略与评估兼顾，结论清晰、有据可查。"
    ),
    "sections": [
        "summary", "guide_overview", "guide_transport", "guide_food_stay",
        "guide_route", "guide_safe", "guide_budget",
        "assess_access", "assess_amenity", "assess_price", "assess_safety",
        "assess_conclusion", "guide_voice", "assess_voice", "conclusion",
    ],
}

REPORT_PROFILES: Dict[str, Dict[str, Any]] = {
    "guide": _GUIDE,
    "assess": _ASSESS,
    "research": _RESEARCH,
}


def report_voice(purpose: str) -> Dict[str, Any]:
    """按目的地产出体裁返回报告 voice（人设/标题语/章节集）；未知或空返回空 dict。

    单一真相源：主写入引擎与后续报告精炼共用，保证「目的地调研」不被竞品/生活圈
    人设染色（错域防护）。
    """
    return REPORT_PROFILES.get(purpose, {})