"""存量报告读时归一（RENAME COLUMN 不改 data JSON）—— B4（R3 读时兼容）。

守护的不变量（db._normalize_report_keys / get_report / list_reports / dashboard_stats）：
- 旧 `reports.data` 快照里的 `brands` / `brand` 键在读路径归一到 `destinations` / `destination`，
  旧键不得漏到上层（前端只见新契约）；
- 归一不动其他字段：标题、章节、旧 `structured.type` 原样保留（前端分支删除后自动不渲染）；
- 旧报告仍可 refine / generate_brief（不因缺新键失败）；
- **新旧键并存时新键优先**（归一不得用旧值覆盖新值）。

种子：test_clarify_async.py::db2_alter_migration（旧形态库造数）、
      test_aggregate_cache.py::intel_overview_bad_json_row（坏行不致命）、
      test_refine_evidence.py::refine_section_refactor_regression（refine 读路径）。
运行：backend/ 下 `pytest tests/test_report_read_compat.py -q`
"""
import json

import pytest

import app.core.db as db
from app.core.pipeline.research import engine as O

_LEGACY_DATA = {
    "id": "r_legacy",
    "title": "大理、丽江 竞品研究报告",
    "subtitle": "旧形态快照",
    "query": "大理 5 天亲子游",
    "brands": ["大理", "丽江"],                     # 旧契约键
    "experts": ["L3-001"],
    "cover_image": "",
    "created_at": "2026-01-01T00:00:00",
    "sections": [
        {"id": "summary", "title": "执行摘要 · 核心判断", "key_takeaway": "旧摘要",
         "highlights": ["旧亮点"], "paragraphs": ["旧全文段落"]},
        {"id": "pricing", "title": "定价策略", "paragraphs": ["旧定价段落"]},   # legacy 章节 id
    ],
    "structured": {"type": "feature_tree", "data": {"功能树": ["A", "B"]}},     # legacy 结构化类型
    "claims": [],
    "metrics": {},
    "evidence": [
        {"evidence_id": "e_legacy", "source_url": "https://example.com/l",
         "source_type": "web", "domain": "example.com", "title": "旧证据",
         "excerpt": "摘要", "credibility": 80.0, "collected_by": "L1-025",
         "brand": "大理", "captured_at": "2026-01-01T00:00:00"},
    ],
}


def _insert_legacy_report(data: dict = None, rid: str = "r_legacy") -> None:
    """绕过 save_report 直接落一行旧形态报告（模拟迁移前的存量库）。"""
    d = dict(_LEGACY_DATA if data is None else data)
    d["id"] = rid
    c = db._connect()
    c.execute(
        "INSERT OR REPLACE INTO reports(report_id,task_id,title,subtitle,query,destinations,"
        "research_type,experts,cover_image,data,evidence_count,claim_count,high_conf_count,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, "", d.get("title", ""), d.get("subtitle", ""), d.get("query", ""),
         json.dumps(d.get("destinations", []), ensure_ascii=False),     # 列本就新形态
         "guide", json.dumps(d.get("experts", []), ensure_ascii=False),
         d.get("cover_image", ""), json.dumps(d, ensure_ascii=False),
         len(d.get("evidence", [])), 0, 0, d.get("created_at", db._now())),
    )
    c.commit()


@pytest.fixture(autouse=True)
def _clean_reports():
    c = db._connect()
    for t in ("evidences", "reports"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    yield


# ── ① 读时归一：旧键消失、新键就位、非键字段不动 ────────────
def test_legacy_report_keys_normalized_on_read():
    _insert_legacy_report()
    rep = db.get_report("r_legacy")
    assert rep is not None
    assert rep["destinations"] == ["大理", "丽江"]
    assert "brands" not in rep, "旧键不得漏到上层"
    assert rep["research_type"] == "guide", "旧报告缺 research_type → 补默认值"
    # 非键字段原样：标题/章节/旧结构化类型不动
    assert rep["title"] == "大理、丽江 竞品研究报告"
    assert [s["id"] for s in rep["sections"]] == ["summary", "pricing"]
    assert rep["structured"]["type"] == "feature_tree"
    # 证据项 brand → destination
    assert rep["evidence"][0]["destination"] == "大理"
    assert "brand" not in rep["evidence"][0]


def test_legacy_card_and_dashboard_reads():
    """列表卡片 / 仪表盘 / 证据分面：旧报告参与聚合且键名为新契约。"""
    _insert_legacy_report()
    # 旧快照里的证据通过 save_report 之外的路径未落 evidences 表 → 手动补一行，验证 live 覆盖
    db._connect().execute(
        "INSERT OR REPLACE INTO evidences(evidence_id,report_id,source_url,source_type,domain,"
        "title,excerpt,credibility,collected_by,destination,captured_at)"
        " VALUES('e_legacy','r_legacy','https://example.com/l','web','example.com','旧证据',"
        "'摘要',80.0,'L1-025','大理',?)",
        (db._now(),),
    )
    db._connect().commit()
    db.invalidate_aggregates()

    card = [r for r in db.list_reports() if r["id"] == "r_legacy"][0]
    assert "brands" not in card and "destinations" in card
    assert db.evidence_facets()["by_destination"] == {"大理": 1}
    assert db.dashboard_stats()["destination_distribution"] == {"大理": 1}


# ── ② 旧报告 refine：不因缺新键失败，且用上了归一后的目的地 ──
def test_legacy_report_refine_uses_normalized_destinations(monkeypatch):
    _insert_legacy_report()
    prompts = []

    def _fake_rewrite(section, extra_context, system_prompt):
        prompts.append(extra_context.get("digest", ""))
        section["paragraphs"] = ["归一后重写段落"]
        section["refined"] = True
        return section

    monkeypatch.setattr(O, "_rewrite_section", _fake_rewrite)
    res = O.refine_section("r_legacy", "summary", ["补充交通信息"])
    assert res["ok"] is True, "旧报告必须仍可精炼（不得因键名老旧而失败）"
    assert prompts and "大理、丽江" in prompts[0], "精炼提示词应带上归一后的目的地"
    # 重写结果已落库
    assert db.get_report("r_legacy")["sections"][0]["refined"] is True


# ── ③ 旧报告 generate_brief：缺 summary/metrics 也不失败 ────
def test_legacy_report_generate_brief_survives(monkeypatch):
    _insert_legacy_report()
    monkeypatch.setattr(O, "chat_json", lambda messages, **kw: {
        "summary": "旧报告一页纸", "judgments": ["判断"], "key_data": ["数据"], "actions": ["行动"],
    })
    brief = O.generate_brief("r_legacy")
    assert brief, "旧报告应能生成一页纸精炼"
    assert brief.get("summary")


# ── ④ 新旧键并存 → 新键优先（归一不得反向覆盖）────────────
def test_both_keys_present_new_wins():
    legacy = dict(_LEGACY_DATA)
    legacy["destinations"] = ["新目的地"]       # 新键已有值
    legacy["brands"] = ["旧目的地"]             # 旧键同时存在
    _insert_legacy_report(legacy, rid="r_both")
    rep = db.get_report("r_both")
    assert rep["destinations"] == ["新目的地"], "新键必须优先，旧键只可丢弃不可覆盖"
    assert "brands" not in rep


def test_normalize_is_pure_and_idempotent():
    """归一幂等：对已归一的 dict 再跑一次结果不变（重连/多次读路径安全）。"""
    once = db._normalize_report_keys(dict(_LEGACY_DATA))
    twice = db._normalize_report_keys(dict(once))
    assert once == twice
    assert once["destinations"] == ["大理", "丽江"]
    assert db._normalize_report_keys("not-a-dict") == "not-a-dict", "非 dict 输入原样返回，不抛"


# ── ⑦ G18 · 降级标记只走运行流，存量报告读路径不受影响（MIG-01）──
def test_legacy_report_has_no_plan_fallback_fields():
    """目的地降级只存在于 trace 与运行中 SSE，不进报告 payload：
    旧快照既无该字段、读路径也不得凭空补出（否则前端横幅会误挂到历史报告上）。
    """
    _insert_legacy_report()
    rep = db.get_report("r_legacy")
    for key in ("plan_fallback", "degraded", "dest_source"):
        assert key not in rep, f"报告 payload 不应出现内部降级字段 {key}"
    # 旧快照没有 trace 数组：读路径不补 span
    assert not [s for s in (rep.get("trace") or []) if s.get("purpose") == O._DEST_PLAN_STEP]


# ── ⑧ W-B5 · 旧 wordcloud echarts option spec 存量哨兵（E1 契约变更后不迁移不改写）──
def test_legacy_wordcloud_option_spec_passes_through_untouched():
    """历史报告 data.charts 里的旧词云 spec（option.series[0].data 形状）：
    读路径必须原样下发——后端不为存量报告重写 spec，双形状兼容由前端渲染器承担。
    """
    legacy = dict(_LEGACY_DATA)
    legacy["charts"] = [{"chart_id": "ch_old", "type": "wordcloud", "title": "全网口碑热词词云",
                         "option": {"title": {"text": "全网口碑热词词云"},
                                    "series": [{"type": "wordcloud",
                                                "data": [{"name": "古城", "value": 5}]}]},
                         "evidence_ids": []}]
    _insert_legacy_report(legacy, rid="r_cloud_legacy")
    rep = db.get_report("r_cloud_legacy")
    cloud = rep["charts"][0]
    assert cloud["type"] == "wordcloud"
    assert "words" not in cloud, "读路径不得给旧 spec 凭空补新键"
    assert cloud["option"]["series"][0]["data"] == [{"name": "古城", "value": 5}]


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
