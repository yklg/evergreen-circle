"""配置契约测试（test-coverage-expander 方案 B-07 + 执行计划 G10）。

契约（G10 收敛后）：
- 配置单一真相源 = CONFIG_SCHEMA：每个键必须能在 Settings 上 getattr，类型标签与实际默认值类型一致；
- demo 兜底语义已收敛：`enable_demo_fallback` 既不存于 CONFIG_SCHEMA 也不存于 Settings（防复辟回归）；
- DB 覆盖 > env 默认：set_setting → invalidate_cache → get_effective_settings 立即生效（热更新）；
- 损坏覆盖值（类型转换失败）整值回落 env 默认，不拖垮全局；
- 未知键写入被忽略；类型错误整包失败抛 SettingsValidationError；密钥空串=保留原值；
- SECRET_KEYS ⊂ CONFIG_SCHEMA 且类型为 str（脱敏语义成立）；
- mask_effective 对全部密钥脱敏（含值）且非密钥字段原样透传。

运行：backend/ 下 `pytest tests/test_config_contract.py -q`
"""
import pytest

import app.core.db as db
import app.core.runtime_config as rc
from app.core.config import get_settings


def _fresh_eff():
    """清缓存后重读有效配置（避免用例间缓存串扰）。"""
    rc.invalidate_cache()
    return rc.get_effective_settings()


# ── B-07-1：demo 兜底收敛（G10 落地断言，防复辟）─────────
def test_demo_fallback_knob_removed():
    """G10：enable_demo_fallback 应从 schema 与 Settings 中移除（未落地的死配置铃）。"""
    assert "enable_demo_fallback" not in rc.CONFIG_SCHEMA, "死配置铃应被收敛删除"
    assert not hasattr(get_settings(), "enable_demo_fallback"), "Settings 不应再有该字段"
    # 存量 DB 覆盖值是惰性攻击：不再进入有效配置
    db.set_setting("enable_demo_fallback", "false")
    eff = _fresh_eff()
    assert "enable_demo_fallback" not in eff, "存量 DB 行不得重新进入有效配置"


# ── B-07-2：Schema 单一真相源 ───────────────────────────
def test_schema_keys_valid_against_settings():
    """每个 schema 键都能从 Settings getattr；空 schema 即失败。"""
    settings = get_settings()
    assert rc.CONFIG_SCHEMA, "CONFIG_SCHEMA 不应为空"
    for key, meta in rc.CONFIG_SCHEMA.items():
        assert hasattr(settings, key), f"schema 键 {key} 在 Settings 上不存在"


def test_schema_type_label_matches_default_type():
    """类型标签与实际默认值类型一致（str/int/float/bool 不漂移）。"""
    settings = get_settings()
    for key, meta in rc.CONFIG_SCHEMA.items():
        default = getattr(settings, key)
        if meta["type"] == "str":
            assert isinstance(default, str), f"{key} 默认应为 str，实际 {type(default).__name__}"
        elif meta["type"] == "int":
            assert isinstance(default, int) and not isinstance(default, bool), f"{key} 默认应为 int"
        elif meta["type"] == "float":
            assert isinstance(default, float), f"{key} 默认应为 float"
        elif meta["type"] == "bool":
            assert isinstance(default, bool), f"{key} 默认应为 bool"
        else:
            raise AssertionError(f"{key} 存在未知类型标签 {meta['type']}")


def test_secret_keys_subset_of_schema_str():
    """SECRET_KEYS ⊂ CONFIG_SCHEMA，且全部为 str 类型。"""
    missing = [k for k in rc.SECRET_KEYS if k not in rc.CONFIG_SCHEMA]
    assert not missing, f"SECRET_KEYS 游离于 schema：{missing}"
    bad_type = [k for k in rc.SECRET_KEYS if rc.CONFIG_SCHEMA[k]["type"] != "str"]
    assert not bad_type, f"密钥键类型应为 str：{bad_type}"


def test_effective_settings_returns_stable_structure():
    """get_effective_settings 返回稳定结构：仅含 schema 键，无未知残留。"""
    eff = _fresh_eff()
    assert set(eff.keys()) == set(rc.CONFIG_SCHEMA.keys())
    assert isinstance(eff, dict)
    # 返回浅拷贝：改返回结果不污染缓存
    eff["llm_timeout"] = 999.0
    assert rc.get_effective_settings()["llm_timeout"] != 999.0


# ── B-07-3：DB 覆盖生效 + 热更新 ────────────────────────
def test_db_override_effective_and_hot_update():
    """set_setting + invalidate → 立即生效（float 还原）；cache_version 递增。"""
    v_before = rc.cache_version()
    db.set_setting("llm_timeout", "60")
    rc.invalidate_cache()
    eff = rc.get_effective_settings()
    assert eff["llm_timeout"] == 60.0, "DB 覆盖（float 还原）应生效"
    assert rc.cache_version() > v_before, "invalidate 后版本应递增"


def test_bool_coerce_semantics():
    """_coerce bool 语义：1/true/yes/on → True；0/false/no/off → False；非法抛 ValueError。"""
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        assert rc._coerce("k", truthy, "bool") is True
    for falsy in ("0", "false", "False", "no", "off"):
        assert rc._coerce("k", falsy, "bool") is False
    with pytest.raises(ValueError):
        rc._coerce("k", "maybe", "bool")


def test_broken_override_falls_back_to_env_default():
    """DB 覆盖值类型损坏（手工改库）→ 整值回落 env 默认，不拖垮全局。"""
    db.set_setting("llm_timeout", "not-a-number")
    eff = _fresh_eff()
    assert eff["llm_timeout"] == get_settings().llm_timeout
    # 其它键不受影响
    assert "llm_model" in eff


# ── B-07-4：apply_settings 校验语义 ─────────────────────
def test_apply_unknown_key_ignored():
    """未知键被忽略（不报错、不落库），兼容旧前端残留。"""
    rc.invalidate_cache()
    out = rc.apply_settings({"definitely_not_a_key": 1})
    assert "definitely_not_a_key" not in out
    assert db.get_all_settings().get("definitely_not_a_key") is None


def test_apply_type_error_whole_patch_fails():
    """类型错误整包失败（SettingsValidationError），合法键也不落库。"""
    rc.invalidate_cache()
    with pytest.raises(rc.SettingsValidationError):
        rc.apply_settings({"llm_timeout": "abc", "llm_max_retries": "3"})
    assert db.get_all_settings().get("llm_max_retries") is None, "整包失败：任何键都不应落库"


def test_apply_secret_empty_string_preserved():
    """密钥空串 = 不修改（保留原值）。"""
    before = db.get_all_settings()
    before.get("llm_api_key")  # 可能为 None
    out = rc.apply_settings({"llm_api_key": ""})
    assert out["llm_api_key"] == get_settings().llm_api_key
    assert db.get_all_settings().get("llm_api_key") is None, "空串不应写入覆盖表"


def test_mask_effective_masks_all_secrets():
    """mask_effective：全部密钥脱敏（含值），非密钥原样透传。"""
    eff = _fresh_eff()
    masked = rc.mask_effective(eff)
    for k in rc.SECRET_KEYS:
        m = str(masked[k])
        assert m == "" or "****" in m, f"{k} 应被脱敏（未配置为空串，已配置含 ****），实际 {m!r}"
    # 非密钥透传
    assert masked["llm_timeout"] == eff["llm_timeout"]


# ── B-07-5：百度日预算开关默认禁用（R7e / ②）──────────────
def test_baidu_daily_quota_default_zero_disabled():
    """G10：``baidu_daily_quota`` 默认 0 = 禁用日预算约束（零行为变化、向后兼容）。

    这是 R7 的「安全阀」契约：日预算必须**显式开启**（.env 设正整数）才会约束调用，
    默认禁用确保现有部署不会因为新增开关而误熔断、误降级。
    """
    s = get_settings()
    assert hasattr(s, "baidu_daily_quota"), "Settings 必须存在 baidu_daily_quota 字段"
    assert isinstance(s.baidu_daily_quota, int) and not isinstance(s.baidu_daily_quota, bool)
    assert s.baidu_daily_quota == 0, "默认必须为 0（禁用），避免低额度 AK 被默认熔断"
    # _default_guard 据此构造的 GlobalDailyBudget 必须 exhausted 永 False（无害）
    from app.living_circle.request_guard import get_daily_budget
    budget = get_daily_budget("g10-ak", s.baidu_daily_quota)
    budget.consume(1)
    assert budget.exhausted is False, "cap=0 时 consume 不得触发熔断"
    assert budget.calls == 0, "cap=0 时 consume 为 no-op（不计数）"