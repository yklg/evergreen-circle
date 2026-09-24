"""runner 终态契约统一（修复计划 wise-flint-darter item1/item2；覆盖评估 A 组 7 钉）。

守护的不变量（终态契约）：管线生成器必须以且仅以一条终态事件（done/error）结束，
或抛异常；runner 是唯一写终态入库、且唯一保证线上有对应终态帧的地方。
读端点（subscribe/ensure_running）零执行副作用：孤儿 running 就地收 failed，绝不重跑。

- TC-R1 管线 yield error → DB failed、真因文案落库、后续订阅不重跑（本次循环故障回归钉）
- TC-R2 管线 raise → 客户端**收到含 message 的 error 帧**（帧断言，补强既有只断状态的种子）
- TC-R3 无终态直接耗尽 → 合成 error 帧 + failed（协议违例守卫）
- TC-R4 brief 形态双写（管线自写 failed + yield error）→ 终态不矛盾、文案不被通用值覆盖
- TC-R5 孤儿 running（DB running + 内存无活句柄）→ 只出 error 帧、不创建运行
- TC-R6 双订阅者：snapshot 回放 + 实时流零重叠、零丢失
- TC-R7 订阅者中途断开 → subs 清理，其余订阅者事件不丢
运行：backend/ 下 `pytest tests/test_runner_terminal.py -q`
"""
import asyncio

import pytest

from app.core import db, orchestrator, runner
from app.core.pipeline.research import engine as O


def _new_task(kind=None):
    tid = O.create_task("大理 终态契约测试", "quick", "", "guide")["taskId"]
    if kind:
        db._connect().execute("UPDATE tasks SET kind=? WHERE task_id=?", (kind, tid))
        db._connect().commit()
    return tid


async def _collect(task_id):
    evs = []
    async for ev in runner.subscribe(task_id):
        evs.append(ev)
    return evs


# ── TC-R1 yield error 终态收口 ───────────────────────────
def test_error_event_terminalizes_and_no_rerun(monkeypatch):
    runner._running.clear()
    calls = []

    async def _err_pipeline(task_id):
        calls.append(task_id)
        yield {"type": "error",
               "data": {"message": "本次未能采集到任何可用证据：博查账户余额不足（请检查搜索服务配额/密钥）"}}

    monkeypatch.setattr(O, "research_pipeline", _err_pipeline, raising=False)
    tid = _new_task()

    async def _scenario():
        runner.ensure_running(tid)
        await asyncio.sleep(0.2)
        return await _collect(tid)   # 故障现场：前端重连订阅
    evs = asyncio.run(_scenario())

    full = db.get_task_full(tid)
    assert full["status"] == "failed"
    assert "博查账户余额不足" in (full.get("error") or "")
    # 重连订阅只补一帧 error（真因），且不再触发流水线
    assert [e["type"] for e in evs] == ["error"]
    assert "博查账户余额不足" in evs[0]["data"]["message"]
    assert calls == [tid], "订阅终态任务不得重跑管线"


# ── TC-R2 raise → 线上广播 error 帧 ──────────────────────
def test_raise_broadcasts_error_frame_to_subscriber(monkeypatch):
    runner._running.clear()

    async def _boom(task_id):
        raise RuntimeError("博查账户余额不足，请充值")
        yield  # noqa: 保持 async generator

    monkeypatch.setattr(O, "research_pipeline", _boom, raising=False)
    tid = _new_task()

    async def _scenario():
        runner.ensure_running(tid)   # _drive 已建但未开跑
        return await _collect(tid)   # 订阅挂上后才轮到 _drive → 首步即抛
    evs = asyncio.run(_scenario())

    errs = [e for e in evs if e["type"] == "error"]
    assert errs, f"raise 通道线上必须有 error 帧，实收：{[e['type'] for e in evs]}"
    assert "博查账户余额不足" in errs[0]["data"]["message"]
    assert db.get_task_full(tid)["status"] == "failed"


# ── TC-R3 无终态耗尽守卫 ─────────────────────────────────
def test_exhausted_without_terminal_synthesizes_error(monkeypatch):
    runner._running.clear()

    async def _drift(task_id):
        yield {"type": "progress", "data": {"percent": 30, "stage": "collect", "evidence_count": 0}}
        return  # 协议违例：既不 done 也不 error

    monkeypatch.setattr(O, "research_pipeline", _drift, raising=False)
    tid = _new_task()

    async def _scenario():
        runner.ensure_running(tid)
        return await _collect(tid)
    evs = asyncio.run(_scenario())

    assert evs[-1]["type"] == "error"
    assert "未落终态" in evs[-1]["data"]["message"]
    full = db.get_task_full(tid)
    assert full["status"] == "failed" and "未落终态" in (full.get("error") or "")


# ── TC-R4 brief 双写幂等（runner 权威 + 管线自写兼容）────
def test_brief_self_write_double_terminal_idempotent(monkeypatch):
    runner._running.clear()
    calls = []
    real_msg = "简报失败：源报告缺失"

    async def _brief(task_id):
        calls.append(task_id)
        db.set_task_failed(task_id, real_msg)   # 管线自写（冗余兼容）
        yield {"type": "error", "data": {"message": real_msg}}

    monkeypatch.setattr(O, "brief_report_pipeline", _brief, raising=False)
    tid = _new_task(kind="brief")

    async def _scenario():
        runner.ensure_running(tid)
        await asyncio.sleep(0.2)
        return await _collect(tid)
    evs = asyncio.run(_scenario())

    full = db.get_task_full(tid)
    assert full["status"] == "failed"
    # 双写同值幂等：文案是管线/帧里的真因，不被守卫的通用值覆盖
    assert full.get("error") == real_msg
    assert [e["type"] for e in evs] == ["error"]
    assert evs[0]["data"]["message"] == real_msg
    assert calls == [tid], "双写收口后订阅不得重跑"


# ── TC-R5 孤儿 running：读端点零执行副作用 ───────────────
def test_orphan_running_marks_failed_without_restart(monkeypatch):
    runner._running.clear()
    calls = []

    async def _never(task_id):
        calls.append(task_id)
        yield {"type": "done", "data": {"reportId": "r_x"}}

    monkeypatch.setattr(O, "research_pipeline", _never, raising=False)
    tid = _new_task()
    db.set_task_running(tid)   # 人为制造「DB running + 内存无活句柄」孤儿

    async def _scenario():
        return await _collect(tid)
    evs = asyncio.run(_scenario())

    assert [e["type"] for e in evs] == ["error"]
    assert "任务已中断" in evs[0]["data"]["message"]
    full = db.get_task_full(tid)
    assert full["status"] == "failed" and "任务已中断" in (full.get("error") or "")
    assert calls == [], "孤儿 running 绝不允许静默重跑（重跑唯一入口=新建任务）"
    assert runner._running[tid].task is None


# ── TC-R6 双订阅者：回放+实时零重叠、零丢失 ──────────────
def test_two_subscribers_no_overlap_no_loss(monkeypatch):
    runner._running.clear()
    n = 6

    async def _slow(task_id):
        for i in range(n):
            await asyncio.sleep(0.005)
            yield {"type": "progress", "data": {"percent": 10 + i, "stage": "collect",
                                                "evidence_count": i}}
        yield {"type": "done", "data": {"reportId": "r_r6"}}

    monkeypatch.setattr(O, "research_pipeline", _slow, raising=False)
    tid = _new_task()

    async def _scenario():
        r = runner._Run()
        runner._running[tid] = r
        r.task = asyncio.create_task(runner._drive(tid, r))
        ta = asyncio.create_task(_collect(tid))
        await asyncio.sleep(0.02)          # A 已在半途，B 中途加入（先回放后实时）
        tb = asyncio.create_task(_collect(tid))
        return await asyncio.gather(ta, tb)
    a, b = asyncio.run(_scenario())

    types = [e["type"] for e in a]
    assert types == ["progress"] * n + ["done"], f"A 应收全序：{types}"

    def _bare(evs):
        return [(e["type"], {k: v for k, v in e["data"].items() if k != "replay"}) for e in evs]

    assert _bare(a) == _bare(b), "中途订阅者 snapshot+实时 必须与早订阅者逐帧一致（零重叠零丢失）"
    # 回放标记契约（派遣节流队列的直刷判据）：B 的回放段是**前缀**（先 snapshot 后实时），
    # 实时段与早订阅者 A 全程不带标记。切分点由时序决定，不逐帧钉死。
    flags = [bool(e["data"].get("replay")) for e in b]
    assert flags == [True] * flags.count(True) + [False] * flags.count(False), \
        f"replay 标记必须呈前缀分布：{flags}"
    assert any(flags), "B 中途加入必有回放段"
    assert not any(bool(e["data"].get("replay")) for e in a), "早订阅者全程为实时帧（实时段不带标记由 A 钉住）"
    seen = [(e["type"], e["data"].get("percent")) for e in a]
    assert len(set(seen)) == len(seen), "不得有重复帧"
    assert db.get_task_full(tid)["status"] == "done"


# ── TC-R7 订阅者断开清理 ─────────────────────────────────
def test_dropped_subscriber_cleaned_up(monkeypatch):
    runner._running.clear()

    async def _slow(task_id):
        for i in range(8):
            await asyncio.sleep(0.005)
            yield {"type": "progress", "data": {"percent": 10 + i, "stage": "collect",
                                                "evidence_count": i}}
        yield {"type": "done", "data": {"reportId": "r_r7"}}

    monkeypatch.setattr(O, "research_pipeline", _slow, raising=False)
    tid = _new_task()

    async def _scenario():
        r = runner._Run()
        runner._running[tid] = r
        r.task = asyncio.create_task(runner._drive(tid, r))
        ta = asyncio.create_task(_collect(tid))
        tb = asyncio.create_task(_collect(tid))
        await asyncio.sleep(0.02)
        assert len(r.subs) == 2
        tb.cancel()                    # 模拟一订阅者断连
        await asyncio.gather(tb, return_exceptions=True)
        await asyncio.sleep(0)
        assert len(r.subs) == 1, "断开者队列必须从 subs 移除"
        evs = await ta                 # 另一订阅者不受影响，收全序
        return evs
    evs = asyncio.run(_scenario())

    assert [e["type"] for e in evs] == ["progress"] * 8 + ["done"]
    assert db.get_task_full(tid)["status"] == "done"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
