"""景点实体与真实路线/商铺/舆情二查（M3 自 engine.py 原文迁出 · 行为零变化）。

阶段：LLM 可数信号抽取（不算分）→ 百度实体解析/真实路线 fan-out →
景点视角二查（probe）→ 商铺 POI 富化与公交挂线 → 逐日行程纯函数装配 →
逐景点评论采集（仅喂舆情，不进证据库）。
依赖：baidu services + search/llm/credibility/dedup/platforms/sentiment 叶子 +
_util/collect/planning；不反向依赖 engine。符号由 engine re-export。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from app.core import llm, search
from app.core.credibility import freshness_days, score_evidence
from app.core.dedup import content_fingerprint
from app.core.doc_kind import classify_doc
from app.core.fetcher import domain_of
from app.core.models import Evidence
from app.core.platforms import PLATFORMS
from app.core.schemas import _filter_eids
from app.core.search import SearchProviderError
from app.core.sentiment import PLATFORM_LABEL
from app.core.source_type import source_type as classify_source
from app.services import baidu as baidu_client

from ._util import _name_hit, _now, _sid
from .collect import _evidence_digest
from .planning import _days_from_text


# 百度批量 fan-out 的阶段级总预算（秒）：单调用另有 baidu_timeout，超时项走占位降级，
# 不回滚已完成的 LLM 分析。
_BAIDU_STAGE_BUDGET_S = 60.0























def _extract_spot_signals(query, destinations, focus, evidences: List[Evidence],
                          top_n: int, model: str,
                          trunc_report: Optional[List[bool]] = None) -> List[Dict[str, Any]]:
    """景点实体阶段：LLM 只做**可数信号的事实抽取**（声量提及数/正面口碑占比/性价比档），
    排序与算分交给 scoring.rank_spots——数值可复现，LLM 无评分话语权。

    失败或无信号时返回空表（上层出「实体表为空」的如实提示），不影响已完成的其他分析。
    trunc_report：同 _analyze_structured 的 L2 线程内截断判定回传通道。
    """
    spec_digest = _evidence_digest(evidences, limit=24)
    valid_eids = {e.evidence_id for e in evidences}
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": (
                    "你是旅游数据分析师。从给定证据中整理目的地热度最高的若干景点，"
                    "为每个景点抽取**可计数的事实信号**，禁止给景点排序或打分。字段口径："
                    "mentions=该景点在证据中被提及/打卡的次数（整数）；"
                    "positive_ratio=正面评价占该景点全部评价的比例（0-1 小数）；"
                    "value_score=性价比主观档位归一（0-1 小数，1 为极高性价比）。"
                    "所有信号都必须能追溯到给定证据，无证据支撑的景点不要编造。输出 JSON："
                    '{"spots":[{"name":"景点名","area":"所在区域","signals":{"mentions":数字,'
                    '"positive_ratio":0-1,"value_score":0-1},"ticket":"门票与预约方式",'
                    '"stay_minutes":建议停留分钟整数,"off_peak":"避峰时段","reason":"一句话入选理由",'
                    '"evidence_ids":["真实id"]}]}。只输出 JSON，不要解释。'
                )},
                {"role": "user", "content": (
                    f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点：{'、'.join(focus)}\n"
                    f"只需给出不超过 {top_n} 个景点。\n证据：\n{spec_digest}"
                )},
            ],
            max_tokens=6000,
            temperature=0.3,
            model=model,
            purpose="景点信号抽取（TopN 实体候选）",
        )
        rows = data.get("spots") if isinstance(data, dict) else data
        out: List[Dict[str, Any]] = []
        for r in (rows if isinstance(rows, list) else []):
            if isinstance(r, dict) and str(r.get("name") or "").strip():
                r["evidence_ids"] = _filter_eids(r.get("evidence_ids"), valid_eids)
                out.append(r)
        if trunc_report is not None:
            trunc_report.append(llm.last_finish_reason() == "length" and not out)
        return out
    except Exception:
        if trunc_report is not None:
            trunc_report.append(False)
        return []


# ── M2：百度实体解析 / 真实路线 / 商铺 POI（envelope 降级，任何失败不抛、不炸任务）──




async def _run_baidu_fanout(coros: List[Any]) -> None:
    """并发跑百度任务，阶段级总预算限时；超时任务取消（该项保持占位降级）。

    子任务体内部已吞异常（百度客户端本就 envelope 不抛），这里只兜住取消与预算。
    """
    if not coros:
        return
    tasks = [asyncio.create_task(c) for c in coros]
    _, pending = await asyncio.wait(tasks, timeout=_BAIDU_STAGE_BUDGET_S)
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _resolve_one_spot(dest: str, item: Dict[str, Any]) -> None:
    """单景点就地解析：地点检索精确匹配 → 地理编码兜底（置信度≥60）→ matched=False 占位。"""
    item["matched"] = False
    name = str(item.get("name") or "").strip()
    if not name:
        return
    r = baidu_client.place_search(name, dest)
    if r.get("ok"):
        hit = next((p for p in r["places"]
                    if _name_hit(name, p.get("name")) and p.get("lat") is not None
                    and p.get("lng") is not None), None)
        if hit:
            item.update({"lat": hit["lat"], "lng": hit["lng"], "matched": True})
            if hit.get("area") and not item.get("area"):
                item["area"] = hit["area"]
            return
    g = baidu_client.geocode(f"{dest}{name}", dest)
    if (g.get("ok") and g.get("lat") is not None
            and int(g.get("confidence") or 0) >= 60):
        item.update({"lat": g["lat"], "lng": g["lng"], "matched": True})


async def _resolve_spot_entities(dest: str, items: List[Dict[str, Any]]) -> bool:
    """并发解析冻结 TopN 景点坐标。返回百度通道是否可用（False→整体占位降级）。"""
    for it in items:
        it["matched"] = False
    if not items or not baidu_client.available():
        return False

    async def one(it: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(_resolve_one_spot, dest, it)
        except Exception:
            it["matched"] = False

    await _run_baidu_fanout([one(it) for it in items])
    return True


def _fmt_duration_sec(sec: Any) -> str:
    try:
        m = int(float(sec) / 60)
    except (TypeError, ValueError):
        return ""
    if m < 1:
        return "1分钟内"
    if m < 60:
        return f"约{m}分钟"
    return f"约{m // 60}小时{m % 60}分钟"


def _spot_routes_one(dest: str, origin: str, it: Dict[str, Any]) -> List[Dict[str, Any]]:
    """单景点逐条实际路线：公交/地铁（transit 最优）+ 打车（driving 里程估价，标「估算」）。"""
    coords = f"{it['lat']},{it['lng']}"
    routes: List[Dict[str, Any]] = []
    t = baidu_client.direction("transit", origin, coords, city=dest)
    if t.get("ok") and t["routes"]:
        best = t["routes"][0]
        vehicles = " → ".join(dict.fromkeys(
            s["vehicle"] for s in best["steps"] if s.get("vehicle"))) or "公交/地铁"
        try:
            km = f"，全程约{round(float(best.get('distance_m') or 0) / 1000, 1)}公里"
        except (TypeError, ValueError):
            km = ""
        routes.append({"mode": "公交/地铁", "duration": _fmt_duration_sec(best.get("duration_s")),
                       "cost": "", "transfer": vehicles[:80], "note": f"自市中心出发{km}",
                       "evidence_ids": []})
    d = baidu_client.direction("driving", origin, coords)
    if d.get("ok") and d["routes"]:
        best = d["routes"][0]
        est = baidu_client.taxi_estimate(best.get("distance_m"))
        cost = f"约{est['fare_yuan']}元（估算）" if est.get("ok") else ""
        routes.append({"mode": "打车", "duration": _fmt_duration_sec(best.get("duration_s")),
                       "cost": cost, "transfer": "", "note": "里程规则估价，实际以上车计价为准",
                       "evidence_ids": []})
    return routes


async def _build_spot_routes(dest: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为冻结榜每个景点规划真实路线（并发 + 阶段预算），产出 coerce_spot_routes 同形结构。

    行集由榜单决定、不由解析成功决定：没坐标或路线算不出的景点仍出一行、routes=[]，
    前端据此显示占位（旧实现按 matched 预筛，把未命中景点整行丢弃，
    真机表现为「Top7 只有 1 张路线卡」）。
    """
    targets = [it for it in items if it.get("spot_id")]
    if not targets or not baidu_client.available():
        return []
    g = await asyncio.to_thread(baidu_client.geocode, dest, "")
    if not g.get("ok"):
        return []
    origin = f"{g['lat']},{g['lng']}"
    results: Dict[str, List[Dict[str, Any]]] = {}

    async def one(it: Dict[str, Any]) -> None:
        if it.get("lat") is None or it.get("lng") is None:
            return  # 无坐标无从算路线：占位行，省掉必然失败的配额
        try:
            routes = await asyncio.to_thread(_spot_routes_one, dest, origin, it)
            if routes:
                results[it["spot_id"]] = routes
        except Exception:
            pass

    await _run_baidu_fanout([one(it) for it in targets])
    rows = [{"spot_id": it["spot_id"], "spot_name": it.get("name", ""),
             "routes": results.get(it["spot_id"], [])}
            for it in targets]  # 按榜单名次保序，可复现
    return [{"destination": dest, "items": rows}] if rows else []


_PROBE_STAGE_BUDGET_S = 90.0
_PROBE_CONCURRENCY = 4


def _probe_spot_perspective_one(dest: str, spot_name: str, tpls: Tuple[str, ...],
                                freshness: str, existing_urls: set,
                                collector: str, per_tpl: int = 2,
                                per_spot: int = 4, aborted=None) -> List["Evidence"]:
    """单景点定向二查（同步）：**逐探针**检索 → URL 去重 → 摘要构造 Evidence。

    不抓全文——二查供核查表填格，搜索摘要本身就是专项参数化事实源
    （票规/设施/机位/无障碍…随视角的 spot_probe_tpls 而变）；
    配额/密钥类终态（SearchProviderError）原样冒泡给阶段层做整体降级，不吞。

    ⚠️ 配额按**探针**分（per_tpl），不是整景点共用一个池子：先跑的探针命中满 4 条就会把
    后面探针的结果全挤出门外。实测亲子卷正是这个形状——独占一条探针的「儿童票规则」命中
    71%，而和别的词塞在同一条探针尾部的「母婴室」命中 0%。列与探针 1:1 配对时，
    per_spot 至少 2×列数才谈得上「每列有据」；否则多花的搜索次数只换来同一批 URL。
    瞬时失败按**单条探针**跳过（与 search.multi_search 的逐条容错同判据），
    一条探针挂了不牵连其余。
    """
    out: List[Evidence] = []
    for t in tpls:
        if len(out) >= per_spot:
            break
        # 服务商终态是**账号级**的：别的任务已判定 quota 时，本任务剩下的探针同一条也不会成，
        # 继续发只多烧配额。逐探针查一次（旧实现一次 multi_search 内部自己循环，无此检查点）。
        if aborted is not None and aborted():
            break
        try:
            results = search.search(f"{dest} {t.format(spot=spot_name)}",
                                    num=5, freshness=freshness)
        except SearchProviderError:
            raise
        except Exception:  # noqa: BLE001
            continue
        kept = 0
        for r in results:
            if kept >= per_tpl or len(out) >= per_spot:
                break
            url = r.get("url", "")
            snippet = str(r.get("snippet") or "").strip()
            if not url or not snippet or url in existing_urls:
                continue
            existing_urls.add(url)
            stype = classify_source(url)
            pub = r.get("captured_at", "")
            cred = score_evidence(url, stype, captured_at=pub or _now(),
                                  has_publish_date=bool(pub), ok_fetch=False,
                                  excerpt=snippet[:280])
            out.append(Evidence(evidence_id=_sid("e"), source_url=url, source_type=stype,
                                title=r.get("title", spot_name), excerpt=snippet[:280],
                                captured_at=pub or _now(), credibility=cred,
                                collected_by=collector, destination=dest,
                                domain=domain_of(url),
                                freshness_days=freshness_days(pub or _now()),
                                content_hash=content_fingerprint(snippet)))
            kept += 1
    return out


async def _probe_spot_perspective(dest: str, items: List[Dict[str, Any]],
                                  tpls: Tuple[str, ...], freshness: str,
                                  existing_urls: set, collector: str,
                                  probe_topn: int, per_tpl: int = 2,
                                  per_spot: int = 4) -> Dict[str, Any]:
    """冻结榜前 N 景点逐点二查（并发 ≤4 + 阶段预算，同百度 fan-out 两型）。

    `per_tpl` / `per_spot` 由注册表按**列数**算出（`RT.perspective_probe_budget`）：
    配额按探针分，才能保证每列都有证据可引用，见 `_probe_spot_perspective_one`。

    返回 {by_spot: {spot_id: [evidence_ids]}, evidences, failed, quota_error}。
    单点失败只记 failed（核查表该格占位）；SearchProviderError 属服务商终态——
    中止剩余任务（不再烧配额），整阶段由调用方降级为「仅槽位」+ 可见 thought。
    证据归属：evidences 表无景点列，spot_id 映射只活在编排期内存（评审 P1-2），
    由装配层写入核查表格内 evidence_ids，不改 DB schema。
    """
    targets = [it for it in items if it.get("spot_id")][:max(0, probe_topn)]
    by_spot: Dict[str, List[str]] = {}
    collected: List[Evidence] = []
    failed: List[str] = []
    quota_error: Optional[str] = None
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def one(it: Dict[str, Any]) -> None:
        nonlocal quota_error
        if quota_error:
            return
        async with sem:
            if quota_error:
                return
            try:
                evs = await asyncio.to_thread(_probe_spot_perspective_one, dest,
                                              str(it.get("name") or ""), tpls,
                                              freshness, existing_urls, collector,
                                              per_tpl, per_spot,
                                              lambda: quota_error is not None)
            except SearchProviderError as e:
                quota_error = str(e)
                return
            except Exception:
                failed.append(str(it["spot_id"]))
                return
        if evs:
            collected.extend(evs)
            by_spot[str(it["spot_id"])] = [e.evidence_id for e in evs]
        else:
            failed.append(str(it["spot_id"]))

    tasks = [asyncio.create_task(one(it)) for it in targets]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=_PROBE_STAGE_BUDGET_S)
        for t in pending:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"by_spot": by_spot, "evidences": collected, "failed": failed,
            "quota_error": quota_error}


def _shop_poi_one(dest: str, row: Dict[str, Any]) -> None:
    """商铺实体保真：百度 POI 精确命中则回填坐标与区域；LLM 只供价格与排队口碑。"""
    name = str(row.get("name") or "").strip()
    if not name:
        return
    r = baidu_client.place_search(name, dest)
    if not r.get("ok"):
        return
    hit = next((p for p in r["places"]
                if _name_hit(name, p.get("name")) and p.get("lat") is not None), None)
    if hit:
        row.update({"lat": hit["lat"], "lng": hit["lng"], "matched": True})
        if hit.get("area") and not row.get("area"):
            row["area"] = hit["area"]


async def _enrich_shops_with_poi(dest: str, shop_groups: List[Dict[str, Any]]) -> None:
    """商铺清单 POI 富化（就地回填 lat/lng/matched）；缺 AK 时静默跳过，前端出占位。"""
    if not shop_groups or not baidu_client.available():
        return
    rows = [x for grp in shop_groups if isinstance(grp, dict)
            for x in (grp.get("items") or []) if isinstance(x, dict)]
    if not rows:
        return

    async def one(x: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(_shop_poi_one, dest, x)
        except Exception:
            pass

    await _run_baidu_fanout([one(x) for x in rows])


def _shop_route_one(dest: str, origin: str, x: Dict[str, Any]) -> List[Dict[str, Any]]:
    """单商铺一条真实公交路线（transit 最优）；打车配额不适用（计划待确认 #4 拍板 transit）。"""
    coords = f"{x['lat']},{x['lng']}"
    t = baidu_client.direction("transit", origin, coords, city=dest)
    if not (t.get("ok") and t["routes"]):
        return []
    best = t["routes"][0]
    vehicles = " → ".join(dict.fromkeys(
        s["vehicle"] for s in best["steps"] if s.get("vehicle"))) or "公交/地铁"
    try:
        km = f"，全程约{round(float(best.get('distance_m') or 0) / 1000, 1)}公里"
    except (TypeError, ValueError):
        km = ""
    return [{"mode": "公交/地铁", "duration": _fmt_duration_sec(best.get("duration_s")),
             "cost": "", "transfer": vehicles[:80],
             "note": f"自市中心出发{km}", "evidence_ids": []}]


async def _attach_shop_routes(dest: str, shop_groups: List[Dict[str, Any]],
                              top_per_food: int) -> int:
    """商铺路线：每种美食按清单顺序取前 top_per_food 家 matched 商铺，并发挂公交路线。

    配额是硬约束（每食物 ≤top_per_food 条 direction 调用）；缺 AK / 无 matched 商铺时
    返回 0，前端走「数据源暂不可用」占位，不影响商铺清单本身。返回成功挂线数量。
    """
    if top_per_food <= 0 or not shop_groups or not baidu_client.available():
        return 0
    per_food: Dict[str, int] = {}
    targets: List[Dict[str, Any]] = []
    for grp in shop_groups:
        if not isinstance(grp, dict):
            continue
        for x in (grp.get("items") or []):
            if not isinstance(x, dict) or not x.get("matched"):
                continue
            if x.get("lat") is None or x.get("lng") is None:
                continue
            food = str(x.get("food") or "").strip() or "_"
            if per_food.get(food, 0) >= top_per_food:
                continue
            per_food[food] = per_food.get(food, 0) + 1
            targets.append(x)
    if not targets:
        return 0
    g = await asyncio.to_thread(baidu_client.geocode, dest, "")
    if not g.get("ok"):
        return 0
    origin = f"{g['lat']},{g['lng']}"

    async def one(x: Dict[str, Any]) -> None:
        try:
            routes = await asyncio.to_thread(_shop_route_one, dest, origin, x)
            if routes:
                x["routes"] = routes
        except Exception:
            pass

    await _run_baidu_fanout([one(x) for x in targets])
    return sum(1 for x in targets if x.get("routes"))


_CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _days_count(text: str) -> int:
    """用户原文的天数短语转整数（与 _DAY_PATTERNS 同一准绳，拿不到返回 0，不推断）。"""
    phrase = _days_from_text(text)
    if not phrase:
        return 0
    if phrase == "周末":
        return 2
    stem = phrase.rstrip("天日 ").strip()
    if stem.isdigit():
        return int(stem)
    if "十" in stem:
        tens, _, ones = stem.partition("十")
        return (_CN_DIGITS.get(tens, 1) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return _CN_DIGITS.get(stem, 0)


def _stop_arrival_digest(routes: List[Dict[str, Any]]) -> str:
    """景点抵达交通摘要：优先公交/地铁，退化打车；无真实路线数据返回空（占位不编造）。"""
    for mode_label, fmt in (("公交/地铁", "公交：{transfer}·{duration}"), ("打车", "打车：{duration}")):
        r = next((x for x in routes if x.get("mode") == mode_label), None)
        if r:
            filled = fmt.format(transfer=r.get("transfer") or mode_label,
                                duration=r.get("duration") or "")
            return filled.replace("：·", "：").replace("··", "·")
    return ""


def _assemble_itinerary(dest: str, spot_items: List[Dict[str, Any]],
                        route_groups: List[Dict[str, Any]],
                        shop_groups: List[Dict[str, Any]], days: int,
                        pace: int) -> List[Dict[str, Any]]:
    """一页视图（M3a/D2，guide 的 deep+expert 档）：把冻结榜单按名次逐日切分，抵达交通
    引用真实路线，商铺按清单顺序每天均衡挂一家——全部引用 spot_id/shop_id，不做名称二次匹配。

    天数优先用户原文与问卷答案（_days_count 双源），拿不到按 pace 推算；LLM 自由发挥的
    route_plan 在本档被整体覆盖（实体单一真相源原则的延伸）。
    纯函数、可单测、结果可复现。
    """
    if not spot_items:
        return []
    n = len(spot_items)
    span = days if days > 0 else max(1, -(-n // max(1, pace)))
    span = max(1, min(span, n))
    per = -(-n // span)
    span = -(-n // per)
    route_by_id = {row.get("spot_id"): (row.get("routes") or [])
                   for grp in (route_groups or []) if isinstance(grp, dict)
                   for row in (grp.get("items") or []) if isinstance(row, dict)}
    shops = [x for grp in (shop_groups or []) if isinstance(grp, dict)
             for x in (grp.get("items") or []) if isinstance(x, dict) and x.get("name")]
    days_out: List[Dict[str, Any]] = []
    si = 0
    for di in range(span):
        chunk = spot_items[di * per:(di + 1) * per]
        if not chunk:
            break
        stops: List[Dict[str, Any]] = []
        for it in chunk:
            stay = it.get("stay_minutes")
            tip = "；".join(x for x in (
                f"门票：{it['ticket']}" if it.get("ticket") else "",
                f"避峰：{it['off_peak']}" if it.get("off_peak") else "",
                f"位置：{it['area']}" if it.get("area") else "") if x)
            stops.append({
                "name": str(it.get("name") or ""),
                "spot_id": str(it.get("spot_id") or ""),
                "lat": it.get("lat"),
                "lng": it.get("lng"),
                "transport": _stop_arrival_digest(route_by_id.get(it.get("spot_id"), [])),
                "duration": f"约{stay}分钟" if stay else "",
                "tip": tip, "shop_id": "",
                "evidence_ids": list(it.get("evidence_ids") or []),
            })
        if si < len(shops):
            s = shops[si]
            si += 1
            price = s.get("price_per_person")
            stops.append({
                "name": f"美食停靠：{s.get('name')}",
                "spot_id": "",
                "transport": "",
                "duration": "约1小时",
                "tip": "；".join(x for x in (
                    str(s.get("food") or ""),
                    f"人均约{price}元（参考）" if price is not None else "",
                    str(s.get("queue_note") or "")) if x),
                "shop_id": str(s.get("shop_id") or ""),
                "evidence_ids": list(s.get("evidence_ids") or []),
            })
        days_out.append({"day": di + 1, "spots": stops})
    return [{"destination": dest, "days": days_out}]


# 逐景点舆情补充采集的并发预算（秒）：景点数×平台数 一次 fan-out，超时项直接缺省。
_SPOT_SENT_BUDGET_S = 90.0


async def _collect_spot_comments(spot_entities: List[Dict[str, Any]], platforms: List[str],
                                 region_q: str, per_take: int, freshness: str, dest: str,
                                 seen_urls: set,
                                 provider_errs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """逐景点舆情补充采集（并发 fan-out + 阶段预算）：每条评论挂 spot_id/spot_name，
    供 analyze_sentiment 做 (spot × platform) 双维聚合。

    - 只喂舆情统计、不生成证据对象：spots 在 analyze 之后，证据库口径不追溯扩容。
    - 相关性硬门槛：标题/摘要必须命中景点名（括号与空白归一后），杜绝题不对版。
    - 展平顺序按（榜单名次 × 平台序）确定 → 舆情样本可复现。
    - 服务商终态错误（欠费/Key）经 provider_errs 出参上报，由调用点出可见 thought 后降级。
    """
    jobs = [(rank, pidx, ent, plat)
            for rank, ent in enumerate(spot_entities)
            for pidx, plat in enumerate(platforms)]
    if not jobs or per_take <= 0:
        return []
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    errs: List[str] = provider_errs if provider_errs is not None else []

    async def one(rank: int, pidx: int, ent: Dict[str, Any], plat: str) -> None:
        spot_name = str(ent.get("name") or "").strip()
        if not spot_name:
            return
        if errs:  # 已确认欠费：一条即止，剩余任务不再烧检索
            buckets[(rank, pidx)] = []
            return
        # 两条查询都要口碑。旧写法第二条要「攻略」——而攻略页正是 doc_kind 会判成 guide
        # 并排除出词云的那一类，等于自己往自己桶里灌将被丢弃的样本（查询条数不变，只换措辞）。
        queries = [f"{spot_name} 真实评价{region_q}", f"{spot_name} 体验 吐槽{region_q}"]
        try:
            results = await asyncio.to_thread(search.multi_search, queries, num=per_take + 4,
                                              site=PLATFORMS[plat].search_site,
                                              freshness=freshness)
            if not results:  # 站内受限时回退：全网检索 + 平台关键词
                results = await asyncio.to_thread(
                    search.multi_search, [f"{spot_name} 评价 {PLATFORM_LABEL.get(plat, plat)}{region_q}"],
                    num=per_take + 4, freshness=freshness)
        except SearchProviderError as e:
            errs.append(str(e))
            buckets[(rank, pidx)] = []
            return
        picked: List[Dict[str, Any]] = []
        for r in results:
            url, title = r.get("url", ""), r.get("title", "")
            text = (r.get("snippet") or title or "").strip()
            if not url or not text or not _name_hit(spot_name, f"{title} {text}"):
                continue
            detected = classify_source(url)
            doc_kind, _reasons = classify_doc(url, title, text)
            picked.append({
                "text": text[:280], "url": url, "title": title,
                "platform": plat if detected in ("web", "official", "news") else detected,
                "destination": dest,
                "spot_id": str(ent.get("spot_id") or ""), "spot_name": spot_name,
                # 与目的地级同一判据（app.core.doc_kind），供逐景点词云分流
                "doc_kind": doc_kind,
            })
        buckets[(rank, pidx)] = picked[:per_take]

    tasks = [asyncio.create_task(one(*j)) for j in jobs]
    _, pending = await asyncio.wait(tasks, timeout=_SPOT_SENT_BUDGET_S)
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for rank, pidx, _ent, _plat in jobs:
        for c in buckets.get((rank, pidx), []):
            if c["url"] in seen_urls:
                continue
            seen_urls.add(c["url"])
            out.append(c)
    return out
