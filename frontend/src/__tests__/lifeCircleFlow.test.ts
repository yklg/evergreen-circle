// @vitest-environment node
/**
 * 生活圈回落 SSE 流（lib/lifeCircleFlow.ts）—— 评审 P1 闭合语义（FE-R5/R6）。
 *
 * 守护一般规则「SSE 全过程强制闭合、错误不挂起、订阅幂等不泄漏」：
 * - progress/message → onProgress；report_ready → 自动取回报告 → onReportReady；error → onError
 * - launchLifeCircle 参数映射：query/center/coord_sys/city 原样透传 createLivingCircleTask
 * - report_ready 取回失败不抛（onReportReady 不触发），不打断其余回调
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    fetchLifeCircleReport: vi.fn(),
    createLivingCircleTask: vi.fn(),
    openTaskStream: vi.fn(),
  }
})

import { fetchLifeCircleReport, createLivingCircleTask, openTaskStream } from '../lib/api' // mocked
import { launchLifeCircle, subscribeLifeCircleTask, __test } from '../lib/lifeCircleFlow'
import { useTaskRegistry } from '../store/taskRegistry'
import type { LivingCircleReport } from '../types'

const onFlowEvent = __test.onFlowEvent

let fireEvent!: (t: string, d: unknown) => void
beforeEach(() => {
  vi.clearAllMocks()
  useTaskRegistry.setState({ tasks: {} })
  ;(createLivingCircleTask as any).mockResolvedValue({ taskId: 'lc-1' })
  ;(openTaskStream as any).mockImplementation((_id: string, handlers: any) => {
    fireEvent = (t: string, d: unknown) => handlers.onEvent(t, d)
    return () => {}
  })
})

describe('onFlowEvent 事件收敛契约', () => {
  it('R5·progress → onProgress(stage, percent)；message → onProgress(message 路径)', () => {
    const cb = { onProgress: vi.fn(), onError: vi.fn(), onReportReady: vi.fn() }
    onFlowEvent('progress', { stage: 'measure', percent: 40 }, cb)
    expect(cb.onProgress).toHaveBeenLastCalledWith('measure', 40, undefined)
    onFlowEvent('message', { text: '采集 POI…' }, cb)
    expect(cb.onProgress).toHaveBeenLastCalledWith('', 0, '采集 POI…')
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('R5·report_ready → 自动取回收报告 → onReportReady(report, reportId)', async () => {
    const report = { dom: 'dummy' } as unknown as LivingCircleReport
    ;(fetchLifeCircleReport as any).mockResolvedValue({ living_circle: report })
    const cb = { onProgress: vi.fn(), onError: vi.fn(), onReportReady: vi.fn() }
    onFlowEvent('report_ready', { reportId: 'r-1' }, cb)
    await vi.waitFor(() => expect(cb.onReportReady).toHaveBeenCalledTimes(1))
    expect(cb.onReportReady).toHaveBeenCalledWith(report, 'r-1')
  })

  it('R6·report_ready 取回为空/失败 → 不触发 onReportReady、不抛错、不打断 error 处理', async () => {
    ;(fetchLifeCircleReport as any).mockResolvedValue(null)
    const cb = { onProgress: vi.fn(), onError: vi.fn(), onReportReady: vi.fn() }
    onFlowEvent('report_ready', { reportId: 'r-miss' }, cb)
    await vi.waitFor(() => expect(fetchLifeCircleReport).toHaveBeenCalled())
    expect(cb.onReportReady).not.toHaveBeenCalled()
  })

  it('R6·error → onError(message)；缺省 message 给兜底文案', () => {
    const cb = { onProgress: vi.fn(), onError: vi.fn(), onReportReady: vi.fn() }
    onFlowEvent('error', { message: '配额耗尽' }, cb)
    expect(cb.onError).toHaveBeenCalledWith('配额耗尽')
    onFlowEvent('error', {}, cb)
    expect(cb.onError).toHaveBeenLastCalledWith('体检任务失败')
  })
})

describe('launchLifeCircle / subscribeLifeCircleTask', () => {
  it('R5·launch 建任务 → 订阅 → 返回 {taskId, close}，参数原样透传（city 不显式注入）', async () => {
    const handle = await launchLifeCircle(
      { query: '凯里老街', center: [107.97, 26.57] as [number, number], coord_sys: 'bd09', city: '' },
      { onProgress: vi.fn() },
    )
    expect(createLivingCircleTask).toHaveBeenCalledWith(
      expect.objectContaining({ query: '凯里老街', center: [107.97, 26.57], coord_sys: 'bd09' }),
    )
    const arg = (createLivingCircleTask as any).mock.calls[0][0] as Record<string, unknown>
    expect(arg).not.toHaveProperty('city') // 城市由后端逆地理，前端不得显式携带
    expect(handle.taskId).toBe('lc-1')
    expect(typeof handle.close).toBe('function')
  })

  it('R6·SSE error 事件 → 页面 onError 降级，不自动 rethrow/挂起', () => {
    const onError = vi.fn()
    const onProgress = vi.fn()
    subscribeLifeCircleTask('lc-1', { onProgress, onError })
    fireEvent('progress', { stage: 'measure', percent: 10 })
    fireEvent('error', { message: '网络中断' })
    expect(onProgress).toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('网络中断')
  })
})

describe('D·registry 单一事实源写入（subscribeLifeCircleTask 收敛层）', () => {
  const reg = () => useTaskRegistry.getState()

  it('D1·progress / evidence → registry.upsert(kind=living_circle, stage, percent, evidence_count)', () => {
    subscribeLifeCircleTask('lc-1', {})
    fireEvent('progress', { stage: 'measure', percent: 30 })
    fireEvent('evidence', { stage: 'measure', evidence: {} })
    const r = reg().tasks['lc-1']
    expect(r).toBeTruthy()
    expect(r.kind).toBe('living_circle')
    expect(r.status).toBe('running')
    expect(r.stage).toBe('measure')
    expect(r.percent).toBe(30)
    expect(r.evidence_count).toBe(1)
  })

  it('D2·report_ready → markDone(taskId, reportId)（同步落终态，无需等 fetch）', () => {
    subscribeLifeCircleTask('lc-1', {})
    fireEvent('report_ready', { reportId: 'r-x' })
    const r = reg().tasks['lc-1']
    expect(r.status).toBe('done')
    expect(r.reportId).toBe('r-x')
  })

  it('D2b·字段兼容：report_id（fixture 演示态）也能 markDone', () => {
    subscribeLifeCircleTask('lc-1', {})
    fireEvent('report_ready', { report_id: 'r-fixture' })
    const r = reg().tasks['lc-1']
    expect(r.status).toBe('done')
    expect(r.reportId).toBe('r-fixture')
  })

  it('D3·error → markFailed', () => {
    subscribeLifeCircleTask('lc-1', {})
    fireEvent('error', { message: '配额耗尽' })
    expect(reg().tasks['lc-1'].status).toBe('failed')
  })

  it('D4·重复 progress 幂等收敛；done 后迟到 progress 不回退 status/percent/stage', () => {
    subscribeLifeCircleTask('lc-1', {})
    fireEvent('progress', { stage: 'measure', percent: 30 })
    fireEvent('progress', { stage: 'collect', percent: 55 })
    fireEvent('report_ready', { reportId: 'r-y' })
    // 终态后漂来的迟到 progress → 忽略
    fireEvent('progress', { stage: 'report', percent: 90 })
    const r = reg().tasks['lc-1']
    expect(r.status).toBe('done')
    expect(r.reportId).toBe('r-y')
    expect(r.percent).toBe(55)
    expect(r.stage).toBe('collect')
  })
})