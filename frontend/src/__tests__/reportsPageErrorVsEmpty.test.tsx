// @vitest-environment jsdom
/**
 * D4 · 取数失败 ≠ 没有报告（分屏后：每屏各自成立）
 *
 * 缺陷当年（架构评审 v4 事实 7）：`ReportsPage.tsx` 的两条 `.catch(() => {})` 把失败
 * 吞掉，而 `api.ts` 又对列表端点做了空数组兜底 ⇒ **后端 500 与真的一份报告都没有，
 * 在 UI 上完全同形**。当年靠一根 allSettled 同时拉两源，于是还有第三种形态"局部失败"。
 *
 * 双 tab 改造后取数按屏拆开，本文件随之重锚（判据一条不删，只是各钉各的屏）：
 * - 生活圈屏失败不影响调研屏，反之亦然 —— 所以"局部失败"从页面级降成**块级**；
 * - 调研屏的 C6/C7 各是自己的资源：证据流挂了，图谱与概览卡照常渲染，但必须点名"这是没取到"。
 *
 * 取数一律走 `lib/api` 的真实导出：判据前提是失败**能抛到页面**（`api.ts` 已去兜底），
 * 若有人把兜底加回来，第 1 条会立刻变红 —— 这正是 `silentFallbackGuard` 的运行时补位。
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
  for (const m of Object.values(mocks)) m.mockReset()
  mocks.fetchIntel.mockResolvedValue(intelPayload())
  mocks.fetchEvidences.mockResolvedValue({ items: [], facets: { total: 0, by_type: {}, by_destination: {} } })
  mocks.fetchSubscriptions.mockResolvedValue([])
  mocks.fetchWorkload.mockResolvedValue([])
})

/** 真实态渲染报告中心：注入 store 为 live（否则走内置快照，测不到取数分支）。 */
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

async function renderResearchTab() {
  await renderLive('/reports?domain=travel')
  await waitFor(() => expect(mocks.fetchIntel).toHaveBeenCalled())
}

function lcRecord(over: Partial<LifeCircleRecord> = {}): LifeCircleRecord {
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
    ...over,
  } as LifeCircleRecord
}

function intelPayload(over: Partial<IntelOverview> = {}): IntelOverview {
  return {
    report_total: 1,
    evidence_total: 42,
    claim_total: 8,
    high_conf_total: 5,
    avg_evidence_per_report: 42,
    fact_accuracy: 63,
    platform_distribution: { official: 30, news: 12 },
    destination_graph: {
      nodes: [
        {
          destination: '大理',
          domain: 'travel',
          source: 'evidences',
          count: 25,
          source_types: ['official', 'news'],
          avg_credibility: 71.4,
          last_at: '2026-09-18T09:30:00',
        },
      ],
      unattributed: 17,
      scanned: 42,
    },
    minutes_saved: 180,
    avg_efficiency: 6,
    avg_coverage: 3,
    total_tokens: 9000,
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

const LC_EMPTY_COPY = '还没有生活圈体检归档'
const LC_FAILURE_TITLE = '生活圈体检记录取数失败'
const INTEL_FAILURE_TITLE = '目的地调研情报取数失败'
/** 只用于"没有失败线索"的否定判据：正向判据点名具体文案，避免 multiple elements 假失败 */
const FAILURE_HINT = /加载失败|取数失败|读取失败|网络|重试/

describe('生活圈屏：三态各自成立', () => {
  it('取数失败 → 说得出成因并给重试入口，绝不渲染空态，也不连累调研取数', async () => {
    mocks.fetchLifeCircleReports.mockRejectedValue(new Error('HTTP 500'))
    await renderLive()

    await waitFor(() => expect(screen.getByText(LC_FAILURE_TITLE)).toBeTruthy())
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
    expect(screen.queryByText(LC_EMPTY_COPY)).toBeNull()
    // 一屏一源：默认落生活圈 tab，不该白拉调研情报
    expect(mocks.fetchIntel).not.toHaveBeenCalled()
  })

  it('真空列表 → 只有空态文案，没有任何失败线索（两态必须可分辨）', async () => {
    mocks.fetchLifeCircleReports.mockResolvedValue([])
    await renderLive()

    await waitFor(() => expect(screen.getByText(LC_EMPTY_COPY)).toBeTruthy())
    expect(screen.queryByText(FAILURE_HINT)).toBeNull()
  })

  it('重试入口真的重新取数：第二次成功后列表出现', async () => {
    mocks.fetchLifeCircleReports
      .mockRejectedValueOnce(new Error('HTTP 500'))
      .mockResolvedValueOnce([lcRecord()])
    await renderLive()

    await waitFor(() => expect(screen.getByText(LC_FAILURE_TITLE)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy())
    expect(screen.queryByText(FAILURE_HINT)).toBeNull()
  })
})

describe('调研屏：整屏失败与块级失败分开', () => {
  it('/api/intel 失败 → 整屏失败态，不显「暂无调研」，也不白拉生活圈列表', async () => {
    mocks.fetchIntel.mockRejectedValue(new Error('HTTP 500'))
    await renderLive('/reports?domain=travel')

    await waitFor(() => expect(screen.getByText(INTEL_FAILURE_TITLE)).toBeTruthy())
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
    // 失败不得被渲染成"屏在、只是没数据"：八块屏一块都不该出现
    expect(screen.queryByText('每次调研概览')).toBeNull()
    expect(screen.queryByText('暂无该类报告')).toBeNull()
    expect(mocks.fetchLifeCircleReports).not.toHaveBeenCalled()
  })

  it('证据流（C6）挂掉时，图谱与概览卡照常渲染，另给一条块级成因', async () => {
    mocks.fetchEvidences.mockRejectedValue(new Error('HTTP 500'))
    await renderResearchTab()

    expect(screen.getByText('大理亲子游调研')).toBeTruthy()
    expect(screen.getByText('目的地情报图谱')).toBeTruthy()
    await waitFor(() => expect(screen.getByText(/证据流取数失败/)).toBeTruthy())
    // 块级失败不得升级成整屏失败
    expect(screen.queryByText(INTEL_FAILURE_TITLE)).toBeNull()
  })

  it('专家贡献（C7）取数失败只影响那一块，整屏仍在', async () => {
    mocks.fetchWorkload.mockRejectedValue(new Error('HTTP 500'))
    await renderResearchTab()

    await waitFor(() => expect(screen.getByText(/专家工作量取数失败/)).toBeTruthy())
    expect(screen.getByText('目的地情报图谱')).toBeTruthy()
  })
})

/* 演示态（fixture）× 调研屏的判据已搬到 `dataModeToggle.test.tsx`：
   那里从侧栏「演示」按钮点进去，走的是用户入口全链路，而不是直接改 store。 */
