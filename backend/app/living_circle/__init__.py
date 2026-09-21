"""常青圈 · 15 分钟生活圈体检域（独立子域，A1）。

与旧 research 域完全隔离：本包只关心「地图能力 → 生活圈体检报告」，
不 import app.core.orchestrator / runner / search / fetcher。
契约对齐前端 F0 冻结的 `LivingCircleReport`（src/types.ts），
即本包产出的 dict 结构 = 前端类型（scene/isochrones/sampling/poi/blindspots/scores）。
"""

# ── 启动期注册：将生活圈子域的口径解析器注入通用引擎层 ──────────
# 条件导入：caliber_index 在 Phase 4 创建前不存在，此时注册静默跳过，
# expert_directive 优雅降级为只渲染 ref 标识符而不渲染 value。
try:
    from app.living_circle import caliber_index
    from app.core.expert_prompt import register_caliber_resolver

    for ns in caliber_index.NAMESPACES:
        register_caliber_resolver(ns, caliber_index.view)
except ImportError:
    # Phase 4 尚未完成时，注入链路静默关闭（可观测但不阻断）
    import logging
    logging.getLogger(__name__).warning(
        "caliber_index 未就绪，专家口径注入已跳过（Phase 4 完成后自动激活）"
    )
