// @vitest-environment node
/**
 * expertStore 双域隔离契约（FE-14~16 / R5）：
 * - load(domain) 分槽写入；travel 同步顶层镜像，living_circle 不触碰顶层；
 * - 双名册 id 相同人设不同 ⇒ 加载生活圈后旅游槽人名不得被串改；
 * - 按域防重入。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  fetchExperts: vi.fn(),
}))

import { fetchExperts } from '../lib/api'
import { useExpertStore } from '../store/expertStore'

const mocked = fetchExperts as unknown as ReturnType<typeof vi.fn>

const TRAVEL = [
  { id: 'L3-001', name: '温叙白', nickname: '体检总检', level: 'L3', group: 'decision' },
  { id: 'L2-001', name: '旅游专家A', nickname: 'T2', level: 'L2', group: 'industry' },
] as never[]
const LIVING = [
  { id: 'L3-001', name: '温叙白', nickname: '体检总检', level: 'L3', group: 'decision' },
  { id: 'L2-001', name: '生活圈专家B', nickname: 'L2', level: 'L2', group: 'facility' },
] as never[]

beforeEach(() => {
  mocked.mockReset()
  useExpertStore.setState({
    expertsByDomain: {},
    loadedDomains: {},
    loadingDomains: {},
    experts: [],
    loaded: false,
    loading: false,
  })
})

describe('FE-14 · 按域分槽加载', () => {
  it('travel / living_circle 各写各的槽，不共享', async () => {
    mocked.mockImplementation(async (domain: string) =>
      domain === 'living_circle' ? LIVING : TRAVEL,
    )
    await useExpertStore.getState().load('travel')
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.expertsByDomain.travel).toEqual(TRAVEL)
    expect(s.expertsByDomain.living_circle).toEqual(LIVING)
    expect(s.loadedDomains.travel).toBe(true)
    expect(s.loadedDomains.living_circle).toBe(true)
  })
})

describe('FE-15 · 顶层 experts 是 travel 槽镜像（旧消费方兼容）', () => {
  it('加载 travel 后顶层 experts/loaded 同步', async () => {
    mocked.mockResolvedValue(TRAVEL)
    await useExpertStore.getState().load() // 默认 travel
    const s = useExpertStore.getState()
    expect(s.experts).toBe(s.expertsByDomain.travel)
    expect(s.loaded).toBe(true)
    expect(s.byId('L2-001')?.name).toBe('旅游专家A')
  })
})

describe('FE-16 · 串人设守卫：生活圈加载不得覆盖 travel 槽', () => {
  it('先 travel 后 living_circle：顶层 experts 仍是旅游名册', async () => {
    mocked.mockImplementation(async (domain: string) => {
      return domain === 'living_circle' ? LIVING : TRAVEL
    })
    await useExpertStore.getState().load('travel')
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.experts).toEqual(TRAVEL)
    // 生活圈人设不得串到旅游槽
    expect(s.experts[1].name).toBe('旅游专家A')
    // 同 id 在生活圈槽是另一个人
    expect(s.expertsByDomain.living_circle?.[1].name).toBe('生活圈专家B')
  })

  it('先 living_circle（未加载 travel）：顶层 experts 保持空，不被生活圈填充', async () => {
    mocked.mockResolvedValue(LIVING)
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.experts).toEqual([])
    expect(s.loaded).toBe(false)
  })
})

describe('防重入', () => {
  it('同域加载中不重复请求；已加载不重新请求', async () => {
    mocked.mockResolvedValue(TRAVEL)
    await Promise.all([
      useExpertStore.getState().load('travel'),
      useExpertStore.getState().load('travel'),
    ])
    expect(mocked).toHaveBeenCalledTimes(1)
    await useExpertStore.getState().load('travel')
    expect(mocked).toHaveBeenCalledTimes(1)
  })
})
