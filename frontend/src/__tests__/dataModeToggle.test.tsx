// @vitest-environment jsdom
/**
 * T3 拍定＝甲 的落地判据：演示态下调研屏挂显式说明态，且**一次请求都不发**。
 *
 * 为什么走侧栏按钮而不是直接改 store：数据模式是用户可观察的开关（侧栏「真实联调 / 演示」），
 * 直接 setState 只测到"store 变了屏会跟着变"，测不到那条按钮到 store 的接线。
 * 这里渲染 VSidebar + 报告中心，点按钮走完整链路。
 *
 * 三条分工：
 * 1. 按钮 → store：点「演示」确实切到 fixture，点「真实联调」切回来；
 * 2. store → 屏：调研屏在 fixture 下出说明文案，八块一块都不渲染；
 * 3. 屏 → 网络：`fetchIntel` / `fetchEvidences` 一次都没被调用（"禁用"是结构性的，
 *    不是取完数再藏起来）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { IntelOverview } from '../types'

const mocks = vi.hoisted(() => ({
  fetchDashboard: vi.fn(),
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
  fetchDashboard: mocks.fetchDashboard,
  fetchLifeCircleReports: mocks.fetchLifeCircleReports,
  fetchIntel: mocks.fetchIntel,
  fetchEvidences: mocks.fetchEvidences,
  fetchSubscriptions: mocks.fetchSubscriptions,
  fetchWorkload: mocks.fetchWorkload,
  createSubscription: mocks.createSubscription,
  deleteReport: mocks.deleteReport,
  deleteLifeCircleReport: mocks.deleteLifeCircleReport,
}))

function intelPayload(): IntelOverview {
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
    cards: [],
    cards_truncated: false,
  }
}

async function renderShell() {
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: VSidebar } = await import('../layout/VSidebar')
  const { default: ReportsPage } = await import('../pages/ReportsPage')
  return render(
    <MemoryRouter initialEntries={['/reports?domain=travel']}>
      <div className="flex">
        <VSidebar />
        <Routes>
          <Route path="/reports" element={<ReportsPage />} />
        </Routes>
      </div>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.fetchDashboard.mockResolvedValue({ reports: 26, evidence_total: 819 })
  mocks.fetchLifeCircleReports.mockResolvedValue([])
  mocks.fetchIntel.mockResolvedValue(intelPayload())
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.resetModules()
})

describe('数据模式开关 → 调研屏（用户入口全链路）', () => {
  it('真实态先出八块屏，点「演示」后换成说明态且不再取数', async () => {
    await renderShell()

    // 真实态：调研屏正常渲染
    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    expect(mocks.fetchIntel).toHaveBeenCalledTimes(1)
    // 切演示之前 C6 是取过证据流的；要钉的是"切过去之后不再发新请求"
    const evidencesBefore = mocks.fetchEvidences.mock.calls.length
    expect(evidencesBefore).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '演示' }))

    const { useDataModeStore } = await import('../store/dataModeStore')
    expect(useDataModeStore.getState().mode).toBe('fixture')

    expect(await screen.findByText('演示模式不含实时调研情报')).toBeTruthy()
    expect(screen.getByText(/点左侧栏「数据模式 · 真实联调」/)).toBeTruthy()
    // 说明态不是八块屏，也不是任何"空"的形态
    expect(screen.queryByText('每次调研概览')).toBeNull()
    expect(screen.queryByText('暂无该类报告')).toBeNull()
    // 切演示之后没有再发过任何情报请求（禁用是结构性的，不是取完再藏）
    expect(mocks.fetchIntel).toHaveBeenCalledTimes(1)
    expect(mocks.fetchEvidences.mock.calls.length).toBe(evidencesBefore)
  })

  it('点「真实联调」切回来：说明态消失、重新取数', async () => {
    await renderShell()
    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '演示' }))
    await screen.findByText('演示模式不含实时调研情报')

    fireEvent.click(screen.getByRole('button', { name: '真实联调' }))
    await waitFor(() => expect(screen.getByText('每次调研概览')).toBeTruthy())
    expect(screen.queryByText('演示模式不含实时调研情报')).toBeNull()
    expect(mocks.fetchIntel.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('生活圈屏在演示态走内置快照，不受调研屏禁用影响', async () => {
    await renderShell()
    fireEvent.click(screen.getByRole('button', { name: '演示' }))
    await screen.findByText('演示模式不含实时调研情报')

    fireEvent.click(screen.getByRole('tab', { name: '生活圈体检' }))
    await waitFor(() => expect(screen.getByRole('tabpanel')).toBeTruthy())
    // 内置快照有两个样区（凯里 / 劲松），列表照常出
    expect(await screen.findByText(/凯里老街 · 生活圈体检报告/)).toBeTruthy()
  })
})
