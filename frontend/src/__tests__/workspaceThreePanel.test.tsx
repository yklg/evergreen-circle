// @vitest-environment jsdom
/**
 * 工作台三栏集成渲染（G7 / G8）：喂入展示事件后，
 * 专家队 / 实时思维流 / 证据库三栏非空填充；终态 done 自动跳转报告。
 *
 * 经 taskStore.ingest 直接投递事件（绕过真实 SSE，等价「事件已到达」），
 * 验证 WorkspacePage 消费层把 store 状态渲染到三栏 UI——治理空壳回归。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, act, cleanup } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { useTaskStore } from '../store/taskStore'

vi.mock('../hooks/useTaskStream', () => ({ useTaskStream: () => {} }))

import WorkspacePage from '../pages/WorkspacePage'

// framer-motion 在 jsdom 下部分动画 API 需 matchMedia 兜底
if (!window.matchMedia) {
  // @ts-ignore 简化 polyfill，仅满足 framer-motion 读取
  window.matchMedia = (q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })
}

// jsdom 的 Element 无 scrollIntoView；VAgentStream 自动滚底 effect 会调用它
// @ts-ignore 测试径供电，仅补 jsdom 缺失能力
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || vi.fn()

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

function renderWorkspace(taskId = 't1', state: Record<string, string> = {}) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: `/workspace/${taskId}`, state }]}>
      <Routes>
        <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        <Route path="/report/:reportId" element={<div data-testid="report-page">报告页</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('工作台三栏集成渲染（G7）', () => {
  beforeEach(() => {
    useTaskStore.getState().reset('t1', '扫描黄山')
  })

  it('G7 · 事件到达后 专家队 / 思维流 / 证据库 三栏非空', () => {
    const s = useTaskStore.getState()
    // 等价「真实流水线事件已到达」：权威节点集 + 思维 + 专家队 + 证据
    s.ingest('node_update', {
      nodes: ['intake', 'orchestrator', 'collect', 'sentiment', 'write', 'audit', 'done'].map(
        (id, i) => ({ id, label: `阶段${i}`, status: 'idle' }),
      ),
    })
    s.ingest('message', { id: 'm1', kind: 'team', text: '专家队就位', members: ['L3-001', 'L1-003'] })
    s.ingest('thought', { id: 'th1', kind: 'dispatch', expert: 'L3-002', text: '已编排执行专家取证', ts: Date.now() })
    s.ingest('evidence', { evidence_id: 'e1', source_url: 'https://x', credibility: 0.8, title: '交通线索', excerpt: '摘要' })

    renderWorkspace()

    // 专家队计数（Count 由 teamMembers.length 派生，头像解析失败不影响计数）
    expect(screen.getByText(/专家队（2）/)).toBeTruthy()
    // 思维流渲染出 thought 文本
    expect(screen.getByText('已编排执行专家取证')).toBeTruthy()
    // 证据库计数
    expect(screen.getByText(/证据库（1）/)).toBeTruthy()
    // 流水线区标题存在
    expect(screen.getByText(/任务流水线/)).toBeTruthy()
  })
})

describe('工作台终态跳转（G8）', () => {
  beforeEach(() => {
    useTaskStore.getState().reset('t1', '扫描黄山')
  })

  it('G8 · done + reportId 后 1600ms 自动跳 /report/:id', () => {
    vi.useFakeTimers()
    renderWorkspace()

    act(() => {
      useTaskStore.getState().ingest('done', { reportId: 'r1' })
    })

    act(() => {
      vi.advanceTimersByTime(1600)
    })

    expect(screen.getByTestId('report-page')).toBeTruthy()
  })
})