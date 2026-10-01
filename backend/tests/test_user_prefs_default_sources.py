"""默认引用清单进偏好层（实施计划 v3 §二 B7 · §八 A-5 的修法本体 / TC-31 族）。

守护的契约
----------
`intel.defaultSources` 是**参与业务计算的结构化数据**（下次建任务时并入清单），
不是字符串偏好。§一 A-5 的结论：偏好层必须加真 `list[str]` 类型 + 条数/单条双上限，
而不是把 JSON blob 塞进一个 `str` 键 —— 后者会把偏好层变成通用 blob，
而且 128 字符的上限根本装不下 10 条网址。

四条硬判据：
  1. **类型往返**：写数组 → 库里是 JSON 文本 → 读回还是数组（不是 Python repr 串）。
  2. **上限是拒绝而不是截断**：`_validate_len` 家族的本性是"不静默改坏用户数据"，
     清单同理（11 条必须报错点名，不能悄悄留 10 条）。
     这与任务入口的"截断并回报"是两种语义：入口是"你填了我就按上限用并告诉你"，
     偏好是"存不下就别存"。
  3. **整键隔离**：清单键被拒**不连坐** `profile.name` / `profile.company`（§四.10），
     但也不能静默收下（静默会让前端 pending 重推逻辑以为已保存）。
     标量键的整包失败语义**不变** —— 两套语义各守各的场景，不是漏实现。
  4. **边界是 `>` 不是 `>=`**：正好等于上限必须通过。

期望值来源
----------
`max_items` / `item_max_len` 取自 `PREF_SCHEMA[KEY]`（import，不抄数）；
标量键既有语义由 `tests/test_user_prefs.py` 守着，本文件不重复。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.core.db as db
from app.core.user_prefs import (
    PREF_SCHEMA, PrefsValidationError, apply_prefs, get_prefs,
)
from app.main import app

client = TestClient(app)

KEY = "intel.defaultSources"


# ── 1. 类型与往返 ──────────────────────────────────────────────────

def test_default_sources_is_declared_as_a_typed_list_not_a_string_blob():
    meta = PREF_SCHEMA[KEY]
    assert meta["type"] == "list[str]", "清单退化回 str blob ⇒ A-5 的修法被回退"
    assert meta["group"] == "intel", meta
    assert meta["max_items"] == 10 and meta["item_max_len"] == 256


def test_round_trip_through_the_prefs_table_stays_a_list():
    stored = apply_prefs({KEY: ["https://a.gov.cn/1", "https://b.gov.cn/2"]})
    assert stored[KEY] == ["https://a.gov.cn/1", "https://b.gov.cn/2"]
    raw = db.get_prefs_all()[KEY]
    assert isinstance(raw, str) and json.loads(raw) == stored[KEY], raw
    assert get_prefs()[KEY] == stored[KEY]


def test_python_repr_never_reaches_the_database():
    """`str([...])` 会把单引号写进库里，读回来就是坏 JSON。钉住落库形态是 JSON。"""
    apply_prefs({KEY: ["https://a.gov.cn/1"]})
    raw = db.get_prefs_all()[KEY]
    assert "'" not in raw and raw.startswith("["), raw
    json.loads(raw)      # 解析不了即红


def test_empty_list_round_trips_as_empty_list_not_absent_key():
    """清空是"存了空清单"，与"从没存过这个键"是两件事：
    `get_prefs()` 只返回库里存在的键（前端据此判定是否首次启动）。"""
    values = apply_prefs({KEY: []})
    assert values[KEY] == []
    assert KEY in db.get_prefs_all(), "清空被存成删键 ⇒ 前端会把空清单误判成新库"


def test_none_is_a_legal_way_to_clear_the_manifest():
    assert apply_prefs({KEY: None})[KEY] == []


def test_http_layer_returns_real_arrays_for_typed_list_keys():
    body = client.put("/api/prefs", json={"patch": {KEY: ["https://x.gov.cn/a"]}}).json()
    assert body["values"][KEY] == ["https://x.gov.cn/a"]
    assert KEY in body["stored"]
    assert client.get("/api/prefs").json()["values"][KEY] == ["https://x.gov.cn/a"]


def test_group_listing_is_derived_from_the_schema():
    """GROUP_PREFS 由 schema 自动派生：前端按域渲染时 intel 组必须带上新键。"""
    assert KEY in client.get("/api/prefs").json()["groups"]["intel"]


# ── 2. 双上限：拒绝而非截断 ────────────────────────────────────────

def test_too_many_items_is_rejected_and_nothing_is_stored():
    raws = [f"https://s{i}.gov.cn/doc" for i in range(PREF_SCHEMA[KEY]["max_items"] + 1)]
    with pytest.raises(PrefsValidationError) as exc:      # 调用方没给收集口 ⇒ 必须抛，不能吞
        apply_prefs({KEY: raws})
    msg = exc.value.errors[KEY]
    assert "10" in msg and "11" in msg, msg
    assert KEY not in get_prefs(), "超限必须整键不写，不能留半份清单"


def test_over_long_item_is_rejected_and_named_by_ordinal():
    long_item = "https://x.gov.cn/" + "a" * PREF_SCHEMA[KEY]["item_max_len"]
    errors: dict = {}
    values = apply_prefs({KEY: [long_item, "https://ok.gov.cn/1"]}, key_errors_out=errors)
    assert KEY in errors and "第 1 条" in errors[KEY], errors
    assert KEY not in values


def test_the_second_offending_item_is_named_as_the_second_one():
    """点名必须是**那一条**，不是笼统一句"超长"——用户看不到第几条就无从修。"""
    long_item = "https://y.gov.cn/" + "b" * PREF_SCHEMA[KEY]["item_max_len"]
    errors: dict = {}
    apply_prefs({KEY: ["https://ok.gov.cn/1", long_item]}, key_errors_out=errors)
    assert "第 2 条" in errors[KEY], errors


def test_boundary_values_at_the_limit_are_accepted():
    """边界判据是 `>` 不是 `>=`：正好 max_items 条、每条正好 item_max_len 字符必须通过。"""
    meta = PREF_SCHEMA[KEY]
    at_len = "u" * meta["item_max_len"]
    assert apply_prefs({KEY: [at_len]})[KEY] == [at_len], "等于 item_max_len 被拒 ⇒ 边界写成了 >="

    exactly_max = [f"https://s{i}.gov.cn" for i in range(meta["max_items"])]
    assert len(apply_prefs({KEY: exactly_max})[KEY]) == meta["max_items"], "等于 max_items 被拒"


# ── 3. 形状错误与整键隔离 ──────────────────────────────────────────

@pytest.mark.parametrize("bad", ["不是数组", 12, {"a": 1}, ["https://ok", 5], [None]])
def test_wrong_shapes_are_rejected_rather_than_stringified(bad):
    """形状错必须点名，不能被 `str()` 兜成怪值（"['https://ok', None]" 落库后读不回来）。"""
    errors: dict = {}
    values = apply_prefs({KEY: bad}, key_errors_out=errors)
    assert KEY in errors, f"{bad!r} 被照单收下而不是被拒：{values}"
    assert KEY not in values


def test_a_bad_list_key_does_not_block_the_other_keys_from_being_written():
    """计划 §四.10：清单里有非法条目 ⇒ 只有该键被拒，昵称/公司仍写入。"""
    long_item = "https://y.gov.cn/" + "b" * 300
    errors: dict = {}
    values = apply_prefs({KEY: [long_item], "profile.name": "阿明",
                          "profile.company": "合规公司"}, key_errors_out=errors)

    assert set(errors) == {KEY}, f"错误面被扩大到了别的键：{sorted(errors)}"
    saved = get_prefs()
    assert saved.get("profile.name") == "阿明", saved
    assert saved.get("profile.company") == "合规公司", saved
    assert KEY not in saved, "被拒的清单整键不写"
    assert values.get("profile.name") == "阿明"


def test_scalar_key_errors_still_take_the_whole_batch_down():
    """标量键的整包失败语义**不变**：一个非法 bool 不能让别的键半写落库。"""
    with pytest.raises(PrefsValidationError):
        apply_prefs({"ui.sidebarCollapsed": "maybe", "profile.name": "不该落库"})
    assert get_prefs() == {}, get_prefs()


def test_unknown_keys_are_still_ignored():
    apply_prefs({"definitely_not_a_pref": "x", KEY: ["https://a.gov.cn/1"]})
    assert "definitely_not_a_pref" not in db.get_prefs_all()
    assert KEY in get_prefs()


# ── 4. HTTP 面 ─────────────────────────────────────────────────────

def test_http_surface_reports_list_rejection_as_200_plus_key_errors():
    long_item = "https://z.gov.cn/" + "c" * 300
    res = client.put("/api/prefs", json={"patch": {KEY: [long_item], "profile.name": "小王"}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and set(body["key_errors"]) == {KEY}, body
    assert get_prefs().get("profile.name") == "小王", get_prefs()
    assert KEY not in get_prefs()


def test_http_surface_omits_key_errors_when_everything_is_clean():
    body = client.put("/api/prefs", json={"patch": {KEY: ["https://clean.gov.cn/1"]}}).json()
    assert "key_errors" not in body, body
    assert body["values"][KEY] == ["https://clean.gov.cn/1"]


def test_http_surface_still_422s_a_scalar_error():
    res = client.put("/api/prefs", json={"patch": {"ui.sidebarCollapsed": "maybe",
                                                   "profile.name": "不该落库"}})
    assert res.status_code == 422, res.text
    assert set(res.json()["detail"]["errors"]) == {"ui.sidebarCollapsed"}


# ── 5. 与任务入口的分工 ────────────────────────────────────────────

def test_prefs_layer_does_not_duplicate_the_entry_point_url_hygiene():
    """偏好层只守形状；归一/去重/协议白名单属于入口卫生（`fetcher.normalize_user_url_list`）。

    钉这条不是为了"允许脏数据"，而是防**两处各写一份判据**：默认清单在建任务时会被
    入口层归一并**可见地**拒掉脏条目，所以偏好层不需要提前替它决定；若两处各写一份，
    改了入口忘了改偏好，同一条网址会在两个地方得到两种结论。
    """
    from app.core.fetcher import normalize_user_url_list

    values = apply_prefs({KEY: ["file:///etc/passwd", "example.com/doc"]})
    assert values[KEY] == ["file:///etc/passwd", "example.com/doc"], "偏好层不该改内容"

    cleaned = normalize_user_url_list(values[KEY])
    assert cleaned["urls"] == ["https://example.com/doc"]
    assert [r["url"] for r in cleaned["rejected"]] == ["file:///etc/passwd"]
