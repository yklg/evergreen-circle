"""章节结构契约：守护「每章要么有结构、要么如实标注丢了结构」这一不变量。

背景（真实故障 r_f2cc14fd）：11 章里 9 章的写稿 JSON 被单章 token 上限截断，而
key_takeaway/highlights 排在输出契约**末尾** → 被砍掉的必然是导图依赖的字段；
失败后的纯文本重试又硬编码返回空结构；写稿阶段没有任何质量检查（质检跑在写稿之前）。
结果前端「本章内容结构」把 9 章全降级成一行正文计数，用户误以为存在两套渲染器。

钉住的不变量：
I1 结构字段必须排在输出契约最前（截断时先落盘）——提示词顺序断言；
I2 单章预算 ≤ 服务商输出上限 8192，且 deep 高于实测截断点 6000（防回退）；
I3 写稿诊断 `_diag` 绝不进报告 section（_section 逐字段白名单）；
I4 structure_status 四态映射正确，且「有材料却空结构」必须判 lost 而非 by_design；
I5 结构补齐只对「有正文、无结构」的章节发起（调用数 = 成本上界），且只喂正文不喂全量证据。

依赖注入点：orchestrator.chat_json / orchestrator.chat / orchestrator.last_finish_reason
（均为模块级 from-import 绑定）→ monkeypatch 假实现，不调真实 LLM。
运行：backend/ 下 `pytest tests/test_section_structure_contract.py -q`
"""
from app.core import orchestrator as O

# 服务商（api.deepseek.com）单次输出上限；预算超过它会被拒
PROVIDER_OUTPUT_CEILING = 8192
# 实测截断点：deep 模式原先的 6000 预算被推理 token 吃光（traces 里 completion_tokens 恰为 6000）
OBSERVED_TRUNCATION_POINT = 6000


def _capture(payload, holder):
    def _fake(messages, **kwargs):
        holder.append((messages, kwargs))
        return payload
    return _fake


def _write(monkeypatch, payload, holder, sid="transport"):
    monkeypatch.setattr(O, "chat_json", _capture(payload, holder))
    return O._write_single_section(
        sid, "一、交通与抵达", "上海玩三天", ["上海"], ["交通"],
        [], [], {}, "test-model", "guide", 5, "180-280",
        O.MODE_CONFIG["deep"]["section_max_tokens"],
    )


# ── I1 输出契约：结构在前 ────────────────────────────────
def test_output_contract_puts_structure_before_paragraphs(monkeypatch):
    holder = []
    st = _write(monkeypatch, {"key_takeaway": "只玩上海", "highlights": ["亮点1"], "paragraphs": ["段1"]}, holder)
    system = holder[0][0][0]["content"]
    assert system.index('"key_takeaway"') < system.index('"paragraphs"'), \
        "结构字段必须先于正文出现在输出契约里，否则截断时先丢的一定是结构"
    assert st["key_takeaway"] == "只玩上海"
    assert O._diag_of(st)["recovered"] == "json"


def test_truncated_json_falls_to_text_retry_and_is_marked(monkeypatch):
    """首次 chat_json 返回 None（截断不可解析）→ 纯文本重试；诊断标 text_retry + truncated。"""
    monkeypatch.setattr(O, "chat_json", lambda messages, **kw: None)
    monkeypatch.setattr(O, "chat", lambda messages, **kw: "第一段" + "内容" * 20 + "\n" + "第二段" + "内容" * 20)
    monkeypatch.setattr(O, "last_finish_reason", lambda: "length")
    st = O._write_single_section(
        "transport", "一、交通与抵达", "上海玩三天", ["上海"], ["交通"],
        [], [], {}, "test-model", "guide", 5, "180-280", 8000,
    )
    assert st["paragraphs"], "纯文本重试应拿到正文"
    assert st["key_takeaway"] == "" and st["highlights"] == [], "重试路径本就拿不到结构，交写后补齐"
    assert O._diag_of(st) == {"recovered": "text_retry", "truncated": True}


# ── I2 预算上界与防回退 ──────────────────────────────────
def test_section_budget_within_provider_ceiling():
    for mode, cfg in O.MODE_CONFIG.items():
        assert cfg["section_max_tokens"] <= PROVIDER_OUTPUT_CEILING, f"{mode} 超过服务商输出上限会被拒"


def test_deep_budget_exceeds_observed_truncation_point():
    """deep 是实际在用的档；预算必须高于实测截断点，否则同一故障必复发。"""
    assert O.MODE_CONFIG["deep"]["section_max_tokens"] > OBSERVED_TRUNCATION_POINT
    assert (O.MODE_CONFIG["quick"]["section_max_tokens"]
            < O.MODE_CONFIG["deep"]["section_max_tokens"]
            <= O.MODE_CONFIG["expert"]["section_max_tokens"]), "三档应保持递增"


# ── I3 诊断键不得泄漏 ────────────────────────────────────
def test_diag_never_leaks_into_report_section():
    sections_text = {
        "transport": {"paragraphs": ["段1", "段2"], "key_takeaway": "", "highlights": [],
                      O.DIAG_KEY: {"recovered": "text_retry", "truncated": True}},
    }
    report = O._assemble_report(
        "上海玩三天", ["上海"], ["交通"],
        {"members": [{"id": "L3-002"}], "lead": "L3-002"},
        [], [], [], {}, [], sections_text, [],
        {}, {}, {}, {}, [], "deep", ["transport"], None, {}, "guide",
    )
    sec = next(s for s in report["sections"] if s["id"] == "transport")
    assert O.DIAG_KEY not in sec, "内部诊断键不得落入报告 JSON"
    assert set(sec) == {
        "id", "title", "level", "key_takeaway", "highlights", "paragraphs", "claims",
        "charts", "source_evidence_ids", "structured", "data_grid", "structure_status",
        "score_gap",
    }
    assert sec["score_gap"] is None, "无缺口章节该键恒在且为 None（与 structure_status 正交）"


# ── I4 structure_status 四态映射 ─────────────────────────
def test_structure_status_mapping():
    diag_retry = {O.DIAG_KEY: {"recovered": "text_retry", "truncated": True}}
    diag_repair = {O.DIAG_KEY: {"recovered": "repaired"}}
    assert O._structure_status({"key_takeaway": "判断"}, True) == "ok"
    assert O._structure_status({"highlights": ["亮点"]}, False) == "ok"
    assert O._structure_status({"key_takeaway": "判断", **diag_repair}, True) == "repaired"
    assert O._structure_status({"paragraphs": ["p"], **diag_retry}, True) == "lost"
    assert O._structure_status({"paragraphs": ["p"], **diag_retry}, False) == "lost"
    assert O._structure_status({"paragraphs": ["p"]}, False) == "by_design"
    # 有材料却拿不到结构 = 可疑，必须判 lost（只看材料会被误判成 by_design，丢真相）
    assert O._structure_status({"paragraphs": ["p"]}, True) == "lost"


def test_summary_ledger_counts_states():
    secs = [{"id": "a", "structure_status": "ok"}, {"id": "b", "structure_status": "lost"},
            {"id": "c", "structure_status": "repaired"}, {"id": "d", "structure_status": "by_design"}]
    assert O._summarize_structure(secs) == {
        "total": 4, "ok": 1, "repaired": ["c"], "lost": ["b"], "by_design": 1,
    }


def test_assemble_report_carries_ledger_and_lost_status():
    sections_text = {
        "transport": {"paragraphs": ["段1"], "key_takeaway": "", "highlights": [],
                      O.DIAG_KEY: {"recovered": "text_retry", "truncated": True}},
    }
    report = O._assemble_report(
        "上海玩三天", ["上海"], ["交通"],
        {"members": [{"id": "L3-002"}], "lead": "L3-002"},
        [], [], [], {}, [], sections_text, [],
        {}, {}, {}, {}, [], "deep", ["transport"], None, {}, "guide",
    )
    assert report["structure_report"]["lost"] == ["transport"]
    assert report["structure_report"]["total"] == len(report["sections"])


# ── I5 补齐范围与成本上界 ────────────────────────────────
def test_structureless_predicate_only_targets_body_without_structure():
    assert O._structureless({"paragraphs": ["p"], "key_takeaway": "", "highlights": []}) is True
    assert O._structureless({"paragraphs": ["p"], "key_takeaway": "判断", "highlights": []}) is False
    assert O._structureless({"paragraphs": ["p"], "key_takeaway": "", "highlights": ["亮点"]}) is False
    assert O._structureless({"paragraphs": [], "key_takeaway": "", "highlights": []}) is False, \
        "无正文不该补结构（补了也无处可依）"
    assert O._structureless(None) is False


def test_repair_skips_llm_when_nothing_to_repair(monkeypatch):
    """成本上界：没有正文时不得发起任何 LLM 调用。"""
    calls = []
    monkeypatch.setattr(O, "chat_json", _capture({"key_takeaway": "x"}, calls))
    assert O._repair_missing_structure("transport", "一、交通与抵达",
                                       {"paragraphs": []}, [], "fast") is None
    assert calls == [], "无正文可提炼时不得调 LLM"


def test_repair_returns_patch_and_keeps_truncation_history(monkeypatch):
    calls = []
    monkeypatch.setattr(O, "chat_json", _capture(
        {"key_takeaway": "只有三天就别跨五地", "highlights": ["亮点1", "亮点2", "亮点3", "多余1", "多余2"]}, calls))
    st = {"paragraphs": ["段1", "段2"], "key_takeaway": "", "highlights": [],
          O.DIAG_KEY: {"recovered": "text_retry", "truncated": True}}
    patch = O._repair_missing_structure("transport", "一、交通与抵达", st, [], "fast")
    assert patch["key_takeaway"] == "只有三天就别跨五地"
    assert patch["highlights"] == ["亮点1", "亮点2", "亮点3"], "补齐最多 3 条亮点"
    assert O._diag_of(patch) == {"recovered": "repaired", "truncated": True}, \
        "补齐要保留「首轮曾被截断」的诊断历史"
    assert len(calls) == 1, "补齐只发一次请求"
    # 只喂本章正文，不重发全量证据摘要（省 token，也避免与既成正文漂移）
    user = calls[0][0][1]["content"]
    assert "段1" in user and "证据摘要" not in user


def test_repair_failure_stays_lost(monkeypatch):
    """补齐失败必须返回 None 由上层保持 lost（绝不静默假装成功）。"""
    monkeypatch.setattr(O, "chat_json", lambda messages, **kw: None)
    st = {"paragraphs": ["段1"], "key_takeaway": "", "highlights": []}
    assert O._repair_missing_structure("transport", "一、交通与抵达", st, [], "fast") is None
    assert O._structure_status(st, True) == "lost"
