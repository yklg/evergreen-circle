"""地标体检的发起、关联与场景隔离（附录 G-08 / G-09 / G-10 / G-11，第一片 D3 / D4 / D10 / 片 1b，
TC-10 / TC-13 / TC-14 / TC-16 / TC-16b）。

地标闭环把「一份攻略」和「一份体检报告」绑在一起，于是冒出四类今天**尚不存在**的接缝。
本文件按「先记实现、再登记缺口」两两成对写法：每对里绿的那条钉住今天的真相，
`xfail(strict)` 那条钉住必须长出来的东西 —— 落地后若忘了摘标记会直接报 XPASS。

今天的真相（绿条实测）：
* `report_spot_checks` 侧表、`db.attach_spot_check()`、runner 终态钩子**全部不存在**；
* `GET /api/life-circle/compare` 对场景**完全无感**：只要两份报告都在库里就能配对
  ⇒ 地标体检一旦入库，用户可以把「官渡区」和「甲秀楼」配成 A/B，得到一张语义错误
  却看起来像证据的差异表（计划 D10 的 P0-2）；
* 列表接口不透出 `scenario` ⇒ 归档里两类记录混列且无从解释；
* `GET /api/life-circle/usage` 不存在（404）⇒ 前端没有额度可显示，
  而 `baidu_daily_quota` 默认 0（＝不约束）⇒ 硬门只能做在**串行锁**上。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.pipeline.diagnosis_templates import assemble_report
from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUNNER = BACKEND_ROOT / "app" / "core" / "runner.py"


def _save(report_id: str, scenario: str | None = None) -> str:
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    if scenario:
        lc["scenario"] = scenario
    report = assemble_report(lc, report_id, f"key:{report_id}", f"关联用例 {report_id}")
    db.save_living_circle_report(report, scene_key=f"key:{report_id}")
    return report_id


# ── G-10 / TC-14：compare 对场景无感 ─────────────────────────────


def test_compare_currently_pairs_any_two_reports():
    """**现状记录（D10 的 P0-2）**：compare 只要两份报告存在就出差异表，跨场景不拦。

    第二条报告只是带上了 `scenario='visitor'` 这个今天无人读的字段 —— 说明
    「地标体检入库」这一步本身不需要改 compare 就能发生，误配是**默认行为**而非边缘情况。
    场景隔离落地后本用例转红，须改为断言 422。
    """
    a = _save("lc-link-home")
    b = _save("lc-link-spot", scenario="visitor")
    resp = client.get(f"/api/life-circle/compare?ids={a},{b}")
    assert resp.status_code == 200, (
        f"compare 已能拒绝跨场景配对（{resp.status_code}）⇒ 本用例须改为正向断言 422"
    )
    assert len(resp.json()["reports"]) == 2, "跨场景两份报告被静默配成了 A/B"


def test_list_endpoint_does_not_expose_scenario():
    """**现状记录**：列表短字段里没有 `scenario` ⇒ 归档无法区分社区体检 / 景点体检。"""
    _save("lc-link-list")
    rows = client.get("/api/life-circle").json()
    assert rows, "列表为空 ⇒ 本用例失去意义，先修落库路径"
    assert "scenario" not in rows[0], (
        f"列表已透出 scenario（keys={sorted(rows[0])}）⇒ 请补「按场景过滤」的前端契约用例"
    )


@pytest.mark.xfail(strict=True, reason="D10：compare 必须对跨场景配对直接 422（不是静默过滤）")
def test_compare_refuses_cross_scenario_pairing():
    """社区 + 景点配对必须 422 并给出可读原因，而不是"选不动"或悄悄只比一份。"""
    a = _save("lc-link-422-home")
    b = _save("lc-link-422-spot", scenario="visitor")
    resp = client.get(f"/api/life-circle/compare?ids={a},{b}")
    assert resp.status_code == 422
    assert "scenario" in json.dumps(resp.json(), ensure_ascii=False) or "场景" in resp.text


# ── G-08 / TC-10：侧表与发起幂等 ─────────────────────────────────


def test_no_spot_check_side_table_yet():
    """**现状记录（D3）**：报告层没有攻略↔体检的关联表，也没有写入口。"""
    assert not hasattr(db, "attach_spot_check"), (
        "db.attach_spot_check 已存在 ⇒ 本用例改为正向断言，并删除配套 xfail"
    )
    tables = {
        r[0] for r in db._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "report_spot_checks" not in tables


@pytest.mark.xfail(
    strict=True,
    reason="D4：同一 (host_report_id, spot_id, scenario) 重复发起必须复用，不产第二行第二任务",
)
def test_spot_check_attach_is_idempotent_per_spot_and_scenario():
    """连点同一景点三次 ⇒ 侧表仍一行；换场景才允许新行；重复写不得产生脏数据。"""
    key = {"host_report_id": "r-guide-1", "host_kind": "guide", "spot_id": "spot-甲秀楼", "scenario": "visitor"}
    db.attach_spot_check(lc_report_id="lc-spot-1", **key, snapshot={}, captured_at="2026-09-26T00:00:00")
    db.attach_spot_check(lc_report_id="lc-spot-2", **key, snapshot={}, captured_at="2026-09-26T00:05:00")
    rows = db.list_spot_checks(**key)
    assert len(rows) == 1, f"重复 attach 产出 {len(rows)} 行"
    assert rows[0]["lc_report_id"] == "lc-spot-2", "重跑应显式覆盖到最新一份，而不是留两条互相矛盾"


# ── G-09 / TC-13：runner 终态钩子按 kind + origin 过滤 ────────────


def _runner_hook_sites() -> list[str]:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in {"attach_spot_check", "maybe_attach_spot_check"}:
                sites.append(f"runner.py:{node.lineno}")
    return sites


def test_runner_has_no_spot_check_hook_yet():
    """**现状记录**：runner 终态不感知地标体检 ⇒ 侧表只能靠调用方记得写（必漏）。"""
    assert _runner_hook_sites() == [], (
        f"runner 已挂钩子 {(_runner_hook_sites())} ⇒ 改为正向断言，"
        "并补 refine/brief 不误触的端到端用例"
    )


@pytest.mark.xfail(
    strict=True,
    reason="D3：终态钩子必须在 runner（kind 无关的真接缝）按 kind+origin 双条件过滤触发",
)
def test_runner_terminal_state_writes_the_side_table():
    assert _runner_hook_sites(), "runner 终态未调用侧表写入口"
    src = RUNNER.read_text(encoding="utf-8")
    # 过滤条件必须显式存在：origin 决定"这是地标体检"，kind 决定"别把 refine/brief 卷进来"
    assert "origin" in src and "kind" in src, "钩子缺少 kind+origin 双条件过滤"


# ── 片 1b / TC-16 · TC-16b：串行锁与额度透出 ─────────────────────


def test_tasks_endpoint_currently_accepts_repeated_spot_launches():
    """**现状记录**：同一景点连发两次会得到两个任务（串行锁要堵的口子）。

    这正是串行锁要堵的口子：`baidu_daily_quota` 保持 0 时日预算永不触发（D6），
    账号级配额唯一的硬门就是"同一攻略内一次只允许一个在途地标体检"。

    载荷只用**已声明键**：片 0b 之后 `CreateTaskBody` 开了 `extra="forbid"`，
    带 `scenario`/`origin` 的载荷会先被 422 挡掉（见下一条），就不再是"两个任务"
    这个事实的证人。
    """
    payload = {
        "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
        "center": [106.7123, 26.5786], "data_mode": "fixture",
    }
    first = client.post("/api/tasks", json=payload)
    second = client.post("/api/tasks", json=payload)
    assert first.status_code == 200 and second.status_code == 200, (
        "串行锁已生效 ⇒ 本用例改为正向断言（第二次被拒且**不创建任务**）"
    )
    assert first.json()["taskId"] != second.json()["taskId"], "两次请求必须今天确实产了两个任务（前提事实）"


def test_spot_launch_keys_are_refused_until_the_backend_declares_them():
    """片 0b 的**新前置条件**：地标体检要带的 `scenario`/`origin` 现在会被 422 拒。

    forbid 之前这两个键是"发了也没人收"（静默丢弃）；现在是"发就报错"。
    ⇒ 片 2 的前端发起动作必须等 `CreateTaskBody` 先声明这两个字段，否则用户点一下
    就拿到 422。把这条钉在这里，是为了让"加字段"发生在"前端开始发"之前。
    """
    for key in ("scenario", "origin"):
        resp = client.post("/api/tasks", json={
            "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
            "center": [106.7123, 26.5786], "data_mode": "fixture",
            key: "visitor" if key == "scenario" else {"host_report_id": "r-guide-1"},
        })
        assert resp.status_code == 422, f"{key} 未被拒绝，forbid 是否失效：{resp.status_code}"
        types = {e.get("type") for e in resp.json()["detail"]}
        assert "extra_forbidden" in types, f"{key} 的 422 不是因为未声明：{sorted(types)}"


@pytest.mark.xfail(
    strict=True,
    reason="片 1b：同攻略在途时第二次地标体检必须被拒，且不创建任务（不消耗配额）",
)
def test_serial_lock_rejects_the_second_launch_without_creating_a_task():
    before = {
        r[0] for r in db._connect().execute("SELECT task_id FROM tasks").fetchall()
    }
    payload = {
        "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
        "center": [106.7123, 26.5786], "data_mode": "fixture",
        "scenario": "visitor", "origin": {"host_report_id": "r-lock", "spot_id": "spot-甲秀楼"},
    }
    first = client.post("/api/tasks", json=payload)
    assert first.status_code == 200
    second = client.post("/api/tasks", json=payload)
    assert second.status_code == 409, f"第二次发起未被拒（{second.status_code}）"
    after = {r[0] for r in db._connect().execute("SELECT task_id FROM tasks").fetchall()}
    assert after == before | {first.json()["taskId"]}, "拒绝却仍然建了任务 ⇒ 白耗一次编排与配额"


@pytest.mark.xfail(
    strict=True,
    reason="片 1b：/usage 必须存在，且 cap=0 时不得显示任何『剩余额度』（无根据的数字违反 D6 诚实条款）",
)
def test_usage_endpoint_reports_launch_count_without_remaining():
    resp = client.get("/api/life-circle/usage")
    assert resp.status_code == 200, f"额度出口不存在（{resp.status_code}）"
    body = resp.json()
    assert "launched_today" in body, f"应透出今日已发起次数，实得 keys={sorted(body)}"
    forbidden = [k for k in body if any(w in k.lower() for w in ("remaining", "left", "surplus"))]
    assert not forbidden, f"cap=0 却报出剩余额度 {forbidden} —— 那串数字没有依据"
