"""R23-C（乙2）· "这一类的覆盖度分子没查够"必须有一个**机器读得到**的数（计划 §16）。

毛病的确切形状（§15 已在真链路上实测到）：那几种成因今天**只有字** —— 那句话由
`diagnosis_templates._evidence_gap_note` 从成因键现场拼给人看（R23-D 起是**六种**：
starved / truncated / capped / failed / unfunded / out_of_budget），而机器读的 `evidence_complete`
只看"发出去的词查全没查全" ⇒ 同屏出现「这一类证据面不完整」+ `evidence_complete = True`。
本位（`coverage_numerator_incomplete_categories`）把"有没有这话"变成一个单一来源的数。

⚠️ 本刀**零行为变更**：不动 `evidence_complete` 的算法与取值（那是乙1，会改判盲/复用门/置信度），
不改正文一个字（第 8 条就是钉这一点的）。并集只在 `CollectionEvidence` 一处算，
读侧不许再并一次 —— 于是"两处算同一件事"这件事必须由本文件的**关系判据**钉住（第 2 条）。
⚠️ 第 2 条用的载荷走的是**生产路径**（`bind_evidence` → `payload()`）：R23-D 加两个键时，
早先那份手抄键名映射静默少发两位、把这条测成反向 —— 那才是它改造成真入口的原因。
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from app.core.pipeline import diagnosis_templates as dt
from app.living_circle import poi_collector as pc
from app.living_circle.baidu_client import (
    STOP_API_ERROR, STOP_COMPLETE, STOP_EMPTY, STOP_PAGE_CAP, STOP_SERVER_CAP,
)
from app.living_circle.caliber import get_caliber
from app.living_circle.category_rule import CATEGORY_RULES
from app.living_circle.geo_utils import xy_to_lnglat
from app.living_circle.scope import SpatialScope

CENTER = (102.75000, 25.01800)
RING_HALF = 2000.0
ALL_CATS = tuple(CATEGORY_RULES)


def _row(cat: str, term: str, stop: str = STOP_COMPLETE) -> pc.TermEvidence:
    return pc.TermEvidence(category=cat, term=term, requested_radius_m=2000.0,
                           pages_fetched=1, returned=3, total=3, stop_reason=stop,
                           farthest_m=None if stop == STOP_COMPLETE else 900.0)


def _ev(per_term: Sequence[pc.TermEvidence] = (),
        starved: Sequence[Tuple[str, str]] = (),
        unfunded: Sequence[str] = (),
        out_of_budget: Sequence[str] = ()) -> pc.CollectionEvidence:
    return pc.CollectionEvidence(
        requested_radius_m=2000.0, per_term=tuple(per_term), starved_terms=tuple(starved),
        expansion_unfunded=tuple(unfunded), expansion_out_of_budget=tuple(out_of_budget))


def _scope() -> SpatialScope:
    ring = [xy_to_lnglat(CENTER, -RING_HALF, -RING_HALF), xy_to_lnglat(CENTER, RING_HALF, -RING_HALF),
            xy_to_lnglat(CENTER, RING_HALF, RING_HALF), xy_to_lnglat(CENTER, -RING_HALF, RING_HALF)]
    zone = {"minutes": 20.0, "geojson": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}
    return SpatialScope.from_reach_zone(get_caliber("walking"), CENTER, 2500.0, zone)


def _caliber(ev: pc.CollectionEvidence) -> Dict[str, Any]:
    """走**生产那条路**拿 caliber：`bind_evidence`（唯一注入点）→ `scope.payload()`（唯一发射点）。

    ⚠️ 这里以前是手抄一份键名映射 —— R23-D 一加两个键，那份手抄就静默少发两位，
    把"正文印不印 ⇔ 并集有没有"这条关系判据测成反向（第 2 条当场红）。⇒ 不抄：
    生产会发什么，由生产自己说。
    ⚠️ 代价是载荷必须**自洽**：`with_evidence` 自己有一道闸（"声称查全 ⇒ 边界必须等于请求半径"），
    而合成载荷通常没有三要素那三行 ⇒ 边界算出来是 0、闸当场拦。补的三行**全是查全**，
    既不进并集也不印话 —— 它们只是让那道闸量得到东西，不参与任何被断言的位。
    """
    from dataclasses import replace

    from app.living_circle.data_source import bind_evidence
    from app.living_circle.scope import TRIAD_KEYS

    scope = _scope()
    filler = [pc.TermEvidence(
        category=c, term=f"{c}·三要素", requested_radius_m=scope.required_radius_m(c),
        pages_fetched=1, returned=1, total=1, stop_reason=STOP_COMPLETE, farthest_m=None)
        for c in TRIAD_KEYS]
    full = replace(ev, per_term=tuple(ev.per_term) + tuple(filler))
    collected = pc.PoiCollection(per_category={}, triads={}, evidence=full)
    return bind_evidence(scope, collected).payload(get_caliber("walking"))


# ──────────── 1. 四种成因各命中一次 ⇒ 都要进并集，且各自都要有活证人 ────────────

def test_each_of_the_four_causes_lands_in_the_union():
    cases = {
        "starved": _ev(starved=[("medical", "社区医院")]),
        "truncated": _ev(per_term=[_row("education", "小学", STOP_PAGE_CAP)]),
        "unfunded": _ev(unfunded=["shopping"]),
        "out_of_budget": _ev(out_of_budget=["elderly"]),
    }
    witnesses = {
        "starved": lambda e: e.starved_terms,
        "truncated": lambda e: e.truncated_terms,
        "unfunded": lambda e: e.expansion_unfunded,
        "out_of_budget": lambda e: e.expansion_out_of_budget,
    }
    got: List[str] = []
    for name, ev in cases.items():
        assert witnesses[name](ev), f"{name} 那一位本身就没记账 ⇒ 这条对它是恒真"
        got += list(ev.coverage_numerator_incomplete)
    assert got == ["medical", "education", "shopping", "elderly"], got


# ──────────── 2. 关系判据（本刀的全部风险）：正文印不印 ⇔ 并集有没有 ────────────

def test_the_note_prints_for_exactly_the_categories_in_the_union():
    """两处算同一件事（写侧算并集、读侧按成因拼话）⇒ 必须逐类对得上，不许悄悄分叉。"""
    ev = _ev(per_term=[_row("medical", "药店", STOP_PAGE_CAP), _row("market", "菜市场"),
                       _row("finance", "银行", STOP_API_ERROR)],
             starved=[("medical", "社区医院"), ("education", "小学")],
             unfunded=["shopping"], out_of_budget=["elderly"])
    cal = _caliber(ev)
    assert cal["coverage_numerator_incomplete_categories"], "并集是空的 ⇒ 下面只是在比空集"
    for cat in ALL_CATS:
        printed = dt._evidence_gap_note(cal, cat, cat) != ""
        in_union = cat in cal["coverage_numerator_incomplete_categories"]
        assert printed == in_union, (
            f"{cat}：正文{'印' if printed else '不印'}、并集{'有' if in_union else '无'} ⇒ 两处已分叉")
    # 没被任何成因命中的类必须两边都没有（否则第 2 条退化成"两边都真"）
    quiet = [c for c in ALL_CATS if c not in cal["coverage_numerator_incomplete_categories"]]
    assert quiet, "所有类都进了并集 ⇒ 这条否证半边没跑起来"
    assert all(dt._evidence_gap_note(cal, c, c) == "" for c in quiet), quiet


# ──────────── 3. 一无所知的行（api_error）算"没查够" ────────────

def test_api_error_row_counts_as_incomplete_not_as_clean():
    ev = _ev(per_term=[_row("recreation", "公园", STOP_API_ERROR)])
    assert ev.coverage_numerator_incomplete == ("recreation",)
    assert ev.complete is False, "并集说有缺口、complete 却说完整 ⇒ 两处判据不同源"


# ──────────── 4. 服务端断页进并集，但走 capped 那一位（R23-D 起不再借 truncated） ────────────

def test_server_capped_category_enters_via_capped_not_via_truncated():
    """`STOP_SERVER_CAP` 不在 `is_exhausted` 里 ⇒ 那一行本来就是"没查够"；R23-D 起它
    **从 `capped_terms` 进并集**，不再混在 `truncated_terms` 里。

    记两条历史：①计划里一度写成"并集不含 capped"—— 那是**错的**（本位判的是 `not complete`）；
    ②R23-D 之前这条断的是「truncated 里有它、正文说'发了但没查全'」—— 那是**归责错位**
    （读者会以为加预算能拿到），现在钉的是"该说的是接口断了页"。

    ⚠️ 类别用 `pharmacy`（三要素键）而不是随手一个关键词类：本条断的是**并集归责**，
    而 `bind_evidence` 只把三要素那三类的边界交进 `evidence_frontier_m`。历史上那与
    `scope.invariant` 那道封顶闸的对照面混过一件事 —— 非三要素类撞封顶会在绑定期被
    读成"类名写错"并抛 `ValueError`（#81，本文件第 4 条改走真入口时现形）。**#81 已修**
    （闸改为比对 `evidence_stop_reasons`，判据见 `test_capped_category_gate.py`），
    这里仍留 `pharmacy` 是因为换类不增加本条的覆盖面，只把它和新那批混成一件事。
    """
    ev = _ev(per_term=[_row("pharmacy", "药店", STOP_SERVER_CAP)])
    assert ev.capped_categories == ("pharmacy",)
    assert ev.capped_terms == ("pharmacy:药店",)
    assert ev.truncated_terms == (), "断页的词又回到 truncated ⇒ 那句「发了但没查全」会替它说谎"
    assert ev.coverage_numerator_incomplete == ("pharmacy",)
    note = dt._evidence_gap_note(_caliber(ev), "pharmacy", "药店")
    assert "接口自称还有货却断了页" in note, note
    assert "发了但没查全" not in note, note


# ──────────── 5. 反向对照：全都查全 ⇒ 并集空、正文空 ────────────

def test_clean_collection_yields_neither_union_nor_note():
    ev = _ev(per_term=[_row("medical", "药店", STOP_COMPLETE), _row("medical", "诊所", STOP_EMPTY)])
    assert ev.per_term, "一行都没有 ⇒ 这条只是在比空集，说明不了「查全」的形状"
    assert ev.coverage_numerator_incomplete == ()
    assert ev.complete is True
    cal = _caliber(ev)
    assert all(dt._evidence_gap_note(cal, c, c) == "" for c in ALL_CATS)


# ──────────── 6. 写侧只许一处：as_detail → scope.payload ────────────

def test_union_reaches_the_report_payload_from_the_same_place():
    ev = _ev(out_of_budget=["education"])
    assert ev.as_detail()["coverage_numerator_incomplete_categories"] == ["education"]
    cal = _caliber(ev)
    assert cal["coverage_numerator_incomplete_categories"] == ["education"], (
        f"发射点没带这个键：{cal.get('coverage_numerator_incomplete_categories')}")


# ──────────── 7. 一类占三种成因：并集只列一次，正文三条并列 ────────────

def test_a_category_with_three_causes_appears_once_but_prints_three_clauses():
    ev = _ev(per_term=[_row("medical", "药店", STOP_PAGE_CAP)],
             starved=[("medical", "社区医院")], out_of_budget=["medical"])
    assert ev.coverage_numerator_incomplete == ("medical",)
    note = dt._evidence_gap_note(_caliber(ev), "medical", "医疗")
    assert note.count("；") == 2 and note.count("另需交代：") == 1, note


# ──────────── 8. 零行为变更：正文一个字都不许多依赖这个新键 ────────────

def test_the_note_does_not_depend_on_the_new_key_at_all():
    """旧快照（没有并集键）上正文照旧印 ⇒ 证明本刀没把措辞改挂到新键上。

    挂上去就是行为变更：换代前那 30 份报告的这句话会整体消失。
    """
    old = {"evidence_expansion_out_of_budget_categories": ["education"],
           "evidence_starved_terms": ["education:小学"]}
    assert "coverage_numerator_incomplete_categories" not in old
    note = dt._evidence_gap_note(old, "education", "教育")
    assert "因预算未发起" in note and "因额度见底中断" in note, note
    assert dt._evidence_gap_note({}, "education", "教育") == ""
