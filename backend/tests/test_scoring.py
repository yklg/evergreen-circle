"""M1 · 评分模型：四维确定性评分 / 边界 / 盲区扣分 / 三要素结论。"""
import pytest

from app.living_circle.scoring import compute_scores, triad_from_points

_ALL = ["market", "medical", "education", "shopping", "elderly", "finance", "recreation", "service"]


def _categories(vals):
    """构造 8 类类别统计；vals: {category: (coverage, min_minutes)}。"""
    out = []
    for cat, label in [
        ("market", "菜市场"),
        ("medical", "医疗"),
        ("education", "教育"),
        ("shopping", "购物"),
        ("elderly", "养老"),
        ("finance", "金融"),
        ("recreation", "文体"),
        ("service", "政务"),
    ]:
        cov, mm = vals.get(cat, (0.5, 10.0))
        out.append({
            "category": cat,
            "label": label,
            "total": 4,
            "in_circle": int(round(cov * 4)),
            "coverage": cov,
            "min_minutes": mm,
            "nearest_name": f"{label}A",
        })
    return out


def test_full_coverage_scores_high():
    cats = _categories({c: (1.0, 5.0) for c in _ALL})
    scores = compute_scores(cats, [], 0)
    assert scores["total"] > 85  # 满覆盖接近满分
    assert scores["total"] <= 100
    assert len(scores["radar"]) == 8
    assert len(scores["bars"]) == 8
    assert all(b["value"] == 100 for b in scores["bars"])


def test_poor_coverage_scores_low():
    cats = _categories({c: (0.1, 18.0) for c in _ALL})
    scores = compute_scores(cats, [], 0)
    assert scores["total"] < 40


def test_score_monotonicity_with_coverage():
    low = compute_scores(_categories({c: (0.3, 15.0) for c in _ALL}), [], 0)["total"]
    high = compute_scores(_categories({c: (0.9, 6.0) for c in _ALL}), [], 0)["total"]
    assert high > low


def test_blindspot_penalty_capped():
    a = compute_scores(_categories({c: (0.8, 8.0) for c in _ALL}), [], 1)["total"]
    b = compute_scores(_categories({c: (0.8, 8.0) for c in _ALL}), [], 5)["total"]
    c = compute_scores(_categories({c: (0.8, 8.0) for c in _ALL}), [], 50)["total"]
    assert a > b >= c  # 多盲区扣分更多，且封顶


def test_triad_from_points_covered_and_missing():
    def field_fn(pt):
        return 3.0 if pt[0] < 0.01 else None  # 只有西侧可达

    triads = triad_from_points(
        [{"lng": 0.1, "lat": 0.0, "name": "菜市A"}, {"lng": 0.2, "lat": 0.0, "name": "菜市B"}],
        [{"lng": 0.0, "lat": 0.0, "name": "药店A"}],
        [{"lng": 1.0, "lat": 1.0, "name": "小学A"}],
        field_fn,
    )
    by = {t["facility"]: t for t in triads}
    assert by["药店"]["covered"] is True
    assert by["药店"]["nearest_name"] == "药店A"
    assert by["药店"]["nearest_minutes"] == pytest.approx(3.0)
    assert by["菜市场"]["covered"] is False
    assert by["小学"]["covered"] is False


def test_triads_passthrough_three_entries():
    triads = [
        {"facility": "菜市场", "covered": True, "nearest_name": "A", "nearest_minutes": 2.0},
        {"facility": "药店", "covered": True, "nearest_name": "B", "nearest_minutes": 3.0},
        {"facility": "小学", "covered": False, "nearest_name": None, "nearest_minutes": None},
    ]
    scores = compute_scores(_categories({}), triads, 0)
    assert len(scores["triads"]) == 3