"""信源组归一化（内容级去重）测试（accuracy-objectivity-hardening 方案 v2.1）。

守护不变量：
- 指纹确定性：同文同指纹（跨进程可复现，md5 而非内建 hash）。
- 转载检测：同文改标题/首段 → 并入同一信源组（token 集合 + Jaccard，位置无关）。
- 异文不误杀：不同内容 → 开新组。
- 短文本边界：< DEDUP_MIN_CHARS 不参与归并（沿用 textquality 短文本放行先例）。

注：测试使用「多句自然拼接」的正文（典型网页正文形态、token 词典丰富）；
不要用单句重复构造——词典过小会放大前缀占比，失真（见 v2.1.2 修正记录）。

运行：backend/ 下 `pytest tests/test_dedup.py -q`
"""
import pytest

from app.core.dedup import (
    content_fingerprint,
    group_new_text,
    normalize_text,
    token_similarity,
    tokenize,
)

_SENTENCES = [
    "腾讯发布第二节度财报：游戏业务收入同比增长百分之十二，广告业务收入增长百分之八。",
    "公司同时宣布将在年内推出三类 AI 原生应用，覆盖办公、教育与金融三大场景。",
    "管理层在业绩电话会上强调，研发投入占比将继续维持在百分之十八左右的水平。",
    "公司计划把生成式 AI 能力全面下沉到生态内所有核心产品线与开放平台。",
    "多位行业分析师认为，这一轮整体布局将显著影响未来几年的竞争格局。",
    "供应链方面，上游芯片采购成本环比下降，为终端产品定价留出了缓冲空间。",
    "海外市场增速持续高于国内，东南亚与拉美正成为新的业绩增长极。",
    "公司首席财务官表示将保持健康的自由现金流，并继续执行股份回购计划。",
    "用户规模已连续六个季度保持双位数增长，付费转化率也同步稳步提升。",
    "内部人士透露，团队正在研发新一代推荐与搜索引擎，预计明年正式上线。",
]


def _doc() -> str:
    return "。".join(_SENTENCES) * 3  # 约 1000 字自然正文，词典丰富


def test_fingerprint_deterministic():
    t = _doc()
    assert content_fingerprint(t) == content_fingerprint(t)
    assert len(content_fingerprint(t)) == 16  # 64-bit → 16 hex


def test_normalize_text():
    assert normalize_text("Trae 2.0 发布！") == "trae#发布"
    assert normalize_text("  A!B  ") == "ab"


def test_republished_merges_into_same_group():
    """同文异链（改标题/首段）→ 并入同一组，转载不冒充独立信源。"""
    doc = _doc()
    repost = "重磅首发 2026 快讯：" + doc
    groups = [{"id": "g_1", "tokens": tokenize(doc), "urls": ["https://a.com/1"]}]
    gid, _ = group_new_text(repost, groups)
    assert gid == "g_1"


def test_republished_reordered_still_merges():
    """正文段落重排（转载常见改写）→ 仍归并同组（位置无关）。"""
    doc = _doc()
    reordered = "。".join(_SENTENCES[9:] + _SENTENCES[:9]) * 3
    groups = [{"id": "g_re", "tokens": tokenize(doc), "urls": ["https://a.com/1"]}]
    gid, _ = group_new_text(reordered, groups)
    assert gid == "g_re"


def test_distinct_content_new_group():
    a = _doc()
    b = ("完全不同的主题：讨论新能源汽车电池回收市场、回收率与环保政策。"
         "行业报告显示回收企业数量快速增加，多家车企宣布自建回收体系。" * 4)[:1500]
    groups = [{"id": "g_1", "tokens": tokenize(a), "urls": ["https://a.com/1"]}]
    gid, _ = group_new_text(b, groups)
    assert gid is None


def test_short_text_skips_grouping():
    short = "手机一般般"
    groups = [{"id": "g_1", "tokens": tokenize(_doc()), "urls": ["https://a.com/1"]}]
    gid, rep = group_new_text(short, groups)
    assert gid is None
    assert rep == []


def test_group_url_accumulation_contract():
    """并入组的调用方契约：收到 group_id 后把新 URL 追加进组 urls。"""
    doc = _doc()
    repost = "速读速报：" + doc
    groups = [{"id": "g_9", "tokens": tokenize(doc), "urls": ["https://a.com/1"]}]
    gid, _ = group_new_text(repost, groups)
    assert gid == "g_9"
    groups[0]["urls"].append("https://b.com/2")  # 采集边界行为
    assert "https://b.com/2" in groups[0]["urls"]


def test_token_similarity_bounds():
    a = tokenize(_doc())
    assert token_similarity(a, a) == 1.0
    assert token_similarity(a, []) == 0.0
    assert 0.0 <= token_similarity(a, a) <= 1.0


def test_empty_inputs_safe():
    assert content_fingerprint("") == ""
    assert tokenize("") == []
    gid, rep = group_new_text("", [])
    assert gid is None and rep == []