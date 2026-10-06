"""片 0b · 请求体封闭性（计划 TC-34 / TC-35 / G-27、INV-契约封闭）

守的契约：**发给后端的未声明键必须被拒，而不是被静默丢弃**。

为什么这条值得单独守：`extra="ignore"`（pydantic 默认）下，前端写错一个键名不报错、
不 4xx、不留痕 —— 载荷被剥成"剩下的合法字段"，服务端照单办完。最坏的形状已经在
`/api/subscriptions` 上真实发生过：发 `{query, brands}` 返回 **200**，订阅被建成
**零目的地**，用户以为在追踪某地，实际什么都不追踪（见
`test_api_client_contract.py::test_subscription_with_undeclared_key_is_refused`）。
"功能整个消失但看起来成功"比 422 危险得多。

⇒ 现在 `app/main.py` 的 8 个请求体全部 `extra="forbid"`，本文件钉两件事：

  1. **判据取行为，且精确到失败种类**：只断"抛异常 / 状态码 4xx"是**无牙**的 —— 最小
     合法载荷自己构造失败也会 422（本仓实测把"8/8 在丢键"错报成"0/8"就是这么来的）。
     必须断 `detail` 里出现 `extra_forbidden`，并同时断**去掉那个键就能通过**（正对照）。
  2. **穷举件自身要闭集**：漏测一个模型 == 那个模型悄悄回到静默丢弃。新增请求体不登记
     即红。
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROBE = "zz_undeclared_probe_key"

# 每个请求体 → 一个**真实可达**的端点 + 该端点今天确实能通过的载荷。
# 载荷写死是刻意的：它同时是"正对照"（不带探针键必须 <400），一旦哪个入口的必填字段
# 变了，这里会先红，而不是让 forbid 的断言悄悄退化成"怎么发都 422"。
CASES: list = [
    ("SettingsPatch", "put", "/api/settings", {"patch": {}}),
    ("PrefsPatch", "put", "/api/prefs", {"patch": {}}),
    ("CreateTaskBody", "post", "/api/tasks", {"query": "凯里老街", "type": "living_circle"}),
    ("ClarifyBody", "post", "/api/tasks/t-contract/clarify", {"answers": {}}),
    ("FeedbackBody", "post", "/api/reports/r-contract/feedback", {}),
    ("RefineBody", "post", "/api/reports/r-contract/refine",
     {"section_id": "s", "annotations": []}),
    ("RefineEvidenceBody", "post", "/api/reports/r-contract/refine-evidence", {}),
    ("SubscriptionBody", "post", "/api/subscriptions", {"query": "凯里深度游"}),
]


def _request_bodies() -> set:
    """从路由表里反查"带请求体的模型"名集合 —— 判据不靠手写名单。

    `app/main.py` 有 `from __future__ import annotations`，所以 `Signature.parameter.annotation`
    是**字符串**而不是类对象；直接 `inspect.isclass` 会得到空集（本文件第一版就是这么错的，
    被下面那条覆盖性用例当场拦下）。⇒ 必须用 `get_type_hints` 把字符串解析回类。
    """
    models = set()
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        try:
            hints = get_type_hints(endpoint)
        except Exception:
            continue
        body = hints.get("body")
        if inspect.isclass(body) and hasattr(body, "model_fields"):
            models.add(body.__name__)
    return models


def _extra_types(resp) -> set:
    detail = resp.json().get("detail") if isinstance(resp.json(), dict) else None
    return {e.get("type") for e in detail} if isinstance(detail, list) else set()


def test_the_case_table_covers_every_request_body_model():
    """穷举件自检：路由里存在的每个请求体都必须在表上。

    漏一格就等于那个模型悄悄退回"静默丢键"，而 forbid 的账看起来仍然是清的。
    """
    actual = _request_bodies()
    assert len(actual) >= 8, f"只从路由反查到 {sorted(actual)}，判据已与 main.py 脱节"
    missing = actual - {name for name, *_ in CASES}
    assert not missing, f"这些请求体没有 forbid 用例：{sorted(missing)}"
    extra = {name for name, *_ in CASES} - actual
    assert not extra, f"表里这些模型已不在路由上（陈旧条目）：{sorted(extra)}"


def test_no_request_body_silently_drops_undeclared_keys():
    """8/8：未声明键必须被拒，且拒绝理由必须是 `extra_forbidden`。"""
    survivors = []
    for name, verb, path, valid in CASES:
        send = getattr(client, verb)
        accepted = send(path, json={**valid, PROBE: 1})
        if accepted.status_code < 400:
            survivors.append((name, path, accepted.status_code))
    assert not survivors, (
        f"这些请求体仍把未声明键丢掉当没事发生：{survivors}"
    )


def test_each_endpoint_rejects_for_the_right_reason_with_a_positive_control():
    """逐端点：422 + `extra_forbidden`，并且**去掉探针键就不再是 422**（正对照）。

    正对照只要求"不是 422"：`refine-evidence` 拿假报告 id 会 404 —— 那说明**请求体已被
    接受**，正是我们要的语义。判据若写成 `<400`，就会把"业务对象不存在"误当成 forbid 失效。
    这条对照防的是：某端点本来就 422（载荷过期）时，上面的 forbid 断言其实在空转。
    """
    for name, verb, path, valid in CASES:
        send = getattr(client, verb)
        bad = send(path, json={**valid, PROBE: 1})
        assert bad.status_code == 422, f"{name}@{path} 未返回 422：{bad.status_code}"
        types = _extra_types(bad)
        assert "extra_forbidden" in types, (
            f"{name}@{path} 的 422 不是因为未声明键：{sorted(types)}"
        )
        good = send(path, json=valid)
        assert good.status_code != 422, (
            f"{name}@{path} 的正对照也 422 ⇒ 载荷已失效，forbid 断言正在空转：{sorted(_extra_types(good))}"
        )


def test_probe_key_is_reported_by_name_so_clients_can_fix_it():
    """422 的 `loc` 必须点名那个键，否则前端只看到"校验失败"而无从修。"""
    resp = client.post("/api/tasks", json={"query": "凯里老街", "type": "living_circle",
                                           PROBE: 1})
    locs = [tuple(e.get("loc") or ()) for e in resp.json()["detail"]]
    assert any(PROBE in loc for loc in locs), f"错误里没有键名：{locs}"


def test_declared_fields_have_no_undocumented_senders():
    """反向穷举（TC-36）：模型上声明的字段，要么有发送方，要么显式登记来源。

    "字段存在"不等于"功能生效"：`sample_profile` 当年就是前端在发、后端没声明（R0）。
    反过来更隐蔽 —— 后端声明了却没人发，那条默认值路径永远不会被真实流量触达。
    这里只钉 `CreateTaskBody`（体检发起的入口），把无发送方的键列成显式清单。

    `CreateTaskBody` 是**两个前端发起口共用**的模型（`api.ts` 的 `createTask` 走 research、
    `createLivingCircleTask` 走 living_circle），所以发送方清单必须取两边的并集 ——
    只取一边的话，另一边的键会被误判成"没人发"（`source_urls` 第一次落地就是这种形状）。
    并集里的每个键都另外用 `key in api.ts` 验一遍存在性：硬清单会漂移，存在性不会。
    """
    from app.main import CreateTaskBody

    api_ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts")
    assert api_ts.exists(), f"前端源不可达（{api_ts}）—— 须修路径而非跳过本守卫"
    src = api_ts.read_text(encoding="utf-8")

    lc_launched = {"query", "sample_profile", "type", "center", "coord_sys", "city", "address",
                   "data_mode",
                   # `travel_mode` 与 `force` 都是**条件发送**（`...(x ? { k: x } : {})`）：
                   # "没表态"与"表态了取默认值"在这两条上都是要分辨的事，所以不发时是真的不发。
                   # `travel_mode` 原先被列在下面"无发送方"那一侧，是清单没跟上线上形状 ——
                   # 放在那里不影响安全性（两个键都非必填，下面的断言仍在守），但它是句假话。
                   "travel_mode", "force"}
    research_launched = {"query", "mode", "model", "type", "source_urls"}
    launched = lc_launched | research_launched
    for key in launched:
        assert key in src, f"发送方清单里的 {key} 在 api.ts 里已找不到 ⇒ 清单漂移，判据在空转"

    unsent = set(CreateTaskBody.model_fields) - launched
    assert unsent == {"purpose"}, (
        f"`CreateTaskBody` 的无发送方字段清单变了，须回计划 §0 登记：{sorted(unsent)}"
    )
    for field in sorted(unsent):
        assert CreateTaskBody.model_fields[field].is_required() is False, (
            f"{field} 没人发却是必填 ⇒ 真实客户端会直接 422"
        )
