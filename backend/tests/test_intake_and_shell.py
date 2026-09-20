"""阶段 2/3 契约测试：名称坐标同源（intake 软守卫）与静默空壳封堵。

对应 v2 计划 §5（阶段 2）与 §6（阶段 3）。两条都由**实测事故**驱动：

- §5 事故：报告 ``lc-d3cfa371`` —— ``scene_name=北京劲松`` 而 ``center=(102.76, 25.03)``（昆明）。
  名称取输入框旧值、坐标取定位结果、城市取「当前展示的报告」—— 三个来源，报告自相矛盾，
  且**完全不可见**：无告警、无标记、无异常，字段全齐。
- §6 事故：报告 ``lc-c796c62d``（迤栖村）—— ``status=done`` / ``percent=100`` / ``error=None``，
  但 ``isochrones=[]``、``poi.points=[]``、``scores.total=0``、``blindspots=1``（面积=整张网格）。
  顶层 7 个契约字段**全部齐全** ⇒ 契约断言逐条通过 ⇒ 用户读到「0 分 / 1 处盲区」，
  真实含义是「什么都没查到」。

本文件按「先红后绿」纪律编写（修复前必然失败，见 ``证据-地图三问/`` 留档）。
"""
import asyncio

import pytest

from app.core import db, runner
from app.core.pipeline import living_circle as lcpipe
from app.core.pipeline.living_circle import (
    NAME_CENTER_MAX_M,
    _sample_scene_centers,
    create_living_circle_task,
    living_circle_pipeline,
)
from app.living_circle.report_contract import live_geometry_deficiency

KAILI = {
    "scene_name": "凯里老街",
    "city": "贵州·凯里",
    "address": "凯里市西门街道老街片区",
    "center": [107.9758, 26.5734],
    "study_radius_m": 2500.0,
    "mode": "standard",
    "data_mode": "fixture",  # 测试无网络：fixture 分支
}

KUNMING = [102.7596, 25.0295]  # 实测事故里那条「名为北京劲松、坐标在昆明」的坐标


def _run_pipeline(task_id: str) -> list:
    async def _impl():
        return [ev async for ev in living_circle_pipeline(task_id)]

    return asyncio.run(_impl())


def _report_of(events: list) -> dict:
    rid = next(e for e in events if e["type"] == "done")["data"]["report_id"]
    return db.get_living_circle_report(rid)


def _lc_of(events: list) -> dict:
    return _report_of(events)["living_circle"]


def _mismatch_warns(events: list) -> list:
    return [
        e for e in events
        if e["type"] == "warn" and (e.get("data") or {}).get("code") == "name_center_mismatch"
    ]


# ────────────────────────── 阶段 2：名称与坐标同源 ──────────────────────────


def test_sample_scene_library_is_mode_independent():
    """样例场景库必须可直接取用（live 模式也要生效）。

    实测缺陷恰好发生在 live 模式，而 live 模式的 CachingDataSource **不透传**
    ``sample_scenes()`` —— 若守卫用数据源取样例，会在最需要它的场景里静默失效。
    故本用例钉住「库本身可用」这一前提。
    """
    centers = _sample_scene_centers()
    names = [c[0] for c in centers]
    assert names, "样例场景库为空 —— 名称/坐标同源校验会静默失效"
    assert any("凯里" in n for n in names), names
    assert any("劲松" in n for n in names), names


def test_name_center_mismatch_is_surfaced():
    """名称与中心点相差约 1800km → 必须产出**可见**告警 + 报告带同源标记。

    旧实现对此完全静默：报告照签、字段照齐、前端照展示「北京劲松」+「昆明坐标」。
    """
    tid = create_living_circle_task(dict(KAILI, scene_name="北京劲松", center=KUNMING))
    events = _run_pipeline(tid)

    warns = _mismatch_warns(events)
    assert warns, "名称与中心点跨省错配，必须产出 name_center_mismatch 告警（旧实现静默）"

    scene = _lc_of(events)["scene"]
    assert scene["name_center_mismatch"] is True
    assert scene["name_center_distance_m"] > NAME_CENTER_MAX_M
    assert scene["name_source"] == "user_query"
    # 举证要能回答「与谁不同源」——只报一个 true 不足以排查
    assert scene["name_ref_center"], "必须给出同名样例的真实中心点，否则无从核对"


def test_same_source_is_not_flagged():
    """名称与坐标同源时**不得**打标（防止把正常用法一起污名化）。"""
    tid = create_living_circle_task(dict(KAILI))
    events = _run_pipeline(tid)

    assert not _mismatch_warns(events), "同源输入不应产生 mismatch 告警"
    assert "name_center_mismatch" not in _lc_of(events)["scene"]
    # 但溯源标记仍应在（intake 总要说明名称来自哪里）
    assert _lc_of(events)["scene"]["name_source"] == "user_query"


# ────────────────────────── 阶段 3：静默空壳 ──────────────────────────


@pytest.mark.parametrize(
    "lc,expect",
    [
        # live 缺几何：两种缺失各自可辨
        ({"data_origin": "live", "isochrones": [], "poi": {"points": []}}, "路网等时圈数据"),
        ({"data_origin": "live", "isochrones": [{"minutes": 5}], "poi": {"points": []}}, "设施点位数据（POI）"),
        # live 齐全：合格
        ({"data_origin": "live", "isochrones": [{"minutes": 5}], "poi": {"points": [{"id": "p1"}]}}, None),
        # offline / fixture 的空白是**有意降级**，不属于残缺（P0-2 已如实标注）
        ({"data_origin": "offline", "isochrones": [], "poi": {"points": []}}, None),
        ({"data_origin": "fixture", "isochrones": [], "poi": {"points": []}}, None),
        # 缺 data_origin 的历史报告：不误判（责任在数据处置，不在读路径兜底）
        ({"isochrones": [], "poi": {"points": []}}, None),
    ],
)
def test_live_geometry_deficiency(lc, expect):
    assert live_geometry_deficiency(lc) == expect


def test_runner_honours_failed_done(monkeypatch):
    """``done`` 只表示「事件流结束」，不表示成功。

    引擎判定失败时带 ``status='failed'`` 收尾；runner 若无条件 ``mark_task_done``，
    就会把引擎写的 failed **覆盖成 done** —— 守卫被自己的收尾动作抹掉。
    本用例正是钉住 runner 侧的终态口径。
    """
    runner._running.clear()
    msg = "未取得路网等时圈数据，请更换中心点或检查配额"

    async def _gen(task_id):
        yield {"type": "progress", "data": {"percent": 99, "stage": "audit", "evidence_count": 0}}
        yield {"type": "error", "data": {"stage": "audit", "code": "empty_geometry", "message": msg}}
        yield {"type": "done", "data": {"reportId": None, "report_id": None, "status": "failed", "error": msg}}

    db.save_task("t_lc_empty_1", query="空壳测试", clarifications={}, kind="living_circle")
    monkeypatch.setattr(lcpipe, "living_circle_pipeline", _gen)

    async def _scenario():
        runner.ensure_running("t_lc_empty_1")
        await asyncio.sleep(0.3)  # 让后台 _drive 跑完

    asyncio.run(_scenario())

    full = db.get_task_full("t_lc_empty_1")
    assert full["status"] == "failed", "空壳报告的 done 不得被当作成功"
    assert msg in (full["error"] or "")
    assert runner._running["t_lc_empty_1"].status == "failed", "/api/tasks 列表也要显示失败态"


def test_list_hides_incomplete_live_reports():
    """读路径只放行**合乎几何契约**的报告；两类都必须被挡下，且数据保留（只隐藏，不删除）。

    两类残缺的可见性差别极大，此前只有第一类被认出来：

    - **内容缺件**：``isochrones`` / ``poi.points`` 为空 ⇒ 读者看到「0 分」；
    - **几何不自洽**：字段一个不缺、报告看起来完全正常，但盲区越出可达区、圈内点数谎报。
      实测 12/14 份存量报告属于后者或更早的形态 —— 旧读路径**逐条放行**。
    """
    def _mk(rid: str, *, iso, points, blindspots=None, caliber=True) -> dict:
        lc: dict = {
            "scene": {"name": "测试样区", "center": [107.9758, 26.5734], "study_radius_m": 2500},
            "data_origin": "live",
            "isochrones": iso,
            "poi": {"points": points},
            "scores": {"total": 70 if iso and points else 0},
            "blindspots": blindspots or [],
            "sampling": {"interpolation": "idw"},
        }
        if caliber:
            # 现行 live 报告必须举证口径（否则可达区无法被唯一确定）—— 契约的 B0 判据
            lc["caliber"] = {"reach_full_min": 20.0, "collect_radius_m": 1500.0}
        return {"id": rid, "created_at": db._now(), "living_circle": lc}

    def _square_iso() -> list:
        """±1000m 方环（外接圆 ≈1414m）→ 可作可达区参照系。"""
        from app.living_circle.geo_utils import ring_area_km2, xy_to_lnglat

        c = (107.9758, 26.5734)
        ring = [xy_to_lnglat(c, x, y) for x, y in
                [(-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000), (-1000, -1000)]]
        return [{
            "minutes": 20,
            "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
            "area_km2": ring_area_km2(ring, c),
        }]

    def _blindspot(rid: str, half: float) -> dict:
        """边长为 ``2×half`` 的方形盲区（±5000m ⇒ 越出可达区；±500m ⇒ 在区内）。"""
        from app.living_circle.geo_utils import xy_to_lnglat

        c = (107.9758, 26.5734)
        ring = [xy_to_lnglat(c, x, y) for x, y in
                [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]]
        return {"id": rid, "polygon": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}

    ok_point = {"id": "p1", "in_circle": True, "lnglat": [107.9758, 26.5734], "name": "中心点设施"}
    out_point = {"id": "p2", "in_circle": False, "lnglat": [108.1, 26.7], "name": "圈外设施"}

    db.save_living_circle_report(_mk("lc-shell-t1", iso=[], points=[]), scene_key="sk-t1")
    db.save_living_circle_report(
        _mk("lc-geom-t1", iso=_square_iso(), points=[ok_point], blindspots=[_blindspot("bs-far", 5000.0)]),
        scene_key="sk-t2",
    )
    db.save_living_circle_report(
        _mk("lc-outpt-t1", iso=_square_iso(), points=[ok_point, out_point]),
        scene_key="sk-t3",
    )
    db.save_living_circle_report(
        _mk("lc-nocal-t1", iso=_square_iso(), points=[ok_point], caliber=False),
        scene_key="sk-t4",
    )
    db.save_living_circle_report(
        _mk("lc-good-t1", iso=_square_iso(), points=[ok_point], blindspots=[_blindspot("bs-near", 500.0)]),
        scene_key="sk-t5",
    )

    visible = [r["id"] for r in db.list_living_circle_reports()]
    assert "lc-good-t1" in visible, "合规报告必须可见"
    for bad in ("lc-shell-t1", "lc-geom-t1", "lc-outpt-t1", "lc-nocal-t1"):
        assert bad not in visible, f"{bad} 不合几何契约，不得出现在用户可见列表"

    everything = [r["id"] for r in db.list_living_circle_reports(include_incomplete=True)]
    for rid in ("lc-shell-t1", "lc-geom-t1", "lc-outpt-t1", "lc-nocal-t1", "lc-good-t1"):
        assert rid in everything, "数据必须保留在库中（只隐藏，不删除）"


# ────────────────────────── 写路径：不合契约不得签发 ──────────────────────────
#
# 读路径的守卫只能「事后遮挡」；真正决定性的是**落库前的签发判定**。
# 这一段用「真实夹具当底座 + 注入一类几何缺陷」的假数据源驱动**真实流水线**，
# 断言：不合契约 ⇒ 任务 failed、报告不落库。三个注入点各对应一类真实事故。


class _MutatingSource:
    """把真实夹具当底座、按 ``mutate`` 注入缺陷的数据源（``client=None`` ⇒ 走 fixture 分支）。

    为什么用真夹具而不是手搓最小报告：手搓的字段形状一旦与产线漂移，测试就会在
    「报告长什么样」这件事上失去判别力 —— 而本段要测的恰恰是「真实产物被改坏后能否拦住」。
    """

    client = None  # 明确的离线源：pipeline 据此走 fixture 分支

    def __init__(self, mutate=None):
        from app.living_circle.data_source import FixtureDataSource

        self._inner = FixtureDataSource()
        self._mutate = mutate

    async def compute(self, check):
        import copy as _copy

        lc = _copy.deepcopy(await self._inner.compute(check))
        if self._mutate:
            self._mutate(lc)
        return lc

    def sample_scenes(self):
        return self._inner.sample_scenes()


def _run_with_mutation(monkeypatch, mutate):
    """用注入缺陷的数据源跑一遍真实流水线 → ``(task_id, events)``。"""
    from app.living_circle import data_source as ds

    monkeypatch.setattr(ds, "get_data_source", lambda *a, **k: _MutatingSource(mutate))
    tid = create_living_circle_task(dict(KAILI))
    return tid, _run_pipeline(tid)


def _strip_geometry(lc: dict) -> None:
    lc["isochrones"] = []
    lc["poi"]["points"] = []


def _blindspot_out_of_reach(lc: dict) -> None:
    """把一个**结构完整**（模板需要的字段一个不少）的盲区放到 5km 外。

    刻意保留 ``center`` / ``radius_m`` / ``missing_facilities`` / ``nearest`` ——
    只改几何，不改形状：否则失败会从「守卫拦住了坏几何」退化成
    「模板缺字段抛 KeyError」，测试虽红却红错了地方（守卫根本没被执行到）。
    """
    from app.living_circle.geo_utils import xy_to_lnglat

    c = tuple(lc["scene"]["center"])
    half = 5000.0
    ring = [xy_to_lnglat(c, x, y) for x, y in
            [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]]
    lc["blindspots"] = [{
        "id": "bs-injected",
        "center": list(c),
        "radius_m": 1000,
        "missing_facilities": ["菜市场"],
        "nearest": [{"facility": "market", "name": "注入样例", "distance_m": 1134.3, "direction": "正东"}],
        "polygon": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
    }]


def _poi_outside_reach(lc: dict) -> None:
    from app.living_circle.geo_utils import xy_to_lnglat

    c = tuple(lc["scene"]["center"])
    far = xy_to_lnglat(c, 4000.0, 0.0)
    lc["poi"]["points"] = list(lc["poi"]["points"]) + [
        {"id": "p-injected", "name": "注入的圈外点", "in_circle": True, "lnglat": [far[0], far[1]]}
    ]


def _drop_caliber(lc: dict) -> None:
    lc.pop("caliber", None)


@pytest.mark.parametrize(
    "mutate,label",
    [
        (_strip_geometry, "Tier A：内容缺件（isochrones / POI 为空）"),
        (_blindspot_out_of_reach, "Tier B1：盲区越出可达区（Q1 复发）"),
        (_poi_outside_reach, "Tier B3：点位越出可达区（Q2 复发）"),
        (_drop_caliber, "Tier B0：live 报告未声明口径"),
    ],
)
def test_pipeline_refuses_to_sign_report_violating_contract(monkeypatch, mutate, label):
    """不合几何契约的 live 产物 → 任务失败、不落库、不签收。"""
    tid, events = _run_with_mutation(monkeypatch, mutate)

    done = next(e for e in events if e["type"] == "done")
    assert done["data"]["status"] == "failed", f"{label}: 不得以 done 收尾"
    assert done["data"]["report_id"] is None, f"{label}: 不得签发 report_id"

    assert any(e["type"] == "error" for e in events), f"{label}: 必须给出 error 事件"
    task = db.get_task_full(tid)
    assert task["status"] == "failed", f"{label}: 任务终态应为 failed"
    assert task["error"], f"{label}: 必须写明失败原因（复用 status/error 字段）"


def test_pipeline_signs_compliant_report(monkeypatch):
    """反例护栏：不注入缺陷时流水线必须正常签发（防止「一律失败」的假修复）。"""
    tid, events = _run_with_mutation(monkeypatch, None)
    done = next(e for e in events if e["type"] == "done")
    rid = done["data"]["report_id"]
    assert rid, "合规产物必须被签发"
    assert db.get_task_full(tid)["status"] == "done"
    assert db.get_living_circle_report(rid) is not None, "合规产物必须落库"
