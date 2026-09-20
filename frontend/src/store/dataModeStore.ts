/**
 * 数据模式运行时开关（C1）：`live`（真实联调，连后端 /api）与 `fixture`（内置快照演示）。
 *
 * 背景：原 `VITE_USE_MOCK` / `VITE_LC_DATA_MODE` 是构建期环境变量，切换需改 .env 重启。
 * 本 store 把「数据模式」提升为运行时状态（与后端 `get_data_source(mode)` 的 data_mode 同轴命名）：
 *   - 侧边栏「数据模式」tab 点击即时切换全局生效；
 *   - localStorage 轻量持久化（`verda.dataMode.v1`），刷新后保持上次选择（真实成为常态）；
 *   - 命名与后端契约对齐：live=真实路网/离线估算链路，fixture=内置演示数据源。
 *
 * 持久化刻意**不引 lib/persist.ts**（那是用户偏好层，会上推 /api/prefs 并参与全局水合；
 * 数据模式是环境态而非用户偏好，且引入会形成 dataModeStore→persist→api→dataModeStore 循环依赖）。
 *
 * 消费方：组件用 `useDataModeStore((s) => s.mode === 'fixture')` 订阅（即时重渲染）；
 *        api.ts 等非组件模块用 `isFixtureMode()` 取快照。
 */
import { create } from 'zustand'

export type DataMode = 'live' | 'fixture'

const LS_KEY = 'verda.dataMode.v1'

function readLocal(): DataMode | null {
  try {
    const v = localStorage.getItem(LS_KEY)
    return v === 'live' || v === 'fixture' ? v : null
  } catch {
    return null // 隐私模式 / 禁用存储：回退默认，绝不抛错
  }
}

function writeLocal(m: DataMode): void {
  try {
    localStorage.setItem(LS_KEY, m)
  } catch {
    // 忽略：无持久化能力时仅本次会话生效
  }
}

/** 初始默认：本地持久化优先；其次构建期 VITE_USE_MOCK（老配置/测试兼容）；否则 live。 */
const INITIAL: DataMode = readLocal() ?? (import.meta.env.VITE_USE_MOCK === '1' ? 'fixture' : 'live')

interface DataModeState {
  mode: DataMode
  setMode: (m: DataMode) => void
}

export const useDataModeStore = create<DataModeState>((set) => ({
  mode: INITIAL,
  setMode: (mode) => {
    set({ mode })
    writeLocal(mode)
  },
}))

/** 非组件模块（lib/api.ts 等）读取当前模式快照。 */
export const isFixtureMode = (): boolean => useDataModeStore.getState().mode === 'fixture'
