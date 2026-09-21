// @vitest-environment node
/**
 * openTaskStream 传输层（真实态 EventSource）——架构修复回归保护：
 *
 * 守护「传输层连接语义 ≠ 域级任务终态」：
 * - 收到域级终态 done/error 即 es.close()，切断流正常关闭后 EventSource 自动重连触发的伪 onerror；
 * - 传输层 onerror 提取可读文案（ErrorEvent.message），绝不 String() 成 [object Event] 暴露给用户；
 * - 未达终态的 onerror 走 4s 延迟确认：瞬时抖动（onopen 恢复）不误报失败，持续断网才上报。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../store/dataModeStore', () => ({ isFixtureMode: () => false }))
vi.mock('../mocks/livingCircleStream', () => ({ replayLivingCircleStream: vi.fn(() => () => {}) }))
vi.mock('../mocks/researchStream', () => ({ replayResearchStream: vi.fn(() => () => {}) }))

import { openTaskStream } from '../lib/api'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  readyState = 0 // CONNECTING
  listeners = new Map<string, Set<(e: { type: string; data: string }) => void>>()
  onerror: ((e: unknown) => void) | null = null
  onopen: (() => void) | null = null
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  addEventListener(t: string, cb: (e: { type: string; data: string }) => void) {
    if (!this.listeners.has(t)) this.listeners.set(t, new Set())
    this.listeners.get(t)!.add(cb)
  }
  dispatch(t: string, data: unknown) {
    const e = { type: t, data: JSON.stringify(data) }
    ;(this.listeners.get(t) ?? new Set()).forEach((cb) => cb(e))
  }
  fireError(e: unknown) {
    // SSE 规范：原生连接错误同时触达 es.onerror 与 addEventListener('error')，且 data 缺失
    this.onerror?.(e)
    ;(this.listeners.get('error') ?? new Set()).forEach((cb) => cb({ type: 'error', data: '' }))
  }
  open() {
    this.onopen?.()
  }
  close() {
    this.readyState = 2 // CLOSED
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.useFakeTimers()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const instance = () => {
  const i = FakeEventSource.instances[0]
  if (!i) throw new Error('no EventSource instance')
  return i
}

describe('openTaskStream · 真实态传输语义', () => {
  it('收到域级终态 done → es.close()，且后续传输 onerror 静默（不误报）', () => {
    const onError = vi.fn()
    const onEvent = vi.fn()
    openTaskStream('t-1', { onEvent, onError })
    const s = instance()
    s.dispatch('done', { reportId: 'r-1' })
    expect(s.readyState).toBe(2) // 已 close
    s.fireError({ message: 'Connection reset' })
    vi.advanceTimersByTime(5000)
    expect(onError).not.toHaveBeenCalled()
    expect(onEvent).toHaveBeenCalledWith('done', { reportId: 'r-1' })
  })

  it('收到域级终态 error（服务端推送）同样 es.close() 且不再触发传输 onerror', () => {
    const onError = vi.fn()
    openTaskStream('t-1', { onEvent: vi.fn(), onError })
    const s = instance()
    s.dispatch('error', { message: '配额耗尽' })
    expect(s.readyState).toBe(2)
    s.fireError({ message: 'x' })
    vi.advanceTimersByTime(5000)
    expect(onError).not.toHaveBeenCalled()
  })

  it('收到域级终态 error（服务端推送 JSON）→ 透传 onEvent + es.close()，不再走传输 onerror 误报', () => {
    const onError = vi.fn()
    const onEvent = vi.fn()
    openTaskStream('t-1', { onEvent, onError })
    const s = instance()
    s.dispatch('error', { message: '配额耗尽' })
    expect(onEvent).toHaveBeenCalledWith('error', { message: '配额耗尽' })
    expect(s.readyState).toBe(2) // 域级 error 属终态，已 close
    s.fireError({ message: 'x' })
    vi.advanceTimersByTime(5000)
    expect(onError).not.toHaveBeenCalled()
  })

  it('未达终态的网络失败 → 4s 确认后上报可读文案（ErrorEvent.message），而非 [object Event]', () => {
    const onError = vi.fn()
    openTaskStream('t-1', { onEvent: vi.fn(), onError })
    const s = instance()
    s.fireError(new ErrorEvent('error', { message: 'Connection refused' }))
    expect(onError).not.toHaveBeenCalled() // 延迟确认期间不上报
    vi.advanceTimersByTime(4000)
    expect(onError).toHaveBeenCalledWith('SSE 连接中断：Connection refused')
  })

  it('瞬时抖动：onerror 后 onopen 恢复 → 不上报失败', () => {
    const onError = vi.fn()
    openTaskStream('t-1', { onEvent: vi.fn(), onError })
    const s = instance()
    s.fireError({ message: 'net::ERR_CONNECTION_RESET' })
    s.open() // 自动重连成功
    vi.advanceTimersByTime(5000)
    expect(onError).not.toHaveBeenCalled()
  })

  it('未带可读 message 的传输 onerror → 兜底泛化文案', () => {
    const onError = vi.fn()
    openTaskStream('t-1', { onEvent: vi.fn(), onError })
    instance().fireError({ message: 'Script error.' })
    vi.advanceTimersByTime(4000)
    expect(onError).toHaveBeenCalledWith('SSE 连接中断（网络或服务端不可用），请检查后重试')
  })

  it('主动 close() 清理待确认定时器，不残留 onError', () => {
    const onError = vi.fn()
    const close = openTaskStream('t-1', { onEvent: vi.fn(), onError })
    instance().fireError({ message: 'x' })
    close() // 订阅方在 4s 内主动关闭（如正常收尾）
    vi.advanceTimersByTime(5000)
    expect(onError).not.toHaveBeenCalled()
  })
})