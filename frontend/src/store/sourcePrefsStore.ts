import { create } from 'zustand'
import { createPersister } from '../lib/persist'
import { MAX_USER_SOURCE_URLS } from '../lib/userSourceStates'

/* 用户指定信源的「默认清单」（计划 v3 §二 B7 · 决策 2/5）。

## 语义分工（这一层只管偏好，不管实例状态）
- 本 store = **用户偏好**：下次调研默认要读哪几份文档。真相源在服务端 `intel.defaultSources`
  （`list[str]`，后端有条数与单条长度双重校验），localStorage 只是秒开缓存。
- `user_sources` 表 = **某一次任务的运行时实例状态**（读到没、被谁引用、归并到哪一组）。
  两者不是一回事，也不得互相冒充：把清单塞进偏好层当业务数据，或把抓取态塞进 prefs，
  都是计划 §一 A-5 点名的职责错位。

## 消费方
- `pages/HomePage.tsx`：首屏预填默认清单 + 「存为下次默认」开关。
- `pages/reports/EvidenceAndTracking.tsx`：建订阅时带上同一份清单，复跑才不会静默少信源。
*/

const LS_KEY = 'verda.sources.v1'

export interface SourcePrefsData {
  defaultSources: string[]
}

export interface SourcePrefsState extends SourcePrefsData {
  setDefaultSources: (list: string[]) => void
}

/** 语义规整：逐项 trim、丢空、去重、截断到上限。
 *  放在 spec.normalize 而不是散落在动作里 —— 「本地读」与「远端水合」两条来源共用同一口径。 */
function normalizeSources(v: SourcePrefsData): SourcePrefsData {
  const out: string[] = []
  for (const raw of v.defaultSources) {
    const s = String(raw ?? '').trim()
    if (s && !out.includes(s)) out.push(s)
    if (out.length >= MAX_USER_SOURCE_URLS) break
  }
  return { defaultSources: out }
}

/* interface 没有隐式索引签名，不能直接当 `PrefShape` 的实参（与 profileStore 同一处理）：
   这里用内联类型字面量，`SourcePrefsData` 仍是对外导出的权威形状。 */
const persister = createPersister<{ defaultSources: string[] }>({
  localKey: LS_KEY,
  prefs: { defaultSources: 'intel.defaultSources' },
  defaults: { defaultSources: [] },
  normalize: normalizeSources,
})

export const useSourcePrefs = create<SourcePrefsState>((set, get) => ({
  ...persister.readLocal(),

  setDefaultSources: (list) => {
    set({ defaultSources: normalizeSources({ defaultSources: list }).defaultSources })
    persister.persist(get())
  },
}))

// 登记到全局水合编排：App.tsx 启动时调用 hydrateAllPrefs() 拉服务端真相源。
persister.register((remote) => {
  useSourcePrefs.setState((s) => ({ ...s, ...remote }))
})
