// @vitest-environment jsdom
/**
 * A3 · 归档删除接线：两域各自走自己的删除端点，且结果可分辨。
 *
 * 为什么单独钉一条（架构评审 v4 事实 4）：`deleteReport` 的唯一消费方原本只有
 * `LibraryPage.tsx`，而那个页面正是要删掉的归档入口。搬迁时若只删页面不把调用点
 * 一起迁过来，`deleteReport` 就成了零消费方导出，报告中心的删除按钮会静默失效；
 * 若两域误用同一端点，删生活圈会打到调研域（后端两张表，打错等于没删）。
 *
 * 双 tab 改造后的两处重锚（判据一条不删）：
 * - 派发到哪条端点由 `lib/domainViews.ts` 的登记表决定，外壳里不再有按域 if/switch；
 * - 调研域的删除入口从"列表行尾"挪到**「每次调研概览」表行尾**（该域现在是仪表盘，没有列表行）。
 *
 * 判据落在用户可观察结果上：点了确认后**哪个 HTTP 端点被调用**、失败时**有没有说人话**。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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

afterEach(cleanup)

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.fetchLifeCircleReports.mockResolvedValue([lcRecord()])
  mocks.fetchIntel.mockResolvedValue(intelPayload())
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
  mocks.deleteReport.mockResolvedValue({ ok: true })
  mocks.deleteLifeCircleReport.mockResolvedValue({ ok: true, deleted: true })
})

function lcRecord(): LifeCircleRecord {
  return {
    id: 'lc-kaili',
    title: '凯里老街 · 生活圈体检报告',
    scene_name: '凯里老街',
    city: '贵州·凯里',
    checked_at: '2026-09-19T20:00:00',
    total_score: 80,
    blindspot_count: 5,
    data_origin: 'live',
    interpolation: 'idw',
  } as LifeCircleRecord
}

function intelPayload(): IntelOverview {
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
  }
}

async function renderLive(initial = '/reports') {
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <P />
    </MemoryRouter>,
  )
}

/** 打开删除确认框，并断言确认文案点名的信息（调研域要点出连带删除的证据量）。 */
async function openConfirm({
  initial,
  anchor,
  buttonLabel,
  expectInWarning,
}: {
  initial: string
  anchor: string
  buttonLabel: string
  expectInWarning: RegExp
}) {
  await renderLive(initial)
  await waitFor(() => expect(screen.getByText(anchor)).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: buttonLabel }))
  await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
  expect(screen.getByText(expectInWarning)).toBeTruthy()
}

describe('报告中心 · 删除归档记录', () => {
  it('确认删除生活圈体检 → 打 /api/life-circle 的删除端点，不打调研域', async () => {
    await openConfirm({
      initial: '/reports',
      anchor: '凯里老街 · 生活圈体检报告',
      buttonLabel: '删除生活圈体检',
      expectInWarning: /重新体检会再次消耗百度配额/,
    })
    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(mocks.deleteLifeCircleReport).toHaveBeenCalledWith('lc-kaili'))
    expect(mocks.deleteReport).not.toHaveBeenCalled()
  })

  it('调研删除入口在「每次调研概览」表行尾，确认后打 /api/reports 并预告连带清除的证据量', async () => {
    await openConfirm({
      initial: '/reports?domain=travel',
      anchor: '大理亲子游调研',
      buttonLabel: '删除目的地调研',
      expectInWarning: /12 条证据/,
    })
    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(mocks.deleteReport).toHaveBeenCalledWith('r-1'))
    expect(mocks.deleteLifeCircleReport).not.toHaveBeenCalled()
  })

  it('删除成功后由这一屏自己重取：登记表决定端点，外壳不出现按域分支', async () => {
    await openConfirm({
      initial: '/reports',
      anchor: '凯里老街 · 生活圈体检报告',
      buttonLabel: '删除生活圈体检',
      expectInWarning: /不可撤销/,
    })
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => expect(mocks.deleteLifeCircleReport).toHaveBeenCalled())
    // 重取走的是这一域的列表端点（第二次及以上）
    await waitFor(() => expect(mocks.fetchLifeCircleReports.mock.calls.length).toBeGreaterThanOrEqual(2))
  })

  it('取消 → 一个删除请求都不发', async () => {
    await openConfirm({
      initial: '/reports',
      anchor: '凯里老街 · 生活圈体检报告',
      buttonLabel: '删除生活圈体检',
      expectInWarning: /不可撤销/,
    })
    fireEvent.click(screen.getByRole('button', { name: '取消' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(mocks.deleteReport).not.toHaveBeenCalled()
    expect(mocks.deleteLifeCircleReport).not.toHaveBeenCalled()
  })

  it('删除失败 → 点名成因并说明记录仍在，不当成已删除', async () => {
    mocks.deleteLifeCircleReport.mockRejectedValue(new Error('HTTP 403'))
    await openConfirm({
      initial: '/reports',
      anchor: '凯里老街 · 生活圈体检报告',
      buttonLabel: '删除生活圈体检',
      expectInWarning: /不可撤销/,
    })
    fireEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(screen.getByText(/删除失败：HTTP 403/)).toBeTruthy())
    expect(screen.getByText(/记录仍在归档里/)).toBeTruthy()
  })
})
