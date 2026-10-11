// @vitest-environment jsdom
/**
 * 浏览器存储键的**单一真相源**守卫 + 改名搬运的行为判据（2026-10-11）。
 *
 * 为什么值得单独守：
 *  1. 这 10 个键原先以上游项目名散在 8 个 store、`persist.ts`、6 个测试文件与 3 个 e2e 里
 *     ——改名漏一处就是**静默的状态重置**（读旧键拿到 null，看起来像"用户没存过"）；
 *  2. 搬运代码写了**没人调**等于没写 ⇒ 单独一条钉 `main.tsx` 真的调了它；
 *  3. 以后新增键、忘了加进旧键名册，老用户那个键的资料同样会静默丢 ⇒ 断言两张表**逐值对齐**。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { LEGACY_LS_KEY_MAP, LS_KEYS, migrateLegacyLsKeys } from '../lib/lsKeys'

const SRC = join(process.cwd(), 'src')
const E2E = join(process.cwd(), 'e2e')
const SELF = 'lib/lsKeys.ts'

/** 递归收集 .ts/.tsx（e2e 与 src 各扫一遍）。 */
function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(ts|tsx)$/.test(e.name)) out.push(p)
  }
  return out
}

afterEach(() => localStorage.clear())

describe('单一真相源：旧键名只许住在 lsKeys.ts 里', () => {
  it('src/ 与 e2e/ 的其它文件里不得出现 `verda.` 字面量（含测试与 e2e）', () => {
    const hits: string[] = []
    for (const file of [...walk(SRC), ...walk(E2E)]) {
      const rel = file.slice(join(process.cwd(), '/').length)
      if (rel.endsWith(SELF)) continue
      const text = readFileSync(file, 'utf8')
      // 只找"像键名"的形态：旧前缀 + 点 + 名字。**注释里的旧名也算违规** ——
      // 注释就是下一个人的复制源，而改名的教训正是"名字只该有一个出处"。
      // （本文件自己也不许写旧名字面量 ⇒ 下面的行为用例一律从名册里取值。）
      text.split('\n').forEach((line, i) => {
        if (/verda\.[a-zA-Z]/.test(line)) hits.push(`${rel}:${i + 1}`)
      })
    }
    expect(hits, `旧键名扩散到了名册之外：${hits.join(', ')}`).toEqual([])
  })

  it('新键名互不重复且统一前缀', () => {
    const vals = Object.values(LS_KEYS)
    expect(new Set(vals).size, '有重复的新键名').toBe(vals.length)
    for (const v of vals) expect(v.startsWith('evergreen.')).toBe(true)
  })

  it('旧键名册与新键集合**逐值对齐**（加键忘了加迁移 = 老用户那个键静默丢）', () => {
    expect(Object.keys(LEGACY_LS_KEY_MAP).sort()).toEqual([...Object.values(LS_KEYS)].sort())
    for (const [next, prev] of Object.entries(LEGACY_LS_KEY_MAP)) {
      expect(prev.startsWith('verda.'), `${next} 的旧名不像旧名：${prev}`).toBe(true)
    }
  })

  it('main.tsx 真的调了搬运（写了没人调等于没写）', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8')
    expect(main).toContain('migrateLegacyLsKeys()')
    // 必须在 render 之前：store 的初始值在模块求值时就读 localStorage，晚了就搬不上
    expect(main.indexOf('migrateLegacyLsKeys()')).toBeLessThan(main.indexOf('createRoot('))
  })
})

describe('搬运行为：旧值搬到新键，安全且幂等', () => {
  // 旧键一律从名册里取（本文件不许写旧名字面量，见上一条守卫）
  const OLD = (k: keyof typeof LS_KEYS) => LEGACY_LS_KEY_MAP[LS_KEYS[k]]

  it('旧键有值、新键没有 ⇒ 搬过去；**旧键保留不删**', () => {
    localStorage.setItem(OLD('dataMode'), 'fixture')
    const moved = migrateLegacyLsKeys()
    expect(moved).toContain(LS_KEYS.dataMode)
    expect(localStorage.getItem(LS_KEYS.dataMode)).toBe('fixture')
    expect(localStorage.getItem(OLD('dataMode')), '旧键被删了 ⇒ 回滚旧版就丢资料').toBe('fixture')
  })

  it('新键已有值 ⇒ 不覆盖（新版跑过又回滚、再升上来的情形）', () => {
    localStorage.setItem(OLD('ui'), '旧值')
    localStorage.setItem(LS_KEYS.ui, '新值')
    const moved = migrateLegacyLsKeys()
    expect(moved).not.toContain(LS_KEYS.ui)
    expect(localStorage.getItem(LS_KEYS.ui)).toBe('新值')
  })

  it('幂等：连跑两次，第二次一个都不搬、值不变', () => {
    localStorage.setItem(OLD('profile'), '安静的水獭')
    const first = migrateLegacyLsKeys()
    expect(first.length).toBeGreaterThan(0)
    // ⚠️ 别用 `{ ...localStorage }`：jsdom 的 Storage 把 length/clear/getItem… 也当可枚举属性，
    // 展开出来是个"方法表"，比不出数据差异。按 `key(i)` 逐条取值才是稳定的快照。
    const snapshot: Record<string, string> = {}
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!
      snapshot[k] = localStorage.getItem(k)!
    }
    expect(migrateLegacyLsKeys(), '第二次不该再搬任何键').toEqual([])
    const after: Record<string, string> = {}
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!
      after[k] = localStorage.getItem(k)!
    }
    expect(after).toEqual(snapshot)
  })

  it('没有旧键时不报错、不产生新键（新用户第一次进来）', () => {
    expect(migrateLegacyLsKeys()).toEqual([])
    expect(localStorage.length, '没旧键却新建了键').toBe(0)
  })
})
