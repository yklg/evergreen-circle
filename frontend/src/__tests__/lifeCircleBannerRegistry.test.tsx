// @vitest-environment jsdom
/**
 * D5 · LifeCirclePage 真实态进度横幅**经 taskRegistry 渲染**（收敛局部 runState）。
 *
 * 守护：点击「开始体检」→ subscribe 层落 registry（kind=living_circle / running）；
 * 之后 SSE progress 事件经 instrument 写 registry → 横幅从注册表派生 stage/percent 重渲染。
 * 不再依赖页面并行的局部 runStage/runPercent。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import type { ForwardedRef } from 'react'

const { api, hands } = vi.hoisted(() => {
  const openTaskStream = vi.fn((_id: string, _handlers: unknown) => () => {})
  return {
    api: {
      createLivingCircleTask: vi.fn(async () => ({ taskId: 'lc-r1' })),
      fetchLifeCircleReports: vi.fn(async () => [{ id: 'lc-kaili' }]),
      fetchLifeCircleReport: vi.fn(async (_id?: string): Promise<unknown> => null),
      openTaskStream,
    },
    hands: { fire: (_t: string, _d: unknown) => {} },
  }
})

// 在 hoisted 中无法引用 hands，需二次桥接：openTaskStream 实现把 handlers 存到闭包再暴露
vi.mock('../lib/api', () => ({
  createLivingCircleTask: api.createLivingCircleTask,
  fetchLifeCircleReports: api.fetchLifeCircleReports,
  fetchLifeCircleReport: api.fetchLifeCircleReport,
  openTaskStream: api.openTaskStream,
}))

vi.mock('../components/lifecircle/LcMap', async () => {
  const React = await import('react')
  return {
    default: React.forwardRef(function FakeLcMap(_props: unknown, ref: ForwardedRef<unknown>) {
      React.useImperativeHandle(ref, () => ({ locate: async () => null }))
      return React.createElement('div', { 'data-testid': 'fake-lc-map' })
    }),
  }
})

const { default: LifeCirclePage } = await import('../pages/LifeCirclePage')
const { useDataModeStore } = await import('../store/dataModeStore')
const { useTaskRegistry } = await import('../store/taskRegistry')
const { getLivingCircleReportMock } = await import('../mocks/livingCircleReports')

beforeEach(() => {
  useDataModeStore.setState({ mode: 'live' })
  useTaskRegistry.setState({ tasks: {} })
  api.fetchLifeCircleReport.mockResolvedValue(getLivingCircleReportMock('lc-kaili'))
  api.createLivingCircleTask.mockClear()
  // 让 subscribe 捕获 onEvent，供测试注入 SSE progress
  hands.fire = () => {}
  api.openTaskStream.mockImplementation((_id: string, h: any) => {
    hands.fire = (t: string, d: unknown) => h.onEvent(t, d)
    return () => {}
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('D5 · 生活圈进度横幅订阅 registry', () => {
  it('开始体检后：banner 出现；SSE progress 经 registry 驱动 stage/percent 重渲染', async () => {
    render(
      <MemoryRouter initialEntries={['/life-circle/kaili']}>
        <Routes>
          <Route path="/life-circle/:sceneId" element={<LifeCirclePage />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByRole('button', { name: /开始体检/ })

    fireEvent.click(screen.getAllByRole('button', { name: /开始体检/ })[0])

    // banner 出现（registry 已种 running 记录）
    await waitFor(() => expect(screen.getByRole('status')).toBeTruthy())

    // 注入 SSE progress → instrument 写 registry → 横幅派生更新
    hands.fire('progress', { stage: 'collect', percent: 55 })
    await waitFor(() => expect(screen.getByText('生活圈体检进行中 · POI 采集')).toBeTruthy())
    expect(screen.getByRole('status').textContent).toContain('55%')

    // 单一事实源核验：registry 与横幅同源
    const reg = useTaskRegistry.getState().tasks['lc-r1']
    expect(reg).toBeTruthy()
    expect(reg.status).toBe('running')
    expect(reg.stage).toBe('collect')
    expect(reg.percent).toBe(55)
  })
})