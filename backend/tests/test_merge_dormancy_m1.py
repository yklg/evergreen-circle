"""T-14a · M1 休眠态保护网（融合 W1 波次 · 临时用例，M2-flip 提交时删除）。

守护什么：M1 是零行为变更树合并——改造侧 4942 行旅游引擎在此阶段**不得以任何
形式被 runner 路由**，research/travel_* 必须仍走当前简版流水线
（app.core.pipeline.research 单文件模块）。若 M1 选边误把 gaizao runner/orchestrator
取入，本测试立即变红。

生命周期：
  M1 前生成（当前 main 即绿）→ M1 合并后必须仍绿 → **M2-flip 提交删除本文件**，
  由 flip 后的形态测试取代（research 成为 pipeline.research 包，工厂指向新引擎）。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import app.core.runner as runner
import app.core.pipeline as pipeline_pkg

PIPELINE_DIR = Path(pipeline_pkg.__file__).resolve().parent


def test_research_factory_still_points_to_legacy_module():
    """research/travel_* 三个 kind 的工厂必须惰性导入单文件 pipeline.research。"""
    src = inspect.getsource(runner._load_research)
    assert "from app.core.pipeline.research import research_pipeline" in src, (
        "M1 休眠态：research 工厂必须仍指向 app.core.pipeline.research（简版单文件）"
    )
    assert "pipeline_travel" not in src and "pipeline.research." not in src, (
        "M1 休眠态：research 工厂不得提前指向休眠/包化引擎"
    )


def test_legacy_research_module_is_a_file_not_package():
    """app/core/pipeline/research 必须仍是 .py 单文件（同名包目录不得在 M1 出现）。"""
    assert (PIPELINE_DIR / "research.py").is_file(), "简版 pipeline/research.py 丢失"
    assert not (PIPELINE_DIR / "research").is_dir(), (
        "M1 不得提前创建 pipeline/research/ 包（与简版单文件同名冲突，属 flip 动作）"
    )


def test_no_dormant_engine_path_registered():
    """任何休眠引擎路径都不得出现在封闭注册表中。"""
    for kind, factory in runner.KIND_PIPELINES.items():
        src = inspect.getsource(factory)
        assert "pipeline_travel" not in src, f"kind={kind} 提前路由到休眠引擎"
    assert "engine" not in " ".join(runner.KIND_PIPELINES.keys()), (
        "注册表不得出现 engine 类 kind"
    )


def test_registry_keys_unchanged_in_m1():
    """M1 注册表键集合与 main 基线逐键一致（flip 才允许调整）。"""
    assert set(runner.KIND_PIPELINES.keys()) == {
        "research",
        "travel_guide",
        "travel_assess",
        "refine",
        "brief",
        "living_circle",
    }
