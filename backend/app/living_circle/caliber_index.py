"""生活圈口径索引层：将真实代码常量映射为机器可校验的标识符。

架构纪律：本模块只 import 生活圈子域内部模块（caliber/scoring/poi/blindspot/isochrone/report_contract），
绝不 import app.core.*；中文可读名归属各自模块，索引只做结构化组装。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# ── 视图数据结构 ────────────────────────────────────────
@dataclass(frozen=True)
class CaliberView:
    ref: str      # 规范键，如 "scoring::WEIGHTS.coverage"
    kind: str     # param | weight | category | triad | profile | field | callable | derived
    module: str   # 溯源模块
    label: str    # 中文可读名
    value: str    # 渲染后的实际值


# ── 命名空间集合（启动期注册用）──────────────────────────
# `scope` 是 rev2 追加的：判盲口径的版本号与采集证据余量都住在 `SpatialScope`
# （那里才是「三概念关系」能做构造即校验的地方），不登记进索引就让专家卡无法引用，
# 而 prose 里一旦提到它们就会被词表闸判成「编造指标」。
NAMESPACES: FrozenSet[str] = frozenset({
    "caliber", "scoring", "poi", "facility", "blindspot", "isochrone", "report", "scope",
})

# ── 内部存储 ────────────────────────────────────────────
_INDEX: Dict[str, CaliberView] = {}


def _require_attr(obj: Any, name: str, ref: str) -> Any:
    """取名册**登记过**的属性；缺失即 `AttributeError`，绝不静默跳过。

    旧写法是 `getattr(mod, name, None)` + 「非 None 才登记」，于是口径常量被改名/删掉时
    那条 ref 只是**无声缺席** —— 专家卡引用不到还算轻的，真正致命的是另一半：
    `_build_index()` 过去不清空 `_INDEX`、只做覆盖，所以在已建过索引的进程里重建一次，
    缺失符号的那条 ref 会带着**旧值**留在索引里替一个不存在的东西作证。
    这是本仓挂账的「改名后 `.get` 静默归零」类缺陷的加强版，两处必须一起修才成立。
    """
    try:
        return getattr(obj, name)
    except AttributeError:
        where = getattr(obj, "__name__", type(obj).__name__)
        raise AttributeError(
            f"口径名册登记的 {ref} 在 {where} 上不存在：要么把名册一起改，要么把符号补回来；"
            f"静默跳过会让索引替已消失的口径作证（计划 v4 阶段 0）"
        ) from None


def _build_index() -> None:
    """重建口径索引：**先建到新表、成功才整体换出**。

    两个坑一起堵（计划 v4 阶段 0）：
    ① 只做覆盖不清空 ⇒ 名册里被改名/删掉的符号，其 ref 会带着**旧值**留在进程级全局里
       替一个不存在的东西作证（僵尸 ref，比静默缺席更坏：它看着像有举证）；
    ② 可"先清空再逐条填"会留下另一个坑 —— 填到一半抛错（①要逼出来的正是这种错），
       进程就只剩半张甚至空索引，下游 `view()` 全部静默返回 None，比僵尸 ref 更难查。
    所以构建期写入落在新表，成功后一次性换出；异常则回滚到旧表并原样抛出。
    """
    global _INDEX
    previous = _INDEX
    _INDEX = {}
    try:
        _populate_index()
    except BaseException:
        _INDEX = previous
        raise


def _populate_index() -> None:
    """从各模块遍历容器把名册逐条填进当前 `_INDEX`（换出与回滚由 `_build_index` 负责）。"""
    from app.living_circle import (
        blindspot,
        caliber,
        facility_rule,
        geo_utils,
        isochrone,
        poi,
        report_contract,
        scoring,
    )

    # 1. caliber :: DEFAULT_CALIBERS（出行方式 × 字段 + 派生属性）
    for mode, c in caliber.DEFAULT_CALIBERS.items():
        ns = f"caliber::{mode}"
        # 基础字段
        for fname in ("speed_m_per_min", "detour_k", "study_radius_m",
                       "iso_minutes", "reach_full_min", "blind_radius_m", "basis"):
            val = _require_attr(c, fname, f"{ns}.{fname}")
            label = _caliber_field_label(fname)
            _INDEX[f"{ns}.{fname}"] = CaliberView(
                ref=f"{ns}.{fname}", kind="param", module="caliber",
                label=label, value=_fmt_caliber_value(fname, val),
            )
        # 派生属性
        for dname in ("innermost_radius_m", "reach_radius_bound_m",
                       "fine_band", "grid_n_for_standard"):
            val = _require_attr(c, dname, f"{ns}.{dname}")
            label = _caliber_derived_label(dname)
            _INDEX[f"{ns}.{dname}"] = CaliberView(
                ref=f"{ns}.{dname}", kind="derived", module="caliber",
                label=label, value=str(val),
            )

    # 2. scoring :: WEIGHTS
    for dim, w in scoring.WEIGHTS.items():
        _INDEX[f"scoring::WEIGHTS.{dim}"] = CaliberView(
            ref=f"scoring::WEIGHTS.{dim}", kind="weight", module="scoring",
            label=_scoring_dim_label(dim), value=str(w),
        )
    # BLINDSPOT_PENALTY_CAP
    cap = _require_attr(scoring, "BLINDSPOT_PENALTY_CAP", "scoring::BLINDSPOT_PENALTY_CAP")
    _INDEX["scoring::BLINDSPOT_PENALTY_CAP"] = CaliberView(
        ref="scoring::BLINDSPOT_PENALTY_CAP", kind="param", module="scoring",
        label="盲区扣分上限", value=str(cap),
    )

    # 3. poi :: CATEGORY_DEFS / TRIAD_KEYWORDS
    for cat, defn in poi.CATEGORY_DEFS.items():
        _INDEX[f"poi::CATEGORY_DEFS.{cat}"] = CaliberView(
            ref=f"poi::CATEGORY_DEFS.{cat}", kind="category", module="poi",
            label=defn.get("label", cat),
            # value 里带"满分线"三个字：裸 `ideal_circle=3` 会被 prose 与专家卡读成"要 3 处才算及格"，
            # 而它是**拿到 100% 的分需要几处**；及格/缺口在系统里是网格判据，不是这个数（计划 §十九）。
            value=f"覆盖度满分线 ideal_circle={defn.get('ideal_circle', '—')}",
        )
    for key, kw_list in poi.TRIAD_KEYWORDS.items():
        _INDEX[f"poi::TRIAD_KEYWORDS.{key}"] = CaliberView(
            ref=f"poi::TRIAD_KEYWORDS.{key}", kind="triad", module="poi",
            label=f"三要素·{key}", value=", ".join(kw_list),
        )
    # norm_name 作为 callable
    _INDEX["poi::norm_name"] = CaliberView(
        ref="poi::norm_name", kind="callable", module="poi",
        label="POI 名称归一", value="poi.norm_name()",
    )

    # 3b. facility :: 设施实体归并判据（口径变更必须可举证，否则报告里的点位名
    #     与百度原始 POI 名不再逐字一致却无从回溯）
    _INDEX["facility::FACILITY_RULE_VERSION"] = CaliberView(
        ref="facility::FACILITY_RULE_VERSION", kind="param", module="facility",
        label="设施归并判据版本", value=facility_rule.FACILITY_RULE_VERSION,
    )
    _INDEX["facility::FACILITY_MERGE_M"] = CaliberView(
        ref="facility::FACILITY_MERGE_M", kind="param", module="facility",
        label="设施归并半径", value=str(facility_rule.FACILITY_MERGE_M),
    )
    _INDEX["facility::SUB_POINT_SUFFIXES"] = CaliberView(
        ref="facility::SUB_POINT_SUFFIXES", kind="param", module="facility",
        label="功能子点后缀词表",
        value=f"{len(facility_rule.SUB_POINT_SUFFIXES)} 项："
              + "、".join(facility_rule.SUB_POINT_SUFFIXES[:6]) + "…",
    )
    # 三要素通道刻意**不**跟随类目归并 —— 这是判盲口径的一部分，必须可被专家卡引用
    _INDEX["facility::triad_channel_policy"] = CaliberView(
        ref="facility::triad_channel_policy", kind="param", module="facility",
        label="三要素通道归并策略", value="geometric（盲区 1km 硬判不随归并减少坐标）",
    )
    _INDEX["facility::merge_enabled"] = CaliberView(
        ref="facility::merge_enabled", kind="param", module="facility",
        label="设施归并开关", value=str(caliber.facility_merge_enabled()),
    )
    # same_facility / dedupe_facility 作为 callable
    for fname in ("same_facility", "facility_core", "promote_display_name"):
        _INDEX[f"facility::{fname}"] = CaliberView(
            ref=f"facility::{fname}", kind="callable", module="facility",
            label=f"设施判据 {fname}", value=f"facility_rule.{fname}()",
        )

    # 4. blindspot :: 常量
    for cname in ("BLIND_RADIUS_M", "BLIND_GRID_M", "SEV_HEAVY", "SEV_MEDIUM",
                  # 逐格台账的表示法三枚：不登记 ⇒ 专家卡一引用就被词表闸判成虚构指标
                  # （阶段 4 的老坑）。`LEDGER_UNKNOWN` 是第三态那个记号本身，值得单独可引。
                  "LEDGER_SCHEMA_VERSION", "LEDGER_GRID", "LEDGER_UNKNOWN"):
        _INDEX[f"blindspot::{cname}"] = CaliberView(
            ref=f"blindspot::{cname}", kind="param", module="blindspot",
            label=_blindspot_label(cname),
            value=str(_require_attr(blindspot, cname, f"blindspot::{cname}")),
        )
    # EFFORT_BY_DIST
    _INDEX["blindspot::EFFORT_BY_DIST"] = CaliberView(
        ref="blindspot::EFFORT_BY_DIST", kind="param", module="blindspot",
        label="补点努力系数",
        value=str(_require_attr(blindspot, "EFFORT_BY_DIST", "blindspot::EFFORT_BY_DIST")),
    )

    # 5. isochrone :: MODE_PARAMS
    #    名册只登记 `grid_n`：`smooth` 是历史上的幻影条目（MODE_PARAMS 里从来没有这个键，
    #    旧写法靠 `params.get(...)` 静默跳过，于是它一直"登记在案"却永不落地）。
    for mode, params in isochrone.MODE_PARAMS.items():
        if "grid_n" not in params:
            raise KeyError(
                f"isochrone::{mode}.grid_n 已登记进名册，但 MODE_PARAMS[{mode!r}] 里没有这个键"
            )
        _INDEX[f"isochrone::{mode}.grid_n"] = CaliberView(
            ref=f"isochrone::{mode}.grid_n", kind="param",
            module="isochrone", label=f"{mode}·grid_n", value=str(params["grid_n"]),
        )

    # 5b. isochrone / geo_utils :: 形状口径（第五把尺：只诊断，不入分）
    #     四件"怎么量的"必须进名册：分箱宽度、分相、原点、方位角实现；外加**复算容差**一把尺
    #     （签发侧 B17 与读侧 shapeOfZone 必须同尺，跨端那份由 test_fixture_mirror 钉相等）。
    #     它们不是实现细节
    #     ——用生产 `shape_of` 实算：换原点圆度动 0.029（0.713→0.684，两城之间才差 0.082），
    #       换分相最弱读数 438→571（虚高 133m）。判据见 tests/test_shape_caliber.py 两条正对照。
    _INDEX["report_contract::SHAPE_CIRCUMRADIUS_TOL_M"] = CaliberView(
        ref="report_contract::SHAPE_CIRCUMRADIUS_TOL_M", kind="param", module="report_contract",
        label="形状·外接半径恒等容差(m)",
        value=str(_require_attr(report_contract, "SHAPE_CIRCUMRADIUS_TOL_M",
                                 "report_contract::SHAPE_CIRCUMRADIUS_TOL_M")),
    )
    for name in ("SHAPE_EMIT", "SHAPE_MINUTES"):
        _INDEX[f"isochrone::{name}"] = CaliberView(
            ref=f"isochrone::{name}", kind="param", module="isochrone",
            label=f"形状·{name}", value=str(_require_attr(isochrone, name, f"isochrone::{name}")),
        )
    for name in ("SHAPE_BIN_DEG", "SHAPE_BIN_PHASE", "SHAPE_ORIGIN", "SHAPE_AZIMUTH_FN",
                 "SHAPE_SCALAR_TOL"):
        _INDEX[f"geo_utils::{name}"] = CaliberView(
            ref=f"geo_utils::{name}", kind="param", module="geo_utils",
            label=f"形状·{name}", value=str(_require_attr(geo_utils, name, f"geo_utils::{name}")),
        )

    # 6. report :: 契约字段 + 采样点分档（timed_count / in_reach_count / sample_count）
    live_required = _require_attr(
        report_contract, "_LIVE_REQUIRED", "report_contract._LIVE_REQUIRED")
    for fname in live_required:
        _INDEX[f"report::{fname}"] = CaliberView(
            ref=f"report::{fname}", kind="field", module="report_contract",
            label=f"报告字段·{fname}", value=f"living_circle.{fname}",
        )
    # ⚠️ 旧名 `report::reachable_count` 的语义其实是「测时返回了值的点数」，
    # 不是「可达点数」——阶段 −1 改名为 timed_count，并**新增** in_reach_count
    # 承载真正的「可达」（≤ caliber.reach_full_min 分钟）。两个数都不能省：
    # 只有一个时，要么把不可达说成可达（旧病），要么把测时覆盖率的信息丢掉。
    _INDEX["report::timed_count"] = CaliberView(
        ref="report::timed_count", kind="field", module="report_contract",
        label="已测时采样点数", value="living_circle.timed_count",
    )
    _INDEX["report::in_reach_count"] = CaliberView(
        ref="report::in_reach_count", kind="field", module="report_contract",
        label="可达采样点数（≤reach_full_min）", value="living_circle.in_reach_count",
    )
    _INDEX["report::sample_count"] = CaliberView(
        ref="report::sample_count", kind="field", module="report_contract",
        label="总采样点数", value="living_circle.sample_count",
    )

    # 7. scope :: 判盲口径的版本号（rev2 单一事实源）
    #    不登记就无法被专家卡引用，而 prose 一旦提到就会被词表闸判成「编造指标」。
    #    `BLIND_RADIUS_M` 已在 `blindspot::` 下登记（同一个定义，两个 ref 只会让名册重复），
    #    这里只补 rev2 新增的那一把常量。
    #    ⚠️ 曾登记过的 `scope::EVIDENCE_MARGIN_M`（采集证据余量）**已撤**：余量不再是一个
    #    模块常量，而是「外接圆 + 本次判定半径」的导出量（片 1b 第二段）。可举证路径现在是：
    #    参数侧 `caliber::{mode}.blind_radius_m`（住所），产物侧 `report::evidence_margin_m`
    #    （payload 里那个数）。⚠️ 产物还有第二把键 `collect_margin_m`（前端恒等式读它），
    #    名册里**没有**它的 ref —— 这是改动前就存在的不对称，不是本轮造成的；补登记会新增
    #    一条可被 prose 引用的 ref，归批次二与 B10 读侧一起判（第十六轮复审 P2-4）。
    from app.living_circle import scope as _scope

    for sname, slabel in (
        ("SCOPE_POLICY_VERSION", "判盲口径版本"),
    ):
        _INDEX[f"scope::{sname}"] = CaliberView(
            ref=f"scope::{sname}", kind="param", module="scope",
            label=slabel,
            value=str(_require_attr(_scope, sname, f"scope::{sname}")),
        )

    # 8. 证据相与评分置信度的**报告载荷键**
    #    ⚠️ 用扁平 ref（`report::evidence_radius_m`），value 才写嵌套路径 —— 不要复制
    #    `_LIVE_REQUIRED` 那处的畸形形态（它把 path-tuple 直接当键，产出
    #    `report::('poi','points')` 这种不可引用 ref；本期不改它，但新键不跟着错）。
    for fname, flabel, fpath in (
        ("cells_inside", "可达区内判定格数", "living_circle.caliber.cells_inside"),
        ("cells_judged", "已判定格数", "living_circle.caliber.cells_judged"),
        ("cells_unknown", "证据不足未判格数", "living_circle.caliber.cells_unknown"),
        # 第三态：判不动且归因于**服务端封顶**的格（`cells_inside = judged + unknown + 这一格`）。
        # 此前是「载荷里有、名册里无」—— 专家口径引用不到它，而报告每天都在发射它（阶段 3-f 的
        # 产物）。登记它不等于修好读侧：`report_contract` 的 B10/B11 仍按 `inside` 算分母，
        # 那条账记在批次二（`test_degrade_chain.py:930/:954` 那对 xfail 是它的台账）。
        ("cells_unjudgeable_by_cap", "接口封顶判不动格数", "living_circle.caliber.cells_unjudgeable_by_cap"),
        ("evidence_margin_m", "证据余量声明", "living_circle.caliber.evidence_margin_m"),
        ("evidence_radius_m", "实测证据边界半径", "living_circle.caliber.evidence_radius_m"),
        ("evidence_frontier_m", "逐类实测证据边界", "living_circle.caliber.evidence_frontier_m"),
        ("evidence_complete", "证据完整性", "living_circle.caliber.evidence_complete"),
        # R23-I · 成本账（欠账出处：计划 §22⑧，全链路真跑后"预登记了几次外呼"却无处核销）。
        # 它是**逐词行求和**派生出来的实测位（不是预算声明），所以登记的必须是载荷里那个末段
        # 键名本身 —— 指到 `poi_collector` 那侧就变成引用一个不发射在报告里的数。
        # ⚠️ 档位名刻意写成"成功返回的页数"而不是"外呼次数"：失败那次不留计数（`pages_fetched`
        # 只在响应正常后自增），报"次数"会让这一位替没发生的事说话（同 `forensic` 那条纪律）。
        ("evidence_pages_returned", "成功返回的检索页数", "living_circle.caliber.evidence_pages_returned"),
        ("judge_radius_m", "可判定半径", "living_circle.caliber.judge_radius_m"),
        # 片 4：取证回合的账目（跑了几轮、打了几个锚点、为什么收手）。它是**嵌套对象**，
        # 而下面那条"ref 指向的键必须真在产出对象里"的核对只看顶层末段键名 ⇒ 登记的必须是
        # `forensic` 这个块本身，不是 `forensic.rounds` 之类（浅一层就恒绿，测不到东西）。
        ("forensic", "取证回合账目", "living_circle.caliber.forensic"),
        # 逐格台账（契约 B13）。同 `forensic` 的理由：它是**嵌套对象**，登记的必须是块本身
        # —— 浅一层到 `cells_ledger.n` 会让"ref 指向的键真在产出对象里"那条核对恒绿。
        ("cells_ledger", "逐格判定台账", "living_circle.caliber.cells_ledger"),
        ("scope_policy_version", "判盲口径版本声明", "living_circle.caliber.scope_policy_version"),
        # **第二根轴的登记**（计划 §六 四步的第四步）。它与上面那把管的是两件事：那把管
        # 「证据域/判盲怎么算」，这把管「同样的点位算出什么分」。不登记 ⇒ 专家口径引用不到、
        # prose 里提到就撞词表闸，而载荷每天都在发射它（`scope.py` 唯一写点）。
        ("coverage_caliber_version", "评分口径版本声明", "living_circle.caliber.coverage_caliber_version"),
        # **第三根轴的登记**（笔 3-B）。它管的是「同一份实测耗时场被怎么解释」，与前两把
        # 各管一件事 ⇒ 独立命名。不登记 ⇒ 专家口径引用不到、prose 提到就撞词表闸。
        ("reach_caliber_version", "可达口径版本声明", "living_circle.caliber.reach_caliber_version"),
        # 常态绕行标定与残差耗时（`isochrone.detour_residual` 的唯一产物）。与上面
        # `timed_count` / `in_reach_count` 同一族：**发在 `sampling` 段而不是 `caliber` 段**，
        # 所以它不在 `test_caliber_invariants` 那份按 caliber 产出核对的白名单里 ——
        # 那条核对会恒判它缺键（第十六轮 P2-4 说过的"浅一层就恒绿"反过来用也一样错）。
        # 它的产出核对走真生产者：`tests/test_reach_calibration.py` 拿 `IsochroneEngine.compute()`
        # 的产物验键集，比在白名单里数末段键名强一格。
        # ⚠️ 登记的是**块本身**（`detour`），不是 `detour.residual_min` —— 与 `forensic` /
        # `cells_ledger` 同一条纪律：浅一层会让核对恒绿。
        ("detour", "常态绕行标定与残差耗时", "living_circle.sampling.detour"),
        # 实测场的**形态**参数（笔 4a 后续）：`sampling.interpolation` 一直只说方法名，
        # 幂次与近邻数躲在 `idw_from_local` 的字面量与默认形参里 ⇒ 拿到载荷的人只能信、
        # 不能复算。现在它们是有名常量（`isochrone.IDW_POWER` / `IDW_NEIGHBORS`）、由发射口
        # 进载荷、并被结论章那句「经 IDW 插值推导（幂次 2、每格取 8 个最近实测点）」引用
        # ⇒ 不登记就会撞词表闸（prose 提到而未登记＝引用不到口径）。两键各自独立登记：
        # 名册核对只看末段键名，登记成 `interpolation_form` 那种"块"反而对不上真实载荷形状
        # （这里是两个平铺标量，不是嵌套块 —— 与 `forensic` / `detour` 的情况相反）。
        ("interpolation_power", "插值幂次（IDW 的 p）", "living_circle.sampling.interpolation_power"),
        ("interpolation_neighbors", "插值近邻数（IDW 的 k）", "living_circle.sampling.interpolation_neighbors"),
        # 口径对比环（笔 B）。登记的必须是**块本身**：它是一次原子发布（阈值＋几何＋面积＋
        # 依据＋断言边界），浅一层到 `iso_compare.minutes` 会让"ref 指向的键真在产出对象里"
        # 那条核对恒绿（与 `forensic` / `cells_ledger` / `detour` 同一条纪律）。
        # 它不是第五档等值线 ⇒ 故意不并进 `isochrones` 那族，也不进四档配色与面积单调性判据。
        ("iso_compare", "口径对比环（文献阈值重切，非能力断言）", "living_circle.iso_compare"),
        ("confidence", "评分置信度", "living_circle.scores.confidence"),
        ("evidence", "盲区扣分证据链", "living_circle.scores.evidence"),
    ):
        _INDEX[f"report::{fname}"] = CaliberView(
            ref=f"report::{fname}", kind="field", module="report_contract",
            label=flabel, value=fpath,
        )

    # 9. scoring :: 盲区扣分的外推口径（rev2 新增两把）
    for pname, plabel in (
        ("BLINDSPOT_PENALTY_PER_EXTRA", "每处外推盲区扣分"),
        ("JUDGE_SHARE_FLOOR", "判定覆盖率外推下限"),
    ):
        _INDEX[f"scoring::{pname}"] = CaliberView(
            ref=f"scoring::{pname}", kind="param", module="scoring",
            label=plabel,
            value=str(_require_attr(scoring, pname, f"scoring::{pname}")),
        )


def view(ref: str) -> Optional[CaliberView]:
    """按 ref 查视图；未知返回 None（由 expert_prompt._resolve_ref 兜底）。"""
    return _INDEX.get(ref)


def resolve(ref: str) -> CaliberView:
    """按 ref 查视图；未知抛 KeyError（由 expert_prompt.try/except 兜住）。"""
    v = _INDEX.get(ref)
    if v is None:
        raise KeyError(ref)
    return v


def all_refs() -> FrozenSet[str]:
    return frozenset(_INDEX.keys())


# 政策术语表：通用领域指标术语（不绑定具体代码常量，但属合法词汇）。
POLICY_TERMS: FrozenSet[str] = frozenset({
    "覆盖率", "可达率", "多样性", "均衡性", "密度", "配额", "占比",
    "采样点可达率", "名称归一与聚簇去重口径",
    "便捷度", "丰富度", "严谨性", "可复现性", "连续性", "烟火气", "韧性",
})


def terms() -> FrozenSet[str]:
    """词表闸：所有口径标识符的中文可读名集合 ∪ 政策术语。

    画像 prose 中出现的指标术语必须 ∈ terms()，否则视为编造。
    """
    return frozenset(v.label for v in _INDEX.values()) | POLICY_TERMS


def owning_experts(ref: str, experts: List[dict]) -> List[str]:
    """反向查：哪些专家的 caliber_refs 包含此 ref。"""
    return [e["id"] for e in experts if any(r["ref"] == ref for r in e.get("caliber_refs", []))]


def validate_vocabulary(text: str) -> List[str]:
    """词表闸校验：检查文本中的指标术语是否都在允许词表中。

    返回问题清单（空列表 = 通过）。
    允许词表 = terms() ∪ POLICY_TERMS（已由 terms() 合并）。

    注意：只校验明确的指标术语，不校验普通描述性文字。
    """
    problems: List[str] = []
    allowed = terms()

    # 精确匹配已知指标术语模式（避免误报普通描述）
    # 这些是真正的指标术语，而非包含"度/性/率"等字的普通词汇
    known_metric_patterns = {
        "覆盖率", "可达率", "多样性", "均衡性", "采样点可达率",
        "名称归一与聚簇去重口径", "测时成功率", "POI去重率", "数据完整率",
        "密度", "配额", "占比", "便捷度", "丰富度", "严谨性",
        "可复现性", "连续性", "烟火气", "韧性",
    }

    # 提取文本中出现的已知指标术语
    found_metrics = [m for m in known_metric_patterns if m in text]

    for term in sorted(found_metrics):
        if term not in allowed:
            problems.append(f"发现未授权指标术语：{term!r}（不在允许词表中）")

    return problems


# ── 辅助：中文标签映射（归属各自模块，不在索引里硬编码）───
def _caliber_field_label(fname: str) -> str:
    labels = {
        "speed_m_per_min": "步行速度",
        "detour_k": "绕行系数",
        "study_radius_m": "研究半径",
        "iso_minutes": "等时圈档位",
        "reach_full_min": "最大可达时间",
        "blind_radius_m": "盲区判定半径",
        "basis": "政策依据",
    }
    return labels.get(fname, fname)


def _caliber_derived_label(dname: str) -> str:
    labels = {
        "innermost_radius_m": "最内圈半径",
        "reach_radius_bound_m": "可达半径上界",
        "fine_band": "精细档位",
        "grid_n_for_standard": "标准网格数",
    }
    return labels.get(dname, dname)


def _fmt_caliber_value(fname: str, val: Any) -> str:
    if fname == "speed_m_per_min":
        return f"{val} m/min"
    if fname == "detour_k":
        return f"×{val}"
    if fname == "study_radius_m":
        return f"{val} m"
    if fname == "iso_minutes":
        return " / ".join(str(m) + "min" for m in val)
    if fname == "basis":
        return str(val)
    return str(val)


def _scoring_dim_label(dim: str) -> str:
    labels = {"coverage": "覆盖度", "reachability": "可达性",
              "diversity": "多样性", "balance": "均衡性"}
    return labels.get(dim, dim)


def _blindspot_label(cname: str) -> str:
    labels = {
        "BLIND_RADIUS_M": "盲区判定半径",
        "BLIND_GRID_M": "盲区网格间距",
        "SEV_HEAVY": "重度阈值",
        "SEV_MEDIUM": "中度阈值",
        "LEDGER_SCHEMA_VERSION": "逐格台账表示法版本",
        "LEDGER_GRID": "逐格台账格型",
        "LEDGER_UNKNOWN": "逐格台账第三态记号",
    }
    return labels.get(cname, cname)


# ── 启动期构建 ──────────────────────────────────────────
_build_index()
