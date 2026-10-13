"""第五维「区域交通时段暴露度」· 判据先行批次（2026-10-13）。

本文件按 `~/.qoder-cn/plans/swift-hollow-carp.md` 的「测试策略决策」落：**判据先行**——
P0 判据先入库，实现未到位的那几条以 `xfail(strict=True)` 挂账（修好后会 XPASS→失败，
强制摘标记，不允许静默转绿，照 `test_caliber_invariants.py` 的既有挂账纪律）。

回溯（见计划文件的覆盖差距矩阵）：
  TC-01 → INV-01  五维权重之和恰为 1.0        【现在就绿，防重分配写错】
  TC-06 → EX-03  路况外呼不吃采集预算        【现在就绿，防共享扣减】
  TC-07 → CT-01  G-9 期望集与「合法桩」同步    【现在就绿，防新原语无人守】
  TC-02 → INV-05 无源样区总分逐位不变         【待步骤 4/8】
  TC-03 → INV-06 声明 tv-1 却缺键即拒签       【待步骤 6】
  TC-04 → INV-04 absent 却发档位即拒签        【待步骤 6】
  TC-05 → EQ-02  未知档位枚举必须拒签         【待步骤 6】
  TC-19 → CI-01  假替身下走通「有源路径」      【待步骤 3/6】
"""
from __future__ import annotations

import asyncio
import importlib
import json
import re
from pathlib import Path

import pytest

from app.living_circle import quota, scoring, traffic

BACKEND = Path(__file__).resolve().parent.parent


# ── 现在就绿的三条：它们守的是"实现不许把既有不变式改坏" ─────────────────────

def test_tc01_scoring_weights_sum_to_one():
    """INV-01：五维（现四维）权重之和必须是 1.0 —— 加第五维时这里第一道现形。

    ⚠️ 失败时先看是不是**故意**改了分配而忘了同步本判据：本判据不锁具体数值，
    只锁"归和"这一条不变量（分数口径里最容易静默出错、又最难事后发现的地方）。
    """
    total = sum(scoring.WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"WEIGHTS 之和 {total} ≠ 1.0 —— 加/改维度后必须重新分配：{scoring.WEIGHTS}"
    assert all(w > 0 for w in scoring.WEIGHTS.values()), f"权重不许非正：{scoring.WEIGHTS}"


def test_tc06_poi_budget_is_free_of_any_traffic_term():
    """EX-03 / F2：路况外呼**不得**挤占采集预算。

    判据形状＝同一条等式在"有没有路况池"两种世界下都成立：`poi_budget_for(mat) == total - mat`。
    一旦有人把路况计入共享扣减（把 traffic 从 total 里减掉），这条会当场红。
    """
    for mat in (0, 137, 600, 1049):
        assert quota.poi_budget_for(mat) == max(0, quota.total_budget() - mat)
    # 独立池若已落地，它必须**不参与**上面那条等式：允许它存在，但不许被减进 total。
    if hasattr(quota, "traffic_budget"):
        assert quota.poi_budget_for(500) == max(0, quota.total_budget() - 500), \
            "traffic_budget 出现后 poi_budget_for 的算式被改动了 —— 独立池的前提破了"


def test_tc07_g9_expectation_set_and_legal_stub_stay_in_sync():
    """CT-01：G-9 的期望集与 `test_degrade_chain._G9_LEGAL_SOURCE` 必须同步长。

    实码依据：`check_guard_construction.py` 的 `FORENSIC_PRIMITIVES`（期望集）与
    `test_degrade_chain.py` 顶部那句注释——「第六名 collect_triad_evidence 是片 4 加进 G-9 的，
    这份桩必须跟着长，否则 M13b 会替『新原语其实没人守』背书」。
    本判据把这句话变成机器可证：两边集合不等即红。
    """
    guard = (BACKEND / "scripts" / "check_guard_construction.py").read_text(encoding="utf-8")
    m = re.search(r"FORENSIC_PRIMITIVES\s*=\s*\(([^)]*)\)", guard, re.S)
    assert m, "找不到 FORENSIC_PRIMITIVES —— 守卫脚本结构变了，先看是不是被改名"
    # ⚠️ 两步净化，各自有前科：
    #   ① 先**剥行注释**——本仓纪律「扫源码类判据先剥注释」，否则解释文字里的引号串会被当代码
    #      （实测：守卫里那句 `coverage="absent"` 的注释让 `absent` 混进了原语集）；
    #   ② 再只认 ASCII 标识符——Python 的 `\w` 也匹配中文，会把行内注释的中文串一起收进来。
    block = "\n".join(re.sub(r"#.*$", "", line) for line in m.group(1).splitlines())
    expected = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', block))
    assert expected, "FORENSIC_PRIMITIVES 解析为空 —— 判据作废，先修本用例的取数"

    chain = (BACKEND / "tests" / "test_degrade_chain.py").read_text(encoding="utf-8")
    m2 = re.search(r"_G9_LEGAL_SOURCE\s*=\s*\((.*?)\n\)", chain, re.S)
    assert m2, "找不到 _G9_LEGAL_SOURCE —— 合法桩结构变了"
    # 桩是相邻字符串字面量的隐式拼接（含 \n 转义），逐个取出再还原成源码文本
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m2.group(1))
    stub = "".join(p.encode("utf-8").decode("unicode_escape") for p in parts)
    assert stub.count("def live_forensic_steps") == 1, "桩里必须恰有一个编排函数"
    missing = sorted(n for n in expected if f"{n}(" not in stub)
    assert not missing, (
        f"G-9 期望集里的这些原语没出现在「合法桩」里：{missing}。"
        "加新原语时两处必须同批改（否则 M13b 会替『新原语没人守』背书）——"
        f"期望集 {sorted(expected)}，桩里出现 {sorted(n for n in expected if f'{n}(' in stub)}"
    )


# ── 待实现的五条：strict xfail 挂账，实现落地后逐条摘标记 ───────────────────

def test_tc19_http_boundary_fake_reaches_the_sourced_branch():
    """CI-01：**有源路径**必须能在无网环境里被走到 —— 在 HTTP 边界打桩。

    为什么替的是 HTTP 出口（`BaiduClient._get`）而不是 `fetch_traffic_exposure` 本身：
    后者会把状态判定与聚合一起绕过，测的只是"假函数返回了假数据"。这里用 2026-10-13
    探针的**真实回执**（`capability_manifest.traffic_service` 那次劲松实测）当响应体，
    客户端层与聚合层都真跑。
    """
    real_body = {
        "status": 0, "message": "成功",
        "description": "该区域整体轻微拥堵。东三环南路：北向南,从双井桥到分钟寺桥拥堵。",
        "evaluation": {"status": 2, "status_desc": "轻微拥堵"},
        "road_traffic": [
            {"road_name": "东三环南路", "congestion_sections": [
                {"road_type": 2, "congestion_distance": 3420, "speed": 18.18, "status": 3,
                 "congestion_trend": "SAME", "section_desc": "北向南,从双井桥到分钟寺桥"}]},
            {"road_name": "劲松中街"},
        ],
    }

    class FakeClient:
        async def _get(self, path, params):
            assert path == "/traffic/v1/around", f"取数路径变了：{path}"
            assert params["radius"].isdigit(), f"半径必须是米制整数：{params}"
            # ⚠️ 坐标顺序的**唯一判据**（2026-10-13 真机事故）：入参 center 是本仓的 (lng,lat)，
            # 而百度要 lat,lng ⇒ 请求里必须**倒过来**。这里传 (116.46…, 39.88…)（lng,lat），
            # 断言请求串以纬度 39.88 开头。少了这条，顺序错会一路静默降级成 absent（真机实测过）。
            lat_s, lng_s = params["center"].split(",")
            assert lng_s.startswith("116.46") and lat_s.startswith("39.88"), (
                f"center 顺序错：请求里是 {params['center']!r}，应为 lat 在前（本仓入参是 lng,lat）")
            return real_body

    # ⚠️ 入参顺序照**本仓约定** (lng, lat)：首版这条判据跟着被测代码一起写成了 (lat, lng)，
    # 于是它替错误前提背了书（顺序错的代码在它面前全绿）——真机事故 2026-10-13。
    block = asyncio.run(traffic.fetch_traffic_exposure(
        FakeClient(), center=(116.464601, 39.883546), radius_m=934.0, caliber=None))
    assert block["coverage"] == "ok", block
    assert block["sections_count"] == 1 and block["congested_distance_m"] == 3420.0
    assert abs(sum(block["tier_share"].values()) - 1.0) < 1e-6
    assert block["region"] == "circle" and "error" not in block
    # 拍板纪律（2026-10-13）：只用聚合、不点名路段 —— 路段名/方向/起止点一律不进载荷
    blob = json.dumps(block, ensure_ascii=False)
    for leak in ("三环", "双井桥", "北向南", "road_name"):
        assert leak not in blob, f"载荷泄露了路段级信息：{leak}"


def _gate(lc):
    from app.living_circle import report_contract as rc
    return rc._traffic_caliber_violations(lc)


def test_tc03_declared_stamp_without_keys_is_rejected():
    """INV-06：声明了 tv-1 却缺 sampling.traffic ⇒ 拒签（照 B14/B16/B17 形状）。"""
    assert _gate({"caliber": {"traffic_caliber_version": "tv-1"}}), "声明了代次却缺键，判据必须非空"
    # 负对照：没声明这一代的存量件 ⇒ 整套跳过（否则全部历史报告会被新闸打死）
    assert _gate({"caliber": {}}) == [] and _gate({}) == []


def test_tc04_absent_coverage_must_not_ship_tier_readings():
    """INV-04：coverage=absent ⇒ 档位读数整块不发（不许印 0，也不许印空）。"""
    lc = {"caliber": {"traffic_caliber_version": "tv-1"},
          "sampling": {"traffic": {"coverage": "absent", "tier_share": {"畅通": 1.0}}}}
    hits = _gate(lc)
    assert hits and "absent" in hits[0], f"absent 却带档位读数必须拒签，实得 {hits}"
    # 干净的 absent（只留状态位）必须放行 —— 缺源是合法态
    ok = {"caliber": {"traffic_caliber_version": "tv-1"},
          "sampling": {"traffic": {"coverage": "absent", "region": "circle"}}}
    assert _gate(ok) == [], f"合法的缺源件被误杀：{_gate(ok)}"


def test_tc05_unknown_tier_enum_is_rejected_not_dropped():
    """EQ-02：百度将来多返回一档时，宁可拒签也不许静默丢弃 —— 且要**点名那个值**。"""
    base = {"coverage": "ok", "region": "circle", "radius_m": 934.0,
            "congested_distance_m": 3420.0, "sections_count": 1,
            "unknown_tier_sections": 0, "unknown_tier_codes": [],
            "exposure_index": 1.6, "exposure_score": 57.1,
            "multiplier_table": {"畅通": 1.0, "缓行": 1.15, "拥堵": 1.6, "严重拥堵": 2.4},
            "multiplier_table_version": "tm-1"}
    bad = {**base, "tier_share": {"畅通": 0.5, "严重拥堵+": 0.5}}
    hits = _gate({"caliber": {"traffic_caliber_version": "tv-1"}, "sampling": {"traffic": bad}})
    assert any("严重拥堵+" in v for v in hits), f"违规消息必须点名那个看不懂的档位值，实得 {hits}"
    # 取数侧同一条纪律的另一半：未知档**进不了载荷读数**，但要计数并列出取值
    real_body = {"status": 0, "evaluation": {"status": 2},
                 "road_traffic": [{"road_name": "X", "congestion_sections": [
                     {"status": 9, "congestion_distance": 100}]}]}
    parsed = traffic._parse(real_body)
    assert parsed["unknown_tier_sections"] == 1 and parsed["unknown_tier_codes"] == [9]
    assert parsed["congested_distance_m"] == 0.0, "看不懂的档位不许混进里程合计"


def test_tc01b_two_weight_tables_keep_the_same_ratio():
    """两张权重表的关系必须是"同一比例的两种写法"，否则无源样区的总分会被静默改掉。

    `scoring.WEIGHTS`（五维）与 `scoring.LEGACY_WEIGHTS`（换代前的四维原字面量）不是两处真源、
    而是一件事的两半：四维在两张表里的**比例**必须一致（容差 1e-9），第五维只占剩下的那一份。
    """
    w, legacy = scoring.WEIGHTS, scoring.LEGACY_WEIGHTS
    assert set(legacy) == set(w) - {"traffic"}
    share = 1.0 - w["traffic"]
    for k, v in legacy.items():
        assert abs(w[k] / share - v) < 1e-9, f"{k} 在两表里的比例不一致：{w[k]}/{share} vs {v}"
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert abs(sum(legacy.values()) - 1.0) < 1e-12


def test_tc02_sourceless_total_is_bit_identical():
    """INV-05：coverage=absent 的载荷，换代前后 scores.total 必须**逐位相同**。

    没有这条，权重重分配会静默把凯里那类无源样区的分数一起改掉（`LEGACY_WEIGHTS` 就是为它存在的）。
    另附有源一侧的正对照：coverage=ok 且 exposure_score 与四维同分时，总分应高于 absent 一侧
    （否则说明第五维被算成了恒零项，"进分"没真发生）。
    """
    four = [{"coverage": 1.0, "min_minutes": 8.0, "in_circle": 3, "label": "医疗"}]
    before = scoring.compute_scores(four, [], 0, judged_share=1.0)
    absent = scoring.compute_scores(four, [], 0, judged_share=1.0, traffic={"coverage": "absent"})
    assert before["total"] == absent["total"], "无源样区的总分被换代动过了"
    ok = scoring.compute_scores(four, [], 0, judged_share=1.0,
                                traffic={"coverage": "ok", "exposure_score": 100.0,
                                         "peak_window": "07:00-09:00",
                                         "multiplier_table_version": "tm-1"})
    assert ok["total"] >= absent["total"], "有源（满分档）不该低于缺源一侧"


# ── 笔 B：第 9 章的两张图件（nar-7）────────────────────────────────────────
#
# 回溯：INV-04（缺源整块不发，延伸到图件）、EQ-01（四档等价类）、R7（既有"option 禁坐标/
# 禁 gap"那把闸是按四章列举的，新增图默认逃出它 ⇒ 这里同形重钉）、OBS-02（措辞纪律）。

JINSONG = json.loads((BACKEND / "app/living_circle/fixtures/beijing-jinsong.json").read_text(encoding="utf-8"))


def _assembled(lc: dict) -> dict:
    from app.core.pipeline.diagnosis_templates import assemble_report
    return assemble_report(lc, "lc-traffic-charts", "key:lc-traffic-charts", "图件判据")


def _traffic_section(rep: dict):
    return next((s for s in rep["sections"] if s["id"] == "traffic"), None)


def test_traffic_charts_have_two_bars_with_all_four_tiers():
    """有源 ⇒ 恰好两张图、四键齐、四档全发（少一行就破坏"占比之和为 1"的可对照性）。"""
    sec = _traffic_section(_assembled(JINSONG))
    assert sec is not None, "有源样区必须出第 9 章"
    charts = sec["charts"]
    assert len(charts) == 2, f"第 9 章图数 {len(charts)} ≠ 2（每章 ≤2 图，两张都已拍板）"
    for c in charts:
        assert {"chart_id", "type", "title", "option"} <= set(c), f"图件缺字段：{sorted(set(c))}"
        assert c["chart_id"].startswith("chart-traffic-"), f"chart_id 前缀不对：{c['chart_id']}"
        assert c["type"] == "bar", f"生活圈报告只用 radar/bar/scatter，实得 {c['type']}"
        assert "evidence_ids" not in c, "本章 source_evidence_ids 为空 ⇒ 图带 evidence_ids 会撞悬空判据"
    tiers = ["畅通", "缓行", "拥堵", "严重拥堵"]
    for c in charts:
        assert c["option"]["yAxis"]["data"] == tiers[::-1], f"{c['chart_id']} 的档位轴缺档或乱序"
        assert len(c["option"]["series"][0]["data"]) == 4, f"{c['chart_id']} 条数 ≠ 4"


def test_traffic_tier_chart_matches_payload_share_and_sums_to_one():
    """占比条的四个数值必须与 `tier_share` 逐档对得上，且四档之和为 100%。"""
    sec = _traffic_section(_assembled(JINSONG))
    tiers = ["畅通", "缓行", "拥堵", "严重拥堵"]
    chart = next(c for c in sec["charts"] if c["chart_id"] == "chart-traffic-tiers")
    by_tier = {d["itemStyle"]["color"]: d["value"] for d in chart["option"]["series"][0]["data"]}
    share = JINSONG["sampling"]["traffic"]["tier_share"]
    assert abs(sum(share.values()) - 1.0) < 1e-6, f"档位占比之和 {sum(share.values())} ≠ 1"
    for t in tiers:
        assert abs(round(share[t] * 100, 3) - by_tier[_tier_color(t)]) < 1e-6, f"{t} 的条值与载荷不符"


def _tier_color(tier: str) -> str:
    from app.core.pipeline.diagnosis_templates import TRAFFIC_TIER_COLOR
    return TRAFFIC_TIER_COLOR[tier]


def test_traffic_mapping_chart_marks_the_recomputed_index():
    """映射图那根线标的必须是载荷里的 `exposure_index`，且四根条就是 `multiplier_table`。

    这根线是"可复算性"的可视化（分数 = Σ占比×倍数），所以它必须与指数逐位同源，
    并且 label 显式 `rotate: 0` —— ECharts 对竖线标签默认自动旋转，会与条形挤在一起。
    """
    tr = JINSONG["sampling"]["traffic"]
    sec = _traffic_section(_assembled(JINSONG))
    chart = next(c for c in sec["charts"] if c["chart_id"] == "chart-traffic-mapping")
    data = {d["itemStyle"]["color"]: d["value"] for d in chart["option"]["series"][0]["data"]}
    for t, m in tr["multiplier_table"].items():
        assert data[_tier_color(t)] == m, f"{t} 的倍数条不是表里那个值"
    ml = chart["option"]["series"][0]["markLine"]["data"][0]
    assert ml["xAxis"] == tr["exposure_index"], "指数线必须逐位等于载荷读数"
    assert ml["label"]["rotate"] == 0, "markLine 标签不许被自动旋转成竖排"
    # 可复算正对照：Σ占比×倍数 必须落在这根线上
    recomputed = sum(tr["tier_share"][t] * tr["multiplier_table"][t] for t in tr["multiplier_table"])
    assert abs(recomputed - tr["exposure_index"]) < 1e-6, f"图上那根线复算不出来：{recomputed}"


def test_traffic_chart_options_carry_no_geography_and_no_segment_name():
    """分享态 P0-5 那把闸的**遍历口径**要覆盖新图：禁经纬度对、禁 `gap \\d`、禁路段名/方向。

    ⚠️ 既有那条扫描（`test_chapter_coverage_position_charts.py` ⑭）是按四章列举的，
    新增图默认不在它覆盖面里 —— 这条就是把同一把尺引到第 9 章，并加一层本章特有的
    "只用聚合、不点名路段"禁令（载荷本就没有路段名，钉死防将来有人往 option 里塞）。
    """
    sec = _traffic_section(_assembled(JINSONG))
    coord = re.compile(r"\d{2,3}\.\d{3,}\s*,\s*\d{1,3}\.\d{3,}")
    gap = re.compile(r"gap\s+\d")
    segment_words = ("路名", "路段名", "向南", "向北", "向东", "向西", "方向", "三环", "辅路", "匝道")
    for c in sec["charts"]:
        blob = json.dumps(c["option"], ensure_ascii=False)
        assert not coord.search(blob), f"{c['chart_id']} 的 option 里出现经纬度对 ⇒ 分享态泄漏精确坐标"
        assert not gap.search(blob), f"{c['chart_id']} 的 option 里出现 gap 读数 ⇒ 那是被脱敏的字段"
        hit = [w for w in segment_words if w in blob]
        assert not hit, f"{c['chart_id']} 的 option 点名了路段/方向：{hit}"


def test_traffic_charts_absent_entirely_when_source_missing():
    """缺源 ⇒ 整章不出现，图也一张不发（presence 门控延伸到图件，不许印成 0）。"""
    import copy
    lc = copy.deepcopy(JINSONG)
    lc["sampling"]["traffic"] = {"coverage": "absent", "region": "circle"}
    rep = _assembled(lc)
    assert _traffic_section(rep) is None, "缺源却发了第 9 章 ⇒ 会把'没测到'印成结论"
    ids = [c["chart_id"] for s in rep["sections"] for c in (s.get("charts") or [])]
    assert not [i for i in ids if i.startswith("chart-traffic-")], f"缺源样区漏出了路况图件：{ids}"


def test_traffic_tier_colors_are_disjoint_from_category_colors():
    """四档路况色是一组独立语义色，与 8 类类目色**交集必须为空**。

    最深档从 `#C06B3E` 下调到 `#9E4A2A` 的动因就是它与类目色 `market=#C2642E` 近似到
    同屏会读错。这组色不进 `LC_CAT_COLOR`、不经 `_cat_color()`，键集必须与档位名册一致。
    """
    from app.core.pipeline.diagnosis_templates import LC_CAT_COLOR, TRAFFIC_TIER_COLOR
    assert set(TRAFFIC_TIER_COLOR) == {"畅通", "缓行", "拥堵", "严重拥堵"}
    both = set(TRAFFIC_TIER_COLOR.values()) & set(LC_CAT_COLOR.values())
    assert not both, f"路况色与类目色撞值：{both}"
    assert len(set(TRAFFIC_TIER_COLOR.values())) == 4, "四档色互异"
    for v in TRAFFIC_TIER_COLOR.values():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", v), f"色值写法不合表内约定：{v}"


def test_assembled_report_text_has_no_raw_markdown_bold():
    """族守卫：装配产出的**正文**里不许出现裸 `**`（本视图按纯文本渲染，星号会原样上屏）。

    成因是实测抓到的：第 9 章一度写了 `**圆域**`，屏上就是一串星号残渣。
    扫描面只圈"会上屏的那几格"（key_takeaway / paragraphs / highlights 文本 / claims 文本），
    不圈载荷里的 `basis` 那类纯溯源字段 —— 它按 markdown 写出处反而是给人读的。
    """
    offenders = []
    for f in sorted((BACKEND / "app/living_circle/fixtures").glob("*.json")):
        rep = _assembled(json.loads(f.read_text(encoding="utf-8")))
        for s in rep["sections"]:
            texts = [s.get("key_takeaway") or ""] + list(s.get("paragraphs") or [])
            texts += [h.get("text", "") if isinstance(h, dict) else str(h) for h in (s.get("highlights") or [])]
            texts += [c.get("text", "") for c in (s.get("claims") or [])]
            offenders += [f"{f.name}/{s['id']}: {t[:50]}" for t in texts if "**" in t]
    assert not offenders, "报告正文出现 markdown 强调（屏上会留裸星号）：\n" + "\n".join(offenders)


def test_traffic_tier_colors_mirror_the_frontend_table():
    """四档路况色跨端镜像：前端那张表与后端 `TRAFFIC_TIER_COLOR` **同名同值、键集相等**。

    为什么值得钉：第 9 章两张条形图的条色出自后端产出的 option，地图上那圈的圈色与图例
    出自前端那张表 —— 两处各写一份，早晚会一条说"拥堵是橙"、另一枚画成红。
    形状照 `test_chapter_map_focus_and_color_table.py::test_7`（正则扫前端源码块，
    扫不到就当场红，而不是静默少比）。
    """
    import re
    from app.core.pipeline.diagnosis_templates import TRAFFIC_TIER_COLOR, TRAFFIC_TIER_ORDER

    ts = (BACKEND.parent / "frontend/src/lib/livingCircle.ts").read_text(encoding="utf-8")
    m = re.search(r"export const LC_TRAFFIC_TIER_COLOR: Record<string, string> = \{(.*?)\n\}", ts, re.S)
    assert m, "前端那张表扫不到（改了写法？本条会静默少比，必须红）"
    pairs = re.findall(r'^\s*"?([一-龥A-Za-z_]+)"?\s*:\s*(\'[^\']+\'|"[^"]+")', m.group(1), re.M)
    ts_colors = {k: v.strip("'\"") for k, v in pairs}
    assert ts_colors == TRAFFIC_TIER_COLOR, (
        f"四档色分叉：只有前端有 {sorted(set(ts_colors) - set(TRAFFIC_TIER_COLOR))}、"
        f"只有后端有 {sorted(set(TRAFFIC_TIER_COLOR) - set(ts_colors))}、"
        f"同档不同值 {sorted(k for k in set(ts_colors) & set(TRAFFIC_TIER_COLOR) if ts_colors[k] != TRAFFIC_TIER_COLOR[k])}")
    # 档位名册也要相等：前端那份 order 决定图例顺序与圈色取值
    order = re.search(r"export const LC_TRAFFIC_TIER_ORDER = \[(.*?)\]", ts)
    assert order and [x.strip(" '\t") for x in order.group(1).split(',')] == list(TRAFFIC_TIER_ORDER), \
        "四档顺序两端不一致 ⇒ 图例与条形图会串档"


def test_traffic_chapter_emits_a_circle_map_focus():
    """笔 E：第 9 章发一种新焦点 `traffic_circle`（半径不进焦点、只留 kind＋图注）。

    焦点里**不许带米数** —— 那是第二个事实源：前端画圈读 `sampling.traffic.radius_m`，
    与主图那一枚同源。这里同时钉图注那三条实话（查询范围≠可达区、没灰化任何点）。
    """
    sec = _traffic_section(_assembled(JINSONG))
    mf = sec["map_focus"]
    assert mf["kind"] == "traffic_circle"
    assert set(mf) <= {"kind", "categories", "blind_id", "title"}, f"焦点键越界：{sorted(mf)}"
    assert mf["categories"] == [], "圆域章不聚焦任何设施类目 ⇒ 一个点都不该灰化"
    assert "radius_m" not in mf and "radius" not in mf, "米数只许住在 sampling.traffic 一处"
    for clause in ("只叠一圈时段圆域", "不是可达区", "一个都没灰化"):
        assert clause in mf["title"], f"图注没交代「{clause}」：{mf['title']}"
    for word in ("只留", "仅显示", "已删除"):
        assert word not in mf["title"], f"图注出现肯定式裁剪声称「{word}」，而画布只叠一圈"


def test_traffic_map_focus_absent_with_the_chapter():
    """缺源 ⇒ 焦点也一张不发（`_section_map_focus` 是独立入口，不许假设调用方门控过）。"""
    import copy
    lc = copy.deepcopy(JINSONG)
    lc["sampling"]["traffic"] = {"coverage": "absent", "region": "circle"}
    rep = _assembled(lc)
    assert _traffic_section(rep) is None
    # 正面半边：把半径改坏（coverage 仍 ok）也不许发焦点 —— 半份声明不该画出一圈像样的东西
    lc2 = copy.deepcopy(JINSONG)
    lc2["sampling"]["traffic"] = {**JINSONG["sampling"]["traffic"], "radius_m": None}
    sec2 = _traffic_section(_assembled(lc2))
    assert sec2 is not None and sec2["map_focus"] is None, "半径坏了却仍发焦点 ⇒ 前端只能静默不画"


# ── 2026-10-13 追加：读数与分数必须同源（演示件真坏过一次）───────────────────
#
# 症状：`sampling.traffic.coverage == "ok"`（第 9 章照常印暴露度 51.995），
# 但 `scores.total` 是**不带第五维**算出来的（注入回执时只写了载荷、没重算分数），
# 而读路径对同代次载荷**直通** ⇒ 全套件全绿、屏上却自相矛盾，评审按公式一复算就穿。

def test_b18_rejects_a_reading_that_never_reached_the_score():
    """契约闸：coverage=ok 而总分那句话里没有第五维 ⇒ 拒签。"""
    from app.living_circle.report_contract import _traffic_caliber_violations
    lc = json.loads((BACKEND / "app/living_circle/fixtures/beijing-jinsong.json").read_text(encoding="utf-8"))
    hits = _traffic_caliber_violations(lc)
    assert hits == [], f"当代夹具本应零违规，实得 {hits}"
    stale = json.loads(json.dumps(lc))
    stale["scores"]["note"] = "确定性评分：覆盖 87.5 / 可达 53.0 / 多样 87.5 / 均衡 0.0"
    hits = _traffic_caliber_violations(stale)
    assert any("没进总分" in h for h in hits), f"分数没进第五维却照签 ⇒ {hits}"
    contradict = json.loads(json.dumps(lc))
    contradict["scores"]["note"] = "确定性评分：…；区域交通时段暴露度：缺源，本项不计入总分"
    assert any("互相打脸" in h for h in _traffic_caliber_violations(contradict)), "有读数却声明缺源，必须红"


def test_every_traffic_ok_fixture_score_actually_includes_the_dimension():
    """夹具面：凡 `coverage=ok` 的载荷，其总分必须能由自己的分量复算出来（含第五维）。

    复算只在**无盲区**的夹具上做严格逐位比对 —— `judged_share` 不进载荷，有盲区时
    盲区扣分无法从存盘字段还原（凯里 ev2 就是这么被误判成"不一致"的：存 68.4、
    按 share=None 复算得 68.8，差异全在外推扣分那一步，与第五维无关）。
    """
    for f in sorted((BACKEND / "app/living_circle/fixtures").glob("*.json")):
        lc = json.loads(f.read_text(encoding="utf-8"))
        tr = (lc.get("sampling") or {}).get("traffic") or {}
        if tr.get("coverage") != "ok":
            continue
        note = lc["scores"]["note"]
        assert "区域交通时段暴露度" in note and "缺源" not in note, f"{f.name}: 读数没进总分 ⇒ {note[:80]}"
        assert "缺源，本项不计入" not in note, f"{f.name}: 有读数却声明缺源"
        if not (lc.get("blindspots") or []):
            rec = scoring.compute_scores(lc["poi"]["categories"], lc["scores"].get("triads") or [],
                                         0, judged_share=None, traffic=tr)
            assert rec["total"] == lc["scores"]["total"], (
                f"{f.name}: 存 {lc['scores']['total']} vs 复算 {rec['total']} ⇒ 分数与载荷不同代")
