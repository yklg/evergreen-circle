"""词表闸的生产接线（附录 G-19，第二片 E0-3，TC-25）。

词表闸 `caliber_index.validate_vocabulary` 本身**是好的** —— 它能把不在允许词表里的
指标术语挑出来（见 `test_gate_rejects_a_fabricated_metric_name`）。问题在它
**在生产路径里一个调用者都没有**：全仓只有 `tests/test_expert_caliber_refs.py` 在跑它
（`grep -rn validate_vocabulary app/` 只命中定义处）。

⇒ 现状是"有闸没接线"。第二片要逐章撰写 ~14k 字，LLM 完全可能造一个看起来很像
行业术语的指标名（如「测时成功率」）。闸不接，编造指标就一路进正文、进导出、进答辩 PPT；
这比"报告薄"严重 —— 薄是缺陷，编造指标是事故。

本文件先钉住闸可用（绿），再用静态扫描登记"生产未接线"这个缺口（xfail strict）。
接线判据故意只看**定义文件之外**是否有调用者，不预设接在哪个函数上：E0-3 具体接在
每章写后校验还是签发前统一校验，由实施决定，但必须可被本扫描发现。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.living_circle import caliber_index

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _gate_call_sites() -> list[str]:
    """AST 扫 `app/**`，返回**除定义文件外**调用 `validate_vocabulary` 的 `file:lineno`。"""
    sites: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path.name == "caliber_index.py":
            continue  # 定义处与内部自引用不算接线
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = getattr(f, "attr", None) or getattr(f, "id", None)
                if name == "validate_vocabulary":
                    sites.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    return sites


# ── 1. 闸本身可用（今天的真事实）─────────────────────────────────


def test_gate_rejects_a_fabricated_metric_name():
    """「测时成功率」不在允许词表 ⇒ 必须被拦。这是第二片逐章撰写的前置能力。"""
    problems = caliber_index.validate_vocabulary("本次体检的测时成功率达到 98%，口径可靠。")
    assert problems, "词表闸对编造指标名静默放行，E0-3 的接线前提不成立"
    assert "测时成功率" in problems[0]


def test_gate_does_not_flag_authorised_terms():
    """对照实验：允许词表内的真术语不得误报。

    没有这条对照，上一条可以靠"什么都拦"作弊通过 —— 闸的价值在于**只拦编造的**。
    """
    text = "覆盖率 0.62、可达率 71%、多样性与均衡性共同构成生活圈配置评价。"
    allowed = caliber_index.terms()
    for term in ("覆盖率", "可达率", "多样性", "均衡性"):
        assert term in allowed, f"{term!r} 已不在允许词表，本用例判据须重指"
    assert caliber_index.validate_vocabulary(text) == []


# ── 2. 现状记录 + 登记缺口 ───────────────────────────────────────


def test_gate_currently_has_no_production_caller():
    """**现状记录（E0-3 根因）**：生产代码里没有任何一处调用词表闸。

    接线后本用例会红并提示改成正向断言 —— 与下面的 xfail 成对，防止"标记长住"
    而真相却是闸仍悬空。
    """
    sites = _gate_call_sites()
    assert sites == [], (
        f"词表闸已接入生产路径 {sites} ⇒ 请把本用例改为「接线存在」的正向断言，"
        "并补一条「章节正文里的编造指标不会进报告」的端到端用例"
    )


@pytest.mark.xfail(
    strict=True,
    reason="E0-3：词表闸必须在撰写/签发路径上被调用，违规打回或降 unverified，不许静默放行",
)
def test_vocabulary_gate_is_wired_into_production():
    """缺口登记：生产路径至少有一处调用词表闸（接在哪一层由实施决定）。"""
    assert _gate_call_sites(), "全仓生产代码无调用者 ⇒ 闸存在但未接线"
