"""旅游调研引擎域（M2-flip 自 gaizao orchestrator 整体平移；M3 模块提取收口）。

分层（依赖单向向下，G-5/G-6/G-7 守卫机器校验）：
  engine       编排顶层：公共 task/clarify/brief/refine 入口 + research_pipeline
  modes        三档规模旋钮（MODE_CONFIG / CORE_SECTIONS）
  planning     需求拆解与目的地发现；dispatch 组队降级；collect 证据采集
  analyze      结构化分析与 typed sanitizer；spots 景点实体/真实路线/舆情二查
  perspective  视角专属核查块；writer 逐章撰写与写后修复；charts_build 图表注册表
  assemble     报告总装；runtime 每任务模型 ContextVar
  _util/errors 共享纯工具与域异常

对外仅暴露 research_pipeline；任务外壳/brief/refine 经 app.core.orchestrator
（只依赖本包 engine 公共面）re-export。
"""
from .engine import research_pipeline

__all__ = ["research_pipeline"]
