"""旅游引擎内部共享纯工具（M3 逐模块提取 · 第一批）。

只放**零 app 依赖、零模块级可变状态**的纯函数：时间/id、数值容忍、目的地行键归一。
charts_build 与 engine（以及后续 extract 的 sanitize/structured 模块）共同消费，
避免子模块反向 import engine 造成循环依赖。
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid
from typing import Any, Dict, List, Optional


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _clamp_int(v, lo: int = 0, hi: int = 100) -> Optional[int]:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _num_or_none(v) -> Optional[float]:
    if isinstance(v, str):
        v = (v.replace("￥", "").replace("¥", "").replace("元", "")
             .replace(",", "").replace("/月", "").strip())
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _core_name(name: Any) -> str:
    """比对用的核心名：**只剥「市」**。剥「省/自治区/特别行政区」会把「吉林省」并到「吉林市」；
    剩余不足 2 字不剥（「市」本身不是地名）。"""
    s = str(name or "").strip()
    if s.endswith("市") and len(s) >= 3:
        return s[:-1]
    return s


def _norm_spot_name(name: Any) -> str:
    return re.sub(r"[（(].*?[）)]|[\s・·\-—]", "", str(name or "")).lower()


def _name_hit(want: str, got: Any) -> bool:
    a, b = _norm_spot_name(want), _norm_spot_name(got)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _row_name(it: Dict[str, Any]) -> str:
    """行主键：目的地名（兼容 LLM 偶发写成 name/brand 的情况，避免整行丢失）。"""
    return str(it.get("destination") or it.get("brand") or it.get("name") or "").strip()


def _row_dest_ok(name: Any, destinations: List[str]) -> bool:
    """行主键是否属于本次调研目的地（兼容「大理↔大理市」这类行政名变体）。"""
    core = _core_name(str(name or "").strip())
    if not core:
        return False
    return any(_name_hit(core, _core_name(d)) for d in destinations)
