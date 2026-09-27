"""跨端契约：前端体检发起载荷的每个键，都必须在 `CreateTaskBody` 上声明。

为什么单独守这条：`CreateTaskBody` 是 pydantic 模型，**未声明的键会被静默丢弃**——
不报错、不降级、不留痕。前端 `createLivingCircleTask`（`frontend/src/lib/api.ts:176`）
发的采样档位键名是 `sample_profile`（R5 改名后的口径），而后端曾只声明 `mode`
⇒ 采样档位**在入口就没了**，随后被 route 的白名单表达式回落成 `standard`。

**R0 已修**（片 0）：`CreateTaskBody.sample_profile` 已声明，解析收口在
`main._lc_sample_profile`。本文件因此从「登记缺口」改写为「正向守缝」，并按这条
缝原本的要求保留历史：*不许直接删掉记录当前行为的那条用例* —— 它现在是正向判据。

第一片要加的 `scenario` / `origin` 走的正是同一条缝（片 2），所以这里守的判据是
**通用的键覆盖**，而不是「sample_profile 这一个键」：前端再发任何后端未声明的键，
本文件立刻红，新字段不会重演一次静默丢弃（场景档一旦丢，游客档会拿到居住档口径，
UI 完全看不出来）。

计划编号：R0 / 附录 G-14 / TC-20。
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import CreateTaskBody, app

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"

client = TestClient(app)


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


def test_declared_body_fields_cover_the_frontend_payload(launch_keys):
    """每个前端键都必须是 `CreateTaskBody` 的声明字段，否则会被 pydantic 静默丢弃。"""
    dropped = launch_keys - set(CreateTaskBody.model_fields)
    assert not dropped, f"前端发送但后端未声明、会被丢弃的键：{sorted(dropped)}"


def test_the_other_launch_keys_are_all_declared(launch_keys):
    """防「整条契约只靠一个已知键撑住」：逐个键都必须在模型上（含 R0 之后新增的键）。"""
    missing = launch_keys - set(CreateTaskBody.model_fields)
    assert not missing, f"未声明键：{sorted(missing)}"


# ── 正向守缝：档位真的落到任务参数上 ─────────────────────────────


def _profile_of(**body) -> str:
    payload = {"query": "凯里老街", "type": "living_circle"}
    payload.update(body)
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 200, resp.text
    return db.get_task_full(resp.json()["taskId"])["clarifications"]["sample_profile"]


@pytest.mark.parametrize("profile", ["quick", "standard", "precise"])
def test_sample_profile_survives_the_entry_and_reaches_the_task(profile):
    """R0 的正判据：前端发什么档位，任务参数里就是什么档位（不再恒 standard）。"""
    assert _profile_of(sample_profile=profile) == profile


def test_precise_is_not_silently_demoted_to_standard():
    """反向对照：`precise` 若又被回落成 `standard`，本用例即刻红。

    只测三档全通是不够的 —— 静默回落的特征恰恰是「合法值也被换成默认值」。
    """
    assert _profile_of(sample_profile="precise") != "standard"


def test_explicit_sample_profile_wins_over_legacy_mode():
    """两个入口同时在场时的次序：新字段优先，旧 `mode` 只做兜底。

    不钉这条次序，日后有人「顺手清理一个字段」就会静默改变档位来源。
    """
    assert _profile_of(sample_profile="precise", mode="quick") == "precise"


def test_legacy_mode_entry_still_honoured():
    """既有契约（`test_living_circle_api` t6 组）：只发 `mode` 的旧入口不受影响。

    这里**只钉一条**正向通路，非法值回落 standard 的语义由 t6 组那两条「记录当前行为
    + TODO(B1)」的用例守 —— 一处判据一份实现，别在两个文件里各写一遍回落规则。
    """
    assert _profile_of(mode="quick") == "quick"


def test_illegal_profile_falls_back_to_standard_for_now():
    """**记录当前行为（不是期望它）**：非法档位仍静默按 standard 跑完。

    改成显式 422 属已登记的独立契约变更 B1（见 `test_living_circle_api` 的
    `test_t6_illegal_mode_silently_falls_back_currently` 的 TODO）。B1 落地时本用例
    须翻红并改为断言 422 —— 而不是留在这里默默放宽。
    """
    assert _profile_of(sample_profile="presice") == "standard"
