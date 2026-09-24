"""旅游调研引擎域（M2-flip 自 gaizao orchestrator 整体平移）。

M3 将按 planning/dispatch/collect/spots/perspective/writer/charts_build/assemble
逐模块提取；当前 engine.py 为平移单体，模块级状态（_GEN_INFLIGHT/ContextVar/
信源组池/trunc 去重）原样保留在同一文件内。
对外仅暴露 research_pipeline；任务外壳/brief/refine 经 app.core.orchestrator re-export。
"""
from .engine import research_pipeline

__all__ = ["research_pipeline"]
