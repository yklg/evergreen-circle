"""证据采集（M3 自 engine.py 原文迁出 · 行为零变化）。

信源分组采集、官方信源识别、平台分类、去重指纹、证据摘要、采集事件发射。
依赖：search/fetcher/credibility/dedup/platforms/textquality 叶子 + _util；不反向依赖 engine。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.core import fetcher, search
from app.core.credibility import freshness_days, score_evidence
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core.fetcher import domain_of
from app.core.models import Evidence
from app.core.platforms import classify_platform
from app.core.textquality import is_relevant_content

from ._util import _now, _sid


# 明显非官网的特征（命中则不可能是 official）
_NON_OFFICIAL_HINTS = (
    "blog", "news", "wiki", "csdn", "jianshu", "juejin", "zhihu", "baijiahao",
    "toutiao", "medium", "wordpress", "cnblogs", "segmentfault", "oschina",
)


DAG_NODES = [
    {"id": "intake", "label": "需求理解"},
    {"id": "orchestrator", "label": "编排派遣"},
    {"id": "collect", "label": "证据采集"},
    {"id": "analyze", "label": "交叉分析"},
    {"id": "spots", "label": "景点实体"},
    {"id": "write", "label": "报告撰写"},
    {"id": "audit", "label": "质检审裁"},
    {"id": "done", "label": "签发交付"},
]


def _ev(type_: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": type_, "data": data}


def _source_type(url: str) -> str:
    d = domain_of(url)
    plat = classify_platform(url)        # 注册表驱动：社媒平台自动识别
    if plat:
        return plat
    if "tieba.baidu" in d or "douban" in d or "v2ex" in d or "reddit" in d or "quora" in d:
        return "zhihu"  # 论坛/问答类归到社区口碑
    # 财报/投关页
    if any(k in (d + url) for k in ("ir.", "investor", "annualreport", "sec.gov", "10-k", "财报", "年报")):
        return "financial_report"
    # 新闻媒体（含国内主流与科技财经媒体的常见域名）
    if any(k in d for k in ("news", "36kr", "sina", "163.com", "qq.com", "ifeng", "sohu",
                            "huxiu", "tmtpost", "caixin", "yicai", "people.com", "xinhuanet",
                            "thepaper", "cls.cn", "stcn", "eastmoney", "cnbeta", "leiphone",
                            "iyiou", "geekpark", "techcrunch", "theverge", "bloomberg")):
        return "news"
    if not d:
        return "web"
    # 仅当域名形态像「官方站点」（短主域、无新闻/博客特征）时才判 official；
    # 其余一律归为普通网页，避免把不权威的新闻/博客误判为官网（对应需求：置信度修正）。
    if _looks_official(d):
        return "official"
    return "web"


def _looks_official(domain: str) -> bool:
    """粗略判断是否像官方站点：层级浅（主域+顶级域）、不含博客/新闻/社区特征。"""
    if any(h in domain for h in _NON_OFFICIAL_HINTS):
        return False
    parts = [p for p in domain.split(".") if p]
    # 形如 gov.cn / dali.gov.cn / example.com —— 2-3 段且主体不太长
    if len(parts) <= 3 and parts and len(parts[0]) <= 18:
        return True
    return False


def _region_keywords(region: str) -> List[str]:
    """把行政区/国家短语拆成关键词，用于舆情相关性消歧（如『云南省大理州』→ [云南省, 大理州, 云南, 大理]）。"""
    if not region:
        return []
    kws: List[str] = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{1,}", region.lower()):
        kws.append(w)
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", region):
        kws.append(w.lower())
    # 去重保序
    seen: set = set()
    return [k for k in kws if not (k in seen or seen.add(k))]


def _sentiment_relevant(destination: str, region_keywords: List[str], title: str, text: str) -> bool:
    """舆情结果相关性判定：必须命中目的地名，或同时带有地区关键词（消歧）。

    解决「调研大理抓到同名内容」：目的地名命中即相关；若目的地名未命中，
    则要求至少命中 1 个地区关键词，否则判为题不对版丢弃。
    """
    blob = f"{title} {text}".lower()
    b = (destination or "").lower().strip()
    if not b:
        return True
    # 目的地名（英文或≥2字中文）直接命中
    if len(b) >= 2 and b in blob:
        return True
    # 目的地名未命中 → 必须有地区关键词背书，否则大概率跑题
    if region_keywords:
        return any(k in blob for k in region_keywords)
    # 没有地区信息时退回宽松：要求目的地名出现（上面已判），到这里说明没命中 → 丢弃
    return False


# ── 采集单目的地（抽出供补采复用）───────────────────────────
def _collect_destination(destination: str, angles: List[str], collector: str,
                         fetch_limit: int, freshness: str,
                         existing_urls: set,
                         groups: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """采集单个目的地：搜索 + 抓取 + 构造 Evidence。返回 {evidences, images, found, dup_skipped, groups}。

    纯同步函数，供 asyncio.to_thread 调用；existing_urls 用于跨轮 URL 去重；
    groups 用于内容级信源组归一化（v2.1：同质转载归并为一组，杜绝转载冒充多源），
    由 run_pipeline 跨目的地/跨轮维护（docstring 注明：groups 池由 run_pipeline 主线程独占维护）。
    """
    queries = [f"{destination} {a}" for a in angles]
    results = search.multi_search(queries, num=10, freshness=freshness)
    out_ev: List[Evidence] = []
    out_img: List[Dict[str, Any]] = []
    fetched = 0
    dup_skipped = 0
    groups = groups or []
    seen_gids = {g["id"] for g in groups if g.get("id")}
    for r in results:
        if fetched >= fetch_limit:
            break
        url = r.get("url", "")
        if not url or url in existing_urls:
            continue
        page = fetcher.fetch_page(url, fallback_snippet=r.get("snippet", ""))
        ok = page.get("ok")
        text = (page.get("text") or r.get("snippet", "")).strip()
        if not text:
            continue
        # 正文二次相关性校验（剔除题不对版）
        if not is_relevant_content(text, [destination], destination):
            continue
        # 内容级信源组归一化：同质转载 → 归并既有组、跳过取证（不冒充独立信源）
        gid, _rep = group_new_text(text, groups)
        if gid:
            dup_skipped += 1
            for g in groups:
                if g.get("id") == gid:
                    g.setdefault("urls", []).append(url)
                    break
            continue
        existing_urls.add(url)
        stype = _source_type(url)
        captured = page.get("captured_at", _now())
        # 用 search 返回的 datePublished（captured_at）做时效性判断更准
        pub_date = r.get("captured_at", "")
        cred = score_evidence(
            url, stype, captured_at=pub_date or captured,
            has_publish_date=bool(pub_date), ok_fetch=bool(ok), excerpt=text[:280],
        )
        fdays = freshness_days(pub_date or captured)
        # 开新信源组（指纹为空/短文本也独立成组）
        gid2 = _sid("g")
        while gid2 in seen_gids:
            gid2 = _sid("g")
        seen_gids.add(gid2)
        groups.append({"id": gid2, "tokens": tokenize(text), "urls": [url]})
        ev = Evidence(
            evidence_id=_sid("e"),
            source_url=url,
            source_type=stype,
            title=r.get("title", destination),
            excerpt=text[:280],
            captured_at=pub_date or captured,
            credibility=cred,
            collected_by=collector,
            image_urls=[im["src"] for im in page.get("images", [])][:3],
            destination=destination,
            domain=domain_of(url),
            freshness_days=fdays,
            content_hash=content_fingerprint(text),
            source_group=gid2,
        )
        ev._full_text = text[:1500]  # type: ignore[attr-defined]
        out_ev.append(ev)
        # 配图
        og = (page.get("og_image") or "").strip()
        pics = page.get("images", []) or []
        fig_src = og or (pics[0]["src"] if pics else "")
        if fig_src:
            fig_alt = "" if og else (pics[0].get("alt", "") if pics else "")
            out_img.append({
                "src": fig_src, "alt": fig_alt, "title": r.get("title", destination),
                "source_url": url, "domain": domain_of(url),
                "source_type": stype, "destination": destination, "evidence_id": ev.evidence_id,
            })
        fetched += 1
    return {"evidences": out_ev, "images": out_img, "found": len(results),
            "dup_skipped": dup_skipped, "groups": groups}


# ── 分析：LLM 基于真实证据产出论点 + 结构化对比 ───────────────
def _evidence_digest(evidences: List[Evidence], limit: int = 28) -> str:
    lines = []
    for e in evidences[:limit]:
        d = domain_of(e.source_url)
        lines.append(f"[{e.evidence_id}|{e.source_type}|{d}] {e.title}：{e.excerpt}")
    return "\n".join(lines)
