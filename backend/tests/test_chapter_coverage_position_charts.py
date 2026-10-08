"""专题章「覆盖度位置图」的契约（2026-10-08 方案 C 档）。

这族图是**参数化复用**概览那张 `_chart_coverage`，不是另起一份实现 —— 本文件钉的就是
"复用没夹带"与"位置图画对了"两件事：

 ⑧ 不传 `focus` 时输出与 nar-1 逐字节相同（摘要基线见下）；
 ⑨ 传 `focus` 时实色条数 == 本章类目数、灰条数 == 序列长 − 实色数，且 `chart_id` 带章 id、
    `evidence_ids` 全部命中证据集；
 ⑩ 概览章不许出现两张同族覆盖度图（预览包里那张 `chart-overview-catcov` 是"改进前/改进后"
    对照残留 —— 生产那张早就带 75% 达标线）；
 ⑪ 三份夹具逐份实跑；序列不足 3 档时不建空图；
 ⑬ 离线载荷不产任何新内容（P0-2 诚实性红线）；
 ⑭ 新图的 option 里不许出现经纬度对或 `gap n.n`（分享态脱敏面，比真人量更硬）。

⑧ 的基线摘要怎么来的（可复算，禁凭记忆）：
    cd skip && git show HEAD:backend/app/core/pipeline/diagnosis_templates.py > /tmp/dt_nar1.py
    cd backend && python3 -c "
    import json, hashlib, importlib.util, sys
    sys.path.insert(0, '.')
    spec = importlib.util.spec_from_file_location('old', '/tmp/dt_nar1.py')
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    from app.core.pipeline.diagnosis_templates import _chart_coverage as new
    lc = json.load(open('app/living_circle/fixtures/kaili.json', encoding='utf-8'))
    canon = lambda o: json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(',',':'))
    print(hashlib.sha256(canon(old._chart_coverage(lc)).encode()).hexdigest()[:16],
          canon(old._chart_coverage(lc)) == canon(new(lc)))"
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest

from app.core.pipeline.diagnosis_templates import (
    _chart_coverage, assemble_report, CATEGORY_CHAPTER,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "app" / "living_circle" / "fixtures"
KAILI: Dict[str, Any] = json.loads((FIXTURE_DIR / "kaili.json").read_text(encoding="utf-8"))
NAR1_COVERAGE_SHA = "0028ea51b12d0917"      # 上面那条命令实测，不是抄来的


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()[:16]


def _report(lc: Dict[str, Any]) -> Dict[str, Any]:
    return assemble_report(copy.deepcopy(lc), "lc-chart", "k", "")


def _section(rep: Dict[str, Any], sid: str) -> Dict[str, Any]:
    return next(s for s in rep["sections"] if s["id"] == sid)


@pytest.fixture(scope="module")
def report():
    return _report(KAILI)


# ── ⑧ 复用不夹带：概览那张一个字节都没变 ──────────────────────────────
def test_8_no_focus_option_is_the_nar1_bytes_exactly():
    option = _chart_coverage(KAILI)
    assert _sha(option) == NAR1_COVERAGE_SHA, (
        "不传 focus 的覆盖度图与 nar-1 基线不符 ⇒ 参数化复用顺手改了概览那张"
        "（金标只会告诉你「产物变了」，说不出「本来不该变」，所以这里单独钉）")
    data = option["series"][0]["data"]
    assert all(isinstance(x, (int, float)) for x in data), (
        f"无 focus 时 data 必须是裸数值列表，现在混进了 {type(data[0]).__name__} ⇒ 逐条着色漏了条件")


# ── ⑨ 位置图画对了 ───────────────────────────────────────────────────
def test_9_focus_marks_exactly_the_chapter_categories(report):
    bars = (KAILI.get("scores") or {}).get("bars") or []
    checked = 0
    for sid in ("medical", "education", "market", "elderly"):
        charts = _section(report, sid)["charts"]
        assert len(charts) == 1, f"{sid} 章应有 1 张位置图，实际 {len(charts)}"
        chart = charts[0]
        assert chart["chart_id"] == f"chart-{sid}-coverage", "chart_id 没带章 id ⇒ 四章会同 id 撞 key"
        assert chart["type"] == "bar" and "option" in chart and "title" in chart, "四键不齐"
        data = chart["option"]["series"][0]["data"]
        assert len(data) == len(bars), "位置图的条数必须与序列同长，否则「位置」是假的"
        solid = [d for d in data if isinstance(d, dict)
                 and d.get("itemStyle", {}).get("opacity") == 1.0]
        dimmed = [d for d in data if isinstance(d, dict)
                  and d.get("itemStyle", {}).get("opacity") == 0.35]
        expected = sum(1 for b in bars if b["category"] in
                       {c for c, owner in CATEGORY_CHAPTER.items() if owner == sid})
        assert len(solid) == expected, (
            f"{sid} 章实色 {len(solid)} 条、本章类目在序列里占 {expected} 条 ⇒ 主角没对上")
        assert len(solid) + len(dimmed) == len(bars), "实色 + 灰条 ≠ 全序列 ⇒ 有条目既不实色也不灰"
        eids = set(chart["evidence_ids"])
        assert eids, f"{sid} 章的位置图没绑证据"
        assert eids <= {e["evidence_id"] for e in report["evidence"]}, f"证据 id 悬空：{eids}"
        checked += 1
    assert checked == 4, "四章位置图没全部扫到 ⇒ 本条对它是恒真"


def test_9b_market_chart_carries_two_solid_bars_not_one(report):
    """菜市与购物章联合两类 ⇒ 实色应是 **2** 条。

    判据第一版写成"恰 1 条实色"，会把这一章自己的图判红（评审 P1-1）。
    """
    data = _section(report, "market")["charts"][0]["option"]["series"][0]["data"]
    solid = [d for d in data if isinstance(d, dict) and d["itemStyle"]["opacity"] == 1.0]
    assert len(solid) == 2, f"菜市章实色条数 {len(solid)} ≠ 2（菜市场 + 购物）"
    assert len(_section(report, "market")["charts"][0]["evidence_ids"]) == 2


# ── ⑩ 概览不许出现两张同族覆盖度图 ────────────────────────────────────
def test_10_overview_has_exactly_one_coverage_family_chart(report):
    charts = _section(report, "overview")["charts"]
    same_family = [c for c in charts if "覆盖度" in (c.get("title") or "")]
    assert len(same_family) == 1, (
        f"概览出现 {len(same_family)} 张同族覆盖度图 ⇒ 把预览期的「改进前/改进后」对照残留搬进了生产。"
        "生产那张早就带 75% 达标线，第二张是同一份 scores.bars 的重复")


# ── ⑪ 三份夹具逐份实跑 + 短序列不建空图 ───────────────────────────────
@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURE_DIR.glob("*.json")))
def test_11_every_fixture_gets_the_position_charts(name: str):
    lc = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    rep = _report(lc)
    bars = (lc.get("scores") or {}).get("bars") or []
    for sid in ("medical", "education", "market", "elderly"):
        charts = _section(rep, sid).get("charts") or []
        assert len(charts) == (1 if len(bars) >= 3 else 0), (
            f"{name} 的 {sid} 章图数与序列长度不联动（bars={len(bars)}）")
    assert len(_section(rep, "isochrone")["charts"]) <= 2, "等时圈章超过 2 图"

    thin = copy.deepcopy(lc)
    thin["scores"]["bars"] = bars[:2]
    thin_rep = _report(thin)
    for sid in ("medical", "education", "market", "elderly"):
        assert not _section(thin_rep, sid).get("charts"), (
            f"序列只剩 2 档时 {sid} 章还建图 ⇒ 画了张没有主角的图")


# ── ⑬ 离线载荷不产任何新内容 ──────────────────────────────────────────
def test_13_offline_payload_gains_no_charts_or_highlights():
    """离线估算报告不产出可比内容（P0-2 诚实性红线）—— 新增这族图/亮点也不许例外。

    刻意**不新增离线夹具文件**：`app/living_circle/fixtures/` 被 5 个测试 glob
    （`test_lc_evidence_chain` / `test_report_invariants` / `test_judge_single_implementation` /
    `test_report_closure` / 金标），加一份会让它们各多跑一份离线载荷。就地改 `data_origin`
    是 `test_lc_conclusion_honesty.py` 已有的写法。

    ⚠️ 第一版只遍历五个专项章 ⇒ **完全没牙**：离线骨架的章 id 是 overview/isochrone/conclusion，
       那五章根本不在场，`sec is None` 一路 continue，往概览上塞一张图照样全绿
       （变异刀 K13 实测零红）。现在钉的是**整份离线报告的图与亮点全集**。
    """
    offline = copy.deepcopy(KAILI)
    offline["data_origin"] = "offline"
    rep = _report(offline)
    assert [s["id"] for s in rep["sections"]] == ["overview", "isochrone", "conclusion"], (
        "离线骨架的章集合变了 ⇒ 下面两条全集断言的基线要一起重看，不许顺手放宽")
    charts = sorted(c["chart_id"] for s in rep["sections"] for c in (s.get("charts") or []))
    assert charts == ["chart-offline-isochrone"], (
        f"离线件长出了别的图：{charts} ⇒ 拿不可比数据画可比结论（P0-2）")
    assert not [h for s in rep["sections"] for h in (s.get("highlights") or [])], (
        "离线件长出了亮点 ⇒ 章级自有句没走离线分支的闸门")


# ── ⑭ 新图 option 禁坐标 ──────────────────────────────────────────────
def test_14_position_chart_options_carry_no_geography():
    """分享链接是公开无鉴权入口（P0-5）：新图只准放类目名与百分比/分钟/面积。

    结构判据比真人量分享态更硬 —— 真人只能证明"这一份没泄漏"，这条能证明"这类图放不进坐标"。
    """
    rep = _report(KAILI)
    coord = re.compile(r"\d{2,3}\.\d{3,}\s*,\s*\d{1,3}\.\d{3,}")
    gap = re.compile(r"gap\s+\d")
    for sid in ("medical", "education", "market", "elderly"):
        blob = _canon(_section(rep, sid)["charts"][0]["option"])
        assert not coord.search(blob), f"{sid} 章位置图的 option 里出现经纬度对 ⇒ 分享态会泄漏精确坐标"
        assert not gap.search(blob), f"{sid} 章位置图的 option 里出现 gap 读数 ⇒ 那是被脱敏的字段"
