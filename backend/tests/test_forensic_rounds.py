"""取证-判盲同源改造的**回合层**测试（计划 v4 批次一 · T1 与 T3 混居）。

T1（真断言，今日即绿）
  B2  `test_u38b_admission_set_is_stable_across_runs`
      —— 同参两次跑出**同一准入词集**。锁的是「确定性」这件事本身，不锁具体是哪几个词；
      阶段 3 换成转置轮询后必须仍然绿（那时变的是内容，不是稳定性）。
  B2b `test_u38c_current_starvation_follows_dict_order`
      —— C 型**现状记录**：今天的饿死集合由 `CATEGORY_RULES` 字典序前缀决定。
      阶段 3 落地时必须转红并**重指判据**，禁止就地放宽或删掉（本仓纪律）。

T3（前置红测试：实现未落地即 skip，不污染全绿套件 —— 沿用 `test_quota.py:1-9` 先例）
  B5  同锚点同半径的重复检索被去重
  B1 / B3 本轮**不生成**，理由见文件末「T3」段落的注释（未生成 ≠ 已覆盖）。

守卫按**单条**打 skipif 而非整文件 `importorskip`：整文件守卫会把 T1 那两条一起静默掉，
而 T1 恰恰是今天就该生效的锁。
"""
import importlib.util

import pytest

pc = pytest.importorskip("app.living_circle.poi_collector", reason="poi_collector.py 待 rev3 落地（§四B）")

from app.living_circle.baidu_client import PlaceSearchOut  # noqa: E402
from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES  # noqa: E402

CENTER = (107.9758, 26.5734)

_HAS_ROUND = hasattr(pc, "collect_triad_evidence")
_HAS_ANCHORS = importlib.util.find_spec("app.living_circle.anchors") is not None
needs_round = pytest.mark.skipif(
    not _HAS_ROUND, reason="取证回合 poi_collector.collect_triad_evidence 待计划阶段 5 落地"
)
needs_anchors = pytest.mark.skipif(
    not _HAS_ANCHORS, reason="锚点源 app.living_circle.anchors 待计划阶段 1 落地"
)


class _Stub:
    """一律返回空结果的百度桩，同时记录每次发出的 (query, center, radius)。"""

    def __init__(self):
        self.calls = 0
        self.queries = []

    async def place_search(self, query, center=None, radius_m=None, **kw):
        self.calls += 1
        self.queries.append((query, tuple(center) if center else None, radius_m))
        return PlaceSearchOut([], None, 1, pc.STOP_EMPTY)


def _collect(total: int):
    import asyncio

    stub = _Stub()
    b = pc.POIBudget(total=total)
    collected = asyncio.run(
        pc.collect_poi(stub, center=CENTER, radius_m=2000, scope=object(), budget_snapshot=b)
    )
    return stub, b, collected


def _admitted(queries):
    return tuple(dict.fromkeys(q[0] for q in queries))


def _searched_terms():
    """采集器实际会发起的词序列（展示词表 + 三要素里另检的那两个）。

    镜像 `poi_collector.py:391-413/433-437` 的枚举口径：`market` 复用类目结果不另发一次，
    其余两个三要素各取 `keywords[0]`。准入/饿死的判据必须建立在这份**完整**词表上，
    否则「三要素被饿死」会被当成「词表之外的噪声」漏掉。
    """
    terms = [kw for defn in CATEGORY_RULES.values() for kw in defn["keywords"]]
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_") or key == "market":
            continue
        kws = ref["keywords"] if isinstance(ref, dict) else [ref]
        if kws and kws[0] not in terms:
            terms.append(kws[0])
    return terms


# ── T1 · 今日即绿 ────────────────────────────────────────────────

def test_u38b_admission_set_is_stable_across_runs():
    """B2 · 同参两次跑出同一准入词集（「检索随机性太强」的机器反证）。"""
    s1, b1, c1 = _collect(total=2)
    s2, b2, c2 = _collect(total=2)

    assert _admitted(s1.queries) == _admitted(s2.queries), (
        f"同参两次跑出发出不同的词：{s1.queries} vs {s2.queries} ⇒ 点位集合不可复现"
    )
    assert c1.evidence.starved_terms == c2.evidence.starved_terms, (
        "被饿死的词集两次不一致 ⇒ 报告举证 `evidence_starved_terms` 不可复算"
    )
    assert b1.remaining == b2.remaining == 0
    # 准入 + 饿死 = 全词表（含另检的两个三要素词）：一条都不许凭空蒸发（P0-2 可见性）
    starved = {t for _cat, t in c1.evidence.starved_terms}
    assert set(_admitted(s1.queries)) | starved == set(_searched_terms()), (
        "有词既没被检索、也没被登记为饿死 ⇒ 该类点位会静默消失"
    )


def test_u38c_current_starvation_follows_dict_order():
    """B2b · **现状记录**：今天谁被饿死 = `CATEGORY_RULES` 字典序的前缀。

    这不是「应有行为」而是「当前行为」。写成判据的目的是：阶段 3 的转置轮询**必须**把这条
    打红并逼着改判据 —— 若那时直接删掉本用例，饿死只是从一种顺序依赖换成另一种，没人会发现。
    """
    total = 2
    _stub, _b, collected = _collect(total=total)
    ordered = _searched_terms()
    starved = {t for _cat, t in collected.evidence.starved_terms}

    assert set(ordered[:total]) & starved == set(), (
        f"准入前缀 {tuple(ordered[:total])} 里出现了饿死词 ⇒ 本用例已随采集策略漂移，"
        f"请把它重指到新的准入策略上（不要直接删）"
    )
    assert len(starved) == len(ordered) - total


# ── T3 · 实现落地后自动转真断言 ──────────────────────────────────
#
# B1（终止阶梯顺序不可反）与 B3（回合数不定仍正确终止）**本轮不生成**：它们要断言的是
# 外循环 `LiveDataSource.compute_stream` 的行为，而计划只定了它的名字与语义、没定事件载荷
# 的字段形状。此时在测试里手写一个 while 循环再断言它，等于把判据写在测试自己身上
# （恒真，抓不到任何生产缺陷）—— 正是 F1 那一类。故标为「待生成」，等 `compute_stream`
# 落地后按真实载荷写判据。B5 保留：它的契约（同锚点同半径不重发）与签名无关。

@needs_round
@needs_anchors
def test_same_anchor_same_radius_is_not_queried_twice():
    """B5 · 已证域必须被记住：同锚点同半径不得重发（否则回合数直接翻倍烧预算）。

    两层判据：① 单回合内重复锚点只发一次；② 跨回合喂回上一回合的 region 后零新增调用。
    """
    import asyncio

    dup = (107.9758, 26.5734)
    anchors = [dup, dup, (107.98, 26.57)]

    stub = _Stub()
    r1 = asyncio.run(
        pc.collect_triad_evidence(
            stub, region=None, anchors=anchors, pool=pc.POIBudget(total=30), round_no=1
        )
    )
    per_anchor = {c for _q, c, _r in stub.queries}
    assert stub.calls == len(per_anchor), (
        f"单回合内对同一锚点发了 {stub.calls} 次而锚点只有 {len(per_anchor)} 个 ⇒ 重复检索"
    )

    calls_r1 = stub.calls
    asyncio.run(
        pc.collect_triad_evidence(
            stub, region=r1, anchors=anchors, pool=pc.POIBudget(total=30), round_no=2
        )
    )
    assert stub.calls == calls_r1, (
        f"第 2 回合对同一批已证锚点又发了 {stub.calls - calls_r1} 次 ⇒ region 没被当作已证域"
    )
