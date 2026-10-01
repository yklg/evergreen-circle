"""真实网页抓取（第 5 章 通用采集）。

- httpx 拉取 HTML → trafilatura 抽正文 → BeautifulSoup 抽图片。
- 失败降级：返回 snippet 占位，trace 标 degraded，绝不抛断流程。
- **例外**：`FetchRejected` 不是"这次没抓到"，而是"根本不该去抓"的安全边界判定，
  一律上抛由调用点显式记账。把它一起降级，防线就会变成没人知道的装饰。
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import re
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(connect=8, read=20, write=5, pool=5)


class FetchRejected(RuntimeError):
    """目标不允许被服务端访问（SSRF 防线撞线）。

    与网络失败/404/反爬的差别是**性质**不是程度：那三类是"这次没抓到"，
    这一类是"不该去抓"。因此它不进入 `ok=False` 降级通道，必须让调用点显式记账。
    """


ALLOWED_SCHEMES = ("http", "https")
MAX_REDIRECTS = 5              # 计划 v3 §二 B0 的跳数上限
MAX_BODY_BYTES = 4_000_000     # 单页声明体积上限

# inet_aton 家族写法：127.1 / 2130706433 / 0x7f000001 / 017700000001。
# GHSA-5c6w-wwfq-7qqm 的绕过类别正是这一族 —— 它们在各平台 getaddrinfo 里的处置
# **不一致**（有的归一成 127.0.0.1，有的直接解析失败），所以归一不能外包给解析器。
_DOTTED_DECIMAL = re.compile(r"^\d{1,3}(?:\.\d{1,3}){0,3}$")
_HEX_LABEL = re.compile(r"^0[xX][0-9a-fA-F]+$")
_OCTAL_LABEL = re.compile(r"^0[0-7]*$")


def _ipv4_from_numeric_form(host: str) -> Optional[int]:
    """把数字形态主机归一成 32 位整数；不是数字形态返回 None（交给 DNS 那条路）。"""
    host = (host or "").strip("[]")
    if not host:
        return None
    single = host
    if _HEX_LABEL.match(single) or re.fullmatch(r"[0-9a-fA-F]{1,8}", single or ""):
        try:
            value = int(single, 16)
        except ValueError:
            return None
        return value if 0 <= value < (1 << 32) else None
    if re.fullmatch(r"\d+", single):
        value = int(single)
        if 0 <= value < (1 << 32):
            return value
        return None
    if not _DOTTED_DECIMAL.match(single):
        return None
    parts = single.split(".")
    octets: List[int] = []
    try:
        for index, raw in enumerate(parts):
            last = index == len(parts) - 1
            if _HEX_LABEL.match(raw):
                piece = int(raw, 16)
            elif len(raw) > 1 and raw.startswith("0"):
                piece = int(raw, 8)                       # 0177 → 127
            else:
                piece = int(raw, 10)
            if not last:
                if not 0 <= piece <= 255:
                    return None
                octets.append(piece)
            else:
                need = 4 - len(parts) + 1                 # 尾段吃掉剩余字节
                if not 0 <= piece < (1 << (8 * need)):
                    return None
                octets.extend(
                    [(piece >> (8 * k)) & 255 for k in range(need - 1, -1, -1)]
                )
    except (ValueError, IndexError):
        return None
    if len(octets) != 4:
        return None
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def _is_non_public(ip: "ipaddress._BaseAddress") -> bool:
    """是否**不该**由服务端去访问。

    判据取 `is_global` 而不是逐条凑 `is_private / is_link_local / ...`：
    后者会漏掉 CGNAT 100.64.0.0/10（Python 3.14 实测 `is_private=False` 但
    `is_global=False`）、基准测试段 198.18/15、以及 TEST-NET 一类保留段。
    `is_global` 的语义正好是本需求要的"公网可路由单播"。
    IPv4 映射 IPv6（::ffff:127.0.0.1）先看内核，免得外层形态骗过判定。
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _is_non_public(mapped)
    return not bool(getattr(ip, "is_global", False))


def _host_is_public(host: str) -> bool:
    """解析后判公网。**解析不出来按不可达处理**（fail closed，不是 fail open）。"""
    if not host:
        return False
    literal = host.strip("[]").rstrip(".")
    if not literal:
        return False
    if (
        _DOTTED_DECIMAL.match(literal) or _HEX_LABEL.match(literal)
        or _OCTAL_LABEL.match(literal) or literal.isdigit()
        or re.fullmatch(r"[0-9a-fA-F]{1,8}", literal)
    ):
        packed = _ipv4_from_numeric_form(literal)
        if packed is None:
            return False
        return not _is_non_public(ipaddress.IPv4Address(packed))
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        return not _is_non_public(ipaddress.ip_address(literal))
    try:
        infos = socket.getaddrinfo(literal, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if _is_non_public(ip):
            return False
    return True


def assert_public_http_url(url: str) -> None:
    """出网闸门：scheme 白名单 + 主机解析后必须是公网可路由地址。

    取 `parsed.hostname` 而不是 `netloc`：它已剥掉 `user:pass@` 与 IPv6 方括号，
    于是 `http://evil.com@127.0.0.1/` 会还原成真实主机 `127.0.0.1` 而被拒。
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise FetchRejected(f"URL 无法解析：{url!r}（{exc}）") from exc
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchRejected(
            f"只允许 {'/'.join(ALLOWED_SCHEMES)}，拒绝向 scheme {parsed.scheme!r} 发起服务端请求"
        )
    try:
        host = parsed.hostname
    except ValueError as exc:
        raise FetchRejected(f"URL 主机部分畸形：{url!r}（{exc}）") from exc
    if not host:
        raise FetchRejected(f"URL 没有主机部分：{url!r}")
    if not _host_is_public(host):
        raise FetchRejected(f"{url!r} 的主机 {host!r} 不是公网可路由地址，已拒绝")


def _fetch_following(client: "httpx.Client", url: str):
    """手动跟随重定向：**每一跳重新过闸门**，并守跳数与声明体积上限。

    原实现 `follow_redirects=True` 的毛病不是"会跟随"，而是**只对首跳判**：
    公网地址 302 到 127.0.0.1 照样读得回来。逐跳判定只能在这里做，不能外包。
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_public_http_url(current)
        resp = client.get(current, follow_redirects=False)
        if resp.status_code not in (301, 302, 303, 307, 308):
            declared = (resp.headers.get("content-length") or "").strip()
            if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                raise FetchRejected(
                    f"声明体积 {declared}B 超上限 {MAX_BODY_BYTES}B：{current!r}"
                )
            return resp
        location = resp.headers.get("location")
        if not location:
            return resp
        current = urljoin(str(resp.url), location)
    raise FetchRejected(f"重定向超过 {MAX_REDIRECTS} 跳上限：{url!r}")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def domain_of(url: str) -> str:
    """URL → 展示/统计用域名。

    必须剥掉 `user:pass@` 凭据段：这一列会进 `evidences.domain` 并被前端渲染成
    `<a href>`（`VEvidenceFeed.tsx`），原样保留等于把凭据**入库且公开展示**。
    `urlparse().hostname` 已经不含 userinfo，但它会丢端口、且对畸形主机名抛错，
    所以这里按 `@` 右切一次，既保端口又不吞凭据。
    """
    try:
        netloc = urlparse(url).netloc
    except Exception:
        return ""
    return netloc.rsplit("@", 1)[-1].lower().replace("www.", "")


# ── 用户手填网址的入口归一（计划 v3 §二 B1 · 唯一实现，B7/B8 共用）──────
MAX_SOURCE_URLS = 10           # 单次任务可填条数上限
MAX_SOURCE_URL_LEN = 256       # 单条字符上限（偏好层与入口同用这一个数）


def canonicalize_user_url(raw: Any) -> tuple[str, str]:
    """把一条用户输入归一成可抓取形态，返回 `(canonical, reason)`。

    `reason` 为空串表示可用；非空表示这条被拒（`canonical` 同时为空）。
    拒绝而不是"静默少一条"是硬要求：入口丢掉的网址在覆盖率里根本不存在，
    用户看到"N 条已读取"却不知道少了一填。

    归一动作（顺序即语义）：
      1. 去首尾空白；
      2. 缺协议自动补 `https://`（计划待确认 3 已拍板：补并显示归一化结果）；
      3. 协议必须是 http/https —— `file://`、`gopher://`、`javascript:` 一律拒，
         这道白名单与出网闸门 `assert_public_http_url` 同源；
      4. **剥掉凭据段** `user:pass@`（B1）；
      5. 丢掉 `#fragment` —— 它不改变服务端抓到的内容，留着只会让同址异写成两条。
    """
    text = str(raw or "").strip()
    if not text:
        return "", "空输入"
    if len(text) > MAX_SOURCE_URL_LEN:
        return "", f"超过 {MAX_SOURCE_URL_LEN} 字符上限（{len(text)}）"
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError as exc:
        return "", f"无法解析：{exc}"
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return "", f"只允许 http/https，收到 {parsed.scheme!r}"
    try:
        host = parsed.hostname
    except ValueError as exc:
        return "", f"主机部分畸形：{exc}"
    if not host:
        return "", "没有主机部分"
    try:
        port = parsed.port
    except ValueError as exc:
        return "", f"端口非法：{exc}"
    # `hostname` 已剥掉 IPv6 字面量的方括号，这里按"主机本身含冒号"还原，
    # 不能按"拼出来的 netloc 含冒号"判 —— 那会把 host:port 也一起框进去（a.example:8443）。
    host_part = f"[{host}]" if ":" in host else host
    netloc = host_part if port is None else f"{host_part}:{port}"
    path = parsed.path or "/"
    canonical = f"{parsed.scheme.lower()}://{netloc}{path}"
    if parsed.query:
        canonical += f"?{parsed.query}"
    return canonical, ""


def normalize_user_url_list(raws: Any,
                            limit: int = MAX_SOURCE_URLS) -> Dict[str, Any]:
    """整份清单的入口卫生：去空 → 逐条归一 → 按归一化结果去重 → 截断到 limit。

    返回 `{urls, rejected, truncated}`：三者都要能显式记账（计划 §二 B1 / §四.2）。
    去重键是**归一化后**的网址，不是原始串 —— 否则 `example.com/a` 与
    `https://example.com/a` 会被算成两条信源，覆盖率分母虚高。
    """
    items = raws if isinstance(raws, (list, tuple)) else []
    seen: set = set()
    urls: List[str] = []
    rejected: List[Dict[str, str]] = []
    for raw in items:
        # 去空：空白项不是"被拒的网址"，不该占拒因清单（否则用户会看到一串空字符串报错）
        if not str(raw or "").strip():
            continue
        canonical, reason = canonicalize_user_url(raw)
        if not canonical:
            rejected.append({"url": str(raw)[:MAX_SOURCE_URL_LEN], "reason": reason})
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        urls.append(canonical)
    truncated = max(0, len(urls) - limit)
    return {"urls": urls[:limit], "rejected": rejected, "truncated": truncated}


def fetch_page(url: str, *, fallback_snippet: str = "") -> Dict[str, Any]:
    """抓取单页正文 + 图片。返回 {text, images, ok, degraded}。

    `FetchRejected` 上抛（安全判定不可降级），其余异常一律降级为 snippet 占位。
    """
    assert_public_http_url(url)
    result: Dict[str, Any] = {
        "url": url,
        "text": fallback_snippet,
        "images": [],
        "og_image": "",
        "ok": False,
        "degraded": True,
    }
    try:
        with httpx.Client(
            timeout=_TIMEOUT,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        ) as client:
            r = _fetch_following(client, url)
            r.raise_for_status()
            # 编码兜底：httpx 按响应头 charset 解码，遇错误声明会乱码。
            # 若检测到乱码，用 apparent_encoding（chardet/charset_normalizer）重解码。
            html = r.text
            try:
                from app.core.textquality import is_garbled
                if is_garbled(html[:2000]):
                    enc = r.encoding or ""
                    for cand in ("utf-8", "gbk", "gb18030"):
                        if cand.lower() == enc.lower():
                            continue
                        try:
                            redecoded = r.content.decode(cand, errors="strict")
                            if not is_garbled(redecoded[:2000]):
                                html = redecoded
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        text = _extract_text(html) or fallback_snippet
        # 乱码正文丢弃，退回 snippet
        try:
            from app.core.textquality import is_garbled
            if text and is_garbled(text):
                text = fallback_snippet
        except Exception:
            pass
        images = _extract_images(html, url)
        og = _extract_og_image(html, url)
        result.update(
            {"text": text[:4000], "images": images[:6], "og_image": og,
             "title": _extract_title(html),
             "ok": True, "degraded": False}
        )
    except FetchRejected:
        raise
    except httpx.HTTPStatusError as exc:
        # 状态码要留住：调用方需要把"404 不存在"和"403 反爬"分开记账（用户可见的
        # 失败原因不能都写成"没抓到"），但降级本身不变。
        result["http_status"] = exc.response.status_code
        result["error"] = type(exc).__name__
    except Exception as exc:
        # 降级保留 snippet
        result["error"] = type(exc).__name__
    result["captured_at"] = _now()
    return result


def _extract_text(html: str) -> str:
    try:
        import trafilatura

        out = trafilatura.extract(html, include_comments=False, include_tables=False)
        if out:
            return out.strip()
    except Exception:
        pass
    # 退而求其次：BeautifulSoup 抓段落
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n".join(p for p in ps if len(p) > 20)
    except Exception:
        return ""


def _extract_title(html: str) -> str:
    """抓页面标题：og:title 优先，`<title>` 兜底（用户指定信源入链时标题不能空）。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("meta", attrs={"property": "og:title"})
        cand = (tag.get("content") or "").strip() if tag else ""
        if not cand:
            cand = soup.title.get_text(strip=True) if soup.title else ""
        return cand[:120]
    except Exception:
        return ""


def _extract_images(html: str, base_url: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            if _looks_like_icon(src):
                continue
            full = urljoin(base_url, src)
            alt = (img.get("alt") or "").strip()
            out.append({"src": full, "alt": alt, "source_url": base_url})
            if len(out) >= 8:
                break
    except Exception:
        pass
    return out


def _extract_og_image(html: str, base_url: str) -> str:
    """优先抓取社媒/媒体分享卡片用的 OG/Twitter 预览大图（最具代表性、可溯源）。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for prop in (
            ("property", "og:image"),
            ("property", "og:image:url"),
            ("name", "twitter:image"),
            ("name", "twitter:image:src"),
            ("itemprop", "image"),
        ):
            tag = soup.find("meta", attrs={prop[0]: prop[1]})
            if tag and tag.get("content"):
                src = tag["content"].strip()
                if src and not src.startswith("data:"):
                    return urljoin(base_url, src)
        # link rel image_src 兜底
        link = soup.find("link", attrs={"rel": "image_src"})
        if link and link.get("href"):
            return urljoin(base_url, link["href"].strip())
    except Exception:
        pass
    return ""


_ICON_HINTS = ("logo", "icon", "sprite", "avatar", "favicon", "blank", "spacer", "pixel", "1x1")


def _looks_like_icon(src: str) -> bool:
    s = src.lower()
    return any(h in s for h in _ICON_HINTS)
