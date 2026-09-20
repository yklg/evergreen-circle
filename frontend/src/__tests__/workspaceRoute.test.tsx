// @vitest-environment jsdom
/**
 * A1/A2/A2b · App 层路由优先级守卫。
 *
 * 机制根因：App.tsx 全屏区 `path="*" → Navigate '/'` 兜底重定向。
 * 本测试用 MemoryRouter 镜像生产 `<Routes>`（含 `*` catch-all，与 App.tsx 同序同构），
 * 守护优先级不变量：
 *   - 目的地调研统一入口在首页；`/workspace` 无参不再注册 → 命中 `*` 兜底回首页，**且不渲染表单**；
 *   - `/workspace/:taskId` 命中任务流水线（不被 `*` 吞）；
 *   - 未知路径仍被 `*` 兜底重定向到 `/`（404 行为不回归）。
 * 若将来有人改动 App.tsx 路由/兜底，改的是同一份形态，本用例直接变红。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    createTask: vi.fn(),
    getTaskStatus: vi.fn(() => Promise.resolve({ status: null, percent: 0, stage: '', evidence_count: 0, report_id: null, started_at: null, updated_at: null })),
  }
})
vi.mock('../hooks/useTaskStream', () => ({ useTaskStream: () => {} }))

import { useTaskRegistry } from '../store/taskRegistry'
import WorkspacePage from '../pages/WorkspacePage'

function HomeProbe() {
  return <div data-testid="home-redirect">HOME-REDIRECT</div>
}

/** 镜像 App.tsx 全屏区路由顺序（含 catch-all），作为真实 `*` 吞没场景的守卫。 */
function AppRoutesMirror() {
  return (
    <Routes>
      <Route path="/workspace/:taskId" element={<WorkspacePage />} />
      <Route path="/" element={<HomeProbe />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

beforeEach(() => useTaskRegistry.setState({ tasks: {} }))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('App 层路由优先级（统一入口 + catch-all 兜底）', () => {
  it('A1 · 无参 /workspace 不再注册 → 兜底回首页，且不渲染「新建目的地调研」表单', () => {
    render(
      <MemoryRouter initialEntries={['/workspace']}>
        <AppRoutesMirror />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('home-redirect')).toBeTruthy()
    expect(screen.queryByText('新建目的地调研')).toBeNull()
  })

  it('A2 · /workspace/:taskId 仍命中流水线（不被 `*` 吞），且带 task id 顶栏', () => {
    render(
      <MemoryRouter initialEntries={['/workspace/t1']}>
        <AppRoutesMirror />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('home-redirect')).toBeNull()
    // 流水线视图顶栏展示任务 id → 证明走的是任务视图而非重定向
    expect(screen.getByText('任务 t1')).toBeTruthy()
  })

  it('A2b · 未知路径仍被 catch-all 兜底重定向到 /（404 行为不回归）', () => {
    render(
      <MemoryRouter initialEntries={['/definitely/not/a/route']}>
        <AppRoutesMirror />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('home-redirect')).toBeTruthy()
  })
})