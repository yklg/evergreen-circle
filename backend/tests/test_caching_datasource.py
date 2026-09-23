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


def test_u34_travel_mode_is_a_cache_key_dimension():
    """U34（种子改写锚点）：travel_mode **是**键维度（E3 行为变更的显式测试锚）。

    v4 之前键缺 travel_mode（riding/driving 与 walking 串同一份缓存）；E3 修复后
    5 参键必须能区分出行方式 —— 同一场景换出行方式 = 不同缓存条目（骑行/驾车可达区不同）。
    旧名 `test_t2_5_travel_mode_is_not_a_cache_key_dimension_yet` 断言「暂不是维度」，
    本版改写为正向断言，防止键维度回退。
    """
    p = _params(PAYLOAD)
    assert len(CachingDataSource._payload(p).split("|")) == 5  # 键维度 = 5 段（含 travel_mode）
    for tm_a, tm_b in (("walking", "riding"), ("walking", "driving"), ("riding", "driving")):
        pa = CheckParams(scene_name=p.scene_name, center=p.center, study_radius_m=p.study_radius_m,
                         sample_profile=p.sample_profile, travel_mode=tm_a)
        pb = CheckParams(scene_name=p.scene_name, center=p.center, study_radius_m=p.study_radius_m,
                         sample_profile=p.sample_profile, travel_mode=tm_b)
        assert CachingDataSource._payload(pa) != CachingDataSource._payload(pb), \
            f"{tm_a}/{tm_b} 不得串同一缓存键"
    # 端到端：同场景同中心换出行方式 → **精确键不命中**（键含 travel_mode），
    # 只可能经邻近兜底复用（served_from='nearby_cache' 而非 'cache'）——串键会直接 'cache' 命中。
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(pa := CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734),
                                             study_radius_m=2500.0, sample_profile="standard", travel_mode="walking")))
    assert src.calls == 1
    pb = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734),
                     study_radius_m=2500.0, sample_profile="standard", travel_mode="riding")
    hit_b = ds.peek(pb)
    assert hit_b is not None
    assert hit_b["served_from"] == "nearby_cache"  # 精确键未命中（travel_mode 是键维度）→ 邻近兜底
    assert src.calls == 1


# ── v5 U23-U25/U32-U33 · 缓存单一入口 peek / 邻近缓存 / 键一致性（E0/D24/D25）──

def test_u23_peek_nearby_cache_hit_zero_calls():
    """U23：peek 精确未命中 + 500m 内有报告 → `served_from='nearby_cache'`，零调用（O1/D9）。"""
    from app.living_circle.geo_utils import haversine_m

    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p1 = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734), study_radius_m=2500.0, sample_profile="standard")
    asyncio.run(ds.compute(p1))
    assert src.calls == 1
    # 同社区 ~290m 微调中心（GPS 抖动尺度）：精确未命中 → 邻近命中，原中心语义保留
    p2 = CheckParams(scene_name="凯里老街", center=(107.9787, 26.5734), study_radius_m=2500.0, sample_profile="standard")
    assert haversine_m(p1.center, p2.center) < 500.0
    hit = ds.peek(p2)
    assert hit is not None
    assert hit["served_from"] == "nearby_cache"
    assert hit["scene"]["center"] == [107.9758, 26.5734]  # 报告仍以原中心为准（D9 诚实呈现）
    assert src.calls == 1  # 零新增调用
    # 中心未解析（0,0）→ 跳过邻近（无意义且易误命中），返回 None
    p0 = CheckParams(scene_name="未定位", center=(0.0, 0.0), study_radius_m=2500.0, sample_profile="standard")
    assert ds.peek(p0) is None


def test_u24_caliber_payload_key_five_params_agree():
    """U24：5 参键 —— `CachingDataSource._payload` == 管线 `_scene_key`（E0 唯一实现，D24）。"""
    from app.core.pipeline.living_circle import _scene_key

    for tm in ("walking", "riding", "driving"):
        for profile in ("quick", "standard", "precise"):
            p = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734), study_radius_m=2500.0,
                            sample_profile=profile, travel_mode=tm)
            params = {"scene_name": "凯里老街", "center": [107.9758, 26.5734], "study_radius_m": 2500.0,
                      "sample_profile": profile, "travel_mode": tm}
            assert CachingDataSource._payload(p) == _scene_key(params), f"{tm}/{profile} 键漂移"


def test_u25_find_recent_report_near_radius_and_nearest():
    """U25：`find_recent_report_near` —— 半径过滤 + 取最近 + data_mode 前缀隔离。"""
    repo = Repository()

    def report(center, name):
        return {"scene": {"name": name, "center": [center[0], center[1]]}, "data_origin": "live"}

    far = (107.9858, 26.5734)    # 东 ~1km → 500m 半径外
    near = (107.9787, 26.5734)   # 东 ~290m → 半径内
    repo.cache_report("live", "seed-far", report(far, "远"))
    repo.cache_report("live", "seed-near", report(near, "近"))
    best = repo.find_recent_report_near("live", (107.9758, 26.5734), 500.0)
    assert best is not None and best["scene"]["name"] == "近"  # 取最近
    # data_mode 前缀隔离：fixture 域同名报告不参与 live 检索
    repo.cache_report("fixture", "seed-near-fixture", report((107.9758, 26.5734), "fixture域"))
    assert repo.find_recent_report_near("live", (107.9758, 26.5734), 500.0)["scene"]["name"] == "近"
    # 半径不足 → None
    assert repo.find_recent_report_near("live", (107.9758, 26.5734), 100.0) is None


def test_u32_peek_and_compute_share_payload_key():
    """U32：`peek` 与 `compute` 共享 `_payload`（R4/D24）—— 键构建唯一实现，peek 键 == compute 键。"""
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p = _params(PAYLOAD)
    # compute 写缓存（键 = _payload）；peek 用同一键直接命中 → 共享键构建
    asyncio.run(ds.compute(p))
    assert src.calls == 1
    hit = ds.peek(p)
    assert hit is not None and hit["served_from"] == "cache"
    assert src.calls == 1  # peek 未触发新的 compute
    # 反向验证：手工以 `_payload` 为键落缓存，peek 必须命中（读路径唯一实现）
    repo2 = Repository()
    ds2 = _ds(repo2, CountingSource())
    repo2.cache_report("live", CachingDataSource._payload(p), {"scene": {"name": "手工键"}, "data_origin": "live"})
    assert ds2.peek(p)["scene"]["name"] == "手工键"


def test_u33_find_recent_report_near_skips_expired_and_dirty():
    """U33：`find_recent_report_near` 预过滤 —— 过期条目不返回 / 缺 scene.center 脏条目跳过 / 500m 边界严格 <。"""
    import time

    # 过期：scan（SQL 预过滤）不返回过期行 → 邻近检索视为不存在
    repo = Repository(backend=MemoryCache(), default_ttl_s=0.05)
    repo.cache_report("live", "seed-exp", {"scene": {"name": "过期", "center": [107.9758, 26.5734]}, "data_origin": "live"})
    time.sleep(0.08)
    assert repo.find_recent_report_near("live", (107.9758, 26.5734), 500.0) is None
    # 脏条目（缺 scene.center）→ 跳过不抛
    repo2 = Repository()
    repo2.cache_report("live", "dirty", {"scene": {"name": "缺中心"}, "data_origin": "live"})
    assert repo2.find_recent_report_near("live", (107.9758, 26.5734), 500.0) is None
    # 500m 边界严格 <（与 U11 同语义）：恰 ≥500m 不命中
    # （haversine 按实现常量计算：500/99400 度 ≈ 500.24m，确保落在边界之外）
    repo3 = Repository()
    d500 = (107.9758 + 500.0 / 99400.0, 26.5734)  # 东 500.24m（lat 26.57 处 1°≈99400m）
    repo3.cache_report("live", "b500", {"scene": {"name": "恰500m", "center": [d500[0], d500[1]]}, "data_origin": "live"})
    assert repo3.find_recent_report_near("live", (107.9758, 26.5734), 500.0) is None

