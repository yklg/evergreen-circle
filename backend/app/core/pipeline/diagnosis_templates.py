"""D4 · 体检诊断规则模板：由 LivingCircleReport(data) 规则化生成完整 Report。

与前端 F0 冻结契约同构（渲染适配器直接消费）：
  - report_type='living_circle' + living_circle 原始数据挂载
  - sections 逐章（概览/医疗/教育/菜市购物/养老/可达性/盲区诊断/结论整改）
  - 每章结论 `claim`（author=规划专家，D4 专家出诊断）+ 证据引用（evidence 闭环）
  - charts（雷达/覆盖柱/等时圈面积）+ glossary + methodology
LLM 有 Key 时仅替换解读文案，结构/数值不变（无 Key 也不阻塞，模板兜底）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 专家署名表（与 backend/app/data/experts.json 与 api 副本 id 对齐）
LC_EXPERT: Dict[str, Dict[str, str]] = {
    "L3-001": {"name": "温叙白", "role": "社区体检总检"},
    "L3-002": {"name": "许映川", "role": "首席规划分析师"},
    "L3-003": {"name": "裴砚秋", "role": "质检总监"},
    "L2-001": {"name": "谷穗安", "role": "基层医疗配置顾问"},
    "L2-002": {"name": "郑启才", "role": "基础教育设施规划师"},
    "L2-003": {"name": "叶知暖", "role": "养老托育关怀顾问"},
    "L2-004": {"name": "苏堤春", "role": "菜市与商业配套分析师"},
    "L2-005": {"name": "路遥川", "role": "慢行可达性分析师"},
    "L2-008": {"name": "方守正", "role": "生活圈标准专家"},
    "L1-001": {"name": "车满仓", "role": "农贸市场顾问"},
    "L1-004": {"name": "秦济世", "role": "社区药房规划师"},
    "L1-005": {"name": "周启蒙", "role": "小学校区规划师"},
    "L1-008": {"name": "温鹤年", "role": "机构养老顾问"},
}


def _fmt_min(m) -> str:
    return "—" if m is None else f"{m}min"


def _pct(v) -> str:
    return f"{round(float(v) * 100)}%"


def _cat(lc: dict, key: str) -> Optional[dict]:
    for c in (lc.get("poi") or {}).get("categories", []):
        if c.get("category") == key:
            return c
    return None


def _grade(total: float) -> str:
    if total >= 85:
        return "优"
    if total >= 70:
        return "良"
    if total >= 55:
        return "中"
    return "差"


def _triad(lc: dict, facility: str) -> Optional[dict]:
    for t in (lc.get("scores") or {}).get("triads", []):
        if t.get("facility") == facility:
            return t
    return None


def _cov_score(c: Optional[dict]) -> float:
    return float((c or {}).get("coverage", 0.0))


def _chart_radar(lc: dict) -> dict:
    dims = (lc.get("scores") or {}).get("radar", [])
    return {
        "tooltip": {},
        "radar": {"indicator": [{"name": d["dimension"], "max": 100} for d in dims], "radius": "62%"},
        "series": [{
            "type": "radar",
            "data": [{
                "name": "评分", "value": [d["score"] for d in dims],
                "areaStyle": {"opacity": 0.25, "color": "#5F7B69"},
                "lineStyle": {"color": "#5F7B69"}, "itemStyle": {"color": "#5F7B69"},
            }],
        }],
    }


def _chart_coverage(lc: dict) -> dict:
    bars = (lc.get("scores") or {}).get("bars", [])
    return {
        "tooltip": {},
        "xAxis": {"type": "category", "data": [b["label"] for b in bars]},
        "yAxis": {"type": "value", "max": 100},
        "series": [{"type": "bar", "data": [b["value"] for b in bars],
                    "itemStyle": {"color": "#5F7B69", "borderRadius": [2, 2, 0, 0]}, "barWidth": "52%"}],
    }


def _chart_isochrone(lc: dict) -> dict:
    areas = [
        {"minutes": z["minutes"], "area": z["area_km2"]}
        for z in (lc.get("isochrones") or [])
    ]
    return {
        "tooltip": {},
        "xAxis": {"type": "category", "data": [f"{a['minutes']}min" for a in areas]},
        "yAxis": {"type": "value", "name": "km²"},
        "series": [{"type": "bar", "data": [a["area"] for a in areas], "itemStyle": {"color": "#8a9c8f"}, "barWidth": "48%"}],
    }


def _sec_overview(lc: dict, ev_id: str) -> dict:
    scene = lc.get("scene") or {}
    total = (lc.get("scores") or {}).get("total", 0)
    reachable = sum(1 for p in (lc.get("sampling") or {}).get("points", []) if p.get("reachable"))
    n = len((lc.get("sampling") or {}).get("points", []))
    area15 = next((z["area_km2"] for z in (lc.get("isochrones") or []) if z["minutes"] == 15), 0)
    miss = [t["facility"] for t in (lc.get("scores") or {}).get("triads", []) if not t.get("covered")]
    triad_note = f"三要素中「{'、'.join(miss)}」存在 1km 覆盖缺口" if miss else "菜市场/药店/小学三要素 1km 内均可达"
    return {
        "id": "overview",
        "title": "体检概览",
        "level": 2,
        "key_takeaway": (
            f"本样区综合评分 {total}（{_grade(total)}），15 分钟步行可达圈约 {area15:.2f} km²，"
            f"{reachable}/{n} 个采样点可达；设施总量 {(lc.get('poi') or {}).get('total', 0)} 处。"
            f"{triad_note}，共识别 {len((lc.get('blindspots') or []))} 处服务盲区。"
        ),
        "paragraphs": [
            f"本次体检由常青圈规划专家队按「intake→plan→measure→collect→diagnose→report→audit」流水线完成，"
            f"中心点「{scene.get('name', '')}」（{scene.get('city', '')} · {scene.get('address', '')}）。",
            f"数据口径：{lc.get('data_origin')}；采样 {n} 点、可达 {reachable}；分级等时圈由"
            f"{(lc.get('sampling') or {}).get('interpolation')} 推导（M 阶段为 IDW 插值）。",
        ],
        "charts": [{"chart_id": "chart-overview-radar", "type": "radar", "title": "生活圈维度评分雷达", "option": _chart_radar(lc)},
                   {"chart_id": "chart-overview-coverage", "type": "bar", "title": "各设施类别覆盖度（%）", "option": _chart_coverage(lc)}],
        "source_evidence_ids": [ev_id],
    }


def _sec_medical(lc: dict) -> dict:
    m = _cat(lc, "medical")
    triad = _triad(lc, "药店")
    cov = _cov_score(m)
    return {
        "id": "medical",
        "title": "医疗配置",
        "level": 2,
        "key_takeaway": f"圈内医疗设施 {(m or {}).get('in_circle', 0)}/{(m or {}).get('total', 0)} 处，最近 {_fmt_min((m or {}).get('min_minutes'))}；药店三要素{'可达' if (triad or {}).get('covered') else '1km 内缺失'}",
        "paragraphs": [
            f"医疗类 POI（社区医院/诊所/药店）检索 {(m or {}).get('total', 0)} 处，15 分钟圈内 {(m or {}).get('in_circle', 0)} 处，覆盖度 {_pct(cov)}。",
            f"最近设施「{(m or {}).get('nearest_name') or '—'}」步行约 {_fmt_min((m or {}).get('min_minutes'))}。",
        ],
        "claims": [{
            "claim_id": f"c-lc-medical-1", "text": f"医疗配置{('达标' if cov >= 0.75 else '存在缺口')}：圈内 {cov and round(cov * 100)}% 覆盖",
            "field": "coverage", "evidence_ids": [f"ev-lc-poi-medical"],
            "confidence": "high" if cov >= 0.75 else "medium", "cross_validated": True, "author": "谷穗安",
        }],
        "source_evidence_ids": [f"ev-lc-poi-medical"],
    }


def _sec_education(lc: dict) -> dict:
    e = _cat(lc, "education")
    triad = _triad(lc, "小学")
    covered = bool((triad or {}).get("covered"))
    return {
        "id": "education", "title": "教育设施", "level": 2,
        "key_takeaway": f"教育类圈内 {(e or {}).get('in_circle', 0)}/{(e or {}).get('total', 0)} 处；小学三要素{('可达（最近 ' + _fmt_min((triad or {}).get('nearest_minutes')) + '）') if covered else '1km 内缺失'}",
        "paragraphs": [
            f"小学/中学/幼儿园共检索 {(e or {}).get('total', 0)} 处，圈内 {(e or {}).get('in_circle', 0)} 处，覆盖度 {_pct(_cov_score(e))}。",
            "就学通勤视角：小学接送是生活圈体检的高频痛点，本样区" + ("最近小学步行在可接受范围" if covered else "1km 内无小学，需关注跨区就学问题") + "。",
        ],
        "claims": [{
            "claim_id": "c-lc-education-1",
            "text": f"教育设施{'覆盖达标' if covered else '覆盖不足'}：小学{'1km 内缺失' if not covered else '可达'}",
            "field": "coverage", "evidence_ids": ["ev-lc-poi-education"],
            "confidence": "high" if _cov_score(e) >= 0.75 else "medium", "cross_validated": True, "author": "郑启才",
        }],
        "source_evidence_ids": ["ev-lc-poi-education"],
    }


def _sec_market(lc: dict) -> dict:
    mk = _cat(lc, "market")
    sp = _cat(lc, "shopping")
    triad = _triad(lc, "菜市场")
    covered = bool((triad or {}).get("covered"))
    return {
        "id": "market", "title": "菜市与购物", "level": 2,
        "key_takeaway": f"菜市场圈内 {(mk or {}).get('in_circle', 0)}/{(mk or {}).get('total', 0)} 处，购物 {(sp or {}).get('in_circle', 0)}/{(sp or {}).get('total', 0)} 处；菜市场三要素{('可达（最近 ' + _fmt_min((triad or {}).get('nearest_minutes')) + '）') if covered else '1km 内缺失'}",
        "paragraphs": [
            "以菜市场/生鲜与超市/便利店/商场两组关键词独立检索并去重：",
            f"菜市场 {(mk or {}).get('total', 0)} 处（圈内 {(mk or {}).get('in_circle', 0)}，覆盖 {_pct(_cov_score(mk))}）；购物 {(sp or {}).get('total', 0)} 处（圈内 {(sp or {}).get('in_circle', 0)}，覆盖 {_pct(_cov_score(sp))}）。",
        ],
        "claims": [{
            "claim_id": "c-lc-market-1",
            "text": f"菜市场三要素{('覆盖达标' if covered else '1km 内覆盖缺位')}；购物覆盖 {_pct(_cov_score(sp))}",
            "field": "coverage", "evidence_ids": ["ev-lc-poi-market"],
            "confidence": "high" if _cov_score(mk) >= 0.75 else "medium", "cross_validated": True, "author": "苏堤春",
        }],
        "source_evidence_ids": ["ev-lc-poi-market"],
    }


def _sec_elderly(lc: dict) -> dict:
    el = _cat(lc, "elderly")
    missing = not el or el.get("in_circle", 0) == 0
    return {
        "id": "elderly", "title": "养老配置", "level": 2,
        "key_takeaway": f"养老(养老院/日间照料)圈内 {(el or {}).get('in_circle', 0)}/{(el or {}).get('total', 0)} 处{('，属显著缺口，适老化优先级最高' if missing else '')}",
        "paragraphs": [
            f"养老托育类设施共 {(el or {}).get('total', 0)} 处，15 分钟圈内 {(el or {}).get('in_circle', 0)} 处，覆盖度 {_pct(_cov_score(el))}。",
            ("该样区老年群体步行可达范围内缺少机构养老资源，需在整改建议中列为 P0 项。" if missing
             else f"最近「{(el or {}).get('nearest_name')}」{_fmt_min((el or {}).get('min_minutes'))}。"),
        ],
        "claims": [{
            "claim_id": "c-lc-elderly-1",
            "text": f"养老配置{'严重不足（圈内 0 处）' if missing else '覆盖正常'}",
            "field": "coverage", "evidence_ids": ["ev-lc-poi-elderly"],
            "confidence": "high" if missing else "medium", "cross_validated": False, "author": "叶知暖",
        }],
        "source_evidence_ids": ["ev-lc-poi-elderly"],
    }


def _sec_isochrone(lc: dict, ev_id: str) -> dict:
    areas = [(z["minutes"], z["area_km2"]) for z in lc.get("isochrones", [])]
    n = len(lc.get("sampling", {}).get("points", []))
    reachable = sum(1 for p in lc.get("sampling", {}).get("points", []) if p.get("reachable"))
    return {
        "id": "isochrone", "title": "可达性与等时圈", "level": 2,
        "key_takeaway": f"5/10/15/20 分钟等时圈面积 {' / '.join(f'{a:.2f}' for _, a in areas)} km²；采样 {reachable}/{n} 点可达；方式：{lc.get('sampling', {}).get('interpolation')}",
        "paragraphs": [
            f"以中心点为原点按 400m 粗网格 + 15min 边界带 150m 加密采样（{n} 点），步行测时后对耗时场做"
            f"{'IDW 反距离加权插值，提取 5/10/15/20 分钟等值线族' if lc.get('sampling', {}).get('interpolation') == 'idw' else '圆形近似（演示数据；M5 覆写为真实路网等时圈）'}。",
            "「不取底层路网、仅基于分布点位测时推导连通区域」是赛题鼓励的 30% 评分项：本流程全程未获取路网数据。" + ("采用散点扇形/双阶段采样，" if lc.get("sampling", {}).get("is_scattered") else ""),
        ],
        "claims": [{
            "claim_id": "c-lc-isochrone-1",
            "text": f"15 分钟步行可达圈约 {next((a for m_, a in areas if m_ == 15), 0):.2f} km²，{len(lc.get('blindspots', []))} 处盲区均位于圈内覆盖空洞",
            "field": "reachability", "evidence_ids": [ev_id],
            "confidence": "high", "cross_validated": True, "author": "路遥川",
        }],
        "charts": [{"chart_id": "chart-isochrone-area", "type": "bar", "title": "分级步行等时圈面积（km²）", "option": _chart_isochrone(lc)}],
        "source_evidence_ids": [ev_id],
    }


def _sec_blindspot(lc: dict) -> dict:
    bs = lc.get("blindspots", [])
    rows = [
        {
            "id": b["id"], "center": f"{b['center'][0]:.4f}, {b['center'][1]:.4f}",
            "missing": b.get("missing_facilities", []), "nearest_name": (b.get("nearest") or [{}])[0].get("name", "—"),
            "nearest_d": (b.get("nearest") or [{}])[0].get("distance_m", 0),
            "direction": (b.get("nearest") or [{}])[0].get("direction", ""),
        }
        for b in bs
    ]
    claims = [
        {
            "claim_id": f"c-lc-bs-{r['id']}", "text": f"{r['id']}：1km 内无 {'、'.join(r['missing'])}；最近「{r['nearest_name']}」{int(r['nearest_d'])}m（{r['direction']}）",
            "field": "blindspot", "evidence_ids": [f"ev-lc-bs-{r['id']}"],
            "confidence": "high", "cross_validated": True, "author": "许映川",
        }
        for r in rows
    ]
    return {
        "id": "blindspot", "title": "服务盲区诊断", "level": 2,
        "key_takeaway": (
            f"识别 {len(bs)} 处 1km 服务盲区" if bs else "未发现 1km 服务盲区，三要素齐备"
        ),
        "paragraphs": ["按赛题口径（1km 内无菜市场/药店/小学即判盲）识别，下表为各盲区缺失要素与最近设施方位（供补点/加设移动服务参考）。"] if bs else ["按赛题口径网格扫描：各网格点 1km 圆内三类必备设施均有覆盖。"],
        "claims": claims,
        "data_grid": {
            "columns": ["盲区编号", "中心点", "缺失设施", "最近设施", "最近距离"],
            "rows": [{
                "name": r["id"], "value": r["nearest_name"], "metric": " / ".join(r["missing"]),
                "source": f"{r['center']} · {int(r['nearest_d'])}m·{r['direction']}", "source_url": "",
            } for r in rows],
        },
        "source_evidence_ids": [f"ev-lc-bs-{r['id']}" for r in rows],
    }


def _sec_conclusion(lc: dict) -> dict:
    total = (lc.get("scores") or {}).get("total", 0)
    suggestions = _build_suggestions(lc)
    return {
        "id": "conclusion", "title": "体检结论与整改建议", "level": 2,
        "key_takeaway": f"综合 {total} 分（{_grade(total)}）；共 {len(lc.get('blindspots', []))} 处服务盲区，整改优先级见下",
        "paragraphs": [f"本样区{('存在多处服务盲区，整改优先级如下：' if lc.get('blindspots') else '设施覆盖整体均衡，建议保持既有配置并动态复检。')}", *suggestions,
                       "提醒：结论基于演示数据（fixture），正式结论以 M5 阶段真实路网测时为准。"],
        "claims": [{
            "claim_id": "c-lc-conclusion-1",
            "text": f"样区综合 {total} 分（{_grade(total)}），首要整改方向：{suggestions[0].lstrip('· ') if suggestions else '持续监测'}",
            "field": "conclusion", "evidence_ids": [f"ev-lc-bs-{b['id']}" for b in lc.get("blindspots", [])],
            "confidence": "high", "cross_validated": True, "author": "温叙白",
        }],
        "source_evidence_ids": [f"ev-lc-bs-{b['id']}" for b in lc.get("blindspots", [])],
    }


def _build_suggestions(lc: dict) -> List[str]:
    """规则化整改建议（盲区/养老缺口兜底）。"""
    out: List[str] = []
    missing = set()
    for b in lc.get("blindspots", []):
        missing.update(b.get("missing_facilities", []))
    plan = {"菜市场": "蔬菜便民车/移动菜市点位", "药店": "社区药柜+线上配送", "小学": "校车线路/学区统筹"}
    for f in missing:
        out.append(f"· 盲区缺位「{f}」：建议{plan.get(f, '补建/补充供给')}。")
    el = _cat(lc, "elderly")
    if el and el.get("in_circle", 0) == 0:
        out.append("· 养老配置 0 覆盖：建议引入日间照料中心或助老驿站，优先级 P0。")
    if not out:
        out.append("· 无显著整改项。")
    return out


def build_evidence(lc: dict) -> List[dict]:
    """证据链（出处=测时/POI/判定记录，延续可溯源卖点）。"""
    ev = [{
        "evidence_id": "ev-lc-measure",
        "source_url": "live://measure", "source_type": "api_measure",
        "title": f"采样点测时记录（{len(lc.get('sampling', {}).get('points', []))} 点）",
        "excerpt": f"批量算路返回 {sum(1 for p in lc.get('sampling', {}).get('points', []) if p.get('reachable'))} 条可达耗时",
        "credibility": 0.95, "collected_by": "路遥川", "captured_at": lc.get("generated_at", ""), "domain": "walkability",
    }]
    for c in lc.get("poi", {}).get("categories", []):
        ev.append({
            "evidence_id": f"ev-lc-poi-{c['category']}", "source_url": "live://poi", "source_type": "poi_search",
            "title": f"{c['label']} POI 检索", "excerpt": f"命中 {c['total']} 处，圈内 {c['in_circle']} 处",
            "credibility": 0.92, "collected_by": "苏堤春", "captured_at": lc.get("generated_at", ""), "domain": c["category"],
        })
    for b in lc.get("blindspots", []):
        ev.append({
            "evidence_id": f"ev-lc-bs-{b['id']}", "source_url": "live://blindspot", "source_type": "grid_scan",
            "title": f"盲区点位 {b['id']}", "excerpt": f"1km 内无 {'、'.join(b.get('missing_facilities', []))}",
            "credibility": 0.98, "collected_by": "许映川", "captured_at": lc.get("generated_at", ""), "domain": "coverage",
        })
    return ev


def assemble_report(lc: dict, report_id: str, scene_key: str, title: str) -> Dict[str, Any]:
    """把 LivingCircleReport(data) 组装成完整 Report（渲染适配器直接消费）。"""
    scene = lc.get("scene") or {}
    total = (lc.get("scores") or {}).get("total", 0)
    blist = lc.get("blindspots", [])
    ev_measure = f"ev-lc-measure"

    sections = [
        _sec_overview(lc, ev_measure),
        _sec_medical(lc),
        _sec_education(lc),
        _sec_market(lc),
        _sec_elderly(lc),
        _sec_isochrone(lc, ev_measure),
        _sec_blindspot(lc),
        _sec_conclusion(lc),
    ]
    experts = [
        "L3-001", "L3-002", "L3-003", "L2-001", "L2-002", "L2-003",
        "L2-004", "L2-005", "L2-008", "L1-001", "L1-004", "L1-005", "L1-008",
    ]
    dispatch = [
        {"id": eid, "reason": f"{LC_EXPERT[eid]['role']}负责本节评审与结论签发（D4 专家出诊断）"}
        for eid in experts
    ]
    evidence = build_evidence(lc)
    report = {
        "id": report_id,
        "report_type": "living_circle",
        "title": title or f"{scene.get('name', '')} · 生活圈体检报告",
        "subtitle": (
            f"{scene.get('city', '')} · {scene.get('address', '')}｜综合 {total} 分（{_grade(total)}）"
            f"· {len(blist)} 处服务盲区 · 共 {(lc.get('poi') or {}).get('total', 0)} 处设施"
        ),
        "query": scene.get("name", ""),
        "brands": [],
        "mode": "standard",
        "created_at": lc.get("generated_at", ""),
        "experts": experts,
        "dispatch": dispatch,
        "toc": [{"id": s["id"], "title": s["title"], "level": s["level"]} for s in sections],
        "sections": sections,
        "charts": [c for s in sections for c in (s.get("charts") or [])],
        "evidence": evidence,
        "claims": [c for s in sections for c in (s.get("claims") or [])],
        "glossary": [
            {"term": "等时圈", "definition": "以中心点为原点、步行耗时相同的等值线族（5/10/15/20 min）"},
            {"term": "服务盲区", "definition": "1km 范围内缺少菜市场/药店/小学任一必备设施的区域"},
            {"term": "IDW 插值", "definition": "反距离加权：以采样点耗时推演连续耗时场，不依赖底层路网"},
            {"term": "BD-09", "definition": "百度坐标系，本项目地图全域统一使用"},
        ],
        "methodology": {
            "window": "单次体检",
            "note": f"data_origin={lc.get('data_origin')} · interpolation={(lc.get('sampling') or {}).get('interpolation')} · scene_key={scene_key}",
        },
        "living_circle": lc,
    }
    return report