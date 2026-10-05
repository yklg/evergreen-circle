"""D4 署名必须派生自**生活圈权威名册** experts_living_circle.json，系统里不得有第二份姓名表。

守住四类回归（前两类是历史/现存缺陷）：
  - 名册增删 id 使装配期查署名抛 KeyError；
  - 署名静默回落成通用职位「规划专家」—— 前端 LifeCircleReportView 至今仍是这个 bug 形态；
  - claim author 与名册姓名漂移；
  - **取错域**：两本名册共用同一套 48 个 id、人设互不通用，域写错不会抛异常，只会把
    生活圈章节署成旅游人设（实测 7/7 章，如医疗章「苏明哲·行程策略专家」）。
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


def _roster(domain: str = "living_circle"):
    """署名期望值取自**生活圈**名册。

    这里曾经写 `load_experts()`（＝travel 默认域）：那条判据一边绿、一边把缺陷钉成正确
    行为，因为被测代码与期望值取的是同一本错名册。⇒ 期望值必须独立于被测路径。
    """
    return {e["id"]: e for e in load_experts(domain)}


@pytest.fixture(scope="module")
def signed_report():
    """本文件只跑**一次**流水线。

    为什么收成模块级夹具：每条用例各跑一次会往测试库多塞同 scene_key 的报告，
    而 `list_living_circle_reports` 是 `LIMIT 50` 的窗口 —— 用例数一多就会把别的
    落库用例挤出窗口（实测踩过）。署名这件事与跑几次无关，一份就够。
    """
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


def test_report_authors_and_reasons_come_from_roster(signed_report):
    rep = signed_report
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


# ── 取错域的反向钉（本轮根因的结构性防线）──────────────────────────
# 章节 → 席位 id：逐条对照 `diagnosis_templates.py` 的 `_sec_*` 构造点
#   :592 medical→L2-001 / :624 education→L2-002 / :648 market→L2-004
#   :693 elderly→L2-003 / :714 isochrone→L2-005 / :981 blindspot→L3-002
#   :1069 conclusion→L3-001
# A2（报告瘦身）会把这张表搬进生产注册表；在那之前它是本文件与规范化脚本共用的口径。
SECTION_SEAT = {
    "medical": "L2-001",
    "education": "L2-002",
    "market": "L2-004",
    "elderly": "L2-003",
    "isochrone": "L2-005",
    "blindspot": "L3-002",
    "conclusion": "L3-001",
}


def test_no_travel_only_persona_appears_anywhere_in_report(signed_report):
    """整份报告 JSON 里不得出现**只属于旅游名册**的人名。

    判据取"两域姓名差集"而非逐个硬编码：名册以后加人/换人，这条不用改。
    """
    import json

    rep = signed_report
    t_names = {e["name"] for e in _roster("travel").values()}
    l_names = {e["name"] for e in _roster("living_circle").values()}
    travel_only = t_names - l_names
    assert travel_only, "两本名册姓名完全相同 ⇒ 这条判据失去区分力，先改名册再谈防串域"

    blob = json.dumps(rep, ensure_ascii=False)
    hit = sorted(n for n in travel_only if n in blob)
    assert not hit, f"报告里混进旅游名册人设 {hit}——署名取错域（应为 living_circle）"


def test_cross_domain_duplicate_name_resolves_to_the_right_seat(signed_report):
    """交叉重名专项钉：可达性章的署名必须是「路遥川」，不是「温叙白」。

    为什么单独钉：travel L2-005 叫「温叙白」，而 living_circle 的 L3-001 也叫「温叙白」
    （living_circle L2-005 才是「路遥川·慢行可达性分析师」）。⇒ 拿姓名反查 id 的修法会把
    这行改对成改错，肉眼也看不出（"温叙白·社区体检总检"在生活圈报告里看着完全合理）。
    """
    rep = signed_report
    sec = {s["id"]: s for s in rep["sections"]}
    authors = [c["author"] for c in sec["isochrone"]["claims"]]
    assert authors, "可达性章必须带署名，否则本判据空转"
    assert authors == [_expert_name("L2-005")], f"可达性章署名应为路遥川，实得 {authors}"
    assert "温叙白" not in authors, "可达性章拿到了旅游名册的 L2-005 人名（交叉重名串域）"


def test_every_section_author_equals_its_declared_seat(signed_report):
    """逐章核：凡有 claims 的章，author 必须＝该章席位在生活圈名册里的姓名（禁抽样）。

    盲区章按盲区条数产 claims ⇒ 无盲区样区（凯里 fixture 实测 0 处）该章合法地没有署名，
    所以判据是"有则必对 ＋ 至少 6 章有"，而不是"7 章都得有"（后者会把数据形态当缺陷）。
    """
    rep = signed_report
    roster = _roster()
    sec = {s["id"]: s for s in rep["sections"]}
    missing = [k for k in SECTION_SEAT if k not in sec]
    assert not missing, f"报告章节缺件，判据将静默漏检：{missing}"
    signed = [sid for sid, seat in SECTION_SEAT.items() if sec[sid]["claims"]]
    assert len(signed) >= 6, f"带署名的章只剩 {len(signed)} 个，判据接近空转：{SECTION_SEAT}"
    for sid in signed:
        seat = SECTION_SEAT[sid]
        authors = [c["author"] for c in sec[sid]["claims"]]
        assert set(authors) == {roster[seat]["name"]}, (
            f"{sid} 章席位 {seat} 应为「{roster[seat]['name']}」，实得 {sorted(set(authors))}"
        )
