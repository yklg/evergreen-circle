# -*- coding: utf-8 -*-
"""M0 百度地图能力探针（真实 AK 冒烟）。

目标：验证 6 类服务端 API 的可用性、返回结构、耗时与限流表现，
据此定型等时圈实现分支（批量算路 vs 并发单点）并校准 F0 契约字段。

用法（在 backend/ 下）：
    .venv/bin/python scripts/probe_baidu.py            # 全部
    .venv/bin/python scripts/probe_baidu.py poiroute   # 只看某组

安全：密钥只从环境读取；任何输出均脱敏（AK 只显示前 3 后 3）。
"""
from __future__ import annotations

import io
import math
import os
import sys
import time
import json
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, "..", ".env")


def mask(s: str) -> str:
    return s[:3] + "****" + s[-3:] if s and len(s) > 8 else "****"


def load_env(path: str) -> None:
    """轻量 .env 加载（避免依赖 python-dotenv）。"""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def get(ak_var: str) -> str:
    load_env(ENV_PATH)
    return os.environ.get(ak_var, "")


def fetch(url: str, timeout: float = 12.0) -> dict:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "evergreencircle-probe/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    dt = (time.perf_counter() - t0) * 1000
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body[:200]}
    return {"ms": round(dt, 1), "data": data}


def probe(name: str, url: str) -> dict:
    res = fetch(url)
    d = res["data"]
    status = d.get("status")
    ok = status == 0
    line = f"[{'OK ' if ok else 'FAIL'}] {name:<22} {res['ms']:>7}ms  status={status}"
    print(line)
    return {"name": name, "ok": ok, "status": status, "ms": res["ms"], "msg": d.get("message", "")}


def probe_place_capacity(AK: str, center: str = "26.5734,107.9758") -> dict:
    """`place` 组 · P0-1 取证：单页上限、`total` 语义、条数能否判别截断。

    **为什么需要这一组**：既有 manifest 的 `poi_search` 写着
    `max_results_per_query: 10` + `truncation_risk: "low"`，而下面的 `poi` 组**从未传
    `page_size`** ⇒ 它看到的是百度默认每页 10 条。「没观察到分页截断」其实是
    「没给足发生截断的机会」—— 一个假阴性，而生产代码 `baidu_client.py` 请求的是 20。

    三件必须分开回答的事，本组各自给出可核对的读数：
      1. `page_size_max` —— 请求多大，百度**真的**给多大（不降级、不报错）；
      2. `total_is_hit_count` —— `resp["total"]` 是「命中总数」还是「本页条数」；
         只有前者成立，`CollectionEvidence.saturated` 才可以用 `returned < total` 判饱和；
      3. `len_alone_decisive` —— 只看待返回条数能否区分「查全了」与「被截断」。
         已知答案大概率是 False（`len == page_size` 两种情形同值），这里把它**测出来**
         而不是写在注释里 —— 这正是本仓「探针回填，非硬编码」的纪律（`caliber.py:13-19`）。
    """
    DENSE = "药店"          # 稠密类别：凯里城区 2km 内必然远超一页，才能压出截断
    out: dict = {"query": DENSE, "radius_m": 2000, "per_page_size": {}}

    for ps in (10, 20, 30, 50):
        url = (
            f"https://api.map.baidu.com/place/v2/search?query={urllib.parse.quote(DENSE)}"
            f"&location={center}&radius=2000&output=json&scope=2&page_size={ps}"
            f"&page_num=0&filter=sort_name:distance&ak={AK}"
        )
        res = fetch(url)
        d = res["data"]
        got = len(d.get("results") or [])
        total = d.get("total")
        row = {
            "status": d.get("status"),
            "msg": d.get("message", ""),
            "returned": got,
            "total": total,
            "honored": d.get("status") == 0 and got == ps,
        }
        out["per_page_size"][str(ps)] = row
        print(f"[place] page_size={ps:<3} status={row['status']} returned={got:<3} "
              f"total={total} honored={row['honored']}")

    honored = [int(k) for k, v in out["per_page_size"].items() if v["honored"]]
    out["page_size_max"] = max(honored) if honored else None

    # `total` 语义：稠密类别下 total 明显大于本页条数 ⇒ 它是命中总数，可用于判饱和
    ok_rows = [v for v in out["per_page_size"].values() if v["status"] == 0]
    out["total_is_hit_count"] = bool(ok_rows) and any(
        (v["total"] or 0) > v["returned"] for v in ok_rows
    )
    # 条数能否判别截断：只要存在 `returned == page_size` 的样本，就**不能**单凭条数判别
    out["len_alone_decisive"] = not any(
        v["returned"] == int(k) for k, v in out["per_page_size"].items() if v["status"] == 0
    )
    out["notes"] = (
        f"实测单页上限={out['page_size_max']}；total"
        f"{'可' if out['total_is_hit_count'] else '不可'}用作命中总数；"
        f"{'条数足以' if out['len_alone_decisive'] else '条数不足以'}单独判别分页截断"
        "（⇒ 饱和判据须走 stop_reason/total，不能靠 len）"
    )
    print(f"\n[place] {out['notes']}")
    return out


def probe_evidence_frontier(AK: str, center: str = "26.5734,107.9758", radius_m: int = 2500,
                            pages: int = 4) -> dict:
    """`frontier` 组 · 把「翻余量能买到多少判定」从推测变成实测。

    P0-1 已证：单页硬上限 20 条、`total` 是命中总数、条数本身不可判截断。于是唯一还能
    扩大证据面的手段是**多翻页**，而每页 = 1 次调用 = 1 个 POI 预算单位（免费档共 27）。
    所以「给三要素加页深」不是免费午餐 —— 它按单位从展示词手里抢预算（P0-2 会饿死展示词）。

    本组按类别逐页取回，记录**第 k 近设施的球面距离**，于是能直接读出：
      - `farthest_m`：本页深下证据边界（第 n 近的点离中心多远）；
      - `honest_judge_r = max(0, farthest_m − 1000)`：该页深下**诚实的**可判定半径；
      - `complete`：`returned < total` 是否已消除（查全了 ⇒ 边界可视为 radius_m）。
    有了这三列，「三要素各要几页」「展示侧要饿死几个词」就是算术，不是争论。
    """
    lat0, lng0 = (float(x) for x in center.split(","))
    out: dict = {"radius_m": radius_m, "page_size": 20, "categories": {}}

    for kw in ("药店", "菜市场", "小学"):
        rows, total, seen = [], None, []
        for pg in range(pages):
            url = (
                f"https://api.map.baidu.com/place/v2/search?query={urllib.parse.quote(kw)}"
                f"&location={center}&radius={radius_m}&output=json&scope=2&page_size=20"
                f"&page_num={pg}&filter=sort_name:distance&ak={AK}"
            )
            d = fetch(url)["data"]
            if d.get("status") != 0:
                rows.append({"page": pg, "status": d.get("status"), "msg": d.get("message", "")})
                break
            items = d.get("results") or []
            total = d.get("total", total)
            for it in items:
                loc = it.get("location") or {}
                try:
                    seen.append(_haversine_m(lat0, lng0, float(loc["lat"]), float(loc["lng"])))
                except (KeyError, TypeError, ValueError):
                    continue
            far = max(seen) if seen else 0.0
            rows.append({
                "page": pg,
                "cum_returned": len(seen),
                "total": total,
                "complete": total is not None and len(seen) >= total,
                "farthest_m": round(far, 1),
                "honest_judge_r_m": round(max(0.0, far - 1000.0), 1),
            })
            if len(items) < 20 or (total is not None and len(seen) >= total):
                break          # 短页/已查全 ⇒ 再翻无意义
        out["categories"][kw] = {"total": total, "pages": rows}
        print(f"\n[frontier] {kw}  total={total}")
        for r in rows:
            print(f"  第{r.get('page', '?')}页 累计={r.get('cum_returned', '—'):<4} "
                  f"查全={str(r.get('complete', '—')):<5} 边界={r.get('farthest_m', '—')}m "
                  f"⇒ 诚实可判半径={r.get('honest_judge_r_m', '—')}m")
    return out


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """球面距离（米）。探针自带一份，不 import app 模块 —— 探针要在装不上依赖时也能跑。"""
    to_rad = math.pi / 180.0
    p1, p2 = lat1 * to_rad, lat2 * to_rad
    dp, dl = (lat2 - lat1) * to_rad, (lng2 - lng1) * to_rad
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


# ── 4a｜"动态"这根轴到底存不存在（能力核实 + 测时误差率自证）──────────────
#
# ⚠️ **本组不在默认列表里**：它花真实配额（一次运行 10 次调用），必须显式点名
#    `.venv/bin/python scripts/probe_baidu.py timeaxis` 才跑。默认列表跑的是零成本/已排期的组。
#
# 三条设计约束，缺一条整个探针就白跑：
# 1. **未知参数会被静默忽略** ⇒ 「status=0、值没变」绝不等于「不支持该参数」。
#    所以必须有一枚**垃圾参数阴性对照**（`probe_deadbeef_4a=1`）：它若也 status=0 且值不变，
#    就证明百度这一层的响应形状对未知键**没有鉴别力**，此时所有阴性结论只能写成
#    「未观察到可观测差异」，不能写成「接口不支持」。这是本探针最容易犯的错，先钉在这。
# 2. **差异必须越过噪声地板** ⇒ 同参数、同点位先连跑两次当基线；参数变体的逐点差
#    只有在**超过基线逐点差**时才算证据。驾车档尤其需要（若它本身带实时路况，逐秒就会抖）。
# 3. **误差率要能 gate 残差的解释力** ⇒ β（残差进评分的权重）一直悬着不拍，等的就是
#    「单点测时噪声到底多大」这个数（计划 §剩余待确认 3）。因此这里同时给三档读数：
#    同窗可重复性（纯噪声）、跨日漂移（含时刻/路况/版本变更）、以及它们与残差量级
#    （八类最近设施 −1.9…+4.3min）的比值 —— 噪声与信号同量级 ⇒ 残差不能进评分。
MATRIX_PATHS = {"walking": "/routematrix/v2/walking", "riding": "/routematrix/v2/riding",
                "driving": "/routematrix/v2/driving"}
DEADBEEF = "probe_deadbeef_4a"        # 阴性对照键：任何真实接口都不该认识它
# 候选时刻/路况参数名：来自百度自己文档页的标题与命名族（direction 系有
# 「未来驾车路线规划」「驾车路线历史耗时」两页，正文是 JS 渲染、抓不到参数表），
# 所以这里**按候选处理**、逐个用值变化来判，而不是照抄文档当已证。
CANDIDATE_PARAMS = {
    "departure_time_epoch": {"departure_time": None},   # None ⇒ 运行时填 now+2h 的秒级时间戳
    "departure_time_str": {"departure_time": None},     # 填 "YYYY-MM-DD HH:MM:SS" 形态
    "time_epoch": {"time": None},
    "traffic_on": {"traffic": "1"},
}


def _matrix_once(ak: str, mode: str, pts: list, dest_latlng, extra: dict | None = None,
                 raw: bool = False) -> dict:
    """一次批量矩阵调用（与生产 `baidu_client._measure_matrix` 同形状：origins 为 lat,lng、
    一行一 origin、duration 秒→分钟、缺失/None 视为不可达）。

    ⚠️ 坐标顺序是**这个探针第一次白跑 13 次调用换来的**：百度这一族接口一律 `lat,lng`，
    而生产 `measure_matrix` 的形参是 `(lng, lat)` 元组、在函数内部才倒过来
    （`dest = f"{destination[1]},{destination[0]}"`）。形参名叫 `dest` 时极易在这里少倒一次
    ⇒ `status=2 destinations is invalid`、整批零数据。这里把形参改名成 `dest_latlng`
    并**直接按顺序拼**，让"要不要倒"这个问题在签名上消失，而不是靠注释提醒。

    只复用**参数形状与解析规则**，不复用 `BaiduClient`：探针要绕开 CallGuard 才能把
    「这次花了几次调用」写在回执里自查（生产闸是进程内的，探针不走它就没人记账 ——
    这正是必须显式点名才跑的原因之一）。
    """
    params = {
        "origins": "|".join(f"{lat},{lng}" for lng, lat in pts),
        "destinations": f"{dest_latlng[0]},{dest_latlng[1]}",
        **(extra or {}),
        "ak": ak,
        "output": "json",
    }
    url = "https://api.map.baidu.com" + MATRIX_PATHS[mode] + "?" + urllib.parse.urlencode(params)
    try:
        res = fetch(url, timeout=20.0)
    except Exception as exc:  # noqa: BLE001 —— 探针不能中途崩：一次失败要变成一行读数，
        # 否则前面几次的调用白花、回执也落不下来（失败如实进回执，不静默跳过）。
        return {"status": None, "message": f"transport_error: {type(exc).__name__}: {exc}",
                "ms": None, "rows": 0, "minutes": [], "row_fields": [], "top_fields": [],
                "extra_params": {k: v for k, v in (extra or {}).items()}}
    d = res["data"]
    raw = d.get("result")
    rows = raw.get("rows") if isinstance(raw, dict) else raw
    rows = rows or []
    mins: list = []
    field_names: set = set()
    for row in rows:
        if isinstance(row, dict):
            field_names.update(row.keys())
        dur = row.get("duration") if isinstance(row, dict) else None
        value = dur.get("value") if isinstance(dur, dict) else dur
        mins.append(None if value is None else round(float(value) / 60.0, 1))
    return {
        "status": d.get("status"),
        "message": d.get("message", ""),
        "ms": res["ms"],
        "rows": len(rows),
        "minutes": mins,
        "row_fields": sorted(field_names),
        "top_fields": sorted(d.keys()),
        "raw_rows": rows if raw else None,
        "extra_params": {k: v for k, v in (extra or {}).items()},
    }


def _boundary_points(lc: dict, want: int = 20) -> tuple:
    """从**已落库的实跑点位**里确定性地挑 `want` 个「可达区边界内外」的点。

    为什么直接用存量 `sampling.points` 而不是重造一遍采样器：`sample_plan`/`build_sample_points`
    造的点是中心点的扇形+网格，重跑一次等于引入第二套采样事实源；而边界判定 `in_reach`
    本来就产在这些点上，取它们才是"同一批点、同一口径、只换一次测时"。
    选点规则（无随机数 ⇒ 可复跑逐位一致）：取实测耗时落在满分线 ±4min 带内的点，
    按 `in_reach` 分两半各 10 个，每半再按 45° 方位分桶轮转取样 ⇒ 角度铺开、不挤在一个象限。
    """
    ring_min = float((lc.get("caliber") or {}).get("reach_full_min") or 20.0)
    pts = [p for p in ((lc.get("sampling") or {}).get("points") or [])
           if p.get("timed") and isinstance(p.get("minutes"), (int, float))
           and p["minutes"] > 0 and abs(p["minutes"] - ring_min) <= 4.0]
    center = (lc.get("scene") or {}).get("center") or []
    if len(pts) < want or len(center) != 2:
        return [], center

    def bucket(p):
        ang = math.degrees(math.atan2(p["lat"] - center[1], p["lng"] - center[0])) % 360.0
        return int(ang // 45)

    picked = []
    for flag in (True, False):
        group = sorted((p for p in pts if bool(p.get("in_reach")) is flag),
                       key=lambda p: (bucket(p), p["minutes"], p["idx"]))
        buckets: dict = {}
        for p in group:
            buckets.setdefault(bucket(p), []).append(p)
        order = sorted(buckets)
        want_half = want // 2
        taken, round_i = [], 0
        while len(taken) < want_half:
            picked_in_round = False
            for b in order:
                if round_i < len(buckets[b]):
                    taken.append(buckets[b][round_i])
                    picked_in_round = True
                    if len(taken) == want_half:
                        break
            if not picked_in_round:
                break
            round_i += 1
        picked.extend(taken)
    picked.sort(key=lambda p: p["idx"])
    return picked, center


def _stats(a: list, b: list) -> dict:
    """两组逐点分钟数的对照（只统计两侧都测到且 >0 的点，其余显式计数、不静默丢）。"""
    deltas, missing = [], {"a_null": 0, "b_null": 0, "both_null": 0}
    for x, y in zip(a, b):
        if x is None or y is None:
            if x is None and y is None:
                missing["both_null"] += 1
            elif x is None:
                missing["a_null"] += 1
            else:
                missing["b_null"] += 1
            continue
        deltas.append(y - x)
    if not deltas:
        return {"n_compared": 0, "identical": 0, "mean_abs_min": None,
                "p90_abs_min": None, "max_abs_min": None, "signed_mean_min": None,
                "mean_rel_pct": None, **missing}
    ad = sorted(abs(v) for v in deltas)
    n = len(ad)
    base_sum = sum(x for x, y in zip(a, b) if x is not None and y is not None)
    return {
        "n_compared": n,
        "identical": sum(1 for v in ad if v < 0.05),
        "mean_abs_min": round(sum(ad) / n, 2),
        "p90_abs_min": ad[min(n - 1, int(round(0.9 * (n - 1))))],
        "max_abs_min": round(ad[-1], 1),
        "signed_mean_min": round(sum(deltas) / n, 2),
        # 相对误差只做**旁注**：残差的量纲纪律（一律分钟、不换算成百分比）管的是可达性产物，
        # 这里的百分比是"测时自证"的读数，写进名册时必须带上这条区分。
        "mean_rel_pct": round(100.0 * sum(ad) / base_sum, 1) if base_sum else None,
        **missing,
    }


def probe_time_axis(ak: str, reports: list) -> dict:
    """`timeaxis` 组 · 4a 的两次真实调用串：能力核实 + 误差率自证。"""
    out: dict = {"probe": "timeaxis", "ak_masked": mask(ak), "calls": 0, "communities": {},
                 "capability": {}, "caveats": []}
    now_epoch = int(time.time())
    cand_vals = {
        "departure_time_epoch": str(now_epoch + 2 * 3600),
        "departure_time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_epoch + 7200)),
        "time_epoch": str(now_epoch + 2 * 3600),
        "traffic_on": "1",
    }
    kaili_pts = None
    preflight_done = False
    for rid, cname in reports:
        lc = _load_lc(rid)
        pts, center = _boundary_points(lc, want=20)
        if not pts:
            print(f"[timeaxis] {cname} 边界带点数不足，跳过")
            continue
        dest = (center[1], center[0])       # (lat, lng) —— 百度这一族接口一律 lat,lng
        coords = [(p["lng"], p["lat"]) for p in pts]
        stored = [p["minutes"] for p in pts]
        if not preflight_done:
            # **止损闸**：先用 1 个 origin 发一次，确认请求形状与解析都对，再放后续 12 次出去。
            # 这条不是防御性冗余，是本探针的第一次真实事故写下来的：坐标顺序写反时，
            # 一次运行把 13 次额度全花在 `status=2 destinations is invalid` 上、零行数据。
            pre = _matrix_once(ak, "walking", coords[:1], dest); out["calls"] += 1
            preflight_done = True
            if pre["status"] != 0 or len(pre["minutes"]) != 1 or pre["minutes"][0] is None:
                out["aborted"] = (f"preflight status={pre['status']} message={pre['message']} "
                                  f"rows={pre['rows']} ⇒ 请求形状或能力不通，立即停手不再发后续调用")
                print(f"[timeaxis] {out['aborted']}")
                return out
        pass_a = _matrix_once(ak, "walking", coords, dest); out["calls"] += 1
        if pass_a["status"] != 0 or pass_a["rows"] != len(coords):
            out["aborted"] = (f"基线 status={pass_a['status']} message={pass_a['message']} "
                              f"need={len(coords)} got={pass_a['rows']} ⇒ 停手（后续变体无可比对象）")
            print(f"[timeaxis] {out['aborted']}")
            return out
        time.sleep(1.2)                     # 留出跨秒间隔，免得把"同一秒的同一份缓存"当成可重复性
        pass_b = _matrix_once(ak, "walking", coords, dest); out["calls"] += 1
        block = {
            "report_id": rid,
            "n_points": len(coords),
            "ring_min": float((lc.get("caliber") or {}).get("reach_full_min") or 20.0),
            "in_reach_n": sum(1 for p in pts if p.get("in_reach")),
            "angles_n": len({int(math.degrees(math.atan2(p["lat"] - center[1],
                                                         p["lng"] - center[0])) // 45) for p in pts}),
            "stored_generated_at": lc.get("generated_at"),
            "stored_minutes": stored,
            "pass_a": pass_a, "pass_b": pass_b,
            # 约定：`signed_mean_min` = 后者 − 前者。噪声地板两侧同侧（今天−今天），
            # 跨日那档刻意写成「今天 − 9 月 30 日那次」⇒ 正号意味着今天测得更久。
            "noise_floor": _stats(pass_a["minutes"], pass_b["minutes"]),
            "cross_day_drift": _stats(stored, pass_b["minutes"]),
        }
        if cname == "凯里":
            kaili_pts = (coords, dest, pass_a, block)
        out["communities"][cname] = block
        nf, cd = block["noise_floor"], block["cross_day_drift"]
        print(f"[timeaxis] {cname} n={block['n_points']} 方位桶={block['angles_n']} "
              f"同窗重复: 逐位相同 {nf['identical']}/{nf['n_compared']} "
              f"max|Δ|={nf['max_abs_min']}min | 跨日: mean|Δ|={cd['mean_abs_min']} "
              f"p90={cd['p90_abs_min']} max={cd['max_abs_min']} 带符号均值={cd['signed_mean_min']}")

    # ── 能力核实：只在凯里那一批点上做参数变体（同一批点、同一目的地，才可比）
    if kaili_pts:
        coords, dest, base, base_block = kaili_pts
        floor_max = base_block["noise_floor"]["max_abs_min"]
        variants = {"_deadbeef_control": {DEADBEEF: "1"}}
        for name, tmpl in CANDIDATE_PARAMS.items():
            key = next(iter(tmpl))
            variants[name] = {key: cand_vals[name]}
        driving_base = _matrix_once(ak, "driving", coords[:20], dest); out["calls"] += 1
        time.sleep(1.2)
        driving_rep = _matrix_once(ak, "driving", coords[:20], dest); out["calls"] += 1
        out["capability"]["driving_repeat"] = _stats(driving_base["minutes"], driving_rep["minutes"])
        out["capability"]["driving_row_fields"] = driving_base["row_fields"]
        out["capability"]["driving_top_fields"] = driving_base["top_fields"]
        out["capability"]["walking_row_fields"] = base["row_fields"]
        out["capability"]["walking_top_fields"] = base["top_fields"]
        trials = [("walking", v) for v in variants.items()] + [
            ("driving", ("_deadbeef_control", {DEADBEEF: "1"})),
            ("driving", ("departure_time_epoch", {"departure_time": cand_vals["departure_time_epoch"]})),
        ]
        rows = []
        for mode, (vname, extra) in trials:
            time.sleep(1.0)
            r = _matrix_once(ak, mode, coords[:20], dest, extra); out["calls"] += 1
            ref = base if mode == "walking" else driving_base
            floor = floor_max if mode == "walking" else out["capability"]["driving_repeat"]["max_abs_min"]
            st = _stats(ref["minutes"], r["minutes"])
            rows.append({"mode": mode, "variant": vname, "params": extra, "status": r["status"],
                         "message": r["message"], "noise_floor_min": floor, "vs_baseline": st,
                         "changed_beyond_floor": bool(st["n_compared"]) and (
                             st["max_abs_min"] or 0.0) > (floor or 0.0)})
            print(f"[timeaxis] {mode:<8} {vname:<24} status={r['status']} "
                  f"改动点数={st['n_compared'] - st['identical']} max|Δ|={st['max_abs_min']} "
                  f"（地板 {floor}）越线={rows[-1]['changed_beyond_floor']}")
        out["capability"]["variants"] = rows
        ctrl = [r for r in rows if r["variant"] == "_deadbeef_control"]
        out["capability"]["unknown_param_rejected"] = bool(ctrl) and any(
            r["status"] not in (0, None) for r in ctrl)
        out["capability"]["noise_floor_max_min"] = floor_max
        out["caveats"].append(
            "垃圾参数对照若 status=0 且值不变 ⇒ 百度这一层对未知键无鉴别力，"
            "所有阴性只能写成「未观察到可观测差异」，不得写成「接口不支持」。")
    return out


def _ensure_app_path() -> None:
    """把 `backend/` 放进 sys.path：脚本的 sys.path[0] 是 scripts/，不含仓库根。"""
    root = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_lc(report_id: str) -> dict:
    """读一份已落库报告（唯一取数出口＝`app.core.db`，探针不自己开第二条 SQL 通路）。"""
    _ensure_app_path()
    from app.core.db import get_living_circle_report
    rec = get_living_circle_report(report_id)
    return (rec or {}).get("living_circle") or {}


def _pick_reports(want_cities: tuple) -> list:
    """按**现场 DB 里真实存在**的实跑报告选点，不硬编 report id。

    取每个目标社区里 `generated_at` 最新、且边界带内点数足够的那一份 —— 硬编 id 会让探针
    在某次清库/重跑之后悄悄选到一份点少的旧件，误差率就在 8 个点上算出来了还自称 20。
    """
    _ensure_app_path()
    from app.core.db import list_living_circle_reports
    best: dict = {}
    for row in list_living_circle_reports(limit=80):
        rid = row.get("id") or row.get("report_id")
        if not rid:
            continue
        lc = _load_lc(rid)
        if (lc.get("data_origin") or "") != "live":
            continue
        scene = (lc.get("scene") or {}).get("name") or ""
        hit = next((w for w in want_cities if w in scene), None)
        if not hit:
            continue
        pts, _ = _boundary_points(lc, want=20)
        if len(pts) < 20:
            continue
        stamp = lc.get("generated_at") or ""
        if stamp > best.get(hit, ("", ""))[0]:
            best[hit] = (stamp, rid)
    return [(best[w][1], w) for w in want_cities if best.get(w, ("", ""))[1]]


def probe_row_fields(ak: str, reports: list) -> dict:
    """`rowfields` 组 · 4a 的续问：百度步行矩阵回带的 `retrograde_dist` / `restrictions_status`
    到底是什么，我们为什么一直没读它们。

    起因是 `timeaxis` 那一跑的结构读数：生产 `baidu_client._measure_matrix` 只取
    `duration.value`，而响应里每行其实有四个字段 —— 两个我们**零消费**。按本仓纪律
    （先盘已算好却没消费的数据），这比"百度有没有路况"更值得先问清：若 `retrograde_dist`
    真的按点在给绕行距离，它就是 P2 那个"受阻代理"的**现成上游信号**，比我们从残差反推更直接。
    一次一批点（每社区 1 次调用），把 20 行原样落进回执。
    """
    out: dict = {"probe": "rowfields", "ak_masked": mask(ak), "calls": 0, "communities": {}}
    for rid, cname in reports:
        lc = _load_lc(rid)
        pts, center = _boundary_points(lc, want=20)
        if len(pts) < 20:
            continue
        dest = (center[1], center[0])
        coords = [(p["lng"], p["lat"]) for p in pts]
        r = _matrix_once(ak, "walking", coords, dest, raw=True); out["calls"] += 1
        if r["status"] != 0 or r["rows"] != len(coords):
            out["communities"][cname] = {"error": f"status={r['status']} {r['message']}"}
            print(f"[rowfields] {cname} status={r['status']} {r['message']}")
            continue
        rows = r["raw_rows"]

        def _num(v):
            return v.get("value") if isinstance(v, dict) else v

        cells = []
        for p, row in zip(pts, rows):
            if not isinstance(row, dict):
                continue
            cells.append({
                "idx": p["idx"], "in_reach": bool(p.get("in_reach")),
                "stored_min": p["minutes"], "api_min": _num(row.get("duration")),
                "dist_m": _num(row.get("distance")),
                "restrictions_status": row.get("restrictions_status"),
                "retrograde_dist": row.get("retrograde_dist"),
            })
        retro = [c["retrograde_dist"] for c in cells]
        restr = [c["restrictions_status"] for c in cells]
        out["communities"][cname] = {
            "report_id": rid, "n": len(cells), "rows": cells,
            "retrograde_dist": {
                "distinct_values": sorted({str(v) for v in retro}),
                "nonnull_count": sum(1 for v in retro if v is not None),
                "nonzero_count": sum(1 for v in retro
                                     if isinstance(v, (int, float)) and v not in (0, 0.0)),
            },
            "restrictions_status": {
                "distinct_values": sorted({str(v) for v in restr}),
                "nonnull_count": sum(1 for v in restr if v is not None),
            },
        }
        c0 = out["communities"][cname]["retrograde_dist"]
        r0 = out["communities"][cname]["restrictions_status"]
        print(f"[rowfields] {cname} n={len(cells)} retrograde_dist 非空 {c0['nonnull_count']}/{len(cells)} "
              f"非零 {c0['nonzero_count']} 取值={c0['distinct_values'][:6]} | "
              f"restrictions_status 非空 {r0['nonnull_count']} 取值={r0['distinct_values'][:6]}")
    return out


def main() -> int:
    groups = sys.argv[1:] or ["geo", "poi", "route", "matrix", "conv", "geocode"]
    AK = get("BAIDU_SERVER_AK")
    if not AK:
        print("缺 BAIDU_SERVER_AK（backend/.env）")
        return 1
    print(f"服务端 AK: {mask(AK)}  |  组: {','.join(groups)}\n")

    KAILI = "26.5734,107.9758"     # 百度坐标参数一律 lat,lng
    JINSONG = "39.8832,116.4637"
    results = []

    if "frontier" in groups:  # 逐页实测证据边界 ⇒ 「诚实可判半径」到底能推多远
        fr = probe_evidence_frontier(AK, KAILI)
        results.append({
            "name": "evidence frontier",
            "ok": bool(fr["categories"]),
            "status": 0 if fr["categories"] else -1,
            "ms": 0,
            "msg": "逐页 farthest_m / honest_judge_r_m",
        })
        print(json.dumps({"evidence_frontier": fr}, ensure_ascii=False, indent=2))

    if "place" in groups:  # P0-1 取证：单页上限 / total 语义 / 条数可否判别截断
        cap = probe_place_capacity(AK, KAILI)
        results.append({
            "name": "place capacity",
            "ok": cap["page_size_max"] is not None,
            "status": 0 if cap["page_size_max"] else -1,
            "ms": 0,
            "msg": cap["notes"],
        })
        print(json.dumps({"poi_search_probe": cap}, ensure_ascii=False, indent=2))

    if "timeaxis" in groups:  # 4a｜花配额：时刻/路况能力核实 + 20 点二次测时误差率
        picked = _pick_reports(("凯里", "劲松"))
        if not picked:
            print("[timeaxis] 现场 DB 里没有边界带点数足够的 live 报告 ⇒ 拒绝开跑（不许改用编点凑数）")
            return 1
        print(f"[timeaxis] 选中的实跑报告: {[(r, c) for r, c in picked]}\n")
        ta = probe_time_axis(AK, picked)
        ta["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt_dir = os.path.join(SCRIPT_DIR, "..", "tmp")
        os.makedirs(receipt_dir, exist_ok=True)
        receipt = os.path.join(receipt_dir, "probe_4a_timeaxis_receipt.json")
        with open(receipt, "w", encoding="utf-8") as f:
            json.dump(ta, f, ensure_ascii=False, indent=2)
        print(f"\n[timeaxis] 真实调用次数 = {ta['calls']}（探针绕开 CallGuard，故此处自行记账）")
        print(f"[timeaxis] 回执已落盘: {receipt}")
        print(json.dumps({k: ta[k] for k in ("capability", "caveats")}, ensure_ascii=False, indent=2))
        for cname, blk in ta["communities"].items():
            print(f"[timeaxis] {cname} 噪声地板={blk['noise_floor']} 跨日漂移={blk['cross_day_drift']}")

    if "rowfields" in groups:  # 4a 续问｜步行矩阵里那两个零消费字段的真实取值（每社区 1 次调用）
        picked = _pick_reports(("凯里", "劲松"))
        if not picked:
            print("[rowfields] 现场 DB 里没有可用的 live 报告 ⇒ 拒绝开跑")
            return 1
        rf = probe_row_fields(AK, picked)
        rf["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt_dir = os.path.join(SCRIPT_DIR, "..", "tmp")
        os.makedirs(receipt_dir, exist_ok=True)
        path = os.path.join(receipt_dir, "probe_4a_rowfields_receipt.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rf, f, ensure_ascii=False, indent=2)
        print(f"[rowfields] 真实调用次数 = {rf['calls']}｜回执: {path}")

    if "geo" in groups:  # 逆地理编码（确认中心点坐标/地址）
        results.append(probe("reverse_geocode kaili",
            f"https://api.map.baidu.com/reverse_geocoding/v3/?ak={AK}&location={KAILI}&output=json&coordtype=bd09ll&extensions_poi=1"))

    if "geocode" in groups:  # 地理编码（地名→坐标）
        q = urllib.parse.quote("凯里市西门街道")
        results.append(probe("geocode kaili street",
            f"https://api.map.baidu.com/geocoding/v3/?address={q}&output=json&ak={AK}"))
        q2 = urllib.parse.quote("北京市朝阳区劲松街道")
        results.append(probe("geocode jinsong street",
            f"https://api.map.baidu.com/geocoding/v3/?address={q2}&output=json&ak={AK}"))

    if "poi" in groups:  # POI 分类检索（周边 radius 口径）
        # ⚠️ 本组**不传 page_size** ⇒ 看到的是百度默认每页 10 条。既有 manifest 里
        #    `poi_search.max_results_per_query: 10` / `truncation_risk: "low"` 就是它留下的
        #    假阴性（生产代码请求 20 条/页）。要回答「会不会被截断」请看 `place` 组。
        for kw in ["菜市场", "药店", "小学"]:
            q = urllib.parse.quote(kw)
            results.append(probe(f"poi {kw}@kaili 2km",
                f"https://api.map.baidu.com/place/v2/search?query={q}&location={KAILI}&radius=2000&output=json&scope=2&filter=sort_name:distance&ak={AK}"))

    if "route" in groups:  # 步行方向 API（单点测时，lat,lng）
        results.append(probe("walk directionlite kaili",
            f"https://api.map.baidu.com/directionlite/v1/walking?origin={KAILI}&destination=26.5734,107.9858&ak={AK}"))

    if "matrix" in groups:  # 批量距离矩阵（walking）—— R2 关键验证
        origins = "26.5734,107.9758|26.5750,107.9850|26.5700,107.9700|26.5800,107.9800"
        dest = "26.5734,107.9758"
        results.append(probe("routematrix walking 4x1",
            f"https://api.map.baidu.com/routematrix/v2/walking?origins={origins}&destinations={dest}&ak={AK}"))

    if "conv" in groups:  # 坐标转换（GCJ-02→BD-09，赛题评分点）
        results.append(probe("geoconv gcj2bd",
            f"https://api.map.baidu.com/geoconv/v1/?coords=116.397428,39.90923&from=1&to=5&ak={AK}"))

    print("\n── 汇总 ──")
    for r in results:
        print(f"  {r['name']:<24} {'OK' if r['ok'] else 'FAIL'}  {r['ms']}ms  status={r['status']}")
    fails = [r for r in results if not r["ok"]]
    print(f"\n通过 {len(results)-len(fails)}/{len(results)}" + ("" if not fails else f"；失败组: {[r['name'] for r in fails]}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())