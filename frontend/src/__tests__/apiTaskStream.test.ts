/**
 * R6 · openTaskStream 真实分支传输层直测（覆盖拓展方案 FE-1~FE-4 / FE-8）。
 *
 * 被测范围：lib/api.ts openTaskStream 的 EventSource 分支（USE_MOCK=false，node 环境）。
 * mock 回放分支（replayLivingCircleStream）由 livingCircleContract.test.ts 覆盖，此处不测。
 *
 * 守护契约（回溯一般规则「SSE 传输层不变量」）：
 * - FE-1  URL 构造：`${API_BASE}/api/tasks/{id}/stream`（测试态 VITE_API_BASE 未设 → 根路径）
 * - FE-2  命名事件 → JSON 解析 → onEvent(type, parsed)；非 JSON 保留原文
 * - FE-3  服务端 error 事件透传 onEvent（P0-1 前端就绪：error 监听必须存在且能解析 {message}）
 * - FE-4  连接失败特征（SSE 规范：原生 error 无 data，且同样派发给 addEventListener('error')）
 *         → onEvent('error', undefined) 与 onError(e) 双派发 —— 消费方必须容忍 data 缺失
 * - FE-8  类型白名单 11 类监听全覆盖（防有人删掉 'error' 等类型）+ close 幂等
 *         注：close 后浏览器保证不再投递，属宿主行为，不做用例（防假绿）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 数据模式已运行时化：本用例直测 EventSource 真实分支，store 默认 live（fixture 分支由契约测试覆盖）
import { openTaskStream } from '../lib/api'
import { useDataModeStore } from '../store/dataModeStore'

type Listener = (ev: { data?: string }) => void

class MockEventSource {
  static instances: MockEventSource[] = []
  static last(): MockEventSource {
    return this.instances[this.instances.length - 1]
  }

  url: string
  readyState = 0
  closed = false
  onopen: (() => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  // 测试桩：public 便于断言监听器注册情况
  listeners: Map<string, Listener[]> = new Map()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, fn: Listener) {
    const arr = this.listeners.get(type) ?? []
    arr.push(fn)
    this.listeners.set(type, arr)
  }

  /** 模拟服务端命名事件（data 为字符串，同浏览器 MessageEvent） */
  emitServer(type: string, data: string) {
    for (const fn of this.listeners.get(type) ?? []) fn({ data })
  }

  /** 模拟连接失败：原生 error 无 data 属性，且 SSE 规范下同样触达 addEventListener('error') */
  emitNativeError() {
    this.onerror?.({})
    for (const fn of this.listeners.get('error') ?? []) fn({})
  }

  close() {
    this.closed = true
    this.readyState = 2
  }
}

describe('openTaskStream 真实分支（传输层契约）', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('FE-1 · URL 构造：/api/tasks/{id}/stream（测试态 VITE_API_BASE 未设 → 根路径）', () => {
    const close = openTaskStream('lc-abc123', { onEvent: () => {} })
    expect(typeof close).toBe('function')
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.last().url).toBe('/api/tasks/lc-abc123/stream')
  })

  it('FE-2 · 命名事件 JSON 解析派发；非 JSON 保留原文', () => {
    const seen: { type: string; data: unknown }[] = []
    openTaskStream('lc-abc123', { onEvent: (t, d) => seen.push({ type: t, data: d }) })
    const es = MockEventSource.last()
    es.emitServer('progress', JSON.stringify({ percent: 40, stage: 'measure', stage_seq: 3 }))
    es.emitServer('message', 'plain-text-not-json')
    expect(seen[0]).toEqual({ type: 'progress', data: { percent: 40, stage: 'measure', stage_seq: 3 } })
    expect(seen[1]).toEqual({ type: 'message', data: 'plain-text-not-json' })
  })

  it('FE-3 · 服务端 error 事件透传 onEvent（P0-1 前端就绪），不触发 onError、不自动关闭', () => {
    const seen: { type: string; data: unknown }[] = []
    const onError = vi.fn()
    openTaskStream('lc-abc123', { onEvent: (t, d) => seen.push({ type: t, data: d }), onError })
    const es = MockEventSource.last()
    es.emitServer('error', JSON.stringify({ message: '配额耗尽' }))
    expect(seen).toEqual([{ type: 'error', data: { message: '配额耗尽' } }])
    expect(onError).not.toHaveBeenCalled()
    expect(es.closed).toBe(false)
  })

  it('FE-4 · 连接失败特征：onEvent("error", undefined) 与 onError 双派发（消费方必须容忍 data 缺失）', () => {
    const onEvent = vi.fn()
    const onError = vi.fn()
    openTaskStream('lc-abc123', { onEvent, onError })
    MockEventSource.last().emitNativeError()
    expect(onEvent).toHaveBeenCalledWith('error', undefined)
    expect(onError).toHaveBeenCalled()
  })

  it('FE-8 · 类型白名单 11 类监听全覆盖（含 error）+ close 幂等', () => {
    const close = openTaskStream('lc-abc123', { onEvent: () => {} })
    const es = MockEventSource.last()
    // 与 api.ts types 数组同步；此断言即同步守卫（任何人删类型必红，尤其 'error'）
    const expected = [
      'node_update',
      'thought',
      'message',
      'evidence',
      'chart',
      'image',
      'progress',
      'trace',
      'report_ready',
      'done',
      'error',
    ]
    for (const t of expected) {
      expect(es.listeners.get(t)?.length ?? 0).toBeGreaterThanOrEqual(1)
    }
    expect(() => {
      close()
      close()
    }).not.toThrow()
    expect(es.closed).toBe(true)
  })
})

describe('openTaskStream 演示态分流（dataMode=fixture，不回归）', () => {
  beforeEach(() => {
    MockEventSource.instances = []
  })
  afterEach(() => {
    useDataModeStore.setState({ mode: 'live' })
  })

  it('非生活圈任务（research）→ replayResearchStream，不建 EventSource', async () => {
    useDataModeStore.setState({ mode: 'fixture' })
    const seen: { type: string; data: unknown }[] = []
    openTaskStream('t-demo-1', { onEvent: (t, d) => seen.push({ type: t, data: d }) }, { purpose: 'guide' })
    expect(MockEventSource.instances).toHaveLength(0), '演示态不得真实连接'
    await new Promise((r) => setTimeout(r, 15))
    expect(seen.length).toBeGreaterThan(0) // 首节 i*speed(i=0) → 0ms 即投递
    expect(seen[0].type).toBe('node_update')
  })

  it('lc-* 生活圈任务 → replayLivingCircleStream，不建 EventSource', async () => {
    useDataModeStore.setState({ mode: 'fixture' })
    openTaskStream('lc-kaili-fx', { onEvent: () => {} })
    expect(MockEventSource.instances).toHaveLength(0)
  })
})
