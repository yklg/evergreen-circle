"""通用搜索采集（第 16 章）。

- 主用博查 Bocha Web Search API（有 key 时），对中文/国内站点友好。
  Endpoint: POST https://api.bocha.cn/v1/web-search
- multi_search：一次跑多条查询并按 URL 去重，用于深度调研多角度检索。
- 相关性过滤：剔除标题/摘要完全不含关键词的结果（避免题不对版）。
- 尽力而为：单条查询失败不抛断，返回已得结果。
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import List, Optional

import httpx

from app.core.runtime_config import get_effective_settings

# 博查异常码 → 人话提示
_BOCHA_ERR = {
    400: "请求参数错误（如缺少 query）",
    401: "博查 API Key 无效或缺失",
    403: "博查账户余额不足，请充值",
    429: "博查请求频率超限，请稍后重试",
    500: "博查搜索服务内部异常",
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_relevant(query: str, title: str, snippet: str) -> bool:
    """简易相关性过滤：检查搜索 query 的核心词是否出现在标题或摘要中。

    避免搜 "京都 交通攻略" 返回汽水音乐之类完全不相关的结果。
    提取 query 中的英文目的地词/中文关键词做匹配。
    """
    if not query:
        return True
    text = f"{title} {snippet}".lower()
    q = query.lower()

    # 提取英文单词（目的地名等），3 个字符以上的都要在结果中出现至少一个
    english_words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", q)
    # 提取中文关键词（2 个字以上的中文字符串）
    chinese_words = re.findall(r"[\u4e00-\u9fa5]{2,}", q)

    must_match = []
    # 英文目的地词（第一个英文词通常是目的地名，必须匹配）
    if english_words:
        must_match.append(english_words[0])
    # 中文第一个名词短语也尽量匹配
    if chinese_words:
        must_match.append(chinese_words[0])

    if not must_match:
        return True

    # 至少要有一个核心词命中（英文不区分大小写）
    for kw in must_match:
        if kw.lower() in text:
            return True

    # 宽松二次校验：只要有任意 2 个查询词命中即可
    all_kw = english_words + chinese_words
    hits = sum(1 for kw in all_kw if kw.lower() in text)
    return hits >= 2


def search_bocha(
    query: str,
    *,
    num: int = 10,
    site: Optional[str] = None,
    freshness: str = "noLimit",
) -> list[dict]:
    """用博查 Bocha Web Search 做网页搜索。

    - `site`: 可选，形如 "douyin.com" / "zhihu.com"，映射到博查 include 限定域名。
    - `freshness`: 时效性过滤（noLimit/oneDay/oneWeek/oneMonth/oneYear），聚焦最新数据。
    - 返回的每条都带 title + url + snippet + source + captured_at，便于后续抓取正文。
    - 自动做相关性过滤，剔除明显不相关的结果。
    """
    settings = get_effective_settings()
    if not settings.get("bocha_api_key"):
        raise RuntimeError("未配置 BOCHA_API_KEY，请在「模型配置」页面填写后重试")

    # count 取值范围 1-50
    count = max(1, min(int(num), 50))
    # 多取一些以预留过滤余量（相关性过滤会淘汰一部分）
    fetch_count = min(count * 2, 50)
    payload = {
        "query": query,
        "summary": True,
        "freshness": freshness or "noLimit",
        "count": fetch_count,
    }
    if site:
        # 博查用 include 限定网站范围（多个用 | 分隔）
        payload["include"] = site

    endpoint = f"{str(settings.get('bocha_base_url') or '').rstrip('/')}/web-search"
    headers = {
        "Authorization": f"Bearer {settings.get('bocha_api_key')}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        connect=8, read=float(settings.get("search_timeout") or 30), write=5, pool=5
    )
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.post(endpoint, headers=headers, json=payload)
        if r.status_code != 200:
            msg = _BOCHA_ERR.get(r.status_code, f"博查接口返回 HTTP {r.status_code}")
            raise RuntimeError(msg)
        body = r.json()

    # 博查在 HTTP 200 时仍可能在 body 内返回错误码
    code = body.get("code")
    if code is not None and int(code) != 200:
        msg = _BOCHA_ERR.get(int(code), body.get("msg") or f"博查返回业务码 {code}")
        raise RuntimeError(msg)

    data = body.get("data") or {}
    web_pages = (data.get("webPages") or {}).get("value") or []

    results: list[dict] = []
    for item in web_pages:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        if not url:
            continue
        # summary（完整摘要，已开启）优先，缺失时退回 snippet
        snippet = (item.get("summary") or item.get("snippet") or "").strip()
        title = (item.get("name") or "").strip()
        # 相关性过滤：剔除明显不相关的结果（题不对版）
        if not _is_relevant(query, title, snippet):
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": item.get("siteName") or item.get("displayUrl", ""),
                # 标准发布时间用 datePublished（dateLastCrawled 有 UTC+8 坑，不用）
                "captured_at": item.get("datePublished") or _now(),
            }
        )
        if len(results) >= count:
            break
    return results


def search(query: str, *, num: int = 10, site: Optional[str] = None,
           freshness: str = "noLimit") -> list[dict]:
    """对外入口：博查搜索。失败抛给上层处理。"""
    return search_bocha(query, num=num, site=site, freshness=freshness)


def multi_search(
    queries: List[str],
    *,
    num: int = 10,
    site: Optional[str] = None,
    freshness: str = "noLimit",
) -> list[dict]:
    """跑多条查询，按 URL 去重聚合。单条失败跳过（尽力而为）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for q in queries:
        try:
            for r in search(q, num=num, site=site, freshness=freshness):
                url = r.get("url", "")
                key = url or r.get("title", "")
                if not key or key in seen:
                    continue
                seen.add(key)
                r["query"] = q
                out.append(r)
        except Exception:
            continue
    return out
