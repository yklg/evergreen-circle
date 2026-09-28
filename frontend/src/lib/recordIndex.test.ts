/**
 * 归档索引（列表层单一事实源）的纯函数契约。
 *
 * 回溯规则：IN-02 边界 / IN-04 非法格式 / INV-01 并集不变量 / INV-03 精度 /
 * DATA-02 时区混排 / CT-01 老记录缺字段 / P-03 不可比 ≠ 0（T5 口径）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import type { LifeCircleRecord, ReportCard } from '../types'
import { TASK_DOMAINS } from '../lib/taskDomains'
import {
  RECORD_DOMAINS,
  filterRecords,
  fmtRecordTime,
  groupBySample,
  groupKeyOf,
  intelCardToRow,
  isComparableScore,
  lcRecordToRow,
  livingCircleRows,
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
    const rows = [
      ...livingCircleRows([lcRow({ total_score: null, blindspot_count: 0 })]),
      researchCardToRow(researchRow()),
    ]
    expect(recordStats(rows)).toBeNull()
  })

  it('n/N：total 只计可比，visibleLcTotal 含不可比的生活圈记录', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'lc-a', total_score: 80 }),
      lcRow({ id: 'lc-b', total_score: null }),
    ])
    const stats = recordStats(rows)!
    expect(stats.total).toBe(1)
    expect(stats.visibleLcTotal).toBe(2)
    expect(stats.avg).toBe(80)
  })

  it('盲区求和只走可比子集（null 分支不可能进入统计）', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'lc-a', total_score: 80, blindspot_count: 5 }),
      lcRow({ id: 'lc-b', total_score: 60, blindspot_count: 2 }),
    ])
    expect(recordStats(rows)!.blindspots).toBe(7)
  })

  it('FE-52/INV-03 · 平均按 Math.round（89.5 → 90）', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'lc-a', total_score: 89 }),
      lcRow({ id: 'lc-b', total_score: 90 }),
    ])
    expect(recordStats(rows)!.avg).toBe(90)
  })

  it('最近一次评分取时间最新的那份，而非数组首位', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'lc-old', total_score: 55, checked_at: '2026-01-01T00:00:00Z' }),
      lcRow({ id: 'lc-new', total_score: 91, checked_at: '2026-09-09T00:00:00Z' }),
    ])
    expect(recordStats(rows)!.latestScore).toBe(91)
  })
})

describe('FE-42/DATA-02 · 排序键解析而非字符串比较', () => {
  it('无时区后缀（真实态）与带 Z（夹具）混排时，仍按时间倒序', () => {
    // 字符串比较会把 '…T00:00:00Z' 判得比 '…T08:00:00' 更晚（'Z' 0x5A > '8' 0x38）
    const rows = livingCircleRows([
      lcRow({ id: 'lc-late', checked_at: '2026-09-19T08:00:00' }),
      lcRow({ id: 'lc-early', checked_at: '2026-09-19T00:00:00Z' }),
    ])
    expect(rows.map((r) => r.id)).toEqual(['lc-late', 'lc-early'])
  })

  it('FE-48/IN-04 · 坏日期回落排序键 0，不抛', () => {
    expect(sortKeyOf('not-a-date')).toBe(0)
    expect(fmtRecordTime('not-a-date')).toBe('not-a-date')
    const rows = livingCircleRows([lcRow({ id: 'lc-bad', checked_at: '坏时间' })])
    expect(rows).toHaveLength(1)
  })
})

describe('FE-45/INV-01 · 两域子集互斥且并起来等于全量', () => {
  /**
   * 分屏后 UI 不再有"全量混排列表"（那正是本轮拆掉的形状），这条天然防线消失。
   * 于是把不变量本身钉成判据：任一域子集不吞行、两域相加不重不漏。
   */
  it('任意顺序输入 → 条数为并集、key 唯一、按域可分且互斥', () => {
    const lc = [lcRow({ id: 'lc-a' }), lcRow({ id: 'lc-b' }), lcRow({ id: 'lc-c' })]
    const research = [
      researchRow({ report_id: 'r-1', id: 'r-1' }),
      researchRow({ report_id: 'r-2', id: 'r-2' }),
    ]
    const rows: ReportRecord[] = [...livingCircleRows(lc), ...research.map(researchCardToRow)]
    expect(rows).toHaveLength(5)
    expect(new Set(rows.map((r) => r.key)).size).toBe(5)
    const lcOnly = filterRecords(rows, 'living_circle')
    const travelOnly = filterRecords(rows, 'travel')
    expect(lcOnly).toHaveLength(3)
    expect(travelOnly).toHaveLength(2)
    expect(lcOnly.length + travelOnly.length).toBe(rows.length)
    // 互斥：两个子集没有共同 key（防"两屏共用一份 records"的偷懒实现）
    expect(lcOnly.map((r) => r.key).some((k) => travelOnly.some((t) => t.key === k))).toBe(false)
  })

  it('空集合三形态都不抛：全空 / 只缺生活圈 / 只缺调研', () => {
    expect(livingCircleRows([])).toEqual([])
    expect(recordStats([])).toBeNull()
    expect(recordStats([researchCardToRow(researchRow())])).toBeNull()
    expect(filterRecords(livingCircleRows([lcRow()]), 'travel')).toEqual([])
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

  it('显式写了但无效的过滤值响亮回落默认域（不再归到已下线的 all）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(normalizeRecordFilter('bogus')).toBe('living_circle')
    expect(normalizeRecordFilter('all')).toBe('living_circle')
    // 静默改写会让失效的分享链接看起来"本来就是这一页"，所以告警本身是判据对象
    expect(warn).toHaveBeenCalledTimes(2)
    const logged = warn.mock.calls.map((c) => String(c[0])).join('\n')
    expect(logged).toContain('bogus')
    expect(logged).toContain('all')
    warn.mockRestore()
  })

  it('不带参数是正常入口：回落默认域但不打扰控制台', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(normalizeRecordFilter(null)).toBe('living_circle')
    expect(warn).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('合法域原样通过且不打告警', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(normalizeRecordFilter('living_circle')).toBe('living_circle')
    expect(normalizeRecordFilter('travel')).toBe('travel')
    expect(warn).not.toHaveBeenCalled()
    warn.mockRestore()
  })
})

describe('FE-37 · 过滤子集与统计联动', () => {
  const rows: ReportRecord[] = [
    ...livingCircleRows([lcRow({ id: 'lc-a', total_score: 80 }), lcRow({ id: 'lc-b', total_score: 60 })]),
    researchCardToRow(researchRow()),
  ]

  it('按域过滤后统计只算该域子集；调研档统计为 null', () => {
    expect(recordStats(filterRecords(rows, 'living_circle'))!.total).toBe(2)
    expect(recordStats(filterRecords(rows, 'travel'))).toBeNull()
  })
})

/* ── 甲档形态：同一样区折叠成组（步骤 0 拍定）─────────────────── */

describe('样区分组 · 键与组头数字', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('分组键 = 样区 + 城市：同名不同城不得并组', () => {
    // 真实库里就有这一对：「北京劲松」同时挂着 北京·朝阳 与 昆明市
    const rows = livingCircleRows([
      lcRow({ id: 'lc-a', scene_name: '北京劲松', city: '北京·朝阳' }),
      lcRow({ id: 'lc-b', scene_name: '北京劲松', city: '昆明市' }),
    ])
    expect(groupKeyOf(rows[0])).not.toBe(groupKeyOf(rows[1]))
    const groups = groupBySample(rows)
    expect(groups).toHaveLength(2)
    expect(new Set(groups.map((g) => g.city)).size).toBe(2)
  })

  it('组内按体检时间倒序，组间按"组内最新一份"倒序', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'gd-1', scene_name: '官渡区', checked_at: '2026-09-21T10:00:00Z', total_score: 22 }),
      lcRow({ id: 'gd-2', scene_name: '官渡区', checked_at: '2026-09-22T11:14:00Z', total_score: 88 }),
      lcRow({ id: 'kl-1', scene_name: '凯里老街', checked_at: '2026-09-23T09:00:00Z', total_score: 68 }),
    ])
    const groups = groupBySample(rows)
    expect(groups.map((g) => g.scene)).toEqual(['凯里老街', '官渡区'])
    expect(groups[1].rows.map((r) => r.id)).toEqual(['gd-2', 'gd-1'])
  })

  it('份数等于组内行数；分数差 = 最新 − 最早', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'a', checked_at: '2026-09-20T00:00:00Z', total_score: 65.3 }),
      lcRow({ id: 'b', checked_at: '2026-09-27T00:00:00Z', total_score: 65.8 }),
    ])
    const g = groupBySample(rows)[0]
    expect(g.rows).toHaveLength(2)
    expect(g.scoreDelta).toBeCloseTo(0.5, 10)
  })

  it('任一端不可比时分数差为 null，绝不写成 0 分', () => {
    const rows = livingCircleRows([
      lcRow({ id: 'a', checked_at: '2026-09-20T00:00:00Z', total_score: null }),
      lcRow({ id: 'b', checked_at: '2026-09-27T00:00:00Z', total_score: 65.8 }),
    ])
    expect(groupBySample(rows)[0].scoreDelta).toBeNull()
  })

  it('单份样区没有"历史"可差：分数差为 null 而不是 0', () => {
    const g = groupBySample(livingCircleRows([lcRow({ id: 'solo' })]))
    expect(g).toHaveLength(1)
    expect(g[0].scoreDelta).toBeNull()
  })

  it('city 缺失的行仍成组，不猜城市', () => {
    const rows = livingCircleRows([lcRow({ id: 'nc', city: '' })])
    const g = groupBySample(rows)[0]
    expect(g.city).toBeNull()
    expect(groupKeyOf(rows[0])).toBe(`${g.scene}||`)
  })
})

describe('调研概览卡 → 归档行（删除入口挪到表行尾）', () => {
  it('intel 卡片映射出的行带 evidence_count，确认文案才点得名', () => {
    const row = intelCardToRow({
      id: 'r-9',
      title: '大理亲子游调研',
      query: '大理 5 天亲子游',
      destinations: ['大理'],
      evidence_count: 58,
      claim_count: 58,
      high_conf_count: 54,
      created_at: '2026-09-18T09:30:00',
    })
    expect(row.domain).toBe('travel')
    expect(row.id).toBe('r-9')
    expect(row.evidence_count).toBe(58)
    expect(row.total_score).toBeNull()
    expect(row.key).toBe('research-r-9')
  })
})
