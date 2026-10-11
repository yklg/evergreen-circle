"""游客档输出契约的**结案**（原附录 G-07，第一片 D1 / D9 / U1，TC-08 后端半）。

本文件今天只做两件事：① 记录"不做游客档"这个决定（见下方决定段）；② 保留两条**按决定为真**的
绿条，说明今天确实产不出"未评"报告 —— 因为根本不存在需要"未评"的那一档。

前端半（`types.ts` 的 `scores | null` 与消费点清单）在
`frontend/src/__tests__/visitorUnrated.test.tsx`；这里守后端半：

* 今天**没有任何一种方式**能产出一份"没打分"的体检报告：`scenario.py` 不存在，
  `scoring.compute_scores` 的入参里也没有场景或权重开关，任何一次组装都会算出一个数值总分。
* 「未评」若被表示成**字段缺席**（`?:`），下游一个 `|| 0` 就把它坐实成"这个景点 0 分";
  若被表示成 `total: 0`，则与真实 0 分不可区分 —— 本仓离线报告的正文层已经这样钉过
  （`livingCircleContract.test.ts` F2 断言 `scores.total === 0`），列表层却存 NULL。
  ⇒ D9 选 `… | null`：值存在、语义是"本档未评"，两端都无法顺手当 0 用。

原判据取自计划 D1 的声明形状（`ScenarioProfile.emits` = 输出契约）；随决定一起撤除。
若将来重开（见重开条件），那两条形状要求仍可作为起点，但**必须先回答"为什么要第二档"**。

## 决定（2026-10-11 拍板）：本仓**不做**游客档

原 D1/D9/U1 那三条红钉已按下述决定撤除，**不再是欠账**。完整结论、依据与重开条件写在
`test_scenario_cache_identity.py` 的文件头（那是本条路线图的结案正本），这里只留与本文件相关的两句：

* 上面那两条**绿条今天依然为真，而且从今往后是"按决定如此"**，不是"还没做"——
  展示层永远不会拿到"未评"的游客档报告，因为不存在游客档。
* 重开条件同正本：赛题/评审要求、真实误读事故、或 `scenario` 真的进了请求体（最后一条有自检钉着）。
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
    """**按决定为真**（不是"还没做"）：组装与评分层都没有"本档不打分"的开关 —— 因为没有第二档。

    要把它读成缺口，先看文件头那条决定与它的重开条件。
    """
    import importlib.util

    assert importlib.util.find_spec(MODULE) is None, (
        f"{MODULE} 已存在 ⇒ 游客档被捡回来了：去 test_scenario_cache_identity.py 的结案处按重开条件办，不要只改这条"
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

