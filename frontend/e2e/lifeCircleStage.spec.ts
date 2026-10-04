import { expect, test } from '@playwright/test'
import {
  MAP_MIN_RATIO,
  SCROLL_TOL,
  box,
  legend,
  main,
  mapCell,
  metrics,
  openStage,
  panel,
  rulerBox,
} from './stageChecks'

/**
 * 生活圈体检台 · 舞台排版回归（计划 B-v1 主张 ①②③④⑤ 的像素层结案）
 *
 * ## 为什么必须有真浏览器
 *
 * 本仓的单元/集成套件跑在 jsdom 上，而 jsdom 没有排版引擎：`getBoundingClientRect` 恒为 0×0，
 * 百分比高度、`grid` 的 stretch、滚动容器全都不成立。内置浏览器面板更糟一次 —— 实测它
 * `requestAnimationFrame` 3.6 秒 0 帧（渲染步被停掉），那时"画布没跟随容器变高"这类观察
 * **既不能证实也不能证伪**。所以像素层的主张只能在真浏览器里钉，这里就是那一层。
 *
 * ## 数据与阈值
 *
 * 数据态用 `localStorage` 钉 fixture（见 `openStage`），不依赖后端；只有"画布跟随容器变高"
 * 那条需要真 BMapGL，拿不到 AK/网络时显式 skip 并写明原因，不让网络状况伪装成功能回归。
 * 每条断言的数值来自 2026-10-04 的真实量测（1440×900 / 1280×720，Chromium 1.63）；
 * **阈值与 locator 的真源是 `stageChecks.ts`**，与压力试验那条共用一份，漂不了。
 */

test.beforeEach(async ({ page }) => {
  await openStage(page)
})

test('① 整页不滚：main 的内容高 == 可视高', async ({ page }) => {
  const m = await metrics(main(page))
  expect(m.scroll, '整页仍会被内容撑高 ⇒ 图例又会滚出视野').toBeLessThanOrEqual(m.client + SCROLL_TOL)
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
  expect(lb.y + lb.height, '图例底边被 main 下沿切掉').toBeLessThanOrEqual(mb.y + mb.height + SCROLL_TOL)

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
  expect(cell.height, '地图格比视口还高 ⇒ 又被右栏撑长了').toBeLessThanOrEqual(view.height + SCROLL_TOL)
  expect(cell.height, '地图格被压扁（上方区域没有限高）').toBeGreaterThan(view.height * MAP_MIN_RATIO)
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
  }).toBeLessThanOrEqual(SCROLL_TOL)              // 余下 2px = 地图格那一圈 1px 边框

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
  expect(Math.abs(a - b), `落定后地图格仍在动（${a} → ${b}）`).toBeLessThanOrEqual(SCROLL_TOL)
})

test('首屏零布局跳动（CLS）：webfont 换面不许把内容挪位', async ({ page, context }) => {
  // 用浏览器自己的 layout-shift 记账，比"采样两个时刻比高度"更严：它覆盖首屏所有来源的跳动，
  // 而不只是我们已知的那一次。观察器必须从第一个脚本起装，所以走 addInitScript。
  await context.addInitScript(() => {
    const w = window as unknown as { __cls?: number }
    w.__cls = 0
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        // layout-shift 的专有字段不在 `PerformanceEntry` 基面上（tsc 会报 TS2339），
        // 也不保证本档 lib.dom 有 `LayoutShift` ⇒ 就地声明，不把浏览器私有形状当类型契约。
        const shift = e as unknown as { value?: number; hadRecentInput?: boolean }
        if (!shift.hadRecentInput) w.__cls = (w.__cls ?? 0) + (shift.value ?? 0)
      }
    }).observe({ type: 'layout-shift', buffered: true })
  })
  await page.goto('/life-circle/kaili-ev2', { waitUntil: 'load' })
  await expect(mapCell(page)).toBeVisible()
  await page.waitForTimeout(2200)          // 给字体交换留窗口：实测那一跳发生在 ~700ms

  const cls = await page.evaluate(() => (window as unknown as { __cls?: number }).__cls ?? 0)
  // 变异测试过的阈值：把 index.html 改回 display=swap，本条在 1280×720 报 CLS=0.4584 并红，
  // 1440×900 因为那一行不换行照绿 —— 所以必须两档都跑。0.01 是 Google Web Vitals"良好"档的一半。
  expect(cls, `首屏 CLS = ${cls.toFixed(4)}，超过 0.01`).toBeLessThan(0.01)
})

/**
 * 2.10 的结案在隔壁：上面这些判据是 2026-10-04 在 **macOS** Chromium 上量的，CI 跑 **Linux**
 * Chromium，字体替换后余量够不够 —— `lifeCircleStageFontStress.spec.ts` 用**同一份阈值**
 * （两者都从 `stageChecks.ts` 取）在"拦掉 webfont"与"根字号 1.25×"两种度量下重跑，
 * 把这件事从推断变成实测。
 */
