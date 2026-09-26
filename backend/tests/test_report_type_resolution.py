"""报告类型解析守卫：生活圈报告**不得**被解析成旅游攻略的骨架。

链条（第二片 E0-2 / 附录 G-17、G-18 的根因）：`RESEARCH_TYPES` 目前只有 `guide` 与
`assessment` 两条（`research_types.py:512,531`），而 `DEFAULT_RESEARCH_TYPE = "guide"`
（`:18`）。生活圈报告没有类型 ⇒ `type_spec("living_circle")` 静默拿到 guide 的 spec ⇒
`sections_for()` 返回**旅游的章节集** ⇒ 再经 `section_structured_keys()` 挂上
`spot_ranking / food_ranking / cost_breakdown` 这些旅游专属数据块。

`type_spec` 的回落本身是**有意设计**（其 docstring：「不报错，防透传断链炸掉整条流水线」），
所以本片不主张"未知一律抛错"——那会伤及旧客户端。真正的缺陷是：**一个已存在的报告族
从未注册自己的类型**，于是它借用了别人的骨架。薄是缺陷，错配是事故。

计划编号：E0-2 / TC-23 / TC-24。
"""
import pytest

from app.core.research_types import (
    DEFAULT_RESEARCH_TYPE,
    RESEARCH_TYPES,
    sections_for,
    section_structured_keys,
    type_spec,
)

# 旅游骨架的标志性键：生活圈报告的任何章节都不该挂上它们
TRAVEL_SECTION_IDS = {"spots", "food", "budget", "route", "shops", "stay"}
TRAVEL_STRUCTURED_KEYS = {
    "spot_ranking", "food_ranking", "spot_routes", "shop_list",
    "route_plan", "stay_options", "cost_breakdown",
}


def test_unknown_type_still_falls_back_by_design():
    """保护既有设计决定：未知/空类型回落默认类型，不抛错。

    若哪天有人把它改成 loud fail，本用例会红并逼他回看 `type_spec` 的 docstring ——
    回落是为了不让旧客户端断链，真正的修法在下一条。
    """
    spec = type_spec("totally-unknown-type")
    assert spec is RESEARCH_TYPES[DEFAULT_RESEARCH_TYPE]
    assert type_spec(None) is RESEARCH_TYPES[DEFAULT_RESEARCH_TYPE]


def test_living_circle_report_currently_borrows_the_travel_skeleton():
    """显式记录**当前**缺陷：living_circle 未注册 ⇒ 拿到 guide 的章节集。

    E0-2 落地后本用例必须**改写**为「拿到生活圈自己的章节集」，不许直接删除。
    """
    lc_sections = sections_for("living_circle", "deep")
    guide_sections = sections_for(DEFAULT_RESEARCH_TYPE, "deep")
    assert lc_sections == guide_sections, (
        "living_circle 已不再借用 guide 章节集 —— 请把本用例改写为正向断言："
        "它应返回生活圈自己的骨架，并保留 guide 回落给未知类型。"
    )


@pytest.mark.xfail(
    strict=True,
    reason="E0-2：RESEARCH_TYPES 缺 living_circle 条目 ⇒ 生活圈报告按旅游骨架装配。"
           "注册真类型后摘标记。",
)
def test_living_circle_has_its_own_registered_report_type():
    assert "living_circle" in RESEARCH_TYPES, "生活圈仍无自己的报告类型"
    assert type_spec("living_circle") is not RESEARCH_TYPES[DEFAULT_RESEARCH_TYPE]


@pytest.mark.xfail(
    strict=True,
    reason="G-18 反错配：注册类型前，生活圈章节集会解析出旅游数据块键。",
)
def test_living_circle_sections_never_mount_travel_blocks():
    """反错配主判据：生活圈报告装配路径上不得出现任何旅游键。"""
    lc_sections = sections_for("living_circle", "deep")
    assert not (set(lc_sections) & TRAVEL_SECTION_IDS), (
        f"章节集里混进旅游章节：{sorted(set(lc_sections) & TRAVEL_SECTION_IDS)}"
    )
    mounted = {k for sid in lc_sections for k in section_structured_keys(sid)}
    assert not (mounted & TRAVEL_STRUCTURED_KEYS), f"挂上了旅游数据块键：{sorted(mounted & TRAVEL_STRUCTURED_KEYS)}"
