"""服务盲区识别（赛题口径）：可达区内 1km 半径三要素覆盖判定 + 灰区聚合。

判定：对**可达区**内的网格点，检查其 1km 圆内是否同时存在 菜市场 / 药店 / 小学；
缺失任一 → 该点判盲。相邻缺失点聚为连通簇，输出：盲区中心（簇质心）+ 缺失设施 +
最近各类设施（距离/方位）+ 灰区多边形。

## 本轮修复的两个结构性缺陷（Q1 本体）

1. **判定网格越出可达区**（旧：``xs = linspace(-study_radius_m, study_radius_m, n)``）
   判定网格铺满「研究区 ±2500m」，而采集区只有 2000m 半径 ⇒ 2km 外「**没查**」被当成
   「**没有**」，四个角点必然缺失 → 从角点起连通域 → 外边界 = 整张方形（5.4km，比研究区还大）。
   现在：网格铺 ±``scope.reach_circumradius_m``，且**只保留落在可达区多边形内的格**。
   可达区外没有「可达但缺设施」这回事，语义上就不该判盲。

2. **像素→米换算用了名义格距**（旧：``return miss, grid_m, center_idx``）
   名义 ``grid_m=200``，而 ``linspace`` 的实际格距是 ``2R/(n-1)``（27 格时 = 192.31m）
   ⇒ 所有多边形尺寸被放大 4%。现在 ``cover_matrix`` 返回**实际格距** ``step``，
   下游（``trace_exterior`` / ``_has_in_cluster`` / 簇质心）一律只用 ``step``，不再用名义值。

## 第三件事：证据不足的格必须标 unknown，不能判盲

判「某格 1km 内没有药店」的前提是**那个 1km 圆被完整查过一遍**。格越靠近证据边界，
其 1km 圆就有越大比例落在边界外 —— 那部分「没查」，不构成「没有」。
⇒ 采集半径若算错，症状是「unknown 计数上升（可见、可诊断）」，
   而不是「盲区膨胀成整张网格（静默错误）」。

## 第四件事（本轮）：证据门控必须**逐类**，不能取三类边界的最小值

上一轮的 ``judged`` 掩码用单一几何半径（``采集半径 − 1km``）门控三类，两个后果：

1. **能力被最稠密那一类拖死**。判盲是**存在性**结论 —— 缺任意一类即成立。所以只要
   **有一类**在该格周围 1km 查全了，这个格就有资格被判定。取 min 等于让药店
   （凯里实测 60 家、百度单页 20 条封顶 ⇒ 证据边界仅 ~1754m）把菜市场（18 家）
   与小学（17 家）—— 两类**一页就穷尽**、边界可达 2.3km —— 本已足够的证据一起废掉。
   用户报的「左上角右下角设施更稀疏为何不判」正是这么丢的。
2. **反过来也不许偷懒**：说「这格**不盲**」要求三类**都**有据且都命中，
   否则只能回答「不知道」。⇒ 不对称规则：**判盲只需一类有据，说『不盲』要三类有据。**

现在门控来自 ``EvidenceRegion.to_mask(格阵, 类别)`` —— 每类一组「锚点 + 已证明查全的深度」
的圆盘，格只要被**任一**同类圆盘完整覆盖就算有据。圆盘由采集侧的实测事实
（``CollectionEvidence``，含分页饱和与封顶事实）构造；未跑真实采集的路径走
``SpatialScope.degenerate_evidence_region`` 的**单圆盘退化特例**，其掩码与旧的
「d ≤ 边界−1km」标量判据逐格相同（``test_evidence_region.py`` A2/A2p 钉着）。
⇒ 判定路径只认区域，没有标量旁支；``triad_judge_radius_m`` 只留给标量举证与 B10 复算。
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.living_circle.contour import (
    blob_area,
    marching_squares_binary,
    mask_connect_center,
    smooth_ring,
    trace_exterior,
)
from app.living_circle.field import BlindnessField
from app.living_circle.geo_utils import (
    LngLat,
    direction_word,
    ensure_closed,
    haversine_m,
    round_lnglat,
    to_local_xy,
    xy_to_lnglat,
)
# 判定格规格的唯一推导点在 `grid.py`（`scope.EvidenceRegion` 也要吃同一份几何，
# 若长在 blindspot 里就会和 scope 形成环依赖）。这里 re-export 是为了让
# `blindspot.judge_grid` 这个既有认知入口继续可用。
from app.living_circle.grid import GridSpec, judge_grid
from app.living_circle.judgement import STAT_KEYS, Judgement, JudgeMasks
from app.living_circle.scope import (
    BLIND_RADIUS_M,  # noqa: F401  # 仅**再导出**：`caliber_index` 以 `blindspot::BLIND_RADIUS_M` 索引本模块属性
    EvidenceRegion,
    SpatialScope,
    TRIAD_KEYS,
    TRIAD_LABEL,
    blind_radius_or,
)

_logger = logging.getLogger(__name__)

# 判定网格格距。
#
# **判定半径与必达要素登记表不住在这里**：`BLIND_RADIUS_M` 是「采集区 / 可达区 / 判定区」
# 三概念关系的一半，归 `scope`（那里才能做构造即校验）；`TRIAD_KEYS` / `TRIAD_LABEL`
# 同时驱动采集侧的证据半径，一处定义才不会被抄歪。本模块只导入、不再各写一份。
# （`caliber_index` 以 `blindspot::BLIND_RADIUS_M` 为 ref 索引**本模块属性**，
#   经导入仍然取得到 —— 换定义位置不动 ref，否则专家名册的引用会集体失效。）
BLIND_GRID_M = 200.0

# marching-squares 采样细化倍率：把每个判定格细分为 refine² 个子采样，
# 使边界能贴合设施真实覆盖（破除规则四边形）。取值平衡精度与开销。
MS_REFINE = 4

# 补点策略：按「最近替代距离」分档（数据驱动，可扩展策略类型）
#  ≤600m → 流动服务；600–1200m → 移动点/改道；>1200m → 新建
EFFORT_BY_DIST: Tuple[Tuple[float, str], ...] = (
    (600.0, "mobile_service"),
    (1200.0, "reroute"),
)

# 严重度分档阈值（gap 越大越严重）
SEV_HEAVY = 0.6
SEV_MEDIUM = 0.33
SEVERITIES = ("heavy", "medium", "light")


# 判定产物（掩码值对象 + 一次判定的捆绑体）住在 `judgement.py`：本模块 import `scope`，
# 把这两个形状留在这里就会逼出 `scope → blindspot` 的回边（同 `GridSpec` 拆进 `grid.py`
# 的那条约束）。字段语义与「谁不许回头改谁」写在 `judgement.JudgeMasks` 的 docstring 上。


def _verdict_masks(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, Sequence[Tuple[float, float]]],
    grid_m: float = BLIND_GRID_M,
    radius_m: Optional[float] = None,
    region: Optional[EvidenceRegion] = None,
) -> JudgeMasks:
    """逐格判定的唯一实现：一次算出 ``inside / blind / verdict / capped`` 四张结论掩码，
    外加逐类三张**输入**掩码（``judgeable`` / ``present`` / ``nearest_m``，各 ``TRIAD_KEYS`` 一张）。

    输入那三张此前算完就地丢弃 ⇒ 报告只剩计数与连续环，"哪一格凭什么这个结论"无从复原
    （计划 cells-ledger-judge-scale §2 的根因）。这里带出来，`render_cells_ledger` 只渲染不重算。

    ## 为什么判定门控必须**逐类**，不能用三类里最短的那条半径

    判盲是**存在性**结论：缺任意一类即判盲。所以某格能否判盲，取决于
    「有没有**至少一类**在该格周围 1km 查全了」，而不是「三类是否都查全」。
    取三类边界的最小值当统一门控 ⇒ 最稠密那一类（凯里实测药店 60 家、单页 20 条封顶，
    证据边界只到 1754m）会把最稀疏那两类（菜市场 18 / 小学 17，**一页即穷尽**）
    本来足够的证据一起废掉 —— 用户问的「左上角右下角设施更稀疏为何不判」正是这么丢的。

    反过来，「确认不盲」要求三类**都**查全且都有命中；否则只能说「不知道」，
    落进 ``cells_unknown``。⇒ 一条不对称规则：**判盲只需一类有据，说『不盲』要三类有据。**

    网格铺 ``±scope.reach_circumradius_m``，仅保留两重筛选后的格：
      - ``inside``：格心落在可达区多边形内（可达区外不判盲）；
      - 有结论：该格至少有一类必达要素**证据齐**（其 1km 圆被该类实测边界完整覆盖）。
    """
    grid = judge_grid(center, scope, grid_m)      # 判定格规格的唯一推导点（`grid.py`）
    coords, n, step = grid.coords, grid.n, grid.step
    # 判定半径的**决议点**（生活圈片 1b）：省略实参 ⇒ 按本次口径取；显式传入 ⇒ 原样用。
    # 往下所有取用（`to_mask` / `_has_within` / `is_cap_bound`）都吃这一份已决议的值，
    # 不再各自读常量 —— 那 21 条取值途径里，判定链上的一律在此收口。
    radius_m = blind_radius_or(radius_m, scope.travel_mode)
    # 判定输入统一是**区域**，不留标量旁支（计划 v4 架构姿态 2）。未显式绑定 region 时走
    # `degenerate_evidence_region` 的单圆盘特例 —— 它的掩码与旧的 `d ≤ 边界−1km` 判据逐格
    # 相同（`test_evidence_region.py::test_single_disc_mask_equals_the_legacy_scalar_rule`
    # 钉着这条等价），所以升级表示法不改判定结果，多锚点才改。
    #
    # 「吃哪一块区域」的解析收拢到 `SpatialScope.judge_region`（计划 v5.9 前置②）：显式参数
    # 通道（T-P0-1 选项①）与落库举证过去各读各的，接线即成第二事实源；现在判定与举证共用
    # 那一处解析，「两条取法给了不同对象 ⇒ 报错」也只写在那一处。
    region = scope.judge_region(center, region)
    judgeable = {key: region.to_mask(grid, key, radius_m=radius_m) for key in TRIAD_KEYS}
    # 第三态按**格**归因，而不是挂一个全局开关。一格算「接口封顶」的充要条件：
    # **挡住它的每一个类**都被封顶 —— 判盲只需一类有据（本文件头那条不对称规则），
    # 所以只要还有一个类是「我们多给预算就判得动」，这格的缺口就记在我们头上。
    # 两个错误方向都朝「好看」：写成 `any` 会把我们的失职赦免给百度；写成全局开关会让
    # 明明是我们的取证缺口的格整体改姓。故逐类取合取，且只在这一格确实判不动时才认领。
    capped_here = np.ones((n, n), dtype=bool)
    for key in TRIAD_KEYS:
        if not region.is_cap_bound(key, radius_m):
            capped_here &= judgeable[key]     # 该类未被封顶 ⇒ 它判不动的地方就不是封顶

    # 预转三要素为局部米坐标（加速 1km 命中判定）
    local: Dict[str, np.ndarray] = {}
    for k2, pts in triads.items():
        if not pts:
            continue
        local[k2] = np.array([_local_m(center, lng, lat) for (lng, lat) in pts], dtype=float)

    miss = np.zeros((n, n), dtype=bool)
    verdict = np.zeros((n, n), dtype=bool)   # 该格是否得出了结论（判盲 或 确认不盲）
    inside = grid.inside_mask(scope)
    inside_rows, inside_cols = np.where(inside)
    # 逐类台账两张（计划 cells-ledger-judge-scale §4.2）。默认值**就是**「无从知道」（-1）：
    # 只有真正求过值的格才会被改写 ⇒ 第三态由初值兜住，不依赖调用方记得初始化。
    # 用 int8/float 而不是 bool，理由见 `JudgeMasks` 的 ⚠️（复审 v1.2 P0-1）。
    present: Dict[str, np.ndarray] = {key: np.full((n, n), -1, dtype=np.int8) for key in TRIAD_KEYS}
    nearest_m: Dict[str, np.ndarray] = {key: np.full((n, n), -1.0) for key in TRIAD_KEYS}
    for i, j in zip(inside_rows, inside_cols):
        x, y = float(coords[j]), float(coords[i])
        # 该类在该格「有据」⇔ 该格的 1km 判定圆完整落在该类某个证据圆盘内
        conclusive = [key for key in TRIAD_KEYS if judgeable[key][i, j]]
        if not conclusive:
            continue                          # 一类都无从下结论 ⇒ unknown/capped 分账在下方
        # 命中与最近距离**同一次算出**（`_hit_and_nearest_m`）：台账要说「这格菜市场最近 212m」，
        # 就不能另起一处只算距离的实现 —— 两处的 `<=` 一旦分叉，卡片上「命中」与「最近距离」
        # 就会互相打脸。
        missing_here: List[str] = []
        for key in conclusive:
            hit, dist = _hit_and_nearest_m(x, y, local.get(key), radius_m)
            present[key][i, j] = 1 if hit else 0
            nearest_m[key][i, j] = dist
            if not hit:
                missing_here.append(key)
        if missing_here:
            miss[i, j] = True                 # 存在性结论：至少一类有据且确实没有
            verdict[i, j] = True
        elif len(conclusive) == len(TRIAD_KEYS):
            verdict[i, j] = True              # 三类皆有据且皆有命中 ⇒ 确认不盲

    return JudgeMasks(
        grid=grid, region=region, step=float(step),
        inside=inside, blind=miss, verdict=verdict,
        capped=(inside & ~verdict & capped_here),
        judgeable=judgeable, present=present, nearest_m=nearest_m,
    )


def _stats_from_masks(masks: JudgeMasks) -> Dict[str, int]:
    """把四张掩码塌成报告要读的五个计数 —— 这组公式的**唯一住所**（片 1a）。

    五个键的算法此前长在 `cover_matrix` 体内 ⇒ 判定产物要交给别人复用时，只能让对方
    「照着抄一遍」或「重算一次掩码」，两条都是本仓反复出事的形状。抽出来之后
    `cover_matrix`（报告视图薄壳）与 `judge_once`（取证视图）吃的是**同一份**分账公式。

    `cells_unknown` 走**逐格交集**而不是 `inside − judged − capped` 的算术差：后者是恒等式，
    万一 `capped` 与 `verdict` 哪天重叠（封顶归因被改动过，历史上就出过 `any`/合取两种写法），
    算术差会把重叠悄悄吞掉、三态照样"闭合"。交集写法让这种形状有地方红。
    """
    stats = {
        "cells_inside": int(masks.inside.sum()),
        "cells_judged": int(masks.verdict.sum()),
        # 三态闭合：inside = judged + unknown + unjudgeable_by_cap（互斥不重不漏）
        "cells_unknown": int((masks.inside & ~masks.verdict & ~masks.capped).sum()),
        "cells_unjudgeable_by_cap": int(masks.capped.sum()),
        "cells_blind": int(masks.blind.sum()),
    }
    # 键名集来自 `judgement.STAT_KEYS`（唯一来源），这里只核对两边没漂：
    # 少一个键 ⇒ 举证少一个数而报告照样绿（第十一轮 P0-2），宁可在这里响亮失败。
    if set(stats) != set(STAT_KEYS):
        raise ValueError(
            f"三态账目的键集与名册登记脱钩：产出 {sorted(stats)}，登记 {sorted(STAT_KEYS)}"
        )
    return stats


#: 逐格台账的表示法版本与格型（与 `footprint_meta` 同一条纪律：换格制要能在读侧查出来）。
#: 行字符串是**方格专属**表示法 —— `blindspot.py:587` 一带的注释已预告 stage2 可能换 H3，
#: 那时不是"换个编码"而是"换一套邻接关系"，所以这两枚常量必须随台账一起落库。
LEDGER_SCHEMA_VERSION = 1
LEDGER_GRID = "square"
#: 三个字符是台账的字母表，读侧（前端 `cellsLedgerOf`）逐字对照 ⇒ 名字册也引这三个。
LEDGER_YES = "1"      # 是（在可达区内 / 该类有据 / 该类 1km 内有设施）
LEDGER_NO = "0"       # 否（求过值，答案为假）
LEDGER_UNKNOWN = "."  # 无从知道 —— ⚠️ 不是"否"。压成 `0` 就等于让报告重犯「判不了冒充不盲」


def render_cells_ledger(masks: JudgeMasks, radius_m: float) -> Dict[str, Any]:
    """把**判定那一次**的逐格输入摊成 `caliber.cells_ledger`（计划 cells-ledger-judge-scale §4）。

    为什么要有这张表：判盲以格为单位，产物却只到「四类计数 + 连续盲区环」。环面积能对上
    格数（凯里实测 8.000 格当量），但它 smeared 跨过 16 格 ⇒ **哪 8 格判盲无法复原**；
    药店缺据的 9 格里"3 判盲 + 6 未判"只能靠排除法说总数，指不出是哪 3 哪 6。
    这张表把中间那一层留住，读者不必再问"这块为什么不算盲"。

    表示法（§4.1 方案 A）：每张 = `n` 行、每行 `n` 字符，行沿 y、列沿 x（与 `GridSpec`
    的 `(coords[j], coords[i])` 同序）。字符只有三个：``1`` / ``0`` / ``.``。
    选它而不是位打包：人眼可读、可 grep，且 **Py/TS 都不需要编解码实现** —— 两份编解码
    正是本仓反复出事的"同一判据两份实现"形态。

    ⚠️ 本函数**只渲染、不重算**：吃 `JudgeMasks`，不吃格阵参数。自己再 `judge_grid` 一遍
    就是第二处格阵来源（`JudgeMasks` docstring 明令禁止），且 γ 守卫 G-10 的调用点计数会红。

    `radius_m` 由调用方给（`Judgement.radius_m` = 本次真正吃的那把尺）。不在这儿取口径：
    多模式分档后它不是常量，写死 1000 会让图上 800m 圆旁边标着 1km（复审 v1.2 P1-1）。
    """
    n = int(masks.grid.n)
    side = (n, n)
    for name in ("inside", "blind", "verdict", "capped"):
        if getattr(masks, name).shape != side:
            raise ValueError(f"render_cells_ledger：masks.{name} 形状与格阵 n={n} 不符")

    def rows_bool(arr: np.ndarray) -> List[str]:
        return ["".join(LEDGER_YES if v else LEDGER_NO for v in row) for row in arr]

    def rows_tri(arr: np.ndarray) -> List[str]:
        # int8 三态 → 字符：-1 无从知道 / 0 否 / 1 是。缺任何一档都是渲染层的错。
        out = []
        for row in arr:
            chars = []
            for v in row:
                if v == -1:
                    chars.append(LEDGER_UNKNOWN)
                elif v == 0:
                    chars.append(LEDGER_NO)
                elif v == 1:
                    chars.append(LEDGER_YES)
                else:
                    raise ValueError(f"present 出现第三态之外的值 {v!r} —— 台账字母表只有 1/0/.")
            out.append("".join(chars))
        return out

    def rows_dist(present_arr: np.ndarray, dist_arr: np.ndarray) -> List[str]:
        # 距离只在「求过值」的格上有意义（`present` 不是 `.` 的格）；其余一律 `-`。
        # inf（该类一个设施都没有）也落 `-`：没有距离可报，但不许它变成 JSON 里的非法值。
        out: List[str] = []
        for pres_row, dist_row in zip(present_arr, dist_arr):
            toks = []
            for v, d in zip(pres_row, dist_row):
                if v == -1 or not math.isfinite(float(d)):
                    toks.append("-")
                else:
                    toks.append(str(int(round(float(d)))))
            out.append(" ".join(toks))
        return out

    ledger: Dict[str, Any] = {
        "grid": LEDGER_GRID,
        "schema_version": LEDGER_SCHEMA_VERSION,
        "n": n,
        "step_m": round(float(masks.step), 1),
        "scan_m": round(float(masks.grid.scan), 1),
        "radius_m": int(round(float(radius_m))),
        "center": [round(masks.grid.center[0], 6), round(masks.grid.center[1], 6)],
        "inside": rows_bool(masks.inside),
        # `capped` 也在台账里：`unknown` 与 `capped` 的分裂**不能**由其余几张推出（两者都是
        # 「没结论」，区别只在谁的失职）。少了这张，B13 就只能复算四个数里的三个 ——
        # 而「把我们的漏查记到百度封顶上」恰是这条链历史上真出过事的形状。
        "capped": rows_bool(masks.capped),
        # `blind` / `verdict` 是**结论**那两张。带上它们不是为了画图（环已经在了），而是让
        # B13 能在读侧**独立重抄一遍不对称规则**再对表：只发输入不发结论，复算就成了同义反复，
        # 「判盲只需一类有据」被改回「三类都要有据」时无人报警。这与 B11 重抄扣分公式同理。
        "blind": rows_bool(masks.blind),
        "verdict": rows_bool(masks.verdict),
    }
    for key in TRIAD_KEYS:
        judge, pres, near = masks.judgeable[key], masks.present[key], masks.nearest_m[key]
        if judge.shape != side or pres.shape != side or near.shape != side:
            raise ValueError(f"render_cells_ledger：逐类 {key} 的掩码形状与格阵不符")
        ledger[f"judge.{key}"] = rows_bool(judge)
        ledger[f"present.{key}"] = rows_tri(pres)
        ledger[f"nearest.{key}"] = rows_dist(pres, near)
    return ledger


def cover_matrix(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, Sequence[Tuple[float, float]]],
    grid_m: float = BLIND_GRID_M,
    radius_m: Optional[float] = None,
    region: Optional[EvidenceRegion] = None,
) -> Tuple[np.ndarray, float, Dict[str, int]]:
    """缺失掩码 + 实际格距 + 格数分档 —— `_verdict_masks` 的**报告视图**薄壳。

    逐格规则、区域解析、不对称纪律都在 `_verdict_masks`（判据与判盲共用那一份）；分账公式在
    `_stats_from_masks`。返回值形状与 stats 的五个键一个都没动（片 1a 保持形状是为了不动
    `test_evidence_region.py` 那 13 处位置调用）。

    ⚠️ **生产侧不许调用它**（计划 v6.5 片 1a 定稿）：线上唯一的判定入口是 `judge_once`，
    它自己走 `_verdict_masks` + `_stats_from_masks`。本壳只留给测试与脚本；这条分工由
    γ 守卫 G-10 钉住（`cover_matrix` 在 `app/**` 的生产调用者必须为 0）。留着的理由不是
    兼容：那 13 处用例正是拿它逐格核对掩码形状的，改成走 `judge_once` 会让它们连带
    跑一遍簇聚合与多边形抽取 —— 测的就不再是判据了。

    返回 ``(miss, step, stats)``：
      - ``step`` 为**实际格距** ``2R/(n-1)``（不是名义 ``grid_m``）；
      - ``stats`` 为格数分档（``cells_inside`` / ``cells_judged`` / ``cells_unknown`` /
        ``cells_blind``），供报告口径显式暴露「有多少可达区内的格没被判定」。
    """
    masks = _verdict_masks(center, scope, triads, grid_m, radius_m, region)
    return masks.blind, masks.step, _stats_from_masks(masks)


def undecided_mask(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, Sequence[Tuple[float, float]]],
    *,
    grid_m: float = BLIND_GRID_M,
    region: Optional[EvidenceRegion] = None,
    radius_m: Optional[float] = None,
) -> Tuple[np.ndarray, GridSpec]:
    """取证规划该读的掩码：可达区内**尚未得出结论**的格，连同判定那一次的格阵。

    这是计划 v5.9 前置①（复审 P0-3）的出口。此前合同只写在 `plan_expansion` 的 docstring 上
    （「调用方传的 inside 应是未判出格」），而 `blindspot` 把 `verdict` 算出来就丢弃 ⇒
    没有任何一层能递出这张掩码，接线那一轮于是只能拿整片可达区去数未覆盖格 —— 已判出的格
    照样排队要证据，D6 那个「约 50 次/场景」始终是推演。

    为什么 ``inside & ~verdict`` 是**合法**的取证需求掩码 —— 这条合法性只在一半方向上成立，
    另一半必须写清楚（第五轮复审 P0-1 打出来的正是这里）：

    - **区域方向单调**：加盘只会让「有据的类」变多（`to_mask` 取圆盘并集），已有结论不会被
      后续取证推翻 ⇒ 已判出的格不必再取证，从需求里划掉是安全的。
    - **点位方向不单调**：一回合**带回来新设施点位**时，某格原本靠「market 有据且确实没有」
      挣来的盲区会退回 unknown —— 因为新点把「没有」这条证据消掉了，而其余类在该格还不够
      有据 ⇒ 既不能说盲也不能说不盲。实测形状：区域一字不动、只补一个西侧 600m 的菜市场点，
      `cells_blind 45 → 12`、`undecided 580 → 612`（32 格重回需求面）。
    ⇒ 所以：① 这张掩码每轮**必须重算**，不许缓存上一轮的；② `covered`（未判出格=0）只是
    **本轮**的结论，不是永久断言；③ 方向是偏保守的 —— 宁可重新要一次取证，也不把「已经知道
    答案」的格永久钉死。

    封顶格**不**从掩码里剔：`is_cap_bound` 说的是「该类现有盘全撞了页上限」，而换个锚点后
    其 1km 邻域未必也超一页 ⇒ 提前剔掉等于把「换个点也许查得全」的格判死。这条取舍让判据
    偏向「宁可多打一次」而不是偏向「少打」，与判盲那套不对称纪律同方向。

    返回带 ``grid`` 是刻意的：判据（`LatticeAnchors.plan_expansion`）必须在**同一个格阵**上
    数格子，调用方自己 `judge_grid` 重算就是第二处格阵来源，`grid_m` 一漂两边掩码对不上。

    ⚠️ 本函数是**规划视图壳**，生产侧调用者必须为 0（γ 守卫 G-10 钉着，`JUDGE_EXPECTED_CALLS`
    里它就是 0）。留它只为测试与脚本可以直接拿掩码而不必先跑簇聚合。
    接线形状（阶段 3 唯一合法形状）——**走唯一入口，别再自己判一遍**::

        j = judge_once(center, scope, triads, grid_m=200.0, region=region)
        plan = LatticeAnchors().plan_expansion(
            j.region, j.grid, cat, inside=j.masks.undecided, radius_m=j.radius_m
        )

    为什么示例里 `radius_m` 也必须传（第十四轮 P1-2）：省略 ⇒ 按口径决议，而口径分档之后
    决议点默认落回**步行档**（这些几何对象手里没有 `travel_mode`）⇒ 判盲用本次的尺、
    规划用另一把。示例是给人照着抄的，抄漏一个关键字参数就静默换尺。

    为什么这行必须改指 `judge_once`：本壳每次调用都自己走一遍 `_verdict_masks`。若阶段 3 按
    旧接线形状接进生产，一次体检就会判两遍（编排一遍 + 这里一遍），而两遍之间只要证据域
    有任何不同步，回合就是在按另一块区域补点 —— 正是片 1a 刚消灭的那个形状（第十一轮 P0-1）。
    """
    masks = _verdict_masks(center, scope, triads, grid_m, radius_m, region)
    return masks.undecided, masks.grid


def inside_mask(
    center: LngLat,
    scan: float,
    coords: np.ndarray,
    n: int,
    scope: SpatialScope,
) -> np.ndarray:
    """可达区内的判定格掩码 —— 旧签名保留，实体已搬去 :meth:`GridSpec.inside_mask`。

    本函数只是那一份实现的调用门面（唯一实现原则：搬家不留第二份）。
    """
    spec = GridSpec(
        center=center, scan=float(scan),
        step=float(coords[1] - coords[0]), n=int(n), coords=coords,
    )
    return spec.inside_mask(scope)


def _local_m(center: LngLat, lng: float, lat: float) -> Tuple[float, float]:
    from app.living_circle.geo_utils import to_local_xy

    return to_local_xy(center, lng, lat)


def _hit_and_nearest_m(x: float, y: float, pts: Any,
                       radius_m: float) -> Tuple[bool, float]:
    """点集内是否有半径内的点，**顺带**给出最近距离（米，无点 ⇒ ``inf``）。

    为什么把距离一起返回而不是让调用方再算一遍：逐格台账要报「这格菜市场最近 212m」
    （计划 cells-ledger-judge-scale §4.4），而命中判定本来就把 `d2` 全算出来了 ——
    另起一处「只算距离」的实现就是第二把尺，两处的 `<=`/`<` 一旦分叉，
    「命中」与「最近距离」会在同一张卡上互相打脸。
    """
    if pts is None or len(pts) == 0:
        return False, float("inf")
    d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
    nearest = float(np.sqrt(d2.min()))
    return bool(d2.min() <= radius_m * radius_m), nearest


def _has_within(x: float, y: float, pts: Any, radius_m: float) -> bool:
    """局部米坐标点集内是否有 (x,y) 半径内的点（numpy 向量化）。"""
    return _hit_and_nearest_m(x, y, pts, radius_m)[0]



def _missing_nearest_m(miss_keys: Sequence[str], nearest: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """每个缺失类的小区最近替代距离。

    赛题口径下缺失类必无 1km 内设施，故 ``nearest`` 只可能在 >1km 处有值；
    若某缺失类连任何设施都没有（``nearest`` 里被跳过），按其最严重处理（``inf``）。
    """
    by_key = {n.get("facility"): n.get("distance_m") for n in nearest}
    return {k: float(by_key.get(k, float("inf"))) for k in miss_keys}


def _required_radius(value: Optional[float], who: str) -> float:
    """私有几何 helper 的半径**必须**由调用方给（计划 v6.9 ④″ 纪律一）。

    为什么不复用 `blind_radius_or` 那套「省略⇒按口径决议」：这些 helper 拿不到
    `travel_mode`，自己取口径就是**第二个住所** —— 而 `assemble.py:377` 正是反向 import
    本模块原语的一条路（注解/预计算路径天生没有 `Judgement`）。让它在这里响亮失败，
    比让它静默按步行档算更便宜。
    """
    if value is None:
        raise ValueError(
            f"{who} 需要调用方显式传入判定半径：决议点只在 `_verdict_masks`/`judge_once`，"
            "私有几何自己取口径 ⇒ 同一次判定会出现两把尺"
        )
    return float(value)


def _excess_farness(miss_nearest: Dict[str, float], min_gap: Optional[float] = None) -> float:
    """度量「超出必达下限的距离」而非绝对距离，保证三档真实可达（R2/架构审查）。

    ``farness = mean over 缺失类 of min(1, max(0, d_k − min_gap)/min_gap)``。
    缺失类若完全无设施（``inf``）→ 该项取 1（最严重，P1-1 回退）。
    归一到 [0,1]。

    ⚠️ 决议放在**早退之前**：`miss_nearest` 为空时也要要求调用方给半径 —— 把校验排在
    ``return 0.0`` 之后，等于「空输入的那格可以不带尺来」，纪律一就漏了一个洞。
    """
    min_gap = _required_radius(min_gap, "_excess_farness")
    if not miss_nearest:
        return 0.0
    total = 0.0
    for d in miss_nearest.values():
        if d == float("inf"):
            total += 1.0
        else:
            total += min(1.0, max(0.0, d - min_gap) / min_gap)
    return total / len(miss_nearest)


def _gap_score(m: int, farness: float) -> float:
    """连续缺口指数 ∈ [0,1]：缺失占比 m/类数 + 超出必达下限的替代距离。

    ``m/类数`` 用 ``len(TRIAD_KEYS)`` 归一化（而非硬编码 3），未来加品类不失真（P1-2）。
    """
    if m <= 0:
        return 0.0
    m_norm = min(m / len(TRIAD_KEYS), 1.0)
    g = 0.6 * m_norm + 0.4 * farness
    return round(min(1.0, g), 3)


def _severity_of(gap: float) -> str:
    if gap >= SEV_HEAVY:
        return "heavy"
    if gap >= SEV_MEDIUM:
        return "medium"
    return "light"


def _strategy_for(distance_m: float) -> str:
    if distance_m == float("inf"):
        return "build"
    for threshold, strategy in EFFORT_BY_DIST:
        if distance_m <= threshold:
            return strategy
    return "build"


def _cluster_served(cluster: np.ndarray, step: float, radius_m: Optional[float] = None) -> int:
    """簇质心 1km 内的判盲格数（补点优先级的 serves 基准）。"""
    radius_m = _required_radius(radius_m, "_cluster_served")
    rows, cols = np.where(cluster)
    if len(rows) == 0:
        return 0
    cy, cx = float(rows.mean()), float(cols.mean())
    served = 0
    for r, c in zip(rows, cols):
        if math.hypot(c - cx, r - cy) * step <= radius_m:
            served += 1
    return int(served)


def _fixes_for(
    miss_keys: Sequence[str],
    miss_nearest: Dict[str, float],
    cluster_center: LngLat,
    served: int,
    gap: float,
) -> List[Dict[str, Any]]:
    """为每个缺失类生成补点处方；``_key_*`` 为全局优先级排序用内部字段，末尾剔除。"""
    out: List[Dict[str, Any]] = []
    for k in miss_keys:
        d = miss_nearest.get(k, float("inf"))
        out.append({
            "facility": TRIAD_LABEL.get(k, k),
            "point": [round(cluster_center[0], 6), round(cluster_center[1], 6)],
            "strategy": _strategy_for(d),
            "nearest_alt_m": None if d == float("inf") else round(d, 1),
            "served": served,
            "_key_gap": gap,
            "_key_serves": served,
        })
    return out


def _assign_priorities(fixes: List[Dict[str, Any]]) -> None:
    """按 gap↓、serves↓、设施名 排序，给全部补点处方连续唯一 priority。"""
    for pos, f in enumerate(
        sorted(fixes, key=lambda x: (-x.get("_key_gap", 0.0), -x.get("_key_serves", 0), x.get("facility", ""))),
        start=1,
    ):
        f["priority"] = pos
        f.pop("_key_gap", None)
        f.pop("_key_serves", None)


def judge_once(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
    region: Optional[EvidenceRegion] = None,
    *,
    radius_m: Optional[float] = None,
) -> Judgement:
    """一次判定的**唯一生产入口**（计划 v6.5 片 1a）：结论 + 账目 + 掩码，只算一遍。

    与旧的 `find_blindspots_with_stats` 的差别只有一件：产物**带得走**。此前出口只交
    `(spots, stats)`，逐格掩码算完就丢 ⇒ 谁想复用（取证回合要按未判动的格补锚点）只能
    再调一次 `undecided_mask`，也就是**第二次逐格判定**，而「这两次吃的证据区域是不是
    同一块」没有任何一层能证明。现在一次判定交出一个 `Judgement`，装配层与回合读的是
    同一个对象。

    triads: {market/pharmacy/primary: [{lng,lat,name}, ...]}（已清洗）。
    `region`：判定区域的**显式注入通道**（T-P0-1 选项①）—— 取证回合中途手里就有新区域，
    但它还不是要落库的报告口径，绑进 `SpatialScope` 会顺带换掉标量视图的来源。这里直接
    送进 `_verdict_masks`，那里守「两条取法不许同时给不同对象」。
    `prefix`：盲区 id 的前缀（通常是场景名）。它在判定时刻定型并随对象交付，装配层不许
    拿别的名字重造一遍。
    `radius_m`（生活圈片 1b，**keyword-only**）：本次判定吃的判定半径。省略 ⇒ 按
    `scope.travel_mode` 从口径对象决议；显式给 ⇒ 原样用（取证回合与读数脚本要用另一把尺时的
    唯一入口）。决议一次，往下**全部显式传**：掩码、簇聚合、连续场、上屏的
    `spots[].radius_m`、以及产物里的 `Judgement.radius_m` —— 半径因此不再是"每条途径各取一份"
    的 21 个数，而是本次判定的一对一事实。
    ⚠️ 为什么必须是关键字参数：本函数的调用点 `:598`/`:615` 用的是**位置实参**，插在 `grid_m`
    之后会把 `prefix` 静默吃进 `radius_m`，盲区 id 从此变成 `bs-area-*` 而不报任何错。
    """
    point_sets: Dict[str, List[Tuple[float, float]]] = {
        k: [round_lnglat(p["lng"], p["lat"]) for p in v if "lng" in p and "lat" in p]
        for k, v in triads.items()
    }
    radius = blind_radius_or(radius_m, scope.travel_mode)
    masks = _verdict_masks(center, scope, point_sets, grid_m, radius, region=region)
    miss, step, stats = masks.blind, masks.step, _stats_from_masks(masks)
    scan = float(scope.reach_circumradius_m)

    # 盲区连续缺失场：以真实设施坐标建，供 marching-squares 按任意亚格点采样
    # （破除矩形伪象的边界层 —— 评审 P0 ①，field 与判定网格解耦）。
    # 半径必须与上面掩码那一次同一个值：环与 `footprint_meta.area_m2` 是这个场切出来的，
    # 「判盲用 800、画圈仍按 1000」会在同一份报告里自相矛盾（第十二轮 P1-2）。
    blindness_field = BlindnessField.build(center, triads, radius)

    if not miss.any():
        if stats["cells_unknown"]:
            _logger.info(
                "盲区判定：可达区内 %d 格未判定（采集区未覆盖其 1km 邻域）—— 非「无盲区」",
                stats["cells_unknown"],
            )
        return Judgement(spots=[], stats=stats, masks=masks, grid_m=grid_m,
                         prefix=prefix, radius_m=radius)

    # 每个缺失簇独立聚合（在掩码中按连通域逐个提取）
    result: List[Dict[str, Any]] = []
    worked = np.zeros_like(miss)
    n = miss.shape[0]
    idx = 0
    for i in range(n):
        for j in range(n):
            if miss[i, j] and not worked[i, j]:
                cluster = mask_connect_center(miss & ~worked, (i, j))
                worked |= cluster

                # 簇质心（像素 → 米 → lnglat）；像素→米一律用真实格距 step
                rows, cols = np.where(cluster)
                cy = float(rows.mean())
                cx = float(cols.mean())
                cluster_center = xy_to_lnglat(center, cx * step - scan, cy * step - scan)

                miss_keys = [
                    k for k in TRIAD_KEYS
                    if not point_sets.get(k)
                    or not _has_in_cluster(cluster, center, scan, point_sets[k], step, radius)
                ]
                if not miss_keys:
                    miss_keys = list(TRIAD_KEYS)  # 理论上必缺，兜底展示

                # 最近各类设施（距离 + 方位）
                nearest = []
                for k in TRIAD_KEYS:
                    if not point_sets.get(k):
                        continue
                    best_p = None
                    best_d = float("inf")
                    name = ""
                    for it in triads.get(k, []):
                        it_p = (it["lng"], it["lat"])
                        d = haversine_m(cluster_center, it_p)
                        if d < best_d:
                            best_d = d
                            best_p = it_p
                            name = it.get("name", "")
                    if best_p is not None:
                        nearest.append({
                            "facility": k,
                            "name": name,
                            "distance_m": round(best_d, 1),
                            "direction": direction_word(cluster_center, best_p),
                        })

                # 严重度/连续缺口指数/补点处方（纯函数，仅依赖 triad 中心 —— 装配层负责 reach/affected）
                miss_nearest = _missing_nearest_m(miss_keys, nearest)
                farness = _excess_farness(miss_nearest, radius)
                gap = _gap_score(len(miss_keys), farness)
                severity = _severity_of(gap)
                served = _cluster_served(cluster, step, radius)
                fixes = _fixes_for(miss_keys, miss_nearest, cluster_center, served, gap)

                # 灰区多边形：从连续缺失场抽取 smooth 边界（破除矩形伪象）
                # marching-squares 建于 field 之上（grid-agnostic），stage2 换 H3 不动这里。
                raw_xy = _cluster_footprint_ring(
                    blindness_field, cluster, step, scan, refine=MS_REFINE
                )
                # 双边界解耦（需求 §二·1 / §7.1.3）：raw=精确锯齿（供严格点内判断），
                # smoothed=显示圆角（默认渲染）。raw_xy 已是「相对 center 的米」坐标系，
                # 直投 xy_to_lnglat（勿再减 scan，否则双重偏移错位）。
                raw_lnglat = [xy_to_lnglat(center, v[0], v[1]) for v in raw_xy]
                sm_lnglat = [xy_to_lnglat(center, v[0], v[1]) for v in smooth_ring(raw_xy)]
                closed = ensure_closed(sm_lnglat)
                raw_closed = ensure_closed(raw_lnglat)
                cells_n = int(cluster.sum())
                idx += 1
                result.append({
                    "id": f"bs-{prefix}-{idx}",
                    "center": [round(cluster_center[0], 6), round(cluster_center[1], 6)],
                    "radius_m": int(radius),
                    "missing_facilities": [TRIAD_LABEL.get(k, k) for k in miss_keys if k in TRIAD_LABEL],
                    "nearest": nearest,
                    "severity": severity,
                    "gap_score": gap,
                    "fixes": fixes,
                    "polygon": {"type": "Polygon", "coordinates": [closed]},
                    "polygon_raw": {"type": "Polygon", "coordinates": [raw_closed]},
                    "footprint_meta": {
                        "cells": cells_n,
                        "grid_m": round(step, 3),
                        "resolution_m": round(step / MS_REFINE, 3),
                        "refine": MS_REFINE,
                        "area_m2": round(blob_area(raw_xy), 1),
                        "undersampled": cells_n <= 3,
                        "grid": "square",
                        "schema_version": 1,
                    },
                })
    # 全局排序：给全部补点处方分配连续唯一 priority（gap↓、serves↓）
    _fixes_all = [f for b in result for f in b.get("fixes", [])]
    _assign_priorities(_fixes_all)
    return Judgement(spots=result, stats=stats, masks=masks, grid_m=grid_m,
                     prefix=prefix, radius_m=radius)


def find_blindspots_with_stats(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
    region: Optional[EvidenceRegion] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """`(spots, stats)` 旧形状 —— `judge_once` 的**报告视图薄壳**，生产侧不许调它。

    留着是因为 `test_blindspot.py` / `test_blindspot_marching.py` 那批用例就按这个二元组解包；
    删掉它们会一起碎，而碎掉的只是形状、不是判据。线上链路（`live_forensic_steps` →
    `assemble_living_circle`）改吃 `Judgement` 之后，本函数的生产调用者必须为 0，
    这条由 γ 守卫 G-10 钉（与 `cover_matrix` 同纪律）。
    """
    j = judge_once(center, scope, triads, grid_m, prefix, region)
    return j.spots, j.stats


def find_blindspots(
    center: LngLat,
    scope: SpatialScope,
    triads: Dict[str, List[Dict[str, Any]]],
    grid_m: float = BLIND_GRID_M,
    prefix: str = "area",
) -> List[Dict[str, Any]]:
    """识别盲区：契约 ``BlindSpot[]``（同样只是薄壳，且**只走唯一入口**）。

    ⚠️ 它此前调的是 `find_blindspots_with_stats`（壳调壳 ⇒ `app/**` 里出现两个判定入口互相
    引用，G-10 的「with_stats 生产零调用」会被它自己打红）。改成直调 `judge_once`，
    两个壳都只依赖唯一入口。
    """
    return judge_once(center, scope, triads, grid_m, prefix).spots


def _has_in_cluster(
    cluster: np.ndarray,
    center: LngLat,
    scan_radius_m: float,
    pts_key: Sequence[Tuple[float, float]],
    step: float,
    radius_m: Optional[float] = None,
) -> bool:
    """簇内任一格「判定半径圆内」命中某类设施（像素→米一律用真实格距 step）。

    半径原先硬写在体内（B 档五处之一）：它的调用点在簇聚合那一圈里，手里就有本次决议出的
    半径 ⇒ 改成调用方传，缺省按纪律一响亮失败（第十四轮 P0 的落点：这条链今天还有第二个
    消费者 `assemble.py` 那条注解路径，helper 不许自己取口径）。
    """
    limit = _required_radius(radius_m, "_has_in_cluster")
    rows, cols = np.where(cluster)
    arr = np.array([_local_m(center, p[0], p[1]) for p in pts_key], dtype=float)
    for r, c in zip(rows, cols):
        x_m = float(c) * step - scan_radius_m
        y_m = float(r) * step - scan_radius_m
        if _has_within(x_m, y_m, arr, limit):
            return True
    return False


def _cluster_footprint_ring(
    field: "BlindnessField",
    cluster: np.ndarray,
    step: float,
    scan: float,
    refine: int = MS_REFINE,
) -> List[List[float]]:
    """簇的连续边界环（物理米坐标，相对场地中心）。

    在簇的像素 bbox **外扩 1 判定格** 内，每个判定格按 ``refine`` 细分，对 ``field``
    采样后跑 marching-squares → 返回含簇质心的主环。

    外扩原因：marching-squares 在「内侧区域被采样窗完整包围」时才能闭合。若直接把
    采样窗取成簇 bbox，簇填满窗口（如整片可达区皆盲）时四角全是内侧、无 served 环
    ⇒ 不产生任何线段 ⇒ 环为空。外扩 1 格让簇外的 served 格进入窗内，正常闭合。

    **兜底**：若簇在采样窗内仍无界（整片可达区全盲），marching-squares 无环可闭合，
    退化为 ``trace_exterior`` 沿簇掩码外边界走环（保证闭合，边界沿格边、仍为方形）。
    既保证每个盲区必有多边形，又让「有 served 邻居」的主流场景吃到平滑边界。
    像素→米沿用判定约定：``x = col*step - scan``、``y = row*step - scan``。
    """
    rows, cols = np.where(cluster)
    if len(rows) == 0:
        return []
    c_min, c_max = int(cols.min()), int(cols.max())
    r_min, r_max = int(rows.min()), int(rows.max())
    pad = 1  # 判定格外扩单元数，保证簇外有 served 环 → marching 可闭合
    # 采样原点（米）：外扩后的 bbox 左上角，含每个判定格 refine 个子采样
    x0 = float(c_min - pad) * step - scan
    y0 = float(r_min - pad) * step - scan
    nx = (c_max - c_min + 1 + 2 * pad) * refine
    ny = (r_max - r_min + 1 + 2 * pad) * refine
    # 实际采样步长 = 判定格距 / refine
    h = step / refine if refine > 0 else step
    loops = marching_squares_binary(field.read, x0, y0, nx, ny, h, level=0.5)
    if not loops:
        # 无 served 环可闭合（整片皆盲）→ 沿簇掩码外边界兜底，保证闭合
        return [
            [px * step - scan, py * step - scan] for px, py in trace_exterior(cluster, 1.0)
        ]
    # 簇质心（米坐标）用于选主环
    cy = float(rows.mean()) * step - scan
    cx = float(cols.mean()) * step - scan
    cx_off, cy_off = cx - x0, cy - y0
    return loose_pick_ring(loops, cx_off, cy_off)


def loose_pick_ring(
    loops: List[List[List[float]]], px: float, py: float
) -> List[List[float]]:
    """在环族中选包含 (px,py) 者（物理米坐标，点相对采样原点）；缺测时返回最大环。"""
    # 每环面积（鞋带）
    best = None
    best_area = -1.0
    for ring in loops:
        area = blob_area(ring)
        contained = _point_in_xy_ring(ring, px, py)
        if contained or area > best_area:
            if area > best_area:
                best_area = area
                best = ring
    return best or (loops[0] if loops else [])


def _point_in_xy_ring(ring: Sequence[Sequence[float]], x: float, y: float) -> bool:
    """点 (x,y) 是否在多边形内（物理米坐标，首尾一致）。"""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) < 3:
        return False
    inside = False
    n = len(pts)
    for i in range(n - 1):
        xi, yi = pts[i]
        xj, yj = pts[i + 1]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
    return inside
