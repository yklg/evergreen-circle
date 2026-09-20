"""U3 · CachingDataSource 装饰器：命中/未命中委托/过期/键隔离（覆盖方案 U3-1~U3-4）。
T2 · 场景身份键三份实现的口径一致性（B3/I4）。"""
import asyncio

import pytest

from app.living_circle.data_source import CheckParams, CachingDataSource, LiveDataSource
from app.living_circle.repository import MemoryCache, Repository


def _scene_key(params: CheckParams) -> str:
    """流水线侧的场景键（带 `scene:` 命名空间前缀）。"""
    from app.core.pipeline.living_circle import _scene_key as impl

    return impl(dict(
        scene_name=params.scene_name,
        center=[params.center[0], params.center[1]] if params.center else None,
        study_radius_m=params.study_radius_m,
        sample_profile=params.sample_profile,
    ))

PAYLOAD = "上海市浦东新区陆家嘴|121.505252,31.233330|2500|standard|walking"
PAYLOAD2 = "凯里老街|107.975800,26.573400|2500|standard|walking"


class CountingSource:
    """计算源：记录调用次数，返回带 data_origin 的稳定契约。"""

    def __init__(self, origin="live"):
        self.calls = 0
        self.origin = origin

    async def compute(self, params: CheckParams) -> dict:
        self.calls += 1
        return {
            "scene": {"name": params.scene_name, "center": list(params.center or (0, 0)), "study_radius_m": int(params.study_radius_m)},
            "data_origin": self.origin,
            "isochrones": [],
            "sampling": {"points": [], "interpolation": "idw"},
            "poi": {"categories": [], "total": 0, "in_circle": 0, "points": []},
            "blindspots": [],
            "scores": {"total": 88.0, "triads": [], "radar": [], "note": ""},
        }


def _ds(repo=None, source=None, read_only=False):
    return CachingDataSource(
        source or CountingSource(),
        repo=repo or Repository(),
        data_mode="live",
        read_only=read_only,
    )


def _params(payload):
    """由场景键还原 CheckParams。

    ⚠️ 这里按下标手工复刻键格式（B3 已知脆弱点）。为防「键格式一变就静默错位」的假绿，
    还原后立刻用生产实现反算一次并比对——格式漂移会在**每一条** U3 用例里炸出来。
    TODO（阶段 3 / B3）：三份实现收敛为 `caliber.payload_key()` 后删除本复刻。
    """
    parts = payload.split("|")
    # caliber_payload_key 现在包含 travel_mode 维度：scene|lng,lat|radius|sample_profile|travel_mode
    assert len(parts) == 5, f"场景键格式已变（期望 5 段）：{payload!r}"
    lng, lat = (float(x) for x in parts[1].split(","))
    p = CheckParams(scene_name=parts[0], center=(lng, lat), study_radius_m=float(parts[2]), sample_profile=parts[3])
    assert CachingDataSource._payload(p) == payload, f"测试手工键与生产实现不一致：{payload!r}"
    return p


def test_u3_1_cache_hit_marks_served_from():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    r1 = asyncio.run(ds.compute(_params(PAYLOAD)))
    assert "served_from" not in r1
    assert src.calls == 1
    r2 = asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 1  # 未再委托
    assert r2["served_from"] == "cache"
    assert "cached_at" in r2
    assert r2["data_origin"] == "live"  # 缓存不改变数据口径


def test_u3_2_miss_delegates_and_backfills():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 1
    asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 1  # 回填后命中
    assert asyncio.run(ds.compute(_params(PAYLOAD)))["served_from"] == "cache"


def test_u3_3_expired_recomputes():
    repo = Repository(backend=MemoryCache(), default_ttl_s=0.05)
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_params(PAYLOAD)))
    import time

    time.sleep(0.08)
    asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 2


def test_u3_4_key_isolation_between_payloads():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_params(PAYLOAD)))
    asyncio.run(ds.compute(_params(PAYLOAD2)))
    assert src.calls == 2
    r1 = asyncio.run(ds.compute(_params(PAYLOAD)))
    assert r1["scene"]["name"] == "上海市浦东新区陆家嘴"
    assert src.calls == 2  # 各自命中各自缓存


def test_u3_read_only_never_writes():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src, read_only=True)
    asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 1
    # read_only：未命中也不回填（离线包装，只读 live 缓存）
    asyncio.run(ds.compute(_params(PAYLOAD)))
    assert src.calls == 2


# ── T2 · 场景身份键三份实现一致性（B3 / I4）─────────────────────────

def test_t2_5_three_payload_implementations_agree():
    """同一场景在 Live 源 / 缓存装饰器 / 流水线三处必须算出同一个身份（去掉命名空间前缀）。

    三份独立实现只要有一份改格式，同场景就会写出两份缓存（重复采集 + 命中不了）。
    """
    p = _params(PAYLOAD)
    live = LiveDataSource._scene_payload(LiveDataSource(ak=""), p)
    caching = CachingDataSource._payload(p)
    scene = _scene_key(p)
    assert live == caching
    # caliber_payload_key 统一后，流水线键不再加 "scene:" 前缀
    assert scene == live, "流水线键与缓存装饰器键必须完全一致"


@pytest.mark.parametrize("mode", ["quick", "standard", "precise"])
@pytest.mark.parametrize("radius", [2500.0, 5000.0, 9000.0])
def test_t2_5_key_separates_by_mode_and_radius(mode, radius):
    """研究半径 / 采样档位任一不同 → 身份键必须不同（分档半径的前置隔离护栏）。"""
    base = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734), study_radius_m=2500.0, sample_profile="standard")
    other = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734), study_radius_m=radius, sample_profile=mode)
    same = mode == "standard" and radius == 2500.0
    assert (CachingDataSource._payload(base) == CachingDataSource._payload(other)) is same


def test_t2_5_none_center_policy_diverges():
    """**记录当前行为**（B3 缺陷之一）：center=None 时三份实现的处理策略不一致。

    - 缓存装饰器 / 流水线：兜底 (0,0) → 参与缓存键；
    - Live 源：直接 TypeError。
    风险：真实场景在 (0,0) 附近时与「未解析中心」的场景撞同一份缓存（串数据）。
    当前流水线在调用前已统一解析中心，所以未爆；TODO（阶段 3/B3）：收敛到 `payload_key()`
    并要求中心点必须已解析（None 直接报错，不兜底 0,0）。
    """
    p = CheckParams(scene_name="未定位场景", center=None, study_radius_m=2500.0, sample_profile="standard")
    assert CachingDataSource._payload(p).split("|")[1] == "0.000000,0.000000"
    # caliber_payload_key 不再加 "scene:" 前缀，两者现在一致
    assert _scene_key(p) == CachingDataSource._payload(p)


def test_t2_5_cache_hit_requires_identical_key():
    """端到端实证：装饰器只认自己的键；流水线键多带 `scene:` 命名空间（用于 DB 场景去重）。

    两侧**主体串必须一致**（上一条用例已断言），否则同一社区会沉淀两份缓存。
    """
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p = _params(PAYLOAD)
    # 流水线键与缓存装饰器键现在一致（都使用 caliber_payload_key）
    repo.cache_report("live", _scene_key(p), {"scene": {"name": "流水线命名空间键"}, "data_origin": "live"})
    hit = asyncio.run(ds.compute(p))
    assert hit["scene"]["name"] == "流水线命名空间键"  # 现在能命中
    assert src.calls == 0  # 命中缓存，不调用源
    # 用装饰器自己的键回填则同样命中
    repo.cache_report("live", CachingDataSource._payload(p), {"scene": {"name": "缓存装饰器键"}, "data_origin": "live"})
    assert asyncio.run(ds.compute(p))["scene"]["name"] == "缓存装饰器键"
    assert src.calls == 0


def test_t2_5_travel_mode_is_not_a_cache_key_dimension_yet():
    """**记录当前行为**：身份键维度包含 travel_mode（R5 已加入）。

    CheckParams 现在有 sample_profile（采样档位）和 travel_mode（出行方式）两个独立字段。
    caliber_payload_key 现在为 5 段：scene|lng,lat|radius|sample_profile|travel_mode
    """
    p = CheckParams(scene_name="x", center=(0.0, 0.0))
    assert hasattr(p, "sample_profile") and p.sample_profile == "standard"
    assert hasattr(p, "travel_mode") and p.travel_mode == "walking"
    # caliber_payload_key 已加入 travel_mode 维度：现在为 5 段
    assert len(CachingDataSource._payload(_params(PAYLOAD)).split("|")) == 5  # 键维度 = 5 段 (含 travel_mode)

