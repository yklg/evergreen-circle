"""POI 采集 + 扩词策略（rev3 §四B）—— 预算感知 S1-S8 单条管线。

职责边界（架构分治，rev3 §二）：
  - **策略层**：怎么花预算、怎么扩词（plan_initial / ExpansionCtx / collect_poi）。
  - **不含预算定义**：只消费 `quota` 产出的**分配快照**（`POIBudget` 由调用方
    按 `quota.quota_budget(sample_profile, travel_mode)` 实例化后传入；本模块既不定义
    total/poi 公式，也不猜采样规格 —— 规格只住在调用方手里）。
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
    STOP_SERVER_CAP,
    is_exhausted,
    is_server_cap,
)
from app.living_circle.caliber import facility_merge_enabled
from app.living_circle.category_rule import CATEGORY_RULES, TRIAD_RULES
from app.living_circle.anchors import anchor_key
from app.living_circle.scope import TRIAD_KEYS, EvidenceDisc

# ⚠️ 上面这几个 `STOP_*` 里，`STOP_COMPLETE/EMPTY/DUP_STOP/NOT_RUN` 在本模块已**无代码引用**
# （完整性与封顶的判定收进了 `baidu_client.is_exhausted/is_server_cap`），留着是因为测试把它们
# 当采集层门面在用（`pc.STOP_EMPTY`）。测试文件自己的注释主张「按契约该从 baidu_client 取」——
# 那句话是对的，收口时把这几处测试的引用一并改指过去，然后删掉这里的再导出；不在本轮顺手改，
# 是为了不让「删无用 import」和「8 处测试改引用」混进同一个改动里。

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
        return is_exhausted(self.stop_reason)

    @property
    def cap_hit(self) -> bool:
        """被**接口自有上限**卡住（≠ 我们没翻）：第三态 `unjudgeable_by_cap` 的唯一原料。

        同样做成 `stop_reason` 的派生量，不留第二个可独立填写的字段。
        """
        return is_server_cap(self.stop_reason)

    @property
    def frontier_m(self) -> float:
        """证据边界：查全 ⇒ 请求半径；被截断 ⇒ 只到最远实测点。"""
        if self.complete:
            return float(self.requested_radius_m)
        return float(self.farthest_m or 0.0)

    def as_disc(self, anchor: Tuple[float, float]) -> "EvidenceDisc":
        """把这一行的事实变成**证据圆盘**（T-P0-4：全项目唯一转换器）。

        为什么必须是唯一一处：转换里有三个容易各抄各的判断 —— 穷尽深度取 `frontier_m`
        （不是 farthest、也不是 requested）、锚点由调用方给（一行本身不带坐标）、
        完整性/封顶由 `stop_reason` 派生。第 0 步脚本原本自带一份等价构造，那份就是
        这里要收掉的第二实现。
        """
        return EvidenceDisc(
            category=self.category,
            anchor=(float(anchor[0]), float(anchor[1])),
            request_radius_m=float(self.requested_radius_m),
            exhausted_radius_m=float(self.frontier_m),
            stop_reason=self.stop_reason,
        )

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
            "cap_hit": self.cap_hit,
        }


@dataclass(frozen=True)
class CollectionEvidence:
    """一次采集的**整体**证据账目（`SpatialScope` 的「事后举证」相的数据来源）。"""

    requested_radius_m: float
    per_term: Tuple[TermEvidence, ...] = ()
    starved_terms: Tuple[Tuple[str, str], ...] = ()   # (category, term)：预算拒绝 ⇒ 0 次调用
    aborted: bool = False                             # 熔断 / 日预算耗尽
    # 逐锚点**证据盘**（计划 v5.8 回合函数的产物）。默认 `()` = 首轮采集的形状，此时判盲仍走
    # 标量视图（与今天逐字相同）；回合函数填它，调用方才能把「A ∪ 本轮」合成一个 region。
    # 盘只由 `TermEvidence.as_disc(anchor)` 这一个转换器产出 —— 这里不留第二个构造点，
    # 也不叫 `anchors`：锚点是「打哪儿」，盘是「证到哪儿」，后者才是判盲要吃的东西。
    discs: Tuple[EvidenceDisc, ...] = ()

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

    def stop_reason_by_category(self) -> Dict[str, str]:
        """逐类「为什么停」——取**决定该类边界的那一行**（frontier 最小者）的原因。

        与 `frontier_m` 同源同规则：边界由短板定，原因也该由同一块短板给。若各按各的规则
        （边界取 min、原因取第一个词），标量视图就会出现「边界是截断词给的、原因却报查全」。
        该类无任何行 ⇒ 不进表（无事实可报），由 `bound_source_by_category` 归成 `missing`。
        """
        binding: Dict[str, TermEvidence] = {}
        for t in self.per_term:
            cur = binding.get(t.category)
            if cur is None or t.frontier_m < cur.frontier_m:
                binding[t.category] = t
        return {cat: t.stop_reason for cat, t in binding.items()}

    def bound_source_by_category(self) -> Dict[str, str]:
        """逐类「边界这个数是从哪儿来的」—— T-P0-4 的映射表（计划 v5.6 三次复审版）。

        映射按**实际数据结构**写，不是按理想枚举写（复审 T-P0-4 那条就打在这里）：
        - 决定边界的那行 `stop_reason ∈ {complete, empty}` ⇒ `frontier`：数由实测证明；
        - 那行是 `page_cap`/`dup_stop`/`server_cap` ⇒ 也是 `frontier`，只是**不完整**
          （数确实是实测到的最远点，缺口由 `evidence_complete` 与 `capped` 分职披露）；
        - 那行是 `api_error` ⇒ `missing`：一行点位都没有，那个「边界」根本不该被当数用；
        - **该类无任何行** ⇒ `missing`：一次都没查成。注意 `starved` 的形态是「无行」而不是
          某一行写着 starved，所以不能靠读 `stop_reason` 找到它。
        `degenerate`（快照/离线反推）不归这里判 —— 那是「有没有 region」层面的事实，
        由 `SpatialScope.evidence_bound_source` 说，两个键不复用同词。
        """
        reasons = self.stop_reason_by_category()
        out: Dict[str, str] = {}
        for t in self.per_term:
            if t.category in out:
                continue
            reason = reasons.get(t.category)
            out[t.category] = "missing" if reason == STOP_API_ERROR else "frontier"
        return out

    @property
    def truncated_terms(self) -> Tuple[str, ...]:
        """发了请求但**没查全**的词（被单页上限截断 / 收益止损提前收页）。

        与 `starved_terms`（一次都没发）刻意分名：两者是不同的缺陷，合成一个词
        「截断」就会被稀释成噪声 —— 与 `poi.truncated`（展示上限）不复用同词同理。
        """
        return tuple(f"{t.category}:{t.term}" for t in self.per_term if not t.complete)

    @property
    def capped_terms(self) -> Tuple[str, ...]:
        """被**接口能力上限**卡住的词（`place_search` 回传 `cap_hit`）。

        取「任一词触顶即算该类触顶」：一个词查不全，整个类别的召回就永远差一截 ——
        这是全称结论（「这一圈没有」）的合取前提被破坏，与 `frontier_m` 取 min 同理。
        """
        return tuple(f"{t.category}:{t.term}" for t in self.per_term if t.cap_hit)

    @property
    def capped_categories(self) -> Tuple[str, ...]:
        seen: Dict[str, None] = {}
        for t in self.per_term:
            if t.cap_hit:
                seen.setdefault(t.category, None)
        return tuple(seen)

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
            "capped_terms": list(self.capped_terms),
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


def _items_of(out: Any) -> List[Dict[str, Any]]:
    """`place_search` 返回值里的点位（鸭子类型兼容旧 stub：非 `PlaceSearchOut` 时按列表读）。"""
    return list(getattr(out, "items", out) or [])


def _evidence_row(category: str, term: str, req_radius: float, out: Any,
                  center: Tuple[float, float]) -> TermEvidence:
    """一次**成功返回**的检索 → 举证行（唯一构造点，`collect_poi` 与取证回合共用）。

    拿不到 `stop_reason` 时按**截断**处理而不是按查全：判「没有」需要穷尽性证据，
    而一条来路不明的返回恰恰给不出它（当成查全会把「没查到」洗成「没有」）。
    """
    items = _items_of(out)
    return TermEvidence(
        category=category, term=term, requested_radius_m=float(req_radius),
        pages_fetched=int(getattr(out, "pages_fetched", 1) or 0), returned=len(items),
        total=getattr(out, "total", None),
        stop_reason=str(getattr(out, "stop_reason", STOP_PAGE_CAP) or STOP_PAGE_CAP),
        farthest_m=_farthest_m(center, items),
    )


def _api_error_row(category: str, term: str, req_radius: float) -> TermEvidence:
    """一次**没发出去/发出去没成**的检索 → `api_error` 举证行（唯一构造点）。

    这条的价值在**留痕**：`complete=False` 且无点位，在报告里它是「这一词我们没查成」，
    不是「这一圈没有设施」。三条检索通道（A 阶段、三要素、扩词）与取证回合都造这一行，
    所以它不许在第三处被重抄一遍 —— 抄一遍就会有一处漏掉「不退款」那半条语义。
    """
    return TermEvidence(
        category=category, term=term, requested_radius_m=float(req_radius),
        pages_fetched=0, returned=0, total=None,
        stop_reason=STOP_API_ERROR, farthest_m=None,
    )


@dataclass
class POIBudget:
    """quota 产出的**分配快照**（不含预算定义，rev3 P1-1/P1-3）。

    - remaining：剩余可调用次数；`consume(cat)` 预扣后返回是否获批。
    - `quench(cat)`：该类别因边际收益跌破阈值而冻结（不再为该类扩词）。
    - `fork()`：返回独立子快照（如需并发分账），子快照消费不影响父。
    - ⚠️ `refund(cat)` **自 v5.6 起无生产调用点**：三条检索通道（A 阶段、三要素、扩词）都
      已统一到「失败不退款 + 记 `api_error` 举证」（`_record_failure`）。理由：请求真发出去
      了额度就已花掉，退款会让「点位凭空消失」在账面上变成「钱没花」。它还留着只因为它自己的
      单测在测这个原语；**要不要连同那条用例一起删，属公类 API 取舍，留给评审定**，不在本轮顺手删。
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
    budget_snapshot: POIBudget,
) -> PoiCollection:
    """预算感知 S1-S8 采集管线（rev3 §三）—— 返回 :class:`PoiCollection`。

    阶段：
      A. 初始语义检索（S1 语义词 + S3 预算导出页深，占预算主体）；
      B. S8 自适应扩词（仅 under-target 类别，吃剩余预算，渐进式停止）；
      C. 扩词后合并去重（不排序——排序由 to_points 单一实现承担）。

    `scope` 透传给 under-target 判定**与逐类检索半径**（`required_radius_m`）。

    `budget_snapshot` **不留默认值**（D5 分区翻转后必须）：取证额度现在是
    「全局预算 − 矩阵按采样规格算出的需求调用」，规格只住在调用方手里。留一个
    「自己猜一份预算」的默认，等于让骑行/驾车档拿步行的 chunk 去算矩阵、再把差额全给
    取证 —— 两端相加越过 42 的精度预算，撞上 45 的熔断闸，把分区算错演成接口故障。

    **证据账目**：每个词的 `stop_reason` / 实测边界 / 是否被预算饿死都落进
    `CollectionEvidence`，由装配层绑进 `SpatialScope` 的「事后举证」相 ——
    判盲的可判定半径从此由**实测边界**决定，而不是由请求半径猜。
    """
    budget = budget_snapshot
    per_category: Dict[str, list] = {}
    ctx = ExpansionCtx(used_terms=set())
    evidence: List[TermEvidence] = []
    starved: List[Tuple[str, str]] = []

    def _record(category: str, term: str, req_radius: float, out: Any) -> List[Dict[str, Any]]:
        """把一次 `place_search` 的结果转成 (点位, 举证)。`out` 为 None 视为调用失败。

        举证行的构造只住在 `_evidence_row`（取证回合函数共用同一处），这里只留两件事：
        「None ⇒ 一无所知、不得当作『没有』」这层守卫，以及把点位交回调用方。
        """
        if out is None:      # 旧 stub / 客户端返回 None ⇒ 一无所知，不得当作「没有」
            return []
        items = _items_of(out)
        evidence.append(_evidence_row(category, term, req_radius, out, center))
        return items

    def _record_failure(category: str, term: str, req_radius: float) -> None:
        """一次**没发出去/发出去没成**的检索 → 记 `api_error` 举证，**不退款**。

        唯一实现：A 阶段（`_initial_search`）、三要素循环、扩词循环与取证回合都走这里
        （计划 v5.6 T-P0-3 / T-P0-3b）；行本身由 `_api_error_row` 造，第三处不再抄一遍。
        不退款是因为请求真发出去了、额度就已经花掉；退款会让「点位凭空消失」在账面上
        变成「钱没花」，缺口于是不可见 —— 而调用失败恰恰是最需要被看见的那类缺口。
        这条举证的意义在于**留痕**：`complete=False` 且无点位，报告里它是「这一词我们
        没查成」，不是「这一圈没有设施」；后续的 `bound_source` 派生（S-P0-2）正以此为原料。
        """
        evidence.append(_api_error_row(category, term, req_radius))

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
            # **不退款**（计划 v4 阶段 3）：见 `_record_failure` 的 docstring —— 该语义现在
            # 只住在那一处，三要素循环与 A 阶段共用同一个构造，不留第二套。
            _record_failure(cat, kw, _term_radius(scope, cat, radius_m))
            return None, "failed"
        return raw, "ok"

    # 准入顺序 = **按词序号转置**（阶段 3 的确定性修复）。旧顺序沿 `CATEGORY_RULES` 字典序
    # 逐类摊开 ⇒ 预算一紧就**整类蒸发**（北京实测：42 总额里 POI 只分到 27、25 词 ⇒ 页深 1、
    # 三要素只剩 2 单位、S8 扩词进不去，谁饿死完全取决于字典序）。转置后饿死落在
    # 「每类尾部若干词」—— 每类都还剩证据，缺失不再偏袒字典序靠后的那一类。
    # ⚠️ 必须 `sorted()`：dict 的插入序会随定义顺序改动而漂移，而「同输入必同准入集」
    # 是报告可复现的前提（u38b 钉稳定性、u38c 钉落点形状）。
    cats_sorted = sorted(CATEGORY_RULES)
    kw_by_cat = {c: list(CATEGORY_RULES[c]["keywords"]) for c in cats_sorted}
    deepest = max((len(kws) for kws in kw_by_cat.values()), default=0)
    a_plan: List[Tuple[str, str, int]] = []
    for idx in range(deepest):
        for cat in cats_sorted:
            kws = kw_by_cat[cat]
            if idx >= len(kws):
                continue          # 词数不齐：短的那类在这一层没有位置
            kw = kws[idx]
            a_plan.append((cat, kw, pages_of.get(kw, 1)))
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
        # 词表解析只住在 `triad_keywords`（第四轮复审 P1-5：这里原本自己抄了一份
        # `ref if isinstance(ref, dict) else {"keywords": [ref]}`，与回合函数那份是第二实现）
        kws = triad_keywords(key)
        kw = kws[0] if kws else ""
        triad_r = _term_radius(scope, key, radius_m)
        if not kw:
            continue
        if not budget.consume(f"triad-{key}"):
            starved.append((key, kw))
            continue
        raw = await client.place_search(kw, center, radius_m=triad_r, max_pages=1)
        if raw is None:
            # T-P0-3（计划 v5.6）：三要素**不再退款、也不再静默跳过**。旧写法是
            # `budget.refund(...) + continue` —— 于是「药店这一类我们根本没查成」在报告里
            # 什么都留不下：点位没有、预算账面像没花、连一行 TermEvidence 都没有，
            # 判盲时那一类的证据缺口无从归因（三要素是盲区 1km 硬判的输入，缺一个类
            # 就等于整份盲区结论少了依据）。现在与类目路径同语义：不退款 + 记 api_error 行。
            _record_failure(key, kw, triad_r)
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
                # T-P0-3b（计划 v5.6）：扩词失败与 A 阶段/三要素**同一语义** —— 不退款、留一行
                # `api_error`。旧写法 `budget.refund(cat) + break` 有两个洞：账面像没花，且这一类
                # 的扩词是"中途失败"还是"到量收手"在报告里完全同形，无从归因。
                # 仍然 `break`（本类不再继续扩词）：失败不代表该停的是**别的类**，那由外层循环各判。
                _record_failure(cat, term, _term_radius(scope, cat, radius_m))
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


def triad_keywords(category: str) -> Tuple[str, ...]:
    """该三要素类要用的**全部**关键词（唯一解析点，计划 v5.8）。

    `TRIAD_RULES["market"]` 是字符串 `"market"` —— 首轮里 market 直接复用类目通道那 3 个词
    的结果（「省 1 次调用」）。但那个技巧在**新锚点上不成立**：首轮那 3 个词是在分析中心查的，
    证不了另一个锚点周围 1km 内有没有。所以回合按全词表逐锚点重查，解析只放这一处，
    别处不再抄一遍 `TRIAD_RULES` 的形状（抄过一次的地方就是下一次漂移的地方）。
    """
    ref = TRIAD_RULES.get(category)
    if isinstance(ref, str):
        return tuple((CATEGORY_RULES.get(ref) or {}).get("keywords") or ())
    return tuple((ref or {}).get("keywords") or ())


@dataclass(frozen=True)
class ForensicRound:
    """一个取证回合的产物 —— **不持循环**（终止阶梯归外循环，计划阶段 5）。

    刻意同时带回 `evidence`（含逐锚点盘）与 `points`：证据域与点位集必须同批交付，
    调用方才拼得出「A ∪ 本轮」。只交证据会逼调用方去 `per_term` 里反推点位 —— 那是
    同一事实的第二份取法（`--dry` 实测就撞在这条上：只装本轮的写法把「本轮不扩」
    显示成了「什么都没查」）。
    """

    round_no: int
    evidence: CollectionEvidence
    points: Dict[str, Tuple[Dict[str, Any], ...]] = field(default_factory=dict)
    anchors_planned: Dict[str, int] = field(default_factory=dict)
    anchors_used: Dict[str, int] = field(default_factory=dict)
    # **实际发出过请求的锚点名单** —— 下一回合 `plan_expansion(already_tried=…)` 的唯一来源。
    # 第四轮复审 P1-4 打的就是这里：只有计数没有名单时，接线方只能拿「本轮规划到的锚点」去喂
    # 下一轮，而规划集里含被池子饿死的那些 ⇒ 没打的点被记成「已试」⇒ 扩容静默停止。
    # 口径按「至少发出过一次请求」计（含失败的请求）：重发同样花钱，而「这一带还没证」
    # 由 region 的未覆盖格数说，不靠重打同一批锚点说。
    anchors_attempted: Dict[str, Tuple[Tuple[float, float], ...]] = field(default_factory=dict)
    # 同回合内被并掉的**重复锚点**数（调用方传重了 ⇒ 只发一次，但重了几个必须是字段）。
    # 不记这个数，`planned` 与 `used + not_run` 就对不上账，「少打了几次」又会长得像「没这些点」。
    anchors_merged: Dict[str, int] = field(default_factory=dict)

    @property
    def anchors_not_run(self) -> Dict[str, int]:
        """计划要打但没打满词表的锚点数（池子见底时的披露位，P0-3）。

        恒等式 `planned == used + merged + not_run` 由 `collect_triad_evidence` 逐类算完
        再返回，测试对着它核对分账闭合（与判盲那套三态分账同形）。
        """
        return {cat: max(0, self.anchors_planned.get(cat, 0) - self.anchors_used.get(cat, 0)
                         - self.anchors_merged.get(cat, 0))
                for cat in self.anchors_planned}

    @property
    def discs(self) -> Tuple[EvidenceDisc, ...]:
        """本轮证据盘 = `evidence.discs` 的同一批对象，不留第二份。"""
        return self.evidence.discs


async def collect_triad_evidence(
    client: Any,
    scope: Any,
    anchors: Dict[str, Sequence[Tuple[float, float]]],
    pool: POIBudget,
    *,
    round_no: int = 1,
) -> ForensicRound:
    """按需扩容回合：在给定锚点上重查三要素，产出**新盘 + 新点位**（计划阶段 5 / v5.8）。

    四条纪律，各防一件具体的事：

    1. **不猜预算、不挑锚点**：`pool` 必须是调用方按 `quota.forensic_budget()` 实例化的快照
       （与 `collect_poi.budget_snapshot` 同纪律）；打哪些锚点已由
       `LatticeAnchors.plan_expansion(region, grid, cat, inside=…)` 决定，本函数一个都不自己
       挑 —— 再决定一次就是第二实现。
    2. **每锚点全词**：`triad_keywords(cat)`（market 3 词、pharmacy/primary 各 1 词），
       沿用生产的关键词口径，不是脚本里 `keywords[0]` 那条捷径。
    3. **池子拒了的词不产盘**：`not_run` 只是「没打」，把它写成一块半径 0 的盘等于凭空宣布
       「这里查过且什么都没有」。它只进 `starved_terms` 与 `anchors_not_run` 两个披露位。
       `anchors_used` 只数**词表全部发出去**的锚点 ⇒ 打了一半的锚点算 `not_run`（保守方向：
       宁可少认一个锚点，也不把「只查了一个词」报成「这个点查干净了」）。
    4. **调用失败不退款 + 记 `api_error`**：与三条既有检索通道同一语义，行由
       `_api_error_row` 造。

    取证通道**一律走 `geometric` 去重**（不跟随类目通道的设施归并）：盲区是「1km 内有没有」
    的硬判，宁多勿少，归并少掉一个坐标就等于少判一处（`_dedupe` 那条「隔离墙」注释）。
    """
    rows: List[TermEvidence] = []
    discs: List[EvidenceDisc] = []
    raw_by_cat: Dict[str, List[Dict[str, Any]]] = {}
    planned: Dict[str, int] = {}
    used: Dict[str, int] = {}
    merged: Dict[str, int] = {}
    attempted: Dict[str, List[Tuple[float, float]]] = {}
    starved: List[Tuple[str, str]] = []

    for category in TRIAD_KEYS:
        terms = triad_keywords(category)
        raw_anchors = tuple(anchors.get(category) or ())
        planned[category] = len(raw_anchors)
        used[category] = 0
        merged[category] = 0
        attempted[category] = []
        if not raw_anchors or not terms:
            continue
        radius_m = _term_radius(scope, category, float(getattr(scope, "collect_radius_m", 0.0)))
        # 坐标归一 + **同回合去重**：同一个锚点同一批词发两遍就是白烧（B5 那层判据），
        # 而「是不是同一个点」只能有一处判法 ⇒ 用 `anchors.anchor_key`，不在这里另写四舍五入。
        uniq: List[Tuple[float, float]] = []
        seen: set = set()
        for pos, item in enumerate(raw_anchors):
            try:
                lng, lat = float(item[0]), float(item[1])
            except (TypeError, KeyError, IndexError) as exc:
                raise ValueError(
                    f"anchors[{category!r}] 第 {pos} 项不是坐标对：{item!r} —— 这里要的是"
                    "**锚点序列**，单个锚点写作 ((lng, lat),)；裸 (lng, lat) 会被当成两个锚点、"
                    "各取到一个坐标分量"
                ) from exc
            key = anchor_key((lng, lat))
            if key in seen:
                merged[category] += 1
                continue
            seen.add(key)
            uniq.append(key)
        for tup in uniq:
            starved_here = False
            sent_any = False
            for term in terms:
                if not pool.consume(f"forensic-{category}"):
                    starved.append((category, term))
                    starved_here = True
                    continue                      # 0 次调用 ⇒ 无行无盘，只留饿死账
                sent_any = True
                out = await client.place_search(term, tup, radius_m=radius_m, max_pages=1)
                if out is None:
                    rows.append(_api_error_row(category, term, radius_m))
                    continue
                row = _evidence_row(category, term, radius_m, out, tup)
                rows.append(row)
                items = _items_of(out)
                discs.append(row.as_disc(tup))     # 唯一转换器：盘只能从举证行导出来
                if items:
                    raw_by_cat.setdefault(category, []).extend(items)
            if sent_any:
                attempted.setdefault(category, []).append(tup)
            if not starved_here:
                used[category] += 1

    points = {cat: tuple(_dedupe(raw_by_cat.get(cat, []), 50.0, "geometric"))
              for cat in TRIAD_KEYS}
    evidence = CollectionEvidence(
        # 本轮没有单一「请求半径」：逐词各自请求到哪儿写在行上（`TermEvidence.requested_radius_m`）。
        # 顶层这个数取口径定格的采集半径，语义与首轮同源，不是某一锚点的半径。
        requested_radius_m=float(getattr(scope, "collect_radius_m", 0.0) or 0.0),
        per_term=tuple(rows),
        starved_terms=tuple(starved),
        aborted=pool.remaining <= 0 and bool(starved),
        discs=tuple(discs),
    )
    return ForensicRound(round_no=round_no, evidence=evidence, points=points,
                         anchors_planned=planned, anchors_used=used, anchors_merged=merged,
                         anchors_attempted={c: tuple(v) for c, v in attempted.items()})


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