"""离线地名定位（T1/A2）：内置全国省市区三级区划 + 区县中心坐标，无 AK 时把地名解析为坐标。

职责边界：
  - 只做「地名 → 坐标 / 坐标 → 区县」的离线解析，不参与等时圈/POI 计算；
  - 数据：`geo_index/china_regions.json`（随仓库提交，运行时零网络）；
  - 定位精度按「区县中心 → 市中心 → 省中心」兜底，报告侧标注近似口径。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_GEO_INDEX = Path(__file__).resolve().parent / "china_regions.json"

LngLat = Tuple[float, float]


class Location:
    """一条离线定位结果（行政区划路径 + 近似中心）。"""

    __slots__ = ("name", "path", "center", "approximate")

    def __init__(self, name: str, path: List[str], center: Optional[LngLat], approximate: str = ""):
        self.name = name
        self.path = path  # [省, 市, 区县]
        self.center = center
        self.approximate = approximate  # 如「区县中心」「市级近似」「省级近似」

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "center": list(self.center) if self.center else None,
            "approximate": self.approximate,
        }


class OfflineGeocoder:
    """基于内置区划数据的离线地理编码器。"""

    def __init__(self, data_path: Optional[Path] = None) -> None:
        path = data_path or _GEO_INDEX
        self._provinces: List[Dict[str, Any]] = []
        if path.exists():
            try:
                self._provinces = json.loads(path.read_text(encoding="utf-8")).get("districts", [])
            except (json.JSONDecodeError, OSError):
                self._provinces = []
        self._index: List[Dict[str, Any]] = []
        self._build_index()

    def _build_index(self) -> None:
        """扁平索引：每条 = {province, city, district, center, path}，供搜索/逆地理。"""
        for p in self._provinces:
            for c in p.get("cities", []):
                for d in c.get("districts", []):
                    self._index.append({
                        "province": p.get("province", ""),
                        "city": c.get("name", ""),
                        "district": d.get("name", ""),
                        "center": tuple(d["center"]) if d.get("center") else None,
                        "city_center": tuple(c["center"]) if c.get("center") else None,
                        "prov_center": tuple(p["center"]) if p.get("center") else None,
                    })

    # ── 地名 → 坐标 ────────────────────────────────────
    def search(self, query: str) -> List[Location]:
        """省/市/区县名或「省市区 详细地址」模糊匹配，返回按精度排序的候选。

        命中优先级：区县名(带 path 消歧) > 市名 > 省名；未命中返回空（调用方走兜底）。
        """
        if not query or not query.strip():
            return []
        q = query.strip()

        # 1) 区县级命中（优先精确、其次包含）
        district_hits: List[Location] = []
        for it in self._index:
            if not it["district"]:
                continue
            if q == it["district"] or (len(q) >= 2 and it["district"] in q):
                center = it["center"] or it["city_center"] or it["prov_center"]
                district_hits.append(Location(
                    name=it["district"],
                    path=[it["province"], it["city"], it["district"]],
                    center=center,
                    approximate="" if it["center"] else ("市级近似" if it["center"] is None and it["city_center"] else "省级近似"),
                ))
        if district_hits:
            # 同名词（北京朝阳 vs 长春朝阳）：优先区县 center 精确者；仍多则全返（调用方取首）
            return district_hits[:5]

        # 2) 市级命中
        city_hits: List[Location] = []
        for it in self._index:
            if it["city"] and (q == it["city"] or (len(q) >= 2 and it["city"] in q)):
                center = it["city_center"] or it["prov_center"]
                city_hits.append(Location(
                    name=it["city"],
                    path=[it["province"], it["city"], ""],
                    center=center,
                    approximate="市级近似" if not it["city_center"] else "市中心",
                ))
        if city_hits:
            return city_hits[:3]

        # 3) 省级命中
        for p in self._provinces:
            name = p.get("province", "")
            if name and (q == name or (len(q) >= 2 and name in q)):
                return [Location(name=name, path=[name, "", ""], center=tuple(p["center"]) if p.get("center") else None, approximate="省级近似")]

        return []

    # ── 坐标 → 区县（逆地理，离线近似）──────────────────
    def reverse(self, lng: float, lat: float) -> Optional[Location]:
        """坐标 → 最近区县中心（米制近似最近邻；无数据返回 None）。"""
        best: Optional[Location] = None
        best_d = float("inf")
        for it in self._index:
            c = it["center"] or it["city_center"] or it["prov_center"]
            if not c:
                continue
            d = (c[0] - lng) ** 2 + (c[1] - lat) ** 2
            if d < best_d:
                best_d = d
                best = Location(
                    name=it["district"],
                    path=[it["province"], it["city"], it["district"]],
                    center=c,
                    approximate="最近区县近似",
                )
        return best
