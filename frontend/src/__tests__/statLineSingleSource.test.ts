/**
 * 「标签 + 文本值」这一形状只允许有一处实现（评审 S5 的长期守卫）
 *
 * ## 它为什么独立成一份，而不是塞进 `statCardSingleSource.test.ts`
 *
 * 那条守卫扫的是**大数字面**（`font-serif text-[26|32]px leading-none`），并且它自己的文件头
 * 写明了覆盖面边界："别把这条守卫偷偷扩成全能闸"。本件守的是**另一个形状** ——
 * 小标签 + 字符串读数（`采集 194 · 圈内 108 · 已展示 108` 这类三段式），
 * 单一实现是 `components/ui/index.tsx` 的 `VStatLine`（两面：`row` 行式 / `tile` 紧凑格）。
 * 两条闸门各管一个形状，谁也不吞谁，判据也都各自可审计。
 *
 * ## 背景（这次事故形状）
 *
 * 同一形状原本散落 **5 份**：`LifeCirclePage` 的 `StatTile`、`LifeCircleReportView` 与
 * `dev/lcP5Probe` 各一份私有 `StatRow`，加上 `ComparePage.tsx:323` 直接内联在 `.map()` 里的
 * 一份（**本闸门首次运行就把它抓出来了** —— 内联实现没有函数名，靠读代码很难数清）。
 * 于是"把读数字号调一档"没有单一答案；而旧守卫只禁数字指纹，**绕得过去** ——
 * 2026-10-04 体检台加 tile 面时就正当地绕了它一次，这条债由本文件收。
 *
 * ## 判据为什么钉 class 串
 *
 * 钉"形状"而不是钉"组件名"：改名换姓的第四份实现照样命中指纹。反面是它会跟着
 * `VStatLine` 的实现一起改 —— 那是有意的耦合：**改形状必须同时改闸门**，
 * 谁想悄悄另起一份，就得先解释为什么动了闸门。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(process.cwd(), 'src')
const UI = join(SRC, 'components', 'ui', 'index.tsx')

/** 两面各自的形状指纹（逐字来自 VStatLine 的 STAT_LINE_FACE） */
const ROW_FACE = 'flex items-center justify-between gap-3 border-b border-line/60 py-1.5'
const TILE_FACE = 'rounded-btn border border-line bg-bg p-2.5'

/**
 * 覆盖面：`src/**` 的 ts/tsx（含 pages、components、dev 探针）。
 * 不覆盖：`__tests__/**`（夹具与判据自身会原样引用这两个串）。
 */
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === '__tests__' || name === 'node_modules') continue
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(ts|tsx)$/.test(name)) out.push(full)
  }
  return out
}

describe('读数行（标签+文本值）的实现只能有一处', () => {
  it('正对照：VStatLine 确实在 ui/index.tsx，且两面都在那儿（否则下面的判据是空过）', () => {
    const ui = readFileSync(UI, 'utf8')
    expect(ui).toMatch(/export function VStatLine/)
    expect(ui).toContain(ROW_FACE)
    expect(ui).toContain(TILE_FACE)
  })

  it('除 ui/index.tsx 外，src 里不得再出现任何一个面（改名重写也算）', () => {
    const files = walk(SRC).filter((f) => f !== UI)
    // 宁可红，不空转：扫不到文件说明路径失效
    expect(files.length).toBeGreaterThan(30)
    for (const f of files) {
      const text = readFileSync(f, 'utf8')
      const rel = f.replace(process.cwd() + '/', '')
      expect(text.includes(ROW_FACE), `${rel} 自己抄了一份行式读数面`).toBe(false)
      expect(text.includes(TILE_FACE), `${rel} 自己抄了一份 tile 读数面`).toBe(false)
    }
  })

  it('消费方走 VStatLine，且体检台那 9 条读数用的是 tile 面', () => {
    const page = readFileSync(join(SRC, 'pages', 'LifeCirclePage.tsx'), 'utf8')
    expect(page).toContain("import { VStatLine } from '../components/ui'")
    expect(page).not.toContain('StatTile')
    // 9 条读数 = 4 条汇总 + 5 条测算口径
    expect((page.match(/<VStatLine face="tile"/g) || []).length).toBe(9)
  })
})
