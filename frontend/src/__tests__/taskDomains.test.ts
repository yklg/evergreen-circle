// @vitest-environment node
/**
 * taskDomains 族注册表契约（R1 单一真相 / R2 写权威读宽容 / R3 family×mode 落地 /
 * R6 注册封闭 fail-loud）。
 * 与 viewRegistry 派生视图同源断言（landing 常量只允许一份）。
 */
import { describe, it, expect } from 'vitest'
import {
  TASK_DOMAINS,
  resolveType,
  resolveTypeOr,
  domainOf,
  familyOf,
  familyOfKind,
  kindOfType,
  kindForDemoPurpose,
  demoPurposeOf,
  submitLanding,
  taskLanding,
  LC_TASK_LANDING_BASE,
} from '../lib/taskDomains'
import { resolveTaskLanding, kindForPurpose, taskViewProvider } from '../lib/viewRegistry'

describe('FE-1 · 三域登记字段齐全', () => {
  it('guide/assessment/living_circle 三行描述符完整', () => {
    for (const type of ['guide', 'assessment', 'living_circle'] as const) {
      const d = TASK_DOMAINS[type]
      expect(d.type).toBe(type)
      expect(['travel', 'living_circle']).toContain(d.family)
      expect(d.kind).toBeTruthy()
      expect(d.examplesKey).toBeTruthy()
      expect(d.queryHint.length).toBeGreaterThan(5)
      expect(['travel', 'living_circle']).toContain(d.expertDomain)
    }
    expect(TASK_DOMAINS.guide.clarifyRequired).toBe(true)
    expect(TASK_DOMAINS.assessment.clarifyRequired).toBe(true)
    expect(TASK_DOMAINS.living_circle.clarifyRequired).toBe(false)
    expect(TASK_DOMAINS.living_circle.demoPurpose).toBeUndefined()
  })
})

describe('FE-2 · 旧方言归一（读宽容）与注册封闭', () => {
  it('assess→assessment；travel_* kind 方言归一到权威 type', () => {
    expect(resolveType('assess')).toBe('assessment')
    expect(resolveType('travel_assess')).toBe('assessment')
    expect(resolveType('travel_guide')).toBe('guide')
    expect(resolveType('guide')).toBe('guide')
    expect(resolveType('living_circle')).toBe('living_circle')
  })

  it('FE-5 · 未登记 type 开发期响亮失败，提示去注册表登记', () => {
    expect(() => resolveType('new_x')).toThrow(/taskDomains/)
    expect(() => resolveType('')).toThrow(/taskDomains/)
    expect(() => resolveType(null)).toThrow(/taskDomains/)
  })

  it('容错读层 resolveTypeOr 未登记回落 fallback 而不抛', () => {
    expect(resolveTypeOr('脏值', 'guide')).toBe('guide')
    expect(resolveTypeOr('assess', 'guide')).toBe('assessment')
  })
})

describe('FE-3 · 落地 = family × dataMode 状态迁移表', () => {
  const id = 't1'
  it('旅游 + 真实态 → /clarify/:id', () => {
    expect(submitLanding('guide', 'live', id)).toBe('/clarify/t1')
    expect(submitLanding('assessment', 'live', id)).toBe('/clarify/t1')
  })
  it('旅游 + 演示态 → /workspace/:id（clarify SSE 无 fixture 分支）', () => {
    expect(submitLanding('guide', 'fixture', id)).toBe('/workspace/t1')
    expect(submitLanding('assessment', 'fixture', id)).toBe('/workspace/t1')
  })
  it('生活圈两态都直达地图 custom（不走问卷）', () => {
    expect(submitLanding('living_circle', 'live', id)).toBe('/life-circle/custom')
    expect(submitLanding('living_circle', 'fixture', id)).toBe('/life-circle/custom')
  })
  it('旧方言输入同样可解析落地（首页 state 脏值容错）', () => {
    expect(submitLanding('assess', 'live', id)).toBe('/clarify/t1')
  })
})

describe('FE-4 · landing 单一来源（viewRegistry 与 taskDomains 字节同源）', () => {
  it('生活圈恢复落地串与既有 taskFloatBarKind 契约字节一致', () => {
    const got = resolveTaskLanding('living_circle', 'lc1')
    expect(got).toBe(`${LC_TASK_LANDING_BASE}?taskId=lc1`)
    expect(got).toBe('/life-circle/kaili?taskId=lc1')
    expect(taskLanding('living_circle', 'lc1')).toBe('/life-circle/kaili?taskId=lc1')
  })
  it('非生活圈 kind 恢复落地进工作台', () => {
    for (const k of ['research', 'travel_guide', 'travel_assess', 'brief']) {
      expect(resolveTaskLanding(k, 't9')).toBe('/workspace/t9')
    }
  })
})

describe('FE-3b · kind / demoPurpose 三方映射', () => {
  it('type→kind；kind→family', () => {
    expect(kindOfType('guide')).toBe('travel_guide')
    expect(kindOfType('assessment')).toBe('travel_assess')
    expect(kindOfType('living_circle')).toBe('living_circle')
    expect(familyOf('guide')).toBe('travel')
    expect(familyOf('living_circle')).toBe('living_circle')
    expect(familyOfKind('travel_assess')).toBe('travel')
    expect(familyOfKind('living_circle')).toBe('living_circle')
    expect(familyOfKind('research')).toBe('travel')
    expect(familyOfKind('unknown_x')).toBe('travel') // 未知 kind 工作台兜底
  })

  it('演示 purpose↔kind 桥：assess 喂回放器仍产出 travel_assess', () => {
    expect(kindForDemoPurpose('assess')).toBe('travel_assess')
    expect(kindForDemoPurpose('guide')).toBe('travel_guide')
    expect(kindForDemoPurpose('')).toBe('research')
    expect(demoPurposeOf('assessment')).toBe('assess')
    expect(demoPurposeOf('guide')).toBe('guide')
    // viewRegistry 旧导出名与新实现同源
    expect(kindForPurpose('assess')).toBe('travel_assess')
  })
})

describe('FE-3c · viewRegistry 派生视图不回退', () => {
  it('注册表 kind 全部有 TaskView；旅游族进工作台、生活圈显引导', () => {
    expect(taskViewProvider('travel_guide').renderWorkspace).toBe(true)
    expect(taskViewProvider('travel_assess').role).toBe('research')
    const lc = taskViewProvider('living_circle')
    expect(lc.renderWorkspace).toBe(false)
    expect(lc.role).toBe('life_circle')
    // 未知 kind 回落 research（不空白）
    expect(taskViewProvider('什么鬼')).toEqual(taskViewProvider('research'))
  })
})
