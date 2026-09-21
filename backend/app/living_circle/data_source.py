"""数据源接口与实现（A3 数据源与韧性分离 · v2 全国离线检索）。

- `DataSource`：`compute(CheckParams) -> LivingCircleReport(dict 契约)` 的抽象。
- `load_poi(client, center, radius_m)`：POI 采集（8 类 + 三要素）**全项目唯一实现**；
  采集半径必须由调用方从 `SpatialScope.collect_radius_m` 传入（本函数不带默认值）。
- `LiveDataSource`：真实百度 API 编排（等时圈 → POI → 盲区 → 评分）；韧性在 client/guard。
- `FixtureDataSource`：内置双样例（凯里/劲松），显式演示模式使用。
- `OfflineDataSource`：离线估算（无 AK 兜底任意地区）——内置区划定位 + 距离模型等时圈
  （复用 IsochroneEngine，注入「直线距离×绕行系数/步行速度」），POI 标注「需联网体检」，
  不产出可比评分/盲区（防污染对比口径）。
- `CachingDataSource`：横切缓存装饰器（v2 核心）——实时结果持久落盘（SqliteCache 30 天），
  无 AK 时先命中「历史实时结果」（served_from='cache'）再落离线估算。
- `get_data_source(mode, ...)`：二选一路由（有 AK → Caching(Live)；无 AK → Caching(Offline)）。
"""
from __future__ import annotations

import copy
import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.living_circle.assemble import assemble_living_circle
from app.living_circle.baidu_client import BaiduClient
from app.living_circle.geo_index.offline_geocoder import OfflineGeocoder
from app.living_circle.geo_utils import haversine_m
from app.living_circle.caliber import get_caliber, caliber_payload_key
from app.living_circle.isochrone import IsochroneEngine, hour_to_minutes
from app.living_circle.repository import Repository
from app.living_circle.scope import SpatialScope

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_DEFAULT_CENTER = (107.9758, 26.5734)  # 最终兜底：凯里老街（演示样区）


async def load_poi(
    client: BaiduClient,
    center: Tuple[float, float],
    radius_m: float,
    scope: Optional["SpatialScope"] = None,
) -> Tuple[Dict[str, list], Dict[str, list]]:
    """POI 采集（8 类 + 三要素）**全项目唯一实现** —— 门面，逻辑收敛到 `poi_collector.collect_poi`。

    ``radius_m`` 必须**由调用方从 :class:`SpatialScope` 取**（``scope.collect_radius_m``）：
    让「谁决定采集半径」保持编译期可见。预算由 `quota` 唯一来源导出；S8 扩词达标判定
    复用 ``scope`` 的圈内计数。未传 scope 时按离退出扩词（保留旧行为兼容）。
    """
    from app.living_circle.poi_collector import collect_poi

    return await collect_poi(client, center, radius_m, scope=scope)


@dataclass
class CheckParams:
    """一次体检的输入定格（对齐前端 LifeCircleScene + mode）。

    R5 命名治理：
    - mode → sample_profile（采样档位：quick/standard/precise）
    - travel_mode（出行方式：walking/riding/driving，默认 walking）
    """

    scene_name: str
    city: str = ""
    address: str = ""
    center: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))  # (lng, lat)
    study_radius_m: float = 2500.0
    sample_profile: str = "standard"  # quick / standard / precise（原 mode）
    travel_mode: str = "walking"  # walking / riding / driving


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
        from app.living_circle.assemble import annotate_blindspots
        from app.living_circle.geo_utils import haversine_m

        best = min(
            self._fixtures,
            key=lambda r: haversine_m(params.center, tuple(r["scene"]["center"])),
        )
        return annotate_blindspots(best)


class LiveDataSource(DataSource):
    """真实百度数据源：一次体检全链路（数据源只管编排，韧性在 client/guard）。"""

    def __init__(
        self,
        ak: str,
        client: Optional[BaiduClient] = None,
        engine: Optional[IsochroneEngine] = None,
        repo: Optional[Repository] = None,
    ) -> None:
        self.client = client or BaiduClient(ak=ak)
        self.engine = engine or IsochroneEngine()
        self.repo = repo or Repository()

    async def aclose(self) -> None:
        await self.client.aclose()

    def _scene_payload(self, p: CheckParams) -> str:
        return caliber_payload_key(p.scene_name, p.center, p.study_radius_m, p.sample_profile)

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        payload_key = self._scene_payload(params)
        cached = self.repo.get_report("live", payload_key)
        if cached is not None:
            return cached

        center = params.center
        caliber = get_caliber(params.travel_mode)

        # 1) 等时圈（批量矩阵测时 → IDW → 等值线族）
        async def meter_fn(pts: List[Tuple[float, float]]) -> List[Optional[float]]:
            return await self.client._measure_matrix(params.travel_mode, pts, center)

        iso = await self.engine.compute(
            center,
            meter_fn,
            study_radius_m=params.study_radius_m,
            mode=params.sample_profile,
        )

        # 2) 空间口径绑定：按 minutes 选可达区环（禁止 iso["isochrones"][-1] 按位置取环）
        scope = SpatialScope.from_iso(caliber, center, params.study_radius_m, iso)
        scope.invariant()

        # 3) POI 采集（半径唯一来自 scope.collect_radius_m）
        per_category, triads = await load_poi(self.client, center, scope.collect_radius_m, scope=scope)

        # 4) 组装（唯一实现，与 pipeline 共用）
        report = assemble_living_circle(params, iso, per_category, triads, scope)
        self.repo.cache_report("live", payload_key, report)
        return report


class OfflineDataSource(DataSource):
    """离线估算数据源（L3，v2）：任意地区兜底——区划定位 + 距离模型等时圈。

    原则（评审诚实性）：`data_origin='offline'`、`interpolation='circular_approx'`，
    POI 标注「需联网体检」，**不产出可比评分/盲区**（scores.note 说明，前端不渲染数字）。
    复用 IsochroneEngine（与 live 同构契约），仅测时函数替换为「直线距离×绕行/速度」。
    """

    def __init__(self, geocoder: Optional[OfflineGeocoder] = None, engine: Optional[IsochroneEngine] = None) -> None:
        self.geocoder = geocoder or OfflineGeocoder()
        self.engine = engine or IsochroneEngine()

    def resolve_center(self, params: CheckParams) -> Optional[Tuple[float, float]]:
        """中心解析：显式坐标 > 区划定位 > 凯里兜底。"""
        c = params.center
        if c and c != (0.0, 0.0):
            return tuple(c)
        hits = self.geocoder.search(params.scene_name)
        if hits and hits[0].center:
            return tuple(hits[0].center)
        return _DEFAULT_CENTER

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        center = self.resolve_center(params)
        # 步骤 5：离线估算 detour_k / speed 按 travel_mode 分档
        caliber = get_caliber(params.travel_mode)

        async def meter_fn(pts: List[Tuple[float, float]]) -> List[Optional[float]]:
            # 距离模型：直线距离 × 绕行系数 → 分钟（与 live 同源速度基准）
            return [hour_to_minutes(haversine_m(center, p) * caliber.detour_k, caliber.speed_m_per_min) for p in pts]

        iso = await self.engine.compute(center, meter_fn, study_radius_m=params.study_radius_m, mode=params.sample_profile)

        # R2/R6：离线报告也增 caliber 举证对象
        caliber_report = {
            "travel_mode": params.travel_mode,
            "speed_m_per_min": caliber.speed_m_per_min,
            "detour_k": caliber.detour_k,
            "study_radius_m": caliber.study_radius_m,
            "iso_minutes": list(caliber.iso_minutes),
            "basis": caliber.basis,
            "measured": caliber.measured,
            "sample_profile": params.sample_profile,
            "note": "离线估算（未实测，按距离模型粗估）",
        }

        return {
            "scene": {
                "name": params.scene_name,
                "city": params.city,
                "address": params.address or "离线估算（区县中心近似）",
                "center": [round(center[0], 6), round(center[1], 6)],
                "study_radius_m": int(params.study_radius_m),
            },
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "data_origin": "offline",
            "caliber": caliber_report,
            "isochrones": iso["isochrones"],
            "sampling": {**iso["sampling"], "interpolation": "circular_approx", "is_scattered": False},
            "poi": {"categories": [], "total": 0, "in_circle": 0, "points": []},
            "blindspots": [],
            "scores": {
                "total": 0,
                "radar": [],
                "bars": [],
                "triads": [],
                "note": (
                    f"离线估算：步行速度 {caliber.speed_m_per_min} m/min × 绕行系数 {caliber.detour_k} 的距离模型，"
                    "未联网采集 POI——综合评分与服务盲区需实时体检后给出，且离线分不可与实时分比较"
                ),
            },
        }


class CachingDataSource(DataSource):
    """横切缓存装饰器（v2 核心）：先查持久缓存，命中返回（served_from='cache'）；未命中委托并回填。

    - 有 AK：包装 Live —— 同中心 30 天秒开 + 实时结果落盘；
    - 无 AK：包装 Offline（read_only）——命中「历史实时结果」离线可查，未命中才走离线估算。
    - 透传内层 `client`（pipeline 用 hasattr 判断是否走 live geocoding / 测时）。
    """

    def __init__(self, source: DataSource, repo: Optional[Repository] = None, data_mode: str = "live", read_only: bool = False) -> None:
        self.source = source
        self.repo = repo or Repository()
        self.data_mode = data_mode
        self.read_only = read_only

    @property
    def client(self) -> Optional[BaiduClient]:
        return getattr(self.source, "client", None)

    @staticmethod
    def _payload(params: CheckParams) -> str:
        c = params.center or (0.0, 0.0)
        return caliber_payload_key(params.scene_name, c, params.study_radius_m, params.sample_profile)

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        payload = self._payload(params)
        hit = self.repo.get_report(self.data_mode, payload)
        if hit is not None:
            hit = copy.deepcopy(hit)
            hit["served_from"] = "cache"
            hit["cached_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            return hit
        report = await self.source.compute(params)
        if not self.read_only:
            self.repo.cache_report(self.data_mode, payload, report)
        return report


def get_data_source(
    mode: str,
    ak: str = "",
    client: Optional[BaiduClient] = None,
    repo: Optional[Repository] = None,
    geocoder: Optional[OfflineGeocoder] = None,
) -> DataSource:
    """工厂（v2 二选一路由 + 横切缓存）：

    - `mode=fixture`（显式演示）→ FixtureDataSource（两样例，零回归）；
    - 有 AK → CachingDataSource(LiveDataSource)（实时全链路 + 落盘缓存）；
    - 无 AK → CachingDataSource(OfflineDataSource, read_only)（先命中历史实时，再离线估算）。

    韧性降级在数据源选择层（不污染 baidu_client）；前端按 data_origin/served_from 标注。
    """
    if mode == "fixture":
        return FixtureDataSource()
    repo = repo or Repository()
    if ak:
        live = LiveDataSource(ak=ak, client=client, repo=repo)
        return CachingDataSource(live, repo=repo, data_mode="live")
    import logging

    logging.getLogger(__name__).warning("baidu AK 缺失：先查历史实时缓存，未命中走离线估算（data_origin=offline）")
    return CachingDataSource(OfflineDataSource(geocoder=geocoder), repo=repo, data_mode="live", read_only=True)


async def degrade_to_offline(params: CheckParams) -> Dict[str, Any]:
    """配额/网络耗尽时的**诚实降级**：产出一份离线估算报告（data_origin='offline'）。

    复用 `OfflineDataSource.compute`：无可比评分/盲区（P0-2 语义），几何契约豁免，
    前端已有「离线估算 · 未联网采集 POI」渲染 —— 让实时体检**永远以任务成功收尾，
    绝不因百度配额演变成「调研失败」**。调用方再叠加 degraded/quota 标记上报。
    """
    source = OfflineDataSource()
    return await source.compute(params)


async def refine_live_with_profile(
    check: CheckParams,
    client: BaiduClient,
    repo: Repository,
    sample_profile: str = "standard",
    engine: Optional[IsochroneEngine] = None,
) -> Dict[str, Any]:
    """后台**精报**（粗报即时之后的升级）：按给定采样档位 + 全量 POI 重算并回填缓存。

    - 用 `sample_profile`（standard/precise）精采样等时圈 + `load_poi` 全量采集；
    - 结果写 `repo.cache_report('live', …)`，供之后 LiveDataSource / 读路径取精报；
    - 返回 `living_circle` 节点 dict（与 pipeline 用的 `assemble_living_circle` 同构），
      由调用方再 `assemble_report` + `db.save_living_circle_report`。
    独立函数（不并入 `LiveDataSource.compute`）：流水线实时分支保持 O(1) 入口，精报可被
    asyncio 后台任务以最低耦合调用，且调用方掌握 scene_key / quota 判定。
    """
    engine = engine or IsochroneEngine()
    center = check.center

    async def meter_fn(pts: List[Tuple[float, float]]) -> List[Optional[float]]:
        return await client.measure_matrix(check.travel_mode, pts, center)

    iso = await engine.compute(center, meter_fn, study_radius_m=check.study_radius_m, mode=sample_profile)
    caliber = get_caliber(check.travel_mode)
    scope = SpatialScope.from_iso(caliber, center, check.study_radius_m, iso)
    scope.invariant()
    per_category, triads = await load_poi(client, center, scope.collect_radius_m, scope=scope)

    report_data = assemble_living_circle(check, iso, per_category, triads, scope)
    payload_key = caliber_payload_key(
        check.scene_name, center, check.study_radius_m, sample_profile, check.travel_mode
    )
    repo.cache_report("live", payload_key, report_data)
    return report_data