// @vitest-environment jsdom
/**
 * F3 · 历史页（DashboardPage 收敛）：VITE_USE_MOCK=1 下为历次体检记录列表
 * （标题/样区/时间/评分/盲区数），点击可打开完整报告。
 * 注意：须在模块求值前 stub 环境（同 homeLifeCircle.test.tsx 模式）。
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

async function renderHistory() {
  vi.resetModules()
  vi.stubEnv('VITE_USE_MOCK', '1')
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

  it('列表含两样区实检记录（评分 65 / 86，盲区 4 / 1）', async () => {
    await renderHistory()
    expect(screen.getAllByText(/凯里老街 · 生活圈体检报告/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/北京劲松 · 生活圈体检报告/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('65').length).toBeGreaterThan(0)
    expect(screen.getAllByText('86').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/盲区 4 处/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/盲区 1 处/).length).toBeGreaterThan(0)
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

  it('演示数据备注提示存在', async () => {
    await renderHistory()
    expect(screen.getByText(/演示数据：含两样区实检/)).toBeTruthy()
  })
})