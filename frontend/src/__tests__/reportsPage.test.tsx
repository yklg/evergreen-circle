// @vitest-environment jsdom
/**
 * F3 · 报告中心（ReportsPage）：演示态（fixture）下列出体检报告，
 * 类型过滤 + 打开阅读器接线正确。数据模式已运行时化：注入 store 为 fixture。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import type { ComponentType } from 'react'

function PathProbe() {
  const loc = useLocation()
  return <div data-testid="path">{loc.pathname}</div>
}

function lastPath(): string | null {
  const els = screen.queryAllByTestId('path')
  if (!els.length) return null
  return els[els.length - 1]?.textContent ?? null
}

async function renderReports() {
  vi.resetModules()
  const { useDataModeStore } = await import('../store/dataModeStore')
  useDataModeStore.setState({ mode: 'fixture' }) // 演示态：内置快照列表
  const { default: Page } = await import('../pages/ReportsPage')
  const P = Page as ComponentType
  return render(
    <MemoryRouter initialEntries={['/reports']}>
      <Routes>
        <Route path="/reports" element={<P />} />
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

describe('ReportsPage · 报告中心（演示态）', () => {
  it('页面骨架 + 报告类型徽标（生活圈体检）', async () => {
    await renderReports()
    expect(screen.getByRole('heading', { name: /报告中心/ })).toBeTruthy()
    expect(screen.getAllByText('生活圈体检').length).toBeGreaterThan(0)
  })

  it('列出两样区体检报告', async () => {
    await renderReports()
    expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/北京劲松 · 生活圈体检报告/).length).toBeGreaterThan(0)
  })

  it('过滤：切「目的地调研」→ 空态；切回「全部」→ 恢复列表', async () => {
    await renderReports()
    fireEvent.click(screen.getByRole('button', { name: '目的地调研' }))
    expect(screen.getByText('暂无该类报告')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '全部' }))
    expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBeGreaterThan(0)
  })

  it('点击「打开」→ /report/lc-kaili', async () => {
    await renderReports()
    const row = screen.getByText('凯里老街 · 生活圈体检报告').closest('div.rounded-card')
    expect(row).not.toBeNull()
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: /打开/ }))
    await waitFor(() => expect(lastPath()).toBe('/report/lc-kaili'))
  })
})