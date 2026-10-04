import { expect, test, type Locator, type Page } from '@playwright/test'
import { LS_DATA_MODE } from './stageChecks'

/**
 * 报告页 · 盲区局部图的**真浏览器**挂载回归（计划笔 8 / P0-7）。
 *
 * ## 为什么 jsdom 那两条不够
 *
 * `lcReportLocalMap.test.tsx` 里的 IntersectionObserver 是我们自己造的替身，它证明的是
 * "代码逻辑对"；这一份证明的是"**这个元素在这个页面的滚动结构里真的会被观测到**"——
 * 报告页正文在 `main > div.overflow-y-auto` 里滚，而观察器用的是默认 root（视口）+
 * `rootMargin: 200px`。替身永远测不出"容器滚到位了却没进视口"这类错。
 * 同理，几何（两栏并排、不出横向滚）也只有真排版引擎说了算：jsdom 的
 * `getBoundingClientRect` 恒为 0×0（`lifeCircleStage.spec.ts` 文件头记着这条教训，
 * 内置浏览器面板更是 rAF 停摆 ⇒ 只能来这里）。
 *
 * ## 数据态
 *
 * `localStorage` 钉 fixture，不依赖后端；样区取 `lc-kaili-ev2`（唯一既有逐格台账、
 * 又有盲区可聚的那一份）。
 */

const REPORT = '/report/lc-kaili-ev2'
const PLACEHOLDER = '滚动到此处加载局部图…'

/** 局部图卡片：由图注反推父容器（图注在懒挂载之外，挂载前后都在）。 */
function card(p: Page): Locator {
  return p.getByText(/^局部视图：盲区图层只留/).locator('..')
}
/** 卡片里那块 360px 的地图槽。 */
function slot(c: Locator): Locator {
  return c.locator('[class*="h-[360px]"]')
}

/** 滚回顶部：报告正文的滚动容器是运行时算出来的（按 computed overflow 判定，不保证是 div，
 *  第一版按 `ancestor::div` 找就直接超时），所以从卡片往上逐个问"你能不能竖滚"。 */
async function scrollToTop(c: Locator): Promise<void> {
  await c.evaluate((el) => {
    let p: HTMLElement | null = el.parentElement
    while (p) {
      if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) p.scrollTop = 0
      p = p.parentElement
    }
    window.scrollTo(0, 0)
  })
}

async function openReport(page: Page): Promise<Locator> {
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  await page.goto(REPORT, { waitUntil: 'domcontentloaded' })
  const c = card(page)
  await expect(c).toBeVisible()
  return c
}

test('首屏不预挂第二张：地图槽里只有占位，没有画布/SVG', async ({ page }) => {
  const c = await openReport(page)
  await scrollToTop(c)
  await expect(c.getByText(PLACEHOLDER)).toBeVisible()
  await expect(slot(c).locator('canvas, svg')).toHaveCount(0)
  // 主图仍在 ⇒ 少画的只是第二张，不是整页地图没渲染（否则下一条"挂上"也没有对照）
  await expect(page.locator('[data-lc-map], main svg').first()).toBeVisible()
})

test('滚到卡片 ⇒ 第二张真挂载（画布或 SVG 落地），占位撤走', async ({ page }) => {
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(c.getByText(PLACEHOLDER)).toHaveCount(0)
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  // 两个地图实例并排共存：主图 + 局部图，且横向不溢出
  await expect(page.locator('[data-lc-map]')).toHaveCount(2)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, '两栏 grid 撑出横向滚动条 ⇒ 局部图挤掉了主栏').toBeLessThanOrEqual(2)
  // 卡片不许被 grid 的默认 stretch 拉高：台账卡实测 629px，不 `self-start` 就会在
  // 图注下面多出一截空白边框（这一条只有真排版引擎测得出来，jsdom 里全是 0×0）。
  const slack = await c.evaluate((el) => {
    const slotEl = el.querySelector('[class*="h-[360px]"]')!
    const capEl = el.lastElementChild!
    return Math.round(el.getBoundingClientRect().height
      - (slotEl.getBoundingClientRect().height + capEl.getBoundingClientRect().height))
  })
  expect(slack, '局部图卡被拉伸 ⇒ 图注下方出现空白边框').toBeLessThanOrEqual(2)
})

test('进过一次视口就常驻：滚走再滚回不该重看一次骨架', async ({ page }) => {
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  await scrollToTop(c)
  await page.waitForTimeout(500)
  await c.scrollIntoViewIfNeeded()
  await expect(c.getByText(PLACEHOLDER)).toHaveCount(0)
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
})

test('反向通道：点局部图 → 台账卡选中那一格', async ({ page }) => {
  // 台账卡 → 图 那一向由 jsdom 测（改 state 就重渲染）；**图 → 台账**要靠真指针：
  // LcMap 走的是地图 click 事件（`onCellPick`），jsdom 里既没有 BMapGL 也没有命中测试。
  // `lifeCircleStage.spec.ts` 记过"合成分派打不动 SDK"，但那是给 overlay 派发合成事件；
  // 这里用 CDP 的真实鼠标事件点画布空白处，2026-10-04 实测能选中格子。
  // 只断"选中了某一格"不断是哪一格：落点由视口尺寸与缩放决定，钉死坐标会漂。
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  const selected = page.locator('rect[data-cell]:not([stroke="#E3E8E3"])')
  await expect(selected).toHaveCount(0)
  const bb = (await slot(c).boundingBox())!
  await page.mouse.click(bb.x + bb.width * 0.42, bb.y + bb.height * 0.55)
  await expect(selected).not.toHaveCount(0)
})
