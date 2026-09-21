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
    yield
    # 用例后无需清理：下个用例开头会再次重置
