/**
 * F1 · 契约完整性校验：fixture 数据必须满足 F0 冻结的 LivingCircleReport 契约。
 * 守护规则：字段齐全 / 等时圈族分钟集 = {5,10,15,20} / 多边形闭合 / 盲区三要素口径 / 评分范围。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import eventFlow from '../mocks/livingCircle/eventFlow.json'
import type { LivingCircleReport, SSEEventType } from '../types'
import {
  getLivingCircleReportMock,
  getLifeCircleRecords,
  LC_REPORT_ID,
} from '../mocks/livingCircleReports'
import { replayLivingCircleStream, LC_STAGES } from '../mocks/livingCircleStream'

const reports = [kaili as LivingCircleReport, jinsong as LivingCircleReport]

const CLOSED_PAIR_OK = (ring: [number, number][]) =>
  Array.isArray(ring) && ring.length >= 5 && ring[0]?.[0] === ring[ring.length - 1]?.[0] && ring[0]?.[1] === ring[ring.length - 1]?.[1]

describe('LivingCircleReport fixture 契约', () => {
  it('顶层字段齐全且 data_origin/interpolation 正确', () => {
    for (const r of reports) {
      expect(r.data_origin).toBe('fixture_sample')
      expect(r.sampling.interpolation).toBe('circular_approx')
      for (const k of ['scene', 'generated_at', 'isochrones', 'sampling', 'poi', 'blindspots', 'scores'] as const) {
        expect(r).toHaveProperty(k)
      }
    }
  })

  it('scene 中心点/研究半径合法', () => {
    for (const r of reports) {
      expect(r.scene.center).toHaveLength(2)
      expect(r.scene.center.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true)
      expect(r.scene.study_radius_m).toBeGreaterThan(1000)
    }
  })

  it('等时圈族必须覆盖 5/10/15/20 分钟且多边形闭合、面积为正', () => {
    for (const r of reports) {
      const mins = r.isochrones.map((z) => z.minutes).sort((a, b) => a - b)
      expect(mins).toEqual([5, 10, 15, 20])
      for (const z of r.isochrones) {
        expect(z.geojson.type).toBe('Polygon')
        expect(CLOSED_PAIR_OK(z.geojson.coordinates[0])).toBe(true)
        expect(z.area_km2).toBeGreaterThan(0)
        // 时间越长圈越大（单调性）
      }
      for (let i = 1; i < r.isochrones.length; i++) {
        expect(r.isochrones[i].area_km2).toBeGreaterThan(r.isochrones[i - 1].area_km2)
      }
    }
  })

  it('采样点可达性自洽（reachable ⇔ minutes ≤ 20）', () => {
    for (const r of reports) {
      expect(r.sampling.points.length).toBeGreaterThan(0)
      for (const p of r.sampling.points) {
        expect(typeof p.lng).toBe('number')
        expect(typeof p.lat).toBe('number')
        if (p.reachable) {
          expect(p.minutes).not.toBeNull()
          expect(p.minutes!).toBeLessThanOrEqual(20)
        } else {
          expect(p.minutes).toBeNull()
        }
      }
    }
  })

  it('POI 类别统计自洽（in_circle ≤ total，coverage ∈ [0,1]）', () => {
    for (const r of reports) {
      expect(r.poi.categories.length).toBeGreaterThanOrEqual(7)
      for (const c of r.poi.categories) {
        expect(c.in_circle).toBeLessThanOrEqual(c.total)
        expect(c.coverage).toBeGreaterThanOrEqual(0)
        expect(c.coverage).toBeLessThanOrEqual(1)
      }
      expect(r.poi.total).toBeGreaterThanOrEqual(r.poi.in_circle)
    }
  })

  it('盲区口径：1km 半径、缺失∈三要素、多边形闭合；双样例数量差异成立', () => {
    const [k, j] = reports as [LivingCircleReport, LivingCircleReport]
    expect(k.blindspots.length).toBeGreaterThan(j.blindspots.length) // 凯里盲区多于劲松
    for (const b of [...k.blindspots, ...j.blindspots]) {
      expect(b.radius_m).toBe(1000)
      expect(b.missing_facilities.length).toBeGreaterThan(0)
      for (const m of b.missing_facilities) {
        expect(['菜市场', '药店', '小学']).toContain(m)
      }
      expect(b.center).toHaveLength(2)
      expect(CLOSED_PAIR_OK(b.polygon.coordinates[0])).toBe(true)
    }
  })

  it('评分自洽：0-100、三要素 3 条、雷达 ≥5 维', () => {
    for (const r of reports) {
      expect(r.scores.total).toBeGreaterThanOrEqual(0)
      expect(r.scores.total).toBeLessThanOrEqual(100)
      expect(r.scores.triads).toHaveLength(3)
      expect(r.scores.radar.length).toBeGreaterThanOrEqual(5)
      for (const t of r.scores.triads) {
        if (t.covered) {
          expect(t.nearest_minutes).not.toBeNull()
          expect(typeof t.nearest_name).toBe('string')
        }
      }
    }
  })
})

const FLOW_TYPES: SSEEventType[] = ['node_update', 'progress', 'message', 'evidence', 'report_ready', 'done']

describe('A4 · eventFlow.json SSE 事件契约', () => {
  it('事件类型全部合法（对齐 SSEEventType 白名单）', () => {
    const flow = eventFlow as unknown as { events: { type: SSEEventType }[] }
    expect(flow.events.length).toBeGreaterThan(20)
    for (const ev of flow.events) {
      expect(FLOW_TYPES).toContain(ev.type)
    }
  })

  it('stage 序列 = intake→plan→measure→collect→diagnose→report→audit 且进度单调', () => {
    const flow = eventFlow as unknown as { stages: string[]; events: { type: string; data: { stage?: string; percent?: number; stage_seq?: number } }[] }
    expect(flow.stages).toEqual(LC_STAGES)
    const progress = flow.events.filter((e) => e.type === 'progress' && e.data.stage)
    const seen: string[] = []
    let prevPercent = -1
    for (const p of progress) {
      seen.push(p.data.stage!)
      expect(p.data.percent!).toBeGreaterThanOrEqual(prevPercent)
      prevPercent = p.data.percent!
    }
    // 出现顺序与 stage 定义一致（允许同一 stage 多条，不允许乱序/缺段）
    const stageIdx = flow.stages
    expect(seen.every((s, i) => i === 0 || stageIdx.indexOf(s) >= stageIdx.indexOf(seen[i - 1]))).toBe(true)
    for (const s of flow.stages) {
      expect(seen).toContain(s)
    }
    // 收尾：最后一条 progress ≈100
    expect(progress.at(-1)?.data.percent).toBeGreaterThanOrEqual(90)
  })

  it('事件载荷必填字段齐全', () => {
    const flow = eventFlow as unknown as {
      events: {
        type: string
        data: {
          stage?: string
          percent?: number
          stage_seq?: number
          node?: { id: string; label: string; status: string }
          text?: string
          evidence?: { evidence_id: string; title: string; credibility: number; collected_by: string }
          report_id?: string
        }
      }[]
    }
    for (const ev of flow.events) {
      const d = ev.data
      switch (ev.type) {
        case 'node_update':
          expect(d.node?.id).toBeTruthy()
          expect(d.node?.label).toBeTruthy()
          expect(['idle', 'working', 'done', 'rework']).toContain(d.node?.status)
          break
        case 'progress':
          expect(typeof d.percent).toBe('number')
          expect(d.stage).toBeTruthy()
          expect(typeof d.stage_seq).toBe('number')
          break
        case 'message':
          expect(d.text).toBeTruthy()
          break
        case 'evidence':
          expect(d.evidence?.evidence_id).toBeTruthy()
          expect(d.evidence?.title).toBeTruthy()
          expect(d.evidence!.credibility).toBeGreaterThan(0)
          expect(d.evidence!.credibility).toBeLessThanOrEqual(1)
          expect(d.evidence?.collected_by).toBeTruthy()
          break
        case 'report_ready':
        case 'done':
          expect(typeof d.report_id).toBe('string')
          break
      }
    }
  })

  it('report_ready 产出的报告可被 mock 加载（防 M3 联调断链）', () => {
    const flow = eventFlow as unknown as { events: { type: string; data: { report_id?: string } }[] }
    const ready = flow.events.find((e) => e.type === 'report_ready')
    expect(ready?.data.report_id).toBeTruthy()
    expect(getLivingCircleReportMock(ready!.data.report_id!)).not.toBeNull()
  })

  it('回放器按序派发全部事件，并可用 reportId 覆写报告目标', () => {
    vi.useFakeTimers()
    const flow = eventFlow as unknown as { events: { type: string }[] }
    const received: string[] = []
    let doneId = ''
    const close = replayLivingCircleStream(
      'lc-demo',
      { onEvent: (type) => received.push(type) },
      { reportId: 'lc-beijing-jinsong', speed: 10, onDone: (rid) => (doneId = rid) },
    )
    vi.advanceTimersByTime(flow.events.length * 10 + 20)
    expect(received).toEqual(flow.events.map((e) => e.type))
    expect(doneId).toBe('lc-beijing-jinsong')
    // close 后再 advance 不再派发（防泄漏）
    close()
    const len = received.length
    vi.advanceTimersByTime(1000)
    expect(received.length).toBe(len)
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('F3 · 完整体检 Report（living_circle 挂载 + 双层章节）', () => {
  it('id 与样区往返一致（lc-kaili / lc-beijing-jinsong）', () => {
    expect(LC_REPORT_ID('kaili')).toBe('lc-kaili')
    expect(LC_REPORT_ID('beijing-jinsong')).toBe('lc-beijing-jinsong')
    expect(getLivingCircleReportMock('lc-kaili')?.id).toBe('lc-kaili')
    expect(getLivingCircleReportMock('lc-beijing-jinsong')?.living_circle?.scene.name).toBe('北京劲松')
  })

  it('report_type=living_circle + living_circle 挂载（渲染适配器判据）', () => {
    const report = getLivingCircleReportMock('lc-kaili')
    expect(report?.report_type).toBe('living_circle')
    expect(report?.living_circle).toBeTruthy()
    expect(report?.living_circle?.scene.name).toBe('凯里老街')
  })

  it('章节齐全：概览/医疗/教育/菜市/养老/可达性/盲区/结论 ≥6 章，toc 与章节一致', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)
      expect(r!.sections.length).toBeGreaterThanOrEqual(6)
      for (const need of ['overview', 'medical', 'education', 'market', 'elderly', 'isochrone', 'blindspot', 'conclusion']) {
        expect(r!.sections.some((s) => s.id === need)).toBe(true)
      }
      expect(r!.toc.map((t) => t.id)).toEqual(r!.sections.map((s) => s.id))
      for (const sec of r!.sections) {
        expect(sec.title).toBeTruthy()
      }
    }
  })

  it('结论/证据/图表全链路闭环：claims.evidence_ids 均可解析', () => {
    const r = getLivingCircleReportMock('lc-kaili')!
    expect(r.claims.length).toBeGreaterThan(5)
    expect(r.evidence.length).toBeGreaterThan(5)
    expect(r.charts.length).toBeGreaterThanOrEqual(2)
    const evIds = new Set(r.evidence.map((e) => e.evidence_id))
    for (const c of r.claims) {
      for (const eid of c.evidence_ids) {
        expect(evIds.has(eid)).toBe(true)
      }
    }
    for (const sec of r.sections) {
      for (const c of sec.charts ?? []) {
        expect(c.option).toBeTruthy()
      }
    }
  })

  it('盲区章节 data_grid 与盲区数据一致（表格行数=盲区数）', () => {
    const r = getLivingCircleReportMock('lc-kaili')!
    const bs = r.sections.find((s) => s.id === 'blindspot')
    expect(bs?.data_grid?.rows.length).toBe(r.living_circle!.blindspots.length)
  })

  it('getLifeCircleRecordMock：未知 id / 非 lc 前缀 → null；历史别名可解析', () => {
    expect(getLivingCircleReportMock('lc-not-exist')).toBeNull()
    expect(getLivingCircleReportMock('r1')).toBeNull()
    expect(getLivingCircleReportMock('lc-kaili-r1')?.title).toContain('凯里老街')
  })

  it('getLifeCircleRecords：≥4 条、id 唯一、按时间倒序、评分 0-100 盲区 ≥0', () => {
    const records = getLifeCircleRecords()
    expect(records.length).toBeGreaterThanOrEqual(4)
    expect(new Set(records.map((r) => r.id)).size).toBe(records.length)
    for (let i = 1; i < records.length; i++) {
      expect(records[i - 1].checked_at >= records[i].checked_at).toBe(true)
    }
    for (const rec of records) {
      expect(rec.total_score).toBeGreaterThanOrEqual(0)
      expect(rec.total_score).toBeLessThanOrEqual(100)
      expect(rec.blindspot_count).toBeGreaterThanOrEqual(0)
      expect(rec.title).toBeTruthy()
    }
  })
})