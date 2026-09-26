// @vitest-environment jsdom
/**
 * 任务 SSE 终态收口测试（修复计划 wise-flint-darter item4 / 覆盖评估 E 组）。
 *
 * 守护的回归：EventSource 规范下服务端关流后浏览器**必然自动重连**；
 * useTaskStream 必须在收到终态帧（done/error）后主动调用 close disposer，
 * 否则即便后端已修好终态契约，页面仍会以极快节奏无限重连（每轮只拿一帧终态）。
 *
 * 做法：mock ../lib/api（沿 clarifyAsync 模式），捕获 handlers 手动驱帧，
 * 断言 close 的调用时机；store 用真实 taskStore 验证文案透传。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act, cleanup } from '@testing-library/react'
import { useTaskStream } from '../hooks/useTaskStream'
import { useTaskStore } from '../store/taskStore'
import * as api from '../lib/api'

const { closeSpy } = vi.hoisted(() => ({ closeSpy: vi.fn() }))

vi.mock('../lib/api', () => ({
  openTaskStream: vi.fn(() => closeSpy),
}))

const mockedOpen = api.openTaskStream as unknown as ReturnType<typeof vi.fn>

function Probe() {
  useTaskStream('t_close_1', '大理 终态测试')
  return null
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function handlers(): any {
  const calls = mockedOpen.mock.calls
  if (!calls.length) throw new Error('openTaskStream 未被调用')
  return calls[0][1]
}

beforeEach(() => {
  mockedOpen.mockClear()
  closeSpy.mockClear()
})

afterEach(() => cleanup())

describe('TC-F1 error 帧 → 主动关流', () => {
  it('error 帧到达：close 恰好一次，真因文案进 store，非终态帧不触发 close', () => {
    render(<Probe />)
    const h = handlers()

    act(() => h.onEvent('progress', { percent: 10, stage: 'collect', evidence_count: 0 }))
    expect(closeSpy).not.toHaveBeenCalled()

    act(() => h.onEvent('error', { message: '博查账户余额不足，请充值' }))
    expect(closeSpy).toHaveBeenCalledTimes(1)
    expect(useTaskStore.getState().error).toBe('博查账户余额不足，请充值')

    // 重连风暴防线：close 后再来帧也不得重复触发（幂等）
    act(() => h.onEvent('error', { message: '再来一帧' }))
    expect(closeSpy).toHaveBeenCalledTimes(1)
  })
})

describe('TC-F2 done 帧 → 同样关流', () => {
  it('done 帧到达：close 一次且置 finished', () => {
    render(<Probe />)
    const h = handlers()
    act(() => h.onEvent('done', { reportId: 'r_done_1' }))
    expect(closeSpy).toHaveBeenCalledTimes(1)
    const s = useTaskStore.getState()
    expect(s.finished).toBe(true)
    expect(s.reportId).toBe('r_done_1')
  })
})

describe('T-F1 done→重载时序在派遣队列冲刷下不回归', () => {
  it('队列尚有积压时 done 到达：余量同步冲刷进 thoughts（不等 500ms 泵）、关流一次、finished 置位', () => {
    vi.useFakeTimers()
    try {
      render(<Probe />)
      const h = handlers()
      const dispatch = (id: string) =>
        h.onEvent('thought', { id, kind: 'dispatch', expert: 'L3-001', text: `派遣-${id}`, ts: 1 })
      act(() => { dispatch('a'); dispatch('b'); dispatch('c') })
      // 首帧即出，其余两条在 500ms 队列里
      expect(useTaskStore.getState().thoughts.map((t) => t.id)).toEqual(['a'])

      act(() => { h.onEvent('done', { reportId: 'r_tf1' }) })
      const s = useTaskStore.getState()
      expect(s.thoughts.map((t) => t.id)).toEqual(['a', 'b', 'c']) // 终态冲刷，无需推进定时器
      expect(closeSpy).toHaveBeenCalledTimes(1)
      expect(s.finished).toBe(true)
      // 冲刷后不残留泵定时器（卸载/回放路径同款防泄漏断言）
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })
})
