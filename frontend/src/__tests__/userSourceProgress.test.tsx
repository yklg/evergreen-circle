// @vitest-environment jsdom
/**
 * 工作台「用户指定信源读取」进度条与逐条终态（计划 v3 §二 F1 · §八 TC-45 的界面半边）。
 *
 * 层次分工沿用 workspacePage.test.tsx 的约定：SSE→字段的映射在 store 层钉（本文件第 1 组），
 * 呈现层只测"字段变了界面跟着说对的话"。
 *
 * 为什么映射要在 store 层单独钉：后端对同一条网址发两帧（`reading` → 终态）。
 * 若按 append 处理，列表会随返工轮越滚越长，「正在读取第 k/N 条」就变成假进度。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { useTaskStore } from '../store/taskStore'
import WorkspacePage from '../pages/WorkspacePage'
import { VEvidenceCard } from '../components/VEvidenceFeed'

vi.mock('../hooks/useTaskStream', () => ({ useTaskStream: () => {} }))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useParams: () => ({ taskId: 't_us' }),
    useNavigate: () => vi.fn(),
    useLocation: () => ({ state: { query: '大理亲子游' } }),
  }
})

beforeEach(() => {
  useTaskStore.getState().reset('t_us', '大理亲子游')
})

afterEach(() => cleanup())

const reading = (id: string, url: string, index: number, total: number) => ({
  id, url, index, total, state: 'reading', ts: '2026-09-28T10:00:00',
})
const done = (id: string, url: string, index: number, total: number, state: string, reason = '') => ({
  id, url, index, total, state, reason, bytes: 1024, ms: 800, ts: '2026-09-28T10:00:02',
})

describe('SSE → store 映射（按 uid upsert，不是追加）', () => {
  it('同一条网址的 reading 与终态只占一行', () => {
    const { ingest } = useTaskStore.getState()
    ingest('user_source', reading('u1', 'https://gov.cn/a', 1, 2))
    expect(useTaskStore.getState().userSources.length).toBe(1)
    ingest('user_source', done('u1', 'https://gov.cn/a', 1, 2, 'fetched'))
    const rows = useTaskStore.getState().userSources
    expect(rows.length).toBe(1)
    expect(rows[0].state).toBe('fetched')
  })

  it('返工轮重复回放到读过的条目也不会增殖', () => {
    const { ingest } = useTaskStore.getState()
    for (let round = 0; round < 3; round += 1) {
      ingest('user_source', reading('u1', 'https://gov.cn/a', 1, 1))
      ingest('user_source', done('u1', 'https://gov.cn/a', 1, 1, 'blocked', '内网地址已拒绝'))
    }
    const rows = useTaskStore.getState().userSources
    expect(rows.length).toBe(1)
    expect(rows[0].state).toBe('blocked')
  })

  it('reset 清空逐条态（换任务不能带着上一任务的清单）', () => {
    useTaskStore.getState().ingest('user_source', reading('u1', 'https://gov.cn/a', 1, 1))
    useTaskStore.getState().reset('t_other', '另一个任务')
    expect(useTaskStore.getState().userSources).toEqual([])
  })
})

describe('呈现层', () => {
  function renderWorkspace() {
    return render(
      <MemoryRouter initialEntries={['/workspace/t_us']}>
        <Routes>
          <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('没有用户指定信源时，整块不出现（不是先渲染再藏起来）', () => {
    renderWorkspace()
    expect(screen.queryByText(/用户指定信源读取/)).toBeNull()
  })

  it('逐条终态各自说对的话：入链 / 没读到 / 内网拒绝 / 归并', () => {
    const { ingest } = useTaskStore.getState()
    ingest('user_source', done('u1', 'https://gov.cn/a', 1, 4, 'fetched'))
    ingest('user_source', done('u2', 'https://x.cn/b', 2, 4, 'unread', 'HTTP 404'))
    ingest('user_source', done('u3', 'http://127.0.0.1:8000/api', 3, 4, 'blocked', '内网地址'))
    ingest('user_source', done('u4', 'https://y.cn/c', 4, 4, 'merged'))
    renderWorkspace()

    expect(screen.getByText('已读取入链')).toBeTruthy()
    expect(screen.getByText('没读到')).toBeTruthy()
    expect(screen.getByText('内网/非法地址已拒绝')).toBeTruthy()
    expect(screen.getByText('与既有信源同质 · 已归并')).toBeTruthy()
    expect(screen.getByText('HTTP 404')).toBeTruthy()
    expect(screen.getByText(/4\/4 已有结论/)).toBeTruthy()
  })

  it('读取中的条目显示「正在读取第 k/N 条」', () => {
    const { ingest } = useTaskStore.getState()
    ingest('user_source', reading('u1', 'https://gov.cn/a', 1, 3))
    ingest('user_source', done('u2', 'https://x.cn/b', 2, 3, 'fetched'))
    ingest('user_source', reading('u3', 'https://y.cn/c', 3, 3))
    renderWorkspace()
    expect(screen.getByText('正在读取第 1/3 条')).toBeTruthy()
    expect(screen.getByText('正在读取第 3/3 条')).toBeTruthy()
    expect(screen.getByText('已读取入链')).toBeTruthy()
    // 表头计的是"已有结论"的条数，不是已发出的帧数：u1/u3 仍在读 ⇒ 1/3
    expect(screen.getByText(/已有结论/).textContent).toContain('1/3')
  })

  it('证据卡的用户指定条目显示中文标签而不是裸 key（标签唯一真相源是注册表）', () => {
    render(
      <VEvidenceCard
        ev={{
          evidence_id: 'e1', source_url: 'https://gov.cn/a', source_type: 'user_supplied',
          domain: 'gov.cn', title: '公报', excerpt: 'x', credibility: 60,
          collected_by: 'user_supplied', captured_at: '2026-09-28T10:00:00',
        } as never}
      />,
    )
    expect(screen.getByText('用户指定')).toBeTruthy()
    expect(screen.queryByText('user_supplied')).toBeNull()
  })
})
