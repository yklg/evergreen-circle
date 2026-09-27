"""v5 U28/U29 · 写路径幂等/隔离与读路径契约（R1/D21 + R2/D22 补实现的测试钉）。

- `delete_living_circle_reports_for_scene`：R1 曾「被调用但全库无定义」（潜伏 AttributeError），
  本版补实现 —— 测试钉住：仅删同 scene / 多 scene 隔离 / 空 scene 安全 / 级联清理关联任务。
- `get_latest_report_id_for_scene`：R2 新增 —— 多报告取 created_at 最新 / 无记录 None / scene 隔离。
  唯一收口（不把 report_id 塞缓存条目），db 为唯一事实源（D22）。
"""
import threading

import pytest

import app.core.db as db


def _mk_report(rid: str, name: str = "测试场景", created_at: str = "", origin: str = "live") -> dict:
    return {
        "id": rid,
        "created_at": created_at,
        "living_circle": {
            "scene": {"name": name},
            "scores": {"total": 70},
            "blindspots": [],
            "data_origin": origin,
        },
    }


# ── U28 · delete_living_circle_reports_for_scene ─────────────────────

def test_u28_delete_only_same_scene():
    db.save_living_circle_report(_mk_report("r-a1", created_at="2026-09-01T00:00:00Z"), scene_key="s28-a")
    db.save_living_circle_report(_mk_report("r-b1", created_at="2026-09-01T00:00:00Z"), scene_key="s28-b")
    assert db.delete_living_circle_reports_for_scene("s28-a") == 1
    assert db.get_latest_report_id_for_scene("s28-a") is None
    assert db.get_latest_report_id_for_scene("s28-b") == "r-b1"  # 多 scene 隔离：B 不受影响


def test_u28_delete_all_rows_of_scene_and_cascades_tasks():
    db.save_living_circle_report(_mk_report("r-1", created_at="2026-09-01T00:00:00Z"), scene_key="s28-x")
    db.save_living_circle_report(_mk_report("r-2", created_at="2026-09-02T00:00:00Z"), scene_key="s28-y")
    db.save_task("t-1", "任务1", {"scene_name": "x"}, kind="living_circle")
    db.save_task("t-2", "任务2", {"scene_name": "y"}, kind="living_circle")
    db.mark_task_done("t-1", "r-1")
    db.mark_task_done("t-2", "r-2")
    assert db.delete_living_circle_reports_for_scene("s28-x") == 1  # 仅同 scene 行被删
    # 级联清理关联任务（report_id 弱关联）：t-1 随 r-1 清除
    assert db.get_task("t-1") is None
    assert db.get_task("t-2") is not None  # 关联 r-2（另一 scene）不受影响
    assert db.get_latest_report_id_for_scene("s28-y") == "r-2"


def test_u28_delete_empty_scene_safe():
    assert db.delete_living_circle_reports_for_scene("不存在的场景") == 0  # 不抛


def test_u28_delete_under_concurrent_writes_no_error():
    """与 save/list 同锁：并发「写 + 删」不炸（D21 并发安全语义）。"""
    errors: list = []

    def writer(i: int):
        try:
            db.save_living_circle_report(_mk_report(f"w{i}", created_at="2026-09-03T00:00:00Z"), scene_key="scene-c")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def deleter():
        try:
            for _ in range(5):
                db.delete_living_circle_reports_for_scene("scene-c")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)] + [threading.Thread(target=deleter)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # 写/删交错时序不确定：终态要么被删空（None），要么残留某次写入 —— 不允许出现脏状态
    latest = db.get_latest_report_id_for_scene("scene-c")
    assert latest is None or latest in {"w0", "w1", "w2"}


# ── U29 · get_latest_report_id_for_scene ─────────────────────────────

def test_u29_latest_by_created_at():
    db.save_living_circle_report(_mk_report("r-old", created_at="2026-08-01T00:00:00Z"), scene_key="scene-l")
    db.save_living_circle_report(_mk_report("r-new", created_at="2026-09-05T00:00:00Z"), scene_key="scene-l")
    assert db.get_latest_report_id_for_scene("scene-l") == "r-new"


def test_u29_no_records_returns_none():
    assert db.get_latest_report_id_for_scene("空场景") is None
    assert db.get_latest_report_id_for_scene("") is None  # 空 scene_key 直接 None，不查库


def test_u29_scene_isolation():
    db.save_living_circle_report(_mk_report("r-a", created_at="2026-09-01T00:00:00Z"), scene_key="s29-a")
    db.save_living_circle_report(_mk_report("r-b", created_at="2026-09-01T00:00:00Z"), scene_key="s29-b")
    assert db.get_latest_report_id_for_scene("s29-a") == "r-a"
    assert db.get_latest_report_id_for_scene("s29-b") == "r-b"


# ── U30 · delete_living_circle_report 的级联完备性 ────────────────────
"""覆盖评估 D2（`~/.qoder-cn/plans/quiet-ridge-teal.md`；架构评审 v4 事实 6）。

不对称的事实：`delete_report`（`db.py:904-924`）按 report_id 级联清
`evidences / traces / report_feedback / tasks / reports` 并在末尾调
`invalidate_aggregates()`（:923，注释「G5 失效钩子：级联删除改变聚合口径」）；
而 `delete_living_circle_report`（`db.py:1451-1458`）**只清 `tasks` +
`living_circle_reports`**，也不失效聚合缓存。

为什么现在必须钉住：计划 v4 波次 B 第 4 步一旦让生活圈证据进 `evidences` 表，
「删除报告」就会留下永久孤儿行 —— `evidence_total` 与 `by_destination` 虚高，
且「计数随报告单调增长」那类断言**照样会绿**（假阳性）。
"""


def _seed_lc_with_related_rows(rid: str, *, destination: str = "北京劲松") -> None:
    """把一份生活圈报告的四张关联表都种上行（走各自生产写路径，不手写 SQL）。"""
    db.save_living_circle_report(_mk_report(rid, created_at="2026-09-06T00:00:00Z"),
                                 scene_key=f"s30-{rid}")
    # 证据：save_report 是 evidences 的唯一入库口（db.py:690-726），复用同 report_id
    db.save_report({
        "id": rid, "title": f"{rid} 证据宿主", "query": "s30", "destinations": [destination],
        "experts": [], "cover_image": "", "created_at": db._now(),
        "evidence": [{"evidence_id": f"e-{rid}", "source_url": "live://poi",
                      "source_type": "poi_search", "domain": "poi", "title": "T",
                      "excerpt": "E", "credibility": 0.9, "collected_by": "x",
                      "destination": destination, "captured_at": db._now()}],
        "claims": [], "metrics": {},
    }, task_id="")
    db.save_traces("t-s30", rid, [{"span_id": f"sp-{rid}", "seq": 1, "agent_id": "a",
                                   "stage": "collect", "purpose": "p"}])
    db.save_report_feedback(rid, 1, 2, {"blocks": 2})


def _count_where(table: str, rid: str) -> int:
    col = "report_id"
    return db._connect().execute(
        f"SELECT COUNT(*) n FROM {table} WHERE {col}=?", (rid,)).fetchone()["n"]


def test_u30_delete_lc_report_removes_report_and_task():
    """**正向（现在就绿）**：报告行与关联任务确实被清 —— 别把后面的红误读成"函数没作用"。

    这条是夹具自证：如果它绿而下面几条红，原因只能是级联缺表，不是桩形或调用写错。
    """
    _seed_lc_with_related_rows("r30-ok")
    db.save_task("t30-ok", "任务", {"scene_name": "x"}, kind="living_circle")
    db.mark_task_done("t30-ok", "r30-ok")
    assert db.delete_living_circle_report("r30-ok") is True
    assert db.get_living_circle_report("r30-ok") is None
    assert db.get_task("t30-ok") is None


@pytest.mark.xfail(strict=True, reason=(
    "D2-1：delete_living_circle_report 只清 tasks+living_circle_reports（db.py:1451-1458），"
    "不像 delete_report 那样级联 evidences/traces/report_feedback（对照 db.py:916-920）。"
    "计划 v4 波次 A 第 1 步（以 delete_report 为级联真相源）落地后摘标。"))
def test_u30_delete_lc_report_cascades_evidences_traces_feedback():
    """级联完备性：删除一份生活圈报告后，四张关联表都不该留孤儿行。"""
    _seed_lc_with_related_rows("r30-cascade")
    assert db.delete_living_circle_report("r30-cascade") is True
    for table in ("evidences", "traces", "report_feedback", "living_circle_reports"):
        assert _count_where(table, "r30-cascade") == 0, f"{table} 残留孤儿行"


def test_u30_current_state_leaves_evidences_traces_feedback():
    """**记录当前行为（不是期望它）**：孤儿行今天确实留着。

    补级联时必须把本用例**重指**为「0 行」断言并删掉这条，而不是留着两套口径互相打脸
    （先例 `test_task_body_contract.py:110-117`「记录当前行为」）。
    """
    _seed_lc_with_related_rows("r30-now")
    assert _count_where("evidences", "r30-now") == 1  # 前置：行确实存在
    assert _count_where("traces", "r30-now") == 1
    assert db.delete_living_circle_report("r30-now") is True
    assert _count_where("evidences", "r30-now") == 1, "当前无级联 ⇒ 证据行永久残留"
    assert _count_where("traces", "r30-now") == 1


@pytest.mark.xfail(strict=True, reason=(
    "D2-2：delete_living_circle_report 不调 invalidate_aggregates（db.py:1451-1458 无该钩子），"
    "而 delete_report 调（db.py:923）⇒ 删除后聚合读数不反映变化。波次 A 第 1 步同批补。"))
def test_u30_delete_lc_report_invalidates_aggregates(monkeypatch):
    """失效钩子对称性：删除报告后必须淘汰聚合缓存。

    用探针直接钉「钩子被调用」，而不是钉「聚合数值变了」—— 后者要等级联先修好，
    两个缺陷会互相遮。正向对照（`delete_report` 会触发钩子）证明探针本身接线有效。
    """
    calls: list = []
    monkeypatch.setattr(db, "invalidate_aggregates", lambda: calls.append("hit"))

    _seed_lc_with_related_rows("r30-inval")
    calls.clear()  # 播种本身会经 save_report 触发钩子（db.py:726），不清掉就成了空断言
    assert db.delete_report("r30-inval") is True
    assert calls, "正面对照失效：探针没接到 delete_report 的钩子，本文件判据不可信"

    calls.clear()
    db.save_living_circle_report(_mk_report("r30-inval2", created_at="2026-09-06T00:00:00Z"),
                                 scene_key="s30-inval2")
    calls.clear()  # 同上：不让"是否被别的写路径顺手失效"混进这条判据
    assert db.delete_living_circle_report("r30-inval2") is True
    assert calls, "delete_living_circle_report 未触发聚合失效"

