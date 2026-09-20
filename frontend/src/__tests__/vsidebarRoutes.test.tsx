// @vitest-environment jsdom
/**
 * B1/B2 · 侧栏「工作台」导航指向 + active 高亮。
 *
 * - B1  NavLink `to='/'`（工作台直通首页统一入口，一词多入口收敛）。
 * - B2  在 `/` 因 end=true 高亮「工作台」；/workspace/:taskId（无侧栏的全屏流水线）与其它路径不高亮。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return { ...actual, fetchDashboard: vi.fn(() => Promise.resolve(null)) }
})

import { useTaskRegistry } from '../store/taskRegistry'
import VSidebar from '../layout/VSidebar'

function renderSidebarAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <VSidebar />
    </MemoryRouter>,
  )
}

beforeEach(() => useTaskRegistry.setState({ tasks: {} }))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('侧栏「工作台」导航', () => {
  it('B1 · 工作台 NavLink href=/（统一入口，而非 /workspace）', () => {
    renderSidebarAt('/')
    const link = screen.getByRole('link', { name: /工作台/ })
    expect(link.getAttribute('href')).toBe('/')
  })

  it('B2 · 在 / 高亮「工作台」（aria-current=page），在 /workspace/:taskId 不高亮', () => {
    const { unmount } = renderSidebarAt('/')
    expect(screen.getByRole('link', { name: /工作台/ }).getAttribute('aria-current')).toBe('page')
    unmount()
    cleanup()
    renderSidebarAt('/workspace/t1')
    expect(screen.getByRole('link', { name: /工作台/ }).hasAttribute('aria-current')).toBe(false)
  })

  it('B2b · 在其它路径（如生活圈）「工作台」不高亮', () => {
    renderSidebarAt('/life-circle/kaili')
    expect(screen.getByRole('link', { name: /工作台/ }).hasAttribute('aria-current')).toBe(false)
  })
})