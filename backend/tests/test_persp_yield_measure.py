"""批次 0 前置测度（v4 前置条件 1+2）：核查表**格级**产出率 + 装配现场的四态终止原因。

要治的第一个病：`schema_completeness` 是**块级**的（`_has_content` 只判「任一子列表非空」），
而核查表按行守恒、每列必出一格，没采到的格子填「待核验（本次未采到）」——**一张全空的表
在块级是满分**。实测报告 `r_6dadffee` 即活证据：块级 1.0，格级 verified 只有 7/28=0.25。
⇒ 「亲子链路到底跑通没有」这个问题在旧测度下**算不出来**（v3 判据不可计算 ⇒ v4 补）。

要治的第二个病：`_fill_persp_blocks` 的 `except Exception: payload = {}` 把四种异质失败压成
同一个产物 —— LLM 抛错 / 返回 None / 真没采到证据 / 反造数守卫全拒，四者的载荷长得一模一样。
⇒ 必须由装配现场交出 `llm_outcome`，且门槛写成**条件式**：`probed_spots == 0 ∨
llm_outcome != ok` ⇒ 判「环境未就绪」，**不得**据此否掉整行配置（否则一次 provider 欠费
就把「视角没填表」和「今天没网」混成同一次返工）。

判据纪律：每条测度都配「共同红灯 + 各自独有红灯」的负样本对（只测一半会得到恒红或恒绿的假护栏）。
"""
import copy

from app.core import llm
from app.core import research_types as RT
from app.core import schemas as SC
from app.core.audit import evaluate_quality
from app.core.pipeline.research import perspective as P

_DEST = "大理"
_CLAR = {"child_age": "3-6岁"}
_PSID = "persp_family"
_CK = RT.perspective_spec(_PSID)["checklist_key"]
_COLS = tuple(RT.perspective_spec(_PSID)["checklist_columns"])
_SPOTS = [{"spot_id": f"s{i}", "name": f"景点{i}"} for i in range(1, 4)]
_EVID = [type("E", (), {"evidence_id": f"e{i}", "excerpt": f"原文{i}"})() for i in range(1, 4)]
_PROBES = {s["spot_id"]: [f"e{k}"] for k, s in enumerate(_SPOTS, start=1)}


def _rows_payload(hollow: bool) -> dict:
    """两种**形状相同、内容不同**的载荷。cells 是 LLM 侧形状（按列名索引的字典）；
    装配后落库的是列表（每格带 column 字段），两套形状由 `_fill_persp_blocks` 负责翻译。

    hollow=True：每格都声称 verified，但引用不出真实证据 id ⇒ 反造数守卫会全量降级。
    hollow=False：每行只有第 1 列真采到，其余列**省略**（守卫契约：没证据就省略，别造）。
    """
    def cells():
        for col in _COLS:
            if hollow:
                yield col, {"text": "看着有内容", "evidence_ids": ["e_不存在"], "verified": True}
            elif col == _COLS[0]:
                yield col, {"text": "1.2 米以下免票", "evidence_ids": ["e1"], "verified": True}
    return {"rows": [{"spot_id": s["spot_id"], "cells": dict(cells())} for s in _SPOTS],
            "rules": [], "packing": []}


def _fill(monkeypatch, payload, *, finish="", boom=False):
    """跑一次真实装配，返回 (blocks, diag)。`finish` 只作用于本次调用的终止原因。"""
    def chat(*a, **k):
        if boom:
            raise RuntimeError("服务商 5xx")
        return payload
    monkeypatch.setattr(llm, "chat_json", chat)
    monkeypatch.setattr(llm, "last_finish_reason", lambda: finish)
    return P._fill_persp_blocks(_PSID, _DEST, _SPOTS, _PROBES, _EVID, _CLAR, "m", "t_probe")


# ── 测度 1：格级比例看得见块级看不见的事 ──────────────────────

def test_cell_ratio_separates_evidence_from_all_placeholder(monkeypatch):
    """同一形状、两种内容 ⇒ 块级同分、格级必须分开（这条就是 v4「算不出来」的正身）。"""
    good, _ = _fill(monkeypatch, _rows_payload(hollow=False))
    hollow, _ = _fill(monkeypatch, _rows_payload(hollow=True))
    assert SC.schema_completeness(good, "guide", _PSID) == \
        SC.schema_completeness(hollow, "guide", _PSID), \
        "前提：块级对两者同分（否则本用例没在证它盲）"
    g = SC.persp_cell_stats(good, _PSID)
    h = SC.persp_cell_stats(hollow, _PSID)
    assert (g["verified"], g["cells"]) == (3, 3 * len(_COLS))
    assert h["verified"] == 0, "全占位表格级必须归零 —— 这正是块级看不见的那件事"


def test_expected_cells_equals_cells_while_row_contract_holds(monkeypatch):
    """`expected_cells`（行×注册表列）与实到格数相等 ⇒ 形状未漂移，比值分母可信。"""
    blocks, _ = _fill(monkeypatch, _rows_payload(hollow=False))
    s = SC.persp_cell_stats(blocks, _PSID)
    assert s["cells"] == s["expected_cells"] == len(_SPOTS) * len(_COLS)


def test_verified_numerator_shares_the_anti_fabrication_verdict(monkeypatch):
    """分子与装配现场的反造数守卫**同判据**：verified 但引用不出真实 eid 的格不算数。"""
    blocks, _ = _fill(monkeypatch, _rows_payload(hollow=True))
    cells = [c for row in blocks[_CK][0]["items"] for c in row["cells"]]
    assert all(not c["verified"] for c in cells), "守卫应把伪 verified 全量降级"
    assert SC.persp_cell_stats(blocks, _PSID)["verified"] == 0


def test_stats_reject_pseudo_verified_cells_in_a_stored_payload():
    """守卫之外的入口也要判得对：**存量载荷里已经躺着** `verified: True` 却没有证据 id 的格。

    ⚠️ 这条是被变异测试逼出来的（第一轮只测上一条，把「守卫降级」误当成了「分子判据」在防，
    实测删掉 `persp_cell_stats` 的 eids 条件时全绿 —— 空覆盖）。纯读测度守的是**落库之后**的
    数据：旧构建的守卫判据可能不同、报告可被外部导入，所以它必须自带同一判据而不是信任上游。

    作用域边界说清楚：这里只判「有没有挂上 evidence_ids」，**不判**该 id 是否还在证据表里 ——
    那是装配现场的反造数守卫的职责（它手上有 `ev_ids`，本函数只有 structured）。
    """
    def cell(col, ver, eids):
        return {"column": col, "text": "1.2 米以下免票", "evidence_ids": eids, "verified": ver}
    st = {_CK: [{"destination": _DEST, "items": [
        {"spot_id": "s1", "cells": [cell(_COLS[0], True, ["e1"]),    # 唯一的真格
                                    cell(_COLS[1], True, []),        # 伪 verified：没证据
                                    cell(_COLS[2], False, ["e2"]),   # 有证据但没声称
                                    cell(_COLS[3], False, [])]}]}]}  # 占位格
    s = SC.persp_cell_stats(st, _PSID)
    assert (s["rows"], s["cells"], s["verified"]) == (1, 4, 1)
    assert s["expected_cells"] == len(_COLS)


# ── 测度 2：四种失败压不扁 ────────────────────────────────────

def test_four_compressed_failures_stay_apart(monkeypatch):
    """共同红灯（格级全 0）+ 各自独有红灯（outcome / payload_rows 两两不同）。"""
    _, err = _fill(monkeypatch, None, boom=True)
    _, none = _fill(monkeypatch, None)
    _, trunc = _fill(monkeypatch, {"rows": []}, finish="length")
    guarded_b, guarded = _fill(monkeypatch, _rows_payload(hollow=True))

    assert err["llm_outcome"] == "error"
    assert none["llm_outcome"] == "empty"
    assert trunc["llm_outcome"] == "truncated"
    assert guarded["llm_outcome"] == "ok", "守卫全拒不是模型故障：它答了，只是引用不出证据"
    assert (err["payload_rows"], none["payload_rows"], guarded["payload_rows"]) == (0, 0, 3)
    # 光看载荷分不出「模型没答」与「答了但全被拒」——台账分得出，这正是 v3 缺的那三个数
    assert SC.persp_cell_stats(guarded_b, _PSID)["verified"] == 0


def test_degraded_terminal_still_emits_placeholder_rows(monkeypatch):
    """测度只是**并列记账**，不得改变降级产出形状（占位可见即正确终态，同 spot_routes 哲学）。"""
    for boom, payload, finish in ((True, None, ""), (False, None, ""),
                                  (False, {"rows": []}, "length")):
        blocks, _ = _fill(monkeypatch, payload, finish=finish, boom=boom)
        assert len(blocks[_CK][0]["items"]) == len(_SPOTS)


def test_skipped_when_no_capability_or_no_rows(monkeypatch):
    """未配能力的视角 / 零 seed 的视角：不调模型，台账记 skipped 且 probed_spots 照实。"""
    out, diag = P._fill_persp_blocks("persp_couple", _DEST, _SPOTS, {}, _EVID, _CLAR, "m")
    assert (out, diag["llm_outcome"], diag["probed_spots"]) == ({}, "skipped", len(_SPOTS))
    _, diag0 = _fill(monkeypatch, _rows_payload(hollow=False))
    assert diag0["spots_with_evidence"] == len(_SPOTS)
    _, diag_none = P._fill_persp_blocks(_PSID, _DEST, [], _PROBES, _EVID, _CLAR, "m")
    assert diag_none["probed_spots"] == 0


# ── 门槛谓词本身：条件式，不是绝对式 ──────────────────────────

def _not_ready(diag) -> bool:
    """批次 0 / B2 的实际判据（写在这里以便被测试钉住，而不是散在文档里）。"""
    return diag["probed_spots"] == 0 or diag["llm_outcome"] != "ok"


def test_gate_is_conditional_so_env_outage_cannot_kill_a_row(monkeypatch):
    """一次 provider 欠费不得被读成「这行配置不行」——两条判据各管一件事。"""
    _, env_down = _fill(monkeypatch, None, boom=True)
    assert _not_ready(env_down), "LLM 抛错 ⇒ 判环境未就绪（不得否掉该行）"

    blocks, answered = _fill(monkeypatch, _rows_payload(hollow=True))
    assert not _not_ready(answered), "模型正常应答但守卫全拒 ⇒ 是产出问题，不是环境问题"
    assert SC.persp_cell_stats(blocks, _PSID)["verified"] == 0, "而它照样过不了产出率门槛"

    assert _not_ready(dict(answered, probed_spots=0)), "零景点 seed ⇒ 判环境未就绪"


# ── 测度 3：落库通路（缺键 ≠ 值为 0）──────────────────────────

def test_quality_dict_carries_all_three(monkeypatch):
    """三个数必须经 `to_dict()` 落库：`quality_before/after` 是手写枚举的产物，
    不进 to_dict 就等于门槛事后读到的是「键不存在」，而不是一个可判的 0。"""
    blocks, diag = _fill(monkeypatch, _rows_payload(hollow=False))
    qr = evaluate_quality([_DEST], ["overview"], [], list(_EVID), blocks,
                          research_type="guide", perspective_section_id=_PSID,
                          persp_llm_outcome=diag["llm_outcome"])
    d = qr.to_dict()
    for k in ("persp_verified_ratio", "persp_probed_spots", "persp_llm_outcome"):
        assert k in d, f"{k} 没进 to_dict ⇒ 落库静默缺该指标"
    assert d["persp_llm_outcome"] == "ok"
    assert d["persp_probed_spots"] == len(_SPOTS)
    assert d["persp_verified_ratio"] == round(1 / len(_COLS), 3)
    assert "persp_verified_ratio" in qr.summary(), "返工卡片看不到格级改善就没法解释「已改善」"


def test_non_perspective_volume_keeps_defaults(monkeypatch):
    """非视角卷：三个数取默认值、仍进 to_dict，且得分/分母逐值不受影响（P0-1 同族防线）。"""
    base = {"spot_ranking": [{"destination": _DEST, "items": [{"name": "洱海"}]}]}
    qr = evaluate_quality([_DEST], ["overview"], [], list(_EVID), base, research_type="guide")
    d = qr.to_dict()
    assert (d["persp_verified_ratio"], d["persp_probed_spots"], d["persp_llm_outcome"]) == \
        (0.0, 0, "")
    assert "persp_verified_ratio" not in qr.summary(), \
        "非视角卷凭空多两个 0 会被读成「测了且为零」而非「没测」"
    assert qr.schema_completeness == SC.schema_completeness(base, "guide")


def test_cell_stats_is_pure_and_total_on_stored_payloads(monkeypatch):
    """门槛要能回看存量报告：比例与格数必须**只从 structured** 算得出（纯函数、幂等、缺键为 0）。"""
    blocks, _ = _fill(monkeypatch, _rows_payload(hollow=False))
    frozen = copy.deepcopy(blocks)
    assert SC.persp_cell_stats(frozen, _PSID) == SC.persp_cell_stats(frozen, _PSID)
    assert SC.persp_cell_stats({}, _PSID)["cells"] == 0
    assert SC.persp_cell_stats(frozen, "") == {"rows": 0, "cells": 0, "expected_cells": 0,
                                               "verified": 0, "rules": 0, "packing": 0}


def test_measure_is_registry_driven_for_future_rows():
    """测度按注册表取键与列，不得把视角键名写死 ⇒ B1 填了新行就自动可测。"""
    for sid in RT.PERSPECTIVE_SPECS:
        s = SC.persp_cell_stats({}, sid)
        assert set(s) == {"rows", "cells", "expected_cells", "verified", "rules", "packing"}
