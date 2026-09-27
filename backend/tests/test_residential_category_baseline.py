"""居住档基线钉死 + 探针可行性核查（第一片 D7 / 片 1-pre / 附录 G-05、TC-06）。

两件事，缺一不可：

1. **基线钉死**：两城 fixture 的逐类目 `total / in_circle / min_minutes`、圈内总数、
   总分、盲区数全部写成字面量。给 `CATEGORY_RULES` 加游客类别（风景名胜/餐饮/酒店/
   停车/公厕/游客中心/交通站点）后，这些数字**必须一字不变** —— 因为新键只增
   「这个 POI 属于哪一类」的分辨率，居住档取哪些类算覆盖一个字都不改（D7）。
   任何一格变化都说明改动越界了，而不是"基线该更新"。

   ⚠️ 只有一类变更允许重钉：**采集口径本身升版**（`scope_policy_version` 变了）。
   那时光标从「可达圈内」挪到「按证据需求逐类外扩」，计数必变，且是**计划爆炸半径表
   预先登记**的变。判据：先看 `caliber.scope_policy_version` 是否换代 —— 换代 ⇒ 随快照
   重钉并在注释里写清是哪一版；未换代而数字动了 ⇒ 越界，按原意处理。
   当前代际：`kaili.json` 仍是升级前的旧快照（未声明版本），`beijing-jinsong.json`
   是 `ev-1` 实测快照（2026-09-27 重刷）。

2. **探针可行性核查**：加键前要先实测真实改判面，但**fixture 存的是判类之后的结果**
   （点位只留 `name/category/minutes/lnglat`，没有百度原始 `tag`）。⇒ 只拿 fixture
   重放，只能复现「按名称弱先验」那半边判据，`accept_tags / reject_tags` 那半边
   **测不到**。若不做本条核查，片 1-pre 的探针会给出一个**看起来干净**的 delta 表
   —— 那是假绿，比没测更糟。
"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"

# 逐类目 (total, in_circle, min_minutes)；None 表示该城该类无可测最近距离
BASELINE = {
    "kaili.json": {
        "totals": {"total": 217, "in_circle": 98, "points": 98},
        "scores_total": 68.7,
        "blindspots": 0,
        "categories": {
            "market": (15, 7, 7.4),
            "medical": (48, 25, 4.7),
            "education": (34, 15, 7.6),
            "shopping": (76, 25, 2.0),
            "elderly": (0, 0, None),
            "finance": (21, 12, 6.2),
            "recreation": (18, 10, 7.1),
            "service": (5, 4, 14.1),
        },
    },
    "beijing-jinsong.json": {
        # ev-1 实测快照（2026-09-27 重刷）。与旧口径相比 market/medical/shopping 采集数
        # 上升 = 证据域逐类外扩 + 分页截断缓解；判定覆盖率 9.1%→21.2%，实测盲区 1→0
        # （新判得的格三类皆有据），综合评分 65.3→65.8。
        # ⚠️ elderly 这一行是 **G1 修复前**的产物：`in_circle=0` 却带 `min_minutes=19.9`
        #    （等时圈凹口外的点把时间灌了进来）。代码已修（`assemble.py` 的 `field_fn`
        #    加多边形门控 + `test_report_invariants.py` 的 G1 用例），但要等下一次真跑
        #    重刷快照才会归 None —— 在那之前由
        #    `test_report_invariants.py::test_g1_residual_in_shipped_jinsong_snapshot`
        #    以 xfail(strict) 记着，别把它当合法基线复制走。
        "totals": {"total": 206, "in_circle": 150, "points": 150},
        "scores_total": 65.8,
        "blindspots": 0,
        "categories": {
            "market": (28, 7, 13.9),
            "medical": (29, 24, 5.6),
            "education": (24, 17, 9.6),
            "shopping": (57, 50, 2.6),
            "elderly": (2, 0, 19.9),
            "finance": (15, 15, 7.0),
            "recreation": (26, 19, 9.7),
            "service": (25, 18, 6.9),
        },
    },
}


def _load(name):
    path = FIXTURES / name
    assert path.exists(), f"fixture 不可达（{path}）—— 基线守卫会空转，须修路径"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_residential_per_category_counts_are_pinned(name):
    """加游客类别键后，居住档逐类目计数必须一字不变（D7 的机器可校验形式）。"""
    poi = _load(name)["poi"]
    expected = BASELINE[name]["categories"]
    actual = {
        c["category"]: (c["total"], c["in_circle"], c.get("min_minutes"))
        for c in poi["categories"]
    }
    assert set(actual) == set(expected), (
        f"{name} 参与统计的类别集变了：{sorted(set(actual) ^ set(expected))} —— "
        "居住档统计子集不得因新增类别键而改变（D7）"
    )
    for cat, want in expected.items():
        assert actual[cat] == want, f"{name}/{cat} 计数漂移：期望 {want}，实得 {actual[cat]}"


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_residential_aggregates_and_scores_are_pinned(name):
    """圈内总数 / 总分 / 盲区数同一条基线：任何一项动都算居住档回归。"""
    report = _load(name)
    want = BASELINE[name]
    assert report["poi"]["total"] == want["totals"]["total"]
    assert report["poi"]["in_circle"] == want["totals"]["in_circle"]
    assert len(report["poi"]["points"]) == want["totals"]["points"]
    assert report["scores"]["total"] == want["scores_total"]
    assert len(report.get("blindspots") or []) == want["blindspots"]


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_poi_conservation_holds_on_fixtures(name):
    """守恒不变量：in_circle == sum(categories.in_circle) == len(points)。"""
    poi = _load(name)["poi"]
    assert poi["in_circle"] == sum(c["in_circle"] for c in poi["categories"])
    assert poi["in_circle"] == len(poi["points"])


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_fixtures_cannot_replay_tag_based_reclassification(name):
    """探针可行性核查：fixture 点位**没有**百度原始 tag ⇒ 只拿它重放判类是半盲。

    这不是"测试失败"，而是把片 1-pre 的**能力边界**钉成可读事实：要真正实测
    「加键会不会改判居住 POI」，必须先拿到含 `tag` 的活体 POI 快照（或给 fixture
    补原始字段）。fixture 一旦补上 tag，本用例会红并提示把探针升级为全量重放。
    """
    points = _load(name)["poi"]["points"]
    assert points, "fixture 无点位，本核查失去意义"
    raw_tag_keys = {"tag", "tags", "type", "detail"} & set(points[0])
    assert not raw_tag_keys, (
        f"fixture 已含原始判类输入 {sorted(raw_tag_keys)} —— "
        "片 1-pre 的探针现在可以做全量重放，请把本用例改写为真实改判面 delta 表"
    )


def test_probe_must_not_claim_full_coverage_from_name_only_replay():
    """判据可追溯性：`evaluate_category` 的 accept/reject_tags 分支在 fixture 上不可达。

    与上一条配对，防止有人拿"探针跑过、delta 为 0"当放行依据。
    """
    from app.living_circle import category_rule

    tag_driven = [
        cat for cat, rule in category_rule.CATEGORY_RULES.items()
        if rule.get("accept_tags") or rule.get("reject_tags")
    ]
    assert tag_driven, "判表已无 tag 驱动分支，本用例判据须重指"
