"""游客档的输出契约：派生指标必须是显式「未评」（附录 G-07，第一片 D1 / D9 / U1，TC-08 后端半）。

前端半（`types.ts` 的 `scores | null` 与消费点清单）在
`frontend/src/__tests__/visitorUnrated.test.tsx`；这里守后端半：

* 今天**没有任何一种方式**能产出一份"没打分"的体检报告：`scenario.py` 不存在，
  `scoring.compute_scores` 的入参里也没有场景或权重开关，任何一次组装都会算出一个数值总分。
* 「未评」若被表示成**字段缺席**（`?:`），下游一个 `|| 0` 就把它坐实成"这个景点 0 分";
  若被表示成 `total: 0`，则与真实 0 分不可区分 —— 本仓离线报告的正文层已经这样钉过
  （`livingCircleContract.test.ts` F2 断言 `scores.total === 0`），列表层却存 NULL。
  ⇒ D9 选 `… | null`：值存在、语义是"本档未评"，两端都无法顺手当 0 用。

本文件的 xfail 判据取自计划 D1 的声明形状（`ScenarioProfile.emits` = 输出契约）。
若实施时换了别的字段名，必须**同时**改这条测试与计划 D1，写清为什么换 ——
而不是把测试放宽成"随便什么都算声明过"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.pipeline.diagnosis_templates import assemble_report
from app.living_circle import scoring

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "living_circle" / "fixtures"
MODULE = "app.living_circle.scenario"


def test_no_way_to_produce_an_unscored_report_today():
    """**现状记录（D9 的起点）**：组装与评分层都没有"本档不打分"的开关。"""
    import importlib.util

    assert importlib.util.find_spec(MODULE) is None, (
        f"{MODULE} 已存在 ⇒ 本用例改为正向断言，并删除配套 xfail"
    )
    import inspect

    params = set(inspect.signature(scoring.compute_scores).parameters)
    assert not ({"scenario", "weights", "ideal", "profile"} & params), (
        f"评分层已能按档取权重（{sorted(params)}）⇒ 请重指本用例为「游客档不调用评分层」"
    )

    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    scores = scoring.compute_scores(
        lc["poi"]["categories"], lc["blindspots"], len(lc["blindspots"])
    )
    assert isinstance(scores["total"], float), "评分层今天恒产数值总分，无「未评」表示"


def test_visitor_report_currently_inherits_residential_scoring():
    """**现状记录**：把场景字段塞进报告，装配层照样算出总分与盲区结构。

    这条是"景点体检会输出一份讲菜市场与养老的报告"的机器可读版本 ——
    今天只要给个 center 就能跑，产出物却完全是居住语义。
    """
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    lc["scenario"] = "visitor"
    report = assemble_report(lc, "lc-visitor-inherit", "key:visitor", "输出契约用例")
    body = report["living_circle"]
    assert body.get("scenario") == "visitor", "报告无法携带场景标识"
    assert isinstance(body["scores"]["total"], float), (
        "游客档报告已不再自动出分 ⇒ 本用例须改为断言 `scores is None`"
    )


@pytest.mark.xfail(
    strict=True,
    reason="D1/D9：游客档必须声明输出契约，派生指标（总分/盲区/三要素）显式为 null 而非缺席或 0",
)
def test_visitor_profile_declares_nullable_derived_metrics():
    import importlib

    scenario = importlib.import_module(MODULE)
    visitor = scenario.VISITOR
    emits = set(visitor.emits)
    forbidden = {"scores", "blindspots", "triads", "coverage", "reachability"}
    assert not (emits & forbidden), f"游客档仍声明要出派生指标：{sorted(emits & forbidden)}"
    assert {"category_counts", "nearest_minutes", "isochrones"} <= emits, (
        f"游客档应只声明可举证读数，实得 {sorted(emits)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="D9/U1：游客档报告的 scores / blindspots 必须是 null（值存在、语义为未评）",
)
def test_visitor_report_serialises_scores_as_null():
    import importlib

    scenario = importlib.import_module(MODULE)
    lc = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
    report = assemble_report(lc, "lc-visitor-null", "key:visitor-null", "游客档报告")
    body = report["living_circle"]
    assert body["scenario"] is scenario.VISITOR.key or body["scenario"] == "visitor"
    assert body["scores"] is None, f"scores 必须是 null，实得 {type(body['scores']).__name__}"
    assert body["blindspots"] is None, "盲区判定属居住需求，游客档必须显式未评"
