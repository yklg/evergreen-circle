// @vitest-environment node
/**
 * 派遣帧节流队列（F2 / rugged-lagoon-merlin Q-F1~F5）
 *
 * 守护契约（taskStore 层，setTimeout 驱动、fake timers 可测）：
 *   Q-F1 实时 dispatch thought 逐条出队（首条立现，其后每 ~500ms 一条）且保序
 *   Q-F2 done/error 终态冲刷余量，冲刷后不再有迟到帧
 *   Q-F3 回放帧（data.replay）直刷不排队（重连/快照历史不重演动画）
 *   Q-F4 非 dispatch 帧不受队列影响（同步上屏，即使队列在排队中）
 *   Q-F5 reset 丢弃队列并清定时器；flushDispatchQueue 冲刷且清定时器
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useTaskStore, DISPATCH_STAGGER_MS } from '../store/taskStore'

const st = () => useTaskStore.getState()
const texts = () => st().thoughts.map((t) => t.text)

function dispatchFrame(id: string, extra: Record<string, unknown> = {}) {
  st().ingest('thought', { id, kind: 'dispatch', expert: `E${id}`, text: `派遣-${id}`, ts: '2026-01-01T00:00:00', ...extra })
}
function burst(n = 6) {
  for (let i = 1; i <= n; i++) dispatchFrame(`d${i}`)
}

beforeEach(() => {
  vi.useFakeTimers()
  st().reset('task_q', 'q')
})
afterEach(() => {
  vi.useRealTimers()
})

describe('dispatch 节流队列', () => {
  it('Q-F1：6 帧突发 → 首条立现、其后每 500ms 一条且保序', () => {
    burst(6)
    expect(texts()).toEqual(['派遣-d1'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS)
    expect(texts()).toEqual(['派遣-d1', '派遣-d2'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 2)
    expect(texts()).toEqual(['派遣-d1', '派遣-d2', '派遣-d3', '派遣-d4'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(texts()).toEqual(['派遣-d1', '派遣-d2', '派遣-d3', '派遣-d4', '派遣-d5', '派遣-d6'])
    expect(st().thoughts.every((t) => t.kind === 'dispatch')).toBe(true)
  })

  it('Q-F2：done 冲刷余量，全部气泡先于终态上屏；error 同理', () => {
    burst(6)
    st().ingest('done', { reportId: 'r_q' })
    expect(texts().length).toBe(6)
    expect(st().finished).toBe(true)
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(texts().length).toBe(6) // 无迟到重复帧

    st().reset('task_q2', 'q')
    burst(3)
    st().ingest('error', { message: 'boom' })
    expect(texts().length).toBe(3)
    expect(st().error).toBe('boom')
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(texts().length).toBe(3)
  })

  it('Q-F3：replay 标记帧直刷不排队，且不推进后续实时队列', () => {
    burst(4) // 1 立现 + 3 排队
    st().ingest('thought', { id: 'rp1', kind: 'dispatch', text: '回放-1', replay: true })
    st().ingest('thought', { id: 'rp2', kind: 'dispatch', text: '回放-2', replay: true })
    expect(texts()).toEqual(['派遣-d1', '回放-1', '回放-2'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS)
    expect(texts()).toEqual(['派遣-d1', '回放-1', '回放-2', '派遣-d2'])
    const rp = st().thoughts.find((t) => t.id === 'rp1') as unknown as Record<string, unknown>
    expect('replay' in rp).toBe(false) // replay 键不残留在 store
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(texts().length).toBe(6) // 实时余量 d2..d4 正常出场，回放未入队
  })

  it('Q-F4：非 dispatch 帧同步上屏（队列排队中也不被延迟）', () => {
    burst(3)
    st().ingest('thought', { id: 'p1', kind: 'plan', text: '规划' })
    st().ingest('evidence', { evidence_id: 'e1', title: '证据' })
    expect(texts()).toEqual(['派遣-d1', '规划'])
    expect(st().evidences.map((e) => e.evidence_id)).toEqual(['e1'])
    expect(st().thoughts.length).toBe(2)
  })

  it('Q-F5：reset 丢弃队列+清定时器；flushDispatchQueue 冲刷并清定时器', () => {
    burst(4)
    st().reset('task_new', 'q2')
    expect(st().thoughts.length).toBe(0)
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(st().thoughts.length).toBe(0) // 旧定时器已清，无幽灵帧漏进新任务

    burst(4) // 1 立现 + 3 在队
    st().flushDispatchQueue()
    expect(st().thoughts.length).toBe(4)
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS * 10)
    expect(st().thoughts.length).toBe(4) // 定时器已清，不重复追加
  })
})
