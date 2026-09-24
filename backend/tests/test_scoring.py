"""评分引擎（scoring.py）单元契约 —— TC-S01~S04（《测试覆盖方案》五 · INV-B/IN-E）。

守护的不变量：
- **可复现**：同一输入两次调用结果全等（无 random/time/网络，纯函数）。
- **LLM 无评分话语权**：分数、名次、归一化维度全部由本模块公式算出。
- **边界收敛**：负数/None/NaN/字符串/bool 等非法信号一律 sanitize 落界，不抛错；
  占比类（positive_ratio/value_score）收敛到 [0,1]，声量收敛到 [0,+inf)。
- **稳定序**：平局按归一化名称再按原序，rank 从 1 连续回填。

运行：backend/ 下 `pytest tests/test_scoring.py -q`
"""
import math

import pytest

from app.core import scoring as SC


def _row(name, mentions, pos, val, **extra):
    r = {"name": name, "signals": {"mentions": mentions, "positive_ratio": pos,
                                   "value_score": val}}
    r.update(extra)
    return r


# ── TC-S01 确定性 / 可复现 ───────────────────────────────
def test_same_input_identical_output():
    rows = [_row("大理古城", 30, 0.8, 0.7), _row("洱海", 22, 0.9, 0.6),
            _row("苍山", 22, 0.9, 0.6), _row("双廊", 5, 0.5, 0.9)]
    a = SC.rank_spots(rows, 4)
    b = SC.rank_spots(rows, 4)
    assert a == b, "同一输入两次调用必须逐项全等（可审计、可复现）"


def test_weight_constants_are_the_declared_formula():
    """榜单展示的公式（0.4×声量+0.4×口碑+0.2×性价比）必须与代码一致，改权重先改文案。"""
    assert (SC.WEIGHT_VOICE, SC.WEIGHT_SENTIMENT, SC.WEIGHT_VALUE) == (0.4, 0.4, 0.2)
    assert SC.WEIGHT_VOICE + SC.WEIGHT_SENTIMENT + SC.WEIGHT_VALUE == pytest.approx(1.0)


def test_score_is_weighted_sum_of_dims():
    out = SC.rank_spots([_row("A", 10, 0.5, 0.4), _row("B", 5, 0.9, 0.2)], 2)
    for r in out:
        d = r["dims"]
        expect = round(SC.WEIGHT_VOICE * d["voice"] + SC.WEIGHT_SENTIMENT * d["sentiment"]
                       + SC.WEIGHT_VALUE * d["value"], 1)
        assert r["score"] == pytest.approx(expect, abs=0.1)
        assert SC.SCORE_MIN <= r["score"] <= SC.SCORE_MAX


# ── TC-S02 信号等价类：非法输入一律落界，不抛 ──────────────
@pytest.mark.parametrize("mentions,pos,val,expect", [
    (None, None, None, {"voice": 0.0, "sentiment": 0.0, "value": 0.0}),
    (-10, -0.5, -1.0, {"voice": 0.0, "sentiment": 0.0, "value": 0.0}),      # 负数截 0
    (float("nan"), 2.5, 0.5, {"voice": 0.0, "sentiment": 1.0, "value": 0.5}),  # NaN→0；占比越界 clamp
    ("12", "0.8", "abc", {"voice": 12.0, "sentiment": 0.8, "value": 0.0}),  # 数字字符串收编，乱码→0
    (True, False, None, {"voice": 0.0, "sentiment": 0.0, "value": 0.0}),    # bool 视为非法
    ({"x": 1}, [1], "0.25", {"voice": 0.0, "sentiment": 0.0, "value": 0.25}),
])
def test_sanitize_signals_equivalence_classes(mentions, pos, val, expect):
    got = SC.sanitize_signals({"signals": {"mentions": mentions, "positive_ratio": pos,
                                           "value_score": val}})
    assert got == expect


def test_sanitize_accepts_flat_fields_and_nested():
    """LLM 常见漂移：字段挂在顶层而非 signals 子字典，也要抽到。"""
    nested = SC.sanitize_signals({"signals": {"mentions": 7, "positive_ratio": 0.5,
                                              "value_score": 0.5}})
    flat = SC.sanitize_signals({"mentions": 7, "positive_ratio": 0.5, "value_score": 0.5})
    assert nested == flat == {"voice": 7.0, "sentiment": 0.5, "value": 0.5}


def test_rank_spots_survives_junk_rows():
    out = SC.rank_spots([{"name": "坏行", "signals": "不是字典"},
                         _row("好行", 10, 0.9, 0.8)], 5)
    assert [r["name"] for r in out] == ["好行", "坏行"]
    assert out[1]["signals_clean"] == {"voice": 0.0, "sentiment": 0.0, "value": 0.0}
    assert not math.isnan(out[0]["score"])


# ── TC-S03 归一化边界 ────────────────────────────────────
def test_single_spot_gets_full_voice_dim():
    """榜内 max 缩放：唯一景点即满分声量（相对分语义，不是绝对分）。"""
    out = SC.rank_spots([_row("独苗", 3, 0.5, 0.5)], 4)
    assert out[0]["dims"]["voice"] == 100.0


def test_all_zero_voice_no_division_error():
    out = SC.rank_spots([_row("A", 0, 0.5, 0.5), _row("B", 0, 0.3, 0.2)], 4)
    assert all(r["dims"]["voice"] == 0.0 for r in out)
    assert out[0]["score"] > out[1]["score"]  # 口碑仍拉开差距


def test_empty_input_and_topn_edges():
    assert SC.rank_spots([], 4) == []
    assert SC.rank_spots([_row("A", 1, 1, 1)], 0) == []
    out = SC.rank_spots([_row("A", 1, 1, 1), _row("B", 1, 1, 1)], 99)
    assert len(out) == 2


def test_internal_bookkeeping_not_leaked():
    """_orig_idx 等中间键不得泄漏到冻结实体行（前端契约字段以外都是脏数据）。"""
    out = SC.rank_spots([_row("A", 1, 0.5, 0.5)], 4)
    assert "_orig_idx" not in out[0]


# ── TC-S04 排序与稳定名次 ────────────────────────────────
def test_descending_score_and_sequential_rank():
    rows = [_row("小景点", 1, 0.3, 0.3), _row("大热门", 100, 0.9, 0.9),
            _row("中不溜", 30, 0.6, 0.6)]
    out = SC.rank_spots(rows, 3)
    assert [r["rank"] for r in out] == [1, 2, 3]
    assert [r["name"] for r in out] == ["大热门", "中不溜", "小景点"]
    assert out[0]["score"] >= out[1]["score"] >= out[2]["score"]


def test_tie_break_is_stable_by_name_then_input_order():
    """平局：先按名称码位序（str 比较，非拼音），再按原始输入序——稳定才可复现。"""
    rows_a = [_row("乙", 10, 0.5, 0.5), _row("甲", 10, 0.5, 0.5), _row("甲", 10, 0.5, 0.5)]
    rows_b = [_row("甲", 10, 0.5, 0.5), _row("乙", 10, 0.5, 0.5), _row("甲", 10, 0.5, 0.5)]
    # "乙"(U+4E59) 码位小于 "甲"(U+7532)，同名平局再以原序定先后
    assert [r["name"] for r in SC.rank_spots(rows_a, 3)] == ["乙", "甲", "甲"]
    assert [r["name"] for r in SC.rank_spots(rows_b, 3)] == ["乙", "甲", "甲"], \
        "两乱序输入排出的榜必须一致"


def test_topn_truncation_keeps_head():
    rows = [_row(f"S{i}", 100 - i, 0.5, 0.5) for i in range(10)]
    out = SC.rank_spots(rows, 4)
    assert [r["name"] for r in out] == ["S0", "S1", "S2", "S3"]
    assert out[-1]["rank"] == 4


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
