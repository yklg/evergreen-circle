"""E′ 第二步 2′ 的**另一半**：把装配器的产物钉成金标准，让"改了装配器忘升戳"会红。

为什么需要这个文件（2026-10-08 实测坐实的缺口）
------------------------------------------------
`test_narrative_read_assembly.py` 的 ⑧ 断的是「库里那行 == 用它自带载荷**在当前进程**重装一次」。
这条比较两侧同源 ⇒ 装配器怎么改右边跟着变，等式**恒成立**。所以 ⑧ 封得住
「绕过装配器改库 / `save` 丢字段」，封不住 §9.2 声明的**另一条**漂道：装配器改了、戳没动。

当时全仓对装配器正文的敏感度实测口径（不是推测）：

| 断言形态 | 位置 | 改正文一个字会红吗 |
|---|---|---|
| 计数锚点 `EXPECT_HIGHLIGHTS/CHARTS/SECTIONS` | 同文件 :54-56 | 不会（只数不改就不动） |
| 「判定格阵」出现／不出现 | `test_report_closure.py:171` 等 3 处 | 不会（反向闸，非固化串） |
| 固化正文黄金串 | **grep 全仓 0 处** | —— |

⇒ 实测把 `lc_subtitle(lc)` 后面接一个字、不升 `NARRATIVE_VERSION`：五个测试文件
`51 passed / 1 xfailed`，**零覆盖**。而戳与产物一旦脱钩，读路径同代次**直通**照旧发旧正文
—— 也就是这条线最初的症状（"改了装配代码，已缓存场景永远看不到"）原样复发。

本文件怎么封
------------
把装配器输出**固化成仓内金标**（`tests/fixtures/narrative_assembly_golden.json`），
断当前输出 == 金标；再把金标里那份 `narrative_version` 与代码里的常量配成对：

  改产物不升戳     ⇒ 逐面金标红   ┐
  升戳不改产物     ⇒ 配对闸红     ┘ ⇒ 两者必须同笔一起动，git diff 看得见
  绕开装配器改库   ⇒ ⑧ 红（那边管）

"升戳不改产物"也要红是有意的：戳的语义是"视图换代"，无实质变化的升戳会让所有存量行
白付一次重装，直通档的证据就此作废。

另有一层顺带的性质：金标是**另一个进程**取的一次快照，而 ⑪ 的两次装配在同一进程内 ——
所以"跨进程才漂"的那一类（字符串 set 迭代序受 PYTHONHASHSEED 影响）由 ⑩ 抓，同进程内
的不一致由 ⑪ 抓，两条不是重复。

期望值来源（禁凭记忆，也禁在本文件里重跑生产实现来生成期望）
------------------------------------------------------------
取基线的命令（本文件自带 `build_golden()`/`render_golden()`；命令是跑通过才写进注释的）：

    cd skip/backend && python3 -c "
    import pathlib
    import tests.test_narrative_assembly_golden as g
    pathlib.Path('tests/fixtures/narrative_assembly_golden.json').write_text(
        g.render_golden(g.build_golden()), encoding='utf-8')"

与 `test_facility_rule.py` 消费 `tests/fixtures/facility_merge_golden.json` 同法：金标进仓，
改判据先改期望并说明理由，**不得为了让实现通过而回填**。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.pipeline import diagnosis_templates
from app.core.pipeline.diagnosis_templates import NARRATIVE_VERSION, assemble_report

FIXTURE_DIR = Path(diagnosis_templates.__file__).resolve().parents[2] / "living_circle" / "fixtures"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "narrative_assembly_golden.json"

# 装配时固定入参：产物里除载荷之外的自由度只有这三个，全部钉死才可比摘要。
GOLDEN_ARGS = ("lc-golden", "golden-key", "")

# 逐面钉：正文/图件/结论/证据/署名各自可能单独漂，只钉整份的话红了看不出是哪一面动的。
PINNED_FACES = ("sections", "toc", "charts", "claims", "evidence", "subtitle", "dispatch", "glossary")

# ⑫ 的黑名单：名字级（模块/变量）+ 内置调用级。当前装配模块实测 0 命中（不是放宽出来的）。
BANNED_ROOTS = {"random", "time", "datetime", "uuid", "requests", "httpx", "sqlite3", "db", "os"}
BANNED_BUILTINS = {"open", "hash", "id"}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()[:16]


def _fixture_names() -> List[str]:
    return sorted(p.name for p in FIXTURE_DIR.glob("*.json"))


def _assemble(name: str) -> Dict[str, Any]:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return assemble_report(payload, *GOLDEN_ARGS)


def _highlights(rep: Dict[str, Any]) -> int:
    return sum(len(s.get("highlights") or []) for s in rep.get("sections") or [])


def _counts(rep: Dict[str, Any]) -> Dict[str, int]:
    return {"sections": len(rep["sections"]), "highlights": _highlights(rep), "charts": len(rep["charts"])}


def _faces(rep: Dict[str, Any]) -> Dict[str, str]:
    """刻意**不含** `narrative_version` —— 那一位归配对闸管，混进来就分不清"产物变了"与"戳变了"。"""
    out = {k: _digest(rep[k]) for k in PINNED_FACES}
    out["report"] = _digest({k: v for k, v in rep.items() if k != "narrative_version"})
    return out


def _pair_lock(golden_stamp: str, current_stamp: str) -> str:
    """戳与金标不同代 ⇒ 返回一句红因；相同 ⇒ 空串。"""
    if golden_stamp == current_stamp:
        return ""
    return (f"金标按 {golden_stamp!r} 取基线，代码里 NARRATIVE_VERSION 已是 {current_stamp!r} ⇒ "
            "视图换代必须与金标同笔重取")


def _coverage_gap(fixtures: List[str], golden_keys: List[str]) -> List[str]:
    out = [f"{name} 有载荷却没有金标 ⇒ 它逃出了覆盖面" for name in fixtures if name not in golden_keys]
    out += [f"金标里的 {key} 在夹具目录里已不存在 ⇒ 死键" for key in golden_keys if key not in fixtures]
    return out


def build_golden() -> Dict[str, Any]:
    """供重取基线用：枚举夹具目录里的**全部** .json，逐面取摘要。"""
    fixtures: Dict[str, Any] = {}
    for name in _fixture_names():
        rep = _assemble(name)
        fixtures[name] = {"counts": _counts(rep), "faces": _faces(rep)}
    return {
        "$schema_note": (
            "生活圈报告装配器（core/pipeline/diagnosis_templates.py::assemble_report）输出的黄金基线。"
            "期望值由当时装配器实测取基线固化，不得为了让实现通过而回填：改了装配器、专家名册或口径而产物"
            "变化 ⇒ 逐面金标红 ⇒ 要么同笔把 NARRATIVE_VERSION 升一代（读路径据此对存量行重装），要么承认这是"
            "回归并回退代码。只升戳而产物没变同样红（配对闸），因为无实质变化的升戳会让所有存量行白付一次"
            "重装、把「同代次直通」的证据打掉。"),
        "schema": "evergreen.narrative-assembly-golden/v1",
        "captured_at": "2026-10-08",
        "narrative_version": NARRATIVE_VERSION,
        "assembler_args": {"report_id": GOLDEN_ARGS[0], "scene_key": GOLDEN_ARGS[1], "title": GOLDEN_ARGS[2]},
        "digest_note": "sha256(canonical)[:16]；canonical = json.dumps(ensure_ascii=False, sort_keys=True, separators=(',',':'))",
        "faces_note": "逐面刻意不含 narrative_version；另有一项 report = 整份（同样剔掉 narrative_version），兜未钉住的面。",
        "fixtures": fixtures,
    }


def render_golden(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _golden() -> Dict[str, Any]:
    assert GOLDEN_PATH.exists(), (
        f"金标文件不在（{GOLDEN_PATH}）⇒ 判据无从比对。按本文件 docstring 里的取基线命令生成，"
        "不许临时 skip")
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


# ── ⑩ 金标准：当前装配器对每个夹具的产物必须逐面等于金标 ─────────────────────────
def test_10_every_fixture_matches_the_pinned_golden():
    names = _fixture_names()
    assert names, f"{FIXTURE_DIR} 下一个 .json 都没扫到 ⇒ 遍历没走通，下面的 0 处不算数"
    golden = _golden()
    gap = _coverage_gap(names, list(golden["fixtures"]))
    assert not gap, "夹具集合与金标键集不闭合 ⇒ " + "；".join(gap)

    lock = _pair_lock(golden["narrative_version"], NARRATIVE_VERSION)
    assert not lock, lock

    stale: List[str] = []
    for name in names:
        rep = _assemble(name)
        want = golden["fixtures"][name]
        got, exp = _faces(rep), want["faces"]
        for face in list(PINNED_FACES) + ["report"]:
            if got[face] != exp[face]:
                stale.append(f"{name} 的 {face} 面变了（金标 {exp[face]} ≠ 当前 {got[face]}）")
        for key, value in _counts(rep).items():
            if value != want["counts"][key]:
                stale.append(f"{name} 的 {key} 数变了（金标 {want['counts'][key]} ≠ 当前 {value}）")
    assert not stale, (
        "装配器产物与金标不符 ⇒ 视图已经换代而戳还停在上一代：读路径对存量行直通，"
        "用户看到的仍是旧正文（就是这条线最初要治的那个症状）。"
        "要么同笔升 NARRATIVE_VERSION，要么回退装配改动。\n" + "\n".join(stale))


def test_11_assembling_the_same_payload_twice_is_byte_identical():
    """直通档的正确性前提是「装配 = 载荷的纯函数」。这条把那句注释变成会红的判据。"""
    names = _fixture_names()
    assert names, "一个夹具都没扫到 ⇒ 本条对它是恒真"
    for name in names:
        assert _canonical(_assemble(name)) == _canonical(_assemble(name)), (
            f"{name} 连装两次输出不同 ⇒ 装配器不纯（随机/墙钟/外部状态），"
            "直通与对账同时失去依据，金标也无从成立")


def test_12_assembler_module_is_free_of_nondeterministic_inputs():
    """⑪ 只挡住"同一进程内跑出不一致"，挡不住"今天凑巧一致"，所以静态禁则另立一条。

    走 AST 不走正则：本模块的 docstring 本来就在说"禁随机/禁墙钟"，按行扫文本会把
    这些**说明**当成违规（假阳），而假阳的闸很快被人放宽掉。
    """
    path = Path(diagnosis_templates.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.FunctionDef) and n.name == "assemble_report" for n in tree.body), (
        f"{path} 里没有 assemble_report ⇒ 扫错了文件，本条对它是恒真")
    hits: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_ROOTS:
                    hits.append(f"{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BANNED_ROOTS:
                hits.append(f"{node.lineno}: from {node.module}")
        elif isinstance(node, ast.Name) and node.id in BANNED_ROOTS:
            hits.append(f"{node.lineno}: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTINS:
            hits.append(f"{node.lineno}: {node.func.id}(")
    assert not hits, (
        f"装配模块里出现非确定性来源 {hits} ⇒ 产物不再是载荷的纯函数。"
        "若确有必要引入（比如取时间戳），必须同时撤掉读路径的直通档"
        "（`living_circle.refresh_report_for_display` 改成每次重装），否则同代次的存量快照会永远发旧货。")


# ── ⑬⑭⑮ 正对照：证明上面三条不是恒真断言 ────────────────────────────────────
def test_13_positive_control_one_char_of_prose_flips_the_face_digest():
    """⑩ 的灵敏度对照：正文改一个字，`sections` 面与整份摘要必须变、其余面必须不变。

    没有这条，⑩ 有可能是"两边读同一份内存对象"式恒真（本仓栽过好几次的形状），
    而那正是上一轮实测出来的失效通道。
    """
    name = _fixture_names()[0]
    before = _faces(_assemble(name))
    tampered = copy.deepcopy(_assemble(name))
    paras = tampered["sections"][0].get("paragraphs") or []
    assert paras, f"{name} 的第一章没有正文段落 ⇒ 本对照改不了字，无效"
    paras[0] = paras[0] + "字"
    after = _faces(tampered)
    assert after["sections"] != before["sections"], "改了一个字而 sections 面摘要没动 ⇒ ⑩ 对正文零敏感"
    assert after["report"] != before["report"], "改了产物而整份摘要没动 ⇒ 兜底面也失效"
    others = [f for f in PINNED_FACES if f != "sections"]
    assert all(after[f] == before[f] for f in others), (
        f"只改第一章正文却连 {others} 也变了 ⇒ 那几面并没有独立钉住，⑩ 的红因不可读")


def test_14_positive_control_a_bare_stamp_bump_is_caught_only_by_the_pair_lock():
    """⑭ 存在的理由摊开写成可检查断言：只改戳时逐面金标**看不见**，配对闸才看得见。"""
    name = _fixture_names()[0]
    rep = _assemble(name)
    bare = dict(rep, narrative_version="nar-99")
    assert _faces(bare) == _faces(rep), (
        "改戳竟然动了逐面摘要 ⇒ narrative_version 混进了摘要里，"
        "配对闸与金标就成了同一件事，本条前提塌了")
    assert _pair_lock(NARRATIVE_VERSION, NARRATIVE_VERSION) == "", "同代次必须放行，否则直通档永不可达"
    assert _pair_lock(NARRATIVE_VERSION, "nar-99"), "配对闸抓不住「只升戳不改产物」⇒ 2′ 第二条通道仍无人守"


def test_15_coverage_gate_function_flags_an_unpinned_fixture():
    """「该发必发」元判据（照 `test_fixture_mirror.py:202` 先例：纯函数 + 合成输入两态）。"""
    assert _coverage_gap(["a.json"], ["a.json"]) == []
    gap = _coverage_gap(["a.json", "b.json"], ["a.json"])
    assert any("b.json" in x for x in gap), f"新增夹具没进金标却没报 ⇒ 覆盖面会静默缩水：{gap}"
    gap2 = _coverage_gap(["a.json"], ["a.json", "stale.json"])
    assert any("stale.json" in x for x in gap2), f"金标里的死键没报 ⇒ 集合闭合只做了半边：{gap2}"

    stale = _golden()["fixtures"]
    assert set(stale) == set(_fixture_names()), "金标键集与夹具集不闭合 ⇒ ⑩ 的枚举闸形同虚设"


@pytest.mark.parametrize("name", sorted(_fixture_names()))
def test_16_golden_faces_are_present_and_nonempty(name: str):
    """防"金标里写个空面对策通过"：每一面都得真钉了非空摘要，且 counts 不是 0。"""
    entry = _golden()["fixtures"][name]
    faces = entry["faces"]
    assert set(faces) == set(PINNED_FACES) | {"report"}, f"{name} 的金标面集不闭合：{sorted(faces)}"
    assert all(len(v) == 16 for v in faces.values()), f"{name} 有面的摘要长度不对 ⇒ 取基线时算歪了"
    assert all(v > 0 for v in entry["counts"].values()), (
        f"{name} 的 counts 出现 0 ⇒ 这份夹具没被装配出内容（如离线骨架夹具本不该进金标集）")
