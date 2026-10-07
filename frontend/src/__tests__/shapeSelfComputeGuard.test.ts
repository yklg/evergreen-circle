/**
 * 守卫（笔三 S17）：形状的两颗标量**只准后端算一次**，渲染面不许从 `bins_m` 反推。
 *
 * 为什么必须有这条：出口 `shapeOfZone` 会校验"标量能被 bins_m/area_km2 复算出来"，
 * 但如果某个卡片为了省事自己写了 `Math.min(...bins)/Math.max(...bins)`，屏上就会出现
 * 第二个生产者 —— 两处一改就各说各话，而这正是本域反复写勘误的那类事故（`covered` 三义、
 * 判定尺半径两处不同式）。守卫**按特征现扫 `src/`**，不点名文件：新增一个卡片面
 * 不需要有人记得把名字加进列表。
 *
 * 豁免面（合法的原始读数消费者）：
 *   - `lib/livingCircle.ts` —— 出口本体，判据就写在这里；
 *   - `components/lifecircle/ShapeSectorOverlay.ts` —— 几何层，只按半径画楔形；
 *   - `types.ts` —— 契约声明。
 * 条形图读 `bins_m` 画**条长**（`Math.max(...bins_m)` 当标尺）是合法消费 —— 特征只钉
 * "min 与 max 相除"这种重算比值的行为，否则守卫会把正常渲染也判成违规，逼人关掉它。
 */
import { readdirSync, readFileSync, statSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const ALLOW = new Set(['lib/livingCircle.ts', 'components/lifecircle/ShapeSectorOverlay.ts', 'types.ts'])

/** 反推标量的特征：对 bins_m 求 min/max，或重算 circularity/weak_ratio。 */
const PATTERNS: [RegExp, string][] = [
  [/Math\.min\s*\([^)]*bins_m[^)]*\)\s*\/\s*Math\.max\s*\(/, '自己由 bins_m 算最弱方位比（min/max 相除）'],
  [/Math\.max\s*\([^)]*bins_m[^)]*\)[^;\n]*\/[^;\n]*Math\.min\s*\(/, '自己由 bins_m 算方位比（max/min 相除）'],
  [/Math\.sqrt\s*\([^)]*(?:area_km2|1e6)[^)]*\)\s*\/[^;]*bins_m/, '自己由面积与半径反推圆度'],
  [/\b(weak_ratio|circularity)\s*[=:][^;\n]*Math\./, '重新赋值两颗标量'],
]

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      // `.tmp-guard-*` 是**本文件自己**正对照用的临时脚手架（下面那条用例写进去的假违规）。
      // 它不能进负扫描：并发跑全量时，A 进程刚写下的 `BadCard.tsx` 会被 B 进程的负扫描抓到 ——
      // 10-07 实测三份并发全量里就这么红过一次（`expected [ Array(1) ] to deeply equal []`，
      // 内容正是 `.tmp-guard-shape/BadCard.tsx:2`），红得像个真违规，其实是自家的脚手架互相看见。
      if (name === '__tests__' || name === 'node_modules' || name.startsWith('.tmp-guard-')) continue
      out.push(...walk(full))
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(full)
    }
  }
  return out
}

/** 扫一棵树，返回违规清单（`相对路径:行号 原因`）。 */
function scanForSelfCompute(root: string): string[] {
  const hits: string[] = []
  for (const file of walk(root)) {
    const rel = relative(root, file).split('\\').join('/')
    if (ALLOW.has(rel)) continue
    const text = readFileSync(file, 'utf-8')
    text.split('\n').forEach((line, i) => {
      if (line.includes('/* 允许自算 */')) return
      for (const [re, why] of PATTERNS) {
        if (re.test(line)) hits.push(`${rel}:${i + 1} ${why}`)
      }
    })
  }
  return hits
}

describe('形状口径 · 渲染面禁自算守卫', () => {
  it('现扫 src/ 全部渲染面：没有任何一处从 bins_m 反推标量', () => {
    expect(scanForSelfCompute(SRC)).toEqual([])
  })

  /**
   * **守卫的守卫**（照后端 `test_single_definition_guard_actually_catches_a_copy` 同构）：
   * 判据必须能抓到一次故意写进去的自算，否则它就是在看空气 —— 全绿只说明"当前代码让
   * 测试满意"，不说明"测试真的在检查东西"。
   */
  it('故意写一次自算 ⇒ 守卫必须转红（正对照）', () => {
    // 必须落在扫描器看得见的地方：`__tests__/` 整目录被排除（测试里合法自算），
    // 上一版把假文件写进 __tests__ 下 ⇒ 正对照扫不到东西却"通过"了断言之外的部分。
    // 目录名带 pid：两个进程共用一个固定名时，`finally` 里的 rmSync 会删掉对方正在用的那份。
    const tmp = join(SRC, `.tmp-guard-shape-${process.pid}`)
    mkdirSync(tmp, { recursive: true })
    const fake = join(tmp, 'BadCard.tsx')
    try {
      writeFileSync(
        fake,
        'export const bad = (s: { bins_m: number[] }) =>\n'
        + '  Math.min(...s.bins_m) / Math.max(...s.bins_m)\n',
        'utf-8',
      )
      // 以脚手架目录自己为根来扫：负扫描现在跳过 `.tmp-guard-*`，若还从 SRC 扫就等于
      // "正对照扫的东西根本不在扫描范围内" —— 那这条判据会静默变成空转（比红更坏）。
      const hits = scanForSelfCompute(tmp)
      expect(hits.map((h) => h.split(':')[0])).toEqual(['BadCard.tsx'])
      expect(hits.join('\n')).toContain('最弱方位比')
    } finally {
      rmSync(tmp, { recursive: true, force: true })
    }
  })
})
