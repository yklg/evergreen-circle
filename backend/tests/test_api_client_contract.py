"""D3 · 跨端契约：`api.ts` 发往 evidences / subscriptions 的每个键，后端都必须认。

为什么这条缝值得单独守（与 `test_task_body_contract.py` 同源，另一组端点）：

- FastAPI 对**未知 query 参数静默忽略** —— `/api/evidences` 只声明 `destination`
  （`app/main.py:653-664`），收到 `?brand=` 不报错、不 4xx，只是**过滤条件整个消失**，
  用户看到的是「筛了，但没生效」；
- pydantic 对**未声明 body 键静默丢弃**，而 `SubscriptionBody.destinations` 带默认值
  （`main.py:670-673`）⇒ POST `{query, brands}` 返回 **200**，订阅被建成**零目的地**。

两者都不炸，只让功能"看起来在跑"。这就是 `api.ts:316-333` 的 `brand` 与 `:359-369` 的
`brands` 能潜伏到今天的原因（架构评审 v4 事实 10）：既有测试只钉**路由存在**
（`test_api_surface_union.py`）与**后端侧参数生效**（`test_dashboard_stats.py:215`），
没有一条钉「前端实际发出的键 ∈ 后端声明的键」。

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

@pytest.mark.xfail(strict=True, reason=(
    "D3-1：api.ts:316-333 的 fetchEvidences 仍发 ?brand=（改造版之前的竞品口径残留），"
    "后端只认 destination（main.py:653-664）⇒ 过滤静默失效。波次 A 第 3 步改为 "
    "destination 后摘标。"))
def test_evidences_query_keys_are_declared_by_backend():
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

def test_unknown_query_param_is_currently_ignored():
    """**记录当前行为（不是期望它）**：`?brand=` 返回的是**全量**，不是「A 的证据」。

    后端补「拒绝未知 query 参数」时，本用例须翻红并改为断言 422 —— 而不是默默放宽
    （先例 `test_task_body_contract.py:110-117`）。
    """
    _seed_report("r-A", "目的地A")
    _seed_report("r-B", "目的地B")
    items = client.get("/api/evidences", params={"brand": "目的地A"}).json()["items"]
    assert len(items) == 2, "未知参数被忽略 ⇒ 过滤条件整个消失，返回全量"


# ── D3-4 键覆盖：body ──────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "D3-4：api.ts:359-369 的 createSubscription 仍 POST {query, brands}，而后端模型是 "
    "{query, destinations, type}（main.py:670-673）⇒ brands 被 pydantic 丢弃。"
    "波次 A 第 3 步改签名后摘标。"))
def test_subscription_body_keys_are_declared_by_backend():
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
