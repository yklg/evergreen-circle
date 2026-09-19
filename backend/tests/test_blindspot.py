"""M1 · 服务盲区：1km 三要素判定 / 灰区聚合 / 最近设施近邻。"""
from app.living_circle.blindspot import BLIND_RADIUS_M, find_blindspots
from app.living_circle.geo_utils import xy_to_lnglat

CENTER = (107.9758, 26.5734)


def _fac(name, x, y):
    lng, lat = xy_to_lnglat(CENTER, x, y)
    return {"name": name, "lng": lng, "lat": lat}


def _dense_triad(center, x=0, y=0):
    """在一个方位点（局部米坐标）放置三要素齐全的一簇设施。"""
    return [
        {"name": f"菜市-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y)))},
        {"name": f"药店-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x + 200, y)))},
        {"name": f"小学-{x},{y}", **dict(zip(("lng", "lat"), xy_to_lnglat(center, x, y + 200)))},
    ]


def test_no_blindspots_when_triad_everywhere():
    """每 1km 圆内三要素齐备 → 0 盲区（用 400m 网格铺满三要素簇）。"""
    triads = {"market": [], "pharmacy": [], "primary": []}
    for x in range(-2000, 2001, 400):
        for y in range(-2000, 2001, 400):
            for k, name in zip(("market", "pharmacy", "primary"), _dense_triad(CENTER, x, y)):
                triads[k].append(name)
    spots = find_blindspots(CENTER, 2500.0, triads, prefix="t")
    assert spots == []


def test_single_missing_facility_produces_blindspot():
    """东南方位缺小学 → 东南角簇盲区，missing_facilities 含小学。"""
    triads = {
        "market": [_fac("菜市", 500, 0), _fac("菜市-远", -1800, 1800), _fac("菜市-北", 0, 1800)],
        "pharmacy": [_fac("药店", 0, 500), _fac("药店-远", 1800, -1800), _fac("药店-北", 1800, 0)],
        # 缺 primary 小学
        "primary": [],
    }
    spots = find_blindspots(CENTER, 2500.0, triads, prefix="kaili")
    assert len(spots) >= 1
    for s in spots:
        assert "小学" in s["missing_facilities"]
        assert s["radius_m"] == int(BLIND_RADIUS_M)
        assert s["polygon"]["type"] == "Polygon"
        ring = s["polygon"]["coordinates"][0]
        assert ring[0] == ring[-1]
        # nearest 应报告最近药店/菜市距离与方位
        assert any(n["facility"] == "pharmacy" for n in s["nearest"])
        assert any(n["distance_m"] > 0 for n in s["nearest"])


def test_blindspot_contract_fields():
    triads = {
        "market": [_fac("菜市", 500, 0)],
        "pharmacy": [_fac("药店", 0, 500)],
        "primary": [],
    }
    spots = find_blindspots(CENTER, 2500.0, triads, prefix="t2")
    first = spots[0]
    assert set(first.keys()) == {"id", "center", "radius_m", "missing_facilities", "nearest", "polygon"}
    assert first["id"].startswith("bs-t2-")
    assert len(first["center"]) == 2


def test_blindspot_dedup_ids_unique():
    triads = {
        "market": [_fac("菜市", 800, 800)],
        "pharmacy": [_fac("药店", -200, -200)],
        "primary": [],
    }
    spots = find_blindspots(CENTER, 2500.0, triads, prefix="u")
    ids = [s["id"] for s in spots]
    assert len(ids) == len(set(ids))