"""POI 采集 + 扩词策略（rev3 §四B）—— 预算感知 S1-S8 单条管线。

职责边界（架构分治，rev3 §二）：
  - **策略层**：怎么花预算、怎么扩词（plan_initial / ExpansionCtx / collect_poi）。
  - **不含预算定义**：只消费 `quota` 产出的**分配快照**（`POIBudget` 从 `quota.quota_budget()`
    实例化，不定义 total/poi 公式）。
  - **不含 HTTP**：真实调用委托 `client.place_search`（外部注入，可经 MockTransport/stub 替换）。
  - 排序统一收敛到 `poi.to_points`（rev3 P1-2）：本模块**不设独立 rerank**。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES
from app.living_circle.quota import quota_budget

logger = logging.getLogger(__name__)

# 渐进式停止阈值：扩词边际收益（圈内新增数）低于此值即 `quench`（rev3 §2.8）。
GAIN_STOP_THRESHOLD = 1

# 扩词请求只取第 1 页（就近召回已足够触发达标或再扩，rev3 §2.8）。
_EXPANSION_PAGES = 1

# 每类点位截断上限（渲染/报告体积，与 to_points 默认一致）。
_CAP_PER_CAT = 25


@dataclass
class POIBudget:
    """quota 产出的**分配快照**（不含预算定义，rev3 P1-1/P1-3）。

    - remaining：剩余可调用次数；`consume(cat)` 预扣后返回是否获批。
    - `refund(cat)`：调用**失败**回滚预扣（防扩词/翻页空转烧预算）。
    - `quench(cat)`：该类别因边际收益跌破阈值而冻结（不再为该类扩词）。
    - `fork()`：返回独立子快照（如需并发分账），子快照消费不影响父。
    """

    total: int
    remaining: int = field(init=False)
    usage: Dict[str, int] = field(default_factory=dict)
    frozen_cats: set = field(default_factory=set)

    def __post_init__(self) -> None:
        self.remaining = self.total

    def consume(self, category: str, units: int = 1) -> bool:
        """预扣 `units` 次调用额度；额度不足或类别已冻结则拒绝（原子，不部分扣减）。

        按页/翻页分账时 `units` 可为 >1，保证预算与真实 HTTP 调用在数量上对齐。
        """
        if units < 1:
            return False
        if self.remaining < units or category in self.frozen_cats:
            return False
        self.remaining -= units
        self.usage[category] = self.usage.get(category, 0) + units
        return True

    def refund(self, category: str, units: int = 1) -> None:
        """调用失败回滚预扣（`units` 与 `consume` 对齐）；不把类别计为已消耗。"""
        back = max(0, units)
        self.remaining = min(self.total, self.remaining + back)
        used = self.usage.get(category, 0)
        if used:
            self.usage[category] = max(0, used - back)

    def quench(self, category: str) -> None:
        self.frozen_cats.add(category)

    def frozen(self, category: str) -> bool:
        return category in self.frozen_cats

    def under_target(self, cats: Dict[str, int], ideal_circle: int) -> bool:
        """该类别是否仍低于理想阈值（应扩词）？

        入参：`cats` 为该类别当前圈内计数（键=类别，值=数量），`ideal_circle` 为阈值。
        返回 `cats` 中**任一类别**计数 < ideal → True（应扩词）；全部达标 → False。
        注：默认取 `cats` 首个条目判定；多类别粒度由 collect_poi 逐类循环显式判读。
        """
        for _cat, n in (cats or {}).items():
            return n < ideal_circle
        return True  # 无计数信息 → 视为未达标，保守触发扩词

    def fork(self) -> "POIBudget":
        child = POIBudget(total=self.total)
        child.remaining = self.remaining
        child.usage = dict(self.usage)
        child.frozen_cats = set(self.frozen_cats)
        return child


@dataclass
class ExpansionCtx:
    """S8 扩词上下文：三路来源线性取词（rev3 §2.8）+ 分型预留接口位。

    next() 按顺序尝试：confirmed name 提炼 → 未用 accept_tags → baidu type 边界补词；
    已用词（`used_terms`）一律跳过；无可用词返回 None。
    缺口分型（缺别名/缺近圈/缺可达性）本期不落地，仅预留 `plan_gap_types` 扩展点。
    """

    used_terms: set = field(default_factory=set)

    def next(
        self,
        confirmed: Sequence[Dict[str, Any]],
        rule: Dict[str, Any],
        existing: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Optional[str]:
        # 来源 1：confirmed name 提炼（取过 s8 的关键词名词）
        for poi in confirmed or []:
            name = (poi.get("name") or "").strip()
            if not name:
                continue
            # 从名称攻击性提炼「服务站/卫生站/药店」等类别判词：取 2-4 字尾名词片段
            term = _extract_term(name)
            if term and term not in self.used_terms:
                self.used_terms.add(term)
                return term
        # 来源 2：未用 accept_tags
        for tag in rule.get("accept_tags") or []:
            if tag and tag not in self.used_terms and tag not in (rule.get("keywords") or []):
                self.used_terms.add(tag)
                return tag
        # 来源 3：existing 里出现的 type/tag 边界补词（去重）
        for items in (existing or {}).values():
            for it in items or []:
                t = (it.get("type") or "").strip()
                if t and t not in self.used_terms:
                    self.used_terms.add(t)
                    return t
        return None

    # 预留分型接口位（rev3 §2.8 后瞻）：后续可在此按缺口类型生成目标词。
    # def plan_gap_types(self, gap: str) -> List[str]: ...


def _extract_term(name: str) -> Optional[str]:
    """从 POI 名称里提炼可复用的类别判词。

    启发式：先查已知的「社区机构」尾名词（取其中在 [2,6] 的最长匹配字符串）；
    无命中则整名过长时取末段。保守策略：仅当长度在 [2,6] 之间才作为扩词，
    避免把超长铺名塞进检索词。
    """
    s = name.strip()
    if not s:
        return None
    suffixes = (
        "社区卫生服务中心",
        "卫生服务站",
        "社区服务站",
        "社区医院",
        "日间照料中心",
        "农贸市场",
        "便民市场",
        "菜市场",
        "药店",
        "药房",
        "便利店",
        "图书馆",
        "派出所",
        "公园",
        "银行",
        "幼儿园",
    )
    best = ""
    for suffix in suffixes:
        if suffix in s and len(suffix) >= 3 and len(best) < len(suffix):
            best = suffix
    if best and 2 <= len(best) <= 6:
        return best
    return s if 2 <= len(s) <= 6 else None


def plan_initial(rule: Dict[str, Any], budget: POIBudget) -> List[Tuple[str, int]]:
    """S1 语义查询计划（rev3 §2.1/§2.3）：返回 [(term, pages)]。

    pages 由预算导出（页深受晕，预算充足自动回升）；词表用 `rule["keywords"]`。
    """
    from app.living_circle.quota import poi_page_depth

    keywords = rule.get("keywords") or []
    if not keywords:
        return []
    pages = poi_page_depth(len(keywords), budget.total)
    return [(kw, pages) for kw in keywords]


async def collect_poi(
    client: Any,
    center: Tuple[float, float],
    radius_m: float,
    scope: Any,
    budget_snapshot: Optional[POIBudget] = None,
    n_terms: Optional[int] = None,
) -> Tuple[Dict[str, list], Dict[str, list]]:
    """预算感知 S1-S8 采集管线（rev3 §三）—— 返回 (per_category, triads)。

    阶段：
      A. 初始语义检索（S1 语义词 + S3 预算导出页深，占预算主体）；
      B. S8 自适应扩词（仅 under-target 类别，吃剩余预算，渐进式停止）；
      C. 扩词后合并去重（不排序——排序由 to_points 单一实现承担）。

    `scope` 透传给 under-target 判定；`n_terms` 缺省按类别判表词数全集估算页深。
    """
    budget = budget_snapshot or POIBudget(total=_poi_budget(n_terms))
    per_category: Dict[str, list] = {}
    ctx = ExpansionCtx(used_terms=set())

    # ── A 阶段：S1 + S2 + S3 初始检索（budget-derived 页深驱动）──
    all_keywords: List[str] = []
    for cat, defn in CATEGORY_RULES.items():
        all_keywords.extend(defn["keywords"])
    plan = plan_initial({"keywords": all_keywords}, budget)  # [(term, pages)]
    pages_of = {term: pages for term, pages in plan}
    for cat, defn in CATEGORY_RULES.items():
        items: list = []
        for kw in defn["keywords"]:
            if kw not in ctx.used_terms:
                ctx.used_terms.add(kw)
            pages = pages_of.get(kw, 1)
            if not budget.consume(cat, units=pages):
                break
            raw = await client.place_search(kw, center, radius_m=radius_m, max_pages=pages)
            if raw is None:
                budget.refund(cat, units=pages)
                break
            items += raw
        per_category[cat] = _dedupe(items)

    # ── 三要素（盲区硬判）：market 复用类目；pharmacy/primary 另检索 ──
    triads: Dict[str, list] = {"market": per_category.get("market", [])}  # 复用类目，省 1 次调用
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_") or key == "market":
            continue
        defn = ref if isinstance(ref, dict) else {"keywords": [ref]}
        kw = (defn.get("keywords") or [""])[0]
        if kw and budget.consume(f"triad-{key}"):
            raw = await client.place_search(kw, center, radius_m=radius_m, max_pages=1)
            if raw is not None:
                triads[key] = _dedupe(raw)
            else:
                budget.refund(f"triad-{key}")

    # ── B 阶段：S8 渐进式扩词（仅 under-target，吃剩余预算）──
    ideal = {cat: defn["ideal_circle"] for cat, defn in CATEGORY_RULES.items()}
    for cat, defn in CATEGORY_RULES.items():
        hits = _in_circle_count(per_category.get(cat, []), scope)
        if hits >= ideal.get(cat, 1):
            continue
        while budget.remaining > 0 and not budget.frozen(cat):
            term = ctx.next(confirmed=per_category.get(cat, []), rule=defn, existing={cat: per_category.get(cat, [])})
            if term is None:
                break
            if not budget.consume(cat):
                break
            raw = await client.place_search(term, center, radius_m=radius_m)
            if raw is None:
                budget.refund(cat)
                break
            before = _in_circle_count(per_category.get(cat, []), scope)
            per_category[cat] = _dedupe(per_category.get(cat, []) + raw)
            after = _in_circle_count(per_category.get(cat, []), scope)
            if after - before < GAIN_STOP_THRESHOLD:
                budget.quench(cat)  # 边际跌破阈值 → 冻结该类别
            elif after >= ideal.get(cat, 1):
                break  # 达标停止

    # ── C 阶段：合并去重（sort 统一交给 to_points，本模块不排）──
    return merge_all(per_category), triads


def merge_all(per_category: Dict[str, list], cap: int = _CAP_PER_CAT) -> Dict[str, list]:
    """扩词后的合并出口：逐类聚簇去重 + 单类截断（不排序）。

    排序由 `poi.to_points` 单一实现承担，本函数仅保证数量收敛；
    C 阶段与外部合并方共用此入口，避免去重/截断逻辑散落。
    """
    out: Dict[str, list] = {}
    for cat, items in (per_category or {}).items():
        out[cat] = _dedupe(items)[:cap]
    return out


def _poi_budget(n_terms: Optional[int]) -> int:
    """实例化 POIBudget 用的 poi 预算（从 quota 快照取，非本模块定义预算公式）。"""
    _mat, poi = quota_budget()
    return poi


def _dedupe(items: List[Dict[str, Any]], radius_m: float = 50.0) -> List[Dict[str, Any]]:
    """坐标聚簇去重（复用 poi.clean 的 50m 语义；保留先到者优先）。"""
    kept: List[Dict[str, Any]] = []
    for it in items:
        if not it or it.get("lat") is None or it.get("lng") is None:
            continue
        dup = False
        for k in kept:
            if _dist_m(it, k) < radius_m:
                dup = True
                break
        if not dup:
            kept.append(it)
    return kept


def _dist_m(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    from app.living_circle.geo_utils import haversine_m

    return haversine_m((a["lng"], a["lat"]), (b["lng"], b["lat"]))


def _in_circle_count(items: List[Dict[str, Any]], scope: Any) -> int:
    """圈内（可达区）设施数：复用 scope 的点在环判定；scope 为空时按原始条数保守近似。"""
    if not items:
        return 0
    ring = getattr(scope, "reach_ring", None)
    if ring is None or not list(ring):
        return len(items)
    from app.living_circle.geo_utils import point_in_ring  # 与 poi.to_points 同一判定

    return sum(1 for it in items if point_in_ring((it["lng"], it["lat"]), ring))