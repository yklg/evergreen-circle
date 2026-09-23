"""K5 · 「空 AK」三道既有防线的守卫测试（R8 · 2026-09-22）。

## 为什么存在

`_shared_gate_params()` 与两个工厂的缓存键**只含 AK**（批次 1 的 B-2）⇒ 若某个入口把空 AK
传下去，所有「忘记传 AK」的客户端会**共享同一把闸与同一份日预算**（键 `""`）。这既可能是
「保守默认」（好事），也可能是「不同账号被合并限流」（坏事）。

计划 §11.4 的裁决（**回源核实后对上一轮建议的自我纠错**）：

- 空 AK 在**生产不可达** —— 三道入口全部显式防护；
- **不做**「空 AK 自动回退到已配置 AK」：`app/main.py:350-351` 的设计意图是
  「缺 AK 就**响亮失败**，绝不照抄一个看起来像坐标的值」；静默回退会把「配置缺失」
  从响亮失败改成静默可用 ⇒ **方向相反**；
- K5 的正确修法 = **给这三道既有防线补守卫测试**，不碰生产行为（§12.7：「K5 **仅**补守卫测试」）。

## 三道防线的归属 —— 本文件是 K5 契约的唯一审计入口

| # | 入口 | 空 AK 行为 | 既有守卫 | 本文件补的 |
|---|---|---|---|---|
| ① | `app/main.py:_to_bd09`（WGS-84 → BD-09） | `HTTPException(422)` | `test_geo_contract.py:175-183` ✅ **已有** | **合法必绿**：防线只在 wgs84 路径生效 |
| ② | `scripts/make_fixture_points.py:main` | `SystemExit` | **无**（此前只在 γ 用例的 docstring 里被提到） | 两侧全补（新增） |
| ③ | `app/living_circle/data_source.py:get_data_source` | WARNING + 离线兜底 | `test_data_source.py:128-140` ✅ **已有**（只断言类型 / `read_only`） | **日志留痕**（`:337` 那行） |

⚠️ **本文件刻意不重复既有断言**：① / ③ 的「违规必红」半边已在上表既有用例里；这里只补它们
**没有**的那半边（① 的合法必绿、③ 的 WARNING）。② 此前零覆盖，故违规/合法两侧都补。

> 计划勘误（E15）：§11.4 / §11.7 称「三道既有防线存在但**无测试锚定**」—— 实测 **① 已有完整
> 守卫（422 + detail 断言）、③ 已有类型守卫**，仅 **② 零覆盖**。故 R8 的真实增量 = ② 全新增
> + ①/③ 补齐缺失半边，而非「三道从零补」。

## 负对照（R8 的验证判据：「去掉任一处防护 ⇒ 对应用例必红」）

| 注入 | 期望 |
|---|---|
| `main.py:_to_bd09` 的 `if not ak:` → `if False:` | `test_defense_1_*` 红 |
| `make_fixture_points.main` 的 `if not ak:` → `if False:` | `test_defense_2_*` 红（**不触网**：`load_poi` 已被替身接住） |
| `data_source.get_data_source` 删掉 `:337` 的 `warning(...)` | `test_defense_3_*` 红 |
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

KAILI = [107.9758, 26.5734]  # BD-09（合法中心）
WGS84 = [116.3975, 39.9087]  # 天安门（WGS-84，走转换路径）


def _patch_ak(monkeypatch, ak: str) -> None:
    """把 `settings.baidu_server_ak` 固定为 `ak`。

    形态与 `test_geo_contract.py:_patch_ak` 一致（含配额档位镜像字段）：`_to_bd09` 与
    `_default_guard` 都在**调用点**才 import `get_settings`，故替换模块属性即可生效。
    """
    import app.core.config as cfg

    class _S:
        baidu_server_ak = ak
        baidu_max_qps = 3.0
        baidu_max_concurrency = 2

    monkeypatch.setattr(cfg, "get_settings", lambda: _S())


# ── 防线 ①：`main.py:_to_bd09` 的 422 ────────────────────────────────
def test_defense_1_does_not_overfire_on_the_bd09_path(monkeypatch):
    """空 AK **不得**连带拒绝 BD-09 直通的入参 —— 防线只属于 wgs84 那条路。

    与 `test_geo_contract.py:175` 的 422 用例成对：那条锚「违规必红」（wgs84 + 空 AK ⇒ 422），
    本条锚「合法必绿」（bd09 + 空 AK ⇒ 200）。若有人把 `if not ak:` 提到 `coord_sys` 判断
    **之前**（把 422 变成无条件），本条立刻红 —— 那是另一种故障：**没配 AK 就整个体检不可用**，
    而本域设计里「BD-09 入参 + 无 AK」是完全合法的组合（离线数据源正是这条路的兜底）。
    """
    _patch_ak(monkeypatch, "")
    resp = client.post(
        "/api/tasks",
        json={"query": "凯里老街", "type": "living_circle", "center": KAILI, "city": "贵州·凯里"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["taskId"].startswith("lc-")


# ── 防线 ②：`scripts/make_fixture_points.py:main` 的 SystemExit ──────
def test_defense_2_script_refuses_without_ak(monkeypatch):
    """夹具脚本缺 AK 必须 `SystemExit`，**且这一判断必须先于任何采集调用**。

    两件事一起锚：

    1. 退出码里的字面消息 —— 同函数内还有另外两处 `SystemExit`（`:72` 守恒违规 / `:86`
       缺权威快照），只断言「抛了 SystemExit」无法区分是哪一处，故锚消息本身；
    2. **先于采集** —— 若防线被去掉，脚本会带着空 AK 真去抓百度（慢、脏、依赖外网）。
       这里把 `load_poi` 换成立刻失败的替身：防线一旦失效，用例**快速变红**而不是去触网。
       第 2 点是本条真正的**有序性不变量**。
    """
    from scripts import make_fixture_points as mfp

    collected: list = []

    async def _never_collect(*args, **kwargs):
        collected.append((args, kwargs))
        raise AssertionError("AK 防线未生效：已进入 POI 采集路径（本用例禁止触网）")

    class _S:
        baidu_server_ak = ""

    monkeypatch.setattr(mfp, "get_settings", lambda: _S())
    monkeypatch.setattr(mfp, "load_poi", _never_collect)

    with pytest.raises(SystemExit) as ei:
        asyncio.run(mfp.main())

    assert "BAIDU_SERVER_AK 未配置" in str(ei.value), str(ei.value)
    assert collected == [], "防线必须先于任何采集调用（否则脚本会带着空 AK 真去抓）"


# ── 防线 ③：`data_source.py:get_data_source` 的 WARNING + 离线兜底 ────
_DATA_SOURCE_LOGGER = "app.living_circle.data_source"


def _warnings_from(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.name == _DATA_SOURCE_LOGGER]


def test_defense_3_factory_leaves_a_trace(caplog):
    """空 AK 走离线兜底时**必须在日志里留痕** —— `:337` 那行是这件事唯一的运行时信号。

    既有 `test_data_source.py:130` 只断言**类型**（`OfflineDataSource` + `read_only=True`）：
    把 `:337` 的 `warning(...)` 整行删掉，那条**照绿** ⇒「空 AK ⇒ 静默降级为离线」变成
    **只能靠读代码才知道**的事实。本条把它锚住。
    """
    from app.living_circle.data_source import get_data_source

    with caplog.at_level(logging.WARNING, logger=_DATA_SOURCE_LOGGER):
        get_data_source("live", ak="")

    hits = [m for m in _warnings_from(caplog) if "baidu AK 缺失" in m]
    assert hits, f"空 AK 必须留痕，实际日志：{_warnings_from(caplog)}"
    # 口径必须写进日志：不写 data_origin 的话，读者无法从这条告警推断出「报告会被标成离线」
    assert "data_origin=offline" in hits[0], hits[0]


def test_defense_3_stays_silent_when_the_ak_is_present(caplog):
    """合法必绿半边：**有 AK 时不得**打这条 WARNING。

    与上一条成对。若有人把 `:337` 的 warning 挪到 `if ak:` **之前**（无条件打），上一条照绿、
    本条红。后果不是「多一行日志」：一条「有 AK 也喊缺 AK」的告警会**训练读者忽略它**，
    于是真正缺 AK 时也没人看 —— 这正是 K3 的 8h 错位在生产上**无法被发现**的同一种失败。
    """
    from app.living_circle.data_source import get_data_source

    with caplog.at_level(logging.WARNING, logger=_DATA_SOURCE_LOGGER):
        get_data_source("live", ak="x")

    noise = [m for m in _warnings_from(caplog) if "baidu AK 缺失" in m]
    assert not noise, f"有 AK 时不该出现「缺 AK」告警：{noise}"
