// @vitest-environment node
/**
 * researchFlow 统一发起入口（权威 type 契约）：
 *  - buildResearchQuery：用户原话透传，空值按类型给兜底句（不再用跨域模板包装）；
 *  - launchResearch：createTask(query, depth, undefined, type) + registry 落 running，
 *    purpose 字段仅为演示回放桥（guide/assess 方言）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { launchResearch, buildResearchQuery } from '../lib/researchFlow'
import { useTaskRegistry } from '../store/taskRegistry'

vi.mock('../lib/api', () => ({ createTask: vi.fn() }))
import { createTask } from '../lib/api'

const mockedCreateTask = createTask as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  mockedCreateTask.mockReset()
  useTaskRegistry.setState({ tasks: {} })
})

describe('buildResearchQuery', () => {
  it('用户原话非空 → 原样透传（不包装、不改写）', () => {
    expect(buildResearchQuery('大理 5 天亲子游攻略，含住宿', 'guide'))
      .toBe('大理 5 天亲子游攻略，含住宿')
    expect(buildResearchQuery('评估成都和杭州哪个宜居', 'assessment'))
      .toBe('评估成都和杭州哪个宜居')
  })
  it('空/纯空白输入 → 按类型给兜底句（不抛、不跨域措辞）', () => {
    expect(buildResearchQuery('', 'guide')).toContain('攻略')
    expect(buildResearchQuery('   ', 'assessment')).toContain('评估')
    expect(buildResearchQuery('')).toContain('攻略') // 默认 guide
  })
  it('旧方言 assess 入参同样归一（读宽容）', () => {
    expect(buildResearchQuery('', 'assess')).toContain('评估')
  })
})

describe('launchResearch', () => {
  it('攻略：createTask(query, depth, undefined, guide) 并在 registry 落 running', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't1', kind: 'travel_guide', purpose: 'guide' })
    const r = await launchResearch('大理 5 天亲子游', 'deep', 'guide')
    expect(mockedCreateTask).toHaveBeenCalledWith('大理 5 天亲子游', 'deep', undefined, 'guide')
    expect(r).toEqual({ taskId: 't1', kind: 'travel_guide' })
    const rec = useTaskRegistry.getState().tasks['t1']
    expect(rec?.status).toBe('running')
    expect(rec?.kind).toBe('travel_guide')
    expect(rec?.purpose).toBe('guide')
  })

  it('FE-9 · 演示态评估双写桥：registry kind=travel_assess 且 purpose=assess（喂回放器）', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't2', kind: 'travel_assess', purpose: 'assess' })
    const r = await launchResearch('评估成都和杭州', 'deep', 'assessment')
    expect(mockedCreateTask).toHaveBeenCalledWith('评估成都和杭州', 'deep', undefined, 'assessment')
    expect(r.kind).toBe('travel_assess')
    const rec = useTaskRegistry.getState().tasks['t2']
    expect(rec?.kind).toBe('travel_assess')
    // 演示回放器按 purpose=assess 取评估话术
    expect(rec?.purpose).toBe('assess')
  })

  it('默认参数：depth=deep、type=guide', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't3', kind: 'travel_guide', purpose: 'guide' })
    await launchResearch('大理')
    expect(mockedCreateTask).toHaveBeenCalledWith('大理', 'deep', undefined, 'guide')
  })
})
