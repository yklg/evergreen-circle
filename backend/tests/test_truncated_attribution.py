"""R23-D（#71）· `truncated` 那一位按**归责**拆成三位：一个词都不许丢，也不许说错责任。

拆之前的形状（计划 §20②）：`truncated_terms` 的谓词是 `not t.complete`，而 `is_exhausted`
只认 `complete` / `empty` ⇒ `page_cap`（我们没接着翻）、`dup_stop`（我们收页）、
`server_cap`（**它不给**）、`api_error`（**没发出去或没成**）四种归责共用那一句
「发了但没查全」。其中对 `api_error` 是**假话**（那一行由 `_api_error_row` 造，
docstring 自己写着"一次**没发出去**/发出去没成"），对 `server_cap` 是**归责错位**
（读者会以为加预算能拿到，实际是接口断页）。

拆之后的三条纪律，本文件逐条钉：
1. **守恒**（主防线）：三位并集 == 旧谓词 `{not complete}`，且两两互斥 ⇒ 拆分只是**换说法**，
   不是少说话。方向是"宁可多交代也不静默" —— 所以新谓词写成**排除式**：
   未知/将来新增的停止原因默认留在 `truncated`（第 3 条就是钉这个）。
2. **各说各的**：capped 那句不许出现"没翻"，failed 那句不许出现"发了但没查全"。
3. **`not_run` 不配拥有键**：它进不了 `per_term`（四条通道页深全 ≥1，第 5、6 条把这件事
   变成**被测住的**事实，而不是我记得的注释）⇒ 为一个结构上恒空的位造披露键 = 造一条假防线。
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from app.core.pipeline import diagnosis_templates as dt
from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import (
    STOP_API_ERROR, STOP_COMPLETE, STOP_DUP_STOP, STOP_EMPTY, STOP_NOT_RUN, STOP_PAGE_CAP,
    STOP_SERVER_CAP,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.quota import poi_page_depth
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


# 五种"没查全"的停法（`is_exhausted` 只认 complete/empty ⇒ 这五种都落进旧谓词）
NOT_EXHAUSTED = (STOP_PAGE_CAP, STOP_DUP_STOP, STOP_SERVER_CAP, STOP_API_ERROR, STOP_NOT_RUN)
# 拆完之后各自该去的位。⚠️ 刻意**不列** `not_run`：它进不了 `per_term`（第 6 节证的是这件事），
# 而万一哪天进来了，排除式谓词会把它兜进 truncated（第 3 条）—— 所以这里少一档是设计，不是漏。
ATTRIBUTION = {
    STOP_PAGE_CAP: "truncated",
    STOP_DUP_STOP: "truncated",
    STOP_SERVER_CAP: "capped",
    STOP_API_ERROR: "failed",
}


def _row(cat: str, term: str, stop: str) -> pc.TermEvidence:
    return pc.TermEvidence(category=cat, term=term, requested_radius_m=2000.0,
                           pages_fetched=0 if stop == STOP_API_ERROR else 1,
                           returned=0, total=None, stop_reason=stop,
                           farthest_m=None if stop in (STOP_COMPLETE, STOP_EMPTY, STOP_API_ERROR) else 900.0)


def _ev(per_term: Sequence[pc.TermEvidence]) -> pc.CollectionEvidence:
    return pc.CollectionEvidence(requested_radius_m=2000.0, per_term=tuple(per_term))


def _buckets(ev: pc.CollectionEvidence) -> Dict[str, Tuple[str, ...]]:
    return {"truncated": ev.truncated_terms, "capped": ev.capped_terms, "failed": ev.failed_terms}


def _old_predicate(ev: pc.CollectionEvidence) -> Tuple[str, ...]:
    """**换代前**那一条谓词，原样重述一遍只为了当差分基线（不参与任何生产判定）。"""
    return tuple(f"{t.category}:{t.term}" for t in ev.per_term if not t.complete)


# ──────────────── 1. 守恒：三位并起来恰好等于旧谓词，且两两互斥 ────────────────

def test_three_buckets_partition_the_old_predicate_exactly():
    ev = _ev([_row("medical", f"{kw}-{i}", stop) for i, stop in enumerate(NOT_EXHAUSTED)
              for kw in ("诊所", "医院")]
             + [_row("market", "菜市场", STOP_COMPLETE), _row("market", "生鲜市场", STOP_EMPTY)])
    old = set(_old_predicate(ev))
    buckets = _buckets(ev)
    assert old, "旧谓词是空的 ⇒ 下面只是在比空集"
    assert len(old) == 10, f"载荷本身不对：五种停法 × 两词 = 10 个唯一词，实得 {len(old)}"
    union = set().union(*(set(v) for v in buckets.values()))
    assert union == old, f"拆分丢了词或多词：只在新谓词 {sorted(union - old)} / 只在旧谓词 {sorted(old - union)}"
    names = list(buckets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            overlap = set(buckets[names[i]]) & set(buckets[names[j]])
            assert not overlap, f"{names[i]} 与 {names[j]} 重叠 ⇒ 同一词会被两句话各交代一次：{sorted(overlap)}"


# ──────────────── 2. 逐档归位：每种停法只进它该去的那一位 ────────────────

def test_each_stop_reason_lands_in_exactly_its_own_bucket():
    for stop, want in ATTRIBUTION.items():
        ev = _ev([_row("pharmacy", "药店", stop)])
        buckets = _buckets(ev)
        hit = [name for name, values in buckets.items() if values]
        assert hit == [want], f"{stop} 应只进 {want}，实际进了 {hit} ⇒ 归责错位或一句话替两种人说"


# ──────────────── 3. 排除式的价值：未知停止原因不许从披露里静默消失 ────────────────

def test_an_unknown_stop_reason_defaults_into_truncated_not_into_silence():
    """将来 `baidu_client` 加第四种"没查全"而没人记得改这里时，最坏表现必须是**多交代一句**。

    反向对照在同一条里：查全的两种（complete/empty）无论怎么写都不许进任何一位。
    """
    ev = _ev([_row("recreation", "公园", "brand_new_reason")])
    assert ev.truncated_terms == ("recreation:公园",), (
        f"未知停法被三位全部漏掉 ⇒ 报告对这一词一个字都不说：{_buckets(ev)}")
    assert ev.complete is False
    clean = _ev([_row("recreation", "公园", STOP_COMPLETE), _row("recreation", "绿地", STOP_EMPTY)])
    assert all(not v for v in _buckets(clean).values()), _buckets(clean)
    assert clean.complete is True


# ──────────────── 4. 读侧：两位各印各的话，且不许互相冒充 ────────────────

def test_the_two_new_clauses_say_their_own_truth_and_never_each_others():
    cap = {"evidence_capped_terms": ["pharmacy:药店"]}
    note_cap = dt._evidence_gap_note(cap, "pharmacy", "药店")
    assert note_cap == ("另需交代：本次有 1 个药店类检索词接口自称还有货却断了页（pharmacy:药店）"
                        + dt._GAP_TAIL), note_cap
    assert "发了但没查全" not in note_cap, "断页的词又被说成我们没翻完"

    fail = {"evidence_failed_terms": ["pharmacy:药店"]}
    note_fail = dt._evidence_gap_note(fail, "pharmacy", "药店")
    assert note_fail == ("另需交代：本次有 1 个药店类检索词请求没成（pharmacy:药店）"
                         + dt._GAP_TAIL), note_fail
    assert "发了但没查全" not in note_fail and "断了页" not in note_fail, note_fail

    # 别类不印（两位都是 `类:词` 形状的全类混合表）
    assert dt._evidence_gap_note(cap, "medical", "医疗") == ""
    assert dt._evidence_gap_note(fail, "medical", "医疗") == ""
    # 键缺席（R23-D 之前的存量快照）读作"不知道"，不许印成"没有词被断页/没成"
    assert dt._evidence_gap_note({}, "pharmacy", "药店") == ""


def test_a_class_can_hold_four_clauses_without_losing_the_prefix_contract():
    """同一类四种成因同时命中（starved + truncated + capped + failed）⇒ 四条子句共用**一个**前缀。

    这四种是**可以**同类的（不像 unfunded/out_of_budget 那样按 `searched` 互斥）：
    一个类既有被拒的词、又有没翻完的词、又撞上断页与失败，完全可能。
    """
    cal = {"evidence_starved_terms": ["pharmacy:卫生所"],
           "evidence_truncated_terms": ["pharmacy:药店"],
           "evidence_capped_terms": ["pharmacy:药房"],
           "evidence_failed_terms": ["pharmacy:医药公司"]}
    note = dt._evidence_gap_note(cal, "pharmacy", "药店")
    assert note.startswith("另需交代：") and note.count("另需交代：") == 1, note
    assert note.count("；") == 3, note
    for frag in ("因预算未发起", "发了但没查全", "接口自称还有货却断了页", "请求没成"):
        assert frag in note, f"{frag} 没上屏：{note}"


# ──────────────── 5. 发射面：两个新键必须从唯一发射点出去 ────────────────

def test_both_new_lists_reach_the_report_payload():
    from app.living_circle.data_source import bind_evidence

    ev = _ev([_row("pharmacy", "药店", STOP_SERVER_CAP), _row("pharmacy", "药房", STOP_API_ERROR),
              _row("pharmacy", "诊所", STOP_PAGE_CAP)])
    collected = pc.PoiCollection(per_category={}, triads={}, evidence=ev)
    cal = bind_evidence(_scope(), collected).payload(get_caliber("walking"))
    assert cal["evidence_capped_terms"] == ["pharmacy:药店"], cal["evidence_capped_terms"]
    assert cal["evidence_failed_terms"] == ["pharmacy:药房"], cal["evidence_failed_terms"]
    assert cal["evidence_truncated_terms"] == ["pharmacy:诊所"], cal["evidence_truncated_terms"]
    # 类级那份照旧在（它喂 unjudgeable_by_cap，与措辞无关）⇒ 拆分不许把它带走
    assert cal["evidence_capped_categories"] == ["pharmacy"], cal["evidence_capped_categories"]


# ──────────────── 6. `not_run` 进不了 per_term：页深地板是被测的事实 ────────────────

def test_no_page_depth_source_can_ever_be_zero_so_not_run_cannot_reach_per_term():
    """`STOP_NOT_RUN` 只是 `place_search` 的**初值**，页深跑满 0 次才会留在初值上。

    四条通道的页深来源逐条量下限：A 阶段走 `poi_page_depth`（含退化输入）、扩词走
    `_EXPANSION_PAGES`、三要素与取证回合是字面 1（后两条由下面那条源码扫描钉住）。
    ⇒ 本刀**不**为 `not_run` 造披露位（恒空键 = 没人能跑的判据）；造了反要被当成已覆盖。
    """
    depths = [poi_page_depth(n, b) for n in (0, 1, 22, 25, 100) for b in (-5, 0, 1, 27, 40, 1000)]
    assert min(depths) >= 1, f"页深出现了 0 ⇒ not_run 从此能进 per_term：{sorted(set(depths))}"
    assert pc._EXPANSION_PAGES >= 1, "B 阶段扩词的页深被改成 0 了 ⇒ 同上"


def test_every_place_search_call_site_in_the_collector_asks_for_at_least_one_page():
    """**按语法树**扫 `poi_collector.py` 里所有 `max_pages=` 实参：一条都不许是 0。

    ⚠️ 不用正则扫源码：本文件第一版就是那么写的，结果把 `:759` 那行**注释**里的
    「旧代码漏传 ⇒ 走 `max_pages=3` 默认」当成第五个调用点 —— 注释里的字面量碰巧 ≥1，
    于是它既不多也不少地**伪装成一条在跑的判据**。走 AST 才只认真调用。
    ⚠️ 也不锚变量名：能求值的直接求（`1` / `_EXPANSION_PAGES`），求不了的（`pages`）
    必须落在"已知来源表"里，出现新形状就红 ⇒ 改名、先算再夹、if 夹钳 都躲不过。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(pc))
    sites = [(node.lineno, ast.unparse(kw.value))
             for node in ast.walk(tree) if isinstance(node, ast.Call)
             for kw in node.keywords if kw.arg == "max_pages"]
    assert len(sites) >= 4, (
        f"AST 只抽到 {len(sites)} 个页深实参，比已知的四条通道还少 ⇒ 扫描面塌了（改写法了？）")
    known_derived = {"pages": [poi_page_depth(n, b) for n in (0, 1, 22, 25, 100)
                               for b in (-5, 0, 1, 27, 40, 1000)]}
    for lineno, expr in sites:
        if expr.isdigit():
            assert int(expr) >= 1, f"`: {lineno}` 字面页深写成了 {expr} ⇒ not_run 从此能进 per_term"
        elif expr.startswith("_"):
            assert int(getattr(pc, expr)) >= 1, f"`:{lineno}` {expr} 被改成 0 ⇒ 同上"
        else:
            assert expr in known_derived, (
                f"`:{lineno}` 出现未知的页深实参 `{expr}` ⇒ 求值表没覆盖它，先接进来再收工")
            assert min(known_derived[expr]) >= 1, f"`:{lineno}` {expr} 的取值里出现了 0"
