// @vitest-environment jsdom
/**
 * A · 工作台任务流水线 role 守卫（pages/WorkspacePage）。
 *
 * - FE-R3  non-role kind（living_circle，经 taskViewProvider）→ 业务引导而非空白。
 *
 * 目的地调研创建入口已统一到首页（HomePage.ResearchWizard），`/workspace` 现在只承载
 * 带 taskId 的任务流水线，不存在无参「新建调研面板」分支。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    createTask: vi.fn(),
  }
})
vi.mock('../hooks/useTaskStream', () => ({ useTaskStream: () => {} }))

import { useTaskRegistry } from '../store/taskRegistry'
import WorkspacePage from '../pages/WorkspacePage'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('工作台任务流水线 role 守卫', () => {
  beforeEach(() => {
    useTaskRegistry.setState({ tasks: {} })
  })

  it('FE-R3 · non-role kind（living_circle）直达工作台 → 业务引导而非空白', async () => {
    function Go() {
      const nav = useNavigate()
      // 模拟历史遗留：生活圈任务被拿到工作台 URL（state.kind=living_circle）
      setTimeout(() => nav('/workspace/lc-task', { state: { kind: 'living_circle' } }), 0)
      return null
    }
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Go />} />
          <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/生活圈体检请前往/)).toBeTruthy())
  })
})