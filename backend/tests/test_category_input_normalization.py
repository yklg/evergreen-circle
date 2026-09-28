"""判类输入归一与冲突裁决（计划 v7 第二轮覆盖评估 · TC-41 … TC-45）。

守护的契约（回溯见计划 §3 G-31/G-32 与 §0 C-11/C-12）：

  * **TC-41 / R1-a** —— 名称里的括号是**分店名/限定语**，`poi.norm_name` 已经为显示与
    实体归并剥掉它，唯独判类吃的是原始名 ⇒ 括号内容会向判类注入跨类关键词。
  * **TC-42 / R1-a×R1-b** —— 真实缺陷样本：`博南口腔(拉薇公园店)` 今天判 `recreation`
    （「口腔」不是任何类的关键词，唯一命中的是括号里的「公园」）。
  * **TC-43 / R1-b** —— 名称弱先验是「判表里最后写命中者胜」（`category_rule.py:141-143`）
    ⇒ 判定随判表**书写次序**变化。修法（显式特异性 / 冲突归 other）未定，先钉后果。
  * **TC-44 / C-10** —— `category_rule.py:144` 的注释承诺「多类命中→归 other」，与实现不一致。
  * **TC-45** —— `accept_tags` 目前**无跨类重叠**（实测），标签路径因此次序无关；
    本条只作**防回归棘轮**，不冒充已发现问题。

写法沿用本仓惯例：今天能测的写成真测试；依赖未实现修复的写成 `xfail(strict=True)`
（落地转绿而不摘标记会主动报 XPASS）。**不放宽任何断言**。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.living_circle import category_rule
from app.living_circle.category_rule import CONFIDENCE, CATEGORY_RULES, _norm, evaluate_category
from app.living_circle.poi import norm_name

FIXTURE_DIR = Path(category_rule.__file__).parent / "fixtures"

# 实测基线（两城 fixture 250 个名称 / 101 个带括号）：这 4 个名字的命中类集会因
# `norm_name` 而改变 —— 判类吃原始名，其它层吃归一名。只降不升。
BRACKET_INPUT_DIVERGENT = {
    "博南口腔(拉薇公园店)",
    "中国农业银行24小时自助银行(贵府佳和拉薇公园支行)",
    "梦石楼(潘家园旧货市场店)",
    "中国邮政(劲松八区邮政所)",
}

# 真实点位名样本：`新发地农贸市场` 已知会在 `market`/`shopping` 之间翻转。
ORDER_SENSITIVE_SAMPLES = (
    "新发地农贸市场",
    "博南口腔(拉薇公园店)",
    "中国农业银行24小时自助银行(贵府佳和拉薇公园支行)",
)


def _name_hits(table: Dict[str, Dict[str, Any]], name: str) -> List[str]:
    """名称弱先验的命中类集 —— 刻意复用生产的 `_norm`，不另写一份归一。

    本文件守的正是「同一判据只允许一份实现」，在这里复刻判据就等于自我否决。
    """
    return [
        cat
        for cat, defn in table.items()
        if any(_norm(kw) in _norm(name) for kw in defn.get("keywords", []))
    ]


def _fixture_names() -> List[str]:
    names: List[str] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        stack: List[Any] = [json.loads(path.read_text(encoding="utf-8"))]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "name" and isinstance(value, str):
                        names.append(value)
                    else:
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return names


def _divergent_names() -> set:
    return {
        name
        for name in _fixture_names()
        if set(_name_hits(CATEGORY_RULES, name)) != set(_name_hits(CATEGORY_RULES, norm_name(name)))
    }


def test_fixture_names_are_actually_scanned():
    """扫描有效性自检：采不到名称时，上面两条输入同源用例就是无样本空过。"""
    names = _fixture_names()
    assert len(names) > 200, f"只扫到 {len(names)} 个名称，判据已与 fixture 脱节"


def test_the_unnormalized_input_defect_is_exactly_the_registered_four():
    """记录现状（只降不升棘轮）：名单变大 = 新缺陷；变小 = 回到计划重指判据。"""
    assert _divergent_names() == BRACKET_INPUT_DIVERGENT, (
        f"括号改变命中类集的名称已变化：{sorted(_divergent_names())}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="TC-41 / R1-a：判类吃原始 name，norm_name 只作用于显示与实体归并 ⇒ 括号里的分店名向判类注入跨类关键词",
)
def test_classification_input_is_normalized_like_the_rest_of_the_pipeline():
    assert _divergent_names() == set(), f"仍因输入未归一而判类不同：{sorted(_divergent_names())}"


@pytest.mark.xfail(
    strict=True,
    reason="TC-42 / R1-a：`博南口腔(拉薇公园店)` 现判 recreation —— 唯一命中的是括号里的「公园」，「口腔」不是任何类关键词",
)
def test_a_dental_clinic_is_not_classified_by_its_branch_name():
    category, confidence = evaluate_category({"name": "博南口腔(拉薇公园店)", "tag": ""})
    assert category != "recreation", f"分店名注入了跨类关键词：{category}/{confidence}"
    assert category in {"medical", "other"}, f"应归 medical，或诚实归 other 并降置信：{category}"
    assert confidence <= CONFIDENCE["mid"], "名称-only 的判定不许顶着高置信"


def _verdicts_under_shuffles(name: str, rounds: int = 50) -> set:
    """整体换掉 `category_rule.CATEGORY_RULES` 这个**对象**，finally 里换回原对象。

    绝不用 `clear()+update()`：`dict == dict` 忽略键序，那样"还原"是假的，
    实测会骗出同一个名字两种判定（本函数曾以此自伤过一次）。
    """
    original = category_rule.CATEGORY_RULES
    rng = random.Random(20260928)
    keys = list(original)
    verdicts = set()
    try:
        for _ in range(rounds):
            shuffled = keys[:]
            rng.shuffle(shuffled)
            category_rule.CATEGORY_RULES = {k: original[k] for k in shuffled}
            verdicts.add(evaluate_category({"name": name, "tag": ""})[0])
    finally:
        category_rule.CATEGORY_RULES = original
    return verdicts


def test_the_shuffle_harness_actually_flips_a_known_sample():
    """敏感性对照：harness 翻不动已知样本，就说明下面那条不变性是恒真守卫。

    同时校验 `evaluate_category` 确实读模块全局（若它把表烧进了默认参数，本对照会红）。
    """
    assert "新发地农贸市场" in ORDER_SENSITIVE_SAMPLES
    assert len(ORDER_SENSITIVE_SAMPLES) >= 3, "样本集被缩减 ⇒ 本对照与 TC-43 同时失去效力"
    flipped = {n for n in ORDER_SENSITIVE_SAMPLES if len(_verdicts_under_shuffles(n)) > 1}
    assert "新发地农贸市场" in flipped, (
        "乱序 harness 无牙：名称弱先验并未随 CATEGORY_RULES 键序变化 ⇒ TC-43 的用例将恒真"
    )


def test_the_shuffle_harness_restores_the_key_order():
    before = list(CATEGORY_RULES)
    _verdicts_under_shuffles("新发地农贸市场", rounds=8)
    assert list(CATEGORY_RULES) == before, "重排后未还原键序 —— 会污染同批其它判类用例"


@pytest.mark.xfail(
    strict=True,
    reason="TC-43 / R1-b：名称多类命中是「判表里最后写命中者胜」⇒ 判定随键序漂移，裁决规则未定",
)
def test_name_prior_verdicts_are_independent_of_rule_table_order():
    for name in ORDER_SENSITIVE_SAMPLES:
        verdicts = _verdicts_under_shuffles(name)
        assert len(verdicts) == 1, f"{name!r} 在键序置换下得到多种判定：{sorted(verdicts)}"


def test_the_documented_promise_is_still_in_the_source():
    """注释被改写/删掉时本条变红：R1-b 的契约问题必须回到计划里重判，不许悄悄改掉承诺。"""
    source = Path(category_rule.__file__).read_text(encoding="utf-8")
    assert "名称命中落在多类" in source, "category_rule.py 的承诺注释已改动 ⇒ 回到计划 §0 C-10 重指判据"


def test_todays_behaviour_is_last_written_hit_wins():
    """记录现状：实现返回的是判表里**更靠后**的那个命中类（与上一条注释的承诺相反）。

    修好 R1-b（显式特异性或归 other）后本条会红，那是要你回来改基线，不是回归失败。
    """
    order = list(CATEGORY_RULES)
    assert order.index("market") < order.index("shopping"), "判表书写次序已变，本条判据需重指"
    assert evaluate_category({"name": "新发地农贸市场", "tag": ""})[0] == "shopping"


@pytest.mark.xfail(
    strict=True,
    reason="TC-44 / C-10：`category_rule.py:144` 注释承诺「多类命中→归 other」，:141-146 实现是最后命中者胜",
)
def test_multi_category_name_hits_follow_the_documented_rule():
    assert evaluate_category({"name": "新发地农贸市场", "tag": ""})[0] == "other"


def _categories_accepting(table: Dict[str, Dict[str, Any]], tag: str) -> List[str]:
    """复用生产的 `_tag_hit`（含 reject 优先），不在测试里另写一套标签裁决。"""
    out = []
    for cat, defn in table.items():
        a_hit, _ = category_rule._tag_hit(tag, defn.get("accept_tags", []), defn.get("reject_tags", []))
        if a_hit:
            out.append(cat)
    return out


def test_no_tag_is_accepted_by_two_categories():
    """防回归棘轮（今天实测成立）：一旦有标签被多类接受，标签路径也会变成次序相关。"""
    tags = [t for defn in CATEGORY_RULES.values() for t in defn.get("accept_tags", []) if _norm(t)]
    assert len(tags) >= 20, f"只扫到 {len(tags)} 个 accept_tags，判据已与判表脱节"
    offenders = {t for t in tags if len(_categories_accepting(CATEGORY_RULES, t)) > 1}
    assert not offenders, f"这些标签被多类接受：{sorted(offenders)}"


def test_the_overlap_checker_has_teeth():
    synthetic = {
        "dental": {"accept_tags": ["诊所"], "reject_tags": [], "keywords": []},
        "shopping": {"accept_tags": ["诊所", "超市"], "reject_tags": [], "keywords": []},
    }
    assert _categories_accepting(synthetic, "诊所") == ["dental", "shopping"], (
        "检查器抓不到人为植入的重叠 ⇒ 上一条用例是恒真守卫"
    )
