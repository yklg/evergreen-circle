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


# --------------------------------------------------------------------------- #
# 封闭任务注册表：kind → 流水线工厂(task_id)。
# 显式登记每一类可执行任务；未登记 kind 走 fail-loud，绝不落到「竞品/调研」兜底。
# 值一律为「调用期才导入」的工厂，避免模块加载期循环依赖（H2 对比导入自洽）。
# 契约约定：kind=路由键（task 类型），purpose=内容腔调（report_voice 档位），勿跨用途。
# --------------------------------------------------------------------------- #
def _load_research(task_id: str):
    from app.core.pipeline.research import research_pipeline  # noqa: PLC0415
    return research_pipeline(task_id)


def _load_living(task_id: str):
    from app.core.pipeline.living_circle import living_circle_pipeline  # noqa: PLC0415
    return living_circle_pipeline(task_id)


def _load_refine(task_id: str):
    return orchestrator.refine_report_pipeline(task_id)


def _load_brief(task_id: str):
    return orchestrator.brief_report_pipeline(task_id)


KIND_PIPELINES: Dict[str, Any] = {
    # 目的地调研一族（攻略/评估/综合）：概览一致，走中性 research 流水线
    "research": _load_research,
    "travel_guide": _load_research,
    "travel_assess": _load_research,
    "refine": _load_refine,
    "brief": _load_brief,
    # 生活圈体检（独立子域）
    "living_circle": _load_living,
}


def _fail_loud(task_id: str, r: _Run, msg: str) -> None:
    """未登记 kind 的终态收尾：广播 error + 落库 failed（绝不以 done 冒充成功）。"""
    ev = {"type": "error", "data": {"message": msg}}
    r.buffer.append(ev)
    for q in list(r.subs):
        q.put_nowait(ev)
    r.status = "failed"
    r.error = msg
    r.updated_at = _now()
    db.set_task_failed(task_id, msg)


def ensure_running(task_id: str) -> _Run:
    """幂等：返回该 task 的运行句柄。

    - 已在跑 → 直接返回（只订阅，不重跑）；
    - DB 已是终态（done/failed）且内存无活任务 → 返回只读终态句柄（前端据此跳转报告）；
    - 否则创建 asyncio.Task 驱动 run_pipeline。
    """
    r = _running.get(task_id)
    if r is not None and r.alive:
        return r

    full = db.get_task_full(task_id)
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
    try:
        # 按 tasks.kind 从封闭注册表分发（无 else 兜底：未登记即 fail-loud）
        full = db.get_task_full(task_id) or {}
        kind = (full.get("kind") or "research")
        pipe = KIND_PIPELINES.get(kind)
        if pipe is None:
            msg = f"未知任务类型 {kind!r}，无法执行。"
            _fail_loud(task_id, r, msg)
            return
        gen = pipe(task_id)
        async for ev in gen:
            r.buffer.append(ev)          # 历史缓冲（重连补帧）
            for q in list(r.subs):       # 广播给各订阅者专属队列
                q.put_nowait(ev)
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
                # 全仓约定：error 事件即**终态**（各流水线 yield 后立即 return，并已自行
                # db.set_task_failed）。此处只把内存态对齐库态 —— 否则 /api/tasks 列表
                # 会一直显示 running（僵尸态），而库里其实早已 failed。
                r.status = "failed"
                r.error = (ev.get("data") or {}).get("message") or "任务失败"
            elif ev["type"] == "done":
                d = ev["data"] or {}
                r.report_id = d.get("reportId") or r.report_id
                if d.get("status") == "failed":
                    # ⚠️ `done` 只表示「事件流结束」，不表示成功。执行引擎判定失败时
                    # （如 live 却几何为空）会带 status='failed' 收尾；若这里无条件
                    # mark_task_done，就会把引擎写的 failed **覆盖成 done** ——
                    # 守卫被自己的收尾动作抹掉，缺陷重新静默。
                    r.status = "failed"
                    r.error = d.get("error") or "任务失败"
                    db.set_task_failed(task_id, r.error)
                else:
                    r.status = "done"
                    db.mark_task_done(task_id, r.report_id or "")
    except asyncio.CancelledError:
        # 被 cancel() 取消：交给定终态逻辑，不写失败原因遮蔽用户意图
        r.status = "failed"
        r.error = "用户取消"
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

    snapshot = list(r.buffer)            # 本订阅者加入前的历史
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
    full = db.get_task_full(task_id) or {}
    if r is not None and r.alive:
        base = {
            "status": r.status, "percent": r.percent, "stage": r.stage,
            "evidence_count": r.evidence_count, "report_id": r.report_id,
            "started_at": r.started_at, "updated_at": r.updated_at,
        }
    else:
        base = {
            "status": full.get("status"), "percent": full.get("percent") or 0,
            "stage": full.get("stage") or "", "evidence_count": full.get("evidence_count") or 0,
            "report_id": full.get("report_id"), "started_at": full.get("started_at"),
            "updated_at": full.get("updated_at"),
        }
    # kind/purpose：供前端「工作台刷新/直达」走 taskViewProvider 判型回退（localStorage 兜底）
    base["kind"] = full.get("kind") or "research"
    base["purpose"] = full.get("purpose") or ""
    return base


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
