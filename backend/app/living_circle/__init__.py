"""常青圈 · 15 分钟生活圈体检域（独立子域，A1）。

与旧 research 域完全隔离：本包只关心「地图能力 → 生活圈体检报告」，
不 import app.core.orchestrator / runner / search / fetcher。
契约对齐前端 F0 冻结的 `LivingCircleReport`（src/types.ts），
即本包产出的 dict 结构 = 前端类型（scene/isochrones/sampling/poi/blindspots/scores）。
"""