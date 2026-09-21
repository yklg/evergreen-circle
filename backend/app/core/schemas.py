"""目的地知识结构化 Schema（对应需求 11/13/14：结构化消息 + 字段完整 + 引用强制）。

按调研类型提供 3 个核心知识对象（键集来自 research_types 注册表 spec["structured_keys"]）：
- guide 游玩攻略：逐日路线 / 住宿选项 / 花费拆解
- assessment 调研评估：可达性矩阵 / 配套清单 / 风险画像

每个对象配 coerce_*(raw, valid_evidence_ids) 容错器：丢弃非法字段、过滤不在证据集内的
evidence_ids（引用强制 = 幻觉抑制），保证输出严格符合 Schema、字段完整、格式一致。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.core import research_types as RT


def _as_list(v) -> list:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def _str(v, default: str = "") -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) else default


def _num(v) -> Optional[float]:
    if isinstance(v, str):
        v = (v.replace("￥", "").replace("¥", "").replace("元", "")
             .replace(",", "").replace("%", "").strip())
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(round(n)) if n is not None else None


def _filter_eids(raw, valid: set) -> List[str]:
    return [e for e in _as_list(raw) if isinstance(e, str) and e in valid]


def _dest_of(it: Dict[str, Any]) -> str:
    """对象主键：目的地名（兼容 LLM 偶发沿用旧键 brand 的情况）。"""
    return _str(it.get("destination")) or _str(it.get("brand")) or _str(it.get("name"))


def _children(it: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [c for c in _as_list(it.get(key)) if isinstance(c, dict)]


# ── 游玩攻略 guide ────────────────────────────────────────
def coerce_route_plan(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, days:[{day, spots:[{name,transport,duration,tip,evidence_ids}]}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("route_plan") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        days = []
        for d in _children(it, "days"):
            spots = []
            for sp in _children(d, "spots"):
                name = _str(sp.get("name"))
                if not name:
                    continue
                spots.append({
                    "name": name,
                    "transport": _str(sp.get("transport")),
                    "duration": _str(sp.get("duration")),
                    "tip": _str(sp.get("tip")),
                    "evidence_ids": _filter_eids(sp.get("evidence_ids"), valid),
                })
            day = _int(d.get("day"))
            if day is None and not spots:
                continue
            days.append({"day": day if day is not None else len(days) + 1, "spots": spots})
        out.append({"destination": dest, "days": [d for d in days if d["spots"] or d["day"]]})
    return out


def coerce_stay_options(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, areas:[{area,price_range,for_whom,pros,cons,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("stay_options") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        areas = []
        for a in _children(it, "areas"):
            area = _str(a.get("area"))
            if not area:
                continue
            areas.append({
                "area": area,
                "price_range": _str(a.get("price_range")),
                "for_whom": _str(a.get("for_whom")),
                "pros": [_str(x) for x in _as_list(a.get("pros")) if _str(x)],
                "cons": [_str(x) for x in _as_list(a.get("cons")) if _str(x)],
                "evidence_ids": _filter_eids(a.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "areas": areas})
    return out


def coerce_cost_breakdown(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{category,amount,unit,share,note,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("cost_breakdown") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        for e in _children(it, "items"):
            cat = _str(e.get("category"))
            amount = _num(e.get("amount"))
            if not cat or amount is None:
                continue
            rows.append({
                "category": cat,
                "amount": amount,
                "unit": _str(e.get("unit"), "元/人"),
                "share": _num(e.get("share")),
                "note": _str(e.get("note")),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


# ── 调研评估 assessment ───────────────────────────────────
def coerce_access_matrix(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, routes:[{mode,duration,cost,frequency,note,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("access_matrix") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        routes = []
        for r in _children(it, "routes"):
            mode = _str(r.get("mode"))
            if not mode:
                continue
            routes.append({
                "mode": mode,
                "duration": _str(r.get("duration")),
                "cost": _str(r.get("cost")),
                "frequency": _str(r.get("frequency")),
                "note": _str(r.get("note")),
                "evidence_ids": _filter_eids(r.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "routes": routes})
    return out


def coerce_amenity_checklist(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{category,item,coverage,note,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("amenity_checklist") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        for e in _children(it, "items"):
            name = _str(e.get("item"))
            if not name:
                continue
            coverage = _str(e.get("coverage"), "partial").lower()
            if coverage not in ("full", "partial", "none"):
                coverage = "partial"
            rows.append({
                "category": _str(e.get("category")),
                "item": name,
                "coverage": coverage,
                "note": _str(e.get("note")),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


def coerce_risk_profile(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{dimension,level,note,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("risk_profile") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        for e in _children(it, "items"):
            dim = _str(e.get("dimension"))
            if not dim:
                continue
            level = _str(e.get("level"), "medium").lower()
            if level not in ("low", "medium", "high"):
                level = "medium"
            rows.append({
                "dimension": dim,
                "level": level,
                "note": _str(e.get("note")),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


_COERCERS: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "route_plan": coerce_route_plan,
    "stay_options": coerce_stay_options,
    "cost_breakdown": coerce_cost_breakdown,
    "access_matrix": coerce_access_matrix,
    "amenity_checklist": coerce_amenity_checklist,
    "risk_profile": coerce_risk_profile,
}


def coerce_structured(raw: Any, research_type: str = RT.DEFAULT_RESEARCH_TYPE,
                      valid_eids: Optional[set] = None) -> Dict[str, List[Dict[str, Any]]]:
    """按类型注册表把 LLM 原始输出规整为 {structured_key: [...]}（未知键不产出）。"""
    keys = RT.type_spec(research_type)["structured_keys"]
    return {k: _COERCERS[k](raw, valid_eids or set()) for k in keys if k in _COERCERS}


def _has_content(item: Dict[str, Any]) -> bool:
    """对象是否含实质内容（任一子列表非空）——不硬编码字段名，新增对象自动适用。"""
    for k, v in item.items():
        if k != "evidence_ids" and isinstance(v, list) and v:
            return True
    return False


def schema_completeness(structured: Dict[str, Any],
                        research_type: str = RT.DEFAULT_RESEARCH_TYPE) -> float:
    """估算该类型三类 Schema 的字段填充率（0-1），供质检与一致性指标用。"""
    keys = RT.type_spec(research_type)["structured_keys"]
    filled = sum(1 for k in keys
                 if any(_has_content(b) for b in (structured.get(k) or []) if isinstance(b, dict)))
    expected = 3
    return round(min(filled, expected) / expected, 3) if expected else 0.0
