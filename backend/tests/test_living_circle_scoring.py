"""生活圈评分的**盲区扣分**口径（`app/living_circle/scoring.py`）。

这个模块此前**没有任何单元测试** —— 只有装配/报告级用例间接读到 `scores["total"]`。
缺测的代价在本次缺陷里现形：扣分只按「判出的盲区条数」算，于是
**证据面越小 ⇒ 盲区越少 ⇒ 分越高**，评分函数在奖励它本该惩罚的缺口，
而没有任何一层会红。

守护的不变量：
- **外推**：扣分用 `blindspot_count / judged_share`（比率估计），不是条数。
- **下限**：`JUDGE_SHARE_FLOOR` 把放大倍数封顶在 5 —— 「判不了」是数据缺口，不是「全是盲区」。
- **上限钳制**：`judged_share > 1`（调用方 bug）只会让扣分**变少**，正是要防的方向，必须钳。
- **清单不伪造**：外推值只进 `scores.evidence`，**绝不**冒充实测盲区条数。
- **置信度**：判定面不完整或证据不完整 ⇒ `confidence == "limited"`。
- **向后兼容**：不传 `judged_share` 的既有调用者算术不变（但置信度不得自称 full）。
"""
import re

import pytest

from app.living_circle.scoring import (
    BLINDSPOT_PENALTY_CAP,
    JUDGE_SHARE_FLOOR,
    compute_scores,
)

TRIADS: list = []


def cats(coverage: float = 1.0) -> list:
    """四维满分附近的构造输入：让 `total` 的差异**只可能**来自盲区扣分。"""
    return [
        {"category": c, "label": c, "coverage": coverage, "in_circle": 5, "min_minutes": 6.0}
        for c in ("market", "pharmacy", "primary", "clinic", "supermarket")
    ]


def total_at(count: int, share=None, complete: bool = True) -> float:
    return compute_scores(cats(), TRIADS, count, judged_share=share, evidence_complete=complete)["total"]


def ev(count: int, share=None, complete: bool = True) -> dict:
    return compute_scores(cats(), TRIADS, count, judged_share=share, evidence_complete=complete)["evidence"]


# ── 1. 外推：低覆盖率必须付账 ─────────────────────────────────────
def test_full_coverage_penalty_uses_raw_count():
    """覆盖率 100% ⇒ 外推是恒等变换，扣分与旧口径逐分相同（这是回归基线，不是新行为）。"""
    e = ev(3, share=1.0)
    assert e["expected_blindspots"] == pytest.approx(3.0)
    assert e["penalty_applied"] == pytest.approx(min(BLINDSPOT_PENALTY_CAP, (3 - 1) * 4.0))


def test_thin_evidence_scores_lower_than_full_evidence_same_count():
    """同一实测条数，判定面越小 ⇒ 分越低。

    这条就是本次缺陷的反面：旧口径下 2 处盲区扣 4 分，无论那 2 处是从 5% 还是 100%
    的可达区里判出来的 —— 采集偷懒一分钱不付。
    """
    assert total_at(2, share=JUDGE_SHARE_FLOOR) < total_at(2, share=1.0)


def test_kaili_measured_case_penalty_hits_cap():
    """凯里实测形状（97 格判 5 格、2 处盲区）：share≈0.05 被下限钳到 0.2 ⇒ 外推 10 处 ⇒ 扣分封顶。

    钉住「下限生效」这一支：若有人把 `max(share, FLOOR)` 写成 `share`，此处会算出
    40 处外推然后照样封顶 12 分 —— 看起来没变，但 `expected_blindspots` 会跳到 40。
    """
    judged = 5 / 97
    e = ev(2, share=judged)
    assert e["penalty_applied"] == pytest.approx(BLINDSPOT_PENALTY_CAP)
    assert e["expected_blindspots"] == pytest.approx(2 / JUDGE_SHARE_FLOOR, abs=0.01)
    assert e["judged_share"] == pytest.approx(judged, abs=1e-4)


def test_amplification_is_capped_by_floor():
    """share→0 时放大倍数封顶 `1/FLOOR = 5`：数据缺口不得被外推成「整片都是盲区」。"""
    assert ev(4, share=0.0)["expected_blindspots"] == pytest.approx(4 / JUDGE_SHARE_FLOOR)


def test_penalty_under_cap_is_exactly_recomputable():
    """未触封顶时，扣分必须能由公式**逐位复算** —— 契约判据 B11 就是这么读的。"""
    share, count = 0.8, 3
    e = ev(count, share=share)
    expected = count / share
    assert e["penalty_applied"] == pytest.approx(
        min(BLINDSPOT_PENALTY_CAP, max(0.0, expected - 1.0) * 4.0), abs=1e-9
    )


# ── 2. 边界与非法方向 ────────────────────────────────────────────
def test_share_above_one_is_clamped_not_flattering():
    """覆盖率若因调用方 bug >1 ⇒ 不得让扣分变少（那是本缺陷的同向复发）。"""
    assert ev(4, share=1.5)["penalty_applied"] == pytest.approx(ev(4, share=1.0)["penalty_applied"])


def test_zero_blindspots_get_no_penalty_but_stay_low_confidence():
    """判不出盲区 ≠ 没有盲区：0 条时不扣分（比率估计放大 0 仍是 0），但置信度必须说 limited。

    「无判定能力」这件事交给 `confidence` + 报告 `caliber.cells_*` 表达，不靠伪造扣分。
    """
    out = compute_scores(cats(), TRIADS, 0, judged_share=0.05)
    assert out["evidence"]["penalty_applied"] == 0.0
    assert out["confidence"] == "limited"


def test_negative_count_does_not_raise_penalty():
    assert ev(-3, share=0.5)["penalty_applied"] == 0.0


def test_total_never_leaves_zero_to_hundred():
    assert 0.0 <= total_at(999, share=JUDGE_SHARE_FLOOR) <= 100.0


# ── 3. 置信度 ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "share,complete,expect",
    [
        (1.0, True, "full"),        # 判满且证据齐 ⇒ 唯一能给 full 的形状
        (0.99, True, "limited"),    # 有一格没判 ⇒ 不自称完整
        (1.0, False, "limited"),    # 判满了，但有词被截断/饿死 ⇒ 证据本身有缺口
        (0.2, True, "limited"),
        (None, True, "limited"),    # 覆盖率无从谈起 ⇒ 更不敢称完整
    ],
)
def test_confidence_matrix(share, complete, expect):
    assert compute_scores(cats(), TRIADS, 1, judged_share=share, evidence_complete=complete)["confidence"] == expect


# ── 4. 向后兼容与「不伪造清单」 ──────────────────────────────────
def test_legacy_positional_call_keeps_old_arithmetic():
    """既有位置参数调用者（`test_visitor_output_contract.py`、手搓脚本）算术不变。"""
    assert total_at(3) == total_at(3, share=1.0)


def test_extrapolated_count_never_masquerades_as_observed():
    """外推值只活在 `scores.evidence` 里 —— 盲区清单/`blindspot_count` 列的语义不变。"""
    out = compute_scores(cats(), TRIADS, 2, judged_share=0.25)
    assert out["evidence"]["expected_blindspots"] == pytest.approx(8.0)
    assert "blindspot_count" not in out, "评分层不得产出一个看起来像实测条数的键"
    assert "实测 2 处盲区" in out["note"] and "外推约 8.0 处" in out["note"]
    assert "盲区清单仍只列有据的那 2 处" in out["note"]
    # 偏置方向也要写在读者看得见的地方：未判面多在更稀疏的外沿 ⇒ 外推只会偏乐观
    assert "偏乐观" in out["note"]


def test_note_states_the_discount_basis():
    """扣分口径要在 note 里读得到，不能只躺在数值键（本仓既有纪律）。"""
    assert "扣分 12.0" in compute_scores(cats(), TRIADS, 2, judged_share=0.05)["note"]


def test_unreachable_categories_are_disclosed_not_silently_dropped():
    """`min_minutes is None` 的类别被踢出可达维度平均 ⇒ 分数**变好**，必须在 note 里可见。

    这不是假想：泄漏 A 修好前，「圈内 0 个」的养老类带着 19.9min 参与平均（拉低分）；
    修好后它不再参与 ⇒ 可达维度上升。若不说，读者会以为修 bug 把分修高了。
    """
    def _row(mm):
        return {"category": "elderly", "label": "养老", "coverage": 0.0,
                "in_circle": 0, "min_minutes": mm}

    before = compute_scores(cats() + [_row(19.9)], TRIADS, 0)["note"]   # 旧形状：越界点也参与
    after = compute_scores(cats() + [_row(None)], TRIADS, 0)["note"]    # 修好后：退出平均
    assert "1 类圈内无可达设施（养老）不计入可达维度" in after
    assert "不计入可达维度" not in before
    dim = lambda note: float(re.search(r"可达 ([\d.]+)", note).group(1))
    assert dim(after) > dim(before), "退出平均的是 0 分项，可达维度必须上升 —— 上升才需要披露"
