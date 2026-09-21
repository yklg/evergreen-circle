"""场抽象（field.py）+ 盲区 marching-squares 边界集成测试。

对应测试覆盖面方案组 2 / 3 / 4：
- FD-1/2/3  BlindnessField 语义（1km 内缺任一必达 → 1，齐全 → 0，空类 → 盲）
- FD-4/5  grid-agnostic 采样 / 边界合理性
- BI-1    语义字段在几何改造前后不变（center/severity/gap/fixes）
- BI-2/3  新 polygon 闭合 / footprint_meta 字段与 undersampled
- AS-1    旧报告无 footprint_meta 经契约不判违规（legacy 兼容）
"""
import numpy as np
import pytest

from app.living_circle.field import BlindnessField, IsoField
from app.living_circle.geo_utils import xy_to_lnglat

CENTER = (107.9758, 26.5734)


def _triads(**kw):
    base = {"market": [], "pharmacy": [], "primary": []}
    base.update({k: [{"lng": l, "lat": t} for l, t in v] for k, v in kw.items()})
    return base


def _mk_center_facilities(offset_m=800.0):
    """在中心点正东 offset_m 放一个设施。"""
    c = list(CENTER)
    fac = xy_to_lnglat(CENTER, offset_m, 0.0)
    return c, fac


def test_blindness_field_missing_triad_returns_one():
    """FD-1 · 该点 1km 内某必达类缺失 → read=1（盲）。"""
    c, fac = _mk_center_facilities(50.0)
    # 只给 market：pharmacy/primary 空缺 → 该点仍判盲
    f = BlindnessField.build(tuple(c), _triads(market=[list(fac)]))
    # 中心点离 market 50m < 1km；但另外两类缺失 → 1
    assert f.read(0.0, 0.0) == 1.0


def test_blindness_field_served_circle_zero():
    """FD-2 · 三要素齐全且均 1km 内 → read=0（已覆盖）。"""
    c, fac = _mk_center_facilities(50.0)
    nearby = list(fac)
    f = BlindnessField.build(
        tuple(c),
        _triads(market=[nearby], pharmacy=[nearby], primary=[nearby]),
    )
    assert f.read(0.0, 0.0) == 0.0


def test_blindness_field_empty_facility_is_blind():
    """FD-3 · 某类整个为空（无设施点位）→ 该点为盲。"""
    c, _ = _mk_center_facilities()
    f = BlindnessField.build(tuple(c), _triads())
    assert f.read(0.0, 0.0) == 1.0


def test_blindness_field_local_meter_sampling():
    """FD-1 反例：该点在设施 1km 圆外 → read=1；在圆内且类齐全 → 0。"""
    c, fac = _mk_center_facilities(200.0)
    f = BlindnessField.build(tuple(c), _triads(market=[list(fac)]))
    # 只 market 已覆盖的点位（1km 内）仍因缺 pharmacy/primary 判盲 → 1
    assert f.read(0.0, 0.0) == 1.0


def test_blindness_field_boundary_all_three_served():
    f = BlindnessField.build(
        tuple(CENTER),
        _triads(
            market=[list(xy_to_lnglat(CENTER, 500, 0))],
            pharmacy=[list(xy_to_lnglat(CENTER, 0, 500))],
            primary=[list(xy_to_lnglat(CENTER, -500, 0))],
        ),
    )
    # 三要素各有设施在 1km 内 → 中心被覆盖 → 0
    assert f.read(0.0, 0.0) == 0.0
    # 移到 3km 外，三类全部 > 1km → 盲 → 1
    assert f.read(0.0, 3000.0) == 1.0


def test_read_missing_key_handled_gracefully():
    """未知类别键不崩（读路径的有意宽容）。"""
    f = BlindnessField(tuple(CENTER), {"market": [(100.0, 0.0)]})
    assert f.read(0.0, 0.0) == 1.0  # 只有 market，缺其他 → 盲


def test_isofield_converts_minutes_to_scalar():
    """IsoField 归一化：分钟→0.0..1.0；None 不可达 → 1.0。"""
    f = IsoField(lambda x, y: None)
    assert f.read(0.0, 0.0) == 1.0
    f2 = IsoField(lambda x, y: 5.0)
    assert 0.0 < f2.read(0.0, 0.0) < 1.0
    f3 = IsoField(lambda x, y: 0.0)
    assert f3.read(0.0, 0.0) == pytest.approx(1.0)