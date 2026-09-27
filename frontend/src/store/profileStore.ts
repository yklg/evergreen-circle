import { create } from 'zustand'
import { createPersister } from '../lib/persist'

/* 当前用户展示资料（昵称 / 公司）。

## 持久化：服务端为真相源，localStorage 只是秒开缓存

修复前本 store 把 localStorage 当作**唯一**真相源，而 localStorage 按 origin 隔离、
可被浏览器/宿主随时清空、不跨设备 —— 于是出现「重启就重置」（见
《用户设置持久化架构修复计划》根因 K1/K2/K4）。

修复后走 `lib/persist.ts` 统一适配层：
- 同步读 localStorage → 首屏无闪屏、离线可用（`initial`）；
- 启动后 `hydrateAllPrefs()`（见 App.tsx）异步拉 `GET /api/prefs`：
  远端有值 → 远端为准；远端没有（新库 / 首次）→ 保留本地并**自动上推**
  （存量本地资料迁移到服务端，不丢）；
- 每次 mutation：本地即时落盘 + debounce 上推 `PUT /api/prefs`。

## 消费方（改动本文件须一并回归，见修复计划 §5）
- `layout/VSidebar.tsx`：左下角资料卡（昵称/公司/首字头像）+ 编辑弹窗
- `pages/HomePage.tsx`：首页问候语 + 右上角头像
*/

const LS_KEY = 'verda.profile.v1'

export const DEFAULT_NAME = '林研究员'
export const DEFAULT_COMPANY = '常青圈'

export interface ProfileData {
  name: string
  company: string
}

export interface ProfileState extends ProfileData {
  setName: (name: string) => void
  setCompany: (company: string) => void
  setProfile: (p: Partial<ProfileData>) => void
}

/** 语义规整：空白名回落默认值。
 *
 * 刻意放在 spec.normalize 而不是散落在 store 动作里 —— 这样「本地读」与
 * 「远端水合」两条来源共用同一口径，不会出现"本地读会回落、远端读不会"的漂移。
 */
function normalizeProfile(p: ProfileData): ProfileData {
  return {
    name: p.name.trim() ? p.name : DEFAULT_NAME,
    company: p.company.trim() ? p.company : DEFAULT_COMPANY,
  }
}

const persister = createPersister<{ name: string; company: string }>({
  localKey: LS_KEY,
  prefs: { name: 'profile.name', company: 'profile.company' },
  defaults: { name: DEFAULT_NAME, company: DEFAULT_COMPANY },
  normalize: normalizeProfile,
})

export const useProfileStore = create<ProfileState>((set, get) => ({
  ...persister.readLocal(),

  setName: (name) => {
    set({ name })
    persister.persist(get())
  },

  setCompany: (company) => {
    set({ company })
    persister.persist(get())
  },

  setProfile: (p) => {
    set((s) => ({
      name: typeof p.name === 'string' ? p.name : s.name,
      company: typeof p.company === 'string' ? p.company : s.company,
    }))
    persister.persist(get())
  },
}))

// 登记到全局水合编排：App.tsx 启动时调用 hydrateAllPrefs() 统一拉取远端真相。
persister.register((remote) => {
  useProfileStore.setState((s) => ({ ...s, ...remote }))
})
