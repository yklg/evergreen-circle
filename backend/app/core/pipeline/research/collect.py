"""证据采集（M3 自 engine.py 原文迁出 · 行为零变化）。

信源分组采集、去重指纹、证据摘要、采集事件发射。信源类别判定不在此实现，
一律取自 `app.core.source_type` 注册表（唯一真相源）。
依赖：search/fetcher/credibility/dedup/source_type/textquality/db/trace 叶子 + _util；
不反向依赖 engine。
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from app.core import db, fetcher, search, trace
from app.core.credibility import freshness_days, score_evidence
from app.core.dedup import content_fingerprint, group_new_text, tokenize
from app.core.fetcher import MAX_SOURCE_URLS, domain_of
from app.core.models import Evidence
from app.core.source_type import is_must_read_kind, source_type as classify_source
from app.core.textquality import is_relevant_content, is_relevant_to_query

from ._util import _now, _sid


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
    """采集单个目的地：搜索 + 抓取 + 构造 Evidence。

    返回 {evidences, images, found, dup_skipped, groups, rejected}；
    `rejected` 是被 SSRF 闸门挡下的 URL（{url, reason}），由调用方计入可观测面。

    纯同步函数，供 asyncio.to_thread 调用；existing_urls 用于跨轮 URL 去重；
    groups 用于内容级信源组归一化（v2.1：同质转载归并为一组，杜绝转载冒充多源），
    由 run_pipeline 跨目的地/跨轮维护（docstring 注明：groups 池由 run_pipeline 主线程独占维护）。
    """
    queries = [f"{destination} {a}" for a in angles]
    results = search.multi_search(queries, num=10, freshness=freshness)
    out_ev: List[Evidence] = []
    out_img: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
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
        # FetchRejected 是安全判定而非抓取失败：接住它并**显式记账** —— 既不让一个
        # 内网地址打断整条流水线，也不让它静默消失（计划 v3 §二 B0 / A-4）。
        try:
            page = fetcher.fetch_page(url, fallback_snippet=r.get("snippet", ""))
        except fetcher.FetchRejected as exc:
            rejected.append({"url": url, "reason": str(exc)})
            continue
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
        stype = classify_source(url)
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
            "dup_skipped": dup_skipped, "groups": groups, "rejected": rejected}


# ── 用户指定信源：直抓（计划 v3 §二 B2）────────────────────────
def collect_user_sources(task_id: str, task_query: str, collector: str,
                         groups: Optional[List[Dict]] = None,
                         existing_urls: Optional[set] = None,
                         only_uid: Optional[str] = None,
                         ev_by_url: Optional[Dict[str, Evidence]] = None) -> Dict[str, Any]:
    """把用户手填的网址**当必读文档直接抓取**入证据链（不走搜索引擎）。

    三个与「搜索来的证据」不同的地方，都是刻意设计：

    1. **destination-less**（§一 A-2）。`evidences.destination` 与相关性判据原本都按
       目的地组织，而用户钉的是一份全省公报、一份部委文档，天然不属于某个目的地。
       拿目的地判据去判它必然误判 ⇒ `destination=""`，跑题判据只看**任务级 query**，
       且只作诊断（`gated_off_query`）、**不阻断入链**。
       这里绝不用 `"*"` 之类哨兵：`audit.decide_rework` 的补采 payload 只滤空串
       （`audit.py:328`），一个 `"*"` 会被当成真目的地发回 collect 去"补采星号"。
    2. **照常参与归并**（§一 A-3）。用户钉的三个站若转载同一篇通稿，强制让它们各自
       独立成行，正好造出这套机制要消灭的"转载冒充多源"。命中既有组 ⇒ 记 `merged`
       并写 `group_id`，覆盖率按**组**核（B4）。
    3. **逐条记账 + 逐条 trace span**（§一 B-P1）。被抓过这件事必须能被举证，
       不接受"没报错即通过"：每条都留 url/状态/耗时/字节。

    状态写点收口在这里（`db.update_user_source` 是本函数唯一的落库口）：
      `blocked` 安全闸门拒绝 / `unread` 抓取失败 / `merged` 同质归并 /
      `gated_off_query` 跑题诊断 / `fetched` 入链。
    """
    rows = [r for r in db.list_user_sources(task_id)
            if r.get("fetch_state") == "pending"
            and (only_uid is None or r["uid"] == only_uid)]
    groups = groups if groups is not None else []
    existing_urls = existing_urls if existing_urls is not None else set()
    out_ev: List[Evidence] = []
    out_img: List[Dict[str, Any]] = []
    seen_gids = {g["id"] for g in groups if g.get("id")}
    records: List[Dict[str, Any]] = []

    for row in rows:
        uid, url = row["uid"], row["url_canonical"]

        # 同址先判：博查已经取过证的地址不再重复抓取（省一次出网，更不双计信源）。
        # 组号从 groups 的 urls 里回捞；**捞不到时回落到那条同址证据本身**（ev_by_url）——
        # 舆情/景点等通道只登记 seen_urls、不建内容组，若这里留空，`merged` 行就既没有
        # evidence_id 也没有 group_id，覆盖率（按组核，§一 A-3）永远无法把"那篇确实被引用"
        # 记到用户头上：实测会让一条已被正文引用的用户网址被判成 uncited。
        if url in existing_urls:
            gid_hit = next((g["id"] for g in groups if url in (g.get("urls") or [])), "")
            twin = (ev_by_url or {}).get(url)
            if twin is not None:
                gid_hit = gid_hit or (getattr(twin, "source_group", "") or "")
            twin_eid = getattr(twin, "evidence_id", "") if twin is not None else ""
            db.update_user_source(uid, fetch_state="merged", group_id=gid_hit,
                                  evidence_id=twin_eid, attempt_reason="与检索结果同址")
            records.append({"uid": uid, "url": url, "state": "merged",
                            "reason": "与检索结果同址", "group_id": gid_hit,
                            "evidence_id": twin_eid})
            continue

        started = time.perf_counter()
        try:
            page = fetcher.fetch_page(url)
        except fetcher.FetchRejected as exc:
            ms = int((time.perf_counter() - started) * 1000)
            db.update_user_source(uid, fetch_state="blocked", attempt_reason=str(exc), ms=ms)
            records.append({"uid": uid, "url": url, "state": "blocked", "reason": str(exc)})
            trace.record_manual_span(
                task_id, collector, "collect", f"用户指定信源：{url}",
                detail="服务端直抓（用户手填地址）",
                decision=f"内网/非法地址闸门拒绝：{exc}", latency_ms=ms,
            )
            continue

        ms = int((time.perf_counter() - started) * 1000)
        text = (page.get("text") or "").strip()
        ok = bool(page.get("ok")) and bool(text)
        size = len(text.encode("utf-8"))

        if not ok:
            reason = _fetch_failure_reason(page)
            db.update_user_source(uid, fetch_state="unread", attempt_reason=reason,
                                  bytes=size, ms=ms)
            records.append({"uid": uid, "url": url, "state": "unread", "reason": reason})
            trace.record_manual_span(
                task_id, collector, "collect", f"用户指定信源：{url}",
                detail="服务端直抓（用户手填地址）",
                decision=f"未读到正文：{reason}", latency_ms=ms,
            )
            continue

        gid, _rep = group_new_text(text, groups)
        if gid:
            for g in groups:
                if g.get("id") == gid:
                    g.setdefault("urls", []).append(url)
                    break
            db.update_user_source(uid, fetch_state="merged", group_id=gid,
                                  attempt_reason="与既有信源组同质（转载）", bytes=size, ms=ms)
            records.append({"uid": uid, "url": url, "state": "merged", "reason": "同质归并",
                            "group_id": gid})
            trace.record_manual_span(
                task_id, collector, "collect", f"用户指定信源：{url}",
                detail="服务端直抓（用户手填地址）",
                decision="正文与既有信源组同质，归并为一组（不冒充独立信源）。",
                latency_ms=ms,
            )
            continue

        captured = page.get("captured_at", _now())
        stype = "user_supplied"
        cred = score_evidence(
            url, stype, captured_at=captured, has_publish_date=False,
            ok_fetch=True, excerpt=text[:280],
        )
        off_query = bool(task_query) and not is_relevant_to_query(text, task_query)
        gid2 = _sid("g")
        while gid2 in seen_gids:
            gid2 = _sid("g")
        seen_gids.add(gid2)
        groups.append({"id": gid2, "tokens": tokenize(text), "urls": [url]})
        existing_urls.add(url)
        title = _user_source_title(page, url)
        ev = Evidence(
            evidence_id=_sid("e"),
            source_url=url,
            source_type=stype,
            title=title,
            excerpt=text[:280],
            captured_at=captured,
            credibility=cred,
            collected_by=collector,
            image_urls=[im["src"] for im in page.get("images", [])][:3],
            destination="",
            domain=domain_of(url),
            freshness_days=freshness_days(captured),
            content_hash=content_fingerprint(text),
            source_group=gid2,
        )
        ev._full_text = text[:1500]  # type: ignore[attr-defined]
        out_ev.append(ev)
        og = (page.get("og_image") or "").strip()
        pics = page.get("images", []) or []
        fig_src = og or (pics[0]["src"] if pics else "")
        if fig_src:
            out_img.append({
                "src": fig_src, "alt": "", "title": title, "source_url": url,
                "domain": domain_of(url), "source_type": stype, "destination": "",
                "evidence_id": ev.evidence_id,
            })
        state = "gated_off_query" if off_query else "fetched"
        db.update_user_source(uid, fetch_state=state, evidence_id=ev.evidence_id,
                              group_id=gid2, bytes=size, ms=ms,
                              **({"attempt_reason": "正文与任务主题不相关（仅诊断，仍入链）"}
                                 if off_query else {}))
        records.append({"uid": uid, "url": url, "state": state,
                        "evidence_id": ev.evidence_id, "group_id": gid2,
                        "bytes": size, "ms": ms})
        trace.record_manual_span(
            task_id, collector, "collect", f"用户指定信源：{url}",
            detail=(f"服务端直抓（用户手填地址）｜正文 {size}B｜耗时 {ms}ms"),
            decision=(f"入证据链 {ev.evidence_id}（类别 {stype}，可信度 {cred:.0f}）"
                      + ("；正文与任务主题不相关，仅诊断标注" if off_query else "")),
            evidence_ids=[ev.evidence_id], latency_ms=ms,
        )

    return {"evidences": out_ev, "images": out_img, "records": records, "groups": groups}


def _fetch_failure_reason(page: Dict[str, Any]) -> str:
    """把"没读到正文"写成可分档的原因（404 与 403 不能同判，用户看到的措辞要区分）。"""
    status = page.get("http_status")
    if status:
        if int(status) in (401, 403):
            return f"HTTP {status}（站点拒绝服务端读取，可能有反爬/登录墙）"
        if int(status) == 404:
            return "HTTP 404（地址不存在）"
        if int(status) >= 500:
            return f"HTTP {status}（站点侧错误）"
        return f"HTTP {status}"
    if page.get("error"):
        return f"抓取失败：{page['error']}"
    return "正文为空（抽取不到可读内容）"


def _user_source_title(page: Dict[str, Any], url: str) -> str:
    """标题优先用抓到的 `<title>`/og:title，退化为域名末段（不留空标题进报告）。"""
    for key in ("title", "og_title"):
        value = str(page.get(key) or "").strip()
        if value:
            return value[:120]
    tail = domain_of(url).split(".")[-2] if domain_of(url) else ""
    return tail or url[:60]


# ── 分析：LLM 基于真实证据产出论点 + 结构化对比 ───────────────
def _digest_line(e: Evidence) -> str:
    return f"[{e.evidence_id}|{e.source_type}|{domain_of(e.source_url)}] {e.title}：{e.excerpt}"


def evidence_source_type(e: Any) -> str:
    """取一条证据的类别 key —— 兼容 `Evidence` 对象与 reports.data 里的 dict 形态。

    派生路径（精炼 / 一页纸 / 复跑）读的是 `db.get_report()` 反序列化出来的 dict，
    主流水线读的是 `Evidence` 对象。判据必须两处同一个函数，否则"必读"这件事
    会在派生路径上悄悄失效（派生报告看不见用户钉的文档，且没有任何提示）。
    """
    if isinstance(e, dict):
        return str(e.get("source_type") or "")
    return str(getattr(e, "source_type", "") or "")


def must_read_first(evidences: List[Any]) -> List[Any]:
    """把注册表判定为必读的证据排到前面，其余保持原序（稳定排序）。

    无必读条目时返回同序列表 —— 派生路径的位置截断（`evidence[:24]`）因此行为不变。
    """
    head = [e for e in evidences if is_must_read_kind(evidence_source_type(e))]
    if not head:
        return list(evidences)
    head_ids = {id(e) for e in head}
    rest = [e for e in evidences if id(e) not in head_ids
            and not is_must_read_kind(evidence_source_type(e))]
    return head + rest


def must_read_ids(evidences: List[Evidence]) -> set:
    """注册表判定为「必读」的证据 id（当前即 `user_supplied` 一类）。

    判据来自 `source_type.SOURCE_KINDS[*].must_read`，不在这里写死类别名 ——
    将来再加一类必读信源（内部资料库等），只改注册表。
    """
    return {e.evidence_id for e in evidences if is_must_read_kind(e.source_type)}


def digest_limit_for(evidences: List[Evidence], base_limit: int) -> int:
    """必读条目**加槽**而不是挤位：`base_limit + min(必读条数, 清单上限)`。

    保留槽若只在 `base_limit` 之内占位，10 条用户正文会把检索证据挤掉一半，
    等于用"用户信源进上下文"换"原有信源看不见"（计划 §二 B3 要求 limit 随之重新定标）。
    无必读条目时返回值 == base_limit ⇒ 入池规模零变化，这是 spots/writer 的等价性前提。
    """
    reserved = min(len(must_read_ids(evidences)), MAX_SOURCE_URLS)
    return base_limit + reserved


def _evidence_digest(evidences: List[Evidence], limit: int = 28,
                     pinned: Optional[Any] = None) -> str:
    """证据入池摘要（writer / spots / analyze 三方共用的**唯一**入池函数）。

    保留槽（计划 v3 §一 A-1）：`pinned` 里的条目**优先占位**，其余按原顺序补足。
    没有保留槽时这里是纯位置截断 —— 用户钉的网址若排在第 21 条之后，就从未进过
    写作 prompt，于是"用户信源没被引用"分不清是"没引用"还是"根本没进上下文"，
    覆盖率测的其实是列表顺序。

    **无 pinned 时逐字节等改动前**（`tests/test_evidence_digest_pinned.py` TC-28 钉这条）：
    必读集为空 ⇒ `ordered == evidences`，输出与旧的 `evidences[:limit]` 完全一致，
    spots 的景点实体 leg 入池不因此变化。
    """
    forced = must_read_ids(evidences) | set(pinned or ())
    if not forced:
        return "\n".join(_digest_line(e) for e in evidences[:limit])
    head = [e for e in evidences if e.evidence_id in forced]
    rest = [e for e in evidences if e.evidence_id not in forced]
    return "\n".join(_digest_line(e) for e in (head + rest)[:limit])
