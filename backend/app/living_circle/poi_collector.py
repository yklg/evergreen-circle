"""POI 采集 + 扩词策略（rev3 §四B）—— 预算感知 S1-S8 单条管线。

职责边界（架构分治，rev3 §二）：
  - **策略层**：怎么花预算、怎么扩词（plan_initial / ExpansionCtx / collect_poi）。
  - **不含预算定义**：只消费 `quota` 产出的**分配快照**（`POIBudget` 从 `quota.quota_budget()`
    实例化，不定义 total/poi 公式）。
  - **不含 HTTP**：真实调用委托 `client.place_search`（外部注入，可经 MockTransport/stub 替换）。
  - 排序统一收敛到 `poi.to_points`（rev3 P1-2）：本模块**不设独立 rerank**。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.living_circle.baidu_client import (
    STOP_API_ERROR,
    STOP_COMPLETE,
    STOP_DUP_STOP,
    STOP_EMPTY,
    STOP_NOT_RUN,
    STOP_PAGE_CAP,
)
from app.living_circle.caliber import facility_merge_enabled
from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES
from app.living_circle.quota import quota_budget
from app.living_circle.scope import TRIAD_KEYS

logger = logging.getLogger(__name__)

# 渐进式停止阈值：扩词边际收益（圈内新增数）低于此值即 `quench`（rev3 §2.8）。
GAIN_STOP_THRESHOLD = 1

# 扩词请求只取第 1 页（就近召回已足够触发达标或再扩，rev3 §2.8）。
_EXPANSION_PAGES = 1

# ⚠️ 阶段 1.5：本模块**不再持有任何截断常量**（原 `_CAP_PER_CAT = 25` 已删除）。
# 理由（两条口径不可混）：采集侧截断会把 `poi.total`（**采集口径**，含圈外）一并压小，
# 让「展示上限」篡改「采集事实」。唯一截断点收敛到 `poi.to_points`（展示层），
# 由它产出 `truncated` 披露；上限值 = `poi.POI_CAP_PER_CAT`。


@dataclass(frozen=True)
class TermEvidence:
    """一个检索词的**采集侧举证**：这次到底把多大的范围查干净了。

    存在理由（P0-1）：判盲要回答的是「某点 1km 内**没有**药店」这种全称否定，
    其前提是那一圈的药店**查全了**。而 `place_search` 返回条数**不足以**判别是否查全
    （探针实测 `len_alone_decisive=false`：`len == page_size` 时「恰好 20 家」与
    「被截断在 20 家」同值）⇒ 完整性必须由 `stop_reason` 承载并留进报告，
    否则下游只能拿几何半径猜，猜错就是把「没查到」洗成「没有」。
    """

    category: str
    term: str
    requested_radius_m: float
    pages_fetched: int
    returned: int
    total: Optional[int]
    stop_reason: str
    farthest_m: Optional[float]

    @property
    def complete(self) -> bool:
        """半径内是否已查全（`api_error` / `not_run` 落 False：一无所知 ≠ 没有）。"""
        return self.stop_reason in (STOP_COMPLETE, STOP_EMPTY)

    @property
    def frontier_m(self) -> float:
        """证据边界：查全 ⇒ 请求半径；被截断 ⇒ 只到最远实测点。"""
        if self.complete:
            return float(self.requested_radius_m)
        return float(self.farthest_m or 0.0)

    def as_row(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "term": self.term,
            "requested_radius_m": round(float(self.requested_radius_m), 1),
            "pages_fetched": self.pages_fetched,
            "returned": self.returned,
            "total": self.total,
            "stop_reason": self.stop_reason,
            "farthest_m": self.farthest_m,
            "frontier_m": round(self.frontier_m, 1),
        }


@dataclass(frozen=True)
class CollectionEvidence:
    """一次采集的**整体**证据账目（`SpatialScope` 的「事后举证」相的数据来源）。"""

    requested_radius_m: float
    per_term: Tuple[TermEvidence, ...] = ()
    starved_terms: Tuple[Tuple[str, str], ...] = ()   # (category, term)：预算拒绝 ⇒ 0 次调用
    aborted: bool = False                             # 熔断 / 日预算耗尽

    def frontier_m(self, category: str) -> float:
        """类别的证据边界 = 其各词边界的**最小值**（保守合取）。

        一个类别由多个关键词并集召回 ⇒ 只要有一个词被截断，该类别的已知边界就只到
        那个词的最远实测点。取 max 会把「没查全」说成「查全了」，正是误报盲区的入口。
        """
        rows = [t for t in self.per_term if t.category == category]
        if not rows:
            return 0.0
        return min(t.frontier_m for t in rows)

    def triad_frontier_m(self, keys: Sequence[str]) -> Dict[str, float]:
        return {k: self.frontier_m(k) for k in keys}

    @property
    def truncated_terms(self) -> Tuple[str, ...]:
        """发了请求但**没查全**的词（被单页上限截断 / 收益止损提前收页）。

        与 `starved_terms`（一次都没发）刻意分名：两者是不同的缺陷，合成一个词
        「截断」就会被稀释成噪声 —— 与 `poi.truncated`（展示上限）不复用同词同理。
        """
        return tuple(f"{t.category}:{t.term}" for t in self.per_term if not t.complete)

    @property
    def complete(self) -> bool:
        """无词被截断、无词被饿死、未熔断 —— 三者齐备才敢声称证据面完整。"""
        return (
            not self.aborted
            and not self.starved_terms
            and bool(self.per_term)
            and all(t.complete for t in self.per_term)
        )

    def as_detail(self) -> Dict[str, Any]:
        """报告 `caliber` 用的摘要（逐条明细同于此，量小且正是举证要的东西）。"""
        return {
            "requested_radius_m": round(float(self.requested_radius_m), 1),
            "terms": [t.as_row() for t in self.per_term],
            "starved_terms": [f"{c}:{t}" for c, t in self.starved_terms],
            "aborted": self.aborted,
        }


class PoiCollection(NamedTuple):
    """`collect_poi` / `load_poi` 的返回：点位 + 三要素 + **证据账目** + **归并账目**。

    用 NamedTuple 而非把 evidence 塞进某个 dict：与 `poi.PoiPointsOut` 同构 ——
    举证必须**无法被顺手丢掉**。

    `merged` 带默认值 ⇒ 既有的**三参构造**（`PoiCollection(per, tri, ev)`，测试与 stub 都这么造）
    仍然合法，第四个字段只在需要归并披露时按属性取。⚠️ 保证的是构造点兼容，**不是**位置解包
    兼容：NamedTuple 解包必须满员，`per_category, triads, evidence = collect_poi(...)` 在四字段
    上是 `ValueError`。真实调用点一律按属性取（`data_source.py:203/504`、
    `pipeline/living_circle.py:368`），所以今天不伤任何路径；写清是因为这句话会误导下一个加
    字段的人，让他以为「带默认值 = 老解包还能跑」。它逐类记 `{"category", "absorbed"}`，**只含真的发生
    归并的类别**（无归并即 `()`）—— 与 `poi.truncated` 同一套「不得静默」纪律：
    归并是"少输出"型操作，守恒不变量对它完全免疫，不留痕就永远查不出来。
    """

    per_category: Dict[str, list]
    triads: Dict[str, list]
    evidence: CollectionEvidence
    merged: tuple = ()


def _farthest_m(center: Tuple[float, float], items: Sequence[Dict[str, Any]]) -> Optional[float]:
    """本批返回点里离中心最远者的距离（= 被截断时的真实证据边界）。"""
    from app.living_circle.geo_utils import haversine_m

    best: Optional[float] = None
    for it in items or []:
        try:
            d = haversine_m(center, (float(it["lng"]), float(it["lat"])))
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or d > best:
            best = d
    return None if best is None else round(best, 1)


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


def _term_radius(scope: Any, category: str, fallback_m: float) -> float:
    """该类别本次要查到哪儿 —— 由 `scope.required_radius_m` 唯一决定（D-1 的落点）。

    scope 缺省（离线脚本 / 未绑定口径的旧调用）时退回传入的 `fallback_m`，
    但**不猜**：调用方必须显式给一个半径，因为半径就是证据边界。
    """
    fn = getattr(scope, "required_radius_m", None)
    if callable(fn):
        return float(fn(category))
    return float(fallback_m)


async def collect_poi(
    client: Any,
    center: Tuple[float, float],
    radius_m: float,
    scope: Any,
    budget_snapshot: Optional[POIBudget] = None,
    n_terms: Optional[int] = None,
) -> PoiCollection:
    """预算感知 S1-S8 采集管线（rev3 §三）—— 返回 :class:`PoiCollection`。

    阶段：
      A. 初始语义检索（S1 语义词 + S3 预算导出页深，占预算主体）；
      B. S8 自适应扩词（仅 under-target 类别，吃剩余预算，渐进式停止）；
      C. 扩词后合并去重（不排序——排序由 to_points 单一实现承担）。

    `scope` 透传给 under-target 判定**与逐类检索半径**（`required_radius_m`）；
    `n_terms` 缺省按类别判表词数全集估算页深。

    **证据账目**：每个词的 `stop_reason` / 实测边界 / 是否被预算饿死都落进
    `CollectionEvidence`，由装配层绑进 `SpatialScope` 的「事后举证」相 ——
    判盲的可判定半径从此由**实测边界**决定，而不是由请求半径猜。
    """
    budget = budget_snapshot or POIBudget(total=_poi_budget(n_terms))
    per_category: Dict[str, list] = {}
    ctx = ExpansionCtx(used_terms=set())
    evidence: List[TermEvidence] = []
    starved: List[Tuple[str, str]] = []

    def _record(category: str, term: str, req_radius: float, out: Any) -> List[Dict[str, Any]]:
        """把一次 `place_search` 的结果转成 (点位, 举证)。`out` 为 None 视为调用失败。

        拿不到 `stop_reason`（非 :class:`PlaceSearchOut` 的鸭子类型返回）时按
        **截断**处理而非按查全处理 —— 保守方向唯一正确：判「没有」需要穷尽性证据，
        而一条来路不明的返回恰恰给不出它。当成查全会把「没查到」洗成「没有」。
        """
        if out is None:      # 旧 stub / 客户端返回 None ⇒ 一无所知，不得当作「没有」
            return []
        items = list(getattr(out, "items", out) or [])
        evidence.append(TermEvidence(
            category=category,
            term=term,
            requested_radius_m=req_radius,
            pages_fetched=int(getattr(out, "pages_fetched", 1) or 0),
            returned=len(items),
            total=getattr(out, "total", None),
            stop_reason=str(getattr(out, "stop_reason", STOP_PAGE_CAP) or STOP_PAGE_CAP),
            farthest_m=_farthest_m(center, items),
        ))
        return items

    # ── A 阶段：S1 + S2 + S3 初始检索（budget-derived 页深驱动）──
    all_keywords: List[str] = []
    for cat, defn in CATEGORY_RULES.items():
        all_keywords.extend(defn["keywords"])
    plan = plan_initial({"keywords": all_keywords}, budget)  # [(term, pages)]
    pages_of = {term: pages for term, pages in plan}

    async def _initial_search(cat: str, kw: str, pages: int) -> Tuple[Any, str]:
        # 与串行同语义：词先登记已用（set.add 幂等），再原子预扣；拒绝即跳过（不发起调用）
        ctx.used_terms.add(kw)
        if not budget.consume(cat, units=pages):
            return None, "starved"          # ← 0 次调用，**必须可见**（P0-2）
        raw = await client.place_search(kw, center, radius_m=_term_radius(scope, cat, radius_m),
                                        max_pages=pages)
        if raw is None:
            budget.refund(cat, units=pages)
            return None, "failed"
        return raw, "ok"

    a_plan: List[Tuple[str, str, int]] = [
        (cat, kw, pages_of.get(kw, 1))
        for cat, defn in CATEGORY_RULES.items()
        for kw in defn["keywords"]
    ]
    # B2 并发（延迟优化）：A 阶段词间无依赖，asyncio.gather 并发发出；预算准入仍是
    # 先到先得（consume 为同步原子操作，事件循环内按任务序确定）→ 准入集合与串行一致
    # （U38 锚定）。三要素检索保持在其后串行 —— 预算顺序与现行为完全一致，防准入漂移。
    results = await asyncio.gather(*(_initial_search(cat, kw, pages) for cat, kw, pages in a_plan))
    raw_by_cat: Dict[str, list] = {}
    for (cat, kw, _pages), (raw, status) in zip(a_plan, results):
        if status == "starved":
            starved.append((cat, kw))
            continue
        if raw is None:
            continue
        items = _record(cat, kw, _term_radius(scope, cat, radius_m), raw)
        if items:
            raw_by_cat.setdefault(cat, []).extend(items)
    # 类目通道是否启用设施实体归并，由只读开关一次性决定（见 `facility_merge_enabled`）。
    facility_policy = "facility" if facility_merge_enabled() else "geometric"
    # 按**被吸收记录的身份**去重记账：采集跑 A/B/C 三轮，S8 扩词会把同一个 ATM 再抓回来
    # 再合一次，按次数记会把同一个设施数两遍，`poi.merged.absorbed` 就成了无从核对的大数。
    absorbed_by_cat: Dict[str, set] = {}

    def _credit(cat: str, absorbed_items: List[Dict[str, Any]]) -> None:
        from app.living_circle.poi import absorbed_key

        if not absorbed_items:
            return
        bucket = absorbed_by_cat.setdefault(cat, set())
        bucket.update(absorbed_key(it) for it in absorbed_items)

    def _dedupe_cat(cat: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """类目去重 + **就地记账**。

        账目只数「因设施归并而少掉的设施」：`len(in) - len(out)` 会把同名重复
        （`is_duplicate` 本来就在合的）也算进来，那样报的就不是本次口径变更的量。
        """
        from app.living_circle.poi import dedupe_facility

        if facility_policy != "facility":
            return _dedupe(items, 50.0, facility_policy, center)
        kept, absorbed = dedupe_facility(items, 50.0, center)
        _credit(cat, absorbed)
        return kept

    per_category = {cat: _dedupe_cat(cat, raw_by_cat.get(cat, []) or []) for cat in CATEGORY_RULES}

    # ── 三要素（盲区硬判）：market 复用类目；pharmacy/primary 另检索 ──
    # market 的证据边界由上面 3 个 market 词共同决定（`frontier_m` 取最小值）。
    # ⚠️ 三要素一律走 `geometric`，且 market 的输入**必须是采集期的 `raw_by_cat["market"]`**：
    #    `per_category["market"]` 已被 facility 归并过一轮，被吸收的点**已经不存在**，
    #    对它重跑 geometric 什么都还原不出来（评审第 2 轮 P0-2）。
    #    代价：报告里会有两个菜市场数字（类目统计口径 vs 盲区判定口径），须在 caliber 举证里写明。
    triads: Dict[str, list] = {
        "market": _dedupe(raw_by_cat.get("market", []) or [], 50.0, "geometric")
    }
    for key, ref in TRIAD_RULES.items():
        if key.startswith("_") or key == "market":
            continue
        defn = ref if isinstance(ref, dict) else {"keywords": [ref]}
        kw = (defn.get("keywords") or [""])[0]
        triad_r = _term_radius(scope, key, radius_m)
        if not kw:
            continue
        if not budget.consume(f"triad-{key}"):
            starved.append((key, kw))
            continue
        raw = await client.place_search(kw, center, radius_m=triad_r, max_pages=1)
        if raw is None:
            budget.refund(f"triad-{key}")
            continue
        items = _record(key, kw, triad_r, raw)
        if items:
            # 显式写死 geometric：三要素是盲区 1km 硬判的输入，绝不跟随类目通道的归并策略。
            triads[key] = _dedupe(items, 50.0, "geometric")

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
            # R4：扩词必须显式传页深。旧代码漏传 ⇒ 走 `max_pages=3` 默认，
            # 于是**扣 1 个预算单位却最多发 3 次 HTTP**，与 POIBudget.consume 的记账语义矛盾。
            raw = await client.place_search(term, center, radius_m=_term_radius(scope, cat, radius_m),
                                            max_pages=_EXPANSION_PAGES)
            if raw is None:
                budget.refund(cat)
                break
            new_items = _record(cat, term, _term_radius(scope, cat, radius_m), raw)
            before = _in_circle_count(per_category.get(cat, []), scope)
            merged = _dedupe_cat(cat, per_category.get(cat, []) + new_items)
            per_category[cat] = merged
            after = _in_circle_count(merged, scope)
            # R3：冻结只认「这个词一点新东西都没带来」，不认「带来的全在可达区外」。
            # 旧判据只看圈内增益 ⇒ 采集半径一旦大于可达区，一整页圈外有效点会被算成
            # 「零增益」并 `quench` **永久冻结**该类别 —— 把「多查到了」当成「没查到」。
            if not new_items:
                budget.quench(cat)
            elif after - before < GAIN_STOP_THRESHOLD:
                pass  # 圈内未达标但确有新增 ⇒ 继续换词，边际另由 ctx.next 收敛
            elif after >= ideal.get(cat, 1):
                break  # 达标停止

    # ── C 阶段：合并去重（sort 统一交给 to_points，本模块不排）──
    merged_cat = merge_all(per_category, 50.0, facility_policy, center, on_absorb=_credit)
    ev = CollectionEvidence(
        requested_radius_m=float(radius_m),
        per_term=tuple(evidence),
        starved_terms=tuple(starved),
        aborted=budget.remaining <= 0 and bool(starved),
    )
    merged_out = tuple(
        {"category": cat, "absorbed": len(ids)}
        for cat, ids in sorted(absorbed_by_cat.items())
        if ids
    )
    return PoiCollection(merged_cat, triads, ev, merged_out)


def merge_all(
    per_category: Dict[str, list],
    radius_m: float = 50.0,
    policy: str = "geometric",
    center: Optional[Tuple[float, float]] = None,
    on_absorb: Optional[Any] = None,
) -> Dict[str, list]:
    """扩词后的合并出口：逐类聚簇去重（**不排序、不截断**）。

    - 排序由 `poi.to_points` 单一实现承担；
    - **截断只在 `poi.to_points` 一处发生**（阶段 1.5）。采集侧若也截一次，
      `poi.total`（采集口径）会被「展示上限」压小 —— 两个口径混成一个，
      正是本计划要消灭的缺陷形态（旧实现此处静默砍到 25，报告里毫无痕迹）。
    - 复杂度不受影响：去重本来就在**全量**原始列表上做（`_dedupe(raw_by_cat[cat])`），
      这里的 cap 从未减少过计算量，只减少了写进报告的量。
    - `policy` / `center` 与 A/B 阶段保持一致，避免最后一道出口换了一套判据。
    - `on_absorb(category, absorbed_items)`：`policy="facility"` 时回调交出**因设施归并**
      被吸收的记录（不含 `is_duplicate` 本来就会合掉的同名重复），供 `poi.merged` 记账。
    """
    from app.living_circle.poi import dedupe_facility

    out: Dict[str, list] = {}
    for cat, items in (per_category or {}).items():
        items = items or []
        if policy == "facility" and center is not None:
            kept, absorbed = dedupe_facility(items, radius_m, center)
            if absorbed and on_absorb is not None:
                on_absorb(cat, absorbed)
        else:
            kept = _dedupe(items, radius_m, "geometric")
        out[cat] = kept
    return out


def _poi_budget(n_terms: Optional[int]) -> int:
    """实例化 POIBudget 用的 poi 预算（从 quota 快照取，非本模块定义预算公式）。"""
    _mat, poi = quota_budget()
    return poi


def _dedupe(
    items: List[Dict[str, Any]],
    radius_m: float = 50.0,
    policy: str = "geometric",
    center: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """聚簇去重（v5 D3）：判据**唯一实现**在 `poi.dedupe_pois` / `poi.dedupe_facility`，
    本模块不再维护 50m 双份漂移实现，只做薄委托。

    `policy` 必须由**调用点显式选定**，两条通道语义不同且不可互换：
      - 类目通道 → `"facility"`：同一实体设施（银行与其 24 小时自助）只出一个点。
      - 三要素通道（菜市场/药店/小学）→ `"geometric"`：盲区是「1km 内有没有」的硬判，
        宁多勿少，绝不因归而少一个坐标。**这条分道不是优化项而是隔离墙。**
    """
    from app.living_circle.poi import dedupe_pois

    return dedupe_pois(items, radius_m, policy, center)


def _in_circle_count(items: List[Dict[str, Any]], scope: Any) -> int:
    """圈内（可达区）设施数：复用 scope 的点在环判定；scope 为空时按原始条数保守近似。"""
    if not items:
        return 0
    ring = getattr(scope, "reach_ring", None)
    if ring is None or not list(ring):
        return len(items)
    from app.living_circle.geo_utils import point_in_ring  # 与 poi.to_points 同一判定

    return sum(1 for it in items if point_in_ring((it["lng"], it["lat"]), ring))