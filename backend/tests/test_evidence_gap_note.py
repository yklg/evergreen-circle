"""片 R23-A（乙）·「没查过 / 没查全」那半句的判据。

报告写「门槛项不足 / 存在缺口」时有三种真成因，本刀负责后两种：
①采集停止线按点数先收手（片 1c-β 的 `_COV_STOP_LINE_NOTE`，本文件不重测）
②某词因预算**一次都没发起**（`caliber.evidence_starved_terms`）
③某词发了但**没查全**（`caliber.evidence_truncated_terms`）

矩阵（每格断的都是**将来上屏的那句话**，预期值是按规格手写的字面量，不是从实现里回抄的）：

| # | 输入 | 断言 |
|---|---|---|
| 1 | ②③同时命中 | 一句里并列，计数与词名都来自载荷 |
| 2 | 只有 ② | 只出「未发起」那半 |
| 3 | 只有 ③ | 只出「没查全」那半 |
| 4 | 词全属**别类** | 空串（全类混合表必须按 `{category}:` 筛，否则拿别类的账冒充本类结论） |
| 5 | 键缺席 / 空表 / 非列表 | 空串 —— 不印，也**不写「0 个」**（缺席=不知道，空表=查全了） |
| 6 | 达标分支（≥75%） | 整句不挂（达标说的是分子已计满，证据面不完整不会让它变假话） |
| 7 | 缺 `required_in_circle` | 正文照点数说，不挂门槛项文案 ⇒ 更没有这句 |

第 6/7 格测的是**分支真话**：同一份载荷换个覆盖度，那句话必须有/没有。
"""
from __future__ import annotations

from app.core.pipeline import diagnosis_templates as dt

MED_LABEL = "医疗"
EDU_LABEL = "教育"

CAL_BOTH = {
    "evidence_starved_terms": ["medical:社区医院", "medical:社区卫生服务中心", "education:小学"],
    "evidence_truncated_terms": ["medical:诊所", "shopping:超市"],
}
NOTE_BOTH = (
    "另需交代：本次有 2 个医疗类检索词因预算未发起（medical:社区医院、medical:社区卫生服务中心）、"
    "1 个医疗类检索词发了但没查全（medical:诊所）"
    " ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。"
)
CAL_STARVED_ONLY = {"evidence_starved_terms": ["medical:社区医院"]}
NOTE_STARVED_ONLY = (
    "另需交代：本次有 1 个医疗类检索词因预算未发起（medical:社区医院）"
    " ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。"
)
CAL_TRUNC_ONLY = {"evidence_truncated_terms": ["medical:诊所", "pharmacy:药店"]}
# ⚠️ 载荷里那条 `pharmacy:药店` 是**故意留的干扰项**：问的是 medical，它必须被筛掉 ⇒ 计数是 1 不是 2。
#    （首跑就是这条红：我原先按"两条都算"写预期，等于样本违反了自己刚定的筛类别规则。）
NOTE_TRUNC_ONLY = (
    "另需交代：本次有 1 个医疗类检索词发了但没查全（medical:诊所）"
    " ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。"
)


def _med(coverage: float = 1 / 3, req: int | None = 1, in_circle: int = 25) -> dict:
    return {
        "category": "medical", "label": MED_LABEL, "total": 48,
        "in_circle": in_circle, "coverage": coverage,
        "required_in_circle": req, "scored_as": ["社区卫生服务中心", "药店"],
    }


def _edu(coverage: float = 1 / 3, req: int | None = 1) -> dict:
    return {
        "category": "education", "label": EDU_LABEL, "total": 34,
        "in_circle": 15, "coverage": coverage,
        "required_in_circle": req, "scored_as": ["小学"],
    }


# ───────────────────────── 1–5：拼装本身 ─────────────────────────

def test_both_causes_render_as_one_clause_pair():
    assert dt._evidence_gap_note(CAL_BOTH, "medical", MED_LABEL) == NOTE_BOTH


def test_starved_only_renders_its_own_clause():
    assert dt._evidence_gap_note(CAL_STARVED_ONLY, "medical", MED_LABEL) == NOTE_STARVED_ONLY


def test_truncated_only_renders_its_own_clause():
    assert dt._evidence_gap_note(CAL_TRUNC_ONLY, "medical", MED_LABEL) == NOTE_TRUNC_ONLY


def test_other_category_terms_do_not_leak_into_this_note():
    """`evidence_*_terms` 是**全类混合表** ⇒ 不筛前缀就会把教育的账印到医疗节头上。"""
    only_edu = {"evidence_starved_terms": ["education:小学"], "evidence_truncated_terms": ["shopping:超市"]}
    assert dt._evidence_gap_note(only_edu, "medical", MED_LABEL) == ""
    # 反向对照：同一份载荷问教育，必须印得出来（否则上一条的"空串"是恒真）
    edu_note = dt._evidence_gap_note(only_edu, "education", EDU_LABEL)
    assert edu_note.startswith("另需交代：本次有 1 个教育类检索词因预算未发起（education:小学）"), edu_note


def test_absent_key_empty_list_and_non_list_all_print_nothing():
    """三种"无话可说"都必须返回空串 —— 尤其不许回落成「0 个」（缺席=不知道、空表=查全了）。"""
    assert dt._evidence_gap_note({}, "medical", MED_LABEL) == ""
    assert dt._evidence_gap_note(None, "medical", MED_LABEL) == ""
    assert dt._evidence_gap_note({"evidence_starved_terms": []}, "medical", MED_LABEL) == ""
    assert dt._evidence_gap_note({"evidence_truncated_terms": []}, "medical", MED_LABEL) == ""
    assert dt._evidence_gap_note({"evidence_starved_terms": None}, "medical", MED_LABEL) == ""
    assert dt._evidence_gap_note({"evidence_starved_terms": "medical:诊所"}, "medical", MED_LABEL) == ""


def test_prefix_filter_is_not_a_substring_match():
    """筛的是 `{category}:` 前缀。`primary` 里含 `med`? 不 —— 但要防的是 `medical_x:` 这类同头类别。"""
    lookalike = {"evidence_starved_terms": ["medical_x:诊所"]}
    assert dt._evidence_gap_note(lookalike, "medical", MED_LABEL) == ""


# ───────────────────────── 6–7：分支真话 ─────────────────────────

def test_medical_gap_branch_carries_the_note_and_keeps_the_stop_line_one():
    s = dt._med_cov_sentence(_med(), CAL_BOTH)
    assert "本节写「存在缺口」" in s
    assert "不排除是采集先停的手" in s          # 片 1c-β 那句仍在，且在前
    assert s.endswith(NOTE_BOTH), s[-120:]
    assert s.index("不排除是采集先停的手") < s.index(NOTE_BOTH)   # 顺序：停止线 → 未发起/没查全
    # 读感回归（落地看图才发现）：新句结尾原本又把前一句的「不能只读成「社区没有」。」重说了一遍
    # ⇒ 同段两遍。这条钉住"只许一遍"，谁把尾句加回重复措辞就会红。
    assert s.count("不能只读成「社区没有」") == 1, s[-200:]


def test_medical_passing_branch_never_says_we_missed_terms():
    """达标 = 分子已计满 ⇒ 证据面不完整不会让它变假话，硬加就是"达标了却说没查完"。"""
    s = dt._med_cov_sentence(_med(coverage=1.0, req=5), CAL_BOTH)
    assert "本节写「达标」" in s
    assert "因预算未发起" not in s and "没查全" not in s


def test_education_gate_is_explicit_because_that_section_has_no_branch():
    hit = dt._edu_cov_sentence(_edu(), CAL_BOTH)
    assert "因预算未发起（education:小学）" in hit, hit[-160:]
    assert "没查全" not in hit.split("因预算未发起")[0]     # 教育节只该看到教育自己的词
    miss = dt._edu_cov_sentence(_edu(coverage=1.0, req=5), CAL_BOTH)
    assert "因预算未发起" not in miss and "没查全" not in miss


def test_legacy_snapshot_without_numerator_key_prints_neither_note():
    """`required_in_circle` 缺席 = 门槛项口径之前的快照 ⇒ 正文没有"门槛项不足"那句话，
    挂一句"「门槛项不足」里含…"就是引用一个屏上不存在的说法。"""
    cal = {"evidence_starved_terms": ["medical:社区医院"]}
    assert dt._med_cov_sentence(_med(req=None), cal) == "覆盖度 33% 按圈内点数计（这份快照出自门槛项口径之前）。"
    assert dt._edu_cov_sentence(_edu(req=None), cal) == "覆盖度 33% 按圈内点数计（这份快照出自门槛项口径之前）。"


# ───────────────────────── 8：两份演示夹具今天都不该印 ─────────────────────────

def test_shipped_fixtures_still_print_nothing():
    """夹具读数没变 ⇒ 落地当天演示报告正文与今天逐字相同（这半是回归网，不是新行为）。

    凯里件：`caliber` 里两个键都没有；劲松件：starved 是空表、truncated 有 7 词但医疗/教育覆盖度都 100%。
    """
    import json
    from pathlib import Path

    fx = Path(__file__).resolve().parents[2] / "frontend" / "src" / "mocks" / "fixtures" / "livingCircle"
    for name in ("kaili.json", "beijing-jinsong.json"):
        lc = json.loads((fx / name).read_text(encoding="utf-8"))
        cal = lc.get("caliber") or {}
        for cat in lc["poi"]["categories"]:
            if cat["category"] not in ("medical", "education"):
                continue
            note = dt._evidence_gap_note(cal, cat["category"], str(cat.get("label") or ""))
            if cat["category"] == "medical":
                s = dt._med_cov_sentence(cat, cal)
            else:
                s = dt._edu_cov_sentence(cat, cal)
            assert note == "" or cat["coverage"] >= 0.75, (name, cat["category"], note)
            assert "因预算未发起" not in s and "发了但没查全" not in s, (name, cat["category"], s[-160:])
