// @vitest-environment jsdom
/**
 * 调研屏 · 专家贡献榜（复刻图三形状后的接缝判据）
 *
 * 钉三件这次真的会漂的东西：
 * 1. **整卡可点**：卡必须是 `link` 且 href 指向 `/experts/:id`（旧形状是 div，不可点）；
 * 2. **层级配色不得长第三份**：仓里已有两份互相冲突的层级色
 *    （`pages/ExpertsPage.tsx:17-21` 硬编码三色 vs `pages/ExpertDetailPage.tsx:58` 读
 *    `badge_color`），而 `ExpertWorkload` 根本没有 `badge_color` ⇒ 本块只准用
 *    `VChip` 的 neutral 面，源码里再出现按层级分色的映射就该红；
 * 3. **静默截断没回来**：旧代码 `.slice(0, 8)` 把出过工的专家砍到 8 位且不报"另有几位"，
 *    这条钉它换件后不再复现。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import type { ComponentType } from 'react'
import type { ExpertWorkload, IntelOverview } from '../types'

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

function workload(i: number): ExpertWorkload {
  return {
    id: `L2-00${i}`,
    name: `专家${i}`,
    title: '行程策略专家',
    layer: i % 2 ? 'L2' : 'L1',
    avatar: `/assets/avatars/L2-00${i}.jpg`,
    missions: 20 - i,
    claims_authored: i,
    evidence_collected: i * 2,
    last_active: '2026-09-20T09:00:00',
  } as ExpertWorkload
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
    cards: [],
    cards_truncated: false,
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
        <Route path="/experts/:id" element={<div data-testid="expert" />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.fetchLifeCircleReports.mockResolvedValue([])
  mocks.fetchIntel.mockResolvedValue(intelPayload())
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
})

afterEach(cleanup)

describe('专家贡献榜 · 整卡可点与报数', () => {
  it('每张卡是指向 /experts/:id 的链接，带层级徽标与三项计数', async () => {
    mocks.fetchWorkload.mockResolvedValue([workload(1), workload(2)])
    await renderTravelTab()

    const link = await screen.findByRole('link', { name: /专家1/ })
    expect(link.getAttribute('href')).toBe('/experts/L2-001')
    expect(screen.getByText('L2')).toBeTruthy()
    expect(within(link).getByText(/19 任务/)).toBeTruthy()
    expect(within(link).getByText(/1 结论/)).toBeTruthy()
    expect(within(link).getByText(/2 证据/)).toBeTruthy()
  })

  it('出过工的专家全数列出：旧的静默 slice(0, 8) 没有跟着复刻过来', async () => {
    mocks.fetchWorkload.mockResolvedValue(Array.from({ length: 11 }, (_, i) => workload(i + 1)))
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('专家1')).toBeTruthy())
    expect(screen.getAllByRole('link', { name: /专家\d+/ })).toHaveLength(11)
    expect(screen.getByText('按真实参与任务量排序 · 11 位出过工')).toBeTruthy()
  })

  it('任务数为 0 的不算"出过工"，且这一句要说清是没人出工而不是取不到', async () => {
    mocks.fetchWorkload.mockResolvedValue([
      workload(1),
      { ...workload(2), missions: 0 },
    ])
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText('专家1')).toBeTruthy())
    expect(screen.queryByText('专家2')).toBeNull()
    expect(screen.getByText('按真实参与任务量排序 · 1 位出过工')).toBeTruthy()
  })

  it('取数失败只在块内报成因，整屏其余块照常（不洗成"没有专家"）', async () => {
    mocks.fetchWorkload.mockRejectedValue(new Error('HTTP 500'))
    await renderTravelTab()

    await waitFor(() => expect(screen.getByText(/专家工作量取数失败/)).toBeTruthy())
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
    expect(screen.getByText('目的地情报图谱')).toBeTruthy()
    expect(screen.queryByText(/位出过工/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(mocks.fetchWorkload).toHaveBeenCalledTimes(2))
  })
})

describe('层级配色只能有一份', () => {
  const REPORT_DIR = join(process.cwd(), 'src', 'pages', 'reports')
  /** 按层级分色的映射指纹：`L1`/`L2`/`L3` 当键去查颜色 */
  const LEVEL_COLOR_MAP = /L[123]\s*:\s*['"`]?(?:text|bg)-/

  it('报告中心各块里不再出现"层级→颜色"的映射（只准用 VChip 现成面）', () => {
    const files = readdirSync(REPORT_DIR).filter((f) => f.endsWith('.tsx'))
    expect(files.length).toBeGreaterThan(3) // 宁可红，不空转
    for (const f of files) {
      expect(
        LEVEL_COLOR_MAP.test(readFileSync(join(REPORT_DIR, f), 'utf8')),
        `${f} 又造了一套层级配色`,
      ).toBe(false)
    }
  })

  it('正对照：本块确实消费 VChip，而不是把层级当纯文本丢掉', () => {
    const src = readFileSync(join(REPORT_DIR, 'ExpertContributionBoard.tsx'), 'utf8')
    expect(src).toMatch(/<VChip/)
    expect(src).toMatch(/from '\.\.\/\.\.\/components\/ui'/)
  })
})
