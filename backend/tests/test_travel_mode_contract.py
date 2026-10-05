"""出行方式取值的**跨端单源**守卫：后端认的三个值 ＝ 前端联合类型的三个成员。

为什么必须有这条：`travel_mode` 决定等时圈口径，也进缓存键 `_scene_key`。后端在
`CreateTaskBody` 之后用一行 `in ("walking", "riding", "driving")` 白名单回落 walking，
前端则用 `types.ts` 的 `TravelMode` 联合类型驱动段控。两处各自演化时：

- 前端加第四档（如 `transit`）而后端没加 ⇒ 请求被**静默回落成 walking**，界面显示"公交"、
  报告里是步行的圈，且因为 `travel_mode` 是缓存键维度，这份错口径还会被复用；
- 后端改名（如 `bike`）而前端没改 ⇒ 同一类静默。

静默回落就住在这条 `else "walking"` 里 —— 它不会报错，只会给出一份口径错位的报告。
所以这里钉的是"两边字面量集合相等"，而不是"前端发出去的值后端认得"（后者只覆盖当下）。
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
MAIN = BACKEND / "app" / "main.py"
FRONTEND_TYPES = BACKEND.parent / "frontend" / "src" / "types.ts"

# 后端唯一认账的地方：不在白名单里就回落 walking
_BACKEND_TUPLE = re.compile(r"body\.travel_mode\s+if\s+body\.travel_mode\s+in\s+\(([^)]*)\)")
# 前端联合的写法两种都要认：单行 `= 'a' | 'b'` 与多行 `=\n  | 'a'`。
# 只按行截断的话，改成多行会解析成"只有第一档"⇒ 报一条口径不明的红。
# 截断点取声明块结束（下一个注释块 / export / 空行）。
_FRONTEND_UNION = re.compile(
    r"export type TravelMode\s*=([\s\S]*?)(?=\n\s*/\*\*|\nexport\s|\n\n)"
)


def _backend_values() -> set[str]:
    m = _BACKEND_TUPLE.search(MAIN.read_text(encoding="utf-8"))
    assert m, "读不到 `body.travel_mode in (...)` 白名单 —— 后端回落写法变了，本判据要跟着改"
    return set(re.findall(r"['\"]([a-z_]+)['\"]", m.group(1)))


def _frontend_values() -> set[str]:
    text = FRONTEND_TYPES.read_text(encoding="utf-8")
    m = _FRONTEND_UNION.search(text)
    assert m, "读不到 `export type TravelMode` 联合声明 —— 前端类型形状变了，本判据要跟着改"
    values = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert len(values) >= 3, (
        f"TravelMode 只解析出 {sorted(values)}（<3 档）⇒ 解析被排版带偏了，宁可红不空转"
    )
    return values


def test_both_sides_declare_a_nonempty_value_set():
    """宁可红，不空转：任一侧解析为空时，相等判据会变成假绿。"""
    assert MAIN.exists() and FRONTEND_TYPES.exists()
    assert _backend_values(), "后端白名单解析为空"
    assert _frontend_values(), "前端 TravelMode 解析为空"


def test_travel_mode_values_match_across_the_wire():
    backend, frontend = _backend_values(), _frontend_values()
    assert backend == frontend, (
        f"出行方式取值两端不一致：后端 {sorted(backend)} ／ 前端 {sorted(frontend)}。"
        " 前端多发的那一档会被后端**静默回落成 walking**（界面显示 A、报告是步行的圈，"
        " 且该错口径会进缓存键被复用）⇒ 加档必须同时改 "
        "`app/main.py` 白名单、`frontend/src/types.ts` 的 TravelMode、段控的键表。"
    )
