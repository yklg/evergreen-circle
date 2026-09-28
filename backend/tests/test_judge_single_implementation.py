"""判类只允许一份实现（计划 §1 INV-判据单实现 · TC-39/TC-40 · 返工 P0-1）。

为什么单独守这一条：为了让"换一张表判类"成为可能，探针脚本曾在 `category_key_delta`
里手抄过一份与 `category_rule.evaluate_category` **同序**的裁决循环。那等于同一个谓词
有两份实现 —— 生产判表一改，脚本不同步，就会产出一张"看起来很干净"的假 delta 表，
而且要靠额外的自检才拦得住。本仓自己把这个反模式写得很清楚：

> `report_contract.py:586-589` —— "把两者再合成第三道门，等于让同一个谓词有三份实现，
> 正是本模块反复要消灭的形态。"

⇒ 修法不是给复刻加自检，而是给生产判类开注入口（`evaluate_category(poi, table=…)`）
并**删掉复刻**。本文件的静态守卫保证它不会以另一种形式长回来。

写法沿用本仓惯例：能测的写真测试，判据自带敏感性对照（防恒真守卫）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.living_circle.category_rule import CATEGORY_RULES, evaluate_category

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
FIXTURE_DIR = BACKEND / "app" / "living_circle" / "fixtures"

# 判表的三份组成字段。同时读其中两份以上、又在对映射做 `.items()` 遍历的函数，
# 就是"自己走一遍判表出类别"的形状。
RULE_FIELDS = {"accept_tags", "reject_tags", "keywords"}

# 已核对的合法用量（**不是**裁决，取词而已）：`poi_collector` 用 `accept_tags` /
# `keywords` 生成百度搜索词，不产出类别。列在这里是显式豁免，不是忽略 —— 若哪天它
# 开始返回类别，守卫会因为它多了 `.items()` 裁决形状而变红，届时必须回到本计划登记。
WHITELIST = {("app/living_circle/poi_collector.py", "next")}


def _replicas_in_source(source: str, label: str) -> list:
    """扫一份源码，返回"第二份判类实现"的 (文件, 函数, 读到的判表字段)。"""
    found = []
    tree = ast.parse(source)
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        literals = {
            node.value
            for node in ast.walk(fn)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        } & RULE_FIELDS
        iterates_table = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "items"
            for node in ast.walk(fn)
        )
        if len(literals) >= 2 and iterates_table:
            found.append((label, fn.name, sorted(literals)))
    return found


def _scan_production_sources() -> list:
    roots = [BACKEND / "app", SCRIPTS]
    offenders = []
    scanned = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name == "category_rule.py":
                continue  # 唯一事实源本身
            label = str(path.relative_to(BACKEND))
            scanned += 1
            for hit in _replicas_in_source(path.read_text(encoding="utf-8"), label):
                if (hit[0], hit[1]) in WHITELIST:
                    continue
                offenders.append(hit)
    assert scanned >= 80, (
        f"只扫到 {scanned} 个源文件（实测基线 92）⇒ 扫描根目录已失效，"
        "本守卫会退化成恒真"
    )
    return offenders


def test_no_second_classification_implementation_exists():
    """全仓（app/ + scripts/）除 `category_rule` 外不得再有第二份判类实现。"""
    offenders = _scan_production_sources()
    assert not offenders, (
        "发现第二份判类实现（应改走 evaluate_category(poi, table=…) 注入）："
        f"{offenders}"
    )


def test_the_replica_scanner_actually_catches_the_shape_it_guards():
    """敏感性对照：把删掉的那段复刻原样喂给扫描器，它必须报出来。

    没有这条，上面的守卫可能只是"永远返回空集的装饰件"。
    """
    deleted_replica = '''
def _evaluate_against(table, poi):
    tag = (poi.get("tag") or "").strip().lower()
    for key, defn in table.items():
        for t in defn["accept_tags"]:
            if t in tag:
                return key
        for t in defn["reject_tags"]:
            if t in tag:
                continue
        if any(kw in poi.get("name", "") for kw in defn["keywords"]):
            best = key
    return "other"
'''
    hits = _replicas_in_source(deleted_replica, "<synthetic>")
    assert len(hits) == 1, f"扫描器抓不到已删除的复刻形状 ⇒ 上一条守卫是恒真：{hits}"
    assert hits[0][1] == "_evaluate_against"


def test_the_probe_script_no_longer_carries_a_replica():
    """探针必须走注入口，且历史上那个函数名不得复活。"""
    probe = SCRIPTS / "probe_category_key_delta.py"
    source = probe.read_text(encoding="utf-8")
    assert "_evaluate_against" not in source, "探针里的同序复刻又回来了"
    assert "table=table" in source, "探针没有通过 `table=` 注入判表 ⇒ 它判的不是生产口径"


@pytest.mark.parametrize("poi", [
    {"name": "潘家园旧货市场-立体停车场", "tag": ""},   # 默认表判 shopping
    {"name": "北京眼镜城-地上停车场", "tag": ""},       # 默认表判 other
])
def test_injecting_a_table_never_mutates_the_global_registry(poi):
    """注入必须是纯参数：换表判类不许污染同进程的全局注册表。

    这正是 R2 修掉的那件事 —— 以前只能在测试里 monkeypatch 模块全局来"换表"，
    而全局表一改，同进程其它用例就串味。
    """
    before_order = list(CATEGORY_RULES)
    before_obj = CATEGORY_RULES
    tiny = {"parking": {"accept_tags": ["停车"], "reject_tags": [], "keywords": ["停车"]}}

    verdict = evaluate_category(poi, table=tiny)[0]

    assert verdict == "parking", f"自定义表未被采用，实得 {verdict}"
    assert list(CATEGORY_RULES) == before_order, "全局判表键序被改动"
    assert CATEGORY_RULES is before_obj, "全局判表对象被替换"
    assert evaluate_category(poi)[0] != "parking", "注入泄漏回了默认表"


def _fixture_names() -> list:
    import json

    names = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        stack = [json.loads(path.read_text(encoding="utf-8"))]
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


def test_the_probe_gets_its_delta_only_through_the_injection_seam():
    """探针必须靠注入拿到 delta，而不是靠自己那份判据。

    这里跑的正是探针改完之后的真实通路：默认表 vs 候选表。两边都由
    `category_rule.evaluate_category` 裁决 ⇒ 测得动的差值就等于"生产改了判表"。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "probe_under_test", SCRIPTS / "probe_category_key_delta.py"
    )
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    names = _fixture_names()
    assert len(names) > 200, f"只取到 {len(names)} 个点位名，样本已失效"
    pois = [{"name": name, "tag": ""} for name in names]

    before = probe._classify_with(CATEGORY_RULES, pois)
    after = probe._classify_with(probe._extended_table(), pois)
    assert len(before) == len(after) == len(pois), "探针的分类序列与点位数不吻合"
    assert any(a != b for a, b in zip(before, after)), (
        "候选表一个点位都没改判 ⇒ 注入这条路没接上，delta 表将是假的零变化"
    )
    index = names.index("博南口腔(拉薇公园店)")
    assert after[index] == "scenic", (
        f"已知点位 {names[index]!r} 未经候选表改判（实得 {after[index]}）"
    )
    assert before[index] != "scenic", "默认表里已存在 scenic ⇒ 候选表并未新增类别"
