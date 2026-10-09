"""注册表席位 ↔ 名册人设必须**互指**：换人要同时改两处，改错一处当场红。

这条取代原先散在两处的手点判据（`test_phase6_lc_team.py` 的
`test_advisors_match_living_circle_roles` 与
`test_method_seats_cover_the_four_pipeline_steps`，各抄了一份「席位→关键词」）。
本文件是它们的**超集**：注册表五张表里出现的每一个席位都要过一遍，而不是只点 8 对。

只比 `role_title` 的**中文段**：名册里是「社区体检总检 / Chief Community Health Inspector」
双段，`_expert()` 取的是 `" / "` 切出的首段。整串匹配会让"改英文人设"误红、"改中文段"漏红。
"""
from __future__ import annotations

import pytest

from app.data import load_experts
from app.living_circle.seat_registry import (
    ARTIFACT_SEAT,
    FALLBACK_TEAM,
    SECTION_SEAT,
    STAGE_SEAT,
    TEAM_FALLBACK,
)

ROSTER = {e["id"]: e for e in load_experts("living_circle")}


def _cn_role(seat_id: str) -> str:
    return (ROSTER[seat_id].get("role_title") or "").split(" / ")[0]


def _all_registered_seats() -> dict[str, str]:
    """五张表里出现过的全部席位 → 它出现在哪张表（报错时能指到轴）。"""
    where: dict[str, list[str]] = {}
    for s in FALLBACK_TEAM:
        where.setdefault(s.seat_id, []).append("FALLBACK_TEAM")
    for axis, table in (("STAGE_SEAT", STAGE_SEAT), ("SECTION_SEAT", SECTION_SEAT),
                        ("ARTIFACT_SEAT", ARTIFACT_SEAT), ("TEAM_FALLBACK", None)):
        if table is None:
            for seat_id in TEAM_FALLBACK:
                where.setdefault(seat_id, []).append(axis)
        else:
            for seat_id in table.values():
                where.setdefault(seat_id, []).append(f"{axis}→{seat_id}")
    return {k: "、".join(v) for k, v in where.items()}


REGISTERED = _all_registered_seats()


def test_registry_is_not_empty_and_tables_are_populated():
    """反空转：席位集合为空 ⇒ 下面每条判据都恒真。"""
    assert REGISTERED, "注册表里一个席位都没有 ⇒ 本文件全部判据在空转"
    assert len(REGISTERED) >= 12, f"注册表只解析出 {len(REGISTERED)} 个席位，疑似某张表被清空"


@pytest.mark.parametrize("seat_id", sorted(REGISTERED))
def test_every_registered_seat_exists_in_the_roster(seat_id: str):
    assert seat_id in ROSTER, (
        f"{seat_id}（登记于 {REGISTERED[seat_id]}）不在生活圈名册里 ⇒ 报告署名会退化成裸 id"
    )


@pytest.mark.parametrize("seat_id,keyword", sorted(
    (s.seat_id, s.role_keyword) for s in FALLBACK_TEAM
))
def test_fallback_seat_role_title_contains_its_keyword(seat_id: str, keyword: str):
    """编排期保底队的每位，名册职位必须含注册表登记的关键词。

    变异：把 `FALLBACK_TEAM` 里 L1-032（评分建模师）换成 L1-029 而 `role_keyword` 仍写
    「评分建模」⇒ 本条红。
    """
    assert seat_id in ROSTER, f"{seat_id} 不在名册，无从核对职位"
    assert keyword in _cn_role(seat_id), (
        f"{seat_id} 的职位是「{_cn_role(seat_id)}」，不含登记的「{keyword}」"
        " ⇒ 要么席位选错，要么人设文案变了，注册表要重排"
    )


def test_fallback_duties_are_present_and_distinct():
    """每位保底席都要有自己的 duty 文案，且不得与他人雷同。

    第一版这里写的是「duty 必须含 role_keyword」—— 那条**不成立**：L3-001 的 duty
    「统筹体检全流程、统一指标口径并终审签发」本就不必复述职位名「总检」，
    L1-032 的「评分计算与建模」也不是关键词「评分建模」的连续子串。
    把文案写成必须含某个 token，等于让散文去迁就判据 ⇒ 换成真正要防的那件事：
    复制粘贴同一句话交差。
    """
    duties = [s.duty for s in FALLBACK_TEAM]
    assert all(d.strip() for d in duties), f"有席位的 duty 是空的：{[s.seat_id for s in FALLBACK_TEAM if not s.duty.strip()]}"
    dupes = {d for d in duties if duties.count(d) > 1}
    assert not dupes, f"多位席位共用同一句职责文案：{sorted(dupes)}"
