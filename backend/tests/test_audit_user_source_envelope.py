"""返工分流的 target 命名空间隔离（实施计划 v3 §九 · TC-36 + 哨兵目的地转正）。

为什么这条必须现在就有
--------------------
`app/core/audit.py:290-345` 的 `decide_rework()` 按 **issue.target 的字符串前缀**硬分流：

    target.startswith("destination:")        → 打回 collect 补采（audit.py:300-310）
    target.startswith("dimension:") / =="schema" → 打回 analyze 重分析（audit.py:313-323）
    qr.single_source_ratio > 阈值            → 按**目的地**补采独立信源组（audit.py:326-343）

计划 v3 §二 B5 要新增 `user_source_coverage` 维度。若它的 issue 沿用 `destination:` 前缀，
就会被这条链读成「某目的地证据不足」，向 collect 发出**补采一个不存在之目的地**的 REWORK：
空转、烧预算、流水线变长，而**没有任何一条现有测试会因此变红**。
本文件把这件事变成会变的灯。

期望值来源
----------
前缀集合与阈值来自 `audit.py` 实测（本文件用 AST 读回 `decide_rework` 里的字面量，
不靠记忆抄），阈值 `SINGLE_SOURCE_REWORK_RATIO` 直接 import 生产常量（audit.py:76）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.core.db as db
from app.core import audit
from app.core.audit import QualityReport, decide_rework
from app.core.models import Evidence

_APP_AUDIT = Path(audit.__file__)


def _issue(target: str) -> dict:
    """issue 的字典形状取自 audit.py:340-342 的组装格式。"""
    return {"target": target, "severity": "medium", "reason": "测试构造", "raised_by": "L3-003"}


def _ev(dest: str, group: str, i: int) -> Evidence:
    return Evidence(
        evidence_id=f"e_{i:03d}", source_url=f"https://s{i}.example.org/x",
        source_type="web", title=f"t{i}", excerpt=f"x{i}",
        captured_at="2026-01-01T00:00:00Z", credibility=50.0, collected_by="collect",
        image_urls=[], republished_from="", destination=dest, source_group=group,
    )


# ── TC-36 本体：user_source: 前缀不得进入任何返工桶 ─────────────────────


def test_user_source_issue_produces_no_rework_envelope():
    """新维度的 issue 只作诊断，不得触发补采/重分析。

    今天就能绿（`user_source:` 不匹配任何分流前缀）。它的价值在于**将来**有人
    扩展 decide_rework 的分流、或给新维度误用 `destination:` 前缀时，这里会红。
    """
    qr = QualityReport(issues=[_issue("user_source:e_024")])

    envelopes = decide_rework(qr, evidences=[])

    receivers = {e.receiver for e in envelopes}
    assert "collect" not in receivers, (
        f"user_source: 的 issue 竟被分流到 collect：{[e.payload for e in envelopes]}"
    )
    assert "analyze" not in receivers, "user_source: 不得被当成维度缺失打回 analyze"


def test_destination_issue_does_reach_the_recollect_bucket():
    """反证配对：证明上面那条不是因为「返工桶根本是死的」才绿。

    没有这条，`test_user_source_issue_produces_no_rework_envelope` 可能只是
    在测一个永远不产出 envelope 的废函数 —— 典型的恒绿假护栏。
    """
    qr = QualityReport(issues=[_issue("destination:大理")])

    envelopes = decide_rework(qr, evidences=[])

    collect_envs = [e for e in envelopes if e.receiver == "collect"]
    assert collect_envs, "destination: 前缀没打回 collect ⇒ decide_rework 的分流形状已变，本文件要重读"
    assert collect_envs[0].payload["destinations"] == ["大理"]


# ── 哨兵目的地：B2 已定死「落空串」，这里钉的是它的下游后果 ──────────────
#
# 转正记录（计划 §十.4 的 B2 决策项）：本例生成时是 `xfail(strict=True)`，钉的是
# 「B2 若选 `"*"` 哨兵，`audit.py:328` 的集合推导只滤空串、会把哨兵当真目的地发回 collect
# 补采」这个可执行后果。B2 落地时选定 **destination 落空串**（`collect_user_sources`），
# 于是判据从"哨兵会不会被误当目的地"改写为更硬的一条：**真实直抓产出的证据走一遍
# decide_rework，补采 payload 里既不该有哨兵、也不该有空目的地**。
# 期望值来源：`audit.py:328`（`{e.destination for e in evidences if e.destination}`）
# 与 `collect_user_sources` 的 destination-less 约定（§一 A-2）。
def test_user_source_evidences_produce_no_recollect_destination(monkeypatch):
    """用户信源入池后，单源超阈的补采请求里不能出现它的目的地值。

    反证配对在 `test_destination_issue_does_reach_the_recollect_bucket`：
    那条证明 collect 桶本身是活的，这条证明用户信源不会把空串/哨兵塞进去。
    """
    from app.core import fetcher, trace
    from app.core.pipeline.research import collect

    task = "t-envelope-b2"
    url = "https://province.gov.cn/bulletin"
    db.add_user_source(task, url, url, 0)
    body = "全省便民生活圈建设推进会召开，部署试点任务与验收标准。" * 4
    monkeypatch.setattr(fetcher, "fetch_page",
                        lambda u, *, fallback_snippet="": {
                            "url": u, "text": body, "images": [], "og_image": "",
                            "title": "全省推进会", "ok": True, "degraded": False,
                            "captured_at": "2026-09-01T00:00:00Z"})

    res = collect.collect_user_sources(task, "全省生活圈政策调研", "L1-025", [], set())
    trace.drain(task)                      # 清掉进程内 span 缓冲，别污染别的用例
    assert res["evidences"], "直抓没产出证据 ⇒ 下面对 decide_rework 的断言是空转"

    evs = res["evidences"] + [_ev("大理", "g1", 1), _ev("大理", "g1", 2)]
    qr = QualityReport(issues=[], single_source_ratio=audit.SINGLE_SOURCE_REWORK_RATIO + 0.1)
    collect_envs = [e for e in decide_rework(qr, evidences=evs) if e.receiver == "collect"]
    assert collect_envs, "单源超阈没发出补采请求 ⇒ 本例判据空转，先确认 decide_rework 形状没变"
    for e in collect_envs:
        # 空串会被 :328 的集合推导滤掉；哨兵滤不掉 —— 两者都不该出现在 payload 里
        assert "*" not in e.payload["destinations"], (
            f"哨兵被当成目的地发去补采：{e.payload}")
        assert "" not in e.payload["destinations"], (
            f"用户信源的目的地以空串形态漏进补采 payload：{e.payload}")
        assert e.payload["destinations"] == ["大理"], (
            f"补采目的地被用户信源改写：{e.payload}")


# ── 结构性防线：分流前缀必须是显式登记的小集合 ──────────────────────────


def _dispatch_literals_in_decide_rework() -> set:
    """AST 读回 `decide_rework` 里用于 target 分流的字符串字面量。

    只收两类：`x.startswith("…")` 的实参，以及 `x == "…"` 的比较右值。
    其它字符串（payload 里的中文理由、Envelope 的 sender 等）不属于分流判据。
    """
    tree = ast.parse(_APP_AUDIT.read_text(encoding="utf-8"))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "decide_rework"), None)
    assert fn is not None, "decide_rework 不叫这个名了 ⇒ 本守卫空转，先重读 audit.py"

    found: set = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"):
            found.update(a.value for a in node.args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str))
        elif isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq):
            found.update(op.value for op in node.comparators
                         if isinstance(op, ast.Constant) and isinstance(op.value, str))
    return found


def test_rework_dispatch_target_vocabulary_is_a_pinned_small_set():
    """返工分流认的 target 词汇集合被钉住；扩桶必须是一次**看得见意图**的改动。

    这正是计划 §二 B5 那条硬约束的守卫形式：新维度只能落在这些前缀之外。
    若有人在此登记了 `user_source:` 并接上返工动作，本例会红并逼人重新评估
    「用户信源未引用」到底该不该触发补采（计划待确认 2 已选：不阻断）。
    """
    found = _dispatch_literals_in_decide_rework()
    pinned = {"destination:", "dimension:", "schema"}

    assert found == pinned, (
        f"decide_rework 的 target 分流词汇与登记不符：新增 {sorted(found - pinned)} / "
        f"缺失 {sorted(pinned - found)}。扩桶前必须确认 user_source: 不会被卷进补采。"
    )


def test_new_dimension_prefix_is_outside_every_dispatch_bucket():
    """前缀不冲突的直接断言：`user_source:` 不以任一在册分流前缀开头。"""
    for prefix in {"destination:", "dimension:"}:
        assert not "user_source:".startswith(prefix)
    assert "user_source:e_1" != "schema"
