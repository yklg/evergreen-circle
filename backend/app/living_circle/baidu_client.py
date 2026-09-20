"""百度地图服务端客户端（真实调用 + 限流/退避，韧性经 request_guard 注入）。

职责边界（A3）：只做真实 HTTP 调用与参数组装，**不含业务快照/Fixture 回退**；
数据源选择与回退在 `data_source.py`。单测经 httpx.MockTransport 注入，
不产生真实网络请求。
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.living_circle.request_guard import CallGuard

logger = logging.getLogger(__name__)

BASE = "https://api.map.baidu.com"

# 批量距离矩阵单次上限（百度个人免费额度保守值，M0 探针 4×1 通过）
MATRIX_CHUNK = 25


class BaiduClient:
    def __init__(
        self,
        ak: str = "",
        guard: Optional[CallGuard] = None,
        transport: Optional[httpx.BaseTransport] = None,
        base: str = BASE,
    ) -> None:
        self.ak = ak
        self.guard = guard or CallGuard()
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
        radius_m: int = 2000,
        scope: int = 2,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """place/v2/search 分类检索 → 归一化 POI [{name,lng,lat,address}]。"""
        results: List[Dict[str, Any]] = []
        for page_num in range(0, 3):  # 最多 3 页兜全
            params: Dict[str, Any] = {
                "query": query,
                "location": f"{center[1]},{center[0]}",
                "radius": radius_m,
                "scope": scope,
                "filter": "sort_name:distance",
                "page_size": page_size,
                "page_num": page_num,
            }
            resp = await self._get("/place/v2/search", params)
            if not resp or resp.get("status") != 0:
                break
            items = resp.get("results") or []
            if not items:
                break
            for it in items:
                loc = it.get("location") or {}
                results.append({
                    "name": it.get("name", ""),
                    "lng": float(loc.get("lng", 0.0)),
                    "lat": float(loc.get("lat", 0.0)),
                    "address": it.get("address", ""),
                })
            if len(items) < page_size:
                break
        return results

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

        out: List[Optional[float]] = []
        dest = f"{destination[1]},{destination[0]}"

        for start in range(0, len(origins), chunk):
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
                for p in chunk_origins:
                    out.append(await self._direction_single(travel_mode, p, destination, fallback_path))
                continue

            for row in rows:
                if not isinstance(row, dict):
                    out.append(None)
                    continue
                # 不可达判定：duration.value == null（探针 P3 结论：restrictions_status 不可靠）
                duration_obj = row.get("duration")
                if duration_obj is None:
                    out.append(None)
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
                    out.append(None)
                    continue
                # duration 单位为秒 → 转分钟
                out.append(round(float(dur_value) / 60.0, 1))

        return out

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