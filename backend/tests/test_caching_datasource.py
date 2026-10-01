"""U3 · CachingDataSource 装饰器：命中/未命中委托/过期/键隔离（覆盖方案 U3-1~U3-4）。
T2 · 场景身份键三份实现的口径一致性（B3/I4）。

场景标识**不再按下标手工复刻键格式**（原 `_shanghai()` 那套）：键一多一个维度，
20 余条用例就靠一个 `len(parts) == 5` 连坐炸掉。现在场景直接用 `CheckParams` 表达，
需要键的地方一律现算 `CachingDataSource._payload(...)` —— 键格式只有一处实现，
跨实现一致性仍由 `test_t2_5_three_payload_implementations_agree` 正向守着。
"""
import asyncio

import pytest

from app.living_circle.caliber import facility_merge_enabled
from app.living_circle.category_rule import COVERAGE_CALIBER_VERSION
from app.living_circle.data_source import CheckParams, CachingDataSource, LiveDataSource
from app.living_circle.facility_rule import FACILITY_RULE_VERSION
from app.living_circle.repository import MemoryCache, Repository
from app.living_circle.scope import SCOPE_POLICY_VERSION
from conftest import live_payload


def _scene_key(params: CheckParams) -> str:
    """流水线侧的场景键（带 `scene:` 命名空间前缀）。"""
    from app.core.pipeline.living_circle import _scene_key as impl

    return impl(dict(
        scene_name=params.scene_name,
        center=[params.center[0], params.center[1]] if params.center else None,
        study_radius_m=params.study_radius_m,
        sample_profile=params.sample_profile,
    ))

SHANGHAI_NAME = "上海市浦东新区陆家嘴"
SHANGHAI_CENTER = (121.505252, 31.233330)


def _shanghai() -> CheckParams:
    """主场景（每次给新实例：CheckParams 会被下游读来算键，不跨用例共享可变对象）。"""
    return CheckParams(scene_name=SHANGHAI_NAME, center=SHANGHAI_CENTER,
                       study_radius_m=2500.0, sample_profile="standard")


def _kaili() -> CheckParams:
    """第二个场景：只用于「不同场景各自命中各自缓存」的隔离判据。"""
    return CheckParams(scene_name="凯里老街", center=(107.975800, 26.573400),
                       study_radius_m=2500.0, sample_profile="standard")


class CountingSource:
    """计算源：记录调用次数，返回带 data_origin 的稳定契约。

    `policy_version` 默认取**当前**判盲口径版本 —— 复用门（`reuse_policy`）只认这个，
    传旧值即可造出「库里存着一份旧口径报告」的场景（见 `test_stale_policy_*`）。
    """

    def __init__(self, origin="live", policy_version=SCOPE_POLICY_VERSION):
        self.calls = 0
        self.origin = origin
        self.policy_version = policy_version

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
            # 批 A③：复用门现在比**本次请求的口径三元组**，替身必须把它替的那一面补齐
            # （真实组装层就是从这里落的，见 `assemble_living_circle` 与 `scope.payload`）。
            # v7.2 片 1d：门上还有**第二把版本键**（评分口径 `cov-*`，比较对象是代码常量、
            # 不来自请求）⇒ 替身同样要带，缺它就是"静默未命中"（u3_1/u3_2/u3_4/u23/u32 首轮全量实测）。
            "caliber": {
                "scope_policy_version": self.policy_version,
                "coverage_caliber_version": COVERAGE_CALIBER_VERSION,
                "travel_mode": params.travel_mode,
                "sample_profile": params.sample_profile,
            },
        }


def _live(payload: dict) -> dict:
    """给手工落缓存的 live 载荷盖上**当前两把口径版本**（唯一实现见 `conftest.live_payload`）。

    复用门 `report_contract.reuse_policy` 只认**同时**带 `caliber.scope_policy_version`（判盲 `ev-*`）
    与 `caliber.coverage_caliber_version`（评分 `cov-*`）的 live 报告
    —— 旧口径报告不许冒充本次体检的答案。本文件的 U3/T2 用例测的是**键与命中机制**，
    所以必须喂当前版本才谈得上「命中」；两把版本门自身由文件末尾 `test_stale_policy_*`
    与 `test_stale_coverage_caliber_*` 专测（那里逐条只缺一把）。
    （不经 `peek`/`compute` 的纯 repository 用例不套此壳 —— 它们压根不过这道门。）
    """
    return live_payload(payload)


def _ds(repo=None, source=None, read_only=False):
    return CachingDataSource(
        source or CountingSource(),
        repo=repo or Repository(),
        data_mode="live",
        read_only=read_only,
    )


def test_u3_1_cache_hit_marks_served_from():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    r1 = asyncio.run(ds.compute(_shanghai()))
    assert "served_from" not in r1
    assert src.calls == 1
    r2 = asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 1  # 未再委托
    assert r2["served_from"] == "cache"
    assert "cached_at" in r2
    assert r2["data_origin"] == "live"  # 缓存不改变数据口径


def test_u3_2_miss_delegates_and_backfills():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 1
    asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 1  # 回填后命中
    assert asyncio.run(ds.compute(_shanghai()))["served_from"] == "cache"


def test_u3_3_expired_recomputes():
    repo = Repository(backend=MemoryCache(), default_ttl_s=0.05)
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_shanghai()))
    import time

    time.sleep(0.08)
    asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 2


def test_u3_4_key_isolation_between_payloads():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(_shanghai()))
    asyncio.run(ds.compute(_kaili()))
    assert src.calls == 2
    r1 = asyncio.run(ds.compute(_shanghai()))
    assert r1["scene"]["name"] == "上海市浦东新区陆家嘴"
    assert src.calls == 2  # 各自命中各自缓存


def test_u3_read_only_never_writes():
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src, read_only=True)
    asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 1
    # read_only：未命中也不回填（离线包装，只读 live 缓存）
    asyncio.run(ds.compute(_shanghai()))
    assert src.calls == 2


# ── T2 · 场景身份键三份实现一致性（B3 / I4）─────────────────────────

def test_t2_5_three_payload_implementations_agree():
    """同一场景在 Live 源 / 缓存装饰器 / 流水线三处必须算出同一个身份（去掉命名空间前缀）。

    三份独立实现只要有一份改格式，同场景就会写出两份缓存（重复采集 + 命中不了）。
    """
    p = _shanghai()
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
    p = _shanghai()
    # 流水线键与缓存装饰器键现在一致（都使用 caliber_payload_key）
    repo.cache_report("live", _scene_key(p), _live({"scene": {"name": "流水线命名空间键"}, "data_origin": "live"}))
    hit = asyncio.run(ds.compute(p))
    assert hit["scene"]["name"] == "流水线命名空间键"  # 现在能命中
    assert src.calls == 0  # 命中缓存，不调用源
    # 用装饰器自己的键回填则同样命中
    repo.cache_report("live", CachingDataSource._payload(p), _live({"scene": {"name": "缓存装饰器键"}, "data_origin": "live"}))
    assert asyncio.run(ds.compute(p))["scene"]["name"] == "缓存装饰器键"
    assert src.calls == 0


def test_u34_travel_mode_is_a_cache_key_dimension():
    """U34（种子改写锚点）：travel_mode **是**键维度（E3 行为变更的显式测试锚）。

    v4 之前键缺 travel_mode（riding/driving 与 walking 串同一份缓存）；E3 修复后
    5 参键必须能区分出行方式 —— 同一场景换出行方式 = 不同缓存条目（骑行/驾车可达区不同）。
    旧名 `test_t2_5_travel_mode_is_not_a_cache_key_dimension_yet` 断言「暂不是维度」，
    本版改写为正向断言，防止键维度回退。
    """
    p = _shanghai()
    key = CachingDataSource._payload(p)
    # 判据不是「键有几段」（旧写法 `len(split("|")) == 5`：facility 版本一并键就整文件连坐），
    # 而是「归并判据版本必须进键」—— 否则改了归并算法，旧缓存仍按同键命中报告里的老数字。
    if facility_merge_enabled():
        assert key.endswith(f"|facility:{FACILITY_RULE_VERSION}"), (
            f"设施归并开着却不在键里 ⇒ 口径变更后旧缓存继续命中，报告静默留旧值：{key!r}"
        )
    else:
        assert "facility:" not in key, (
            f"归并已关，键形必须与历史逐字一致（现存缓存要能继续命中，重采要烧检索配额）：{key!r}"
        )
    assert key.split("|")[4] == "walking", f"travel_mode 必须是键维度：{key!r}"
    for tm_a, tm_b in (("walking", "riding"), ("walking", "driving"), ("riding", "driving")):
        pa = CheckParams(scene_name=p.scene_name, center=p.center, study_radius_m=p.study_radius_m,
                         sample_profile=p.sample_profile, travel_mode=tm_a)
        pb = CheckParams(scene_name=p.scene_name, center=p.center, study_radius_m=p.study_radius_m,
                         sample_profile=p.sample_profile, travel_mode=tm_b)
        assert CachingDataSource._payload(pa) != CachingDataSource._payload(pb), \
            f"{tm_a}/{tm_b} 不得串同一缓存键"
    # 端到端：同场景同中心换出行方式 → **精确键不命中**（键含 travel_mode）。
    # 批 A③ 改的是后半句：邻近兜底现在也过口径比较 ⇒ **riding 的体检不会被一份 walking 报告答掉**。
    # 改前这里断的是 `served_from == "nearby_cache"`，那条断言的真实目的是"证明精确键没串"，
    # 而它顺手把跨档复用当成了可接受行为 —— 骑行档的可达区、证据面与步行档不是同一个问题
    # （`repository.find_recent_report_near` 只按中心点距离取最近一份，键前缀帮不上忙）。
    # 代价写在计划里：换档后那一次会重跑取证（约 32 次检索），换来的是对得上档位的答案。
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    asyncio.run(ds.compute(pa := CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734),
                                             study_radius_m=2500.0, sample_profile="standard", travel_mode="walking")))
    assert src.calls == 1
    pb = CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734),
                     study_radius_m=2500.0, sample_profile="standard", travel_mode="riding")
    hit_b = ds.peek(pb)
    assert hit_b is None, (
        "riding 的体检被 walking 的报告答掉了 —— 复用门没比口径（批 A③ 的判据）"
    )
    assert src.calls == 1, "本用例只验 peek 的判定，不该顺手重算"


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
    p = _shanghai()
    # compute 写缓存（键 = _payload）；peek 用同一键直接命中 → 共享键构建
    asyncio.run(ds.compute(p))
    assert src.calls == 1
    hit = ds.peek(p)
    assert hit is not None and hit["served_from"] == "cache"
    assert src.calls == 1  # peek 未触发新的 compute
    # 反向验证：手工以 `_payload` 为键落缓存，peek 必须命中（读路径唯一实现）
    repo2 = Repository()
    ds2 = _ds(repo2, CountingSource())
    repo2.cache_report("live", CachingDataSource._payload(p), _live({"scene": {"name": "手工键"}, "data_origin": "live"}))
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



# ── 判盲口径复用门（report_contract.reuse_policy）───────────────────
# 上面每条 U3/T2 都靠 `_live()` 喂当前版本才谈得上「命中」。本段反向证明**门真的有牙**：
# 缺了它，「给每个 stub 补一个字段」这件事可以悄悄把门架空而无人判红。


def test_stale_policy_version_forces_recompute():
    """库里存着旧口径 live 报告 → peek 视为未命中、compute 重算，不冒充本次答案。"""
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p = _shanghai()
    repo.cache_report("live", CachingDataSource._payload(p), {
        "scene": {"name": "旧口径", "center": list(p.center)},
        "data_origin": "live",
        "caliber": {"scope_policy_version": "ev-0"},
    })
    assert ds.peek(p) is None
    got = asyncio.run(ds.compute(p))
    assert src.calls == 1, "旧口径报告被直接吐给用户了 —— 门没牙"
    assert got["scene"]["name"] == p.scene_name  # 拿的是新结果，不是「旧口径」


def test_stale_coverage_caliber_forces_recompute():
    """判盲口径是当前的、**只有评分口径那把缺** ⇒ 照样不许复用（v7.2 片 1d 第二把键）。

    与上一条成对：那条拦「证据域变了」，这条拦「同样的点位算出来的分变了」。
    缺这条会怎样：改造后第一次体检的新分数落库，第二次体检从库里捞出**改造前**那份
    （演示数据上就是教育 88.6 / 总分 68.7 那一组）当本次答案上屏，页面看不出它是旧分子算的。
    形状刻意取「缺键」而不是「值不同」：存量 30 份报告全是缺键那一形（计划 §六 的主路径），
    而"值不同"那一形由 `test_subkind_caliber.py` 的 T8 逐理由钉着。
    """
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p = _shanghai()
    stale = live_payload({
        "scene": {"name": "旧评分口径", "center": list(p.center)},
        "data_origin": "live",
    })
    stale["caliber"].pop("coverage_caliber_version")   # 判盲那把留着 ⇒ 只有第二根轴缺
    repo.cache_report("live", CachingDataSource._payload(p), stale)
    assert ds.peek(p) is None
    got = asyncio.run(ds.compute(p))
    assert src.calls == 1, "缺评分口径声明的报告被直接吐给用户了 —— 第二把门没牙"
    assert got["scene"]["name"] == p.scene_name  # 拿的是新结果，不是「旧评分口径」那份


def test_live_report_without_any_caliber_is_not_reused():
    """存量报告（连 `caliber` 都没有）同样被拦 —— D-4 的「拦复用」拦的正是它们。"""
    repo = Repository()
    ds = _ds(repo, CountingSource())
    p = _shanghai()
    repo.cache_report("live", CachingDataSource._payload(p), {
        "scene": {"name": "存量", "center": list(p.center)}, "data_origin": "live",
    })
    assert ds.peek(p) is None


def test_nearby_cache_hit_is_also_gated():
    """邻近 500m 分支必须同样过门 —— 这条正是「把版本加进缓存键」拦不住的那条路。

    `find_recent_report_near` 走**键前缀扫 + 从值里读 `scene.center`**，
    键里加分段对它完全无效；只有读侧谓词拦得住。
    """
    repo = Repository()
    ds = _ds(repo, CountingSource())
    p = _shanghai()
    near = (p.center[0] + 0.001, p.center[1])  # 东 ~110m，落在 500m 半径内
    repo.cache_report("live", "seed-near-stale", {
        "scene": {"name": "邻近旧口径", "center": list(near)},
        "data_origin": "live",
        "caliber": {"scope_policy_version": "ev-0"},
    })
    assert repo.find_recent_report_near("live", p.center, 500.0) is not None  # 仓储层确实找得到
    assert ds.peek(p) is None, "邻近分支绕过了复用门"


@pytest.mark.parametrize("mode", ["fixture", "fixture_sample", "offline"])
def test_non_live_modes_are_not_version_gated(mode):
    """演示/夹具/offline 不受版本约束 —— 否则「演示」开关会因为本次改动直接没数据。"""
    repo = Repository()
    ds = CachingDataSource(CountingSource(), repo=repo, data_mode=mode)
    p = _shanghai()
    repo.cache_report(mode, CachingDataSource._payload(p), {
        "scene": {"name": "演示数据", "center": list(p.center)}, "data_origin": mode,
    })
    hit = ds.peek(p)
    assert hit is not None and hit["scene"]["name"] == "演示数据"


# ── 批 A③ · 复用门要比**本次请求的口径三元组** ──────────────────────

def test_reuse_gate_requires_the_request_caliber_triple():
    """主判据：邻近命中的三份口径声明逐个与本次请求相等，缺一项都不给复用。

    四条子判据各自精确到失败种类（`reason` 必须点名是哪一项不符，不是"都返回 False"）：
      ① 同档同参 ⇒ **仍可**复用（邻近兜底是 D9/O1 的设计，门不许做成零复用）；
      ② 换 travel_mode / 换 sample_profile / 换 study_radius ⇒ 三种各自不可复用；
      ③ 载荷缺任一项声明 ⇒ 不可复用，理由是「不能猜口径」而不是「值不符」；
      ④ 调用方没给本次口径 ⇒ fail-closed（live 载荷一律不可复用，不"跳过比较"）。
    另钉一条形状细节：payload 把半径落成 `int`、请求侧是 `float`，归一后必须算同一个档
    —— 逐字串比会让「当前编排刚产出的报告」被自己拦下。
    """
    from app.living_circle.report_contract import reuse_policy

    base = {
        "data_origin": "live",
        "scene": {"name": "凯里老街", "center": [107.9758, 26.5734], "study_radius_m": 2500},
        "caliber": {"scope_policy_version": SCOPE_POLICY_VERSION,
                    "coverage_caliber_version": COVERAGE_CALIBER_VERSION,
                    "travel_mode": "walking", "sample_profile": "standard"},
    }
    # `wanted` **刻意只有三把**（本次请求的三元组）：评分口径那把不来自请求、由门自己拿代码常量比。
    # 10-01 全量实测：曾经把它塞进 `wanted` 并要求读 `wanted[...]` ⇒ 这种手写三元组的调用方当场 KeyError。
    wanted = {"travel_mode": "walking", "sample_profile": "standard", "study_radius_m": 2500.0}
    assert reuse_policy(base, wanted) == (True, "")
    assert reuse_policy(
        {**base, "scene": dict(base["scene"], study_radius_m=2500.0)}, wanted
    ) == (True, ""), "半径 2500（落盘形）与 2500.0（请求形）被判成两个档 ⇒ 自家产物拦自家"

    for field, value, label in (("travel_mode", "riding", "出行方式"),
                                ("sample_profile", "precise", "采样档"),
                                ("study_radius_m", 5000.0, "研究半径")):
        ok, why = reuse_policy(base, dict(wanted, **{field: value}))
        assert not ok, f"{field} 换成 {value} 后仍被判可复用 ⇒ 门没比这一项"
        assert label in why, f"失败种类没点名：{why!r}（期望含 {label!r}）"

    for spot, key in (("caliber", "travel_mode"), ("caliber", "sample_profile"),
                      ("scene", "study_radius_m")):
        stripped = {**base, spot: {k: v for k, v in base[spot].items() if k != key}}
        ok, why = reuse_policy(stripped, wanted)
        assert not ok and "不能猜口径" in why, (
            f"缺 {spot}.{key} 的载荷得到 {why!r} —— 邻近复用把没声明当成了相符"
        )

    ok, why = reuse_policy(base, None)
    assert not ok and "未收到本次请求的口径" in why, f"wanted 缺失时门放行了：{why!r}"


def test_reuse_gate_does_not_reject_a_fresh_product_of_itself():
    """不变式：**当前编排刚产出的 live 报告，同参第二次必须命中缓存**（零新增调用）。

    这条是批 A③ 落地时用来否掉原方案的判据。原稿写的是「`unknown/inside` 超阈值 或
    `evidence_complete=false` ⇒ 不可复用」，而线上唯一那份带 ev-1 的存量报告实测就是
    `evidence_complete=false`、share=21/99=21.2% —— 那条规则拦的不是旧答案，是**当前编排
    刚跑出来的那份**，后果是每次体检都被推去重跑取证（`U22/U39` 的"二次命中零新增调用"
    当场就红，真实配额也重复花）。
    复用门要回答的是「换我重跑一次，答案会不会不同」，不是「这份结论厚不厚」；
    证据面薄的账由评分侧外推封顶（`scoring.JUDGE_SHARE_FLOOR`）与 `confidence=limited` 负责。
    """
    repo = Repository()
    src = CountingSource()
    ds = _ds(repo, src)
    p = _shanghai()
    asyncio.run(ds.compute(p))
    assert src.calls == 1
    hit = ds.peek(p)
    assert hit is not None and hit["served_from"] == "cache", (
        "刚产出的报告第二次同参请求没命中 ⇒ 复用门把自己那一份也拦下了"
    )
    assert src.calls == 1, "同参二次不该重跑计算源"
