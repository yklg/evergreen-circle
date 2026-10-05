"""专家组队（M3 自 engine.py 原文迁出 · 行为零变化）。

LLM 动态指派 + 配额/层级/多样性校验（_coerce_dispatch fail-loud 幻觉过滤）+ 降级兜底 + trace 留痕。
依赖：llm/runtime/trace/data 叶子；不反向依赖 engine。符号由 engine re-export。
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from app.core import llm, trace
from app.data import load_experts

#: 调研域取哪本专家名册 —— 唯一定义源，engine 侧同 import 此常量。
#: 两本名册共用同一套 48 个 id、人设不同（`app/data/__init__.py`），所以域必须写出来：
#: 少写一次不会报错，只会静默换成另一个人名。
ROSTER_DOMAIN = "travel"

from . import runtime


# 兜底组队按职级从名册现算（不再写死 id 清单）；函数组优先，保住舆情位的语义。
_FALLBACK_PICK = {"L3": 1, "L2": 2, "L1": 3}


# ── 编排：LLM 动态指派专家（含理由 + 降级三态）────────────────
# 团队配额：(职级, 下限, 上限, 名册里的角色称呼)。同一份常量既拼进指派 prompt、
# 又驱动 _composition_violations —— 此前「1×L3 + 1-2×L2 + 3-6×L1」只是 prompt 里的
# 口头承诺，代码一行没校验（TC-E07 钉的就是这个洞）。
_TEAM_QUOTA = (("L3", 1, 1, "决策层统筹"), ("L2", 1, 2, "策略顾问"), ("L1", 3, 6, "执行专家"))


_TEAM_QUOTA_DESC = "、".join(
    (f"{lo}-{hi} 位 {lvl} {name}" if lo != hi else f"{lo} 位 {lvl} {name}")
    for lvl, lo, hi, name in _TEAM_QUOTA)


def _levels_of(ids, level_of: Dict[str, str]) -> Counter:
    return Counter(level_of.get(i, "?") for i in ids)


def _composition_violations(member_ids: List[str], level_of: Dict[str, str]) -> List[str]:
    """按 _TEAM_QUOTA 检查层级配比，返回违规说明（空列表即合规）。"""
    n = _levels_of(member_ids, level_of)
    out = []
    for lvl, lo, hi, _name in _TEAM_QUOTA:
        c = n.get(lvl, 0)
        if not lo <= c <= hi:
            out.append(f"{lvl} 期望 {lo}-{hi} 位，实得 {c} 位")
    return out


def _coerce_dispatch(raw: Any, valid_ids: set, level_of: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """把指派产出规整成 {lead, members, repairs}；形状不符一律 None（交调用方判降级）。

    三道处理都必须留痕，旧实现是三道无痕兜底：
      - 幻觉/非法 id：丢弃（旧实现已有）；
      - 重复 id：去重保序（旧实现会虚增 missions）；
      - lead 悬空或非法：归一到队内决策层（旧实现直接 `members[0]`，无声换人）。
    """
    if not isinstance(raw, dict):
        return None
    members: List[Dict[str, str]] = []
    seen: set = set()
    dropped = 0
    for m in raw.get("members") or []:
        if not isinstance(m, dict):
            dropped += 1
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or mid not in valid_ids:
            dropped += 1
            continue
        if mid in seen:
            dropped += 1
            continue
        seen.add(mid)
        members.append({"id": mid, "reason": str(m.get("reason") or "").strip()})
    if not members:
        return None
    repairs: List[str] = []
    if dropped:
        repairs.append(f"丢弃 {dropped} 个非法/重复指派项")
    lead = raw.get("lead")
    if not (isinstance(lead, str) and lead in seen):
        if isinstance(lead, str) and lead:
            repairs.append(f"lead {lead} 不在队内，已归一")
        lead = next((m["id"] for m in members if level_of.get(m["id"]) == "L3"),
                    members[0]["id"])
    return {"lead": lead, "members": members, "repairs": repairs}


def _fallback_team(experts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """规则兜底组队：按职级从名册取，函数组 L1 排在行业组之前。

    注意它**只在 LLM 完全不可用时**才到这里，且调用方必然同时给出 degraded ——
    「兜底」与「真组队」在下游必须可区分，否则症状会伪装成业务决策。
    """
    def pick(level: str, want: int) -> List[Dict[str, Any]]:
        pool = [e for e in experts if e["level"] == level]
        # 函数组（采集/舆情）优先，保证降级轮里 collect/舆情两位仍有对口人
        pool.sort(key=lambda e: 0 if e.get("group") == "function" else 1)
        return pool[:want]

    chosen = pick("L3", _FALLBACK_PICK["L3"]) + pick("L2", _FALLBACK_PICK["L2"]) \
        + pick("L1", _FALLBACK_PICK["L1"])
    return [{"id": e["id"], "reason": f"规则兜底：按 {e['level']} 职级配额选入"}
            for e in chosen]


def _record_dispatch_span(msgs: List[Dict[str, str]], decision: str) -> None:
    """把降级原因写进 trace，让决策回放看得见「这次不是真组队」。

    观测不得变成新的失败面：不在调研流程内（无 task_id）时 record_span 自行短路。
    """
    try:
        trace.record_span(model=runtime._model("fast"), messages=msgs, response="",
                          decision=decision)
    except Exception:  # noqa: BLE001  —— 观测失败不得带崩编排
        pass


def _dispatch_experts(query: str, destinations: List[str], focus: List[str]) -> Dict[str, Any]:
    """动态指派专家团队，返回 {lead, members, degraded, degraded_reason, repairs}。

    `degraded` 恒存在（成功为 None）：让「LLM 挑出来的队」与「规则凑出来的队」
    在契约层可区分。三态取值见 _dispatch_experts 内注释。
    降级标记只走 trace 与运行中 SSE，不进报告 payload（见 test_report_read_compat 的
    plan_fallback 同源约定）。
    """
    experts = load_experts(ROSTER_DOMAIN)
    valid_ids = {e["id"] for e in experts}
    level_of = {e["id"]: e["level"] for e in experts}
    roster = [
        {"id": e["id"], "name": e["name"], "level": e["level"],
         "role": e["role_title"], "skills": e.get("skills", [])[:3]}
        for e in experts
    ]
    msgs = [
        {"role": "system", "content": (
            "你是 Verda 首席指挥官。从专家名册中为本次旅游调研挑选最合适的团队。"
            f"规则：必须含 {_TEAM_QUOTA_DESC}。"
            "为每位被选专家给出一句指派理由（说明负责什么、为何适合），理由不超过 20 字。"
            '只输出 JSON：{"lead":"专家id","members":[{"id":"专家id","reason":"指派理由"}]}。'
        )},
        {"role": "user", "content": (
            f"调研主题：{query}\n目的地：{'、'.join(destinations)}\n重点维度：{'、'.join(focus)}\n"
            f"专家名册：{json.dumps(roster, ensure_ascii=False)}"
        )},
    ]
    # max_tokens 从 2000 提到 3600：2000 在「8 位 × 长中文理由 + 思考未可关」下必被
    # 截空（实测 span sp_dc3935abad：completion=1999、推理占 1835、response 为空）。
    # 理由上界已同时下发，二者一起构成该调用点的输出预算契约。
    try:
        data = llm.chat_json(msgs, max_tokens=3600, temperature=0.4,
                         model=runtime._model("fast"), purpose="动态指派专家团队")
    except Exception as e:  # noqa: BLE001
        # 旧实现是 `except Exception: pass` —— 有 typed error（LLMModelUnavailable /
        # LLMNotConfigured）却无人消费，故障被伪装成「指挥官选了这 6 个人」。
        detail = f"{type(e).__name__}: {e}"
        _record_dispatch_span(msgs, f"动态指派专家团队· 指派调用失败（{detail[:120]}）")
        fb = _fallback_team(experts)
        return {"lead": fb[0]["id"], "members": fb, "repairs": [],
                "degraded": "llm_error", "degraded_reason": detail}

    team = _coerce_dispatch(data, valid_ids, level_of)
    if team is None:
        # 拿到了回复但不可用（截断 / 非 JSON / 形状不符 / id 全非法）。
        # 判据复用 brisk L2 的同一读数，避免两套「是不是截断」。
        trunc = llm.last_finish_reason() == "length"
        detail = ("输出被截断（思考未关或预算不足），无可用团队" if trunc
                  else "指派产出不可解析或全部指派非法")
        _record_dispatch_span(msgs, f"动态指派专家团队· {detail}")
        fb = _fallback_team(experts)
        return {"lead": fb[0]["id"], "members": fb, "repairs": [],
                "degraded": "llm_output_unusable",
                "degraded_reason": detail + f"（finish_reason={llm.last_finish_reason()}）"}

    ids = [m["id"] for m in team["members"]]
    bad = _composition_violations(ids, level_of)
    if bad:
        # 形状可用但配比违约：保留 LLM 的团队（它仍能干活），只把违约显性化。
        # 不静默重挑，避免「谁在选人」又从 LLM 手里滑回规则。
        detail = "团队层级配比不符：" + "；".join(bad)
        _record_dispatch_span(msgs, f"动态指派专家团队· {detail}")
        return {**team, "degraded": "spec_violation", "degraded_reason": detail}
    return {**team, "degraded": None, "degraded_reason": ""}
