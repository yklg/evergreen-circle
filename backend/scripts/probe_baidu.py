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