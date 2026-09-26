// @vitest-environment jsdom
/**
 * taskStore 的 SSE → 状态映射契约（计划 §5.4 G19）。
 *
 * 为什么在 store 层断言而不是只在页面层：横幅的样式属渲染细节，而「哪一帧置哪一个字段」
 * 是数据契约；此前 `src/store/` 下只有 profileStore.test.ts，运行流映射零覆盖。
 * 守护点：plan_fallback 走 message 通道、**不占用** error 通道，且与澄清流的
 * destinations_fallback 字段彼此独立（两字段分属两条流、两个页面）。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useTaskStore } from './taskStore'
import type { SSEEventType } from '../types'

const ingest = (type: SSEEventType, data: unknown) =>
  useTaskStore.getState().ingest(type, data)

beforeEach(() => {
  useTaskStore.getState().reset('t_store', '大理 丽江 攻略')
})

describe('plan_fallback → planFallback', () => {
  it('收到 plan_fallback 消息帧 → planFallback=true，且 error 仍为 null', () => {
    expect(useTaskStore.getState().planFallback).toBe(false)
    ingest('message', {
      id: 'm1',
      kind: 'plan_fallback',
      expert: 'L3-001',
      text: '目的地由自动识别得出（上海），建议核对后再采纳。',
    })
    const s = useTaskStore.getState()
    expect(s.planFallback).toBe(true)
    expect(s.error).toBeNull()
    // 温和提示不改运行态
    expect(s.running).toBe(true)
    expect(s.messages).toHaveLength(1)
  })

  it('其它 kind 的消息帧不置位（不误报降级）', () => {
    ingest('message', { id: 'm1', kind: 'mode', text: '调研类型：游玩攻略', mode: 'deep' })
    ingest('message', { id: 'm2', kind: 'team', members: ['L3-001'] })
    expect(useTaskStore.getState().planFallback).toBe(false)
    expect(useTaskStore.getState().teamMembers).toEqual(['L3-001'])
  })

  it('error 事件只置 error，不联动 planFallback（两条通道互不影响）', () => {
    ingest('error', { message: '模型不可用' })
    const s = useTaskStore.getState()
    expect(s.error).toBe('模型不可用')
    expect(s.running).toBe(false)
    expect(s.planFallback).toBe(false)
  })

  it('澄清流的 destinations_fallback 不影响运行流字段', () => {
    // 澄清载荷即便混进运行流，也不能把两个字段并成一个布尔
    ingest('message', { id: 'm1', kind: 'clarify', destinations_fallback: true })
    ingest('progress', { percent: 10, destinations_fallback: true })
    expect(useTaskStore.getState().planFallback).toBe(false)
  })

  it('reset() 归零 planFallback（换任务不残留上一任务的降级态）', () => {
    ingest('message', { id: 'm1', kind: 'plan_fallback', text: '降级' })
    expect(useTaskStore.getState().planFallback).toBe(true)
    useTaskStore.getState().reset('t_next', '我想去上海玩三天')
    const s = useTaskStore.getState()
    expect(s.planFallback).toBe(false)
    expect(s.messages).toEqual([])
    expect(s.error).toBeNull()
  })
})
