"""多样性覆盖度不变量 INV-D1（TC-E20）。

用户诉求是「有 48 位专家，为什么每次都是那几个」。前面几个文件钉的是**机制**
（降级不可伪装、解析边界、预算数值），本文件钉的是**结果**：出镜集合必须有广度。

为什么需要单独一条结果钉：机制类断言全部转绿后，仍可能出现
「组队成功了但 LLM 因名册顺序固定而总挑前几位」——那是另一种只有覆盖面能抓住的失效。
本项目实测现状：`expert_stats` 只有 6 行、3 份报告 experts 字段完全相同。

约定：本文件全部按**生产实况**注入（`chat_json` 拿不到可用产出 +
`last_finish_reason()=="length"`），不假装有团队。因此当前必然 xfail(strict)；
Stage A（降级可见）+ B1（槽位解析）+ B2（多采集者）落地后转绿，届时须摘标。

种子：test_expert_dispatch_degraded.py（同一函数的契约面）、
      test_dashboard_stats.py（跨轮聚合断言写法）。
运行：backend/ 下 `pytest tests/test_expert_diversity.py -q`
"""
import pytest

from app.core import llm
from app.core.pipeline.research import engine as O
from app.data import load_experts

STAGES = "quiet-shore-pike Stage A+B1+B2 未实施（现状恒落回兜底 6 人）"

# 6 轮不同主题，覆盖攻略/评估两类与不同目的地维度
ROUNDS = [
    ("大理 5 天亲子游", ["大理"], ["交通", "住宿", "预算", "口碑"]),
    ("成都 alone 三天美食行", ["成都"], ["美食", "预算", "安全"]),
    ("杭州亲子主题乐园评估", ["杭州"], ["景点", "住宿", "交通"]),
    ("乌镇两天一夜安静行", ["乌镇"], ["住宿", "口碑", "节奏"]),
    ("南京博物院研学攻略", ["南京"], ["景点", "教育", "交通"]),
    ("三亚冬季避寒性价比调研", ["三亚"], ["预算", "气候", "住宿"]),
]

POOL_L1 = [e["id"] for e in load_experts("travel") if e["level"] == "L1"]


def _dead_llm(monkeypatch):
    """按生产实况注入：产出不可用（截断），且无任何真组队信息。"""
    monkeypatch.setattr(llm, "chat_json", lambda messages, **kw: None)
    monkeypatch.setattr(llm, "last_finish_reason", lambda: "length")


def _appearances(monkeypatch):
    seen = []
    for query, dests, focus in ROUNDS:
        _dead_llm(monkeypatch)
        out = O._dispatch_experts(query, dests, focus)
        seen.extend(m["id"] for m in out["members"])
    return seen


@pytest.mark.xfail(strict=True, reason=STAGES)
def test_tc_e20a_expert_pool_breadth_across_runs(monkeypatch):
    """6 轮调研后，出镜专家数必须明显超过兜底名单的 6 人。

    阈值取 12（>2× 兜底规模）而非「全部 48」：一轮组队本就是小团队，
    要求全池覆盖会变成不可能达成的配额断言，反而诱发为凑数选人。
    """
    seen = set(_appearances(monkeypatch))
    assert len(seen) > 12, f"6 轮只用过 {len(seen)} 位专家：{sorted(seen)}"


@pytest.mark.xfail(strict=True, reason=STAGES)
def test_tc_e20b_l1_execution_layer_is_who_rotates(monkeypatch):
    """轮换主要应发生在 L1 执行层（池子里 36/48 都在这一层）。

    L3 决策层只有 3 人，主持位轮换上限本就是 3（docs/AGENTS.md §3 的角色映射），
    所以本钉只统计 L1：6 轮后至少应有 5 位不同的 L1 出镜。
    """
    seen = set(_appearances(monkeypatch))
    l1_seen = {i for i in seen if i.startswith("L1")}
    assert len(l1_seen) >= 5, (
        f"L1 层 36 人只出镜 {len(l1_seen)} 位（共 {len(POOL_L1)} 位可选）：{sorted(l1_seen)}")


def test_tc_e20c_pool_depth_is_not_the_bottleneck():
    """前提事实（现状绿钉）：可轮换的池子确实够深，问题不在名册规模。

    若哪天 L1 少于 24 位，本 bug 的「该不该轮换」结论需要重新评估 ——
    那时真正的约束会变成名册本身，而不是选人逻辑。
    """
    assert len(POOL_L1) == 36
    assert len({e["id"] for e in load_experts("travel")}) == 48, "id 必须唯一，否则统计与署名会串号"
