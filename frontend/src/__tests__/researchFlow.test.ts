// @vitest-environment node
/**
 * researchFlow 统一发起入口：
 *  - buildResearchQuery 按 purpose 归一（评估/攻略）query 模板（唯一收敛点）；
 *  - launchResearch 调用 createTask 并在 taskRegistry 落 running。
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
  it('purpose=assess → 评估报告模板', () => {
    expect(buildResearchQuery('黄山', 'assess')).toBe('以15分钟便民生活圈视角调研「黄山」，产出评估报告')
  })
  it('purpose=guide → 攻略报告模板', () => {
    expect(buildResearchQuery('大理', 'guide')).toBe('以15分钟便民生活圈视角调研「大理」，产出攻略报告')
  })
  it('默认 purpose → 评估报告', () => {
    expect(buildResearchQuery('凯里老街')).toContain('产出评估报告')
  })
})

describe('launchResearch', () => {
  it('调用 createTask(query, depth, undefined, purpose) 并在 registry 落 running', async () => {
    mockedCreateTask.mockResolvedValue({ taskId: 't1', kind: 'travel_assess' })
    const r = await launchResearch('以15分钟便民生活圈视角调研「黄山」，产出评估报告', 'deep', 'assess')
    expect(mockedCreateTask).toHaveBeenCalledWith(
      '以15分钟便民生活圈视角调研「黄山」，产出评估报告',
      'deep',
      undefined,
      'assess',
    )
    expect(r).toEqual({ taskId: 't1', kind: 'travel_assess' })
    const rec = useTaskRegistry.getState().tasks['t1']
    expect(rec?.status).toBe('running')
    expect(rec?.kind).toBe('travel_assess')
    expect(rec?.purpose).toBe('assess')
  })
})