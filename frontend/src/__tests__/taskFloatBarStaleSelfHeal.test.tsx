// @vitest-environment jsdom
/**
 * 空任务进度条自愈 + 手动关闭（root-fix 回归）：
 *  - notFound=true（后端明确无此任务）→ 自动回收空壳；
 *  - notFound=false 且 running → 进度 upsert；
 *  - 网络失败/5xx → notFound=false → 不 remove（杜绝误删真实任务）；
 *  - running 卡 X → 手动关闭。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const { getTaskStatusMock } = vi.hoisted(() => ({ getTaskStatusMock: vi.fn() }))
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return { ...actual, getTaskStatus: getTaskStatusMock }
})

import { useTaskRegistry, type TaskRecord } from '../store/taskRegistry'
import TaskFloatBar from '../components/TaskFloatBar'

function runningTask(id: string, percent = 0): TaskRecord {
  return {
    taskId: id,
    query: '黄山',
    kind: 'research',
    purpose: '',
    status: 'running',
    percent,
    evidence_count: 0,
    stage: '',
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    reportId: null,
  }
}

const gone = {
  status: null, percent: 0, stage: '', evidence_count: 0,
  report_id: null, started_at: null, updated_at: null,
}

beforeEach(() => {
  vi.useFakeTimers()
  useTaskRegistry.setState({ tasks: { s1: runningTask('s1') } })
  getTaskStatusMock.mockReset()
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('TaskFloatBar 空进度条自愈 + 手动关闭', () => {
  it('notFound=true → 自动回收空壳（空进度条消失）', async () => {
    getTaskStatusMock.mockResolvedValue({ ...gone, notFound: true })
    render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    await vi.advanceTimersByTimeAsync(3000)
    expect(useTaskRegistry.getState().tasks['s1']).toBeUndefined()
  })

  it('notFound=false 且 running → 进度被 upsert', async () => {
    getTaskStatusMock.mockResolvedValue({ ...gone, status: 'running', percent: 30, stage: 'collect', notFound: false })
    render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    await vi.advanceTimersByTimeAsync(3000)
    expect(useTaskRegistry.getState().tasks['s1']?.percent).toBe(30)
    expect(useTaskRegistry.getState().tasks['s1']?.status).toBe('running')
  })

  it('关键反例：网络失败/5xx → notFound=false → 不 remove，进度原样保留', async () => {
    getTaskStatusMock.mockResolvedValue({ ...gone, notFound: false }) // 暂不可用
    render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    await vi.advanceTimersByTimeAsync(3000)
    expect(useTaskRegistry.getState().tasks['s1']).toBeDefined()
    expect(useTaskRegistry.getState().tasks['s1']?.status).toBe('running')
  })

  it('running 卡点 X → 手动关闭', () => {
    getTaskStatusMock.mockResolvedValue({ ...gone, notFound: false })
    const { container } = render(
      <MemoryRouter>
        <TaskFloatBar />
      </MemoryRouter>,
    )
    const closeBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.getAttribute('title') === '关闭进度条（不删除该任务）',
    ) as HTMLButtonElement
    fireEvent.click(closeBtn)
    expect(useTaskRegistry.getState().tasks['s1'] ?? null).toBeNull()
  })
})