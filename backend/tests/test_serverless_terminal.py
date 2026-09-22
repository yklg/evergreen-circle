"""serverless 入口（api/index.py）终态收口（修复计划 item3b·评审 P0-1；覆盖评估 D 组）。

api/index.py 的 stream_task 直驱 run_pipeline、**不经 runner**：若 yield error /
raise / 无终态耗尽都不落库，线上形态会原样复活「悬空 running → 无限重跑」故障。
本文件按文件路径加载 index.py（sys.modules 已有 backend 的 app 包，镜像同构），
对 gen 路径钉与 runner 同一终态契约。

- TC-X1 管线 yield error → DB failed + 线上下发 error 帧
- TC-X2 管线 raise → DB failed；无终态耗尽 → 合成 failed + error 帧
运行：backend/ 下 `pytest tests/test_serverless_terminal.py -q`
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path

import pytest

from app.core import db
from app.core import orchestrator as O

_INDEX_PATH = Path(__file__).resolve().parents[2] / "api" / "index.py"


def _load_serverless():
    spec = importlib.util.spec_from_file_location("serverless_index", _INDEX_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_serverless()


class _Req:
    """最小 Request 替身：永不判为断连。"""

    async def is_disconnected(self):
        return False


async def _drain_sse(resp_coro):
    resp = await resp_coro
    frames = []
    async for chunk in resp.body_iterator:
        frames.append(chunk)
    return frames


def _err_frame_of(frames):
    for f in frames:
        head, _, data = f.partition("\n")
        if head.startswith("event: error"):
            return json.loads(data.removeprefix("data: "))
    return None


def test_serverless_error_event_terminalizes_db(monkeypatch):
    async def _err(task_id, sub_id=""):
        yield {"type": "error", "data": {"message": "博查账户余额不足，请充值"}}

    monkeypatch.setattr(mod, "run_pipeline", _err)
    tid = O.create_task("大理 终态收口测试", "quick", "", "guide")["taskId"]
    frames = asyncio.run(_drain_sse(mod.stream_task(tid, _Req())))

    full = db.get_task_full(tid)
    assert full["status"] == "failed"
    assert "博查账户余额不足" in (full.get("error") or "")
    assert _err_frame_of(frames) is not None


def test_serverless_raise_terminalizes_db(monkeypatch):
    async def _boom(task_id, sub_id=""):
        raise RuntimeError("下游炸了")
        yield

    monkeypatch.setattr(mod, "run_pipeline", _boom)
    tid = O.create_task("大理 终态收口测试", "quick", "", "guide")["taskId"]
    frames = asyncio.run(_drain_sse(mod.stream_task(tid, _Req())))

    full = db.get_task_full(tid)
    assert full["status"] == "failed" and "下游炸了" in (full.get("error") or "")
    assert _err_frame_of(frames) is not None


def test_serverless_exhaustion_synthesizes_failed(monkeypatch):
    async def _drift(task_id, sub_id=""):
        yield {"type": "progress", "data": {"percent": 5, "stage": "collect",
                                            "evidence_count": 0}}

    monkeypatch.setattr(mod, "run_pipeline", _drift)
    tid = O.create_task("大理 终态收口测试", "quick", "", "guide")["taskId"]
    frames = asyncio.run(_drain_sse(mod.stream_task(tid, _Req())))

    full = db.get_task_full(tid)
    assert full["status"] == "failed" and "未落终态" in (full.get("error") or "")
    assert _err_frame_of(frames) is not None, "守卫必须向客户端补发 error 帧"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
