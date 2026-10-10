/**
 * A4b · 演示流水线的**上屏数字必须指得回产物**（`eventFlow.json` ↔ `kaili-ev2.json`）。
 *
 * ## 为什么必须有这份文件
 *
 * `eventFlow.json` 是 F0 手绘的，句里那句「识别 4 处服务盲区…综合评分 65」和它末尾
 * `report_ready` 打开的那份报告（`lc-kaili`：盲区 **0 处**、65.4 分）**从来没对上过**，
 * 而 A4 那份契约只验事件类型/字段/进度单调 —— 结构全绿、内容全假，一路活到 10-03。
 * 10-03 把整条流重录到 ev-2 真跑件之后，如果没有这份文件，下一次动夹具或动流又会漂回去。
 *
 * ## 被守护的契约
 *
 * 每条断言都**带上下文**去匹配（`/可达区内 7 处/` 而不是 `includes('7')`），
 * 期望值一律现算自 `kaili-ev2.json`，脚本里不抄第二份读数 —— 抄了就成判据的第二实现。
 * 覆盖：中心点/半径/速度与绕行、采样点数与可达点数、四档等时圈面积、两类 POI 的
 * 命中与最近、POI 总量、逐格五档、评分与四条子分、取证轮读数、盲区明细、判定覆盖率、
 * 专家数、采集半径、归并半径、台账位阵张数，以及 `report_ready` 的目标报告 id。
 */
import { describe, expect, it } from 'vitest'
import eventFlow from '../mocks/livingCircle/eventFlow.json'
import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { LivingCircleReport } from '../types'

const LC = kailiEv2 as unknown as LivingCircleReport
const CAL = LC.caliber!
const LED = CAL.cells_ledger!
const FLOW = eventFlow as unknown as {
  report_id: string
  events: { type: string; data: Record<string, unknown> }[]
}

/** 全部 message 与 evidence.excerpt 拼成一块文本：上屏话只有这两个来源。 */
const SAID = FLOW.events
  .map((e) => {
    const d = e.data as { text?: string; evidence?: { excerpt?: string; title?: string }; node?: { label?: string } }
    return [d.text, d.evidence?.excerpt, d.evidence?.title, d.node?.label].filter(Boolean).join('\n')
  })
  .join('\n')

const cat = (key: string) => LC.poi.categories.find((c) => c.category === key)!
/** 数值进正则前一律转义：`7.4` 里的 `.` 不转义就是"任意字符"，判据会松一档。 */
const esc = (v: unknown) => String(v).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const said = (re: RegExp, why: string) => {
  expect(SAID, `${why}\n实际没在流里找到匹配 ${re} 的句子`).toMatch(re)
}

/** 本文件所有期望值都**现算自夹具** ⇒ 夹具缺任一字段，等于那条断言失去基线。
 *  与其在算式里 `?? 0` 把"缺字段"伪装成"值为 0"（那正是本文件要防的结构全绿、内容全假），
 *  不如在入口一次硬要求：缺就红，并说清缺的是哪一个。 */
const num = (v: unknown, what: string): number => {
  expect(typeof v === 'number' && Number.isFinite(v), `夹具缺「${what}」⇒ 本文件失去基线`).toBe(true)
  return v as number
}
const COLLECT_R = num(CAL.collect_radius_m, 'caliber.collect_radius_m')
const CELLS_INSIDE = num(CAL.cells_inside, 'caliber.cells_inside')
const CELLS_JUDGED = num(CAL.cells_judged, 'caliber.cells_judged')
const CELLS_BLIND = num(CAL.cells_blind, 'caliber.cells_blind')
const SPEC = LC.sampling.spec
const TEAM_IDS = LC.team?.expert_ids ?? []

describe('A4b · 演示流水线上屏数字 ↔ ev-2 产物', () => {
  it('夹具带得上屏要念的那几件产物（缺任一件，后面的断言全是空转）', () => {
    expect(SPEC, '夹具缺 sampling.spec ⇒ 「全实测」那条没有判据').toBeTruthy()
    expect(TEAM_IDS.length, '夹具缺 team.expert_ids ⇒ 专家数那条没有判据').toBeGreaterThan(0)
    expect(CAL.facility_merge?.merge_radius_m, '夹具缺 caliber.facility_merge.merge_radius_m').toBeTruthy()
  })

  it('流末尾打开的就是那份 ev-2 真跑件，且报告取到实体（不是 null 冒充已接线）', () => {
    const ready = FLOW.events.filter((e) => e.type === 'report_ready' || e.type === 'done')
    expect(ready.length).toBeGreaterThan(0)
    for (const e of ready) {
      expect((e.data as { report_id?: string }).report_id).toBe('lc-kaili-ev2')
    }
    expect(FLOW.report_id).toBe('lc-kaili-ev2')
    expect(getLivingCircleReportMock('lc-kaili-ev2')).not.toBeNull()
  })

  it('中心点、研究半径、出行参数逐字取自 caliber', () => {
    const [lng, lat] = LC.scene.center
    said(new RegExp(`（${esc(lng)}, ${esc(lat)}）`), `中心点应念 ${lng}, ${lat}（全角括号，与上屏一致）`)
    said(new RegExp(`${esc(LC.scene.study_radius_m)}m`), '研究半径应等于 scene.study_radius_m')
    said(new RegExp(`${esc(CAL.speed_m_per_min)}m/min · 绕行系数 ×${esc(CAL.detour_k)}`), '速度与绕行系数')
    said(new RegExp(`采集半径 ${esc(Math.round(COLLECT_R))}m`), '采集半径取 caliber.collect_radius_m')
  })

  it('采样读数：点数、可达点数、四档等时圈面积', () => {
    const n = LC.sampling.points.length
    expect(LC.sampling.timed_count).toBe(n)
    said(new RegExp(`${n} 个采样点`), '采样点数')
    said(new RegExp(`${n} 点全部拿到实测耗时`), '全实测（且 spec.degraded 为假）')
    expect(SPEC!.degraded).toBe(false)
    said(new RegExp(`${LC.sampling.in_reach_count} 点落在`), '可达区内点数')
    const areas = LC.isochrones.map((i) => i.area_km2).join(' / ')
    said(new RegExp(areas.replace(/\./g, '\\.') + ' km²'), `四档面积应逐字等于 ${areas}`)
  })

  it('POI 两类明细与总量，都指回 poi.categories / poi 标量', () => {
    const m = cat('market')
    said(new RegExp(`采集到 ${m.total} 处`), '菜市场命中数')
    said(new RegExp(`可达区内 ${esc(m.in_circle)} 处，最近「${esc(m.nearest_name)}」${esc(m.min_minutes)}min`), '菜市场圈内数与最近')
    const d = cat('medical')
    said(new RegExp(`命中 ${esc(d.total)} 处，可达区内 ${esc(d.in_circle)} 处，最近「${esc(d.nearest_name)}」${esc(d.min_minutes)}min`), '医疗明细')
    said(new RegExp(`共 ${esc(LC.poi.total)} 处，可达区内 ${esc(LC.poi.in_circle)} 处`), 'POI 总量')
    const el = cat('elderly')
    expect(el.in_circle).toBe(0)
    said(/养老类 0 处 —— 本批检索词不含社区级命名，读作未检出而非没有/, '养老那 0 处必须按「未检出」说，不许读成资源缺失')
  })

  it('逐格五档与「1 处盲区」对上台账；覆盖率与盲区外推口径一致', () => {
    const blind = [...LED.blind.join('')].filter((c) => c === '1').length
    const verdict = [...LED.verdict.join('')].filter((c) => c === '1').length
    const capped = [...LED.capped.join('')].filter((c) => c === '1').length
    const clear = verdict - blind
    const unknown = CELLS_INSIDE - blind - clear - capped
    expect([CELLS_BLIND, CELLS_JUDGED, CAL.cells_unknown]).toEqual([blind, verdict, unknown])
    said(new RegExp(
      `可达区内 ${CELLS_INSIDE} 格，判出结论 ${verdict} 格（判盲 ${blind} · 不盲 ${clear}）`
      + `、未定 ${unknown} 格、封顶 ${capped} 格；识别 ${LC.blindspots.length} 处服务盲区`,
    ), '逐格五档 + 盲区处数')
    said(new RegExp(`判定覆盖率 ${Math.round(CELLS_JUDGED / CELLS_INSIDE * 100)}%`
      + `（${CELLS_JUDGED}/${CELLS_INSIDE} 格）`), '判定覆盖率')
    expect(Object.keys(LED).filter((k) => Array.isArray(LED[k as keyof typeof LED])
      && typeof (LED[k as keyof typeof LED] as string[])[0] === 'string'
      && (LED[k as keyof typeof LED] as string[])[0].length === LED.n)).toHaveLength(10)
    said(/逐格台账 10 张位阵齐备/, '台账位阵张数（20 键里有 10 张是位阵）')
  })

  it('评分与四条子分逐字取自 scores.note，不是另算一遍', () => {
    const sub = LC.scores.note.match(/覆盖 ([\d.]+) \/ 可达 ([\d.]+) \/ 多样 ([\d.]+) \/ 均衡 ([\d.]+)/)
    expect(sub, '夹具的 scores.note 里没有那四个子分，本用例失去基线').not.toBeNull()
    said(new RegExp(`综合评分 ${esc(LC.scores.total)}（覆盖 ${esc(sub![1])} / 可达 ${esc(sub![2])} / 多样 ${esc(sub![3])} / 均衡 ${esc(sub![4])}）`),
      '总分与四子分')
  })

  it('取证那一轮：锚点数、未决格变化、额度与收手原因全对上 forensic', () => {
    const f = CAL.forensic!
    const r = f.rounds_detail![0]
    expect(f.stop_reason).toBe('rounds_exhausted')
    said(new RegExp(`只对药店类补打 ${r.anchors_used} 个锚点：未决格 ${r.cells_undecided_before} → ${r.cells_undecided_after}，`
      + `判盲仍 ${r.cells_blind_after} 格；额度 ${f.pool_total} 用 ${f.pool_used} 剩 ${f.pool_remaining}，`
      + `收手原因 ${f.stop_reason}`), '取证轮读数')
  })

  it('盲区明细：id、缺哪类、三向最近距离与缺口指数都取自 blindspots[0]', () => {
    const b = LC.blindspots[0]
    expect(b.missing_facilities).toEqual(['小学'])
    expect(b.severity).toBe('light')
    const near = Object.fromEntries(b.nearest.map((n) => [n.facility, n]))
    said(new RegExp(`盲区 ${b.id}（缺小学）`), '盲区 id 与缺失类')
    said(new RegExp(`最近小学「${esc(near.primary.name)}」${esc(near.primary.direction)} ${esc(near.primary.distance_m)}m，`
      + `菜市${esc(near.market.direction)} ${esc(near.market.distance_m)}m、药房${esc(near.pharmacy.direction)} ${esc(near.pharmacy.distance_m)}m`),
      '三向最近举证')
    said(new RegExp(`缺口指数 ${esc(b.gap_score)}`), '缺口指数')
  })

  it('专家数与归并半径：念出来的数就是产物里的数', () => {
    said(new RegExp(`${TEAM_IDS.length} 位专家`), '专家数取 team.expert_ids')
    said(new RegExp(`同名 ${CAL.facility_merge!.merge_radius_m}m 内归并`), '设施归并半径')
  })
})
