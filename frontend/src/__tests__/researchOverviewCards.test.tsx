// @vitest-environment jsdom
/**
 * 调研屏 · 每次调研概览的截断可见性（计划 v9 步骤 4b，架构评审的 P0 就在这条上）
 *
 * 为什么单独钉：B 档把 25 份压成 9 张，"看着像全列了"的风险是这次改造自己造出来的。
 * 上一波刚花整波消灭"截断样本冒充全量"，这一波若把截断藏进卡片网格，就是原地复发。
 *
 * 判据形状：
 * - 纯函数 `overviewTruncation` 钉**整句话**（含 P0 用例：后端 `LIMIT 60` 截断时，
 *   按钮名里不得出现库内总数 61 —— 点下去只出 60 张，那句话就是谎）；
 * - 渲染判据走用户入口（`ReportsPage` + mock 的 `lib/api`），数的是**用户真能点到的
 *   删除按钮个数**与屏上真能读到的文案，不是组件内部 state。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import type { ComponentType } from 'react'
import type { IntelOverview, ResearchCard } from '../types'
import { VISIBLE_CARDS, overviewTruncation } from '../pages/reports/overviewTruncation'

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

function card(i: number): ResearchCard {
  return {
    id: `r-${i}`,
    title: `调研 ${i} 号`,
    query: `query ${i}`,
    destinations: [`地${i}`],
    evidence_count: i,
    claim_count: i,
    high_conf_count: i,
    created_at: `2026-09-${String((i % 20) + 1).padStart(2, '0')}T09:00:00`,
  } as ResearchCard
}

function cards(n: number): ResearchCard[] {
  return Array.from({ length: n }, (_, i) => card(i + 1))
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
    // 后端 `_agg_compute` 恒发的两键（口径说明行仅含用户指定信源时非空）
    user_source_evidence: 0,
    distribution_note: '',
    destination_graph: { nodes: [], unattributed: 0, scanned: 12 },
    minutes_saved: 60,
    avg_efficiency: 6,
    avg_coverage: 3,
    total_tokens: 5000,
    cards: [card(1)],
    cards_truncated: false,
    ...over,
  }
}

async function renderTravelTab() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={['/reports?domain=travel']}>
      <Routes>
        <Route path="/reports" element={<P />} />
        <Route path="/report/:id" element={<div data-testid="report" />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** 用 queryAll：本文件既有"恰 9 张"也有"零张"两种计数，getAll 在零个时是抛不是返回空 */
const deleteButtons = () => screen.queryAllByRole('button', { name: '删除目的地调研' })

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.fetchLifeCircleReports.mockResolvedValue([])
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
  mocks.fetchIntel.mockResolvedValue(intelPayload())
})

afterEach(cleanup)

describe('截断说明的唯一出口 overviewTruncation', () => {
  it('没截断 → 一句话都不说（不制造"共 25 份"这种噪音）', () => {
    expect(overviewTruncation(intelPayload({ report_total: 1, cards: cards(1) }))).toBeNull()
    expect(overviewTruncation(intelPayload({ report_total: 9, cards: cards(9) }))).toBeNull()
  })

  it('前端切 9 份 → 说明与按钮名都用库内总数（此时两者等价，按钮不撒谎）', () => {
    const t = overviewTruncation(intelPayload({ report_total: 25, cards: cards(25) }))!
    expect(t.note).toBe(`仅列最近 ${VISIBLE_CARDS} 份（库内共 25 份）`)
    expect(t.expandLabel).toBe('展开全部 25 份')
  })

  it('P0：后端 LIMIT 60 已截断 → 按钮名只能报已取回的份数，不得出现库内总数', () => {
    const t = overviewTruncation(
      intelPayload({ report_total: 61, cards: cards(60), cards_truncated: true }),
    )!
    expect(t.note).toBe(`仅列最近 ${VISIBLE_CARDS} 份（已取回 60 份，库内共 61 份）`)
    expect(t.expandLabel).toBe('展开这 60 份')
    // 显式钉反例：按钮名里出现 61 就意味着点下去少 1 张
    expect(t.expandLabel).not.toContain('61')
  })
})

describe('调研屏 · 概览卡默认只画 9 张且把截断写在脸上', () => {
  it('25 份 → 屏上恰 9 张 + 说明 + 「展开全部 25 份」，点开后 25 张', async () => {
    mocks.fetchIntel.mockResolvedValue(intelPayload({ report_total: 25, cards: cards(25) }))
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    expect(deleteButtons()).toHaveLength(VISIBLE_CARDS)
    expect(screen.getByText(`仅列最近 ${VISIBLE_CARDS} 份（库内共 25 份）`)).toBeTruthy()
    expect(screen.getByText('调研 9 号')).toBeTruthy()
    expect(screen.queryByText('调研 10 号')).toBeNull()
    expect(screen.getByRole('button', { name: '展开全部 25 份' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '展开全部 25 份' }))
    await waitFor(() => expect(deleteButtons()).toHaveLength(25))
    expect(screen.getByText('调研 25 号')).toBeTruthy()
    expect(screen.getByText('当前 25 张 · 已取回 25 份 · 库内 25 份')).toBeTruthy()
  })

  it('后端截断（61/60）→ 屏上按钮写「展开这 60 份」，库内总数只在说明与计数行里', async () => {
    mocks.fetchIntel.mockResolvedValue(
      intelPayload({ report_total: 61, cards: cards(60), cards_truncated: true }),
    )
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    const btn = screen.getByRole('button', { name: '展开这 60 份' })
    expect(btn.textContent).not.toContain('61')
    expect(screen.getByText('仅列最近 9 份（已取回 60 份，库内共 61 份）')).toBeTruthy()

    fireEvent.click(btn)
    await waitFor(() => expect(deleteButtons()).toHaveLength(60))
    // 展开后仍然报得出"库内还有 1 份没取回"，不会被当成全量
    expect(screen.getByText('当前 60 张 · 已取回 60 份 · 库内 61 份')).toBeTruthy()
  })

  it('总数改了，那句话里的数字跟着改（与 report_total 同源，不是写死的 25）', async () => {
    mocks.fetchIntel.mockResolvedValue(intelPayload({ report_total: 40, cards: cards(40) }))
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('仅列最近 9 份（库内共 40 份）')).toBeTruthy())
    expect(screen.getByRole('button', { name: '展开全部 40 份' })).toBeTruthy()
  })

  it('库里零份 → 说"还没有调研报告"并点明不是取数失败，不留一块空白', async () => {
    mocks.fetchIntel.mockResolvedValue(intelPayload({ report_total: 0, cards: [] }))
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    expect(screen.getByText(/库里还没有调研报告/)).toBeTruthy()
    expect(deleteButtons()).toHaveLength(0)
  })
})
