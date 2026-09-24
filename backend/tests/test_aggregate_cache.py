"""只读聚合缓存契约测试（执行计划 G5；test-coverage-expander 方案 B-06）。

契约（db.py _AGG_CACHE 层）：
- 首次读未命中 → 重建一次（compute 计数=1）；二次读命中 → 计数不增、结构等价；
- 写路径失效钩子：save_report / delete_report / invalidate_report_brief → 缓存淘汰后重查重建；
- 失效幂等：无缓存时 invalidate_aggregates() 不报错；
- 读返回深拷贝：修改返回对象不污染缓存本体；
- dashboard 与 intel 共享同一份聚合（一次 compute 同时喂两个入口）。

种子模式沿用 test_dashboard_stats（conftest 隔离 + 逐用例清业务表）。
运行：backend/ 下 `pytest tests/test_aggregate_cache.py -q`
"""
import pytest

import app.core.db as db


@pytest.fixture(autouse=True)
def _clean_business_tables():
    """逐用例清空业务表 + 失效聚合缓存（双保险，避免跨用例脏缓存）。"""
    c = db._connect()
    for t in ("evidences", "traces", "report_feedback", "tasks", "reports"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    db.invalidate_aggregates()
    yield


def _ev(eid, source_type="douyin", destination="目的地A", credibility=80.0):
    return {
        "evidence_id": eid, "source_url": "https://example.com/" + eid,
        "source_type": source_type, "domain": "example.com", "title": "证据 " + eid,
        "excerpt": "内容", "credibility": credibility, "collected_by": "tester",
        "destination": destination, "captured_at": db._now(),
    }


def _make_report(rid, *, evidence=None, metrics=None, claims=None):
    report = {
        "id": rid, "title": "报告 " + rid, "subtitle": "", "query": "测试查询",
        "destinations": ["目的地A"], "experts": [], "cover_image": "", "created_at": db._now(),
        "evidence": evidence or [], "claims": claims or [],
        "metrics": metrics or {
            "efficiency": {"manual_estimate_minutes": 60, "elapsed_minutes": 10,
                           "efficiency_multiple": 6, "tokens_used": 500},
        },
    }
    db.save_report(report, task_id="")


def _count_compute(monkeypatch):
    """替换 _agg_compute 为计数版，返回计数 dict（monkeypatch 用例结束自动还原）。"""
    calls = {"n": 0}
    orig = db._agg_compute

    def _wrapped():
        calls["n"] += 1
        return orig()
    monkeypatch.setattr(db, "_agg_compute", _wrapped)
    return calls


# ── B-06-1：首查重建 / 二次命中 ──────────────────────────
def test_first_miss_then_hit_no_recompute(monkeypatch):
    """首查 compute=1；二次读命中 → 计数不增且结构等价；dashboard/intel 共享同一次聚合。"""
    _make_report("r_c1", evidence=[_ev("e_c1")])
    calls = _count_compute(monkeypatch)

    s1 = db.dashboard_stats()
    assert calls["n"] == 1, "首查应重建一次"
    assert s1["reports"] == 1 and s1["evidence_total"] == 1

    s2 = db.dashboard_stats()
    assert calls["n"] == 1, "二次读应命中缓存（不重算）"
    assert s2 == s1, "命中返回与首查结构等价"

    i = db.intel_overview()
    assert calls["n"] == 1, "intel 入口应共享 dashboard 同一次聚合"
    assert i["total_tokens"] == 500


def test_read_returns_deep_copy_not_cached_object():
    """读返回深拷贝：修改返回值不污染缓存本体。"""
    _make_report("r_c2", evidence=[_ev("e_c2")])
    s = db.dashboard_stats()
    s["reports"] = 999
    s["platform_distribution"]["douyin"] = 999
    s["research_cards"][0]["title"] = "被改"
    again = db.dashboard_stats()
    assert again["reports"] == 1
    assert again["platform_distribution"]["douyin"] == 1
    assert again["research_cards"][0]["title"].startswith("报告 r_c2")


# ── B-06-2：写路径失效钩子 ───────────────────────────────
def test_save_report_invalidates_cache(monkeypatch):
    """save_report 写路径 → 缓存淘汰 → 新报告被重查覆盖。"""
    db.dashboard_stats()  # 先建缓存（空库）
    calls = _count_compute(monkeypatch)

    _make_report("r_c3", evidence=[_ev("e_c3")])   # 写路径 → 应失效
    s = db.dashboard_stats()
    assert calls["n"] == 1, "写后读应重建"
    assert s["reports"] == 1 and s["evidence_total"] == 1


def test_delete_report_invalidates_cache():
    """delete_report 写路径 → 缓存淘汰 → 删除即时反映。"""
    _make_report("r_c4", evidence=[_ev("e_c4")])
    assert db.dashboard_stats()["reports"] == 1
    db.delete_report("r_c4")
    s = db.dashboard_stats()
    assert s["reports"] == 0 and s["evidence_total"] == 0


def test_invalidate_report_brief_hooks_cache():
    """invalidate_report_brief 写路径（data 更新）→ 缓存淘汰（无缓存时幂等 no-op）。"""
    _make_report("r_c5", evidence=[_ev("e_c5")])
    assert db.dashboard_stats()["reports"] == 1
    db.invalidate_report_brief("r_c5")   # 无 brief，但 data 写路径仍应失效
    assert db.dashboard_stats()["reports"] == 1  # 重建后口径不变


# ── B-06-3：失效幂等 ─────────────────────────────────────
def test_invalidate_aggregates_idempotent():
    """无缓存时 invalidate 不报错；连续多次失效后读取仍正确。"""
    db.invalidate_aggregates()  # 空缓存 no-op
    db.invalidate_aggregates()
    _make_report("r_c6", evidence=[_ev("e_c6")])
    db.invalidate_aggregates()
    assert db.dashboard_stats()["reports"] == 1


def test_intel_overview_hit_after_dashboard():
    """dashboard 先行 → intel_overview 命中同一次聚合（缓存存在，非二次全表扫描）。"""
    _make_report("r_c7", evidence=[_ev("e_c7")])
    db.dashboard_stats()
    assert db._AGG_CACHE is not None, "dashboard 已建立共享聚合缓存"
    intel = db.intel_overview()
    assert intel["minutes_saved"] == 50
    assert intel["total_tokens"] == 500