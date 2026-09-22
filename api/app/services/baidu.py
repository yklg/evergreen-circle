"""百度地图服务端 API 客户端（M2 实体解析 / 路线 / POI）。

- 全部接口走 **envelope 降级**：缺 AK / 超时 / 网络错 / 非 200 / 百度 status≠0 一律返回
  `{"ok": False, "reason": ...}`，绝不抛异常——调用方（spots 阶段）按 reason 走占位降级，
  任务不失败（《目的地实体政策》）。
- 坐标统一 bd09ll（百度经纬度），前端 JSAPI 原生坐标系，无需换算。
- AK / 超时走后端环境变量（Settings.baidu_server_ak / baidu_timeout），不进「模型配置」页。
- 打车费用为规则估算（起步 + 里程），调用方必须标「估算」。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import get_settings

_BASE = "https://api.map.baidu.com"

# 打车估价常量（口径写死、可复现；产出必须标「估算」）
TAXI_BASE_FARE_YUAN = 10.0   # 起步价（3km 内）
TAXI_BASE_KM = 3.0
TAXI_PER_KM_YUAN = 2.0       # 超出起步里程后每公里


def _server_config() -> tuple[str, float]:
    """读百度服务端 AK 与单次调用超时。测试可 monkeypatch 本函数注入。"""
    s = get_settings()
    return s.baidu_server_ak or "", float(s.baidu_timeout or 8.0)


def _client(timeout: float) -> httpx.Client:
    """httpx 客户端工厂（测试 monkeypatch 本函数注入 MockTransport）。"""
    return httpx.Client(
        timeout=httpx.Timeout(connect=5, read=timeout, write=5, pool=5),
        follow_redirects=True,
    )


def available() -> bool:
    """百度服务端 AK 是否可用；False 时 spots 阶段整体走降级链。"""
    ak, _ = _server_config()
    return bool(ak)


def _fail(reason: str) -> Dict[str, Any]:
    return {"ok": False, "reason": reason}


def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET 百度接口 → 解析 JSON → 校验百度业务 status。失败一律出 envelope。"""
    ak, timeout = _server_config()
    if not ak:
        return _fail("no_ak")
    query = dict(params)
    query["ak"] = ak
    query.setdefault("output", "json")
    url = f"{_BASE}/{path.lstrip('/')}"
    try:
        with _client(timeout) as client:
            r = client.get(url, params=query)
    except httpx.TimeoutException:
        return _fail("timeout")
    except httpx.RequestError:
        return _fail("network")
    if r.status_code != 200:
        return _fail(f"http_{r.status_code}")
    try:
        body = r.json()
    except Exception:
        return _fail("bad_json")
    if not isinstance(body, dict):
        return _fail("bad_body")
    status = body.get("status")
    if status is not None and int(status) != 0:
        return _fail(f"api_status_{status}")
    return {"ok": True, "body": body}


def place_search(
    query: str, region: str, *, page_size: int = 10
) -> Dict[str, Any]:
    """地点检索 v2（region 精确检索）。

    成功：{"ok": True, "places": [{name, lat, lng, area, address, detail_info?}...]}
    无结果为 ok=True + places=[]（调用方据此走地理编码兜底，不算接口失败）。
    """
    resp = _get(
        "place/v2/search",
        {
            "query": query,
            "region": region,
            "region_limit": "true",
            "page_size": max(1, min(int(page_size), 20)),
            "scope": 2,
        },
    )
    if not resp.get("ok"):
        return resp
    rows = resp["body"].get("result") or []
    places: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") or {}
        places.append(
            {
                "name": (item.get("name") or "").strip(),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "area": (item.get("area") or "").strip(),
                "address": (item.get("address") or "").strip(),
                "tag": (item.get("tag") or "").strip(),
            }
        )
    return {"ok": True, "places": places}


def geocode(address: str, city: str = "") -> Dict[str, Any]:
    """地理编码 v3：地址 → bd09ll 坐标。

    成功：{"ok": True, "lat": .., "lng": .., "confidence": int}
    置信度不足由调用方判断是否视为 matched=false。
    """
    params: Dict[str, Any] = {"address": address}
    if city:
        params["city"] = city
    resp = _get("geocoding/v3/", params)
    if not resp.get("ok"):
        return resp
    result = resp["body"].get("result") or {}
    loc = result.get("location") or {}
    if loc.get("lat") is None or loc.get("lng") is None:
        return _fail("empty_result")
    return {
        "ok": True,
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "confidence": result.get("confidence"),
    }


def _digest_route(route: Dict[str, Any]) -> Dict[str, Any]:
    """从百度 direction 的一条 route 中提取可展示摘要与换乘步骤。"""
    steps_out: List[Dict[str, Any]] = []
    for st in route.get("steps") or []:
        if not isinstance(st, dict):
            continue
        # vehicle 可能是字符串（步行/地铁）或 dict（{"description": "地铁2号线"}），两种都归一
        raw_vehicle = st.get("vehicle") or st.get("type") or ""
        if isinstance(raw_vehicle, dict):
            vehicle = str(raw_vehicle.get("description") or "").strip()
        else:
            vehicle = str(raw_vehicle).strip()
        raw_dist = st.get("distance")
        if isinstance(raw_dist, dict):
            distance_text = raw_dist.get("text", "")
        else:
            distance_text = raw_dist
        steps_out.append(
            {
                "instruction": str(st.get("instruction") or "").strip(),
                "vehicle": vehicle,
                "distance_m": distance_text,
            }
        )
    return {
        "distance_m": route.get("distance"),
        "duration_s": route.get("duration"),
        "steps": steps_out,
    }


def direction(
    mode: str,
    origin: str,
    destination: str,
    city: Optional[str] = None,
    city_limit: bool = True,
) -> Dict[str, Any]:
    """路线规划 v2（mode: transit|driving|walking）。坐标格式 "lat,lng"。

    成功：{"ok": True, "routes": [{distance_m, duration_s, steps:[...]}...]}（按耗时升序）
    """
    if mode not in ("transit", "driving", "walking"):
        return _fail(f"bad_mode_{mode}")
    params: Dict[str, Any] = {"origin": origin, "destination": destination}
    if city:
        params["city1"] = city
        params["city2"] = city
        if mode == "transit" and city_limit:
            params["citylimit"] = "true"
    resp = _get(f"direction/v2/{mode}", params)
    if not resp.get("ok"):
        return resp
    result = resp["body"].get("result") or {}
    routes = result.get("routes") or result.get("route") or []
    if isinstance(routes, dict):
        routes = [routes]
    digests = [_digest_route(r) for r in routes if isinstance(r, dict)]
    digests.sort(key=lambda d: d.get("duration_s") or 0)
    return {"ok": True, "routes": digests}


def taxi_estimate(distance_m: Optional[float]) -> Dict[str, Any]:
    """按里程估算打车费（纯函数、可复现）；结果必须标「估算」。"""
    if distance_m is None:
        return {"ok": False, "reason": "no_distance"}
    km = float(distance_m) / 1000.0
    if km <= 0:
        return {"ok": False, "reason": "bad_distance"}
    fare = TAXI_BASE_FARE_YUAN + max(0.0, km - TAXI_BASE_KM) * TAXI_PER_KM_YUAN
    return {"ok": True, "fare_yuan": round(fare), "distance_km": round(km, 1), "estimated": True}
