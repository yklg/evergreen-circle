"""运行时可覆盖配置层（env 默认 + SQLite 覆盖）。

解决的问题（见「模型配置模块实施计划」RC1/RC2/RC3）：
- RC1：config.get_settings() 是 lru_cache 冻结单例，模块导入后不再读，
       导致「运行时改配置」没有通道。本层提供 get_effective_settings()，
       每次读都反映最新覆盖值（带可失效缓存，避免每次 chat() 读库）。
- RC3：覆盖值落 SQLite settings 表，进程重启后仍在。

优先级：**DB 覆盖 > env 默认**。DB 只存「用户在界面上改过的键」，
未改的键一律回落 env 默认值。

密钥安全（RC4）：get_effective_settings() 返回真实值，仅供服务端内部使用；
对外接口必须经 mask_effective() 脱敏后再返回。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from app.core import db
from app.core.config import get_settings

_logger = logging.getLogger(__name__)


class SettingsValidationError(ValueError):
    """配置校验失败（整包失败，含字段级 message）。

    由 main.py 捕获并转成 HTTP 422。core 层不依赖 FastAPI，保持分层纯净。
    """

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# ── 可配置键的单一真相源 ─────────────────────────────────
# 每项强制带 type / group；default 取自 env（Settings 的默认值），
# 此处不重复硬编码默认值，避免双源真相漂移。
CONFIG_SCHEMA: Dict[str, Dict[str, str]] = {
    # 提供方连接（厂商无关的 OpenAI 兼容连接；键名已在泛化后为 llm_*，
    # 旧名 zhipu_* 覆盖值由启动迁移 migrate_legacy_settings() 搬入）
    "llm_api_key":        {"type": "str",  "group": "provider"},
    "llm_base_url":       {"type": "str",  "group": "provider"},
    # 模型矩阵（按报告章节角色分配）
    "llm_model":          {"type": "str",  "group": "model_matrix"},
    "llm_model_core":     {"type": "str",  "group": "model_matrix"},
    "llm_model_aux":      {"type": "str",  "group": "model_matrix"},
    "llm_model_fast":     {"type": "str",  "group": "model_matrix"},
    # 推理参数（注意：temperature/max_tokens 是 chat() 的 per-call 参数，
    # 各调用点刻意用不同值（JSON 输出 0.3 / 创意生成 0.6），故不做全局配置，
    # 强行统一会破坏现有精细化设计。）
    "llm_timeout":        {"type": "float", "group": "params"},
    "llm_max_retries":    {"type": "int",   "group": "params"},
    # 搜索提供方
    "bocha_api_key":      {"type": "str",  "group": "search"},
    "bocha_base_url":     {"type": "str",  "group": "search"},
    "search_timeout":     {"type": "float", "group": "search"},
    # 澄清问卷：竞品发现超时（秒）与发现缓存 TTL（天）
    "clarify_discover_timeout_s": {"type": "float", "group": "params"},
    "discovery_cache_ttl_d":      {"type": "int",   "group": "params"},
    # 平台采集 Cookie
    "douyin_cookie":      {"type": "str",  "group": "platform"},
    "xhs_cookie":         {"type": "str",  "group": "platform"},
    "bilibili_cookie":    {"type": "str",  "group": "platform"},
}

# 密钥键：GET 时必须脱敏，永不明文返回前端
SECRET_KEYS = {
    "llm_api_key",
    "bocha_api_key",
    "douyin_cookie",
    "xhs_cookie",
    "bilibili_cookie",
}

# 分组 → 字段列表（供前端按组渲染表单）
GROUP_FIELDS: Dict[str, List[str]] = {}
for _k, _meta in CONFIG_SCHEMA.items():
    GROUP_FIELDS.setdefault(_meta["group"], []).append(_k)

# ── 键名泛化迁移（zhipu_* → llm_*）──────────────────────
# 旧键带厂商前缀，与「OpenAI 兼容多厂商」语义错位；新键厂商无关。
# DB 里可能残留旧版本在 settings 表存的覆盖值，启动时经 migrate_legacy_settings()
# 幂等搬入新键（见「模型配置键名泛化实施计划.md」）。
LEGACY_KEY_MAP: Dict[str, str] = {
    "zhipu_api_key": "llm_api_key",
    "zhipu_base_url": "llm_base_url",
    "zhipu_model": "llm_model",
    "zhipu_model_core": "llm_model_core",
    "zhipu_model_aux": "llm_model_aux",
    "zhipu_model_fast": "llm_model_fast",
}
_MIGRATED = False
_MIGRATE_LOCK = threading.Lock()

# 模型值迁移：预设从 V3 升级到 V4 时，已落库的旧模型名需在启动时升级，
# 避免「预设改了、存量值不跟着走」的漂移复发。仅精确命中旧名才改写，不碰用户自定义值。
LEGACY_MODEL_MAP: Dict[str, str] = {
    "deepseek-chat": "deepseek-v4-pro",
    "deepseek-reasoner": "deepseek-v4-flash",
}
_MODEL_MIGRATED = False


def migrate_legacy_settings() -> int:
    """把 settings 表遗留的 zhipu_* 覆盖值搬到 llm_*（进程内一次，幂等）。

    由 main.py lifespan 启动时显式调用（fail-fast：迁移失败即启动失败，不静默丢数据）。
    返回本次迁移键数；无旧键时 no-op 返回 0。
    """
    global _MIGRATED
    if _MIGRATED:
        return 0
    with _MIGRATE_LOCK:
        if _MIGRATED:
            return 0
        moved = db.migrate_settings(LEGACY_KEY_MAP)
        _MIGRATED = True
        return moved


def migrate_model_values() -> int:
    """把 settings 表遗留的旧版模型名升级到当前预设（幂等，进程内一次）。

    仅当 4 个模型字段值精确命中 LEGACY_MODEL_MAP 才改写，避免覆盖用户自定义值。
    由 main.py lifespan 启动调用。**best-effort**：模型名升级属非关键改进，
    失败仅记 warning 并返回 0，不向外抛（与键名迁移的严格 fail-fast 刻意区分）。
    """
    global _MODEL_MIGRATED
    if _MODEL_MIGRATED:
        return 0
    with _MIGRATE_LOCK:
        if _MODEL_MIGRATED:
            return 0
        try:
            eff = get_effective_settings()
            changed = 0
            for key in ("llm_model", "llm_model_core", "llm_model_aux", "llm_model_fast"):
                val = eff.get(key)
                if isinstance(val, str) and val in LEGACY_MODEL_MAP:
                    db.set_setting(key, LEGACY_MODEL_MAP[val])
                    changed += 1
            if changed:
                invalidate_cache()
            return changed
        except Exception:  # noqa: BLE001
            _logger.warning("模型值迁移跳过（非关键）", exc_info=True)
            return 0
        finally:
            _MODEL_MIGRATED = True


# ── 可失效内存缓存 ───────────────────────────────────────
# 避免每次 chat() 都读一次 DB；仅在配置变更（version 递增）时重算。
_EFF_CACHE: Optional[Dict[str, Any]] = None
_EFF_VERSION = 0
_EFF_LOCK = threading.RLock()


def _coerce(key: str, raw: str, typ: str) -> Any:
    """把 DB 里的字符串还原成声明的类型；失败抛 ValueError。"""
    if typ == "str":
        return raw
    if typ == "int":
        return int(str(raw).strip())
    if typ == "float":
        return float(str(raw).strip())
    if typ == "bool":
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        raise ValueError("必须是 true/false")
    raise ValueError(f"未知类型 {typ}")


def _build_effective() -> Dict[str, Any]:
    """合成 env 默认 + DB 覆盖。DB 优先。"""
    env = get_settings()
    overrides = db.get_all_settings()
    out: Dict[str, Any] = {}
    for key, meta in CONFIG_SCHEMA.items():
        if key in overrides:
            try:
                out[key] = _coerce(key, overrides[key], meta["type"])
                continue
            except Exception:
                # 单个键损坏（手工改库等）不应拖垮全局：回落 env 默认
                pass
        out[key] = getattr(env, key)
    return out


def get_effective_settings() -> Dict[str, Any]:
    """返回运行时有效配置（已合并 DB 覆盖）。带可失效缓存。"""
    global _EFF_CACHE
    with _EFF_LOCK:
        if _EFF_CACHE is None:
            _EFF_CACHE = _build_effective()
        # 返回浅拷贝，防止调用方改到缓存本体
        return dict(_EFF_CACHE)


def invalidate_cache() -> None:
    """配置变更后调用，下次 get_effective_settings() 重新合成。"""
    global _EFF_CACHE, _EFF_VERSION
    with _EFF_LOCK:
        _EFF_CACHE = None
        _EFF_VERSION += 1


def cache_version() -> int:
    with _EFF_LOCK:
        return _EFF_VERSION


def apply_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """校验 → 落库 → 失效缓存。

    - 未知键：忽略（不报错，兼容旧前端）。
    - 密钥空字符串：视为「不修改」，跳过（保留原值）。
    - 类型转换失败：**整包失败**，收集全部字段级错误后抛 SettingsValidationError。

    返回：落库后的有效配置（未脱敏，供内部使用）。
    """
    if not isinstance(patch, dict):
        raise SettingsValidationError({"patch": "必须是对象"})

    errors: Dict[str, str] = {}
    to_write: Dict[str, str] = {}

    for key, raw in patch.items():
        meta = CONFIG_SCHEMA.get(key)
        if meta is None:
            continue  # 忽略未知键
        # 密钥传空串 = 保留原值（前端密钥框留空即表示不改）
        if key in SECRET_KEYS and (raw is None or str(raw).strip() == ""):
            continue
        try:
            val = _coerce(key, "" if raw is None else str(raw), meta["type"])
        except Exception as e:
            errors[key] = f"类型错误（期望 {meta['type']}）：{e}"
            continue
        to_write[key] = str(val)

    if errors:
        raise SettingsValidationError(errors)

    for k, v in to_write.items():
        db.set_setting(k, v)

    # 末行失效：配置缓存 + LLM 客户端（客户端重建见 core/llm.py）
    invalidate_cache()
    try:
        from app.core.llm import invalidate_client

        invalidate_client()
    except Exception:
        pass

    return get_effective_settings()


def mask_secret(val: Any) -> str:
    """脱敏密钥：遮蔽中段，保留末 4 位便于用户核对。"""
    s = "" if val is None else str(val)
    if not s:
        return ""
    if len(s) <= 7:
        return "****"
    return f"{s[:3]}****{s[-4:]}"


def mask_effective(eff: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把有效配置脱敏后返回（供 GET /api/settings 使用）。"""
    eff = eff if eff is not None else get_effective_settings()
    return {k: (mask_secret(v) if k in SECRET_KEYS else v) for k, v in eff.items()}


def configured_flags(eff: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """各能力是否已配置（供状态条展示）。"""
    eff = eff if eff is not None else get_effective_settings()
    return {
        "llm": bool(eff.get("llm_api_key")),
        "bocha": bool(eff.get("bocha_api_key")),
    }
