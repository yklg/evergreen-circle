import { create } from 'zustand'
import type { Expert } from '../types'
import { fetchExperts } from '../lib/api'

/**
 * 专家名册按**域**隔离：双名册 id 集合相同但人设不同（travel 行业人设 vs
 * living_circle 设施人设）。各域独立缓存槽，加载互不覆盖。
 *
 * `domain` 是**必填参数**，本文件不留任何"默认域"。理由不是风格：两本名册共用同一套
 * 48 个 id，取错域不会报错、不会 404，只会把人名静默换成另一个人的（生活圈报告曾整批
 * 署成旅游人设，实测 7/7 章；前端也曾把「温叙白·花费与性价比分析师」当成总检签名）。
 * 顶层曾有一组 `experts/byId/resolve` 的 travel 镜像槽用于"零改动兼容"——那正是这个陷阱
 * 的入口，已删除：现在每个消费方都必须写出自己要哪本人设。
 */
export type ExpertDomainName = 'travel' | 'living_circle'

/** 合法域清单（与后端 `app/data.DOMAINS` 同集；端点/静态文件判据共用这一份） */
export const EXPERT_DOMAINS = ['travel', 'living_circle'] as const

interface ExpertState {
  /** 按域缓存的名册槽 */
  expertsByDomain: Partial<Record<ExpertDomainName, Expert[]>>
  /** 各域是否已加载/加载中（防重入） */
  loadedDomains: Partial<Record<ExpertDomainName, boolean>>
  loadingDomains: Partial<Record<ExpertDomainName, boolean>>
  load: (domain: ExpertDomainName) => Promise<void>
  byId: (id: string, domain: ExpertDomainName) => Expert | undefined
  /** 署名解析：报告里的 author 可能是专家 id、姓名或昵称，三者都要能在**指定域**内查到。 */
  resolve: (key: string, domain: ExpertDomainName) => Expert | undefined
}

export const useExpertStore = create<ExpertState>((set, get) => ({
  expertsByDomain: {},
  loadedDomains: {},
  loadingDomains: {},

  load: async (domain: ExpertDomainName) => {
    if (get().loadedDomains[domain] || get().loadingDomains[domain]) return
    set((s) => ({ loadingDomains: { ...s.loadingDomains, [domain]: true } }))
    try {
      const list = await fetchExperts(domain)
      set((s) => ({
        expertsByDomain: { ...s.expertsByDomain, [domain]: list },
        loadedDomains: { ...s.loadedDomains, [domain]: true },
        loadingDomains: { ...s.loadingDomains, [domain]: false },
      }))
    } catch {
      set((s) => ({ loadingDomains: { ...s.loadingDomains, [domain]: false } }))
    }
  },

  byId: (id, domain) => (get().expertsByDomain[domain] ?? []).find((e) => e.id === id),
  resolve: (key, domain) =>
    (get().expertsByDomain[domain] ?? []).find(
      (e) => e.id === key || e.name === key || e.nickname === key,
    ),
}))
