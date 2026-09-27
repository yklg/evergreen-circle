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
居住基线数字**，属需单独决策的显式契约变更 —— 届时 `test_residential_category_baseline.py`
的钉值会整组转红，那是它该做的事，不是回归。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.living_circle.category_rule import CATEGORY_RULES, evaluate_category

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"


def _fixture_names() -> list[str]:
    names: list[str] = []
    for fname in ("kaili.json", "beijing-jinsong.json"):
        d = json.loads((FIXTURES / fname).read_text(encoding="utf-8"))
        names += [p["name"] for p in d["poi"]["points"]]
    assert names, "fixture 读空 ⇒ 本文件失去真实样本"
    return names


def _name_matches(name: str) -> list[str]:
    """按判表书写次序，列出名称弱先验命中的全部类别。"""
    hit: list[str] = []
    for key, rule in CATEGORY_RULES.items():
        if any(kw and kw in name for kw in rule["keywords"]):
            hit.append(key)
    return hit


def test_multi_category_names_exist_in_real_samples():
    """前提事实：真实点位里确实存在"名称命中多个类"的情况（不是理论构造）。"""
    colliding = [(n, _name_matches(n)) for n in _fixture_names() if len(_name_matches(n)) >= 2]
    assert colliding, "判表已无名称交叉 ⇒ 本文件判据须重指"
    printable = "；".join(f"{n}→{h}" for n, h in colliding[:5])
    print(f"\n名称多类命中点位 {len(colliding)} 个：{printable}")


def test_last_written_category_wins_today():
    """**现状记录（缺陷本体）**：名称命中多类时，胜出者是**判表里写得最后**的那个。

    用真实点位说：农贸市场同时命中 market 与 shopping，今天判给 shopping ——
    菜市场类被"书写更靠后"的购物类吃掉。
    """
    for name in _fixture_names():
        hit = _name_matches(name)
        if len(hit) >= 2 and "农贸市场" in name:
            got = evaluate_category({"name": name, "lng": 0, "lat": 0})[0]
            assert got == hit[-1], f"裁决规则若已改，本用例判据须重指：{name} → {got}，命中次序 {hit}"
            assert got != "market", (
                f"{name} 已判给 market ⇒ 次序缺陷似已修，请删除本记录用例并把"
                "test_multi_hit_is_treated_as_ambiguous 的缺口标记摘掉"
            )
            return
    pytest.fail("两城样本里找不到带「农贸市场」的多类命中点位，前提事实变了 ⇒ 须重指判据")


def test_reversing_table_order_reverses_the_verdict():
    """**反向对照**：只颠倒判表书写次序，同一句话就换一个类别。

    没有这条，上面那条可能只是"shopping 恰好更专属性"的巧合。次序可逆 ⇒ 结论由
    dict 顺序决定，而不是由语义决定 —— 这才是要修的根因。
    """
    reversed_table = dict(reversed(list(CATEGORY_RULES.items())))
    for name in _fixture_names():
        base = [k for k in CATEGORY_RULES if any(kw and kw in name for kw in CATEGORY_RULES[k]["keywords"])]
        if len(base) < 2:
            continue
        last_normal, last_reversed = base[-1], list(reversed(base))[-1]
        assert last_normal != last_reversed, "两类命中却同序 ⇒ 样本选得不对，换一条"
        # 用生产函数逐点判：临时换掉注册表，**必须**在 finally 里还原
        original = copy.deepcopy(CATEGORY_RULES)
        try:
            CATEGORY_RULES.clear()
            CATEGORY_RULES.update(reversed_table)
            flipped = evaluate_category({"name": name, "lng": 0, "lat": 0})[0]
        finally:
            CATEGORY_RULES.clear()
            CATEGORY_RULES.update(original)
        assert flipped == last_reversed, (
            f"{name}：正序判 {last_normal}、逆序判 {flipped} ⇒ 若不再由次序决定，"
            "本用例须改写为「裁决与次序无关」的正向断言"
        )
        return
    pytest.fail("样本里已不存在名称多类命中的点位 ⇒ 前提消失，本文件判据须重指")


@pytest.mark.xfail(
    strict=True,
    reason="category_rule.py:144 的注释承诺「名称命中落在多类 → 归 other」，实现里没有多类计数",
)
def test_multi_hit_is_treated_as_ambiguous():
    """缺口登记：名称多类命中必须按注释所说判为模糊（归 other / 或显式降置信并披露）。

    修法定了之后本用例转绿 ⇒ 强制摘标记；同时 `test_residential_category_baseline.py`
    的钉值会整组转红（因为 market/shopping 的归属真的会变），那是**显式基线变更**，
    需要单独决策，不许就地改数。
    """
    name = next((n for n in _fixture_names() if "农贸市场" in n), None)
    assert name is not None, "样本里没有「农贸市场」点位，判据须重指"
    assert evaluate_category({"name": name, "lng": 0, "lat": 0})[0] == "other"
