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
import threading
import time
from typing import Any, Dict, List, Optional

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

# 服务商级终态码：鉴权/欠费——重试与换查询词都无意义。
# 429 不在此列：它是账号级 QPS 节流（博查文案自述「请稍后重试」），属瞬态，
# 真机 r_b14e555d 实证——逐景点二查首发 429 即被当终态中止整阶段，核查表满屏占位。
_PROVIDER_TERMINAL_CODES = (401, 403)
_THROTTLE_CODES = (429,)
_PROVIDER_TERMINAL_HINTS = ("余额", "配额", "鉴权", "quota", "unauthorized")


class SearchProviderError(RuntimeError):
    """服务商级终态错误（Key 无效 / 欠费 / 限流退避用尽）。

    multi_search 对它**不做逐条容错、直接冒泡**（一条即止，不再烧剩余查询），
    保证真因如实送达上层，而不是被吞成「0 结果」。
    """


class _Throttled(RuntimeError):
    """账号级 QPS 节流（429）：同一查询按退避阶梯重发，不即判终态。"""


# 退避阶梯（对齐 llm.py _RATE_LIMIT_BACKOFFS 先例）：首发不等待，其后逐档退避；
# 阶梯用尽仍被限流才升格为服务商终态。
_THROTTLE_BACKOFFS = (2.0, 5.0, 10.0)
# 出站最小间隔：限流按账号 QPS 计，多线程 fan-out 会把请求叠成突发打满配额，
# 故在唯一出站收口处排队（持锁只睡「距下次可发的差额」，请求本身不占锁）。
_MIN_INTERVAL_S = 0.6
_sleep = time.sleep          # 测试注入点：节流/退避不真等
_pace_lock = threading.Lock()
_next_send_at = 0.0


def _pace() -> None:
    """账号级出站节流：保证任意两次真实请求之间至少间隔 _MIN_INTERVAL_S。"""
    global _next_send_at
    with _pace_lock:
        wait = _next_send_at - time.monotonic()
        if wait > 0:
            _sleep(wait)
        _next_send_at = time.monotonic() + _MIN_INTERVAL_S


def _provider_error(code: int, msg: str) -> RuntimeError:
    if code in _THROTTLE_CODES:
        return _Throttled(msg)
    if code in _PROVIDER_TERMINAL_CODES or any(h in msg.lower() for h in _PROVIDER_TERMINAL_HINTS):
        return SearchProviderError(msg)
    return RuntimeError(msg)


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
        raise SearchProviderError("未配置 BOCHA_API_KEY，请在「模型配置」页面填写后重试")

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
    body: dict = {}
    throttled: Optional[_Throttled] = None
    for delay in (0.0,) + _THROTTLE_BACKOFFS:
        if delay:
            _sleep(delay)
        _pace()
        try:
            body = _bocha_once(endpoint, headers, payload, timeout)
            break
        except _Throttled as t:
            throttled = t      # QPS 打满：退避后重发同一条查询，不即判终态
    else:
        raise SearchProviderError(str(throttled))

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


def _bocha_once(endpoint: str, headers: dict, payload: dict,
                timeout: "httpx.Timeout") -> dict:
    """单次博查请求：返回响应 body；429 → _Throttled，鉴权/欠费 → 服务商终态。"""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.post(endpoint, headers=headers, json=payload)
        if r.status_code != 200:
            msg = _BOCHA_ERR.get(r.status_code, f"博查接口返回 HTTP {r.status_code}")
            raise _provider_error(r.status_code, msg)
        body = r.json()

    # 博查在 HTTP 200 时仍可能在 body 内返回错误码
    code = body.get("code")
    if code is not None and int(code) != 200:
        msg = _BOCHA_ERR.get(int(code), body.get("msg") or f"博查返回业务码 {code}")
        raise _provider_error(int(code), msg)
    return body


def search(query: str, *, num: int = 10, site: Optional[str] = None,
           freshness: str = "noLimit") -> list[dict]:
    """对外入口：博查搜索。失败抛给上层处理。"""
    return search_bocha(query, num=num, site=site, freshness=freshness)


def search_provider_probe(*, query: str = "景点 开放时间 门票", num: int = 1) -> Dict[str, Any]:
    """搜索服务商可用性探针：`{state, ready, reason, hits}`。

    为什么要有它：批次 0 / B2 的门槛是**条件式**的 —— `probed_spots == 0 ∨ llm_outcome != ok`
    判「环境未就绪」而非「链路未通」。这个判据要能执行，就得在**烧掉整份 deep 预算之前**
    一次问出「现在到底有没有网」。全仓此前只有 LLM 侧的能力探明（`llm.record_model_fact`），
    搜索侧没有 healthcheck。

    ⚠️ **刻意不落库、不缓存**：探针答案是**时点事实**（欠费会充值、key 会补填、429 会过去）。
    把一次探测持久化成「能力位」，就是把时点计数当不变量用 —— 本轮已经在「存量 0 条」那条
    前提上栽过一次（活库上的计数不能当不变量，见计划 v4.1 偏差 1）。⇒ 每次判定当场再探一次。

    `state ∈ ready / no_key / terminal / transient / error`；`hits == 0 且 state == ready` 是
    合法组合（鉴权与配额都通、只是这条探针词没命中），上层按 needs 自行取舍。
    """
    try:
        rows = search(query, num=num)
        return {"state": "ready", "ready": True, "reason": "",
                "hits": len(rows) if isinstance(rows, list) else 0}
    except SearchProviderError as e:
        msg = str(e)
        if "未配置" in msg or "API_KEY" in msg.upper():
            return {"state": "no_key", "ready": False, "reason": msg, "hits": 0}
        if any(h in msg for h in _PROVIDER_TERMINAL_HINTS) or "无效" in msg:
            return {"state": "terminal", "ready": False, "reason": msg, "hits": 0}
        if "频率超限" in msg:
            # 429 不是终态（`_THROTTLE_CODES` 同判据：search() 内部已按退避阶梯重发过一轮，
            # 走到这里说明退避用尽 —— 仍属"过一会儿再来"，不得与欠费同判）
            return {"state": "transient", "ready": False, "reason": msg, "hits": 0}
        return {"state": "error", "ready": False, "reason": msg, "hits": 0}
    except Exception as e:  # noqa: BLE001
        # 探针的产物是**分类**，不是异常：这里吞掉的是「归类完成」，不是「失败被藏起来」——
        # 未归类的一律落到 state=error 并带上原文，调用方据此判「环境未就绪」。
        return {"state": "error", "ready": False, "reason": f"{type(e).__name__}: {e}", "hits": 0}


def multi_search(
    queries: List[str],
    *,
    num: int = 10,
    site: Optional[str] = None,
    freshness: str = "noLimit",
) -> list[dict]:
    """跑多条查询，按 URL 去重聚合。单条瞬时失败跳过（尽力而为）；
    服务商级终态错误（SearchProviderError）直接冒泡，一条即止。"""
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
        except SearchProviderError:
            raise
        except Exception:
            continue
    return out
