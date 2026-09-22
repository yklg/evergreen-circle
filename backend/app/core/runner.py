"""任务执行与传输解耦层（后台常驻重构的核心）。

此前 `run_pipeline` 这条 async generator 被 SSE 端点直接 `async for` 消费，
任务生命周期 == HTTP 连接生命周期：前端一断连，生成器被 aclose → 调研死亡、
已采集证据全丢、报告不落库。

本模块把「运行中的任务」提升为一等实体：
- `run_pipeline`（执行引擎，纯 async generator）只被这里驱动一次；
- 事件同时进「历史缓冲」(给重连者补帧) 与「各订阅者专属队列」(实时推送)；
- SSE 端点退化为纯订阅者：断连只撤订阅，不杀任务。

依赖方向单向：runner → orchestrator / db。orchestrator 完全不知道 runner 存在，
未做任何改动（保持纯执行引擎，避免反向依赖与循环依赖）。
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Dict, List, Optional

from app.core import db, orchestrator
from app.core.llm import LLMModelUnavailable, is_temporary_unavailable

BUFFER_MAX = 2000          # 历史缓冲容量，超出自动淘汰最旧事件
RELEASE_DELAY = 300.0      # 终态后保留窗口（秒），供末次重连补帧，超时释放防内存泄漏


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class _Run:
    def __init__(self, terminal: bool = False):
        self.subs: "list[asyncio.Queue[Dict[str, Any]]]" = []  # 各订阅者专属队列
        self.buffer: deque = deque(maxlen=BUFFER_MAX)   # 历史缓冲（重连补帧）
        self.status = "done" if terminal else "running"
        self.alive = not terminal                        # running → 有活的 asyncio.Task
        self.report_id: Optional[str] = None
        self.error: Optional[str] = None
        self.percent = 0
        self.stage = ""
        self.evidence_count = 0
        self.query = ""
        self.started_at = _now()
        self.updated_at = _now()
        self.subscribers = 0
        self.task: Optional["asyncio.Task[None]"] = None


_running: Dict[str, _Run] = {}


def _broadcast(r: _Run, ev: Dict[str, Any]) -> None:
    """事件入历史缓冲并推给各订阅者专属队列（与 _drive 主循环同一广播路径）。"""
    r.buffer.append(ev)
    for q in list(r.subs):
        q.put_nowait(ev)


def ensure_running(task_id: str) -> _Run:
    """幂等：返回该 task 的运行句柄。

    - 已在跑 → 直接返回（只订阅，不重跑）；
    - DB 已是终态（done/failed）且内存无活任务 → 返回只读终态句柄（前端据此跳转报告）；
    - DB 'running' 但内存无活句柄 = **孤儿运行**（进程重启/崩溃遗留）→
      就地收为 failed，**读端点绝不静默重跑**（重跑的唯一入口是新建任务 POST /api/tasks）；
    - 其余（'created' 等新任务）→ 创建 asyncio.Task 驱动执行引擎。
    """
    r = _running.get(task_id)
    if r is not None and r.alive:
        return r

    full = db.get_task_full(task_id)
    if full and full.get("status") == "running":
        msg = "任务已中断（服务重启或异常退出），请重新发起调研"
        db.set_task_failed(task_id, msg)
        full = {**full, "status": "failed", "error": msg}

    if full and full.get("status") in ("done", "failed"):
        # 内存已无活任务：以 DB 终态构造只读句柄，避免重跑已完成任务
        _running.pop(task_id, None)
        r = _Run(terminal=True)
        r.status = full["status"]
        r.report_id = full.get("report_id")
        r.error = full.get("error")
        r.percent = full.get("percent") or 0
        r.stage = full.get("stage") or ""
        r.evidence_count = full.get("evidence_count") or 0
        r.query = full.get("query", "")
        r.started_at = full.get("started_at") or r.started_at
        r.updated_at = full.get("updated_at") or r.updated_at
        _running[task_id] = r
        return r

    # 全新运行
    r = _Run()
    r.query = (full or {}).get("query", "")
    _running[task_id] = r
    db.set_task_running(task_id)
    r.task = asyncio.create_task(_drive(task_id, r))
    return r


async def _drive(task_id: str, r: _Run) -> None:
    """终态契约（唯一权威）：管线生成器必须以且仅以一条终态事件（done/error）结束，
    或抛异常；runner 是唯一写终态入库、且唯一保证线上有对应终态帧的地方。

    兼容说明：brief/refine 管线自身也调 db.set_task_failed（orchestrator 内部）、
    run_pipeline 在落库后自写 done——那是冗余兼容，与 runner 写同一终态幂等
    （UPDATE 同值），不允许管线写入与事件帧不同值的终态。
    """
    terminal_seen = False  # 管线是否已吐终态事件（done/error）
    try:
        # 按 tasks.kind 分发到不同的执行引擎（共享 progress/done/error 处理）
        full = db.get_task_full(task_id) or {}
        kind = (full.get("kind") or "research")
        if kind == "refine":
            gen = orchestrator.refine_report_pipeline(task_id)
        elif kind == "brief":
            gen = orchestrator.brief_report_pipeline(task_id)
        else:
            gen = orchestrator.run_pipeline(task_id)
        async for ev in gen:
            _broadcast(r, ev)               # 历史缓冲 + 各订阅者专属队列
            if ev["type"] == "progress":
                d = ev["data"]
                r.percent = d.get("percent", 0)
                r.stage = d.get("stage", "")
                r.evidence_count = d.get("evidence_count", 0)
                r.updated_at = _now()
                db.patch_task_progress(task_id, r.percent, r.stage, r.evidence_count)
            elif ev["type"] == "report_ready":
                r.report_id = ev["data"].get("reportId")
            elif ev["type"] == "error":
                # yield error 同样是终态：runner 统一收口入库（帧已广播，不补发）
                terminal_seen = True
                msg = (ev.get("data") or {}).get("message") or "任务失败"
                r.status = "failed"
                r.error = msg
                db.set_task_failed(task_id, msg)
            elif ev["type"] == "done":
                terminal_seen = True
                r.report_id = ev["data"].get("reportId") or r.report_id
                r.status = "done"
                db.mark_task_done(task_id, r.report_id or "")
        if not terminal_seen:
            # 协议违例守卫：生成器耗尽却未落终态 → 合成 error 帧 + failed，
            # 杜绝任何早退路径把任务悬在 running（本次无限重跑故障的结构性防线）
            msg = "任务异常结束（未落终态）"
            r.status = "failed"
            r.error = msg
            _broadcast(r, {"type": "error", "data": {"message": msg}})
            db.set_task_failed(task_id, msg)
    except asyncio.CancelledError:
        # 被 cancel() 取消：交给定终态逻辑，不写失败原因遮蔽用户意图
        r.status = "failed"
        r.error = "用户取消"
        _broadcast(r, {"type": "error", "data": {"message": "用户取消"}})
        db.set_task_failed(task_id, "用户取消")
        raise
    except LLMModelUnavailable as e:
        # 模型被厂商下架/重命名：给出含建议模型的友好提示，引导去「模型配置」页迁移
        r.status = "failed"
        msg = (
            f"当前模型不可用（{e.suggested_model or '厂商已下架'}）：{e}。"
            f"请到「模型配置」页一键迁移到 {e.suggested_model or '可用模型'}。"
        )
        r.error = msg
        _broadcast(r, {"type": "error", "data": {"message": msg}})
        db.set_task_failed(task_id, msg)
    except Exception as e:  # noqa: BLE001
        # 终态收尾，绝不静默吞掉；标记失败以便前端与 DB 状态一致
        if is_temporary_unavailable(e):
            # 评审 P1-b：Google 临时高负载（503），给友好文案而非原始英文栈
            msg = "当前模型服务负载较高（503），请稍后 30 秒左右重试再发起调研。"
        else:
            msg = str(e)
        r.status = "failed"
        r.error = msg
        _broadcast(r, {"type": "error", "data": {"message": msg}})
        db.set_task_failed(task_id, msg)
    finally:
        r.alive = False
        for q in list(r.subs):
            q.put_nowait({"type": "stream_end", "data": {}})
        # 延迟释放，保留窗口供末次重连补帧
        asyncio.create_task(_release_later(task_id, RELEASE_DELAY))


async def _release_later(task_id: str, delay: float) -> None:
    await asyncio.sleep(delay)
    r = _running.get(task_id)
    if r is not None and not r.alive and r.subscribers <= 0:
        _running.pop(task_id, None)


async def subscribe(task_id: str):
    """SSE 订阅生成器：先回放历史缓冲（前端 reset 后重建完整态，无重复），
    再接本订阅者专属实时队列。

    关键：snapshot 与 subs.append 之间无任何 await，_drive 这个独立 Task 无法在
    此窗口插入，故历史与实时零重叠、零丢失。
    """
    r = ensure_running(task_id)
    if not r.alive:
        # 只读终态句柄：复用前端既有 done/error 处理，自动跳转报告
        if r.status == "done":
            yield {"type": "done", "data": {"reportId": r.report_id}}
        else:
            yield {"type": "error", "data": {"message": r.error or "任务已失败"}}
        return

    # 回放帧打 data.replay 标记（不改事件类型/顺序）：前端派遣节流队列据此
    # 对历史帧直刷不排队，只对实时新增帧逐条出场（服务端是回放/实时的唯一知情人）。
    snapshot = [
        {**ev, "data": {**(ev.get("data") or {}), "replay": True}} for ev in r.buffer
    ]
    q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    r.subs.append(q)
    r.subscribers += 1
    try:
        for ev in snapshot:
            yield ev
        while True:
            ev = await q.get()
            if ev["type"] == "stream_end":
                break
            yield ev
    finally:
        r.subscribers -= 1
        try:
            r.subs.remove(q)
        except ValueError:
            pass


def get_status(task_id: str) -> Dict[str, Any]:
    r = _running.get(task_id)
    if r is not None and r.alive:
        return {
            "status": r.status, "percent": r.percent, "stage": r.stage,
            "evidence_count": r.evidence_count, "report_id": r.report_id,
            "started_at": r.started_at, "updated_at": r.updated_at,
        }
    full = db.get_task_full(task_id) or {}
    return {
        "status": full.get("status"), "percent": full.get("percent") or 0,
        "stage": full.get("stage") or "", "evidence_count": full.get("evidence_count") or 0,
        "report_id": full.get("report_id"), "started_at": full.get("started_at"),
        "updated_at": full.get("updated_at"),
    }


def list_running() -> List[Dict[str, Any]]:
    return [
        {
            "task_id": tid, "query": r.query, "status": r.status,
            "percent": r.percent, "stage": r.stage,
            "evidence_count": r.evidence_count, "started_at": r.started_at,
        }
        for tid, r in _running.items()
        if r.alive
    ]


def cancel(task_id: str) -> None:
    r = _running.get(task_id)
    if r is not None and r.alive and r.task is not None:
        r.task.cancel()
    if r is not None:
        r.status = "failed"
        r.error = "用户取消"
        r.alive = False
        for q in list(r.subs):
            q.put_nowait({"type": "stream_end", "data": {}})
    db.set_task_failed(task_id, "用户取消")


def reconcile_orphans() -> int:
    """进程重启后清理孤儿 running（交 DB 标记 failed）。"""
    return db.reconcile_orphan_runs()
