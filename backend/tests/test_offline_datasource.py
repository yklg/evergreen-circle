"""U2 · OfflineDataSource：离线估算契约完整 + 复用引擎同构 + 不产可比评分/盲区（覆盖方案 U2-1~U2-7）。"""
import asyncio

from app.living_circle.data_source import CheckParams, OfflineDataSource
from app.living_circle.isochrone import (  # noqa: F401  (口径同源校验)
    REACH_FULL_MIN,
    WALK_SPEED_M_PER_MIN,
    reach_flags,
)


def _compute(scene_name="上海市浦东新区陆家嘴", center=None, city="上海市", address="", sample_profile="standard"):
    ds = OfflineDataSource()
    params = CheckParams(scene_name=scene_name, city=city, address=address, center=center, sample_profile=sample_profile)
    return asyncio.run(ds.compute(params))


def test_u2_1_contract_complete():
    r = _compute()
    for k in ["scene", "generated_at", "data_origin", "isochrones", "sampling", "poi", "blindspots", "scores"]:
        assert k in r
    assert r["data_origin"] == "offline"
    assert {z["minutes"] for z in r["isochrones"]} == {5, 10, 15, 20}
    assert r["sampling"]["interpolation"] == "circular_approx"
    assert r["sampling"]["is_scattered"] is False
    assert r["scene"]["center"] == [round(r["scene"]["center"][0], 6), round(r["scene"]["center"][1], 6)]


def test_u2_2_engine_reuse_isomorphic_with_live():
    """与 live 同构：isochrones 字段结构一致 + 面积随分钟单调递增。"""
    r = _compute()
    prev = 0.0
    for z in r["isochrones"]:
        assert set(z.keys()) == {"minutes", "area_km2", "geojson"}
        assert z["geojson"]["type"] == "Polygon"
        assert z["area_km2"] > prev  # 距离模型下大圈必然更大
        prev = z["area_km2"]
    # 采样点自洽：距离模型下无「测时失败」的点（timed 恒真），
    # 但**可达性仍要分档** —— 超出 REACH_FULL_MIN 的点 in_reach=False。
    for p in r["sampling"]["points"]:
        assert p["timed"] is True
        assert isinstance(p["in_reach"], bool)
        assert p["minutes"] is not None and p["minutes"] >= 0
        assert p["in_reach"] is (p["minutes"] <= REACH_FULL_MIN)
    # 分档汇总数与逐点一致，且随 sampling 一起落报告（消费方不再自行 filter）
    flags = reach_flags(r["sampling"]["points"])
    assert r["sampling"]["timed_count"] == flags.timed_count == len(r["sampling"]["points"])
    assert r["sampling"]["in_reach_count"] == flags.in_reach_count
    assert 0 < r["sampling"]["in_reach_count"] < flags.timed_count, (
        "in_reach 与 timed 未分离：距离模型下必然存在 >20min 的采样点"
    )


def test_u2_3_no_comparable_score():
    r = _compute()
    assert r["blindspots"] == []
    assert r["scores"]["total"] == 0
    assert "需实时体检" in r["scores"]["note"]
    assert "不可与实时分比较" in r["scores"]["note"]
    assert r["scores"]["triads"] == []
    assert r["scores"]["radar"] == []


def test_offline_report_missing_evidence_keys_is_not_a_violation():
    """离线骨架不带证据相 ⇒ 契约三条必须**整体跳过**（缺键 ≠ 违规）。

    为什么不给它补键：离线态没有实测采集半径可谈，硬造 `evidence_*` 就是把「没采集」
    洗成「采集齐了」。而 B5/B10/B11 的门禁挂在 `scope_policy_version` 上，正是为了让
    「无网络时的诚实降级」不被判成脏数据 —— 否则读路径会把离线骨架一起隐藏（P0-2 的老账）。
    """
    from app.living_circle.report_contract import assess_geometry, report_is_presentable, reuse_policy
    from app.living_circle.scope import SCOPE_POLICY_VERSION

    r = _compute()
    cal = r["caliber"]
    # 前提守卫：这份报告**真的**缺整套证据键（若哪天离线也发版本，本用例要重指判据）
    assert SCOPE_POLICY_VERSION not in cal, "离线骨架开始声明口径版本 ⇒ 本用例判据需重指"
    for k in ("evidence_margin_m", "evidence_radius_m", "evidence_complete", "judge_radius_m"):
        assert k not in cal, f"离线报告出现 {k} ⇒ 「没采集」被伪装成「已举证」"

    assert assess_geometry(r).violations == (), assess_geometry(r).reason
    assert report_is_presentable(r) is True
    # 复用门只管 live 载荷冒充新答案；离线骨架不受版本约束（它的可用性由 presentability 管）
    assert reuse_policy(r) == (True, "")
    # 前端拿到的是「没有置信度」而不是「置信度=full」：缺键必须一路缺到展示层
    assert r["scores"].get("confidence") is None


def test_u2_4_poi_empty_and_marked():
    r = _compute()
    assert r["poi"] == {"categories": [], "total": 0, "in_circle": 0, "points": []}


def test_u2_5_zero_center_still_contract():
    r = _compute(scene_name="未知名", center=(0.0, 0.0))
    assert r["data_origin"] == "offline"
    assert {z["minutes"] for z in r["isochrones"]} == {5, 10, 15, 20}


def test_u2_6_empty_scene_name_no_crash():
    r = _compute(scene_name="")
    assert r["data_origin"] == "offline"
    assert r["scene"]["name"] == ""


def test_u2_7_deterministic():
    a = _compute()
    b = _compute()
    # 仅 generated_at 时间戳允许差异，其余逐字段相等（无随机）
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b
