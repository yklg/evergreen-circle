"""数据源接口与实现（A3 数据源与韧性分离）。

- `DataSource`：`compute(CheckParams) -> LivingCircleReport(dict 契约)` 的抽象。
- `LiveDataSource`：真实百度 API 编排（等时圈 → POI → 盲区 → 评分）；
  韧性（限流/退避）在 baidu_client/request_guard，业务快照回退不在这里。
- `FixtureDataSource`：内置双样例（凯里/劲松），按中心点就近匹配——评审无 Key 演示与降级兜底。
- `get_data_source(mode, ...)`：按任务 `data_mode: 'live'|'fixture'` 选择实现。
缓存键经 Repository 注入，并带 data_mode 前缀（防串）。
"""
from __future__ import annotations

import copy
import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.living_circle.baidu_client import BaiduClient
from app.living_circle.blindspot import find_blindspots
from app.living_circle.geo_utils import to_local_xy
from app.living_circle.isochrone import IsochroneEngine, idw_for_points
from app.living_circle.poi import CATEGORY_DEFS, TRIAD_KEYWORDS, clean, to_stats
from app.living_circle.repository import Repository
from app.living_circle.scoring import compute_scores, triad_from_points

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@dataclass
class CheckParams:
    """一次体检的输入定格（对齐前端 LifeCircleScene + mode）。"""

    scene_name: str
    city: str = ""
    address: str = ""
    center: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))  # (lng, lat)
    study_radius_m: float = 2500.0
    mode: str = "standard"  # quick / standard / precise


class DataSource:
    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        raise NotImplementedError


class FixtureDataSource(DataSource):
    """内置样例数据源：读 fixtures/*.json（与前端 mock 同构），按中心点就近返回。"""

    def __init__(self, fixtures_dir: Optional[Path] = None) -> None:
        self._fixtures: List[Dict[str, Any]] = []
        for f in (fixtures_dir or _FIXTURES_DIR).glob("*.json"):
            import json

            with open(f, encoding="utf-8") as fh:
                self._fixtures.append(json.load(fh))

    def sample_names(self) -> List[str]:
        return [r.get("scene", {}).get("name", "") for r in self._fixtures]

    def sample_scenes(self) -> List[Dict[str, Any]]:
        """样例场景快照（名称→中心），供无坐标输入的兜底匹配。"""
        return [
            {"name": r.get("scene", {}).get("name", ""), "center": r.get("scene", {}).get("center", [0, 0])}
            for r in self._fixtures
        ]

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        if not self._fixtures:
            raise ValueError("无内置样例数据（fixtures 目录为空）")
        from app.living_circle.geo_utils import haversine_m

        best = min(
            self._fixtures,
            key=lambda r: haversine_m(params.center, tuple(r["scene"]["center"])),
        )
        return copy.deepcopy(best)


class LiveDataSource(DataSource):
    """真实百度数据源：一次体检全链路（数据源只管编排，韧性在 client/guard）。"""

    def __init__(
        self,
        ak: str,
        client: Optional[BaiduClient] = None,
        engine: Optional[IsochroneEngine] = None,
        repo: Optional[Repository] = None,
        poi_radius_m: int = 2000,
    ) -> None:
        self.client = client or BaiduClient(ak=ak)
        self.engine = engine or IsochroneEngine()
        self.repo = repo or Repository()
        self.poi_radius = poi_radius_m

    async def aclose(self) -> None:
        await self.client.aclose()

    def _scene_payload(self, p: CheckParams) -> str:
        return (
            f"{p.scene_name}|{p.center[0]:.6f},{p.center[1]:.6f}|"
            f"{int(p.study_radius_m)}|{p.mode}"
        )

    async def _load_poi(self, center: Tuple[float, float]) -> Tuple[Dict[str, list], Dict[str, list]]:
        """采集 8 类民生 POI + 三要素 POI（多关键词查全 + 清洗）。"""
        per_category: Dict[str, list] = {}
        for cat, defn in CATEGORY_DEFS.items():
            items: list = []
            for kw in defn["keywords"]:
                items += await self.client.place_search(kw, center, radius_m=self.poi_radius)
            per_category[cat] = clean(items)
        triads: Dict[str, list] = {}
        for key, kw in TRIAD_KEYWORDS.items():
            triads[key] = clean(await self.client.place_search(kw, center, radius_m=self.poi_radius))
        return per_category, triads

    @staticmethod
    def _minutes_by_point(
        points: List[Dict[str, Any]],
        sample_xy: np.ndarray,
        minutes: List[Optional[float]],
        center: Tuple[float, float],
    ) -> List[float | None]:
        """对 POI 点集按 IDW 场插值耗时（一次向量化）。"""
        if not points:
            return []
        query_xy = np.array([to_local_xy(center, p["lng"], p["lat"]) for p in points])
        return idw_for_points(sample_xy, minutes, query_xy)

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        payload_key = self._scene_payload(params)
        cached = self.repo.get_report("live", payload_key)
        if cached is not None:
            return cached

        center = params.center

        # 1) 等时圈（批量步行矩阵测时 → IDW → 等值线族）
        iso = await self.engine.compute(
            center,
            lambda pts: self.client.route_matrix_walking(pts, center),
            study_radius_m=params.study_radius_m,
            mode=params.mode,
        )
        iso15 = next((z for z in iso["isochrones"] if z["minutes"] == 15), None)
        iso15_ring = iso15["geojson"]["coordinates"][0] if iso15 else []
        sample_pts = iso["sampling"]["points"]
        sample_minutes = [sp["minutes"] for sp in sample_pts]
        # 采样点局部坐标（与插值场同原点 → POI 耗时回填复用同一批 IDW）
        sample_xy = np.array([to_local_xy(center, sp["lng"], sp["lat"]) for sp in sample_pts])

        # 2) POI 采集与清洗
        per_category, triads = await self._load_poi(center)

        # 3) 类别统计 + 耗时回填（对全部 POI 一次插值，再按类别取最近）
        stats = to_stats(per_category, triads, iso15_ring, center)
        for s in stats:
            cat = s["category"]
            items = per_category.get(cat, [])
            times = self._minutes_by_point(items, sample_xy, sample_minutes, center)
            paired = [(t, it) for t, it in zip(times, items) if t is not None]
            if paired:
                best_t, best_it = min(paired, key=lambda x: x[0])
                s["min_minutes"] = best_t
                s["nearest_name"] = best_it.get("name") or s.get("nearest_name")
            else:
                s["min_minutes"] = None

        # 4) 三要素覆盖结论 + 盲区
        def field_fn(pt: Tuple[float, float]) -> Optional[float]:
            xy = np.array([to_local_xy(center, pt[0], pt[1])])  # (1,2)
            vals = idw_for_points(sample_xy, sample_minutes, xy)
            v = vals[0]
            return None if v is None or v > 20 else v

        def as_full(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [{"lng": it["lng"], "lat": it["lat"], "name": it.get("name", "")} for it in items]

        triads_conclusion = triad_from_points(
            as_full(triads.get("market", [])),
            as_full(triads.get("pharmacy", [])),
            as_full(triads.get("primary", [])),
            field_fn,
        )
        blindspots = find_blindspots(center, params.study_radius_m, triads, prefix=params.scene_name)

        # 5) 评分
        scores = compute_scores(stats, triads_conclusion, len(blindspots))

        report = {
            "scene": {
                "name": params.scene_name,
                "city": params.city,
                "address": params.address,
                "center": [round(center[0], 6), round(center[1], 6)],
                "study_radius_m": int(params.study_radius_m),
            },
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "data_origin": "live",
            "isochrones": iso["isochrones"],
            "sampling": iso["sampling"],
            "poi": {
                "categories": stats,
                "total": sum(s["total"] for s in stats),
                "in_circle": sum(s["in_circle"] for s in stats),
            },
            "blindspots": blindspots,
            "scores": scores,
        }
        self.repo.cache_report("live", payload_key, report)
        return report


def get_data_source(
    mode: str,
    ak: str = "",
    client: Optional[BaiduClient] = None,
    repo: Optional[Repository] = None,
) -> DataSource:
    """工厂：按 data_mode 选择实现；显式 live 但无 AK → 降级 fixture（A3 韧性，不抛错）。

    水平降级在此（数据源选择层），不污染 baidu_client；前端横幅标注 data_origin。
    """
    if mode == "fixture" or (mode == "live" and not ak):
        if mode == "live" and not ak:
            # 显式告警让可观测性可查；返回 fixture 保证演示不中断
            import logging

            logging.getLogger(__name__).warning("baidu AK 缺失，生活圈体检降级为 fixture 演示数据")
        return FixtureDataSource()
    return LiveDataSource(ak=ak, client=client, repo=repo)