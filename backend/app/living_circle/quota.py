"""百度调用预算唯一事实源（rev3 §四F / v3 §3.3 / v5 §B）。

职责边界（架构分治，rev3 §二）：
  - **只定义预算怎么算**（纯函数），是 `total_budget / mat_budget_for / poi_budget_for /
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

# 取证回合窗口（秒）—— 计划 v5.4 闭 P0-5 的「新开一格」，独立复审更正后的形状。
# ⚠️ **`BUDGET_WINDOW_S` 一动不动**是这条闭法的核心，不是巧合：矩阵闸 `_matrix_share_ceil()`、
# 首轮 `poi_budget_for()`、熔断上限三处**同吃** `total_budget()`，一抬窗口就把三处一起推漂，
# 要「把闸锁回 42」只能把 42 抄成硬编码常量 = 第二个事实源（本仓反复出事的正是这个形状），
# 且 `tests/test_quota.py:37` 的 `mat + poi == total` 不变量会九个组合全红。
# 所以扩容额度另立一格：只进熔断上限，不进首轮分区 ⇒ 首轮仍是 (11, 31)、驾车闸仍是 15
# ⇒ **等时圈几何零变化**这条守得住。
# 档位 11→16 由计划 v6.1 拍板（第六轮复审复算出来的数）：一轮按需扩容在步行 ±2500m 形状下
# 需要 20×1(药店) + 4×3(市场全词) = **32 次**，11 秒窗口只给 23 次 ⇒ 骑行/驾车/precise 档
# 恒带 `anchors_dropped`（恰是最需要扩容的那两档）。16 秒给 `round(3×16×0.7)=34` 次，一轮跑得满。
# 代价是墙钟（按第 0 步实测 0.326 秒/次）：一次体检的真实用量从「矩阵 11 + 首轮 31 = 42 次
# ≈13.7 秒」涨到「再加一回合 32 次 = 74 次 ≈24 秒」，**用户可感 = 进度条多约 10 秒**；
# 熔断上限随之从 42+23+3=68 抬到 42+34+3=79（上限是防失控循环的闸，不等于实际用量）。
FORENSIC_WINDOW_S = 16.0

# 分块/翻页异常时的保守页深默认（非 0、非除零产物）。
_DEFAULT_PAGE_DEPTH = 1

# 页深 clamp 上下限
PAGE_DEPTH_MIN = 1
PAGE_DEPTH_MAX = 3


# ── 分区方向已翻转（计划 v4 阶段 3 / D5）─────────────────────────
# 旧写法是 `mat_budget = round(total × 0.35)` 再 `max_matrix_origins = mat × chunk` ——
# 「能跑多少算多少」：占比是一个**没有任何被检对象**的魔数，而它同时管着两个互不相干的
# 量（矩阵点数与 POI 取证词表），这就是 P0-3 的耦合根因。
# 正确方向是 **规格 → 需求点数 → 所需调用**：采样规格（档位 + 出行方式）决定要点多少个点，
# 点数除以分块上限就是矩阵该占的额度。实测（走 `matrix_demand_points`，即真造一遍再数）：
#   quick   粗 400 全域         步行 149 点 / 2 次
#   standard 粗 400 + 边界带细 150  步行 1049 点 / 11 次  驾车 12625 点 / 505 次
#   precise 粗 300 + 带细 120      步行 1684 点 / 17 次
# 计划里那组「≈353 点 / 15 次」是按**窄环带**估的，真实 `fine_band` 几乎铺满整个圆盘，
# 需求大出一个量级 —— 记在这里，因为它是下一条那个闸存在的唯一理由。
_MATRIX_SHARE_CEIL = 0.35  # 矩阵可占的**上限**占比（不是分配比例，见 `mat_budget_for`）


def _matrix_share_ceil() -> int:
    """矩阵额度硬闸 = round(total × 0.35)（免费档 15，付费档 140→49）。

    ⚠️ 这个常量的角色变了：旧代码里它是**分配**（矩阵固定拿 35%，用不完也占着）；
    现在只是**闸**（规格需求超过 35% 才削平）。留闸的理由是实测的驾车档：
    `standard/驾车` 需求 505 次，若不设闸就是「矩阵吃满 42、取证 0 次」——
    计划风险 2b 明写「别默认两个都要」，而此刻没有实测墙钟替我们选边，
    所以先保证**取证永不被清零**（用户报的「检索随机性」主体就是取证饿死）。
    真正的动态让渡属阶段 5 的回合配额（每回合边际配额 + 全局剩余）。
    """
    return round(total_budget() * _MATRIX_SHARE_CEIL)


def _qps() -> float:
    """当前 AK 档位的 QPS（个人免费档默认 3）。"""
    from app.core.config import get_settings

    s = get_settings()
    return max(float(s.baidu_max_qps or 3.0), 1.0)


def total_budget() -> int:
    """单次体检全局百度调用预算（免费档 = round(3×20×0.7) = 42）。"""
    return round(_qps() * BUDGET_WINDOW_S * LOAD_FACTOR)


# ── 分区方向：规格 → 需求点数 → 所需调用（D5）。翻转的理由与那份额闸的角色，
#    都写在文件头 `_MATRIX_SHARE_CEIL` 那一段，此处不留第二份叙述。
def _chunk_of(travel_mode: str) -> int:
    """批量矩阵的**分块上限** —— 全模块唯一 chunk 读取点（v5 I2 的原纪律）。

    `max(…, 1)` 是防 0/负值把上限坍缩成「一个点都采不了」：manifest 缺失时
    `api.chunk` 可能是 0，那也至少得允许逐点算路。
    """
    from app.living_circle.caliber import get_caliber

    cal = get_caliber(travel_mode)
    return max(int(cal.api.chunk if cal.api else 0) or 0, 1)


def matrix_calls_for(points: int, travel_mode: str) -> int:
    """需求点数 → 矩阵调用数 = ceil(点数 / 分块上限)。"""
    return -(-max(int(points), 0) // _chunk_of(travel_mode))   # 向上取整除法，不引 math


def mat_budget_for(sample_profile: str, travel_mode: str) -> int:
    """按**采样规格**反向导出的矩阵额度 = min(规格需求, 份额闸)（免费档 standard/步行 = 11）。

    两个规格参数**都不留默认值**：额度是从规格算出来的，让漏传在签名上就报错，
    而不是悄悄按「standard + 步行」去算一个驾车档的预算（同 `poi_page_depth` 的教训）。

    与旧 `mat_budget()` 的区别不在数值，在**谁来定**：旧值是一个与档位、出行方式都无关的
    15，步行 standard 实际只用 11 次（余下 4 次凭空蒸发，谁也没得到），驾车 standard 需求
    505 次也只见 15 次。现在额度由规格算出，只在规格越过后被份额闸削平（削平即如实降级：
    `max_points` 变小 ⇒ `sample_plan` 丢边界加密带并标 `degraded`，不悄悄减点数）。
    """
    from app.living_circle.isochrone import matrix_demand_points

    demand = matrix_calls_for(matrix_demand_points(sample_profile, travel_mode), travel_mode)
    return min(demand, _matrix_share_ceil())


def poi_budget_for(mat_calls: int) -> int:
    """剩下的都归取证（免费档 standard/步行 = 42−11 = 31；驾车 = 42−15 = 27 与旧值同）。"""
    return max(0, total_budget() - int(mat_calls))


def quota_budget(sample_profile: str, travel_mode: str) -> tuple[int, int]:
    """一次性返回 (mat, poi) 分区快照 —— 分区只有这一个出口。"""
    mat = mat_budget_for(sample_profile, travel_mode)
    return mat, poi_budget_for(mat)


def max_matrix_origins(sample_profile: str, travel_mode: str) -> int:
    """交给采样器的 `max_points` 上限 = 矩阵额度 × 分块上限（**唯一 chunk 读取点**）。

    与旧同名函数的区别：旧值 = 一个比例 × 全局预算 × chunk（与规格无关），
    新值 = 规格需求向上取整到整块 ⇒ 正常档位下不触发降级，预算真不够时才降规格。
    """
    return mat_budget_for(sample_profile, travel_mode) * _chunk_of(travel_mode)


def forensic_budget() -> int:
    """扩容取证回合的**独立额度格**（免费档 = round(3×16×0.7) = 34）。

    它与 `total_budget()` 不相加也不互斥于分区：首轮采集照旧只吃 `poi_budget_for(mat)`，
    这一格专门付给「判盲之后按未覆盖格补锚点」那几轮（计划阶段 5 的 `collect_triad_evidence`）。
    为什么要单列而不是把 42 摊大：摊大 `total` 会同时移动矩阵闸与首轮 poi 的基准（见
    `FORENSIC_WINDOW_S` 上方那段），而这三处各自有测试钉着 —— 一格新额度只该多一个数。
    档位取 16 而不是 11 是**算出来的**：一轮按需扩容在步行 ±2500m 形状下需 32 次（药店 20 锚点
    ×1 词 + 市场 4 锚点×3 词，全词口径），23 次撑不满 ⇒ 大范围档恒带 `anchors_dropped`。
    """
    return round(_qps() * FORENSIC_WINDOW_S * LOAD_FACTOR)


def total_calls_hard_ceiling() -> int:
    """单次体检**全局调用熔断上限**（免费档 42+34+3=79）。

    42 是矩阵+POI 的精度预算；intake 阶段（地理编码/逆地理/坐标转换）还需头寸；
    v5.4 起再加一格 `forensic_budget()`（扩容回合 34），否则回合第一轮就会被掐在 45 次上
    （第 0 步实测 A 屏已吃 28 次 ⇒ 扩容 10~20 次贴线，北京侧必撞熔断、剩余锚点 `not_run`）。
    熔断定位是**防失控循环**（扩词/翻页空转），不是替代分区预算：分区照旧各管各的额度，
    这里只兜住「总调用数失控」。`ceiling = total + forensic + INTAKE_MARGIN` 恒等式由
    `tests/test_quota.py` 的 u15 钉住字面值 79。
    """
    return total_budget() + forensic_budget() + INTAKE_MARGIN


def poi_page_depth(n_terms: int, poi_budget: int) -> int:
    """POI 每关键词页深：由预算导出，clamp 到 [1,3]。

    - 免费档 floor(27/22)=1；词少/预算足时自动回升（付费档获益）；
    - 预算为 0/负 → 保守页深 1；词数为 0 → 避免除零，回退页深 1；
    - 预算远大于词数 → clamp 上限 3，杜绝爆表。

    `poi_budget` **必须显式传入**，不留默认值：当年形参与模块级函数 `poi_budget()` 同名即
    遮蔽，「省略参数」会走到 `poi_budget()` 调用一个 None 上 ⇒ `TypeError: 'NoneType' object is
    not callable`。真实调用点一直显式传预算，所以那条路径从未被执行过 —— 那条函数现已随
    D5 改名成 `poi_budget_for(mat_calls)`（它要的是矩阵额度，不是全局占比），但**漏传必炸**
    这条签名纪律留着：要取证预算就写 `quota_budget(profile, travel_mode)[1]`。
    """
    if n_terms <= 0 or poi_budget <= 0:
        return _DEFAULT_PAGE_DEPTH
    return max(PAGE_DEPTH_MIN, min(PAGE_DEPTH_MAX, floor(poi_budget / n_terms)))