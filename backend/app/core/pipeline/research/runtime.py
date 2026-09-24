"""旅游引擎运行时模型解析（M3 自 engine.py 原文迁出）。

每任务协程隔离的 ContextVar + 模型档位解析；各子模块共享，不反向依赖 engine。
"""
from __future__ import annotations

from contextvars import ContextVar

from app.core.runtime_config import get_effective_settings


# 单条调研任务的「用户指定分析模型」覆盖（仅 core/aux 档生效，fast 杂务不动）。
# ContextVar 随每个 asyncio pipeline 协程隔离；run_pipeline 入口 set 覆盖式写入，
# 不同任务之间无串扰（且每次 set 覆盖旧值，无累积）。
_pipeline_model_override: ContextVar[str] = ContextVar("_pipeline_model_override", default="")


def _model(tier: str) -> str:
    """tier: 'core' | 'aux' | 'fast' → 实际模型名。

    每次调用都读运行时有效配置（env 默认 + 界面覆盖），
    因此用户在「模型配置」改了模型矩阵后下一次调研立即生效，无需重启。

    override：若本次调研用户在 HomePage 指定了分析模型（core/aux 档），
    则核心章与辅助章统一用该模型；fast 杂务（intake/情感分类/专家指派）
    始终走 settings.fast，不被覆盖。返回**永远是纯模型名**（直接作 LLM API
    的 model 参数），绝不带任何后缀——(override) 标注只在 trace 展示层加。
    """
    override = _pipeline_model_override.get()
    s = get_effective_settings()
    if tier == "fast":
        # 杂务快速档不受 override 影响，始终按 settings
        return s.get("llm_model_fast") or ""
    if override:
        # 核心章 / 辅助章统一用用户指定的分析模型
        return override
    if tier == "core":
        return s.get("llm_model_core") or ""
    return s.get("llm_model_aux") or ""
