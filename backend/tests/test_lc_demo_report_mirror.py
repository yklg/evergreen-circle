"""演示态快照的防漂移闸：烘进前端的那三份，必须还等于当代装配器的产物。

为什么需要这个文件
------------------
`backend/scripts/bake_lc_demo_reports.py` 把后端装配器的输出固化成
`frontend/src/mocks/fixtures/livingCircleReports/*.report.json`，演示态读路径
（`livingCircleReports.ts::getBakedDemoReport`）直接吃这三份文件。固化本身就是新的漂道：
**烘的那一刻一致，不等于以后一直一致** —— 改了 `diagnosis_templates.py` 而没重烘，
演示态就继续播旧正文，而这正是本专线最初的症状（"重新跑一次报告还是和之前一样"）。

与 `test_narrative_assembly_golden.py` 的分工（不是重复）
--------------------------------------------------------
金标钉的是「装配器输出 vs 后端金标摘要」，射程只在后端仓内；本文件钉的是
「装配器输出 vs 已经交付给前端的那份文件」，管的是**跨端交付物会不会过期**。
两侧同笔才闭：改装配器 ⇒ 金标红（要升戳）+ 本文件红（要重烘）。

三条闸各自拦什么
----------------
  改产物不重烘        ⇒ 面级比较红          ┐ 烘与不烘都必须和代码同代，
  升 NARRATIVE_VERSION 却不重烘 ⇒ 配对闸红  ┘ git diff 里看得见
  夹具目录与快照清单不再一一对应 ⇒ 覆盖面闸红（新增样区忘了烘 / 删样区留下死快照）

再加一族「来路」闸（2026-10-11 甲）：演示件上那两句"这份是刚跑的"必须已被换成"内置快照"，
且换的动作不许越界、装配器改口时必须抛错 —— 见下方 `_paras` 起那三块。

期望值来源：`bake.build()` 现场装配一次（与盘上那份**同一个生产者**，不是另抄一份模板），
再与盘上文件做深比较。这条不防"装配器本身算错"（那是金标那条的职责），只防"交付物过期"。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.pipeline.diagnosis_templates import NARRATIVE_VERSION, assemble_report  # noqa: E402
from scripts.bake_lc_demo_reports import (  # noqa: E402
    DEMO_ORIGIN_REWRITES,
    DEMO_STEMS,
    FIXTURES_DIR,
    OUT_DIR,
    REQUIRED_REPORT_KEYS,
    _load_fixture,
    build,
    relabel_origin_for_demo,
)

# `_captured_at` 每次烘都变 ⇒ 剔掉再比，否则"重烘过但内容没变"会被误判成漂移。
# `narrative_version` 刻意**不**进面级比较 —— 那一位归下面的配对闸管：混进来会让
# "只升戳不重烘"同时红两处，红了却说不清是哪半件事（先例见 test_narrative_assembly_golden.py
# 的 `_faces()` 同一取舍）。
IGNORED_KEYS = ("_captured_at",)
FACE_EXCLUDED = ("_captured_at", "narrative_version", "_narrative_version")


def _read_snapshot(stem: str) -> Dict[str, Any]:
    path = OUT_DIR / f"{stem}.report.json"
    assert path.exists(), f"演示态快照不在盘上：{path}"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _comparable(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in FACE_EXCLUDED}


def _drift(stem: str, fresh: Dict[str, Any], on_disk: Dict[str, Any]) -> List[str]:
    """纯函数：返回差异清单（空 == 没漂）。拆出来是为了能给它配正对照。"""
    a, b = _comparable(fresh), _comparable(on_disk)
    if a == b:
        return []
    out: List[str] = []
    keys = set(a) | set(b)
    for k in sorted(keys):
        if k not in a:
            out.append(f"{stem}: 快照多一位 {k}（当代装配器不再发它）")
        elif k not in b:
            out.append(f"{stem}: 快照缺一位 {k}（装配器现在发它 ⇒ 该重烘）")
        elif a[k] != b[k]:
            out.append(f"{stem}: {k} 内容与当代装配器不一致")
    return out


def test_every_demo_sample_has_a_snapshot():
    """覆盖面闭合：夹具目录里那份 == 快照清单那份，双向都不许有孤儿。"""
    stems_on_disk = {p.name[: -len(".report.json")] for p in OUT_DIR.glob("*.report.json")}
    fixtures = {p.stem for p in FIXTURES_DIR.glob("*.json")}
    missing = [s for s in DEMO_STEMS if s not in stems_on_disk]
    dead = [s for s in stems_on_disk if s not in fixtures]
    assert not missing, f"演示样区没烘出快照：{missing}"
    assert not dead, f"快照指向的夹具已不在：{dead}"
    assert set(DEMO_STEMS) == stems_on_disk, f"清单与盘上不一致：{set(DEMO_STEMS)} vs {stems_on_disk}"


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_snapshot_matches_current_assembler(stem: str):
    """面级闸：现装配一次 vs 盘上那份。改了 diagnosis_templates.py 没重烘 ⇒ 这里红。"""
    fresh, _payload = build(stem)
    on_disk = _read_snapshot(stem)
    drift = _drift(stem, fresh, on_disk)
    assert not drift, "演示态快照落后于当代装配器 ⇒ 重跑 bake_lc_demo_reports.py：\n  - " + "\n  - ".join(drift)


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_stamp_pair_lock(stem: str):
    """配对闸：快照里的代次必须等于代码常量。只升戳不重烘也红（否则直通档证据作废）。"""
    on_disk = _read_snapshot(stem)
    assert on_disk["narrative_version"] == NARRATIVE_VERSION, (
        f"{stem}: 快照按 {on_disk['narrative_version']!r} 烘出，代码里 NARRATIVE_VERSION 已是 "
        f"{NARRATIVE_VERSION!r} ⇒ 视图换代必须与演示态快照同笔重烘"
    )
    assert on_disk["_narrative_version"] == NARRATIVE_VERSION, f"{stem}: 快照头部元数据与正文代次不一致"


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_snapshot_carries_the_ledger_payload_back(stem: str):
    """快照刻意不含 `living_circle`（省一半 bundle），读路径靠现成 import 拼回 ⇒ 两边都得对得上。"""
    fresh, payload = build(stem)
    on_disk = _read_snapshot(stem)
    assert "living_circle" not in on_disk, f"{stem}: 快照里混进了 living_circle 载荷 ⇒ bundle 会翻倍"
    assert "living_circle" not in fresh, f"{stem}: build() 没剥载荷，与快照那条口径不一致"
    # 装配器**原始输出**里必须在场（否则前端拼回来的那份就不是它发的，读路径等于自己造数据）
    raw = assemble_report(_load_fixture(stem), f"lc-{stem}", stem, "")
    assert "living_circle" in raw, f"{stem}: 装配器不发 living_circle ⇒ 读路径的拼回假设失效"
    assert raw["living_circle"] == payload, f"{stem}: build() 交出的载荷与装配器那份不同源"
    assert payload.get("scene", {}).get("name"), f"{stem}: 载荷没有 scene.name，读路径拼不回可读报告"
    # 台账在场性：载荷带台账 ⇒ 盲区章正文里必须有那条逐格台账段（`_ledger_sentence` 的产物），
    # 载荷不带 ⇒ 一个字都不许出现。这是**同源**判据，不是"按后缀猜"。
    # 原先这里写的是 `has_ledger == stem.endswith("-ev2")` —— 2026-10-11 作废：`cells_ledger`
    # 现在每次真跑都渲染（`assemble.py:339` 无条件走），新跑的两份样区（上海五角场/凯里下司）
    # 天然带它，那条后缀规则会误杀；"两份夹具互串"改由 `bake._assert_samples_are_distinct()`
    # （`build()` 会调）在全集层面用指纹拦。
    payload_has_ledger = "cells_ledger" in (payload.get("caliber") or {})
    blind = next((s for s in on_disk.get("sections") or [] if s.get("id") == "blindspot"), None)
    prose_has_ledger = "判定格" in "".join((blind or {}).get("paragraphs") or [])
    assert prose_has_ledger == payload_has_ledger, (
        f"{stem}: 载荷台账={payload_has_ledger}，而正文里的台账段={prose_has_ledger}"
        " ⇒ 装配器在这一位上做了增删（或快照落的是另一份载荷）"
    )


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_snapshot_satisfies_report_contract(stem: str):
    """快照必须满足前端 `Report` 的必填键 —— 少一位编译不红，只在运行时崩。"""
    on_disk = _read_snapshot(stem)
    missing = [k for k in REQUIRED_REPORT_KEYS if k not in on_disk]
    assert not missing, f"{stem}: 快照缺 Report 必填键 {missing}"


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_demo_fixture_is_strict_json(stem: str):
    """载荷必须是**标准 JSON**：`NaN`/`Infinity` 在 Python 里合法、在浏览器里非法。

    2026-10-11 实发：一份真跑载荷里落了 `"nearest_m": Infinity`（某类设施一个都没有时，
    `scoring` 只挡了负数没挡 `inf`）⇒ 镜像闸、金标全绿，而 Vite/浏览器 `JSON.parse` 直接
    `expected value at line 10973`。`parse_constant` 会被标准库里"遇到非标准字面量"时回调，
    拿它当探测器：一旦命中就点名到具体字面量，而不是等前端报一句解析错。
    """
    with open(FIXTURES_DIR / f"{stem}.json", encoding="utf-8") as fh:
        json.load(fh, parse_constant=lambda c: pytest.fail(f"{stem}: 载荷含非标准 JSON 字面量 {c!r}"))
    snap = _read_snapshot(stem)
    json.dumps(snap, ensure_ascii=False, allow_nan=False)


def test_ledger_sample_ships_the_charts_the_demo_needs():
    """`kaili-ev2` 存在的唯一理由是"演示态看得见逐格台账"。这条把它钉成永久闸。

    实测读数：这份有 1 处盲区、9 张图（含 `chart-fix-priority`），另两份 0 盲区、8 张图。
    """
    on_disk = _read_snapshot("kaili-ev2")
    chart_ids = {c["chart_id"] for c in on_disk["charts"]}
    assert "chart-fix-priority" in chart_ids, f"整改优先级图不在场：{sorted(chart_ids)}"
    blind = next(s for s in on_disk["sections"] if s["id"] == "blindspot")
    prose = "".join(blind.get("paragraphs") or [])
    assert "判定格" in prose, "盲区章没讲判定格 ⇒ 台账那一屏在演示态又变回没人看得见"


def test_snapshot_drops_the_empty_legacy_key():
    """快照不带 `brands` —— 这条同时把 `test_semantic_residue.py` 的扫描口径钉住。

    那个键是旅游契约退役期的恒空旧键（前端零消费方、`types.ts` 里可选），后端自己只拿
    "legacy 空数组键、读兼容"这一条豁免。把它复制进 `frontend/src` 的新文件会要求为该目录
    新开一条竞品语义豁免；为一份恒空数组不值得，而可选键的缺席与在场在契约上等价。
    真态库里那行仍带它 —— 本条只管演示件。
    """
    for stem in DEMO_STEMS:
        on_disk = _read_snapshot(stem)
        assert "brands" not in on_disk, f"{stem}: 快照带了 brands 这个恒空旧键 ⇒ 会要求新增竞品语义白名单豁免"


# ── 来路改写（演示态不许说"这份是刚跑的"）───────────────────────────
#
# 载荷是**历史真实跑批留档**，装配器因此写「数据口径：live；…」与「提醒：本报告为真实接口
# 取证（data_origin=live）…」。这两句在真实态成立，搬到演示态就是假话（演示一个接口都不发）。
# 改写住在烘件脚本（`DEMO_ORIGIN_REWRITES`），因为装配器无从知道这份载荷是刚跑的还是仓里烘的。
# 下面三条各管一面：**盘上那份的说法是对的** ／ **改写没有越界** ／ **装配器改口时烘不动**。


def _paras(report: Dict[str, Any]):
    """(章 id, 段序, 原文) 三元组，按装配顺序展开 —— 逐段核，禁抽样。"""
    return [
        (sec["id"], i, text)
        for sec in (report.get("sections") or [])
        for i, text in enumerate(sec.get("paragraphs") or [])
    ]


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_demo_snapshot_says_it_is_a_baked_snapshot(stem: str):
    """盘上那份：装配器的两句"真实取证"原文一处不许剩，演示态说法各恰好一句。"""
    texts = [p for _, _, p in _paras(_read_snapshot(stem))]
    for old, new in DEMO_ORIGIN_REWRITES:
        leftover = sum(t.count(old) for t in texts)
        assert leftover == 0, f"{stem}: 演示件里还剩 {leftover} 处「{old[:20]}…」⇒ 那句在演示态不成立"
        landed = sum(t.count(new) for t in texts)
        assert landed == 1, f"{stem}: 演示态说法「{new[:20]}…」出现 {landed} 次（要求恰好 1）"


@pytest.mark.parametrize("stem", DEMO_STEMS)
def test_relabel_moves_exactly_those_two_sentences(stem: str):
    """越界检查：改写只动那两段、只做起表替换，且不就地改装配器产物。

    这条存在是因为面级闸的期望值本身就调用改写（同一个生产者）⇒ 它**看不出**改写越界。
    证据侧的 `source_url=live://poi` 与 `methodology.note=data_origin=live · …` 是机器溯源
    指针，必须原样留着 —— 把它们一起"洗白"才是真造假。
    """
    raw_before = assemble_report(_load_fixture(stem), f"lc-{stem}", stem, "")
    baseline = _paras(raw_before)
    rel = relabel_origin_for_demo(raw_before)

    assert _paras(raw_before) == baseline, "relabel 就地改了装配器产物（它必须返回新对象）"
    outside = {k: v for k, v in raw_before.items() if k != "sections"}
    assert outside == {k: v for k, v in rel.items() if k != "sections"}, (
        f"{stem}: 改写碰到了 sections 之外的面（证据 source_url／methodology.note 这些照报字段不许动）"
    )

    after = _paras(rel)
    assert len(after) == len(baseline), f"{stem}: 段落条数变了（{len(baseline)} → {len(after)}）"
    changed = [(a, b) for a, b in zip(baseline, after) if a != b]
    assert len(changed) == len(DEMO_ORIGIN_REWRITES), (
        f"{stem}: 被改的段落有 {len(changed)} 段，改写表只有 {len(DEMO_ORIGIN_REWRITES)} 条 ⇒ 越界或漏改"
    )
    used = set()
    for (sid, idx, before), (_sid, _idx, after_text) in changed:
        for n, (old, new) in enumerate(DEMO_ORIGIN_REWRITES):
            if before.replace(old, new) == after_text:
                used.add(n)
                break
        else:
            raise AssertionError(f"{stem}: {sid}[{idx}] 那段不是「原文做表替换」的结果 ⇒ 改写夹带了别的措辞")
    assert used == set(range(len(DEMO_ORIGIN_REWRITES))), f"{stem}: 改写表有 {sorted(set(range(len(DEMO_ORIGIN_REWRITES))) - used)} 条没落地"


def test_relabel_refuses_when_the_assembler_sentence_moves():
    """反证（防恒真）：装配器把那两句改了口 ⇒ 烘件脚本必须**抛**，不能静默少改一句。

    没有这一条，"命中次数必须恰好 1"这个约束只是注释；日后有人重写口径句，改写会命中 0 次，
    于是演示件重新印上"真实接口取证"而两条闸都照绿（面级闸两侧同源、来路闸读的是盘上那份）。
    """
    raw = assemble_report(_load_fixture("kaili"), "lc-kaili", "kaili", "")
    tampered = copy.deepcopy(raw)
    old = DEMO_ORIGIN_REWRITES[0][0]
    hits = 0
    for sec in tampered.get("sections") or []:
        for i, text in enumerate(sec.get("paragraphs") or []):
            if old in text:
                sec["paragraphs"][i] = text.replace(old, "数据口径：本次实测；")
                hits += 1
    assert hits == 1, f"这条反证自己失效了：原文命中 {hits} 次，没能挪走它"
    with pytest.raises(RuntimeError, match="拒绝烘进演示态"):
        relabel_origin_for_demo(tampered)


def test_drift_detector_itself_has_teeth():
    """正对照（防恒真）：改一个字必须报漂，只动 `_captured_at` 必须不报漂。

    没有这一条，上面所有比较都可能是"两边同时坏所以永远相等"。
    """
    fresh, _ = build("kaili")
    same = copy.deepcopy(fresh)
    assert _drift("kaili", fresh, same) == [], "同一份内容自比却报漂 ⇒ 比较逻辑坏了"

    touched = copy.deepcopy(fresh)
    touched["subtitle"] = touched["subtitle"] + " "
    assert _drift("kaili", fresh, touched), "改了正文一个字却测不出漂 ⇒ 这条闸没有牙"

    only_time = copy.deepcopy(fresh)
    only_time["_captured_at"] = "2000-01-01T00:00:00.000Z"
    assert _drift("kaili", fresh, only_time) == [], "只动生成时刻就报漂 ⇒ 重烘会被误判成内容变化"
