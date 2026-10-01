"""跨端词表镜像：前端的用户指定信源词表必须与后端逐字一致（计划 v3 §二 G0/B5 · §八 CT-01 同族）。

为什么这条缝值得单独守（与 `test_api_client_contract.py` 同源，另一类物件）：
后端把「读取态」和「覆盖率桶」拆成两套词是有意的（`db.USER_SOURCE_STATES` 由 collect 写、
`audit.USER_SOURCE_COVERAGE_BUCKETS` 是派生指标），前端要把它们渲染成人话。两边各写一份时，
**任何一侧改名都不会让任何一侧变红**：界面会把 `gated_off_query` 直接上屏（用户看见裸 key），
或者更糟——把新的桶静默渲染成旧文案。这正是本项目反复出现的"单边正确、两边脱节"形状。

写法沿用 `test_api_client_contract.py` / `test_task_body_contract.py`：
从前端**真实源码**取词表，"解析不出键＝判据已与真实源脱节，宁可红，不空转"。
"""
import re
from pathlib import Path

import app.core.db as db
from app.core import audit
from app.core.fetcher import MAX_SOURCE_URLS

FRONT_STATES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "userSourceStates.ts"
)


def _src() -> str:
    assert FRONT_STATES.exists(), f"前端词表文件不见了：{FRONT_STATES}（判据已与真实源脱节）"
    return FRONT_STATES.read_text(encoding="utf-8")


def _array_literal(name: str) -> list:
    """取 `export const NAME = [...] as const` 里的字符串项。"""
    m = re.search(rf"export const {name} = \[(.*?)\] as const", _src(), re.S)
    assert m, f"前端源码里解析不出 `export const {name} = [...] as const`（改名或换写法要同步本判据）"
    items = re.findall(r"'([^']+)'", m.group(1))
    assert items, f"{name} 解析出空数组 ⇒ 判据会退化成恒真"
    return items


def _const_number(name: str) -> int:
    m = re.search(rf"export const {name} = (\d+)", _src())
    assert m, f"前端源码里解析不出 `export const {name} = <整数>`"
    return int(m.group(1))


def _label_map_keys(map_name: str) -> list:
    m = re.search(rf"export const {map_name}: Record<[^>]+>.*?= \{{(.*?)\n\}}", _src(), re.S)
    if not m:
        m = re.search(rf"export const {map_name}: Record<string, string> = \{{(.*?)\n\}}", _src(), re.S)
    assert m, f"前端源码里解析不出 `{map_name}` 这张表"
    return re.findall(r"^\s*(\w+):", m.group(1), re.M)


# ── 读取态：存储词表 ────────────────────────────────────────────
def test_frontend_state_vocabulary_equals_the_stored_states():
    """`userSourceStates.USER_SOURCE_STATES` ≡ `db.USER_SOURCE_STATES`（含顺序）。

    顺序也判：这张表决定界面上"待读取/已读取入链/…"的呈现次序与筛选清单，
    两侧同序才不会今天这边按流程排、那边按字母排。
    """
    assert _array_literal("USER_SOURCE_STATES") == list(db.USER_SOURCE_STATES)


def test_every_stored_state_has_a_chinese_label():
    """每个存储态都有中文标签；少一个就会把裸 key 上屏，而没有任何东西报错。"""
    labels = _label_map_keys("USER_SOURCE_STATE_LABELS")
    missing = [s for s in db.USER_SOURCE_STATES if s not in labels]
    assert not missing, f"前端缺这些态的标签：{missing}"


def test_frontend_labels_name_the_blocked_state_as_rejection_not_failure():
    """判据精确到**失败种类**：`blocked` 是安全闸门拒绝，`unread` 是没读到。

    两者若都写成"读取失败"，用户会以为内网地址是被拒的普通 404，答辩时也无法解释
    这条防线在起作用（§二 B0 的默认启用是功能，不是错误）。
    """
    src = _src()
    blocked_label = re.search(r"blocked: '([^']+)'", src).group(1)
    unread_label = re.search(r"unread: '([^']+)'", src).group(1)
    assert "拒绝" in blocked_label, blocked_label
    assert "拒绝" not in unread_label, unread_label


# ── 覆盖率桶：派生词表 ──────────────────────────────────────────
def test_frontend_coverage_buckets_are_the_derived_vocabulary():
    """界面显示覆盖率桶的前端表，必须覆盖 audit 产出的全部桶名（含不进分母的三类）。"""
    buckets = _label_map_keys("USER_SOURCE_COVERAGE_LABELS")
    missing = [b for b in audit.USER_SOURCE_COVERAGE_BUCKETS if b not in buckets]
    # merged / gated_off_query 是"读取态"上的诊断标，覆盖率行仍以 cited/uncited 为主：
    # 允许它们不在桶表里，但必须在**态表**里（上一条测试已钉）。
    truly_missing = [b for b in missing if b in ("cited", "uncited", "pending", "unread", "blocked")]
    assert not truly_missing, f"前端缺这些覆盖率桶的标签：{truly_missing}"


def test_coverage_buckets_are_declared_once_in_the_backend():
    """后端桶清单本身不得被复制成两份（与注册表纪律一致）。"""
    src = (Path(__file__).resolve().parents[1] / "app" / "core" / "audit.py").read_text(encoding="utf-8")
    assert src.count("USER_SOURCE_COVERAGE_BUCKETS = (") == 1


# ── 条数上限：同一个数只能在两侧各出现一次且相等 ─────────────────
def test_frontend_url_cap_matches_backend():
    """前端预检用的上限 ≡ 后端裁决用的上限。

    不等会出两种坏形状：前端放行 12 条、后端静默砍到 10（用户以为都在读）；
    或前端只让填 8 条，后端明明支持 10（功能被界面阉割）。
    """
    assert _const_number("MAX_USER_SOURCE_URLS") == MAX_SOURCE_URLS
