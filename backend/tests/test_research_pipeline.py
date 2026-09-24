"""T-08 特征测试：flip 后新旅游引擎的 SSE 骨架 vs 融合前旧引擎冻结骨架。

融合三跳（M1 树合并 → M2-flip 单一行为切换 → M3 模块提取）完成后，本测试把
「旧竞品引擎在真机跑出的事件/节点/报告键骨架」（fixtures/legacy_research_skeleton.json，
flip 前录制）与今天的新 research 引擎（全量 mock、零网络）逐项对比，钉死：

1. **前端旧契约不塌**：旧骨架的 7 类事件在新引擎全部仍会发出；终态仍是
   report_ready → done{reportId}，无 error；首帧仍是 node_update(idle)。
2. **新增事件类型封闭可审**：新引擎只允许多出 chart/image/trace（error 为异常终态，
   旧骨架 happy path 本来就不含）；team/spots/plan_fallback 是 message 的 kind，
   不是新 type——任何未在此登记的 type 出现即红（防 SSE 契约静默膨胀）。
3. **DAG 节点演进而非断裂**：旧 7 节点中 sentiment 节点显式退役（舆情收编为
   collect 阶段 + 独立舆情章），analyze/spots 为新增；guide 档实际推进的节点集
   == collect.DAG_NODES 注册表（节点登记与发射同源，不许多发/漏发）。
4. **报告契约换轴有清单**：旧报告键分三类冻结——
   - 保留键（22）必须仍在（前端旧读路径不塌）；
   - 退役键（7：brands/confidence/kind/plan/purpose/report_type/type）必须消失，
     竞品轴与双类型别名不得回潮（读层归一在 db._LEGACY_REPORT_KEYS 另守）；
   - 新轴键（7：destinations/research_type/structured/answers_digest/
     structure_report/methodology/contradictions）必须在。

做法：复用 test_two_type_pipeline 的全量假外部依赖（chat_json/multi_search/
fetch_page/百度缺 AK），guide 与 assessment 两类型各跑一遍 quick 档。
运行：backend/ 下 `pytest tests/test_research_pipeline.py -q`
"""
import json
from pathlib import Path

import pytest

from app.core.pipeline.research.collect import DAG_NODES
from test_two_type_pipeline import _install_fakes, _run_pipeline

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "legacy_research_skeleton.json"
LEGACY = json.loads(_FIXTURE.read_text(encoding="utf-8"))

# 旧骨架 7 类事件（done/evidence/message/node_update/progress/report_ready/thought）
LEGACY_EVENT_TYPES = set(LEGACY["event_type_set"])
# flip 后允许的新增 type（闭集；error 是异常终态，happy path 不发，登记只为解释）。
# 注意：team 降级/spots 阶段/plan_fallback 均以 message+kind 表达，不在此列。
ADDED_EVENT_TYPES = {"chart", "image", "trace", "error"}

# 旧 DAG 节点：sentiment 显式退役（舆情不再独占节点，收编 collect + 独立报告章）；
# 其余 6 个必须仍在，analyze/spots 为新引擎新增（guide 档可见）。
LEGACY_NODES = set(LEGACY["node_ids"])
RETIRED_NODES = {"sentiment"}
RETAINED_NODES = LEGACY_NODES - RETIRED_NODES
ADDED_NODES = {"analyze", "spots"}

# 旧报告键（30）→ flip 契约三分类
LEGACY_REPORT_KEYS = set(LEGACY["report_top_level_keys"])
REMOVED_REPORT_KEYS = {
    "brands",        # 竞品轴 → destinations（db 读层另做 brands→destinations 归一）
    "confidence",    # 报告级总置信退役；置信只留在 claim 级
    "kind", "purpose", "report_type", "type",  # 双类型/引擎别名 → research_type 单键
    "plan",          # 旧引擎计划快照，新引擎过程经 thought/trace 对外
}
NEW_REPORT_KEYS = {
    "destinations", "research_type", "structured", "answers_digest",
    "structure_report", "methodology", "contradictions",
}
RETAINED_REPORT_KEYS = LEGACY_REPORT_KEYS - REMOVED_REPORT_KEYS


def _emitted_types(evs) -> set:
    return {e["type"] for e in evs}


def _emitted_node_ids(evs) -> set:
    ids = set()
    for e in evs:
        if e["type"] != "node_update":
            continue
        d = e["data"]
        if isinstance(d.get("nodes"), list):
            ids.update(n["id"] for n in d["nodes"] if isinstance(n, dict))
        if d.get("node"):
            ids.add(d["node"])
    return ids


@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_legacy_event_types_all_still_emitted(monkeypatch, rtype):
    """旧骨架事件集是新引擎事件集的子集——前端既有消费分支不会断供。"""
    _install_fakes(monkeypatch)
    _, evs, _ = _run_pipeline(rtype)

    actual = _emitted_types(evs)
    missing = LEGACY_EVENT_TYPES - actual
    assert not missing, f"新引擎缺发旧契约事件：{sorted(missing)}"


@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_new_event_types_are_a_registered_closed_set(monkeypatch, rtype):
    """新增事件类型封闭：实际类型必须 ⊆ 旧集 ∪ 登记新增；未登记 type 出现即红。"""
    _install_fakes(monkeypatch)
    _, evs, _ = _run_pipeline(rtype)

    allowed = LEGACY_EVENT_TYPES | ADDED_EVENT_TYPES
    unknown = _emitted_types(evs) - allowed
    assert not unknown, (
        f"出现未登记的新 SSE 事件类型 {sorted(unknown)}："
        "若是刻意新增，须同步本测试闭集 + types.ts/taskStore/mock 三处真相")
    # happy path 不允许异常终态
    assert "error" not in _emitted_types(evs)


@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_terminal_skeleton_matches_legacy(monkeypatch, rtype):
    """首帧 node_update(idle)；report_ready 先于 done；done 携 reportId 且与落库一致。"""
    _install_fakes(monkeypatch)
    _, evs, report = _run_pipeline(rtype)

    assert evs[0]["type"] == "node_update"
    assert all(n.get("status") == "idle" for n in evs[0]["data"]["nodes"])

    types = [e["type"] for e in evs]
    assert types[-1] == "done"
    assert types.index("report_ready") < types.index("done")
    assert LEGACY["terminal_events"] == ["done"]

    done_ev = evs[-1]["data"]
    ready_ev = next(e["data"] for e in evs if e["type"] == "report_ready")
    assert done_ev["reportId"] == ready_ev["reportId"] == report["id"]

    # percent 单调不减且收口 100（旧骨架 progress 语义不漂移）
    percents = [e["data"]["percent"] for e in evs if e["type"] == "progress"]
    assert percents == sorted(percents) and percents[-1] == 100


def test_dag_nodes_evolved_by_registered_diff(monkeypatch):
    """guide 档节点集 == DAG_NODES 注册表；相对旧骨架仅 sentiment 退役、analyze/spots 新增。"""
    _install_fakes(monkeypatch)
    _, evs, _ = _run_pipeline("guide")

    actual = _emitted_node_ids(evs)
    assert actual == {n["id"] for n in DAG_NODES}, "管线发射节点必须与 DAG_NODES 注册表一致"
    assert RETAINED_NODES <= actual, f"旧节点丢失：{sorted(RETAINED_NODES - actual)}"
    assert not (RETIRED_NODES & actual), "sentiment 节点已退役，不得回潮"
    assert ADDED_NODES <= actual, f"新引擎应新增 analyze/spots 节点：{sorted(ADDED_NODES - actual)}"
    # 断言与旧骨架的显式对账（三集合恰好瓜分差异，防夹具被悄悄改动）
    assert LEGACY_NODES == RETAINED_NODES | RETIRED_NODES
    assert {n["id"] for n in DAG_NODES} == RETAINED_NODES | ADDED_NODES


@pytest.mark.parametrize("rtype", ["guide", "assessment"])
def test_report_keys_flip_contract_three_way_classification(monkeypatch, rtype):
    """落库报告键：22 保留键仍在、7 竞品/别名键消失、7 新轴键齐备。"""
    _install_fakes(monkeypatch)
    _, _, report = _run_pipeline(rtype)
    keys = set(report.keys())

    missing = RETAINED_REPORT_KEYS - keys
    assert not missing, f"旧契约报告键丢失（前端旧读路径会塌）：{sorted(missing)}"

    resurrected = REMOVED_REPORT_KEYS & keys
    assert not resurrected, f"竞品轴/旧别名报告键回潮：{sorted(resurrected)}"

    absent_new = NEW_REPORT_KEYS - keys
    assert not absent_new, f"新轴报告键缺失：{sorted(absent_new)}"

    # 三分类恰好覆盖旧骨架全集，且新旧键不重叠（夹具与契约同步漂移时此处即红）
    assert (RETAINED_REPORT_KEYS | REMOVED_REPORT_KEYS) == LEGACY_REPORT_KEYS
    assert not (NEW_REPORT_KEYS & LEGACY_REPORT_KEYS)
