"""生活圈专家**席位注册表** —— 「谁天生该干哪一步」的唯一出口。

## 为什么必须有这张表

这张表存在之前，同一个事实在仓里散着 **9 份**手抄，且互相矛盾：

1. `pipeline/lc_team.py` 的 `_FALLBACK_SEATS`（10 席 + 理由文案）
2. `pipeline/diagnosis_templates.py` 里 8 处内联席位 id（章节署名）
3. 同文件 `build_evidence` 里 3 处 `collected_by` **姓名**字面量
4. 同文件 `assemble_report` 里**另一份 13 人**保底名单（与 1 的 10 人不同）
5. 同文件理由缺失时的兜底句子
6. `pipeline/living_circle.py` 里 5 处 SSE `collected_by` 席位 id
7. `scripts/normalize_report_signatures.py` 的 `SECTION_SEAT`
8. `tests/test_expert_signature_derivation.py` 里同一张表的第二次抄写
9. 前端演示夹具 `eventFlow.json` 里每个 stage 的席位

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

# ── 证据产物 → 采集席位 ──────────────────────────────────────────────
# ⚠️ 目前**两个消费空间并存**：SSE 的 `collected_by` 发这里的**席位 id**，
# 报告载荷的 `collected_by` 发由它派生的**姓名**。统一成 id 属 A2（要付一次
# 报告代次升级 + 金标重取，屏上零变化），本批只把姓名改成派生、不再硬写。
ARTIFACT_SEAT: Dict[str, str] = {
    "measure": "L2-005",     # 采样点测时
    "collect": "L2-004",     # 设施 POI 检索
    "blindspot": "L3-002",   # 盲区点位扫描
}


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
