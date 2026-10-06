"""数据源接口与实现（A3 数据源与韧性分离 · v2 全国离线检索）。

- `DataSource`：`compute(CheckParams) -> LivingCircleReport(dict 契约)` 的抽象。
- `load_poi(client, center, radius_m, scope, *, sample_profile, travel_mode)`：
  POI 采集（8 类 + 三要素）**全项目唯一实现**；采集半径必须由调用方从
  `SpatialScope.collect_radius_m` 传入（本函数不带默认值），取证预算同样由调用方手里的
  采样规格向 `quota` 换取（本函数不猜规格）。
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
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import (TYPE_CHECKING, Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from app.living_circle.anchors import LatticeAnchors, PLAN_EXPAND, hub_attempted
from app.living_circle.assemble import assemble_living_circle
from app.living_circle.baidu_client import BaiduClient
from app.living_circle.blindspot import judge_once
from app.living_circle.geo_index.offline_geocoder import OfflineGeocoder
from app.living_circle.geo_utils import LngLat, haversine_m
from app.living_circle.caliber import get_caliber, caliber_payload_key
from app.living_circle.isochrone import IsochroneEngine, hour_to_minutes
from app.living_circle.degrade_policy import degrade_reason, degraded_block, partial_for
from app.living_circle.judgement import STAT_KEYS
from app.living_circle.poi_collector import (
    POIBudget,
    collect_poi,
    collect_triad_evidence,
    triad_keywords,
)
from app.living_circle.report_contract import reuse_policy
from app.living_circle.repository import Repository
from app.living_circle.scope import EvidenceRegion, SpatialScope, TRIAD_KEYS

if TYPE_CHECKING:                    # 只喂注解，不给依赖图添新边（运行期边已由 `blindspot` 建好）
    from app.living_circle.anchors import AnchorsPlan
    from app.living_circle.judgement import Judgement

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_DEFAULT_CENTER = (107.9758, 26.5734)  # 最终兜底：凯里老街（演示样区）

_logger = logging.getLogger(__name__)

# 邻近缓存半径（O1/D9）：距既有实时中心 ≤500m 的新体检直接复用，零额度消耗。
# 500m ≈ 一个街区尺度，覆盖「定位到我」的 GPS 抖动与同社区内微调中心。
NEARBY_CACHE_M = 500.0


def wanted_caliber(params: CheckParams) -> Dict[str, Any]:
    """本次请求的口径三元组 —— 复用门 `reuse_policy` 的比较对象（批 A③）。

    只在这一个地方组装：`compute` 的精确命中与 `peek` 的邻近命中吃同一份形状，
    两份各拼一次就会长成「同一道门比较三样、另一道门比较两样」。
    """
    return {
        "travel_mode": params.travel_mode,
        "sample_profile": params.sample_profile,
        # 请求侧那次体检的半径（**不是**档位半径）：`reuse_policy` 拿它比 `scene.study_radius_m`。
        "study_radius_m": params.study_radius_m,
        # ⚠️ 这里**不放**第二把版本键（评分口径 `cov-*`）。10-01 曾经放过，代价是全量 9 红：
        # 它不是"本次请求"的参数（用户没有"要哪一档分子"这个选项），塞进三元组就等于伪造一个
        # 用户从没做过的请求，还让所有自带三元组调 `reuse_policy` 的调用方 KeyError。
        # 门那一边直接比模块常量（`report_contract.reuse_policy` 的「评分口径」那一行）。
    }


async def load_poi(
    client: BaiduClient,
    center: Tuple[float, float],
    radius_m: float,
    scope: Optional["SpatialScope"] = None,
    *,
    sample_profile: str,
    travel_mode: str,
) -> "PoiCollection":
    """POI 采集（8 类 + 三要素）**全项目唯一实现** —— 门面，逻辑收敛到 `poi_collector.collect_poi`。

    ``radius_m`` 必须**由调用方从 :class:`SpatialScope` 取**（``scope.collect_radius_m``）：
    让「谁决定采集半径」保持编译期可见。S8 扩词达标判定复用 ``scope`` 的圈内计数。
    未传 scope 时按离退出扩词（保留旧行为兼容）。

    ``sample_profile`` / ``travel_mode`` **不留默认值**（D5 分区翻转后的新承重参数）：
    取证额度现在是「全局预算 − 矩阵按规格算出的需求调用」，规格漏传就等于拿步行的
    chunk 去算驾车的矩阵，两端相加会越过 42 的精度预算 ⇒ 撞在 45 的熔断闸上，
    把「我们分区算错」演成「接口出问题」。要漏就漏在签名上（同 `quota.poi_page_depth` 的教训）。

    返回 :class:`PoiCollection`（点位 + 三要素 + **证据账目**）—— 第三个字段用 NamedTuple
    承载而非塞进 dict，理由与 ``poi.PoiPointsOut`` 同构：举证无法被顺手丢掉。
    """
    from app.living_circle.quota import quota_budget

    _mat, poi = quota_budget(sample_profile, travel_mode)
    return await collect_poi(
        client, center, radius_m, scope=scope, budget_snapshot=POIBudget(total=poi)
    )


def bind_evidence(scope: "SpatialScope", collected: "PoiCollection") -> "SpatialScope":
    """把采集侧的**实测证据账目**绑进口径定格（「事后举证」相的唯一绑定点）。

    唯一实现：live 分支与后台精报分支都走这里。两处各写一份换算，就会有一处漏绑 ——
    而漏绑的形态是 ``evidence_radius_m is None`` ⇒ 判定退回「拿请求半径当证据半径」，
    正是本轮要消灭的东西。故此处不留第二份。
    """
    from app.living_circle.poi_collector import PoiCollection  # noqa: F401  (类型提示用)
    from app.living_circle.scope import TRIAD_KEYS

    ev = collected.evidence
    detail = ev.as_detail()
    detail["truncated_terms"] = list(ev.truncated_terms)
    return scope.with_evidence(
        ev.triad_frontier_m(TRIAD_KEYS),
        complete=ev.complete,
        detail=detail,
        capped=ev.capped_categories,
        # T-P0-4：边界与「为什么停」**同源绑定**（都由决定边界的那一行给）。缺这一格，
        # 盘上的完整性就只能由表示层凭空声明（合成盘因此一律不自称查全，见 EvidenceDisc）。
        stop_reasons=ev.stop_reason_by_category(),
    )


@dataclass
class CheckParams:
    """一次体检的输入定格（对齐前端 LifeCircleScene + mode）。

    R5 命名治理：
    - mode → sample_profile（采样档位：quick/standard/precise）
    - travel_mode（出行方式：walking/riding/driving，默认 walking）

    `force`（4b）：用户**点名要重测**时为真 —— 只让 `peek` 早退，不改任何键、不改任何门。
    ⚠️ 它**绝不进缓存键**（`_payload` 不读它）也不进 `wanted_caliber`：进了就等于把
    "我这次是强制重算的"写进身份 —— 同一地点会裂成两条历史，而重算后覆盖再也对不上原行
    （口径版本号为什么走载荷不走键，理由在 `scope.SCOPE_POLICY_VERSION` 那段，同一条）。
    """

    scene_name: str
    city: str = ""
    address: str = ""
    center: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))  # (lng, lat)
    study_radius_m: float = 2500.0
    sample_profile: str = "standard"  # quick / standard / precise（原 mode）
    travel_mode: str = "walking"  # walking / riding / driving
    force: bool = False  # 4b：用户点名重测 ⇒ `peek` 早退（见类 docstring，绝不进缓存键）


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
        return caliber_payload_key(
            p.scene_name, p.center, p.study_radius_m, p.sample_profile, p.travel_mode
        )

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        payload_key = self._scene_payload(params)
        cached = self.repo.get_report("live", payload_key)
        if cached is not None:
            reusable, why = reuse_policy(cached, wanted_caliber(params))
            if reusable:
                return cached
            # 旧口径缓存不得冒充本次体检的答案 ⇒ 落到下面的实时重算。
            # 重算结果按**同一 payload 键**写回（`scene_key` 不变）⇒ 不产生第二条历史。
            _logger.info("实时缓存命中但不可复用（%s）：%s", payload_key, why)

        # 编排本身不在此重写一份 —— 走 `live_forensic_steps`（全项目唯一实现）。
        # 本函数只多两件事：查自己的 payload 缓存、把实时产物写回缓存。
        report: Dict[str, Any] = {}
        produced = False   # 只有实时产物才写缓存；降级产物不冒充「一次跑完的 live 结果」
        async for step in live_forensic_steps(self.client, self.engine, params):
            if step.report is None:
                continue
            report = step.report
            produced = step.kind == STEP_REPORT
        if produced:
            # 写缓存（「live 命名空间不装 offline 报告」由 `Repository.cache_report` 唯一拦截）
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

        iso = await self.engine.compute(
            center, meter_fn, study_radius_m=params.study_radius_m,
            mode=params.sample_profile, travel_mode=params.travel_mode,
        )
        # ⚠️ 引擎顺手算出的那份**常态绕行标定 / 残差耗时**（`sampling.detour`）在这里必须摘掉。
        # 离线链的 `meter_fn` 是距离模型的恒等式（`直线 × detour_k ÷ 速度`），拿它去标定会得到
        # `detour_factor_measured ≡ caliber.detour_k`、残差处处 0 —— 那是**代数量自己和自己相等**，
        # 不是一次测量。留着它，屏幕上就会出现「按本次实测标定的常态绕行 1.3×…最堵的一档 0min」
        # 这种替一次没发生的测量举证的话（`interpolation` 改成 `circular_approx` 是同一条纪律）。
        # 下面那份 caliber 也不声明 `reach_caliber_version`：没有键集就不发版本号，
        # 读侧契约 B14 才不会把离线件判成"声明了却缺键"。
        sampling = {
            k: v for k, v in iso["sampling"].items() if k != "detour"
        }
        sampling.update({"interpolation": "circular_approx", "is_scattered": False})

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
            # 摘掉 `detour`（理由见上面剥离它那段）：离线没有实测标定可声明，键与键集必须同批缺席。
            "sampling": sampling,
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
        return caliber_payload_key(
            params.scene_name, c, params.study_radius_m, params.sample_profile, params.travel_mode
        )

    @staticmethod
    def _reusable(hit: Optional[Dict[str, Any]],
                  wanted: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """缓存命中过**复用门**；不可复用则视为未命中。

        邻近分支同样必须过门：`find_recent_report_near` 走的是**整个 live 命名空间扫描 +
        从值里读 `scene.center`**（`repository.py:267`），所以「把版本加进缓存键」拦不住它，
        而它连出行方式/半径/采样档都不比较 ⇒ 只有读侧谓词拦得住（批 A③ 补的后两半）。
        """
        if hit is None:
            return None
        reusable, why = reuse_policy(hit, wanted)
        if not reusable:
            _logger.info("缓存命中但不可复用：%s", why)
            return None
        return hit

    def peek(self, params: CheckParams) -> Optional[Dict[str, Any]]:
        """**单一缓存入口**（v5 E0/I1）：精确命中 → 邻近 500m 命中 → None。

        - 键构建与 `compute` 共用 `_payload`（D24：同参同键，唯一实现）；
        - 两支命中都要过 :func:`reuse_policy`（口径版本门 + 本次请求的口径三元组，批 A③），
          不可复用视为未命中；
        - 命中时深度拷贝 + 标注 `served_from`（'cache' | 'nearby_cache'）+ `cached_at`，
          **不污染缓存原值**（调用方注入 team 等元数据不影响下次命中）；
        - 精确未命中才查邻近（`repo.find_recent_report_near`，SQL 预过滤 D25）；
          中心未解析（(0,0)）时跳过邻近（无意义且易误命中原点附近缓存）。
        - ``params.force`` ⇒ **整道门跳过、直接判未命中**（4b 的重算入口）。放在这里而不是
          各调用点各自判断：`compute` 与管线 live 分支共用本函数（E0 的"单一入口"），
          只要还有第二条读缓存的路，force 就得在两处各记一遍 —— 漏一处就是"点了没重测"。
          跳过之后 `compute` 照常委托内层源重算并 `backfill` 覆盖同一把键 ⇒ 重算的结果
          成为下一次的缓存，不需要额外状态。
        """
        if params.force:
            _logger.info("显式要求重测（force）：跳过精确与邻近两级复用，走完整实跑")
            return None
        payload = self._payload(params)
        wanted = wanted_caliber(params)
        hit = self._reusable(self.repo.get_report(self.data_mode, payload), wanted)
        served_from = "cache"
        if hit is None:
            c = params.center or (0.0, 0.0)
            if c != (0.0, 0.0):
                hit = self._reusable(
                    self.repo.find_recent_report_near(self.data_mode, c, NEARBY_CACHE_M), wanted
                )
                served_from = "nearby_cache"
        if hit is None:
            return None
        hit = copy.deepcopy(hit)
        hit["served_from"] = served_from
        hit["cached_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        return hit

    def backfill(self, params: CheckParams, report: Dict[str, Any]) -> None:
        """实时重算结果回填缓存（E0：回填逻辑唯一实现，编排器不摸 repo/键细节）。

        ``read_only``（无 AK 离线包装）时不写 live 缓存。
        """
        if self.read_only:
            return
        self.repo.cache_report(self.data_mode, self._payload(params), report)

    async def compute(self, params: CheckParams) -> Dict[str, Any]:
        """命中短路 / 未命中委托内层数据源并回填（E0：compute 与管线 live 分支共用 peek）。"""
        hit = self.peek(params)
        if hit is not None:
            return hit
        report = await self.source.compute(params)
        self.backfill(params, report)
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


async def scope_or_degrade(
    *,
    caliber: Any,
    center: Any,
    radius_m: float,
    iso: Dict[str, Any],
    params: "CheckParams",
    guard: Any = None,
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """`SpatialScope.from_iso` 的**唯一调用封装**（γ 守卫 G-4：`app/**` 内只允许本函数调用它）。

    先把「可降级」的情况分流走，再让 `from_iso` 对真正的口径错误照旧 `raise`
    —— **不许弱化、不许删**（`scope.py:111` 拦的是「静默空壳报告」，本身是对的）。

    返回 `(scope, degraded_report)`，二者**恰一**为 None。
    """
    has_iso = bool(iso.get("isochrones") or [])
    reason = degrade_reason(guard, has_isochrones=has_iso)
    if reason is not None:
        report = await degrade_to_offline(params)
        report["degraded"] = degraded_block(guard, isochrone_empty=not has_iso)
        return None, report
    scope = SpatialScope.from_iso(caliber, center, radius_m, iso)
    scope.invariant()
    return scope, None


async def degrade_if_incomplete(
    *,
    per_category: Dict[str, Any],
    params: "CheckParams",
    guard: Any = None,
) -> Optional[Dict[str, Any]]:
    """采集后校验：**POI 一个点都没拿到** ⇒ 产出降级报告，否则 None。

    D1① 之后这里不再管「闸中止」：采集阶段能走到这儿说明等时圈已经真测过，
    闸再落也只说明**后面的类别没查到** —— 那是 `partial_for(guard)` 的事（残缺声明），
    不是把整份报告打回离线正圆（那会连已测到的几何与已判出的盲区一起丢掉）。

    ⚠️ 「POI 非空」**不等于**「数据完整」：完整性由 `partial` 与 `evidence_starved_terms`
    共同披露，不由本函数代劳。
    """
    has_poi = bool(per_category) and any(bool(v) for v in per_category.values())
    if degrade_reason(guard, has_isochrones=True, has_poi=has_poi) is None:
        return None
    report = await degrade_to_offline(params)
    report["degraded"] = degraded_block(guard, poi_empty=not has_poi)
    return report


async def degrade_to_offline(params: CheckParams) -> Dict[str, Any]:
    """配额/网络耗尽时的**诚实降级**：产出一份离线估算报告（data_origin='offline'）。

    复用 `OfflineDataSource.compute`：无可比评分/盲区（P0-2 语义），几何契约豁免，
    前端已有「离线估算 · 未联网采集 POI」渲染 —— 让实时体检**永远以任务成功收尾，
    绝不因百度配额演变成「调研失败」**。调用方再叠加 degraded/quota 标记上报。
    """
    source = OfflineDataSource()
    return await source.compute(params)


# ── 取证编排的唯一实现（计划 v6.1 片 0）─────────────────────────
STEP_MEASURE = "measure"
STEP_COLLECT = "collect"
STEP_JUDGE = "judge"
STEP_DEGRADED = "degraded"
STEP_REPORT = "report"
STEP_ROUND = "round"

#: 一次体检最多打几个**扩容**回合（v6.1③ 拍板「1 轮封顶」）。
#: ⚠️ 调大它的前置条件不是"再多给点额度"，而是先落 v6.1④ 的 **stride 首轮冻结**：
#: `plan_expansion` 每一趟都从 `region.min_exhausted_m(cat)` 重导间距，而 min 对并集
#: **单调不增** ⇒ 回合抓回来的页截断浅盘会把该类永久推进 `below_stride_floor`（第六轮复审
#: P0-2a 复验为真）。今天 `plan_expansion` 没有承载"冻结"的入参 ⇒ 那条记在批次二。
#: 在这个常量上改数字 = 把一条已知会空转的循环放大。
MAX_FORENSIC_ROUNDS = 1

# 收手的原因必须**分名**：这四条是四种不同的事实，合成一个"回合结束"就把它们抹平了 ——
# `undecided_zero` 判全了（好消息）；`nothing_to_ask` 没有排得出、又没打过的锚点（我们的
# 格阵到头了，不是钱花完）；`forensic_pool_short` 额度不够（钱的事，是**唯一**该落 `partial`
# 的一条 —— 把另两条也接进触发条件，就是让一份「按计划收手」的报告长得像「被配额打断」）；
# `rounds_exhausted` 自己设的轮次上限（policy，既不该报成"查全了"也不该报成"配额耗尽"）。
# ⚠️ 归因**优先级**（闸真中止时不吃这条）不住在这里，住 `degrade_policy.partial_block`。
STOP_UNDECIDED_ZERO = "undecided_zero"
STOP_NOTHING_TO_ASK = "nothing_to_ask"
STOP_POOL_SHORT = "forensic_pool_short"
STOP_ROUNDS_EXHAUSTED = "rounds_exhausted"

FORENSIC_POINTS_POLICY = (
    "盲区按「首轮 + 各取证回合」并集的点位判；8 类计数与评分仍按首轮点位"
)


@dataclass(frozen=True)
class ForensicRoundRecord:
    """一次「判定 → 是否再打」的账目：`caliber.forensic` 与 `round` 事件的**共同原料**。

    为什么一份记录、两个出口：逐回合事件与落库披露若各拼一份 dict，"上屏说打了 17 个锚点、
    报告里写 20 个"就无人能拦 —— 而这类分家正是本链一路在灭的形状。
    计数一律是**派生量**（`@property`），不是可填字段：`planned == sent + dropped` 与
    `sent == used + merged + not_run` 这两条恒等式由构造保证，不靠调用方算术。

    `pass_no` 是**判定视图**的序号（0=首轮那份，i≥1=第 i 个扩容回合买回来的那份），
    与它派发出的取证回合号差 1 —— 派发出去的那次叫 `round_no = pass_no + 1`（`collect_triad_evidence`
    的词表）。两个号都从 0/1 起，混用一次就会让"第几轮"在事件与载荷里指不同的东西。
    """

    pass_no: int
    plans: Dict[str, Any]              # cat -> AnchorsPlan（带 cap 那一趟；未派发时为需求趟）
    calls: int = 0                     # 本轮真消耗的取证额度（池子读数差）
    pool_remaining: int = 0
    anchors_used: Dict[str, int] = field(default_factory=dict)
    anchors_merged: Dict[str, int] = field(default_factory=dict)
    anchors_not_run: Dict[str, int] = field(default_factory=dict)
    starved_terms: int = 0
    points_added: int = 0
    undecided_before: int = 0
    blind_before: int = 0
    undecided_after: Optional[int] = None
    blind_after: Optional[int] = None
    dispatched: bool = False           # 这一趟是否真派出了一个取证回合（True=打了）
    stopped_by: Optional[str] = None

    @property
    def anchors_planned(self) -> int:
        return sum(int(p.anchors_total) for p in self.plans.values())

    @property
    def anchors_sent(self) -> int:
        return sum(len(p.anchors) for p in self.plans.values())

    @property
    def anchors_dropped(self) -> int:
        return sum(int(p.anchors_dropped) for p in self.plans.values())

    @property
    def anchors_used_total(self) -> int:
        return sum(int(v) for v in self.anchors_used.values())

    @property
    def anchors_merged_total(self) -> int:
        return sum(int(v) for v in self.anchors_merged.values())

    @property
    def anchors_not_run_total(self) -> int:
        return sum(int(v) for v in self.anchors_not_run.values())

    @property
    def asking(self) -> Tuple[str, ...]:
        return tuple(sorted(c for c, p in self.plans.items() if p.reason == PLAN_EXPAND))

    def to_row(self) -> Dict[str, Any]:
        """上屏/落库的那一份 dict（**唯一**序列化点）。"""
        return {
            "pass_no": self.pass_no,
            "dispatched": bool(self.dispatched),
            "calls": int(self.calls),
            "pool_remaining": int(self.pool_remaining),
            "anchors_planned": self.anchors_planned,
            "anchors_sent": self.anchors_sent,
            "anchors_used": self.anchors_used_total,
            "anchors_merged": self.anchors_merged_total,
            "anchors_not_run": self.anchors_not_run_total,
            "anchors_dropped": self.anchors_dropped,
            "starved_terms": int(self.starved_terms),
            "points_added": int(self.points_added),
            "cells_undecided_before": int(self.undecided_before),
            "cells_blind_before": int(self.blind_before),
            "cells_undecided_after": self.undecided_after,
            "cells_blind_after": self.blind_after,
            "asking": list(self.asking),
            "stopped_by": self.stopped_by,
            "per_category": {
                cat: {
                    "reason": p.reason,
                    "stride": int(p.stride),
                    "cells_uncovered": p.cells_uncovered,
                    "anchors_total": int(p.anchors_total),
                    "anchors_dropped": int(p.anchors_dropped),
                    "exhausted_min_m": (None if p.exhausted_min_m is None
                                        else round(float(p.exhausted_min_m), 1)),
                }
                for cat, p in sorted(self.plans.items())
            },
        }


def forensic_block(records: Sequence[ForensicRoundRecord], *,
                   max_rounds: int, pool: POIBudget) -> Dict[str, Any]:
    """把逐回合记录汇成 ``caliber.forensic``（唯一构造点，计划 v7.0 片 4）。

    `per_category` 取**最后一条**记录的读数 —— 它回答的是「现在为什么停」，不是历史流水；
    历史在 `rounds` 列表里逐条摆着，两种问法各给各的数，不为了"一份 dict 打天下"而混。
    缺席即未发射（`scope.payload` 只在拿到 dict 时发这个键）：离线估算与夹具从没走过取证
    阶段，给它们补一份 `rounds: 0` 等于替一次没发生的取证举证。
    """
    last = records[-1] if records else None
    # 顶层那几个 `anchors_*` 只累加**真派发过**的趟次。末趟（因封顶/判全/无点可打而停下的那趟）
    # 也算过一次需求，把它并进总数就会得出「计划 59 个锚点、砍掉 31 个」这种句子 —— 而其中
    # 有 17 个我们从来没打算打（轮次已到顶）。未派发趟的读数原样留在 `rounds_detail` 与
    # `per_category` 里，问「现在还想扩吗」读它们，问「这轮花了多少」读顶层，两种问法不混。
    sent_recs = [r for r in records if r.dispatched]
    return {
        "rounds": len(sent_recs),
        "judging_passes": len(records),
        "max_rounds": int(max_rounds),
        "stop_reason": last.stopped_by if last is not None else None,
        "pool_total": int(pool.total),
        "pool_used": int(pool.total - pool.remaining),
        "pool_remaining": int(pool.remaining),
        "anchors_planned": sum(r.anchors_planned for r in sent_recs),
        "anchors_sent": sum(r.anchors_sent for r in sent_recs),
        "anchors_used": sum(r.anchors_used_total for r in sent_recs),
        "anchors_merged": sum(r.anchors_merged_total for r in sent_recs),
        "anchors_not_run": sum(r.anchors_not_run_total for r in sent_recs),
        "anchors_dropped": sum(r.anchors_dropped for r in sent_recs),
        "calls": sum(r.calls for r in sent_recs),
        "points_added_judging_only": sum(r.points_added for r in sent_recs),
        "points_policy": FORENSIC_POINTS_POLICY,
        "per_category": (last.to_row()["per_category"] if last is not None else {}),
        "rounds_detail": [r.to_row() for r in records],
    }


def _plan_cat(lat: LatticeAnchors, judgement: "Judgement", category: str, *,
              cap: Optional[int], tried: Sequence[LngLat]) -> "AnchorsPlan":
    """一类本轮的锚点计划 —— `plan_expansion` 在 `app/**` 里的**唯一**调用点。

    抽成一个函数不是为了整洁，是因为下面那两趟规划要调它两次：若把 `plan_expansion`
    直写两遍，G-9 那类「每个原语恰一处」的门会数出 2 处。红在自家门上的正确反应不是改门，
    而是让"那一处"只有一个名字。

    三个入参的来路各守一条纪律，少传任一个都会静默换口径：
    `region/grid/undecided/radius_m` 全部取自**同一次** `Judgement`（v5.9 前置①：判据与判盲
    吃同一份掩码与同一把尺）；`inside` 是 `masks.undecided` 而**不是**整片可达区
    （复审 P0-3：已判出的格照样排队要证据，D6 那个成本推演就还是纸面上的）。
    """
    return lat.plan_expansion(
        judgement.region, judgement.grid, category,
        max_anchors_per_cat=cap, already_tried=tried,
        inside=judgement.masks.undecided, radius_m=judgement.radius_m,
    )


def _plan_forensic_round(lat: LatticeAnchors, judgement: "Judgement", pool: POIBudget,
                         tried_by_cat: Mapping[str, Sequence[LngLat]],
                         ) -> Tuple[Dict[str, Tuple[LngLat, ...]], Dict[str, "AnchorsPlan"]]:
    """这一趟该打哪些锚点 —— **两趟**规划：先量需求，再按池子份额砍。零真实调用。

    为什么要两趟：`max_anchors_per_cat` 得知道「有几类想扩」才定得出份额，而"想扩几类"
    本身就是 `plan_expansion` 的读数。两趟都是纯函数 ⇒ 没有第二次决定的风险，只有第二次
    算术的成本（µs 级）。第二趟的 `anchors_dropped` 才是披露里那个数 —— 第一趟的
    `anchors_total` 只是需求，拿它当"打了几个"就是 v5.1 P0-3 要拦的静默截断。

    份额算式（v6.1③「按词数加权」的落地）：`share = remaining // 想扩的类数`，
    `cap = max(1, share // 词数)`。三件事各自防一种坏形状：
    - 除以词数 ⇒ market 一类 3 个词，不按词数折的话它会用 1/3 的份额打出 3 倍的调用；
    - 均分给「想扩的类」而不是全部类 ⇒ 已经 `covered` 的类不该占份额（否则稠密城那几类
      明明只有药店要扩，药店却只能拿到 1/3 池子）；
    - `max(1, …)` 的下界 ⇒ 预算再紧也不整类蒸发（与 `test_u38c` 那条转置轮询同方向）。
    """
    demand = {cat: _plan_cat(lat, judgement, cat, cap=None, tried=tried_by_cat.get(cat, ()))
              for cat in TRIAD_KEYS}
    asking = [cat for cat in TRIAD_KEYS if demand[cat].reason == PLAN_EXPAND]
    if not asking:
        return {}, demand                       # 没人要 ⇒ 原样交回需求趟的读数（供 `per_category`）
    share = pool.remaining // len(asking)
    plans: Dict[str, "AnchorsPlan"] = {}
    for cat in TRIAD_KEYS:
        if cat not in asking:
            plans[cat] = demand[cat]
            continue
        cap = max(1, share // max(1, len(triad_keywords(cat))))
        plans[cat] = _plan_cat(lat, judgement, cat, cap=cap, tried=tried_by_cat.get(cat, ()))
    return {cat: plans[cat].anchors for cat in asking}, plans



@dataclass(frozen=True)
class RoundOutcome:
    """一个取证回合走完后**一次性交出的整包事实**（计划 v6.1⑦「载荷定死」）。

    为什么要单独一个类型，而不是让消费方从 `ForensicStep` 上现场凑：回合循环（批 B 片 4）
    要包的是**回合产物**，不是"步"。载荷不定死，逐回合 trace 事件、`measure`/`collect` 的
    evidence 原料、以及「这轮的三态账目出自哪一次判定」就各消费方各拼一份 —— 拼出来的三份
    可以互相分家，而分家正是本仓反复出事的那一类（片 1a 收的就是它）。
    `report` 存在时与 `judgement` 一起校验（见 `__post_init__`）：**组装层若换了账目，
    构造即报错**，而不是等读侧 B11/B12 在另一个进程里发现。

    字段对齐计划 v6.1 的写法：那里的 `face` 由片 1a 的 `judgement` 承担（同一个捆绑出口，
    不留两个名字）；`degraded?` 不进这个类型 —— 降级出路根本不判定（POI 一个点都没拿到，
    判了也是空判），所以它没有回合产物，仍只走 `STEP_DEGRADED`。
    `round_no`（片 4 起为**真循环计数**）：末轮那次判定的趟序号 = `forensic.judging_passes − 1`
    = `forensic.rounds`（派发过的扩容回合数）。0 表示"一个回合都没打"，与批 A② 那个占位的
    恒 0 是同一个值、不同的意思 —— 现在它是由循环赋的，不是写死的。
    """

    round_no: int
    iso: Dict[str, Any]
    scope: SpatialScope
    collected: Any
    judgement: "Judgement"
    report: Optional[Dict[str, Any]] = None
    partial: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.round_no < 0:
            raise ValueError(f"回合序号必须非负，实得 {self.round_no}")
        if self.report is None:
            return                     # 中间轮只交取证事实，组装留给末轮（一次体检只落一条库）
        cal = self.report.get("caliber") or {}
        missing = sorted(set(STAT_KEYS) - set(cal))
        if missing:
            raise ValueError(
                f"回合载荷里的报告缺三态键 {missing} —— 载荷的用处就是让消费方无从各拼一份，"
                "缺键意味着有人绕过了捆绑出口"
            )
        for key in STAT_KEYS:
            if int(cal[key]) != int(self.judgement.stats[key]):
                raise ValueError(
                    f"报告宣称 {key}={cal[key]}，而本轮那一次判定算出的是 "
                    f"{self.judgement.stats[key]} —— 上屏的账目不是这次判定的账目"
                )


@dataclass(frozen=True)
class ForensicStep:
    """一次取证编排走到哪一步、这一步手上有哪些**事实**。

    只交事实、不产事件文案：舞台文本（`STAGE_PERCENT`、`evidence_id`、降级 label、专家队注入）
    留在编排方（pipeline）里 —— 数据源一旦开始懂 UI，就再拿不到「同一份编排喂两种消费者」
    这条便宜（`LiveDataSource` 与后台精报都没有事件）。

    `judgement`（计划 v6.5 片 1a）：`STEP_JUDGE` 交出的一次判定产物 —— 结论 + 三态账目 +
    **逐格掩码**。此前掩码算完就丢，谁要复用只能再判一遍；现在取证回合读的是这一个对象，
    而组装层只消费它（`assemble_living_circle` 的 `judgement` 必填参数）。

    `outcome`（批 A②）：本轮的**整包载荷**（`RoundOutcome`）。`judge` 步交判定时的载荷，
    `report` 步交「同一份判定 + 已组装报告」的载荷（`dataclasses.replace` 出来的，不是重算），
    其余步为 `None`。降级步永远是 `None`：那条出路没有判定，也就没有回合产物。

    `forensic_round`（片 4）：只在 `STEP_ROUND` 上给 —— 那一个扩容回合花了多少额度、
    买回来几格结论。它不落库（一次体检只落一条库，末值由 `outcome` 交），只上屏。
    `round` 步**故意不带 `outcome`**：中间轮的载荷与末轮载荷若同类型，读侧就会以为
    中间轮那份也能落库（`RoundOutcome` 的 `report=None` 分支正是为这一步留的）。
    """

    kind: str
    iso: Dict[str, Any] = field(default_factory=dict)
    scope: Optional[SpatialScope] = None
    collected: Any = None
    report: Optional[Dict[str, Any]] = None
    partial: Optional[Dict[str, Any]] = None
    judgement: Any = None
    outcome: Optional[RoundOutcome] = None
    forensic_round: Optional[ForensicRoundRecord] = None


async def live_forensic_steps(
    client: BaiduClient,
    engine: IsochroneEngine,
    check: "CheckParams",
    *,
    sample_profile: Optional[str] = None,
    intake_meta: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[ForensicStep]:
    """live 取证编排的**唯一一份**实现。

    此前同一段编排抄了三遍：`pipeline.living_circle` 的 live 分支（**线上唯一在跑的那份**）、
    `LiveDataSource.compute`、`refine_live_with_profile`。三份的顺序逐字同构，只差缓存与
    `intake_meta` —— 正是本仓反复出事的形状：取证回合（阶段 5 的 `compute_stream`）要接的是
    循环，而循环若接在其中一份上，另外两份就永远学不到它（第六轮复审 P0-6 点名的就是这个）。

    顺序就是事件顺序，**不许重排**：等时圈 → 先发 `measure` → 口径绑定 → 采集 → 绑实测证据 →
    残缺判定 → 发 `collect` → **判定** → 发 `judge` → 组装 → 发 `report`。用 async generator
    而不是「一把协程返回末值」正是为了这条：`measure` 必须早于采集完成流出，否则 SSE 的
    「边跑边出」退化成「跑完才出」，而这种退化没有任何一层会自动发现
    （`test_u36`/`test_pipeline_event_contract` 是现有的网）。

    `judge` 这一步**不发事件**（片 1a）：它交的是掩码与账目，上屏文案一个字都不变 ——
    时序表因此从四个 kind 升到五个，而事件序列与片 0 验收时逐字节相同（这两句话不矛盾，
    前者是编排事实、后者是上屏事实，各自的判据分别是 `test_m14` 与 `test_u36`）。

    降级有两条出路（口径绑不上 / 采集被残缺判定拦下），都以 `STEP_DEGRADED` 交出，调用方
    照旧发「百度{label}：降级为离线估算」那条消息 —— `evidence_count=0` 与正常分支的 `2`
    是**有意不同**的，不许统一。降级出路**不判定**（POI 一个点都没拿到，判了也是空判）。
    """
    from app.living_circle.quota import max_matrix_origins

    profile = sample_profile or check.sample_profile
    center = tuple(check.center)

    async def meter_fn(pts: List[Tuple[float, float]]) -> List[Optional[float]]:
        return await client.measure_matrix(check.travel_mode, pts, center)

    iso = await engine.compute(
        center,
        meter_fn,
        study_radius_m=check.study_radius_m,
        mode=profile,
        max_points=max_matrix_origins(profile, check.travel_mode),
        travel_mode=check.travel_mode,
    )
    yield ForensicStep(kind=STEP_MEASURE, iso=iso)

    guard = getattr(client, "guard", None)
    scope, degraded = await scope_or_degrade(
        caliber=get_caliber(check.travel_mode), center=center,
        radius_m=check.study_radius_m, iso=iso, params=check, guard=guard,
    )
    if degraded is not None:
        yield ForensicStep(kind=STEP_DEGRADED, iso=iso, report=degraded)
        return

    collected = await load_poi(
        client, center, scope.collect_radius_m, scope=scope,
        sample_profile=profile, travel_mode=check.travel_mode,
    )
    scope = bind_evidence(scope, collected)
    degraded = await degrade_if_incomplete(
        per_category=collected.per_category, params=check, guard=guard,
    )
    if degraded is not None:
        yield ForensicStep(kind=STEP_DEGRADED, iso=iso, scope=scope,
                           collected=collected, report=degraded)
        return

    partial = partial_for(guard)
    yield ForensicStep(kind=STEP_COLLECT, iso=iso, scope=scope,
                       collected=collected, partial=partial)

    # ── 取证回合（计划 v7.0 片 4）────────────────────────────
    # 首轮之后「按未判出的格补锚点、重判、再收」这一圈，接在**唯一编排**里 —— 接在别处
    # 就是第四份编排（片 0 收拢三份的全部理由）。三个消费方（pipeline 的 live 分支、
    # `LiveDataSource.compute`、`refine_live_with_profile`）从这一步起同时获得回合。
    from app.living_circle.quota import forensic_budget

    pool = POIBudget(total=forensic_budget())
    lat = LatticeAnchors()
    records: List[ForensicRoundRecord] = []
    # 判盲与判据共用的那份区域，初值 = **首轮标量边界的退化单圆盘**（锚点=分析中心）。
    # 显式取退化盘而不是让 `judge_once` 走缺省，是为了让回合有地方并入新盘；两者逐位相同
    # 由 `test_cover_matrix_default_path_is_bitwise_the_degenerate_single_disc` 钉着。
    region = scope.degenerate_evidence_region(center)
    # 判定吃的点位 = 并集；上屏的 8 类计数与评分吃的点位 = 首轮（`collected.triads`）。
    # 这两面性的存在理由与销账去处都写在计划 v6.1（用户拍板"展示面不动"），披露在
    # `caliber.forensic.points_added_judging_only` + `points_policy` 两处。
    judge_points: Dict[str, List[Dict[str, Any]]] = {
        cat: list(collected.triads.get(cat) or []) for cat in TRIAD_KEYS}
    tried_by_cat: Dict[str, Tuple[LngLat, ...]] = {}
    judgement: Optional["Judgement"] = None

    for pass_no in range(MAX_FORENSIC_ROUNDS + 1):
        # 判定：必须走在 `bind_evidence` **之后**、组装之前，且每次判定都吃**当前那份并集**。
        # ⚠️ 这个位置是口径问题不是风格问题 —— 判在绑证据之前，`judge_region` 会落回
        # 「未绑证据的退化区域」（`scope.py:745`），可判面静默变松而没有任何一层能发现。
        judgement = judge_once(center, scope, judge_points, prefix=check.scene_name,
                               region=region)
        undecided = int(judgement.masks.undecided.sum())
        blind = int(judgement.stats["cells_blind"])
        if not tried_by_cat:
            # 首轮那一次检索就是在**中心格**打的 ⇒ 中心格恒为"已试"。取法不住在这里，
            # 住 `anchors.hub_attempted` —— 成本推演脚本复算同一笔账时要读同一个定义，
            # 两边各写一份 `cell(n//2, n//2)` 就会"生产收了钱、脚本以为没收"。
            tried_by_cat = hub_attempted(judgement.grid)
        if pass_no and records:
            # 上一趟派发的那个回合买回来什么，现在才知道 —— 补上"之后"的读数再发事件。
            records[-1] = replace(records[-1], undecided_after=undecided, blind_after=blind)
            yield ForensicStep(kind=STEP_ROUND, iso=iso, scope=scope, collected=collected,
                               judgement=judgement, forensic_round=records[-1])
        anchors, plans = _plan_forensic_round(lat, judgement, pool, tried_by_cat)
        # 三条 break 的**顺序**就是判据的优先级，不可反（复审 B1：反了就会把"已经判全"
        # 说成"额度用完"，或把"没点可打"说成"轮次封顶"）：
        # ① 可达区内每格都有结论 ⇒ 收手是好消息；② 没有一类排得出新锚点 ⇒ 再打就是白烧，
        # 且它必须早于③，否则"无点可打"会被后面那趟封顶误标；③ 自己设的轮次上限。
        stop: Optional[str] = None
        if undecided == 0:
            stop = STOP_UNDECIDED_ZERO
        elif not anchors:
            stop = STOP_NOTHING_TO_ASK
        elif pass_no >= MAX_FORENSIC_ROUNDS:
            stop = STOP_ROUNDS_EXHAUSTED
        if stop is not None:
            records.append(ForensicRoundRecord(
                pass_no=pass_no, plans=plans, pool_remaining=pool.remaining,
                undecided_before=undecided, blind_before=blind,
                undecided_after=undecided, blind_after=blind, stopped_by=stop))
            break

        sent_before = pool.remaining
        rnd = await collect_triad_evidence(client, scope, anchors, pool, round_no=pass_no + 1)
        not_run = sum(rnd.anchors_not_run.values())
        # 「有需求而没额度」= 池子见底 / 回合被闸打断 / 有锚点一个词都没打上 / 规划端砍掉了。
        # 后两条都算：被 cap 砍掉的锚点覆盖的格**没有下家**，不披露就是"少打了几次"长得像
        # "这些地方不用打"（v5.1 P0-3 原话）。
        short = (pool.remaining <= 0 or bool(rnd.evidence.aborted) or not_run > 0
                 or any(int(p.anchors_dropped) > 0 for p in plans.values()))
        records.append(ForensicRoundRecord(
            pass_no=pass_no, plans=plans, dispatched=True,
            calls=sent_before - pool.remaining, pool_remaining=pool.remaining,
            anchors_used=rnd.anchors_used, anchors_merged=rnd.anchors_merged,
            anchors_not_run=rnd.anchors_not_run,
            starved_terms=len(rnd.evidence.starved_terms),
            points_added=sum(len(v) for v in rnd.points.values()),
            undecided_before=undecided, blind_before=blind,
            stopped_by=STOP_POOL_SHORT if short else None))
        # 并集：区域只增（`to_mask` 取并集 ⇒ 已有结论不会被推翻），点位只增（会把"没有"
        # 那条证据消掉 ⇒ 掩码每趟**必重算**，第五轮复审 P0-1）。`tried` 只记真发过请求的锚点
        # —— 口径来自 `ForensicRound.anchors_attempted` 的注释：拿"规划到"的喂下一轮，
        # 被池子饿死的点会被记成已试 ⇒ 扩容静默停止。
        region = EvidenceRegion(tuple(region.discs) + tuple(rnd.discs))
        for cat, pts in rnd.points.items():
            judge_points.setdefault(cat, []).extend(pts)
        for cat, tried in rnd.anchors_attempted.items():
            tried_by_cat[cat] = tuple(tried_by_cat.get(cat, ())) + tuple(tried)

    forensic = forensic_block(records, max_rounds=MAX_FORENSIC_ROUNDS, pool=pool)
    # 闸中止过 ⇒ `partial_for` 内部优先吃闸的 detail；只有闸没事而回合带着缺口收手时，
    # 归因才落到「取证额度耗尽」（`forensic_pool_short`）。优先级住在 `degrade_policy`。
    partial = partial_for(guard, forensic_short=any(
        r.stopped_by == STOP_POOL_SHORT for r in records))
    # 判定：`judge` 这一步**不发事件**（片 1a）—— 它交的是掩码与账目，上屏文案一个字不变。
    # `outcome` 挂在**末轮**那次判定上（一次体检只落一条库），`round_no` 从今天的恒 0
    # 变成真正的循环计数：`RoundOutcome.round_no == 判定趟数 − 1 == forensic.judging_passes − 1`。
    outcome = RoundOutcome(round_no=max(0, len(records) - 1), iso=iso, scope=scope,
                           collected=collected, judgement=judgement, partial=partial)
    yield ForensicStep(kind=STEP_JUDGE, iso=iso, scope=scope,
                       collected=collected, partial=partial, judgement=judgement,
                       outcome=outcome)
    report_data = assemble_living_circle(
        check, iso, collected.per_category, collected.triads, scope,
        intake_meta=intake_meta, poi_merged=collected.merged, partial=partial,
        judgement=judgement,
        # 落库声明必须来自**这一趟真正用的档位**（`profile`），不是 `check.sample_profile`：
        # 缓存键按 `profile` 建（`:619`），复用门按声明比（`reuse_policy`）—— 三者必须同源。
        sample_profile=profile,
        # 取证账目 + 「判定吃的区域」：逐锚点举证（`evidence_anchors`）必须由**判定真正吃的
        # 那块并集**发射，不能再拿首轮那份标量绑定塌一次（v5.9 前置②的那条守卫）。
        forensic=forensic,
    )
    # `replace` 而不是新建：报告必须挂在**同一次判定**的那份载荷上，构造时 `__post_init__`
    # 会逐键核对报告的三态账目与 `judgement.stats` ⇒ 「组装层换了一把账目」在生成器里就炸，
    # 不用等读侧 B11/B12 在另一个进程里发现。
    yield ForensicStep(kind=STEP_REPORT, iso=iso, scope=scope, collected=collected,
                       report=report_data, outcome=replace(outcome, report=report_data))


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
    # 编排走唯一实现；本函数只多两件事：按 `sample_profile` 精算档位、把实时产物写进 repo。
    report_data: Dict[str, Any] = {}
    produced = False
    async for step in live_forensic_steps(client, engine, check, sample_profile=sample_profile):
        if step.report is None:
            continue
        report_data = step.report
        produced = step.kind == STEP_REPORT
    if not produced:
        return report_data   # 降级出路：与今天一致，**不写缓存**（否则离线骨架会冒充精报）
    payload_key = caliber_payload_key(
        check.scene_name, check.center, check.study_radius_m, sample_profile, check.travel_mode
    )
    # 写缓存（同 `LiveDataSource.compute`：不变量由 `Repository.cache_report` 唯一拦截）
    repo.cache_report("live", payload_key, report_data)
    return report_data