"""Phase 2 · 加载器可用性守卫：数据问题绝不升级为可用性问题。

守住一条铁律：load_experts() 与 /health 端点不因名册数据缺陷而抛异常。
这是防止「校验器被顺手塞进 loader」退化的唯一结构防线。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data import load_experts
from app.main import app as _app
import app.data as data_mod

_ORIG_DATA = data_mod._DATA


@pytest.fixture(autouse=True)
def _swap_data_path(tmp_path: Path):
    """每用例使用独立临时 experts.json，不污染真实文件。"""
    fake = tmp_path / "experts.json"
    data_mod._DATA = fake
    yield
    data_mod._DATA = _ORIG_DATA
    data_mod.load_experts.cache_clear()


client = TestClient(_app)


def _write_roster(entries: list[dict]):
    with open(data_mod._DATA, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


def test_load_experts_tolerates_missing_caliber_refs():
    """caliber_refs 缺失时应回落 [] 而非抛异常。"""
    _write_roster([{"id": "L3-001", "name": "Test", "level": "L3"}])
    experts = load_experts()
    assert experts[0].get("caliber_refs") == []


def test_load_experts_tolerates_missing_skills():
    """skills 非列表时应回落 [] 并记录 warning。"""
    _write_roster([{"id": "L3-001", "name": "Test", "level": "L3", "skills": "not-a-list"}])
    experts = load_experts()
    assert experts[0]["skills"] == []


def test_load_experts_tolerates_missing_name():
    """name 缺失时加载器记录 warning 但不抛异常；调用方应使用 .get() 访问。"""
    _write_roster([{"id": "L3-001", "level": "L3"}])
    experts = load_experts()
    # 加载器不注入默认值，只记录 warning；调用方用 .get() 安全访问
    assert experts[0].get("name") is None


def test_expert_by_id_uses_get_not_subscript():
    """expert_by_id 必须用 .get() 查 id，硬下标会在畸形条目上 KeyError。"""
    _write_roster([{"level": "L3"}, {"id": "L3-001", "name": "OK", "level": "L3"}])
    result = data_mod.expert_by_id("L3-001")
    assert result is not None
    assert result["name"] == "OK"


def test_health_endpoint_survives_broken_roster():
    """即使名册全坏，/health 仍应返回 200（加载器宽松 + lru_cache 不固化异常）。"""
    _write_roster([{"garbage": True}])
    r = client.get("/health")
    assert r.status_code == 200
