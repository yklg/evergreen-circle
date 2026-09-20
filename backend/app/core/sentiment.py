"""舆情分析（第 6 章）：真实评论情感分类 + 观点阵营 + 体量统计。

数据全部来自真实站内检索到的评论（带真实链接）。无评论则如实返回空结构，
绝不使用任何 demo 假数据。LLM 可用时走 LLM 情感分类，否则规则兜底。
观点阵营占比归一化到 100%（修复历史 >100% bug）。抖音永远排第一。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.core.llm import chat_json
from app.core.platforms import PLATFORMS

# 各平台元数据统一从平台注册表（app.core.platforms）派生，避免多份注册表漂移。
# 注：抖音永远排第一（与历史行为一致）。
PLATFORM_SITES = {k: p.search_site for k, p in PLATFORMS.items()}
PLATFORM_ORDER = list(PLATFORMS.keys())
PLATFORM_LABEL = {k: p.label for k, p in PLATFORMS.items()}

_POS = ["好", "强", "喜欢", "推荐", "优秀", "值得", "香", "爱了", "性价比", "流畅", "丝滑", "靠谱"]
_NEG = ["差", "贵", "卡", "失望", "垃圾", "退", "坑", "难用", "bug", "缺点", "拉胯", "翻车"]


def _empty_result() -> Dict[str, Any]:
    """无任何真实评论时如实返回空结构（不造假）。"""
    return {
        "overall": {"pos": 0, "neu": 0, "neg": 0},
        "overall_count": {"pos": 0, "neu": 0, "neg": 0},
        "by_platform": {},
        "timeline": [],
        "camps": [],
        "voices": [],
        "highlights": [],
        "sample_size": 0,
    }


def _rule_sentiment(text: str) -> str:
    p = sum(w in text for w in _POS)
    n = sum(w in text for w in _NEG)
    if p > n:
        return "pos"
    if n > p:
        return "neg"
    return "neu"


def _llm_classify(brand: str, comments: List[Dict[str, Any]]) -> bool:
    """用 LLM 给每条真实评论打 pos/neu/neg，写回 comment["sentiment"]。

    成功返回 True，失败返回 False（调用方走规则兜底）。
    """
    if not comments:
        return False
    items = [{"i": i, "text": (c.get("text") or "")[:200]} for i, c in enumerate(comments)]
    data = chat_json(
        [
            {"role": "system", "content": "你是资深舆情分析师，对每条用户评论判断它对目标品牌的情感倾向。"},
            {"role": "user", "content": (
                f"目标品牌：{brand}\n\n下面是若干条真实用户评论，请逐条判断情感，"
                f"只能是 pos（正面/看好）、neu（中立/观望）、neg（负面/质疑）三选一。\n"
                f"严格输出 JSON 数组，每项形如 {{\"i\": 0, \"s\": \"pos\"}}，i 与输入对应，不要多余文字。\n\n"
                f"评论列表：\n{items}"
            )},
        ],
        temperature=0.1,
        max_tokens=1500,
    )
    if not isinstance(data, list):
        return False
    mapping = {}
    for it in data:
        if isinstance(it, dict) and "i" in it and it.get("s") in ("pos", "neu", "neg"):
            mapping[int(it["i"])] = it["s"]
    if not mapping:
        return False
    for i, c in enumerate(comments):
        c["sentiment"] = mapping.get(i) or _rule_sentiment(c.get("text", ""))
    return True


def analyze_sentiment(brand: str, comments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """comments: [{text, platform, url, title}]（均为真实检索结果）。返回 SentimentResult 结构。"""
    if not comments:
        return _empty_result()

    # 逐条打情感：LLM 优先，失败规则兜底
    if not _llm_classify(brand, comments):
        for c in comments:
            c["sentiment"] = _rule_sentiment(c.get("text", ""))

    overall = {"pos": 0, "neu": 0, "neg": 0}
    by_platform: Dict[str, Dict[str, int]] = {}
    for c in comments:
        s = c.get("sentiment", "neu")
        overall[s] += 1
        plat = c.get("platform", "douyin")
        by_platform.setdefault(plat, {"pos": 0, "neu": 0, "neg": 0})
        by_platform[plat][s] += 1

    total = max(sum(overall.values()), 1)
    overall_pct = _normalize_pct(overall, total)

    # 观点阵营（占比基于真实计数，归一化到 100%）
    camps = _build_camps(brand, comments, total)

    # 平台原声墙（各平台代表性真实评论，抖音优先）+ LLM 金句摘抄
    voices = _build_voices(comments)
    highlights = _extract_highlights(brand, comments)

    # 平台排序：抖音永远第一
    ordered_platform = {}
    for p in PLATFORM_ORDER:
        if p in by_platform:
            ordered_platform[p] = by_platform[p]
    for p in by_platform:
        if p not in ordered_platform:
            ordered_platform[p] = by_platform[p]

    # 按品牌聚合：不同竞品的口碑对比（支持「不同平台/竞品观点聚类」）
    by_brand = _build_by_brand(comments)

    return {
        "overall": overall_pct,
        "overall_count": overall,
        "by_platform": ordered_platform,
        "by_brand": by_brand,
        "timeline": [],  # 评论无可靠日期，不伪造时间线
        "camps": camps,
        "voices": voices,
        "highlights": highlights,
        "sample_size": len(comments),
    }


def _build_by_brand(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按品牌聚合情感分布与样本量（不同竞品口碑横向对比）。"""
    agg: Dict[str, Dict[str, int]] = {}
    for c in comments:
        b = (c.get("brand") or "").strip()
        if not b:
            continue
        s = c.get("sentiment", "neu")
        agg.setdefault(b, {"pos": 0, "neu": 0, "neg": 0})
        agg[b][s] += 1
    out: List[Dict[str, Any]] = []
    for b, counts in agg.items():
        n = counts["pos"] + counts["neu"] + counts["neg"]
        if not n:
            continue
        pct = _normalize_pct(counts, n)
        out.append({"brand": b, "sample": n, "pos": pct["pos"], "neu": pct["neu"], "neg": pct["neg"]})
    out.sort(key=lambda x: x["sample"], reverse=True)
    return out


def _build_voices(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按平台聚合代表性真实原声（抖音优先），每条带情感标签与可溯源链接。"""
    by_plat: Dict[str, List[Dict[str, Any]]] = {}
    for c in comments:
        plat = c.get("platform", "douyin")
        by_plat.setdefault(plat, []).append(c)
    voices: List[Dict[str, Any]] = []
    plats = [p for p in PLATFORM_ORDER if p in by_plat] + \
            [p for p in by_plat if p not in PLATFORM_ORDER]
    for plat in plats:
        items = [c for c in by_plat[plat] if c.get("url") and (c.get("text") or "").strip()]
        # 优先挑有明确情感倾向（pos/neg）的，更有信息量
        items.sort(key=lambda c: 0 if c.get("sentiment") in ("pos", "neg") else 1)
        for c in items[:3]:
            voices.append({
                "platform": plat,
                "platform_label": PLATFORM_LABEL.get(plat, plat),
                "text": (c.get("text") or "").strip()[:160],
                "sentiment": c.get("sentiment", "neu"),
                "url": c.get("url", ""),
                "title": c.get("title", ""),
            })
    return voices


def _extract_highlights(brand: str, comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM 从真实评论中摘出最有代表性的『金句短语』，每条挂回真实来源链接（可溯源）。"""
    pool = [c for c in comments if c.get("url") and (c.get("text") or "").strip()]
    if not pool:
        return []
    items = [{"i": i, "text": (c.get("text") or "")[:200],
              "platform": PLATFORM_LABEL.get(c.get("platform", ""), "")}
             for i, c in enumerate(pool)]
    try:
        data = chat_json(
            [
                {"role": "system", "content": (
                    "你是资深社媒舆情分析师。从真实用户评论中挑选/提炼最有代表性、最有信息量、"
                    "最能反映真实口碑的『金句短语』（可直接摘抄原句中的关键片段，保持真实口吻）。"
                    "只挑 4-6 条最有冲击力或最具代表性的，覆盖正面与负面不同声音。"
                    "严格输出 JSON 数组，每项 {\"i\": 原评论序号, \"phrase\": \"金句短语(不超过30字)\"}，"
                    "phrase 必须忠于原评论含义，不得编造。不要多余文字。"
                )},
                {"role": "user", "content": f"目标品牌：{brand}\n评论列表：\n{items}"},
            ],
            temperature=0.3,
            max_tokens=800,
        )
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in data:
        if not isinstance(it, dict) or "i" not in it or not it.get("phrase"):
            continue
        try:
            src = pool[int(it["i"])]
        except (ValueError, IndexError, TypeError):
            continue
        out.append({
            "phrase": str(it["phrase"])[:40],
            "platform": src.get("platform", ""),
            "platform_label": PLATFORM_LABEL.get(src.get("platform", ""), ""),
            "sentiment": src.get("sentiment", "neu"),
            "url": src.get("url", ""),
        })
    return out[:6]


def _normalize_pct(counts: Dict[str, int], total: int) -> Dict[str, int]:
    """把计数转百分比并保证三项之和恰为 100（最大余数法）。"""
    keys = list(counts.keys())
    raw = {k: counts[k] / total * 100 for k in keys}
    floored = {k: int(raw[k]) for k in keys}
    remainder = 100 - sum(floored.values())
    # 把剩余的百分点按小数部分从大到小补给各项
    order = sorted(keys, key=lambda k: raw[k] - floored[k], reverse=True)
    for k in order[:max(remainder, 0)]:
        floored[k] += 1
    return floored


def _build_camps(brand: str, comments: List[Dict[str, Any]], total: int) -> List[Dict[str, Any]]:
    pos = [c for c in comments if c.get("sentiment") == "pos"]
    neg = [c for c in comments if c.get("sentiment") == "neg"]
    neu = [c for c in comments if c.get("sentiment") == "neu"]

    groups = [
        (pos, f"看好派：认可{brand}的产品力", f"该阵营用户普遍认可{brand}在体验、性价比或口碑上的优势。"),
        (neg, f"质疑派：担忧{brand}的短板", f"该阵营用户对{brand}的价格、稳定性或服务存在明确顾虑。"),
        (neu, "观望派：理性比较中", "该阵营尚在多方对比、未形成明确倾向，关注后续表现。"),
    ]
    # 占比归一化：先各自取百分比，再用最大余数法保证总和 = 100
    counts = {"pos": len(pos), "neg": len(neg), "neu": len(neu)}
    pct = _normalize_pct(counts, max(total, 1))
    pct_map = {"pos": pct["pos"], "neg": pct["neg"], "neu": pct["neu"]}
    key_map = {0: "pos", 1: "neg", 2: "neu"}

    camps: List[Dict[str, Any]] = []
    for idx, (group, title, summary) in enumerate(groups):
        if not group:
            continue
        quotes = [
            {"text": c.get("text", ""), "url": c.get("url", ""), "platform": PLATFORM_LABEL.get(c.get("platform", ""), "")}
            for c in group[:4] if c.get("url")
        ]
        camps.append({
            "title": title,
            "ratio": pct_map[key_map[idx]],
            "summary": summary,
            "quotes": quotes,
        })
    return camps


def category_keywords(category: str) -> List[str]:
    """把主题短语拆成关键词，用于舆情相关性消歧（如『交通与票务』→ [交通, 票务]）。

    中英文混合分词：英文按字母数字连字符片段；中文短语在整段之外再切 2 字片段，
    提升命中召回（长短语不再被当拒绝词）。去重保序；空→[]。
    """
    if not category:
        return []
    kws: List[str] = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{1,}", category.lower()):
        kws.append(w)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", category):
        kws.append(run.lower())
        if len(run) > 2:
            for i in range(len(run) - 1):
                kws.append(run[i:i + 2].lower())
    seen: set = set()
    return [k for k in kws if not (k in seen or seen.add(k))]


def sentiment_relevant(topic: str, cat_keywords: List[str], title: str, text: str) -> bool:
    """舆情/口碑结果相关性判定：必须命中主题名，或同时带主题关键词（消歧）。

    解决「调研目的地却抓到无关内容」：主题名命中即相关；若主题名未命中，
    则要求至少命中 1 个主题关键词，否则判为题不对版丢弃。
    单字主题不构成直击（防『山』误配『黄山/泰山』），需关键词背书。
    """
    blob = f"{title} {text}".lower()
    b = (topic or "").lower().strip()
    if not b:
        return True
    # 主题名（英文或≥2字中文）直接命中
    if len(b) >= 2 and b in blob:
        return True
    # 主题名未命中 → 必须有主题关键词背书，否则大概率跑题
    if cat_keywords:
        return any(k in blob for k in cat_keywords)
    # 没有主题信息时退回宽松：要求主题名出现（上面已判），到这里说明没命中 → 丢弃
    return False


def aggregate_sentiment(evidences: List[Dict[str, Any]], topic: str) -> Dict[str, Any]:
    """确定性舆情聚合：对一批证据做主题相关的正/中/负计数 + 主题词频 + 代表原声。

    与 analyze_sentiment（平台维度、需真实评论检索）互补：本函数作为可离线主线，
    任何写了情感标签的证据（appraisal ∈ positive/neutral/negative）优先采用，缺失时
    回退到规则判定。theme 字段或文本片段用作词频。quotes 始终绑定真实 evidence_id。
    """
    pos = neu = neg = 0
    themes: Dict[str, int] = {}
    quotes: List[Dict[str, Any]] = []
    for e in evidences:
        text = (e.get("text") or "").strip()
        lab = str(e.get("appraisal") or "").lower()
        if lab in ("positive", "pos"):
            s = "positive"
        elif lab in ("negative", "neg"):
            s = "negative"
        elif lab in ("neutral", "neu"):
            s = "neutral"
        else:
            r = _rule_sentiment(text)
            s = {"pos": "positive", "neg": "negative", "neu": "neutral"}[r]
        if s == "positive":
            pos += 1
        elif s == "negative":
            neg += 1
        else:
            neu += 1
        th = (e.get("theme") or "").strip() or "整体"
        themes[th] = themes.get(th, 0) + 1
        if text:
            quotes.append({
                "evidence_id": e.get("evidence_id", ""),
                "text": text[:160],
            })
    ordered = sorted(themes.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "topic": topic,
        "positive": pos,
        "neutral": neu,
        "negative": neg,
        "themes": [t for t, _ in ordered[:10]],
        "quotes": quotes,
    }
