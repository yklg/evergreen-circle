"""生活圈体检流水线（A2：与旧 research 流水线并列的独立编排域）。"""

from .living_circle import create_living_circle_task, living_circle_pipeline

__all__ = ["create_living_circle_task", "living_circle_pipeline"]