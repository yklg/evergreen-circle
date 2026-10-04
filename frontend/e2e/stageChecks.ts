import { expect, type Locator, type Page } from '@playwright/test'

/**
 * 舞台几何判据的**唯一来源**（`lifeCircleStage.spec.ts` 与 `lifeCircleStageFontStress.spec.ts` 共用）。
 *
 * 为什么要有这个文件：压力试验那条（2.10）如果自带一份阈值，就迟早和主守卫漂成两个数 ——
 * 换字体那侧悄悄放松一点，主侧红了也没人知道是哪半边在骗人。locator 同理。
 * 数字来由见主守卫文件头注释：2026-10-04 在 macOS Chromium 1.63 真实量测，不是拍的。
 */

export const LS_DATA_MODE = 'verda.dataMode.v1'
export const SCENE = '/life-circle/kaili-ev2'

/** 1–2px 的滚动条与亚像素差异；地图格那一圈 1px 边框也计在这里 */
export const SCROLL_TOL = 2
/** 右栏必须有真内容可滚：台账 + 盲区清单撑出来的实测余量远大于这个数 */
export const ASIDE_OVERFLOW_MIN = 200
/** 地图格下限：上方区（表头 + 有界横幅）不许把它压扁 */
export const MAP_MIN_RATIO = 0.45

export const main = (p: Page): Locator => p.locator('main')
export const panel = (p: Page): Locator => p.locator('main aside')
export const mapCell = (p: Page): Locator => p.locator('main [class*="lg:grid-rows-"] > div').first()
export const legend = (p: Page): Locator => p.locator('div[class*="left-3"][class*="top-3"]').first()
export const rulerBox = (p: Page): Locator => p.getByRole('checkbox', { name: /判定尺/ })

export const box = async (l: Locator) => await (await l.boundingBox())!
export const metrics = async (l: Locator) =>
  await l.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight, scrollTop: el.scrollTop }))

/** 进入体检台并等布局落定（fixture 数据态，不依赖后端） */
export async function openStage(page: Page): Promise<void> {
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  /**
   * `domcontentloaded` 而不是默认的 `load`：版式类由 vite 本地产出，外部 webfont CSS 只是字体。
   * 等 `load` 等于把"fonts CDN 连不上"变成每条用例白等 10s（实测整套从 45s 变 4.6m），
   * 更糟的是它会让人想给网络问题找布局解释。落没落地由下面两个 expect 判。
   */
  await page.goto(SCENE, { waitUntil: 'domcontentloaded' })
  await expect(mapCell(page)).toBeVisible()
  await expect(panel(page).locator('text=服务盲区清单')).toBeVisible()
}

export interface StageGeometry {
  mainClient: number
  mainScroll: number
  asideClient: number
  asideScroll: number
  mapCell: number
  legendHeight: number
  /** 图例浮层：可视高 / 内容高。两者不等就说明 `max-h` 正在生效（2.11 的修复面） */
  legendClient: number
  legendScroll: number
  viewportHeight: number
}

/**
 * 主守卫那四条几何主张（① 整页不滚 / ② 右栏自滚 / ③ 滚到底图例仍在 + 判定尺点得动 /
 * ④ 地图格由视口决定且不被压扁）在**当前页面状态**上重跑一遍，并回报量到的数。
 * 数值判定全部走本文件顶部的共享阈值 —— 与主守卫同一份，漂不了。
 */
export async function assertStageGeometry(page: Page): Promise<StageGeometry> {
  const viewportHeight = page.viewportSize()!.height

  const m = await metrics(main(page))
  expect(m.scroll, '整页仍会被内容撑高 ⇒ 图例又会滚出视野').toBeLessThanOrEqual(m.client + SCROLL_TOL)

  const a = await metrics(panel(page))
  expect(a.scroll, '右栏内容不该等于可视高（台账/盲区清单没收纳）').toBeGreaterThan(
    a.client + ASIDE_OVERFLOW_MIN,
  )
  await panel(page).evaluate((el) => { el.scrollTop = el.scrollHeight })
  expect((await metrics(panel(page))).scrollTop, '右栏 scrollTop 动不了').toBeGreaterThan(200)
  expect((await metrics(main(page))).scrollTop, '右栏滚不等于页面滚').toBe(0)

  await expect(legend(page), '右栏滚到底后图例出了视野').toBeInViewport()
  const lb = await box(legend(page))
  const mb = await box(main(page))
  // 失败信息带上四个数：这条是整套里余量最窄的一条（见字体压力试验），没数字没法归因
  expect(
    lb.y + lb.height,
    `图例底边被 main 下沿切掉：图例 ${lb.y.toFixed(1)}+${lb.height.toFixed(1)}=${(lb.y + lb.height).toFixed(1)} ` +
      `vs main 下沿 ${(mb.y + mb.height).toFixed(1)}（超出 ${(lb.y + lb.height - mb.y - mb.height).toFixed(1)}px，容差 ${SCROLL_TOL}px）`,
  ).toBeLessThanOrEqual(mb.y + mb.height + SCROLL_TOL)

  /**
   * 台账 2.11 的正判据：**图例不许越出地图格**。
   * 与上一条不同，这条是**同源比较**（图例与地图格都在同一个 `<main>` 里，且 `max-h` 挂在地图格上），
   * 所以它与字体度量无关 —— 字体再怎么换，越界就只有"max-h 失效"这一种解释。
   */
  const cellBox = await box(mapCell(page))
  const legendFit = await legend(page).evaluate((el) => ({
    client: el.clientHeight,
    scroll: el.scrollHeight,
  }))
  expect(
    lb.y + lb.height,
    `图例越出地图格（2.11 回归）：图例底 ${(lb.y + lb.height).toFixed(1)} vs 地图格底 ` +
      `${(cellBox.y + cellBox.height).toFixed(1)}；图例 可视 ${legendFit.client} / 内容 ${legendFit.scroll}`,
  ).toBeLessThanOrEqual(cellBox.y + cellBox.height + SCROLL_TOL)
  await rulerBox(page).check()
  await expect(rulerBox(page)).toBeChecked()

  const cell = (await box(mapCell(page))).height
  expect(cell, '地图格比视口还高 ⇒ 又被右栏撑长了').toBeLessThanOrEqual(viewportHeight + SCROLL_TOL)
  expect(cell, '地图格被上方区压扁').toBeGreaterThan(viewportHeight * MAP_MIN_RATIO)
  expect(cell, '右栏内容更长时地图必须仍稳定').toBeLessThan(a.scroll)

  return {
    mainClient: m.client,
    mainScroll: m.scroll,
    asideClient: a.client,
    asideScroll: a.scroll,
    mapCell: cell,
    legendHeight: lb.height,
    legendClient: legendFit.client,
    legendScroll: legendFit.scroll,
    viewportHeight,
  }
}
