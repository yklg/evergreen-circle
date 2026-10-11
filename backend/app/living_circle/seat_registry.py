"""生活圈专家**席位注册表** —— 「谁天生该干哪一步」的唯一出口。

## 为什么必须有这张表

这张表存在之前，同一个事实在仓里散着 **9 份**手抄，且互相矛盾：

1. `pipeline/lc_team.py` 的 `_FALLBACK_SEATS`（10 席 + 理由文案）
2. `pipeline/diagnosis_templates.py` 里 8 处内联席位 id（章节署名）
3. 同文件 `build_evidence` 里 3 处 `collected_by` **姓名**字面量（现已收成本表 `artifact_seat`，`nar-5` 起发 id）
4. 同文件 `assemble_report` 里**另一份 13 人**保底名单（与 1 的 10 人不同）
5. 同文件理由缺失时的兜底句子
6. `pipeline/living_circle.py` 里 5 处 SSE `collected_by` 席位 id
7. `scripts/normalize_report_signatures.py` 的 `SECTION_SEAT`
8. `tests/test_expert_signature_derivation.py` 里同一张表的第二次抄写
9. 前端演示夹具 `eventFlow.json` 里每个 stage 的席位（2026-10-11 已收编：实测 7 个 stage 里
   5 个与 `STAGE_SEAT` 不符 ⇒ 按本表现场派生重写了那 12 处，并由
   `tests/test_lc_seat_registry_single_source.py::test_demo_event_flow_stage_owners_match_the_registry`
   钉住逐位相等）

⇒ 只要没有唯一出口，"把归属补上"这件事就只能变成**第 10 份手抄**。所以本表先落地，
再谈事件归属（`pipeline/living_circle.py` 的 `_progress`）与报告署名。

## 三条边界（写在这里，别靠猜）

- **只服务生活圈**。目的地调研域若将来也要过程可见，届时再抽公共层 —— 现在抽是过早抽象
  （两域席位语义完全不同，共用一张表只会变成两个 if）。
- **本模块绝不 import `app.core.pipeline.*`**。若为了断言键集去 import `living_circle.STAGES`，
  就成了 pipeline→registry→pipeline 的环，并撞 `scripts/check_guard_construction.py` 的
  G-5「pipeline 无上层回握」。所有"键集相等"判据一律落在 `tests/`，那里可以同时 import 两侧。
- **值必须与名册互指**。每个 `Seat.role_keyword` 是该席位 `role_title` **中文段**（`_expert()`
  按 `" / "` 切首段）必须包含的子串；漂移由 `tests/test_lc_seat_registry_consistency.py` 判红。
  只比中文段：整串匹配会让"改英文人设"误红、"改中文段"漏红。

## 两张保底名单是**故意**分开的

`FALLBACK_TEAM`（10 席，编排期：LLM 选队失败时用它）与 `TEAM_FALLBACK`（13 人，装配期：
载荷里根本没有 `team` 时用来填 `report.dispatch`）**不是同一件事的两份拷贝** —— 成员、数量、
用途都不同。合并它们会改变 `report.dispatch` 的字节，即触发报告代次升级；要合请先按
`docs/ARCHITECTURE.md` 的换代流程立项，别在这里顺手删。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Seat:
    """一个席位及其在本域里的职责描述。`seat_id` 是唯一身份，其余都是它的注释。"""

    seat_id: str
    duty: str           # 指派理由文案：编排期保底队用它，横幅 tooltip 也用它
    role_keyword: str   # 名册 role_title 中文段必须含它（漂移守卫的输入）


# ── 编排期保底队（决策层 2 ＋ 四领域顾问 ＋ 四方法专家）────────────────
# 逐字搬自 lc_team._FALLBACK_SEATS，顺序即交付顺序（决策层在前）。
# 刻意**不按设施类别裁剪**：原先那张「类别→顾问」映射表依赖从未被传的
# `facility_categories` 形参，且组队排在 POI 采集之前（那时类别还没确定）
# ⇒ 那条分支线上永远走不到，只有测试在跑；连同席位错位一起删掉了。
FALLBACK_TEAM: Tuple[Seat, ...] = (
    Seat("L3-001", "统筹体检全流程、统一指标口径并终审签发", "总检"),
    Seat("L3-002", "把控设施覆盖与评分建模的逻辑严谨性", "规划分析师"),
    Seat("L2-001", "负责医疗类设施的配置密度与就医可达性评估", "医疗"),
    Seat("L2-002", "负责教育类设施的学位与就近入学情况评估", "教育"),
    Seat("L2-003", "负责养老与托育设施的配置评估", "养老"),
    Seat("L2-004", "负责菜市场与商业配套的覆盖评估", "商业配套"),
    Seat("L1-025", "负责中心点定位与坐标解析", "空间定位"),
    Seat("L1-030", "负责设施点位检索与核验", "核验"),
    Seat("L1-027", "负责步行耗时测时与可达性测算", "测算"),
    Seat("L1-032", "负责四维体检评分计算与建模", "评分建模"),
)

# ── 装配期兜底名单（载荷里没有 team 时填 report.dispatch）──────────────
# 与上面的 10 席**不同**：多出的 L3-003/L2-008/L1-001/L1-004/L1-005/L1-008
# 是"每章至少有一位可署名的人"的覆盖需要，不是编排决策。
TEAM_FALLBACK: Tuple[str, ...] = (
    "L3-001", "L3-002", "L3-003", "L2-001", "L2-002", "L2-003",
    "L2-004", "L2-005", "L2-008", "L1-001", "L1-004", "L1-005", "L1-008",
)

# ── stage → 负责席位（SSE 进度帧的归属）───────────────────────────────
# 键集必须与 `pipeline/living_circle.py` 的 STAGES 相等；那条判据在
# tests/test_lc_seat_registry_single_source.py（本模块不得 import pipeline）。
# report/audit 两档的出处是**职责**而非既有文案：audit 那一步代码真做的是
# 几何体检 + 形状闸门 + 落库，属质检闸门，不是总检签发。
STAGE_SEAT: Dict[str, str] = {
    "intake": "L1-025",     # 中心点定位与坐标解析
    "plan": "L3-001",       # 统筹与组建专家队（名册原文；曾误挂 L3-002）
    "measure": "L1-027",    # 步行耗时测时
    "collect": "L1-030",    # 设施点位检索与核验
    "diagnose": "L1-032",   # 四维评分建模
    "report": "L2-008",     # 按标准装配章节
    "audit": "L3-003",      # 质检闸门与落库
}

# ── 报告章节 → 署名席位 ──────────────────────────────────────────────
# `overview` 不产 claims ⇒ 不登记（登记了反而让"带署名的章 ⊆ 本表"那条行为判据空转）。
# 曾同时存在于 normalize_report_signatures.py 与 test_expert_signature_derivation.py，
# 两份逐字相同 —— 现在两处都 import 这里。
SECTION_SEAT: Dict[str, str] = {
    "medical": "L2-001",
    "education": "L2-002",
    "elderly": "L2-003",
    "market": "L2-004",
    "isochrone": "L2-005",
    "blindspot": "L3-002",
    "conclusion": "L3-001",
}

# ── 设施类别 → 署名席位（第四条轴：**纯派生**，2026-10-11）────────────
# ⚠️ 它与文件头提到的那张**已被删掉**的「类别→顾问」映射表**不是一回事**，别读成复活：
# 被删的那张服务**编排期组队**，而组队排在 POI 采集之前（`facility_categories` 那时必定为空）
# ⇒ 那条分支线上永远走不到、只有测试在跑。这里服务的是**装配之后的署名上屏**：报告里每个类别
# 的读数归谁。类别在报告里是确定的，不存在"算的时候还不知道"的时序问题。
#
# 规则一句话：**类别的席位 = 它归口章节的署名席位**。⇒ 全部由 `SECTION_SEAT` 派生，
# 不新增第二份"谁负责什么"的手抄（那正是本文件存在的理由）。
CATEGORY_SECTION: Dict[str, str] = {
    # 8 类民生设施（键取自 `category_rule.CATEGORY_RULES`）
    "market": "market",
    "medical": "medical",
    "education": "education",
    "elderly": "elderly",
    "shopping": "market",      # 购物与菜市同章（`SECTION_SEAT["market"]` 的章名就是"菜市与购物"）
    # 三要素里的另外两类（`market` 已在上面）：按**设施归属**进章，不按名字里的字猜
    "pharmacy": "medical",     # 药店：它的 POI 规则就挂在医疗章的必查项里（`category_rule` 那份表）
    "primary": "education",
    # 没有专章的三类：报告里唯一逐条说出它们的地方是盲区与逐格台账
    # ⇒ 归写那一段的人（`blindspot`），而不是硬塞给结论章
    "finance": "blindspot",
    "recreation": "blindspot",
    "service": "blindspot",
}

CATEGORY_SEAT: Dict[str, str] = {c: SECTION_SEAT[s] for c, s in CATEGORY_SECTION.items()}

# ── 证据产物 → 采集席位 ──────────────────────────────────────────────
# 两个消费空间**已收成一个**（2026-10-11 挂账 A2 结案，`nar-5`）：SSE 与报告载荷的
# `collected_by` 现在都发这里的席位 id，`diagnosis_templates.py` 那个把 id 转成姓名的派生
# helper 已随之删除。这一位屏上零消费者（前端渲染读的是 claim 姓名与 `experts` 名单），
# 所以统一形状不改变任何读数 —— 判据 =
# `test_expert_signature_derivation.py::test_evidence_collected_by_is_a_seat_in_its_own_roster`。
ARTIFACT_SEAT: Dict[str, str] = {
    "measure": "L2-005",     # 采样点测时
    "collect": "L2-004",     # 设施 POI 检索
    "blindspot": "L3-002",   # 盲区点位扫描
}


def signature_seats() -> Tuple[str, ...]:
    """报告正文里**会被署名**的全部席位（章节 + 证据产物），按注册表声明序去重。

    为什么要这一颗：`assemble_report` 原先只在载荷不带 team 时才用 `TEAM_FALLBACK`（13 人，
    多出几位的目的正是"每章至少有一位可署名的人"）。载荷自带 team 时它照用不校验 ⇒
    实测两份样区的 team 都没有 `L3-002`，而盲区章席位登记的恰是 `L3-002` ⇒ 报告把盲区章
    与那条盲区证据署给了一个**不在自己名册里**的人（`kaili-ev2` 与真报告 `lc-91d1f091` 各 2 处）。
    现在装配期按这张派生表补齐覆盖，判据 = `test_report_signatures_never_escape_its_own_roster`。

    顺序即语义：先章节后证据产物，装配期按此序追加，**不许**在这里手写成员名单
    （手写＝第三份席位表，正是本注册表要消灭的那族病）。
    """
    out: List[str] = []
    for seat in (*SECTION_SEAT.values(), *ARTIFACT_SEAT.values()):
        if seat not in out:
            out.append(seat)
    return tuple(out)


def stage_owner(stage: str) -> Optional[str]:
    """某 stage 的负责席位；未登记的 stage 返回 None（**不抛**）。

    SSE 中途抛 KeyError 会打断一次真跑，而"新增 stage 忘登记"该红的是测试
    （键集闭合判据），不是用户的体检任务。返回 None ⇒ 该条进度帧不带 `expert`
    键，前端按"缺席即不印"处理。
    """
    return STAGE_SEAT.get(stage)


def section_seat(section_id: str) -> Optional[str]:
    """某报告章节的署名席位；未登记（如 overview）返回 None。"""
    return SECTION_SEAT.get(section_id)


def artifact_seat(artifact: str) -> str:
    """某类证据产物的采集席位。查不到即抛 —— 调用点全在生产主链上，
    静默发一个悬空 id 会让报告署名退化成裸 id（`_expert` 的回落路径）。"""
    return ARTIFACT_SEAT[artifact]
