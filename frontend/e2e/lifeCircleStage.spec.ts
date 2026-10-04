import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * 生活圈体检台 · 舞台排版回归（计划 B-v1 主张 ①②③④⑤ 的像素层结案）
 *
 * 数据态固定走 fixture（`verda.dataMode.v1` = `fixture`），不依赖后端；
 * 只有"画布跟随容器变高"那条需要真 BMapGL，拿不到 AK/网络时会显式 skip 并说明原因。
 *
 * 每条断言的数值都来自 2026-10-04 的真实量测（1440×900 / 1280×720，Chromium 1.63），
 * 不是拍脑袋的阈值；容差只为吸收 1–2px 的滚动条与亚像素差异。
 */

const LS_DATA_MODE = 'verda.dataMode.v1'
const SCENE = '/life-circle/kaili-ev2'

const main = (p: Page): Locator => p.locator('main')
const panel = (p: Page): Locator => p.locator('main aside')
const mapCell = (p: Page): Locator => p.locator('main [class*="lg:grid-rows-"] > div').first()
const legend = (p: Page): Locator => p.locator('div[class*="left-3"][class*="top-3"]').first()
const rulerBox = (p: Page): Locator => p.getByRole('checkbox', { name: /判定尺/ })

const box = async (l: Locator) => await (await l.boundingBox())!
const metrics = async (l: Locator) => await l.evaluate((el) => ({
  client: el.clientHeight,
  scroll: el.scrollHeight,
  scrollTop: el.scrollTop,
}))

test.beforeEach(async ({ page }) => {
  await page.addInitScript(([k, v]) => { localStorage.setItem(k, v) }, [LS_DATA_MODE, 'fixture'])
  await page.goto(SCENE)
  await expect(mapCell(page)).toBeVisible()
  await expect(panel(page).locator('text=服务盲区清单')).toBeVisible()
})

test('① 整页不滚：main 的内容高 == 可视高', async ({ page }) => {
  const m = await metrics(main(page))
  expect(m.scroll, '整页仍会被内容撑高 ⇒ 图例又会滚出视野').toBeLessThanOrEqual(m.client + 2)
})

test('② 右栏自己滚：内容超出可视且 scrollTop 真的可动', async ({ page }) => {
  const a = await metrics(panel(page))
  expect(a.scroll, '右栏内容不该等于可视高（台账/盲区清单没收纳）').toBeGreaterThan(a.client + 200)
  await panel(page).evaluate((el) => { el.scrollTop = el.scrollHeight })
  const moved = await metrics(panel(page))
  expect(moved.scrollTop).toBeGreaterThan(200)
  // 整页仍然不滚 —— 右栏滚不等于页面滚
  expect((await metrics(main(page))).scrollTop).toBe(0)
})

test('③ 右栏滚到底时图例仍在视口内，且真指针点得动', async ({ page }) => {
  await panel(page).evaluate((el) => { el.scrollTop = el.scrollHeight })
  await expect(legend(page)).toBeInViewport()
  const lb = await box(legend(page))
  const mb = await box(main(page))
  expect(lb.y + lb.height, '图例底边被 main 下沿切掉').toBeLessThanOrEqual(mb.y + mb.height + 2)

  // 真点击：这条同时守着「百度注入 .BMap_mask（z-index:9）吞掉勾选」那次事故
  const box1 = rulerBox(page)
  await expect(box1).toBeVisible()
  await box1.check()
  await expect(box1).toBeChecked()
})

test('⑤ 折叠只收色块：判读勾选留在原位仍可点（S3）', async ({ page }) => {
  await expect(page.getByText('采样点耗时热力（0→20min）')).toBeVisible()
  await page.getByRole('button', { name: '收起' }).click()
  await expect(page.getByText('采样点耗时热力（0→20min）')).toBeHidden()
  await expect(rulerBox(page)).toBeVisible()
  await rulerBox(page).check()
  await expect(rulerBox(page)).toBeChecked()
})

test('④ 地图格高度由视口决定，不随右栏内容长（原 bug 的反面）', async ({ page }) => {
  const cell = await box(mapCell(page))
  const view = page.viewportSize()!
  const aside = await metrics(panel(page))
  expect(cell.height, '地图格比视口还高 ⇒ 又被右栏撑长了').toBeLessThanOrEqual(view.height + 2)
  expect(cell.height, '地图格被压扁（上方区域没有限高）').toBeGreaterThan(view.height * 0.45)
  expect(cell.height, '右栏内容更长时地图必须仍稳定').toBeLessThan(aside.scroll)
})

test('画布跟随容器变高（live BMapGL；降级分支走 viewBox 自适应）', async ({ page }) => {
  const host = page.locator('[data-lc-map]')
  if (!(await host.count())) {
    test.skip(true, '没走 live 分支（无 AK / 无网络）⇒ 降级 SVG 画布按 viewBox 自适应，本条不适用')
    return
  }
  const canvas = page.locator('[data-lc-map] canvas').first()

  /**
   * 只比"稳定后"相等，不等加载中的某一帧 —— 这条是被实测教出来的：
   * CJK 字体约 700ms 落地交换，表头从两行收回一行，地图格随之 572 → 620px
   * （1280×720 才有这一跳；1440×900 那一行不换行，全程不动）。
   * 在切换两侧各测一次 host / canvas，就会比出 48px 的"假红"。
   */
  await expect.poll(async () => Math.abs((await box(host)).height - (await box(canvas)).height), {
    timeout: 8000, intervals: [200, 400, 800],
  }).toBeLessThanOrEqual(2)              // 余下 2px = 地图格那一圈 1px 边框

  const h0 = (await box(host)).height

  await host.evaluate((el) => { el.style.height = '320px' })
  await expect.poll(async () => (await box(canvas)).height, { timeout: 5000, intervals: [250, 500] })
    .toBeLessThan(360)

  await host.evaluate((el) => { el.style.height = '' })
  await expect.poll(async () => (await box(canvas)).height, { timeout: 5000, intervals: [250, 500] })
    .toBeGreaterThan(h0 - 40)
})

test('首屏落定后不再抖：地图格高度 1.5s 内不变', async ({ page }) => {
  await page.waitForTimeout(1800)          // 跨过上面记录的那一跳
  const a = (await box(mapCell(page))).height
  await page.waitForTimeout(1500)
  const b = (await box(mapCell(page))).height
  expect(Math.abs(a - b), `落定后地图格仍在动（${a} → ${b}）`).toBeLessThanOrEqual(2)
})
