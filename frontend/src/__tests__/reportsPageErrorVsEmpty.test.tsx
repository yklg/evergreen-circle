// @vitest-environment jsdom
/**
 * D4 · 取数失败 ≠ 没有报告（报告中心真实态）
 *
 * 缺陷当年（架构评审 v4 事实 7）：`ReportsPage.tsx` 的两条 `.catch(() => {})` 把失败
 * 吞掉，而 `api.ts` 又对 `/api/life-circle`、`/api/reports` 做了 `safeJson(...,[])`
 * 空数组兜底 ⇒ **后端 500 / 网络断 与 真的一份报告都没有，在 UI 上完全同形**，都渲染
 * 「暂无该类报告」。用户会以为"我还没做过体检"，而不是"取数出了问题"。
 *
 * 长期保留：波次 A3 已落地三态（失败 / 局部失败 / 空），本文件因此从"挂账"转成
 * "防回退" —— 判据落在用户可观察的结果上（有没有那句成因、能不能重试），
 * 而不是去扫源码里有没有 `.catch`。去掉三态中任何一态都会让它变红。
 *
 * 取数一律走 `lib/api` 的真实导出：判据前提是失败**能抛到页面**（`api.ts` 已去兜底），
 * 若有人把兜底加回来，第 1 条与第 4 条会立刻变红 —— 这正是 `silentFallbackGuard` 的运行时补位。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentType } from 'react'
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

beforeEach(() => {
  mocks.fetchReports.mockReset()
  mocks.fetchLifeCircleReports.mockReset()
  mocks.deleteReport.mockReset()
  mocks.deleteLifeCircleReport.mockReset()
})

/** 真实态渲染报告中心：注入 store 为 live（否则走内置快照，测不到取数分支）。 */
async function renderLive() {
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'live' })
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={['/reports']}>
      <P />
    </MemoryRouter>,
  )
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

function researchCard(over: Partial<ReportCard> = {}): ReportCard {
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
  } as unknown as ReportCard
}

const EMPTY_COPY = '暂无该类报告'
const FAILURE_TITLE = '记录加载失败'
/** 只用于"没有失败线索"的否定判据：正向判据点名具体文案，避免 multiple elements 假失败 */
const FAILURE_HINT = /加载失败|读取失败|网络|重试/

describe('报告中心：真实态取数三态', () => {
  it('两源都失败 → 说得出成因并给重试入口，绝不渲染「暂无该类报告」', async () => {
    mocks.fetchReports.mockRejectedValue(new Error('HTTP 500'))
    mocks.fetchLifeCircleReports.mockRejectedValue(new Error('HTTP 500'))
    await renderLive()

    await waitFor(() => expect(mocks.fetchLifeCircleReports).toHaveBeenCalled())
    expect(screen.getByText(FAILURE_TITLE)).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
    expect(screen.queryByText(EMPTY_COPY)).toBeNull()
  })

  it('真空列表 → 只有空态文案，没有任何失败线索（两态必须可分辨）', async () => {
    mocks.fetchReports.mockResolvedValue([])
    mocks.fetchLifeCircleReports.mockResolvedValue([])
    await renderLive()

    await waitFor(() => expect(screen.getByText(EMPTY_COPY)).toBeTruthy())
    expect(screen.queryByText(FAILURE_HINT)).toBeNull()
  })

  it('重试入口真的重新取数：第二次成功后列表出现', async () => {
    mocks.fetchReports.mockRejectedValueOnce(new Error('HTTP 500')).mockResolvedValueOnce([])
    mocks.fetchLifeCircleReports
      .mockRejectedValueOnce(new Error('HTTP 500'))
      .mockResolvedValueOnce([lcRecord()])
    await renderLive()

    await waitFor(() => expect(screen.getByText(FAILURE_TITLE)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() =>
      expect(screen.getByText('凯里老街 · 生活圈体检报告')).toBeTruthy(),
    )
    expect(screen.queryByText(FAILURE_HINT)).toBeNull()
  })

  it('只有一源失败 → 成功那一侧照常渲染，另给一条局部提示', async () => {
    mocks.fetchReports.mockResolvedValue([researchCard()])
    mocks.fetchLifeCircleReports.mockRejectedValue(new Error('HTTP 500'))
    await renderLive()

    await waitFor(() => expect(screen.getByText('大理亲子游调研')).toBeTruthy())
    expect(screen.getByText(/部分记录加载失败/)).toBeTruthy()
    // 整页失败态不得抢占：局部失败时仍能看到归档内容
    expect(screen.queryByText(FAILURE_TITLE)).toBeNull()
  })
})
