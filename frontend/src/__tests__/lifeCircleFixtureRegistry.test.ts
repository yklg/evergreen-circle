// @vitest-environment node
/**
 * D6 · 演示（fixture）态生活圈任务：replay 事件落 taskRegistry（与真实态同一消费层）。
 *
 * 真实 api.openTaskStream 在 fixture 下走 replayLivingCircleStream（不建 EventSource），
 * 事件形状与真实 SSE 同构 → subscribeLifeCircleTask 的 instrument 照常写入 registry，
 * 最后 report_ready/done 落 markDone。守护「演示与真实共用同一进度事实源」。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useDataModeStore } from '../store/dataModeStore'
import { useTaskRegistry } from '../store/taskRegistry'
import { subscribeLifeCircleTask } from '../lib/lifeCircleFlow'

describe('D6 · fixture replay → registry 单一事实源', () => {
  beforeEach(() => {
    useDataModeStore.setState({ mode: 'fixture' })
    useTaskRegistry.setState({ tasks: {} })
  })

  it(
    '订阅 lc- 任务：回放进度写入 registry（kind/stage/percent），report_ready/done 落 done',
    async () => {
      const close = subscribeLifeCircleTask('lc-fixture-1')
      // 首节事件 0ms 即投递，等回放到终态（eventFlow 末 events 约 index 30 → ~4.5s）
      await waitForStatus('lc-fixture-1', 'done', 12000)
      const r = useTaskRegistry.getState().tasks['lc-fixture-1']
      expect(r).toBeTruthy()
      expect(r.kind).toBe('living_circle')
      expect(r.status).toBe('done')
      expect(r.reportId).toBeTruthy()
      expect(r.percent).toBeGreaterThan(0)
      close()
    },
    15000,
  )
})

/** 轻量 waitFor：轮询 registry 直到某任务达指定状态（fixture 回放有真实 setTimeout 时序）。 */
async function waitForStatus(taskId: string, status: string, timeoutMs: number) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const cur = useTaskRegistry.getState().tasks[taskId]
    if (cur && (cur.status === status || cur.status === 'failed')) return
    await new Promise((r) => setTimeout(r, 100))
  }
  expect.fail(`task ${taskId} 未在 ${timeoutMs}ms 内达到 ${status}`)
}