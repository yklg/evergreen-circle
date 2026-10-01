"""用户指定信源进统计与标签下发（实施计划 v3 §二 B6 + G0 的展示面 · §八 TC-37 / TC-38 / CT-03）。

守护的契约
----------
1. **饼图自动多一类**：`evidence_facets` 是 `GROUP BY source_type`（`db.py`），
   新类别一进 `evidences` 表就自动进 `platform_distribution` ⇒ 本文件钉的是"确实自动"，
   而不是"我们额外补了一条 SQL"。补第二条 SQL 就是第二个口径，早晚和 GROUP BY 漂开。
2. **聚合缓存必须被写路径打穿**：`_AGG_CACHE` 是进程级只读缓存，写证据后不失效的话，
   用户刷新看到的是旧饼图 —— 这类"功能对了、界面没动"最难查。
3. **口径变动要可见**（前端 `degradeDisclosure` 同源纪律）：说明行只在真有用户指定
   信源时出现；没有时**不出现**。一句永远在的话等于没有话。
4. **中文标签的唯一真相源是注册表**：`/api/source-kinds` 下发 `kind_view()`；
   新类别若前端各抄一份映射，它会显示成裸 key（`user_supplied` 直接上屏），
   而且没有任何东西会变红。

期望值来源
----------
- `label_zh` 取自 `source_type.SOURCE_KINDS`（逐项比对，不抄中文串）；
- `base_score` 的 16 项等值由 `test_pool_membership_baseline.py` 钉，本文件不重复；
- 缓存失效钩子取自 `db.invalidate_aggregates` 的既有约定（写路径成功后调用）。
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core import source_type as ST
from app.core.models import Evidence
from app.main import app

client = TestClient(app)


def _report_with_evidence(report_id: str, types: Dict[str, int]) -> None:
    """经**生产写路径**落一份带指定类别证据的报告（不手写 INSERT SQL）。"""
    evidence = []
    for i, (stype, n) in enumerate(types.items()):
        for j in range(n):
            evidence.append({
                "evidence_id": f"e_{report_id}_{i}_{j}",
                "source_url": f"https://s{i}{j}.example.org/doc",
                "source_type": stype,
                "domain": f"s{i}{j}.example.org",
                "title": f"t{stype}{j}", "excerpt": "x", "credibility": 60.0,
                "collected_by": "L1-025", "destination": "大理",
                "captured_at": "2026-09-01T00:00:00Z",
            })
    db.save_report({
        "id": report_id, "title": f"{report_id} 标题", "query": "大理调研",
        "destinations": ["大理"], "experts": [], "cover_image": "", "created_at": db._now(),
        "evidence": evidence, "claims": [], "metrics": {},
    }, task_id="")


@pytest.fixture(autouse=True)
def _clean_reports():
    """本文件的断言是**绝对计数**，而 `platform_distribution` 是全表实时聚合。

    因此清库必须在 setup 也做一次：只做 teardown 等于假设"前面跑过的文件都自觉清了库"，
    而 reports/evidences 两张表并不在 autouse `_isolate` 的管辖内 —— 任何一个后来者写进
    一行 user_supplied 证据，本文件的 "== 1" 就会读成 6（这正是本轮全量跑出的红法）。
    """
    _wipe()
    yield
    _wipe()


def _wipe() -> None:
    c = db._connect()
    for t in ("evidences", "reports", "traces", "tasks"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    db.invalidate_aggregates()


# ── 1. 新类别自动进分布 ────────────────────────────────────────────

def test_user_supplied_evidence_appears_in_platform_distribution_without_extra_sql():
    _report_with_evidence("r-b6-a", {"web": 2, "user_supplied": 1})

    dist = db.intel_overview()["platform_distribution"]
    assert dist.get("user_supplied") == 1, f"新类别没进饼图数据：{dist}"
    assert dist.get("web") == 2


def test_distribution_counts_survive_a_second_report():
    """全表实时聚合：两份报告的同类别**累加**（这正是"历史不可比"的成因，见说明行）。"""
    _report_with_evidence("r-b6-b", {"user_supplied": 1})
    _report_with_evidence("r-b6-c", {"user_supplied": 2})
    assert db.intel_overview()["platform_distribution"]["user_supplied"] == 3


def test_no_user_supplied_evidence_means_the_key_is_absent_not_zero():
    """没填清单的任务不得凭空造出一个 "user_supplied": 0 的扇区。"""
    _report_with_evidence("r-b6-d", {"web": 1})
    dist = db.intel_overview()["platform_distribution"]
    assert "user_supplied" not in dist, dist


# ── 2. 聚合缓存失效 ────────────────────────────────────────────────

def test_aggregate_cache_is_invalidated_by_the_write_path():
    """写路径必须打穿 `_AGG_CACHE`，否则界面停在旧饼图（计划 §二 B6 的显式核查项）。"""
    _report_with_evidence("r-b6-e", {"web": 1})
    first = db.intel_overview()["platform_distribution"]      # 这次读会建缓存
    _report_with_evidence("r-b6-f", {"user_supplied": 4})     # 写路径应顺带失效缓存
    second = db.intel_overview()["platform_distribution"]

    assert first.get("user_supplied") in (None, 0), first
    assert second.get("user_supplied") == 4, (
        f"写完新证据后读到的还是旧聚合：{second} —— 缓存失效钩子没覆盖这条写路径")


# ── 3. 口径说明行的可见性 ──────────────────────────────────────────

def test_disclosure_line_appears_only_when_user_sources_are_present():
    """§八 TC-38：有则说明、无则不出现（永远在的说明等于没有说明）。"""
    _report_with_evidence("r-b6-g", {"web": 1})
    assert db.intel_overview()["distribution_note"] == "", "无用户信源时不该有说明行"

    _report_with_evidence("r-b6-h", {"user_supplied": 3})
    note = db.intel_overview()["distribution_note"]
    assert "用户指定信源" in note and "3" in note, note


def test_disclosure_counts_the_evidence_rows_not_the_manifest_size():
    """说明行报的是**已入库**条数：归并/未读取的网址不会成为证据行，不能虚报。"""
    _report_with_evidence("r-b6-i", {"user_supplied": 1})
    intel = db.intel_overview()
    assert intel["user_source_evidence"] == 1
    assert str(intel["distribution_note"]).count("1") >= 1


# ── 4. 标签下发：注册表是唯一真相源 ────────────────────────────────

def test_source_kinds_endpoint_returns_the_registry_view():
    body = client.get("/api/source-kinds").json()
    kinds = body["kinds"]
    assert {k["id"] for k in kinds} == set(ST.SOURCE_KINDS), "下发集与注册表不同集"
    by_id = {k["id"]: k for k in kinds}
    # 中文标签逐项取自注册表对象本身，不抄字面量：改注册表名这里自动跟着走
    for key, kind in ST.SOURCE_KINDS.items():
        assert by_id[key]["label"] == kind.label_zh, key
    assert by_id["user_supplied"]["label"] == "用户指定"


def test_source_kinds_endpoint_lists_no_unlabelled_kind():
    """每个类别都得有非空中文名，否则前端只能显示裸 key（这就是本功能要消灭的形状）。"""
    kinds = client.get("/api/source-kinds").json()["kinds"]
    blank = [k["id"] for k in kinds if not str(k["label"]).strip()]
    assert not blank, f"这些类别没有展示名：{blank}"


def test_kind_view_is_stably_ordered_for_direct_ui_rendering():
    """下发顺序即展示顺序（按基准分降序、同分按 id）：UI 不再各自 sort，两次请求同序。"""
    ids = [k["id"] for k in client.get("/api/source-kinds").json()["kinds"]]
    assert ids == sorted(ids, key=lambda i: (-ST.SOURCE_KINDS[i].base_score, i)), ids


def test_user_supplied_kind_is_registered_with_the_decided_base_score():
    """待确认 1 已拍板 base_score=60，且 fetchable/in_stats/in_groups 均为真。"""
    kind = ST.SOURCE_KINDS["user_supplied"]
    assert kind.base_score == 60
    assert (kind.fetchable, kind.in_stats, kind.in_groups) == (True, True, True)
    assert kind.provenance == "user", "provenance 不是 user ⇒ 内网闸门的默认启用判据失去依据"
    assert kind.must_read is True, "必读标志缺失会让保留槽整套机制静默失效"


def test_credibility_base_scores_are_derived_from_the_registry():
    """`credibility` 的分值表必须**是**注册表派生的那份（同一对象，不是抄一份）。"""
    from app.core import credibility

    assert credibility._BASE_BY_TYPE is ST.BASE_BY_TYPE
    assert ST.BASE_BY_TYPE["user_supplied"] == 60
