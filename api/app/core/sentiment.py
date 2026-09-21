"""舆情分析（第 6 章）：真实评论情感分类 + 观点阵营 + 体量统计。

数据全部来自真实站内检索到的评论（带真实链接）。无评论则如实返回空结构，
绝不使用任何 demo 假数据。LLM 可用时走 LLM 情感分类，否则规则兜底。
观点阵营占比归一化到 100%（修复历史 >100% bug）。抖音永远排第一。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.llm import chat_json
from app.core.platforms import PLATFORMS

# 各平台元数据统一从平台注册表（app.core.platforms）派生，避免多份注册表漂移。
# 注：抖音永远排第一（与历史行为一致）。
PLATFORM_SITES = {k: p.search_site for k, p in PLATFORMS.items()}
PLATFORM_ORDER = list(PLATFORMS.keys())
PLATFORM_LABEL = {k: p.label for k, p in PLATFORMS.items()}

_POS = ["好", "强", "喜欢", "推荐", "优秀", "值得", "值得去", "香", "爱了", "性价比",
        "流畅", "丝滑", "靠谱", "出片", "惊艳", "vlog", "美", "舒服", "不虚此行"]
_NEG = ["差", "贵", "卡", "失望", "垃圾", "退", "坑", "难用", "bug", "缺点", "拉胯", "翻车",
        "不值", "宰客", "踩坑", "排队", "人挤", "照骗", "劝退", "避雷", "排队久"]


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


def _llm_classify(destination: str, comments: List[Dict[str, Any]]) -> bool:
    """用 LLM 给每条真实评论打 pos/neu/neg，写回 comment["sentiment"]。

    成功返回 True，失败返回 False（调用方走规则兜底）。
    """
    if not comments:
        return False
    items = [{"i": i, "text": (c.get("text") or "")[:200]} for i, c in enumerate(comments)]
    data = chat_json(
        [
            {"role": "system", "content": "你是资深旅游舆情分析师，对每条用户评论判断它对目标目的地/城市的情感倾向。"},
            {"role": "user", "content": (
                f"目标目的地：{destination}\n\n下面是若干条真实用户评论，请逐条判断情感，"
                f"只能是 pos（正面/推荐）、neu（中立/观望）、neg（负面/劝退）三选一。\n"
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


def analyze_sentiment(destination: str, comments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """comments: [{text, platform, url, title}]（均为真实检索结果）。返回 SentimentResult 结构。"""
    if not comments:
        return _empty_result()

    # 逐条打情感：LLM 优先，失败规则兜底
    if not _llm_classify(destination, comments):
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
    camps = _build_camps(destination, comments, total)

    # 平台原声墙（各平台代表性真实评论，抖音优先）+ LLM 金句摘抄
    voices = _build_voices(comments)
    highlights = _extract_highlights(destination, comments)

    # 平台排序：抖音永远第一
    ordered_platform = {}
    for p in PLATFORM_ORDER:
        if p in by_platform:
            ordered_platform[p] = by_platform[p]
    for p in by_platform:
        if p not in ordered_platform:
            ordered_platform[p] = by_platform[p]

    # 按目的地聚合：不同目的地的口碑对比（支持「不同平台/目的地观点聚类」）
    by_destination = _build_by_destination(comments)

    return {
        "overall": overall_pct,
        "overall_count": overall,
        "by_platform": ordered_platform,
        "by_destination": by_destination,
        "timeline": [],  # 评论无可靠日期，不伪造时间线
        "camps": camps,
        "voices": voices,
        "highlights": highlights,
        "sample_size": len(comments),
    }


def _build_by_destination(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按目的地聚合情感分布与样本量（不同目的地口碑横向对比）。"""
    agg: Dict[str, Dict[str, int]] = {}
    for c in comments:
        b = (c.get("destination") or "").strip()
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
        out.append({"destination": b, "sample": n, "pos": pct["pos"], "neu": pct["neu"], "neg": pct["neg"]})
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


def _extract_highlights(destination: str, comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                    "最能反映目的地真实口碑的『金句短语』（可直接摘抄原句中的关键片段，保持真实口吻）。"
                    "只挑 4-6 条最有冲击力或最具代表性的，覆盖推荐与劝退不同声音。"
                    "严格输出 JSON 数组，每项 {\"i\": 原评论序号, \"phrase\": \"金句短语(不超过30字)\"}，"
                    "phrase 必须忠于原评论含义，不得编造。不要多余文字。"
                )},
                {"role": "user", "content": f"目标目的地：{destination}\n评论列表：\n{items}"},
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


def _build_camps(destination: str, comments: List[Dict[str, Any]], total: int) -> List[Dict[str, Any]]:
    pos = [c for c in comments if c.get("sentiment") == "pos"]
    neg = [c for c in comments if c.get("sentiment") == "neg"]
    neu = [c for c in comments if c.get("sentiment") == "neu"]

    groups = [
        (pos, f"推荐派：认可{destination}的体验", f"该阵营用户普遍认可{destination}在景色、体验或性价比上的优势。"),
        (neg, f"劝退派：点出{destination}的短板", f"该阵营用户对{destination}的价格、人流或服务存在明确顾虑。"),
        (neu, "观望派：理性比较中", "该阵营尚在多方对比、未形成明确倾向，关注后续体验反馈。"),
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
