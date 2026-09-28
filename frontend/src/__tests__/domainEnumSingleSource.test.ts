/**
 * D7 · 域枚举单一事实源：过滤维度只能从 `lib/taskDomains` 派生
 *
 * 规矩（架构评审 v4 / 计划 v4 波次 A3）：新增业务域只允许在 `TASK_DOMAINS`
 * 加一行 + 报告中心多一个过滤 chip，**不得**在页面里维护第二套域词汇。缺陷当年
 * 的形状：`ReportsPage.tsx` 自带 `type TypeFilter = 'all' | 'living_circle' | 'research'`
 * 并硬编码三个 chip —— 其中 `research` 这个词在 `taskDomains` 里**根本不存在**
 * （那里的口径是 `family: 'travel' | 'living_circle'`，见 `taskDomains.ts:17`）。
 * 于是"加一个域要改几处"没有答案：改 `TASK_DOMAINS` 不会让报告中心多出口，
 * 改报告中心也不会让其它页跟着走。
 *
 * 长期保留：本文件是「派生链」守卫，不随 A3 落地而删 —— 下面两条正向判据防的正是
 * 有人把 chip 集合改回字面量、或绕开列表层另起一条派生。
 *
 * 两条判据分工（波次 A3 落地后重指到真实接缝）：
 * - 正向（防回退）：任何页面不得出现由 `DomainFamily` 值拼成的字面量数组；
 * - 正向（派生链闭合）：页面消费 `recordIndex` 派生出的 `RECORD_DOMAINS`，而
 *   `recordIndex` 本身从 `taskDomains` 派生 —— 页面到注册表之间**只允许这一条链**。
 *   页面不直接 import `taskDomains` 不是漏洞：集合派生是列表层职责，逐族断言已由
 *   `lib/recordIndex.test.ts`（FE-40「RECORD_DOMAINS 恰等于注册表 family 集合」）钉住。
 *   这里改钉「页面不得自带词汇表」+「链头确实指向注册表」两端的接缝。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const PAGES = join(process.cwd(), 'src', 'pages')
const RECORD_INDEX = join(process.cwd(), 'src', 'lib', 'recordIndex.ts')

/** 由 DomainFamily 值构成的数组字面量，如 ['travel', 'living_circle'] */
const DOMAIN_LITERAL_ARRAY = /\[\s*'(travel|living_circle)'(?:\s*,\s*'(?:travel|living_circle)')+\s*\]/

function pageFiles(): string[] {
  return readdirSync(PAGES).filter((f) => f.endsWith('.tsx')).sort()
}

describe('域枚举只能有一个真相源', () => {
  it('页面里不出现 DomainFamily 字面量数组（正向防回退）', () => {
    const files = pageFiles()
    expect(files.length).toBeGreaterThan(5) // 宁可红，不空转：读不到页面就说明路径失效
    for (const f of files) {
      const text = readFileSync(join(PAGES, f), 'utf8')
      expect(DOMAIN_LITERAL_ARRAY.test(text), `${f} 自行硬编码了域数组`).toBe(false)
    }
  })

  it('报告中心的过滤 chip 集合来自列表层派生，不再自带词汇表', () => {
    const text = readFileSync(join(PAGES, 'ReportsPage.tsx'), 'utf8')
    // 链尾：页面必须消费派生集合（缺了它下面三条否定判据就只是空转）
    expect(text).toMatch(/RECORD_DOMAINS[\s\S]*from '\.\.\/lib\/recordIndex'/)
    expect(text).not.toMatch(/type TypeFilter =/)
    expect(text).not.toMatch(/\{ key: 'living_circle', label: '生活圈体检' \}/)
    expect(text).not.toMatch(/\{ value: 'research'/)
    // 展示文案同样只在列表层一份；页面里再拼一遍就是第二套词汇
    expect(text).not.toMatch(/label: '生活圈体检'|label: '目的地调研'/)
  })

  it('派生链的链头确实接在 taskDomains 注册表上', () => {
    const text = readFileSync(RECORD_INDEX, 'utf8')
    expect(text).toMatch(/from '\.\/taskDomains'/)
    // 集合由注册表求 family 得到，而非抄一份常量（值级等价见 recordIndex.test.ts FE-40）
    expect(text).toMatch(/Object\.values\(TASK_DOMAINS\)\.map\(\(d\) => d\.family\)/)
  })
})
