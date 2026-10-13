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

import importlib
import re
from pathlib import Path

import pytest

from app.living_circle import quota, scoring

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
    # ⚠️ 只认 ASCII 标识符：Python 的 \w 也匹配中文，会把元组里行内注释的引号串当成原语名
    expected = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1)))
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

@pytest.mark.xfail(strict=True, reason="待计划步骤 3/6/8：第五维进分尚未实现")
def test_tc19_ci_path_reaches_the_sourced_branch():
    """CI-01：CI 里必须走到「有源」那一路（否则绿灯只证明了 absent 分支）。"""
    traffic = importlib.import_module("app.living_circle.traffic")
    assert hasattr(traffic, "fetch_traffic_exposure"), "缺少取数原语 fetch_traffic_exposure"


@pytest.mark.xfail(strict=True, reason="待计划步骤 6：_traffic_caliber_violations 尚未实现")
def test_tc03_declared_stamp_without_keys_is_rejected():
    """INV-06：声明了 tv-1 却缺 sampling.traffic ⇒ 拒签（照 B14/B16/B17 形状）。"""
    rc = importlib.import_module("app.living_circle.report_contract")
    fn = getattr(rc, "_traffic_caliber_violations")
    lc = {"caliber": {"traffic_caliber_version": "tv-1"}}
    assert fn(lc), "声明了代次却缺键，判据必须非空"


@pytest.mark.xfail(strict=True, reason="待计划步骤 6：absent 却发档位须拒签")
def test_tc04_absent_coverage_must_not_ship_tier_readings():
    """INV-04：coverage=absent ⇒ 档位读数整块不发（不许印 0，也不许印空）。"""
    rc = importlib.import_module("app.living_circle.report_contract")
    fn = getattr(rc, "_traffic_caliber_violations")
    lc = {"caliber": {"traffic_caliber_version": "tv-1"},
          "sampling": {"traffic": {"coverage": "absent", "tier_share": {"畅通": 1.0}}}}
    assert fn(lc), "absent 却带档位读数，必须拒签"


@pytest.mark.xfail(strict=True, reason="待计划步骤 6：未知档位枚举须拒签")
def test_tc05_unknown_tier_enum_is_rejected_not_dropped():
    """EQ-02：百度将来多返回一档时，宁可拒签也不许静默丢弃。"""
    rc = importlib.import_module("app.living_circle.report_contract")
    fn = getattr(rc, "_traffic_caliber_violations")
    lc = {"caliber": {"traffic_caliber_version": "tv-1"},
          "sampling": {"traffic": {"coverage": "ok", "segments_in_ring": 12,
                                   "tier_share": {"畅通": 0.5, "严重拥堵+": 0.5}}}}
    assert any("严重拥堵+" in v for v in fn(lc)), "违规消息必须点名那个看不懂的档位值"


@pytest.mark.xfail(strict=True, reason="待计划步骤 4/8：无源样区总分逐位不变判据")
def test_tc02_sourceless_total_is_bit_identical():
    """INV-05：coverage=absent 的载荷，换代前后 scores.total 必须逐位相同。

    没有这条，权重重分配会静默把凯里那类无源样区的分数一起改掉。
    """
    from app.living_circle.scoring import compute_scores  # noqa: PLC0415
    absent = {"coverage": "absent"}
    before = compute_scores({}, {}, 0, judged_share=0.0, evidence_complete=False)
    after = compute_scores({}, {}, 0, judged_share=0.0, evidence_complete=False, traffic=absent)
    assert before["total"] == after["total"], "无源样区的总分被换代动过了"
