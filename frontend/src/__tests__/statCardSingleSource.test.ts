/**
 * 统计卡只允许有一份实现（计划 v9 步骤 1–3 的长期守卫）
 *
 * 背景：同一形状的"数字 + 标签 + 口径说明"卡，仓里原本有**两份私有实现** ——
 * `components/RecordStatsStrip.tsx` 的 `StatBlock`（生活圈统计带）与
 * `pages/reports/ResearchIntelView.tsx` 的 `Stat`（调研屏八块）。照参考图再抄一遍
 * 就是第三份，于是"把数字字号调一档"没有单一答案。本波收敛成 `ui/index.tsx` 的
 * `VStatCard`，这条守卫防的是它**再长回去**。
 *
 * 判据为什么钉"数字那一行的 class"而不是卡的外层面：
 * `rounded-card border border-line/60 bg-card p-4 shadow-card` 在本仓是**通用卡面**
 * （`VChart`、`VClaimCard`、`RecordRow`、`KnowledgePage` 都在用），拿它当禁串会
 * 误伤一片；而 `font-serif text-[26px] leading-none` / `text-[32px]` 这两档数字面
 * 是统计卡独有的形状指纹。
 *
 * 覆盖面边界（写清楚，免得日后当成全能闸）：
 * - 只扫 `src/pages/**` 与 `src/components/RecordStatsStrip.tsx` —— 页面层是这次
 *   分叉真正长出来的地方；
 * - **不覆盖** `src/components/MetricsStrip.tsx:26`（报告内指标条，另有一处
 *   `text-[26px]` 的 VCountUp 用法）。它是既有的相邻形状，不在本波范围，
 *   要收它得单独一批，别把这条守卫偷偷扩成全能闸。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const PAGES = join(process.cwd(), 'src', 'pages')
const STRIP = join(process.cwd(), 'src', 'components', 'RecordStatsStrip.tsx')
const UI = join(process.cwd(), 'src', 'components', 'ui', 'index.tsx')

/** 统计卡的数字面：两档字号都算（vcard 用 32px，tile/flat 用 26px） */
const STAT_NUMBER_FACE = /font-serif text-\[(26|32)px\] leading-none/

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (name.endsWith('.tsx')) out.push(full)
  }
  return out
}

describe('统计卡的实现只能有一处', () => {
  it('页面层不得自带统计卡数字面（必须消费 VStatCard）', () => {
    const files = walk(PAGES)
    expect(files.length).toBeGreaterThan(10) // 宁可红，不空转：扫不到页面说明路径失效
    for (const f of files) {
      expect(
        STAT_NUMBER_FACE.test(readFileSync(f, 'utf8')),
        `${f.replace(process.cwd() + '/', '')} 自己手搓了一张统计卡`,
      ).toBe(false)
    }
    expect(STAT_NUMBER_FACE.test(readFileSync(STRIP, 'utf8'))).toBe(false)
  })

  it('正对照：唯一实现确实在 ui/index.tsx（否则上面的判据是空过）', () => {
    const src = readFileSync(UI, 'utf8')
    expect(src).toMatch(/export function VStatCard/)
    expect(STAT_NUMBER_FACE.test(src)).toBe(true)
    // 三面枚举是收敛的前提：少一面就会在换件时被动改掉某一屏的像素
    expect(src).toMatch(/vcard:[\s\S]*?tile:[\s\S]*?flat:[\s\S]*?\} as const/)
  })

  it('两屏都真的在消费它（防止"提了共享件但没人用"）', () => {
    expect(readFileSync(STRIP, 'utf8')).toMatch(/<VStatCard/)
    expect(readFileSync(join(PAGES, 'reports', 'ResearchIntelView.tsx'), 'utf8')).toMatch(/<VStatCard/)
  })
})
