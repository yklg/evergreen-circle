# -*- coding: utf-8 -*-
"""1c · 外部时变源可行性探针（信号配时 / 信号灯几何 / 覆盖偏置）。

要回答的问题（见 `docs/常青圈_作品介绍.md` §9.2 的 1c）：
「红绿灯、施工围挡这类**随时刻变化**的因素，除了百度步行测时那根已被证伪的时刻轴之外，
还有没有别的数据源可接？」OSM 是候选之一，本探针把它探到底。

三问分别对应三个 Overpass 键：
  sig  `highway=traffic_signals`        —— 路口信号灯**几何**在不在图上
  dir  `traffic_signals:direction`      —— 有没有标它管哪个方向
  sch  `traffic_signals:schedule`       —— 有没有**配时排程**（时变建模真正需要的那一位）

半径读 `scope.BLIND_RADIUS_M`（判盲共用的那把尺），不写字面量；样区中心读出厂夹具，不手抄。

零配额：只打 Overpass 公共端点，**不碰百度接口**。

用法（在 backend/ 下）：
    .venv/bin/python scripts/probe_timevarying_sources.py
    .venv/bin/python scripts/probe_timevarying_sources.py --radius 1500   # 换尺复量

花费控制：每个样区 1 次请求（三键合一查询），样区数 = 夹具去重后的中心点数；请求间隔 6s。
判据自证：一次查询必须回 `len(KEYS)` 段 `out count`，段数不符即 **拒绝出结论**（否则会拿
"少回一段"误读成"该键计数为 0"）。⚠️ 已知假阴面：Overpass 的 0 只表示**该时刻未测绘**，
不表示现场没有信号灯 —— 读数只能用来判"这个源可不可依赖"，不能用来判"有没有"。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.living_circle import scope  # noqa: E402  判盲半径的唯一真源

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]
USER_AGENT = "evergreen-circle-feasibility/1.0 (offline time-varying source probe)"
KEYS = [
    ("sig", 'node["highway"="traffic_signals"]'),
    ("dir", 'node["traffic_signals:direction"]'),
    ("sch", 'node["traffic_signals:schedule"]'),
]
FIXTURE_DIR = BACKEND / "app" / "living_circle" / "fixtures"
RECEIPT = BACKEND / "tmp" / "probe_1c_timevarying_receipt.json"


def samples() -> list[dict]:
    """从出厂夹具取样区中心（按中心点去重，避免同一地点的变体副本重复外呼）。"""
    out: dict[tuple, dict] = {}
    for f in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        root = data.get("living_circle") or data  # 两种壳都吃：整份 Report 或裸 living_circle 载荷
        scene = root.get("scene") or {}
        center = scene.get("center")
        if not center or root.get("data_origin") != "live":
            continue
        key = (round(float(center[0]), 6), round(float(center[1]), 6))
        out.setdefault(key, {"fixture": f.name, "name": scene.get("name"), "center": list(center)})
    return list(out.values())


def build_query(lat: float, lng: float, radius: float) -> str:
    parts = [f"[out:json][timeout:40];"]
    for name, sel in KEYS:
        parts.append(f'{sel}(around:{radius:g},{lat},{lng})->.{name};')
    for name, _ in KEYS:
        parts.append(f'(.{name};);out count;')
    return "".join(parts)


def fetch(query: str, tries: int = 6) -> str:
    """公共端点会限流/504 ⇒ 临时故障换一台镜像重试。

    重试口径照本仓红线：**临时超时 / 5xx / 连接被对端掐断**最多 3 轮；
    **4xx（含权限、参数错）不重试**——那是我们的请求有问题，重试只会白打端点。
    全部失败时把错误原文抛出去（回执里逐条记，不吞）。
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    errors = []
    for attempt in range(tries):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        req = urllib.request.Request(endpoint, data=body, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = f"{endpoint.split('/')[2]}: HTTP {exc.code}"
            if exc.code < 500:  # 4xx 是我们的问题，不重试
                raise RuntimeError(f"端点拒绝（不重试）：{detail} —— {' '.join(str(exc.read()[:200], 'utf-8', 'replace').split())}") from exc
            errors.append(detail)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            # ConnectionError 覆盖 RemoteDisconnected（不被 URLError 包住的形态，曾把整轮探针打断）
            errors.append(f"{endpoint.split('/')[2]}: {type(exc).__name__}: {exc}")
        else:
            if '"count"' in text:
                return text
            errors.append(f"{endpoint.split('/')[2]}: 返回里没有 out count 段")
        time.sleep(10 * (attempt // len(ENDPOINTS) + 1))
    raise RuntimeError(f"三台镜像各试过 {tries // len(ENDPOINTS) or 1} 轮仍失败 —— " + " | ".join(errors[-3:]))


def parse_counts(text: str) -> dict[str, int]:
    """按 out count 的语句顺序取 total；段数不符直接判废，不猜。"""
    totals = [
        int(dict(re.findall(r'"(\w+)":\s*"(\d+)"', m.group(1))).get("total", -1))
        for m in re.finditer(r'"tags":\s*\{(.*?)\}', text, re.S)
    ]
    if len(totals) != len(KEYS):
        raise RuntimeError(f"期望 {len(KEYS)} 段读数，实得 {len(totals)} —— 口径不成立，本次结论作废")
    return {name: totals[i] for i, (name, _) in enumerate(KEYS)}


def osm_timestamp(text: str) -> str:
    m = re.search(r'"timestamp_osm_base":\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="1c 外部时变源可行性探针（零百度配额）")
    ap.add_argument("--radius", type=float, default=None, help="查询半径（米），默认取 scope.BLIND_RADIUS_M")
    args = ap.parse_args()

    radius = args.radius if args.radius is not None else float(scope.BLIND_RADIUS_M)
    rows = samples()
    print(f"样区数 {len(rows)} · 半径 {radius:g}m（scope.BLIND_RADIUS_M={scope.BLIND_RADIUS_M:g}）· 键 {[k for k, _ in KEYS]}")

    receipt = {"probe": "1c-external-time-varying-sources", "mirrors": ENDPOINTS,
               "radius_m": radius, "radius_source": "CLI" if args.radius else "scope.BLIND_RADIUS_M",
               "keys": {k: s for k, s in KEYS}, "samples": [], "requests": 0, "osm_base": ""}

    for i, s in enumerate(rows):
        lng, lat = s["center"]
        try:
            text = fetch(build_query(lat, lng, radius))
            counts = parse_counts(text)
        except RuntimeError as exc:
            receipt["samples"].append({**s, "error": str(exc)})
            print(f"  {str(s['name']):12} 取数失败：{exc}")
            continue
        receipt["requests"] += 1
        receipt["osm_base"] = receipt["osm_base"] or osm_timestamp(text)
        receipt["samples"].append({**s, "counts": counts})
        print(f"  {str(s['name']):12} 信号灯={counts['sig']:4} 带方向={counts['dir']:4} 带配时={counts['sch']:4}")
        if i < len(rows) - 1:
            time.sleep(6)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOSM 数据基线时刻：{receipt['osm_base']}")
    print(f"回执 → {RECEIPT.relative_to(BACKEND)}（tmp/ 已 ignore，不入库）")

    ok = [r for r in receipt["samples"] if "counts" in r]
    failed = len(receipt["samples"]) - len(ok)
    sig_total = sum(r["counts"]["sig"] for r in ok)
    sch_total = sum(r["counts"]["sch"] for r in ok)
    print(f"合计（{len(ok)}/{len(rows)} 个样区取到数）：信号灯几何 {sig_total} 处 · 配时排程 {sch_total} 处")
    if failed:
        print(f"⚠️ {failed} 个样区未取到数 ⇒ 本次是**部分读数**，不许当完整结论用（回执里逐条记了失败原因）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
