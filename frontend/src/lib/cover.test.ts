/**
 * F5 报告封面兜底生成（F5-1 ~ F5-2）
 *
 * 覆盖缺口（计划 §5.3 D7）：`cover.ts` 的文案此前无任何守卫，且它正是「竞品调研」
 * 字样最容易残留的兜底路径（历史 `makeCoverSvg` 里曾硬编码类型文案）。
 *
 * 守护契约：
 *   F5-1  生成的封面 SVG **不含**「竞品」（防回潮哨兵）+ 含旅游调研定位文案
 *   F5-2  直出/兜底分支与 byline 回落取自 BRAND（品牌单一真相源）
 *
 * 说明：SVG 内配色为模块内硬编码色值（非取 BRAND 常量），故此处**不**断言配色来源 ——
 * 只断言可观测行为，避免用 className/色值断言冒充契约（同 reportHero 的教训）。
 */
import { describe, it, expect } from 'vitest'
import { coverFor } from './cover'
import { BRAND } from './brand'

function decode(svg: string): string {
  expect(svg.startsWith('data:image/svg+xml,')).toBe(true)
  return decodeURIComponent(svg.slice('data:image/svg+xml,'.length))
}

describe('F5 封面兜底', () => {
  it('F5-1 生成 SVG 不含「竞品」，且带旅游调研定位文案', () => {
    const svg = decode(coverFor({ title: '大理 5 天亲子游攻略', destinations: ['大理'] }))
    expect(svg).not.toContain('竞品')
    expect(svg).toContain('旅游调研')
    expect(svg).toContain(`${BRAND.en.toUpperCase()} · 旅游调研`)
    expect(svg).toContain('大理 5 天亲子游攻略')
    expect(svg).toContain('大理')
  })

  it('F5-2 本地路径直出；无目的地时 byline 回落 BRAND.coverByline', () => {
    // 本地路径 / 后端 data URL 直出，不重新生成
    expect(coverFor({ title: 'T', cover_image: '/assets/brand/report-cover.png' })).toBe(
      '/assets/brand/report-cover.png',
    )
    // 外部失效 URL → 走兜底生成
    const svg = decode(coverFor({ title: 'T', cover_image: 'https://evil.example/x.png' }))
    expect(svg).toContain(BRAND.coverByline)
    expect(svg).not.toContain('evil.example')
    // 无目的地 + 无标题 → 兜底文案
    const bare = decode(coverFor({ title: '' }))
    expect(bare).toContain(BRAND.coverByline)
    expect(bare).toContain('旅游调研')
  })
})
