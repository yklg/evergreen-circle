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
        """坐标转换（默认 GCJ-02→BD-09）。返回转换后 (lng, lat) 列表。"""
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
        resp = await self._get(
            "/reverse_geocoding/v3/",
            {"location": f"{location[1]},{location[0]}", "coordtype": "bd09ll", "extensions_poi": 0},
        )
        if not resp or resp.get("status") != 0:
            return None
        return {
            "name": (resp.get("result", {}) or {}).get("formatted_address", "") or "",
            "city": "",
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

    # ── 步行测时 ────────────────────────────────────────
    async def direction_walking(self, origin: Tuple[float, float], destination: Tuple[float, float]) -> Optional[float]:
        """单点步行测时 → 分钟（None=不可达/失败）。"""
        resp = await self._get(
            "/directionlite/v1/walking",
            {"origin": f"{origin[1]},{origin[0]}", "destination": f"{destination[1]},{destination[0]}"},
        )
        if not resp or resp.get("status") != 0:
            return None
        result = (resp.get("result") or {}).get("routes") or []
        if not result:
            return None
        duration_s = result[0].get("duration", 0)
        return duration_s / 60.0 if isinstance(duration_s, (int, float)) else None

    async def route_matrix_walking(
        self,
        origins: List[Tuple[float, float]],
        destination: Tuple[float, float],
    ) -> List[Optional[float]]:
        """批量距离矩阵（walking）：N×1 → 分钟列表（None=不可达/该元素失败）。

        分块调用（MATRIX_CHUNK/次），聚合结果；M0 探针已验证批量分支可行。
        """
        out: List[Optional[float]] = []
        dest = f"{destination[1]},{destination[0]}"
        for start in range(0, len(origins), MATRIX_CHUNK):
            chunk = origins[start : start + MATRIX_CHUNK]
            origins_str = "|".join(f"{lat},{lng}" for lng, lat in chunk)
            resp = await self._get(
                "/routematrix/v2/walking",
                {"origins": origins_str, "destinations": dest},
            )
            elements = (resp or {}).get("result", {}).get("elements") or []
            for el in elements:
                if el.get("status") != 0:
                    out.append(None)
                else:
                    duration_s = el.get("duration", {}).get("value")
                    out.append(duration_s / 60.0 if isinstance(duration_s, (int, float)) else None)
        return out