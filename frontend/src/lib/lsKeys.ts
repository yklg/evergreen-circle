/**
 * 浏览器本地存储键的**单一真相源** + 一次性的"改名搬运"（2026-10-11）。
 *
 * ## 为什么要有这个模块
 *
 * 这些键原先以上游项目的名字（`verda.*`）散在 8 个 store 与 `persist.ts` 里，
 * 另有 6 个测试文件与 3 个 e2e 把它们写成字面量 —— 改名要摸 20 处，而**漏一处就是
 * 静默的状态重置**：读不到旧数据，看起来像"用户什么都没存过"。
 * 与「品牌名只该有一个出处」那条同一个理由：**改名字只该改一处**。
 *
 * ## 老用户的资料不能丢（这是本文件存在的一半理由）
 *
 * `migrateLegacyLsKeys()` 在应用启动时跑一次，规则三条：
 *  1. 旧键有值、新键没有 ⇒ 搬过去；
 *  2. **新键已有值就不动**（同一台机器上新版跑过又回滚到旧版的情形）；
 *  3. 旧键**保留不删** —— 回滚回去数据还在，它也天然是"这份值从哪搬来"的凭据。
 * 幂等：重复执行不改变任何东西。存储不可用（隐私模式）时静默跳过，绝不拦住启动。
 */

/** 当前键名（唯一真相源）。改名 = 改这里 + 同步 `LEGACY_LS_KEY_MAP` 的键。 */
export const LS_KEYS = {
  dataMode: 'evergreen.dataMode.v1',
  annotations: 'evergreen.annotations.v1',
  knowledge: 'evergreen.knowledge.v1',
  tasks: 'evergreen.tasks.v1',
  mapNotes: 'evergreen.mapNotes.v1',
  profile: 'evergreen.profile.v1',
  sources: 'evergreen.sources.v1',
  ui: 'evergreen.ui.v1',
  demoArchive: 'evergreen.demoArchive.v1',
  prefsPending: 'evergreen.prefs.pending.v1',
} as const

export type LsKeyName = keyof typeof LS_KEYS

/**
 * 改名前的旧键（上游项目名）→ 新键。
 *
 * **旧名只允许出现在这里**（`lsKeysSingleSource.test.ts` 守着这条：其它任何文件里
 * 出现 `verda.` 字面量都会红）。搬完不删旧键，所以这张名册要长期留着 ——
 * 只有当确认所有在用环境都搬过一遍之后，才可以考虑清理，那次清理同样要先改这条守卫。
 */
export const LEGACY_LS_KEY_MAP: Record<string, string> = {
  [LS_KEYS.dataMode]: 'verda.dataMode.v1',
  [LS_KEYS.annotations]: 'verda.annotations.v1',
  [LS_KEYS.knowledge]: 'verda.knowledge.v1',
  [LS_KEYS.tasks]: 'verda.tasks.v1',
  [LS_KEYS.mapNotes]: 'verda.mapNotes.v1',
  [LS_KEYS.profile]: 'verda.profile.v1',
  [LS_KEYS.sources]: 'verda.sources.v1',
  [LS_KEYS.ui]: 'verda.ui.v1',
  [LS_KEYS.demoArchive]: 'verda.demoArchive.v1',
  [LS_KEYS.prefsPending]: 'verda.prefs.pending.v1',
}

/** 执行一次搬运，返回**实际搬了哪些键**（供测试与排查用；没搬的不会出现在里面）。 */
export function migrateLegacyLsKeys(): string[] {
  const moved: string[] = []
  for (const [next, prev] of Object.entries(LEGACY_LS_KEY_MAP)) {
    try {
      if (localStorage.getItem(next) !== null) continue
      const old = localStorage.getItem(prev)
      if (old === null) continue
      localStorage.setItem(next, old)
      moved.push(next)
    } catch {
      /* 隐私模式 / 存储被禁：搬不了就不搬，下次启动再试，绝不拦住启动 */
    }
  }
  return moved
}
