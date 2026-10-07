"""E′ 第一步 · 读侧装配：代次戳决定"直通还是重装"，快照降级为兜底与审计副本。

治的缺陷（2026-10-07 实测坐实）：正文/亮点/图件是**写时**装配后冻结落库的
（`pipeline/living_circle.py::_finalize_living_report` → `assemble_report` → 落库），
而缓存命中路径直接回旧行不重装（`living_circle.py:284-318`）⇒ **改了装配代码，
已缓存场景永远看不到**。同一份官渡区载荷：存量 0 亮点/3 图/1152 字，
当前装配器重装 5 亮点/5 图/2560 字。

判据分层（每条钉一件事，互不重叠）：
 ① 该发必发 —— 新产出的报告顶层带 `narrative_version`，且它**不在** `caliber` 里；
 ② 同代次直通 —— 断装配器**一次都没被调用**（"省 CPU"必须可证，不是口头承诺）；
 ③ 缺戳老快照重装 —— 用户不重跑取证、只刷新就变厚（V1，本批改动的全部理由）；
 ④ 异代次重装 —— 响应与"直调装配器"**逐字相同**（防"只换 sections 不换 subtitle/toc"
    那种装半份：那会让 `subtitle` 说 0 处盲区而正文列出 1 处）；
 ⑤ 重装抛错 —— 回落快照、状态码 200、日志有 warning（禁空页、禁 500、禁静默）；
 ⑥ 派生链与存在性检查**不受影响** —— `db.get_report` 仍返回冻结快照（V3 回归锚）；
 ⑦ 戳不进复用门 —— `reuse_policy` 只看载荷，结构上读不到顶层这一位（与 `test_pages_returned.py:235`、
    `test_shape_stamp_does_not_move_the_reuse_gate` 同族）。

⚠️ "老快照"怎么造：不能只把戳删掉 —— 用**当前**装配器装出来的内容本来就是厚的，
那样 ③ 的"变厚"无从谈起（第一版就犯过这个错，前置断言当场红）。必须连**加厚前的形状**
一起退化（摘 highlights、砍章数、去台账句），才模拟得出库里真躺着的那种行。

夹具实读数（不硬编码猜数）：`app/living_circle/fixtures/kaili.json` 经当前装配器
= 8 章 / 亮点 3 / 图 4。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.pipeline import living_circle as lcp
from app.core.pipeline.diagnosis_templates import NARRATIVE_VERSION, assemble_report
from app.living_circle import report_contract
from app.main import app
from conftest import live_payload

client = TestClient(app)

FIXTURE = (Path(__file__).resolve().parent.parent
           / "app" / "living_circle" / "fixtures" / "kaili.json")
KAILI: Dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))

RID = "lc-narr-test"
SCENE_KEY = "narr-test-key"

# 实测量出来的锚点。换夹具要一起重测，不许退化成 `>= 1` 这种恒真断言
EXPECT_HIGHLIGHTS = 3
EXPECT_CHARTS = 4
EXPECT_SECTIONS = 8


def _assemble() -> Dict[str, Any]:
    return assemble_report(json.loads(json.dumps(KAILI)), RID, SCENE_KEY, "")


def _degrade_to_pre_thickening(rep: Dict[str, Any]) -> None:
    """把一份报告**就地**退化成加厚前的样子：亮点清空、章数砍到 2、台账句摘掉。"""
    rep["sections"] = rep["sections"][:2]
    for sec in rep["sections"]:
        sec["highlights"] = []
    rep["sections"] = [
        {**s, "paragraphs": [p for p in (s.get("paragraphs") or []) if "判定格阵" not in p]}
        for s in rep["sections"]
    ]
    rep["charts"] = rep["charts"][:3]
    rep["toc"] = [{"id": s["id"], "title": s["title"], "level": s["level"]} for s in rep["sections"]]


def _seed(stamp: Optional[str] = ..., *, legacy_body: bool = False) -> Dict[str, Any]:
    """落一份库行。`stamp=None` 表示"nar 之前落库的老行"（顶层没这个键）。"""
    rep = _assemble()
    if legacy_body:
        _degrade_to_pre_thickening(rep)
    if stamp is ...:
        pass
    elif stamp is None:
        rep.pop("narrative_version", None)
    else:
        rep["narrative_version"] = stamp
    db.save_living_circle_report(rep, scene_key=SCENE_KEY)
    return rep


def _highlights(rep: Dict[str, Any]) -> int:
    return sum(len(s.get("highlights") or []) for s in rep.get("sections") or [])


@pytest.fixture(autouse=True)
def _clean_scene():
    db.delete_living_circle_reports_for_scene(SCENE_KEY)
    yield
    db.delete_living_circle_reports_for_scene(SCENE_KEY)


@pytest.fixture
def calls(monkeypatch):
    """数装配器被调了几次。②③④ 的"直通 / 重装"全靠它变成可判读数。"""
    seen: list = []
    real = lcp.assemble_report

    def spy(*args, **kwargs):
        seen.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(lcp, "assemble_report", spy)
    return seen


def test_1_fresh_report_carries_the_stamp_and_the_stamp_is_not_a_caliber_axis():
    rep = _seed()
    assert rep["narrative_version"] == NARRATIVE_VERSION, "装配器没在产物上盖代次戳 ⇒ 读侧无从判定"
    assert "narrative_version" not in (rep["living_circle"].get("caliber") or {}), (
        "戳漏进 caliber ⇒ 它会被当成一根**测量口径轴**（那五把 ev/cov/rc/sh/facility 才是），"
        "而它只是视图的代次")


def test_2_same_generation_serves_snapshot_without_reassembling(calls):
    _seed()
    del calls[:]                                  # 把播种那次装配排除在计数外
    got = client.get(f"/api/reports/{RID}").json()
    assert got["narrative_version"] == NARRATIVE_VERSION
    assert len(calls) == 0, "同代次仍重装 ⇒ '直通'档形同虚设，每次读报告都白付一次装配"
    assert _highlights(got) == EXPECT_HIGHLIGHTS


def test_3_legacy_row_thickens_on_a_plain_refresh(calls):
    """V1：不重跑取证、不改参数，只刷新 ⇒ 老场景就变厚。整件事的存在理由。"""
    stored = _seed(None, legacy_body=True)
    assert _highlights(stored) == 0 and "narrative_version" not in stored, (
        "前提不成立：这份'老快照'本来就有亮点 ⇒ 比不出重装带来的增量")
    del calls[:]
    got = client.get(f"/api/reports/{RID}").json()
    assert len(calls) == 1, "缺戳没触发重装"
    assert _highlights(got) == EXPECT_HIGHLIGHTS
    assert len(got["sections"]) == EXPECT_SECTIONS
    assert len(got["charts"]) == EXPECT_CHARTS


def test_4_stale_stamp_response_equals_direct_assembly_exactly(calls):
    """④ 整体替换：装半份（只换 sections、留着旧 subtitle/toc）当场红。"""
    stored = _seed("nar-0")
    del calls[:]
    got = client.get(f"/api/reports/{RID}").json()
    rebuilt = _assemble()
    assert got == rebuilt, (
        "读侧重装与直调装配器不是同一份 ⇒ 大概率只换了一部分键；"
        "`subtitle`/`toc`/`charts` 必须与 `sections` 同代，否则标题与正文互相打脸")
    assert got["narrative_version"] == NARRATIVE_VERSION
    assert stored["narrative_version"] == "nar-0", "库里的行不该被读路径改写"


def test_5_reassembly_failure_falls_back_to_the_snapshot(caplog, monkeypatch):
    _seed("nar-0", legacy_body=True)

    def boom(*_a, **_k):
        raise RuntimeError("装配器炸了")

    monkeypatch.setattr(lcp, "assemble_report", boom)
    with caplog.at_level(logging.WARNING, logger="app.core.pipeline.living_circle"):
        r = client.get(f"/api/reports/{RID}")
    assert r.status_code == 200, "读路径把展示打死 ⇒ 用户看到空页/500"
    assert r.json()["narrative_version"] == "nar-0", "回落必须回到那份快照，不是回个半成品"
    assert any(rec.levelno == logging.WARNING and "[narrative]" in rec.message
               for rec in caplog.records), "回落没留痕 ⇒ 违规只有用户看得见"


def test_6_db_readers_and_existence_checks_still_get_the_frozen_snapshot():
    """⑥ V3 回归锚：派生链（精炼/一页纸/复跑）与存在性检查读的都是 `db.get_report`，
    它们要可复现输入。这层只许挂在报告响应上，漏进去就是改了它们的字节。"""
    _seed("nar-0", legacy_body=True)
    stored = db.get_report(RID)
    assert stored["narrative_version"] == "nar-0"
    assert _highlights(stored) == 0, "db 读路径被污染 ⇒ 派生链的输入不再可复现"


def test_7_narrative_stamp_cannot_move_the_reuse_gate():
    """⑦ 拦复用门＝重跑取证、烧真配额。装配代次只管视图，不该有这个副作用。

    ⚠️ 第一版这里用 `reuse_policy(lc, None)` 比"加不加戳同判"，**是条恒真断言**：
    kaili 夹具的 caliber 本来就缺 `scope_policy_version`，门对带戳与不带戳都同样拒
    （拒因是"ev 版本不符"，跟本函数一点关系没有）⇒ 红了也说明不了任何事。
    现在先用 `conftest.live_payload` 把代次盖齐、**断门本来会放行**，再比三种加戳形态。
    """
    lc = live_payload(json.loads(json.dumps(KAILI)))
    cal = lc.get("caliber") or {}
    wanted = {
        "travel_mode": cal.get("travel_mode", "walking"),
        "sample_profile": cal.get("sample_profile", "standard"),
        "study_radius_m": float(lc["scene"]["study_radius_m"]),
    }
    base = report_contract.reuse_policy(lc, wanted)
    assert base[0] is True, f"前提不成立：这份载荷本来就不给复用（{base[1]}），比不出'加戳没改变判定'"

    on_top = dict(lc)
    on_top["narrative_version"] = "nar-9"          # 真实落点：Report 顶层
    assert report_contract.reuse_policy(on_top, wanted) == base, (
        "reuse_policy 读到了载荷顶层的装配代次 ⇒ 存量与邻近复用会被集体打 miss")

    buried = json.loads(json.dumps(lc))
    buried["caliber"]["narrative_version"] = "nar-9"   # 假想落点：哪天有人把它挪进 caliber
    assert report_contract.reuse_policy(buried, wanted) == base, (
        "reuse_policy 读了 caliber 里的装配代次 ⇒ 换代次会让 27 份存量与每次 500m 邻近复用"
        "全部 miss、重打 1049 点距离矩阵，换来的正确性是零")

    assert report_contract.narrative_refresh_needed(
        {"report_type": "research"}, NARRATIVE_VERSION)[0] is False, "非生活圈报告不许被这层碰"
    assert report_contract.narrative_refresh_needed(
        {"report_type": "living_circle"}, NARRATIVE_VERSION)[0] is False, "没有载荷时无从重装，只能原样给"
