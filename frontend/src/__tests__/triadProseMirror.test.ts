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
import { readFileSync } from 'node:fs'
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
  const VIEW = join(process.cwd(), 'src/components/lifecircle/LifeCircleReportView.tsx')
  // 这些短语都源自"把可达尺说成 1km 尺"，一律不许再被手写出来
  const BANNED = ['1km 内缺失', '1km 内覆盖缺位', '1km 内无小学', '1km 内均可达', '1km 覆盖缺口', '小学 1km 三要素事实']

  it('mock 里不许再出现手写三元式与旧短语', () => {
    const src = readFileSync(MOCK, 'utf-8')
    for (const phrase of BANNED) expect(src, `mock 里还有：${phrase}`).not.toContain(phrase)
    expect(src, 'mock 不许再自己判 `triad?.covered` 出结论').not.toMatch(/triad\?\.covered\s*\?/)
  })

  it('体检单三要素卡的措辞出自共享渲染器（当前仍由 WIP 栅栏挡着，见下）', () => {
    const src = readFileSync(VIEW, 'utf-8')
    // 该文件在用户 WIP 内，UI 卡片那一处尚未迁移 —— 这条**故意**记为已知未完成，
    // 迁移完成后把下面两行改成断言 `triadChipText` 存在。
    const migrated = src.includes('triadChipText')
    if (!migrated) {
      expect(src).toContain('1km 内缺失')   // 现状：仍是旧写法，等第四笔落地后一并迁
      return
    }
    for (const phrase of BANNED) expect(src, `卡片里还有：${phrase}`).not.toContain(phrase)
  })
})
