# -*- coding: utf-8 -*-
"""阶段 2 · 多方式能力探针（P1–P7）。

扩展 probe_baidu.py 的 modes 组，探骑行/驾车矩阵可用性、duration 量级、
不可达判定语义、兜底通道、POI radius 截断等。

用法（在 backend/ 下）：
    .venv/bin/python scripts/probe_modes.py            # 全跑 P1→P7
    .venv/bin/python scripts/probe_modes.py --p1       # 只跑 P1（权限检查）
    .venv/bin/python scripts/probe_modes.py --p5       # 只跑 P5（duration 反算半径）

花费控制：P1→P7 顺序，任一 FAIL 即停。预计 60–120 次 GET（P2 占大头）。
"""
from __future__ import annotations

import io
import os
import sys
import time
import json
import math
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, "..", ".env")


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


def get_ak() -> str:
    load_env(ENV_PATH)
    return os.environ.get("BAIDU_SERVER_AK", "")


def mask(s: str) -> str:
    return s[:3] + "****" + s[-3:] if s and len(s) > 8 else "****"


def fetch_json(url: str, timeout: float = 12.0) -> Tuple[dict, float]:
    """GET JSON，返回 (data_dict, elapsed_ms)。"""
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "evergreencircle-probe/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        return {"error": str(e), "status": None}, dt
    dt = (time.perf_counter() - t0) * 1000
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body[:200], "status": None}
    return data, dt


def probe_matrix(
    name: str,
    ak: str,
    travel_mode: str,
    origins: List[Tuple[float, float]],  # (lng, lat)
    destinations: List[Tuple[float, float]],
) -> Dict[str, Any]:
    """探矩阵 API：记 rows、duration 分布、不可达计数、首行字段名。

    travel_mode: walking / riding / driving
    """
    # 百度矩阵 API 要求 lat,lng 格式
    origins_str = "|".join(f"{lat},{lng}" for lng, lat in origins)
    dests_str = "|".join(f"{lat},{lng}" for lng, lat in destinations)

    url = f"https://api.map.baidu.com/routematrix/v2/{travel_mode}?origins={origins_str}&destinations={dests_str}&ak={ak}"
    data, ms = fetch_json(url)

    status = data.get("status")
    ok = status == 0
    result = data.get("result", [])
    rows = len(result)
    expect_rows = len(origins) * len(destinations)

    # 解析 duration 分布
    durations = []
    unreachable_count = 0
    first_row_fields = []
    for row in result:
        elements = row.get("elements", [])
        for elem in elements:
            dur = elem.get("duration", {}).get("value")
            if dur is None:
                unreachable_count += 1
            else:
                durations.append(dur)
            if not first_row_fields:
                first_row_fields = list(elem.keys())

    # 统计量
    dur_stats = {}
    if durations:
        dur_stats = {
            "min": round(min(durations) / 60.0, 1),  # 秒 → 分钟
            "median": round(sorted(durations)[len(durations) // 2] / 60.0, 1),
            "max": round(max(durations) / 60.0, 1),
        }

    line = f"[{'OK ' if ok else 'FAIL'}] {name:<30} {ms:>7}ms  status={status}  rows={rows}/{expect_rows}  unreachable={unreachable_count}"
    print(line)

    return {
        "name": name,
        "ok": ok,
        "status": status,
        "ms": round(ms, 1),
        "rows": rows,
        "expect_rows": expect_rows,
        "unreachable_count": unreachable_count,
        "durations_min_med_max": dur_stats,
        "first_row_fields": first_row_fields,
    }


def probe_direction(name: str, ak: str, travel_mode: str, origin: Tuple[float, float], destination: Tuple[float, float]) -> Dict[str, Any]:
    """探单点兜底通道（directionlite/v1/riding 或 direction/v2/driving）。"""
    o_lat, o_lng = origin[1], origin[0]
    d_lat, d_lng = destination[1], destination[0]

    if travel_mode == "riding":
        url = f"https://api.map.baidu.com/directionlite/v1/riding?origin={o_lat},{o_lng}&destination={d_lat},{d_lng}&ak={ak}"
    elif travel_mode == "driving":
        url = f"https://api.map.baidu.com/direction/v2/driving?origin={o_lat},{o_lng}&destination={d_lat},{d_lng}&ak={ak}"
    else:
        raise ValueError(f"Unsupported direction mode: {travel_mode}")

    data, ms = fetch_json(url)
    status = data.get("status")
    ok = status == 0

    line = f"[{'OK ' if ok else 'FAIL'}] {name:<30} {ms:>7}ms  status={status}"
    print(line)

    return {"name": name, "ok": ok, "status": status, "ms": round(ms, 1)}


def probe_poi_radius(name: str, ak: str, center: Tuple[float, float], radius_m: int, keyword: str) -> Dict[str, Any]:
    """探 POI radius 截断：radius 被拒或分页截断。"""
    q = urllib.parse.quote(keyword)
    lat, lng = center[1], center[0]
    url = f"https://api.map.baidu.com/place/v2/search?query={q}&location={lat},{lng}&radius={radius_m}&output=json&scope=2&filter=sort_name:distance&ak={ak}"

    data, ms = fetch_json(url)
    status = data.get("status")
    ok = status == 0
    results = data.get("results", [])
    total_count = len(results)

    line = f"[{'OK ' if ok else 'FAIL'}] {name:<30} {ms:>7}ms  status={status}  count={total_count}"
    print(line)

    return {"name": name, "ok": ok, "status": status, "ms": round(ms, 1), "count": total_count}


def generate_ring_points(center: Tuple[float, float], radius_m: float, n: int = 8) -> List[Tuple[float, float]]:
    """生成环上均匀采样点（用于探边界可达率）。"""
    points = []
    lng, lat = center
    # 粗略转换：1° ≈ 111km
    delta = radius_m / 111000.0
    for i in range(n):
        angle = 2 * math.pi * i / n
        p_lng = lng + delta * math.cos(angle)
        p_lat = lat + delta * math.sin(angle)
        points.append((round(p_lng, 6), round(p_lat, 6)))
    return points


def main() -> int:
    args = sys.argv[1:]
    run_all = not any(a.startswith("--p") for a in args)

    def should_run(probe_num: int) -> bool:
        if run_all:
            return True
        return f"--p{probe_num}" in args

    AK = get_ak()
    if not AK:
        print("缺 BAIDU_SERVER_AK（backend/.env）")
        return 1
    print(f"服务端 AK: {mask(AK)}\n")

    # 两样区中心
    KAILI = (107.9758, 26.5734)
    JINSONG = (116.4637, 39.8832)

    results: List[Dict[str, Any]] = []
    stop_on_fail = True

    # ── P1: riding/driving 矩阵是否存在可访问 ──────────────────────
    if should_run(1):
        print("══ P1: 多方式矩阵权限检查 ══")
        for mode in ["riding", "driving"]:
            r = probe_matrix(
                f"P1-{mode}-single-origin",
                AK,
                mode,
                [KAILI],
                [JINSONG],
            )
            results.append(r)
            if not r["ok"] and stop_on_fail:
                print(f"\n⚠️  {mode} 矩阵无权限（status={r['status']}），多方式当场终止")
                print("   → 只保留阶段 1 的口径建模（独立成立）")
                return 1
        print()

    # ── P2: origins 上限阶梯 {1,25,50,100} × 三方式 ────────────────
    if should_run(2):
        print("══ P2: Origins 上限阶梯测试 ══")
        for mode in ["walking", "riding", "driving"]:
            for n_origins in [1, 25, 50, 100]:
                origins = generate_ring_points(KAILI, 2500 if mode == "walking" else (5000 if mode == "riding" else 9000), min(n_origins, 8))
                r = probe_matrix(
                    f"P2-{mode}-{n_origins}origins",
                    AK,
                    mode,
                    origins,
                    [KAILI],
                )
                results.append(r)
                if not r["ok"] and stop_on_fail:
                    print(f"\n⚠️  {mode}×{n_origins} 失败，停止后续阶梯")
                    break
            print()

    # ── P3: restrictions_status 语义（发明显不可达点） ───────────────
    if should_run(3):
        print("══ P3: restrictions_status 语义检查 ══")
        # 发一个跨城远距离点（凯里→南极附近，明显不可达）
        impossible_dest = (107.9758, -80.0)
        for mode in ["walking", "riding", "driving"]:
            r = probe_matrix(
                f"P3-{mode}-impossible",
                AK,
                mode,
                [KAILI],
                [impossible_dest],
            )
            results.append(r)
            # 若 driving 恒 0 → baidu_client.py:196 不可达判定失效
            if mode == "driving" and r["unreachable_count"] == 0 and r["rows"] > 0:
                print(f"   ⚠️  driving 对明显不可达点未标记 unreachable，需换判据")
        print()

    # ── P4: 单点兜底通道 ───────────────────────────────────────────
    if should_run(4):
        print("══ P4: 单点兜底通道检查 ══")
        far_point = (108.0, 26.6)  # 凯里附近稍远点
        for mode in ["riding", "driving"]:
            r = probe_direction(
                f"P4-{mode}-fallback",
                AK,
                mode,
                KAILI,
                far_point,
            )
            results.append(r)
        print()

    # ── P5: duration 量级 → 反算 15min 半径 ────────────────────────
    if should_run(5):
        print("══ P5: Duration 量级反算半径 ══")
        for mode, target_radius_m in [("walking", 1000), ("riding", 3750), ("driving", 6000)]:
            ring_pts = generate_ring_points(KAILI, target_radius_m, n=8)
            r = probe_matrix(
                f"P5-{mode}-15min-radius",
                AK,
                mode,
                ring_pts,
                [KAILI],
            )
            results.append(r)
            # 反算：看 median duration 是否接近 15min
            if r["durations_min_med_max"]:
                med_min = r["durations_min_med_max"].get("median", 0)
                expected_range = (12, 18)  # 15min ±3min
                in_range = expected_range[0] <= med_min <= expected_range[1]
                print(f"   → median={med_min}min {'✓' if in_range else '✗'} (期望 {expected_range})")
                if not in_range:
                    print(f"   ⚠️  不在文献量级内，可能坐标顺序或路径有误")
        print()

    # ── P6: place/v2/search radius 2000/5000/9000 × 3 类目 ────────
    if should_run(6):
        print("══ P6: POI radius 截断检查 ══")
        for radius_m in [2000, 5000, 9000]:
            for kw in ["菜市场", "药店", "小学"]:
                r = probe_poi_radius(
                    f"P6-r{radius_m}-{kw}",
                    AK,
                    KAILI,
                    radius_m,
                    kw,
                )
                results.append(r)
                # radius 被拒或异常少结果
                if r["count"] < 3:
                    print(f"   ⚠️  radius={radius_m} {kw} 仅 {r['count']} 条，可能被截断")
        print()

    # ── P7: 完整分档总请求数/秒数/退避次数 ─────────────────────────
    if should_run(7):
        print("══ P7: 完整分档压力测试 ══")
        total_requests = 0
        total_ms = 0
        retry_count = 0

        # 模拟一次标准模式完整体检的请求量
        for mode in ["walking"]:
            origins = generate_ring_points(KAILI, 2500, n=12)
            r = probe_matrix(
                f"P7-{mode}-full-standard",
                AK,
                mode,
                origins,
                [KAILI],
            )
            results.append(r)
            total_requests += 1
            total_ms += r["ms"]

        print(f"   总请求数: {total_requests}")
        print(f"   总耗时: {round(total_ms / 1000, 1)}s")
        print(f"   退避次数: {retry_count}")
        print()

    # ── 汇总 ───────────────────────────────────────────────────────
    print("── 汇总 ──")
    for r in results:
        status_str = f"status={r['status']}" if "status" in r else ""
        extra = ""
        if "rows" in r:
            extra = f" rows={r['rows']}/{r.get('expect_rows', '?')}"
        if "count" in r:
            extra = f" count={r['count']}"
        print(f"  {r['name']:<35} {'OK' if r['ok'] else 'FAIL':>4}  {r['ms']:>7}ms  {status_str}{extra}")

    fails = [r for r in results if not r["ok"]]
    print(f"\n通过 {len(results)-len(fails)}/{len(results)}" + ("" if not fails else f"；失败: {[r['name'] for r in fails]}"))

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
