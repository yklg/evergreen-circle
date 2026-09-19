"""M1 · 缓存仓库：data_mode 前缀防串 / TTL / 三种缓存读写。"""
import time

from app.living_circle.repository import MemoryCache, Repository


def test_memory_cache_ttl_expiry():
    cache = MemoryCache()
    cache.set("k", {"v": 1}, ttl_s=0.05)
    assert cache.get("k") == {"v": 1}
    time.sleep(0.08)
    assert cache.get("k") is None


def test_repository_data_mode_isolation():
    """同一场景不同 data_mode 不得串数据（A3 防串契约）。"""
    repo = Repository()
    payload = "凯里老街|107.9758,26.5734|2500|standard"
    repo.cache_samples("live", payload, [{"idx": 0, "minutes": 1.0}])
    repo.cache_samples("fixture", payload, [{"idx": 0, "minutes": 99.0}])
    assert repo.get_samples("live", payload)[0]["minutes"] == 1.0
    assert repo.get_samples("fixture", payload)[0]["minutes"] == 99.0


def test_repository_poi_roundtrip():
    repo = Repository()
    payload = "kaili"
    cats = [{"category": "market", "total": 4}]
    assert repo.get_poi("live", payload) is None
    repo.cache_poi("live", payload, cats)
    assert repo.get_poi("live", payload) == cats


def test_repository_report_roundtrip():
    repo = Repository()
    payload = "kaili-c"
    report = {"scene": {"name": "凯里老街"}, "scores": {"total": 65}}
    assert repo.get_report("live", payload) is None
    repo.cache_report("fixture", payload, report)
    assert repo.get_report("fixture", payload) == report
    # live 前缀不串
    assert repo.get_report("live", payload) is None