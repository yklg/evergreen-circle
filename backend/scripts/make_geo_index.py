"""生成内置全国省市区三级区划 + 区县中心坐标（离线地名定位数据，T1/A1）。

数据来源（均在文件头注明，可复现）：
  1. 层级名称与行政代码：xiangyuecn/AreaCity-JsSpider-StatsGov → `ok_data_level3.csv`
     （民政部行政区划口径；https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov）
  2. 中心坐标：阿里 DataV 公共行政区划边界 `https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json`
     （properties.center，[lng, lat]；民政部口径，公共资源）
     DataV 层级约定：省文件返回其子级=地级市（直辖市子级=区县）；区县中心须按「市代码」二级请求。

用法：cd backend && .venv/bin/python -m scripts.make_geo_index
产出：backend/app/living_circle/geo_index/china_regions.json（随仓库提交，运行时零网络依赖）
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LEVEL3_CSV_URL = (
    "https://cdn.jsdelivr.net/gh/xiangyuecn/AreaCity-JsSpider-StatsGov@master/"
    "src/%E9%87%87%E9%9B%86%E5%88%B0%E7%9A%84%E6%95%B0%E6%8D%AE/ok_data_level3.csv"
)
DATAV_FULL_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
DATAV_PROV_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json"

OUT = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "geo_index" / "china_regions.json"


def _fetch(url: str, tries: int = 3) -> bytes:
    """带节流重试的下载（DataV 公共资源，礼貌限速即可，无需长退避）。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lc-geo-index/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def _load_level3() -> List[Dict[str, Any]]:
    raw = _fetch(LEVEL3_CSV_URL).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "pid": r["pid"],
            "deep": int(r["deep"]),
            "name": r["name"],
            "full_name": r["ext_name"].strip() or r["name"],
            "adcode6": r["ext_id"].strip()[:6],
        })
    return out


def _prov_centers() -> Dict[str, List[float]]:
    d = json.loads(_fetch(DATAV_FULL_URL).decode("utf-8"))
    return {
        f["properties"]["adcode"]: f["properties"]["center"]
        for f in d["features"]
        if f["properties"].get("center")
    }


def _prov_cities(adcode6: str) -> List[Tuple[str, str, Optional[List[float]]]]:
    """省 adcode → [(市 adcode, 市名, 市中心)]。

    DataV 层级：省文件子级=地级市；直辖市（上海/北京/天津/重庆）子级=区县（此处返回空）。
    """
    try:
        d = json.loads(_fetch(DATAV_PROV_URL.format(adcode=adcode6)).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return [
        (f["properties"]["adcode"], f["properties"]["name"], f["properties"].get("center"))
        for f in d["features"]
        if f["properties"].get("level") == "city"
    ]


def _direct_districts(adcode6: str) -> Dict[str, List[float]]:
    """直辖市：省文件子级即为区县（level=='district'）→ 直接取中心。"""
    try:
        d = json.loads(_fetch(DATAV_PROV_URL.format(adcode=adcode6)).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        f["properties"]["name"]: f["properties"]["center"]
        for f in d["features"]
        if f["properties"].get("level") == "district" and f["properties"].get("center")
    }


def _district_centers(city_adcode: str) -> Dict[str, List[float]]:
    """市 adcode → {区县名: center}（DataV 市文件子级=区县）。"""
    try:
        d = json.loads(_fetch(DATAV_PROV_URL.format(adcode=city_adcode)).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        f["properties"]["name"]: f["properties"]["center"]
        for f in d["features"]
        if f["properties"].get("level") == "district" and f["properties"].get("center")
    }


def build() -> Dict[str, Any]:
    rows = _load_level3()
    provs = [r for r in rows if r["deep"] == 0]
    prov_centers = _prov_centers()

    # 断点续传：已存在的「省代码 → {区县名: center}」与「省代码 → {市名: center}」恢复，
    # 避免重复请求 DataV（覆盖不足可反复重跑，逐次收敛）。
    prev_dist: Dict[str, Dict[str, List[float]]] = {}
    prev_city: Dict[str, Dict[str, List[float]]] = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
            for p in old.get("districts", []):
                key = p.get("_adcode6") or ""
                dm: Dict[str, List[float]] = {}
                cm: Dict[str, List[float]] = {}
                for c in p.get("cities", []):
                    if c.get("center"):
                        cm[c["name"]] = c["center"]
                    for d in c.get("districts", []):
                        if d.get("center"):
                            dm[d["name"]] = d["center"]
                if dm:
                    prev_dist[key] = dm
                if cm:
                    prev_city[key] = cm
        except Exception:  # noqa: BLE001
            prev_dist, prev_city = {}, {}

    tree: List[Dict[str, Any]] = []
    for p in provs:
        pcode = p["adcode6"]
        cities = [r for r in rows if r["deep"] == 1 and r["pid"] == p["id"]]
        dc = prev_dist.get(pcode)
        cmap = prev_city.get(pcode) or {}
        # 未恢复区县坐标 → 实时抓取（省→市→区县 两级）
        if dc is None:
            dc = {}
            if len(cities) == 0:
                dc = _direct_districts(pcode)  # 直辖市：子级即区县
            else:
                for c_adcode, c_name, c_center in _prov_cities(pcode):
                    cmap.setdefault(c_name, c_center)
                    dc.update(_district_centers(c_adcode))
                    time.sleep(0.25)  # 礼貌限速（实测 9 连发无拦截）
            time.sleep(1.0)
        city_nodes: List[Dict[str, Any]] = []
        for c in cities:
            dists = [r for r in rows if r["deep"] == 2 and r["pid"] == c["id"]]
            dist_nodes: List[Dict[str, Any]] = []
            centers: List[List[float]] = []
            for d in dists:
                # DataV 区县名 = 完整名（如「黄浦区」），须用 full_name 匹配（简称 name 会失配）
                center = dc.get(d["full_name"])
                if center:
                    centers.append(center)
                dist_nodes.append({"name": d["full_name"], "center": center})
            # 市中心：DataV 市 center 优先 → 区县中心均值近似 → 省中心
            ccenter = cmap.get(c["full_name"])
            if not ccenter and centers:
                ccenter = [round(sum(x[i] for x in centers) / len(centers), 6) for i in (0, 1)]
            if not ccenter:
                ccenter = prov_centers.get(pcode)
            city_nodes.append({"name": c["full_name"], "center": ccenter, "districts": dist_nodes})
        tree.append({
            "province": p["full_name"],
            "_adcode6": pcode,
            "center": prov_centers.get(pcode),
            "cities": city_nodes,
        })
    return {"source": [LEVEL3_CSV_URL, DATAV_FULL_URL], "districts": tree}


def main() -> None:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n_dist = sum(len(c["districts"]) for p in data["districts"] for c in p["cities"])
    n_center = sum(
        1 for p in data["districts"] for c in p["cities"] for d in c["districts"] if d.get("center")
    )
    n_city_center = sum(1 for p in data["districts"] for c in p["cities"] if c.get("center"))
    print(f"✅ {OUT} 写入完成：省 {len(data['districts'])} · 区县 {n_dist}（含中心坐标 {n_center}）· 市级含中心 {n_city_center}")


if __name__ == "__main__":
    main()
