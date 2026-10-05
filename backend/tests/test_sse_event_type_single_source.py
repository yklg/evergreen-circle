"""事件 type 的**生产者侧**单源守卫：后端实发的每个 type，前端必须订阅。

为什么必须有这条：事件 type 的真相原本散在三处 —— 后端 `_ev("<type>", …)` 的字面量、
后端测试里的 A4 白名单、前端 `types.ts` 的 `SSEEventType`（`api.ts` 的 `SSE_SUBSCRIPTIONS`
按它穷举）。三处各自演化时，**新增一个 type 的人只会撞到后端白名单，撞不到"前端到底收不收"**。

活证据：`living_circle.py` 从 2026-09 起就在发 `warn`（名称与中心点不同源的核对提示），
后端 `test_intake_and_shell.py` 还依赖它存在，但前端 union 里没有 ⇒ 传输层直接丢弃，
那条提示从未上过屏，且没有任何测试变红。

既有的 `livingCircleContract.test.ts:535-539` 只钉了另一半方向（演示 fixture 的事件流 ⊆
`SSEEventType`），查不到"后端实发"这一侧。本文件补的就是这一侧。
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND_TYPES = BACKEND.parent / "frontend" / "src" / "types.ts"
PIPELINES = (
    BACKEND / "app" / "core" / "pipeline" / "living_circle.py",
    BACKEND / "app" / "core" / "pipeline" / "research" / "engine.py",
)

_EMIT = re.compile(r'_ev\(\s*"([a-z_]+)"')
_UNION = re.compile(r"export type SSEEventType\s*=\n((?:\s*\| '[a-z_]+'\n)+)")


def _emitted_types() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in PIPELINES:
        out[p.name] = set(_EMIT.findall(p.read_text(encoding="utf-8")))
    return out


def _contract_types() -> set[str]:
    text = FRONTEND_TYPES.read_text(encoding="utf-8")
    m = _UNION.search(text)
    assert m, "读不到 `export type SSEEventType` 联合声明 —— 前端类型形状变了，本判据要跟着改"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_frontend_union_is_not_empty_and_pipelines_are_found():
    """宁可红，不空转：读不到文件或解析出空集合时，下面的判据全是假绿。"""
    assert FRONTEND_TYPES.exists()
    assert _contract_types(), "SSEEventType 解析为空"
    for name, types in _emitted_types().items():
        assert types, f"{name} 里没解析到任何 _ev(...) 发射点"


def test_every_emitted_event_type_is_registered_by_the_frontend():
    """后端实发的每个 type 都必须在 `SSEEventType` 里，否则前端订阅表按 union 穷举时漏掉它。"""
    contract = _contract_types()
    missing = {
        f"{name}: {sorted(t - contract)}"
        for name, t in _emitted_types().items()
        if t - contract
    }
    assert not missing, (
        f"后端在发、前端不订阅（事件会被传输层静默丢弃）：{sorted(missing)}"
        " ⇒ 在 frontend/src/types.ts 的 SSEEventType 补上，并确认 api.ts 的 "
        "SSE_SUBSCRIPTIONS 与消费侧分流都接住了"
    )
