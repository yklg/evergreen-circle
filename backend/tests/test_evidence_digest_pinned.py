"""证据入池保真基线（实施计划 v3 §九 · TC-28 + TC-26，均为真测试；B3 已落地转正）。

守护的契约
----------
`app/core/pipeline/research/collect.py:208` 的 `_evidence_digest()` 是**三个消费方共用**
的入池函数（`writer.py:80` 以 `limit=20` 调用、`spots.py:27` 以默认 `limit=28` 复用），
它今天的实现是 `for e in evidences[:limit]` —— **位置截断、不排序、不判相关性**。

计划 v3 的 A-1 结论：「用户指定信源若排在第 21 条之后，就从未进入写作上下文」，
因此新增的 `pinned=` 保留槽必须满足两条互不冲突的性质：

  性质一（TC-28，今天必须绿、B3 落地后仍必须绿）
      **不传 pinned 时，输出与改动前逐字节相等。** 这条守的是零回归：
      `spots.py` 景点实体 leg 的入池不能因为保留槽的加入而悄悄变化。

  性质二（TC-26，生成时 xfail、B3 落地后转正）
      **pinned 里的每一条都必须出现在输出里**，无论它在 `evidences` 中排第几。

期望值来源（禁凭记忆）
----------------------
黄金串按 `collect.py:212` 的格式串
    `f"[{e.evidence_id}|{e.source_type}|{domain_of(e.source_url)}] {e.title}：{e.excerpt}"`
用 `fetcher.py:25-29` 的 `domain_of()`（`urlparse().netloc.lower().replace("www.", "")`）
逐条手算后固化为**字面量**，不是在本文件里重跑一遍生产实现来生成期望
（重跑实现来断言实现 = 恒真断言）。

采基线的方法（日后可重取）：
    cd skip/backend && python3 -c "
    from app.core.pipeline.research.collect import _evidence_digest
    import tests.test_evidence_digest_pinned as t
    print(repr(_evidence_digest(t.sample_evidences(30), limit=20)))"

⚠️ 未采用 property-based（hypothesis）：该依赖未安装，引入依赖属配置变更需单独授权。
   本轮以**参数化穷举**替代（长度 0/1/limit-1/limit/limit+1/limit+10 × pinned 空/单条/全部/边界外）。
"""
from __future__ import annotations

import pytest

from app.core.models import Evidence
from app.core.pipeline.research import collect

WRITER_LIMIT = 20   # 来源：writer.py:80 的 `limit=20`
DEFAULT_LIMIT = 28  # 来源：collect.py:208 的形参默认值（spots.py:27 复用的就是它）


def _ev(i: int) -> Evidence:
    """构造一条字段合法的 Evidence（字段序取自 models.py 的 dataclass 声明）。"""
    return Evidence(
        evidence_id=f"e_{i:03d}",
        source_url=f"https://site{i}.example.org/doc/{i}",
        source_type="web",
        title=f"标题{i}",
        excerpt=f"摘要{i}",
        captured_at="2026-01-01T00:00:00Z",
        credibility=50.0,
        collected_by="collect",
        image_urls=[],
        republished_from="",
        destination="大理",
        source_group=f"g_{i:03d}",
    )


def sample_evidences(n: int) -> list:
    return [_ev(i) for i in range(1, n + 1)]


def _line(i: int) -> str:
    """黄金串的单行形状——只用于**组装期望**，不参与被测实现。"""
    return f"[e_{i:03d}|web|site{i}.example.org] 标题{i}：摘要{i}"


# ── 性质一：无 pinned ⇒ 逐字节等改前（TC-28，真测试）──────────────────


@pytest.mark.parametrize("total,limit", [
    (0, WRITER_LIMIT), (1, WRITER_LIMIT), (WRITER_LIMIT - 1, WRITER_LIMIT),
    (WRITER_LIMIT, WRITER_LIMIT), (WRITER_LIMIT + 1, WRITER_LIMIT),
    (WRITER_LIMIT + 10, WRITER_LIMIT), (DEFAULT_LIMIT, DEFAULT_LIMIT),
    (30, DEFAULT_LIMIT),
])
def test_no_pinned_output_is_byte_identical_to_positional_head(total, limit):
    """不传 pinned 时，digest 必须等于「前 min(total, limit) 条的黄金串拼接」。

    期望值由本文件按已声明的格式手算，不回调生产实现。
    """
    expected_lines = [_line(i) for i in range(1, min(total, limit) + 1)]
    expected = "\n".join(expected_lines)

    out = collect._evidence_digest(sample_evidences(total), limit=limit)

    assert out == expected, (
        f"total={total} limit={limit}：入池内容与位置截断基线不一致。"
        "若无 pinned 的输出都变了，说明 B3 的保留槽改动了三个共用方"
        "（writer.py:80 / spots.py:27 / analyze）共同的默认行为 —— 这是回归，不是增强。"
    )


def test_golden_literal_three_items():
    """一条**全字面量**黄金串：不经过本文件里任何按格式组装期望的 helper。

    加这条的理由是防止「期望由同一格式串派生 ⇒ 格式错了也测不出」。
    字面量按 `fetcher.py:25-29` 的 `domain_of()` 实算结果手核。
    """
    assert collect._evidence_digest(sample_evidences(3), limit=WRITER_LIMIT) == (
        "[e_001|web|site1.example.org] 标题1：摘要1\n"
        "[e_002|web|site2.example.org] 标题2：摘要2\n"
        "[e_003|web|site3.example.org] 标题3：摘要3"
    )


def test_positional_slice_really_drops_the_tail_today():
    """钉住今天的**事实**：limit=20、30 条时第 21—30 条不在池里。

    这条不是给缺陷背书，而是 A-1 的证据本体 —— B3 落地后若仍成立，说明保留槽
    没生效；届时应把本例改写成「无 pinned 时依然丢弃尾部（保持零回归）」并删掉
    下面这句对现状的描述性断言。
    """
    out = collect._evidence_digest(sample_evidences(30), limit=WRITER_LIMIT)
    lines = out.splitlines()

    assert len(lines) == WRITER_LIMIT
    assert lines[-1] == _line(20)
    assert _line(21) not in out            # 尾部第 21 条今天确实进不了池
    assert _line(30) not in out


# ── 性质二：pinned 必入池（TC-26，B3 已落地）─────────────────────────

# 转正记录（B3 已落地）：以下两例生成时挂 `xfail(strict=True)`，因为当时
# `_evidence_digest` 只有 (evidences, limit) 两个形参、入池纯靠位置截断。
# B3 加了 pinned= 保留槽后它们转 XPASS = FAILED，按 §十.4 摘掉标记、断言体一字未动。
# 同时必须**保持绿**的是上面两条零回归用例（TC-28 / 黄金串）：它们守的是
# writer / spots / analyze 三个共用方在"无必读条目"时的入池不变。


@pytest.mark.parametrize("total,pinned_ids", [
    (25, ["e_024"]),
    (25, ["e_021", "e_022", "e_023", "e_024", "e_025"]),
    (30, ["e_030"]),
    (30, ["e_005", "e_030"]),
    (WRITER_LIMIT + 10, [f"e_{i:03d}" for i in range(21, 31)]),
])
def test_pinned_evidence_must_be_in_pool_regardless_of_position(total, pinned_ids):
    """任意 pinned 条目必出现在 digest 中 —— 覆盖率判据的成立前提。

    若这条不成立，「用户指定信源未进报告」就分不清是『没被引用』还是『根本没进上下文』，
    计划 v3 A-1 指出的正是这种混判。
    """
    evs = sample_evidences(total)
    out = collect._evidence_digest(evs, limit=WRITER_LIMIT, pinned=set(pinned_ids))

    for eid in pinned_ids:
        assert eid in out, f"pinned {eid} 未进池（limit={WRITER_LIMIT}, total={total}）"
    assert len(out.splitlines()) <= WRITER_LIMIT, "保留槽不得突破 limit：pinned 是占位，不是扩容"


def test_pinned_empties_and_over_limit_still_safe():
    """边界：pinned 为空集合时等同一位置截断；pinned 数量 > limit 时不崩且仍守 limit。"""
    evs = sample_evidences(25)
    assert collect._evidence_digest(evs, limit=WRITER_LIMIT, pinned=set()) == \
        collect._evidence_digest(evs, limit=WRITER_LIMIT)

    over = collect._evidence_digest(evs, limit=5, pinned={f"e_{i:03d}" for i in range(1, 26)})
    assert len(over.splitlines()) == 5


# ── 生产接缝：必读条目由注册表自动判定，不靠调用点传参 ──────────────────

def _user_ev(i: int) -> Evidence:
    """一条**用户指定信源**的证据（source_type 由 `collect_user_sources` 落 `user_supplied`）。"""
    return Evidence(
        evidence_id=f"u_{i:03d}",
        source_url=f"https://user{i}.gov.cn/doc",
        source_type="user_supplied",
        title=f"用户指定{i}",
        excerpt=f"用户正文{i}",
        captured_at="2026-01-01T00:00:00Z",
        credibility=60.0,
        collected_by="L1-025",
        image_urls=[],
        republished_from="",
        destination="",
        source_group=f"gu_{i:03d}",
    )


def test_must_read_is_registry_owned_and_only_user_supplied_has_it():
    """保留槽的判据归注册表；今天**只有** `user_supplied` 是必读。

    钉成显式小集是为了"悄悄多一类必读"必须是一次看得见的改动 —— 每多一类必读，
    所有共用方的入池规模都会跟着涨（token 成本在这里，不在调用点）。
    """
    from app.core import source_type as ST

    must = {k for k, v in ST.SOURCE_KINDS.items() if v.must_read}
    assert must == {"user_supplied"}, f"必读类别集合变了：{sorted(must)}"
    assert ST.is_must_read_kind("user_supplied") is True
    assert ST.is_must_read_kind("web") is False
    assert ST.is_must_read_kind("不存在的类别") is False, "未知 key 不得被判成必读"


def test_a_25th_position_user_source_still_reaches_the_writer_prompt():
    """**A-1 的回归防线**（计划 §四.4）：≥25 条检索证据 + 用户钉 1 条 ⇒ 该条仍在池里。

    与上面 TC-26 的差别是接缝：那条从外部传 `pinned=`，这条**什么都不传** ——
    走的是 writer 真实调用的形状（`_evidence_digest(evidences, limit=digest_limit_for(evs, 20))`）。
    保留槽若只能靠调用点记得传参，就等于没修。
    """
    web = sample_evidences(29)
    tail_user = _user_ev(1)
    evs = web + [tail_user]                      # 用户信源排在第 30 位（旧写法必然被截掉）

    limit = collect.digest_limit_for(evs, WRITER_LIMIT)
    out = collect._evidence_digest(evs, limit=limit)

    assert tail_user.evidence_id in out, "排在尾部的用户信源仍被位置截断挤出 prompt（A-1 复发）"
    # 加槽而非挤位：原有 20 条检索证据一条都不能少
    for e in web[:WRITER_LIMIT]:
        assert e.evidence_id in out, f"{e.evidence_id} 被必读条目挤出入池"


@pytest.mark.parametrize("n_user", [0, 1, 5, 10, 11, 20])
def test_digest_limit_adds_exactly_one_slot_per_must_read_up_to_the_cap(n_user):
    """`digest_limit_for` = base + min(必读条数, 清单上限)；无必读时**逐字等 base**。

    上限取自 `fetcher.MAX_SOURCE_URLS`（入口层就限制了 ≤10 条），
    所以必读条目不可能超过它 —— 超过的部分按上限计，prompt 规模有硬上界。
    """
    from app.core import fetcher

    evs = sample_evidences(29) + [_user_ev(i) for i in range(1, n_user + 1)]
    assert collect.digest_limit_for(evs, WRITER_LIMIT) == \
        WRITER_LIMIT + min(n_user, fetcher.MAX_SOURCE_URLS)
    if n_user == 0:
        assert collect.digest_limit_for(evs, 28) == 28, "无必读条目时入池规模必须零变化"


def test_must_read_ids_follow_the_registry_not_the_call_site():
    """必读集由 source_type 派生：调用点不需要知道"哪些是用户钉的"。"""
    evs = sample_evidences(3) + [_user_ev(9)]
    assert collect.must_read_ids(evs) == {"u_009"}
