// @vitest-environment jsdom
/**
 * T5 · 归档行的来源举证：0 分与「不可比」必须是两种显示。
 *
 * 承继自被删除的历史页测试（`dashboardHistory.test.tsx` 的第二组 describe）——
 * 页面删了，判据不能跟着删：答辩现场无 AK 分支若把 `total_score=null` 渲染成
 * 「0 分 · 差」，就是一次错误的举证。判据重指到归档层的新接缝：
 * 行渲染走 `components/RecordRow`，统计带隐藏走 `pages/ReportsPage`。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentType } from 'react'
import RecordRow from '../components/RecordRow'
import { lcRecordToRow, researchCardToRow } from '../lib/recordIndex'
import type { LifeCircleRecord, ReportCard } from '../types'

const mocks = vi.hoisted(() => ({
  fetchReports: vi.fn(),
  fetchLifeCircleReports: vi.fn(),
  deleteReport: vi.fn(),
  deleteLifeCircleReport: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  fetchReports: mocks.fetchReports,
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
  deleteReport: mocks.deleteReport,
  deleteLifeCircleReport: mocks.deleteLifeCircleReport,
}))

afterEach(cleanup)

const GRADES = ['优', '良', '中', '差'] as const

function lc(over: Partial<LifeCircleRecord> = {}): LifeCircleRecord {
  return {
    id: 'lc-lujiazui',
    title: '陆家嘴 · 生活圈体检报告',
    scene_name: '陆家嘴',
    city: '上海市',
    checked_at: '2026-09-19T00:00:00Z',
    total_score: 70,
    blindspot_count: 2,
    data_origin: 'live',
    interpolation: 'idw',
    ...over,
  } as LifeCircleRecord
}

function offlineRow() {
  return lcRecordToRow(lc({ total_score: null, blindspot_count: 0, data_origin: 'offline', interpolation: 'circular_approx' }))
}

// 「离线估算」在行里出现两处：分数位（不可比时的回落显示）与来源徽标 ⇒ 一律用 all 变体。
// 档位徽标渲染成 `综合 良` 一个 span（两个文本子节点），故"没有档位"必须连它一起否掉，
// 否则只查裸档位字会静默放过。
function expectNoGradeShown() {
  for (const g of GRADES) expect(screen.queryAllByText(g)).toHaveLength(0)
  expect(screen.queryByText(/综合\s+(优|良|中|差)/)).toBeNull()
}

describe('RecordRow · 来源举证（不可比 ≠ 0 分）', () => {
  it('离线估算行：显示「离线估算」，不显示 0、不显示评分档位、不显示盲区', () => {
    render(<RecordRow record={offlineRow()} onOpen={() => {}} />)
    expect(screen.getAllByText('离线估算').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).toBeNull()
    expectNoGradeShown()
    expect(screen.queryByText(/盲区/)).toBeNull()
  })

  it('可比行：分数、综合档位与盲区数三者同现', () => {
    render(<RecordRow record={lcRecordToRow(lc())} onOpen={() => {}} />)
    expect(screen.getByText('70')).toBeTruthy()
    expect(screen.getByText(/综合\s+良/)).toBeTruthy()
    expect(screen.getByText('盲区 2 处')).toBeTruthy()
    expect(screen.getByText('真实数据')).toBeTruthy()
  })

  it('配额降级行：与「未联网离线」说不同的话（同一口径不得只留一种说法）', () => {
    const row = lcRecordToRow(
      lc({
        total_score: null,
        data_origin: 'offline',
        degraded: { reason: 'quota', detail: 'total_meltdown', note: '日额度已用尽' },
      }),
    )
    render(<RecordRow record={row} onOpen={() => {}} />)
    expect(screen.getByText('配额降级 · 总量熔断')).toBeTruthy()
    expect(screen.getAllByText('离线估算').length).toBeGreaterThan(0)
    expectNoGradeShown()
  })

  it('调研行：不伪造分数与盲区，域徽标走调研口径', () => {
    const row = researchCardToRow({
      report_id: 'r-1',
      title: '大理亲子游调研',
      query: '大理 5 天亲子游',
      created_at: '2026-09-18T09:30:00',
      evidence_count: 12,
    } as unknown as ReportCard)
    render(<RecordRow record={row} onOpen={() => {}} />)
    expect(screen.getByText('目的地调研')).toBeTruthy()
    expectNoGradeShown()
    expect(screen.queryByText(/盲区/)).toBeNull()
    expect(screen.queryByText('离线估算')).toBeNull()
  })
})

describe('ReportsPage · 无可比评分时统计带整体不渲染', () => {
  it('归档里只有离线估算记录 → 不出现「平均评分」，也不把 null 当 0 计入', async () => {
    vi.resetModules()
    mocks.fetchLifeCircleReports.mockResolvedValue([lc({ total_score: null, data_origin: 'offline' })])
    mocks.fetchReports.mockResolvedValue([])
    const { useDataModeStore } = await import('../store/dataModeStore')
    useDataModeStore.setState({ mode: 'live' })
    const { default: Page } = await import('../pages/ReportsPage')
    const P = Page as ComponentType
    render(
      <MemoryRouter initialEntries={['/reports']}>
        <P />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getAllByText('离线估算').length).toBeGreaterThan(0))
    expect(screen.queryByText('平均评分')).toBeNull()
    expect(screen.queryByText('体检总数')).toBeNull()
  })
})
