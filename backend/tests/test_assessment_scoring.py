"""评估类算分（scoring.py 扩展段）单元契约 —— 批次① T-06/T-07（对齐 test_scoring.py 范式）。

守护的不变量：
- **声明即公式**：权重与枚举映射是模块常量（SCORE_FORMULAS），图表文案、glossary
  与测试引用同一张表——改数值必须先改文案，违反即红。
- **可复现**：同一输入两次调用结果全等（无 random/time/网络，纯函数）。
- **降级契约**：任一维度输入不足 → 该维度/该方式/该行/整体**不出分**（None 或省略），
  绝不用假数据（0/估算）顶替；计数类（count_evidence_strength）例外——0 条证据本身
  就是可展示的事实，恒返回完整字典。
- **LLM 无评分话语权**：枚举（full/none、low/high…）→ 数值全部由本模块映射表折算。

运行：backend/ 下 `pytest tests/test_assessment_scoring.py -q`
"""
import pytest

from app.core import scoring as SC


def _claim(eids):
    return {"evidence_ids": list(eids)}


def _ev(eid, domain="", source_type="news"):
    return {"evidence_id": eid, "domain": domain, "source_type": source_type}


# ── TC-A01 weighted_score：通用加权入口 ──────────────────────
def test_weighted_score_is_declared_weighted_sum_with_breakdown():
    score, breakdown = SC.weighted_score({"a": 80.0, "b": 50.0}, {"a": 0.6, "b": 0.4})
    assert score == pytest.approx(68.0)
    assert breakdown["a"] == {"value": 80.0, "weight": 0.6, "contribution": 48.0}
    assert breakdown["b"] == {"value": 50.0, "weight": 0.4, "contribution": 20.0}


def test_weighted_score_skips_missing_or_illegal_dims():
    """缺维度/非法值不计分、不按 0 拉低、也不重归一——声明的公式就是公式。"""
    score, breakdown = SC.weighted_score(
        {"a": None, "b": "不是数字", "c": True, "d": 70.0},
        {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.5})
    assert set(breakdown) == {"d"}
    assert score == pytest.approx(35.0)


def test_weighted_score_all_illegal_returns_none():
    assert SC.weighted_score({}, {"a": 0.5}) == (None, {})
    assert SC.weighted_score({"a": None}, {"a": 0.5}) == (None, {})
    assert SC.weighted_score({"a": float("nan")}, {"a": 0.5}) == (None, {})


def test_weighted_score_clamps_values_to_score_domain():
    """越界值收敛到 [0,100]：负值截 0（沿用 _to_number 口径），>100 截 100。"""
    _, lo = SC.weighted_score({"a": -5}, {"a": 1.0})
    _, hi = SC.weighted_score({"a": 150}, {"a": 1.0})
    assert lo["a"]["value"] == 0.0
    assert hi["a"]["value"] == 100.0


# ── TC-A02 可达性：按交通方式拆解 ────────────────────────────
def _access_rows():
    return [
        {"destination": "大理", "routes": [
            {"mode": "高铁", "duration_minutes": 120, "cost_yuan": 400},
            {"mode": "自驾", "duration_minutes": 300, "cost_yuan": 600}]},
        {"destination": "丽江", "routes": [
            {"mode": "高铁", "duration_minutes": 240, "cost_yuan": 400},
            {"mode": "自驾", "duration_minutes": 150, "cost_yuan": 300}]},
    ]


def test_accessibility_mode_score_matches_hand_computed():
    """方式内报告相对分：min/x×100 折算时间/费用分，再按 0.6/0.4 加权。"""
    out = SC.score_accessibility(_access_rows())
    assert [r["destination"] for r in out] == ["大理", "丽江"]
    dali, lijiang = out[0], out[1]
    # 大理：高铁两维均为报告内最优 → 100；自驾 耗时 150/300、费用 300/600 各 50 分
    assert dali["modes"]["高铁"] == pytest.approx(100.0)
    assert dali["modes"]["自驾"] == pytest.approx(50.0)
    assert dali["score"] == pytest.approx(75.0)          # (100 + 50) / 2
    # 丽江：高铁 耗时 120/240 → 50、费用满分；自驾两维均最优
    assert lijiang["modes"]["高铁"] == pytest.approx(70.0)   # 0.6×50 + 0.4×100
    assert lijiang["modes"]["自驾"] == pytest.approx(100.0)
    assert lijiang["score"] == pytest.approx(85.0)
    # breakdown 带原始值供图内展开
    assert dali["breakdown"]["高铁"]["duration_minutes"] == 120
    assert dali["breakdown"]["高铁"]["dims"]["duration"]["weight"] == 0.6


def test_accessibility_weight_constants_are_the_declared_formula():
    """图表文案与 glossary 引用的权重必须与本模块常量一致（改权重先改文案）。"""
    assert (SC.WEIGHT_DURATION, SC.WEIGHT_COST) == (0.6, 0.4)
    assert SC.SCORE_FORMULAS["accessibility"] == {"duration": SC.WEIGHT_DURATION,
                                                  "cost": SC.WEIGHT_COST}
    assert sum(SC.SCORE_FORMULAS["accessibility"].values()) == pytest.approx(1.0)


def test_accessibility_solo_destination_gets_full_marks():
    """相对分语义（同 rank_spots 的榜内缩放）：报告内唯一路线即满分，不是绝对分。"""
    out = SC.score_accessibility([{"destination": "独苗", "routes": [
        {"mode": "大巴", "duration_minutes": 999, "cost_yuan": 8888}]}])
    assert out[0]["modes"]["大巴"] == 100.0
    assert out[0]["score"] == 100.0


def test_accessibility_same_mode_multiple_routes_takes_best_each():
    out = SC.score_accessibility([{"destination": "大理", "routes": [
        {"mode": "高铁", "duration_minutes": 300, "cost_yuan": 900},
        {"mode": "高铁", "duration_minutes": 180, "cost_yuan": 300}]}])
    assert out[0]["breakdown"]["高铁"]["duration_minutes"] == 180
    assert out[0]["breakdown"]["高铁"]["cost_yuan"] == 300


# ── TC-A03 可达性降级分支（T-07）────────────────────────────
def test_accessibility_skips_mode_missing_numeric_field():
    """T-07：缺 duration_minutes / cost_yuan 的方式整条跳过，不用假数据参与。"""
    rows = [{"destination": "大理", "routes": [
        {"mode": "高铁", "duration_minutes": 180},                     # 缺费用
        {"mode": "飞机", "cost_yuan": 900},                            # 缺耗时
        {"mode": "自驾", "duration_minutes": 240, "cost_yuan": 500},   # 齐全
        {"mode": "轮渡", "duration_minutes": "约 6 小时", "cost_yuan": 100},  # 脏值同缺
    ]}]
    out = SC.score_accessibility(rows)
    assert list(out[0]["modes"]) == ["自驾"], "缺数值字段的方式必须整条跳过"


def test_accessibility_destination_without_scorable_mode_is_omitted():
    rows = [{"destination": "缺数据城", "routes": [{"mode": "高铁", "duration": "3 小时"}]},
            {"destination": "有数据城", "routes": [
                {"mode": "高铁", "duration_minutes": 60, "cost_yuan": 100}]}]
    out = SC.score_accessibility(rows)
    assert [r["destination"] for r in out] == ["有数据城"]
    assert SC.score_accessibility([{"destination": "空城", "routes": []}]) == []
    assert SC.score_accessibility([]) == []


# ── TC-A04 配套覆盖度：枚举 → 覆盖率 ────────────────────────
def test_amenity_coverage_is_declared_mapping():
    out = SC.score_amenity_coverage([{"coverage": "full"}, {"coverage": "full"},
                                     {"coverage": "partial"}, {"coverage": "none"}])
    assert out == {"total": 4, "counts": {"full": 2, "partial": 1, "none": 1},
                   "coverage": 62.5}   # (2×1.0 + 0.5 + 0) / 4


def test_amenity_coverage_equivalence_classes():
    assert SC.score_amenity_coverage([]) is None
    assert SC.score_amenity_coverage(["脏行"]) is None
    assert SC.score_amenity_coverage([{"coverage": "FULL"}])["coverage"] == 100.0
    unknown = SC.score_amenity_coverage([{"coverage": "未知"}, {"item": "无字段"}])
    assert unknown["counts"] == {"full": 0, "partial": 2, "none": 0}, \
        "未知/缺失 coverage 按 partial 计（与 coerce_amenity_checklist 口径一致）"


def test_amenity_coverage_ratio_constants_pinned():
    assert SC.COVERAGE_RATIO == {"full": 1.0, "partial": 0.5, "none": 0.0}
    assert SC.SCORE_FORMULAS["amenity"] == SC.COVERAGE_RATIO


# ── TC-A05 风险画像：枚举 → 综合风险分 ──────────────────────
def test_risk_composite_is_equal_weighted_level_mean():
    out = SC.score_risk_level([{"dimension": "治安", "level": "high"},
                               {"dimension": "医疗应急", "level": "low"}])
    assert out["score"] == pytest.approx(50.0)          # (80 + 20) / 2
    assert out["level"] == "medium"
    assert out["counts"] == {"low": 1, "medium": 0, "high": 1}
    assert out["breakdown"]["治安"] == {"value": 80.0, "weight": 0.5,
                                        "contribution": 40.0, "level": "high"}
    assert out["breakdown"]["医疗应急"]["level"] == "low"


def test_risk_same_dimension_duplicates_averaged_first():
    out = SC.score_risk_level([{"dimension": "治安", "level": "high"},
                               {"dimension": "治安", "level": "low"}])
    assert out["score"] == pytest.approx(50.0)
    assert out["breakdown"]["治安"]["value"] == 50.0
    assert out["counts"]["high"] == 1 and out["counts"]["low"] == 1


def test_risk_level_band_and_enum_mapping_pinned():
    assert SC.RISK_LEVEL_SCORE == {"low": 20.0, "medium": 50.0, "high": 80.0}
    assert SC.SCORE_FORMULAS["risk"] == SC.RISK_LEVEL_SCORE
    assert SC.score_risk_level([{"dimension": "治安", "level": "low"}])["level"] == "low"
    assert SC.score_risk_level([{"dimension": "治安", "level": "medium"}])["level"] == "medium"
    assert SC.score_risk_level([{"dimension": "治安", "level": "high"}])["level"] == "high"


def test_risk_equivalence_classes():
    assert SC.score_risk_level([]) is None
    assert SC.score_risk_level([{"level": "high"}]) is None, "无 dimension 的条目忽略"
    assert SC.score_risk_level(["脏行"]) is None
    out = SC.score_risk_level([{"dimension": "治安", "level": "警告"}])
    assert out["counts"]["medium"] == 1, "未知 level 按 medium（与 coerce_risk_profile 口径一致）"


# ── TC-A06 证据强度计数（risk 章图数据源）───────────────────
def test_evidence_strength_counts_three_metrics():
    claims = [_claim(["e1", "e2"]), _claim(["e2"]), _claim([]), _claim(["脏id"])]
    evidences = [_ev("e1", "a.com"), _ev("e2", "b.com"), _ev("e3", "c.com")]
    out = SC.count_evidence_strength(claims, evidences)
    assert out == {"claims_total": 4, "evidence_total": 2, "domains": 2,
                   "supported": 2, "unsupported": 2, "support_ratio": 0.5}


def test_evidence_strength_domain_falls_back_to_source_type():
    """缺 domain 回退 source_type：同源不得因缺域名被拆成多条计数。"""
    out = SC.count_evidence_strength([_claim(["e1", "e2", "e3"])], [
        _ev("e1", "", "review"), _ev("e2", "", "review"), _ev("e3", "a.com")])
    assert out["domains"] == 2
    assert out["evidence_total"] == 3


def test_evidence_strength_never_returns_none():
    """计数类恒返回完整字典：0 条证据本身就是可展示的事实，不是输入不足。"""
    assert SC.count_evidence_strength([], []) == {
        "claims_total": 0, "evidence_total": 0, "domains": 0,
        "supported": 0, "unsupported": 0, "support_ratio": 0.0}


def test_evidence_strength_accepts_dataclass_objects():
    """实际链路里 claims 是 dict、evidences 是 Evidence dataclass，两者都要吃。"""
    from app.core.models import Evidence

    ev = Evidence(evidence_id="e1", source_url="https://a.com/x", source_type="news",
                  title="标题", excerpt="摘录", captured_at="", credibility=80.0,
                  collected_by="L1-001", domain="a.com")
    out = SC.count_evidence_strength([_claim(["e1", "e2"])], [ev])
    assert out["supported"] == 1
    assert out["evidence_total"] == 1, "不存在的 e2 属脏引用，不计入"
    assert out["domains"] == 1


# ── TC-A07 注册表完整性 / 确定性 ─────────────────────────────
def test_registry_declares_all_scoring_domains():
    assert set(SC.SCORE_FORMULAS) == {"accessibility", "amenity", "risk"}
    for domain, table in SC.SCORE_FORMULAS.items():
        assert table, f"{domain} 映射表不得为空"


def test_same_input_identical_output():
    rows = [{"destination": "大理", "routes": [
        {"mode": "高铁", "duration_minutes": 120, "cost_yuan": 400}]}]
    items = [{"dimension": "治安", "level": "high"}]
    amen = [{"coverage": "full"}, {"coverage": "none"}]
    claims, evidences = [_claim(["e1"])], [_ev("e1", "a.com")]
    assert SC.score_accessibility(rows) == SC.score_accessibility(rows)
    assert SC.score_risk_level(items) == SC.score_risk_level(items)
    assert SC.score_amenity_coverage(amen) == SC.score_amenity_coverage(amen)
    assert SC.count_evidence_strength(claims, evidences) == \
        SC.count_evidence_strength(claims, evidences)
    assert SC.weighted_score({"a": 1.0}, {"a": 1.0}) == SC.weighted_score({"a": 1.0}, {"a": 1.0})


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
