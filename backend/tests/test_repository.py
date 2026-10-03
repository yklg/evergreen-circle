"""M1 · 缓存仓库：data_mode 前缀防串 / TTL / 三种缓存读写 / SqliteCache 落盘并发（U4）。
T2 · 后端介质可互换契约（MemoryCache ≡ SqliteCache）+ 落盘边界（I11/I9）。"""
import inspect
import re
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import app as _app_pkg
from app.living_circle.repository import (
    CACHE_PATH_ENV,
    DEFAULT_CACHE_PATH,
    MemoryCache,
    Repository,
    SqliteCache,
    resolve_cache_path,
)


def test_memory_cache_ttl_expiry():
    cache = MemoryCache()
    cache.set("k", {"v": 1}, ttl_s=0.05)
    assert cache.get("k") == {"v": 1}
    time.sleep(0.08)
    assert cache.get("k") is None


def test_repository_data_mode_isolation():
    """同一场景不同 data_mode 不得串数据（A3 防串契约）。"""
    repo = Repository()
    payload = "凯里老街|107.9758,26.5734|2500|standard"
    repo.cache_samples("live", payload, [{"idx": 0, "minutes": 1.0}])
    repo.cache_samples("fixture", payload, [{"idx": 0, "minutes": 99.0}])
    assert repo.get_samples("live", payload)[0]["minutes"] == 1.0
    assert repo.get_samples("fixture", payload)[0]["minutes"] == 99.0


def test_repository_poi_roundtrip():
    repo = Repository()
    payload = "kaili"
    cats = [{"category": "market", "total": 4}]
    assert repo.get_poi("live", payload) is None
    repo.cache_poi("live", payload, cats)
    assert repo.get_poi("live", payload) == cats


def test_repository_report_roundtrip():
    repo = Repository()
    payload = "kaili-c"
    report = {"scene": {"name": "凯里老街"}, "scores": {"total": 65}}
    assert repo.get_report("live", payload) is None
    repo.cache_report("fixture", payload, report)
    assert repo.get_report("fixture", payload) == report
    # live 前缀不串
    assert repo.get_report("live", payload) is None


# ── U4 · SqliteCache（T2/P0-3：落盘 / 持久 / 过期 / 并发安全）──────────

def test_u4_1_set_get_roundtrip(tmp_path):
    c = SqliteCache(tmp_path / "u4.db")
    c.set("k", {"a": 1, "b": [1, 2, 3]}, ttl_s=60)
    assert c.get("k") == {"a": 1, "b": [1, 2, 3]}


def test_u4_2_persistent_across_instances(tmp_path):
    p = tmp_path / "persist.db"
    SqliteCache(p).set("k", {"v": 42}, ttl_s=600)
    assert SqliteCache(p).get("k") == {"v": 42}  # 关闭后新实例可读（落盘非内存）


def test_u4_3_expiry(tmp_path):
    c = SqliteCache(tmp_path / "exp.db")
    c.set("k", {"v": 1}, ttl_s=0.05)
    assert c.get("k") == {"v": 1}
    time.sleep(0.08)
    assert c.get("k") is None  # 过期惰性清理


def test_u4_4_delete(tmp_path):
    c = SqliteCache(tmp_path / "del.db")
    c.set("k", {"v": 1}, ttl_s=60)
    c.delete("k")
    assert c.get("k") is None


def test_u4_5_idempotent_set_overwrites(tmp_path):
    c = SqliteCache(tmp_path / "idem.db")
    c.set("k", {"v": 1}, ttl_s=60)
    c.set("k", {"v": 2}, ttl_s=60)
    assert c.get("k") == {"v": 2}
    conn = sqlite3.connect(str(tmp_path / "idem.db"))
    rows = conn.execute("SELECT COUNT(*) FROM lc_cache").fetchone()[0]
    conn.close()
    assert rows == 1  # INSERT OR REPLACE，无重复行


def test_u4_6_wal_and_busy_timeout(tmp_path):
    c = SqliteCache(tmp_path / "wal.db")
    conn = sqlite3.connect(str(tmp_path / "wal.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.close()
    assert busy > 0


def test_u4_7_concurrent_writes_no_busy(tmp_path):
    c = SqliteCache(tmp_path / "conc.db")
    errors: list = []

    def worker(i: int):
        try:
            for j in range(5):
                c.set(f"k{i}-{j}", {"i": i, "j": j}, ttl_s=60)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    for i in range(6):
        assert c.get(f"k{i}-4") == {"i": i, "j": 4}


def test_u4_8_large_value(tmp_path):
    c = SqliteCache(tmp_path / "big.db")
    big = {"data": "x" * (1024 * 1024)}  # 1MB
    c.set("big", big, ttl_s=60)
    assert c.get("big") == big


# ── T2 ⑥ · MemoryCache / SqliteCache 共享契约套件（I11）───────────────
# 两实现可互换是 `Repository(backend=…)` 注入点成立的前提：换介质不得改变命中语义。

@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    return MemoryCache() if request.param == "memory" else SqliteCache(tmp_path / f"c-{request.param}.db")


def test_t2_6_roundtrip_nested(backend):
    v = {"points": [{"idx": 0, "minutes": None, "名": "菜市"}], "n": 1}
    backend.set("k", v, ttl_s=60)
    assert backend.get("k") == v


def test_t2_6_missing_key_returns_none(backend):
    assert backend.get("nope") is None


def test_t2_6_overwrite_wins(backend):
    backend.set("k", {"v": 1}, ttl_s=60)
    backend.set("k", {"v": 2}, ttl_s=60)
    assert backend.get("k") == {"v": 2}


def test_t2_6_keys_are_isolated(backend):
    backend.set("a", {"v": 1}, ttl_s=60)
    backend.set("b", {"v": 2}, ttl_s=60)
    assert backend.get("a") == {"v": 1}
    assert backend.get("b") == {"v": 2}


def test_t2_6_delete_then_get(backend):
    backend.set("k", {"v": 1}, ttl_s=60)
    backend.delete("k")
    assert backend.get("k") is None


def test_t2_6_delete_missing_is_noop(backend):
    backend.delete("never-written")  # 不得抛
    assert backend.get("never-written") is None


def test_t2_6_expiry(backend):
    backend.set("k", {"v": 1}, ttl_s=0.05)
    assert backend.get("k") == {"v": 1}
    time.sleep(0.08)
    assert backend.get("k") is None


def test_t2_6_write_after_delete(backend):
    backend.set("k", {"v": 1}, ttl_s=60)
    backend.delete("k")
    backend.set("k", {"v": 3}, ttl_s=60)
    assert backend.get("k") == {"v": 3}


# ── T2 ⑦ · 零/负 TTL 语义（两实现必须一致：都不得留下永不过期项）─────

@pytest.mark.parametrize("ttl", [0.0, -1.0, -9999.0])
def test_t2_7_non_positive_ttl_never_outlives_the_call(backend, ttl):
    backend.set("k", {"v": 1}, ttl_s=ttl)
    time.sleep(0.02)
    assert backend.get("k") is None, f"ttl={ttl} 竟仍可读（负 TTL 未归零）"


# ── T2 ⑧~⑨ · SqliteCache 特有的落盘边界 ─────────────────────────────

def test_t2_8_corrupted_row_returns_none(tmp_path):
    """库里塞非法 JSON（手工改盘/半写）→ get 返回 None 不抛（缓存故障必须降级重算）。"""
    p = tmp_path / "bad.db"
    c = SqliteCache(p)
    c.set("k", {"v": 1}, ttl_s=600)
    conn = sqlite3.connect(str(p))
    conn.execute("UPDATE lc_cache SET value='{not-json' WHERE key='k'")
    conn.commit()
    conn.close()
    assert c.get("k") is None
    c.set("k2", {"v": 2}, ttl_s=600)  # 坏行不阻断后续读写
    assert c.get("k2") == {"v": 2}


def test_t2_8_missing_table_returns_none(tmp_path):
    """表被外部删除（缓存文件被人清过）→ get 不得抛，静默视为未命中。"""
    c = SqliteCache(tmp_path / "t8.db")
    conn = sqlite3.connect(str(tmp_path / "t8.db"))
    conn.execute("DROP TABLE lc_cache")
    conn.commit()
    conn.close()
    assert c.get("k") is None


def test_t2_9_non_serializable_value_escapes_set_currently(tmp_path):
    """**记录当前行为 + TODO**（I9 / 评审 P0-2）：不可序列化值让 TypeError 逃出 `set`。

    `set` 只捕 `sqlite3.Error`，`json.dumps` 的 TypeError 会一路上抛到 pipeline，
    使一次「已经算完的体检」在写缓存时崩掉（MemoryCache 则静默收下 → 两实现语义分裂）。
    TODO：`set` 内包 `except (TypeError, ValueError): return`（缓存写失败应降级为不缓存）。
    """
    c = SqliteCache(tmp_path / "t9.db")
    with pytest.raises(TypeError):
        c.set("k", {"obj": object()}, ttl_s=60)
    assert c.get("k") is None  # 未落半行
    c.set("k", {"ok": 1}, ttl_s=60)  # 抛错后连接已释放，缓存仍可用
    assert c.get("k") == {"ok": 1}
    m = MemoryCache()
    m.set("k", {"obj": object()}, ttl_s=60)  # 内存实现不抛 → 契约不对称
    assert m.get("k")["obj"] is not None


# ──────── U5 · 缓存落点可换（重采演示夹具要绕开「键不含检索词表」的旧载荷） ────────
#
# 为什么有这一格：报告缓存的键 = 场景名 + 中心 + 半径 + 档位 + 出行方式，**不含检索词表**
# （`data_source.caliber_payload_key`）⇒ 改了 `CATEGORY_RULES` 的词表不会让它失效，同参再跑
# 必命中 30 天内的旧载荷。`scripts/snapshot_live` 撞的就是这个：一次外呼都不发、把补词前的
# 数据写回夹具，而它自己那道「必须是本场景当前口径」的门也只校 ev/cov 两把键 ⇒ 全绿放行。


def test_u5_1_default_cache_path_is_the_shipped_file(monkeypatch):
    """不设变量时落点必须**还是**现役那份 `app/lc_cache.db`。

    这颗开关是保护型的：默认值 = 加它之前的行为。期望值从 `app` 包位置现算，不抄
    `DEFAULT_CACHE_PATH`（那等于问常量"你等于你自己吗"）。
    """
    monkeypatch.delenv(CACHE_PATH_ENV, raising=False)
    expected = Path(_app_pkg.__file__).resolve().parent / "lc_cache.db"
    got = resolve_cache_path()
    assert got == expected, f"默认落点挪了：{got} ≠ {expected}"
    assert got == DEFAULT_CACHE_PATH, "resolver 与默认常量分叉 ⇒ 调用方各自认账"


def test_u5_2_env_redirects_every_write(tmp_path, monkeypatch):
    """设了 LC_CACHE_PATH ⇒ 建库、写、读全落在那颗新文件上。

    两态对照才有信息量：换两个目标各写各的，若 resolver 忽略环境变量，两次都会落到同一个
    文件、后一次覆盖前一次 ⇒ 第一条断言当场红。sqlite 不会替调用方建父目录，故路径落在
    tmp_path 本身。
    """
    a, b = tmp_path / "cache-a.db", tmp_path / "cache-b.db"
    monkeypatch.setenv(CACHE_PATH_ENV, str(a))
    ca = SqliteCache(resolve_cache_path())
    ca.set("live:report:u5", {"report": {"n": 1}}, ttl_s=600)
    monkeypatch.setenv(CACHE_PATH_ENV, str(b))
    cb = SqliteCache(resolve_cache_path())
    cb.set("live:report:u5", {"report": {"n": 2}}, ttl_s=600)
    assert ca.get("live:report:u5") == {"report": {"n": 1}}, "写 b 把 a 覆盖了 ⇒ 落点根本没换"
    assert cb.get("live:report:u5") == {"report": {"n": 2}}
    assert a.is_file() and b.is_file()


def test_u5_3_empty_env_means_unset(monkeypatch):
    """空串按「没设」处理（与 `core.db` 的 VERDA_DB_PATH 同形状）。

    不这么做，一个 `LC_CACHE_PATH=` 会把库指到空路径 —— 比默认更糟：当场炸或写到 cwd。
    """
    monkeypatch.setenv(CACHE_PATH_ENV, "")
    assert resolve_cache_path() == DEFAULT_CACHE_PATH


def test_u5_4_pipeline_takes_its_cache_location_from_the_resolver():
    """接线腿：pipeline 不得再自己写死缓存文件名，否则这颗开关对真实链路无效。

    先剥注释再扫 —— 那段注释**必须**提到默认落点是什么，算进判据就等于把"把话说清楚"判成违规。
    """
    from app.core.pipeline import living_circle as pipe

    src = inspect.getsource(pipe)
    code = "\n".join(re.sub(r"#.*", "", line) for line in src.splitlines())
    assert "resolve_cache_path(" in code, "pipeline 没走 resolver ⇒ 换不了落点"
    assert "lc_cache.db" not in code, "pipeline 里还留着写死的缓存文件名"
