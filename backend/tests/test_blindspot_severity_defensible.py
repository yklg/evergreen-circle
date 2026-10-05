"""C · 盲区严重度与补点优先级**只许用可辩护量**，人口永远是旁注。

为什么需要这道守卫：`blindspot.py:707` 的注释已经写明「严重度/连续缺口指数/补点处方
（纯函数，仅依赖 triad 中心 —— 装配层负责 reach/affected）」，但**注释拦不住人**。
而这一格恰好是最容易被"顺手优化"的地方 —— 学界确实认为引力/2SFCA 那一支更适合定位
薄弱环节（见 `docs` 引用的北大综述），但那条路的**前提是可信需求规模**，而本仓的
`assemble._affected_for` 自标 `provenance:"proxy"`、`note` 明写"非真实人口数据"
（按 `DEMAND_DENSITY_HH_KM2` 规划基准估算）。把这样一个数接进严重度，评审一句
"这人数哪来的"就能把整份盲区清单的优先级问倒。

所以这里不实现"换排序量"（现状已经是可辩护量），而是**钉住它不许被换掉**。
"""
from __future__ import annotations

import inspect

import pytest

from app.living_circle import blindspot
from app.living_circle.assemble import _affected_for
from app.living_circle.scope import BLIND_RADIUS_M

# 排序/严重度链上的全部函数 —— 少列一个就是留一个缺口
SEVERITY_PATH = (
    "_excess_farness", "_gap_score", "_severity_of", "_strategy_for",
    "_cluster_served", "_assign_priorities",
)
POPULATION_TOKENS = ("affected", "estimated_residents", "estimated_households", "DEMAND_DENSITY", "HH_SIZE")


@pytest.mark.parametrize("fn", SEVERITY_PATH)
def test_severity_path_never_reads_population(fn):
    src = inspect.getsource(getattr(blindspot, fn))
    hits = [t for t in POPULATION_TOKENS if t in src]
    assert not hits, f"{fn} 读到了人口量 {hits} —— 严重度/优先级只许用几何与距离这些可辩护量"


def test_gap_score_is_pure_and_monotone():
    """`_gap_score(m, farness)` 只吃两个数，且两个方向都单调递增。

    单调性是"可辩护"的一部分：读者要能预判改哪个数会让这一处更严重。
    """
    assert blindspot._gap_score(0, 0.0) == 0.0
    assert blindspot._gap_score(1, 0.0) < blindspot._gap_score(2, 0.0) < blindspot._gap_score(3, 0.0)
    assert blindspot._gap_score(1, 0.0) < blindspot._gap_score(1, 0.5) < blindspot._gap_score(1, 1.0)
    # 归一化：缺失占比按 len(TRIAD_KEYS) 而非硬编码，且整体不越 [0,1]
    assert 0.0 <= blindspot._gap_score(99, 99.0) <= 1.0


def test_severity_is_monotone_in_gap():
    sev = [blindspot._severity_of(g) for g in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    rank = {"light": 0, "medium": 1, "heavy": 2}
    assert all(rank[a] <= rank[b] for a, b in zip(sev, sev[1:])), f"严重度随 gap 非单调：{sev}"


def test_priority_order_ignores_population():
    """补点优先级：故意把人口与 gap 摆成**反相关**，排序必须照 gap↓/serves↓ 走。

    这是行为层的反证 —— 若哪天有人把 `affected` 接进 `_assign_priorities`，
    这三条的次序会立刻翻掉。
    """
    fixes = [
        {"facility": "小学", "_key_gap": 0.30, "_key_serves": 5,
         "affected": {"estimated_residents": 99999, "provenance": "proxy"}},
        {"facility": "药店", "_key_gap": 0.75, "_key_serves": 2,
         "affected": {"estimated_residents": 12, "provenance": "proxy"}},
        {"facility": "菜市场", "_key_gap": 0.75, "_key_serves": 9,
         "affected": {"estimated_residents": 30, "provenance": "proxy"}},
    ]
    blindspot._assign_priorities(fixes)
    order = [f["facility"] for f in sorted(fixes, key=lambda x: x["priority"])]
    assert order == ["菜市场", "药店", "小学"], f"优先级被非几何量影响了：{order}"
    assert all("_key_gap" not in f and "_key_serves" not in f for f in fixes), "私有排序键泄漏到产物"


def test_affected_stays_declared_as_proxy():
    """人口那一格的**自证**不许被摘掉 —— 它是"只展示、不进判定"的唯一可见凭据。

    摘掉 `provenance:"proxy"` 或改掉"非真实人口数据"那句，就等于把估算值伪装成实测值，
    下一次接进排序时不会再有任何东西报警。
    """
    ring = [(107.9658, 26.5634), (107.9858, 26.5634),
            (107.9858, 26.5834), (107.9658, 26.5834), (107.9658, 26.5634)]
    pts = [{"lng": 107.9758, "lat": 26.5734, "minutes": 3.0, "timed": True, "in_reach": True}]
    got = _affected_for(ring, (107.9758, 26.5734), pts)
    assert got is not None, "受影响人口估算整格消失 —— 盲区清单的规模感无处交代"
    assert got["provenance"] == "proxy", f"自证被摘：{got['provenance']}"
    assert "非真实人口数据" in got["note"], f"note 不再声明是估算：{got['note']}"
    assert got["estimated_residents"] > 0


def test_blind_radius_is_the_declared_1km_ruler():
    """顺带钉住判盲半径确实是 1000m 那把尺（`blocked_by_geometry` 的措辞依赖它）。"""
    assert BLIND_RADIUS_M == pytest.approx(1000.0)
