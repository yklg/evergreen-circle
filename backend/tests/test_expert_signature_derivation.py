"""D4 署名必须派生自权威名册 experts.json，系统里不得有第二份姓名表。

守住三类回归（前两类是历史/现存缺陷）：
  - 名册增删 id 使装配期查署名抛 KeyError；
  - 署名静默回落成通用职位「规划专家」—— 前端 LifeCircleReportView 至今仍是这个 bug 形态；
  - claim author 与名册姓名漂移。
"""
import asyncio

import pytest

from app.core import db
from app.core.pipeline.diagnosis_templates import _expert, _expert_name
from app.core.pipeline.living_circle import (
    create_living_circle_task,
    living_circle_pipeline,
)
from app.data import load_experts

# Phase 6：诊断模板 fallback 保底团队（动态编排失败时使用）
DISPATCH_IDS = (
    "L3-001", "L3-002", "L3-003",
    "L2-001", "L2-002", "L2-003", "L2-004", "L2-005", "L2-008",
    "L1-001", "L1-004", "L1-005", "L1-008",
)

KAILI = {
    "scene_name": "凯里老街",
    "city": "贵州·凯里",
    "address": "凯里市西门街道老街片区",
    "center": [107.9758, 26.5734],
    "study_radius_m": 2500.0,
    "mode": "standard",
    "data_mode": "fixture",
}


def _roster():
    return {e["id"]: e for e in load_experts()}


def _report():
    tid = create_living_circle_task(KAILI)

    async def _impl():
        rid = None
        async for ev in living_circle_pipeline(tid):
            if ev["type"] == "done":
                rid = ev["data"]["report_id"]
        return rid

    return db.get_report(asyncio.run(_impl()))


def test_dispatch_seats_all_exist_in_roster():
    """席位 id 在名册中缺失时，派生路径回落而不崩；但缺失本身必须报红。"""
    missing = [i for i in DISPATCH_IDS if i not in _roster()]
    assert not missing, f"章节席位在名册中查不到：{missing}"


@pytest.mark.parametrize("eid", DISPATCH_IDS)
def test_signature_equals_roster_derivation(eid):
    entry = _roster()[eid]
    sig = _expert(eid)
    assert sig["name"] == entry["name"]
    assert sig["role"] == entry["role_title"].split(" / ")[0]


@pytest.mark.parametrize("eid", DISPATCH_IDS)
def test_real_seat_role_is_not_the_fallback_label(eid):
    """回落职位出现在真实席位上 ⇒ 名册查丢但流程没断，正是最难发现的静默降级。"""
    assert _expert(eid)["role"] != "规划专家"


def test_unknown_seat_degrades_without_raising():
    assert _expert("L9-999") == {"name": "L9-999", "role": "规划专家"}
    assert _expert_name("L9-999") == "L9-999"


def test_report_authors_and_reasons_come_from_roster():
    rep = _report()
    roster = _roster()
    names = {e["name"] for e in roster.values()}

    authors = {c["author"] for c in rep["claims"]}
    assert authors, "报告必须带章节结论署名"
    assert authors <= names, f"署名不在名册中：{sorted(authors - names)}"

    # Phase 6：dispatch reasons 现在是动态生成的，只需验证非空且不含回落标记
    for d in rep["dispatch"]:
        assert d["reason"], f"专家 {d['id']} 的分工理由不应为空"
        assert "规划专家负责" not in d["reason"], (
            f"专家 {d['id']} 的分工理由不应使用回落模板"
        )
