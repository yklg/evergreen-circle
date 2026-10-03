"""D4 · 体检诊断规则模板：由 LivingCircleReport(data) 规则化生成完整 Report。

与前端 F0 冻结契约同构（渲染适配器直接消费）：
  - report_type='living_circle' + living_circle 原始数据挂载
  - sections 逐章（概览/医疗/教育/菜市购物/养老/可达性/盲区诊断/结论整改）
  - 每章结论 `claim`（author=规划专家，D4 专家出诊断）+ 证据引用（evidence 闭环）
  - charts（雷达/覆盖柱/等时圈面积）+ glossary + methodology
LLM 有 Key 时仅替换解读文案，结构/数值不变（无 Key 也不阻塞，模板兜底）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.data import expert_by_id
from app.living_circle.category_rule import CATEGORY_RULES
from app.living_circle.isochrone import reach_flags


def sampling_counts(lc: Dict[str, Any]) -> Tuple[int, int, int]:
    """报告的采样点分档 ``(已测时, 圈内可达, 采样总数)`` —— 叙述文案的**唯一取值口径**。

    ⚠️ 不要在这里 filter points 自己数。阶段 −1 之前本模块有 5 处
    ``sum(1 for p in points if p.get("reachable"))``，而 ``reachable`` 的语义是
    「测时返回了值」不是「可达」，且字段已更名为 ``timed``/``in_reach`` ——
    ``dict.get`` 遇到旧名**不报错、只返回 None**，文案会静默变成「0/1049 个采样点可达」。
    这正是本计划要消灭的「静默漂移」，所以取值收敛到本函数一处。

    汇总数缺失时（历史快照）按点回算，**回算也走同一个 ``reach_flags`` 判据**。
    """
    s = (lc.get("sampling") or {})
    pts = s.get("points") or []
    timed, in_reach = s.get("timed_count"), s.get("in_reach_count")
    if timed is None or in_reach is None:
        f = reach_flags(pts)
        return f.timed_count, f.in_reach_count, len(pts)
    return int(timed), int(in_reach), len(pts)


def poi_metric_label(poi: Dict[str, Any]) -> str:
    """POI 指标文案 —— 与前端 ``lib/livingCircle.poiMetricLabel`` **逐字同口径**（阶段 2.5 / D2）。

    三段式 ``采集 N · 圈内 M · 已展示 K``：

    - **N** = ``poi.total``：**采集口径**（研究范围内检索到的总数，含圈外）。保留它是为了不把
      额度账讲错 —— 删掉会让人以为「只用 98 次检索就采到了图例里全部设施」。
    - **M** = ``sum(categories[].in_circle)``：**可达口径**。⚠️ **重算，不读 ``poi.in_circle``**：
      那是一个「与 categories 可能不一致的冗余自我声明」，读它等于把两个数各算各的老毛病
      搬到文案层（阶段 1 的教训）。
    - **K** = ``len(points)``：**下发给渲染层的点数**。装配层守恒时 ``K == M``。

    第四段**仅当装配层真的截断过**（``poi.truncated.dropped > 0``）才出现 —— 这是「静默截断」
    被消灭的可见证据：截断过一次，报告里就永久留痕。

    同一句话在 Py/TS 各有一份实现（前端不能执行 Python），口径漂移靠契约测试对齐；
    ``frontend/src/mocks/livingCircleReports.ts`` 必须调 TS 那份，**不得手写字符串**。
    """
    poi = poi or {}
    declared = sum(int((c or {}).get("in_circle") or 0) for c in (poi.get("categories") or []))
    actual = len(poi.get("points") or [])
    base = f"采集 {int(poi.get('total') or 0)} · 圈内 {declared} · 已展示 {actual}"
    tr = poi.get("truncated") or {}
    dropped = int(tr.get("dropped") or 0)
    if dropped <= 0:
        return base
    detail = "/".join(
        f"{(x or {}).get('category')} {int((x or {}).get('dropped') or 0)}"
        for x in (tr.get("categories") or [])
        if int((x or {}).get("dropped") or 0) > 0
    )
    cap = tr.get("cap_per_cat")
    cap_note = f"，每类上限 {cap}" if cap is not None else ""
    return f"{base} · 另有 {dropped} 处未展示（{detail}{cap_note}）"


def poi_dedupe_rule_label(poi: Dict[str, Any]) -> str:
    """POI 清洗规则文案 —— 与前端 ``lib/livingCircle.poiDedupeRuleLabel`` **逐字同口径**。

    报告叙述「做了什么清洗」必须由报告自己的披露推出，不能钉死在模板里：旧写法把
    「名称归一与 50m 聚簇去重」写死，设施归并上线后报告仍在描述修复前的算法 ——
    词表闸抓虚构指标，抓不到这种**过期描述**，它是报告文本层造假。

    ``poi.merged`` 缺失 = 归并上线前冻结的快照 ⇒ 退回旧描述，而不是谎报新规则生效过。
    """
    poi = poi or {}
    base = "名称归一与 50m 聚簇去重"
    mg = poi.get("merged") or {}
    if not mg.get("enabled"):
        return base
    version = mg.get("rule_version") or "?"
    n = int(mg.get("absorbed") or 0)
    if n <= 0:
        return f"{base} + 设施实体归并（{version}，本次无同体子点）"
    detail = "/".join(
        f"{(x or {}).get('category')} {int((x or {}).get('absorbed') or 0)}"
        for x in (mg.get("categories") or [])
        if int((x or {}).get("absorbed") or 0) > 0
    )
    return f"{base} + 设施实体归并（{version}，吸收 {n} 处同体子点：{detail}）"


def _expert(eid: str) -> Dict[str, str]:
    """署名由权威名册 experts.json 派生（不再有第二份姓名表）。

    role 取 role_title 首段中文；名册缺该 id 时回落 id 本身 + 通用职位而非抛 KeyError，
    避免一个专家条目问题打断整份 D4 报告装配。
    """
    e = expert_by_id(eid) or {}
    return {
        "name": e.get("name") or eid,
        "role": (e.get("role_title") or "").split(" / ")[0] or "规划专家",
    }


def _expert_name(eid: str) -> str:
    return _expert(eid)["name"]


def _fmt_min(m) -> str:
    return "—" if m is None else f"{m}min"


def _pct(v) -> str:
    return f"{round(float(v) * 100)}%"


def _cat(lc: dict, key: str) -> Optional[dict]:
    for c in (lc.get("poi") or {}).get("categories", []):
        if c.get("category") == key:
            return c
    return None


def _grade(total: float) -> str:
    if total >= 85:
        return "优"
    if total >= 70:
        return "良"
    if total >= 55:
        return "中"
    return "差"


def _loc_prefix(scene: dict) -> str:
    """地点前缀：``城市 · 地址｜``，**空片段不参与拼接**；全空时整个前缀（含 ``｜``）省略。

    为什么要判空：``address`` 可能为空（例如区划选择只给了城市）。直接 f-string 拼接会产出
    「昆明市 · ｜综合 64.4 分」这种悬空分隔符 —— 分隔符只有在两侧都有内容时才有意义。
    """
    parts = (
        str(scene.get("city") or "").strip(),
        str(scene.get("address") or "").strip(),
    )
    joined = " · ".join(p for p in parts if p)
    return f"{joined}｜" if joined else ""


def lc_subtitle(lc: dict) -> str:
    """报告副标题 —— **单一实现**：生成报告与存量回填共用这一份公式。

    把两个判据收在一个函数里，避免"生成时写对、回填时又写歪"：

    - 「共 N 处设施」数**可达区内**（``poi.in_circle``），不是采集区内（``poi.total``）。
      旧实现引 ``poi.total``，同一份报告里「POI 采集（圈内 N）」与副标题会互相矛盾。
    - 地点前缀空片段不参与拼接（见 :func:`_loc_prefix`），避免「昆明市 · ｜综合 …」悬空分隔符。
    """
    scene = lc.get("scene") or {}
    total = (lc.get("scores") or {}).get("total", 0)
    poi_in_reach = int((lc.get("poi") or {}).get("in_circle") or 0)
    if (lc.get("data_origin") or "") == "offline":
        # 离线估算：不产出可比章节（P0-2 诚实性），仅体检骨架
        return f"{_loc_prefix(scene)}离线估算 · 评分待实时体检 · 未联网采集 POI"
    return (
        f"{_loc_prefix(scene)}综合 {total} 分（{_grade(total)}）"
        f"· {len(lc.get('blindspots') or [])} 处服务盲区"
        f" · 共 {poi_in_reach} 处设施（可达区内）"
    )


def _triad(lc: dict, facility: str) -> Optional[dict]:
    for t in (lc.get("scores") or {}).get("triads", []):
        if t.get("facility") == facility:
            return t
    return None


def _cov_score(c: Optional[dict]) -> float:
    return float((c or {}).get("coverage", 0.0))


def _ideal(cat: str) -> int:
    """覆盖度**满分线**（拿到 100% 要几个分子）。后端读 `CATEGORY_RULES` 拿得到，
    报告 payload 里**没有**这个数 ⇒ 前端那几句（`mocks/livingCircleReports.ts`）不写分母，
    分母只许出现在这里（否则就是第二份尺，见 §十九）。"""
    return int((CATEGORY_RULES.get(cat) or {}).get("ideal_circle") or 1)


# 「门槛项不足」这句话有**六种**真成因会让它失真，六种都只活在载荷里 ⇒ 各配一个子句上屏
# （片 R23-A·乙 接前两种，片 R23-B1 接第三种，片 R23-B3 接第四种，片 R23-D 接第五、六种）：
# ①某词因预算**一次都没发起**（`caliber.evidence_starved_terms`）
# ②某词发了、**我们没接着翻完**（`evidence_truncated_terms`，单页上限 / 收益止损）
# ③这一类**整轮没轮到扩词**（`evidence_expansion_unfunded_categories`，存的是裸类别名 ——
#   那一轮连词名都还没产生）。
# ④这一类**扩过词、却在额度见底时还没达标**（`evidence_expansion_out_of_budget_categories`，
#   同样存裸类别名）。③④ 是"钱不够"的两种形状：③是排程没摊到，④是摊到了但额度太薄 ——
#   合并就看不出该怪排程还是怪额度。少交代一种，读者就只能把"不足"读成"社区没有"。
# ⑤某词**接口自称还有货却断了页**（`evidence_capped_terms`）：再怎么加预算也拿不到这一截。
# ⑥某词**请求没成**（`evidence_failed_terms`）：这一词一无所知，不是"查了没查全"。
#   ⚠️ ⑤⑥ 在 R23-D 之前**混在②里**（那一位的谓词是 `not complete`，五种停法全落进来）⇒
#   对⑥是**假话**（根本没成）、对⑤是**归责错位**（读者会以为加预算能拿到）。
#   编号按**落地顺序**排，屏上顺序按**归责由近及远**排（①②⑤⑥③④，见下面两处循环）——
#   两套序不同是有意的：读者要先看到"我们的失职"，再看到"额度怎么排的"。
# ⚠️ 曾经还有**第七种**：采集按**点数**收手、分子按**门槛项**算，于是"点数够了就先停手"。
#   它由 R23-B2 就地修掉（收手单位改到与分子同一个，见 `poi_collector._at_target`），
#   所以那句"停止线按点数算"的交代**必须随之撤掉** —— 撤句与换单位同批，留着就是假话。
# ⚠️ 下面**九个**常量与前端 `mocks/livingCircleReports.ts` 的同名件**逐字同源**，由
#    `tests/test_fixture_mirror.py` 的镜像判据钉住；拼装规则也只许一份：
#    `_GAP_LEAD + 子句…(_GAP_JOIN)… + _GAP_TAIL`。
#    「本次有 N 个…」写在**子句里**而不是前缀里，是因为③④两种子句（都没扩够）不以计数开头。
_GAP_LEAD = '另需交代：'
_GAP_STARVED = '本次有 {n} 个{label}类检索词因预算未发起（{terms}）'
_GAP_TRUNCATED = '本次有 {n} 个{label}类检索词发了但没查全（{terms}）'
# ⚠️ 括号里写"一次都没扩成"而不是"一个词都没发起"：一类**首次**扩词就撞上接口失败、
#    且此时额度正好归零 ⇒ 它确实**发起过**（`_record_failure` 留了 `api_error` 行），
#    说"没发起"就是假话；"没扩成"两种分支都为真。（计划 §14⑤.3）
_GAP_UNFUNDED = '本轮没有额度为这一类扩词（一次都没扩成）'
_GAP_OUT_OF_BUDGET = '这一类的扩词在到达标线之前因额度见底中断（扩过词，不是查够了）'
# R23-D（#71）：从②里移出来的两种归责各说各的。⚠️ 措辞里**不许**出现"我们没翻"或"再查就有"：
# ⑤是接口自己断的页（加预算也拿不到），⑥是这一词压根没成（一无所知，连"翻过"都说不出口）。
_GAP_CAPPED = '本次有 {n} 个{label}类检索词接口自称还有货却断了页（{terms}）'
_GAP_FAILED = '本次有 {n} 个{label}类检索词请求没成（{terms}）'
_GAP_JOIN = '；'
_GAP_TAIL = ' ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。'


def _evidence_gap_note(caliber: Optional[dict], category: str, label: str) -> str:
    """本类「没查过 / 没查全 / 它不给 / 没查成 / 整轮没扩词 / 扩到一半没钱」那半句；
    无话可说时返回**空串**（不印，也不硬编「0 个」）。

    只读载荷、不重判。六个来源是**六种不同缺陷**（`scope.py` 那处注释分职），所以各读各的键：
    - `evidence_starved_terms` / `evidence_truncated_terms` / `evidence_capped_terms`（R23-D）/
      `evidence_failed_terms`（R23-D）是**全类混合表**，形如 `类:词`，
      必须按 `{category}:` 前缀筛本类，否则教育类的账会印到医疗节头上；
    - `evidence_expansion_unfunded_categories`（R23-B1）/ `evidence_expansion_out_of_budget_categories`
      （R23-B3）是**类别表**，按类名整等判定 —— 它们没有"词"可指（前者词根本没被推导出来，
      后者是词跑到一半额度没了）。
    键缺席（换代前冻结的快照）与空表都算无话可说 —— 前者是「不知道」，后者是「查全了」，
    两种都不许印成「0 个」。
    """
    clauses: List[str] = []
    for tpl, key in ((_GAP_STARVED, "evidence_starved_terms"),
                     (_GAP_TRUNCATED, "evidence_truncated_terms"),
                     (_GAP_CAPPED, "evidence_capped_terms"),
                     (_GAP_FAILED, "evidence_failed_terms")):
        raw = (caliber or {}).get(key)
        if not isinstance(raw, list):
            continue
        mine = [t for t in raw if isinstance(t, str) and t.startswith(f"{category}:")]
        if mine:
            clauses.append(tpl.format(n=len(mine), label=label, terms='、'.join(mine)))
    for tpl, key in ((_GAP_UNFUNDED, "evidence_expansion_unfunded_categories"),
                     (_GAP_OUT_OF_BUDGET, "evidence_expansion_out_of_budget_categories")):
        hit = (caliber or {}).get(key)
        if isinstance(hit, list) and category in hit:
            clauses.append(tpl)
    if not clauses:
        return ''
    return _GAP_LEAD + _GAP_JOIN.join(clauses) + _GAP_TAIL



def _med_cov_sentence(m: Optional[dict], caliber: Optional[dict]) -> str:
    """医疗节那句「达标 / 存在缺口」必须自证它判的是哪把尺（第 21 轮 P1-2 + §十九 措辞义务）。

    用户 10-01 拍板"维持按分数 75%" ⇒ 判据代码不动，但换来两条文字义务：
    ①"达标"= 覆盖度 ≥75%，`cov-1` 下等价于**基层医疗门槛项 ≥⌈0.75×满分线⌉ 家**，
      不许说成"医疗不缺了"；②"存在缺口"只指门槛项未计满，**不许**说成"圈内没有医疗设施"。
    两个分支各说各的真话，不共用一句。名单与分子都取 payload（`scored_as`/`required_in_circle`），
    缺键（换代前冻结的存量快照）⇒ 照点数说，不挂门槛项文案。
    「未发起 / 没查全」那半句（`_evidence_gap_note`）**只挂在缺口分支**：达标说的是分子已计满，
    证据面不完整不会让它变成假话，硬加上去就是"达标了却说没查完"。
    """
    cov = _cov_score(m)
    req = (m or {}).get("required_in_circle")
    in_circle = int((m or {}).get("in_circle") or 0)
    if req is None:
        return f"覆盖度 {_pct(cov)} 按圈内点数计（这份快照出自门槛项口径之前）。"
    labels = (m or {}).get("scored_as") or []
    named = f"（{' / '.join(str(x) for x in labels)}）" if labels else ""
    need = -((-3 * _ideal("medical")) // 4)          # = ceil(0.75 × 满分线)
    head = (f"其中计入覆盖度分子的是基层医疗门槛项 {req} 处{named}，"
            f"另有 {in_circle - req} 处不计入分子（含诊所等不计分形状与判不准的存疑项）。")
    tail = (f"覆盖度 {_pct(cov)} ⇒ 本节写「达标」—— 这只指该覆盖度 ≥75%，在此分子口径下"
            f"相当于圈内基层医疗 ≥{need} 家；不等于「医疗不缺了」。"
            if cov >= 0.75 else
            f"覆盖度 {_pct(cov)} ⇒ 本节写「存在缺口」—— 这只指基层医疗门槛项不足 {need} 家"
            f"（覆盖度 <75%），不表示圈内没有医疗设施（圈内仍有 {in_circle} 处）。"
            + _evidence_gap_note(caliber, "medical", str((m or {}).get("label") or "医疗")))
    return head + tail


def _edu_cov_sentence(e: Optional[dict], caliber: Optional[dict]) -> str:
    """教育节把「圈内 N 处」与「覆盖度 X%」拆成两个口径各自的数。

    旧写法两句并排（凯里：圈内 15 处 + 覆盖度 33.3%），读者按点数复算 15÷3=100% ⇒ 只能认定
    数据对不上。⚠️ 本节的「覆盖达标」判的是**小学 1km 三要素事实**、置信度判的是**这个覆盖度
    是否 ≥75%** —— 两把尺不同，所以"达标 + 置信度 medium"是合法组合，必须当场说圆。
    「没发起 / 没查全 / 整轮没扩词」那一句同样**只在 <75% 时挂**（本节没有分支句，所以闸门得显式写在这里）。
    """
    cov = _cov_score(e)
    req = (e or {}).get("required_in_circle")
    in_circle = int((e or {}).get("in_circle") or 0)
    if req is None:
        return f"覆盖度 {_pct(cov)} 按圈内点数计（这份快照出自门槛项口径之前）。"
    labels = (e or {}).get("scored_as") or []
    named = f"「{' / '.join(str(x) for x in labels)}」" if labels else "门槛项"
    gap = '' if cov >= 0.75 else _evidence_gap_note(caliber, "education", str((e or {}).get("label") or "教育"))
    return (f"但覆盖度的分子只取{named} {req} 处 ÷ 满分线 {_ideal('education')} ⇒ {_pct(cov)} —— "
            f"「圈内 {in_circle} 处」与「覆盖度 {_pct(cov)}」是两个口径各自的数，"
            f"不是同一个数的两次说法。" + gap)


def _chart_radar(lc: dict) -> dict:
    dims = (lc.get("scores") or {}).get("radar", [])
    return {
        "tooltip": {},
        "radar": {"indicator": [{"name": d["dimension"], "max": 100} for d in dims], "radius": "62%"},
        "series": [{
            "type": "radar",
            "data": [{
                "name": "评分", "value": [d["score"] for d in dims],
                "areaStyle": {"opacity": 0.25, "color": "#5F7B69"},
                "lineStyle": {"color": "#5F7B69"}, "itemStyle": {"color": "#5F7B69"},
            }],
        }],
    }


def _chart_coverage(lc: dict) -> dict:
    bars = (lc.get("scores") or {}).get("bars", [])
    return {
        "tooltip": {},
        "xAxis": {"type": "category", "data": [b["label"] for b in bars]},
        "yAxis": {"type": "value", "max": 100},
        "series": [{"type": "bar", "data": [b["value"] for b in bars],
                    "itemStyle": {"color": "#5F7B69", "borderRadius": [2, 2, 0, 0]}, "barWidth": "52%"}],
    }


def _chart_isochrone(lc: dict) -> dict:
    areas = [
        {"minutes": z["minutes"], "area": z["area_km2"]}
        for z in (lc.get("isochrones") or [])
    ]
    return {
        "tooltip": {},
        "xAxis": {"type": "category", "data": [f"{a['minutes']}min" for a in areas]},
        "yAxis": {"type": "value", "name": "km²"},
        "series": [{"type": "bar", "data": [a["area"] for a in areas], "itemStyle": {"color": "#8a9c8f"}, "barWidth": "48%"}],
    }


def _sec_overview(lc: dict, ev_id: str) -> dict:
    scene = lc.get("scene") or {}
    total = (lc.get("scores") or {}).get("total", 0)
    reachable, in_reach, n = sampling_counts(lc)
    area15 = next((z["area_km2"] for z in (lc.get("isochrones") or []) if z["minutes"] == 15), 0)
    miss = [t["facility"] for t in (lc.get("scores") or {}).get("triads", []) if not t.get("covered")]
    triad_note = f"三要素中「{'、'.join(miss)}」存在 1km 覆盖缺口" if miss else "菜市场/药店/小学三要素 1km 内均可达"
    poi = lc.get("poi") or {}
    return {
        "id": "overview",
        "title": "体检概览",
        "level": 2,
        "key_takeaway": (
            f"本样区综合评分 {total}（{_grade(total)}），15 分钟步行可达圈约 {area15:.2f} km²，"
            f"{in_reach}/{n} 个采样点圈内可达（已测时 {reachable}）；设施 {poi_metric_label(poi)}。"
            f"{triad_note}，共识别 {len((lc.get('blindspots') or []))} 处服务盲区。"
        ),
        "paragraphs": [
            f"本次体检由常青圈规划专家队按「intake→plan→measure→collect→diagnose→report→audit」流水线完成，"
            f"中心点「{scene.get('name', '')}」（{scene.get('city', '')} · {scene.get('address', '')}）。",
            f"数据口径：{lc.get('data_origin')}；采样 {n} 点、已测时 {reachable}、圈内可达 {in_reach}；分级等时圈由"
            f"{(lc.get('sampling') or {}).get('interpolation')} 推导（M 阶段为 IDW 插值）。",
        ],
        "charts": [{"chart_id": "chart-overview-radar", "type": "radar", "title": "生活圈维度评分雷达", "option": _chart_radar(lc)},
                   {"chart_id": "chart-overview-coverage", "type": "bar", "title": "各设施类别覆盖度（%）", "option": _chart_coverage(lc)}],
        "source_evidence_ids": [ev_id],
    }


def _sec_medical(lc: dict) -> dict:
    m = _cat(lc, "medical")
    triad = _triad(lc, "药店")
    cov = _cov_score(m)
    req = (m or {}).get("required_in_circle")
    in_circle = int((m or {}).get("in_circle") or 0)
    return {
        "id": "medical",
        "title": "医疗配置",
        "level": 2,
        "key_takeaway": f"圈内医疗设施 {in_circle}/{(m or {}).get('total', 0)} 处，最近 {_fmt_min((m or {}).get('min_minutes'))}；药店三要素{'可达' if (triad or {}).get('covered') else '1km 内缺失'}",
        "paragraphs": [
            f"医疗类 POI 检索 {(m or {}).get('total', 0)} 处，15 分钟圈内 {in_circle} 处；{_med_cov_sentence(m, lc.get('caliber'))}",
            f"最近设施「{(m or {}).get('nearest_name') or '—'}」步行约 {_fmt_min((m or {}).get('min_minutes'))}。",
        ],
        "claims": [{
            "claim_id": f"c-lc-medical-1",
            "text": (f"医疗配置{('达标' if cov >= 0.75 else '存在缺口')}"
                     + (f"：圈内 {in_circle} 处中基层医疗门槛项 {req} 处 ⇒ 覆盖度 {_pct(cov)}"
                        if req is not None else f"：圈内覆盖度 {_pct(cov)}")),
            "field": "coverage", "evidence_ids": [f"ev-lc-poi-medical"],
            "confidence": "high" if cov >= 0.75 else "medium", "cross_validated": True, "author": _expert_name("L2-001"),
        }],
        "source_evidence_ids": [f"ev-lc-poi-medical"],
    }


def _sec_education(lc: dict) -> dict:
    e = _cat(lc, "education")
    triad = _triad(lc, "小学")
    covered = bool((triad or {}).get("covered"))
    cov = _cov_score(e)
    req = (e or {}).get("required_in_circle")
    return {
        "id": "education", "title": "教育设施", "level": 2,
        "key_takeaway": f"教育类圈内 {(e or {}).get('in_circle', 0)}/{(e or {}).get('total', 0)} 处；小学三要素{('可达（最近 ' + _fmt_min((triad or {}).get('nearest_minutes')) + '）') if covered else '1km 内缺失'}",
        "paragraphs": [
            f"小学/中学/幼儿园共检索 {(e or {}).get('total', 0)} 处，圈内 {(e or {}).get('in_circle', 0)} 处（三类都在这一类的检索范围内）；{_edu_cov_sentence(e, lc.get('caliber'))}",
            "就学通勤视角：小学接送是生活圈体检的高频痛点，本样区" + ("最近小学步行在可接受范围" if covered else "1km 内无小学，需关注跨区就学问题") + "。",
        ],
        "claims": [{
            "claim_id": "c-lc-education-1",
            # 「达标」与「置信度」两半各挂各的判据 —— 凯里教育今天就是"达标 + medium"同屏
            # （达标来自小学 1km 事实，medium 来自覆盖度 0.333），不说圆就像两套数字在打架。
            "text": (f"教育设施{'覆盖达标' if covered else '覆盖不足'}（这一句判的是小学 1km 三要素事实）"
                     f"：小学{'1km 内缺失' if not covered else '可达'}"
                     + (f"；覆盖度 {_pct(cov)}（分子取门槛项 {req} 处）" if req is not None else f"；覆盖度 {_pct(cov)}")
                     + f" ⇒ 置信度 {'high' if cov >= 0.75 else 'medium'}（判据是那个覆盖度是否 ≥75%，与上面那句不是同一把尺）"),
            "field": "coverage", "evidence_ids": ["ev-lc-poi-education"],
            "confidence": "high" if cov >= 0.75 else "medium", "cross_validated": True, "author": _expert_name("L2-002"),
        }],
        "source_evidence_ids": ["ev-lc-poi-education"],
    }


def _sec_market(lc: dict) -> dict:
    mk = _cat(lc, "market")
    sp = _cat(lc, "shopping")
    triad = _triad(lc, "菜市场")
    covered = bool((triad or {}).get("covered"))
    return {
        "id": "market", "title": "菜市与购物", "level": 2,
        "key_takeaway": f"菜市场圈内 {(mk or {}).get('in_circle', 0)}/{(mk or {}).get('total', 0)} 处，购物 {(sp or {}).get('in_circle', 0)}/{(sp or {}).get('total', 0)} 处；菜市场三要素{('可达（最近 ' + _fmt_min((triad or {}).get('nearest_minutes')) + '）') if covered else '1km 内缺失'}",
        "paragraphs": [
            "以菜市场/生鲜与超市/便利店/商场两组关键词独立检索并去重：",
            f"菜市场 {(mk or {}).get('total', 0)} 处（圈内 {(mk or {}).get('in_circle', 0)}，覆盖 {_pct(_cov_score(mk))}）；购物 {(sp or {}).get('total', 0)} 处（圈内 {(sp or {}).get('in_circle', 0)}，覆盖 {_pct(_cov_score(sp))}）。",
        ],
        "claims": [{
            "claim_id": "c-lc-market-1",
            "text": f"菜市场三要素{('覆盖达标' if covered else '1km 内覆盖缺位')}；购物覆盖 {_pct(_cov_score(sp))}",
            "field": "coverage", "evidence_ids": ["ev-lc-poi-market"],
            "confidence": "high" if _cov_score(mk) >= 0.75 else "medium", "cross_validated": True, "author": _expert_name("L2-004"),
        }],
        "source_evidence_ids": ["ev-lc-poi-market"],
    }


# 养老那一维的「未检出」措辞（#87 丙档）。**四段各有后端一份、前端一份**，
# 镜像判据 = `tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends`
# （比名字集合、比值、比使用处数）。为什么做成常量而不是就地写字符串：
# 这四句今天同时进生产正文与演示态正文，改一边忘另一边 = 同一个事实两种说法且没有任何东西会红。
# ⚠️ 这四段只替换**存在性断言**（显著缺口 / 缺少资源 / 严重不足 / 0 覆盖）；
# 数值句（`圈内 0/2 处`、`覆盖度 0%`）由数据现算，一位不动。
_LC_ELDERLY_UNDETECTED_TAIL = "，现役检索词表未检出（读作“未检出”，不等于“不存在”）"
_LC_ELDERLY_UNDETECTED_CAUSE = (
    "本维的 0 出在检索面而非资源面：养老一类现役名称词只有「养老院／日间照料中心」，"
    "社区级命名（养老服务驿站、居家养老服务站等）既不在检索词内、也不被本类判表认下"
    " ⇒ 这一维应读作“未检出”，下一步是先补词重采、再谈补建。"
)
_LC_ELDERLY_UNDETECTED_CLAIM = "未检出（圈内 0 处，现役词表不含社区级命名）"
_LC_ELDERLY_UNDETECTED_ADVICE = (
    "· 养老配置未检出（覆盖 0%）：先按社区级命名补词重采，"
    "补词后仍无再提补建日间照料中心/助老驿站，优先级 P0。"
)


def _sec_elderly(lc: dict) -> dict:
    el = _cat(lc, "elderly")
    missing = not el or el.get("in_circle", 0) == 0
    return {
        "id": "elderly", "title": "养老配置", "level": 2,
        "key_takeaway": f"养老(养老院/日间照料)圈内 {(el or {}).get('in_circle', 0)}/{(el or {}).get('total', 0)} 处{(_LC_ELDERLY_UNDETECTED_TAIL if missing else '')}",
        "paragraphs": [
            f"养老托育类设施共 {(el or {}).get('total', 0)} 处，15 分钟圈内 {(el or {}).get('in_circle', 0)} 处，覆盖度 {_pct(_cov_score(el))}。",
            (_LC_ELDERLY_UNDETECTED_CAUSE if missing
             else f"最近「{(el or {}).get('nearest_name')}」{_fmt_min((el or {}).get('min_minutes'))}。"),
        ],
        "claims": [{
            "claim_id": "c-lc-elderly-1",
            "text": f"养老配置{_LC_ELDERLY_UNDETECTED_CLAIM}" if missing else "养老配置覆盖正常",
            "field": "coverage", "evidence_ids": ["ev-lc-poi-elderly"],
            "confidence": "high" if missing else "medium", "cross_validated": False, "author": _expert_name("L2-003"),
        }],
        "source_evidence_ids": ["ev-lc-poi-elderly"],
    }


def _sec_isochrone(lc: dict, ev_id: str) -> dict:
    areas = [(z["minutes"], z["area_km2"]) for z in lc.get("isochrones", [])]
    reachable, in_reach, n = sampling_counts(lc)
    return {
        "id": "isochrone", "title": "可达性与等时圈", "level": 2,
        "key_takeaway": f"5/10/15/20 分钟等时圈面积 {' / '.join(f'{a:.2f}' for _, a in areas)} km²；采样 {n} 点，圈内可达 {in_reach}（已测时 {reachable}）；方式：{lc.get('sampling', {}).get('interpolation')}",
        "paragraphs": [
            f"以中心点为原点按 400m 粗网格 + 15min 边界带 150m 加密采样（{n} 点），步行测时后对耗时场做"
            f"{'IDW 反距离加权插值，提取 5/10/15/20 分钟等值线族' if lc.get('sampling', {}).get('interpolation') == 'idw' else '圆形近似（演示数据；M5 覆写为真实路网等时圈）'}。",
            "「不取底层路网、仅基于分布点位测时推导连通区域」是赛题鼓励的 30% 评分项：本流程全程未获取路网数据。" + ("采用散点扇形/双阶段采样，" if lc.get("sampling", {}).get("is_scattered") else ""),
        ],
        "claims": [{
            "claim_id": "c-lc-isochrone-1",
            "text": f"15 分钟步行可达圈约 {next((a for m_, a in areas if m_ == 15), 0):.2f} km²，{len(lc.get('blindspots', []))} 处盲区均位于圈内覆盖空洞",
            "field": "reachability", "evidence_ids": [ev_id],
            "confidence": "high", "cross_validated": True, "author": _expert_name("L2-005"),
        }],
        "charts": [{"chart_id": "chart-isochrone-area", "type": "bar", "title": "分级步行等时圈面积（km²）", "option": _chart_isochrone(lc)}],
        "source_evidence_ids": [ev_id],
    }


def _sec_blindspot(lc: dict) -> dict:
    bs = lc.get("blindspots", [])
    sev_label = {"heavy": "重度", "medium": "中度", "light": "轻度"}
    strat_label = {"mobile_service": "流动服务", "reroute": "移动点/改道补充", "build": "补建站点"}
    sev_count = {"heavy": 0, "medium": 0, "light": 0}
    for b in bs:
        sev_count[b.get("severity") or "light"] += 1

    def _fix_short(fx: dict) -> str:
        if not fx:
            return "—"
        strat = strat_label.get(fx.get("strategy"), fx.get("strategy") or "")
        return f"{fx.get('facility')}·{strat}·P{fx.get('priority')}" if fx.get("priority") is not None else f"{fx.get('facility')}·{strat}"

    rows = [
        {
            "id": b["id"], "center": f"{b['center'][0]:.4f}, {b['center'][1]:.4f}",
            "severity": b.get("severity") or "", "severity_label": sev_label.get(b.get("severity") or "", ""),
            "gap": b.get("gap_score"),
            "missing": b.get("missing_facilities", []),
            "nearest_name": (b.get("nearest") or [{}])[0].get("name", "—"),
            "nearest_d": (b.get("nearest") or [{}])[0].get("distance_m", 0),
            "direction": (b.get("nearest") or [{}])[0].get("direction", ""),
            "fix": (b.get("fixes") or [{}])[0],
        }
        for b in bs
    ]
    claims = [
        {
            "claim_id": f"c-lc-bs-{r['id']}",
            "text": (
                f"{r['id']}（{'、'.join(r['missing'])}）{r['severity_label'] or r['severity']}级："
                f"最近「{r['nearest_name']}」{int(r['nearest_d'])}m（{r['direction']}）；"
                f"建议 {_fix_short(r['fix'])}"
            ),
            "field": "blindspot", "evidence_ids": [f"ev-lc-bs-{r['id']}"],
            "confidence": "high", "cross_validated": True, "author": _expert_name("L3-002"),
        }
        for r in rows
    ]
    return {
        "id": "blindspot", "title": "服务盲区诊断", "level": 2,
        "key_takeaway": (
            f"识别 {len(bs)} 处 1km 服务盲区（重度 {sev_count['heavy']}／中度 {sev_count['medium']}／轻度 {sev_count['light']}）"
            if bs else "未发现 1km 服务盲区，三要素齐备"
        ),
        "paragraphs": ["按赛题口径（1km 内无菜市场/药店/小学即判盲）识别。下表为各盲区的缺失要素、严重度分级与补点建议（供整改优先级参考）。"] if bs else ["按赛题口径网格扫描：各网格点 1km 圆内三类必备设施均有覆盖。"],
        "claims": claims,
        "data_grid": {
            "columns": ["盲区编号·严重度", "缺失设施", "最近设施", "补点建议"],
            "rows": [{
                "name": f"{r['id']} · {r['severity_label'] or '—'}",
                "value": f"最近 {r['nearest_name']} {int(r['nearest_d'])}m · {_fix_short(r['fix'])}",
                "metric": " / ".join(r["missing"]),
                "source": f"{r['center']} · {r['direction']} · gap {r['gap']}", "source_url": "",
            } for r in rows],
        },
        "source_evidence_ids": [f"ev-lc-bs-{r['id']}" for r in rows],
    }


def _origin_note(lc: dict) -> str:
    """「结论基于什么取证」这句提醒的唯一归属处——按 data_origin 出话，不抄常量。

    第三档（未知/缺失）既不自称真实也不自称演示：没声明来源就是"不知道"，
    替它任选一边都是作伪证。offline 走不到这里（assemble_report 已分叉到 _offline_sections）。
    """
    origin = (lc.get("data_origin") or "")
    if origin == "live":
        interp = (lc.get("sampling") or {}).get("interpolation") or "—"
        return (f"提醒：本报告为真实接口取证（data_origin=live），分级等时圈由采样点测时经 {interp} 插值推导；"
                "正式结论以 M5 阶段实地测时为准。")
    if origin in ("fixture", "fixture_sample"):
        return "提醒：结论基于演示数据（fixture），正式结论以 M5 阶段真实路网测时为准。"
    return (f"提醒：本报告未声明数据来源（data_origin={origin or '缺失'}），结论按未核验口径解读，"
            "正式结论以 M5 阶段真实路网测时为准。")


def _sec_conclusion(lc: dict) -> dict:
    total = (lc.get("scores") or {}).get("total", 0)
    suggestions = _build_suggestions(lc)
    return {
        "id": "conclusion", "title": "体检结论与整改建议", "level": 2,
        "key_takeaway": f"综合 {total} 分（{_grade(total)}）；共 {len(lc.get('blindspots', []))} 处服务盲区，整改优先级见下",
        "paragraphs": [f"本样区{('存在多处服务盲区，整改优先级如下：' if lc.get('blindspots') else '设施覆盖整体均衡，建议保持既有配置并动态复检。')}", *suggestions,
                       _origin_note(lc)],
        "claims": [{
            "claim_id": "c-lc-conclusion-1",
            "text": f"样区综合 {total} 分（{_grade(total)}），首要整改方向：{suggestions[0].lstrip('· ') if suggestions else '持续监测'}",
            "field": "conclusion", "evidence_ids": [f"ev-lc-bs-{b['id']}" for b in lc.get("blindspots", [])],
            "confidence": "high", "cross_validated": True, "author": _expert_name("L3-001"),
        }],
        "source_evidence_ids": [f"ev-lc-bs-{b['id']}" for b in lc.get("blindspots", [])],
    }


def _build_suggestions(lc: dict) -> List[str]:
    """规则化整改建议（盲区/养老缺口兜底）。"""
    out: List[str] = []
    missing = set()
    for b in lc.get("blindspots", []):
        missing.update(b.get("missing_facilities", []))
    plan = {"菜市场": "蔬菜便民车/移动菜市点位", "药店": "社区药柜+线上配送", "小学": "校车线路/学区统筹"}
    for f in missing:
        out.append(f"· 盲区缺位「{f}」：建议{plan.get(f, '补建/补充供给')}。")
    el = _cat(lc, "elderly")
    if el and el.get("in_circle", 0) == 0:
        out.append(_LC_ELDERLY_UNDETECTED_ADVICE)
    if not out:
        out.append("· 无显著整改项。")
    return out


def build_evidence(lc: dict) -> List[dict]:
    """证据链（出处=测时/POI/判定记录，延续可溯源卖点）。"""
    _timed, _in_reach, _n = sampling_counts(lc)
    ev = [{
        "evidence_id": "ev-lc-measure",
        "source_url": "live://measure", "source_type": "api_measure",
        "title": f"采样点测时记录（{_n} 点）",
        "excerpt": f"批量算路返回 {_timed} 条耗时，其中圈内可达 {_in_reach} 条",
        "credibility": 0.95, "collected_by": "路遥川", "captured_at": lc.get("generated_at", ""), "domain": "walkability",
    }]
    for c in lc.get("poi", {}).get("categories", []):
        ev.append({
            "evidence_id": f"ev-lc-poi-{c['category']}", "source_url": "live://poi", "source_type": "poi_search",
            "title": f"{c['label']} POI 检索", "excerpt": f"命中 {c['total']} 处，圈内 {c['in_circle']} 处",
            "credibility": 0.92, "collected_by": "苏堤春", "captured_at": lc.get("generated_at", ""), "domain": c["category"],
        })
    for b in lc.get("blindspots", []):
        ev.append({
            "evidence_id": f"ev-lc-bs-{b['id']}", "source_url": "live://blindspot", "source_type": "grid_scan",
            "title": f"盲区点位 {b['id']}", "excerpt": f"1km 内无 {'、'.join(b.get('missing_facilities', []))}",
            "credibility": 0.98, "collected_by": "许映川", "captured_at": lc.get("generated_at", ""), "domain": "coverage",
        })
    return ev


def _offline_sections(lc: dict) -> List[Dict[str, Any]]:
    """离线估算报告的诚实章节（P0-2：不产出可比评分/盲区/整改建议）。

    仅保留体检骨架：概览（数据口径 + 距离模型等时圈）、可达性（圆形近似说明）、
    结论（明确待实时体检）——绝不冒充真实路网测时与 POI 分析。
    """
    scene = lc.get("scene") or {}
    areas = [(z["minutes"], z["area_km2"]) for z in lc.get("isochrones", [])]
    n = len((lc.get("sampling") or {}).get("points", []))
    reachable, in_reach, _n = sampling_counts(lc)
    area15 = next((a for m, a in areas if m == 15), 0)
    return [
        {
            "id": "overview", "title": "体检概览（离线估算）", "level": 2,
            "key_takeaway": "当前为离线估算模式：未连接百度实时路网与 POI，等时圈按「区县中心近似 + 直线距离 × 绕行系数」距离模型推导，综合评分与服务盲区需实时体检后给出，不可与实时分比较。",
            "paragraphs": [
                f"中心点「{scene.get('name', '')}」（{scene.get('city', '')} · {scene.get('address', '')}）由内置全国区划库定位（区县中心近似），研究范围 {(scene.get('study_radius_m') or 1000) / 1000:.1f}km。",
                f"数据口径：data_origin=offline · interpolation={(lc.get('sampling') or {}).get('interpolation')}。15 分钟等时圈约 {area15:.2f} km²（圆形近似，非真实路网形状）。",
                f"采样 {n} 点（直线距离 × 绕行系数 1.3 测时，已测时 {reachable}、圈内可达 {in_reach}）；未联网采集 POI，设施清单、盲区与评分需发起实时体检后给出。",
            ],
            "charts": [{"chart_id": "chart-offline-isochrone", "type": "bar",
                        "title": "分级步行等时圈面积（km² · 距离模型）", "option": _chart_isochrone(lc)}],
            "source_evidence_ids": ["ev-lc-measure"],
        },
        {
            "id": "isochrone", "title": "可达性与等时圈", "level": 2,
            "key_takeaway": f"5/10/15/20 分钟等时圈面积 {' / '.join(f'{a:.2f}' for _, a in areas)} km²；方式：{(lc.get('sampling') or {}).get('interpolation')}（圆形近似）",
            "paragraphs": [
                "离线模式未调用百度路网测时，等时圈由直线距离 × 绕行系数换算步行耗时后取圆形近似，仅用于体检骨架展示。",
                "「不取底层路网、仅基于分布点位测时推导」仍是算法主线；本页为离线兜底，形状不反映真实路网，实时体检后自动替换为 IDW 插值等时圈。",
            ],
            "charts": [],
            "source_evidence_ids": ["ev-lc-measure"],
        },
        {
            "id": "conclusion", "title": "体检结论（待实时体检）", "level": 2,
            "key_takeaway": "离线估算无真实 POI/盲区数据，本页不给出可比结论；请发起实时体检获取真实路网等时圈、设施覆盖与整改建议。",
            "paragraphs": [
                "离线模式下评分、盲区、整改建议均不产出（data_origin=offline 报告落库时 total_score 为 NULL，前端显示「待实时体检」）。",
                "有 AK/配额时对同一中心点发起实时体检，结果将落盘缓存（30 天），无 AK 时也可离线复用历史实时结果。",
            ],
            "claims": [{
                "claim_id": "c-lc-offline-1",
                "text": "离线估算模式：不产出可比评分/盲区，待实时体检",
                "field": "conclusion", "evidence_ids": [],
                "confidence": "high", "cross_validated": True, "author": _expert_name("L3-001"),
            }],
            "source_evidence_ids": [],
        },
    ]


def assemble_report(lc: dict, report_id: str, scene_key: str, title: str) -> Dict[str, Any]:
    """把 LivingCircleReport(data) 组装成完整 Report（渲染适配器直接消费）。"""
    scene = lc.get("scene") or {}
    offline = (lc.get("data_origin") or "") == "offline"
    ev_measure = f"ev-lc-measure"

    if offline:
        # 离线估算：不产出可比章节（P0-2 诚实性），仅体检骨架
        sections = _offline_sections(lc)
    else:
        sections = [
            _sec_overview(lc, ev_measure),
            _sec_medical(lc),
            _sec_education(lc),
            _sec_market(lc),
            _sec_elderly(lc),
            _sec_isochrone(lc, ev_measure),
            _sec_blindspot(lc),
            _sec_conclusion(lc),
        ]
    subtitle = lc_subtitle(lc)
    
    # Phase 6：从报告数据中读取动态选中的专家团队，若无则回退到保底名单
    team_info = lc.get("team", {})
    experts = team_info.get("expert_ids") if isinstance(team_info, dict) else None
    
    if not experts:
        # 保底：决策层 + 核心策略顾问 + 关键方法专家
        experts = [
            "L3-001", "L3-002", "L3-003", "L2-001", "L2-002", "L2-003",
            "L2-004", "L2-005", "L2-008", "L1-001", "L1-004", "L1-005", "L1-008",
        ]
    
    reasons = team_info.get("reasons", []) if isinstance(team_info, dict) else []
    dispatch = [
        {"id": eid, "reason": reasons[i] if i < len(reasons) else f"{_expert(eid)['role']}负责本节评审与结论签发（D4 专家出诊断）"}
        for i, eid in enumerate(experts)
    ]
    evidence = build_evidence(lc)
    report = {
        "id": report_id,
        "report_type": "living_circle",
        "title": title or f"{scene.get('name', '')} · 生活圈体检报告",
        "subtitle": subtitle,
        "query": scene.get("name", ""),
        "brands": [],
        "mode": "standard",
        "created_at": lc.get("generated_at", ""),
        "experts": experts,
        "dispatch": dispatch,
        "toc": [{"id": s["id"], "title": s["title"], "level": s["level"]} for s in sections],
        "sections": sections,
        "charts": [c for s in sections for c in (s.get("charts") or [])],
        "evidence": evidence,
        "claims": [c for s in sections for c in (s.get("claims") or [])],
        "glossary": [
            {"term": "等时圈", "definition": "以中心点为原点、步行耗时相同的等值线族（5/10/15/20 min）"},
            {"term": "服务盲区", "definition": "1km 范围内缺少菜市场/药店/小学任一必备设施的区域"},
            {"term": "IDW 插值", "definition": "反距离加权：以采样点耗时推演连续耗时场，不依赖底层路网"},
            {"term": "BD-09", "definition": "百度坐标系，本项目地图全域统一使用"},
        ],
        "methodology": {
            "window": "单次体检",
            "note": f"data_origin={lc.get('data_origin')} · interpolation={(lc.get('sampling') or {}).get('interpolation')} · scene_key={scene_key}",
        },
        "living_circle": lc,
    }
    return report