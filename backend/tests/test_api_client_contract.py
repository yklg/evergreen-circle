"""D3 · 跨端契约：`api.ts` 发往 evidences / subscriptions 的每个键，后端都必须认。

为什么这条缝值得单独守（与 `test_task_body_contract.py` 同源，另一组端点）：

- FastAPI 对**未知 query 参数静默忽略** —— 收到 `?brand=` 不报错、不 4xx，只是**过滤条件
  整个消失**，用户看到的是「筛了，但没生效」；
- pydantic 对**未声明 body 键静默丢弃**，若字段还带默认值，畸形 body 甚至能换回 200。

两者都不炸，只让功能"看起来在跑"。这就是 `api.ts` 的 `brand` / `brands` 能潜伏到今天
的原因（架构评审 v4 事实 10）：既有测试只钉**路由存在**（`test_api_surface_union.py`）与
**后端侧参数生效**（`test_dashboard_stats.py`），没有一条钉「前端实际发出的键 ∈ 后端声明
的键」—— 单边正确、两边脱节，正是这类事故的形状。

2026-09-27 波次 A 第 3/5 步已收：`api.ts` 两处键名改对、`/api/evidences` 挂上
`_reject_unknown_query_params` 闸。**仍欠一条**：`SubscriptionBody.destinations` 的默认值
`[]` 未去（它会让"键名再次写错"表现为 200 + 零目的地，而不是 422），去默认值属契约变更、
与既有 `test_subscriptions.py` 的一条已钉绿断言对撞，登记待拍。

写法沿用 `test_task_body_contract.py:33-59`：从 `api.ts` 真实源码取键、
「解析不出键＝判据已与真实源脱节，宁可红，不空转」。

计划编号：D3-1 … D3-5（覆盖评估 `~/.qoder-cn/plans/quiet-ridge-teal.md`）。
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.main import SubscriptionBody, app

API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    c = db._connect()
    for t in ("evidences", "reports", "subscriptions", "traces", "report_feedback", "tasks"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    db.invalidate_aggregates()
    yield


# ── 取键：从前端真实源，而不是从记忆 ───────────────────────────────

def _fn_slice(name: str) -> str:
    """截出 `export async function <name>` 到下一个导出函数之间的源码。"""
    src = API_TS.read_text(encoding="utf-8")
    start = src.index(f"export async function {name}")
    rest = src[start + 1:]
    nxt = rest.find("export async function")
    return rest[:nxt] if nxt != -1 else rest


def _query_keys(fn_name: str) -> set:
    block = _fn_slice(fn_name)
    keys = set(re.findall(r"qs\.set\(\s*['\"]([a-z_][a-z0-9_]*)['\"]", block))
    # 解析不出键＝判据已与真实源脱节；宁可红，不空转（先例 test_task_body_contract.py:51）
    assert keys, f"{fn_name} 里没解析出任何 qs.set 键，判据已与 api.ts 脱节"
    return keys


def _body_keys(fn_name: str) -> set:
    block = _fn_slice(fn_name)
    m = re.search(r"JSON\.stringify\(\s*\{([^}]*)\}", block)
    assert m, f"{fn_name} 里没解析出 JSON.stringify({{...}}) 载荷"
    keys = {p.split(":", 1)[0].strip() for p in m.group(1).split(",") if p.strip()}
    assert len(keys) >= 2, f"仅解析出 {sorted(keys)}，判据已与 api.ts 脱节"
    return keys


def _declared_query_params(path: str, method: str = "get") -> set:
    spec = app.openapi()["paths"][path][method]["parameters"]
    names = {p["name"] for p in spec if p.get("in") == "query"}
    assert names, f"{path} 未导出任何 query 参数，OpenAPI 形状变了"
    return names


def _seed_report(rid: str, destination: str) -> None:
    db.save_report({
        "id": rid, "title": f"{rid}", "query": rid, "destinations": [destination],
        "experts": [], "cover_image": "", "created_at": db._now(),
        "evidence": [{"evidence_id": f"e-{rid}", "source_url": "https://example.com",
                      "source_type": "official", "domain": "example.com", "title": "T",
                      "excerpt": "E", "credibility": 90.0, "collected_by": "x",
                      "destination": destination, "captured_at": db._now()}],
        "claims": [], "metrics": {},
    }, task_id="")


# ── D3-1 键覆盖：query ─────────────────────────────────────────────

def test_evidences_query_keys_are_declared_by_backend():
    """前端 `fetchEvidences` 发出的每个 query 键，都必须是后端声明过的参数。

    历史：2026-09-27 以 `xfail(strict)` 登记为 D3-1（长期发 `?brand=`）。波次 A 第 3 步
    把 `api.ts` 改成 `destination` 后摘标，转为正向判据长期保留：以后任一侧改名，
    本条即刻红（先例 `test_task_body_contract.py:9-10`）。
    """
    sent = _query_keys("fetchEvidences")
    undeclared = sent - _declared_query_params("/api/evidences")
    assert not undeclared, f"前端发送但后端不认、会被静默忽略的键：{sorted(undeclared)}"


# ── D3-2 正向守缝：声明过的键真的过滤 ─────────────────────────────

def test_destination_filter_actually_filters_when_key_is_declared():
    """`destination` 是后端声明过的键 ⇒ 必须真的把另一目的地的证据筛掉。

    这条现在就该绿（后端侧没问题），它是下面那条「未知键被忽略」的对照：
    同一条 SQL、同一批数据，唯一差别是参数名。
    """
    _seed_report("r-A", "目的地A")
    _seed_report("r-B", "目的地B")
    items = client.get("/api/evidences", params={"destination": "目的地A"}).json()["items"]
    assert [i["destination"] for i in items] == ["目的地A"]


# ── D3-3 记录当前行为：未知键静默忽略 ─────────────────────────────

def test_unknown_query_param_is_rejected():
    """未知参数 ⇒ 422，不再"静默返回全量"。

    历史：本条曾是「记录当前行为」（`?brand=` 返回全量、过滤条件整个消失）。波次 A 第 5 步
    给 `/api/evidences` 挂了 `_reject_unknown_query_params` 后翻正为 422（先例
    `test_task_body_contract.py:110-117`：契约变更后把记录用例改成新判据，而不是留着两套）。
    """
    _seed_report("r-A", "目的地A")
    resp = client.get("/api/evidences", params={"brand": "目的地A"})
    assert resp.status_code == 422, resp.text
    assert "brand" in resp.text, f"422 里要点名是哪个键被拒：{resp.text}"


# ── D3-4 键覆盖：body ──────────────────────────────────────────────

def test_subscription_body_keys_are_declared_by_backend():
    """前端 POST 的每个 body 键都必须在 `SubscriptionBody` 上声明，否则被 pydantic 丢弃。

    历史：2026-09-27 以 `xfail(strict)` 登记为 D3-4（发 `{query, brands}`）。波次 A 第 3 步
    改签名后摘标。注意：`destinations`/`type` 目前**仍带服务端默认值**，所以"键名写错"
    会表现为 200 + 空目的地而非 422 —— 去默认值是已登记的独立契约变更（见下一条）。
    """
    sent = _body_keys("createSubscription")
    undeclared = sent - set(SubscriptionBody.model_fields)
    assert not undeclared, f"前端发送但模型未声明的键：{sorted(undeclared)}"


def test_subscription_with_undeclared_key_is_built_with_zero_destinations():
    """**记录当前行为（不是期望它）**：畸形载荷今天返回 200，订阅建成零目的地。

    危害比报错更大：用户以为在追踪「三亚 亲子游」，实际 destinations 为空，
    永不复跑。`SubscriptionBody.destinations` 去掉默认值后本用例应翻红并改断言 422。
    """
    resp = client.post("/api/subscriptions", json={"query": "三亚 亲子游攻略",
                                                   "brands": ["三亚"]})
    assert resp.status_code == 200, resp.text          # 不报错
    created = resp.json()
    assert created["destinations"] == [], "未声明的 brands 被丢弃 ⇒ 订阅没有追踪任何目的地"
