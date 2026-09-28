"""名称弱先验的裁决次序缺陷（片 1-pre 探针当场抓出，第一片 D7 的关键路径前置）。

跑 `scripts/probe_category_key_delta.py --source fixture`（两城 202 个点位，零额度）时，
居住档计数出现非零 delta：加 7 个游客候选键后 `recreation` 少 2。顺着它查下去，发现的
问题比"加键会不会动基线"更根因 ——

`category_rule.evaluate_category` 的名称弱先验是**for 循环里最后一个命中者胜出**
（`category_rule.py:141-143`：`best = (key, mid); best_name_hit = key` 无多类计数），
而它上面那行注释写的是「名称命中落在多类（模糊）→ 归 other，避免以名称拍脑袋」。
**注释与实现不一致**，且实现把结论交给了 `CATEGORY_RULES` 的**书写顺序**。

⇒ 两个后果：
1. **今天就已在误判**：真实点位「洪源居农贸市场」「金井农贸市场」被算进 `shopping`
   而不是 `market` —— 而菜市场正是盲区三要素之一，等于把判定输入判错了；
2. **片 1 的探针结论不可解释**：任何新键只要名字子串撞上，就会靠"写在后面"抢走既有点位，
   delta 大小取决于 dict 次序而不是语义。⇒ 不先定裁决规则，加键的"会不会动居住基线"
   根本测不出可归因的答案。

本文件只做两件事：把**当前行为**钉成可读事实（绿），把**注释承诺的规则**登记成缺口
（`xfail(strict)`）。真正的修法（最长匹配优先 / 专属性权重 / 归 other 并披露）会**改动
居住基线数字**，属需单独决策的显式契约变更。（2026-09-29 修法落地后基线**未**转红：
那些点位由 `accept_tags` 先裁掉，名称弱先够不到；见 `test_multi_hit_is_treated_as_ambiguous`
的说明。）
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.living_circle import category_rule
from app.living_circle.category_rule import CATEGORY_RULES, evaluate_category
from app.living_circle.poi import norm_name

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"


def _fixture_names() -> list[str]:
    names: list[str] = []
    for fname in ("kaili.json", "beijing-jinsong.json"):
        d = json.loads((FIXTURES / fname).read_text(encoding="utf-8"))
        names += [p["name"] for p in d["poi"]["points"]]
    assert names, "fixture 读空 ⇒ 本文件失去真实样本"
    return names


def _name_matches(name: str) -> list[str]:
    """按判表书写次序，列出名称弱先验命中的全部类别。

    归一走 `norm_name`（与生产同一份）：判类现在吃归一名，helper 吃原始名就会与生产
    判断不同源，本文件的"多类命中"样本会挑错。
    """
    normed = norm_name(name)
    hit: list[str] = []
    for key, rule in CATEGORY_RULES.items():
        if any(kw and kw in normed for kw in rule["keywords"]):
            hit.append(key)
    return hit


def test_multi_category_names_exist_in_real_samples():
    """前提事实：真实点位里确实存在"名称命中多个类"的情况（不是理论构造）。"""
    colliding = [(n, _name_matches(n)) for n in _fixture_names() if len(_name_matches(n)) >= 2]
    assert colliding, "判表已无名称交叉 ⇒ 本文件判据须重指"
    printable = "；".join(f"{n}→{h}" for n, h in colliding[:5])
    print(f"\n名称多类命中点位 {len(colliding)} 个：{printable}")


def test_ruling_is_independent_of_table_order():
    """正向不变量：颠倒判表书写次序，裁决必须**不变**。

    2026-09-29 由「反向对照」改写而来 —— 原用例断言"逆序就换一类"，那钉的是缺陷本体，
    修法落地后它必然红（原用例自己的收尾语就是这么指示的）。现在钉的是同一处的契约：
    名称多类命中归 `other`，与 `CATEGORY_RULES` 的书写次序无关。

    换表用**整体替换对象**而非 `clear()+update()`：后者靠 in-place 改序，一旦哪天
    `dict == dict` 的比较被拿来当"还原成功"的证据就会假还原（同 TC-43 harness 的教训）。
    """
    candidates = [n for n in _fixture_names() if len(_name_matches(n)) >= 2 and "农贸市场" in n]
    assert candidates, "样本里已不存在名称多类命中的「农贸市场」点位 ⇒ 前提消失，判据须重指"
    name = candidates[0]
    expected = evaluate_category({"name": name, "lng": 0, "lat": 0})
    assert expected[0] == "other", f"多类命中未归 other：{name} → {expected}"

    original = category_rule.CATEGORY_RULES
    reversed_table = dict(reversed(list(original.items())))
    assert list(reversed_table) != list(original), "判表键序对称 ⇒ 逆序等于正序，本用例无效力"
    try:
        category_rule.CATEGORY_RULES = reversed_table
        flipped = evaluate_category({"name": name, "lng": 0, "lat": 0})
    finally:
        category_rule.CATEGORY_RULES = original
    assert flipped == expected, (
        f"{name}：正序 {expected}、逆序 {flipped} ⇒ 裁决重新被书写次序决定（R1-b 回潮）"
    )
    assert list(category_rule.CATEGORY_RULES) == list(original), "还原失败 ⇒ 会污染同批其它判类用例"


def test_multi_hit_is_treated_as_ambiguous():
    """缺口登记 → 落地：名称多类命中按注释所说判为模糊（归 other、置信 low）。

    原 docstring 预告 `test_residential_category_baseline.py` 的钉值会整组转红、需单独决策。
    2026-09-29 实测**没有转红**（全量 2176 passed，基线 8 类 × 2 城逐条绿）—— 原因是那些
    点位先被 `accept_tags` 路径裁掉，名称弱先验轮不到它们。所以那次"显式基线变更"的决策
    并没有被触发；若将来重刷夹具使名称先验重新起作用，基线仍可能动，届时按原指示办。
    """
    name = next((n for n in _fixture_names() if "农贸市场" in n), None)
    assert name is not None, "样本里没有「农贸市场」点位，判据须重指"
    assert evaluate_category({"name": name, "lng": 0, "lat": 0})[0] == "other"
