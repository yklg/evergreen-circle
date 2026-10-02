"""民生 POI：类别表 / 多关键词采集 / 清洗去重 / 分类覆盖统计。

三大口径（与前端 F0 契约 / 赛题一致）：
  - 8 类民生类别 → `FacilityCategoryStat[]`（category/total/in_circle/coverage/min_minutes/nearest）
  - 盲区三要素（菜市场/药店/小学）→ 独立 POI 点集，供 blindspot.py 做 1km 判定
判表唯一事实源 = `category_rule.CATEGORY_RULES`：本模块的 `CATEGORY_DEFS` /
`TRIAD_KEYWORDS` 由它**派生**（仅补 is_market），不再双写两套判表（rev3 §四A/P1-1）。
采集策略：每类多关键词查全率（百度 place/v2/search），名称归一 + 50m 聚簇去重。
"""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.living_circle.category_rule import (
    CATEGORY_RULES,
    SUB_KIND_TABLE,
    TRIAD_RULES,
    evaluate_category,
    sub_kind_of,
    sub_kind_rule_labels,
)
from app.living_circle.facility_rule import (
    annotate_name,
    facility_core,
    norm_name,
    pick_display_name,
    pick_representative,
    same_facility,
    sub_point_labels,
)
from app.living_circle.geo_utils import haversine_m, point_in_ring, round_lnglat
from app.living_circle.scope import SpatialScope

# ── 每类点位**展示**上限（唯一共享常量）──────────────────────────
# 计划 §8-D3：25 → 200。当前最大类别（shopping 圈内 31）永不触发，
# 但**保留最后一道防线**：某天某城市抓回 500 个点时，报告体积与前端页面不至于被压垮。
#
# ⚠️ 语义边界（两条口径不可混）：
#   - 本值决定「**展示多少**」，**不决定「抓回多少」**（那是 `quota` 的职责）⇒ **不消耗检索额度**；
#   - 因此采集出口（`poi_collector.merge_all`）**不得**再用它截一次 —— 在采集侧截断会把
#     `poi.total`（采集口径，含圈外）一并压小，等于让「展示上限」篡改了「采集事实」。
#   - **唯一截断点 = 本模块 `to_points`**，且必须产出 `truncated` 披露（阶段 1.3）。
POI_CAP_PER_CAT = 200


class PoiConservationError(RuntimeError):
    """点数守恒 `sum(categories[].in_circle) == len(points)` 被打破（阶段 1.4）。

    只在**测试 / CI** 抛出（`conservation_policy() == 'strict'`）；生产 / 演示走
    「照出报告 + `poi.conservation.ok=false` 留痕」，但**任何环境都不静默**。
    """


class PoiPointsOut(NamedTuple):
    """`to_points` 的返回：点位 + **截断披露**（阶段 1.3）。

    `truncated` 逐类记录 `{"category", "kept", "dropped"}`，**只含真的发生截断的类别**
    （无截断即 `[]`）。用 NamedTuple 而非裸 list：截断信息**无法被顺手丢掉**，
    而调用方仍可 `points, truncated = to_points(...)` 解包。

    调用方必须把它落进 ``poi.truncated`` ——「静默截断」正是本阶段要消灭的缺陷
    （旧实现在 `poi.py:237` 无声无息地砍掉 6 条购物点，报告里看不出任何痕迹）。
    """
    points: List[Dict[str, Any]]
    truncated: List[Dict[str, Any]]


def _build_category_defs() -> Dict[str, Dict[str, Any]]:
    """从 `category_rule.CATEGORY_RULES` 派生（键/词表/阈值单一来源，仅补 poi 专有 is_market）。"""
    defs: Dict[str, Dict[str, Any]] = {}
    for key, rule in CATEGORY_RULES.items():
        d: Dict[str, Any] = {
            "label": rule["label"],
            "keywords": list(rule["keywords"]),
            "ideal_circle": rule["ideal_circle"],
        }
        if key == "market":
            d["is_market"] = True
        defs[key] = d
    return defs


def _build_triad_keywords() -> Dict[str, str]:
    """从 `category_rule.TRIAD_RULES` 派生 `{key: 检索词}`（盲区三要素兼容视图）。"""
    out: Dict[str, str] = {}
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_"):
            continue
        kw = ""
        if isinstance(ref, dict):
            kw = (ref.get("keywords") or [""])[0]
        elif isinstance(ref, str):
            kw = ref
        if kw:
            out[key] = kw
    return out


# ── 民生类别表（category 键与前端 fixture 保持一致）───────
# keywords：百度 place 检索关键词组（多词查全率）；ideal_circle：圈内理想阈值（评分基准）
CATEGORY_DEFS = _build_category_defs()

# 盲区三要素（赛题硬判口径：1km 内无菜市场/药店/小学）
TRIAD_KEYWORDS = _build_triad_keywords()


# `norm_name` 的定义已归入 `facility_rule`（纯判表层不得反向依赖本模块，否则 import 成环），
# 由上方 import 再导出：`poi.norm_name` 仍可寻址，口径索引 `poi::norm_name` 与专家团绑定照旧命中。


# 「坐标重合」的强合并阈值（米）：不同名但贴脸同址（同一门牌）视为重复。
# 10m 量级 ≈ 临街店铺门面宽度，避免把「同一家店被不同名重复返回」漏掉，
# 同时绝不误伤同一街区的相邻不同名设施（金马/瑞霖便利店，>10m）。
DUPLICATE_NEAR_M = 10.0


def is_duplicate(a: Dict[str, Any], b: Dict[str, Any], radius_m: float = 50.0) -> bool:
    """两条 POI 是否判重（v5 D3 单一实现）：
    （同名 且 距离 < radius_m） 或 （距离 < DUPLICATE_NEAR_M）。

    - 同名 <50m：同一家店被多关键词重复返回 → 合并；
    - 不同名 ≥10m：相邻同类型设施（金马/瑞霖便利店）→ **保留**；
    - 不同名 <10m：贴脸同址（名称只是别称/店招差异）→ 合并。
    """
    d = haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"]))
    if d < DUPLICATE_NEAR_M:
        return True
    return norm_name(a.get("name", "")) == norm_name(b.get("name", "")) and d < radius_m


def _facility_merges(a: Dict[str, Any], b: Dict[str, Any], radius_m: float) -> bool:
    """是否**因设施实体判据**而合并（排除 `is_duplicate` 本来就会合掉的情形）。

    用于记账：`poi.merged.absorbed` 必须只数「这次新合掉的设施」，掺进同名重复
    就把一个口径变更的数量和一个既有行为的数量混成了一个数字。
    """
    if is_duplicate(a, b, radius_m):
        return False
    return same_facility(a, b, haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"])), radius_m)


def _same_or_facility(a: Dict[str, Any], b: Dict[str, Any], radius_m: float) -> bool:
    """几何判重 **或** 同一实体设施。判据分别来自 `is_duplicate` 与 `facility_rule`，
    本函数是唯一把两者并列的地方 —— 实体判据绝不下沉进 `is_duplicate`（见其 docstring）。
    """
    if is_duplicate(a, b, radius_m):
        return True
    return same_facility(a, b, haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"])), radius_m)


def absorbed_key(it: Dict[str, Any]) -> Tuple[str, float, float]:
    """被吸收记录的身份键 —— 用于把「判据命中次数」折算成「少掉的设施条数」。

    采集要跑 A/B/C 三轮去重，S8 扩词会把同一个 ATM 再抓回来再合一次；按次数记账
    会把同一个设施数两遍，报告里的 `absorbed` 就成了一个无从核对的大数。
    """
    return (it.get("name", ""), round(float(it.get("lng", 0.0)), 5), round(float(it.get("lat", 0.0)), 5))


def dedupe_facility(
    items: List[Dict[str, Any]], radius_m: float, center: Tuple[float, float]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """设施实体聚组：每组出 1 个代表点，返回 (代表点列表, **因归并而**被吸收的记录)。

    **星型而非单链**：候选只与「当前组的锚点」比对，锚点 = 组内距 `center` 最近者。
    单链（与任一成员判重即入组）会让沿街同品牌的 支行↔ATM个贷中心↔支行B 串成一长条。

    代表点携带 `name`（组内主点名，全组皆子点时升格为其所属机构名，撞名则不升格）与
    `sub_points` / `sub_roles`。**「含某职能」的标注不在这里拼** —— 采集期要连续过
    A/B/C 三轮去重，把展示装饰拼进 `name` 会让下一轮把它当子点后缀重新匹配、重复叠加。
    拼接只发生在 `to_points`（点位唯一出口）。
    """
    valid = [it for it in items if it and it.get("lat") is not None and it.get("lng") is not None]
    # 升格撞名护栏：输入里所有主点的原名
    parent_names = {
        it["name"] for it in valid
        if it.get("name") and not facility_core(it["name"]).is_sub_point
    }

    remaining = list(valid)
    kept: List[Dict[str, Any]] = []
    absorbed: List[Dict[str, Any]] = []
    while remaining:
        seed = remaining.pop(0)
        members = [seed]
        anchor = seed
        i = 0
        while i < len(remaining):
            cand = remaining[i]
            if _same_or_facility(cand, anchor, radius_m):
                if _facility_merges(cand, anchor, radius_m):
                    absorbed.append(cand)
                members.append(cand)
                remaining.pop(i)
                if haversine_m((cand["lng"], cand["lat"]), center) < haversine_m(
                    (anchor["lng"], anchor["lat"]), center
                ):
                    anchor = cand
            else:
                i += 1

        rep = pick_representative(members, center)
        out = dict(rep)
        out["name"] = pick_display_name(members, rep, sorted(parent_names))
        others = [m for m in members if m is not rep]
        labels = sub_point_labels(members)
        if labels:
            out["sub_roles"] = labels
        if others:
            out["sub_points"] = [[m["lng"], m["lat"]] for m in others]
        kept.append(out)
    return kept, absorbed


def dedupe_pois(
    items: List[Dict[str, Any]],
    radius_m: float = 50.0,
    policy: str = "geometric",
    center: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """聚簇去重（o(n²) 在小样本下足够，每类 ≤ 几十条）。

    两条策略，**由调用点显式选定**（`poi_collector` 分通道传）：
      - `policy="geometric"`（默认）：判据只有 `is_duplicate`，半径内保留先到者。
        这条分支的实现**逐字保持原样** —— 盲区三要素（菜市场/药店/小学）走它，
        因为「1km 内有没有」是硬判，宁多勿少，不因归并少一个坐标。
      - `policy="facility"` **且** 传了 `center`：改走 `dedupe_facility`，同一实体设施
        只出一个代表点。缺 `center` 时**静默退回 geometric**（星型聚组必须有距离参照，
        拿可达区环顶点当圆心会让「最近设施」变成「离某个环顶点最近的设施」）。

    判据唯一实现 = `is_duplicate`（D3）+ `facility_rule.same_facility`，`clean` 与
    `poi_collector` 共用，消除两处 50m 逻辑双份漂移（R3/问题 3 根因）。
    """
    if policy == "facility" and center is not None:
        return dedupe_facility(items, radius_m, center)[0]
    kept: List[Dict[str, Any]] = []
    for it in items:
        if not it or it.get("lat") is None or it.get("lng") is None:
            continue
        if any(is_duplicate(it, k, radius_m) for k in kept):
            continue
        kept.append(it)
    return kept


def clean(items: List[Dict[str, Any]], dedupe_radius_m: float = 50.0) -> List[Dict[str, Any]]:
    """清洗管道：过滤无坐标 → 坐标落点规整 → 聚簇去重（保先到者优先）。"""
    valid = [it for it in items if it.get("lat") is not None and it.get("lng") is not None]
    seen_names: set = set()
    out: List[Dict[str, Any]] = []
    for it in valid:
        key = f"{norm_name(it.get('name', ''))}|{round(it['lng'], 5)}|{round(it['lat'], 5)}"
        if key in seen_names:
            continue
        seen_names.add(key)
        out.append({**it, "lng": round(it["lng"], 6), "lat": round(it["lat"], 6)})
    return dedupe_pois(out, dedupe_radius_m)


def stamp_sub_kind(items: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    """给**采集侧原始点位**就地派生 `sub_kind`（唯一盖章点）；没建子类表的类别原样返回。

    ⚠️ 传进来的名字必须是 `annotate_name` 加工**之前**的原始名（§二 规范句）：
    被吸收子点拼进父名的「· 含大药房」一类后缀一旦参与，父点子类会被子点决定。
    ⇒ 因此盖章只发生在两处：读侧 `to_stats`、采集侧收手闸（R23-B2），两处都在归并之前。
    """
    if category not in SUB_KIND_TABLE:
        return items
    return [{**it, "sub_kind": sub_kind_of(it, category)} for it in items]


def required_count_from_raw_points(items_in_circle: List[Dict[str, Any]],
                                   category: str) -> Optional[int]:
    """门槛项数，但吃**还没盖章**的点位：盖章 + 计数一次做完（R23-B2 的采集侧收手闸用）。

    存在理由：`required_count_from_points` 要求每颗点带 `sub_kind`，而采集侧的点位没有
    —— 让调用方自己决定"要不要先盖章"就会留下第二份口径（忘了盖 ⇒ 恒 `None` ⇒ 收手闸
    静默退回点数，看起来像"这一类没门槛口径"）。所以这里把两步焊成一个原子。
    语义与 `required_count_from_points` 逐字相同（`None` = 这一类没有门槛项口径可言）。
    """
    return required_count_from_points(stamp_sub_kind(items_in_circle, category), category)


def required_count_from_points(points: List[Dict[str, Any]],
                               category: str) -> Optional[int]:
    """门槛项数 = `cov-1` 的**分子**；返回 ``None`` = 这一批点位**没有门槛项口径可言**（走点数）。

    两种 ``None``：① 该类别没建子类表；② 建了表但这批点位**不是每颗都带 `sub_kind` 键**
    （= 旧口径载荷：存量 30 份与回填前的夹具都是这一形态，§六「读侧按旧口径解释、不回填」）。
    ⚠️ ② 用 `all` 而不是 `any`（第二十一轮评审 P2-b）：**半迁移批次**（有的点带键、有的不带）在
    `any` 下会被当成新口径，没带键的那几颗直接不进分子 —— 那是**少算**，而本批的原则是"读不准就按旧的、保守解释"。
    生产两处写点（`to_points` / `to_stats`）都是**全量盖章**，所以 `all` 不会把自家新产物误判成旧载荷；
    而"点里有字段但判成非门槛（`other`/诊所）"仍不会被当成旧载荷 —— 那是**带着值**的。
    ⚠️ 但**空批次不算②**：建了表而该类一颗点都没有 ⇒ 返回 0 而不是 None —— 两种读法在这里给出
    同一个 0，而"门槛项 0 ⇒ 真缺口"恰恰是最需要上屏的那一句（`elderly` 这类没表的类别仍返回 None，
    它没有门槛口径可言）。
    """
    table = SUB_KIND_TABLE.get(category)
    if table is None:
        return None
    if not points:
        return 0
    if not all("sub_kind" in p for p in points):
        return None
    return sum(1 for p in points
               if (table.get(p.get("sub_kind")) or {}).get("required"))


def coverage_from_points(points: List[Dict[str, Any]], ideal: int, category: str) -> float:
    """覆盖度 = ``min(1.0, 分子 / ideal)`` —— **全仓唯一一份算式**（计划 §三 第 1 条）。

    两口径的差别**只写在分子上**（分子的唯一出处是 `required_count_from_points`，
    连"这一类到底按哪个口径"这件事也只在那里判一次），函数体里只许出现这一个 `min`：
    写成两个分支各带一个 `min` 就违反"单一算式"，也会被
    `test_coverage_formula_has_single_implementation`(T2) 的正向半边抓住。

    ⚠️ 代价必须知道：新口径落地后，凡是**没经过 `to_points`** 就喂进来的点位（手搓载荷、旧回放）
       都会静默按点数算 ⇒ 落点只有 `to_points` 会写 `sub_kind`（§三 第 3 条的硬前提），
       判据是 T1 的第二半（`derive_stats_from_points` 必须给出门槛项口径的 1/3）。
    """
    numerator = required_count_from_points(points, category)
    if numerator is None:
        numerator = len(points)
    return min(1.0, numerator / ideal)


def to_stats(
    per_category: Dict[str, List[Dict[str, Any]]],
    triads: Dict[str, List[Dict[str, Any]]],
    scope: SpatialScope,
    center: Tuple[float, float],
) -> List[Dict[str, Any]]:
    """类别统计：圈内数 / 覆盖度 / 最近设施（步行耗时由调用方注入则用，否则用距离换算提示）。

    coverage = min(1, **门槛项数** / ideal_circle)（`cov-1` 的分子；出处只有
    `required_count_from_points` 一处）；min_minutes 由调用方在测时后填充（此处填 None 占位，
    live 管线在 poi+isochrone 后统一回填 nearest_minutes）。
    ⚠️ 第二十一轮评审 P2-a：这句原本写的是 `min(1, in_circle / ideal_circle)` —— 分子换代后**注释还在说点数**，
    而 `in_circle` 今天仍然如实报点数（它是"图上画了几颗"，不进覆盖度）。

    「圈内」= **可达区**（``scope.reach_ring``）。形参从 ``iso15_ring`` 改为 ``scope``：
    旧形参名承诺 15min 圈、实收 20min 圈、文档又写 15min，**三处不一致且没有任何一层能发现**；
    现在圈从 ``scope`` 取，而 ``scope`` 的构造已校验过环的 ``minutes == caliber.reach_full_min``。
    """
    reach_ring = scope.reach_ring
    stats: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        defn = CATEGORY_DEFS[cat]
        in_circle = [it for it in items if point_in_ring((it["lng"], it["lat"]), reach_ring)]
        ideal = defn["ideal_circle"]
        # `to_stats` 吃的是**采集侧原始点位**（尚未被 `annotate_name` 拼过后缀）⇒ 在这里就地派生
        # `sub_kind` 是安全的，也正是 §二 规范句要的"原始名那一侧"。盖章只住在 `stamp_sub_kind`
        # 一处（采集侧收手闸 R23-B2 走同一处），没建表的类别原样返回 ⇒ 让
        # `coverage_from_points` 走它自己的"无表 ⇒ 点数"支，两支不在此重复。
        scored = stamp_sub_kind(in_circle, cat)
        coverage = coverage_from_points(scored, ideal, cat)
        labels = sub_kind_rule_labels(cat)
        nearest = None
        nearest_d = float("inf")
        # 兜底「最近」只在**圈内**点里取 —— 与下方 `in_circle`/`coverage` 同一个域。
        # 旧实现在 `items`（采集口径，含圈外）上取最近 ⇒ 圈内一个点都没有的类别
        # 也能报出一个「最近设施名」，采集半径一旦外扩就被放大。
        for it in in_circle:
            d = haversine_m((it["lng"], it["lat"]), center)
            if d < nearest_d:
                nearest_d = d
                nearest = it
        stats.append({
            "category": cat,
            "label": defn["label"],
            "total": len(items),
            "in_circle": len(in_circle),
            "coverage": round(coverage, 4),
            # 门槛项数（`cov-1` 的分子）随覆盖度一起落盘 ⇒ 前端只许读这一个数，
            # 绝不在展示侧重判子类（那会是第二份判类实现）。`None` = 这一类没有门槛项口径可言。
            "required_in_circle": required_count_from_points(scored, cat),
            # 门槛项**名单**（`scored_as` 计分 / `unscored_as` 不计分）：与分子读同一张
            # `SUB_KIND_TABLE`，但**不吃点位**（`sub_kind_rule_labels`）⇒ 展示侧那句
            # 「覆盖度只数「小学」」里的名字与数字都来自 payload，前端一个字都不自己判（片 1c-β C1 甲档）。
            # 没建表的类别 ⇒ 两个都是 `None`（不是 `[]`：空名单会说"这一类没有不计分的形状"，那是假话）。
            "scored_as": labels[0] if labels else None,
            "unscored_as": labels[1] if labels else None,
            "min_minutes": None,  # 测时后回填
            "nearest_name": nearest.get("name") if nearest else None,
        })
    # 盲区三要素点集归一化输出（供 blindspot 复用，避免重复检索）
    return stats


def backfill_nearest_minutes(
    stats: List[Dict[str, Any]],
    per_category: Dict[str, List[Dict[str, Any]]],
    field_fn,
) -> List[Dict[str, Any]]:
    """`min_minutes` / `nearest_name` 的**唯一生产者**（`assemble.build_report` 活路径调用）。

    `field_fn(point) -> 分钟数`（不可达返回 None）—— 封顶谓词由调用方持有，本函数**必须**
    只经它取值：只有如此，「最近 X 分钟」才与三要素卡（`triad_from_points` 走同一个
    `field_fn`）同源同域。此前该函数从未被生产代码调用，装配层另写了一份不过封顶的
    实现，导致采集区（含圈外）的设施能定出「最近」—— 见 `assemble.py` 的封顶注释。
    """
    for s in stats:
        cat = s["category"]
        items = per_category.get(cat, [])
        best: Optional[Dict[str, Any]] = None
        best_m = None
        for it in items:
            m = field_fn((it["lng"], it["lat"]))
            if m is None:
                continue
            if best_m is None or m < best_m:
                best_m = m
                best = it
        s["min_minutes"] = round(best_m, 1) if best_m is not None else None
        if best is not None:
            s["nearest_name"] = best.get("name")
    return stats


def triad_point_sets(triads: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Tuple[float, float]]]:
    """三要素 POI → 坐标集。"""
    return {
        k: [round_lnglat(it["lng"], it["lat"]) for it in v]
        for k, v in triads.items()
        if v
    }


def to_points(
    per_category: Dict[str, List[Dict[str, Any]]],
    times_by_cat: Dict[str, List[Optional[float]]],
    scope: SpatialScope,
    center: Tuple[float, float],
    cap_per_cat: int = POI_CAP_PER_CAT,
) -> PoiPointsOut:
    """原始 POI → 报告点位（真实坐标，供前端 BMapGL 渲染，对齐 PoiPoint 契约）。

    - **只输出可达区内的点**（圈外不展示、不进报告）：旧实现把 2km 采集圈内的点全量输出，
      实测 151 条里只有 18 条在圈内（88% 圈外），展示层只按条数截断 ⇒ 用户看到「圈外地点被检索出来」。
    - 每类排序键 = 「圈内有耗时优先 → 有耗时优先 → **距离近**优先」后截断 ``cap_per_cat`` 条。
      旧实现第三键是**名称字母序** ⇒ 留下的是「按名字挑的点」而不是「离得近的点」。
    - ``center`` 是**查询中心**（必传）：距离以它为参照，不能用可达区环的顶点（环顶点顺序随
      ``linspace`` 行进方向而定，拿 `ring[0]` 当圆心会让「最近的设施」变成「离某个顶点最近的设施」）。
    - ``id`` 稳定可溯源（``poi-{category}-{idx}``）；``lnglat`` 输出 BD-09 ``[lng, lat]``。

    **返回值是 :class:`PoiPointsOut`（点位 + 截断披露），不是裸 list**（阶段 1.3）：
    截断必须随点位一起交回调用方，让它**没法「顺手」把 6 条被砍掉的购物点变没**。
    判定「截断是否发生」只看 `len(entries) > cap_per_cat`，与排序键无关。
    """
    reach_ring = scope.reach_ring
    points: List[Dict[str, Any]] = []
    truncated: List[Dict[str, Any]] = []
    for cat, items in per_category.items():
        times = times_by_cat.get(cat, [])
        entries: List[Dict[str, Any]] = []
        for idx, it in enumerate(items):
            t = times[idx] if idx < len(times) else None
            in_reach = point_in_ring((it["lng"], it["lat"]), reach_ring)
            if not in_reach:
                continue  # 圈外点：不展示、不进报告、不计分
            conf = _point_confidence(it)
            raw_name = it.get("name") or ""
            entries.append({
                "id": f"poi-{cat}-{idx}",
                "name": annotate_name(raw_name or (CATEGORY_DEFS.get(cat, {}).get("label", cat)),
                                      it.get("sub_roles") or ()),
                "category": cat,
                # ⚠️ 子类**吃 `raw_name`（`annotate_name` 之前）**，绝不吃上面那个 `name`：
                # 归并会把被吸收方的职能拼成「· 含大药房」一类后缀，让子点替父点决定子类
                # （§二 规范句；判据 T18）。没建表的类别 ⇒ None，覆盖度那一支自动退回点数口径。
                "sub_kind": sub_kind_of({"name": raw_name, "tag": it.get("tag") or "",
                                         "type": it.get("type") or ""}, cat),
                "lnglat": [round(it["lng"], 6), round(it["lat"], 6)],
                "minutes": round(t, 1) if t is not None else None,
                "in_circle": True,
                "_distance_m": haversine_m((it["lng"], it["lat"]), center),
                "_confidence": conf,
            })
        # 排序键 = 可达→minutes 非空→confidence 高→距中心近（rev3 P1-2 单一排序键；
        # confidence 由 category_rule 派生，杜绝名称字母序，也不在别处再做一轮排序）。
        entries.sort(key=lambda p: (p["minutes"] is None, -p["_confidence"], p["_distance_m"]))
        kept = entries[:cap_per_cat]
        dropped = len(entries) - len(kept)
        if dropped > 0:
            truncated.append({"category": cat, "kept": len(kept), "dropped": dropped})
        for p in kept:
            p.pop("_distance_m", None)
            p.pop("_confidence", None)  # 排序键属内部元数据，不进报告点位契约
            points.append(p)
    return PoiPointsOut(points, truncated)


def derive_stats_from_points(
    stats: List[Dict[str, Any]], points: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """把 `categories[].in_circle` / `coverage` **收敛到 `points` 这个唯一真身**（阶段 1.2）。

    这是本计划的核心动作：报告里「圈内 N 处」与「图上 M 个点」从此**只有一个真身**
    （`points`），面板数字由它派生 ⇒ 二者不可能再对不上。

    - ``in_circle`` = 该类别在 `points` 里的条数（可达口径 = 图上实际画了几个）；
    - ``coverage`` = ``min(1, 门槛项数 / ideal_circle)`` **重算**（`cov-1` 分子，出处同 `to_stats`）
      —— 不重算的话 `coverage` 与 `in_circle` 又成两条链（截断后 coverage 仍按截断前算）；
      ⚠️ 喂进来的 `points` **不带 `sub_kind`**（= 存量 30 份那种旧载荷）⇒ 分子退回点数，
      这条回退是本函数的**主路径**，判据见 `test_subkind_caliber.py` 的 T1/T21；
    - ``total`` **不动**：它是**采集口径**（含圈外的 `per_category` 计数）。
      审查 R1 修正 —— 若也从 points 反算，「采集 217」会塌成 98，信息永久丢失。
    - ``min_minutes`` / ``nearest_name`` **不动**：由 IDW 耗时场回填，与点数无关。

    就地更新并入参 `stats`（调用方已持有该 list），返回同一对象便于链式使用。
    """
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for p in points:
        by_cat.setdefault(str(p.get("category")), []).append(p)
    for s in stats:
        cat = str(s.get("category"))
        pts = by_cat.get(cat, [])
        n = len(pts)
        s["in_circle"] = n
        ideal = (CATEGORY_DEFS.get(cat) or {}).get("ideal_circle") or 1
        # 与 `to_stats` **同调同一颗** `coverage_from_points`（计划 §三 第 2 条）：这条链会就地
        # 覆盖 `to_stats` 的结果，两处若各写一遍算式，改一处就等于没改（第十七/十八轮的 P0-1）。
        # `required_in_circle` 也必须在这里一起覆盖 —— 只更 `coverage` 会让"分子到底是几"
        # 这条链停在 `to_stats` 的旧点集上，与截断/在圈过滤后的 `in_circle` 分叉。
        s["coverage"] = round(coverage_from_points(pts, ideal, cat), 4)
        s["required_in_circle"] = required_count_from_points(pts, cat)
        # 名单与分子同批覆盖（理由同上：这条链会就地盖掉 `to_stats` 的结果，只更一个数
        # 就会让"名字"停在截断前那份上）。名单不吃点位 ⇒ 与 `pts` 是否带 `sub_kind` 无关。
        labels = sub_kind_rule_labels(cat)
        s["scored_as"] = labels[0] if labels else None
        s["unscored_as"] = labels[1] if labels else None
    return stats


def check_poi_conservation(poi: Dict[str, Any]) -> Optional[str]:
    """点数守恒判据：``sum(categories[].in_circle) == len(points)``。合规返回 ``None``。

    **唯一实现**（阶段 1.4 / 阶段 3 的契约测试与 `lc_healthcheck` D 段都走它），
    避免「判据在生产侧和测试侧各写一份」——`sum(in_circle)` 此前只出现在
    `assemble.py` 与体检脚本里，测试侧 0 处，100+ 条生活圈测试全部绕开了真正会坏的不变量。

    违规时返回**可读**的差异描述（含逐类差额）：只说「不相等」不够，
    必须让「哪个类被砍掉了多少」一眼可见，否则排查又回到数点位上。
    """
    cats = poi.get("categories") or []
    pts = poi.get("points") or []
    declared = sum(int(c.get("in_circle") or 0) for c in cats)
    actual = len(pts)
    if declared == actual:
        return None
    by_cat: Dict[str, int] = {}
    for p in pts:
        key = str(p.get("category"))
        by_cat[key] = by_cat.get(key, 0) + 1
    diff = [
        f"{c.get('category')}: 声明 {int(c.get('in_circle') or 0)} / 实到 {by_cat.get(str(c.get('category')), 0)}"
        for c in cats
        if int(c.get("in_circle") or 0) != by_cat.get(str(c.get("category")), 0)
    ]
    detail = "；".join(diff) if diff else "逐类求和自洽但总数不符（类别键不匹配？）"
    return (
        f"汇总 {declared} ≠ 点位数 {actual}（差 {actual - declared}）；"
        f"逐类不一致：{detail}"
    )


def _point_confidence(it: Dict[str, Any]) -> float:
    """点位置信度：偏好采集方显式写入的 ``_confidence``，缺省用判表 `evaluate_category` 派生。

    返回 0..1 数值作为排序键；异常值收敛到 0.5 中性档，保证排序稳定不抛。
    """
    raw = it.get("_confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    try:
        _cat, conf = evaluate_category(it)
        return float(conf)
    except Exception:  # noqa: BLE001  判表异常不应让展示层崩溃
        return 0.5


def nearest_for(point: Tuple[float, float], points: Sequence[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    """点到点集最近距离（米），无点返回 None。"""
    best_d = None
    best_p = None
    for p in points:
        d = haversine_m(point, p)
        if best_d is None or d < best_d:
            best_d = d
            best_p = p
    if best_d is None:
        return None
    return {"distance_m": best_d, "point": best_p}