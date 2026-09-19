import { create } from 'zustand'
import { createPersister } from '../lib/persist'

/* 界面偏好（当前只有「首页模型选择器」有实际消费方）。

## 修复了什么
修复前 `model` 是**纯内存态**：首页选完模型，一刷新就回到 `Auto`
（见《用户设置持久化架构修复计划》根因 K3 —— 与"用户资料重启丢"同源，
都是用户设置没有持久层的子症状）。

修复后经 `lib/persist.ts` 统一适配层持久化：本地秒开 + 服务端为真相源。

## 消费方（改动本文件须一并回归，见修复计划 §5）
- `pages/HomePage.tsx` 的 `ModelPicker`（选择）与 `submit()`（读取 `model`）
  语义不变：`'Auto'` 仍表示「不覆盖、按 settings 编排」。

## 说明
`sidebarCollapsed / setSidebar / toggleSidebar` 当前**无任何消费方**（历史遗留），
本轮一并纳入持久化（零成本），但**不删除**——避免夹带与本次修复无关的改动。
*/

const LS_KEY = 'verda.ui.v1'

export const DEFAULT_MODEL = 'Auto'

export interface UIData {
  model: string
  sidebarCollapsed: boolean
}

interface UIState extends UIData {
  toggleSidebar: () => void
  setSidebar: (v: boolean) => void
  setModel: (m: string) => void
}

const persister = createPersister<{ model: string; sidebarCollapsed: boolean }>({
  localKey: LS_KEY,
  prefs: { model: 'ui.model', sidebarCollapsed: 'ui.sidebarCollapsed' },
  defaults: { model: DEFAULT_MODEL, sidebarCollapsed: false },
})

export const useUIStore = create<UIState>((set, get) => ({
  ...persister.readLocal(),

  toggleSidebar: () => {
    set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed }))
    persister.persist(get())
  },
  setSidebar: (v) => {
    set({ sidebarCollapsed: v })
    persister.persist(get())
  },
  /* 模型选择器（影响 HomePage 提交时的 model override） */
  setModel: (m) => {
    set({ model: m })
    persister.persist(get())
  },
}))

// 登记到全局水合编排（App.tsx 启动时统一拉远端真相）。
persister.register((remote) => {
  useUIStore.setState((s) => ({ ...s, ...remote }))
})
