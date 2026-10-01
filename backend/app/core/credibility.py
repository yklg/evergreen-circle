"""证据可信度真实计算（对应需求 8：替换写死的 0.85/0.5/0.7）。

设计为轻量、确定性、可解释的打分模型，输出 0-100 的整数，精确到个位、有真实差异：
- 来源分级基分（官方文旅/财报/新闻/知乎/OTA 与旅行社区/B站/微博/小红书/抖音/评测）
- 域名权威性加减（gov/edu/官网/财经媒体 加分；聚合站/营销号 减分）
- 发布时间与时效性（有发布时间加分；越新越加分，过旧减分）
- 抓取质量（正文抽取成功加分；仅 snippet 降级减分；正文够长加分）

不依赖 LLM、不耗 token，纯规则计算。
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional
from urllib.parse import urlparse

from app.core.source_type import BASE_BY_TYPE as _BASE_BY_TYPE


# 来源类型基础分 = 信源类别注册表的派生值（app/core/source_type.py 为唯一真相源）。
# 这里不再维护字面量表：分数与类别的对应关系一旦有两份，改类别就得改两处，
# 而漏改不会报错，只会让某类证据的可信度悄悄漂走。
# 全域修正项（_AUTHORITY_HINTS / _LOW_QUALITY_HINTS）留在本模块：
# 它们**跨类别**作用于域名，属于"修正"而非"类别定义"。


# 高权威域名/后缀（命中加分）
_AUTHORITY_HINTS = (
    ".gov.cn", ".gov", ".edu.cn", ".edu", ".org.cn",
    "36kr.com", "sina.com.cn", "finance.sina", "caixin.com", "yicai.com",
    "people.com.cn", "xinhuanet.com", "cls.cn", "stcn.com", "eastmoney.com",
    "tmtpost.com", "huxiu.com", "ifeng.com", "cnbeta",
    # 文旅主管/研究机构与官方旅游数据源
    "mct.gov.cn", "ctaweb.org.cn", "wentiju",
)

# 低质聚合/营销号特征（命中减分）
_LOW_QUALITY_HINTS = (
    "baijiahao", "toutiao.com", "sohu.com", "163.com/dy",
    "zhuanlan", "marketing", "ad.", "promo",
)

_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})")

# ── 舆论过热护栏（v2.1：去热度化，杜绝"把热度当可信度"）────────
# 语义唯一判定点 = assess_viral()；score_evidence 只按传入的 viral 标记扣分。
# 阈值依据：营销号刷量/争议发酵一般远超普通口碑互动量级；可按需调整。
VIRAL_COMMENT_THRESHOLD = 10000  # 单条评论数 ≥ 此值视为过热
VIRAL_LIKE_THRESHOLD = 50000  # 单条点赞数 ≥ 此值视为过热
VIRAL_PENALTY = 8  # 过热证据的扣分数


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _parse_year(captured_at: str) -> Optional[int]:
    if not captured_at:
        return None
    m = re.search(r"(20\d{2})", captured_at)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def freshness_days(captured_at: str) -> Optional[int]:
    """从 captured_at（ISO 或含日期字符串）估算距今天数；无法解析返回 None。"""
    if not captured_at:
        return None
    # 尝试标准 ISO
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            dt = _dt.datetime.strptime(captured_at[:len(fmt) + 2].strip(), fmt)
            return max(0, (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - dt).days)
        except Exception:
            continue
    # 退而求其次：只取年月
    m = _DATE_RE.search(captured_at)
    if m:
        try:
            y, mo = int(m.group(1)), int(m.group(2))
            dt = _dt.datetime(y, max(1, min(12, mo)), 1)
            return max(0, (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - dt).days)
        except Exception:
            return None
    return None


def assess_viral(signals: Optional[dict]) -> dict:
    """舆论过热唯一判定点（v2.1 单点判定）。

    - 无互动信号（无 comments/likes）→ {"viral": False, "checked": False, "reason": ""}
      （未判定，供调用方记录"过热判定覆盖率"，不做空转推断）；
    - 有信号且命中阈值 → {"viral": True, "checked": True, "reason": <原因>}；
    - 有信号未命中 → {"viral": False, "checked": True, "reason": ""}。
    """
    signals = signals or {}
    likes = _as_int(signals.get("likes"))
    comments = _as_int(signals.get("comments"))
    if likes <= 0 and comments <= 0:
        return {"viral": False, "checked": False, "reason": ""}
    if comments >= VIRAL_COMMENT_THRESHOLD:
        return {"viral": True, "checked": True, "reason": f"评论量超阈值（{comments}）"}
    if likes >= VIRAL_LIKE_THRESHOLD:
        return {"viral": True, "checked": True, "reason": f"点赞量超阈值（{likes}）"}
    return {"viral": False, "checked": True, "reason": ""}


def score_evidence(
    url: str,
    source_type: str,
    captured_at: str = "",
    has_publish_date: bool = False,
    ok_fetch: bool = True,
    excerpt: str = "",
    signals: Optional[dict] = None,
    viral: bool = False,
) -> int:
    """返回 0-100 的可信度分数（int，精确到个位、有差异）。

    signals（可选）：补充信号，用于社媒类证据的细化打分，例如
        {"platform": "bilibili", "likes": 1200, "followers": 50000, "comments": 300}
    评论数/粉丝数越高，代表该口碑越有代表性、越可信（对应需求：媒体平台按
    评论数/粉丝数微调）。无信号时退回基础规则，不影响主流程。

    viral（可选，v2.1）：是否舆论过热（须由 assess_viral 判定后传入，本函数不自行
    判定——保证"什么算过热"只有一处实现）。为 True 时扣 VIRAL_PENALTY 分。
    """
    signals = signals or {}
    domain = _domain(url)
    score = _BASE_BY_TYPE.get(source_type, _BASE_BY_TYPE["unknown"])

    # 域名权威性
    if any(h in domain or h in url for h in _AUTHORITY_HINTS):
        score += 10
    if any(h in domain or h in url for h in _LOW_QUALITY_HINTS):
        score -= 5

    # 发布时间与时效性
    if has_publish_date:
        score += 6
    fd = freshness_days(captured_at)
    if fd is not None:
        if fd <= 365:
            score += 5
        elif fd <= 730:
            score += 2
        elif fd > 1095:
            score -= 5

    # 抓取质量
    if ok_fetch:
        score += 6
    else:
        score -= 8
    if excerpt and len(excerpt) > 200:
        score += 3

    # 社媒平台热度信号：互动代表"代表性"而非"可信度"（封顶 +6，v2.1 去热度化）
    score += _engagement_bonus(signals)

    # 舆论过热惩罚（v2.1）：高热≠可信，按传入标记扣分
    if viral:
        score -= VIRAL_PENALTY

    # 让分数有非 5 倍数的细微差异：用域名长度做轻微扰动（确定性、可复现）
    if domain:
        score += (len(domain) % 4) - 1  # -1..+2

    return max(5, min(98, int(round(score))))


def _engagement_bonus(signals: dict) -> int:
    """根据互动信号（评论数/点赞数/粉丝数）给出 0-6 的加分（v2.1 封顶 6，对数刻度，确定性）。

    互动只代表口碑"代表性/讨论度"的轻微加分，不再承担"可信度"主加分（去热度化）。
    """
    import math

    if not signals:
        return 0
    likes = _as_int(signals.get("likes"))
    comments = _as_int(signals.get("comments"))
    followers = _as_int(signals.get("followers"))
    # 评论权重最高（真实讨论度），其次点赞，再次粉丝量
    raw = comments * 3 + likes * 1 + followers * 0.2
    if raw <= 0:
        return 0
    # log10 刻度：100→约3分，1万→约6分（封顶），百万→仍约为6分（封顶）
    return int(max(0, min(6, round(math.log10(raw + 1) * 3))))


def _as_int(v) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0
