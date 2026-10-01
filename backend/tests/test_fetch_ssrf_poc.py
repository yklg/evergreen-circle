"""SSRF 非破坏式取证（实施计划 v3 §九 · TC-13 / TC-19；B0 落地后均为正式断言）。

为什么要有这个文件（而不是只在函数层断言"抛了拒绝异常"）
------------------------------------------------------
外部经验 **E3**（GHSA-5c6w-wwfq-7qqm 的验证手法）：防护声明容易，**证明它真的没发出请求**
才算数。本文件在 127.0.0.1 上起一个会**计数**的最小 HTTP server，断言的是服务端侧的观测：
被指向内网的 URL 提交后对端一次都没被碰。函数返回了什么不算证据，对端没被请求到才算。

判据来源
--------
- 命中计数取自本文件自己的 handler（`do_GET` 里 `_Counting.hits.append()`），不解析日志。
- 原形状 `follow_redirects=True` / `timeout=connect 8, read 20` 见改动前的 `fetcher.py:43-45`
  与 `:18`；B0 改为 `follow_redirects=False` + `_fetch_following()` 逐跳判定。
- 计划 v3 §二 B0 的常量：`MAX_REDIRECTS = 5`、`MAX_BODY_BYTES = 4MB`。

⚠️ 本文件的已知局限（写清楚，不伪造覆盖）
------------------------------------------
本机没有可控的公网主机，三条用例的首跳都落在 loopback，因此都会在**第 0 跳**被拒。由此：
  * 能证明"整条链一次都没发出"；
  * **不能**区分「只校验首跳」与「每一跳都校验」，也**测不到** `MAX_REDIRECTS` 的纯值
    （上限只有在首跳合法时才可能被触及）。
逐跳与跳数上限的真验证需要下面任一接缝，届时补独立用例（计划 §10.4 已登记为未覆盖）：
  (a) `fetch_page()` 接受可注入的 `httpx` transport；
  (b) 把逐跳判定抽成可直接驱动的纯函数（入参为 Location 头 / 目标 URL）。
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import fetcher


class _Counting(BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):        # noqa: N802 —— BaseHTTPRequestHandler 的约定方法名
        _Counting.hits.append(self.path)
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/private")
            self.end_headers()
            return
        if self.path.startswith("/hop"):
            self.send_response(302)
            self.send_header("Location", "/hop")
            self.end_headers()
            return
        body = b"<html><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


@pytest.fixture
def local_target():
    """在 127.0.0.1 上起一个会计数的 server，返回 (base_url, hits)。"""
    _Counting.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Counting)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", _Counting.hits
    finally:
        srv.shutdown()
        srv.server_close()


def test_pointing_at_loopback_leaves_the_target_untouched(local_target):
    """TC-13：内网地址必须一次都没被请求（服务端侧观测，非函数返回值）。"""
    base_url, hits = local_target

    with pytest.raises(fetcher.FetchRejected):
        fetcher.fetch_page(f"{base_url}/private")

    assert hits == [], f"内网对端收到 {len(hits)} 次请求（{hits}）—— 防护未生效"


def test_redirect_chain_to_internal_is_never_fetched(local_target):
    """TC-19：302 指向内网时不得抓取。局限见模块 docstring。"""
    base_url, hits = local_target

    with pytest.raises(fetcher.FetchRejected):
        fetcher.fetch_page(f"{base_url}/redirect")

    assert "/private" not in hits, f"跟随重定向打到了内网目标：{hits}"


def test_infinite_redirect_chain_is_rejected_before_the_first_hop(local_target):
    """无限自跳转链在第 0 跳即被拒 ⇒ 对端一次都不该被碰。

    这条**不**验证 `MAX_REDIRECTS` 的数值（见模块 docstring），别把它当上限已验证。
    """
    base_url, hits = local_target

    with pytest.raises(fetcher.FetchRejected):
        fetcher.fetch_page(f"{base_url}/hop")

    assert hits == [], f"第 0 跳就该被拒，对端却被请求了 {len(hits)} 次：{hits[:3]}…"
