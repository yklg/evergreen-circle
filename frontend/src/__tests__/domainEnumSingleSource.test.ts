/**
 * D7 · 域枚举单一事实源：过滤维度只能从 `lib/taskDomains` 派生
 *
 * 规矩（架构评审 v4 / 计划 v4 波次 B 第 10 步）：新增业务域只允许在 `TASK_DOMAINS`
 * 加一行 + 报告中心多一个过滤 chip，**不得**在页面里维护第二套域词汇。今天
 * `ReportsPage.tsx:18` 自带一个页面本地的 `type TypeFilter = 'all' | 'living_circle'
 * | 'research'`，:75-82 又硬编码三个 chip —— 其中 `research` 这个词在 `taskDomains`
 * 里**根本不存在**（那里的口径是 `family: 'travel' | 'living_circle'`，
 * 见 `taskDomains.ts:17`）。于是"加一个域要改几处"没有答案：改 `TASK_DOMAINS`
 * 不会让报告中心多出口，改报告中心也不会让其它页跟着走。
 *
 * 两条判据分工：
 * - 正向（现在就该绿，防回退）：任何页面不得出现由 `DomainFamily` 值拼成的字面量数组；
 * - `it.fails`（挂账现状）：报告中心的过滤集合必须来自 `taskDomains`。落地波次 B 时
 *   摘标记，先例 `visitorUnrated.test.tsx:121-122`。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const PAGES = join(process.cwd(), 'src', 'pages')

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

  it('报告中心确实在用页面本地过滤词（登记事实，修复时随下条一起重指）', () => {
    const text = readFileSync(join(PAGES, 'ReportsPage.tsx'), 'utf8')
    expect(text).toMatch(/type TypeFilter = 'all' \| 'living_circle' \| 'research'/)
    expect(text).not.toMatch(/from '..\/lib\/taskDomains'/)
  })

  it.fails('报告中心的过滤 chip 集合必须从 taskDomains 派生，不再自带词汇表', () => {
    const text = readFileSync(join(PAGES, 'ReportsPage.tsx'), 'utf8')
    expect(text).toMatch(/from '..\/lib\/taskDomains'/)
    expect(text).not.toMatch(/type TypeFilter =/)
    // chip 的 key 只能来自派生集合，不能是硬编码三元组
    expect(text).not.toMatch(/\{ key: 'living_circle', label: '生活圈体检' \}/)
  })
})
