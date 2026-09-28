// @vitest-environment jsdom
/**
 * F3 · 报告中心外壳：两个 tab、每域一屏。
 *
 * 数据模式已运行时化：本文件用真实态（live）+ mock 的 `lib/api` 导出，
 * 这样"切 tab 换了数据源"这件事本身就落在判据里（旧形态是一根 allSettled 拉两源，
 * 切过滤条件不换取数）。
 *
 * 钉的四件事：
 * 1. tab 条恰两个、无「全部」，a11y 是 tablist/tab/tabpanel（T8）；
 * 2. 每屏只出自己的内容 —— 两屏共用一份 records 的偷懒实现会被互斥断言打回；
 * 3. 生活圈屏按样区折叠，默认只显最新一份；
 * 4. 深链回落必须响亮（`?domain=all` 已下线）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import type { ComponentType } from 'react'
import type { IntelOverview, LifeCircleRecord } from '../types'

const mocks = vi.hoisted(() => ({
  fetchLifeCircleReports: vi.fn(),
  fetchIntel: vi.fn(),
  fetchEvidences: vi.fn(),
  fetchSubscriptions: vi.fn(),
  fetchWorkload: vi.fn(),
  createSubscription: vi.fn(),
  deleteReport: vi.fn(),
  deleteLifeCircleReport: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
  fetchIntel: mocks.fetchIntel,
  fetchEvidences: mocks.fetchEvidences,
  fetchSubscriptions: mocks.fetchSubscriptions,
  fetchWorkload: mocks.fetchWorkload,
  createSubscription: mocks.createSubscription,
  deleteReport: mocks.deleteReport,
  deleteLifeCircleReport: mocks.deleteLifeCircleReport,
}))

function PathProbe() {
  const loc = useLocation()
  return <div data-testid="path">{loc.pathname}</div>
}

function lc(over: Partial<LifeCircleRecord> = {}): LifeCircleRecord {
  return {
    id: 'lc-kaili',
    title: '凯里老街 · 生活圈体检报告',
    scene_name: '凯里老街',
    city: '贵州·凯里',
    checked_at: '2026-09-19T20:00:00',
    total_score: 68.7,
    blindspot_count: 0,
    data_origin: 'live',
    interpolation: 'idw',
    ...over,
  } as LifeCircleRecord
}

function intelPayload(over: Partial<IntelOverview> = {}): IntelOverview {
  return {
    report_total: 1,
    evidence_total: 12,
    claim_total: 4,
    high_conf_total: 2,
    avg_evidence_per_report: 12,
    fact_accuracy: 50,
    platform_distribution: { official: 12 },
    destination_graph: {
      nodes: [
        {
          destination: '大理',
          domain: 'travel',
          source: 'evidences',
          count: 12,
          source_types: ['official'],
          avg_credibility: 70,
          last_at: '2026-09-18T09:30:00',
        },
      ],
      unattributed: 0,
      scanned: 12,
    },
    minutes_saved: 60,
    avg_efficiency: 6,
    avg_coverage: 3,
    total_tokens: 5000,
    cards: [
      {
        id: 'r-1',
        title: '大理亲子游调研',
        query: '大理 5 天亲子游',
        destinations: ['大理'],
        evidence_count: 12,
        claim_count: 4,
        high_conf_count: 2,
        created_at: '2026-09-18T09:30:00',
      },
    ],
    cards_truncated: false,
    ...over,
  }
}

async function renderReports(initial = '/reports') {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/reports" element={<P />} />
        <Route path="/report/:id" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  // 官渡区两份（一新一旧）、凯里老街一份：折叠形态与分数差都要有样本
  mocks.fetchLifeCircleReports.mockResolvedValue([
    lc(),
    lc({ id: 'lc-old', checked_at: '2026-09-15T20:00:00', total_score: 60 }),
    lc({ id: 'lc-gd', scene_name: '官渡区', city: '昆明市', title: '官渡区 · 生活圈体检报告' }),
  ])
  mocks.fetchIntel.mockResolvedValue(intelPayload())
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
})

afterEach(cleanup)

describe('报告中心 · tab 条', () => {
  it('恰两个 tab、没有「全部」，且默认落生活圈并出列表', async () => {
    await renderReports()
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())

    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    expect(tabs.map((t) => t.textContent)).toEqual(['生活圈体检', '目的地调研'])
    expect(screen.queryByRole('button', { name: '全部' })).toBeNull()
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel')).toBeTruthy()
  })

  it('切到调研 tab → 出该屏独有内容，且生活圈一行都不剩（两屏不共用一份 records）', async () => {
    await renderReports()
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())

    fireEvent.click(screen.getByRole('tab', { name: '目的地调研' }))
    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    expect(screen.getByText('大理亲子游调研')).toBeTruthy()
    expect(screen.queryByText('凯里老街 · 生活圈体检报告')).toBeNull()
    // 切 tab 就是换数据源：调研屏不该继续吃生活圈列表
    expect(mocks.fetchIntel).toHaveBeenCalled()
  })

  it('切回生活圈 → 列表回来，调研内容消失', async () => {
    await renderReports('/reports?domain=travel')
    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())

    fireEvent.click(screen.getByRole('tab', { name: '生活圈体检' }))
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())
    expect(screen.queryByText('大理亲子游调研')).toBeNull()
  })

  it('旧深链 ?domain=all 响亮回落到生活圈 tab（不静默改写）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await renderReports('/reports?domain=all')
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())
    expect(screen.getByRole('tab', { name: '生活圈体检' }).getAttribute('aria-selected')).toBe('true')
    expect(warn.mock.calls.map((c) => String(c[0])).join('\n')).toContain('all')
    warn.mockRestore()
  })
})

describe('报告中心 · 生活圈屏按样区折叠', () => {
  it('同一样区默认只显最新一份，展开才出历史', async () => {
    await renderReports()
    await waitFor(() => expect(screen.getAllByRole('button', { name: /展开看历史/ })).toHaveLength(1))

    // 凯里老街两份：收起态只应看到最新那份的时间
    expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: /展开看历史/ }))
    await waitFor(() => expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBe(2))
  })

  it('组头报出份数与分数差，单份样区不显分数差', async () => {
    await renderReports()
    await waitFor(() => expect(screen.getByText('官渡区')).toBeTruthy())

    const gdGroup = screen.getByText('官渡区').closest('section') as HTMLElement
    expect(within(gdGroup).getByText('1 份')).toBeTruthy()
    expect(within(gdGroup).queryByText(/与最早一次/)).toBeNull()

    const klGroup = screen.getByText('凯里老街').closest('section') as HTMLElement
    expect(within(klGroup).getByText('2 份')).toBeTruthy()
    expect(within(klGroup).getByText('与最早一次 +8.7 分')).toBeTruthy()
  })
})
