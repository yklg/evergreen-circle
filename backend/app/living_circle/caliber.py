"""口径单一事实源（R1）：按出行方式分档的测时与圈层定义。

所有模块不得再硬编码速度 / 绕行系数 / 研究半径 / 圈层分钟数；统一从本模块取值。
口径变更只改这里，其余模块通过导入常量或调用派生函数获得值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

# ── 第三把口径版本键：可达口径 `rc-*`（笔 3-B）─────────────────────────────────
#
# 三把键各管一根轴，谁也不许替谁说话（前两根的来历见 `scope.SCOPE_POLICY_VERSION`
# 与 `category_rule.COVERAGE_CALIBER_VERSION`）：
#   `ev-*`   判盲口径 —— 证据域 / 判定半径 / 逐格台账怎么算（改它 ⇒ 盲区数与清单变）
#   `cov-*`  评分口径 —— 覆盖度的分子是"点数"还是"门槛项"（改它 ⇒ 覆盖维与总分变）
#   `rc-*`   可达口径 —— 实测耗时场**怎么被解释**：本次标定出的常态绕行系数与残差耗时
#
# 为什么第三根独立成键而不并进 `ev-*`：残差耗时回答的是"同一份实测场里，哪儿比同城常态
# 更难达"，它既不改判定域也不改分子，只改耗时场派生出的解释。并进任何一根，版本记录就又
# 在撒谎 —— `cov-1` 那次正是因为评分口径借了判盲的键表达，两份分母不同的报告被当成可比。
#
# `rc-1` = 在 `sampling` 段内发射 `detour`（唯一生产者 `isochrone.detour_residual`：
# 声明值 vs 本次实测中位数、隐含系数 p10/p90、入样点数与三类剔除计数、残差分钟分位）。
# ⚠️ 版本号与键集是**同一次发布的两半**：声明 `rc-1` 却没有 `sampling.detour` ⇒ 读侧契约
#    （`report_contract`）直接报错，半吊子发布不许过。
# ⚠️ 本版本**还不碰分数**（`scoring.reach_dim` 仍只按实测分钟算）⇒ 存量报告重算只补键、
#    不改读数。分数换代是下一档（届时 `rc-2`：措辞表加一行 + 复用门加一行 + 夹具两项，
#    组合式措辞自 3-前置 起已把加轴的成本压到这里）。
REACH_CALIBER_VERSION = "rc-1"


@dataclass(frozen=True)
class ApiCapability:
    """百度 API 能力描述（探针回填，非硬编码）。"""
    matrix_path: str          # e.g. "/routematrix/v2/walking"
    chunk: int                # 单次批量上限
    fallback_path: str        # 单点兜底路径
    restrictions_field: str   # 不可达判定字段名


@dataclass(frozen=True)
class ReachCaliber:
    """某出行方式的口径定义（唯一事实源）。

    - speed / detour_k / study_radius / iso_minutes：政策与文献依据；
    - fine_band：由最内圈半径派生（防「最内圈网格坍缩」复发），非硬编码；
    - api：实测能力（探针写入 manifest.json 后加载）；
    - basis：政策原文出处（答辩举证用）；
    - measured：是否经真实路网测时验证（True=步行，False=近似口径）；
    - blind_radius_m：盲区判定半径（「多大范围内没有该类设施 ⇒ 该格判盲」），
      是判盲与取证共用的那把尺，见 `scope.BLIND_RADIUS_M` 的兼容说明。
    """
    travel_mode: str
    speed_m_per_min: float
    detour_k: float
    study_radius_m: int
    iso_minutes: Tuple[int, ...] = (5, 10, 15, 20)
    reach_full_min: float = 20.0  # 可达性满分阈值（= 最外圈分钟数）
    api: Optional[ApiCapability] = None
    basis: str = ""
    measured: bool = False
    # 盲区判定半径的**住所**（生活圈片 1b）。此前它只住在 `scope.BLIND_RADIUS_M` 一个模块
    # 常量上，却有 21 条取值途径（15 个函数默认值 + 5 处体内硬用 + 1 处发射进报告）——
    # 默认值在 def 期就被焊进函数对象，所以"改源头"不会让默认路径跟着改。搬进口径对象后，
    # 半径与 speed/detour_k/study_radius 同族，可随出行方式分档。
    # ⚠️ 三个档位今天**同值**，这是现状不是巧合的省略：判盲半径分档属于阶段 3-5 的政策决定，
    # 本片只把住所搬对、不改任何一格的结论（验收线 = 默认路径逐字节不变）。
    blind_radius_m: float = 1000.0
    # 口径对比档（笔 B）：把**同一份实测耗时场**按文献里的另一个阈值再多切一条等值线，
    # 用来让"满分线 20min、四档 5/10/15/20"这把**我们选的**尺与文献那把尺并排看得见。
    # ⚠️ 它不是"第五档等值线"：四档 `iso_minutes` 与 `isochrones` 的长度是硬契约（配色表、
    #    面积单调性、前端图例都按四档钉），这条环单独发在 `living_circle.iso_compare` 里。
    #    它也只作**口径对比**，不作任何人群能力断言 —— 文献量的是群体有效窗口，
    #    不是某个具体居民能走多远。
    # 只有步行档给值：8min 出自「基准 80 m/min 是健康成年人、高龄有效步行窗口可能仅 5–8min」
    # 的文献，同一个数换到骑行/驾车档量的是完全不同的东西 ⇒ 那两档 `None` ⇒ 不发环、不渲染。
    iso_compare_min: Optional[float] = None

    @property
    def innermost_radius_m(self) -> float:
        """最内圈理论半径（直线距离模型下）。"""
        return self.iso_minutes[0] * self.speed_m_per_min / self.detour_k

    @property
    def reach_radius_bound_m(self) -> float:
        """可达区半径的**理论下界**（直线距离模型：分钟 × 速度 ÷ 绕行系数）。

        不是可达区的实际半径 —— 实际半径由路网实测的等时圈决定（通常 ≥ 本值，
        因为路网绕行比 ``detour_k`` 更曲折）。它的用途是**量级校验**：
        把实测外接圆与这个下界比对，若实测值反而更小，说明测时或圈层提取出了问题
        （``SpatialScope`` 与本值一起举证，让「圈为什么这么小」在报告里可查）。
        """
        return self.reach_full_min * self.speed_m_per_min / self.detour_k

    @property
    def fine_band(self) -> Tuple[float, float]:
        """边界带加密区间：从最内圈半径起算，到研究半径止。

        派生而非硬编码 → 换 mode 或调 speed/detour 时自动适配，根治 P0 坍缩。
        """
        r_inner = self.innermost_radius_m
        return (max(r_inner, 400.0), float(self.study_radius_m))

    @property
    def grid_n_for_standard(self) -> int:
        """标准档位插值格点数：保证 step ≤ 最内圈半径/4。

        step = 2*R/(n-1) ≤ r_inner/4  →  n ≥ 8*R/r_inner + 1
        """
        import math
        r_inner = self.innermost_radius_m
        if r_inner <= 0:
            return 61  # 兜底
        n = math.ceil(8 * self.study_radius_m / r_inner) + 1
        return max(n, 41)  # 不低于 quick 档位


# ── 默认口径表（步行有政策依据，骑行/驾车为近似口径，待探针验证）───────────

# 口径对比环的依据原文（笔 B）。措辞是**纪律的一部分**，不是装饰：
# ① 主语必须是"口径/阈值"，不能是"老年人能走多远"——文献量的是群体有效窗口，
#    把它写成对具体社区/具体居民的能力断言，就违反了"无证据不立论"；
# ② 必须写出"同一份实测耗时场按该阈值重切"，让读者知道这不是第二次测量、也没有第二次测量；
# ③ 标明出处与取区间保守侧（5–8min ⇒ 取 8min）这一选择本身。
ISO_COMPARE_BASIS = (
    "口径对照（非第五档）：文献指出 80 m/min 的基准步速是健康成年人，高龄有效步行窗口"
    "可能仅 5–8min ⇒ 此处取区间保守侧 8min，把**同一份实测耗时场**重切一条等值线。"
    "它是两把尺的对比，不构成对任何具体个体步行能力的判断。"
)

DEFAULT_CALIBERS: Dict[str, ReachCaliber] = {
    "walking": ReachCaliber(
        travel_mode="walking",
        speed_m_per_min=80.0,  # R7: 75→80，落在政策 0.8–1.2km 上沿
        detour_k=1.3,
        study_radius_m=2500,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        # 口径对比档：只有步行给值（依据与措辞纪律见 `ISO_COMPARE_BASIS`）。骑行/驾车留 None。
        iso_compare_min=8.0,
        basis="商务部 2021《城市一刻钟便民生活圈建设意见》「步行约15分钟的服务半径」；"
              "《城市规划》2022.5 实测步行 15min ≈ 0.8–1.2km",
        measured=True,
        api=ApiCapability(
            matrix_path="/routematrix/v2/walking",
            chunk=25,
            fallback_path="/directionlite/v1/walking",
            restrictions_field="restrictions_status",
        ),
    ),
    "riding": ReachCaliber(
        travel_mode="riding",
        speed_m_per_min=200.0,  # 暂定 12km/h，待探针 P5 反算校准
        detour_k=1.2,
        study_radius_m=5000,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        basis="近似口径（无官方政策原文），速度参考共享单车平均巡航速度",
        measured=False,
        api=ApiCapability(
            matrix_path="/routematrix/v2/riding",
            chunk=25,
            fallback_path="/directionlite/v1/riding",
            restrictions_field="restrictions_status",
        ),
    ),
    "driving": ReachCaliber(
        travel_mode="driving",
        speed_m_per_min=500.0,  # 暂定 30km/h，待探针 P5 反算校准
        detour_k=1.15,
        study_radius_m=9000,
        iso_minutes=(5, 10, 15, 20),
        reach_full_min=20.0,
        basis="近似口径（无官方政策原文），速度参考城市道路平均车速",
        measured=False,
        api=ApiCapability(
            matrix_path="/routematrix/v2/driving",
            chunk=25,
            fallback_path="/direction/v2/driving",
            restrictions_field="restrictions_status",
        ),
    ),
}


def _load_manifest() -> Dict[str, Any]:
    """加载探针能力清单（若存在）。"""
    import json
    from pathlib import Path
    
    manifest_path = Path(__file__).parent / "capability_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _apply_manifest_caliber(caliber: ReachCaliber, manifest: Dict[str, Any]) -> ReachCaliber:
    """用 manifest 实测值覆盖 caliber 的 api 字段。"""
    cap = manifest.get("capacity", {}).get(caliber.travel_mode, {})
    if not cap:
        return caliber
    
    # 从 manifest 读取 chunk 上限
    chunk = cap.get("chunk_max_origins", caliber.api.chunk if caliber.api else 25)
    
    # 构建新的 ApiCapability
    api = caliber.api
    if api:
        api = ApiCapability(
            matrix_path=api.matrix_path,
            chunk=chunk,
            fallback_path=api.fallback_path,
            restrictions_field=api.restrictions_field,
        )
    
    # 返回更新后的 caliber（measured 标记为 True 若有实测数据）
    measured = cap.get("measured", caliber.measured)
    # **只覆盖这两个字段，其余一律原样带走** —— 这里曾是逐字段手抄的 `ReachCaliber(...)`
    # 重建清单，漏抄一行不会报错、只会把那个字段悄悄打回 dataclass 默认值：
    # `blind_radius_m` 当年就是这么漏的（默认值恰好等于原值 ⇒ 无人发现），而 10-06 加
    # `iso_compare_min` 时**又漏了一次**（步行档明明写了 8.0，`get_caliber` 拿回来却是 None）。
    # 两次同形 ⇒ 这是结构问题，不是手抖：清单的正确长度永远是"全部字段"，而人只记得住改过的
    # 那两个。`dataclasses.replace` 让"新增字段自动带走"成为机制而非纪律。
    # 判据：`tests/test_interpolation_form` 同批新增的 `test_get_caliber_keeps_every_field`
    # 逐字段对比 `DEFAULT_CALIBERS` 与 `get_caliber` 的读数（覆盖路径非空时才有意义，
    # 而装了 manifest 的仓里它总是非空）。
    return replace(caliber, api=api, measured=measured)


# 加载 manifest 并应用实测值
_MANIFEST = _load_manifest()
if _MANIFEST:
    for mode in list(DEFAULT_CALIBERS.keys()):
        DEFAULT_CALIBERS[mode] = _apply_manifest_caliber(DEFAULT_CALIBERS[mode], _MANIFEST)


def get_caliber(travel_mode: str = "walking") -> ReachCaliber:
    """获取指定出行方式的口径定义（默认步行）。"""
    if travel_mode not in DEFAULT_CALIBERS:
        raise ValueError(
            f"未知出行方式: {travel_mode!r}，可用值: {list(DEFAULT_CALIBERS.keys())}"
        )
    return DEFAULT_CALIBERS[travel_mode]


def all_travel_modes() -> List[str]:
    """返回所有已定义的出行方式列表。"""
    return list(DEFAULT_CALIBERS.keys())


# ── 设施实体归并开关 ─────────────────────────────────────────
# 归并只在**采集出口**发生，而采集要烧百度检索配额 ⇒ 关掉它 = 退回旧缓存键 + 旧判据，
# 现存缓存继续命中、不触发重采。默认开启（这是修 bug，不是实验特性）；
# 需要回退时设环境变量 `LC_FACILITY_MERGE=off`。
FACILITY_MERGE_ENV = "LC_FACILITY_MERGE"
_OFF_VALUES = frozenset({"off", "0", "false", "no"})


def facility_merge_enabled() -> bool:
    """设施实体归并是否生效（只读，读环境变量）。"""
    raw = os.environ.get(FACILITY_MERGE_ENV, "on").strip().lower()
    return raw not in _OFF_VALUES


def caliber_payload_key(
    scene_name: str,
    center: Tuple[float, float],
    study_radius_m: int,
    sample_profile: str,
    travel_mode: str = "walking",
) -> str:
    """统一的场景身份键（B3/R6：纳入 travel_mode，防串缓存）。

    三份实现（LiveDataSource / CachingDataSource / pipeline）收敛到此函数，
    不再各自拼接字符串。

    设施归并开启时把**判据版本**并进键（阶段「已定口径 5」）：口径一变旧缓存自然
    miss，避免「新算法读到老数字」。关闭时键形保持与历史完全一致，让现存缓存继续
    命中 —— 这正是开关存在的理由：归并生效必须重新联网采集，而重采要烧检索配额，
    不能让一次口径变更在用户打开页面时替他把钱花了。
    """
    c = center or (0.0, 0.0)
    # 函数内 import：本模块是口径基座，不在模块级依赖判表（与 `poi_collector._dedupe`
    # 委托 `poi`、`data_source.load_poi` 委托 `poi_collector` 的既有写法一致）。
    from app.living_circle.facility_rule import FACILITY_RULE_VERSION

    facility = f"|facility:{FACILITY_RULE_VERSION}" if facility_merge_enabled() else ""
    return (
        f"{scene_name}|{c[0]:.6f},{c[1]:.6f}|"
        f"{int(study_radius_m)}|{sample_profile}|{travel_mode}{facility}"
    )
