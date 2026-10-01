"""用户级偏好域层（白名单 + 校验 + 语义）。

## 为什么需要这一层（与 runtime_config.py 的边界）

`settings` 表存的是**系统级运行时配置**：env 默认 + 运维覆盖，键受 CONFIG_SCHEMA
约束，对外 GET 必须脱敏（含 LLM/搜索密钥、平台 Cookie）。它有三条硬语义：
启动迁移（migrate_legacy_settings / migrate_model_values）、脱敏（mask_effective）、
"密钥空串=不修改"。

`prefs` 表存的是**用户级偏好**：昵称/公司/界面选择。它是明文、无密钥、原样返回、
不参与任何启动迁移。

两者强行合并会立刻产生互相误伤：脱敏会把用户昵称当密钥打码；启动迁移会改写用户
偏好；CONFIG_SCHEMA 作为"系统配置白名单"的语义也会被稀释。故**分表 + 分域层**
（见 db.py 模块 docstring 的同款说明）。

## 分层

    main.py（传输层 HTTP 契约） → 本模块（域层：白名单/校验/类型还原） → db.py（存储层）

## 读取契约（关键，供前端判定"是否首次"）

`get_prefs()` **只返回库中实际存在的键**，不合成默认值。原因：前端首次启动需要区分
「远端为空（新库）→ 保留本地资料并上推」与「远端有值 → 以远端为准」。若此处填充
默认值，这个区分就消失了，会导致存量本地资料被默认值覆盖（真实数据丢失）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.core import db

# ── 键命名单一真相源 ─────────────────────────────────────
# 命名空间化（`域.字段`）：一眼看出归属，新增域不必改表结构。
# max_len 是**纵深防御**：防止有人把 base64/整篇正文塞进 prefs 撑爆库
# （标注/知识库的大体积数据属独立议题，不走本层，见修复计划的 §8 边界）。
#
# `list[str]` 类型的存在理由（计划 v3 §一 A-5）：用户默认引用清单是**参与业务计算的
# 结构化数据**，不是字符串偏好。把它 JSON 编码塞进一个 `str` 键会让偏好层变成通用
# blob（长度上限 128 字符也装不下 10 条网址），所以域层加真类型 + 条数/单条双上限。
PREF_SCHEMA: Dict[str, Dict[str, Any]] = {
    "profile.name":             {"type": "str",  "group": "profile", "max_len": 64},
    "profile.company":          {"type": "str",  "group": "profile", "max_len": 64},
    "ui.model":                 {"type": "str",  "group": "ui",      "max_len": 128},
    "ui.sidebarCollapsed":      {"type": "bool", "group": "ui",      "max_len": 8},
    "intel.defaultSources":     {"type": "list[str]", "group": "intel",
                                 "max_items": 10, "item_max_len": 256},
}

# 单次请求可写入的偏好总字节上限（防批量灌库）。
MAX_PREFS_BYTES = 16 * 1024

# 分组 → 键列表（供前端按域渲染，与 runtime_config.GROUP_FIELDS 同构）。
GROUP_PREFS: Dict[str, List[str]] = {}
for _k, _meta in PREF_SCHEMA.items():
    GROUP_PREFS.setdefault(_meta["group"], []).append(_k)


class PrefsValidationError(ValueError):
    """偏好校验失败（整包失败，含字段级 message）。

    由 main.py 捕获并转成 HTTP 422。core 层不依赖 FastAPI，保持分层纯净
    （与 runtime_config.SettingsValidationError 同款约定）。
    """

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _coerce(key: str, raw: Any, typ: str) -> Any:
    """把库里的字符串还原成声明的类型；失败抛 ValueError（与 runtime_config 同款语义）。"""
    if typ == "list[str]":
        return _coerce_str_list(raw)
    s = "" if raw is None else str(raw)
    if typ == "str":
        return s
    if typ == "int":
        return int(s.strip())
    if typ == "float":
        return float(s.strip())
    if typ == "bool":
        v = s.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise ValueError("必须是 true/false")
    raise ValueError(f"未知类型 {typ}")


def _coerce_str_list(raw: Any) -> List[str]:
    """`list[str]` 的类型还原：库里是 JSON 文本，HTTP 侧可能直接给数组。

    只判**形状**（是数组、元素都是字符串），不判内容对不对 ——
    网址的归一/去重/上限属于入口卫生（`fetcher.normalize_user_url_list`），
    在任务创建那一步做；偏好层再抄一份判据就是第二个真相源。
    """
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = "" if raw is None else str(raw)
        if not text.strip():
            return []
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"不是合法的字符串数组：{exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("必须是数组")
        items = parsed
    if any(not isinstance(x, str) for x in items):
        raise ValueError("数组元素必须都是字符串")
    return [x for x in items]


def _validate_len(key: str, s: str, meta: Dict[str, Any]) -> None:
    """长度守卫：超限抛 ValueError（不静默截断——截断会悄悄改坏用户数据）。"""
    limit = meta.get("max_len")
    if isinstance(limit, int) and len(s) > limit:
        raise ValueError(f"超长（上限 {limit} 字符，实际 {len(s)}）")


def _validate_list(items: List[str], meta: Dict[str, Any]) -> None:
    """`list[str]` 的双上限：条数与单条长度分别守，两个都**不静默截断**。

    只报条数不报第几条，用户没法修；所以超长的哪几条要点名出来。
    """
    max_items = meta.get("max_items")
    if isinstance(max_items, int) and len(items) > max_items:
        raise ValueError(f"最多 {max_items} 条，实际 {len(items)} 条")
    item_limit = meta.get("item_max_len")
    if isinstance(item_limit, int):
        over = [f"第 {i + 1} 条（{len(x)} 字符）" for i, x in enumerate(items)
                if len(x) > item_limit]
        if over:
            raise ValueError(f"单条上限 {item_limit} 字符，超出：{'、'.join(over)}")


def get_prefs() -> Dict[str, Any]:
    """读取全部已存偏好（**仅库中实际存在的键**，类型已还原）。

    单个键损坏（手工改库 / 旧版本类型漂移）时**跳过该键**而非整包失败：
    读路径的可用性优先，不能让一个坏键把整页资料清空。
    """
    stored = db.get_prefs_all()
    out: Dict[str, Any] = {}
    for key, raw in stored.items():
        meta = PREF_SCHEMA.get(key)
        if meta is None:
            continue  # 未知键（旧版本残留）不进有效偏好
        try:
            out[key] = _coerce(key, raw, meta["type"])
        except Exception:  # noqa: BLE001
            continue  # 损坏键跳过，不拖垮全局
    return out


def apply_prefs(patch: Dict[str, Any],
                *, key_errors_out: Dict[str, str] | None = None) -> Dict[str, Any]:
    """校验 → 落库（单事务）→ 返回落库后的全量偏好。

    - 未知键：忽略（不报错，兼容旧/新前端跨版本）。
    - 标量键类型转换失败 / 超长：**整包失败**，收集全部字段级错误后抛
      PrefsValidationError，任何键都不落库（不做半写）。
    - 请求体超总量上限：整包失败。
    - `list[str]` 键（默认引用清单）：**整键隔离** —— 该键的形状/上限错误不连坐其它键，
      其余键照常落库，错误消息经 `key_errors_out` 回给调用方（计划 §四.10）。

    为什么清单键要单独开一条路（不是图省事）：一个网址填错是**内容噪声**，
    而昵称/公司与它无因果关系；若沿用整包失败，用户会看到"改了昵称没存上"，
    而真正被拒的是那条无关的网址。同时它**不能静默收下**：静默收下会让前端的
    pending 重推逻辑以为已保存，下次启动又被远端盖掉。两者都要避免，所以是
    "拒该键 + 照常写其它键 + 把拒因回给调用方"，而不是 422 也不是照单全收。
    """
    if not isinstance(patch, dict):
        raise PrefsValidationError({"patch": "必须是对象"})

    errors: Dict[str, str] = {}
    isolated: Dict[str, str] = {}
    to_write: Dict[str, str] = {}

    for key, raw in patch.items():
        meta = PREF_SCHEMA.get(key)
        if meta is None:
            continue  # 忽略未知键
        is_list_key = meta["type"] == "list[str]"
        try:
            # bool 走「原生 bool 直通 + 字符串形态经 _coerce 判合法性」两路，
            # 避免把 Python 的 True 误判成字符串 "True" 后再做模糊匹配。
            if meta["type"] == "bool" and isinstance(raw, bool):
                coerced: Any = raw
            else:
                coerced = _coerce(key, raw, meta["type"])
            if is_list_key:
                _validate_list(coerced, meta)
            else:
                _validate_len(key, str(coerced), meta)
        except Exception as e:  # noqa: BLE001
            message = f"类型错误（期望 {meta['type']}）：{e}"
            if is_list_key:
                isolated[key] = message      # 整键隔离，不连坐
                continue
            errors[key] = message
            continue
        # list[str] 以 JSON 文本落 prefs 表（prefs 是键值表，序列化只发生在这里一次）；
        # 其余类型保持既有 str() 形状，非清单键的存储字节不变。
        to_write[key] = (json.dumps(coerced, ensure_ascii=False)
                         if is_list_key else str(coerced))

    if errors:
        raise PrefsValidationError(errors)

    total = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in to_write.items())
    if total > MAX_PREFS_BYTES:
        raise PrefsValidationError(
            {k: f"总体积超限（上限 {MAX_PREFS_BYTES} 字节）" for k in to_write}
        )

    db.set_prefs(to_write)
    if key_errors_out is not None:
        key_errors_out.update(isolated)
    elif isolated:
        # 调用方没给收集口：不能把拒因吞在函数里。抛出来让它至少可见，
        # 但**已经写进去的其它键不回滚**（回滚就变回连坐语义了）。
        raise PrefsValidationError(isolated)
    return get_prefs()


def prefs_doc() -> Dict[str, Any]:
    """供 GET /api/prefs 返回的结构（值 + 分组元信息）。

    `stored` 显式给出库中存在的键，前端据此判定「是否首次（远端为空）」——
    不依赖"返回对象是否为空"的隐式约定，契约更硬。
    """
    values = get_prefs()
    return {
        "values": values,
        "stored": sorted(values.keys()),
        "groups": GROUP_PREFS,
    }
