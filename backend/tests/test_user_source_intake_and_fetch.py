"""用户指定信源的入口卫生与直抓（实施计划 v3 §二 B1 + B2 · §八 TC-04/05/06/08/16/20/21/24/45）。

守护的契约
----------
用户手填网址是这条链路上**第二条真实出网口**（第一条是博查、第三条是百度地图 API）。
一旦开这个口，三件事必须同时成立，否则功能就是"看起来能用"：

  1. 入口不许静默丢条款：>10 条要**截断并回报截断数**，非法条目要**点名原因**
     （`normalize_user_url_list` 的 `truncated`/`rejected` 两支）。
  2. 抓取结果不许静默消失：每条网址必须落到一个**声明过的终态**
     （fetched / unread / blocked / merged / gated_off_query），且失败原因分档可见
     （404 与 403 不能同判成"没抓到"，这是计划 §八 TC-21 的判据形状）。
  3. 用户信源是 destination-less：它天然不属于任何目的地，`destination` 必须落**空串**
     （不是 `"*"` 哨兵 —— `decide_rework` 会把哨兵当真目的地发回 collect 补采，
     见 `test_audit_user_source_envelope.py`）。

期望值来源
----------
- 上限 10 / 单条 256 取自 `fetcher.MAX_SOURCE_URLS` / `MAX_SOURCE_URL_LEN`（import，不抄数）；
- 终态词表取自 `db.USER_SOURCE_STATES`；
- 抓取桩替换的是生产接缝 `fetcher.fetch_page`，`FetchRejected` 由闸门本身抛出（不桩它）。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core import fetcher, trace
from app.core.pipeline.research import collect
from app.main import app

client = TestClient(app)

TASK = "t-b2-smoke"


def _page(text: str = "大理古城游客中心公布开放时间与预约规则。" * 6,
          ok: bool = True, **extra: Any) -> Dict[str, Any]:
    base = {"url": "x", "text": text, "images": [], "og_image": "",
            "title": "测试页标题", "ok": ok, "degraded": not ok,
            "captured_at": "2026-09-01T00:00:00Z"}
    base.update(extra)
    return base


@pytest.fixture
def stub_fetch(monkeypatch):
    """把网络出口 `fetch_page` 换成可编程桩（可设正文、状态码、以及"被闸门拒绝"）。

    桩的是**出网这一层**，不是判定层：闸门自身的正确性由 `test_fetch_ssrf_guard.py`
    与 `test_fetch_ssrf_poc.py` 用真实现钉死（含"对端一次都没被请求"的服务侧观测）。
    本文件要钉的是另一件事 —— 闸门上抛 `FetchRejected` 之后，collect **有没有记账**、
    有没有因为一条内网地址打断整条流水线。所以这里按 `reject` 名单注入该异常：
    测试环境没有可用 DNS，若在桩里改跑真判据，`ok.gov.cn` 一类域名会被 fail-closed
    一并拒成 `blocked`，用例就变成在测"解析不了"而不是在测"记账"。
    真闸门那条路另有 `test_real_gate_rejects_loopback_ip_without_dns` 覆盖。
    """
    behavior: Dict[str, Any] = {"responses": {}, "reject": set(),
                                "default": _page(), "calls": []}

    def fake(url: str, *, fallback_snippet: str = "") -> Dict[str, Any]:
        behavior["calls"].append(url)
        if url in behavior["reject"]:
            raise fetcher.FetchRejected(f"{url!r} 的主机不是公网可路由地址，已拒绝")
        return behavior["responses"].get(url, dict(behavior["default"]))

    monkeypatch.setattr(fetcher, "fetch_page", fake)
    return behavior


# ── B1 · 入口卫生（纯函数层，等价类 + 边界）─────────────────────────

def test_missing_scheme_is_normalized_to_https_and_shown_back():
    """待确认 3 已拍板：`example.com/doc` 自动补 https://，且回给前端的是补完后的串。"""
    urls, _ = fetcher.normalize_user_url_list(["example.com/doc"])["urls"], None
    assert urls == ["https://example.com/doc"]


def test_credentials_are_stripped_at_the_entry_point():
    cleaned = fetcher.normalize_user_url_list(["https://u:p@evil.com/doc"])
    assert cleaned["urls"] == ["https://evil.com/doc"], cleaned
    assert "u:p" not in cleaned["urls"][0]


@pytest.mark.parametrize("raw", [
    "file:///etc/passwd",
    "gopher://127.0.0.1:11211/x",
    "javascript:alert(1)",
    "data:text/html,hi",
])
def test_non_http_schemes_are_rejected_with_a_named_reason(raw):
    cleaned = fetcher.normalize_user_url_list([raw])
    assert cleaned["urls"] == []
    assert len(cleaned["rejected"]) == 1, f"{raw} 被静默丢弃而非点名拒绝"
    assert cleaned["rejected"][0]["url"] == raw
    assert cleaned["rejected"][0]["reason"], "拒因必须可读，不能是空串"


def test_dedup_is_by_canonical_form_not_by_raw_string():
    """`example.com/a` 与 `https://example.com/a/` 补全/归一后是否同址，由归一决定；
    这里钉的是"归一后相同 ⇒ 只留一条"，防止覆盖率分母把一条网址数成两条。"""
    cleaned = fetcher.normalize_user_url_list(
        ["https://example.com/a", "https://example.com/a", "  https://example.com/a  "])
    assert cleaned["urls"] == ["https://example.com/a"]
    assert cleaned["truncated"] == 0


def test_over_limit_is_truncated_and_reports_the_count():
    """>10 条 ⇒ 落库 10 条 + `truncated` 报出被砍掉的条数（不静默丢弃）。"""
    raws = [f"https://s{i}.gov.cn/doc" for i in range(fetcher.MAX_SOURCE_URLS + 3)]
    cleaned = fetcher.normalize_user_url_list(raws)
    assert len(cleaned["urls"]) == fetcher.MAX_SOURCE_URLS
    assert cleaned["truncated"] == 3, f"截断数没报出来：{cleaned['truncated']}"


def test_over_long_item_is_rejected_not_stored():
    long_url = "https://x.gov.cn/" + "a" * fetcher.MAX_SOURCE_URL_LEN
    cleaned = fetcher.normalize_user_url_list([long_url, "https://ok.gov.cn/1"])
    assert cleaned["urls"] == ["https://ok.gov.cn/1"]
    assert cleaned["rejected"] and "上限" in cleaned["rejected"][0]["reason"]


def test_empty_and_blank_items_are_dropped_without_a_rejection_entry():
    """空白项不是"被拒的网址"，不该占拒因清单（否则用户会看到一堆空字符串报错）。"""
    cleaned = fetcher.normalize_user_url_list(["", "   ", None, "https://a.gov.cn/1"])
    assert cleaned["urls"] == ["https://a.gov.cn/1"]
    assert cleaned["rejected"] == []


def test_fragment_is_dropped_because_it_does_not_change_what_we_fetch():
    cleaned = fetcher.normalize_user_url_list(["https://a.gov.cn/doc#section-2"])
    assert cleaned["urls"] == ["https://a.gov.cn/doc"]


def test_port_is_preserved():
    cleaned = fetcher.normalize_user_url_list(["http://a.example:8443/x"])
    assert cleaned["urls"] == ["http://a.example:8443/x"]


# ── B1 · 任务入口（走 HTTP，判据落在用户可观察结果上）─────────────────

def _post_task(payload: Dict[str, Any]):
    return client.post("/api/tasks", json=payload)


def test_task_without_source_urls_keeps_the_old_response_shape():
    """**零回归基线**（计划 §四.2）：不带清单时响应不得多出任何键。"""
    res = _post_task({"query": "大理亲子游", "mode": "quick"})
    assert res.status_code == 200
    assert set(res.json()) == {"taskId", "researchType"}, res.json()


def test_task_with_source_urls_registers_one_row_per_url():
    res = _post_task({"query": "大理调研", "mode": "quick",
                      "source_urls": ["https://a.gov.cn/1", "https://b.gov.cn/2"]})
    assert res.status_code == 200
    body = res.json()
    assert "sourceUrls" in body
    task_id = body["taskId"]
    rows = db.list_user_sources(task_id)
    assert [r["url_canonical"] for r in rows] == ["https://a.gov.cn/1", "https://b.gov.cn/2"]
    assert [r["seq"] for r in rows] == [0, 1]
    assert {r["fetch_state"] for r in rows} == {"pending"}, "登记态不是 pending ⇒ 采集会漏抓"
    assert body["sourceUrls"]["accepted"] == [r["url_canonical"] for r in rows]


def test_source_urls_are_echoed_after_normalization_not_as_typed():
    """用户填 `example.com`，界面要显示补全后的 https 形态（否则"填了却没抓到"无从对证）。"""
    res = _post_task({"query": "洱海", "mode": "quick", "source_urls": ["example.com/doc"]})
    body = res.json()
    assert body["sourceUrls"]["accepted"] == ["https://example.com/doc"]
    assert db.list_user_sources(body["taskId"])[0]["url_canonical"] == "https://example.com/doc"


def test_truncation_is_visible_in_the_http_response():
    raws = [f"https://s{i}.gov.cn/doc" for i in range(fetcher.MAX_SOURCE_URLS + 2)]
    body = _post_task({"query": "多源", "mode": "quick", "source_urls": raws}).json()
    assert len(body["sourceUrls"]["accepted"]) == fetcher.MAX_SOURCE_URLS
    assert body["sourceUrls"]["truncated"] == 2
    assert len(db.list_user_sources(body["taskId"])) == fetcher.MAX_SOURCE_URLS


def test_rejected_items_are_reported_in_the_http_response():
    body = _post_task({"query": "混填", "mode": "quick",
                       "source_urls": ["file:///etc/passwd", "https://ok.gov.cn/1"]}).json()
    assert [r["url"] for r in body["sourceUrls"]["rejected"]] == ["file:///etc/passwd"]
    assert body["sourceUrls"]["accepted"] == ["https://ok.gov.cn/1"]
    assert len(db.list_user_sources(body["taskId"])) == 1


def test_living_circle_with_source_urls_is_rejected_not_silently_dropped():
    """生活圈流水线不读网页。"填了却什么都没发生"是 R0 那条被静默丢弃的 sample_profile
    的同一个形状 ⇒ 明确 422，让前端能提示。"""
    res = client.post("/api/tasks", json={
        "query": "某小区", "type": "living_circle", "city": "昆明",
        "source_urls": ["https://a.gov.cn/1"],
    })
    assert res.status_code == 422, res.text
    assert "生活圈" in res.text


def test_malformed_source_urls_element_is_422():
    """数组元素类型错了必须 422（`extra="forbid"` 只挡未声明键，挡不住坏形状）。"""
    res = client.post("/api/tasks", json={"query": "q", "mode": "quick",
                                          "source_urls": [{"not": "a url"}]})
    assert res.status_code == 422, res.text


# ── B2 · 直抓的六种终态 ───────────────────────────────────────────

def _register(uid_urls: List[str], task_id: str = TASK) -> None:
    for i, u in enumerate(uid_urls):
        db.add_user_source(task_id, u, u, i)


def _row(task_id: str, url: str) -> Dict[str, Any]:
    return next(r for r in db.list_user_sources(task_id) if r["url_canonical"] == url)


def test_successful_fetch_enters_the_evidence_chain(stub_fetch):
    url = "https://ok.gov.cn/report"
    _register([url])
    stub_fetch["responses"][url] = _page("大理州发布便民生活圈试点名单与建设标准。" * 5)

    res = collect.collect_user_sources(TASK, "大理便民生活圈调研", "L1-025", [], set())

    assert len(res["evidences"]) == 1
    ev = res["evidences"][0]
    assert ev.source_type == "user_supplied"
    assert ev.collected_by == "L1-025"
    assert ev.source_url == url
    assert ev.title == "测试页标题", "抓到正文却没标题 ⇒ 证据链里会显示空标题"
    row = _row(TASK, url)
    assert row["fetch_state"] == "fetched"
    assert row["evidence_id"] == ev.evidence_id
    assert row["group_id"] == ev.source_group
    assert row["bytes"] > 0 and row["ms"] >= 0


def test_destination_is_empty_string_never_a_sentinel(stub_fetch):
    """A-2 的落地形态：用户信源没有目的地，落**空串**。

    空串是 `audit.decide_rework` 唯一会过滤掉的值（`audit.py:328` 的集合推导）；
    选 `"*"` 会把"补采一个叫 * 的目的地"发回 collect。这里把选择钉成构造层判据。
    """
    url = "https://gov.cn/province-bulletin"
    _register([url])
    stub_fetch["responses"][url] = _page("全省便民生活圈建设推进会召开，部署试点任务。" * 4)

    res = collect.collect_user_sources(TASK, "全省生活圈政策调研", "L1-025", [], set())
    assert res["evidences"], "直抓没产出证据"
    assert res["evidences"][0].destination == ""
    assert res["evidences"][0].destination != "*"


def test_internal_address_is_blocked_and_accounted(stub_fetch):
    """TC-13 的流水线侧：闸门拒绝必须**记账**，既不打断流水线也不静默消失。"""
    url = "http://127.0.0.1:8000/api/intel"
    _register([url, "https://ok2.gov.cn/x"])
    stub_fetch["reject"].add(url)
    stub_fetch["responses"]["https://ok2.gov.cn/x"] = _page("古城游客量与承载力的统计公报。" * 4)

    res = collect.collect_user_sources(TASK, "大理游客量调研", "L1-025", [], set())

    blocked = [r for r in res["records"] if r["state"] == "blocked"]
    assert blocked and blocked[0]["url"] == url
    assert _row(TASK, url)["fetch_state"] == "blocked"
    assert _row(TASK, url)["attempt_reason"], "拒绝原因没落库 ⇒ 界面无法显示「内网地址已拒绝」"
    assert len(res["evidences"]) == 1, "一条被拒不拖累其余条目"


def test_real_gate_rejects_loopback_ip_without_any_stub():
    """**不桩任何东西**：生产 `fetch_page` 的闸门对 IP 字面量当场拒绝（不依赖 DNS）。

    上面那根桩注入的是"闸门已抛"这一后果；这条补的是真接缝 —— 证明 collect 接的
    确实是 `fetcher.FetchRejected` 这个类，而不是某个测试自己造的异常。
    """
    url = "http://127.0.0.1:8000/api/intel"
    _register([url])
    res = collect.collect_user_sources(TASK, "大理古城调研", "L1-025", [], set())
    assert [r["state"] for r in res["records"]] == ["blocked"], res["records"]
    assert res["evidences"] == []
    assert _row(TASK, url)["fetch_state"] == "blocked"
    assert "公网" in _row(TASK, url)["attempt_reason"]


def test_http_404_and_403_are_distinct_reasons(stub_fetch):
    """TC-21：404 与 403 都是"没读到"，但**分档不混**（用户要能区分"地址错"和"站点拒"）。"""
    u404, u403 = "https://gone.gov.cn/x", "https://wall.gov.cn/y"
    _register([u404, u403])
    stub_fetch["responses"][u404] = _page("", ok=False, http_status=404)
    stub_fetch["responses"][u403] = _page("", ok=False, http_status=403)

    res = collect.collect_user_sources(TASK, "调研", "L1-025", [], set())

    assert res["evidences"] == []
    states = {_row(TASK, u)["fetch_state"] for u in (u404, u403)}
    assert states == {"unread"}, states
    r404 = _row(TASK, u404)["attempt_reason"]
    r403 = _row(TASK, u403)["attempt_reason"]
    assert "404" in r404 and "403" in r403, (r404, r403)
    assert r404 != r403, "两种失败同判 ⇒ 用户分不清是地址错还是站点反爬"
    assert res["records"] and all(rec["state"] == "unread" for rec in res["records"])


def test_empty_body_is_unread_with_a_readable_reason(stub_fetch):
    url = "https://blank.gov.cn/x"
    _register([url])
    stub_fetch["responses"][url] = _page("", ok=False)
    collect.collect_user_sources(TASK, "调研", "L1-025", [], set())
    reason = _row(TASK, url)["attempt_reason"]
    assert reason and "404" not in reason, f"没状态码却编出 404：{reason}"


def test_duplicate_reprint_is_merged_not_inflated(stub_fetch):
    """A-3：用户钉 3 站同一篇通稿 ⇒ 照常归并，**不各自独立成行**。

    否则正好造出这套去重机制要消灭的"转载冒充多源"，`single_source_ratio` 也会被假独立
    信源拉低（计划 §一 B-P1 质量分口径移动）。
    """
    same = "大理古城周末交通组织调整通告，绕行方案如下。" * 6
    urls = ["https://a.gov.cn/t", "https://b.gov.cn/t", "https://c.gov.cn/t"]
    _register(urls)
    for u in urls:
        stub_fetch["responses"][u] = _page(same)

    groups: List[Dict] = []
    res = collect.collect_user_sources(TASK, "大理交通调研", "L1-025", groups, set())

    assert len(res["evidences"]) == 1, "三条同质正文只该开一个证据行"
    assert len(groups) == 1, f"组数被转载撑到 {len(groups)}"
    states = [_row(TASK, u)["fetch_state"] for u in urls]
    assert states[0] == "fetched" and set(states[1:]) == {"merged"}, states
    gids = [_row(TASK, u)["group_id"] for u in urls]
    assert len(set(gids)) == 1 and gids[0], "归并后必须同属一个信源组（覆盖率按组核）"
    # 三条地址都要留在组里，B4 的"按组核"才数得出这条网址确实被读过
    assert set(groups[0]["urls"]) == set(urls), groups[0]["urls"]


def test_off_topic_body_is_diagnosed_but_still_enters_chain(stub_fetch):
    """A-2：跑题判据用**任务级 query**（不是目的地），命中只作诊断，仍入链。

    全省公报对"大理"任务天然不含目的地名 —— 用它当阻断判据会误杀合法信源。
    """
    url = "https://gov.cn/province"
    _register([url])
    stub_fetch["responses"][url] = _page("关于举办全国机器人锦标赛的通知。" * 8)

    res = collect.collect_user_sources(TASK, "大理亲子游攻略", "L1-025", [], set())

    assert len(res["evidences"]) == 1, "跑题是诊断项，不是丢弃项"
    assert _row(TASK, url)["fetch_state"] == "gated_off_query"
    assert _row(TASK, url)["evidence_id"] == res["evidences"][0].evidence_id


def test_already_collected_url_is_merged_by_same_address(stub_fetch):
    """用户钉的网址博查也搜到过 ⇒ 不重复入链（否则同一篇在饼图里成两个独立信源）。"""
    url = "https://dali.gov.cn/news"
    _register([url])
    collect_user_urls = {url}
    res = collect.collect_user_sources(TASK, "大理", "L1-025", [], collect_user_urls)
    assert res["evidences"] == []
    assert _row(TASK, url)["fetch_state"] == "merged"
    assert stub_fetch["calls"] == [], "同址条目应先判同址再抓，白烧一次出网"


def test_same_address_merge_links_the_twin_evidence_so_coverage_can_credit_it(stub_fetch):
    """同址归并必须把**那条已存在的证据**连上，否则覆盖率永远说不清"这篇其实被用上了"。

    实测形状（2026-09-28 端到端，任务 t_9242f46d）：用户钉的一篇新闻正文与检索证据同址，
    归并后 `group_id=''`、`evidence_id=NULL` —— 因为舆情/景点这类通道只登记 `seen_urls`、
    不建内容组。于是那条新闻即使被正文引用，按组核（§一 A-3）也数不到用户头上：
    报告会说"你钉的文档读了但没用上"，而真话是"它就在正文里"。
    """
    from app.core.audit import compute_user_source_coverage
    from app.core.models import Evidence

    url = "https://dali.gov.cn/news"
    _register([url])
    twin = Evidence(
        evidence_id="e_twin_001", source_url=url, source_type="news", title="同址新闻",
        excerpt="x", captured_at="2026-09-01T00:00:00Z", credibility=80.0,
        collected_by="L1-031", image_urls=[], republished_from="", destination="大理",
        source_group="g_twin_001",
    )
    collect.collect_user_sources(TASK, "大理", "L1-025", [], {url}, ev_by_url={url: twin})

    row = _row(TASK, url)
    assert row["fetch_state"] == "merged"
    assert row["evidence_id"] == "e_twin_001", row
    assert row["group_id"] == "g_twin_001", row

    # 判据落在用户可观察结果上：那条同址新闻被结论引用 ⇒ 用户这钉算"已引用"
    claims = [{"claim_id": "c1", "evidence_ids": ["e_twin_001"]}]
    coverage = compute_user_source_coverage([row], claims, [twin])
    assert coverage["cited"] == 1, coverage
    assert coverage["uncited"] == 0, coverage


def test_same_address_merge_without_the_index_would_have_been_misjudged(stub_fetch):
    """反证配对：不给 ev_by_url（改动前的形状）⇒ 两个链接字段皆空、覆盖率判 uncited。

    没有这条，上一条可能只是在测"随便传什么都会连上"。它同时把缺陷本身钉成事实：
    将来有人删掉回落逻辑，这一条不会变红，但**上一条**会。
    """
    from app.core.audit import compute_user_source_coverage

    url = "https://dali.gov.cn/news"
    _register([url])
    collect.collect_user_sources(TASK, "大理", "L1-025", [], {url})

    row = _row(TASK, url)
    assert not row["evidence_id"] and not row["group_id"], row
    coverage = compute_user_source_coverage([row], [{"claim_id": "c1", "evidence_ids": ["e_x"]}], [])
    assert coverage["cited"] == 0 and coverage["uncited"] == 1, coverage


def test_every_pending_row_ends_in_a_declared_state(stub_fetch):
    """守恒（计划 §八 INV-01）：分母恒等 —— 每条登记过的网址都必须有一个声明过的终态。

    这条是"某条网址凭空消失"的防线：漏计不是数字小一点，而是覆盖率算错方向。
    """
    urls = [
        "https://ok.gov.cn/1", "https://gone.gov.cn/2", "http://127.0.0.1/3",
        "https://wall.gov.cn/4",
    ]
    _register(urls)
    stub_fetch["responses"]["https://gone.gov.cn/2"] = _page("", ok=False, http_status=404)
    stub_fetch["responses"]["https://wall.gov.cn/4"] = _page("", ok=False, http_status=403)
    stub_fetch["reject"].add("http://127.0.0.1/3")

    res = collect.collect_user_sources(TASK, "大理古城调研", "L1-025", [], set())

    assert len(res["records"]) == len(urls), "有网址没被处理（既没抓取也没记账）"
    states = {rec["state"] for rec in res["records"]}
    assert states <= set(db.USER_SOURCE_STATES), f"越界状态词：{states - set(db.USER_SOURCE_STATES)}"
    stored = [_row(TASK, u)["fetch_state"] for u in urls]
    assert stored.count("blocked") == 1 and stored.count("unread") == 2
    assert stored.count("fetched") == 1
    assert len(urls) == len(stored) == sum(
        1 for _ in db.list_user_sources(TASK)), "记账条数与登记条数不等 ⇒ 分母破了"


def test_re_running_does_not_refetch_finished_rows(stub_fetch):
    """幂等：已落终态的行不再重复抓取（复跑/补采轮不该把同一网址再烧一次）。"""
    url = "https://ok.gov.cn/rerun"
    _register([url])
    collect.collect_user_sources(TASK, "调研", "L1-025", [], set())
    calls_after_first = len(stub_fetch["calls"])
    again = collect.collect_user_sources(TASK, "调研", "L1-025", [], set())
    assert len(stub_fetch["calls"]) == calls_after_first, "重跑又抓了一遍"
    assert again["records"] == []


def test_only_uid_targets_a_single_row(stub_fetch):
    """引擎逐条驱动时要能只处理一行（界面显示「正在读取第 k/N 条」靠这个接缝）。"""
    a, b = "https://x.gov.cn/a", "https://x.gov.cn/b"
    _register([a, b])
    uid_a = _row(TASK, a)["uid"]
    res = collect.collect_user_sources(TASK, "调研", "L1-025", [], set(), only_uid=uid_a)
    assert [rec["url"] for rec in res["records"]] == [a]
    assert _row(TASK, b)["fetch_state"] == "pending", "只点一条却把另一条也动了"


# ── B2 · 每条都有 trace span（OBS-01）─────────────────────────────

def test_each_user_source_leaves_a_trace_span(stub_fetch):
    """计划 §四.9：trace 面板要能看到每条的出网记录（url/状态/耗时）。

    这条补的是在册风险「trace 面板无 HTTP 轨迹」的一半 —— 新增了出网口却没有轨迹，
    答辩就无法举证"确实读了这几个网址"。
    """
    urls = ["https://t1.gov.cn/a", "https://t2.gov.cn/b"]
    _register(urls)
    collect.collect_user_sources(TASK, "调研", "L1-025", [], set())

    spans = trace.drain(TASK)          # span 还在进程内缓冲，报告落库前不进 traces 表
    purposes = [s["purpose"] for s in spans]
    for u in urls:
        hits = [p for p in purposes if u in p]
        assert hits, f"{u} 没有对应 trace span：{purposes}"
    for s in spans:
        assert "用户指定信源" in s["purpose"], s["purpose"]
        assert s["response"], "span 没写终态，面板上就是一条空记录"
