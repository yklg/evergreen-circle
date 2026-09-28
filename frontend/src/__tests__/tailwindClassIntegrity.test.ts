/**
 * Tailwind 颜色工具类完整性守卫（类 `/scripts/check_guard_construction.py` 的前端对应物）。
 *
 * **为什么需要**：Tailwind 只对**定义过**的 token 生成 CSS；写错的类名
 * **不报错、不警告，只是静默什么都不生成** —— 页面照跑，颜色却悄悄变成继承色/透明。
 * 本守卫一次扫出 4 处既有的悬空类（2026-09-22 全部已修，证据 = `dist/assets/*.css` 里生成 0 次）：
 *   1. `text-warn-deep`（调色板只有 `warn`，`-deep` 变体只有 `primary-deep` 有）
 *      ⇒ 该 chip 文字色实际是父级 `ink-3` 灰，对比度仅 2.45:1（11px 小字，AA 要 ≥4.5:1）；
 *   2. `bg-paper`（7 个文件 14 处）⇒ 这些面板的背景色**根本不存在**，一直是透明的；
 *   3. `border-ink-1/10` / `bg-ink-1/5`（`LcMap.tsx` 5 处）⇒ 调色板无 `ink-1`，边框/hover 底丢失；
 *   4. `from-tint`（`ChapterContentMap.tsx` 1 处）⇒ 渐变起点透明。
 *
 * **判据**：出现的每个颜色工具类，其色值部分必须属于
 * ① 项目调色板（`theme.extend.colors` 的扁平 token）· ② Tailwind 默认工具类.
 * 任意值写法（`text-[#8A6420]`）不检查 —— 它自带色值，不需要 token 存在。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
// @ts-expect-error tailwind.config.js 是无类型声明的 CJS/ESM 混合配置，仅本测试读取其 token
import config from '../../tailwind.config.js'

const SRC = join(process.cwd(), 'src')

/* ── ① 项目调色板（含一层命名空间）── */
const COLOR_TOKENS = new Set<string>()
for (const [k, v] of Object.entries<any>(config.theme.extend.colors ?? {})) {
  COLOR_TOKENS.add(k)
  if (v && typeof v === 'object') for (const k2 of Object.keys(v)) COLOR_TOKENS.add(`${k}-${k2}`)
}

/* ── ② Tailwind 默认工具类的形态（本项目未覆盖到的）── */
const TAILWIND_DEFAULT_COLOR = /^(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(-(50|100|200|300|400|500|600|700|800|900|950))?$/
const TAILWIND_BASE_COLORS = new Set(['white', 'black', 'transparent', 'current', 'inherit'])
const TAILWIND_FONT_SIZE = /^([2-9]xl|\d?xl|xs|sm|base|lg)$/
/** `border-b` / `border-l-2` / `border-x` / `border-2` 这类是方向+宽度，不是颜色 */
const BORDER_GEOMETRY = /^([xyse]|[trbl])(-\d)?$|^\d$/

/** 前缀各自的非颜色原生工具类 */
const NON_COLOR: Record<string, Set<string>> = {
  text: new Set([
    ...Object.keys(config.theme.extend.fontSize ?? {}),
    'left', 'center', 'right', 'justify', 'start', 'end', 'clip', 'ellipsis', 'wrap', 'nowrap',
  ]),
  bg: new Set([
    'clip', 'none', 'auto', 'cover', 'contain', 'fixed', 'local', 'scroll',
    'repeat', 'no-repeat', 'bottom', 'center', 'left', 'right', 'top', 'origin',
  ]),
  border: new Set(['solid', 'dashed', 'dotted', 'double', 'none', 'hidden', 'collapse', 'separate', 'spacing']),
}

/**
 * **已知遗留清单**（都经构建产物核实：CSS 里生成 0 次 ⇒ 确实不生效）。
 * 入列纪律同 `check_guard_construction.py` 的 G-4 白名单：**必须写明理由 + 待决策**，不许静默豁免。
 *
 * 📌 当前为**空** —— 2026-09-22 已把上一批全修完（并同步从本清单移除）：
 *   · `bg-paper`（7 文件 14 处）→ `bg-bg`
 *   · `border-ink-1/10` / `bg-ink-1/5`（`LcMap.tsx` 5 处）→ `border-ink/10` / `bg-ink/5`
 *   · `from-tint`（`ChapterContentMap.tsx` 1 处）→ `from-primary-tint`
 *   · `text-warn-deep`（`DashboardPage.tsx` 1 处）→ `text-[#8A6420]`
 * **修好一项就删一项**，否则清单会变成"永远亮着所以没人看"的假护栏（有反向用例钉住这一点）。
 */
const KNOWN_LEGACY: Array<{ cls: string; count: string; plan: string }> = []
const KNOWN_LEGACY_TOKENS = new Set(KNOWN_LEGACY.map((k) => k.cls))

const COLOR_PREFIXES = ['text', 'bg', 'border', 'ring', 'fill', 'stroke', 'decoration', 'from', 'to', 'via']

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(ts|tsx)$/.test(name)) out.push(full)
  }
  return out
}

/**
 * 抽取「类名来源」片段：① `className="…"` / `className={'…'}` 的属性值；
 * ② 赋给 `*Cls|*Class|*Classes` 变量的字符串常量（如 `lib/reportLayout.ts` 的 `tocLinkCls`）。
 *
 * ⚠️ 为什么**不**扫全文：注释与测试描述里的散文会产生大量误报 ——
 * 实测 `attr('stroke-width', 2)`（`GraphPage.tsx:85`）、注释 `text-anchor=end`
 * （`miniRadar.test.tsx:12`）都不是类名。**扫描范围本身就是一条判据**：宁可漏掉动态拼出来的
 * 类名，也不要被散文淹掉（漏报会被人眼发现，误报会让守卫被人关掉）。
 */
function classSourcesIn(fileContent: string): string[] {
  const out: string[] = []
  for (const m of fileContent.matchAll(/className\s*=\s*["'`]([^"'`]*)["'`]/g)) out.push(m[1])
  for (const m of fileContent.matchAll(/class\s*=\s*["'`]([^"'`]*)["'`]/g)) out.push(m[1])
  for (const m of fileContent.matchAll(/(?:const|let)\s+\w*(?:Cls|Class|Classes|CLASSES)\w*\s*=\s*["'`]([^"'`]*)["'`]/g)) out.push(m[1])
  // className={cn('a', cond && 'b')} —— 整个 {...} 片段（截断 400 字符防回溯）
  for (const m of fileContent.matchAll(/className\s*=\s*\{[\s\S]{0,400}?\}/g)) out.push(m[0])
  return out
}

/** 收集**疑似非法**的颜色工具类 */
function collectSuspects(): string[] {
  const re = new RegExp(`(?:^|[\\s"'\`])((?:${COLOR_PREFIXES.join('|')})-([^\\s"'\`]+))`, 'g')
  const bad = new Set<string>()
  for (const file of walk(SRC)) {
    for (const code of classSourcesIn(readFileSync(file, 'utf-8'))) {
      for (const m of code.matchAll(re)) {
        const cls = m[1]
        const raw = m[2]
      // 只认**纯类名形态**的 token：排除中文注释里的散文（`text-aux（与…`）与 SVG 属性
      // （`stroke-width=`、`stroke-dasharray=`）、CSS 属性（`border-radius:`）。
      if (!/^[A-Za-z0-9\-.\/\[\]()#,]+$/.test(raw)) continue
      if (raw.includes('#') || raw.includes('(') || raw.includes('[')) continue // 任意值写法
      const token = raw.split('/')[0] // 去 `/opacity` 后缀
      const prefix = cls.slice(0, cls.indexOf('-'))

      if (KNOWN_LEGACY_TOKENS.has(`${prefix}-${token}`)) continue // 已知遗留，见上方清单
      if (COLOR_TOKENS.has(token)) continue
      if (NON_COLOR[prefix]?.has(token)) continue
      if (TAILWIND_BASE_COLORS.has(token)) continue
      if (TAILWIND_DEFAULT_COLOR.test(token)) continue
      if (prefix === 'text' && TAILWIND_FONT_SIZE.test(token)) continue
      if (prefix === 'border' && BORDER_GEOMETRY.test(token)) continue
      if (prefix === 'ring' && /^\d$/.test(token)) continue // ring-2 是宽度不是颜色
      if (prefix === 'bg' && token.startsWith('gradient')) continue // bg-gradient-to-r 等

        bad.add(`${relative(process.cwd(), file)} → ${cls}`)
      }
    }
  }
  return [...bad].sort()
}

const suspects = collectSuspects()

describe('Tailwind 颜色工具类完整性', () => {
  it('守卫自己的前置：调色板解析成功且形状符合预期（空表会让下面所有断言空转）', () => {
    expect(COLOR_TOKENS.size).toBeGreaterThan(10)
    for (const t of ['primary', 'primary-deep', 'warn', 'risk', 'ink-3', 'line', 'primary-tint', 'sun-soft']) {
      expect(COLOR_TOKENS.has(t)).toBe(true)
    }
    // 这两条**必须**是 false —— 它们正是本守卫要拦的东西
    expect(COLOR_TOKENS.has('warn-deep')).toBe(false)
    expect(COLOR_TOKENS.has('paper')).toBe(false)
  })

  it('源码里不存在「调色板没有、Tailwind 也不认」的颜色工具类', () => {
    // 失败信息即修复清单：每行 `<文件> → <类名>`
    expect(suspects).toEqual([])
  })

  it('已知遗留清单结构合法，且条目都带「处数 + 修法计划」', () => {
    for (const k of KNOWN_LEGACY) {
      expect(k.count.length).toBeGreaterThan(0)
      expect(k.plan.length).toBeGreaterThan(0)
    }
    // ⚠️ 反向：清单里的每一项都必须**当前确实不合法** —— 修好却忘了删，就会变成
    // 「永远亮着所以没人看」的假护栏（`paper` 已修完，所以它必须不在调色板里却也不在清单里）
    expect(COLOR_TOKENS.has('paper')).toBe(false)
    expect(KNOWN_LEGACY_TOKENS.has('bg-paper')).toBe(false)
  })

  it('合法写法不得被误报（负对照：这些类都**应该**通过）', () => {
    // 任意值 + 默认工具类 + 项目 token 都在源码里真实存在且通过了上面的扫描
    expect(suspects.some((s) => s.includes('#8A6420'))).toBe(false)
    expect(suspects.some((s) => s.includes('text-xs'))).toBe(false)
    expect(suspects.some((s) => s.includes('border-b'))).toBe(false)
    expect(suspects.some((s) => s.includes('bg-white'))).toBe(false)
    expect(suspects.some((s) => s.includes('bg-warn/10'))).toBe(false)
  })
})

/* ══════════════════════════════════════════════════════════════════════════
 * 第二段守卫：CSS 自定义属性（设计令牌）的消费面。
 *
 * 与上面**同一类失效模式**：`var(--未定义的名字)` 不报错、不警告，只是取不到值
 * ⇒ 颜色静默变成继承色/透明。2026-09-28 把令牌去品牌化（`--verda-*` → `--c-*`）时，
 * 只要有一处消费点漏改，全量测试照样绿 —— 所以这条必须机器可校验。
 * ══════════════════════════════════════════════════════════════════════════ */

/** 定义面：设计令牌目前唯一真值源是 `src/index.css` 的 `:root`；新增定义点须登记到这里。 */
const CSS_DEF_FILES = ['src/index.css']
const TW_INTERNAL = /^--tw-/ // Tailwind 自己注入的中间变量，不由本项目定义

function cssVarDefs(): Set<string> {
  const out = new Set<string>()
  for (const rel of CSS_DEF_FILES) {
    const text = readFileSync(join(process.cwd(), rel), 'utf-8')
      .replace(/\/\*[\s\S]*?\*\//g, '') // 注释里的示例 `--x:` 不算定义
    for (const m of text.matchAll(/(?:^|[\s{;])(--[A-Za-z0-9-]+)\s*:/gm)) out.add(m[1])
  }
  return out
}

/**
 * 消费面：两种写法都算 —— ① `var(--x)`；② 把令牌名当字符串传的调用点
 * （`ChapterMindmapSvg.tsx` 的 `v('--c-warn')` 助手，展开后才是 `var(...)`，
 *  只搜 `var(--` 会漏掉该文件全部 17 处）。
 *
 * 扫描前先剥掉注释：文档里的示例令牌（含下面那个"已改名"的负对照）不是消费点。
 */
function collectCssVarRefs(): { refs: string[]; dangling: string[] } {
  const defs = cssVarDefs()
  const files = [
    ...walk(SRC),
    ...CSS_DEF_FILES.map((rel) => join(process.cwd(), rel)),
    join(process.cwd(), 'index.html'),
  ]
  const refs: string[] = []
  const dangling: string[] = []
  for (const file of files) {
    if (!/\.(ts|tsx|css|html)$/.test(file)) continue
    const text = readFileSync(file, 'utf-8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    text.split('\n').forEach((line, i) => {
      for (const m of line.matchAll(/(?:var\(\s*|['"`])(--[A-Za-z0-9-]+)/g)) {
        const name = m[1]
        if (TW_INTERNAL.test(name)) continue
        refs.push(name)
        if (!defs.has(name)) dangling.push(`${relative(process.cwd(), file)}:${i + 1} → ${name}`)
      }
    })
  }
  return { refs, dangling }
}

/**
 * 负对照用的"必然不存在"令牌名。前缀走运行时拼接 —— 直接把 `'--verda…'` 写进字面量
 * 会被上面的扫描当成一处真实消费点，守卫就永远红在自己的哨兵上。
 */
const VAR_PREFIX = '-'.repeat(2)
const RENAMED_AWAY_TOKEN = `${VAR_PREFIX}verda-primary`
const NEVER_DEFINED_TOKEN = `${VAR_PREFIX}c-nonexistent-token`

const cssVars = collectCssVarRefs()

describe('CSS 自定义属性完整性（悬空 var() 会静默丢色）', () => {
  it('守卫自己的前置：定义面与消费面都非空（任一侧塌成空集本守卫就恒绿）', () => {
    const defs = cssVarDefs()
    expect(defs.size).toBeGreaterThan(15)
    for (const t of ['--c-primary', '--c-ink-3', '--c-line', '--ease', '--r-card']) {
      expect(defs.has(t)).toBe(true)
    }
    expect(cssVars.refs.length).toBeGreaterThanOrEqual(30) // 基线实测 38（2026-09-28），留下调余量
    // 反向：未定义的名字**必须**不在定义面里 —— 它们正是本守卫要拦的形状
    expect(defs.has(RENAMED_AWAY_TOKEN)).toBe(false)
    expect(defs.has(NEVER_DEFINED_TOKEN)).toBe(false)
  })

  it('每个被消费的设计令牌都有定义', () => {
    // 失败信息即修复清单：每行 `<文件>:<行> → --令牌名`
    expect(cssVars.dangling).toEqual([])
  })
})
