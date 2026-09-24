"""任务外壳兼容层（M2-flip：旅游引擎已整体归入 app.core.pipeline.research）。

职责边界（import 方向由 test_import_direction_guard 守护）：
  - 本模块**不再包含任何编排/写作/采集逻辑**，仅 re-export 引擎的任务生命周期
    （建任务/澄清问卷/brief/refine）符号，供 main.py 与既有测试稳定导入；
  - 运行期任务一律由 runner.KIND_PIPELINES 直接驱动 pipeline.research.research_pipeline；
  - 生活圈域 pipeline/living_circle.py 与本模块无依赖关系。

M3 语义精修时，任务外壳若需独立演进，再从 engine.py 提取到本文件（方向不变）。
"""
from __future__ import annotations

from app.core.pipeline.research.engine import (
    ClarifyAnswerRequiredError,
    GuideSingleDestinationError,
    brief_report_pipeline,
    create_brief_task,
    create_refine_task,
    create_task,
    generate_brief,
    generate_clarify,
    refine_report_pipeline,
    refine_section,
    research_pipeline,
    submit_clarify,
)

# 兼容别名：gaizao main.py 与部分测试按 run_pipeline 名称导入；
# 行为即 research_pipeline（注册表经 runner 解析，不经此别名）。
run_pipeline = research_pipeline

__all__ = [
    "ClarifyAnswerRequiredError",
    "GuideSingleDestinationError",
    "brief_report_pipeline",
    "create_brief_task",
    "create_refine_task",
    "create_task",
    "generate_brief",
    "generate_clarify",
    "refine_report_pipeline",
    "refine_section",
    "research_pipeline",
    "run_pipeline",
    "submit_clarify",
]
