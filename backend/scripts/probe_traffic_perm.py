#!/usr/bin/env python3
"""实时路况查询（Traffic API）· 权限与返回字段探针（计划步骤 1）。

要回答的两件事：
  ① 当前这把 AK 有没有开通「实时路况查询 API」——文档明写 2018-08-31 前注册的 AK 默认无权限，
     而本仓已经撞过一次同族形态：官方等时圈服务返回 `status=240`「APP 服务被禁用」
     （见 `app/living_circle/capability_manifest.json` 的 `isochrone_service`）；
  ② 它**到底返回什么字段**——我始终没能从文档站核到字段清单（页面是前端渲染，两次抓取只拿到空壳），
     所以这一枪就是去取这份证据：有没有可换算的量化量（拥堵里程/平均速度/指数），
     还是只有状态枚举；以及**返不返回路段几何/路段名**（后者关系到赛题"不取底层路网"那条口径）。

零猜测原则：端点路径按"命名族"逐个试，**404 不算失败**（那是路径猜错，零成本）；
只有拿到非 404 响应才停。重试口径照本仓红线：临时超时/5xx 最多 1 次，4xx 一律不重试。

用法（在 backend/ 下）：
    .venv/bin/python scripts/probe_traffic_perm.py
花费：正常 1 次调用（最多 3 次，全是 404 时也不会产生配额消耗）。
回执：`backend/tmp/probe_traffic_perm_receipt.json`（已 ignore），含每次尝试的**原始 body**。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
RECEIPT = BACKEND / "tmp" / "probe_traffic_perm_receipt.json"
BASE = "https://api.map.baidu.com"

# 端点候选：来自百度文档的**命名族**（`/traffic/v1/*`），不是已核验的清单 —— 这正是本探针要证的。
# 顺序按本方案的用法排：先区域（我们要拿环的多边形/矩形），再周边。
CANDIDATES = [
    # 先按百度区域检索的惯例 `lat,lng` 试；报「范围过大」时优先怀疑经纬顺序被反解（见下一条）
    ("bound", "/traffic/v1/bound", lambda b: {"bounds": b["bounds"]}),
    ("bound_lnglat", "/traffic/v1/bound", lambda b: {"bounds": b["bounds_lnglat"]}),
    ("bound_small", "/traffic/v1/bound", lambda b: {"bounds": b["bounds_small"]}),
    ("around", "/traffic/v1/around", lambda b: {"center": b["center"], "radius": "1000"}),
    ("road", "/traffic/v1/road", lambda b: {"road_name": "建国路", "city": "北京"}),
]


def load_env(path: Path) -> None:
    """轻量 .env 加载（照 scripts/probe_baidu.py 的做法，不引 python-dotenv）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def mask(s: str) -> str:
    return s[:3] + "****" + s[-3:] if s and len(s) > 8 else "****"


def jinsong_bbox() -> dict:
    """劲松 15min 环的外接矩形（城市样区，最可能被路况服务覆盖）。

    用**出厂夹具的真实多边形**算 bbox——零外呼、与产品同源；不手抄坐标。
    """
    lc = json.loads((BACKEND / "app/living_circle/fixtures/beijing-jinsong.json").read_text(encoding="utf-8"))
    ring = next(z["geojson"]["coordinates"][0] for z in lc["isochrones"] if z["minutes"] == 15)
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    sw, ne = (min(lats), min(lngs)), (max(lats), max(lngs))
    center = ((min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2)
    mid_span = 0.004  # ≈450m 的小框：用来区分"面积上限"与"顺序反解"
    return {
        "bounds": f"{sw[0]:.6f},{sw[1]:.6f};{ne[0]:.6f},{ne[1]:.6f}",
        "bounds_lnglat": f"{sw[1]:.6f},{sw[0]:.6f};{ne[1]:.6f},{ne[0]:.6f}",
        "bounds_small": (f"{center[0]-mid_span:.6f},{center[1]-mid_span:.6f};"
                         f"{center[0]+mid_span:.6f},{center[1]+mid_span:.6f}"),
        "center": f"{center[0]:.6f},{center[1]:.6f}",
        "ring_points": len(ring), "span_km": round((ne[0] - sw[0]) * 111.32, 2),
    }


def field_inventory(obj, depth: int = 0, max_depth: int = 3) -> dict:
    """逐层列键与类型——**只列结构不抄值**（拥堵状态词这类枚举值例外，单独收集）。"""
    if depth > max_depth:
        return {"...": "depth-limit"}
    if isinstance(obj, dict):
        return {k: field_inventory(v, depth + 1, max_depth) for k, v in list(obj.items())[:30]}
    if isinstance(obj, list):
        return {"[list]": field_inventory(obj[0], depth + 1, max_depth) if obj else "empty",
                "len": len(obj)}
    return type(obj).__name__


def numeric_leaves(obj, path: str = "") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += numeric_leaves(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj[:2]:
            out += numeric_leaves(v, f"{path}[]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(path.lstrip("."))
    return out


def try_call(ak: str, name: str, path: str, params_of, bbox: dict, tries: int = 2) -> dict:
    params = dict(params_of(bbox), ak=ak, output="json")
    # 自证闸：参数值必须是字符串。上一版把整个 bbox dict 传给了 `bounds`，URL 里成了 JSON 串，
    # 百度回 `bounds参数错误` —— 差一点把"我传错了"读成"接口参数形状不对"。
    bad = {k: type(v).__name__ for k, v in params.items() if not isinstance(v, str)}
    if bad:
        raise SystemExit(f"探针参数自检失败（值必须是字符串）：{bad}")
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    rec = {"name": name, "path": path, "params": {**{k: v for k, v in params.items() if k != "ak"}, "ak": mask(ak)}}
    for attempt in range(tries):
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=12) as resp:
                body = resp.read().decode("utf-8", "replace")
                rec.update(http_status=resp.status, latency_ms=int((time.time() - t0) * 1000))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            rec.update(http_status=exc.code, latency_ms=int((time.time() - t0) * 1000))
            if exc.code == 404:
                rec["body_raw"] = body[:800]
                rec["verdict"] = "路径不存在（候选猜错，零成本）"
                return rec
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt + 1 < tries:
                time.sleep(3)
                continue
            rec.update(http_status=None, error=f"{type(exc).__name__}: {exc}")
            return rec
        break
    rec["body_bytes"] = len(body)
    rec["body_raw"] = body[:4000]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        rec["verdict"] = "非 JSON 响应（先看 body_raw）"
        return rec
    rec["status_field"] = data.get("status")
    rec["status_meaning"] = {0: "正常", 2: "参数错", 240: "APP 服务被禁用（该服务未为此 AK 开通）",
                             302: "配额/额度类", 401: "AK 无效"}.get(data.get("status"), "未登记")
    rec["field_inventory"] = field_inventory(data)
    rec["numeric_leaves"] = numeric_leaves(data)[:40]
    blob = json.dumps(data, ensure_ascii=False)
    rec["has"] = {
        "拥堵状态枚举": any(w in blob for w in ("畅通", "缓行", "拥堵", "严重")),
        "量化字段(里程/速度/指数)": any(w in blob for w in ("distance", "speed", "index", "里程", "速度", "指数")),
        "路段几何/坐标": any(w in blob for w in ("geo", "coordinates", "polyline", "路段")),
    }
    rec["verdict"] = ("有权限" if data.get("status") == 0 else f"未能用（status={data.get('status')}，{rec['status_meaning']}）")
    return rec


def main() -> int:
    load_env(BACKEND / ".env")
    ak = os.environ.get("BAIDU_SERVER_AK", "")
    if not ak:
        print("缺 BAIDU_SERVER_AK（backend/.env）")
        return 1
    bbox = jinsong_bbox()
    print(f"服务端 AK: {mask(ak)} | 样区 bbox 取劲松 15min 环（{bbox['ring_points']} 点，跨度 {bbox['span_km']}km）\n")

    attempts = []
    for name, path, fn in CANDIDATES:
        rec = try_call(ak, name, path, fn, bbox)
        attempts.append(rec)
        print(f"[{name:6}] {path} → http={rec.get('http_status')} status={rec.get('status_field')} "
              f"latency={rec.get('latency_ms')}ms | {rec.get('verdict', rec.get('error', ''))}")
        # 只有真拿到数据（status=0）才停；404（路径猜错）与 status=2（参数形状不对，换候选可能对）
        # 都继续试；其余（240 未开通 / 401 AK 无效 / 网络失败）换候选也救不了，停。
        if rec.get("status_field") == 0:
            break
        if rec.get("http_status") not in (404, None) and rec.get("status_field") != 2:
            break

    receipt = {"probe": "traffic-perm", "ak_masked": mask(ak), "bbox": bbox, "attempts": attempts,
               "called_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "calls_spent": sum(1 for a in attempts if a.get("http_status") not in (404, None))}
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n回执 → {RECEIPT.relative_to(BACKEND)}（tmp/ 已 ignore）")
    ok = [a for a in attempts if a.get("status_field") == 0]
    if ok:
        print("三态判定：**有权限** —— 按 has 三项决定倍数表能不能实测标定")
    elif attempts and attempts[-1].get("http_status") == 404:
        print("三态判定：**路径未命中** —— 端点名不是这一族，需换候选（零配额消耗）")
    else:
        print("三态判定：**拿不到**（见回执 status_meaning）—— 走计划里的失败出口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
