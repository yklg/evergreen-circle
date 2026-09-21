import { create } from 'zustand'
import type { Expert } from '../types'
import { fetchExperts } from '../lib/api'

interface ExpertState {
  experts: Expert[]
  loaded: boolean
  loading: boolean
  load: () => Promise<void>
  byId: (id: string) => Expert | undefined
  /** 署名解析：报告里的 author 可能是专家 id（竞品域）也可能是姓名（生活圈 D4），两者都要能查到。 */
  resolve: (key: string) => Expert | undefined
}

export const useExpertStore = create<ExpertState>((set, get) => ({
  experts: [],
  loaded: false,
  loading: false,
  load: async () => {
    if (get().loaded || get().loading) return
    set({ loading: true })
    try {
      const experts = await fetchExperts()
      set({ experts, loaded: true, loading: false })
    } catch {
      set({ loading: false })
    }
  },
  byId: (id) => get().experts.find((e) => e.id === id),
  resolve: (key) =>
    get().experts.find((e) => e.id === key || e.name === key || e.nickname === key),
}))
