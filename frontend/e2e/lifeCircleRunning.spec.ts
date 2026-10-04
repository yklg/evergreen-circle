import { expect, test } from '@playwright/test'

/**
 * 2.2c · 「体检进行中」横幅按轮次增长时，地图与右栏不能被压塌
 *
 * 为什么单独一个文件、一个 project：这块横幅的条件是 `!isFixture && runActive`
 * （`LifeCirclePage.tsx:627`），只有**真实模式**会渲染它；而布局那批用例走 fixture 态。
 * 数据通道完全不同，混在一起 `beforeEach` 就变成一堆条件分支 —— 分开写，各自前提是直的。
 *
 * ## 为什么这里没有 `page.route`
 *
 * 上一版用 `route.fulfill` 打 SSE，结果任务永远进不了 `running` —— 原因不在注册表
 * （`subscribeLifeCircleTask` 一进来就 `seedRegistry` 写 running，`lifeCircleFlow.ts:138`），
 * 而在**传输层**：fulfill 一次性给完 body 就关连接 ⇒ 客户端 `onError` → `markFailed`
 * ⇒ 横幅刚挂上就被卸载。"停在 running"没法靠伪造响应体做到，只能有一个真保持打开的 SSE，
 * 所以这里改用一个只服务于本用例的最小 mock 后端（`e2e/support/lcRunningApi.mjs`），
 * 由第二个 dev server（5200）把 `/api` 代理过去。
 * **页面走的仍是生产那条链**：`createLivingCircleTask → subscribeLifeCircleTask → taskRegistry → 横幅`，
 * 一行生产码都没为测试让路。
 */

const MOCK = 'http://127.0.0.1:8799'
/**
 * 横幅里那一列的**结构锚点**：横幅根是 `role="status"`，它的第一个 `<div>` 子节点就是
 * 会按轮次长高的那一列（`LifeCirclePage.tsx:640`）。
 * 刻意不用 `[class*="22vh"]` 找它 —— 那样一旦有人摘掉限高，选择器直接找不到元素，
 * 用例是"因为元素消失而红"，看不出几何到底坏在哪。用结构锚点后，同样的变异会报出
 * 「列高 365px 超过 22vh 上限 160px」这种带数的红。
 */
const BANNER_CELL = '[role="status"] > div.min-w-0'   // 进度条那个 div 没有 min-w-0，不会误匹配

const metrics = (p: import('@playwright/test').Locator) =>
  p.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight }))

/** 起一次真实模式的体检：先告诉 mock 要发几轮，再点「开始体检」 */
async function startRun(page: import('@playwright/test').Page, rounds: number) {
  const set = await page.request.get(`${MOCK}/api/e2e/rounds?n=${rounds}`)
  expect(set.ok(), 'mock 后端没起来（webServer 没拉起 8799？）').toBe(true)
  await page.addInitScript(() => localStorage.setItem('verda.dataMode.v1', 'live'))
  await page.goto('/life-circle/custom')
  const cta = page.getByRole('button', { name: /开始体检/ })
  await expect(cta, '真实模式的「开始体检」入口没出现（页面结构变了？）').toBeVisible()
  await page.locator('main input').first().fill('凯里老街')
  await cta.click()
  await expect(page.getByText('生活圈体检进行中 ·'), '横幅没挂上 ⇒ runActive 仍是 false').toBeVisible()
}

test('真 SSE 下任务停在 running：5 轮取证账逐条上屏，舞台几何不受影响', async ({ page }) => {
  await startRun(page, 5)

  await expect(page.getByText(/^取证扩容 · 第 /)).toHaveCount(5, { timeout: 15_000 })

  const view = page.viewportSize()!
  const cell = await page.locator('main [class*="lg:grid-rows-"] > div').first().boundingBox()
  expect(cell!.height, `地图格被压到 ${cell!.height}px`).toBeGreaterThan(view.height * 0.45)
  expect(cell!.height, '地图格比视口还高 ⇒ 又被内容撑了').toBeLessThanOrEqual(view.height + 2)

  const aside = page.locator('main aside')
  const am = await metrics(aside)
  expect(am.client, '右栏没有可视高度了').toBeGreaterThan(240)
  expect((await aside.evaluate((el) => el.scrollTop = el.scrollHeight)), '右栏不能自滚').toBeGreaterThan(0)

  const legend = await page.locator('div[class*="left-3"][class*="top-3"]').first().boundingBox()
  expect(legend!.y + legend!.height, '图例底边越出地图格').toBeLessThanOrEqual(cell!.y + cell!.height + 2)
})

/**
 * 这条才是 S1 那块限高的**像素级验收**。
 *
 * 5 轮在 720 档只有约 150px，**还没顶到 `lg:max-h-[22vh]`（=158px）** —— 只测 5 轮的话，
 * "有界"这件事根本没被压到，摘掉 max-h 也不会红。所以把回合数按到 12（真机上取证回合
 * 从没到过这个量级，这是故意的压力档）：横幅内容必然超出 22vh，此时必须同时成立 ——
 * 横幅列自身 `clientHeight ≤ 22vh` 且 `scrollHeight > clientHeight`（真在有界内滚）、
 * 地图格仍 > 45% 视口、右栏仍有 > 240px 可视高。
 * 变异验证：把 `LifeCirclePage.tsx` 那列的 `lg:max-h-[22vh]` 摘掉，本条必红。
 */
test('横幅被撑到超过 22vh 时：它自己滚，地图格与右栏仍有可用高度', async ({ page }) => {
  await startRun(page, 12)

  const lines = page.getByText(/^取证扩容 · 第 /)
  await expect(lines).toHaveCount(12, { timeout: 20_000 })

  const view = page.viewportSize()!
  const banner = page.locator(BANNER_CELL)
  const bm = await metrics(banner)
  const cap = Math.round(view.height * 0.22) + 2
  expect(bm.client, `横幅列高 ${bm.client}px 超过 22vh 上限 ${cap}px ⇒ 限高失效`).toBeLessThanOrEqual(cap)
  expect(bm.scroll, `内容只有 ${bm.scroll}px，这一档没压出溢出 ⇒ 压力档失效（改大回合数）`).toBeGreaterThan(bm.client)

  const cell = await page.locator('main [class*="lg:grid-rows-"] > div').first().boundingBox()
  expect(cell!.height, `地图格被压到 ${cell!.height}px ⇒ 无界横幅又在抢视口`).toBeGreaterThan(view.height * 0.45)

  const aside = page.locator('main aside')
  const am = await metrics(aside)
  expect(am.client, '右栏没有可视高度了').toBeGreaterThan(240)

  const legend = await page.locator('div[class*="left-3"][class*="top-3"]').first().boundingBox()
  expect(legend!.y, '图例被顶出地图格上沿').toBeGreaterThanOrEqual(cell!.y - 1)
  expect(legend!.y + legend!.height, '图例底边越出地图格').toBeLessThanOrEqual(cell!.y + cell!.height + 2)
})
