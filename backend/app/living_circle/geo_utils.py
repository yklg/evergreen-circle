"""几何工具（living_circle 域单一实现来源，A1）。

约定：全域使用百度坐标系 BD-09，坐标一律 (lng, lat)。渲染/插值所需的
「米制平面」由本模块统一提供：
  - to_local_xy / xy_to_lnglat：以中心点为原点的本地等距近似投影（渲染用，非测地结算）
  - haversine_m：球面大圆米制距离（盲区判定/近邻距离）
  - ring_area_km2：多边形面积（等距平面近似，鞋带公式）
M 阶段所有换算只准走这里，禁止各模块自行 COPY 换算逻辑。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

LngLat = Tuple[float, float]  # (lng, lat)

# 每度纬度对应米（WGS-84 平均）
M_PER_DEG_LAT = 111_320.0

# BD-09 经纬度的合法值域（值域即契约，不随模块漂移）
BD_LNG_ABS_MAX = 180.0
BD_LAT_ABS_MAX = 90.0


def parse_bd_lnglat(v: object) -> Optional[LngLat]:
    """BD-09 经纬度合法性解析 —— 全项目唯一实现。

    契约（四条同时满足才算合法）：
      1) 是长度恰为 2 的序列；
      2) 两项均为实数（``bool`` 不算）；
      3) 两项均有限（拒绝 inf / nan）；
      4) ``|lng| <= 180`` 且 ``|lat| <= 90``。

    任一条不满足 → 返回 ``None``，由调用方决定拒绝方式（API 层 422 / 前端抛错）。

    **为什么必须是「值校验」而不是「类型校验」**：本域的 ``LngLat`` 是裸元组
    ``Tuple[float, float]``，BD-09 经纬度、百度墨卡托米、局部平面米三者在类型系统里
    **完全同形**。历史事故：BMapGL ``dragend`` 的 ``e.point`` 是墨卡托平面坐标（米）
    ``(11440230.81, 2860409.52)``，被当作经纬度穿过全链路 → 地图中心被打到
    ``lng 150.81, lat 84.60``（北极圈）→ 无瓦片 → 画布退化为纯色。
    故坐标系语义只能由**值域**兜住；这也是本函数作为跨层契约存在的唯一理由。
    """
    if isinstance(v, (str, bytes)):
        return None
    try:
        items = list(v)  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(items) != 2:
        return None
    out: List[float] = []
    for it in items:
        if isinstance(it, bool) or not isinstance(it, (int, float)):
            return None
        f = float(it)
        if not math.isfinite(f):
            return None
        out.append(f)
    lng, lat = out
    if abs(lng) > BD_LNG_ABS_MAX or abs(lat) > BD_LAT_ABS_MAX:
        return None
    return (lng, lat)

# 方位词（盲区"最近设施"的方向描述，16 方位）
_DIRECTIONS = [
    "正北", "东北", "正东", "东南",
    "正南", "西南", "正西", "西北",
]


def to_local_xy(center: LngLat, lng: float, lat: float) -> Tuple[float, float]:
    """中心点局部平面投影 → (x 米, y 米)。x 向东、y 向北。"""
    d_lng = lng - center[0]
    d_lat = lat - center[1]
    x = d_lng * M_PER_DEG_LAT * math.cos(math.radians(center[1]))
    y = d_lat * M_PER_DEG_LAT
    return float(x), float(y)


def xy_to_lnglat(center: LngLat, x: float, y: float) -> LngLat:
    """局部平面投影逆变换 → (lng, lat)。"""
    lng = center[0] + x / (M_PER_DEG_LAT * math.cos(math.radians(center[1])))
    lat = center[1] + y / M_PER_DEG_LAT
    return (float(lng), float(lat))


def haversine_m(a: LngLat, b: LngLat) -> float:
    """球面大圆距离（米）。a/b 均为 (lng, lat)。"""
    r = 6_371_000.0
    d_lat = math.radians(b[1] - a[1])
    d_lng = math.radians(b[0] - a[0])
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(a[1])) * math.cos(math.radians(b[1])) * math.sin(d_lng / 2) ** 2
    )
    return float(2 * r * math.asin(min(1.0, math.sqrt(h))))


def ring_area_km2(ring: Sequence[LngLat], center: LngLat) -> float:
    """多边形面积（km²）：先把环投影到中心点局部平面，再用鞋带公式。

    注意：环必须闭合（首尾同点）——契约与前端一致；不闭合时自动补齐。
    """
    pts = [to_local_xy(center, lng, lat) for (lng, lat) in ring]
    if pts and (pts[0][0] != pts[-1][0] or pts[0][1] != pts[-1][1]):
        pts = pts + [pts[0]]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0 / 1_000_000.0


def bearing(a: LngLat, b: LngLat) -> float:
    """a→b 的方位角（度，0=正北，顺时针）。"""
    d_lng = math.radians(b[0] - a[0])
    lat1 = math.radians(a[1])
    lat2 = math.radians(b[1])
    y = math.sin(d_lng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lng)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def direction_word(a: LngLat, b: LngLat) -> str:
    """a→b 的 8 方位词（正北/东北/…）。"""
    deg = bearing(a, b)
    idx = int(((deg + 22.5) % 360) // 45)
    return _DIRECTIONS[idx % 8]


def polygon_centroid(ring: Sequence[LngLat], center: LngLat) -> LngLat:
    """多边形质心（平面近似，逆投影回球面）。"""
    pts = [(to_local_xy(center, lng, lat)) for (lng, lat) in ring]
    if pts and (pts[0][0] != pts[-1][0] or pts[0][1] != pts[-1][1]):
        pts = pts + [pts[0]]
    a = 0.0
    cx = 0.0
    cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return ring[0]
    a2 = a * 3.0
    return xy_to_lnglat(center, cx / a2, cy / a2)


def round_lnglat(lng: float, lat: float, digits: int = 6) -> LngLat:
    return (round(lng, digits), round(lat, digits))


def is_closed(ring: Sequence[LngLat]) -> bool:
    return len(ring) >= 4 and ring[0][0] == ring[-1][0] and ring[0][1] == ring[-1][1]


def ensure_closed(ring: List[LngLat]) -> List[LngLat]:
    """保证闭环（首尾同点），不闭合则自动追加首点。"""
    if ring and (ring[0][0] != ring[-1][0] or ring[0][1] != ring[-1][1]):
        return ring + [ring[0]]
    return ring


def envelope_minmax(points: Sequence[LngLat]) -> Tuple[float, float, float, float]:
    """最小外接矩形 (lng_min, lat_min, lng_max, lat_max)。"""
    lngs = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lngs), min(lats), max(lngs), max(lats))


def point_in_ring(pt: LngLat, ring: Sequence[LngLat]) -> bool:
    """射线法点在多边形内判定（闭包容忍：无需人为闭合）。"""
    x, y = pt
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ── 形状口径（第五把尺：只诊断，不入分）────────────────────────────────────
# 半径与方位都必须相对**某一个点**量。用本文件这颗 `shape_of` 只换原点（中心点→多边形质心）实测：
# 凯里 15min 圆度 0.713→0.684（动 0.029，而两城之间总共只差 0.082 ⇒ 口径吃掉 36%）、最弱读数
# 438m→553m；北京劲松 15min 更直接 —— 最弱方位**改口**（正西→东北）。所以原点/分相/方位角实现
# 三件事必须钉死并随键下发。两组数字的判据在 `tests/test_shape_caliber.py` 的两条正对照里，
# 改口径会让它们转红 —— 别把它们抄回注释当新事实（注释里换过一次数，就是因为当年抄的是平面近似值）。
SHAPE_BIN_DEG = 45.0          # 分箱宽度：与 direction_word 的 8 词 45° 分桶对齐
SHAPE_BIN_PHASE = "center"    # 分相：以方位为中心。floor 分相会把缺口并进隔壁方向取最大值
SHAPE_ORIGIN = "scene.center" # 原点：报告定格中心点，不是质心（polygon_centroid 零消费者）
SHAPE_AZIMUTH_FN = "bearing"  # 方位角实现：球面 bearing()，与 direction_word 同源


def shape_of(ring: Sequence[LngLat], center: LngLat, area_km2: float) -> dict:
    """等时圈环的形状读数（纯几何、零外呼）。

    `area_km2` 是**入参不是自算**：面积的唯一出处是 `ring_area_km2`（由发键方把
    同一档已算好的 `area_km2` 递进来）。这里再算一遍就会长出第二个面积真源，
    而 `circularity` 恰好只依赖它 —— 那是本域「同一量两处生产」反复出事的老形态。

    分箱：`k = ((方位角 + 22.5) % 360) // 45`，与 `direction_word` 逐字同式。
    半径取**箱内最大**并 round 到 0.1m —— 与 `scope.reach_circumradius_m`（同为
    `max(haversine_m(center, p))`，落库 round 1 位）保持可精确对账的精度。
    """
    if not ring:
        raise ValueError("shape_of：空环无从量形状")
    if area_km2 is None or area_km2 <= 0 or not math.isfinite(area_km2):
        raise ValueError(f"shape_of：面积必须是正的有限值，拿到 {area_km2!r}")
    bins: List[float] = [0.0] * 8
    for p in ring:
        k = int(((bearing(center, p) + 22.5) % 360.0) // SHAPE_BIN_DEG) % 8
        r = haversine_m(center, p)
        if r > bins[k]:
            bins[k] = r
    bins = [round(r, 1) for r in bins]
    r_max = max(bins)
    r_min = min(bins)
    if r_max <= 0:
        raise ValueError("shape_of：环上所有顶点与中心点同址，形状无定义")
    eq_r = math.sqrt(area_km2 * 1_000_000.0 / math.pi)
    return {
        "bins_m": bins,
        "bins_word": [_DIRECTIONS[k] for k in range(8)],   # 词表只有一份：随键下发，前端不另抄
        "bin_deg": SHAPE_BIN_DEG,
        "bin_phase": SHAPE_BIN_PHASE,
        "origin": SHAPE_ORIGIN,
        "azimuth_fn": SHAPE_AZIMUTH_FN,
        "circularity": round(eq_r / r_max, 3),
        "weak_ratio": round(r_min / r_max, 3),
    }
