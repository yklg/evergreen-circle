import { expect, test, type Locator, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

import { LS_DATA_MODE } from './stageChecks'

/**
 * 第三屏（方位形状）的**真浏览器**回归 —— 计划笔三 S18。
 *
 * ## 为什么 jsdom 那 13 条不够
 * `shapeScreen.test.tsx` 量不到任何几何：jsdom 的 `getBoundingClientRect` 恒为 0×0
 * （教训原文在 `lifeCircleStage.spec.ts` 文件头）。而这一屏的主张恰好全是几何：
 * 两栏是否真并排、第三张 GL/SVG 实例会不会撑出横向滚动、卡片有没有被 grid 的默认
 * stretch 拉高、选中一个方位之后行高会不会跳。
 *
 * ## 为什么这里强制走降级画布
 * 扇区在 live 分支是 BMapGL 覆盖物（**不进 DOM**），在降级分支才是 `[data-sector]` 的
 * `<polygon>`。为了把"点条形↔点扇区"这条通道钉成可断言的 DOM 事实，这里把
 * `/api/life-circle/map-config` 打成空 AK ⇒ `LcMap` 落静态画布。
 * 真机 BMapGL 上的贴合（楔形与环是否同一中心）不在本文件能力内，需要 AK/网络，
 * 已在交付报告里列为未验证项。
 */

const REPORT = '/report/lc-kaili-ev2'
const SHAPE_CAPTION = /^方位形状：/
const PLACEHOLDER = '滚动到此处加载方位图…'

async function openFallbackReport(page: Page): Promise<Locator> {
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  await page.route('**/api/life-circle/map-config', (route) =>
    route.fulfill({ json: { browser_ak: '', map_style_id: '' } }),
  )
  await page.goto(REPORT, { waitUntil: 'domcontentloaded' })
  const cap = page.getByText(SHAPE_CAPTION)
  await expect(cap, '第三屏图注不在 ⇒ 本文件所有判据失去对象').toBeVisible({ timeout: 15_000 })
  return cap.locator('..')
}

/** 条形行（按 aria-label 认，不按 class —— class 是实现细节，换一套写法就放走回归）。 */
function bars(card: Page | Locator): Locator {
  return card.getByRole('button', { name: /方向最远可达 \d+ 米/ })
}

test('懒挂载：没滚到第三屏时槽里只有占位，滚到才落地', async ({ page }) => {
  const card = await openFallbackReport(page)
  await page.evaluate(() => window.scrollTo(0, 0))
  const slot = card.locator('[class*="h-[360px]"]')
  await expect(slot.locator('canvas, svg')).toHaveCount(0)
  await expect(card.getByText(PLACEHOLDER)).toBeVisible()

  await card.scrollIntoViewIfNeeded()
  await expect(card.getByText(PLACEHOLDER)).toHaveCount(0)
  await expect(slot.locator('canvas, svg')).not.toHaveCount(0)
})

test('三张图并排不撑横向滚动，卡片不被 grid 拉高', async ({ page }) => {
  const card = await openFallbackReport(page)
  await card.scrollIntoViewIfNeeded()
  await expect(card.locator('[data-sector]')).toHaveCount(8)
  await expect(card.locator('[data-sector-hit]')).toHaveCount(8)

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, '第三屏撑出横向滚动条 ⇒ 条形卡挤掉了地图栏').toBeLessThanOrEqual(2)

  const geo = await card.evaluate((el) => {
    const row = el.parentElement!
    const kids = [...row.children] as HTMLElement[]
    // 按**标题文本**认条形卡：`aria-pressed` 会被图例里的边界档按钮命中（第一版就这么误判过）
    const barsEl = kids.find((k) => /方位最远可达/.test(k.textContent ?? '')) ?? null
    const box = (n: Element | null) => (n ? n.getBoundingClientRect() : null)
    const mb = box(el)
    const bb = box(barsEl)
    return {
      cols: getComputedStyle(row).gridTemplateColumns.split(' ').length,
      hasBars: !!barsEl,
      barsRight: mb && bb ? bb.left > mb.left + 40 : false,
      sameBand: mb && bb ? Math.abs(mb.top - bb.top) < 40 : false,
      mapW: Math.round(mb?.width ?? 0),
      barsW: Math.round(bb?.width ?? 0),
      // 图注下方不许出现被 stretch 撑出来的空白
      slack: Math.round(
        el.getBoundingClientRect().height
        - (el.querySelector('[class*="h-[360px]"]')!.getBoundingClientRect().height
           + (el.lastElementChild?.getBoundingClientRect().height ?? 0)),
      ),
    }
  })
  expect(geo.hasBars, '条形卡不在第三屏里 ⇒ 只剩一张地图').toBe(true)
  expect(geo.cols, '两栏没生效').toBeGreaterThanOrEqual(2)
  expect(geo.barsRight, '条形卡不在地图右侧').toBe(true)
  expect(geo.sameBand, '两张卡不在同一横带 ⇒ 版式与上面两行不同构').toBe(true)
  expect(geo.mapW, '地图栏应比条形栏宽（1.6fr : 1fr）').toBeGreaterThan(geo.barsW)
  expect(geo.slack, '卡片被拉伸 ⇒ 图注下方出现空白边框').toBeLessThanOrEqual(2)
})

test('条形 8 行齐全，方位词与米数来自后端键（前端不另抄词表）', async ({ page }) => {
  const card = await openFallbackReport(page)
  await card.scrollIntoViewIfNeeded()
  const rows = bars(page)
  await expect(rows).toHaveCount(8)
  const labels = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))
  expect(labels[0], '第一行应是正北').toContain('正北')
  expect(labels.some((l) => l.includes('正东'))).toBe(true)
  // 读数句与常驻声明都在场
  await expect(page.getByText(/最弱方向：/)).toBeVisible()
  // 这条声明**全页只出现一次**（在右栏常驻声明里）：图注与读数都不复述。
  // 同一句话在两栏各写一遍，改一处漏一处 —— 本域为这类漂移写过太多次勘误。
  await expect(page.getByText(/不参与综合评分/)).toHaveCount(1)
})

test('开关：默认开 ⇒ 8 个扇区；关掉 ⇒ 整层消失；再开 ⇒ 回来', async ({ page }) => {
  const card = await openFallbackReport(page)
  await card.scrollIntoViewIfNeeded()
  const toggle = page.getByRole('switch', { name: '方位形状图层' })
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await expect(card.locator('[data-sector]')).toHaveCount(8)

  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await expect(card.locator('[data-sector]')).toHaveCount(0)

  await toggle.click()
  await expect(card.locator('[data-sector]')).toHaveCount(8)
})

test('双向互指：点条形点亮对应扇区，点扇区选中对应行，且行高不跳', async ({ page }) => {
  const card = await openFallbackReport(page)
  await card.scrollIntoViewIfNeeded()
  const heightBefore = await card.evaluate((el) => Math.round(el.getBoundingClientRect().height))

  await bars(page).nth(2).click()
  await expect(card.locator('[data-sector="2"]')).toHaveAttribute('fill', '#B9665E')
  await expect(bars(page).nth(2)).toHaveAttribute('aria-pressed', 'true')
  await expect(bars(page).nth(0)).toHaveAttribute('aria-pressed', 'false')

  await card.locator('[data-sector-hit="6"]').click()
  await expect(bars(page).nth(6)).toHaveAttribute('aria-pressed', 'true')
  await expect(card.locator('[data-sector="2"]')).not.toHaveAttribute('fill', '#B9665E')

  const heightAfter = await card.evaluate((el) => Math.round(el.getBoundingClientRect().height))
  expect(Math.abs(heightAfter - heightBefore), '选中方位导致行高跳动 ⇒ 下面的内容会跟着抖').toBeLessThanOrEqual(2)
})

/**
 * **不发屏的正对照**：把形状键摘掉（存量件形态），第三屏必须整块消失 ——
 * 不是留一张空图、也不是留一个点了没反应的开关。
 */
test('载荷没有形状键 ⇒ 第三屏整块不出现（无幽灵栏、无假开关）', async ({ page }) => {
  const fixture = JSON.parse(
    readFileSync(new URL('../src/mocks/fixtures/livingCircle/kaili-ev2.json', import.meta.url), 'utf8'),
  ) as Record<string, unknown> & { generated_at: string }
  const lc = JSON.parse(JSON.stringify(fixture)) as {
    isochrones: Record<string, unknown>[]
  }
  lc.isochrones.forEach((z) => {
    delete z.shape
  })
  await page.addInitScript(() => localStorage.setItem(LS_DATA_MODE, 'live'))
  await page.route('**/api/life-circle/map-config', (route) =>
    route.fulfill({ json: { browser_ak: '', map_style_id: '' } }),
  )
  await page.route('**/api/reports/**', (route) =>
    route.fulfill({
      json: {
        id: 'lc-e2e-noshape', report_type: 'living_circle', title: '无形状键回归', subtitle: '',
        query: '', brands: [], mode: 'standard', created_at: fixture.generated_at,
        experts: [], toc: [], sections: [], charts: [], claims: [], evidence: [],
        glossary: [], methodology: { window: '单次体检', note: '' }, living_circle: lc,
      },
    }),
  )
  await page.goto('/report/lc-e2e-noshape', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(/^局部视图：/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(SHAPE_CAPTION)).toHaveCount(0)
  await expect(page.getByRole('switch', { name: '方位形状图层' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /方向最远可达/ })).toHaveCount(0)
  await expect(page.locator('[data-sector]')).toHaveCount(0)
})
