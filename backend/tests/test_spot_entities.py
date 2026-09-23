"""景点实体契约（schemas 实体四键 + orchestrator 信号抽取降级）—— TC-B02/B03 单元面。

守护的不变量（INV-C 实体一致性的数据层防线）：
- spot_id 是**稳定生成键**：同目的地同序必得同 id，显式给的 id 原样保留（地图/路线/
  舆情/一页视图全部引用它，抖动一次就错位一处）。
- 非法行在边界被剔除（无名行、无目的地组），evidence_ids 只认白名单（四铁律）。
- 信号字段双命名兼容（canonical voice/sentiment/value ↔ LLM 原始 mentions/
  positive_ratio/value_score），且优先读 scoring 清洗后的 signals_clean。
- 坐标与 matched 位**允许缺失**（M1 契约先行，M2 百度实体解析才填充）：缺失不炸。
- _extract_spot_signals 对 LLM 异常静默降级为空表（上层出如实提示，任务不失败）。

运行：backend/ 下 `pytest tests/test_spot_entities.py -q`
"""
import asyncio

import pytest

from app.core import orchestrator as O
from app.services import baidu as baidu_mod
from app.core.schemas import (coerce_food_ranking, coerce_shop_list,
                              coerce_spot_ranking, coerce_spot_routes)

_EIDS = {"e_aaaaaaaa", "e_bbbbbbbb"}


def _spot(name, **kw):
    row = {"name": name, "signals": {"mentions": 10, "positive_ratio": 0.8,
                                     "value_score": 0.6},
           "evidence_ids": ["e_aaaaaaaa", "e_forged00"]}
    row.update(kw)
    return row


# ── spot_ranking ─────────────────────────────────────────
def test_spot_id_generated_stably_by_destination():
    raw = [{"destination": "大理", "items": [_spot("古城"), _spot("洱海")]}]
    first = coerce_spot_ranking(raw, _EIDS)
    second = coerce_spot_ranking(raw, _EIDS)
    assert first == second
    ids = [it["spot_id"] for it in first[0]["items"]]
    assert ids == ["大理_spot_1", "大理_spot_2"], "spot_id = 目的地slug_序号，同序必同 id"


def test_explicit_spot_id_is_preserved():
    out = coerce_spot_ranking(
        [{"destination": "大理", "items": [_spot("古城", spot_id="custom_x")]}], _EIDS)
    assert out[0]["items"][0]["spot_id"] == "custom_x", "M2 冻结表回灌时显式 id 不得被重新生成"


def test_row_and_group_boundary_drops():
    out = coerce_spot_ranking(
        [{"destination": "大理", "items": [_spot("古城"), {"signals": {}}, "非字典"]},
         {"destination": "", "items": [_spot("孤儿")]},
         {"items": [_spot("无目的地组")]}], _EIDS)
    assert len(out) == 1 and len(out[0]["items"]) == 1, "无名行/无目的地组必须被剔除"


def test_evidence_whitelist_enforced_and_coordinate_optional():
    it = coerce_spot_ranking([{"destination": "大理", "items": [_spot("古城")]}],
                             _EIDS)[0]["items"][0]
    assert it["evidence_ids"] == ["e_aaaaaaaa"], "白名单外证据必须被过滤"
    assert it["lat"] is None and it["lng"] is None and it["matched"] is None, \
        "M1 契约允许坐标缺失（M2 百度实体解析填充），缺了不得丢行"
    assert it["rank"] == 1 and it["score"] is None, "rank 缺省按序回填；score 由 scoring 负责"


def test_signals_prefer_clean_and_accept_llm_aliases():
    out = coerce_spot_ranking([{"destination": "大理", "items": [
        _spot("甲", signals_clean={"voice": 1, "sentiment": 2, "value": 3}),
        {"name": "乙", "mentions": 8, "positive_ratio": 0.5, "value_score": 0.4},
    ]}], _EIDS)[0]["items"]
    assert out[0]["signals"] == {"voice": 1.0, "sentiment": 2.0, "value": 3.0}, \
        "scoring 清洗结果优先（榜单明细与算分同源）"
    assert out[1]["signals"] == {"voice": 8.0, "sentiment": 0.5, "value": 0.4}, \
        "顶层原始字段名也要能抽出（LLM 形状漂移容错）"


def test_dims_carried_for_score_breakdown_display():
    out = coerce_spot_ranking([{"destination": "大理", "items": [
        _spot("甲", dims={"voice": 100.0, "sentiment": 80.0, "value": 60.0}, score=82.0,
              rank=1)]}], _EIDS)[0]["items"][0]
    assert out["dims"] == {"voice": 100.0, "sentiment": 80.0, "value": 60.0}
    assert out["score"] == 82.0
    no_dims = coerce_spot_ranking([{"destination": "大理", "items": [_spot("乙")]}],
                                  _EIDS)[0]["items"][0]
    assert no_dims["dims"] is None, "无明细时显式 None（前端整列省略），不得造假 0 分"


# ── food_ranking / spot_routes / shop_list ───────────────
def test_food_ranking_shape():
    out = coerce_food_ranking([{"destination": "大理", "dishes": [
        {"name": "乳扇", "category": "小吃", "price_range": "10-20 元",
         "evidence_ids": ["e_bbbbbbbb", "e_x"]}, {"无名": 1}]}], _EIDS)
    items = out[0]["items"]
    assert len(items) == 1
    assert items[0]["food_id"] == "大理_food_1"
    assert items[0]["evidence_ids"] == ["e_bbbbbbbb"]


def test_spot_routes_reference_spot_id_and_lowercase_mode():
    out = coerce_spot_routes([{"destination": "大理", "spots": [
        {"spot_id": "大理_spot_1", "spot_name": "大理古城", "routes": [
            {"mode": "Subway", "duration": "25分钟", "cost": "4元", "transfer": "1",
             "evidence_ids": ["e_aaaaaaaa"]},
            {"mode": "", "note": "无方式整条剔除"},
        ]},
        {"name": "无id也可按名挂接"},
    ]}], _EIDS)
    items = out[0]["items"]
    assert items[0]["spot_id"] == "大理_spot_1"
    assert items[0]["routes"][0]["mode"] == "subway"
    assert len(items[0]["routes"]) == 1
    assert items[1]["spot_id"] == "", "缺 spot_id 保留空串占位，由上层决定降级"


def test_shop_list_price_stripped_to_number():
    out = coerce_shop_list([{"destination": "大理", "shops": [
        {"name": "老字号", "food": "乳扇", "price_per_person": "￥58元",
         "evidence_ids": ["e_aaaaaaaa"]}]}], _EIDS)
    it = out[0]["items"][0]
    assert it["price_per_person"] == 58.0, "参考价必须收敛为数值（脏符号剥掉）"
    assert it["shop_id"] == "大理_shop_1"
    assert it["matched"] is None and it["lat"] is None, "POI 实体位 M2 前允许缺失"


def test_shop_list_routes_normalized_like_spot_routes():
    """M3e：商铺行携带 routes 子表，规整契约与 spot_routes 同源（mode 小写、脏行剔除）。"""
    out = coerce_shop_list([{"destination": "大理", "shops": [
        {"name": "老字号", "food": "乳扇", "matched": True, "lat": 25.69, "lng": 100.16,
         "routes": [{"mode": "Transit", "duration": "约40分钟", "transfer": "公交1路",
                     "evidence_ids": ["e_forged00"]},
                    {"mode": "", "note": "无方式整条剔除"}]}]}], _EIDS)
    it = out[0]["items"][0]
    assert len(it["routes"]) == 1
    r = it["routes"][0]
    assert r["mode"] == "transit"
    assert set(r) == {"mode", "duration", "cost", "transfer", "note", "evidence_ids"}
    assert r["evidence_ids"] == [], "伪造证据 id 不得漏网"
    assert it["matched"] is True and it["lat"] == 25.69, "POI 回填位应被保留"


# ── M3e · 商铺公交路线：配额与降级 ─────────────────────────
def _shop(name, food, **kw):
    row = {"shop_id": name, "food": food, "name": name,
           "matched": True, "lat": 25.69, "lng": 100.16}
    row.update(kw)
    return row


def _fake_baidu_channel(monkeypatch, direction_calls):
    monkeypatch.setattr(baidu_mod, "available", lambda: True)
    monkeypatch.setattr(baidu_mod, "geocode",
                        lambda address, city="": {"ok": True, "lat": 25.70, "lng": 100.15})

    def fake_direction(mode, origin, destination, city=None, city_limit=True):
        assert mode == "transit", "商铺路线配额只走 transit 通道（计划待确认 #4）"
        direction_calls.append(destination)
        return {"ok": True, "routes": [{
            "distance_m": 8200, "duration_s": 2400,
            "steps": [{"instruction": "乘坐公交1路", "vehicle": "公交1路"}]}]}

    monkeypatch.setattr(baidu_mod, "direction", fake_direction)


def test_attach_shop_routes_quota_and_determinism(monkeypatch):
    """每美食只给清单序前 N 家 matched 商铺挂线；未核验/缺坐标行不消耗配额、不发调用。"""
    calls = []
    _fake_baidu_channel(monkeypatch, calls)
    rows = [_shop("甲", "乳扇"), _shop("乙", "乳扇"), _shop("丙", "乳扇"),
            _shop("丁", "饵丝", matched=False), _shop("戊", "米线", lat=None)]
    n = asyncio.run(O._attach_shop_routes("大理", [{"destination": "大理", "items": rows}], 2))
    assert n == 2
    assert [x["name"] for x in rows if x.get("routes")] == ["甲", "乙"], "按清单序取前 2，可复现"
    assert len(calls) == 2, "direction 调用数必须等于配额内实体数"
    r = rows[0]["routes"][0]
    assert r["mode"] == "公交/地铁" and "自市中心出发" in r["note"] and "8.2公里" in r["note"]
    assert r["duration"] == "约40分钟" and r["transfer"] == "公交1路"


def test_attach_shop_routes_degrades_without_ak_or_anchor(monkeypatch):
    """缺 AK / 目的地锚点地理编码失败 → 返回 0 且零调用，商铺清单照常（占位降级）。"""
    monkeypatch.setattr(baidu_mod, "available", lambda: False)
    rows = [_shop("甲", "乳扇")]
    assert asyncio.run(O._attach_shop_routes("大理", [{"destination": "大理", "items": rows}], 2)) == 0
    assert "routes" not in rows[0]

    monkeypatch.setattr(baidu_mod, "available", lambda: True)
    monkeypatch.setattr(baidu_mod, "geocode", lambda address, city="": {"ok": False, "reason": "超时"})
    calls = []
    monkeypatch.setattr(baidu_mod, "direction",
                        lambda *a, **k: calls.append(a) or {"ok": False})
    assert asyncio.run(O._attach_shop_routes("大理", [{"destination": "大理", "items": rows}], 2)) == 0
    assert calls == [], "锚点拿不到时不得继续烧 direction 配额"


def test_attach_shop_routes_zero_topn_short_circuits(monkeypatch):
    """topn=0（quick 档）直接短路：即便 AK 可用也不发任何百度调用。"""
    def boom(*a, **k):
        raise AssertionError("不应触达百度通道")

    monkeypatch.setattr(baidu_mod, "available", boom)
    rows = [_shop("甲", "乳扇")]
    assert asyncio.run(O._attach_shop_routes("大理", [{"destination": "大理", "items": rows}], 0)) == 0


# ── M3a · 一页视图逐日组装（纯函数：确定性 + 实体引用完整性）──
@pytest.mark.parametrize("text,days", [
    ("大理 5 天亲子游攻略", 5), ("我想去玩三天", 3), ("两周日程", 0),
    ("周末去走走", 2), ("十天环岛", 10), ("二十天", 20), ("十五天", 15),
    ("没有天数的一句话", 0),
    # 现状刻画：中文数词只配「天」进准绳正则，「十日」暂不计为 10（数字写法「10日」可以）。
    ("十日环岛", 0),
])
def test_days_count_from_user_text(text, days):
    assert O._days_count(text) == days


def _spot_row(i, **kw):
    row = {"spot_id": f"大理_spot_{i}", "name": f"景点{i}", "area": "城区",
           "lat": 25.5 + i * 0.25, "lng": 100.0 + i * 0.5,
           "stay_minutes": 120 + i, "ticket": "免费", "off_peak": "工作日上午",
           "evidence_ids": ["e_aaaaaaaa"]}
    row.update(kw)
    return row


def _route_groups(ids):
    return [{"destination": "大理", "items": [
        {"spot_id": i, "spot_name": "", "routes": [
            {"mode": "公交/地铁", "duration": "约40分钟", "transfer": "公交1路",
             "cost": "", "note": "自市中心出发", "evidence_ids": []}]} for i in ids]}]


def test_assemble_itinerary_covers_frozen_ids_once_and_keeps_rank_order():
    spots = [_spot_row(i) for i in range(1, 11)]
    shops = [{"destination": "大理", "items": [
        {"shop_id": "大理_shop_1", "name": "甲店", "food": "乳扇", "price_per_person": 58,
         "queue_note": "饭点排队", "evidence_ids": ["e_bbbbbbbb"]},
        {"shop_id": "大理_shop_2", "name": "乙店", "food": "饵丝"}]}]
    out = O._assemble_itinerary("大理", spots, _route_groups([r["spot_id"] for r in spots]),
                                shops, days=0, pace=4)
    assert out[0]["destination"] == "大理"
    days = out[0]["days"]
    assert [d["day"] for d in days] == [1, 2, 3], "10 景点 pace=4 → 3 天（4/4/2）"
    stops = [s for d in days for s in d["spots"]]
    ref = [s["spot_id"] for s in stops if s["spot_id"]]
    assert ref == [f"大理_spot_{i}" for i in range(1, 11)], "按榜单名次保序、每实体恰好出现一次"
    assert {s["shop_id"] for s in stops if s["shop_id"]} == {"大理_shop_1", "大理_shop_2"}, "商铺逐日挂接"
    t = next(s for s in stops if s["spot_id"] == "大理_spot_1")
    assert t["transport"] == "公交：公交1路·约40分钟" and t["duration"] == "约121分钟"
    assert t["lat"] == 25.75 and t["lng"] == 100.5, "N6：冻结实体坐标随挂接透传"
    assert "免费" in t["tip"] and "工作日上午" in t["tip"]
    food = next(s for s in stops if s["shop_id"] == "大理_shop_1")
    assert "58元（参考）" in food["tip"] and "饭点排队" in food["tip"]
    assert "lat" not in food, "美食停靠不注入坐标（商铺非分布图点位）"
    # 确定性：同输入两次组装结果全等
    assert out == O._assemble_itinerary("大理", spots, _route_groups([r["spot_id"] for r in spots]),
                                        shops, days=0, pace=4)


def test_assemble_itinerary_days_from_user_and_degradations():
    spots = [_spot_row(i) for i in (1, 2)]
    out = O._assemble_itinerary("大理", spots, [], [], days=5, pace=4)
    assert [d["day"] for d in out[0]["days"]] == [1, 2], "天数不超实体数，不造空天"
    assert out[0]["days"][0]["spots"][0]["transport"] == "", "无真实路线数据时交通留空（占位不编造）"
    assert O._assemble_itinerary("大理", [], [], [], days=3, pace=4) == []


# ── orchestrator._extract_spot_signals 降级（TC-B03 单元面）──
class _Ev:
    """最小 Evidence 替身：只覆盖 _evidence_digest 读取的字段。"""
    evidence_id = "e_aaaaaaaa"
    source_type = "web"
    source_url = "https://x.example.com/1"
    title = "证据"
    excerpt = "正文" * 40


def test_signal_extraction_swallows_llm_failure(monkeypatch):
    """LLM 不可用（异常/超时）→ 空表而非抛出：spots 阶段降级、任务照跑完。"""
    def boom(*a, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(O, "chat_json", boom)
    assert O._extract_spot_signals("q", ["大理"], ["f"], [_Ev()], 4, "fast") == []


def test_signal_extraction_drops_nameless_and_filters_eids(monkeypatch):
    seen = {}

    def fake(messages, **kw):
        seen["purpose"] = kw.get("purpose")
        seen["user"] = messages[-1]["content"]
        return {"spots": [_spot("古城"), {"signals": {}}, None]}
    monkeypatch.setattr(O, "chat_json", fake)
    out = O._extract_spot_signals("大理攻略", ["大理"], ["景点"], [_Ev()], 4, "fast")
    assert seen["purpose"] == "景点信号抽取（TopN 实体候选）"
    assert "[e_aaaaaaaa|" in seen["user"], "提示词必须携带真实证据 id（无证据不立论）"
    assert [r["name"] for r in out] == ["古城"]
    assert out[0]["evidence_ids"] == ["e_aaaaaaaa"], "伪造证据 id 不得进入实体行"


def test_signal_extraction_accepts_bare_list(monkeypatch):
    """LLM 直接返回列表（无 spots 包装）也要接住——形状漂移不该清空实体表。"""
    monkeypatch.setattr(O, "chat_json", lambda m, **k: [_spot("古城")])
    out = O._extract_spot_signals("q", ["大理"], [], [_Ev()], 4, "fast")
    assert [r["name"] for r in out] == ["古城"]


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))


# ── brisk-pond-finch L2 · trunc_report 线程内传回通道（LT-3 / LT-7 单元面）──
def test_signals_trunc_report_true_only_when_length_and_empty(monkeypatch):
    monkeypatch.setattr(O, "chat_json", lambda *a, **k: None)
    monkeypatch.setattr(O, "last_finish_reason", lambda: "length")
    rep: list = []
    assert O._extract_spot_signals("q", ["大理"], ["f"], [_Ev()], 4, "fast",
                                   trunc_report=rep) == []
    assert rep == [True], "截断实锤（finish=length 且产物空）必须在线程内求值传回"
    monkeypatch.setattr(O, "last_finish_reason", lambda: "stop")
    rep2: list = []
    O._extract_spot_signals("q", ["大理"], ["f"], [_Ev()], 4, "fast", trunc_report=rep2)
    assert rep2 == [False], "模型真没数据（finish=stop）不报截断——防误报"


def test_signals_llm_exception_is_not_truncation(monkeypatch):
    """LT-7：TC-B03 吞异常语义保持（不抛、空表），但异常≠截断，不得误触发降级文案。"""
    def boom(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr(O, "chat_json", boom)
    rep: list = []
    assert O._extract_spot_signals("q", ["大理"], ["f"], [_Ev()], 4, "fast",
                                   trunc_report=rep) == []
    assert rep == [False]


def test_analyze_structured_trunc_report(monkeypatch):
    monkeypatch.setattr(O, "chat_json", lambda *a, **k: None)
    monkeypatch.setattr(O, "last_finish_reason", lambda: "length")
    rep: list = []
    out = O._analyze_structured("q", ["大理"], ["f"], [], "guide", trunc_report=rep)
    assert rep == [True] and all(not v for v in out.values())
    monkeypatch.setattr(O, "last_finish_reason", lambda: "stop")
    rep2: list = []
    O._analyze_structured("q", ["大理"], ["f"], [], "guide", trunc_report=rep2)
    assert rep2 == [False]
