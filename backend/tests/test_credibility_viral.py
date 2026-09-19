"""可信度去热度化 / 舆论过热护栏测试（accuracy-objectivity-hardening 方案 v2.1）。

守护不变量：
- assess_viral 单点判定：无信号不推断（checked=False）、命中阈值才判 viral、reason 可解释。
- score_evidence(..., viral=True) 扣 VIRAL_PENALTY 分（不自行判定，同输入差恰为惩罚值）。
- 互动加分「代表性」封顶 6（去热度化：热度不再是可信度主加分）。

运行：backend/ 下 `pytest tests/test_credibility_viral.py -q`
"""
from app.core.credibility import assess_viral, score_evidence, _engagement_bonus


def test_assess_viral_missing_signal_not_checked():
    """无互动信号 → 未判定（checked=False），供调用方统计判定覆盖率。"""
    r = assess_viral({})
    assert r == {"viral": False, "checked": False, "reason": ""}


def test_assess_viral_comments_hit():
    r = assess_viral({"comments": 20000, "likes": 0})
    assert r["viral"] is True
    assert r["checked"] is True
    assert "评论" in r["reason"]


def test_assess_viral_likes_hit():
    r = assess_viral({"likes": 80000, "comments": 0})
    assert r["viral"] is True
    assert r["checked"] is True
    assert "点赞" in r["reason"]


def test_assess_viral_not_hit():
    r = assess_viral({"comments": 50, "likes": 100})
    assert r == {"viral": False, "checked": True, "reason": ""}


def test_score_evidence_viral_penalty_exact():
    url = "https://weibo.com/example"
    base = score_evidence(url, "weibo", signals={})
    penalized = score_evidence(url, "weibo", signals={}, viral=True)
    # 同输入唯一差异为 viral 标记 → 差恰为 VIRAL_PENALTY=8
    assert base - penalized == 8


def test_engagement_bonus_capped_at_six():
    """百万级互动 → 封顶 +6（去热度化：代表性加分不再充当可信度主加分）。"""
    huge = {"likes": 10 ** 8, "comments": 10 ** 7, "followers": 10 ** 9}
    assert _engagement_bonus(huge) == 6
    # 温和互动不变式：加分在 0..6 之间，且低互动 < 封顶
    small = _engagement_bonus({"likes": 10, "comments": 5})
    assert 0 <= small <= 6
    assert _engagement_bonus({}) == 0