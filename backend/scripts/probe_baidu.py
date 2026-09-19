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