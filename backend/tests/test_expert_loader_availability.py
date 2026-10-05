"""加载器可用性 + 双名册 parity 守卫。

三条铁律：
1. `load_experts(domain)` 与 /health 不因**名册数据缺陷**抛异常（字段缺失回落默认值、
   living_circle 文件缺失借 travel）；但**域名本身写错**必须响 —— 见 unknown_domain 两条。
2. T-06 融合双名册：travel/living_circle 两份 48 人名册的 id 集合、字段键、层级计数
   必须一致（仅知识人设/group 内容允许不同），防旧报告署名解析与组队落空。
3. `domain` 必填、不得带默认值：两域同 id 异人设，留默认域等于让忘记传域的调用点
   静默换成另一个人名（生活圈署名曾整批取成旅游人设，实测 7/7 章）。
"""
import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data import load_experts
from app.main import app as _app
import app.data as data_mod

_ORIG_FILES = dict(data_mod._FILES)


@pytest.fixture(autouse=True)
def _swap_data_path(tmp_path: Path, request):
    """每用例使用独立临时 travel 名册；parity 用例读真实双名册，跳过替换。"""
    if request.node.name.startswith("test_dual_roster"):
        yield
        return
    fake = tmp_path / "experts.json"
    data_mod._FILES["travel"] = fake
    yield
    data_mod._FILES = dict(_ORIG_FILES)
    data_mod.load_experts.cache_clear()


client = TestClient(_app)


def _write_roster(entries: list[dict]):
    with open(data_mod._FILES["travel"], "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


def test_load_experts_tolerates_missing_caliber_refs():
    _write_roster([{"id": "L3-001", "name": "Test", "level": "L3"}])
    experts = load_experts("travel")
    assert experts[0].get("caliber_refs") == []


def test_load_experts_tolerates_missing_skills():
    _write_roster([{"id": "L3-001", "name": "Test", "level": "L3", "skills": "not-a-list"}])
    experts = load_experts("travel")
    assert experts[0]["skills"] == []


def test_load_experts_tolerates_missing_name():
    _write_roster([{"id": "L3-001", "level": "L3"}])
    experts = load_experts("travel")
    assert experts[0].get("name") is None


def test_expert_by_id_uses_get_not_subscript():
    _write_roster([{"level": "L3"}, {"id": "L3-001", "name": "OK", "level": "L3"}])
    result = data_mod.expert_by_id("L3-001", "travel")
    assert result is not None
    assert result["name"] == "OK"


def test_health_endpoint_survives_broken_roster():
    _write_roster([{"garbage": True}])
    r = client.get("/health")
    assert r.status_code == 200


# ── T-06：双名册 parity（真实 travel / living_circle 文件）──────────────
def test_dual_roster_id_sets_identical():
    travel = load_experts("travel")
    living = load_experts("living_circle")
    assert len(travel) == len(living) == 48
    assert {e["id"] for e in travel} == {e["id"] for e in living}


def test_dual_roster_level_counts_identical():
    levels = lambda roster: Counter(e.get("level") for e in roster)
    assert levels(load_experts("travel")) == levels(load_experts("living_circle"))
    assert levels(load_experts("travel")) == Counter({"L3": 3, "L2": 9, "L1": 36})


def test_dual_roster_field_keys_identical_but_group_differs():
    travel = load_experts("travel")
    living = load_experts("living_circle")
    # 字段键集合逐人对齐（同 id 条目结构一致）
    t_by_id = {e["id"]: set(e.keys()) for e in travel}
    for e in living:
        assert set(e.keys()) == t_by_id[e["id"]], f"字段漂移: {e['id']}"
    # group 必须按域不同（旅游 industry/function vs 生活圈 facility/method）
    tg = Counter(e.get("group") for e in travel)
    lg = Counter(e.get("group") for e in living)
    assert {"industry", "function"} <= set(tg)
    assert {"facility", "method"} <= set(lg)
    assert tg != lg


def test_unknown_domain_raises_instead_of_borrowing_travel():
    """未知域必须抛错。

    旧契约（本文件曾钉的那条）是"未知域回落 travel、照样 200"——那正是署名串域事故的
    守门人：两本名册共用同一套 48 个 id，域拼错时静默拿到另一本人设，调用点看不出任何
    异常，只在报告上换成另一个人名。⇒ 域缺失可以（端点缺省＝travel 是公开契约），
    域**错**必须响。
    """
    _write_roster([{"id": "L3-001", "name": "T", "level": "L3"}])
    with pytest.raises(ValueError, match="未知专家域"):
        load_experts("not_a_domain")


def test_domain_is_required_positionally():
    """`load_experts` / `expert_by_id` 的 domain 不得带回默认值。

    判据形状是签名级而非行为级：默认值一回来，新调用点就会重新变成"忘记传域也不报错"。
    """
    import inspect

    from app.data import expert_by_id, experts_by_level

    for fn in (load_experts, expert_by_id, experts_by_level):
        params = inspect.signature(fn).parameters
        assert params["domain"].default is inspect.Parameter.empty, (
            f"{fn.__name__} 的 domain 又带上了默认值 {params['domain'].default!r}"
        )


# ── T-06 HTTP 层：GET /api/experts?domain= 透传（loader 层 parity 上面对齐，这里钉端点）──
def test_dual_roster_api_experts_domain_query():
    """BE-3：domain 白名单值透传到 loader，返回对应域名册（id 集与 loader 同源）。"""
    travel = client.get("/api/experts").json()
    living = client.get("/api/experts?domain=living_circle").json()
    assert [e["id"] for e in travel] == [e["id"] for e in load_experts("travel")]
    assert [e["id"] for e in living] == [e["id"] for e in load_experts("living_circle")]
    # 双域人设必须不同（同 id 不同 group），证明透传而非恒返一份
    by_group_t = {e["id"]: e.get("group") for e in travel}
    assert any(by_group_t[e["id"]] != e.get("group") for e in living)


def test_api_experts_default_is_travel_but_unknown_domain_422():
    """BE-4：缺省仍＝travel（前端取旅游名册时刻意不带 ?domain=，`lib/api.ts:54`），
    但**非法域 422** —— 不再静默洗成另一本人设。"""
    default_body = client.get("/api/experts").json()
    assert [e["id"] for e in default_body] == [e["id"] for e in load_experts("travel")]

    weird = client.get("/api/experts?domain=not_a_domain")
    assert weird.status_code == 422
    assert "未知专家域" in weird.json()["detail"]


def test_dual_roster_api_expert_detail_resolves_same_id_to_different_personas():
    """同一个 id 在两域必须是**不同人名**（端点级串域钉）。

    为什么单独钉这条：`/api/experts/{eid}` 曾经不接域参数，生活圈详情页永远拿旅游人设。
    取 L3-002 是因为它在两本名册里分别是「林清越·首席分析官」与「许映川·首席规划分析师」，
    且**姓名不重叠** ⇒ 断言能真正区分两域，而不是碰巧同名。
    """
    t = client.get("/api/experts/L3-002").json()
    l = client.get("/api/experts/L3-002?domain=living_circle").json()
    assert t["name"] == "林清越" and l["name"] == "许映川"
    assert client.get("/api/experts/L3-002?domain=nope").status_code == 422
