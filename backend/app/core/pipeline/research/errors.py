"""旅游调研任务层领域异常（M3 自 engine.py 原文迁出）。

shell/planning/API 共同消费；独立成模块避免子模块反向 import engine。
"""
from __future__ import annotations


class GuideSingleDestinationError(ValueError):
    """guide 档位结构性约束：地图/路线/评分配额均以单目的地为前提（计划待确认 #7 拍板硬拒绝）。"""


class ClarifyAnswerRequiredError(ValueError):
    """已触发的条件题（show_if）缺答——首个必答闸门（rough-cliff-vole）。

    只对触发态拒：未触发的隐藏题缺答不拒（非亲子用户根本看不到该题）。
    """
