"""跨端契约：前端体检发起载荷的每个键，都必须在 `CreateTaskBody` 上声明。

为什么单独守这条：`CreateTaskBody` 是 pydantic 模型，**未声明的键会被静默丢弃**——
不报错、不降级、不留痕。前端 `createLivingCircleTask`（`frontend/src/lib/api.ts`）
发的采样档位键名是 `sample_profile`（R5 改名后的口径），而后端只声明了 `mode`
⇒ 采样档位**在入口就没了**，随后被 route 的白名单表达式回落成 `standard`。

这正是第一片要加 `scenario` 字段的那条缝：先修缝再加字段，否则新字段重演同一个静默
丢弃（场景档一旦丢，游客档会拿到居住档口径，UI 完全看不出来）。

计划编号：R0 / 附录 G-14 / TC-20。
"""
import re
from pathlib import Path

import pytest

from app.main import CreateTaskBody

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"


def _frontend_launch_keys() -> set:
    """取 `createLivingCircleTask` 里 `body: JSON.stringify({...})` 的顶层键名。

    两种写法都要收：`key: value` 与 ES6 简写 `key,`（如 `center,`）。
    """
    src = API_TS.read_text(encoding="utf-8")
    fn = src[src.index("export async function createLivingCircleTask"):]
    start = fn.index("body: JSON.stringify({")
    block = fn[start:fn.index("})", start)]
    keys = set(re.findall(r"^\s{6}([a-z_][a-z0-9_]*)\s*:", block, re.MULTILINE))
    keys |= set(re.findall(r"^\s{6}([a-z_][a-z0-9_]*)\s*,\s*$", block, re.MULTILINE))
    return keys


@pytest.fixture(scope="module")
def launch_keys() -> set:
    assert API_TS.exists(), f"前端源不可达（{API_TS}）—— 须修路径而非跳过本守卫"
    keys = _frontend_launch_keys()
    # 解析不出键＝判据已与真实源脱节；宁可红，不空转
    assert len(keys) >= 6, f"仅解析出 {sorted(keys)}，判据已与 api.ts 脱节"
    return keys


@pytest.mark.xfail(
    strict=True,
    reason="R0：前端发 sample_profile，CreateTaskBody 只声明 mode ⇒ pydantic 静默丢弃，"
           "采样档位恒回落 standard。修缝（补声明字段）后摘掉本标记。",
)
def test_declared_body_fields_cover_the_frontend_payload(launch_keys):
    """每个前端键都必须是 `CreateTaskBody` 的声明字段，否则会被静默丢弃。"""
    dropped = launch_keys - set(CreateTaskBody.model_fields)
    assert not dropped, f"前端发送但后端未声明、会被丢弃的键：{sorted(dropped)}"


def test_undeclared_sampling_profile_is_currently_dropped(launch_keys):
    """显式记录**当前**行为，而不是期望它。

    R0 修复后本用例必须**改写**为「sample_profile 被保留」，不许直接删掉——
    否则这条缝失去全部可追溯性。
    """
    assert "sample_profile" in launch_keys, "前端已改键名，本用例判据须同步重指"
    assert "sample_profile" not in CreateTaskBody.model_fields
    body = CreateTaskBody.model_validate(
        {"query": "x", "type": "living_circle", "sample_profile": "precise"}
    )
    assert not hasattr(body, "sample_profile")
    # 模型默认值 deep，与前端要求的 precise 无关；route 的白名单随后回落 standard
    assert body.mode == "deep"


def test_the_other_launch_keys_are_all_declared(launch_keys):
    """防「整条契约只靠一个已知失败撑住」：除采样档位外，其余键必须都已声明。"""
    others = launch_keys - {"sample_profile"}
    missing = others - set(CreateTaskBody.model_fields)
    assert not missing, f"新增的未声明键：{sorted(missing)}"
