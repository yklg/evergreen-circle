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
    `test_shape_stamp_does_not_move_the_reuse_gate` 同族）；
 ⑧ 快照＝**它自带载荷的产物**（第二步 2′：把"该信哪份"从注释升级成会红的判据）；
 ⑨ ⑧ 的正对照 —— 绕过装配器改库里的产物，比较必须翻脸（否则 ⑧ 是恒真断言）。

⚠️ ⑧⑨ 只封住 2′ 声明的两条漂道之一（「绕开装配器改库」）。另一条「装配器改了而戳没动」
   本文件**结构上看不见** —— ⑧ 的两侧都在同一进程里由同一个装配器算出，代码怎么改右边
   跟着变，等式恒成立。那一条由 `test_narrative_assembly_golden.py` 的逐面金标 + 配对闸封。

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

# 实测量出来的锚点。换夹具要一起重测，不许退化成 `>= 1` 这种恒真断言。
#
# nar-2（2026-10-08 方案 C 档）后这两个数**由分支构成拼出来**，逐条列在这里，
# 免得下次口径一动、数字变了却没人说得清是谁贡献的：
#   亮点 10 = 概览 2（`spread` + `triad`；该夹具盲区 0 ⇒ 没有 `blindspot` 句）
#             + 医疗 1 + 教育 2 + 菜市 1 + 养老 1（各章自有句）
#             + 等时圈 2 + 结论 1
#   图   8 = 概览 2 + 等时圈 2 + **四个专题章各 1 张覆盖度位置图**（nar-1 时是 4）
# 养老的耗时位次句在该夹具下不产（`min_minutes` 为 None ⇒ 取不到最近点，见
# `test_highlights_are_chapter_specific.py` 的缺席分支判据）。
EXPECT_HIGHLIGHTS = 10
EXPECT_CHARTS = 8
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
    assert len(stored["charts"]) < EXPECT_CHARTS, (
        "前提不成立：退化出来的'老行'图数不比现在少 ⇒ 这条比的是自己跟自己，"
        "加厚档位（含 nar-2 新增的四张位置图）没有可判的增量")
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


def test_8_stored_snapshot_is_the_product_of_its_own_payload():
    """⑧ 快照＝可验证缓存，不是第二处权威（第二步 2′ 的落点）。

    前七条都在验"读出去的东西对不对"，没有一条验**库里那一行自己**。而 2′ 要防的失效
    恰好在这儿：有人绕过装配器改库、`save` 时丢了字段、或载荷被就地改过而戳没动 ——
    屏幕上全都看不出来（读路径同代次直通，直接把漂掉的快照发出去）。

    判据：把库里那行读回来，用**它自带的那份载荷**重新装配一次，两者必须逐字相等。
    对**本条管的这条通道**而言 "payload_sha256" 是冗余（直接判定比哈希更强，哈希只是它的
    代理），所以 2′ 实现里刻意**不加哈希** —— 加了反而给"这是哪一代"造出第二处权威，
    与本仓「一词多义/单一来源」那条纪律相反。
    ⚠️ 但这不等于 2′ 不需要金标准：本条对「装配器改了而戳没动」是恒等的（两侧同源），
       那一半落在 `test_narrative_assembly_golden.py`。

    ⚠️ 刻意不读生产库（`app/data/verda.db` 被 gitignore，CI 里不存在）：判据必须自己
    造行，否则它在 CI 里恒 skip —— 恒 skip 的守卫比没有守卫更坏。
    """
    _seed()
    stored = db.get_report(RID)
    assert stored is not None, "落库后读不回来 ⇒ 后面的比较没有对象"
    rebuilt = assemble_report(
        stored["living_circle"], RID, SCENE_KEY, stored.get("title") or ""
    )
    assert stored == rebuilt, (
        "库里那行不是它自带载荷在当前代次下的装配产物 ⇒ 快照已经漂，"
        "而同代次读路径会直通把它发出去"
    )
    # 逐字相等之外再钉三个最容易各自漂的面（防"两边同时错成一份"时的可读性）
    assert stored["sections"] == rebuilt["sections"]
    assert stored["toc"] == rebuilt["toc"]
    assert stored["subtitle"] == rebuilt["subtitle"]


def test_9_guard_detects_a_snapshot_edited_behind_the_assembler(calls):
    """⑨ 正对照：⑧ 真的会红。手工把库里那行的正文改一个字，⑧ 式的比较必须翻脸。

    没有这条，⑧ 可能是"两边都读同一份内存对象"式的恒真断言（本仓栽过好几次的形状）。
    """
    _seed()
    stored = db.get_report(RID)
    tampered = assemble_report(stored["living_circle"], RID, SCENE_KEY, stored.get("title") or "")
    tampered["sections"][0]["highlights"] = []          # 绕过装配器，直接改产物
    db.save_living_circle_report(tampered, scene_key=SCENE_KEY)

    again = db.get_report(RID)
    rebuilt = assemble_report(again["living_circle"], RID, SCENE_KEY, again.get("title") or "")
    assert again != rebuilt, (
        "改了库里的产物而载荷没动，比较却仍然相等 ⇒ ⑧ 是恒真断言，守不住任何东西")
    assert again["sections"][0].get("highlights") == [] and rebuilt["sections"][0].get("highlights"), (
        "篡改没落到正确的位置上，这条正对照无效")
    assert len(calls) == 0, "本条只做库内比较，不该触发读路径重装"


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


def test_10_two_generations_coexist_without_cross_contamination(calls):
    """⑰ 混态：库里同时躺着 nar-1 的老行与 nar-2 的新行 —— 升代次后**真实存在的中间态**。

    前九条各测单态（要么全是老行、要么刚播种就是当代），没有一条管两代行并排时会不会互相污染：
    老行必须重装、新行必须直通，且各自的 `narrative_version` 不许串台
    （串台的形态是"新行被当成老行反复白重装"或"老行被当成新行永远发旧正文"）。
    """
    stale = _seed("nar-1")                              # 老行：戳落后一代
    fresh = _assemble()
    fresh["id"] = RID + "-fresh"
    db.save_living_circle_report(fresh, scene_key=SCENE_KEY)
    assert fresh["narrative_version"] == NARRATIVE_VERSION, "前提不成立：新行本来就不带当代戳"
    del calls[:]

    got_stale = client.get(f"/api/reports/{RID}").json()
    assert len(calls) == 1, "老行没触发重装"
    assert got_stale["narrative_version"] == NARRATIVE_VERSION

    got_fresh = client.get(f"/api/reports/{RID}-fresh").json()
    assert len(calls) == 1, "当代戳的新行被误判成老行 ⇒ 每次读都白重装一次"
    assert got_fresh == fresh, "新行读回来变了 ⇒ 两代行互相污染"
    assert db.get_report(RID)["narrative_version"] == "nar-1", "读路径把老行的戳改写了 ⇒ 不许回写"
    assert stale["narrative_version"] == "nar-1"
