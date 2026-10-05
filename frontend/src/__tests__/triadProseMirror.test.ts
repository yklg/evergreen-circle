/**
 * 三要素措辞的**跨端**镜像守卫。
 *
 * 为什么要单独一道：`test_fixture_mirror.py` 只比后端 `fixtures/*.json` 与前端
 * `mocks/fixtures/livingCircle/*.json` 的**数据**，从来不比**渲染句子**。于是后端模板把
 * "15 分钟圈内"改成"可达区内"时 mock 不会红、后端把三要素说法改成两把尺时 mock 也不会红
 * —— 演示态与实时态各说一套，而这正是"结构全绿、内容为假"那个老教训的另一种形态。
 *
 * 本测试把两侧措辞钉成同一份：前端渲染器的每个**纯字面量**分支，必须在后端模板源码里
 * 原样存在。任何一侧单独改措辞都会红。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import {
  triadClaimText,
  triadOverviewText,
  triadSchoolParaText,
  triadState,
  triadTakeawayText,
} from '../lib/livingCircle'
import type { TriadFacility } from '../types'

const BACKEND_TEMPLATE = join(
  process.cwd(),
  '../backend/app/core/pipeline/diagnosis_templates.py',
)
const backendSrc = readFileSync(BACKEND_TEMPLATE, 'utf-8')

const T = (over: Partial<TriadFacility>): TriadFacility => ({
  facility: '药店',
  covered: Boolean(over.in_reach),
  nearest_name: null,
  nearest_minutes: null,
  ...over,
} as TriadFacility)

const REACHABLE = T({ in_reach: true, nearest_minutes: 4.7, within_blind_radius: true, nearest_m: 300 })
const BLOCKED = T({ in_reach: false, within_blind_radius: true, nearest_m: 950 })
const ABSENT = T({ in_reach: false, within_blind_radius: false, nearest_m: 2200 })
const UNKNOWN = T({ in_reach: false, within_blind_radius: null })
const LEGACY = { facility: '药店', covered: false, nearest_name: null, nearest_minutes: null } as TriadFacility

describe('三要素措辞 · 跨端字面量必须同源', () => {
  // 纯字面量分支：两侧必须逐字相同，所以拿后端源码当唯一真相来比
  const LITERALS: Array<[string, string]> = [
    ['takeaway/absent', triadTakeawayText(ABSENT)],
    ['takeaway/unknown', triadTakeawayText(UNKNOWN)],
    ['takeaway/missing', triadTakeawayText(null)],
    ['claim/reachable', triadClaimText(REACHABLE)],
    ['claim/blocked', triadClaimText(BLOCKED)],
    ['claim/absent', triadClaimText(ABSENT)],
    ['claim/unknown', triadClaimText(UNKNOWN)],
    ['claim/missing', triadClaimText(null)],
    ['school/absent', triadSchoolParaText(ABSENT)],
    ['school/unknown', triadSchoolParaText(UNKNOWN)],
    ['overview/all-good', triadOverviewText([REACHABLE, REACHABLE, REACHABLE])],
    ['overview/empty', triadOverviewText([])],
  ]

  for (const [name, phrase] of LITERALS) {
    it(`${name} 的措辞与后端逐字相同`, () => {
      expect(backendSrc, `后端模板里找不到这句话 ⇒ 两侧措辞已漂移：${phrase}`).toContain(phrase)
    })
  }

  it('分桶句式的三段骨架与后端一致', () => {
    const mixed = triadOverviewText([BLOCKED, ABSENT, UNKNOWN])
    for (const frag of ['中心 1km 内没有', '1km 内有但步行到不了', '1km 内有没有未查全', '三要素：']) {
      expect(backendSrc, `后端缺这段骨架：${frag}`).toContain(frag)
      expect(mixed).toContain(frag)
    }
  })
})

describe('三要素措辞 · 状态判定与后端同表', () => {
  it('五态判定逐例对齐', () => {
    expect(triadState(REACHABLE)).toBe('reachable')
    expect(triadState(BLOCKED)).toBe('blocked')
    expect(triadState(ABSENT)).toBe('absent')
    expect(triadState(UNKNOWN)).toBe('unknown')
    expect(triadState(null)).toBe('missing')
  })

  it('旧快照只有 covered：可达尺照读，1km 尺一律落 unknown', () => {
    expect(triadState(LEGACY)).toBe('unknown')
    expect(triadState({ ...LEGACY, covered: true })).toBe('reachable')
    // 不许把"没查过"塌成"1km 内没有"
    expect(triadTakeawayText(LEGACY)).not.toContain('中心 1km 内没有')
  })
})

describe('渲染面不许再自己写三要素的假结论', () => {
  const MOCK = join(process.cwd(), 'src/mocks/livingCircleReports.ts')
  // 这些短语都源自"把可达尺说成 1km 尺"，一律不许再被手写出来。
  // 最后一条是卡片标题：三个渲染面原本各写一份「必备设施三要素（1km）」，而那一排 chip
  // 一把报分钟、一把报直线米数 —— 标题带上任一把尺，另一半就成了假话。
  const BANNED = [
    '1km 内缺失', '1km 内覆盖缺位', '1km 内无小学', '1km 内均可达', '1km 覆盖缺口',
    '小学 1km 三要素事实', '必备设施三要素（1km）',
  ]
  /** 手写 `covered ? …` 二元式 —— 五态塌成两态的机器形态，禁在**除措辞出口以外**的一切文件。 */
  const HANDWRITTEN = /covered\s*\?(?!\?)/

  /**
   * 扫描面：`src/` 下全部 `.ts`/`.tsx`，排除两处 —— `lib/livingCircle.ts`（唯一出口本体，
   * 它的注释里就得写着那句禁令）与测试文件（守卫自己把禁令原文当字符串拿着）。
   */
  function shippedFiles(): Array<{ rel: string; src: string }> {
    const out: Array<{ rel: string; src: string }> = []
    const walk = (dir: string) => {
      for (const ent of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, ent.name)
        if (ent.isDirectory()) {
          walk(p)
          continue
        }
        const rel = p.slice(join(process.cwd()).length + 1)
        if (!/\.(ts|tsx)$/.test(ent.name) || rel.includes('__tests__') || rel.includes('.test.')) continue
        if (rel === join('src', 'lib', 'livingCircle.ts')) continue
        out.push({ rel, src: readFileSync(p, 'utf-8') })
      }
    }
    walk(join(process.cwd(), 'src'))
    return out
  }

  const files = shippedFiles()

  /**
   * 谁在画三要素那一排：读本仓 payload 的 `triads`（或走 `triadRows` 取数）**且**产出 chip。
   * 按特征现扫而不是点名文件 —— 点名列表会跟着新增渲染面一起腐烂（同一形状就有过三份：
   * 体检台、报告体检单、`dev/` 预览件，只钉报告那一处等于放行另外两处）。
   */
  const painters = files.filter((f) => /triads|triadRows/.test(f.src) && f.src.includes('rounded-chip'))

  it('扫描面非空（空扫描面会让下面全部断言恒绿）', () => {
    expect(files.length).toBeGreaterThan(80)
    expect(painters.map((f) => f.rel)).toEqual(
      expect.arrayContaining([
        'src/components/lifecircle/LifeCircleReportView.tsx',
        'src/pages/LifeCirclePage.tsx',
        'src/dev/lcP5Probe.tsx',
      ]),
    )
  })

  /* ⚠️ 短语禁令的作用面是**三要素的渲染面**，不是全仓：`LcMap.tsx:919` 那句「1km 内缺失」
   * 说的是盲区簇质心的真 1km 判定（由 `missing_facilities` 驱动），合法且与 triad 无关
   * ——AGENTS §7.3 第 4 条。把它一起禁掉，等于用守卫逼着盲区章把一个真话改薄。 */
  it('画三要素的渲染面不许出现旧短语', () => {
    for (const { rel, src } of painters) {
      for (const phrase of BANNED) expect(src, `${rel} 里还有：${phrase}`).not.toContain(phrase)
    }
  })

  it('画三要素 chip 的地方一律用共享渲染器出措辞与配色', () => {
    for (const { rel, src } of painters) {
      expect(src, `${rel} 自己在画三要素，却没走 triadChipText`).toContain('triadChipText')
      expect(src, `${rel} 自己在配色，没走 TRIAD_CHIP_CLASS`).toContain('TRIAD_CHIP_CLASS')
    }
  })

  it('全仓不许手写 `covered ?` 二元式（五态塌成两态的机器形态）', () => {
    for (const { rel, src } of files) {
      expect(src, `${rel} 手写了 covered 二元式`).not.toMatch(HANDWRITTEN)
    }
  })

  it('mock 里不许再自己判 `triad?.covered` 出结论', () => {
    const src = readFileSync(MOCK, 'utf-8')
    expect(src, 'mock 不许再自己判 `triad?.covered` 出结论').not.toMatch(/triad\?\.covered\s*\?/)
  })
})
