"""用户级偏好（prefs）契约测试。

契约来源：《用户设置持久化架构修复计划》§3.1 / §7。
被测对象：`core/user_prefs.py`（域层）+ `db.py` 的 prefs 存储（存储层）+ `/api/prefs`（传输层）。

覆盖维度（等价类 / 边界 / 异常分支 / 状态迁移 / 不变量）：
- **首次判定契约**（最关键）：空库时 `get_prefs()` 必须返回 `{}`、`stored == []`
  —— 前端靠它区分「远端为空 → 保留本地并上推」与「远端有值 → 远端为准」。
  若此处填充默认值，存量本地资料会被默认值覆盖（真实数据丢失）。
- 类型往返：str / bool 落库 → 还原类型不漂移。
- 异常分支：未知键忽略、类型错整包失败、非法 bool、超长、总体积超限。
- 状态迁移：重复写入幂等（覆盖而非追加）、delete_pref 后回落。
- 不变量：**明文不脱敏**（与 settings 的 SECRET_KEYS 语义严格区分）；坏键不拖垮全局。
- 写入原子性：整包校验失败时任何键都不落库（不做半写）。

运行：backend/ 下 `pytest tests/test_user_prefs.py -q`
"""
import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core import user_prefs as up
from app.main import app


# ── 首次判定契约（前端「是否首次」的硬依赖）───────────────
def test_empty_db_returns_no_keys_and_empty_stored():
    """空库：values == {} 且 stored == []。前端据此判定「远端为空」。"""
    assert up.get_prefs() == {}
    doc = up.prefs_doc()
    assert doc["values"] == {}
    assert doc["stored"] == []


def test_partial_provision_is_visible_but_not_filled_with_defaults():
    """只写了 1 个键 → 只回 1 个键，绝不合成其余键的默认值。"""
    up.apply_prefs({"profile.name": "李工"})
    assert up.get_prefs() == {"profile.name": "李工"}
    assert up.prefs_doc()["stored"] == ["profile.name"]


# ── 类型往返 ────────────────────────────────────────────
def test_type_roundtrip_str_and_bool():
    up.apply_prefs({"profile.name": "王研究员", "profile.company": "某科技", "ui.sidebarCollapsed": True})
    got = up.get_prefs()
    assert got["profile.name"] == "王研究员"
    assert got["profile.company"] == "某科技"
    assert got["ui.sidebarCollapsed"] is True, "bool 必须还原为 bool，不能留字符串"

    up.apply_prefs({"ui.sidebarCollapsed": False})
    assert up.get_prefs()["ui.sidebarCollapsed"] is False


def test_bool_string_forms_accepted():
    """字符串形态的布尔（前端可能传 "true"/"false"）也应被接受。"""
    up.apply_prefs({"ui.sidebarCollapsed": "true"})
    assert up.get_prefs()["ui.sidebarCollapsed"] is True
    up.apply_prefs({"ui.sidebarCollapsed": "off"})
    assert up.get_prefs()["ui.sidebarCollapsed"] is False


def test_ui_model_roundtrip():
    up.apply_prefs({"ui.model": "deepseek-flash"})
    assert up.get_prefs()["ui.model"] == "deepseek-flash"


# ── 异常分支 ────────────────────────────────────────────
def test_unknown_key_ignored_and_not_persisted():
    """未知键被忽略（跨版本兼容），且绝不落库。"""
    up.apply_prefs({"definitely_not_a_pref": "x", "profile.name": "A"})
    assert db.get_prefs_all().get("definitely_not_a_pref") is None
    assert up.get_prefs() == {"profile.name": "A"}


def test_type_error_fails_whole_patch_and_writes_nothing():
    """整包失败：非法 bool 与合法键同批提交 → 合法键也不落库（不做半写）。"""
    with pytest.raises(up.PrefsValidationError) as exc:
        up.apply_prefs({"ui.sidebarCollapsed": "maybe", "profile.name": "不该落库"})
    assert "ui.sidebarCollapsed" in exc.value.errors
    assert db.get_prefs_all() == {}, "整包失败时任何键都不应落库"


def test_over_length_rejected_without_silent_truncation():
    """超长直接拒绝（不静默截断——截断会悄悄改坏用户数据）。"""
    long_name = "名" * (up.PREF_SCHEMA["profile.name"]["max_len"] + 1)
    with pytest.raises(up.PrefsValidationError) as exc:
        up.apply_prefs({"profile.name": long_name})
    assert "profile.name" in exc.value.errors
    assert db.get_prefs_all() == {}
    # 正好卡在上限应通过
    at_limit = "名" * up.PREF_SCHEMA["profile.name"]["max_len"]
    up.apply_prefs({"profile.name": at_limit})
    assert up.get_prefs()["profile.name"] == at_limit


def test_total_size_cap(monkeypatch):
    """总体积上限：把上限压到极小值，验证整包被拒且不落库。"""
    monkeypatch.setattr(up, "MAX_PREFS_BYTES", 4)
    with pytest.raises(up.PrefsValidationError):
        up.apply_prefs({"profile.name": "abcd", "profile.company": "efgh"})
    assert db.get_prefs_all() == {}


def test_non_dict_patch_rejected():
    with pytest.raises(up.PrefsValidationError):
        up.apply_prefs(["not", "a", "dict"])  # type: ignore[arg-type]


# ── 状态迁移 / 幂等 ─────────────────────────────────────
def test_repeated_write_is_idempotent_overwrite():
    up.apply_prefs({"profile.name": "A"})
    up.apply_prefs({"profile.name": "B"})
    assert up.get_prefs()["profile.name"] == "B"
    assert len(db.get_prefs_all()) == 1, "重复写应是覆盖而非追加"


def test_delete_pref_falls_back_to_absent():
    up.apply_prefs({"profile.name": "A", "profile.company": "C"})
    db.delete_pref("profile.name")
    got = up.get_prefs()
    assert "profile.name" not in got
    assert got["profile.company"] == "C"


def test_clear_prefs_empties_everything():
    up.apply_prefs({"profile.name": "A", "ui.model": "m"})
    db.clear_prefs()
    assert up.get_prefs() == {}


# ── 不变量 ──────────────────────────────────────────────
def test_broken_row_skipped_not_fatal():
    """坏行（手工改库把 bool 写成非法值）→ 跳过该键，其余照常返回。"""
    db.set_prefs({"profile.name": "正常", "ui.sidebarCollapsed": "maybe"})
    got = up.get_prefs()
    assert got["profile.name"] == "正常"
    assert "ui.sidebarCollapsed" not in got, "损坏键应被跳过而不是让整包失败"


def test_unknown_row_in_db_not_exposed():
    """库中残留的未知键（旧版本写入）不得进入有效偏好。"""
    db.set_prefs({"legacy.stale": "x"})
    assert up.get_prefs() == {}


def test_prefs_are_plaintext_unlike_settings_secrets():
    """语义边界断言：prefs 明文原样返回，不走 settings 的脱敏通道。"""
    from app.core import runtime_config as rc

    up.apply_prefs({"profile.name": "林研究员"})
    assert up.get_prefs()["profile.name"] == "林研究员", "prefs 不得被脱敏"
    # 反向对照：settings 侧确实存在脱敏语义（防未来有人把两表合一）
    assert rc.SECRET_KEYS, "settings 侧密钥脱敏语义应仍存在"


# ── 传输层：/api/prefs ──────────────────────────────────
def test_api_get_empty_shows_stored_empty():
    c = TestClient(app)
    r = c.get("/api/prefs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["values"] == {}
    assert body["stored"] == []
    assert "profile" in body["groups"] and "ui" in body["groups"]


def test_api_put_then_get_roundtrip():
    c = TestClient(app)
    r = c.put("/api/prefs", json={"patch": {"profile.name": "赵分析师", "profile.company": "X Lab"}})
    assert r.status_code == 200
    assert r.json()["values"]["profile.name"] == "赵分析师"

    r2 = c.get("/api/prefs")
    assert r2.json()["values"] == {"profile.name": "赵分析师", "profile.company": "X Lab"}
    assert r2.json()["stored"] == ["profile.company", "profile.name"]


def test_api_put_validation_error_is_422_with_field_errors():
    c = TestClient(app)
    r = c.put("/api/prefs", json={"patch": {"ui.sidebarCollapsed": "maybe"}})
    assert r.status_code == 422
    assert "ui.sidebarCollapsed" in r.json()["detail"]["errors"]
    assert db.get_prefs_all() == {}


def test_api_put_empty_patch_is_noop_not_error():
    """空 patch（前端无改动时的兜底调用）应是幂等 no-op，不报错。"""
    c = TestClient(app)
    r = c.put("/api/prefs", json={"patch": {}})
    assert r.status_code == 200
    assert r.json()["values"] == {}
