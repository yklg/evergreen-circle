/**
 * 流水线视图协议（lib/viewRegistry.ts）—— 任务类型 → 展示形态映射（FE E / provider）。
 *
 * 守护不变量「工作台不再因新任务类型空白」：
 * - research / travel_guide / travel_assess → 工作台角色流水线（renderWorkspace=true）
 * - living_circle → 生活圈页引导（renderWorkspace=false + hint）
 * - unknown / 空串 → 归一化到 research（直达/历史/跨设备不空白）
 * - kindForPurpose：guide/assess/'' → travel_guide/travel_assess/research（与后端映射一致）
 */
import { describe, it, expect } from 'vitest'
import { taskViewProvider, kindForPurpose } from '../lib/viewRegistry'

describe('taskViewProvider：kind → 展示形态', () => {
  it('FE·research 家族 → 工作台角色流水线', () => {
    for (const k of ['research', 'travel_guide', 'travel_assess']) {
      const v = taskViewProvider(k)
      expect(v.role, k).toBe('research')
      expect(v.renderWorkspace, k).toBe(true)
      expect(v.hint, k).toBe('')
    }
  })

  it('FE·living_circle → 生活圈页引导（renderWorkspace=false，而非空白）', () => {
    const v = taskViewProvider('living_circle')
    expect(v.role).toBe('life_circle')
    expect(v.renderWorkspace).toBe(false)
    expect(v.hint).toContain('生活圈')
  })

  it('FE·unknown/空串 → 归一化到 research（直达/历史回退不空白）', () => {
    for (const k of ['', null, undefined, 'some_new_kind']) {
      const v = taskViewProvider(k)
      expect(v.renderWorkspace, String(k)).toBe(true)
      expect(v.role, String(k)).toBe('research')
    }
  })
})

describe('kindForPurpose：purpose → kind（与后端 post_task 归一化一致）', () => {
  it('FE·guide/assess/其余 → travel_guide/travel_assess/research', () => {
    expect(kindForPurpose('guide')).toBe('travel_guide')
    expect(kindForPurpose('assess')).toBe('travel_assess')
    expect(kindForPurpose('')).toBe('research')
    expect(kindForPurpose('unknown')).toBe('research')
  })
})