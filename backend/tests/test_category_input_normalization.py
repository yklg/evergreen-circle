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


def test_classification_input_is_normalized_like_the_rest_of_the_pipeline():
    """TC-41 / R1-a 落地。

    2026-09-29 重指判据：原来比的是**命中类集差异**（`_divergent_names()`）—— 那说的是
    "括号里确实含跨类关键词"这一名称层事实，输入归一修好后它依然成立，继续拿它当缺陷判据
    会把已修读成未修。现在钉契约本身：**喂原始名与喂归一名必须得到同一判定**。
    """
    divergent = {
        name
        for name in _fixture_names()
        if evaluate_category({"name": name, "tag": ""})
        != evaluate_category({"name": norm_name(name), "tag": ""})
    }
    assert divergent == set(), f"判类仍随输入是否归一而变：{sorted(divergent)[:5]}"


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


def test_the_shuffle_harness_still_has_teeth():
    """对照的有效性自检：TC-43 不得是恒真守卫。

    2026-09-29 重指：R1-b 修好后「乱序下 verdict 会翻」这件事**不再成立**，原对照随之失效。
    TC-43 要防的仍是同一个坑，所以这里改钉两点前提：
    ① 样本确实**多类命中**，且命中类集的首末元素不同 —— 若实现退回"最后命中者胜"，
       正序与逆序判表必然给出两个类别（对照有牙的证明，不靠生产码里留着缺陷来提供牙）；
    ② 换掉模块全局判表真的能改判定 —— 否则说明 `evaluate_category` 把表烧进了默认参数，
       harness 的注入路是假的，TC-43 只是在原地打转。
    """
    assert "新发地农贸市场" in ORDER_SENSITIVE_SAMPLES
    assert len(ORDER_SENSITIVE_SAMPLES) >= 3, "样本集被缩减 ⇒ 本对照与 TC-43 同时失去效力"
    ambiguous = {n for n in ORDER_SENSITIVE_SAMPLES if len(_name_hits(CATEGORY_RULES, n)) >= 2}
    assert "新发地农贸市场" in ambiguous, (
        f"样本已不再多类命中（{sorted(ambiguous)}）⇒ 换样本，否则 TC-43 恒真"
    )
    for name in sorted(ambiguous):
        hits = _name_hits(CATEGORY_RULES, name)
        assert hits[0] != hits[-1], f"{name!r} 命中类集首末同为 {hits[0]} ⇒ 次序敏感读不出来，须换样本"

    original = category_rule.CATEGORY_RULES
    try:
        category_rule.CATEGORY_RULES = {}
        burned = evaluate_category({"name": "新发地农贸市场", "tag": ""})
    finally:
        category_rule.CATEGORY_RULES = original
    assert burned[0] == "other", (
        "清空判表却不改判定 ⇒ evaluate_category 没读模块全局，注入这条路是假的"
    )


def test_the_shuffle_harness_restores_the_key_order():
    before = list(CATEGORY_RULES)
    _verdicts_under_shuffles("新发地农贸市场", rounds=8)
    assert list(CATEGORY_RULES) == before, "重排后未还原键序 —— 会污染同批其它判类用例"


def test_name_prior_verdicts_are_independent_of_rule_table_order():
    for name in ORDER_SENSITIVE_SAMPLES:
        verdicts = _verdicts_under_shuffles(name)
        assert len(verdicts) == 1, f"{name!r} 在键序置换下得到多种判定：{sorted(verdicts)}"


def test_the_documented_promise_is_still_in_the_source():
    """注释被改写/删掉时本条变红：R1-b 的契约问题必须回到计划里重判，不许悄悄改掉承诺。"""
    source = Path(category_rule.__file__).read_text(encoding="utf-8")
    assert "名称命中落在多类" in source, "category_rule.py 的承诺注释已改动 ⇒ 回到计划 §0 C-10 重指判据"


def test_the_ruling_baseline_after_the_fix():
    """落地后的裁决基线（由"记录现状"条重指而来）。

    两半都要钉住，缺一半就会把修正在往错误方向跑读成绿：
    ① 多类命中 ⇒ `other/low`（不再由判表书写次序决定）；
    ② **单类命中仍归该类、仍给 mid** —— 反向对照。把"归 other"做成"名称先验一律不算数"
       是过度收窄，那样 8 类点位会大面积塌成 other，本条会红。
    """
    order = list(CATEGORY_RULES)
    assert order.index("market") < order.index("shopping"), "判表书写次序已变，本条判据需重指"
    assert evaluate_category({"name": "新发地农贸市场", "tag": ""}) == ("other", CONFIDENCE["low"])

    single = next(
        (n for n in _fixture_names() if len(_name_hits(CATEGORY_RULES, norm_name(n))) == 1), None
    )
    assert single is not None, "样本里没有单类命中点位 ⇒ 无法证明未过度收窄，判据须重指"
    hit = _name_hits(CATEGORY_RULES, norm_name(single))[0]
    assert evaluate_category({"name": single, "tag": ""}) == (hit, CONFIDENCE["mid"]), (
        f"{single!r} 单类命中 {hit} 却没被判给它 ⇒ 名称先验被过度收窄"
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
