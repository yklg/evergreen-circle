"""搜索服务商可用性探针（批次 0 前置条件 3）：五种归类各配一个真样本。

判据纪律（v4.3 ④）：每条 state 都必须被它**自己那一个**样本驱动 —— 只测「抛异常 ⇒ 不 ready」
会得到一条把所有病因压成一个 state 的假护栏，而那正是本探针要消除的东西
（`_fill_persp_blocks` 压扁四种失败是同一形状的病）。
"""
from app.core import search as S


def _probe(monkeypatch, side):
    monkeypatch.setattr(S, "search", side)
    return S.search_provider_probe()


def test_ready_with_hits(monkeypatch):
    r = _probe(monkeypatch, lambda q, **k: [{"url": "u1", "title": "t"}])
    assert (r["state"], r["ready"], r["hits"]) == ("ready", True, 1)
    assert not r["reason"]


def test_auth_and_quota_ok_even_when_this_query_hit_nothing(monkeypatch):
    """0 结果 ≠ 没网：鉴权与配额都通，只是探针词没命中 —— 不得混进 error。"""
    r = _probe(monkeypatch, lambda q, **k: [])
    assert (r["state"], r["ready"], r["hits"]) == ("ready", True, 0)


def test_missing_key_is_its_own_state(monkeypatch):
    """「没配 key」必须与「欠费」分开：两者的处置完全不同（补 key vs 充值）。"""
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(
        S.SearchProviderError("未配置 BOCHA_API_KEY，请在「模型配置」页面填写后重试")))
    assert (r["state"], r["ready"]) == ("no_key", False)
    assert "BOCHA_API_KEY" in r["reason"]


def test_balance_exhausted_is_terminal(monkeypatch):
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(
        S.SearchProviderError("博查账户余额不足，请充值")))
    assert (r["state"], r["ready"]) == ("terminal", False)


def test_invalid_key_is_terminal(monkeypatch):
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(
        S.SearchProviderError("博查 API Key 无效或缺失")))
    assert r["state"] == "terminal"


def test_throttle_is_not_terminal(monkeypatch):
    """429 单列 transient：与 `_THROTTLE_CODES` 同判据。

    真机 r_b14e555d 实证过这个区分的代价 —— 首发 429 被当终态中止整阶段，核查表满屏占位。
    探针若把它读成 terminal，批次 0 就会把「稍后再试」误判成「这个视角行不行」。
    """
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(
        S.SearchProviderError("博查请求频率超限，请稍后重试")))
    assert (r["state"], r["ready"]) == ("transient", False)


def test_unclassified_becomes_error_with_the_original_text(monkeypatch):
    """未归类的一律 state=error 且**带上原文**：探针吞掉的是「归类完成」，不是失败本身。"""
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(
        S.SearchProviderError("博查搜索服务内部异常")))
    assert (r["state"], r["ready"], r["reason"]) == ("error", False, "博查搜索服务内部异常")


def test_network_exception_is_caught_and_named(monkeypatch):
    r = _probe(monkeypatch, lambda q, **k: (_ for _ in ()).throw(TimeoutError("connect timed out")))
    assert (r["state"], r["ready"]) == ("error", False)
    assert "TimeoutError" in r["reason"], "异常类型名必须留在 reason 里，否则归类无从诊断"


def test_probe_state_is_a_closed_enum():
    """门槛读的是**固定枚举**：函数里出现的 state 字面量必须恰好是这五个。

    多一个没约定的值 ⇒ 判据 `state != "ready"` 仍会工作，但 `!= ok` 那类写法会把它悄悄
    读成"就绪"；少一个 ⇒ 有一类病因没了归宿。两边都靠这条钉住。
    """
    import inspect
    src = inspect.getsource(S.search_provider_probe)
    produced = {lit for lit in ("ready", "no_key", "terminal", "transient", "error")
                if f'"{lit}"' in src}
    assert produced == {"ready", "no_key", "terminal", "transient", "error"}, \
        f"探针 state 取值漂移：{sorted(produced)}"


def test_probe_issues_exactly_one_minimal_query(monkeypatch):
    """探针的代价承诺：一次调用、num 最小。跑 deep 预算前先探，不该反过来吃掉预算。"""
    calls = []

    def spy(q, **k):
        calls.append((q, k))
        return []
    monkeypatch.setattr(S, "search", spy)
    S.search_provider_probe()
    assert len(calls) == 1
    assert calls[0][1].get("num") == 1
