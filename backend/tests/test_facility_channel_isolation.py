"""设施归并的两条通道隔离与披露守卫（评审 P0-1 / P0-2 专项）。

为什么单独立一个文件：这两条是**架构级**约束，不是某个函数的输入输出。

- P0-1：三要素（菜市场/药店/小学）与类目**共用同一份 `_dedupe` 实现**
  （`poi_collector.py:450` → `:515-520` → `poi.dedupe_pois`）。归并判据一旦渗进
  三要素通道，盲区 1km 硬判的输入坐标就会变少 —— 面板「服务盲区 2 处」可能凭空
  变 3 处。这是报告结论级变化，严重度高于地图上少一个点。
- P0-2：`to_points` 是**逐字段白名单**构造点位（`poi.py:268-277`），`PoiCollection`
  原本只有三个槽 ⇒ 归并统计在结构上到不了报告。**归并是「少输出」型操作，守恒
  不变量对它完全免疫**（现状 104/104 全绿的同时藏着 8 个 ATM），不留痕就无从发现。
"""
import asyncio
import json
import math
import pathlib

import pytest

from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import STOP_COMPLETE, PlaceSearchOut
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0


def _xy(x, y=0.0):
    return xy_to_lnglat(CENTER, x, y)


def _poi(name, x, y, tag="银行"):
    lng, lat = _xy(x, y)
    return {"name": name, "lng": lng, "lat": lat, "address": "关兴路", "tag": tag,
            "type": "金融", "uid": f"u-{name}"}


# 每类三个词会各自返回同一批点 ⇒ 天然产生「同名重复」，用来验证记账不会把同名重复
# 混进设施归并的账里。
BANKS = [_poi("中国工商银行(昆明关上支行)", 400, 0), _poi("中国工商银行24小时自助银行(关上支行)", 415, 0)]
PHARMACY = [_poi("一心堂药店", 600, 0, "药店"), _poi("一心堂药店-门诊", 612, 0, "药店")]
PRIMARY = [_poi("关上第一小学", 700, 0, "小学")]
MARKET = [_poi("金马农贸市场", 300, 0, "菜市场"), _poi("金马农贸市场-东门", 312, 0, "菜市场")]


class StubClient:
    def __init__(self):
        self.calls = 0

    async def place_search(self, query, center, **kw):
        self.calls += 1
        if query == "银行":
            out = BANKS
        elif query in ("菜市场", "农贸市场", "生鲜市场"):
            out = MARKET
        elif query == "药店":
            out = PHARMACY
        elif query == "小学":
            out = PRIMARY
        else:
            out = []
        return PlaceSearchOut([dict(i) for i in out], len(out), 1, STOP_COMPLETE)


def _scope():
    ring = [_xy(-RING_HALF, -RING_HALF), _xy(RING_HALF, -RING_HALF),
            _xy(RING_HALF, RING_HALF), _xy(-RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0,
            "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _collect(monkeypatch, enabled=True):
    monkeypatch.setenv("LC_FACILITY_MERGE", "on" if enabled else "off")
    return asyncio.run(pc.collect_poi(StubClient(), CENTER, 2000.0, scope=_scope()))


# ── P0-1：三要素通道不吃归并 ────────────────────────────────────────

def test_triad_channels_keep_every_coordinate(monkeypatch):
    """药店/小学/菜市场的三要素坐标集必须**不因归并而减少**。"""
    collected = _collect(monkeypatch)
    assert [i["name"] for i in collected.triads["pharmacy"]] == [
        "一心堂药店", "一心堂药店-门诊"], "三要素通道被归并污染 ⇒ 盲区硬判输入变少"
    assert len(collected.triads["primary"]) == 1


def test_market_triad_is_recomputed_from_raw_not_from_category(monkeypatch):
    """菜市场三要素必须回到**采集期原始点集**重算。

    `per_category["market"]` 已在 `:428` 被 facility 去过一轮，被吸收的点**已经不存在**；
    对它重跑 geometric 什么都还原不出来（评审第 2 轮 P0-2）。本用例把输入集钉死。
    """
    collected = _collect(monkeypatch)
    cat_names = [i["name"] for i in collected.per_category["market"]]
    triad_names = [i["name"] for i in collected.triads["market"]]
    assert "金马农贸市场-东门" not in cat_names, "前提：类目通道确已把东门归并进市场"
    assert "金马农贸市场-东门" in triad_names, "三要素通道必须仍持有东门坐标"


def test_category_channel_does_merge(monkeypatch):
    """对照组：类目通道确实归并了 —— 否则上面两条是「什么都没发生」空过。"""
    collected = _collect(monkeypatch)
    assert [i["name"] for i in collected.per_category["finance"]] == ["中国工商银行(昆明关上支行)"]


# ── P0-2：披露不静默 ────────────────────────────────────────────────

def test_merged_disclosure_counts_only_facility_absorptions(monkeypatch):
    """`absorbed` 只数设施归并，不掺同名重复。

    本 stub 每类三个检索词返回同一批点 ⇒ 采集期存在大量**同名**重复；若按
    `len(in)-len(out)` 记账，market 会报出远大于 1 的数字，`poi.merged` 就成了
    一个无从核对的大数。
    """
    collected = _collect(monkeypatch)
    by = {m["category"]: m["absorbed"] for m in collected.merged}
    assert by == {"finance": 1, "market": 1}


def test_switch_off_yields_empty_disclosure_and_legacy_points(monkeypatch):
    """开关 off ⇒ 无归并、无披露，点位回到归并前形态（现存缓存因此仍可比对）。"""
    collected = _collect(monkeypatch, enabled=False)
    assert collected.merged == ()
    assert [i["name"] for i in collected.per_category["finance"]] == [
        "中国工商银行(昆明关上支行)", "中国工商银行24小时自助银行(关上支行)"]


def test_poi_collection_keeps_three_arg_construction_and_defaults_merged():
    """`merged` 的默认值保住的是**三参构造**，不是三元组位置解包。

    原用例名 `..._still_unpacks_as_three_tuple` 断的是一件不可能的事：NamedTuple 解包必须
    满员，四字段解成三个必 `ValueError`（它自己的下一行已把 `_fields` 写成 4 个，两条判据
    互相矛盾 ⇒ 加 `merged` 时只改了后半句）。生产 docstring 的同名承诺已一并改正。
    这里改成守真正需要守的两件事：老构造点照旧可用、`merged` 缺省为空披露。
    """
    legacy = pc.PoiCollection({}, {}, None)          # 三参构造（测试与 stub 的既有造法）
    per_category, triads, evidence = legacy[:3]      # 取前三件：满员解包办不到，切片可以
    assert (per_category, triads, evidence) == ({}, {}, None)
    assert legacy.merged == (), "无归并即空披露，不得静默"
    assert pc.PoiCollection._fields == ("per_category", "triads", "evidence", "merged")
    with pytest.raises(ValueError):
        per, tri, ev = legacy                        # 反证：满员解包才是唯一形状


def test_merge_all_single_arg_still_works():
    """`merge_all` 被既有测试以单参调用，扩形参不得破坏它。"""
    assert pc.merge_all({"market": []}) == {"market": []}


# ── 披露必须活到报告出口 ────────────────────────────────────────────

def test_merged_field_always_present_in_poi_block():
    """`poi.merged` 字段恒存在（对齐 `truncated` 恒存在判据）。

    缺字段 = 无从判别这份报告是不是新口径产物；这与 `test_poi_conservation.py`
    对 `truncated` 的要求同一条理由。
    """
    asm = pytest.importorskip("app.living_circle.assemble")
    from app.living_circle.poi import to_stats

    per_category = {"finance": [dict(i) for i in BANKS]}
    scope = _scope()
    stats = to_stats(per_category, {}, scope, CENTER)
    block = asm.build_poi_block(per_category, {}, scope, CENTER, stats)
    assert "merged" in block
    assert set(block["merged"]) == {"rule_version", "enabled", "absorbed", "categories"}
    assert block["merged"]["absorbed"] == 0, "未经采集期归并 ⇒ 此处应为 0，不得凭空报数"


def test_caliber_index_registers_facility_namespace():
    """归并口径必须可被专家卡引用；不登记就会被词表闸判成「编造指标」。"""
    import app.living_circle                      # noqa: F401  触发 resolver 注册（既有约束）
    from app.living_circle import caliber_index

    for ref in ("facility::FACILITY_RULE_VERSION", "facility::FACILITY_MERGE_M",
                "facility::triad_channel_policy", "facility::merge_enabled"):
        view = caliber_index.view(ref)
        assert view is not None, f"口径索引缺 {ref}"
    assert caliber_index.view("facility::FACILITY_MERGE_M").value == "50.0"


# ── 黄金夹具必须真的能加载并被两侧共用 ──────────────────────────────

def test_golden_fixture_is_loadable_and_complete():
    """夹具是本判据的唯一凭据；官渡区那份缓存已过期消失，坏了就没有第二份。"""
    path = pathlib.Path(__file__).parent / "fixtures" / "facility_merge_golden.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "evergreen.facility-golden-pairs/v1"
    ids = {p["id"] for p in doc["pairs"]}
    assert "guandong-bocom-vs-ccb-atm" in ids, "交行/建行 23m 回归锁不得丢失"
    assert any("guandong" in i for i in ids), "官渡样本已随缓存过期消失，夹具是其唯一留存"
    # 先钉住样本量再逐条遍历：否则夹具被清空时下面的循环会**空转通过**，
    # 让「凭据已丢失」看起来像「全部通过」。
    assert len(doc["pairs"]) >= 11, f"夹具样本退化：{len(doc['pairs'])} 组"
    for p in doc["pairs"]:
        assert {"name", "lng", "lat", "category"} <= set(p["a"]) and {"pins", "expect"} <= set(p)
        assert math.isfinite(p["distance_m"])
