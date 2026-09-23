"""百度调用预算唯一事实源（rev3 §四F / v3 §3.3 / v5 §B）。

职责边界（架构分治，rev3 §二）：
  - **只定义预算怎么算**（纯函数），是 `total_budget / mat_budget / poi_budget /
    poi_page_depth / max_matrix_origins / total_calls_hard_ceiling` 的**唯一归属**。
  - 其他模块**不得重复定义预算公式**——只消费本模块产出的数值/分配快照。
  - 预算口径：免费档按「QPS × 体检窗口秒数 × 负载安全系数」推导，付费/商用档经
    `.env` 放大 `baidu_max_qps` 后自动外推（写入即外推，无需改代码）。
"""
from __future__ import annotations

from math import floor

# 体检预算窗口（秒）：单次体检默认采集时间窗口。
BUDGET_WINDOW_S = 20.0
# 负载安全系数：留给重试/抖动/边界，避免贴满 QPS 打爆.
LOAD_FACTOR = 0.7

# 熔断头寸：地理编码/逆地理/坐标转换等 intake 阶段调用（v5 D2：42 为矩阵+POI 精度预算，
# 熔断定位是防失控循环，须给 intake 留 3 次头寸）。
INTAKE_MARGIN = 3

# 分块/翻页异常时的保守页深默认（非 0、非除零产物）。
_DEFAULT_PAGE_DEPTH = 1

# 页深 clamp 上下限
PAGE_DEPTH_MIN = 1
PAGE_DEPTH_MAX = 3

_MATRIX_RATIO = 0.35  # 全局预算 → 等时圈矩阵的分配占比


def _qps() -> float:
    """当前 AK 档位的 QPS（个人免费档默认 3）。"""
    from app.core.config import get_settings

    s = get_settings()
    return max(float(s.baidu_max_qps or 3.0), 1.0)


def total_budget() -> int:
    """单次体检全局百度调用预算（免费档 = round(3×20×0.7) = 42）。"""
    return round(_qps() * BUDGET_WINDOW_S * LOAD_FACTOR)


def mat_budget() -> int:
    """预算中划给等时圈矩阵的部分（免费档 round(42×0.35)=15）。"""
    return round(total_budget() * _MATRIX_RATIO)


def poi_budget() -> int:
    """预算划给 POI 采集的部分（免费档 42−15=27）。"""
    return max(0, total_budget() - mat_budget())


def quota_budget() -> tuple[int, int]:
    """一次性返回 (mat, poi) 预算分区（免费档 (15, 27)），供调用方取分配快照。"""
    return mat_budget(), poi_budget()


# 兼容别名：部分调用方/文档以 `budget_partition` 引用同一分区函数。
budget_partition = quota_budget


def max_matrix_origins(chunk: int) -> int:
    """等时圈矩阵的**最大采样点数** = 矩阵预算 × 分块上限（免费档 15×25=375）。

    语义：把整个矩阵预算花在**一批批量算路上**，ceil(点/分块) 恰好 ≤ mat_budget。
    调用方（isochrone 预算感知采样）把采样点数压到该值以下，即保证不超预算。
    ``chunk`` 从 `get_caliber(travel_mode).api.chunk` 读取（见 `max_matrix_origins_for`）。
    """
    return mat_budget() * max(int(chunk or 0), 1)


def max_matrix_origins_for(travel_mode: str) -> int:
    """按出行方式口径的矩阵采样上限——**唯一 chunk 读取点**（v5 I2）。

    消除三处各自从 caliber 读 chunk 的派生漂移（pipeline / LiveDataSource /
    refine_live_with_profile 统一走本助手）。默认兜底 chunk=25（manifest 缺失时）。
    """
    from app.living_circle.caliber import get_caliber

    cal = get_caliber(travel_mode)
    api = cal.api
    return max_matrix_origins(api.chunk if api else 25)


def total_calls_hard_ceiling() -> int:
    """单次体检**全局调用熔断上限**（免费档 42+3=45）。

    42 是矩阵+POI 的精度预算；intake 阶段（地理编码/逆地理/坐标转换）还需头寸。
    熔断定位是**防失控循环**（扩词/翻页空转），不是替代分区预算。
    """
    return total_budget() + INTAKE_MARGIN


def poi_page_depth(n_terms: int, poi_budget: Optional[int] = None) -> int:
    """POI 每关键词页深：由预算导出，clamp 到 [1,3]。

    - 免费档 floor(27/22)=1；词少/预算足时自动回升（付费档获益）；
    - 预算为 0/负 → 保守页深 1；词数为 0 → 避免除零，回退页深 1；
    - 预算远大于词数 → clamp 上限 3，杜绝爆表。
    """
    budget = poi_budget if poi_budget is not None else poi_budget()
    if n_terms <= 0 or budget <= 0:
        return _DEFAULT_PAGE_DEPTH
    return max(PAGE_DEPTH_MIN, min(PAGE_DEPTH_MAX, floor(budget / n_terms)))