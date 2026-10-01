"""SSRF 内网访问防护（实施计划 v3 §九 · TC-11/12/14/15/17/18）。

**现状（10-02 第 22 轮复核）**：防线已落地，本文件 **0 条 xfail 标记**（`grep -c "^@pytest.mark.xfail"` = 0），
全部为正式断言。标题原先写的"全条 `xfail(strict=True)`"是 B0 落地前的旧状态，与正文脱节会误导下一个
读它的人（第 22 轮 R22-8）；随之删掉的还有已无消费者的 `_X_B1` 标记 —— 它记的那笔「netloc 凭据归一」欠账
已随 §二 B1 落地转正，见 `test_credential_in_netloc_is_stripped_before_it_reaches_storage_or_ui` 的转正记录。

为什么这些用例钉的是「被拒绝」而不是「没抓到」
--------------------------
计划 v3 的 B0 之前，`app/core/fetcher.py:32` 的 `fetch_page()` 对**任意** URL 无差别发请求：
`httpx.Client(timeout=..., follow_redirects=True)`，无 scheme 白名单、无解析后地址校验。
今天这条路是安全的，因为 URL 全部来自博查返回值；一旦用户可以手填网址（本需求），
`http://127.0.0.1:8000/api/intel`、`http://169.254.169.254/`（云元数据）、
`http://192.168.x.x`（局域网设备）就都变成可达目标，而抓回的内容会**进报告、进统计**。

期望值的判据来源（不是手写猜测）
------------------------------
- 拒绝类别取自真实失效形状：GitHub advisory **GHSA-5c6w-wwfq-7qqm** 的防护就是
  「精确过滤 `localhost` / `127.0.0.1` 字符串」，被 loopback 的等价写法绕过——
  短写、十进制、十六进制、八进制。**结论：字符串黑名单不够，必须解析后判**（计划 B0）。
- `is_private / is_loopback / is_link_local / is_reserved / is_multicast` 的归属取自
  **标准库 `ipaddress`**（本文件用当前 Python 实测其真值表，见
  `test_ipaddress_classification_table_is_what_we_assume`，把"我以为的语义"钉成"实测的语义"）。
- `domain_of()` 的行为取自 `fetcher.py:25-29`：`urlparse(url).netloc.lower().replace("www.", "")`。

📌 通道纪律：`FetchRejected` 走的是**上抛**通道而非 `ok=False` 降级通道 ——
   断言一律落在"被拒绝"这个具体失败种类上，不接受"没抓到东西"当通过。

⚠️ **两条没有活入口的用例**（第 22 轮 R22-9，仍未修）：`test_public_looking_hostname_that_resolves_to_loopback_is_rejected`
   的两个参数（`WILDCARD_DNS_HOSTS`）要靠真实 DNS 解析探针域名，不可解析时走 `pytest.skip(...)`
   ⇒ 它们在离线读数里既不是红、也不是绿，而是**没跑**。报"这批全绿"时必须带上 `-rs` 把 skip 行列出来，
   否则账面会盖掉这一点。`MAX_REDIRECTS` 至今零判据。
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

from app.core import fetcher

def _rejected(url: str) -> bool:
    """`fetch_page` 必须在**发出任何请求前**拒绝该 URL。"""
    FetchRejected = fetcher.FetchRejected          # B0 已落地：取不到就是本文件整体失效，当场红
    try:
        fetcher.fetch_page(url)
    except FetchRejected:
        return True
    except Exception as exc:                       # 其它异常＝没拦住，只是碰巧失败了
        raise AssertionError(
            f"{url} 未走拒绝路径，实际抛出 {type(exc).__name__}: {exc}。"
            "把『连接恰好失败』当成『防护生效』，是本类测试最典型的假绿。"
        )
    raise AssertionError(f"{url} 竟然抓取成功 —— 内网地址可达，防护未接线")


# ── TC-11 loopback 的等价写法（GHSA-5c6w-wwfq-7qqm 的绕过类别）─────────

LOOPBACK_EQUIVALENTS = [
    "http://127.0.0.1/",              # 直写
    "http://localhost/",              # 主机名
    "http://LOCALHOST/",              # 大小写
    "http://127.1/",                  # 短写
    "http://127.0.0.2/",              # 整个 127/8
    "http://2130706433/",             # 十进制
    "http://0x7f000001/",             # 十六进制
    "http://017700000001/",           # 八进制
    "http://[::1]/",                  # IPv6 环回（带方括号）
    "http://::1/",                    # IPv6 环回（无方括号）
    "http://0/",                      # INADDR_ANY
    "http://[::ffff:127.0.0.1]/",     # IPv4映射 IPv6
]


@pytest.mark.parametrize("url", LOOPBACK_EQUIVALENTS)
def test_loopback_equivalent_encodings_are_all_rejected(url):
    assert _rejected(url)


# ── TC-12 私有 / 链路本地 / 保留段 ─────────────────────────────────────

PRIVATE_OR_RESERVED = [
    "http://169.254.169.254/latest/meta-data/",   # 云元数据（link-local）
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://100.64.0.1/",                         # CGNAT，归属由 ipaddress 实测决定
    "http://198.18.0.1/",                         # 基准测试段
    "http://[fd00::1]/",                          # IPv6 唯一本地地址
]


@pytest.mark.parametrize("url", PRIVATE_OR_RESERVED)
def test_private_link_local_and_reserved_targets_are_rejected(url):
    assert _rejected(url)


def test_ipaddress_classification_table_is_what_we_assume():
    """真测试：把 B0 的判据前提钉成实测值 —— 我们用 `is_global`，不用 `is_private`。

    实测**两个解释器一致**（`.venv/bin/python` 3.10.20 与系统 `python3` 3.14.6）：
        100.64.0.1        is_private=False  is_global=False  ← CGNAT，is_private 漏了它
        198.18.0.1        is_private=True   is_global=False  ← 基准测试段
        0.0.0.0           is_unspecified=True  is_global=False
        169.254.169.254   is_link_local=True   is_global=False
        8.8.8.8           is_global=True
    ⇒ 若按 `is_private/is_loopback/...` 凑判据会**放过 CGNAT**；本实现取 `is_global`
    的否定式为唯一判据。日后 Python 升级改动这张表，这里会先红，而不是等 SSRF 用例静默变绿。

    期望值来源：上表为两解释器实测输出（`python -c "import ipaddress;..."`），非记忆。
    """
    non_public = ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1",
                  "169.254.169.254", "100.64.0.1", "198.18.0.1", "0.0.0.0",
                  "::1", "fd00::1", "255.255.255.255", "192.0.2.1"]
    wrong = [a for a in non_public if ipaddress.ip_address(a).is_global]
    assert not wrong, f"这些地址被判为公网可路由（B0 会放行它们）：{wrong}"

    public = ["8.8.8.8", "114.114.114.114", "151.101.0.83"]
    over_block = [a for a in public if not ipaddress.ip_address(a).is_global]
    assert not over_block, f"公网地址被误判为内网（会挡掉正常信源）：{over_block}"


def test_ipv4_mapped_ipv6_does_not_smuggle_loopback():
    """`::ffff:127.0.0.1` 的外层是 IPv6 形态，`is_global` 会判 False；映射内核才是 127.0.0.1。

    钉住这条是因为 B0 的递归判据（先看 ipv4_mapped）一旦被人"简化"掉，
    就会退化成放过一整类伪装地址。
    """
    ip = ipaddress.ip_address("::ffff:127.0.0.1")
    assert ip.ipv4_mapped == ipaddress.IPv4Address("127.0.0.1")
    assert fetcher._is_non_public(ip), "IPv4 映射 IPv6 的环回伪装必须被识破"


# ── TC-17 fail-closed：解析不了不等于放行 ───────────────────────────────

UNRESOLVABLE = [
    "http://this-host-should-not-exist.invalid/",
    "http:///",
    "http://",
    "not-a-url-at-all",
    "http://0xzz/",                    # 非法数字形式：必须拒，不得因"解析异常"而放行
    "http://127.0.0.1.1/",             # 四段但首段可解析成环回的畸形写法
]


@pytest.mark.parametrize("url", UNRESOLVABLE)
def test_unresolvable_targets_fail_closed_not_open(url):
    """B0 的核心语义：`getaddrinfo` 抛错 / 主机名畸形 ⇒ **拒绝**，而不是"没判出内网"就放过。"""
    assert _rejected(url)


# ── TC-18 scheme 白名单 ────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://127.0.0.1:11211/_stats",
    "ftp://127.0.0.1/",
    "http://127.0.0.1%0a/",
])
def test_non_http_schemes_and_smuggling_are_rejected(url):
    assert _rejected(url)


# ── TC-14 wildcard DNS：黑名单与解析后判据的唯一区分点 ──────────────────

WILDCARD_DNS_HOSTS = ["127.0.0.1.nip.io", "127.0.0.1.sslip.io"]


@pytest.mark.parametrize("host", WILDCARD_DNS_HOSTS)
def test_public_looking_hostname_that_resolves_to_loopback_is_rejected(host):
    """字符串黑名单**必然放过**这类域名；只有解析后再判才能拦住。

    这条是 B0 设计选择的**有效性证据**，不是锦上添花。
    """
    try:
        infos = socket.getaddrinfo(host, 80)
    except socket.gaierror:
        pytest.skip(
            f"{host} 在本机不可解析 ⇒ 无法取证『解析后判据』是否真拦住它"
            "（该情形属**未覆盖**，不得当成已通过）"
        )
    if not any(str(info[4][0]).startswith("127.") for info in infos):
        pytest.skip(f"{host} 未解析回 127/8，探针域名已失效，需重取基线")

    assert _rejected(f"http://{host}/")


# ── TC-15 userinfo 伪装与凭据泄漏 ──────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1#@evil.com/",           # netloc 真值是 127.0.0.1
    "http://evil.com@127.0.0.1/",            # 看着像 evil.com，主机仍是 127.0.0.1
    "http://trusted.com\\@127.0.0.1/",
])
def test_userinfo_disguised_hosts_are_rejected_by_resolved_host(url):
    assert _rejected(url)


def test_credential_in_netloc_is_stripped_before_it_reaches_storage_or_ui():
    """凭据型 URL 不得原样进入 `evidences.domain` / 前端 `<a href>`（计划 v3 §二 B1）。

    转正记录：本例生成时是 `xfail(strict=True)`，因为 `domain_of()` 当时返回
    `u:p@evil.com`。B1 落地（按 `@` 右切取真实 netloc）后转 XPASS = FAILED，按 §十.4
    摘标记；与之配对的 `test_domain_of_today_keeps_credentials_this_is_the_observed_fact`
    （钉的是既成缺陷事实）同步删除 —— 留着一份"缺陷现场照"会让下一次改动以为要保住它。
    """
    assert "u:p@" not in fetcher.domain_of("http://u:p@evil.com/x").lower()
    assert fetcher.domain_of("http://u:p@evil.com/x").lower() == "evil.com"


def test_port_survives_domain_of_because_only_the_credential_segment_is_dropped():
    """剥凭据不能顺手把端口也弄丢：`domain_of` 的老口径一直带端口，下游按它分组。

    这条是防"修 A 坏 B"的配对反证 —— 若改用 `urlparse().hostname` 实现，本例会红
    （hostname 不带端口），而端口丢失会静默改掉既有证据的 domain 值。
    """
    assert fetcher.domain_of("http://u:p@evil.com:8443/x") == "evil.com:8443"
    assert fetcher.domain_of("http://evil.com:8443/x") == "evil.com:8443"
