/**
 * F3 · 生活圈体检「完整 Report」mock 构造器。
 *
 * 从 F0 fixture（LivingCircleReport）用规则化模板生成一张**完整的 Report**：
 *  - 挂载 `report_type: 'living_circle'` + `living_circle` 原始数据（A1 渲染适配器的判据）
 *  - 章节报告（医疗/教育/购物/养老/可达性/盲区/结论）——逐章由规划专家署名（D4 专家当诊断主角）
 *  - evidence/claims/charts 全链路齐全（延续「每个结论都有出处」卖点，出处=POI/测时/判定记录）
 *
 * M 阶段后端按同一契约产出（pipeline/living_circle.py + diagnosis_templates.py），
 * 前端零改动；本文件只在 VITE_USE_MOCK=1 时被消费。
 */
import type {
  ChartSpec,
  Claim,
  Evidence,
  FacilityCategoryStat,
  LifeCircleRecord,
  LivingCircleReport,
  Report,
  ReportSection,
} from '../types'
import { SAMPLE_COMMUNITIES } from './livingCircleMock'
import {
  lcLocPrefix,
  poiDedupeRuleLabel,
  poiMetricLabel,
  samplingReach,
  scoreGrade,
  triadClaimText,
  triadOverviewText,
  triadSchoolParaText,
  triadTakeawayText,
} from '../lib/livingCircle'

/** D4 · 专家署名表（与 backend/app/data/experts.json 及 api 副本的 id 对齐；M2 换血后仅文案微调） */
export const LC_EXPERT: Record<string, { name: string; role: string }> = {
  'L3-001': { name: '温叙白', role: '社区体检总检' },
  'L3-002': { name: '许映川', role: '首席规划分析师' },
  'L3-003': { name: '裴砚秋', role: '质检总监' },
  'L2-001': { name: '谷穗安', role: '基层医疗配置顾问' },
  'L2-002': { name: '郑启才', role: '基础教育设施规划师' },
  'L2-003': { name: '叶知暖', role: '养老托育关怀顾问' },
  'L2-004': { name: '苏堤春', role: '菜市与商业配套分析师' },
  'L2-005': { name: '路遥川', role: '慢行可达性分析师' },
  'L2-008': { name: '方守正', role: '生活圈标准专家' },
  'L1-001': { name: '车满仓', role: '农贸市场顾问' },
  'L1-004': { name: '秦济世', role: '社区药房规划师' },
  'L1-005': { name: '周启蒙', role: '小学校区规划师' },
  'L1-008': { name: '温鹤年', role: '机构养老顾问' },
}
const EXP = LC_EXPERT

/** 历史快照别名：早期轮次的记录页复用最近一期体检报告阅读器 */
const LC_ALIAS: Record<string, string> = {
  'lc-kaili-r1': 'lc-kaili',
  'lc-beijing-jinsong-r1': 'lc-beijing-jinsong',
}

/** 报告 id：「lc-」+ 样例 id（与 LifeCirclePage 入口一致） */
export const LC_REPORT_ID = (sceneId: string) => `lc-${sceneId}`

function cat(report: LivingCircleReport, key: string): FacilityCategoryStat | undefined {
  return report.poi.categories.find((c) => c.category === key)
}

/** `cov-1`：覆盖度那句必须自己交代**分子是什么** —— 只许读 payload 的 `required_in_circle`。
 *  键缺席 = 这份快照冻结在分子换代前 ⇒ 返回空串（照点数说），**不得**挂门槛项文案。
 *  ⚠️ 满分线（`ideal_circle`）不在 payload 里 ⇒ 前端这几句**不写「≥3 家」**；那个数只有后端
 *  `diagnosis_templates.py`（直接读 `CATEGORY_RULES`）有权印出来。写在这里就是第二份尺。 */
function covBasisText(c: FacilityCategoryStat | undefined): string {
  const req = c?.required_in_circle
  return req == null ? '' : `（其中计入覆盖度分子的是门槛项 ${req} 处）`
}

/* 「门槛项不足」这句话有**六种**真成因会让它失真，六种都只活在载荷里 ⇒ 各配一个子句上屏
   （片 R23-A·乙 接前两种，R23-B1 接第三种，R23-B3 接第四种，R23-D 接第五、六种）：
   ①词因预算**一次都没发起**（`evidence_starved_terms`）②词发了、**我们没接着翻完**
   （`evidence_truncated_terms`）③这一类**整轮没跑过扩词**，额度在别的类上花完了
   （`evidence_expansion_unfunded_categories`，存的是裸类别名 —— 那一轮连词名都还没产生）
   ④这一类**扩过词、却在额度见底时还没达标**（`evidence_expansion_out_of_budget_categories`）。
   ③④ 分名分职：③是排程没摊到、④是摊到了但额度太薄，合并就看不出该怪谁。
   ⑤词**接口自称还有货却断了页**（`evidence_capped_terms`）⑥词**请求没成**（`evidence_failed_terms`）。
   ⑤⑥ 在 R23-D 之前混在②里 ⇒ 对⑥「发了但没查全」是假话、对⑤是归责错位（读者会以为加预算能拿到）。
   ⚠️ 编号按**落地顺序**排，屏上顺序按**归责由近及远**排（①②⑤⑥③④）—— 两套序不同是有意的。
   ⚠️ 曾经还有**第七种**：采集按点数收手、分子按门槛项算 ⇒ 那句"停止线按点数算"的交代由
      R23-B2 随换单位一起撤掉（留着就是假话），两端同批，见 `poi_collector._at_target`。
   ⚠️ 下面**九个**常量与后端 `diagnosis_templates` 的同名件**逐字同源**，拼装规则也只许一份：
      `GAP_LEAD + 子句…(GAP_JOIN)… + GAP_TAIL`（镜像判据见 `test_fixture_mirror.py`）。
      「本次有 N 个…」写在**子句里**而不是前缀里，因为第③④种不以计数开头。 */
const GAP_LEAD = '另需交代：'
const GAP_STARVED = '本次有 {n} 个{label}类检索词因预算未发起（{terms}）'
const GAP_TRUNCATED = '本次有 {n} 个{label}类检索词发了但没查全（{terms}）'
// ⚠️ "一次都没扩成"不是笔误：一类首次扩词就撞接口失败且额度归零时它**发起过**，
//    写"一个词都没发起"会是假话（后端 `diagnosis_templates` 同注，计划 §14⑤.3）
const GAP_UNFUNDED = '本轮没有额度为这一类扩词（一次都没扩成）'
const GAP_OUT_OF_BUDGET = '这一类的扩词在到达标线之前因额度见底中断（扩过词，不是查够了）'
// R23-D：从②里移出来的两种归责。措辞里不许出现"我们没翻"或"再查就有"（后端同注）
const GAP_CAPPED = '本次有 {n} 个{label}类检索词接口自称还有货却断了页（{terms}）'
const GAP_FAILED = '本次有 {n} 个{label}类检索词请求没成（{terms}）'
const GAP_JOIN = '；'
const GAP_TAIL = ' ⇒ 这一类证据面不完整，上面那个覆盖度的分子里含我们没查过或没查全的部分。'

/** 本类「没查过 / 没查全 / 它不给 / 没查成 / 整轮没扩词 / 扩到一半没钱」那半句；
 *  无话可说时返回**空串**（不印，也不硬编「0 个」）。
 *  前四个键是 `{类}:{词}` 形状的**全类混合表** ⇒ 必须按前缀筛本类；后两个是**类别表**，按类名整等判定。
 *  键缺席（换代前冻结的快照）与空表都算无话可说：前者是"不知道"、后者是"查全了"。 */
function evidenceGapNote(
  caliber: LivingCircleReport['caliber'],
  category: string,
  label: string,
): string {
  const clauses: string[] = []
  for (const [tpl, key] of [
    [GAP_STARVED, 'evidence_starved_terms'],
    [GAP_TRUNCATED, 'evidence_truncated_terms'],
    [GAP_CAPPED, 'evidence_capped_terms'],
    [GAP_FAILED, 'evidence_failed_terms'],
  ] as const) {
    const raw = caliber?.[key]
    if (!Array.isArray(raw)) continue
    const mine = raw.filter((t) => typeof t === 'string' && t.startsWith(`${category}:`))
    if (mine.length) clauses.push(tpl.replace('{n}', `${mine.length}`).replace('{label}', label).replace('{terms}', mine.join('、')))
  }
  for (const [tpl, key] of [
    [GAP_UNFUNDED, 'evidence_expansion_unfunded_categories'],
    [GAP_OUT_OF_BUDGET, 'evidence_expansion_out_of_budget_categories'],
  ] as const) {
    const hit = caliber?.[key]
    if (Array.isArray(hit) && hit.includes(category)) clauses.push(tpl)
  }
  return clauses.length ? GAP_LEAD + clauses.join(GAP_JOIN) + GAP_TAIL : ''
}

/** 医疗节那句「达标 / 存在缺口」必须自证它判的是哪把尺（§十九 用户拍板"维持按分数 75%"换来的
 *  措辞义务）：达标 = 覆盖度 ≥75%，**不等于**"医疗不缺了"；存在缺口 = 门槛项未计满，
 *  **不等于**"圈内没有医疗设施"。两个分支各说各的真话，不许共用一句。
 *  名单走 payload 的 `scored_as`（后端 `sub_kind_rule_labels` 发的规则名单）。
 *  「没发起 / 没查全 / 整轮没扩词」那一句**只挂缺口分支**：达标说的是分子已计满，证据面不完整不会让它变成假话。 */
function medCoverageSentence(m: FacilityCategoryStat | undefined, caliber: LivingCircleReport['caliber']): string {
  const cov = pct(m?.coverage ?? 0)
  const req = m?.required_in_circle
  if (req == null) return `覆盖度 ${cov} 按圈内点数计（这份快照出自门槛项口径之前）。`
  const named = m?.scored_as?.length ? `（${m.scored_as.join(' / ')}）` : ''
  const rest = (m?.in_circle ?? 0) - req
  const ok = (m?.coverage ?? 0) >= 0.75
  return `其中计入覆盖度分子的是基层医疗门槛项 ${req} 处${named}，另有 ${rest} 处不计入分子（含诊所等不计分形状与判不准的存疑项）。覆盖度 ${cov} ⇒ 本节${
    ok
      ? '写「达标」—— 这只指该覆盖度 ≥75%（门槛项已计满），不等于「医疗不缺了」。'
      : `写「存在缺口」—— 这只指基层医疗门槛项未计满（覆盖度 <75%），不表示圈内没有医疗设施（圈内仍有 ${m?.in_circle ?? 0} 处）。${evidenceGapNote(caliber, 'medical', m?.label ?? '医疗')}`
  }`
}

/** 教育节那句：把「圈内 15 处」与「覆盖度 33%」拆成两个口径各自的数 —— 旧写法把两句并排，
 *  读者按点数复算得 15÷3=100%，只能认定数据对不上（第 21 轮 P1-2 的现场形态）。
 *  「没发起 / 没查全 / 整轮没扩词」同样只在 <75% 时挂（本节没有分支句，闸门得显式写在这里）。 */
function eduCoverageSentence(e: FacilityCategoryStat | undefined, caliber: LivingCircleReport['caliber']): string {
  const cov = pct(e?.coverage ?? 0)
  const req = e?.required_in_circle
  if (req == null) return `覆盖度 ${cov} 按圈内点数计（这份快照出自门槛项口径之前）；`
  const named = e?.scored_as?.length ? `「${e.scored_as.join(' / ')}」` : '门槛项'
  const gap = (e?.coverage ?? 0) >= 0.75 ? '' : evidenceGapNote(caliber, 'education', e?.label ?? '教育')
  return `但覆盖度的分子只取${named} ${req} 处，故为 ${cov} —— 「圈内 ${e?.in_circle ?? 0} 处」与「覆盖度 ${cov}」是两个口径各自的数，不是同一个数的两次说法；${gap}`
}

function fmtMin(m: number | null): string {
  return m == null ? '—' : `${m}min`
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

/** 依评分档位给一句话总评（规则模板 → M 阶段 LLM 解读的降级同构） */
function overviewNote(r: LivingCircleReport): string {
  const grade = scoreGrade(r.scores.total)
  // 分档走唯一口径（timed≠可达）。mock 与真报告必须同源，否则演示态与实时态文案会打架。
  const reach = samplingReach(r)
  const area = r.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0
  const triadNote = triadOverviewText(r.scores.triads)
  return `本样区综合评分 ${r.scores.total}（${grade.label}），15 分钟步行可达圈约 ${area.toFixed(2)} km²，${reach.inReach}/${reach.total} 个采样点圈内可达（已测时 ${reach.timed}）；设施 ${poiMetricLabel(r)}。${triadNote}，共识别 ${r.blindspots.length} 处服务盲区。`
}

function charter(ids: string[]): { id: string; reason: string }[] {
  return ids.map((id) => ({
    id,
    reason: `${EXP[id]?.role ?? '规划专家'}负责本节评审与结论签发（D4 专家出诊断）`,
  }))
}

/* ── 章节构造（每组数据 → 段落/结论/图表均可从 fixture 数据推出，保证双样例一致口径） ── */

function secMedical(r: LivingCircleReport): ReportSection {
  const m = cat(r, 'medical')
  const ph = cat(r, 'pharmacy') ?? m
  const triad = r.scores.triads.find((t) => t.facility === '药店')
  const claims: Claim[] = [
    {
      claim_id: `c-${r.scene.name}-medical-1`,
      text: `医疗设施圈内 ${m ? `${m.in_circle}/${m.total}` : '—'} 处${covBasisText(m)}，最近药房 ${fmtMin(triad?.nearest_minutes ?? ph?.min_minutes ?? null)}，${m && m.coverage >= 0.75 ? '基本满足 15 分钟就医购药需求' : '存在明显配置缺口'}`,
      field: 'coverage',
      evidence_ids: [`ev-${r.scene.name}-poi-medical`],
      confidence: m && m.coverage >= 0.75 ? 'high' : 'medium',
      cross_validated: true,
      author: EXP['L2-001'].name,
    },
  ]
  return {
    id: 'medical',
    title: '医疗配置',
    level: 2,
    key_takeaway: `圈内医疗设施 ${m ? `${m.in_circle}/${m.total}` : '—'} 处，最近 ${fmtMin(m?.min_minutes ?? null)}；社区医院/诊所/药店三类中${(ph?.nearest_name || m?.nearest_name) ? `最近为「${ph?.nearest_name ?? m?.nearest_name}」` : '尚无近端设施'}`,
    paragraphs: [
      `对研究范围内医疗类 POI 按 ${m?.total ?? 0} 处做${poiDedupeRuleLabel(r)}，可达区内 ${m?.in_circle ?? 0} 处；${medCoverageSentence(m, r.caliber)}`,
      `最近设施「${m?.nearest_name ?? '—'}」步行约 ${fmtMin(m?.min_minutes ?? null)}。药店作为赛题盲区三要素之一：${triadTakeawayText(triad)}。`,
    ],
    claims,
    charts: [
      {
        chart_id: `chart-${r.scene.name}-medical`,
        type: 'bar',
        title: '医疗类设施圈内/圈外分布',
        option: medicalBarChart(m),
      },
    ],
    source_evidence_ids: [`ev-${r.scene.name}-poi-medical`],
  }
}

function secEducation(r: LivingCircleReport): ReportSection {
  const e = cat(r, 'education')
  const triad = r.scores.triads.find((t) => t.facility === '小学')
  return {
    id: 'education',
    title: '教育设施',
    level: 2,
    key_takeaway: `教育类圈内 ${e ? `${e.in_circle}/${e.total}` : '—'} 处；小学为盲区三要素之一，${triadTakeawayText(triad)}`,
    paragraphs: [
      `教育设施统计范围含小学/中学/幼儿园，共检索 ${e?.total ?? 0} 处，可达区内 ${e?.in_circle ?? 0} 处；${eduCoverageSentence(e, r.caliber)}最近设施「${e?.nearest_name ?? '—'}」${fmtMin(e?.min_minutes ?? null)}。`,
      `就学通勤视角：小学接送是生活圈体检的高频痛点，本样区${triadSchoolParaText(triad)}。`,
    ],
    claims: [
      {
        claim_id: `c-${r.scene.name}-education-1`,
        text: `教育设施${triadClaimText(triad)}（这一句判的是小学三要素）；覆盖度 ${e?.coverage != null ? pct(e.coverage) : '—'}${e?.required_in_circle != null ? `（按门槛项 ${e.required_in_circle} 处 ÷ 满分线，圈内共 ${e.in_circle} 处）` : ''} ⇒ 置信度 ${(e?.coverage ?? 0) >= 0.75 ? 'high' : 'medium'}（这一句判的是那个覆盖度是否 ≥75%，与上面那句不是同一把尺）`,
        field: 'coverage',
        evidence_ids: [`ev-${r.scene.name}-poi-education`],
        confidence: (e?.coverage ?? 0) >= 0.75 ? 'high' : 'medium',
        cross_validated: true,
        author: EXP['L2-002'].name,
      },
    ],
    source_evidence_ids: [`ev-${r.scene.name}-poi-education`],
  }
}

function secMarket(r: LivingCircleReport): ReportSection {
  const mk = cat(r, 'market')
  const sp = cat(r, 'shopping')
  const triad = r.scores.triads.find((t) => t.facility === '菜市场')
  return {
    id: 'market',
    title: '菜市与购物',
    level: 2,
    key_takeaway: `菜市场 ${mk ? `${mk.in_circle}/${mk.total}` : '—'} 处圈内；购物(超市/便利店/商场) ${sp ? `${sp.in_circle}/${sp.total}` : '—'} 处圈内；菜市场三要素${triadTakeawayText(triad)}`,
    paragraphs: [
      `以「菜市场/生鲜」与「超市/便利店/综合商场」两组关键词独立检索并做${poiDedupeRuleLabel(r)}：菜市场 ${mk?.total ?? 0} 处（圈内 ${mk?.in_circle ?? 0}，覆盖 ${pct(mk?.coverage ?? 0)}），购物 ${sp?.total ?? 0} 处（圈内 ${sp?.in_circle ?? 0}，覆盖 ${pct(sp?.coverage ?? 0)}）。`,
      // 两个菜市场数字并存是刻意的：类目统计按归并后的设施数，盲区三要素按未归并的坐标集
      // （1km 硬判宁多勿少）。不写出来就会被读成口径打架。
      `注：本处菜市场数为**设施统计口径**；盲区判定另用未归并的三要素坐标集（菜市场/药店/小学是 1km 硬判，宁多勿少），两个数不一致属预期。`,
      // 尾部原来挂着一段"不可达就说缺席"的三元式 —— 读的是可达尺的 `covered` 却写"缺席"，
      // 与本章 key_takeaway 会打脸；三要素的结论一律交回 `triadTakeawayText` 等渲染器说。
      `每日采买的便利度是居民感知最强的民生指标，本样区最近菜市场「${mk?.nearest_name ?? '—'}」${fmtMin(mk?.min_minutes ?? null)}。`,
    ],
    claims: [
      {
        claim_id: `c-${r.scene.name}-market-1`,
        text: `菜市场三要素${triadClaimText(triad)}；购物配套覆盖 ${sp?.coverage != null ? pct(sp.coverage) : '—'}`,
        field: 'coverage',
        evidence_ids: [`ev-${r.scene.name}-poi-market`],
        confidence: (mk?.coverage ?? 0) >= 0.75 ? 'high' : 'medium',
        cross_validated: true,
        author: EXP['L2-004'].name,
      },
    ],
    source_evidence_ids: [`ev-${r.scene.name}-poi-market`],
  }
}

// 养老那一维的「未检出」措辞（#87 丙档）：与后端 `diagnosis_templates._LC_ELDERLY_*` **逐字同一份**，
// 镜像判据 = `backend/tests/test_fixture_mirror.py::test_elderly_undetected_notes_are_one_text_on_both_ends`
// （比名字集合 + 比值 + 比使用处数）。改一边忘另一边 = 同一个事实两种说法，今天没有任何东西会红。
// ⚠️ 声明形状是判据的一部分：单行 + 单引号字面量，抽不到就报错（不许改成多行或双引号）。
const LC_ELDERLY_UNDETECTED_TAIL = '，现役检索词表未检出（读作“未检出”，不等于“不存在”）'
const LC_ELDERLY_UNDETECTED_CAUSE = '这一维的 0 出在检索面而非资源面：现役名称词表已含机构级与社区级两类命名，圈内仍零命中只能说明“按这张词表没查到”。若本地设施的命名形状与词表不同形，漏的就仍在检索面 —— 所以本维读作“未检出”，下一步是先按本地命名复核词表、再谈补建。'
const LC_ELDERLY_UNDETECTED_CLAIM = '未检出（圈内 0 处，按现役名称词表检索无命中）'
const LC_ELDERLY_UNDETECTED_ADVICE = '· 养老配置未检出（覆盖 0%）：先按本地实际命名复核检索词表，复核后仍零命中再提补建日间照料中心/助老驿站，优先级 P0。'

function secElderly(r: LivingCircleReport): ReportSection {
  const el = cat(r, 'elderly')
  const rec = cat(r, 'recreation')
  const missing = !el || el.in_circle === 0
  return {
    id: 'elderly',
    title: '养老配置',
    level: 2,
    key_takeaway: `养老(含社区级命名)圈内 ${el ? `${el.in_circle}/${el.total}` : '0/0'} 处${missing ? LC_ELDERLY_UNDETECTED_TAIL : ''}；文体类 ${rec ? `${rec.in_circle}/${rec.total}` : '—'} 处`,
    paragraphs: [
      `养老托育类设施共 ${el?.total ?? 0} 处，可达区内 ${el?.in_circle ?? 0} 处，覆盖度 ${pct(el?.coverage ?? 0)}。${missing ? LC_ELDERLY_UNDETECTED_CAUSE : `最近「${el?.nearest_name}」${fmtMin(el?.min_minutes ?? null)}。`}`,
      `文体(公园/健身) ${rec?.total ?? 0} 处（圈内 ${rec?.in_circle ?? 0}），作为全龄友好配套的补充观测项${rec?.min_minutes != null ? `，最近「${rec.nearest_name}」${fmtMin(rec.min_minutes)}` : ''}。`,
    ],
    claims: [
      {
        claim_id: `c-${r.scene.name}-elderly-1`,
        text: `养老配置${missing ? LC_ELDERLY_UNDETECTED_CLAIM : `覆盖 ${pct(el?.coverage ?? 0)}`}，适老化优先整改`,
        field: 'coverage',
        evidence_ids: [`ev-${r.scene.name}-poi-elderly`],
        confidence: missing ? 'high' : 'medium',
        cross_validated: false,
        author: EXP['L2-003'].name,
      },
    ],
    source_evidence_ids: [`ev-${r.scene.name}-poi-elderly`],
  }
}

function secIsochrone(r: LivingCircleReport): ReportSection {
  const areas = r.isochrones.map((z) => ({ minutes: z.minutes, area: z.area_km2 }))
  const reach = samplingReach(r)
  return {
    id: 'isochrone',
    title: '可达性与等时圈',
    level: 2,
    key_takeaway: `5/10/15/20 分钟步行等时圈面积 ${areas.map((a) => a.area.toFixed(2)).join(' / ')} km²；采样 ${reach.total} 点，圈内可达 ${reach.inReach}（已测时 ${reach.timed}）；方式：${r.sampling.interpolation === 'idw' ? 'IDW 反距离加权插值' : '圆形近似（演示数据）'}`,
    paragraphs: [
      `以中心点为原点按 400m 粗网格 + 15min 边界带 150m 加密采样（共 ${r.sampling.points.length} 个点），调用步行测时接口后对耗时场做${r.sampling.interpolation === 'idw' ? ' IDW 反距离加权插值，提取 5/10/15/20 分钟等值线族' : ' 圆形近似（fixture 演示阶段；M5 覆写为真实路网等时圈）'}。`,
      `「不取底层路网、仅基于分布点位测时推导连通区域」是赛题鼓励的 30% 评分项：本流程${r.sampling.is_scattered ? '采用散点扇形双层采样，' : ''}全程未获取路网数据，并通过抽样回验控制误差。`,
    ],
    claims: [
      {
        claim_id: `c-${r.scene.name}-isochrone-1`,
        text: `15 分钟步行可达圈约 ${(r.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0).toFixed(2)} km²，${r.blindspots.length} 处盲区均位于圈内设施覆盖空洞`,
        field: 'reachability',
        evidence_ids: [`ev-${r.scene.name}-measure`],
        confidence: 'high',
        cross_validated: true,
        author: EXP['L2-005'].name,
      },
    ],
    charts: [isochroneChart(areas)],
    source_evidence_ids: [`ev-${r.scene.name}-measure`],
  }
}

/**
 * 逐格台账句（演示态侧）—— 与后端 `diagnosis_templates._ledger_sentence` **逐字同一份**，
 * 由 `backend/tests/test_fixture_mirror.py` 钉住。只读三张位，绝不重算不对称判盲规则。
 * 无台账 / 验形不过 ⇒ 空串（不印，也不印 0）：`ev-2` 之前的快照根本无从知道判了几格。
 */
export function ledgerSentence(r: LivingCircleReport): string {
  const led = (r.caliber as { cells_ledger?: Record<string, unknown> } | undefined)?.cells_ledger
  if (!led || typeof led !== 'object') return ''
  const n = led.n
  if (typeof n !== 'number' || n <= 0 || n % 2 === 0) return ''
  if (led.grid !== 'square' || led.schema_version !== 1) return ''
  const rowsOf = (key: string): string[] | null => {
    const v = led[key]
    if (!Array.isArray(v) || v.length !== n) return null
    for (const row of v) if (typeof row !== 'string' || row.length !== n) return null
    return v as string[]
  }
  const inside = rowsOf('inside'), blind = rowsOf('blind'), verdict = rowsOf('verdict'), capped = rowsOf('capped')
  if (!inside || !blind || !verdict || !capped) return ''
  const num = (key: string) => {
    const v = led[key]
    return typeof v === 'number' && v > 0 ? v : null
  }
  const step = num('step_m'), radius = num('radius_m'), scan = num('scan_m')
  if (step === null || radius === null || scan === null) return ''
  const bit = (rows: string[], i: number, j: number) => rows[i][j] === '1'
  let inCnt = 0, blindCnt = 0, clearCnt = 0, unknownCnt = 0, cappedCnt = 0
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      if (!bit(inside, i, j)) continue
      inCnt += 1
      if (bit(blind, i, j)) blindCnt += 1
      else if (bit(verdict, i, j)) clearCnt += 1
      else if (bit(capped, i, j)) cappedCnt += 1
      else unknownCnt += 1
    }
  }
  const judged = blindCnt + clearCnt
  return (
    `判定格阵 ${n}×${n}（格距 ${Math.round(step)}m、判定尺半径 ${Math.round(radius)}m）：` +
    `${inCnt} 格落在可达区内、其中 ${judged} 格出到结论` +
    `（判盲 ${blindCnt} 格、确认不盲 ${clearCnt} 格）；` +
    `余下 ${unknownCnt} 格未定（有类别没查全，属我们的取证缺口）、` +
    `${cappedCnt} 格判不动（接口能力封顶）—— 后两档与「不盲」不是一回事，` +
    '既不算进「出到结论」，也不合并成一句「没结论」。'
  )
}

function secBlindspot(r: LivingCircleReport): ReportSection {
  const rows = r.blindspots.map((b) => ({
    盲区编号: b.id.replace(/^bs-/, ''),
    中心点: `${b.center[0].toFixed(4)}, ${b.center[1].toFixed(4)}`,
    缺失设施: b.missing_facilities.join(' / '),
    最近设施: b.nearest[0]?.name ?? '—',
    最近距离: b.nearest[0] ? `${Math.round(b.nearest[0].distance_m)}m·${b.nearest[0].direction}` : '—',
  }))
  const claims: Claim[] = r.blindspots.map((b) => ({
    claim_id: `c-${r.scene.name}-bs-${b.id}`,
    text: `${b.id.replace(/^bs-/, '盲区 ')}：1km 内无 ${b.missing_facilities.join('、')}；最近「${b.nearest[0]?.name ?? '—'}」${b.nearest[0] ? `${Math.round(b.nearest[0].distance_m)}m（${b.nearest[0].direction}）` : ''}`,
    field: 'blindspot',
    evidence_ids: [`ev-${r.scene.name}-bs-${b.id}`],
    confidence: 'high',
    cross_validated: true,
    author: EXP['L3-002'].name,
  }))
  return {
    id: 'blindspot',
    title: '服务盲区诊断',
    level: 2,
    key_takeaway: r.blindspots.length
      ? `识别 ${r.blindspots.length} 处 1km 服务盲区${r.blindspots.some((b) => b.missing_facilities.includes('小学')) ? '，含小学缺口' : ''}；三要素缺位处列出最近设施的距离与方位供整改`
      : r.caliber?.cells_unknown
        ? `可判定范围内未发现 1km 服务盲区；网格扫描 ${r.caliber.cells_inside ?? '—'} 格中仅 ${r.caliber.cells_judged ?? '—'} 格可判定，其余 ${r.caliber.cells_unknown} 格因采集半径不足未判定，不能据此判定全圈无障碍`
        : '网格扫描全部完成判定，未发现 1km 服务盲区，三要素齐备',
    paragraphs: [
      `按赛题口径（1km 内无菜市场/药店/小学即判盲），以 ${
        r.blindspots.length ? `${r.blindspots.length} 处` : '网格扫描'
      } 盲区点位聚合为灰色区域多边形。`,
      ...(r.blindspots.length
        ? [
            '下表为各盲区的缺失要素与最近设施方位（供「最近距补点/加设流动服务」式整改参考）。',
          ]
        : []),
      // 台账段追加在口径句之后（与后端 `_sec_blindspot` 同一位置约定）；无台账则空串不追加。
      ...((() => { const s = ledgerSentence(r); return s ? [s] : [] })()),
    ],
    claims,
    highlights: [highlightItems(r).blindspot].filter((x): x is string => !!x),
    data_grid: {
      columns: ['盲区编号', '中心点', '缺失设施', '最近设施', '最近距离'],
      rows: rows.map((x) => ({ name: x['盲区编号'], value: x['最近设施'], metric: x['缺失设施'], source: `${x['中心点']} · ${x['最近距离']}`, source_url: 'fixture://blindspot' })),
    },
    source_evidence_ids: r.blindspots.map((b) => `ev-${r.scene.name}-bs-${b.id}`),
  }
}

function secConclusion(r: LivingCircleReport): ReportSection {
  const weak = [...r.scores.bars].sort((a, b) => a.value - b.value).slice(0, 2)
  const hints = buildSuggestions(r)
  return {
    id: 'conclusion',
    title: '体检结论与整改建议',
    level: 2,
    key_takeaway: `综合 ${r.scores.total} 分；短板项：${weak.map((w) => `${w.label}(${w.value})`).join('、') || '无明显短板'}`,
    paragraphs: [
      `本样区${r.blindspots.length ? '存在多处服务盲区，整改优先级如下：' : '设施覆盖整体均衡，建议保持既有配置并动态复检。'}`,
      ...hints,
      '提醒：以上结论基于演示数据（fixture · 圆形近似等时圈），正式结论以 M5 阶段真实路网测时为准。',
    ],
    claims: [
      {
        claim_id: `c-${r.scene.name}-conclusion-1`,
        text: `样区综合 ${r.scores.total} 分（${scoreGrade(r.scores.total).label}），首要整改方向：${hints[0]?.replace(/^·\s*/, '') ?? '持续监测'}`,
        field: 'conclusion',
        evidence_ids: r.blindspots.map((b) => `ev-${r.scene.name}-bs-${b.id}`),
        confidence: 'high',
        cross_validated: true,
        author: EXP['L3-001'].name,
      },
    ],
    highlights: [highlightItems(r).spread].filter((x): x is string => !!x),
    source_evidence_ids: r.blindspots.map((b) => `ev-${r.scene.name}-bs-${b.id}`),
  }
}

/** 规则化整改建议（盲区/养老缺口兜底） */
function buildSuggestions(r: LivingCircleReport): string[] {
  const out: string[] = []
  const missingFac = new Set<string>()
  for (const b of r.blindspots) b.missing_facilities.forEach((f) => missingFac.add(f))
  const byCategory: Record<string, string> = { '菜市场': '蔬菜便民车/移动菜市点位', '药店': '社区药柜+线上配送', '小学': '校车线路/学区统筹' }
  for (const f of missingFac) out.push(`· 盲区缺位「${f}」：建议${byCategory[f] ?? '补建/补充供给'}（参考最近设施 ${(r.blindspots[0]?.nearest.find((n) => n.facility)?.name ?? '—')} 方位）。`)
  const el = cat(r, 'elderly')
  if (el && el.in_circle === 0) out.push(LC_ELDERLY_UNDETECTED_ADVICE)
  if (out.length === 0) out.push('· 无显著整改项。')
  return out
}

/* ── 图表构造（ECharts option，契约内自由形态） ── */

function radarChart(r: LivingCircleReport): ChartSpec {
  const dims = r.scores.radar
  return {
    chart_id: `chart-${r.scene.name}-radar`,
    type: 'radar',
    title: '生活圈维度评分雷达',
    option: {
      tooltip: {},
      radar: {
        indicator: dims.map((d) => ({ name: d.dimension, max: 100 })),
        radius: '62%',
        splitArea: { areaStyle: { color: ['#f7faf7', '#eef3ee'] } },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              name: '评分',
              value: dims.map((d) => d.score),
              areaStyle: { opacity: 0.25, color: '#5F7B69' },
              lineStyle: { color: '#5F7B69' },
              itemStyle: { color: '#5F7B69' },
            },
          ],
        },
      ],
    },
  }
}

function coverageBarChart(r: LivingCircleReport): ChartSpec {
  return {
    chart_id: `chart-${r.scene.name}-coverage`,
    type: 'bar',
    title: '各设施类别覆盖度（%）',
    option: {
      tooltip: {},
      xAxis: { type: 'category', data: r.scores.bars.map((b) => b.label) },
      yAxis: { type: 'value', max: 100 },
      series: [
        {
          type: 'bar',
          data: r.scores.bars.map((b) => b.value),
          itemStyle: { color: '#5F7B69', borderRadius: [2, 2, 0, 0] },
          barWidth: '52%',
        },
      ],
    },
  }
}

function medicalBarChart(m: FacilityCategoryStat | undefined): Record<string, unknown> {
  return {
    tooltip: {},
    legend: { data: ['圈内', '圈外'] },
    xAxis: { type: 'category', data: ['社区医院/诊所/药店'] },
    yAxis: { type: 'value' },
    series: [
      { name: '圈内', type: 'bar', data: [m?.in_circle ?? 0], itemStyle: { color: '#5F7B69' }, barWidth: 30 },
      { name: '圈外', type: 'bar', data: [(m?.total ?? 0) - (m?.in_circle ?? 0)], itemStyle: { color: '#cad3cd' }, barWidth: 30 },
    ],
  }
}

function isochroneChart(areas: { minutes: number; area: number }[]): ChartSpec {
  return {
    chart_id: 'chart-isochrone-area',
    type: 'bar',
    title: '分级步行等时圈面积（km²）',
    option: {
      tooltip: {},
      xAxis: { type: 'category', data: areas.map((a) => `${a.minutes}min`) },
      yAxis: { type: 'value', name: 'km²' },
      series: [
        {
          type: 'bar',
          data: areas.map((a) => Number(a.area.toFixed(2))),
          itemStyle: { color: '#8a9c8f' },
          barWidth: '48%',
        },
      ],
    },
  }
}

/* ── 证据构造（出处=POI/测时/判定，延续可溯源叙事） ── */

function buildEvidence(r: LivingCircleReport): Evidence[] {
  const prefix = `ev-${r.scene.name}`
  const at = r.generated_at
  const ev: Evidence[] = [
    {
      evidence_id: `${prefix}-measure`,
      source_url: `fixture://living-circle/${r.scene.name}/sampling`,
      source_type: 'api_measure',
      title: `采样点测时记录（${r.sampling.points.length} 点）`,
      excerpt: `批量算路 walking 返回 ${samplingReach(r).timed} 条耗时，其中圈内可达 ${samplingReach(r).inReach} 条，15min 圈面积约 ${(r.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0).toFixed(2)} km²`,
      credibility: 0.95,
      collected_by: 'L2-005',
      captured_at: at,
      domain: 'walkability',
    },
    ...r.poi.categories.map((c) => ({
      evidence_id: `${prefix}-poi-${c.category}`,
      source_url: `fixture://living-circle/${r.scene.name}/poi/${c.category}`,
      source_type: 'poi_search' as const,
      title: `${c.label} POI 检索（2km）`,
      excerpt: `命中 ${c.total} 处，圈内 ${c.in_circle} 处${c.nearest_name ? `，最近「${c.nearest_name}」${fmtMin(c.min_minutes)}` : '，圈内空缺'}`,
      credibility: 0.92,
      collected_by: 'L2-004',
      captured_at: at,
      domain: c.category,
    })),
    ...r.blindspots.map((b) => ({
      evidence_id: `${prefix}-bs-${b.id}`,
      source_url: `fixture://living-circle/${r.scene.name}/blindspot/${b.id}`,
      source_type: 'grid_scan' as const,
      title: `盲区点位 ${b.id.replace(/^bs-/, '')}`,
      excerpt: `1km 内无 ${b.missing_facilities.join('、')}；最近「${b.nearest[0]?.name ?? '—'}」${b.nearest[0] ? `${Math.round(b.nearest[0].distance_m)}m（${b.nearest[0].direction}）` : ''}`,
      credibility: 0.98,
      collected_by: 'L3-002',
      captured_at: at,
      domain: 'coverage',
    })),
  ]
  return ev
}

/* ── 主构造器 ── */

/**
 * 亮点句（演示态侧）—— 与后端 `diagnosis_templates._highlight_items` 同判据、同措辞。
 * 按主题返回，各章按键取；某主题无数据就不产该条（宁可少一条，不写没据的判断）。
 *
 * ⚠️ 这是"同一份文案两处实现"的又一例（计划风险台账 R1/R3）。本轮只镜像 highlights
 * 这一个字段——它是本次新增里最可见的一项；其余新句式的演示态分叉已在批次二**量化记录**，
 * 统一交给"报告装配单一真相源"那次重构收，不再往这里加第五、第六份。
 */
export function highlightItems(r: LivingCircleReport): Record<string, string> {
  const out: Record<string, string> = {}
  const bars = r.scores.bars ?? []
  if (bars.length >= 2) {
    const lo = bars.reduce((a, b) => (b.value < a.value ? b : a))
    const hi = bars.reduce((a, b) => (b.value > a.value ? b : a))
    if (hi.value !== lo.value) {
      out.spread = `最长板与短板差 ${Math.round(hi.value - lo.value)} 分：「${hi.label}」${hi.value} 对「${lo.label}」${lo.value}`
    }
  }
  const b0 = r.blindspots?.[0]
  const res = (b0?.affected as { estimated_residents?: number } | undefined)?.estimated_residents
  if (res) {
    out.blindspot = `一处 1km 服务空洞压着受估 ${res} 人 —— 缺的是${(b0?.missing_facilities ?? []).join('、')}`
  }
  const tri = r.scores.triads ?? []
  if (tri.length) {
    const far = tri.reduce((a, b) => ((b.nearest_minutes ?? 0) > (a.nearest_minutes ?? 0) ? b : a))
    if (far.nearest_minutes) {
      out.triad = `三要素都判可达，但「${far.facility}」要走 ${far.nearest_minutes}min —— 可达不等于方便`
    }
  }
  return out
}

const HL_ORDER = ['spread', 'blindspot', 'triad'] as const

function hlList(r: LivingCircleReport): string[] {
  const it = highlightItems(r)
  return HL_ORDER.map((k) => it[k]).filter((x): x is string => !!x).slice(0, 3)
}

function buildSections(r: LivingCircleReport): ReportSection[] {
  return [
    {
      id: 'overview',
      title: '体检概览',
      level: 2,
      key_takeaway: overviewNote(r),
      paragraphs: [
        `本次体检由常青圈规划专家队按「intake→plan→measure→collect→diagnose→report→audit」流水线完成，中心点「${r.scene.name}」（${r.scene.city} · ${r.scene.address}），研究范围 ${(r.scene.study_radius_m / 1000).toFixed(1)}km。`,
        `数据口径：${r.data_origin === 'offline' ? '离线估算（offline）· 区县中心近似 + 距离模型测时，未联网采集 POI，评分与盲区需实时体检后给出' : r.data_origin === 'fixture_sample' ? '演示数据（fixture_sample）· 等时圈圆形近似' : '真实百度 API（live）· IDW 插值等时圈'}。图例与章节图表均可溯源至采样点 / POI / 判定等确定性动作。`,
      ],
      charts: [radarChart(r), coverageBarChart(r)],
      highlights: hlList(r),
      source_evidence_ids: [`ev-${r.scene.name}-measure`],
    },
    secMedical(r),
    secEducation(r),
    secMarket(r),
    secElderly(r),
    secIsochrone(r),
    secBlindspot(r),
    secConclusion(r),
  ]
}

/** 从样例 fixture 构造一张完整的体检 Report（多次调用返回稳定结果，供缓存复用） */
export function buildLivingCircleReport(sceneId: string): Report | null {
  const sample = SAMPLE_COMMUNITIES.find((s) => s.id === sceneId)
  if (!sample) return null
  const lc = sample.report
  const experts = [
    'L3-001',
    'L3-002',
    'L3-003',
    'L2-001',
    'L2-002',
    'L2-003',
    'L2-004',
    'L2-005',
    'L2-008',
    'L1-001',
    'L1-004',
    'L1-005',
    'L1-008',
  ]
  const sections = buildSections(lc)
  const report: Report = {
    id: LC_REPORT_ID(sceneId),
    report_type: 'living_circle',
    title: `${lc.scene.name} · 生活圈体检报告`,
    // 副标题的「共 N 处设施」数**可达区内**（`poi.in_circle`），不是采集区内（`poi.total`）。
    // 与后端 `core/pipeline/diagnosis_templates.py::assemble_report` 保持逐字同口径 ——
    // 同一句话在两处实现（Py/TS）里各写一份时，口径必须显式对齐，否则演示报告与真实报告会不一致。
    // 地点前缀走 `lcLocPrefix` 单一实现（空片段不拼接，避免「昆明市 · ｜综合…」悬空分隔符）。
    subtitle: `${lcLocPrefix(lc.scene)}综合 ${lc.scores.total} 分（${scoreGrade(lc.scores.total).label}）· ${lc.blindspots.length} 处服务盲区 · 共 ${lc.poi.in_circle} 处设施（可达区内）`,
    query: lc.scene.name,
    brands: [],
    mode: 'standard',
    created_at: lc.generated_at,
    experts,
    dispatch: charter(experts),
    toc: sections.map((s) => ({ id: s.id, title: s.title, level: s.level })),
    sections,
    charts: sections.flatMap((s) => s.charts ?? []),
    evidence: buildEvidence(lc),
    claims: sections.flatMap((s) => s.claims ?? []),
    glossary: [
      { term: '等时圈', definition: '以中心点为原点、步行耗时相同的等值线族（5/10/15/20 min），对应不同可达范围', source: 'methodology' },
      { term: '服务盲区', definition: '1km 范围内缺少菜市场/药店/小学任一必备设施的区域', source: '赛题口径' },
      { term: 'IDW 插值', definition: '反距离加权：以采样点耗时推演连续耗时场，不依赖底层路网', source: 'methodology' },
      { term: 'BD-09', definition: '百度坐标系，本项目地图全域统一使用', source: 'contract' },
    ],
    methodology: {
      window: '单次体检',
      note: `data_origin=${lc.data_origin} · interpolation=${lc.sampling.interpolation} · study_radius=${lc.scene.study_radius_m}m`,
    },
    quality_before: undefined,
    quality_after: undefined,
    audit_review: undefined,
    trace: undefined,
    living_circle: lc,
  }
  return report
}

/** 按报告 id 取 mock 报告（支持历史快照别名） */
export function getLivingCircleReportMock(id: string): Report | null {
  const base = LC_ALIAS[id] ?? id
  const prefix = 'lc-'
  if (!base.startsWith(prefix)) return null
  return buildLivingCircleReport(base.slice(prefix.length))
}

/** 历史页 / 报告中心共用：历次体检记录（首批 = 两样区实检 + 早期轮次快照） */
export function getLifeCircleRecords(): LifeCircleRecord[] {
  // `kaili-ev2` 排进来不是凑数：它是三份内置样区里**唯一带逐格台账**的那一份
  // （`caliber.cells_ledger`，判盲 8 格）。不列它，报告中心里台账卡与台账段永远取不到，
  // 演示态就会变成"功能做了但没人看得见"。
  const two: LifeCircleRecord[] = (['kaili-ev2', 'kaili', 'beijing-jinsong']
    .map((sceneId): LifeCircleRecord | null => {
      const sample = SAMPLE_COMMUNITIES.find((s) => s.id === sceneId)
      if (!sample) return null
      const lc = sample.report
      return {
        id: LC_REPORT_ID(sceneId),
        // 用样区名而非 `lc.scene.name`：ev2 与 kaili 是**同一个社区的两轮体检**，
        // scene.name 都是「凯里老街」⇒ 两条记录会同名，报告中心里点哪条分不清。
        // 样区名带口径后缀（「凯里老街 · 逐格台账口径」），另两条一字不变。
        title: `${sample.title} · 生活圈体检报告`,
        scene_name: lc.scene.name,
        city: lc.scene.city,
        checked_at: lc.generated_at,
        total_score: lc.scores.total,
        blindspot_count: lc.blindspots.length,
        data_origin: lc.data_origin,
        interpolation: lc.sampling.interpolation,
      }
    })
    .filter((x): x is LifeCircleRecord => x !== null))

  // 早期轮次快照（fixture 演示历史时间线；复用阅读器，见 LC_ALIAS）
  const snapshots: LifeCircleRecord[] = [
    {
      id: 'lc-kaili-r1',
      title: '凯里老街 · 首轮体检快照',
      scene_name: '凯里老街',
      city: '贵州·凯里',
      checked_at: '2026-09-02T03:18:00.000Z',
      total_score: 62,
      blindspot_count: 4,
      data_origin: 'fixture_sample',
      interpolation: 'circular_approx',
    },
    {
      id: 'lc-beijing-jinsong-r1',
      title: '北京劲松 · 首轮体检快照',
      scene_name: '北京劲松',
      city: '北京·朝阳',
      checked_at: '2026-08-29T11:42:00.000Z',
      total_score: 84,
      blindspot_count: 2,
      data_origin: 'fixture_sample',
      interpolation: 'circular_approx',
    },
  ]
  return [...two, ...snapshots].sort((a, b) => (a.checked_at < b.checked_at ? 1 : -1))
}