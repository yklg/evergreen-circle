"""加载器可用性 + 双名册 parity 守卫。

两条铁律：
1. load_experts() 与 /health 不因名册数据缺陷抛异常（宽松 loader）；
2. T-06 融合双名册：travel/living_circle 两份 48 人名册的 id 集合、字段键、层级计数
   必须一致（仅知识人设/group 内容允许不同），防旧报告署名解析与组队落空。
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
    experts = load_experts()
    assert experts[0].get("caliber_refs") == []


def test_load_experts_tolerates_missing_skills():
    _write_roster([{"id": "L3-001", "name": "Test", "level": "L3", "skills": "not-a-list"}])
    experts = load_experts()
    assert experts[0]["skills"] == []


def test_load_experts_tolerates_missing_name():
    _write_roster([{"id": "L3-001", "level": "L3"}])
    experts = load_experts()
    assert experts[0].get("name") is None


def test_expert_by_id_uses_get_not_subscript():
    _write_roster([{"level": "L3"}, {"id": "L3-001", "name": "OK", "level": "L3"}])
    result = data_mod.expert_by_id("L3-001")
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


def test_unknown_domain_falls_back_to_travel():
    """未知 domain 不抛异常、不回落错名册，使用 travel 默认。"""
    _write_roster([{"id": "L3-001", "name": "T", "level": "L3"}])
    experts = load_experts("not_a_domain")
    assert experts and experts[0]["id"] == "L3-001"


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


def test_dual_roster_api_experts_default_and_unknown_domain():
    """BE-4：缺省与非法 domain 均回落 travel，200（fail-loud 到默认，不报错/不回错名册）。"""
    default_ids = [e["id"] for e in client.get("/api/experts").json()]
    weird = client.get("/api/experts?domain=not_a_domain")
    assert weird.status_code == 200
    assert [e["id"] for e in weird.json()] == default_ids
