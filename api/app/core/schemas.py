"""目的地知识结构化 Schema（对应需求 11/13/14：结构化消息 + 字段完整 + 引用强制）。

按调研类型提供核心知识对象（键集来自 research_types 注册表 spec["structured_keys"]）：
- guide 游玩攻略：景点榜单/美食榜单/逐景点路线/商铺清单 + 逐日路线 / 住宿选项 / 花费拆解
- assessment 调研评估：可达性矩阵 / 配套清单 / 风险画像

每个对象配 coerce_*(raw, valid_evidence_ids) 容错器：丢弃非法字段、过滤不在证据集内的
evidence_ids（引用强制 = 幻觉抑制），保证输出严格符合 Schema、字段完整、格式一致。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def _bool(v, default: Optional[bool] = None) -> Optional[bool]:
    return v if isinstance(v, bool) else default


def _filter_eids(raw, valid: set) -> List[str]:
    return [e for e in _as_list(raw) if isinstance(e, str) and e in valid]


def _dest_of(it: Dict[str, Any]) -> str:
    """对象主键：目的地名（兼容 LLM 偶发沿用旧键 brand 的情况）。"""
    return _str(it.get("destination")) or _str(it.get("brand")) or _str(it.get("name"))


def _children(it: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [c for c in _as_list(it.get(key)) if isinstance(c, dict)]


def _slug(dest: str) -> str:
    """spot_id/food_id/shop_id 前缀：目的地名去空白（实体名保留中文，稳定即可）。"""
    return "".join(dest.split()) or "dest"


# ── 游玩攻略 guide ────────────────────────────────────────
def coerce_route_plan(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, days:[{day, spots:[{name,spot_id,lat,lng,transport,duration,tip,shop_id,evidence_ids}]}]}]
    —— spot_id/shop_id 为实体挂接键（M3a 一页视图由规则组装、引用冻结实体表；缺省空串占位）。"""
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
                    "spot_id": _str(sp.get("spot_id")),
                    # 坐标随实体挂接透传（N6 分布图数据源；规则组装自冻结实体带入，LLM 版留 None）
                    "lat": _num(sp.get("lat")),
                    "lng": _num(sp.get("lng")),
                    "transport": _str(sp.get("transport")),
                    "duration": _str(sp.get("duration")),
                    "tip": _str(sp.get("tip")),
                    "shop_id": _str(sp.get("shop_id")),
                    "evidence_ids": _filter_eids(sp.get("evidence_ids"), valid),
                })
            day = _int(d.get("day"))
            if day is None and not spots:
                continue
            days.append({"day": day if day is not None else len(days) + 1, "spots": spots})
        out.append({"destination": dest, "days": [d for d in days if d["spots"] or d["day"]]})
    return out


_STAY_RANGE_SEP = re.compile(r"\d\s*[-~～–—]|(?:到|至)")
_STAY_UPPER = re.compile(r"以内|以下|不超过|封顶")
_STAY_LOWER = re.compile(r"起|以上")


def _price_bounds(text: Any) -> Tuple[Optional[int], Optional[int]]:
    """住宿价格自由文本 → (price_min, price_max) 数值判据（N5，不造数）：
    "300-500"→(300,500)；"约800起"→(800,None)；"500以内"→(None,500)；
    单一数字→两端同值；乱码/无数字/区间倒挂→(None,None)。"""
    s = _str(text).replace("￥", "").replace("¥", "").replace("元", "").replace(",", "")
    nums = [_int(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    nums = [n for n in nums if n is not None]
    if not nums:
        return None, None
    if len(nums) >= 2 and _STAY_RANGE_SEP.search(s):
        lo, hi = nums[0], nums[1]
        return (None, None) if lo > hi else (lo, hi)
    if _STAY_UPPER.search(s):
        return None, nums[0]
    if _STAY_LOWER.search(s):
        return nums[0], None
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def coerce_stay_options(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, areas:[{area,price_range,price_min,price_max,for_whom,pros,cons,evidence_ids}]}]
    —— price_min/max 为 N5 价位带数值：优先 LLM 显式产出，缺失/非法时由 price_range 文本按判据派生。"""
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
            price_range = _str(a.get("price_range"))
            lo = _int(a.get("price_min"))
            hi = _int(a.get("price_max"))
            if lo is None and hi is None:
                lo, hi = _price_bounds(price_range)
            elif lo is not None and hi is not None and lo > hi:
                lo, hi = None, None  # LLM 产出倒挂：判据否决，不造数
            areas.append({
                "area": area,
                "price_range": price_range,
                "price_min": lo,
                "price_max": hi,
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


# ── 景点实体与榜单 guide（M1 契约先行：lat/lng/matched 允许为空，M2 由实体解析填充）──
def _signals_of(e: Dict[str, Any]) -> Dict[str, float]:
    """三类规范信号 {voice,sentiment,value}：优先取 scoring 产出的 signals_clean，
    回落兼容 LLM 原始字段名（voice|mentions / sentiment|positive_ratio / value|value_score）。"""
    clean = e.get("signals_clean")
    if isinstance(clean, dict):
        return {k: (_num(clean.get(k)) or 0.0) for k in ("voice", "sentiment", "value")}
    sig = e.get("signals") if isinstance(e.get("signals"), dict) else e
    return {
        "voice": _num(sig.get("voice")) or _num(sig.get("mentions")) or 0.0,
        "sentiment": _num(sig.get("sentiment")) or _num(sig.get("positive_ratio")) or 0.0,
        "value": _num(sig.get("value")) or _num(sig.get("value_score")) or 0.0,
    }


def coerce_spot_ranking(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{spot_id,name,area,lat,lng,matched,signals,score,rank,
    reason,ticket,stay_minutes,off_peak,evidence_ids}]}]；spot_id 缺省按序号稳定生成。"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("spot_ranking") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        children = _children(it, "items") or _children(it, "spots") or _children(it, "spots_ranking")
        for e in children:
            name = _str(e.get("name")) or _str(e.get("spot"))
            if not name:
                continue
            rows.append({
                "spot_id": _str(e.get("spot_id")) or f"{_slug(dest)}_spot_{len(rows) + 1}",
                "name": name,
                "area": _str(e.get("area")),
                "lat": _num(e.get("lat")),
                "lng": _num(e.get("lng")),
                "matched": _bool(e.get("matched")),
                "signals": _signals_of(e),
                "dims": ({k: _num(d.get(k)) or 0.0 for k in ("voice", "sentiment", "value")}
                         if (d := e.get("dims")) and isinstance(d, dict) else None),
                "score": _num(e.get("score")),
                "rank": _int(e.get("rank")) or len(rows) + 1,
                "reason": _str(e.get("reason")),
                "ticket": _str(e.get("ticket")),
                "stay_minutes": _int(e.get("stay_minutes")),
                "off_peak": _str(e.get("off_peak")),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


def coerce_food_ranking(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{food_id,name,category,reason,price_range,evidence_ids}]}]"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("food_ranking") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        for e in _children(it, "items") or _children(it, "dishes"):
            name = _str(e.get("name")) or _str(e.get("food"))
            if not name:
                continue
            rows.append({
                "food_id": _str(e.get("food_id")) or f"{_slug(dest)}_food_{len(rows) + 1}",
                "name": name,
                "category": _str(e.get("category")),
                "reason": _str(e.get("reason")),
                "price_range": _str(e.get("price_range")),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


def _norm_routes(e: Dict[str, Any], key: str, valid: set) -> List[Dict[str, Any]]:
    """路线子表规整（spot_routes 与 shop_list 共用）：mode 小写非空才收，字段固定六项。"""
    routes = []
    for r in _children(e, key):
        mode = _str(r.get("mode")).lower()
        if not mode:
            continue
        routes.append({
            "mode": mode,
            "duration": _str(r.get("duration")),
            "cost": _str(r.get("cost")),
            "transfer": _str(r.get("transfer")),
            "note": _str(r.get("note")),
            "evidence_ids": _filter_eids(r.get("evidence_ids"), valid),
        })
    return routes


def coerce_spot_routes(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{spot_id,spot_name,routes:[{mode,duration,cost,transfer,note,evidence_ids}]}]}]
    —— 路线按 spot_id 挂接景点实体，mode ∈ transit/bus/subway/taxi/driving/walking。"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("spot_routes") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        children = _children(it, "items") or _children(it, "spots")
        for e in children:
            name = _str(e.get("spot_name")) or _str(e.get("name"))
            if not name:
                continue
            routes = _norm_routes(e, "routes", valid)
            rows.append({
                "spot_id": _str(e.get("spot_id")),
                "spot_name": name,
                "routes": routes,
            })
        out.append({"destination": dest, "items": rows})
    return out


def coerce_shop_list(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, items:[{shop_id,food,name,area,price_per_person,queue_note,matched,lat,lng,routes,evidence_ids}]}]
    —— price_per_person 为「参考价」；POI 实体（matched/坐标）与 routes（真实公交路线）由编排层回填。"""
    valid = valid_eids or set()
    items = raw if isinstance(raw, list) else (raw.get("shop_list") if isinstance(raw, dict) else None)
    out: List[Dict[str, Any]] = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        dest = _dest_of(it)
        if not dest:
            continue
        rows = []
        for e in _children(it, "items") or _children(it, "shops"):
            name = _str(e.get("name")) or _str(e.get("shop"))
            if not name:
                continue
            rows.append({
                "shop_id": _str(e.get("shop_id")) or f"{_slug(dest)}_shop_{len(rows) + 1}",
                "food": _str(e.get("food")),
                "name": name,
                "area": _str(e.get("area")),
                "price_per_person": _num(e.get("price_per_person")),
                "queue_note": _str(e.get("queue_note")),
                "matched": _bool(e.get("matched")),
                "lat": _num(e.get("lat")),
                "lng": _num(e.get("lng")),
                "routes": _norm_routes(e, "routes", valid),
                "evidence_ids": _filter_eids(e.get("evidence_ids"), valid),
            })
        out.append({"destination": dest, "items": rows})
    return out


# ── 调研评估 assessment ───────────────────────────────────
def coerce_access_matrix(raw: Any, valid_eids: Optional[set] = None) -> List[Dict[str, Any]]:
    """规整为 [{destination, routes:[{mode,duration,cost,frequency,note,[duration_minutes],[cost_yuan],evidence_ids}]}]

    duration_minutes / cost_yuan 是**可选**数值字段（供确定性算分消费）：无法从证据
    确证时省略键而非填 0——「未知」与「0 元/0 分钟」在降级契约里语义不同（缺字段
    则该交通方式不计分，0 会污染均分）。原 duration/cost 文本字段原样保留用于展示。
    """
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
            route = {
                "mode": mode,
                "duration": _str(r.get("duration")),
                "cost": _str(r.get("cost")),
                "frequency": _str(r.get("frequency")),
                "note": _str(r.get("note")),
                "evidence_ids": _filter_eids(r.get("evidence_ids"), valid),
            }
            dm = _num(r.get("duration_minutes"))
            if dm is not None and dm > 0:
                route["duration_minutes"] = round(dm, 1)
            cy = _num(r.get("cost_yuan"))
            if cy is not None and cy > 0:
                route["cost_yuan"] = round(cy, 1)
            routes.append(route)
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
    "spot_ranking": coerce_spot_ranking,
    "food_ranking": coerce_food_ranking,
    "spot_routes": coerce_spot_routes,
    "shop_list": coerce_shop_list,
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
                        research_type: str = RT.DEFAULT_RESEARCH_TYPE,
                        perspective_section_id: str = "") -> float:
    """估算该类型全部结构化对象的填充率（0-1），供质检与一致性指标用。
    分母 = `structured_keys_for` 的**本卷有效键集**（类型基础键 + 视角命中时追加的
    视角键），随类型、视角与改造演进，不硬编码——非视角卷分母逐值不变（评审 P0-1）。"""
    keys = RT.structured_keys_for(research_type, perspective_section_id)
    filled = sum(1 for k in keys
                 if any(_has_content(b) for b in (structured.get(k) or []) if isinstance(b, dict)))
    expected = len(keys)
    return round(min(filled, expected) / expected, 3) if expected else 0.0
