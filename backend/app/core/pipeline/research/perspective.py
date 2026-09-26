"""调研视角专属块装配（M3 自 engine.py 原文迁出 · 行为零变化）。

视角（亲子/情侣/独行/摄影/长辈 或 自住/投资/求学/养老/数字游民）的章节集、
问卷闸门、专属结构化键注册表均在 research_types；本模块只负责把逐景点二查证据
装配成核查表/铁律/行前清单（行集由冻结榜 seed，LLM 只填格不造行）。
依赖：llm 叶子 + research_types 注册表；不反向依赖 engine。符号由 engine re-export。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core import llm
from app.core import research_types as RT


def _fill_persp_blocks(persp_sid: str, dest: str, spot_entities: List[Dict[str, Any]],
                       probes: Dict[str, List[str]], evidences: List[Any],
                       clar: Dict[str, Any], model: str,
                       task_id: str = "") -> "tuple[Dict[str, Any], Dict[str, Any]]":
    """视角专属块装配（同步，to_thread 调用；rough-cliff-vole P3）。

    行集**由冻结榜 seed**（每个 spot_id 恰一行，LLM 只填格不造行——多报/漏报的
    行一律不采纳，缺失格走「待核验」占位）；不造数守卫：格/规则声称 verified 但
    引用不出真实证据 id → 强制降为待核验。LLM 整体失败不炸管线：照常产出全占位表
    （占位可见即正确终态，同 spot_routes 降级哲学）。
    返回 `(blocks, diag)`：blocks = {checklist_key: [...], rules_key: [...], packing_key: [...]}
    （组级 destination 分组）；diag = 装配台账，见下。

    ⚠️ 为什么 diag 必须由**这里**产出：本函数的 `except Exception: payload = {}` 把四种异质
    失败压成同一个产物——LLM 抛错 / 返回 None / 真没采到证据 / 反造数守卫把格子全拒——
    四者的载荷长得一模一样，事后从 `structured` **不可反推**（批次 0 的前置条件 2）。
    `last_finish_reason()` 是 ContextVar，在本上下文里紧跟自己那次 `chat_json` 读，拿到的
    就是自己这次的终止原因（不是跨任务的全局汇，故并发安全）。
    """
    p = RT.perspective_spec(persp_sid)
    ck = p.get("checklist_key")
    cols = tuple(p.get("checklist_columns") or ())
    # 只记**不可反推**的三项。格级 verified/总数、rules/packing 条数一律不进这里 ——
    # 那些能从 structured 算（`schemas.persp_cell_stats`），再记一份就是第二套口径，
    # 两处一旦漂移，门槛读到的就是某个谁都不认的数。
    diag: Dict[str, Any] = {"llm_outcome": "skipped", "probed_spots": len(spot_entities),
                            "spots_with_evidence": sum(1 for v in probes.values() if v),
                            "payload_rows": 0, "task_id": task_id}
    if not ck or not spot_entities:
        return {}, diag
    cols = tuple(p.get("checklist_columns") or ())
    ev_ids = {getattr(e, "evidence_id", "") for e in evidences}
    ev_by_id = {getattr(e, "evidence_id", ""): e for e in evidences}
    hard_q = tuple(p.get("hard_constraints") or ())
    constraints = "；".join(f"{q}={clar.get(q)}" for q in hard_q if str(clar.get(q) or "").strip())
    ev_lines = []
    for it in spot_entities:
        eids = [x for x in (probes.get(str(it.get("spot_id"))) or []) if x in ev_ids]
        digest = "；".join(f"[{x}] {str(getattr(ev_by_id[x], 'excerpt', ''))[:110]}"
                           for x in eids[:4])
        ev_lines.append(f"{it.get('spot_id')}|{it.get('name', '')}|{digest or '（二查未采到证据）'}")
    payload: Dict[str, Any] = {}
    try:
        _raw = llm.chat_json(
            [
                {"role": "system", "content": (
                    f"你是旅游调研「{RT.SECTION_PLAN.get(persp_sid, persp_sid)}」专项核查填格员。"
                    f"逐景点填以下列：{'、'.join(cols)}。铁律："
                    "①每格只能引用该景点行内给出的 [e_xxxx] 证据，text 里保留关键数字/规则原文；"
                    "②该景点没有对应证据时**省略该格**（系统会填「待核验」），严禁凭常识造参数；"
                    "③rules 是给该行程的可执行铁律（≤5 条），每条必须引用 ≥1 个真实证据 id，"
                    "并在 refs 里写出它所依据的问卷约束字段名（可选值：" +
                    ("、".join(hard_q) or "无") + "）；"
                    "④packing 只收与目的地事实挂钩的行前清单项（气候/票证/设施类），"
                    "通用到任何城市都成立的项不收。"
                    '输出 JSON：{"rows":[{"spot_id":"…","cells":{"列名":{"text":"…",'
                    '"evidence_ids":["e_…"],"verified":true}}}],'
                    '"rules":[{"text":"…","refs":["字段"],"evidence_ids":["e_…"]}],'
                    '"packing":[{"item":"…","reason":"…","evidence_ids":["e_…"]}]}。只输出 JSON。'
                )},
                {"role": "user", "content": (
                    f"目的地：{dest}\n本次问卷硬约束：{constraints or '（无）'}\n"
                    "景点证据行（spot_id|名称|证据摘要）：\n" + "\n".join(ev_lines)[:6000]
                )},
            ],
            max_tokens=3600, temperature=0.3, model=model,
            purpose="视角专属核查表与铁律填格",
        )
        # 终止原因必须**紧跟自己那次调用**读：length = 被 max_tokens 截断（单元格 JSON 体量
        # 随列数线性涨，截断即解析不出东西），与「模型答了但没内容」是两种病因、两种药。
        diag["llm_outcome"] = ("truncated" if llm.last_finish_reason() == "length"
                               else "ok" if isinstance(_raw, dict) else "empty")
        payload = _raw if isinstance(_raw, dict) else {}
    except Exception:
        payload = {}
        diag["llm_outcome"] = "error"
    diag["payload_rows"] = len(payload.get("rows") or [])
    rows_in = {str(r.get("spot_id")): r for r in (payload.get("rows") or [])
               if isinstance(r, dict)}
    items: List[Dict[str, Any]] = []
    for it in spot_entities:  # 行守恒：冻结榜每行恰一行
        cells_in = (rows_in.get(str(it.get("spot_id"))) or {}).get("cells") or {}
        cells = []
        for col in cols:
            raw = cells_in.get(col) if isinstance(cells_in.get(col), dict) else {}
            eids = [x for x in (raw.get("evidence_ids") or []) if x in ev_ids]
            text = str(raw.get("text") or "").strip()
            if raw.get("verified") and eids and text:
                cells.append({"column": col, "text": text,
                              "evidence_ids": eids, "verified": True})
            else:
                cells.append({"column": col, "text": "待核验（本次未采到）",
                              "evidence_ids": [], "verified": False})
        items.append({"spot_id": it.get("spot_id"), "spot_name": it.get("name", ""),
                      "cells": cells})
    out: Dict[str, Any] = {ck: [{"destination": dest, "items": items}]}
    rules_key = p.get("rules_key")
    if rules_key:
        rules = []
        for r in (payload.get("rules") or [])[:5]:
            if not isinstance(r, dict):
                continue
            eids = [x for x in (r.get("evidence_ids") or []) if x in ev_ids]
            refs = [q for q in (r.get("refs") or []) if str(q) in hard_q]
            text = str(r.get("text") or "").strip()
            if text and eids and refs:
                rules.append({"text": text, "refs": refs, "evidence_ids": eids})
        out[rules_key] = [{"destination": dest, "items": rules}]
    packing_key = p.get("packing_key")
    if packing_key:
        pack = []
        for r in (payload.get("packing") or [])[:8]:
            if not isinstance(r, dict):
                continue
            eids = [x for x in (r.get("evidence_ids") or []) if x in ev_ids]
            item = str(r.get("item") or "").strip()
            if item and eids:
                pack.append({"item": item, "reason": str(r.get("reason") or "").strip(),
                             "evidence_ids": eids})
        out[packing_key] = [{"destination": dest, "items": pack}]
    return out, diag
