"""降级判据的**唯一出口**（架构评审 S-5 / 计划 §14 R-1 · 2026-09-22）。

把「该不该降级」与「为什么降级」拆成两层 —— 这是本模块存在的全部理由：

- **触发（trigger）＝数据缺失或不完整**
  ① 等时圈族为空（无法确定可达区）；② POI 全空。
- **归因（detail）＝配额信号**，用于填 ``degraded.detail`` / ``partial.detail`` 与日志。
- **分级（v4 阶段 4 / D1 拍板）**：闸在**哪个阶段**切断，决定后果有多重 ——
  · 测时阶段（`has_poi=None`，几何还没拿到）中止 ⇒ 整份打回离线骨架（旧行为，未变）；
  · **取证阶段**（几何与点位都已拿到）中止 ⇒ **保留 live 几何与盲区，只标 `partial`**。
  理由：降级产出的是「无盲区 + 等时圈退化成 detour_k 正圆」——那是用**一定不出错**
  换掉**本来已经算出来的东西**。多轮取证下预算耗尽是常态且部分结果有价值，
  把常态事件当成整份不可信，等于让报告质量随配额抖动。

⚠️ **为什么不能直接用 ``stats.quota_hits > 0`` 触发**（架构评审 P1-1）：
``quota_hits`` 在**每次失败的 attempt** 上 +1（``request_guard.py:540``），**含随后重试成功的那次**
⇒ 一次瞬时 302/429 + 重试成功就会触发 ⇒ 把一份**数据完整**的报告误降级成离线骨架（过度降级）。

⚠️ **为什么也不能只看「数据为空」**（架构评审 P1-2）：``total_meltdown`` 可能在 POI 采集中途置位
⇒ POI **非空但残缺** ⇒ 只看空会漏 ⇒ 中止信号必须显式参与**测时阶段**的判定；
而取证阶段的残缺改由 `partial` 承载，不再整份打回（D1①）。

⚠️ **能力封顶永不触发任何降级**（D1③）：`cells_unjudgeable_by_cap > 0` 说的是
「接口再快也不给这些货」，与我们的调用预算无关 —— 若把它接进触发条件，
报告就会在接口天花板面前自我打回离线，而离线版本的信息量**更少**。

**阶段从哪来**：不新增 guard 字段，也不靠调用方口头声明 —— 由 `has_poi` 的三态编码：
``None`` = 采集前（还在测时阶段），``True/False`` = 采集后（取证阶段）。
住在这里的关系只有一处，调用点无需知道自己第几阶段。

⚠️ **键必须落在「值」上，不是「属性是否存在」**（硬规则 11）：``budget_exhausted`` 是
``@property``，恒返回 bool、永不缺失 ⇒ ``if x is None`` 式的「缺失才回落」会**永久忽略**老信号
（本仓已因此出过一次回归）。这里一律 ``bool(getattr(...))`` 并用 ``or`` 并联。

对外契约（K11 / 勘误 E17）：``degraded.reason`` **恒为** ``DEGRADE_REASON_QUOTA_EXHAUSTED``
—— 该字面量被 ``test_u18`` / ``test_g09`` 两条用例钉住；细粒度原因只进 ``degraded.detail``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ── 对外唯一降级原因（K11 闭集；新增取值必须同步前端映射表与两条既有用例）──
DEGRADE_REASON_QUOTA_EXHAUSTED = "baidu_quota_exhausted"
DEGRADE_REASONS = (DEGRADE_REASON_QUOTA_EXHAUSTED,)

DEGRADE_NOTE = "百度调用预算耗尽，实时采集被熔断，已降级为离线估算"

# D1①：取证阶段被切断时**不**降级，只声明「部分完成」。与 DEGRADE_NOTE 分名分职：
# 一个说「这份不可信，换骨架」，一个说「这份可信但有些类别没查到」。
PARTIAL_NOTE = "百度调用在取证阶段被熔断：等时圈与已采点位保持实时口径，未采到的类别按证据缺口披露"
# 片 4：取证额度不足**不是**熔断。说成熔断会让读者以为这份报告随时可能整份作废，
# 而真实情况是「按计划只允许打这么多，打完还有格没判出」—— 两者要的话不一样。
PARTIAL_NOTE_FORENSIC = ("取证额度不足（扩容回合的计划份额不够铺完可达区）：等时圈与盲区保持"
                         "实时口径，未判出的格按证据缺口披露，不是接口故障")

# detail → 面向用户的中文标签（供流水线事件文案使用；test_u18 断言文案含「熔断」）
DETAIL_LABELS: Dict[str, str] = {
    "total_meltdown": "总量熔断",
    "daily_budget_exhausted": "日预算熔断",
    "quota_blocked": "配额受限",
    "isochrone_empty": "测时失败",
    "poi_empty": "采集为空",
    # 片 4（v7.0）新来源：**不是**百度掐的，是我们自己给扩容回合那格额度不够铺完需求。
    # 与 `total_meltdown` 分名的理由与 D1 同一条：把「按计划只打了 32 次就收手」演成
    # 「接口崩了」，读者就会以为这份报告随时可能整份作废。
    # ⚠️ 这张表是跨语言夹具（`test_degrade_chain.py` M11 拿它比
    # `frontend/src/__tests__/fixtures/degradeDetailContract.json` 与 `lib/livingCircle.ts`
    # 那份副本）⇒ 加一枚要三处同批加，少一处就红在别人的门上。
    "forensic_pool_short": "取证额度不足",
    "unknown": "配额耗尽",
}


def _flag(guard: Any, name: str) -> bool:
    """读 guard 上的布尔信号。**键在值上**：``bool(...)`` 而非 ``is None``（见模块 docstring）。"""
    return bool(getattr(guard, name, False))


def aborted_by_guard(guard: Any) -> bool:
    """guard 是否**提前中止**（明知数据必然残缺）。"""
    if guard is None:
        return False
    return _flag(guard, "total_meltdown") or _flag(guard, "budget_exhausted")


def degrade_detail(
    guard: Any = None,
    *,
    isochrone_empty: bool = False,
    poi_empty: bool = False,
) -> str:
    """细粒度归因（只用于 ``degraded.detail`` / 日志，**不参与触发**）。"""
    if guard is not None:
        if _flag(guard, "total_meltdown"):
            return "total_meltdown"
        if _flag(guard, "budget_exhausted"):
            return "daily_budget_exhausted"
        hits = getattr(getattr(guard, "stats", None), "quota_hits", 0) or 0
        if int(hits) > 0:
            return "quota_blocked"
    if isochrone_empty:
        return "isochrone_empty"
    if poi_empty:
        return "poi_empty"
    return "unknown"


def degrade_reason(
    guard: Any = None,
    *,
    has_isochrones: bool = True,
    has_poi: Optional[bool] = None,
) -> Optional[str]:
    """是否应**整份打回离线**；不该则返回 ``None``（残缺改由 `partial_for` 承载）。

    参数
    ----
    has_isochrones : 等时圈族是否非空（``False`` ⇒ 必定降级）。
    has_poi : POI 是否非空；``None`` 表示**尚不知道**（测时后、采集前 ⇒ 仍处测时阶段）。

    分级规则（D1）：

    ==========================  ==============================  ==========================
    已拿到                       闸是否中止                       结果
    ==========================  ==============================  ==========================
    等时圈没有                    —                              打回离线（几何无从谈起）
    等时圈有、POI 还不知道         是                             打回离线（测时阶段就被切断）
    等时圈有、POI 有               是                             **不降级**，标 partial
    等时圈有、POI 全空             任意                           打回离线（盲区没有输入）
    ==========================  ==============================  ==========================
    """
    if not has_isochrones:
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    if has_poi is False:
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    if has_poi is None and aborted_by_guard(guard):
        # 还在测时阶段：闸已经落下，拿到的环族随时可能是残缺的一批点插出来的
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    return None


def partial_block(guard: Any, *, stage: str = "forensic",
                  forensic_short: bool = False) -> Dict[str, Any]:
    """构造 ``report["partial"]`` 节点（**唯一实现**）。

    与 `degraded_block` 的区别是这份报告**仍然是 live 的**：等时圈真测过、盲区真判过，
    只是某些类别没查到。归因照旧走 `degrade_detail`，所以「总量熔断 / 日预算 / 配额受限」
    这些字样在两个节点里含义一致。

    **归因优先级只有这一条**（片 4 新增的第二来源带来）：闸真中止 ⇒ 吃闸的 detail；
    闸没事而取证额度不够 ⇒ 才归因「取证额度不足」。反过来的话，一次总量熔断会被写成
    "我们只是把扩容额度用完了" —— 那是把最重的事实说成最轻的，方向错到底。
    """
    detail = degrade_detail(guard)
    note = PARTIAL_NOTE
    if forensic_short and not aborted_by_guard(guard):
        detail = "forensic_pool_short"
        note = PARTIAL_NOTE_FORENSIC
    return {
        "stage": stage,
        "detail": detail,
        "note": note,
    }


def partial_for(guard: Any, *, stage: str = "forensic",
                forensic_short: bool = False) -> Optional[Dict[str, Any]]:
    """该不该标 partial：闸中止过、**或取证回合带着额度缺口收手**才标，否则 ``None``。

    单独一个出口的理由：三个 live 组装点都要做同一件「被切断就把残缺写进报告」的事。
    让每处各写一遍 `if aborted_by_guard(...)` 就是三份实现 —— 漏一处的那份报告就会
    把「有些类别没查到」演成「一次完整取证」。

    `forensic_short` 为什么让调用方交布尔、判据却不住在它那边（复审 P0-4 的闭法）：
    取证池打完**不是** guard 中止，那条事实在 `aborted_by_guard` 上永远读不出来。
    若让每个调用方各自决定「什么算额度缺口」，就会出现三份定义（有人只看 `remaining`、
    有人只看 `aborted`、有人把"没点可打"也算进来）—— 而 `remaining>0 却仍有锚点没打成`
    恰好是前两种唯一分歧的地方。所以调用方只交一条**事实**（本轮收手原因是
    `forensic_pool_short` 这个词表取值），词表 → 残缺 的映射与优先级住在本模块。
    """
    if not aborted_by_guard(guard) and not forensic_short:
        return None
    return partial_block(guard, stage=stage, forensic_short=forensic_short)


def degraded_block(
    guard: Any = None,
    *,
    isochrone_empty: bool = False,
    poi_empty: bool = False,
) -> Dict[str, Any]:
    """构造 ``report["degraded"]`` 节点（**唯一实现**，三入口共用）。"""
    detail = degrade_detail(guard, isochrone_empty=isochrone_empty, poi_empty=poi_empty)
    return {
        "reason": DEGRADE_REASON_QUOTA_EXHAUSTED,
        "detail": detail,
        "note": DEGRADE_NOTE,
    }


def detail_label(detail: str) -> str:
    """detail → 中文标签（未知取值回落 ``unknown`` 的标签，不抛异常）。"""
    return DETAIL_LABELS.get(detail, DETAIL_LABELS["unknown"])
