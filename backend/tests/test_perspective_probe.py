"""rough-cliff-vole · 采集层契约钉（VR-C 组：槽位角度 + 逐景点二查 + 模式门控）。

守护契约：
  VR-C1 二查检索词含景点原名与模板关键词（证据归属的源头）
  VR-C2 单点失败隔离：失败景点记 failed、成功景点挂 id（行守恒的采集侧前提）
  VR-C3 服务商终态（配额/密钥）→ 中止剩余、quota_error 送达，不吞成 0 结果
  VR-C4 未配置视角/无配额模式 → 零搜索调用（零波及计数钉）
  VR-C6 并发在飞 ≤4
  槽位：视角槽位与 days/origin 同型占格、不被 max_angles 挤掉、不挤爆模型角度
"""
import asyncio

import pytest

from app.core import search
from app.core import llm
from app.core.pipeline.research import engine as O
from app.core.pipeline.research import planning
from app.core import research_types as rt
from app.core.search import SearchProviderError

_DEST = "大理"
_SPOTS = [{"spot_id": f"大理_spot_{i}", "name": n} for i, n in
          enumerate(["洱海", "大理古城", "喜洲古镇", "沙溪古镇",
                     "双廊镇", "周城", "崇圣寺三塔"], start=1)]
_TPLS = rt.PERSPECTIVE_SPECS["persp_family"]["spot_probe_tpls"]


def _mk_results(queries):
    return [{"url": f"https://example.com/{abs(hash(q)) % 10**8}",
             "title": q, "snippet": f"{q}：儿童免票线 1.2 米，母婴室在一楼",
             "captured_at": "2026-09-01"} for q in queries]


# ── VR-C1/C2 检索词与失败隔离 ───────────────────────────────────

def test_probe_queries_carry_spot_name_and_template(monkeypatch):
    """接缝 = `search.search`（逐探针各调一次），不再是 `multi_search`（合并池）。

    改判据的理由见 `test_probe_quota_is_per_template_not_shared_pool`：探针合并成一个池子
    会让先跑的探针吃掉全部槽位，所以供给侧改成了逐探针配额，测试接缝随之重指。
    """
    seen: list = []

    def fake_search(query, **kw):
        seen.append(query)
        return _mk_results([query])

    monkeypatch.setattr(search, "search", fake_search)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS[:2], _TPLS, "oneYear",
                                           set(), "L1-012", 7))
    assert len(seen) == 4  # 2 景点 × 2 模板
    assert any("洱海" in q and "儿童票" in q for q in seen)
    assert any("大理古城" in q and "母婴室" in q for q in seen)
    assert set(out["by_spot"]) == {"大理_spot_1", "大理_spot_2"}
    assert all(ids and all(i.startswith("e_") for i in ids)
               for ids in out["by_spot"].values())
    assert len(out["evidences"]) == 4


def test_probe_partial_failure_isolates_rows(monkeypatch):
    """7 中 2 失败：成功 5 个挂 id、失败 2 个记 failed——都不丢（装配层据此占位）。"""
    def fake_search(query, **kw):
        if "周城" in query or "崇圣寺" in query:
            return []  # 搜不到（非异常）
        return _mk_results([query])

    monkeypatch.setattr(search, "search", fake_search)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS, _TPLS, "oneYear",
                                           set(), "L1-012", 7))
    assert len(out["by_spot"]) == 5
    assert set(out["failed"]) == {"大理_spot_6", "大理_spot_7"}
    assert out["quota_error"] is None


def test_probe_dedupes_urls_across_spots(monkeypatch):
    """跨景点 URL 去重共用 seen_urls 池（同一条转载不得给两个景点当证据）。"""
    same = [{"url": "https://dup.com/x", "title": "t", "snippet": "s 儿童票 免票",
             "captured_at": ""}]
    monkeypatch.setattr(search, "search", lambda q, **kw: list(same))
    urls: set = set()
    out1 = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS[:1], _TPLS, "oneYear",
                                            urls, "L1-012", 7))
    out2 = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS[1:2], _TPLS, "oneYear",
                                            urls, "L1-012", 7))
    assert out1["evidences"] and not out2["evidences"]


def test_probe_quota_is_per_template_not_shared_pool(monkeypatch):
    """**本批改动的正身**：配额按探针分，先跑的探针不得把后面的挤出槽位。

    亲子实测的形状就是这条的反面：独占一条探针的「儿童票规则」命中 71%，而和别的词塞在
    同一条探针里的「母婴室」命中 0%。旧实现是 `multi_search` 合并成一个池子再截前 4 条
    ⇒ 探针 1 有 5 条结果时，探针 2 一条都进不来。列与探针 1:1 配对（4 列 4 探针）时，
    这个挤出效应会让**每一列的命中率取决于探针排列顺序**，而不是列本身有没有事实。
    """
    def rich_first(query, **kw):
        if "儿童票" in query:      # 探针 1：网络声音大
            return _mk_results([f"{query}#{i}" for i in range(5)])
        return _mk_results([query])  # 探针 2：只 1 条

    monkeypatch.setattr(search, "search", rich_first)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS[:1], _TPLS, "oneYear",
                                           set(), "L1-012", 7, per_tpl=2, per_spot=4))
    evs = out["evidences"]
    assert len(evs) == 3, f"应为 探针1 取 2 + 探针2 取 1，实得 {len(evs)}"
    from collections import Counter
    by_tpl = Counter("票规" if "儿童票" in e.title else "母婴" for e in evs)
    assert by_tpl["母婴"] == 1, f"后置探针被挤出了槽位：{dict(by_tpl)}"


def test_probe_transient_failure_skips_only_that_template(monkeypatch):
    """单条探针瞬时失败只跳过它：一条挂了不牵连同景点其余列（与 multi_search 逐条容错同判据）。

    ⚠️ 但服务商**终态**（配额/密钥）必须照冒泡中止整阶段 —— 两种失败的处理方向相反，
    把它们混成一个 except 就是「429 被当终态、核查表满屏占位」那次真机事故的形状。
    """
    def half_broken(query, **kw):
        if "母婴室" in query:
            raise RuntimeError("连接重置")
        return _mk_results([query])

    monkeypatch.setattr(search, "search", half_broken)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS[:1], _TPLS, "oneYear",
                                           set(), "L1-012", 7))
    assert out["evidences"] and out["quota_error"] is None
    assert out["by_spot"]["大理_spot_1"], "另一条探针的证据必须仍然挂上"


# ── VR-C3 服务商终态中止 ────────────────────────────────────────

def test_probe_quota_error_aborts_remaining(monkeypatch):
    calls: list = []

    def fake_search(query, **kw):
        calls.append(query)
        if "洱海" in query:
            raise SearchProviderError("quota exceeded")
        return _mk_results([query])

    monkeypatch.setattr(search, "search", fake_search)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS, _TPLS, "oneYear",
                                           set(), "L1-012", 7))
    assert out["quota_error"] and "quota" in out["quota_error"]
    # 只断言「确实少发了」：并发下具体放行几条取决于调度，写成紧数值就是条抖动的断言。
    # 「逐探针中止」本身由下面那条单线程用例精确钉住。
    assert len(calls) < len(_SPOTS) * len(_TPLS), (
        f"终态后仍把 7 景点 × 2 探针全发完（中止没生效）：{len(calls)} 次")


def test_one_probe_aborts_its_remaining_templates(monkeypatch):
    """单景点内：别的任务已判终态 ⇒ 本任务剩下的探针一条都不该再发。

    直测 `_probe_spot_perspective_one`（单线程、零调度噪声），因为阶段级用例里
    「放行了几条」是时序函数，只能断「< 全量」这种弱命题。4×4 之后每景点最多 4 条探针，
    没有这个检查点的代价从「多 1 次」变成「多 3 次 × 在途任务数」。
    """
    issued: list = []
    state = {"aborted": False}

    def fake_search(query, **kw):
        issued.append(query)
        state["aborted"] = True          # 第一条就把全局终态置起来
        return _mk_results([query])

    monkeypatch.setattr(search, "search", fake_search)
    evs = O._probe_spot_perspective_one(_DEST, "洱海", _TPLS, "oneYear", set(), "L1-012",
                                       per_tpl=2, per_spot=8,
                                       aborted=lambda: state["aborted"])
    assert len(issued) == 1, f"应在第一条后停下，实发 {len(issued)} 条：{issued}"
    assert evs, "已拿到的证据不因中止而丢弃"


# ── VR-C4 门控与零波及 ─────────────────────────────────────────

def test_probe_topn_zero_calls_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("probe_topn=0 不得发起任何搜索")

    monkeypatch.setattr(search, "search", boom)
    monkeypatch.setattr(search, "multi_search", boom)
    out = asyncio.run(O._probe_spot_perspective(_DEST, _SPOTS, _TPLS, "oneYear",
                                           set(), "L1-012", 0))
    assert out == {"by_spot": {}, "evidences": [], "failed": [], "quota_error": None}


def test_unconfigured_perspective_has_no_probe_tpls():
    """情侣/独行等未填表视角：spot_probe_tpls 空 → 调用点谓词天然跳过。"""
    for sid in ("persp_couple", "persp_solo", "persp_photo"):
        assert not rt.PERSPECTIVE_SPECS[sid]["spot_probe_tpls"]
        assert rt.PERSPECTIVE_SPECS[sid]["angle_tpls"] == ()


def test_mode_config_persp_quotas():
    """模式门控（评审 P0-3）：quick 零配额；deep/expert 槽位 2；deep max_angles 8。"""
    assert O.MODE_CONFIG["quick"]["persp_slots"] == 0
    assert O.MODE_CONFIG["quick"]["persp_probe_topn"] == 0
    assert O.MODE_CONFIG["deep"]["persp_slots"] == 2
    assert O.MODE_CONFIG["deep"]["max_angles"] == 8
    assert O.MODE_CONFIG["expert"]["max_angles"] == 11


# ── 槽位角度（与 days/origin 同型占格）──────────────────────────

def _angles(raw, **kw):
    spec = rt.type_spec("guide")
    return O._orthogonal_angles(raw, [_DEST], "", spec, kw.pop("max_angles", 8), **kw)


def test_slots_reserve_not_squeezed_out():
    raw = [f"角度{i}" for i in range(10)]
    slots = rt.PERSPECTIVE_SPECS["persp_family"]["angle_tpls"]
    got = _angles(raw, persp_angles=slots)
    for a in slots:
        assert a in got, "视角槽位必须占格（同 days/origin 契约）"
    # 模型角度不被挤爆：max_angles=8、无 days/origin、槽位 2 → 模型角度保留 6
    assert sum(1 for a in got if a.startswith("角度")) == 6


def test_slots_zero_when_mode_has_no_budget():
    got = _angles(["角度1", "角度2"], max_angles=4, persp_angles=())
    assert all("亲子" not in a for a in got)


def test_slot_angles_are_destination_orthogonal():
    """槽位模板不得含地名（采集层自动前缀目的地，重复地名污染证据归属）。"""
    for sid, p in rt.PERSPECTIVE_SPECS.items():
        for a in p["angle_tpls"]:
            assert not any(d in a for d in ("大理", "成都", "杭州"))


# ── _plan_research 接线 ────────────────────────────────────────

def test_plan_research_wires_slots_only_for_family(monkeypatch):
    captured: dict = {}

    def fake_chat(messages, **kw):
        return {"subject": "大理", "region": "云南省", "destinations": ["大理"],
                "focus": ["交通"], "search_angles": [f"角度{i}" for i in range(6)]}

    def fake_orth(raw, dests, days, spec, max_angles, origin="", fk=(), persp_angles=()):
        captured["persp"] = tuple(persp_angles)
        return list(raw)[:max_angles]

    monkeypatch.setattr(llm, "chat_json", fake_chat)
    monkeypatch.setattr(planning, "_orthogonal_angles", fake_orth)
    fam = {"party": "亲子家庭", "destinations": ["大理"], "_type": "guide"}
    O._plan_research("大理攻略", fam, 8, "guide", "", persp_slots=2)
    assert captured["persp"] == rt.PERSPECTIVE_SPECS["persp_family"]["angle_tpls"]
    O._plan_research("大理攻略", {"party": "情侣/夫妻", "destinations": ["大理"],
                                  "_type": "guide"}, 8, "guide", "", persp_slots=2)
    assert captured["persp"] == ()
    O._plan_research("大理攻略", fam, 4, "guide", "", persp_slots=0)
    assert captured["persp"] == (), "quick 档零配额：亲子答案也不占槽位"
