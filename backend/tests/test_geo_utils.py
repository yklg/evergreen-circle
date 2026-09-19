"""M1 · 几何工具：投影往返 / 球面距离 / 面积 / 点在环内 / 方位。"""
import math

import pytest

from app.living_circle import geo_utils as g


def test_to_local_xy_roundtrip():
    center = (107.9758, 26.5734)
    for p in [(107.9758, 26.5734), (108.0, 26.6), (107.9, 26.5)]:
        x, y = g.to_local_xy(center, p[0], p[1])
        lng, lat = g.xy_to_lnglat(center, x, y)
        assert abs(lng - p[0]) < 1e-6
        assert abs(lat - p[1]) < 1e-6


def test_center_is_origin():
    center = (107.9758, 26.5734)
    assert g.to_local_xy(center, center[0], center[1]) == (0.0, 0.0)


def test_haversine_known_distance():
    # 1 度纬度 ≈ 111.32 km
    d = g.haversine_m((0.0, 0.0), (0.0, 1.0))
    assert 111_000 < d < 112_000


def test_ring_area_km2_square():
    center = (0.0, 0.0)
    # 以中心为原点构造 2000m×2000m 正方形环
    ring = [g.xy_to_lnglat(center, x, y) for x, y in [(-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000)]]
    area = g.ring_area_km2(ring, center)
    assert 3.5 < area < 4.5  # 理论 4 km²，平面近似容差


def test_point_in_ring():
    center = (107.9758, 26.5734)
    ring = [g.xy_to_lnglat(center, x, y) for x, y in [(-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000), (-1000, -1000)]]
    inside = g.xy_to_lnglat(center, 0, 0)
    outside = g.xy_to_lnglat(center, 2000, 2000)
    assert g.point_in_ring(inside, ring)
    assert not g.point_in_ring(outside, ring)


def test_direction_word():
    a = (0.0, 0.0)
    assert g.direction_word(a, (0.0, 0.001)) == "正北"
    assert g.direction_word(a, (0.001, 0.0)) == "正东"
    assert g.direction_word(a, (-0.001, 0.0)) == "正西"


def test_ensure_closed_and_is_closed():
    ring = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]
    closed = g.ensure_closed(ring)
    assert g.is_closed(closed)
    assert not g.is_closed(ring)
    assert g.ensure_closed(closed) == closed  # 幂等


def test_bearing_roundtrip():
    a = (0.0, 0.0)
    b = (0.0, 0.01)
    assert math.isclose(g.bearing(a, b) % 360, 0.0, abs_tol=5)  # 正北≈0°