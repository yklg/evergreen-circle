"""实测场的**形态**（IDW 幂次 p 与近邻数 k）从函数体字面量升为可举证口径（笔 4a 后续）。

起因是 4a 那一条被关掉的待确认：`sampling.interpolation` 一直只说方法名，而"这个场到底
怎么插出来的"躲在 `idw_from_local` 的一个 `p = 2.0` 字面量和默认形参 `k=8` 里 ——
拿到载荷的人只能信、不能复算，正是 P1 那条根因（量的出处没做成一等公民）的形状。
按凯里/劲松两份实跑快照量过：p 从 2 改 1 或 3、k 从 8 改 4/16 ⇒ 圈内格平均绝对差
0.24–0.44min、最坏单格 17.1min、12–18 个圈内格跨过 20min 满分线 —— 与残差信号
（−1.9…+4.3min）同量级，所以它是口径，不是实现细节。

判据分四组，各自挡的是不同的复发形状：
① **产出侧**：发射口真的把两键发进 `sampling`，而且那两个数**真的在决定算法**
   （只钉字面值＝注释硬，钉"改常量 ⇒ 场跟着变"才是单一事实源）。
② **契约 B15**：半份声明、非 IDW 却带 IDW 参数、值非法，四类各一；**两半皆缺必须合法**
   （否则这条一上线就把三十来份存量报告从历史列表里抹掉 —— 那是 B14 撞过的同一格）。
③ **诚实性**：离线链随 `detour` 一起摘键（行为 + 结构各钉一条，行为只能证明今天摘了，
   结构才证明以后搬不走）。
④ **消费与登记**：名册两条 ref 指向的键名必须**等于**发射口给出的键名（两处各写一遍就会漂），
   结论章那句真的把两个数说出来，且**缺键就不印**。
"""
import asyncio
from typing import Any, Dict

import pytest

from app.core.pipeline.diagnosis_templates import _origin_note
from app.living_circle import caliber_index
from app.living_circle import isochrone as iso_mod
from app.living_circle.isochrone import (
    IDW_NEIGHBORS,
    IDW_POWER,
    IsochroneEngine,
    has_interpolation_form,
    idw_from_local,
    interpolation_form_keys,
)
from app.living_circle.report_contract import (
    _interpolation_form_violations,
    assess_geometry,
)

CENTER = (107.9758, 26.5734)
SPEED = 80.0


async def _radial_meter(pts):
    """规则场：每点按局部距离给一个已知分钟数（`compute` 的 `meter_fn` 是被 await 的）。"""
    out = []
    for i, p in enumerate(pts):
        d = ((p[0] - CENTER[0]) * 60000.0) ** 2 + ((p[1] - CENTER[1]) * 60000.0) ** 2
        out.append(round(d ** 0.5 / SPEED, 1) if i % 97 else None)
    return out


def _lc(sampling_extra: Dict[str, Any], method: str = "idw") -> Dict[str, Any]:
    """一份只装 `sampling` 的最小载荷（B15 只看这一段的自洽）。"""
    sp: Dict[str, Any] = {"interpolation": method, "points": [], "timed_count": 1}
    sp.update(sampling_extra)
    return {"data_origin": "live", "sampling": sp, "caliber": {}}


# ── ① 产出侧 ────────────────────────────────────────────────

def test_compute_declares_both_form_keys_with_the_constants():
    """引擎造出的场必须把 p、k 一起发进 `sampling`，值取自模块常量。"""
    iso = asyncio.run(IsochroneEngine().compute(
        CENTER, _radial_meter, study_radius_m=2500, mode="quick"))
    sp = iso["sampling"]
    assert sp["interpolation"] == "idw"
    assert has_interpolation_form(sp), f"发了 idw 却没发场形态：{sorted(sp)}"
    assert sp["interpolation_power"] == IDW_POWER
    assert sp["interpolation_neighbors"] == IDW_NEIGHBORS
    assert interpolation_form_keys() == {"interpolation_power": sp["interpolation_power"],
                                        "interpolation_neighbors": sp["interpolation_neighbors"]}
    # 引擎自己产出的这份，必须过得了同一条契约（否则产出侧与契约侧各说一套）
    assert _interpolation_form_violations({"data_origin": "live", "sampling": sp,
                                          "caliber": {}}) == []


def test_the_constants_actually_drive_the_math():
    """**单一事实源的行为版**：改常量 ⇒ 场跟着变。

    只断言"sampling 里的数等于常量"是够的但偏软：那种写法在 `p` 仍被硬编码进函数体时
    照样绿（发射口抄了一份，算式里是另一份）。这里直接 monkeypatch 两个常量再算场，
    红在"抄了两份"那一格。
    """
    sample = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0), (50.0, 50.0)]
    minutes = [10.0, 20.0, 30.0, 40.0, 50.0]
    grid = [(0.0, 0.0), (70.0, 30.0)]
    import numpy as np
    s, g = np.array(sample), np.array(grid)

    base = idw_from_local(s, minutes, g)
    monkey_p = idw_from_local(s, minutes, g)  # 同参数复跑：必须逐位一致（可复算性本身）
    assert list(base) == list(monkey_p)

    original_power, original_k = iso_mod.IDW_POWER, iso_mod.IDW_NEIGHBORS
    try:
        iso_mod.IDW_POWER = 1.0
        assert list(idw_from_local(s, minutes, g)) != list(base), "幂次改了场却不动 ⇒ 算式另有出处"
        iso_mod.IDW_POWER = original_power
        iso_mod.IDW_NEIGHBORS = 2
        assert list(idw_from_local(s, minutes, g)) != list(base), \
            "改了 IDW_NEIGHBORS、不传 k 的调用却不动 ⇒ 近邻数被烤进了签名或算式"
    finally:
        iso_mod.IDW_POWER, iso_mod.IDW_NEIGHBORS = original_power, original_k
    assert list(idw_from_local(s, minutes, g)) == list(base), "还原后必须回到原场"


def test_default_neighbour_count_is_resolved_at_call_time():
    """不传 `k` 时用的必须是 `IDW_NEIGHBORS` **当下那个值** —— 默认值不许烤进签名。

    这条是被自己的判据逼出来的：我先前写的是 `idw_from_local.__defaults__[0] == IDW_NEIGHBORS`，
    那是**值比较**，把签名里的常量名换成字面量 8 照样绿（等于什么都没钉）。现在生产侧
    默认值改成 `None` + 运行时解析，这里就能量出"改常量 ⇒ 不传参的调用也跟着变"。
    """
    import numpy as np

    sample = np.array([(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0), (50.0, 50.0)])
    minutes = [10.0, 20.0, 30.0, 40.0, 50.0]
    grid = np.array([(0.0, 0.0), (70.0, 30.0)])
    original = iso_mod.IDW_NEIGHBORS
    try:
        iso_mod.IDW_NEIGHBORS = 2
        assert list(idw_from_local(sample, minutes, grid)) != \
               list(idw_from_local(sample, minutes, grid, k=original)), \
            "改常量却不影响默认调用 ⇒ 邻域数被烤进了签名，声明与算式从此各活各的"
    finally:
        iso_mod.IDW_NEIGHBORS = original
    assert list(idw_from_local(sample, minutes, grid)) == \
           list(idw_from_local(sample, minutes, grid, k=IDW_NEIGHBORS)), "还原后默认必须等于显式值"


# ── ② 契约 B15 ──────────────────────────────────────────────

def test_absent_form_is_legal_so_existing_reports_stay_visible():
    """两半皆缺＝合法。这条是整个判据的前提。

    把它判成违规，等于让这条口径一上线就把三十来份存量 live 报告从历史列表里抹掉
    （`assess_geometry` 同时挂在读路径上）—— 与 10-05 那次"无条件声明 rc-1 撞上 B14
    把离线件打死"是同一格。缺键的正确形态是**不印**，不是**不可用**。
    """
    assert _interpolation_form_violations(_lc({})) == []
    assert _interpolation_form_violations(_lc({"interpolation": "circular_approx"})) == []


@pytest.mark.parametrize("extra", [
    {"interpolation_power": IDW_POWER},                       # 只发一半
    {"interpolation_neighbors": IDW_NEIGHBORS},               # 只发另一半
])
def test_half_published_form_is_a_violation(extra):
    """只有一半 ⇒ 违规：读者拿到幂次没有近邻数，照样复不出场，而"看起来声明过"更易被误信。"""
    issues = _interpolation_form_violations(_lc(extra))
    assert any("一半" in s for s in issues), issues


def test_non_idw_method_carrying_idw_form_is_a_violation():
    """一份载荷同时说两种造法 ⇒ 必须红（离线链正是靠摘键避免这一格）。"""
    issues = _interpolation_form_violations(_lc(
        {"interpolation_power": 2.0, "interpolation_neighbors": 8}, method="circular_approx"))
    assert any("两种造法" in s for s in issues), issues


@pytest.mark.parametrize("key,bad", [
    ("interpolation_power", 0.0), ("interpolation_power", -1.0),
    ("interpolation_power", float("nan")), ("interpolation_power", float("inf")),
    ("interpolation_power", "two"),
    ("interpolation_neighbors", 0), ("interpolation_neighbors", -3),
    ("interpolation_neighbors", 2.5), ("interpolation_neighbors", True),
])
def test_illegal_form_values_are_rejected(key, bad):
    """值非法四类各一：`p ≤ 0`/非有限/非数、`k < 1`/非整数/布尔。

    `1/d^0` 是常数权重、`k=0` 是空加权 —— 两者都会**静默**产出无意义的场，
    而 `True` 是 `isinstance(True, int)` 为真的那一格，不挡就会当成"1 个近邻"放行。
    """
    other = {"interpolation_power": 2.0, "interpolation_neighbors": 8}
    other[key] = bad
    issues = _interpolation_form_violations(_lc(other))
    assert issues, f"{key}={bad!r} 被判成合法载荷"


def test_valid_form_adds_nothing_to_the_geometry_verdict():
    """合规声明不该给一份本来能展示的载荷**新增**违规（判据只罚不自洽，不罚"多说了"）。"""
    bare = _lc({})
    declared = _lc({"interpolation_power": 2.0, "interpolation_neighbors": 8})
    assert _interpolation_form_violations(declared) == []
    assert len(assess_geometry(declared).violations) == len(assess_geometry(bare).violations)


# ── ③ 诚实性：离线链 ────────────────────────────────────────

def test_offline_strips_the_form_keys_too():
    """离线件把 `interpolation` 改口成 `circular_approx`，就必须同时摘掉 IDW 的 p、k。"""
    from app.living_circle.data_source import CheckParams, OfflineDataSource

    rep = asyncio.run(OfflineDataSource().compute(
        CheckParams(scene_name="凯里老街", center=(107.9758, 26.5734))))
    sp = rep["sampling"]
    assert sp["interpolation"] == "circular_approx"
    assert not has_interpolation_form(sp), "离线继承了 IDW 形态参数 ⇒ 载荷同时说了两种造法"
    for key in interpolation_form_keys():
        assert key not in sp, key
    assert _interpolation_form_violations(rep) == []
    assert rep["data_origin"] == "offline" and sp["points"] and "timed_count" in sp


def test_offline_strip_lives_at_the_rewrite_site():
    """结构判据：摘键必须写在 `interpolation` 改口那一句之前（搬走就红）。

    行为用例只能证明"今天这份离线件里没有"；把 `sampling.update({...circular_approx})`
    挪到摘键之前，或把摘键换成只摘 `detour`，夹具照样绿、离线件照样自相矛盾。
    """
    import inspect

    from app.living_circle.data_source import OfflineDataSource

    src = inspect.getsource(OfflineDataSource.compute)
    # 锚点取**那句代码本身**，不取 `circular_approx` 这个词（方法 docstring 里也提到它，
    # 拿词当锚点会把"注释在前"当成"改口在前"，判据就在空转）
    i_strip = src.index("interpolation_form_keys")
    i_relabel = src.index('"interpolation": "circular_approx"')
    assert i_strip < i_relabel, "改口在前、摘键在后（或根本没摘）⇒ 中间态是一份两种造法的载荷"
    assert src.index('"detour"') < i_relabel


# ── ④ 登记与消费 ────────────────────────────────────────────

@pytest.mark.parametrize("fname", sorted(interpolation_form_keys()))
def test_every_emitted_key_is_registered_and_points_at_sampling(fname):
    """名册必须登记发射口给出的**每一个**键，且路径落在 `living_circle.sampling.`。

    判据的键名表**取自定义函数**而不是测试里抄一份：抄的那份会漂（本仓的"措辞表/复用门/
    名册"三方对齐吃过同样教训）。不登记 ⇒ 结论章那句提到它时撞词表闸。
    """
    view = caliber_index.view(f"report::{fname}")
    assert view is not None, f"{fname} 发射了却没登记 ⇒ prose 提到就撞词表闸"
    assert view.value == f"living_circle.sampling.{fname}", view.value


def test_prose_prints_the_form_only_when_declared():
    """结论章那句是真消费者：声明了就说出两个数，没声明就**不印**（不替历史件编参数）。"""
    declared = _lc({"interpolation_power": 2.0, "interpolation_neighbors": 8})
    note = _origin_note(declared)
    assert "幂次 2" in note and "8 个最近实测点" in note, note

    frozen = _lc({})
    old = _origin_note(frozen)
    assert "幂次" not in old and "近邻" not in old, f"存量件不声明，句子却替它编了参数：{old}"
    assert "插值推导" in old, "缺键只该少那半句，主体提醒不许一起消失"
