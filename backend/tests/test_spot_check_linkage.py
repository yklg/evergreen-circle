"""地标体检的发起、关联与场景隔离（附录 G-08 / G-09 / G-10 / G-11，第一片 D3 / D4 / D10 / 片 1b，
TC-10 / TC-13 / TC-14 / TC-16 / TC-16b）。

地标闭环把「一份攻略」和「一份体检报告」绑在一起，于是冒出四类接缝。本文件按
「先记实现、再登记缺口」两两成对写法：每对里绿的那条钉住真相，`xfail(strict)` 那条
钉住必须长出来的东西 —— 落地后若忘了摘标记会直接报 XPASS。

## 现状（片 1 落地后，2026-10-11）

* `report_spot_checks` 侧表、`db.attach_spot_check()` / `maybe_attach_spot_check()`、
  runner 终态钩子、`GET /api/life-circle/{report_id}/spot-checks` **已落地**；
  原来钉"不存在"的两条现状条已转成**正向判据**（`test_side_table_and_writer_exist` /
  `test_runner_terminal_state_is_the_only_hook_site`），D3 / D4 两条红钉已摘标。
* 仍**未**落地、继续挂在 xfail 里的三件：D10 的 compare 跨场景 422、片 1b 的串行锁、
  片 1b 的 `/api/life-circle/usage`。
* 列表接口仍不透出 `scenario`（本期只透 `origin` 来源）；`GET /api/life-circle/compare`
  对场景仍无感 ⇒ 在 D10 落地前，跨场景配对仍是**默认行为**而非边缘情况。
* `baidu_daily_quota` 默认 0（＝不约束）⇒ 硬门只能做在**串行锁**上。

## 末节那组「侧表性质判据」

T-02 / T-03 / T-04 / T-05 / T-10 钉的是侧表**自身**必须成立的性质（唯一索引真挡重、
写入口是真 upsert 而不是 `INSERT OR REPLACE`、并发只留一行、来源不存在不许落库、
删任一侧都断关联）。它们与上面那些"闭环长什么样"的用例互补，动 `db.attach_spot_check`
或删除路径时先看这一组。
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


def test_side_table_and_writer_exist():
    """**正向判据**（原为现状条 D3，片 1 落地后转正）：侧表与写入口都在。"""
    assert hasattr(db, "attach_spot_check"), "侧表写入口不见了"
    assert hasattr(db, "maybe_attach_spot_check"), "生产入口不见了"
    tables = {
        r[0] for r in db._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "report_spot_checks" in tables, "侧表没建出来"


def test_spot_check_attach_is_idempotent_per_spot_and_scenario():
    """连点同一景点三次 ⇒ 侧表仍一行；换场景才允许新行；重复写不得产生脏数据。

    （原为 `xfail(strict=True)` 的 D4 红钉，片 1 落地后摘标转正。）
    """
    key = {"host_report_id": "r-guide-1", "host_kind": "guide", "spot_id": "spot-甲秀楼", "scenario": "visitor"}
    db.attach_spot_check(lc_report_id="lc-spot-1", **key, snapshot={}, captured_at="2026-09-26T00:00:00")
    db.attach_spot_check(lc_report_id="lc-spot-2", **key, snapshot={}, captured_at="2026-09-26T00:05:00")
    db.attach_spot_check(lc_report_id="lc-spot-3", **key, snapshot={}, captured_at="2026-09-26T00:10:00")
    rows = db.list_spot_checks(**key)
    assert len(rows) == 1, f"重复 attach 产出 {len(rows)} 行"
    assert rows[0]["lc_report_id"] == "lc-spot-3", "重跑应显式覆盖到最新一份，而不是留两条互相矛盾"

    # 换场景（口径档）才允许第二行 —— 这条同时钉住"scenario 在幂等键里"这件事
    other = {**key, "scenario": "visitor-alt"}
    db.attach_spot_check(lc_report_id="lc-spot-9", **other, snapshot={}, captured_at="2026-09-26T00:15:00")
    assert len(db.list_spot_checks(host_report_id="r-guide-1", spot_id="spot-甲秀楼")) == 2


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


def test_runner_terminal_state_is_the_only_hook_site():
    """**正向判据**（原为现状条，片 1 落地后转正）：终态写点唯一。

    为什么要数"只有一处"：生活圈管线自己调了三处 `mark_task_done`，钩子若改挂进管线
    就会被抄成三份、迟早分叉；挂 runner 终态则天然只有一处。
    """
    sites = _runner_hook_sites()
    assert sites, "runner 终态没挂钩子 ⇒ 侧表只能靠调用方记得写（必漏）"
    assert len(sites) == 1, f"钩子被挂到了 {sites} —— 终态写点应当唯一"


def _hook_guard_expressions() -> list[str]:
    """取出"包住侧表写入口的那个 if 条件表达式"的源码串（供双条件判据用）。"""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        called = {
            getattr(c.func, "attr", None) or getattr(c.func, "id", None)
            for c in ast.walk(node)
            if isinstance(c, ast.Call)
        }
        if called & {"attach_spot_check", "maybe_attach_spot_check"}:
            guards.append(ast.unparse(node.test))
    return guards


def test_runner_terminal_state_writes_the_side_table():
    """（原为 `xfail(strict=True)` 的 D3 红钉，片 1 落地后摘标转正。）

    ⚠️ 判据从"整文件里找得到 `origin` 与 `kind` 两个词"升级成**取那个 if 的条件表达式**：
    整文件子串判据无牙 —— 别的分支里随便出现这两个词它就绿，把 `if origin:` 单独留下、
    删掉 `kind` 那一半也照样绿。现在缺任一半即红。
    """
    assert _runner_hook_sites(), "runner 终态未调用侧表写入口"
    guards = _hook_guard_expressions()
    assert guards, "侧表写入口没有被任何 if 包住 ⇒ 无条件写（refine/brief/调研任务都会被卷进来）"
    joined = " ".join(guards)
    assert "kind" in joined, f"钩子缺 kind 条件 ⇒ refine/brief 等非体检任务会被误触：{guards}"
    assert "origin" in joined, f"钩子缺 origin 条件 ⇒ 任何体检任务都会被当成地标体检：{guards}"


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
    """片 0b 的前置条件，**片 1 之后只剩 `scenario` 这一半**。

    `origin` 已在片 1 声明并被下面那条转正用例覆盖；`scenario`（口径档）仍未声明 ——
    流水线还不读它，发一个兑现不了的标签比不发更坏（片 0 修掉的 `sample_profile` 就是那个形状）。
    ⇒ D1/D2/D9 那一批落地时，`CreateTaskBody` 先声明 `scenario`，前端才可以开始发。
    """
    for key in ("scenario",):
        resp = client.post("/api/tasks", json={
            "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
            "center": [106.7123, 26.5786], "data_mode": "fixture",
            key: "visitor",
        })
        assert resp.status_code == 422, f"{key} 未被拒绝，forbid 是否失效：{resp.status_code}"
        types = {e.get("type") for e in resp.json()["detail"]}
        assert "extra_forbidden" in types, f"{key} 的 422 不是因为未声明：{sorted(types)}"


def test_origin_is_declared_and_accepted_with_a_forbidding_submodel():
    """片 1 转正：`origin` 已声明 ⇒ 带上它必须 200，且**原样落进** `tasks.clarifications`。

    三件事一起钉：① 键收下了；② 值是结构化三元组（不是被压成字符串）；③ 子模型同样
    `extra="forbid"` —— 客户端多塞一个 `snapshot` 要拿到 422 而不是被静默丢掉
    （快照由服务端按宿主报告自取，不能让客户端喂）。
    """
    resp = client.post("/api/tasks", json={
        "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
        "center": [106.7123, 26.5786], "data_mode": "fixture",
        "origin": {"host_kind": "guide", "host_report_id": "r-origin-1", "spot_id": "spot-甲秀楼"},
    })
    assert resp.status_code == 200, resp.text
    full = db.get_task_full(resp.json()["taskId"]) or {}
    assert (full.get("clarifications") or {}).get("origin") == {
        "host_kind": "guide", "host_report_id": "r-origin-1", "spot_id": "spot-甲秀楼",
    }, f"origin 没有原样落进载荷：{full.get('clarifications')}"

    extra = client.post("/api/tasks", json={
        "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
        "center": [106.7123, 26.5786], "data_mode": "fixture",
        "origin": {"host_kind": "guide", "host_report_id": "r-origin-2",
                   "spot_id": "spot-甲秀楼", "snapshot": {"injected": True}},
    })
    assert extra.status_code == 422, f"子模型没拦住客户端喂 snapshot：{extra.status_code}"
    assert "extra_forbidden" in {e.get("type") for e in extra.json()["detail"]}


@pytest.mark.xfail(
    strict=True,
    reason="片 1b：同攻略在途时第二次地标体检必须被拒，且不创建任务（不消耗配额）",
)
def test_serial_lock_rejects_the_second_launch_without_creating_a_task():
    before = {
        r[0] for r in db._connect().execute("SELECT task_id FROM tasks").fetchall()
    }
    # 载荷只带**已声明**键：`scenario` 本期未声明（片 1 只加 origin）⇒ 带上它先被 422 挡掉，
    # 那这条就不再是"两个任务"这个事实的证人，红的原因也会变成"422"而不是"没锁"（假挂账）。
    payload = {
        "query": "甲秀楼", "type": "living_circle", "city": "贵阳",
        "center": [106.7123, 26.5786], "data_mode": "fixture",
        "origin": {"host_report_id": "r-lock", "spot_id": "spot-甲秀楼"},
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


# ── P0 侧表性质红钉（测试覆盖评估 T-02 / T-03 / T-04 / T-05 / T-10）────────────
# 上面各条钉的是「地标体检这个闭环长什么样」；下面这一组钉的是**侧表自身必须成立的性质**。
# 五条在片 1 落地前一律 XFAIL(strict)：钉的是「长出来时必须成立」，不是「今天没有」
# ——后者由 :87 / :128 两条现状条负责。落地后逐条摘标转正向。


# ── 侧表性质判据（测试覆盖评估 T-02 / T-03 / T-04 / T-05 / T-10）────────────
# 上面各条钉的是「地标体检这个闭环长什么样」；下面这一组钉的是**侧表自身必须成立的性质**。
# 五条先以 XFAIL(strict) 进来（钉「长出来时必须成立」），片 1 落地当天**同笔摘标转正**。


def test_side_table_has_a_unique_index_over_the_idempotency_key():
    """T-02：索引不是"建了就完"：要能被 `sqlite_master` 读到，且真的把重复写入挡住。"""
    db.attach_spot_check(
        lc_report_id="lc-ux-1", host_kind="guide", host_report_id="r-ux",
        spot_id="spot-ux", scenario="residential", snapshot={},
        captured_at="2026-10-11T00:00:00",
    )
    indexes = db._connect().execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='report_spot_checks'"
    ).fetchall()
    unique = [r for r in indexes if r[1] and "UNIQUE" in r[1].upper()]
    assert unique, f"report_spot_checks 上没有 UNIQUE 索引：{indexes}"

    key = {"host_kind": "guide", "host_report_id": "r-ux", "spot_id": "spot-ux", "scenario": "residential"}
    db.attach_spot_check(lc_report_id="lc-ux-2", snapshot={}, captured_at="2026-10-11T00:01:00", **key)
    assert len(db.list_spot_checks(**key)) == 1, "同键两次写入产出了两行 ⇒ 唯一索引没起作用"


def test_side_table_writer_is_a_real_upsert():
    """T-03：SQLite 的 `INSERT OR REPLACE` 是**先删后插**，未在语句里给出的列会退回默认值；
    `DO NOTHING` 则让"重跑"静默保留旧行 ⇒ 最新一份的证据永远不上屏。两种都算假 upsert。

    ⚠️ 原本打算用"第二次只给部分字段，断言未给字段不被重置"来钉这件事，**已证伪**：
    `scenario` 本身就在幂等键里，少给它就等于换了一个键，落两行是**正确**行为，
    那样写的判据会因错误原因通过。故改成"源码形状 + 最新值胜出"两半。

    ⚠️ 源码那半**必须走 AST 取函数体**，不能按行剥 `#` 注释：这段 docstring 里就写着
    `INSERT OR REPLACE` 这几个字，按行剥法会把 docstring 一起搜进去 ⇒ 判据自己判自己红
    （同型教训见 `mapEventCoordGuard.test.ts` 的"剥掉块注释，本文件的判据就写在注释里"）。
    """
    tree = ast.parse((BACKEND_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "attach_spot_check"
    )
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # 摘掉 docstring，只留可执行语句
    code = ast.unparse(ast.Module(body=body, type_ignores=[])).upper()
    assert "ON CONFLICT" in code, "写入口没有 ON CONFLICT —— 不是 upsert"
    assert "INSERT OR REPLACE" not in code, "用了 INSERT OR REPLACE ⇒ 先删后插，未给的列会回退默认值"

    key = {"host_kind": "guide", "host_report_id": "r-up", "spot_id": "spot-up", "scenario": "residential"}
    db.attach_spot_check(lc_report_id="lc-up-1", snapshot={"v": 1}, captured_at="2026-10-11T00:00:00", **key)
    db.attach_spot_check(lc_report_id="lc-up-2", snapshot={"v": 2}, captured_at="2026-10-11T01:00:00", **key)
    row = db.list_spot_checks(**key)[0]
    assert row["lc_report_id"] == "lc-up-2", f"第二次写入没覆盖：{row}"
    assert row["captured_at"] == "2026-10-11T01:00:00", f"时效位没跟到最新：{row}"


def test_concurrent_attach_keeps_exactly_one_row():
    """T-04：照 `test_rate_limiter_shared.py:532-551` 的起跑闸范式：两线程在同一 Event 上等齐再同时写。

    ⚠️ **实测过：运行时这一半单独没有牙**（所以下面还有静态那一半）。原因在 `db._connect()`：
    它给每个线程一份自己的连接（`threading.local()`）且 `check_same_thread=False`，库又是 WAL +
    `busy_timeout=30000` ⇒ 去掉 `_LOCK` 之后两条线程依旧各自成功、结果仍是 1 行 —— 这条运行时
    判据分辨不出"有没有临界区"。它留下的价值是"并发写入不抛异常、不产第二行"这个冒烟事实；
    **真正钉住纪律的是静态半**：写入口必须把整段写在 `with _LOCK:` 里。
    """
    import threading

    key = {"host_kind": "guide", "host_report_id": "r-cc", "spot_id": "spot-cc", "scenario": "residential"}
    start = threading.Event()
    errors: list = []

    def worker(i: int) -> None:
        start.wait()
        try:
            db.attach_spot_check(
                lc_report_id=f"lc-cc-{i}", snapshot={}, captured_at="2026-10-11T00:00:00", **key
            )
        except Exception as exc:  # noqa: BLE001 —— 并发下任何异常都要被记下来当判据
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(2)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=5)
    assert not errors, f"并发写入抛异常：{errors}"
    assert len(db.list_spot_checks(**key)) == 1

    # 静态半：整段写操作必须在 `with _LOCK:` 里（与仓内其余 35 处同一纪律）
    tree = ast.parse((BACKEND_ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "attach_spot_check"
    )
    locked = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.With)
        and any(getattr(item.context_expr, "id", None) == "_LOCK" for item in n.items)
    ]
    assert locked, "写入口没有 `with _LOCK:` 把写操作圈起来（并发下会互相覆盖成半截账）"
    writes = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in {"execute", "executemany"}
    ]
    assert writes, "取不到写语句 ⇒ 判据已与实现脱节"
    for w in writes:
        assert any(
            w is node or any(w is inner for inner in ast.walk(node))
            for node in locked
        ), f"db.py:{w.lineno} 的写语句落在 `with _LOCK:` 之外"


def test_maybe_attach_refuses_an_unknown_host_report():
    """T-05：存在性校验只能落在**生产入口** `maybe_attach_spot_check` 上，不能落在裸写入口
    `attach_spot_check`：上面那条幂等用例（:104）直接用它、宿主报告 `r-guide-1` 并不存在
    ——把校验塞进裸写入口会当场把那条钉住语义的用例弄红。

    客户端填一个不存在的 `host_report_id`，删攻略时的级联就清不掉它，那行孤儿永久留在库里。
    """
    key = {"host_kind": "guide", "host_report_id": "r-ghost", "spot_id": "spot-ghost", "scenario": "residential"}
    db.save_task(
        "t-ghost", "甲秀楼",
        {"origin": {"host_kind": "guide", "host_report_id": "r-ghost", "spot_id": "spot-ghost"}},
        kind="living_circle",
    )
    db.maybe_attach_spot_check("t-ghost", "lc-ghost-report")
    assert db.list_spot_checks(**key) == [], "宿主报告不存在却写进了侧表 ⇒ 孤儿的来源"


def test_spot_checks_endpoint_returns_the_association_array():
    """片 1 的回读端点**真被调过**：返回数组、内容对得上、陌生 id 给空数组而不是 404。

    为什么单开一条：`test_api_surface_union` 只证明"路由在表里"，不证明它能应答；
    而攻略页的回读（片 2）就是靠这条端点 —— 一条从没被调用过的路由等于没有。
    """
    host = "r-endpoint-host"
    lc = _save("lc-endpoint-side")
    db.save_report({"id": host})
    key = {"host_kind": "guide", "host_report_id": host, "spot_id": "spot-endpoint", "scenario": "residential"}
    db.attach_spot_check(lc_report_id=lc, snapshot={}, captured_at="2026-10-11T00:00:00", **key)

    got = client.get(f"/api/life-circle/{lc}/spot-checks")
    assert got.status_code == 200, got.text
    checks = got.json()["checks"]
    assert [c["spot_id"] for c in checks] == ["spot-endpoint"]
    assert checks[0]["host_report_id"] == host
    assert checks[0]["snapshot"] == {}, "snapshot 必须是解开的 dict，不是 JSON 串"

    empty = client.get("/api/life-circle/lc-does-not-exist/spot-checks")
    assert empty.status_code == 200, "陌生报告 id 不该 404 —— 空数组才是常态"
    assert empty.json()["checks"] == []


def test_deleting_either_side_clears_the_association_only():
    """T-10：删攻略 ⇒ 关联行清、那份体检报告仍在；删体检报告 ⇒ 关联行清、攻略仍在。

    两个方向都要清，因为这条关联跨两张主表；只清一侧会留下永远点得进去的孤儿入口。
    """
    host = "r-cascade-host"
    lc = _save("lc-cascade-side")
    db.save_report({"id": host})
    key = {"host_kind": "guide", "host_report_id": host, "spot_id": "spot-cascade", "scenario": "residential"}
    db.attach_spot_check(lc_report_id=lc, snapshot={}, captured_at="2026-10-11T00:00:00", **key)
    assert len(db.list_spot_checks(**key)) == 1, "前提不成立：关联行没写进去"

    db.delete_report(host)
    assert db.list_spot_checks(**key) == [], "删了攻略却留着关联行"
    assert db.get_living_circle_report(lc) is not None, "删攻略把体检报告一起删了 —— 那不该发生"

    host2 = "r-cascade-host-2"
    lc2 = _save("lc-cascade-side-2")
    db.save_report({"id": host2})
    key2 = {"host_kind": "guide", "host_report_id": host2, "spot_id": "spot-cascade-2", "scenario": "residential"}
    db.attach_spot_check(lc_report_id=lc2, snapshot={}, captured_at="2026-10-11T00:00:00", **key2)
    db.delete_living_circle_report(lc2)
    assert db.list_spot_checks(**key2) == [], "删了体检报告却留着关联行"
    assert db.get_report(host2) is not None, "删体检报告把攻略一起删了 —— 那不该发生"
