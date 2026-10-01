"""一次判定的产物（计划 v6.5 片 1a · 判定结果要能穿过组装层边界）。

**为什么单独一个模块**：这两个形状此前都长在 `blindspot.py` 里（那里的 `_JudgeMasks`），而
`blindspot` 已经 import `scope`（`blindspot.py:76`）⇒ 谁想把判定产物交给 `scope.payload`
举证、或交给编排层复用，就得让 `scope`/`data_source` 回头握 `blindspot` —— 那条环正是
`GridSpec` 当年被拆进 `grid.py` 的原因（`blindspot.py:72-75` 的注释记着同一条约束）。
本模块只 import `numpy`/`dataclasses`/`typing`（`GridSpec`、`EvidenceRegion` 走
`TYPE_CHECKING`：注解在 PEP 563 下不求值，不构成运行期边）：**不给任何模块添新边**。

`Judgement` 装的是**一次判定的全部事实**：结论（spots）、账目（stats）、掩码（masks）。
取证回合（计划阶段 5）要读的正是掩码 —— 此前出口只给前两样，回合想拿掩码就还得再走一遍
`undecided_mask`（第二次逐格判定），而「两次判定吃的证据区域是不是同一块」无人能证。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

import numpy as np

if TYPE_CHECKING:                     # 只为读注解，不在运行期建边
    from app.living_circle.grid import GridSpec
    from app.living_circle.scope import EvidenceRegion


#: 三态账目的五个键（**名字集的唯一来源**：`blindspot._stats_from_masks` 生产它，
#: 本模块校验它，名册 `report::` 登记它 —— 三处引用同一个元组，不再各写一份键名）。
STAT_KEYS = (
    "cells_inside",
    "cells_judged",
    "cells_unknown",
    "cells_unjudgeable_by_cap",
    "cells_blind",
)


def judged_share(stats: "Mapping[str, int]") -> Optional[float]:
    """判定覆盖率 = 已判定格 / 可达区内格。无判定格（`cells_inside == 0`）⇒ ``None``。

    交给评分的是**比例**而不是格数：格数随格距与场景大小变化，比例才是「这次判了多少面」
    的可比量。`None` 表示覆盖率无从谈起，评分据此退回按条数扣分（不猜、不放大）。

    这里是这个比率的**唯一实现**（批 A③ 从 `assemble._judged_share` 搬来）。搬的理由不是
    整洁：复用门 `reuse_policy` 也要用它判「这份旧报告的结论够不够格当本次答案」，
    两处各写一遍 `judged / inside` 就成了「评分与缓存门用两个比率」—— 那正是本链一路在灭的形状。
    本模块运行期不 import 任何项目模块 ⇒ 两边指过来都不构成环。
    """
    inside = int(stats.get("cells_inside", 0) or 0)
    if inside <= 0:
        return None
    return int(stats.get("cells_judged", 0) or 0) / float(inside)


@dataclass(frozen=True)
class JudgeMasks:
    """判盲那一次算出的逐格掩码 —— 判据与判盲共用的**同一份**计算（计划 v5.9 前置①）。

    各字段守一件事，缺一即那条合同只能写在 docstring 上没人能执行：

      - ``blind``：缺失掩码（判盲结论本身）；
      - ``verdict``：该格是否**已得出结论**（判盲 或 三类皆有据且皆有命中）。此前它算出来就
        就地丢弃 ⇒ 取证判据拿不到「哪些格还没结论」，只能拿整片可达区去数未覆盖格，于是
        已判出的格也排队要证据（复审 P0-3：D6 那个「约 50 次/场景」因此一直是推演）；
      - ``capped``：因接口封顶而判不动的格（第三态归因）；
      - ``judgeable`` / ``present`` / ``nearest_m``：**逐类**的判定输入 —— 每类一张 ``n×n``。
        这三张是「逐格台账」（计划 cells-ledger-judge-scale §4）的唯一数据源，此前算完就地
        丢弃，于是报告只剩计数与连续环，读者无法复原「哪一格凭什么这个结论」。
        ⚠️ ``present`` 的类型是 ``int8`` 三态（``-1`` 无从知道 / ``0`` 有据但 1km 内没有 /
        ``1`` 有据且命中），**不是 bool**：``_has_within`` 只对「有据」的类求值，其余格从未
        算过；用 bool 数组会把「没算过」塌成「算过且没有」，那正是 ``ev-1`` 整套改造要消灭的
        形状（复审 v1.2 P0-1）。``nearest_m`` 同用 ``-1`` 表「无从知道」（JSON 里不许出 NaN）。
      - ``grid`` / ``region`` / ``step``：**这一次**判定用的格阵与区域 —— 判据要复用它们，
        自己重算格阵就是第二处格阵来源（``grid_m`` 一漂两边掩码对不上）。
    """

    grid: "GridSpec"
    region: "EvidenceRegion"
    step: float                                # 实际格距 = 2R/(n-1)，不是名义 grid_m
    inside: np.ndarray                         # 可达区内的格
    blind: np.ndarray                          # 判为「缺失」的格
    verdict: np.ndarray                        # 已下结论的格（缺 或 确认不缺）
    capped: np.ndarray                         # 判不动且归因于服务端封顶的格
    judgeable: Dict[str, np.ndarray]           # 逐类 bool：该格 1km 圆是否被该类证据盘完整覆盖
    present: Dict[str, np.ndarray]             # 逐类 int8 三态（-1/0/1），见上方 ⚠️
    nearest_m: Dict[str, np.ndarray]           # 逐类 float 米，-1 = 无从知道

    @property
    def undecided(self) -> np.ndarray:
        """判过却仍无结论的格（``unknown`` ∪ ``capped``）—— 取证规划的读数口径。

        住在掩码上而不是调用方各写一遍：``inside & ~verdict`` 这条式子一旦在两处出现，
        第三态归因被改动时就会有一处悄悄不算封顶格。
        """
        return self.inside & ~self.verdict


@dataclass(frozen=True)
class Judgement:
    """``blindspot.judge_once`` 的产物：结论 + 账目 + 掩码，一次判定、三个视图。

    ⚠️ 所有权（片 1a 的契约，写在这里是因为类型表达不了它）：

    - ``spots`` 是**移交**给装配层的可变条目 —— ``assemble`` 会就地补 ``reach``/``affected``
      （那两样要耗时场与采样点，只有组装层持有，不上搬），所以富化发生在交付之后；
    - ``stats`` 与 ``masks`` 是**判定时刻的快照**，富化不许回头改它们。新增的逐类三张
      （``masks.judgeable`` / ``masks.present`` / ``masks.nearest_m``）同属这份快照 ——
      它们与 ``blind``/``verdict`` 必须出自同一次 ``_verdict_masks``，事后补一张就等于
      把"逐格事实"变成"事后叙述"。

    ``prefix`` 也带在对象上：盲区 id（``bs-{prefix}-{i}``）在判定时刻定型，组装层不许
    拿别的场景名重造一遍。
    """

    spots: List[Dict[str, Any]]
    stats: Dict[str, int]
    masks: JudgeMasks
    grid_m: float
    prefix: str
    # 本次判定实际吃的那把尺（生活圈片 1b）。上对象的理由与 `prefix` 同一条：报告里每条
    # 盲区的 `radius_m` 要报「用过的尺」，而不是让读侧再拿模块常量算一遍 —— 那等于在报告里
    # 宣称一个没人用过的口径。
    radius_m: float

    def __post_init__(self) -> None:
        """构造即校验：账目与掩码必须是**同一次**判定的产物。

        这条不是装饰。片 1a 之后 `stats` 会流到三处（评分、口径举证、契约复算），而掩码会流到
        取证回合 —— 若允许调用方手拼一个 `stats` 缺键、或掩码与账目形状不一致的对象，
        缺的那一键会一路走到 `report_contract` 的读侧变成「静默少一个数」（第十一轮 P0-2）。
        """
        missing = set(STAT_KEYS) - set(self.stats)
        if missing:
            raise ValueError(f"Judgement.stats 缺三态键 {sorted(missing)} —— 五个键是举证的最小集")
        side = int(self.masks.grid.n)
        for name in ("inside", "blind", "verdict", "capped"):
            arr = getattr(self.masks, name)
            if arr.shape != (side, side):
                raise ValueError(
                    f"Judgement.masks.{name} 形状 {arr.shape} 与格阵 n={side} 不符 —— "
                    "掩码与格阵来自两次判定，正是这片要消灭的形状"
                )
        # 逐类三张（逐格台账的数据源）：键集必须一致、形状必须是这次格阵、且**不许自相矛盾**。
        # 类别名不在这里校验 —— 本模块运行期不 import 项目模块（文件头那条无边纪律），
        # 「键集恰等于 TRIAD_KEYS」由生产侧 `blindspot._verdict_masks` 保证。
        keys = set(self.masks.judgeable)
        if not keys or keys != set(self.masks.present) or keys != set(self.masks.nearest_m):
            raise ValueError(
                f"Judgement.masks 三张逐类容器的键集不齐（judgeable={sorted(keys)} "
                f"present={sorted(self.masks.present)} nearest_m={sorted(self.masks.nearest_m)}）"
                " —— 台账会少一类，读者看到的『有据』就是残缺的"
            )
        for key in sorted(keys):
            jd, pr, nm = self.masks.judgeable[key], self.masks.present[key], self.masks.nearest_m[key]
            for label, arr in (("judgeable", jd), ("present", pr), ("nearest_m", nm)):
                if arr.shape != (side, side):
                    raise ValueError(
                        f"Judgement.masks.{label}[{key}] 形状 {arr.shape} 与格阵 n={side} 不符"
                    )
            if pr.dtype != np.int8:
                raise ValueError(
                    f"Judgement.masks.present[{key}] 类型是 {pr.dtype} 而非 int8 —— "
                    "bool 会把「没算过」塌成「算过且没有」，第三态在渲染前就丢了（复审 P0-1）"
                )
            # 三态一致性：判定只对**可达区内**的格求值（区外语义上不该判盲），所以
            # 「有据」的口径是 `inside & judgeable` —— 区外哪怕证据盘盖到了，也从未算过。
            # -1（无从知道）只能出现在这个交集之外；交集内必须给出 0/1，不许留 -1 装没算过。
            asked = self.masks.inside & jd
            if (pr[~asked] != -1).any():
                raise ValueError(
                    f"Judgement.masks.present[{key}] 在从未求值的格上写了 0/1 —— "
                    "「没查过」被写成「查过且没有/有」"
                )
            if (pr[asked] < 0).any():
                raise ValueError(
                    f"Judgement.masks.present[{key}] 在 inside&judgeable 的格上仍是 -1 —— "
                    "有据却没结论，台账会把它读成「无从知道」"
                )
            # 距离同一条纪律的读侧：只有求过值的格才谈得上"最近多少米"。
            if (nm[~asked] >= 0).any():
                raise ValueError(
                    f"Judgement.masks.nearest_m[{key}] 在从未求值的格上有距离 —— "
                    "没查过的格不许带举证距离"
                )
            if (nm[asked] < 0).any():
                raise ValueError(
                    f"Judgement.masks.nearest_m[{key}] 在 inside&judgeable 的格上仍是 -1 —— "
                    "有据却没算距离，说明 `_has_within` 与距离记录不是同一次调用"
                )
        # 半径（片 1b）：正数 + 与每条上屏盲区一致。`spots` 为空时**不许**用「逐条断言」
        # 表达（空集上恒真），所以这里无条件先校 `radius_m` 本身。
        if not self.radius_m > 0:
            raise ValueError(f"Judgement.radius_m 必须是正数米，实得 {self.radius_m!r}")
        for spot in self.spots:
            # 发射端把尺取整（`blindspot.py` 的 `"radius_m": int(radius)`，那是逐字节契约），
            # 而半径的住所类型是 `float` ⇒ 逐位相等会把 800.6m 这档判成"两把尺"、构造即抛、
            # 判定链整条断（第十五轮 P2-1）。容差必须**恰等于发射宽度 1m**：再大就是拿两把
            # 尺当一把，真换了档位（800 vs 1000）就漏了；缺键给的 -1 差得远，照红。
            if abs(float(spot.get("radius_m", -1)) - float(self.radius_m)) >= 1.0:
                raise ValueError(
                    f"盲区 {spot.get('id')!r} 上屏的 radius_m={spot.get('radius_m')} 与本次"
                    f"判定的 {self.radius_m} 不符 —— 报告宣称了一把没人用过的尺"
                )

    @property
    def region(self) -> Optional["EvidenceRegion"]:
        return self.masks.region

    @property
    def grid(self) -> "GridSpec":
        return self.masks.grid

    @property
    def step(self) -> float:
        return self.masks.step
