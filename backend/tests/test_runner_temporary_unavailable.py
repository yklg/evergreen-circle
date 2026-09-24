"""调研主流程 503 友好文案测试（S4 / 评审 P1-b）。

守护 runner._drive 异常收口：当调研进行中遇 Google 临时高负载（503），
失败态文案应为友好中文「负载较高（503）」，而非原始英文栈。

注意：runner 通过封闭注册表 KIND_PIPELINES 分发到 research_pipeline（而非
legacy orchestrator.run_pipeline），因此这里 patch 的是真正的分发目标。
"""
import asyncio

from app.core import orchestrator
from app.core.pipeline.research import engine as research
from app.core.runner import _Run, _drive


def test_runner_503_friendly_message(monkeypatch):
    # 异步生成器（async for 会立即在首个 yield 前抛出 503）
    async def _boom_pipeline(task_id):
        e = RuntimeError(
            "Error code: 503 ... currently experiencing high demand ... status: 'UNAVAILABLE'"
        )
        e.status_code = 503
        raise e
        yield  # noqa: UNREACHABLE (保持 async generator，供 `async for` 消费)

    monkeypatch.setattr(research, "research_pipeline", _boom_pipeline)

    r = _Run()
    asyncio.run(_drive("t1", r))

    assert r.status == "failed"
    assert "负载较高（503）" in (r.error or "")
