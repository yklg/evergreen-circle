"""信源分类判据词表只能有一处（实施计划 v3 §九 · TC-39 + 扫描器自证 + 防空转双保险）。

守护的契约
----------
「一个 URL 属于哪类信源」的**分类判据词表**（非官网特征 / 财报投关 / 新闻媒体三张表）
曾经存在**两份完全相同的副本**：

    app/core/source_type.py                     ← 计划指定的唯一落点
    app/core/pipeline/research/collect.py       ← 生产流水线实际在用的那份

两份内容逐字相同 ⇒ "改一处忘另一处"只会静默分叉，不会让任何测试变红。
计划 v3 §一 B-P0-1 的结论是：G0 的注册表**升级 `source_type.py` 本身**，
而不是再新造一个模块 —— 否则"信源类别的真相源"从两份变三份。
副本已随 G0 删除；本守卫留着，把「第二份词表回潮」钉成结构防线。

写法照抄仓库既有惯例（不是新造）
--------------------------------
`tests/test_registry_single_source.py` 已经确立了三件套：
  1. 静态 AST 扫描「注册表外不得再出现第二份清单」（`:62-91`）
  2. 防空转双保险「期望集为空 / 一个候选都没扫到 ⇒ 先判红」（`:114-129`）
  3. 坏样本自证「造一个真坏输入，守卫必须点名它」（`:153-168`）
本文件逐条对齐，缺任何一条都视为恒绿假护栏。

期望值来源
----------
三张词表的字面值采集自 `app/core/source_type.py` 当前实现（AST 抽取，非手抄）；
`test_frozen_vocab_still_matches_the_live_registry` 把「冻结表 == 现表」也钉住，
改词表必须同步改本文件，否则红。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import source_type as ST

_BACKEND = Path(__file__).resolve().parents[1]
_APP = _BACKEND / "app"

ALLOWED_HOME = "source_type.py"          # 唯一合法持有者（计划 v3 §二 G0）

# 采集自 app/core/source_type.py 的 NON_OFFICIAL_HINTS / FINANCIAL_HINTS / NEWS_HINTS
FROZEN_VOCAB = {
    "非官网特征": [
        "blog", "news", "wiki", "csdn", "jianshu", "juejin", "zhihu", "baijiahao",
        "toutiao", "medium", "wordpress", "cnblogs", "segmentfault", "oschina",
    ],
    "财报投关": ["ir.", "investor", "annualreport", "sec.gov", "10-k", "财报", "年报"],
    "新闻媒体": [
        "news", "36kr", "sina", "163.com", "qq.com", "ifeng", "sohu", "huxiu",
        "tmtpost", "caixin", "yicai", "people.com", "xinhuanet", "thepaper",
        "cls.cn", "stcn", "eastmoney", "cnbeta", "leiphone", "iyiou", "geekpark",
        "techcrunch", "theverge", "bloomberg",
    ],
}

# 一份清单里命中 ≥3 个判据词即视为「第二份分类判据」（阈值理由：
# 三张表的最小长度是 7，任何合法的单点复用都不可能凑到 3 个词）
_MIN_DUPLICATE_TERMS = 3

VOCAB_UNION = frozenset(sum(FROZEN_VOCAB.values(), []))

# 扫描域必须覆盖到的模块（计划 v3 §五 认定的分类相关落点）。
# 用它代替「文件数 > N」这类魔数：作用域塌了要能指名道姓地红。
_MUST_BE_SCANNED = {
    "core/source_type.py",
    "core/platforms.py",
    "core/credibility.py",
    "core/pipeline/research/collect.py",
    "core/pipeline/research/engine.py",
    "core/pipeline/research/spots.py",
}


def _duplicate_vocab_hits(tree: ast.AST) -> list:
    """扫一份 AST，返回 (行号, 命中词数, 命中词) 清单。纯函数，便于坏样本自证。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        vals = [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        overlap = [v for v in vals if v in VOCAB_UNION]
        if len(overlap) >= _MIN_DUPLICATE_TERMS:
            out.append((node.lineno, len(overlap), overlap))
    return out


def _scan_app():
    """返回 (扫描到的相对路径集合, [(文件, 行号, 命中数)])；唯一合法持有者被排除。"""
    scanned, hits = set(), []
    for p in sorted(_APP.rglob("*.py")):
        rel = p.relative_to(_APP).as_posix()
        scanned.add(rel)
        if p.name == ALLOWED_HOME:
            continue
        for lineno, n, overlap in _duplicate_vocab_hits(
                ast.parse(p.read_text(encoding="utf-8"), filename=str(p))):
            hits.append((rel, lineno, n, overlap))
    return scanned, hits


# ── TC-39：注册表外不得再出现第二份分类判据词表 ─────────────────────────
#
# 转正记录（G0 已落地）：本例生成时是 `xfail(strict=True)`，因为 `collect.py:23,53,56`
# 那份副本当时就在，且**生产流水线用的是副本那份**。G0 删掉副本、把
# `engine.py` / `spots.py` 的 import 改指 `app.core.source_type` 后转 XPASS = FAILED，
# 按 §十.4 的约定摘掉标记、断言体一字未动。它今天的价值是**防回潮**：
# 谁再抄一份词表进别的模块，本例会点名到文件与行号。
def test_no_second_copy_of_classification_vocabulary_outside_the_registry():
    scanned, hits = _scan_app()
    assert not hits, "分类判据词表出现第二份：" + "; ".join(
        f"{f}:{ln}（命中 {n} 词，如 {ov[:3]}）" for f, ln, n, ov in hits
    )


# ── 防空转双保险（真测试，今天应绿）────────────────────────────────────


def test_guard_scope_and_vocabulary_are_not_empty():
    """两条空转保险：词表为空 ⇒ 判据退化成恒真；扫描域不含关键模块 ⇒ 守卫在空转。"""
    assert VOCAB_UNION, "判据词表为空 ⇒ 本守卫必然恒绿，先确认是不是被改名了"
    assert len(VOCAB_UNION) >= 30, f"词表疑似被截断，只剩 {len(VOCAB_UNION)} 词"

    scanned, _ = _scan_app()
    missing = sorted(_MUST_BE_SCANNED - scanned)
    assert not missing, f"扫描域缺少分类相关模块（作用域塌了）：{missing}"

    assert scanned, "app/ 下一个 .py 都没扫到 ⇒ 守卫空转（目录搬家是这个形状）"


def test_frozen_vocab_still_matches_the_live_registry():
    """冻结表 == `source_type.py` 现表。改词表必须显式同步本文件。

    注意正本里「财报投关 / 新闻媒体」两张表是**内联在 `any(...)` 里**的
    （source_type.py:46 / :49），不是模块顶层赋值 —— 所以必须 ast.walk 整棵树，
    只遍历 tree.body 会把它们漏掉、进而把正本判成"词表被改"（假红）。
    """
    tree = ast.parse((_APP / "core" / ALLOWED_HOME).read_text(encoding="utf-8"))
    live_lists = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vals) >= 3:
                live_lists.append(vals)
    assert live_lists, "source_type.py 里扫不到分类判据词表 ⇒ 正本被改名或重排，先修这里"

    for name, expected in FROZEN_VOCAB.items():
        assert expected in live_lists, (
            f"词表「{name}」与正本不一致（正本被改动？请同步本文件与 G0 注册表）"
        )


# ── 坏样本自证（真测试，证明扫描器有牙，不是恒绿假护栏）─────────────────


@pytest.mark.parametrize("snippet,expect_hits", [
    # 副本原样：必被判
    ('HINTS = ("blog", "news", "wiki", "csdn")', 1),
    ('HINTS = ["36kr", "sina", "caixin"]', 1),
    # 集合形态同样要判（分类词表常以 set 存在）
    ('HINTS = {"ir.", "investor", "sec.gov"}', 1),
    # 只有 2 个词：不足阈值，属合法复用（别把正常代码判成违例）
    ('HINTS = ("36kr", "sina")', 0),
    # 词表外的字符串清单：不判
    ('HINTS = ("douyin", "xiaohongshu", "bilibili")', 0),
    ('HINTS = ("https://a.com/x", "https://b.com/y", "https://c.com/z")', 0),
])
def test_scanner_fires_on_synthetic_bad_samples_only_where_it_should(snippet, expect_hits):
    hits = _duplicate_vocab_hits(ast.parse(snippet))
    assert len(hits) == expect_hits, f"{snippet!r} 期望 {expect_hits} 命中，实际 {hits}"


def test_scanner_reports_which_terms_matched_not_just_a_count():
    """报错信息必须点名命中词——否则维护者无法判断是真重复还是巧合词面。"""
    hits = _duplicate_vocab_hits(ast.parse('X = ["blog", "news", "wiki"]'))
    assert len(hits) == 1
    _, n, overlap = hits[0]
    assert n == 3 and set(overlap) == {"blog", "news", "wiki"}
