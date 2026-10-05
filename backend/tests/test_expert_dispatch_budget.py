"""专家指派调用的输出预算契约（TC-E10）。

背景（真实故障 r_38bdd649 / span sp_dc3935abad，详见
~/.qoder-cn/plans/quiet-shore-pike.md）：`_dispatch_experts` 以 `max_tokens=2000`
要求模型输出 5-8 位专家、每位一句中文指派理由；实测该次调用
`completion_tokens=1999`、decision 带「输出被截断（推理 1835 tok）」，
`response` 直接被思考 token 吃光成空串 —— 于是每次都落回硬编码兜底 6 人。

本文件不复现截断（那需要真模型），而是把**驱动截断的三个数值**钉成可核对的事实：
1. 输入侧：48 人名册全量入 prompt 的字符体积（决定 prompt token）；
2. 输出侧：当前 `max_tokens` 实参值；
3. 契约侧：prompt 对「指派理由长度」有上界约束。

三者共同决定「预算是否够用」。任何一项变动都应在这里留下痕迹，
而不是等到线上又连续 7 轮出同 6 个人时才发现。

Stage A 已把 (2) 提到 3600 并给 (3) 加上 20 字上界；本文件随之从
「记录现状 + TODO」转为正式契约断言。

种子：test_llm_truncation_observe.py（截断可观测的数值同族）、
      test_expert_dispatch_degraded.py（同一函数的契约面）。
运行：backend/ 下 `pytest tests/test_expert_dispatch_budget.py -q`
"""
import json
import re

from app.core import llm
from app.core.pipeline.research import engine as O
from app.data import load_experts

# 实测基线（2026-09-22，experts.json 48 条、字段 id/name/level/role/skills[:3]）
ROSTER_MIN_CHARS = 6000      # 名册 JSON 体积下限：低于此说明有人给 roster 加了切片
# 输出预算：原为 2000，在「8 位 × 长中文理由 + 思考不可关」下必被截空
# （实测 span sp_dc3935abad：completion=1999、推理占 1835、response 为空）。
# Stage A 同时下发了「理由 ≤20 字」上界并把预算提到 3600。
EXPECTED_MAX_TOKENS = 3600


def _capture_kwargs(monkeypatch, payload=None):
    seen = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        seen.update(kwargs)
        return payload

    monkeypatch.setattr(llm, "chat_json", fake)
    return seen


def test_roster_volume_is_not_sliced():
    """输入侧：48 位专家全量序列化进 prompt，体积在基线量级。

    守的是「有人为省 token 把 roster 切成前 N 位」——那会让后面的专家永久不可选，
    且症状与本 bug 一模一样（永远是那几个），极难从报告里看出来。
    """
    pool = load_experts("travel")
    assert len(pool) == 48
    roster = [
        {"id": e["id"], "name": e["name"], "level": e["level"],
         "role": e["role_title"], "skills": e.get("skills", [])[:3]}
        for e in pool
    ]
    chars = len(json.dumps(roster, ensure_ascii=False))
    assert chars >= ROSTER_MIN_CHARS, f"名册体积异常缩小（{chars} 字符），检查是否被切片"
    # 中文字符按 ≈1 token/字 估，给后续预算核对留一个可算的量
    assert chars < ROSTER_MIN_CHARS * 3, "名册体积暴涨，prompt 预算需重估"


def test_current_output_budget_matches_contract(monkeypatch):
    """输出侧：指派调用实参 `max_tokens` 必须是与输出契约相称的值。

    本钉故意断言**具体数值**而非「不小于某值」—— 目的是让「改了这个数」必须
    经过本文件与一次理由长度约束的复核，而不是悄悄漂移回 2000。
    """
    seen = _capture_kwargs(monkeypatch, {"lead": "L3-001",
                                         "members": [{"id": "L3-001", "reason": "统筹"}]})
    O._dispatch_experts("大理", ["大理"], ["交通"])
    assert seen["max_tokens"] == EXPECTED_MAX_TOKENS, (
        "输出预算已变更：确认是否仍保留指派理由长度上界，否则截断致兜底会复发")


def test_prompt_bounds_reason_length(monkeypatch):
    """契约侧：prompt 必须给「指派理由」一个长度上界。

    旧 prompt 只说「一句具体的指派理由」，实测 LLM 每位写 ~100 中文字 ×6-8 位，
    叠加推理 token 必然撑破预算 —— 这是「输出体积 = 失败面」的量化来源。
    """
    seen = _capture_kwargs(monkeypatch, None)
    O._dispatch_experts("大理", ["大理"], ["交通"])
    blob = json.dumps(seen["messages"], ensure_ascii=False)
    assert "指派理由" in blob, "prompt 仍应要求给出理由"
    bounded = re.search(r"理由[^。]{0,16}(\d+)\s*字", blob)
    assert bounded, "指派理由长度上界丢失：输出体积失去约束，截断致兜底的根因会回来"
    assert int(bounded.group(1)) <= 40, f"理由上界放宽到 {bounded.group(1)} 字，需重估 max_tokens"
