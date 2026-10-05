// @vitest-environment node
/**
 * expertStore 双域隔离契约（FE-14~16 / R5）。
 *
 * 三件事，逐条钉住：
 * - load(domain) 分槽写入，按域防重入；
 * - **不存在"默认域"**：`load/byId/resolve` 的 domain 是必填参数，顶层也不再有
 *   experts/loaded/loading 镜像槽 —— 曾经有（注释写着"既有 11 个消费方零改动"），
 *   而那个镜像就是生活圈页面静默读到旅游人设的入口；
 * - 同一 id 在两域是**两个人**，取错域必须查不到（undefined），而不是查到另一个人。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  fetchExperts: vi.fn(),
}))

import { fetchExperts } from '../lib/api'
import { useExpertStore } from '../store/expertStore'

const mocked = fetchExperts as unknown as ReturnType<typeof vi.fn>

/**
 * 夹具刻意让同 id 在两域是**不同姓名**（真实名册正是如此：L3-002 在两域分别是
 * 林清越 / 许映川）。原先两域都写「温叙白」，等于把最需要区分的形状抹平了。
 */
const TRAVEL = [
  { id: 'L3-001', name: '沈砚', nickname: 'T1', level: 'L3', group: 'decision' },
  { id: 'L2-001', name: '旅游专家A', nickname: 'T2', level: 'L2', group: 'industry' },
] as never[]
const LIVING = [
  { id: 'L3-001', name: '温叙白', nickname: 'L1', level: 'L3', group: 'decision' },
  { id: 'L2-001', name: '生活圈专家B', nickname: 'L2', level: 'L2', group: 'facility' },
] as never[]

beforeEach(() => {
  mocked.mockReset()
  useExpertStore.setState({ expertsByDomain: {}, loadedDomains: {}, loadingDomains: {} })
})

describe('FE-14 · 按域分槽加载', () => {
  it('travel / living_circle 各写各的槽，不共享', async () => {
    mocked.mockImplementation(async (domain: string) => (domain === 'living_circle' ? LIVING : TRAVEL))
    await useExpertStore.getState().load('travel')
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.expertsByDomain.travel).toEqual(TRAVEL)
    expect(s.expertsByDomain.living_circle).toEqual(LIVING)
    expect(s.loadedDomains.travel).toBe(true)
    expect(s.loadedDomains.living_circle).toBe(true)
  })

  it('域是必填参数：签名上不得出现默认值', async () => {
    const st = useExpertStore.getState()
    // 判据取 arity 而非"传 undefined 会怎样"：默认值一回来，新调用点就重新变成
    // "忘记传域也不报错"，而两域同 id 时那只会静默换人名。
    expect(st.load.length, 'load(domain)').toBe(1)
    expect(st.byId.length, 'byId(id, domain)').toBe(2)
    expect(st.resolve.length, 'resolve(key, domain)').toBe(2)
  })

  it('顶层不再有 travel 镜像槽（experts / loaded / loading）', () => {
    // 兼容镜像曾是"零改动迁移"的台阶，实际效果是让所有旧消费方继续读旅游人设。
    // 这里钉它**不存在**：有人再加回 getter，本条就红。
    const s = useExpertStore.getState() as unknown as Record<string, unknown>
    for (const legacy of ['experts', 'loaded', 'loading']) {
      expect(s, `顶层又出现了兼容字段 ${legacy}`).not.toHaveProperty(legacy)
    }
  })
})

describe('FE-16 · 串人设守卫：取错域要查不到，不能查到另一个人', () => {
  it('byId 按域解析：同 id 两域返回不同姓名', async () => {
    mocked.mockImplementation(async (domain: string) => (domain === 'living_circle' ? LIVING : TRAVEL))
    await useExpertStore.getState().load('travel')
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.byId('L3-001', 'travel')?.name).toBe('沈砚')
    expect(s.byId('L3-001', 'living_circle')?.name).toBe('温叙白')
    expect(s.byId('L2-001', 'living_circle')?.name).toBe('生活圈专家B')
  })

  it('未加载的域返回 undefined（不回落另一本名册）', async () => {
    mocked.mockResolvedValue(TRAVEL)
    await useExpertStore.getState().load('travel')
    const s = useExpertStore.getState()
    expect(s.byId('L3-001', 'living_circle')).toBeUndefined()
    expect(s.resolve('沈砚', 'living_circle')).toBeUndefined()
  })

  it('resolve 三种键（id / 姓名 / 昵称）都只在指定域内查', async () => {
    mocked.mockImplementation(async (domain: string) => (domain === 'living_circle' ? LIVING : TRAVEL))
    await useExpertStore.getState().load('travel')
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.resolve('L2-001', 'travel')?.name).toBe('旅游专家A')
    expect(s.resolve('旅游专家A', 'travel')?.id).toBe('L2-001')
    expect(s.resolve('T2', 'travel')?.id).toBe('L2-001')
    expect(s.resolve('生活圈专家B', 'travel')).toBeUndefined()
  })
})

describe('防重入与失败态', () => {
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

  it('取册失败：该域标未加载且不留半成品槽', async () => {
    mocked.mockRejectedValue(new Error('network down'))
    await useExpertStore.getState().load('living_circle')
    const s = useExpertStore.getState()
    expect(s.expertsByDomain.living_circle).toBeUndefined()
    expect(s.loadedDomains.living_circle).toBeFalsy()
    expect(s.loadingDomains.living_circle).toBe(false)
  })
})
