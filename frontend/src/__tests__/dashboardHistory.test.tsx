// @vitest-environment jsdom
/**
 * F3 · 历史页（DashboardPage 收敛）：演示态（fixture）下为历次体检记录列表
 * （标题/样区/时间/评分/盲区数），点击可打开完整报告。
 * 数据模式已运行时化：resetModules 后注入 store 为 fixture（同 homeLifeCircle.test.tsx 模式）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import type { ComponentType } from 'react'

import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'

function PathProbe() {
  const loc = useLocation()
  return <div data-testid="path">{loc.pathname}</div>
}

function lastPath(): string | null {
  const els = screen.queryAllByTestId('path')
  if (!els.length) return null
  return els[els.length - 1]?.textContent ?? null
}

async function renderHistory() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'fixture' }) // 演示态：内置快照记录
  const { default: Page } = await import('../pages/DashboardPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/dashboard" element={<P />} />
        <Route path="/report/:id" element={<PathProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.unstubAllEnvs()
})

afterEach(() => {
  cleanup()
})

describe('DashboardPage · 历史体检记录（mock 态）', () => {
  it('页面骨架：标题 + 副标题', async () => {
    await renderHistory()
    expect(screen.getByRole('heading', { name: /历史体检记录/ })).toBeTruthy()
  })

  it('列表含两样区实检记录（评分/盲区数与快照同源）', async () => {
    await renderHistory()
    expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/北京劲松 · 生活圈体检报告/).length).toBeGreaterThan(0)
    // 断言值从快照派生：重算快照后无需手改测试，但页面读错快照会立刻转红
    for (const f of [kaili, jinsong]) {
      expect(screen.getAllByText(String(f.scores.total)).length).toBeGreaterThan(0)
      expect(screen.getAllByText(new RegExp(`盲区 ${f.blindspots.length} 处`)).length).toBeGreaterThan(0)
    }
  })

  it('体检统计带渲染（体检总数 / 平均评分 / 累计盲区）', async () => {
    await renderHistory()
    expect(screen.getByText('体检总数')).toBeTruthy()
    expect(screen.getByText('平均评分')).toBeTruthy()
    expect(screen.getByText('累计盲区')).toBeTruthy()
  })

  it('点击「打开报告」→ /report/lc-beijing-jinsong', async () => {
    await renderHistory()
    const row = screen.getByText('北京劲松 · 生活圈体检报告').closest('div.rounded-card')
    expect(row).not.toBeNull()
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: /打开报告/ }))
    await waitFor(() => expect(lastPath()).toBe('/report/lc-beijing-jinsong'))
  })

  it('内置快照备注提示存在（真实百度实跑数据）', async () => {
    await renderHistory()
    expect(screen.getByText(/内置快照：两样区真实百度实跑数据/)).toBeTruthy()
  })
})

/**
 * T5 · 离线记录（total_score=null）的降级呈现：0 分与「不可比」必须是两种显示，
 * 否则答辩现场无 AK 分支会出现「陆家嘴 0 分 · 差」的错误举证。
 */
describe('DashboardPage · 离线记录不可比（total_score=null）', () => {
  async function renderOfflineOnly() {
    vi.resetModules()
    vi.doMock('../mocks/livingCircleReports', async () => {
      const actual = await vi.importActual<typeof import('../mocks/livingCircleReports')>('../mocks/livingCircleReports')
      return {
        ...actual,
        getLifeCircleRecords: () => [
          {
            id: 'lc-offline-1',
            title: '陆家嘴 · 生活圈体检报告',
            scene_name: '陆家嘴',
            city: '上海市',
            checked_at: '2026-09-19T00:00:00Z',
            total_score: null,
            blindspot_count: 0,
            data_origin: 'offline',
            interpolation: 'circular_approx',
          },
        ],
      }
    })
    const { useDataModeStore } = await import('../store/dataModeStore')
    useDataModeStore.setState({ mode: 'fixture' })
    const { default: Page } = await import('../pages/DashboardPage')
    const P = Page as ComponentType
    return render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<P />} />
          <Route path="/report/:id" element={<PathProbe />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('null 评分行显示「离线估算」，不显示 0，也不出现评分档位文案', async () => {
    await renderOfflineOnly()
    expect(screen.getAllByText('离线估算').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).toBeNull()
    for (const g of ['优', '良', '中', '差']) expect(screen.queryAllByText(g)).toHaveLength(0)
    // 无一条可比评分 → 统计带整体不渲染（不得把 null 当 0 计入平均）
    expect(screen.queryByText('平均评分')).toBeNull()
    vi.doUnmock('../mocks/livingCircleReports')
  })
})