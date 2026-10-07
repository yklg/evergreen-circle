"""T1 · 口径不变量守护（test-coverage-expander 批次 1，回溯 I1/I10）。

守护的是「15 分钟是什么」这件事**只有一个事实源**，以及「画出来的圈确实是那个口径」。
不测几何细节（那是 test_isochrone.py 的职责），只测跨模块的口径一致性。

两条已知 P0 以 xfail(strict=True) 挂账：修好后用例会变 XPASS→失败，强制摘掉标记，
不允许静默转绿。
"""
from __future__ import annotations

import ast
import inspect
import json
import math
import re
import statistics
from pathlib import Path

import pytest

from app.living_circle import blindspot, data_source, field, isochrone, scoring, scope
from app.living_circle.caliber import (
    DEFAULT_CALIBERS,
    ReachCaliber,
    _apply_manifest_caliber,
    get_caliber,
)
from app.living_circle.data_source import CheckParams, OfflineDataSource
from app.living_circle.geo_utils import haversine_m
from app.living_circle.poi_collector import POIBudget
from app.living_circle.isochrone import ISO_MINUTES, MODE_PARAMS, build_sample_points
from app.living_circle.isochrone import hour_to_minutes

WALK_CALIBER = get_caliber("walking")
OFFLINE_DETOUR_K = WALK_CALIBER.detour_k
WALK_SPEED_M_PER_MIN = WALK_CALIBER.speed_m_per_min
REACH_FULL_MIN = WALK_CALIBER.reach_full_min

FIXTURES = Path(isochrone.__file__).parent / "fixtures"
KAILI = json.loads((FIXTURES / "kaili.json").read_text(encoding="utf-8"))
JINSONG = json.loads((FIXTURES / "beijing-jinsong.json").read_text(encoding="utf-8"))

# 政策口径：商务部 2021《城市一刻钟便民生活圈建设意见》「步行约 15 分钟的服务半径」，
# 《城市规划》2022.5 实测步行 15min ≈ 0.8–1.2km。
POLICY_WALK_15MIN_M = (800.0, 1200.0)


def _offline_report(center=(107.9758, 26.5734), name="凯里老街"):
    import asyncio

    ds = OfflineDataSource()
    return asyncio.run(ds.compute(CheckParams(scene_name=name, city="", address="", center=center)))


def _ring(report, minutes):
    z = next(z for z in report["isochrones"] if z["minutes"] == minutes)
    return z["geojson"]["coordinates"][0]


def _radial_stats(report, minutes):
    """圈相对自身中心的 (平均半径, 变异系数 CV, 顶点数, 面积)。

    CV = 半径标准差/均值：正圆 CV=0，真实路网等时圈必然 CV>0 —— 「不是画的圆」的量化判据。
    """
    c = tuple(report["scene"]["center"])
    radii = [haversine_m(c, (p[0], p[1])) for p in _ring(report, minutes)]
    mean = statistics.fmean(radii)
    return {
        "r_mean": mean,
        "cv": statistics.pstdev(radii) / mean,
        "vertices": len(radii),
        "area": next(z for z in report["isochrones"] if z["minutes"] == minutes)["area_km2"],
    }


# ── I1 · 速度口径单一源 ────────────────────────────────────────────

def test_speed_constant_derived_from_single_source():
    """口径常量只允许在 caliber.py 定义一次（B5：禁止散落第二份字面量）。"""
    from app.living_circle.caliber import DEFAULT_CALIBERS
    walking = DEFAULT_CALIBERS["walking"]
    assert walking.speed_m_per_min == 80


def test_caliber_constants_are_the_same_object_across_modules():
    """引用而非复制：`is` 断言，防「data_source 里再写一个 75.0」的口径漂移。"""
    assert data_source.get_caliber("walking") is isochrone.get_caliber("walking")
    assert inspect.signature(hour_to_minutes).parameters["speed"].default == WALK_SPEED_M_PER_MIN


# ── I1b · 判盲口径常量单一源 ───────────────────────────────────────
# 证据域修复带出的同族缺陷。旧状态：`BLIND_RADIUS_M` 在 `blindspot` 与 `field` 各写一份
# 1000.0，`TRIAD_KEYS` 同样两份。`field.py` 当时的注释给了理由：「`blindspot` 已 import
# 本模块，反向 import 会成环」。环是真的 —— 但**复制口径不是解环的办法**，把常量一起
# 下移到最底层的 `scope`（它不 import 任何判盲模块），两边都 import 它，环与单一源同时成立。

_LC_DIR = Path(inspect.getfile(scope)).parent
_JUDGE_CALIBER_NAMES = ("BLIND_RADIUS_M", "TRIAD_KEYS", "TRIAD_LABEL")


def _defining_modules(name: str, root: Path = _LC_DIR) -> list[str]:
    """`root` 下**以模块级赋值语句定义**了 `name` 的模块名（import 不计）。"""
    hits: list[str] = []
    for py in sorted(root.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in tree.body:  # 只看模块级：函数内的局部同名变量不是口径
            if isinstance(node, ast.AnnAssign):
                targets: list[ast.expr] = [node.target]
            elif isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                hits.append(py.stem)
    return hits


@pytest.mark.parametrize("cname", _JUDGE_CALIBER_NAMES)
def test_blindspot_caliber_constants_have_single_definition(cname):
    """判盲口径常量只允许在 `scope.py` 定义一次（B5 原则从速度口径扩到判定半径与必达要素）。"""
    defs = _defining_modules(cname)
    assert defs == ["scope"], f"{cname} 必须在且只在 scope.py 定义，实际定义于 {defs}"


def test_single_definition_guard_actually_catches_a_copy(tmp_path):
    """负对照：本守护**不是永真断言** —— 造一份复制品，它必须立刻变红。

    「防复发」用例最常见的失效方式是写成一棵永远绿的树（判据取错了目录、或只匹配
    `import` 不匹配赋值）。这里直接喂给它一个含两份定义的假目录来证明判据有效。
    """
    (tmp_path / "scope.py").write_text("BLIND_RADIUS_M = 1000.0\n", encoding="utf-8")
    (tmp_path / "field.py").write_text("BLIND_RADIUS_M = 1000.0\n", encoding="utf-8")
    (tmp_path / "blindspot.py").write_text(
        "from app.living_circle.scope import BLIND_RADIUS_M\n\n"
        "def f():\n    BLIND_RADIUS_M = 5.0  # 函数内局部变量，不算口径\n    return BLIND_RADIUS_M\n",
        encoding="utf-8",
    )
    assert _defining_modules("BLIND_RADIUS_M", tmp_path) == ["field", "scope"]
    # 真实代码库必须仍然只有一处 —— 否则上面那条参数化用例与本条会一起红
    assert _defining_modules("BLIND_RADIUS_M") == ["scope"]


def test_blindspot_and_field_share_the_same_caliber_objects():
    """消费方拿到的是**同一个对象**，不是等值的第二份 —— 登记表加一类必达要素时无需两处同改。"""
    assert blindspot.TRIAD_KEYS is field.TRIAD_KEYS is scope.TRIAD_KEYS
    assert blindspot.TRIAD_LABEL is scope.TRIAD_LABEL
    assert list(scope.TRIAD_LABEL) == list(scope.TRIAD_KEYS)  # 键集合与登记表同源（test_field 契约）
    assert blindspot.BLIND_RADIUS_M == field.BLIND_RADIUS_M == scope.BLIND_RADIUS_M == 1000.0


def test_judge_radius_is_a_relation_owned_by_scope():
    """可判定半径必须是 `SpatialScope` 的关系（构造即校验），不得回流到消费方。

    旧实现是 `blindspot.judge_radius_m(scope, ...)` —— 判定公式住在消费方，任何新判定
    都得自己抄一遍，抄错没有任何一层能发现（`judge_radius_m` 的量级问题因此被「暂缓」了一轮）。
    """
    assert not hasattr(blindspot, "judge_radius_m"), "判定半径公式不得退回 blindspot"
    assert callable(scope.SpatialScope.judge_radius_m)
    s = scope.SpatialScope(
        travel_mode="walking", reach_min=20.0, reach_ring=(), reach_circumradius_m=1367.2,
        collect_radius_m=1367.2, study_radius_m=2500.0,
    )
    assert s.judge_radius_m() == pytest.approx(367.2)          # D2 现状：外接圆 − 1km
    assert s.judge_radius_m(500.0) == pytest.approx(867.2)     # 半径随证据需求走，非硬编码


def test_rev2_evidence_keys_are_both_indexed_and_real():
    """rev2 新口径键必须**两边都落**：进口径索引 + 真在产出里。

    - 不进索引 ⇒ 专家卡无法引用，prose 里提到「实测证据边界半径」会被词表闸判成编造指标
      （项目记忆「阶段 4：机制就绪但绑定仅 1/48；词表闸捕虚构指标」正是这个坑）；
    - 只登记不核对 ⇒ ref 名字写错照样「存在」，渲染出空值却无人报警。
    """
    from app.living_circle import caliber_index

    rev2_refs = (
        "scope::SCOPE_POLICY_VERSION",
        "scoring::BLINDSPOT_PENALTY_PER_EXTRA", "scoring::JUDGE_SHARE_FLOOR",
        "report::cells_inside", "report::cells_judged", "report::cells_unknown",
        # 第三态（片 1a 补登记）：不放进这份白名单就是「登记了没人验」——
        # 下面的产出核对是按**末段键名**匹配的，浅到放进嵌套支也照样绿。
        "report::cells_unjudgeable_by_cap",
        "report::evidence_margin_m", "report::evidence_radius_m",
        "report::evidence_frontier_m", "report::evidence_complete",
        "report::judge_radius_m", "report::scope_policy_version",
        # 第二十一轮评审 **P0-1**：评分口径那把键登记进了名册，却没进这份白名单 ⇒
        # 下面那段"ref 指向的键必须真在产出对象里"的核对**只遍历白名单**，于是"登记了没人验"。
        # 放进来的效果：拿 `s.payload(...)` 这份**生产产出**去验 `coverage_caliber_version` 确实在里面
        # —— 删掉 `scope.py` 那行发射会当场红，而不是"2296 条全绿、每份新报告被自家门拒"。
        "report::coverage_caliber_version",
        # 第三根轴（笔 3-B `rc-1`）：与上面那把一样是**发射在 caliber 里**的版本声明，
        # 所以进这份按 caliber 产出核对的白名单；它的**读数块** `sampling.detour` 不在这儿
        # （发在 sampling 段，核对走真生产者 ⇒ 见 `tests/test_reach_calibration.py`）。
        # 删掉 `scope.py` 那行发射 ⇒ 本条当场红，而不是"全绿但每份新报告没人能引用这个口径"。
        "report::reach_caliber_version",
        # 第四根轴（笔九 S20 · `sh-1`）：与上面几把同为**发射在 caliber 里**的版本声明 ⇒ 进这份
        # 按 caliber 产出核对的白名单。只登名册不进这里，就是第二十一轮 P0-1 点名的"登记了没人验"
        # —— 删掉 `scope.py` 那行发射时 0 条报警，而每份新报告都会被自家 B17 之外的大门静默放过。
        # 它的另一半键集 `isochrones[*].shape` **不在这里**（发在等时圈段，核对走真生产者）。
        "report::shape_caliber_version",
        "report::confidence", "report::evidence",
        # 片 4：取证回合账目。放进这份名单才有意义 —— 名册登记与产出核对是两条腿，
        # 少前者是"引用不到"，少后者是"登记了个不存在的键"。
        "report::forensic",
        # R23-I · 成本账那一位同样必须两条腿都站住：只进口径名册而不进这份白名单，
        # 就是第二十一轮 P0-1 点名的"登记了没人验"（删掉发射行时 0 条报警）。
        # ⚠️ 它是**条件发射**的键（`scope.payload()` 只在采集明细带着 `pages_returned` 时才出），
        # 所以下面那份 detail 必须带上这一位 —— 这里验的是"发射行还在不在"，
        # 值对不对（逐词行求和、缺明细时不发）由 `tests/test_pages_returned.py` 走真链核。
        "report::evidence_pages_returned",
    )
    missing = sorted(set(rev2_refs) - set(caliber_index.all_refs()))
    assert not missing, f"rev2 口径键未登记进 caliber_index：{missing}"

    # ref 的 value 里写的嵌套路径必须真在产出对象里（防「登记了却拼错」）
    s = scope.SpatialScope(
        travel_mode="walking", reach_min=20.0,
        reach_ring=((107.97, 26.57), (107.98, 26.57), (107.98, 26.58), (107.97, 26.58)),
        reach_circumradius_m=1367.2, collect_radius_m=1367.2 + WALK_CALIBER.blind_radius_m,
        study_radius_m=2500.0,
    ).with_evidence(
        {"market": 2367.2, "pharmacy": 1800.0, "primary": 2367.2},
        # `pages_returned` 在这里给值，只为让下面那圈逐键核对拿到条件发射的载荷
        # （发射点在 `scope.payload()` 里那个 `if "pages_returned" in …`）；它的取值对不对
        # 不在本用例职责内 —— 见 `tests/test_pages_returned.py`。
        complete=False,
        detail={"truncated_terms": ["药店"], "starved_terms": [], "pages_returned": 2},
    )
    # 三态必须闭合：97 = 已判 5 + 无据 90 + 接口封顶 2（这条算式在此不是为了测 payload，
    # 是为了让上面那份逐键核对拿到**真出过数**的载荷，而不是一个恰好有键的样板）
    payload = s.payload(WALK_CALIBER, {"cells_inside": 97, "cells_judged": 5,
                                      "cells_unknown": 90, "cells_unjudgeable_by_cap": 2,
                                      "cells_blind": 2},
                        # 取证账目由**真生产者**造（空记录 = 一次没派的形状），不在测试里手抄
                        # 一份字段表 —— 手抄的那份只会验"我写的键在我抄的表里"（恒真）。
                        forensic=data_source.forensic_block(
                            [], max_rounds=data_source.MAX_FORENSIC_ROUNDS,
                            pool=POIBudget(total=0)))
    produced_scores = scoring.compute_scores([], [], 0, judged_share=5 / 97, evidence_complete=False)

    for ref in rev2_refs:
        if not ref.startswith("report::"):
            continue
        value = caliber_index.view(ref).value
        key = value.rsplit(".", 1)[1]
        host = payload if ".caliber." in value else produced_scores
        assert key in host, f"{ref} 指向 {value!r}，但产出对象里没有 {key!r} —— 登记与实现漂移"

    # 采集留边的举证路径（片 1b 第二段：解绑后它是**导出量**，不再是模块常量）：
    # 参数侧指回口径对象，产物侧指回 payload 键（上面那份逐键核对已经验过它在 payload 里）。
    # ⚠️ 这里不许改回 `view("scope::EVIDENCE_MARGIN_M").value == str(...)`：那条钉的是
    # 「常量值 == walking 快照」，值相等就绿，正是第十二轮复审 P0-3 点名的假闸。
    assert caliber_index.view("scope::EVIDENCE_MARGIN_M") is None, (
        "`scope::EVIDENCE_MARGIN_M` 又登记回来了 —— 留边在构造时现算，"
        "名册里留一个指向 import 期 walking 快照的 ref，就是替一个不该存在的第二住所背书"
    )
    assert caliber_index.view("caliber::walking.blind_radius_m") is not None, (
        "判定半径的住所没有可引用的 ref ⇒ 专家卡与词表闸拿不到唯一事实源"
    )


def _probe_index_with_missing_symbol():
    """子进程里删掉已登记符号再重建索引，回传「本来有没有 / 抛了什么错 / 旧索引还在不在」。

    必须走子进程：`caliber_index._INDEX` 是**进程级全局**，在主进程里 delattr + 重建会
    污染后续用例（本仓「还原全局注册表」的老坑）。
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    import app as _app_pkg

    backend = Path(_app_pkg.__file__).parent.parent
    code = (
        "import json\n"
        "from app.living_circle import caliber_index, scope\n"
        "REF = 'scope::SCOPE_POLICY_VERSION'\n"
        "had = caliber_index.view(REF) is not None\n"
        "value_before = getattr(caliber_index.view(REF), 'value', None)\n"
        "n_before = len(caliber_index.all_refs())\n"
        "err = None\n"
        "try:\n"
        "    del scope.SCOPE_POLICY_VERSION\n"
        "    caliber_index._build_index()\n"
        "except Exception as e:\n"
        "    err = type(e).__name__\n"
        "view = caliber_index.view(REF)\n"
        "print(json.dumps({'had': had, 'err': err, 'kept': view is not None,\n"
        "                  'value_before': value_before,\n"
        "                  'value_after': getattr(view, 'value', None),\n"
        "                  'n_before': n_before, 'n_after': len(caliber_index.all_refs())}))\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=str(backend), capture_output=True, text=True
    )
    assert res.returncode == 0, f"探针子进程失败：{res.stderr[-400:]}"
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_missing_registered_symbol_raises_on_rebuild():
    """阶段 0 转正（原 `xfail(strict)` 挂账）：名册登记的符号缺失必须**报错**。

    旧写法 `getattr(mod, name, None)` + 「非 None 才登记」把改名/删除吞成「什么都没发生」。
    计划 v4 还要往名册里加 `cells_unjudgeable_by_cap`/`evidence_anchors`/`comparable_key`
    三个键 —— 拼错符号名时拿到的必须是红，不是无声。
    """
    probe = _probe_index_with_missing_symbol()
    assert probe["had"] is True, "前置不成立：ref 本来就不在索引里，本用例会空过"
    assert probe["err"] == "AttributeError", (
        f"缺失符号得到的是 {probe['err']!r}，不是 AttributeError ⇒ 静默跳过又回来了"
    )


def test_failed_rebuild_rolls_back_to_the_previous_index():
    """**现状记录**（阶段 0 新行为的接缝）：构建失败时旧索引整表留着，不留半张。

    堵的是修①时容易顺手引入的修②坑：把 `_build_index` 改成「先 `_INDEX.clear()` 再逐条填」，
    一旦填充中途抛错，进程里就剩半张甚至空索引 —— 下游 `view()` 全部静默返回 None，
    比原来的僵尸 ref 更难查。现在的实现是「建到新表、成功才换出、异常回滚」，
    所以 ref 条数与取值必须逐字不变。本用例转红 = 有人把换出/回滚改成了就地清空。
    """
    probe = _probe_index_with_missing_symbol()
    assert probe["err"] == "AttributeError", "前置不成立：没报错就谈不上回滚"
    assert probe["n_after"] == probe["n_before"] > 0, (
        f"失败的重建把索引改成了 {probe['n_after']} 条（原 {probe['n_before']}）"
        f"⇒ 半张/空索引会让下游 view() 静默返回 None"
    )
    assert probe["kept"] is True and probe["value_after"] == probe["value_before"], (
        "ref 消失或取值变了 ⇒ 不再是整表换出，回到就地清空的写法了"
    )


def test_scoring_reach_threshold_is_tied_to_outermost_iso_ring():
    """可达性满分阈值必须等于最外圈分钟数（否则「满分」与圈层族口径脱钩）。"""
    assert scoring.REACH_FULL_MIN == ISO_MINUTES[-1]


def test_offline_note_text_matches_code_constants():
    """scores.note 是对外举证文本：必须与代码常量逐字相同，不得手写数字。"""
    note = _offline_report()["scores"]["note"]
    assert f"{WALK_SPEED_M_PER_MIN} m/min" in note
    assert f"绕行系数 {OFFLINE_DETOUR_K}" in note


# ── I1 · 离线口径反算落政策区间 ────────────────────────────────────

def test_offline_15min_radius_lands_in_policy_band():
    """速度 × 15min ÷ 绕行系数 = 直线服务半径，须落 0.8–1.2km（政策 + 文献量级）。"""
    r = ISO_MINUTES[2] * WALK_SPEED_M_PER_MIN / OFFLINE_DETOUR_K
    assert POLICY_WALK_15MIN_M[0] <= r <= POLICY_WALK_15MIN_M[1], f"15min 直线半径 {r:.0f}m 出政策口径"


def test_offline_rendered_15min_ring_matches_declared_model():
    """渲染出的 15min 圈平均半径必须≈口径反算值（文本说的和图上画的同源）。"""
    report = _offline_report()
    declared = ISO_MINUTES[2] * WALK_SPEED_M_PER_MIN / OFFLINE_DETOUR_K
    got = _radial_stats(report, 15)["r_mean"]
    assert abs(got - declared) / declared < 0.05, f"图上 {got:.0f}m vs 口径 {declared:.0f}m"


# ── I10 · 圈层真实性（正圆判据 / 跨城独立性）────────────────────────

@pytest.mark.parametrize("report", [KAILI, JINSONG], ids=["kaili", "jinsong"])
def test_live_rings_are_not_perfect_circles(report):
    """真实路网等时圈必须不规则：CV>0（正圆 = 算法退化为画圆）。"""
    for m in ISO_MINUTES:
        assert _radial_stats(report, m)["cv"] > 0.01, f"{m}min 圈 CV 过小，疑似正圆兜底"


@pytest.mark.parametrize("minutes", [10, 15, 20])
def test_live_rings_differ_between_cities(minutes):
    """两城同分钟圈应显著不同（路网结构不同）；10/15/20min 圈成立。"""
    a = _radial_stats(KAILI, minutes)
    b = _radial_stats(JINSONG, minutes)
    assert abs(a["r_mean"] - b["r_mean"]) / a["r_mean"] > 0.01
    assert abs(a["area"] - b["area"]) / a["area"] > 0.01


def test_innermost_live_ring_is_city_dependent():
    """不变量（原挂账项转正）：5min 圈形状必须由路网决定 → 两城不可能一致。

    历史：本用例曾以 `xfail(strict=True)` 挂账，因为旧快照里两城 5min 圈**逐点同形**
    （面积完全相同、r_mean 相对差 <1e-4、顶点数一致）——那是 B8「最内圈采样点坍缩」
    的症状。2026-09-20 以真实 AK 重跑 `scripts/snapshot_live.py` 后症状消失
    （新快照为 standard 档，5min 圈 r_mean 126.2m vs 107.2m，相对差 15%，面积差 25%），
    故摘掉 xfail 标记，改为硬不变量。

    ⚠️ B8 本体（`fine_band` 未透传 ⇒ 格距 > 最内圈半径/4）**仍未修复**，
    由 `test_grid_resolution_invariant_is_violated_at_innermost_ring` 继续量化跟踪；
    换回粗采样档（quick）时本不变量仍可能被打破 —— 这正是需要盯住的地方。
    """
    a = _radial_stats(KAILI, 5)
    b = _radial_stats(JINSONG, 5)
    assert abs(a["r_mean"] - b["r_mean"]) / a["r_mean"] > 0.01


def test_grid_resolution_invariant_is_violated_at_innermost_ring():
    """**记录当前行为** + 量化 B8 判据：格距与最内圈半径的比值。

    期望 `step ≤ 最内圈半径/4`；实际 356.7m vs 138.6m → 比值 0.23（最内圈内仅 1 个采样点），
    等值线只能由插值格（83.3m）凭空生成 —— 这就是两城 5min 圈同形的根因。
    """
    center = tuple(KAILI["scene"]["center"])
    inner_r = _radial_stats(KAILI, 5)["r_mean"]
    step = min(
        d for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, MODE_PARAMS["standard"]["coarse"], MODE_PARAMS["standard"]["fine"])) if d > 1.0
    )
    inside = sum(1 for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, 400, 150)) if d <= inner_r)
    assert inside == 1  # 仅中心点
    assert step > inner_r / 4  # 违反分辨率不变量（期望 <，见上方 xfail 用例）


@pytest.mark.xfail(strict=True, reason="P0（B8）：分辨率不变量未落地，caliber.py 落地后改为断言成立")
def test_grid_resolution_invariant_should_hold():
    TODO = "见 plan/graceful-fjord-swan.md R8/B8：格距须 ≤ 最内圈半径/4"
    center = tuple(KAILI["scene"]["center"])
    inner_r = _radial_stats(KAILI, 5)["r_mean"]
    step = min(
        d for d in (haversine_m(center, p) for p in build_sample_points(center, 2500, 400, 150)) if d > 1.0
    )
    assert step <= inner_r / 4, TODO


# ── 死参数：IsochroneEngine(walk_speed=…) 不参与任何计算 ───────────

def test_injected_walk_speed_is_currently_inert():
    """**记录当前行为**：构造参数存到了 self.walk_speed，但 compute 全程不读它。

    口径来自调用方注入的 meter_fn，所以引擎层「配了但不用」= 假的可配置性。
    阶段 1 R5/R7 落地后本用例应转红（改为断言注入生效）。
    """
    import asyncio

    async def radial(pts):
        return [haversine_m((107.9758, 26.5734), p) / WALK_SPEED_M_PER_MIN for p in pts]

    slow = asyncio.run(isochrone.IsochroneEngine(walk_speed=15.0).compute((107.9758, 26.5734), radial, study_radius_m=2500, mode="quick"))
    fast = asyncio.run(isochrone.IsochroneEngine(walk_speed=150.0).compute((107.9758, 26.5734), radial, study_radius_m=2500, mode="quick"))
    assert [z["area_km2"] for z in slow["isochrones"]] == [z["area_km2"] for z in fast["isochrones"]]


@pytest.mark.xfail(strict=True, reason="R5/R7：walk_speed 为死参数，口径重构后须真正生效")
def test_injected_walk_speed_should_take_effect():
    import asyncio

    center = (107.9758, 26.5734)

    def radial(speed):
        async def m(pts):
            return [haversine_m(center, p) / speed for p in pts]
        return m

    slow = asyncio.run(isochrone.IsochroneEngine(walk_speed=37.5).compute(center, radial(75.0), study_radius_m=2500, mode="quick"))
    fast = asyncio.run(isochrone.IsochroneEngine(walk_speed=150.0).compute(center, radial(75.0), study_radius_m=2500, mode="quick"))
    assert slow["isochrones"][0]["area_km2"] != fast["isochrones"][0]["area_km2"]


# ── 生活圈片 1b · 半径的住所搬到口径对象之后的两处静默前置 ──────────────

def test_blind_radius_lives_in_the_caliber_and_survives_manifest_rebuild():
    """判定半径的**住所**是 `ReachCaliber.blind_radius_m`，且必须活得过 manifest 重建。

    为什么单独钉这条（第十二轮 P0-6 / 第十四轮 P1-1）：`_apply_manifest_caliber` 是
    **逐字段手抄重建**（那份清单列了 9 个字段名）。漏抄一行不会报错，只会把该字段打回
    dataclass 默认值 —— 而默认值恰好等于原值 ⇒ "分档"静默失效、全量一字不差。
    所以判据必须用一个**非 1000** 的值。monkeypatch 走不通（`ReachCaliber` 是 frozen，
    且 manifest 只在 import 期应用一次），只能手造实例直调那个重建函数。
    """
    probe = ReachCaliber(
        travel_mode="probe", speed_m_per_min=80.0, detour_k=1.3,
        study_radius_m=2500, blind_radius_m=800.0,
    )
    rebuilt = _apply_manifest_caliber(probe, {"chunk": 25})
    assert rebuilt.blind_radius_m == 800.0, (
        "manifest 重建把判定半径打回了默认值 ⇒ 新字段没进那份逐字段手抄的清单，"
        "分档会在没人报错的情况下失效"
    )

    # 住所只有一处：兼容名必须仍等于 walking 档的登记值（它不许变成第二个数）
    assert scope.BLIND_RADIUS_M == get_caliber("walking").blind_radius_m
    assert scope.resolve_blind_radius_m("walking") == get_caliber("walking").blind_radius_m
    # 今天三档同值是**现状**不是省略：分档属于阶段 3-5 的政策决定（计划 v6.9 ①）
    assert {m: c.blind_radius_m for m, c in DEFAULT_CALIBERS.items()} == {
        "walking": 1000.0, "riding": 1000.0, "driving": 1000.0,
    }
    # 显式覆盖必须原样用，不许被口径盖掉
    assert scope.blind_radius_or(800.0, "walking") == 800.0

    # 收紧（批 A①）：回落哪一档必须由调用方**点名**。这两个 helper 的 `travel_mode` 不许
    # 再带默认值 —— 默认值存在 = 省略实参的调用静默按步行档算（分档日无人报警）；改成必填后，
    # 漏传在第一次调用就 TypeError，那四个拿不到 mode 的站点（`EvidenceDisc`/`is_cap_bound`/
    # `BlindnessField`/`LatticeAnchors`）则在代码里显式写着 "walking"，债看得见。
    for helper in (scope.resolve_blind_radius_m, scope.blind_radius_or):
        param = inspect.signature(helper).parameters["travel_mode"]
        assert param.default is inspect.Parameter.empty, (
            f"{helper.__name__}.travel_mode 又带回默认值了 ⇒ 纯几何值对象的省略路径重新变成"
            "没人点名的步行档回落"
        )


def test_blind_radius_is_indexed_as_a_caliber_param():
    """新字段必须**进口径名册**：不登记 ⇒ 专家卡引用不到，prose 里提到就撞词表闸。

    这正是项目记忆里「机制就绪但绑定仅 1/48」那一坑（阶段 4）⇒ 登记与取值、label 一起核。
    """
    from app.living_circle import caliber_index

    ref = "caliber::walking.blind_radius_m"
    assert ref in caliber_index.all_refs(), f"{ref} 未登记 ⇒ 名册缺一支"
    view = caliber_index.view(ref)
    assert view.value == "1000.0", view.value
    assert view.label == "盲区判定半径", (
        f"label 兜底成了裸英文名（{view.label}）⇒ 上屏会露一个没人认识的键（第十四轮 P2）"
    )
