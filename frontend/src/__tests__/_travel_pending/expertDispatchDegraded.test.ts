// @vitest-environment node
/**
 * 专家组队帧的向后兼容与降级可见性（quiet-shore-pike TC-E19）
 *
 * 背景：后端 `_dispatch_experts` 每次都在 LLM 产出不可读时静默返回硬编码兜底名单，
 * 前端因此把「规则凑出来的 6 个人」渲染成与真组队完全一样的专家队，用户看不出差别
 * （现象：48 位专家，永远只有那几个出镜）。Stage A 计划给 SSE 的组队帧加
 * `degraded` 标记（**只走运行流，不进报告 payload**）。
 *
 * 守护契约：
 *   E19a team 帧的既有解析（members → teamMembers）必须容忍未知新增字段，
 *        这样 Stage A 加 `degraded` 时前端可以零改动先不炸；
 *   E19b 组队/派遣帧上的附加字段不得干扰 dispatch 节流队列的出场节奏
 *        （与 dispatchQueue.test.ts 的 Q-F1 同源，防止「加了标记导致气泡丢帧」）；
 *   E19c 降级组队必须在 store 上有可读出口（dispatchDegraded），且真组队不误标、
 *        reset 后归零 —— Stage A 已实施，本组为正式断言。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useTaskStore, DISPATCH_STAGGER_MS } from '../store/taskStore'

const st = () => useTaskStore.getState()

function teamMessage(extra: Record<string, unknown> = {}) {
  st().ingest('message', {
    id: 'm_team',
    kind: 'team',
    expert: 'L3-001',
    members: ['L3-001', 'L2-003', 'L1-012'],
    text: '专家队已就位，开始深度采集。',
    dispatch: [
      { id: 'L3-001', reason: '统筹拆解与终审' },
      { id: 'L1-012', reason: '亲子项目采集' },
    ],
    ...extra,
  })
}

function dispatchFrame(id: string, extra: Record<string, unknown> = {}) {
  st().ingest('thought', {
    id, kind: 'dispatch', expert: `E${id}`, text: `派遣-${id}`,
    ts: '2026-01-01T00:00:00', ...extra,
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  st().reset('task_e19', 'e19')
})
afterEach(() => {
  vi.useRealTimers()
})

describe('组队帧向后兼容', () => {
  it('E19a：team 帧建立 teamMembers，且未知新增字段不影响既有解析', () => {
    teamMessage({ degraded: 'llm_output_unusable', unexpected_field: 42 })
    expect(st().messages.length).toBe(1)
    expect(st().teamMembers).toEqual(['L3-001', 'L2-003', 'L1-012'])
  })

  it('E19a2：无 degraded 的普通 team 帧结果完全相同（扩字段不得改变既有语义）', () => {
    teamMessage()
    expect(st().teamMembers).toEqual(['L3-001', 'L2-003', 'L1-012'])
  })

  it('E19b：派遣帧带 degraded 附加字段时，节流节奏与保序不受影响', () => {
    dispatchFrame('d1', { degraded: 'llm_output_unusable' })
    dispatchFrame('d2')
    dispatchFrame('d3')
    expect(st().thoughts.map((t) => t.text)).toEqual(['派遣-d1'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS)
    expect(st().thoughts.map((t) => t.text)).toEqual(['派遣-d1', '派遣-d2'])
    vi.advanceTimersByTime(DISPATCH_STAGGER_MS)
    expect(st().thoughts.map((t) => t.text)).toEqual(['派遣-d1', '派遣-d2', '派遣-d3'])
  })

  it('E19b2：team 帧本身不入派遣队列（同步上屏，与 Q-F4 同族）', () => {
    dispatchFrame('d1')
    teamMessage({ degraded: 'llm_output_unusable' })
    expect(st().thoughts.length).toBe(1)
    expect(st().messages.length).toBe(1)
  })

  it('E19c：降级组队必须在 store 上有可读出口，供工作台标注', () => {
    teamMessage({ degraded: 'llm_output_unusable' })
    expect(st().dispatchDegraded).toBe('llm_output_unusable')
  })

  it('E19c2：真组队不得留下降级标记（防误标，reset 后回到 null）', () => {
    teamMessage({ degraded: 'llm_output_unusable' })
    expect(st().dispatchDegraded).toBe('llm_output_unusable')
    st().reset('task_e19b', 'e19b')
    expect(st().dispatchDegraded).toBeNull()
    teamMessage({ degraded: '' })
    expect(st().dispatchDegraded).toBeNull()
  })
})
