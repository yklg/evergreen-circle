/**
 * 归档索引（列表层单一事实源）的纯函数契约。
 *
 * 回溯规则：IN-02 边界 / IN-04 非法格式 / INV-01 并集不变量 / INV-03 精度 /
 * DATA-02 时区混排 / CT-01 老记录缺字段 / P-03 不可比 ≠ 0（T5 口径）。
 */
import { describe, it, expect } from 'vitest'
import type { LifeCircleRecord, ReportCard } from '../types'
import { TASK_DOMAINS } from '../lib/taskDomains'
import {
  RECORD_DOMAINS,
  buildRecordIndex,
  filterRecords,
  fmtRecordTime,
  isComparableScore,
  lcRecordToRow,
  normalizeRecordFilter,
  recordStats,
  researchCardToRow,
  sortKeyOf,
  type ReportRecord,
} from '../lib/recordIndex'

function lcRow(over: Partial<LifeCircleRecord> = {}): LifeCircleRecord {
  return {
    id: 'lc-1',
    title: '凯里老街 · 生活圈体检报告',
    scene_name: '凯里老街',
    city: '贵州·凯里',
    checked_at: '2026-09-19T20:00:00Z',
    total_score: 70,
    blindspot_count: 3,
    data_origin: 'live',
    interpolation: 'idw',
    ...over,
  } as LifeCircleRecord
}

function researchRow(over: Partial<ReportCard> = {}): ReportCard {
  return {
    id: 'r-1',
    report_id: 'r-1',
    title: '大理亲子游调研',
    subtitle: '大理',
    query: '大理 5 天亲子游',
    experts: [],
    evidence_count: 12,
    claim_count: 4,
    high_conf_count: 2,
    created_at: '2026-09-18T09:30:00',
    ...over,
    // 归档索引不读品牌维度字段；不写进夹具以免把旧语义带回活跃代码
  } as unknown as ReportCard
}

describe('FE-35/IN-02 · 可比性判据（0 分与不可比是两件事）', () => {
  it('total_score = 0 / null 都不可比；正分才可比', () => {
    expect(isComparableScore({ total_score: 0 })).toBe(false)
    expect(isComparableScore({ total_score: null })).toBe(false)
    expect(isComparableScore({ total_score: 1 })).toBe(true)
  })
})

describe('FE-35 · recordStats 统计口径', () => {
  it('无可比记录 → null（统计带整体不渲染，不得把 null 当 0 计入平均）', () => {
    const rows = buildRecordIndex([lcRow({ total_score: null, blindspot_count: 0 })], [researchRow()])
    expect(recordStats(rows)).toBeNull()
  })

  it('n/N：total 只计可比，visibleLcTotal 含不可比的生活圈记录', () => {
    const rows = buildRecordIndex(
      [lcRow({ id: 'lc-a', total_score: 80 }), lcRow({ id: 'lc-b', total_score: null })],
      [],
    )
    const stats = recordStats(rows)!
    expect(stats.total).toBe(1)
    expect(stats.visibleLcTotal).toBe(2)
    expect(stats.avg).toBe(80)
  })

  it('盲区求和只走可比子集（null 分支不可能进入统计）', () => {
    const rows = buildRecordIndex(
      [lcRow({ id: 'lc-a', total_score: 80, blindspot_count: 5 }), lcRow({ id: 'lc-b', total_score: 60, blindspot_count: 2 })],
      [],
    )
    expect(recordStats(rows)!.blindspots).toBe(7)
  })

  it('FE-52/INV-03 · 平均按 Math.round（89.5 → 90）', () => {
    const rows = buildRecordIndex(
      [lcRow({ id: 'lc-a', total_score: 89 }), lcRow({ id: 'lc-b', total_score: 90 })],
      [],
    )
    expect(recordStats(rows)!.avg).toBe(90)
  })

  it('最近一次评分取时间最新的那份，而非数组首位', () => {
    const rows = buildRecordIndex(
      [
        lcRow({ id: 'lc-old', total_score: 55, checked_at: '2026-01-01T00:00:00Z' }),
        lcRow({ id: 'lc-new', total_score: 91, checked_at: '2026-09-09T00:00:00Z' }),
      ],
      [],
    )
    expect(recordStats(rows)!.latestScore).toBe(91)
  })
})

describe('FE-42/DATA-02 · 排序键解析而非字符串比较', () => {
  it('无时区后缀（真实态）与带 Z（夹具）混排时，仍按时间倒序', () => {
    // 字符串比较会把 '…T00:00:00Z' 判得比 '…T08:00:00' 更晚（'Z' 0x5A > '8' 0x38）
    const rows = buildRecordIndex(
      [
        lcRow({ id: 'lc-late', checked_at: '2026-09-19T08:00:00' }),
        lcRow({ id: 'lc-early', checked_at: '2026-09-19T00:00:00Z' }),
      ],
      [],
    )
    expect(rows.map((r) => r.id)).toEqual(['lc-late', 'lc-early'])
  })

  it('FE-48/IN-04 · 坏日期回落排序键 0，不抛', () => {
    expect(sortKeyOf('not-a-date')).toBe(0)
    expect(fmtRecordTime('not-a-date')).toBe('not-a-date')
    const rows = buildRecordIndex([lcRow({ id: 'lc-bad', checked_at: '坏时间' })], [])
    expect(rows).toHaveLength(1)
  })
})

describe('FE-45/INV-01 · 归档并集不变量', () => {
  it('两源任意顺序 → 条数为并集、key 唯一、按域可分', () => {
    const lc = [lcRow({ id: 'lc-a' }), lcRow({ id: 'lc-b' }), lcRow({ id: 'lc-c' })]
    const research = [researchRow({ report_id: 'r-1', id: 'r-1' }), researchRow({ report_id: 'r-2', id: 'r-2' })]
    const rows = buildRecordIndex(lc, research)
    expect(rows).toHaveLength(5)
    expect(new Set(rows.map((r) => r.key)).size).toBe(5)
    expect(filterRecords(rows, 'living_circle')).toHaveLength(3)
    expect(filterRecords(rows, 'travel')).toHaveLength(2)
    expect(filterRecords(rows, 'all')).toHaveLength(
      filterRecords(rows, 'living_circle').length + filterRecords(rows, 'travel').length,
    )
  })

  it('空集合三形态都不抛：全空 / 只缺生活圈 / 只缺调研', () => {
    expect(buildRecordIndex([], [])).toEqual([])
    expect(recordStats(buildRecordIndex([], []))).toBeNull()
    expect(recordStats(buildRecordIndex([], [researchRow()]))).toBeNull()
    expect(filterRecords(buildRecordIndex([lcRow()], []), 'travel')).toEqual([])
  })
})

describe('FE-39 · 调研行绝不伪造生活圈字段', () => {
  it('travel 行的评分/盲区/来源都是 null，而不是 0 与空串', () => {
    const row = researchCardToRow(researchRow())
    expect(row.total_score).toBeNull()
    expect(row.blindspot_count).toBeNull()
    expect(row.data_origin).toBeNull()
    expect(row.city).toBeNull()
    expect(row.evidence_count).toBe(12)
    const rendered = JSON.stringify(row)
    expect(rendered).not.toMatch(/"total_score":0/)
    expect(rendered).not.toMatch(/"blindspot_count":0/)
  })
})

describe('FE-46/CT-01 · 老记录缺字段容错（历史快照无 degraded / interpolation）', () => {
  it('缺可选字段时行模型仍可用，徽标输入保持原值', () => {
    // 运行时下发可能比声明的类型更瘦（历史快照），故走 unknown 收口而非假装类型合规
    const bare = { ...lcRow(), degraded: undefined, interpolation: undefined, city: '' }
    const row = lcRecordToRow(bare as unknown as LifeCircleRecord)
    expect(row.degraded).toBeNull()
    expect(row.city).toBeNull()
    expect(row.data_origin).toBe('live')
    expect(() => recordStats([row])).not.toThrow()
  })
})

describe('FE-40 · 域枚举由 taskDomains 注册表派生', () => {
  it('RECORD_DOMAINS 恰等于注册表里的 family 集合', () => {
    const families = [...new Set(Object.values(TASK_DOMAINS).map((d) => d.family))].sort()
    expect([...RECORD_DOMAINS].sort()).toEqual(families)
  })

  it('未知过滤值归一到 all（深链/手输 URL）', () => {
    expect(normalizeRecordFilter('bogus')).toBe('all')
    expect(normalizeRecordFilter(null)).toBe('all')
    expect(normalizeRecordFilter('living_circle')).toBe('living_circle')
  })
})

describe('FE-37 · 过滤子集与统计联动', () => {
  const rows: ReportRecord[] = buildRecordIndex(
    [lcRow({ id: 'lc-a', total_score: 80 }), lcRow({ id: 'lc-b', total_score: 60 })],
    [researchRow()],
  )

  it('按域过滤后统计只算该域子集；调研档统计为 null', () => {
    expect(recordStats(filterRecords(rows, 'living_circle'))!.total).toBe(2)
    expect(recordStats(filterRecords(rows, 'travel'))).toBeNull()
  })
})
