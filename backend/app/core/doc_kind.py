"""舆情语料的文档类型判定（词云口碑化架构修复计划 · 步骤 1）。

## 为什么要有这个模块

舆情链路喂给词云的一直不是「评论」，而是搜索引擎摘要。对报告 r_6dadffee 的 25 条舆情
证据逐条手工定标，真实构成是：**口碑 7 / SEO 介绍页 5 / 门票票务页 5 / 航班时刻表 3 /
攻略指南 3 / 新闻通稿 1 / 页面壳（JS 墙）1** —— 只有 28% 是用户口碑。

不区分文档类型，任何选词算法都白搭：地名与页面 chrome 词（航班/时刻表/座位数/图片）
在剩下 72% 的文本里天然高频，评价词在 28% 的文本里天然低频。所以「这是不是口碑」必须
先成为一个**被建模的事实**，而不是靠停用词表事后打捞。

## 设计约定

- 本模块是**叶子**：只依赖标准库，不 import 任何 pipeline，也不 import opinions /
  wordfreq / source_type（保持 sentiment → {doc_kind, opinions} 的单向依赖）。
- 判据是**查表**，`_RULES` 的元素顺序即优先级：**先硬排除，再谈纳入**。
  新增一类页面 = 加一条记录，不改判定逻辑本身（对齐 platforms.py 的注册表思路）。
- **形态标记 ≠ 评价词表**：`_REVIEW_MARKS` 只收「像不像真人在讲自己的经历」这类
  *形态/人称* 标记（我去过、楼主、评论区、旅居、让人感到…）。评价形容词
  （美、值得、古朴…）属 `opinions` 的词表，出现在这里即为职责越界 —— 由
  `test_doc_kind.py` 的守卫用例钉住，不靠自觉。
- 刻意**不**复用 `source_type`：实测 sohu.com 的三条里，一条是新闻通稿、两条是
  个人游记/出行问答，按域名判 news 会把后两条误杀。故 news 走内容形态标记。

## unknown 的语义（重要）

调用方未打标（字段缺席）时按 `UNKNOWN` 处理：`UNKNOWN` **不进词云**，但
**计入 `corpus_size` 与情感统计**。即「没看过 ≠ 不是口碑」——保守到不把未接线
路径的样本静默清零，同时也不允许未经判定的文本冒充观点证据。
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

# 判定结果全集。顺序即 `_RULES` 的优先级：越靠前越先截走。
KINDS: Tuple[str, ...] = ("chrome", "flight", "ticket_faq", "review", "news", "seo", "guide", "other")
# 未打标（字段缺席）时的取值。不在 KINDS 内：它不是判定结果，是「没判过」。
UNKNOWN = "unknown"
# 可进词云的唯一类型。其余（含 UNKNOWN）一律不进。
REVIEW_KIND = "review"

# 页面壳：JS 未启用墙 / 登录墙 / 验证码。**只按标记判，不设正文长度门槛**：
# 长度门槛想拦的「近乎为空的文本」本来就会因无任何标记落到 other，同样进不了词云与
# 统计；而它误伤的却是一句话点评（「洱海很美。」5 字即被当成页面壳）。
_CHROME_MARKS: Tuple[str, ...] = (
    "doesn't work properly without", "enable it to continue", "we're", "sorry but",
    "please enable", "请启用", "请开启javascript", "登录后可见", "登录后查看",
    "验证码", "访问受限", "页面加载中", "403 forbidden", "404 not found",
)

# 交通查询页：航班/时刻表/座位数。OTA 站内搜索最容易整批召回这类页面。
_FLIGHT_URL_MARKS: Tuple[str, ...] = ("flights.", "/schedule", "/flight", "/hangban", "/jipiao")
_FLIGHT_MARKS: Tuple[str, ...] = (
    "航班查询", "航班时刻表", "航班时刻", "时刻表", "航线查询", "航班号查询",
    "准点率", "座位数", "机型", "班期", "机票查询", "机票预订", "无直飞",
)

# 票务/规则页：门票、开放时间、免票条件。信息有用，但不是口碑。
_TICKET_URL_MARKS: Tuple[str, ...] = ("you.ctrip.com/sight", "/sight/", "/poi/", "/ticket")
_TICKET_MARKS: Tuple[str, ...] = (
    "门票/地址", "门票价格", "开放时间", "游玩攻略简介", "预约", "票价",
    "周岁", "身高在", "凭老年证", "凭身份证", "现役军人凭", "单次票",
)

# 口碑正门标记：只放「第一人称 / 叙事形态 / 感受句式」，不放评价形容词。
# 定位是**精度优先**的闸门：漏掉一条真口碑（判成 other）只是少一个样本，
# 放进一条 SEO 文案则会污染整张词云与好评率。召回主要靠采集侧检索角度
# （步骤 2b 把「避坑 攻略」换成「体验 吐槽」），不靠把这张表扩到无边界。
_REVIEW_MARKS: Tuple[str, ...] = (
    "我去过", "我去了", "我来了", "住了", "旅居", "亲测", "亲自", "不吹不黑",
    "问我", "我想了", "我的感受", "个人觉得", "说实话", "真心觉得", "这是我",
    "分享我", "楼主", "评论区", "回帖", "网友说",
    "让人感到", "让人觉得", "给人留下", "每一张照片", "记住这个名字", "不允许你们不来",
    "很可惜", "私藏", "踩过的坑", "实际体验", "住过",
)

# 新闻通稿形态（按内容而非域名：同一域名下通稿与游记并存）。
_NEWS_MARKS: Tuple[str, ...] = (
    "特别声明", "不代表", "新华社", "中新网", "日电", "记者", "累计接待",
    "通讯员", "责任编辑", "本文来源",
)

# SEO/百科介绍页：地名 + 建制沿革 + 面积人口。
_SEO_URL_MARKS: Tuple[str, ...] = ("/study/", "studytag", "travel-guide", "/baike", "wiki")
_SEO_MARKS: Tuple[str, ...] = (
    "位于云南省", "位于四川省", "占地面积", "总面积", "总人口", "历史可追溯",
    "都曾将它作为都城", "是大理最著名的景", "自由行旅遊攻略", "气温日差",
    "日照较多", "始建于明",
)

# 攻略/指南/行程页：教你怎么玩，不含谁觉得怎么样。
_GUIDE_MARKS: Tuple[str, ...] = (
    "旅游攻略", "旅行指南", "购物指南", "旅游提醒", "行程规划", "出行建议",
    "实用出行", "自驾", "路线安排", "行程安排", "提前订房", "订票",
    "可以去这些地方玩", "旅行社",
)

# (kind, url 标记, 正文/标题合并后命中的标记)。空元组 = 该维度不参与判定。
_RULES: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("chrome", (), _CHROME_MARKS),
    ("flight", _FLIGHT_URL_MARKS, _FLIGHT_MARKS),
    ("ticket_faq", _TICKET_URL_MARKS, _TICKET_MARKS),
    ("review", (), _REVIEW_MARKS),
    ("news", (), _NEWS_MARKS),
    ("seo", _SEO_URL_MARKS, _SEO_MARKS),
    ("guide", (), _GUIDE_MARKS),
)

# 域名标记只在 url 上找（避免正文里引用了别的站点就误判），文本标记在标题+正文上找。
_URL_ONLY_KINDS = frozenset({"flight", "ticket_faq", "seo"})


def classify_doc(url: str, title: str, text: str) -> Tuple[str, List[str]]:
    """判定单条舆情语料的文档类型，返回 `(kind, reasons)`。

    `reasons` 是命中说明（如 `"body:航班时刻表"`、`"url:you.ctrip.com/sight"`），
    供 trace 与验收对照表如实交代「为什么这条被剔」，不做黑箱判定。
    纯函数：不查库、不打网络、不依赖调用方状态。
    """
    blob = f"{title} {text}".lower()
    u = (url or "").lower()

    for kind, url_marks, body_marks in _RULES:
        if kind == "chrome":
            hit = _hit(blob, _CHROME_MARKS)
            if hit:
                return "chrome", [f"body:{hit}"]
            continue
        if kind == "review":
            hit = _hit(blob, body_marks)
            if hit:
                return REVIEW_KIND, [f"body:{hit}"]
            continue
        hit = _hit(u, url_marks) if kind in _URL_ONLY_KINDS else None
        if hit:
            return kind, [f"url:{hit}"]
        hit = _hit(blob, body_marks)
        if hit:
            return kind, [f"body:{hit}"]
    return "other", ["无任一类型标记"]


def counts_as_review(comment: Dict[str, Any]) -> bool:
    """是否算「可核验用户口碑」——**词云与评价短语的唯一判据**。

    只有真口碑才允许作为观点证据出现在词云里；`UNKNOWN`（未打标）与其余类型一律不进。
    禁止在调用方另写 `c["doc_kind"] == "review"`：那会造出第二套口径。
    """
    return (comment.get("doc_kind") or UNKNOWN) == REVIEW_KIND


# 计入情感统计的类型集合：真口碑 + 未打标。
_STATS_KINDS = frozenset({REVIEW_KIND, UNKNOWN})


def counts_in_sentiment(comment: Dict[str, Any]) -> bool:
    """是否计入好评率/样本量统计——**与词云判据不同，不要混用**。

    为什么必须分成两个判据：未打标（`UNKNOWN`）的文本「没被判过」，把它从好评率里
    抹掉会让任何尚未接线 doc_kind 的调用路径静默产出空舆情、且看不出是被剔了还是
    压根没采到；而让它冒充观点证据进词云，又会把本次要修的症状原样留下。
    ⇒ 统计侧保守纳入、证据侧严格排除。
    """
    return (comment.get("doc_kind") or UNKNOWN) in _STATS_KINDS


def _hit(haystack: str, marks: Sequence[str]) -> str:
    for m in marks:
        if m and m.lower() in haystack:
            return m
    return ""


def kind_counts(comments: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """按 doc_kind 聚合计数（含 UNKNOWN），供报告方法论与 trace 如实披露。"""
    out: Dict[str, int] = {}
    for c in comments:
        k = (c.get("doc_kind") or UNKNOWN)
        out[k] = out.get(k, 0) + 1
    return out


__all__ = ["KINDS", "UNKNOWN", "REVIEW_KIND", "classify_doc",
           "counts_as_review", "counts_in_sentiment", "kind_counts"]
