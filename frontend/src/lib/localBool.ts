/**
 * 轻量布尔偏好 store 工厂：localStorage 单一真源 + 运行时 Zustand。
 *
 * 刻意**不引 lib/persist.ts**（偏好层会上推 /api/prefs 并参与全局水合；且
 * persist → api → 本工厂 会形成循环依赖，与 store/dataModeStore.ts 同因）。
 * 本工厂用于「纯前端、无需服务端水合」的布尔开关（如底图注记开关）。
 */
import { create } from 'zustand'

export interface LocalBoolApi {
  /** 当前开关状态 */
  on: boolean
  /** 切换并持久化（true→'1' / false→'0'）。 */
  set: (on: boolean) => void
}

/**
 * 新建一个布尔偏好 store。
 * @param key localStorage 键
 * @param defaultValue 无持久化值时的默认态
 */
export function createLocalBool(key: string, defaultValue: boolean) {
  const read = (): boolean => {
    try {
      const v = localStorage.getItem(key)
      return v === '1' ? true : v === '0' ? false : defaultValue
    } catch {
      return defaultValue // 隐私模式 / 禁用存储：回退默认，绝不抛错
    }
  }
  const write = (on: boolean) => {
    try {
      localStorage.setItem(key, on ? '1' : '0')
    } catch {
      // 忽略：无持久化能力时仅本次会话生效
    }
  }
  return create<LocalBoolApi>((set) => ({
    on: read(),
    set: (on) => {
      set({ on })
      write(on)
    },
  }))
}
