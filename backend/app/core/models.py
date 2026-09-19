"""核心数据模型（第 3 章）：Evidence / Claim / Envelope / 报告结构。

Python 3.9 兼容：使用 typing.Optional / List，避免 `X | None` 运行期解析问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    evidence_id: str
    source_url: str
    source_type: str  # official|news|douyin|xiaohongshu|bilibili|weibo|zhihu|review|financial_report
    title: str
    excerpt: str
    captured_at: str
    credibility: float  # 0-100 整数（由 credibility.score_evidence 计算，精确到个位、有差异）
    collected_by: str
    report_id: str = ""  # 证据统一归属具体报告；'' 表示尚未挂载（旧数据兜底，正常路径恒非空）
    screenshot_path: str = ""
    image_urls: List[str] = field(default_factory=list)
    lang: str = "zh"
    brand: str = ""
    domain: str = ""
    freshness_days: Optional[int] = None  # 距今天数，None=无法解析
    # ── 客观性加固（信源组 / 舆论过热）────────────────────────
    content_hash: str = ""  # 内容指纹（dedup.content_fingerprint；短文本为 ""）
    source_group: str = ""  # 信源组 id（同质转载归并为一组；空=未分组/短文本）
    republished_from: List[str] = field(default_factory=list)  # 与代表 URL 同质化的转载地址
    viral: bool = False  # 舆论过热标记（credibility.assess_viral 单点判定）
    viral_reason: str = ""  # 过热原因（如"评论量超阈值"）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Claim:
    claim_id: str
    text: str
    field: str  # feature_tree|pricing_model|user_persona|swot|sentiment|overview
    evidence_ids: List[str]
    confidence: str  # high|medium|low|unverified
    cross_validated: bool
    author: str
    claim_type: str = "mixed"  # fact|opinion|mixed（分析层客观性标注，默认 mixed 兼容旧数据）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Issue:
    issue_id: str
    target: str  # claim_id / section
    severity: str  # high|medium|low
    reason: str
    raised_by: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Envelope:
    msg_id: str
    sender: str
    receiver: str
    task_type: str  # PRODUCE | REWORK | PASS
    payload: Dict[str, Any] = field(default_factory=dict)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    trace_ref: str = ""


def make_claim(
    claim_id: str,
    text: str,
    field_name: str,
    evidence_ids: List[str],
    author: str,
    independent_groups: int = 0,
    claim_type: str = "mixed",
) -> Claim:
    """按四铁律计算置信度：无证据→unverified；≥2 个独立信源组→high。

    独立信源以「信源组（Evidence.source_group）」计：同一事实/转载文无论多少个
    URL 都算一组，杜绝转载冒充多源（架构根因修复，替换原 independent_domains 域名近似）。
    """
    if not evidence_ids:
        return Claim(claim_id, text, field_name, [], "unverified", False, author, claim_type)
    cross = independent_groups >= 2
    if cross:
        conf = "high"
    elif len(evidence_ids) >= 2:
        conf = "medium"
    else:
        conf = "low"
    return Claim(claim_id, text, field_name, evidence_ids, conf, cross, author, claim_type)
