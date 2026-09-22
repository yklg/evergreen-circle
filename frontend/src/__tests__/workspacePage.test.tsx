// @vitest-environment jsdom
/**
 * 工作台降级横幅（计划 §5.4 G20）
 *
 * 层次约定（v6 决定 3）：SSE→字段的映射契约在 taskStore.test.ts 钉；这里只测**呈现**——
 * 组件是否订阅 `planFallback`、横幅是否走温和样式、且不与 error 条混为一谈。
 * 守护的回归是：有人把横幅条件写成 `error`、或把降级文案塞进 error 通道时，此处变红。
 *
 * 做法：mock 掉 useTaskStream（避免真实 SSE 副作用），直接 setState 造 store 状态。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useTaskStore } from '../store/taskStore'
import type { TraceSpan } from '../types'
import { PLAN_FALLBACK_HINT } from '../lib/destinationFallbackCopy'
import WorkspacePage from '../pages/WorkspacePage'

vi.mock('../hooks/useTaskStream', () => ({ useTaskStream: () => {} }))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useParams: () => ({ taskId: 't_ws' }),
    useNavigate: () => vi.fn(),
    useLocation: () => ({ state: { query: '我想去个没去过的安静小城玩三天' } }),
  }
})

beforeEach(() => {
  useTaskStore.getState().reset('t_ws', '我想去个没去过的安静小城玩三天')
})

afterEach(() => cleanup())

/** 一条真实的降级决策 span：字段形状与后端 `_plan_trace` 写入的 lite span 对齐。 */
const TRACE: TraceSpan = {
  span_id: 's1',
  seq: 1,
  agent_id: '',
  stage: 'intake',
  purpose: '目的地集合判定',
  model: '',
  prompt: '候选目的地：（无）；勾选：（无）→ 降级',
  response: '',
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  latency_ms: 1200,
  decision: '自动识别得到候选小城（降级）',
  ts: '2026-09-21T10:00:00',
}

describe('G20 工作台 plan_fallback 温和横幅', () => {
  it('未降级时不渲染横幅文案', () => {
    render(<WorkspacePage />)
    expect(screen.queryByText(PLAN_FALLBACK_HINT)).toBeNull()
    expect(screen.queryByText(/查看决策日志/)).toBeNull()
  })

  it('planFallback=true → 横幅出现，且不出现 error 条文案', () => {
    useTaskStore.setState({ planFallback: true })
    render(<WorkspacePage />)
    expect(screen.getByText(PLAN_FALLBACK_HINT)).toBeTruthy()
    // 温和提示不是故障：error 通道文案不得出现
    expect(screen.queryByText(/采集流中断/)).toBeNull()
    // 运行态保持：横幅不代表任务中断
    expect(screen.getByText('专家队正在集结，马上开始……')).toBeTruthy()
  })

  it('点「查看决策日志」→ 已收起的面板重新展开（revealKey 入口真实生效）', () => {
    useTaskStore.setState({ planFallback: true, traces: [TRACE] })
    const { container } = render(<WorkspacePage />)
    // 先手动收起面板，得到右下角悬浮入口态
    fireEvent.click(screen.getByLabelText('关闭决策日志'))
    expect(screen.getByText('决策日志 · 1')).toBeTruthy()

    // 横幅入口强制揭示：点完必须能看到「目的地集合判定」这条降级决策
    fireEvent.click(screen.getByText('查看决策日志'))
    expect(screen.getByText('Agent 决策日志 · Trace')).toBeTruthy()
    expect(container.textContent).toContain('目的地集合判定')
  })

  it('真实 error 与降级互不遮蔽：两条可同屏，error 条独立渲染', () => {
    useTaskStore.setState({ planFallback: true, error: '模型不可用', running: false })
    render(<WorkspacePage />)
    expect(screen.getByText(PLAN_FALLBACK_HINT)).toBeTruthy()
    expect(screen.getByText(/采集流中断：模型不可用/)).toBeTruthy()
  })
})
