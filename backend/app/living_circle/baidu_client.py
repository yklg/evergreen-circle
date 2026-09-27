"""百度地图服务端客户端（真实调用 + 限流/退避，韧性经 request_guard 注入）。

职责边界（A3）：只做真实 HTTP 调用与参数组装，**不含业务快照/Fixture 回退**；
数据源选择与回退在 `data_source.py`。单测经 httpx.MockTransport 注入，
不产生真实网络请求。

**进程级治理是构造期不变量（β，2026-09-22）**：任何 `BaiduClient`（无论 `guard=` 从哪来）
的调用**恒**受「按 AK 共享的并发/QPS 闸 + 当日总量预算」约束 —— 此前它是 **opt-in**
（`guard` 一有值就整条跳过 `_default_guard` ⇒ 拿到私有闸），即一条**静默脱离治理**的后门。
唯一例外：显式书写、打 WARNING、并被静态守卫（γ）限制在 `tests/**` 的 `allow_ungated=True`。
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import httpx

from app.living_circle.request_guard import (
    CallGuard,
    GlobalDailyBudget,
    GlobalRateLimiter,
    get_daily_budget,
    get_rate_limiter,
)

logger = logging.getLogger(__name__)

BASE = "https://api.map.baidu.com"

# 翻页收益止损：place/search 某页去重后新增条数低于此值即停止翻页（rev3 §2.3）
PAGE_STOP_MIN_NEW = 3

# 百度 place/v2/search **单页真实上限**（探针实测回填，勿凭印象改）。
# `scripts/probe_baidu.py place` 组 @凯里：请求 10/20 → 如实返回；请求 30/50 →
# `status=0` 但**静默降级**回 20 条（不报错、不告警）。
# ⇒ 这条实测事实不是性能参数，而是**正确性前提**：「短页 = 半径内已查全」这条判据
#   只在「服务端真的按 page_size 供货」时成立。若按 30 请求并按 30 判短页，
#   拿到 20 条会被误判成「查全了」⇒ 把「没查到」洗成「没有」—— 正是本仓 Q1 的缺陷形态。
# 与 `capability_manifest.json:poi_search.page_size_max` 同源，漂移由
# `tests/test_baidu_client.py` 的对照用例判红。
PLACE_PAGE_SIZE_MAX = 20

# `place_search` 的停止原因 —— **证据完整性的唯一承重判据**（P0-1）。
# 为什么必须显式建模：`results.append` 是无条件的（跨页去重只累加 `new_in_page`、从不删行），
# 故 `len(results)` 不编码任何内部状态；五个退出点共享同一个整数。探针亦确认
# `len_alone_decisive = false`（`len == page_size` 时「恰好查完」与「被截断」同值）。
STOP_COMPLETE = "complete"        # 短页 ⇒ 半径内已查全 ⇒ 可把请求半径当作证据边界
STOP_EMPTY = "empty"              # status=0 且 0 条 ⇒ 该半径内**真的没有**（可用于判盲）
STOP_PAGE_CAP = "page_cap"        # 页深耗尽而末页仍是满页 ⇒ **被截断** ⇒ 边界只能取最远实测点
STOP_DUP_STOP = "dup_stop"        # 收益止损 ⇒ 同「被截断」处理（再翻也未必有新点，但边界外仍可能有）
STOP_API_ERROR = "api_error"      # 请求失败/非 0 status ⇒ **一无所知**，绝不可当作「没有」
STOP_NOT_RUN = "not_run"          # 未发起任何请求（页深 0 / 预算拒绝）⇒ 同样是一无所知


class PlaceSearchOut(NamedTuple):
    """`place_search` 的返回：点位 + **证据完整性举证**。

    用 NamedTuple 而非裸 list，理由与 `poi.py:39 PoiPointsOut` 完全同构：
    后者是为「静默截断」把披露做成**无法被顺手丢掉**的形状；本类型是它的采集侧对偶 ——
    判盲要回答的是「某点 1km 内**没有**药店」这种全称否定，而它的前提恰恰是
    「这一圈的药店**查全了**」。裸 list 把这个前提丢在函数内部，于是下游只能靠
    几何半径猜，猜错就是误报盲区。

    `total` 只作旁证：探针实测同一次逐页翻检中它会漂移（60 → 63 → 60），
    **承重判据是 `stop_reason`**。
    """

    items: List[Dict[str, Any]]
    total: Optional[int]
    pages_fetched: int
    stop_reason: str

    @property
    def evidence_complete(self) -> bool:
        """半径内是否已查全 —— 只有为真时，请求半径才可以被当作**证据边界**使用。

        `api_error` / `not_run` 落 False 是刻意的：一无所知 ≠ 没有设施。
        """
        return self.stop_reason in (STOP_COMPLETE, STOP_EMPTY)

    @property
    def truncated(self) -> bool:
        """明确「还想拿但没拿到」的两种情形（不含失败/未跑，那些是 unknown）。"""
        return self.stop_reason in (STOP_PAGE_CAP, STOP_DUP_STOP)


def _shared_gate_params(ak: str) -> Tuple[int, float, GlobalRateLimiter, GlobalDailyBudget]:
    """进程级共享闸参数的**唯一取数口**：并发 / 级间间隔 / 闸对象 / 日预算对象。

    ⚠️ 唯一出口纪律（本项目反复验证有效）：**不得**在别处重算 ``1/qps`` 或另取一次
    ``get_daily_budget`` —— 一旦存在两处取数，`_default_guard` 与 `_attach_shared_gates`
    就会各持一份口径，「按 AK 共享」随即退化为「看起来共享」（B-2 同族形态）。
    下面两个消费方都吃这一份。

    参数源自 `Settings`（默认并发 ≤ QPS、间隔 ≥ 1/QPS，留余量）；升级到付费/商用额度后
    经 ``.env`` 放大换取更高采样精度。
    """
    from app.core.config import get_settings

    s = get_settings()
    qps = max(float(s.baidu_max_qps or 3.0), 1.0)
    concurrency = max(1, int(s.baidu_max_concurrency or 2))
    min_interval_s = round(1.0 / qps, 3)
    # R4：按 AK 共享进程级「并发+QPS 闸」
    rate_limiter = get_rate_limiter(ak, concurrency, min_interval_s)
    # R7d：按 AK 共享「当日调用总量预算」（cap<=0 ⇒ 禁用，默认 0）
    daily_budget = get_daily_budget(ak, int(getattr(s, "baidu_daily_quota", 0) or 0))
    return concurrency, min_interval_s, rate_limiter, daily_budget


def _default_guard(ak: str = "") -> "CallGuard":
    """按百度 AK 配额档位构造**保守**默认韧性层。

    个人免费档并发≈3 / QPS≈3。旧默认 ``CallGuard()``（并发 4 / 间隔 0.25s ≈ 4QPS）
    **已经高于免费档**，是「100/3 超限短信」与后续调研失败的推手之一。

    ``max_total_calls``（v5 B4/R2b）：接 `quota.total_calls_hard_ceiling()`（免费档 45），
    让管线 L277-281 的 ``total_meltdown`` 降级路径真正可触发——预算耗尽 → 诚实离线，
    绝不硬算。预算公式唯一归属 `quota.py`，此处只消费数值（I2 同哲学）。
    ⚠️ **本字段必须留在这里**：`test_u16_default_guard_wired_to_hard_ceiling` 钉住它；
    把它降成裸 ``CallGuard()``（方案 §12.3 B-2 的**字面**写法）会让所有生产 client
    丢掉 per-task 熔断上限 ⇒ 「一次体检烧穿 45 次」的旧缺陷复发（见 §12.10 D-5）。

    ⚠️ **本函数不再独自承担「共享」职责**（β）：闸的挂接已收口到 `_attach_shared_gates`，
    本函数只负责「取一份保守参数 + 一个 guard 壳」；二者共用 `_shared_gate_params()`，
    故「显式 guard」与「默认 guard」拿到的**必是同一把闸**。
    """
    from app.living_circle.quota import total_calls_hard_ceiling

    concurrency, min_interval_s, rate_limiter, daily_budget = _shared_gate_params(ak)
    return CallGuard(
        max_concurrency=concurrency,
        min_interval_s=min_interval_s,
        timeout_s=12.0,
        max_total_calls=total_calls_hard_ceiling(),
        rate_limiter=rate_limiter,
        daily_budget=daily_budget,
    )


def _attach_shared_gates(guard: "CallGuard", ak: str) -> None:
    """β（2026-09-22 裁决）：把进程级共享闸**无条件**接到 guard 上。

    此前共享是 **opt-in**：``self.guard = guard or _default_guard(self.ak)`` —— ``guard``
    一旦有值，``_default_guard`` **整个不被调用** ⇒ 该 client 拿私有闸
    （``rate_limiter is None`` ⇒ 回退每实例 ``_sem`` / ``_pace``）。
    于是「显式传 guard」成了一条**静默脱离进程级治理**的后门
    （同族：空 AK 缓存键、``LiveDataSource(client=…)`` 注入真实 client）。
    现在：无论 guard 从哪来，都以**共享闸为准**；guard 只保留其
    ``timeout_s`` / ``max_retries`` / ``backoff*`` / ``max_total_calls`` 定制。

    ⚠️ **只覆盖 `rate_limiter` / `daily_budget` 两个字段**，**不动**每实例的
    ``_max_concurrency`` / ``min_interval`` —— 那两者是「无共享闸时」的兜底；
    连它们一起覆盖，会让「拆掉共享闸」这件事在**行为上不可观测**
    （负对照 J4 随即失去判别力，退化成假护栏）。

    ⚠️ **契约（B-7 / K10）**：经本函数绑定的闸只约束**真实流量**；
    ``allow_ungated=True`` 的豁免 client 调用**不计入**共享日预算、**不占**共享闸
    ⇒ 「当日已用 N 次」**不是**全部调用数，**不得**用作计量 / 告警 / 报表的真源
    （本计数器是**节流状态**，见 `GlobalDailyBudget` docstring）。
    """
    _, _, rate_limiter, daily_budget = _shared_gate_params(ak)
    guard.rate_limiter = rate_limiter
    guard.daily_budget = daily_budget


class BaiduClient:
    """百度服务端客户端。**进程级治理是构造期不变量**（见模块 docstring / β）。"""

    def __init__(
        self,
        ak: str = "",
        guard: Optional[CallGuard] = None,
        transport: Optional[httpx.BaseTransport] = None,
        base: str = BASE,
        allow_ungated: bool = False,
    ) -> None:
        """构造客户端。``allow_ungated`` 是**唯一**的进程级闸豁免开关（默认关）。

        ⚠️ ``allow_ungated=True`` **仅在同时显式传入 `guard=` 时才有意义**
        （否则没有可豁免的对象），且只许出现在 ``tests/**``：生产代码里出现会被
        静态守卫 γ（`scripts/check_guard_construction.py`，G-2）判红。
        豁免意味着该 client 的调用**不计入**共享日预算、**不占**共享并发/QPS 闸。

        设计理由（为何留一条后门而不是无条件覆盖）：无条件覆盖会逼测试改用**更隐蔽**的
        绕过方式（干脆不经过 `BaiduClient`、或不测真实路径），后门照样存在 ——
        那正是本线要根治的「静默旁路」形态。让绕过**显式、具名、打日志、被守卫限制范围**
        才是正确边界（详见方案 §12.3 裁决 乙）。
        """
        self.ak = ak
        # 显式 guard 只贡献它的 timeout / retry / max_total_calls 定制，闸一律以共享为准（β）
        self.guard = guard if guard is not None else _default_guard(self.ak)
        if guard is not None and allow_ungated:
            logger.warning(
                "[living_circle] BaiduClient 显式豁免进程级闸（allow_ungated=True，仅限测试）："
                "该 client 的调用**不计入**全局并发 / QPS / 日预算。",
            )
        else:
            # `_default_guard` 内部已挂过同一份闸；此处是**无条件再声明一次**
            # （工厂按 AK 缓存 ⇒ 取回同一对象、参数相同故不告警）—— 让不变量
            # 「无论 guard 从哪来都受共享闸约束」在代码结构上无分支可绕。
            _attach_shared_gates(self.guard, self.ak)
        self.base = base.rstrip("/")
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport if self._transport else None,
                timeout=httpx.Timeout(self.guard.timeout_s, connect=5.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """带韧性的一次 GET（guard.call 负责并发/限速/退避/重试）。"""
        params = {**params, "ak": self.ak, "output": "json"}
        url = f"{self.base}{path}?" + urllib.parse.urlencode(params)

        async def work():
            client = self._client_get()
            r = await client.get(url)
            if r.status_code != 200:
                return {"status": r.status_code, "message": f"HTTP {r.status_code}"}
            try:
                return r.json()
            except Exception:  # noqa: BLE001
                return {"status": -1, "message": "bad json"}

        return await self.guard.call(work)

    # ── 坐标与地理编码 ──────────────────────────────────
    async def geocoding(self, address: str) -> Optional[Tuple[float, float]]:
        """地理编码：address → (lng, lat) BD-09。"""
        resp = await self._get("/geocoding/v3/", {"address": address})
        if not resp or resp.get("status") != 0:
            return None
        loc = resp.get("result", {}).get("location") or {}
        if "lng" in loc and "lat" in loc:
            return (float(loc["lng"]), float(loc["lat"]))
        return None

    async def geoconv(self, coords: List[Tuple[float, float]], from_: int = 1, to: int = 5) -> List[Tuple[float, float]]:
        """坐标转换（默认 WGS-84→BD-09）。返回转换后 (lng, lat) 列表。

        百度 `geoconv/v1` 的坐标类型编号：**1=WGS-84(GPS)、2=GCJ-02(国测局)、3=BD-09(百度)**。
        故默认 `from_=1, to=5` 是「WGS-84 → BD-09 经纬度」（5 = bd09ll），
        与浏览器 `navigator.geolocation` 的输出口径对齐。
        （原 docstring 写作「GCJ-02→BD-09」——把 1 当成 GCJ-02。这类"文档与编码不一致"
        正是坐标系事故的温床，故此处逐字写清编号含义。）
        """
        if not coords:
            return []
        pairs = ";".join(f"{lng},{lat}" for lng, lat in coords)
        resp = await self._get("/geoconv/v1/", {"coords": pairs, "from": from_, "to": to})
        if not resp or resp.get("status") != 0:
            return []
        out = []
        for item in resp.get("result", []) or []:
            out.append((float(item["x"]), float(item["y"])))
        return out

    async def reverse_geocoding(self, location: Tuple[float, float]) -> Optional[Dict[str, Any]]:
        """坐标 → 地址（BD-09 输入）。

        ⚠️ 历史实现返回 ``{"name": formatted_address, "city": ""}`` —— ``city`` 恒为空串：
        契约字段已声明却**从未接线**（百度响应里明明有 ``addressComponent``）。
        后果是「城市」只能由调用方去别处猜（前端拿的是**当前展示报告**的城市 →
        名/坐标/城市三者来源不一，实测产出「名称=北京劲松 / 中心=昆明」的报告）。

        现按百度 ``addressComponent`` 取：直辖市（北京/上海/天津/重庆）的 ``city`` 为空，
        此时回落 ``province``；``district`` 单独返回供调用方组合。
        """
        resp = await self._get(
            "/reverse_geocoding/v3/",
            {"location": f"{location[1]},{location[0]}", "coordtype": "bd09ll", "extensions_poi": 0},
        )
        if not resp or resp.get("status") != 0:
            return None
        result = resp.get("result") or {}
        comp = result.get("addressComponent") or {}
        city = (comp.get("city") or "").strip() or (comp.get("province") or "").strip()
        return {
            "name": result.get("formatted_address", "") or "",
            "city": city,
            "district": (comp.get("district") or "").strip(),
            "province": (comp.get("province") or "").strip(),
        }

    # ── POI 检索 ────────────────────────────────────────
    async def place_search(
        self,
        query: str,
        center: Tuple[float, float],
        radius_m: int,
        scope: int = 2,
        page_size: int = PLACE_PAGE_SIZE_MAX,
        max_pages: int = 3,
    ) -> PlaceSearchOut:
        """place/v2/search 分类检索 → :class:`PlaceSearchOut`（点位 + 证据完整性举证）。

        - `radius_m` **无默认值**：检索半径就是证据边界，必须由调用方显式决定。
          旧默认 `2000` 是「与 caliber 无关的硬编码采集半径」的最后一处残骸
          （见 `data_source.py` 「采集半径由调用方传入」纪律与 `scope.py` 的三概念表）。
        - `page_size` 默认取**探针实测的单页上限**（见 `PLACE_PAGE_SIZE_MAX` 的理由）。
        - `max_pages` 默认 3（V3 向后兼容全量兜底）；S8 扩词/预算感知采集传更小值或 1。
        - 保留 `tag`（服务属性）+ `detail_info.type`（别名）—— S2 标签裁决 / S8 扩词来源三的判据。
        - 收益止损：某页去重后新增 < `PAGE_STOP_MIN_NEW` 即停止翻页，不再无脑翻满。

        「短页 = 查全」这条判据按**实测页容量**而非请求值比对（`effective_page_size`）：
        百度对超额 `page_size` 静默降级，按请求值判短页会把「降级返回的满页」误读成「查全」。
        """
        effective_page_size = min(int(page_size or PLACE_PAGE_SIZE_MAX), PLACE_PAGE_SIZE_MAX)
        results: List[Dict[str, Any]] = []
        total: Optional[int] = None
        pages_fetched = 0
        stop = STOP_NOT_RUN

        for page_num in range(0, max(0, max_pages)):
            params: Dict[str, Any] = {
                "query": query,
                "location": f"{center[1]},{center[0]}",
                "radius": radius_m,
                "scope": scope,
                "filter": "sort_name:distance",
                "page_size": effective_page_size,
                "page_num": page_num,
            }
            resp = await self._get("/place/v2/search", params)
            if not resp or resp.get("status") != 0:
                stop = STOP_API_ERROR
                break
            if total is None and resp.get("total") is not None:
                total = int(resp["total"])
            items = resp.get("results") or []
            pages_fetched += 1
            if not items:
                # 首页就空 ⇒ 该半径内确实没有；中途空页 ⇒ 上页已给满、此处收尾 ⇒ 视为查全
                stop = STOP_EMPTY if pages_fetched == 1 else STOP_COMPLETE
                break
            new_in_page = 0
            for it in items:
                loc = it.get("location") or {}
                entry = {
                    "name": it.get("name", ""),
                    "lng": float(loc.get("lng", 0.0)),
                    "lat": float(loc.get("lat", 0.0)),
                    "address": it.get("address", ""),
                    "tag": it.get("tag", ""),
                    "type": (it.get("detail_info") or {}).get("type", ""),
                    # 设施身份的原始凭据。此前被整场丢弃 ⇒ 归并层只剩「名称 + 坐标」可用，
                    # 只能靠几何与字符串相等猜同一实体（`facility_rule` 的原则 1 因此
                    # 只能读名称）。`tag`/`address` 本来就在，只是从未被下游判据消费。
                    "uid": it.get("uid", ""),
                }
                # 页内去重收益判定：名称+坐标已存在 → 不计新增（配合翻页止损）
                if not any(
                    e["name"] == entry["name"] and abs(e["lng"] - entry["lng"]) < 1e-5
                    for e in results
                ):
                    new_in_page += 1
                results.append(entry)
            if len(items) < effective_page_size:
                stop = STOP_COMPLETE          # 短页 ⇒ 半径内已查全
                break
            if new_in_page < PAGE_STOP_MIN_NEW:
                stop = STOP_DUP_STOP          # 收益止损 ⇒ 按截断处理，不得当作查全
                break
        else:
            # 页深跑满且末页仍是满页 ⇒ 后面还有，只是没翻 —— 这就是被截断
            stop = STOP_PAGE_CAP if pages_fetched else STOP_NOT_RUN
        return PlaceSearchOut(results, total, pages_fetched, stop)


    # ── 测时（批量矩阵 + 单点兜底）────────────────────────
    async def _measure_matrix(
        self,
        travel_mode: str,
        origins: List[Tuple[float, float]],
        destination: Tuple[float, float],
        chunk_size: Optional[int] = None,
    ) -> List[Optional[float]]:
        """通用距离矩阵（walking/riding/driving）：N×1 → 分钟列表（None=不可达）。

        travel_mode: walking / riding / driving
        chunk_size: 分块大小（默认从 caliber 读取；若未加载 manifest 则兜底 25）
        """
        from app.living_circle.caliber import get_caliber

        caliber = get_caliber(travel_mode)
        api = caliber.api
        if not api:
            raise ValueError(f"Travel mode {travel_mode!r} has no API capability configured")

        chunk = chunk_size or api.chunk
        matrix_path = api.matrix_path
        fallback_path = api.fallback_path

        dest = f"{destination[1]},{destination[0]}"

        async def _measure_batch(start: int) -> List[Optional[float]]:
            chunk_origins = origins[start : start + chunk]
            origins_str = "|".join(f"{lat},{lng}" for lng, lat in chunk_origins)
            resp = await self._get(
                matrix_path,
                {"origins": origins_str, "destinations": dest},
            )
            rows = (resp or {}).get("result") or []
            if isinstance(rows, dict):
                rows = rows.get("rows") or []  # 兼容 {result:{rows:[...]}} 变体

            if len(rows) < len(chunk_origins):
                # 批量块部分/全部失败 → 降级单点兜底
                logger.warning(
                    "[living_circle] %s routematrix 块行数不足（need=%d got=%d），降级单点兜底",
                    travel_mode, len(chunk_origins), len(rows),
                )
                batch: List[Optional[float]] = []
                for p in chunk_origins:
                    batch.append(await self._direction_single(travel_mode, p, destination, fallback_path))
                return batch

            batch = []
            for row in rows:
                if not isinstance(row, dict):
                    batch.append(None)
                    continue
                # 不可达判定：duration.value == null（探针 P3 结论：restrictions_status 不可靠）
                duration_obj = row.get("duration")
                if duration_obj is None:
                    batch.append(None)
                    continue
                
                # 兼容两种格式：{duration: {value: N}} 或 {duration: N}（裸数字）
                if isinstance(duration_obj, dict):
                    dur_value = duration_obj.get("value")
                elif isinstance(duration_obj, (int, float)):
                    dur_value = duration_obj
                else:
                    # 字符串或其他类型 → 视为不可达（不猜值）
                    dur_value = None
                
                if dur_value is None:
                    batch.append(None)
                    continue
                # duration 单位为秒 → 转分钟
                batch.append(round(float(dur_value) / 60.0, 1))
            return batch

        # B1 分块并发（延迟优化）：块间无数据依赖，asyncio.gather 并发发出。
        # 并发受 CallGuard 闸门（sem + 级间限速）约束 → 总调用数/QPS 与串行一致，
        # 墙钟从「块数×(延迟+限速间隔)」降为「块数÷QPS + 延迟尾」；
        # gather 返回顺序即输入顺序（asyncio 语言级保证）→ 结果顺序与串行版一致。
        batches = await asyncio.gather(*[_measure_batch(start) for start in range(0, len(origins), chunk)])
        return [item for sublist in batches for item in sublist]

    async def measure_matrix(
        self,
        travel_mode: str,
        origins: List[Tuple[float, float]],
        destination: Tuple[float, float],
    ) -> List[Optional[float]]:
        """批量距离矩阵（**任意出行方式**）：N×1 → 分钟列表（None=不可达/该元素失败）。

        pipeline 与数据源都走这一个入口；``travel_mode`` 由调用方从 `CheckParams` 传入。
        旧版 pipeline 只会调 ``route_matrix_walking`` ⇒ 用户选「骑行/驾车」时测时口径
        被静默降级为步行（报告仍按骑行/驾车口径渲染），是「形参名承诺 ≠ 实参语义」的又一例。
        """
        return await self._measure_matrix(travel_mode, origins, destination)

    async def route_matrix_walking(
        self,
        origins: List[Tuple[float, float]],
        destination: Tuple[float, float],
    ) -> List[Optional[float]]:
        """批量距离矩阵（walking）：向后兼容薄壳，等价 ``measure_matrix("walking", …)``。"""
        return await self._measure_matrix("walking", origins, destination)

    async def _direction_single(
        self,
        travel_mode: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        fallback_path: str,
    ) -> Optional[float]:
        """单点方向 API 兜底（当矩阵返回行数不足时调用）。"""
        o_lat, o_lng = origin[1], origin[0]
        d_lat, d_lng = destination[1], destination[0]
        resp = await self._get(
            fallback_path,
            {"origin": f"{o_lat},{o_lng}", "destination": f"{d_lat},{d_lng}"},
        )
        if not resp or resp.get("status") != 0:
            return None
        result = resp.get("result")
        if not result or not isinstance(result, dict):
            return None
        routes = result.get("routes")
        if not routes or not isinstance(routes, list) or len(routes) == 0:
            return None
        duration_sec = routes[0].get("duration")
        if duration_sec is None:
            return None
        return round(float(duration_sec) / 60.0, 1)

    async def direction_walking(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> Optional[float]:
        """单点步行方向 API（兜底通道）。"""
        return await self._direction_single("walking", origin, destination, "/directionlite/v1/walking")