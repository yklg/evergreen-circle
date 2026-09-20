/**
 * F1 · 契约完整性校验：fixture 数据必须满足 F0 冻结的 LivingCircleReport 契约。
 * 守护规则：字段齐全 / 等时圈族分钟集 = {5,10,15,20} / 多边形闭合 / 盲区三要素口径 / 评分范围。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import eventFlow from '../mocks/livingCircle/eventFlow.json'
import type { LivingCircleReport, LngLat, SSEEventType } from '../types'
import {
  getLivingCircleReportMock,
  getLifeCircleRecords,
  LC_REPORT_ID,
} from '../mocks/livingCircleReports'
import { replayLivingCircleStream, LC_STAGES } from '../mocks/livingCircleStream'
import { dataOriginBadge, LC_CANVAS, LC_ISO_COLORS, lcCoLocated, lcLocPrefix, lcMeters, lcPolyPts, lcSceneDistanceM, lcToPx, LC_CO_LOCATED_M, planComparisonOverlay } from '../lib/livingCircle'
import { BD_LAT_ABS_MAX, BD_LNG_ABS_MAX, parseBdLngLat } from '../lib/geo'

const reports = [kaili as unknown as LivingCircleReport, jinsong as unknown as LivingCircleReport]

/** 经度增量（dLng °）折算为地面距离的米数（取其近似，仅用于测试判定）。 */
const lngM = (dLng: number, lat = 26.25) => Math.abs(dLng) * 111320 * Math.cos((lat * Math.PI) / 180)

/** 经度偏移辅助（自定基准点向东推进 dLng°）。 */
const east = (lng: number, d: number) => [lng + d, 26.25] as LngLat

const CLOSED_PAIR_OK = (ring: [number, number][]) =>
  Array.isArray(ring) && ring.length >= 5 && ring[0]?.[0] === ring[ring.length - 1]?.[0] && ring[0]?.[1] === ring[ring.length - 1]?.[1]

/** 可达区环（按 caliber.reach_full_min 取，不是按位置取末位）。 */
function reachRing(r: LivingCircleReport): [number, number][] {
  const target = r.caliber?.reach_full_min ?? 20
  const zone = r.isochrones.find((z) => z.minutes === target)
  expect(zone, `等时圈族里找不到 minutes==${target} 的可达区环`).toBeTruthy()
  return zone!.geojson.coordinates[0] as [number, number][]
}

/** 某点距报告中心的地面距离（米）。 */
function distM(r: LivingCircleReport, p: [number, number]): number {
  const [mx, my] = lcMeters(r.scene.center, p[0], p[1])
  return Math.hypot(mx, my)
}

describe('LivingCircleReport fixture 契约', () => {
  it('顶层字段齐全且 data_origin/interpolation 正确', () => {
    for (const r of reports) {
      // M5：fixture 为真实百度实跑快照（live / IDW 插值）
      expect(r.data_origin).toBe('live')
      expect(r.sampling.interpolation).toBe('idw')
      for (const k of ['scene', 'generated_at', 'isochrones', 'sampling', 'poi', 'blindspots', 'scores'] as const) {
        expect(r).toHaveProperty(k)
      }
    }
  })

  it('scene 中心点/研究半径合法，且坐标满足 BD-09 值域', () => {
    for (const r of reports) {
      expect(r.scene.center).toHaveLength(2)
      expect(r.scene.center.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true)
      // 旧防线是「长度 2 + isFinite」——它**逐条放行**墨卡托米坐标（11440230.81 也是有限数）。
      // 值域才是唯一能区分坐标系的判据：拖拽事件把墨卡托米当经纬度写进报告时，只有这里会红。
      const [lng, lat] = r.scene.center
      expect(Math.abs(lng)).toBeLessThanOrEqual(BD_LNG_ABS_MAX)
      expect(Math.abs(lat)).toBeLessThanOrEqual(BD_LAT_ABS_MAX)
      expect(parseBdLngLat(r.scene.center)).not.toBeNull()
      expect(r.scene.study_radius_m).toBeGreaterThan(1000)
    }
  })

  it('空间口径举证：采集区 ⊇ 可达区，且判盲覆盖度可复核（Q1/Q2 的可判据化）', () => {
    for (const r of reports) {
      const cal = r.caliber
      expect(cal, '报告缺少 caliber 举证对象').toBeTruthy()
      for (const k of [
        'reach_full_min',
        'reach_radius_bound_m',
        'reach_circumradius_m',
        'collect_radius_m',
        'collect_margin_m',
        'cells_inside',
        'cells_judged',
        'cells_unknown',
      ] as const) {
        expect(typeof cal![k], `caliber.${k} 缺失（无可观测性出口 ⇒ 采集半径算错也看不出来）`).toBe('number')
      }
      // 可达区 ⊆ 采集区（否则可达区内必然存在无数据格，「没查到」会被当成「没有」）
      expect(cal!.collect_radius_m!).toBeGreaterThanOrEqual(cal!.reach_circumradius_m! * 0.999)
      // 采集半径 = 外接圆 + 余量
      expect(cal!.collect_radius_m!).toBeCloseTo(cal!.reach_circumradius_m! + cal!.collect_margin_m!, 3)
      // 判盲格数分账必须闭合（可判定 + 不可判定 = 可达区内总格数）
      expect(cal!.cells_judged! + cal!.cells_unknown!).toBe(cal!.cells_inside!)
      // 实测外接圆不应小于理论下界（更小 ⇒ 测时或圈层提取出了问题）
      expect(cal!.reach_circumradius_m!).toBeGreaterThanOrEqual(cal!.reach_radius_bound_m! * 0.9)
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

  it('采样点可达性自洽（reachable ⇔ minutes 非空）', () => {
    // 真实路网测时语义：reachable ⇔ 有分钟值；分钟本身无 ≤20 上限（2.5km 研究域步行可到 75min）
    for (const r of reports) {
      expect(r.sampling.points.length).toBeGreaterThan(0)
      for (const p of r.sampling.points) {
        expect(typeof p.lng).toBe('number')
        expect(typeof p.lat).toBe('number')
        expect(p.reachable).toBe(p.minutes !== null)
        if (p.reachable) {
          expect(typeof p.minutes).toBe('number')
          expect(p.minutes!).toBeGreaterThanOrEqual(0)
        }
      }
    }
  })

  it('poi.points 点位契约（M5.1 增量字段）', () => {
    // points 允许为空（权威快照未采集/配额受限时优雅降级），非空时逐字段校验
    for (const r of reports) {
      expect(Array.isArray(r.poi.points)).toBe(true)
      for (const p of r.poi.points) {
        expect(p.id.startsWith('poi-')).toBe(true)
        expect(typeof p.name).toBe('string')
        expect(typeof p.category).toBe('string')
        expect(p.lnglat).toHaveLength(2)
        expect(p.lnglat.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true)
        expect(p.minutes === null || typeof p.minutes === 'number').toBe(true)
        expect(typeof p.in_circle).toBe('boolean')
      }
    }
  })

  it('poi.points 全部落在可达区内（Q2：圈外点不进报告、不给前端）', () => {
    for (const r of reports) {
      const cr = Math.max(...reachRing(r).map((p) => distM(r, p)))
      for (const p of r.poi.points) {
        expect(p.in_circle).toBe(true)
        expect(distM(r, p.lnglat as [number, number])).toBeLessThanOrEqual(cr * 1.02)
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

  it('盲区口径：1km 半径、缺失∈三要素、多边形闭合；且盲区必须落在可达区内', () => {
    for (const r of reports) {
      for (const b of r.blindspots) {
        expect(b.radius_m).toBe(1000)
        expect(b.missing_facilities.length).toBeGreaterThan(0)
        for (const m of b.missing_facilities) {
          expect(['菜市场', '药店', '小学']).toContain(m)
        }
        expect(b.center).toHaveLength(2)
        expect(CLOSED_PAIR_OK(b.polygon.coordinates[0])).toBe(true)

        // 盲区中心与每个顶点都必须落在**可达区外接圆**内（Q1 判据）。
        // 旧断言是「凯里盲区数 > 劲松盲区数」——那只是旧实现把整张判定网格连成一片灰框
        // （29km²）后的产物，不是契约；修好判盲范围后凯里 0 处、劲松 1 处，该断言自然失效。
        const cr = Math.max(...reachRing(r).map((p) => distM(r, p)))
        const ring = b.polygon.coordinates[0] as [number, number][]
        for (const p of ring) expect(distM(r, p)).toBeLessThanOrEqual(cr * 1.02)
        expect(distM(r, b.center as [number, number])).toBeLessThanOrEqual(cr * 1.02)
      }
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

/* ── F1/F2 · data_origin 四态徽标 + 离线报告契约（P0-1 迁移守护） ── */

/** 镜像 OfflineDataSource 产出的离线报告结构（契约测试用，不落 fixture） */
function offlineReport(): LivingCircleReport {
  return {
    scene: { name: '上海市浦东新区陆家嘴', city: '上海市', address: '离线估算（区县中心近似）', center: [121.505252, 31.23333], study_radius_m: 2500 },
    generated_at: '2026-09-19T00:00:00.000Z',
    data_origin: 'offline',
    isochrones: [
      { minutes: 5, area_km2: 0.12, geojson: { type: 'Polygon', coordinates: [[[121.5, 31.23], [121.52, 31.23], [121.52, 31.25], [121.5, 31.25], [121.5, 31.23]]] } },
      { minutes: 10, area_km2: 0.48, geojson: { type: 'Polygon', coordinates: [[[121.48, 31.21], [121.56, 31.21], [121.56, 31.27], [121.48, 31.27], [121.48, 31.21]]] } },
      { minutes: 15, area_km2: 1.08, geojson: { type: 'Polygon', coordinates: [[[121.45, 31.18], [121.6, 31.18], [121.6, 31.29], [121.45, 31.29], [121.45, 31.18]]] } },
      { minutes: 20, area_km2: 1.92, geojson: { type: 'Polygon', coordinates: [[[121.4, 31.15], [121.66, 31.15], [121.66, 31.32], [121.4, 31.32], [121.4, 31.15]]] } },
    ],
    sampling: { points: [], interpolation: 'circular_approx', is_scattered: false },
    poi: { categories: [], total: 0, in_circle: 0, points: [] },
    blindspots: [],
    scores: { total: 0, radar: [], bars: [], triads: [], note: '离线估算：步行速度 80 m/min × 绕行系数 1.3 的距离模型，未联网采集 POI——综合评分与服务盲区需实时体检后给出，且离线分不可与实时分比较' },
  }
}

describe('F1 · data_origin 四态徽标映射（P0-1 单一真相源）', () => {
  it('live → 真实数据（绿）', () => {
    const b = dataOriginBadge({ data_origin: 'live' })
    expect(b.label).toBe('真实数据')
    expect(b.tone).toBe('live')
  })

  it('served_from=cache（data_origin 保持 live）→ 历史实时 · 离线可查（蓝）', () => {
    const b = dataOriginBadge({ data_origin: 'live', served_from: 'cache' })
    expect(b.label).toBe('历史实时 · 离线可查')
    expect(b.tone).toBe('info')
  })

  it('offline → 离线估算（黄），且与 cache 态不冲突', () => {
    const b = dataOriginBadge({ data_origin: 'offline' })
    expect(b.label).toBe('离线估算')
    expect(b.tone).toBe('warn')
    expect(b.detail).toMatch(/待实时体检/)
  })

  it('fixture_sample → 演示数据（黄）', () => {
    const b = dataOriginBadge({ data_origin: 'fixture_sample' })
    expect(b.label).toBe('演示数据')
    expect(b.tone).toBe('warn')
  })
})

describe('F2 · 离线报告契约（offline 结构 + served_from/cached_at 可选）', () => {
  it('offline 报告结构：data_origin=offline + 等时圈单调 + POI/盲区空 + 评分 note 说明不可比', () => {
    const r = offlineReport()
    expect(r.data_origin).toBe('offline')
    expect(r.sampling.interpolation).toBe('circular_approx')
    expect(r.isochrones.map((z) => z.minutes)).toEqual([5, 10, 15, 20])
    for (let i = 1; i < r.isochrones.length; i++) {
      expect(r.isochrones[i].area_km2).toBeGreaterThan(r.isochrones[i - 1].area_km2)
    }
    expect(r.poi.total).toBe(0)
    expect(r.poi.categories).toEqual([])
    expect(r.poi.points).toEqual([])
    expect(r.blindspots).toEqual([])
    expect(r.scores.total).toBe(0) // 保留结构但不渲染可比数字
    expect(r.scores.note).toMatch(/需实时体检/)
    expect(r.scores.note).toMatch(/不可与实时分比较/)
  })

  it('served_from/cached_at 为可选字段（旧 live 报告零影响）', () => {
    expect('served_from' in kaili).toBe(false)
    expect('cached_at' in kaili).toBe(false)
    const cached: LivingCircleReport = { ...offlineReport(), data_origin: 'live', served_from: 'cache', cached_at: '2026-09-18T00:00:00.000Z' }
    expect(cached.served_from).toBe('cache')
    expect(typeof cached.cached_at).toBe('string')
    // 缓存命中保持 data_origin=live（契约：缓存不改变数据口径）
    expect(cached.data_origin).toBe('live')
  })
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

/* ── F4 · 副标题口径与分隔符（与后端 assemble_report 同口径） ── */

describe('F4 · 报告副标题：设施数口径 + 地点前缀分隔符', () => {
  it('「共 N 处设施」数可达区内（poi.in_circle），不是采集总数（poi.total）', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)!
      const lc = r.living_circle!
      // 两个数必须不同，否则断言没有判别力（夹具退化时会静默通过）
      expect(lc.poi.in_circle).not.toBe(lc.poi.total)
      expect(r.subtitle).toContain(`共 ${lc.poi.in_circle} 处设施`)
      expect(r.subtitle).not.toContain(`共 ${lc.poi.total} 处设施`)
    }
  })

  it('lcLocPrefix：空片段不参与拼接，全空时整个前缀（含 ｜）省略', () => {
    expect(lcLocPrefix({ city: '昆明市', address: '西门街道' })).toBe('昆明市 · 西门街道｜')
    expect(lcLocPrefix({ city: '昆明市', address: '' })).toBe('昆明市｜')
    expect(lcLocPrefix({ city: '昆明市', address: null })).toBe('昆明市｜')
    expect(lcLocPrefix({ city: '', address: '西门街道' })).toBe('西门街道｜')
    expect(lcLocPrefix({ city: '', address: '' })).toBe('')
    expect(lcLocPrefix({})).toBe('')
    // 两侧都是空白字符也应视作空（防止「 · ｜」这类纯空白悬空分隔符）
    expect(lcLocPrefix({ city: '  ', address: '\t' })).toBe('')
  })

  it('mock 副标题不留悬空分隔符，且以地点前缀开头', () => {
    for (const id of ['lc-kaili', 'lc-beijing-jinsong']) {
      const r = getLivingCircleReportMock(id)!
      const lc = r.living_circle!
      expect(r.subtitle).not.toContain(' · ｜')
      expect(r.subtitle?.startsWith('｜')).toBe(false)
      expect(r.subtitle?.startsWith(`${lcLocPrefix(lc.scene)}综合 `)).toBe(true)
      // 整段版式（含分隔符前后的空格）必须与后端逐字同口径
      expect(r.subtitle).toMatch(
        /综合 [\d.]+ 分（[优中良差]）· \d+ 处服务盲区 · 共 \d+ 处设施（可达区内）$/,
      )
    }
  })
})

/* ── T5 · 画布口径与降级呈现护栏（I14/I5，多方式分档前置） ── */

describe('T5 · 降级画布 (LC_CANVAS) 与报告半径同源', () => {
  it('LC_CANVAS.R 必须等于报告 study_radius_m（半径一变，米→像素投影即失准）', () => {
    for (const r of reports) {
      expect(r.scene.study_radius_m).toBe(LC_CANVAS.R)
    }
    expect(offlineReport().scene.study_radius_m).toBe(LC_CANVAS.R)
  })

  it('等时圈配色表覆盖全部圈层（不足会渲染出 undefined 色）', () => {
    for (const r of reports) {
      expect(LC_ISO_COLORS.length).toBeGreaterThanOrEqual(r.isochrones.length)
    }
  })

  it('中心点投影落在画布正中（投影语义单一源）', () => {
    const c = reports[0].scene.center as LngLat
    const [x, y] = lcToPx(c, c[0], c[1])
    expect(x).toBeCloseTo(LC_CANVAS.W / 2, 6)
    expect(y).toBeCloseTo(LC_CANVAS.H / 2, 6)
  })

  it('**当前行为**：R 为常量 → 9000m 半径的圈投影溢出画布（B2 前置证据）', () => {
    // TODO（B2）：R 改由 report.scene.study_radius_m 派生后，此用例应断言 x <= W。
    const c: LngLat = [121.505252, 31.23333]
    const lngAt = (meters: number) => c[0] + meters / (111320 * Math.cos((c[1] * Math.PI) / 180))
    const [x2500] = lcToPx(c, lngAt(2500), c[1])
    const [x9000] = lcToPx(c, lngAt(9000), c[1])
    expect(x2500).toBeCloseTo(LC_CANVAS.W, 6) // 研究域右边界恰为画布右沿
    expect(x9000).toBeGreaterThan(LC_CANVAS.W * 2) // 骑行/驾车分档后溢出 → SVG 裁切
    expect(lcMeters(c, lngAt(9000), c[1])[0]).toBeCloseTo(9000, 0)
  })

  it.todo('B2：R 派生自 study_radius_m 后，9000m 圈必须完整落在画布内（对比模式取 max(R_A,R_B)）')

  it('poi.points 为空数组时等时圈几何渲染路径不受影响（点位与圈层解耦）', () => {
    const r = offlineReport()
    expect(r.poi.points).toEqual([])
    for (const z of r.isochrones) {
      const pts = lcPolyPts(r.scene.center as LngLat, z.geojson.coordinates[0] as LngLat[])
      expect(pts.split(' ').length).toBe(z.geojson.coordinates[0].length)
      expect(pts).not.toContain('NaN')
    }
  })
})
describe('L10 · 对比呈现决策原语（选谁 → 怎么呈现一体决策）', () => {
  const c = [107.98, 26.25] as LngLat

  it('lcSceneDistanceM 距离度量守恒（经度每差 ~0.01° ≈ 1000m）', () => {
    const d = lcSceneDistanceM(c, east(c[0], 0.01))
    expect(d).toBeCloseTo(1000, -1) // 量级正确（±100m 内）
    expect(lcSceneDistanceM(c, c)).toBe(0)
    // 对称性
    expect(lcSceneDistanceM(c, east(c[0], 0.02))).toBeCloseTo(lcSceneDistanceM(east(c[0], 0.02), c), 0)
  })

  it('lcCoLocated 在 4km 阈值内外正确翻转', () => {
    const near = lngM(0.02) // ≈2km
    const far = lngM(0.06) // ≈6km
    expect(near).toBeLessThan(LC_CO_LOCATED_M)
    expect(far).toBeGreaterThan(LC_CO_LOCATED_M)
    expect(lcCoLocated(c, east(c[0], 0.02))).toBe(true)
    expect(lcCoLocated(c, east(c[0], 0.06))).toBe(false)
  })

  it('planComparisonOverlay：同片 → shareMap 单图叠加；跨城 → 双图 + 归一示意', () => {
    expect(planComparisonOverlay(c, east(c[0], 0.02))).toEqual({
      shareMap: true,
      normalize: false,
      reason: 'co-located',
    })
    expect(planComparisonOverlay(c, east(c[0], 0.06))).toEqual({
      shareMap: false,
      normalize: true,
      reason: 'cross-location',
    })
  })
})
