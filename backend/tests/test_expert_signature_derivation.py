"""D4 署名必须派生自**生活圈权威名册** experts_living_circle.json，系统里不得有第二份姓名表。

守住四类回归（前两类是历史/现存缺陷）：
  - 名册增删 id 使装配期查署名抛 KeyError；
  - 署名静默回落成通用职位「规划专家」—— 前端 LifeCircleReportView 至今仍是这个 bug 形态；
  - claim author 与名册姓名漂移；
  - **取错域**：两本名册共用同一套 48 个 id、人设互不通用，域写错不会抛异常，只会把
    生活圈章节署成旅游人设（实测 7/7 章，如医疗章「苏明哲·行程策略专家」）。
"""
import asyncio
import json
import re
from pathlib import Path

import pytest

from app.core import db
from app.core.pipeline.diagnosis_templates import (
    _expert,
    _expert_name,
    assemble_report,
)
from app.core.pipeline.living_circle import (
    create_living_circle_task,
    living_circle_pipeline,
)
from app.data import load_experts
from app.living_circle.seat_registry import (
    SECTION_SEAT as _SECTION_SEAT,
    TEAM_FALLBACK as _TEAM_FALLBACK,
    signature_seats,
)

# Phase 6：诊断模板 fallback 保底团队（动态编排失败时使用）。
# 这张名单与下面的 SECTION_SEAT 都**不在本文件抄写** —— 唯一出口是席位注册表。
DISPATCH_IDS = _TEAM_FALLBACK

KAILI = {
    "scene_name": "凯里老街",
    "city": "贵州·凯里",
    "address": "凯里市西门街道老街片区",
    "center": [107.9758, 26.5734],
    "study_radius_m": 2500.0,
    "mode": "standard",
    "data_mode": "fixture",
}


# 席位 id 的形状（`L1-025` / `L2-005` / `L3-002` 同一族）。旅行域用同一种形状，
# 所以"形状对"不等于"域对"—— 域由 `_roster()` 那一格单独管。
_SEAT_ID_RE = re.compile(r"^[A-Z]\d-\d{3}$")


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
# 章节 → 席位 id 取自生产注册表 `app/living_circle/seat_registry.SECTION_SEAT`。
# 本文件原先自带一份、`scripts/normalize_report_signatures.py` 再自带一份，与装配代码三处
# 并存 —— A2 挂账的"搬进生产注册表"已由 C1 落地，这里改为 import，不再抄。
SECTION_SEAT = _SECTION_SEAT


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


def test_evidence_collected_by_is_a_seat_in_its_own_roster(signed_report):
    """B9（报告载荷半边）：`evidence[].collected_by` 必须是**席位 id**，且属于**这份报告自己的** `experts`。

    本条前身是 `test_evidence_collected_by_is_a_roster_name`（钉"必须是姓名"）。2026-10-11 挂账 A2
    结案（`nar-5`）：载荷这一侧改发席位 id，于是它与 SSE 那一侧
    （`test_sse_evidence_collected_by_is_a_registered_seat`）从此**同一形状**，两个并存的空间收成一个。
    新形状不是把判据放松，而是同时收紧两处：
      ① 形状闸 —— 漂回姓名（含非 `L\\d-\\d{3}` 的任何一个值）当场红；
      ② 归属闸 —— 只认名册全集不够（那正是 12:05 那个缺陷漏掉的方式：署给的人也在 48 人全集里），
         这里要求它出现在**这份报告自己的** `experts` 里。
    B1 的 AST 扫描只认 `L\\d-\\d{3}` 形状 ⇒ 它抓不到硬写的**姓名**，这一侧由本条兜住。
    变异：把 `diagnosis_templates` 的 `artifact_seat("measure")` 换回裸姓名 `"路遥川"` ⇒ 本条红。
    """
    rep = signed_report
    own = set(rep.get("experts") or [])
    assert own, "signed_report 没有 experts ⇒ 本条会因空集而假绿"
    roster = _roster()
    got = [ev.get("collected_by") for ev in (rep.get("evidence") or [])]
    assert got, "signed_report 里没有一条 evidence ⇒ 本条在空转"
    not_seat_shape = sorted({c for c in got if not _SEAT_ID_RE.match(str(c))})
    assert not not_seat_shape, f"证据采集人漂回姓名/裸文本（A2 之后这一位必须是席位 id）：{not_seat_shape}"
    outside = sorted({c for c in got if c not in own})
    assert not outside, f"证据采集席位不在本报告自己的名册里：{outside}"
    unknown = sorted({c for c in got if c not in roster})
    assert not unknown, f"证据采集席位不在生活圈名册里（取错域）：{unknown}"


# ── 署名必须落在**这份报告自己的名册**里（不是全 48 人名册）──────────────────
#
# 上面两条拿 `_roster()`（名册全集）做期望值 —— 章侧钉**姓名**（它上屏），证据侧自 `nar-5` 起钉
# **席位 id**（它不上屏）⇒ 它们封得住"取错域 / 形状漂回"，
# 封不住"署给一个没参与本次体检的人"：那种人**也在**名册全集里。
# 实测漏网的正是这一档（2026-10-11）：`kaili-ev2.json` 与 `beijing-jinsong.json` 的
# `team.expert_ids` 都没有 `L3-002`，而 `SECTION_SEAT["blindspot"]` 登记的就是它 ⇒
# 盲区章 claim 与那条盲区证据署名为「许映川」，而该报告自己的 `experts` 里没有这个人
# （`kaili-ev2` 2 处；真报告 `lc-91d1f091` 同样 2 处，两份 nar-3 存量行各命中）。
# 修在装配期（`nar-4`）：名册按 `signature_seats()` 补齐 ⇒ 本条从"红"变"绿"。
#
# 变异实测（摘掉补齐那一段）：`test_report_signatures_never_escape_its_own_roster` **只红
# `kaili-ev2` 一份** —— `beijing-jinsong` 有 0 处盲区 ⇒ 盲区章不产 claim、也没有盲区证据，
# 那个席位根本没上屏，所以"逐份核"这一条**单靠自己会漏掉一份夹具**。
# 正因如此另配 `test_roster_backfill_actually_happened`（它红在**两份**自带 team 的夹具上）：
# 它不问"有没有署名跑出去"，只问"该补的补了没、原有成员与顺序动没动"，
# 于是补齐逻辑被摘掉时不会因为某份夹具的数据形态而静默。

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"


def _assemble_fixture(stem: str) -> tuple:
    payload = json.loads((_FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    team_ids = (payload.get("team") or {}).get("expert_ids") or []
    return assemble_report(payload, f"lc-{stem}", stem, ""), team_ids


@pytest.mark.parametrize("stem", ["kaili", "kaili-ev2", "beijing-jinsong"])
def test_report_signatures_never_escape_its_own_roster(stem):
    """逐份核（禁抽样）：凡报告里署了名的地方，那个人必须在这份报告自己的 `experts` 里。

    三份都跑，但要说清各自在测什么：`kaili` 无 team 走兜底名册（本来就覆盖署名席位）、
    `beijing-jinsong` 0 盲区（那个席位根本不上屏）⇒ **本条实际只有 `kaili-ev2` 会红**，
    覆盖面由下面那条正对照补上（见本块注释的变异实测）。
    """
    rep, team_ids = _assemble_fixture(stem)
    own = set(rep["experts"])
    assert own, f"{stem}: 报告没有 experts ⇒ 本条会因空集而假绿"
    names = {_expert_name(i) for i in own}

    escaped = []
    for sec in rep.get("sections") or []:
        for claim in sec.get("claims") or []:
            if claim.get("author") and claim["author"] not in names:
                escaped.append(f"{sec['id']} 章 claim 署「{claim['author']}」")
    for ev in rep.get("evidence") or []:
        # `nar-5` 起这一位是**席位 id**（不是姓名）：claim 侧仍发姓名（它上屏），证据侧发 id（它不上屏）。
        if ev.get("collected_by") and ev["collected_by"] not in own:
            escaped.append(f"证据 {ev['evidence_id']} 采集席位 {ev['collected_by']!r}")
    assert not escaped, f"{stem}: 署名跑出本报告名册之外 ⇒ {escaped}"


@pytest.mark.parametrize("stem", ["kaili-ev2", "beijing-jinsong"])
def test_roster_backfill_actually_happened(stem):
    """正对照（防恒真）：载荷缺席位时名册必须**变长**，否则上一条可能只是碰巧绿。

    没有这一条，"补齐"整段被摘掉后上一条仍可能因数据形态（无盲区 ⇒ 不产 claim）而不红 ——
    那正是本族原先漏掉这个缺陷的方式。
    """
    rep, team_ids = _assemble_fixture(stem)
    assert team_ids, f"{stem} 应自带 team（否则本条失去意义，需重挑夹具）"
    own = rep["experts"]
    assert len(own) > len(team_ids), f"{stem}: 名册没补齐（载荷 {len(team_ids)} 人 → 报告 {len(own)} 人）"
    missing = [s for s in signature_seats() if s not in team_ids]
    assert missing, f"{stem}: 载荷名册本来就已覆盖全部署名席位 ⇒ 本条在空转，需重挑夹具"
    assert all(s in own for s in missing), f"{stem}: 缺的席位 {missing} 没被补进名册"
    # 追加只发生在末尾：原有成员与顺序逐字保留（否则 reasons[i] 与 expert_ids[i] 的下标对齐会断）
    assert own[: len(team_ids)] == list(team_ids), f"{stem}: 补齐改写了原有成员或顺序"
