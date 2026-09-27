"""D1 · 证据写路径的唯一性与归属（跨报告不互相吞行）。

**为什么单独守这条**：`evidences.evidence_id` 是 `TEXT PRIMARY KEY`
（`app/core/db.py:124`），而写路径是 `INSERT OR REPLACE`（`db.py:713`）⇒ 两份报告
只要有一条 id 相同，后写的就**静默覆盖**前一份的那一行，连带改写它的 `report_id`
归属。读侧不会报错，只是少几条 —— 这正是「目的地情报图谱永远是空的」那类事故的
形状（架构评审 v4 事实 3/5，`~/.qoder-cn/plans/rosy-pool-dory.md`）。

生活圈的证据由 `build_evidence`（`app/core/pipeline/diagnosis_templates.py:462`）
产出，id 目前是**常量或类别拼接**：`"ev-lc-measure"`（:466）、`ev-lc-poi-{category}`
（:474）、`ev-lc-bs-{b.id}`（:480），且**不带 `destination`**。因此一旦让生活圈报告
走证据入库（计划 v4 波次 B 第 4 步 / 待拍板⑤），前两条缺陷会立刻生效。

判据边界：本文件与 `test_chapter_invariants.py:72-73`（章节引用必须落在同一份报告
的证据集内）**正交** —— 那条守「装配体内自洽」，本文件守「跨报告入库不互吞」。

挂账方式：现状缺陷用 `@pytest.mark.xfail(strict=True)`，每条 reason 带评审条目编号与
file:line；修好后转 XPASS 会**主动失败**，强制摘标（先例 `test_caliber_invariants.py:6`、
`test_baidu_client.py:345`）。另有两条「记录当前行为」的正向用例，修复时必须**重指判据**
而不是删除（先例 `test_task_body_contract.py:10`）。

运行：backend/ 下 `pytest tests/test_evidence_write_uniqueness.py -q`
计划编号：D1-1 … D1-4（覆盖评估 `~/.qoder-cn/plans/quiet-ridge-teal.md`）。
"""
import pytest

import app.core.db as db
from app.core.pipeline.diagnosis_templates import build_evidence


@pytest.fixture(autouse=True)
def _clean_business_tables():
    """逐用例清空业务表（沿用 `test_dashboard_stats.py:26-35` 的种子模式）。"""
    c = db._connect()
    for t in ("evidences", "traces", "report_feedback", "tasks", "reports",
              "living_circle_reports"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    yield


def _lc(scene_name: str, city: str, *, category: str = "medical",
        blindspot_id: str = "b1") -> dict:
    """最小可用的 `living_circle` 节点，形状取自真实夹具
    `app/living_circle/fixtures/beijing-jinsong.json`（poi.categories / blindspots /
    sampling 三处 `build_evidence` 会读）。`timed_count`/`in_reach_count` 显式给出，
    避免走 `sampling_counts` 的按点回算分支（那是另一个判据，别混进来）。
    """
    return {
        "generated_at": "2026-09-27T00:00:00Z",
        "scene": {"name": scene_name, "city": city},
        "sampling": {"points": [], "timed_count": 40, "in_reach_count": 25},
        "poi": {"categories": [{"category": category, "label": "医疗",
                                 "total": 12, "in_circle": 5}]},
        "blindspots": [{"id": blindspot_id, "missing_facilities": ["超市"]}],
        "scores": {"total": 70},
        "data_origin": "live",
    }


def _ev(eid: str, destination: str) -> dict:
    return {
        "evidence_id": eid, "source_url": f"https://example.com/{eid}",
        "source_type": "official", "domain": "example.com", "title": f"证据 {eid}",
        "excerpt": "内容", "credibility": 90.0, "collected_by": "tester",
        "destination": destination, "captured_at": db._now(),
    }


def _save(rid: str, evidence: list, destination: str) -> None:
    """走生产写路径 `db.save_report`（它才是 evidences 的唯一入库口，db.py:690-726）。"""
    db.save_report({
        "id": rid, "title": f"{rid} 报告", "subtitle": "", "query": "测试查询",
        "destinations": [destination], "experts": [], "cover_image": "",
        "created_at": db._now(), "evidence": evidence, "claims": [], "metrics": {},
    }, task_id="")


def _rows_for(rid: str) -> list:
    c = db._connect()
    return [r["evidence_id"] for r in
            c.execute("SELECT evidence_id FROM evidences WHERE report_id=? ORDER BY evidence_id",
                      (rid,)).fetchall()]


def _total_rows() -> int:
    return db._connect().execute("SELECT COUNT(*) n FROM evidences").fetchone()["n"]


# ── D1-1 正向守缝：id 互异时，两份报告的证据必须并存 ─────────────

def test_distinct_evidence_ids_are_kept_side_by_side():
    """不变量的正面：id 全局唯一 ⇒ 两份报告各 3 行、互不干扰。

    这条必须**现在就绿**。它证明本文件的桩形与写路径都没问题，因此后面几条转红时，
    原因只能是「id 相同被覆盖」，不会是夹具写错。
    """
    _save("r-A", [_ev("e-A-1", "目的地A"), _ev("e-A-2", "目的地A"), _ev("e-A-3", "目的地A")],
          "目的地A")
    _save("r-B", [_ev("e-B-1", "目的地B"), _ev("e-B-2", "目的地B"), _ev("e-B-3", "目的地B")],
          "目的地B")
    assert _total_rows() == 6
    assert _rows_for("r-A") == ["e-A-1", "e-A-2", "e-A-3"]
    assert _rows_for("r-B") == ["e-B-1", "e-B-2", "e-B-3"]


# ── D1-2 现状缺陷：生活圈证据 id 跨报告必重 ─────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "D1-2：build_evidence 产常量/类别拼接 id（diagnosis_templates.py:466,474,480），"
    "而 evidence_id 是主键 + INSERT OR REPLACE（db.py:124,713）⇒ 第二份报告覆盖第一份。"
    "计划 v4 波次 B 第 4 步（id 报告作用域化）落地后摘标。"))
def test_two_lc_reports_do_not_overwrite_each_other_evidence():
    """两个不同样区、各自跑 `build_evidence` 入库 ⇒ 应当 6 行、每份 3 行。"""
    _save("lc-r-A", build_evidence(_lc("北京劲松", "北京·朝阳")), "北京劲松")
    _save("lc-r-B", build_evidence(_lc("凯里老街", "黔东南")), "凯里老街")
    assert _total_rows() == 6, f"实际 {_total_rows()} 行：id 相同被 INSERT OR REPLACE 吞掉"
    assert len(_rows_for("lc-r-A")) == 3, "第一份报告的证据归属被后一份改写"


def test_lc_evidence_id_shapes_are_as_documented():
    """**现状记录（必须绿）**：钉住 `build_evidence` 今天产出的 id 形态。

    单独钉一条绿的意义：下面那条参数化 xfail 里若前缀表写错，取到的样本集会变空，
    「无交集」就成了空集假象 —— 而 xfail 体内部的任何失败都长得像"如期失败"，看不出是
    夹具失效。把取样事实挪到绿用例里，错了就立刻红在这里。
    """
    ids = {e["evidence_id"] for e in build_evidence(_lc("北京劲松", "北京·朝阳"))}
    assert ids == {"ev-lc-measure", "ev-lc-poi-medical", "ev-lc-bs-b1"}, sorted(ids)


@pytest.mark.parametrize("kind", ["measure", "poi", "blindspot"])
@pytest.mark.xfail(strict=True, reason=(
    "D1-3：同一 kind 的证据 id 不含报告作用域（ev-lc-measure / ev-lc-poi-{category} / "
    "ev-lc-bs-{blindspot.id}，diagnosis_templates.py:466-483）⇒ 跨报告 id 集合必然相交。"))
def test_lc_evidence_ids_are_unique_per_kind_across_reports(kind):
    """等价类划分：三类证据来源各测一条，避免「只测了 measure 就以为都安全」。

    按 id **前缀**取类，不按 kind 字样做子串匹配 —— 盲区证据 id 是 `ev-lc-bs-*`，
    并不含 "blindspot" 这个词，子串筛会筛出空集让断言空转（取样事实由上面那条绿用例守）。
    """
    prefix = {"measure": "ev-lc-measure", "poi": "ev-lc-poi-", "blindspot": "ev-lc-bs-"}[kind]
    ids_a = {e["evidence_id"] for e in build_evidence(_lc("北京劲松", "北京·朝阳"))}
    ids_b = {e["evidence_id"] for e in build_evidence(_lc("凯里老街", "黔东南"))}
    shared = {i for i in (ids_a & ids_b) if i == prefix or i.startswith(prefix)}
    assert not shared, f"「{kind}」类证据 id 跨报告相同：{sorted(shared)}"


# ── D1-4 现状缺陷：证据没有 destination，入库即成隐形数据 ─────────

@pytest.mark.xfail(strict=True, reason=(
    "D1-4：build_evidence 的记录不含 destination 键 ⇒ save_report 落成空串（db.py:720），"
    "再被 evidence_facets 的 WHERE destination!=''（db.py:1015）与情报页的 if (!b) continue "
    "（改造版 DashboardPage.tsx:91-92）双重丢弃 ⇒ 目的地情报图谱恒空。"))
def test_lc_evidence_rows_carry_a_destination():
    """每条生活圈证据都必须带非空 destination，否则入库了也等于没入库。"""
    for e in build_evidence(_lc("北京劲松", "北京·朝阳")):
        assert (e.get("destination") or "").strip(), f"{e['evidence_id']} 缺 destination"


def test_destination_less_evidence_is_invisible_to_facets():
    """**记录当前行为**：缺 destination 的行确实进了表，但对目的地聚合完全不可见。

    这条现在是绿的，且它绿得正是问题所在。修复（D1-4 摘标）时**不要删它**，
    改成断言「带 destination 的行必须出现在 by_destination」——判据重指，先例见
    `test_task_body_contract.py:10`「不许直接删掉记录当前行为的那条用例」。
    """
    _save("lc-r-nodest", [{"evidence_id": "e-no-dest", "source_url": "live://poi",
                          "source_type": "poi_search", "domain": "poi", "title": "T",
                          "excerpt": "E", "credibility": 0.9, "collected_by": "x",
                          "captured_at": db._now()}], "北京劲松")
    assert _total_rows() == 1, "行确实写进去了"
    assert db.evidence_facets()["by_destination"] == {}, "但对目的地聚合是隐形的"
