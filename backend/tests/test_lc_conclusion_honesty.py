"""结论章那句「本报告基于什么取证」必须按 data_origin 出话（批次二挂账⑤ 的销账用例）。

背景（2026-09-30 真机读报告页撞见）：`_sec_conclusion` 把「提醒：结论基于演示数据（fixture）…」
写成 paragraphs 的**无条件尾句**，而同模块的 `:249`/`:542` 早就在读 `data_origin` —— 只有结论章没读。
后果不是措辞不雅：当天两份**真实接口体检**（北京 `lc-9910b573`、凯里 `lc-7b252c2c`）的结论章节
自称演示数据，把"11 次真实调用把 78 格未判压到 13 格"这件成果自己声明成假的。

钉住的不变量（判据形态=整句归属，不是子串，避免 `'查全' ⊂ '未查全'` 那类陷阱）：
- I1 live 档：只能说"真实接口取证"，**不得**出现"演示数据"；且插值口径跟着 `sampling.interpolation` 走
      （写死 IDW 会在别的推导方式下说假话）。
- I2 fixture / fixture_sample 档：仍说"演示数据" —— 旧契约对这两档是真话，不许顺手改掉。
- I3 未知/缺失档：**两边都不许说**（不自称真实、也不自称演示），只能说"未声明数据来源"。
- I4 offline 档**也有** id='conclusion' 那一章，但由 `_offline_sections` 另出话 ⇒ 反向确认它不吃上面三档措辞。

本文件不放进 `test_chapter_invariants.py`：那个文件的 docstring 明写"绝不比对具体措辞"，
措辞真伪用例放进去会污染它的方法论。
运行：backend/ 下 `pytest tests/test_lc_conclusion_honesty.py -q`
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.core.pipeline.diagnosis_templates import assemble_report
from app.living_circle import caliber_index  # noqa: F401  # 触发口径名册注册（先于组装）

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"

REAL = "真实接口取证"
DEMO = "演示数据"
UNDECLARED = "未声明数据来源"


def _conclusion_paragraph(lc: dict) -> str:
    """走生产入口取结论章那句提醒（末句），不直接调私有函数——否则用例守的是没人走的路。"""
    rep = assemble_report(lc, "lc-honesty", "key:lc-honesty", "诚实性用例")
    sec = next(s for s in rep["sections"] if s["id"] == "conclusion")
    return sec["paragraphs"][-1]


@pytest.fixture()
def base_lc() -> dict:
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    assert lc.get("data_origin") == "live", "前置不成立：夹具本身不是 live，I1 的对照会空转"
    return lc


def test_live_says_real_forensics_and_never_demo(base_lc):
    note = _conclusion_paragraph(copy.deepcopy(base_lc))
    assert REAL in note, note
    assert DEMO not in note, f"live 报告不许自称演示数据：{note}"


def test_live_interp_follows_sampling_field(base_lc):
    """插值口径必须跟着 sampling.interpolation，不是写死 IDW。"""
    lc = copy.deepcopy(base_lc)
    lc["sampling"]["interpolation"] = "idw_probe_marker"
    note = _conclusion_paragraph(lc)
    assert "idw_probe_marker" in note, f"结论句没吃 sampling.interpolation：{note}"
    assert "IDW" not in note.replace("idw_probe_marker", ""), f"另有硬写的插值名：{note}"


@pytest.mark.parametrize("origin", ["fixture", "fixture_sample"])
def test_demo_origins_keep_the_old_sentence(base_lc, origin):
    lc = copy.deepcopy(base_lc)
    lc["data_origin"] = origin
    note = _conclusion_paragraph(lc)
    assert DEMO in note, f"{origin} 档该说演示数据：{note}"
    assert REAL not in note, f"{origin} 档不许自称真实接口取证：{note}"


@pytest.mark.parametrize("origin", ["", "unknown_origin"])
def test_undeclared_origin_claims_neither_side(base_lc, origin):
    lc = copy.deepcopy(base_lc)
    lc["data_origin"] = origin
    note = _conclusion_paragraph(lc)
    assert UNDECLARED in note, note
    assert "演示" not in note, f"来源没交代却沾『演示』二字（含『演示口径』这类近邻写法）：{note}"
    assert REAL not in note, f"来源没交代却自称真实：{note}"


def test_offline_conclusion_does_not_go_through_origin_note(base_lc):
    """offline 也有 id='conclusion' 那一章，但由 `_offline_sections` **另出话**（标题即「待实时体检」），
    不吃本模块的三档句子 —— 反向判据是"三档独有词一个都不出现"，而不是"没有结论章"。

    （2026-09-30 首跑红的就是我这条：原写成 `assert 无 conclusion 章`，把"另一处出话"错当成"不出话"。）
    """
    lc = copy.deepcopy(base_lc)
    lc["data_origin"] = "offline"
    rep = assemble_report(lc, "lc-honesty-off", "key:lc-honesty-off", "诚实性用例")
    sec = next(s for s in rep["sections"] if s["id"] == "conclusion")
    assert "待实时体检" in sec["title"], sec["title"]
    joined = " ".join(sec["paragraphs"])
    for token in (REAL, UNDECLARED, DEMO):
        assert token not in joined, f"offline 章串进了 _origin_note 的某档措辞（{token}）：{joined}"
