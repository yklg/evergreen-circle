// @vitest-environment jsdom
/**
 * D7/D8/D9 · TaskFloatBar 对 kind 的分流（回归阻断）：living_circle 不再被误接管到工作台。
 *
 * - D7  living_circle running → 文案「生活圈体检中」，点击回落生活圈页（?taskId=）而非 /workspace/:id。
 * - D8  research/travel_* running → 仍跳 /workspace/:id（不回归）。
 * - D9  living_circle done（带 report_id）→ 跳 /report/:reportId；failed → 关闭。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { fireEvent, render, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    getTaskStatus: vi.fn(() =>
      Promise.resolve({ status: null, percent: 0, stage: '', evidence_count: 0, report_id: null, started_at: null, updated_at: null }),
    ),
  }
})

const { nav } = vi.hoisted(() => ({ nav: { to: '' } }))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => (to: string) => {
      nav.to = to
    },
  }
})

import { useTaskRegistry, type TaskRecord } from '../store/taskRegistry'
import TaskFloatBar from '../components/TaskFloatBar'

function seed(task: TaskRecord) {
  useTaskRegistry.setState({ tasks: { [task.taskId]: task } })
}

beforeEach(() => {
  useTaskRegistry.setState({ tasks: {} })
  nav.to = ''
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('TaskFloatBar kind 分流', () => {
  it('D7 · living_circle running → 「生活圈体检中」，点击回落生活圈页（?taskId=）', () => {
    seed({
      taskId: 'lc1',
      query: '凯里老街',
      kind: 'living_circle',
      purpose: 'living_circle',
      status: 'running',
      percent: 40,
      evidence_count: 3,
      stage: 'measure',
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      reportId: null,
    })
    render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    fireEvent.click(document.querySelector('button') as HTMLButtonElement)
    expect(nav.to).toBe('/life-circle/kaili?taskId=lc1')
  })

  it('D8 · research/travel_* running → 仍跳 /workspace/:id（不回归）', () => {
    seed({
      taskId: 't2',
      query: '黄山',
      kind: 'travel_guide',
      purpose: 'guide',
      status: 'running',
      percent: 20,
      evidence_count: 1,
      stage: 'collect',
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      reportId: null,
    })
    render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    fireEvent.click(document.querySelector('button') as HTMLButtonElement)
    expect(nav.to).toBe('/workspace/t2')
  })

  it('D9 · living_circle done(带 report_id) → 跳 /report/:reportId', () => {
    seed({
      taskId: 'lc-done',
      query: '凯里老街',
      kind: 'living_circle',
      purpose: 'living_circle',
      status: 'done',
      percent: 100,
      evidence_count: 12,
      stage: 'audit',
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      reportId: 'r-lc-001',
    })
    const { container } = render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    // finished 项内层「报告已就绪 · 点击查看」按钮驱动跳转
    const doneBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('报告已就绪'),
    ) as HTMLButtonElement
    fireEvent.click(doneBtn)
    expect(nav.to).toBe('/report/r-lc-001')
  })
})