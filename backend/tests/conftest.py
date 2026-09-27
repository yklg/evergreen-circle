"""测试隔离夹具。

关键约束（见 db.py）：
- `_DB_PATH = _resolve_db_path()` 在 **import app.core.db 时** 即解析，
  因此 VERDA_DB_PATH 必须在 import 任何 app 模块 **之前** 设好，
  否则会指向真实的 app/data/verda.db，污染生产库。
- 整个测试会话复用同一个临时 DB 文件；每次用例前后用 clear_settings()
  清表 + 重置 runtime_config 的进程级迁移标记，保证用例互不污染。
"""
import os
import tempfile
from pathlib import Path

# ── 必须在 import app 之前设置 ──────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="verda-test-"))
os.environ["VERDA_DB_PATH"] = str(_TMP / "test.db")

import pytest  # noqa: E402

import app.core.db as db  # noqa: E402
import app.core.runtime_config as rc  # noqa: E402
import app.living_circle.request_guard as request_guard  # noqa: E402
from app.living_circle.scope import SCOPE_POLICY_VERSION  # noqa: E402


def live_payload(payload: dict) -> dict:
    """给一份 **要过复用门** 的 live 桩载荷盖上当前判盲口径版本（就地返回同一对象）。

    复用门 ``report_contract.reuse_policy``（生产调用点仅两处：``data_source.py:145``
    ``LiveDataSource.compute`` 的缓存读、``:301`` ``CachingDataSource._reusable``
    （经 ``peek``/``compute``））只认带 ``caliber.scope_policy_version`` 的 live 载荷 ——
    旧口径/无口径的报告不许冒充本次体检的答案。因此**凡测试里手工落 live 缓存、
    再指望 ``peek``/``compute`` 命中**的桩，都必须过这个门，否则会静默变成"未命中"，
    用例照样绿但测的已经不是它以为的那件事。

    **不要**在这些地方套它：

    * 纯 ``Repository.cache_report`` / ``get_report`` / ``find_recent_report_near`` 层用例
      —— 压根不走门（如 ``test_degrade_chain.py`` M1-b、``test_caching_datasource`` U25/U33）；
    * 几何契约 / 可展示性判据的桩（``test_intake_and_shell``、``test_blindspot_marching``、
      ``test_fixture_mirror``）—— 那是另一道门（``assess_geometry``），补版本只会稀释判据；
    * ``test_caching_datasource.py`` 末尾 `test_stale_policy_*` 三条**故意不带版本**的
      负对照 —— 它们负责证明门真的有牙，全量套壳会把门架空。
    """
    payload.setdefault("caliber", {})["scope_policy_version"] = SCOPE_POLICY_VERSION
    return payload


@pytest.fixture(autouse=True)
def _isolate():
    """每用例前清空 settings/prefs 表并重置进程级迁移标记/缓存。"""
    db.clear_settings()
    db.clear_prefs()
    db.clear_discovery_cache()
    db.invalidate_aggregates()          # G5：聚合读缓存与库文件解耦，隔离库切换必须显式失效
    rc._MODEL_MIGRATED = False
    rc._MIGRATED = False
    rc.invalidate_cache()
    # P0-2 复核：进程级限流闸 / 日预算也是**模块级单例**，跨用例持久。
    # 原先只在 test_rate_limiter_shared.py 内用 autouse 夹具清理 ⇒ **作用域过窄**：
    # 该文件内污染被抹平、其他文件（与真实运行环境）不可见。夹具的作用域本身就是一条
    # 隐性断言 —— 共享状态必须在**全局** conftest 清，才谈得上「用例互不污染」。
    request_guard._limiter_cache.clear()
    request_guard._daily_cache.clear()
    yield
    # 用例后无需清理：下个用例开头会再次重置
