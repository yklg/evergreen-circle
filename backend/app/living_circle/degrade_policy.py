"""降级判据的**唯一出口**（架构评审 S-5 / 计划 §14 R-1 · 2026-09-22）。

把「该不该降级」与「为什么降级」拆成两层 —— 这是本模块存在的全部理由：

- **触发（trigger）＝数据缺失或不完整**
  ① 等时圈族为空（无法确定可达区）；② POI 全空；③ guard **提前中止**
  （``total_meltdown`` / ``budget_exhausted``）。
- **归因（detail）＝配额信号**，**只用于填 ``degraded.detail`` 与日志，不单独触发**。

⚠️ **为什么不能直接用 ``stats.quota_hits > 0`` 触发**（架构评审 P1-1）：
``quota_hits`` 在**每次失败的 attempt** 上 +1（``request_guard.py:540``），**含随后重试成功的那次**
⇒ 一次瞬时 302/429 + 重试成功就会触发 ⇒ 把一份**数据完整**的报告误降级成离线骨架（过度降级）。

⚠️ **为什么也不能只看「数据为空」**（架构评审 P1-2）：``total_meltdown`` 可能在 POI 采集中途置位
⇒ POI **非空但残缺** ⇒ 只看空会漏 ⇒ 触发条件必须显式包含「提前中止」。

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

# detail → 面向用户的中文标签（供流水线事件文案使用；test_u18 断言文案含「熔断」）
DETAIL_LABELS: Dict[str, str] = {
    "total_meltdown": "总量熔断",
    "daily_budget_exhausted": "日预算熔断",
    "quota_blocked": "配额受限",
    "isochrone_empty": "测时失败",
    "poi_empty": "采集为空",
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
    """是否应降级；不降级返回 ``None``。

    参数
    ----
    has_isochrones : 等时圈族是否非空（``False`` ⇒ 必定降级）。
    has_poi : POI 是否非空；``None`` 表示**尚不知道**（测时后、采集前 ⇒ 不判这一项）。
    """
    if aborted_by_guard(guard):
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    if not has_isochrones:
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    if has_poi is False:
        return DEGRADE_REASON_QUOTA_EXHAUSTED
    return None


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
