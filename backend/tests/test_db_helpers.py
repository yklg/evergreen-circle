"""v5 U28/U29 · 写路径幂等/隔离与读路径契约（R1/D21 + R2/D22 补实现的测试钉）。

- `delete_living_circle_reports_for_scene`：R1 曾「被调用但全库无定义」（潜伏 AttributeError），
  本版补实现 —— 测试钉住：仅删同 scene / 多 scene 隔离 / 空 scene 安全 / 级联清理关联任务。
- `get_latest_report_id_for_scene`：R2 新增 —— 多报告取 created_at 最新 / 无记录 None / scene 隔离。
  唯一收口（不把 report_id 塞缓存条目），db 为唯一事实源（D22）。
"""
import threading

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
