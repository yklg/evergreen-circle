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
            return real_body

    block = asyncio.run(traffic.fetch_traffic_exposure(
        FakeClient(), center=(39.883546, 116.464601), radius_m=934.0, caliber=None))
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
