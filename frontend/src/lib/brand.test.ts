import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { BRAND } from './brand'

/* 品牌漂移守卫。
 *
 * `index.html` 是静态壳 —— 首屏（JS 执行前）与 SEO 用的 <title> 必须写死，
 * 无法 import `brand.ts`。为不让"改一处忘另一处"静默漂移，这里用测试把它钉住
 * （与 backend/tests/test_api_mirror_guard.py 同款思路）。
 *
 * 失败时的处理：两边改成一致即可 —— 品牌名改名应同时改
 * `src/lib/brand.ts` 的 BRAND.title 与 `index.html` 的 <title>。
 */

const INDEX_HTML = fileURLToPath(new URL('../../index.html', import.meta.url))

describe('brand.ts ↔ index.html 漂移守卫', () => {
  const html = readFileSync(INDEX_HTML, 'utf-8')

  it('index.html 的 <title> 与 BRAND.title 完全一致', () => {
    const m = html.match(/<title>([\s\S]*?)<\/title>/)
    expect(m, 'index.html 缺少 <title>').not.toBeNull()
    expect(m![1].trim()).toBe(BRAND.title)
  })

  it('theme-color 与 BRAND.themeColor 一致', () => {
    const m = html.match(/<meta\s+name="theme-color"\s+content="([^"]+)"/)
    expect(m, 'index.html 缺少 theme-color').not.toBeNull()
    expect(m![1]).toBe(BRAND.themeColor)
  })

  it('图标声明齐备（SVG 主图标 + iOS 触屏图标）', () => {
    expect(html).toContain('rel="icon"')
    expect(html).toContain('href="/favicon.svg"')
    expect(html).toContain('rel="apple-touch-icon"')
    expect(html).toContain('href="/apple-touch-icon.png"')
  })

  it('brand.ts 自身取值稳定（防止误改品牌名而不知情）', () => {
    expect(BRAND.en).toBe('Verda')
    expect(BRAND.zh).toBe('青野')
    expect(BRAND.full).toBe('青野 Verda')
    expect(BRAND.title).toContain(BRAND.full)
    expect(BRAND.coverByline).toContain(BRAND.en)
  })

  it('favicon.svg 使用品牌色（不再是默认紫色占位图）', () => {
    const svg = readFileSync(
      fileURLToPath(new URL('../../public/favicon.svg', import.meta.url)),
      'utf-8',
    )
    expect(svg).not.toContain('#863bff')
    // 品牌色谱系（#8daa97 → #6b8875 渐变）都在鼠尾草绿一支上
    expect(svg).toMatch(/#(8daa97|6b8875|7c9885)/i)
  })

  it('apple-touch-icon.png 存在（由 make_brand_icon.py 从 favicon.svg 生成）', () => {
    const png = fileURLToPath(new URL('../../public/apple-touch-icon.png', import.meta.url))
    const buf = readFileSync(png)
    // PNG magic number
    expect(buf.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
    expect(buf.length).toBeGreaterThan(500)
  })
})

/* F6 产品定位文案哨兵：竞品情报 → 旅游调研（跨文件，防回潮）
 *
 * 覆盖缺口（计划 §5.4 F6）：定位文案散落在 README / index.html / 首页，
 * 只改一处就会留下"前台旅游调研、文档竞品情报"的错位描述。
 * 这里用**跨文件哨兵**把它钉住（与「brand.ts ↔ index.html」同款思路）。 */
describe('产品定位文案：旅游调研（不再出现竞品情报）', () => {
  const FILES = {
    README: fileURLToPath(new URL('../../../README.md', import.meta.url)),
    INDEX_HTML,
    HOME_PAGE: fileURLToPath(new URL('../pages/HomePage.tsx', import.meta.url)),
  }
  const texts = Object.fromEntries(
    Object.entries(FILES).map(([k, p]) => [k, readFileSync(p, 'utf-8')]),
  )

  it('README / index.html / 首页 均不含「竞品」字样', () => {
    for (const [name, text] of Object.entries(texts)) {
      expect(text, `${name} 仍有竞品语义残留`).not.toContain('竞品')
    }
  })

  it('定位文案为旅游调研（README 含「旅游调研」，首页副标题与 BRAND.tagline 同源）', () => {
    expect(texts.README).toContain('旅游调研')
    expect(texts.INDEX_HTML).toContain(BRAND.title)
    expect(BRAND.title).toContain('旅游调研')
    expect(texts.HOME_PAGE).toContain('旅游调研')
  })
})
