import { create } from 'zustand'
import type { Expert } from '../types'
import { fetchExperts } from '../lib/api'

/**
 * 专家名册按**域**隔离：双名册 id 集合相同但人设不同（travel 行业人设 vs
 * living_circle 设施人设）。各域独立缓存槽，切换加载互不覆盖——
 * 否则首页看生活圈专家墙会把运行中旅游流水线的专家**人名**串掉（R5 域隔离）。
 *
 * 兼容策略：顶层 experts/loaded/loading/byId/resolve 是 **travel 默认槽镜像**，
 * 既有 11 个消费方零改动；新代码需要双域时订阅 expertsByDomain 并调 load(domain)。
 */
export type ExpertDomainName = 'travel' | 'living_circle'
const DEFAULT_DOMAIN: ExpertDomainName = 'travel'

interface ExpertState {
  /** 按域缓存的名册槽 */
  expertsByDomain: Partial<Record<ExpertDomainName, Expert[]>>
  /** 各域是否已加载/加载中（防重入） */
  loadedDomains: Partial<Record<ExpertDomainName, boolean>>
  loadingDomains: Partial<Record<ExpertDomainName, boolean>>
  // ── travel 默认槽镜像（历史接口，保持语义不变）──
  experts: Expert[]
  loaded: boolean
  loading: boolean
  load: (domain?: ExpertDomainName) => Promise<void>
  byId: (id: string) => Expert | undefined
  /** 署名解析：报告里的 author 可能是专家 id 也可能是姓名/昵称，两者都要能查到（travel 名册）。 */
  resolve: (key: string) => Expert | undefined
}

export const useExpertStore = create<ExpertState>((set, get) => ({
  expertsByDomain: {},
  loadedDomains: {},
  loadingDomains: {},
  experts: [],
  loaded: false,
  loading: false,

  load: async (domain: ExpertDomainName = DEFAULT_DOMAIN) => {
    if (get().loadedDomains[domain] || get().loadingDomains[domain]) return
    set((s) => ({ loadingDomains: { ...s.loadingDomains, [domain]: true } }))
    try {
      const list = await fetchExperts(domain)
      set((s) => ({
        expertsByDomain: { ...s.expertsByDomain, [domain]: list },
        loadedDomains: { ...s.loadedDomains, [domain]: true },
        loadingDomains: { ...s.loadingDomains, [domain]: false },
        // travel 槽同步镜像到历史顶层字段；其它域绝不触碰顶层（防串人设）
        ...(domain === DEFAULT_DOMAIN
          ? { experts: list, loaded: true, loading: false }
          : {}),
      }))
    } catch {
      set((s) => ({ loadingDomains: { ...s.loadingDomains, [domain]: false } }))
      if (domain === DEFAULT_DOMAIN) set({ loading: false })
    }
  },

  byId: (id) => get().experts.find((e) => e.id === id),
  resolve: (key) =>
    get().experts.find((e) => e.id === key || e.name === key || e.nickname === key),
}))
