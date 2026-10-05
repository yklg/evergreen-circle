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

  // 批 2′：组队降级提示要**留得住**。这里刻意放在"5 轮 message 都到齐之后"再断言 ——
  // 如果页面把降级当普通进度文案（`runMsg`）渲染，它早被后面的 message 冲掉了。
  const notice = page.getByText(/本次专家队由保底名单编排/)
  await expect(notice, '降级提示没出现或被后续 message 冲掉').toBeVisible()
  const noticeBox = await notice.boundingBox()
  expect(noticeBox!.height, '降级提示行高异常').toBeGreaterThan(8)
  expect(noticeBox!.height, '降级提示行高异常').toBeLessThan(80)

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

/**
 * ── 出行方式段控（travel_mode 前端可见可控）───────────────────────────
 *
 * 页面数据通道与上面两条相同：真实模式 + `e2e/support/lcRunningApi.mjs`。
 * 历史列表由 `/api/e2e/records?on=0|1` 切换，用来把页面停在**两个 CTA 挂载点**之一：
 * 有记录态的头部行（h-9）与无记录态的首屏行（h-11）。只测一处＝另一半没人看过。
 *
 * 三条主张，全部由 DOM 变异实测过"能咬住"（见 `mutate_round3.mjs` 的回执）：
 * 1. 段控可见且**在 CTA 行矩形内** ⇒ 摘掉无记录态那个挂载点、或把段控挪出这一行都会红；
 * 2. CTA 行**不得横向溢出**（`scrollWidth - clientWidth ≤ 1`）且输入框宽 ≥ 140
 *    ⇒ 这一条盯的是输入框的 `min-w-0`：删掉它输入框退回 `size=20` 的固有宽 173px，
 *    1280 档整行溢出 17px；把段控改成整块（`display:block`）则输入框被压到 26px、溢出 145px，
 *    两种改法都被这一条抓住；
 * 3. 请求体：动了段控才带 `travel_mode`，没动就**不带这个键** —— 后端 `extra="forbid"`
 *    会静默丢弃未声明的键，而"没表态"与"选了步行"在缓存键上必须可区分。
 *
 * 反过来说，段控自身宽度（≥126）与行高（≤40）在这里是**结果性**读数：实测删 `shrink-0`
 * 一类"保护段控"的写法完全无影响（段控不被压扁靠的是"输入框是唯一可伸缩项"），
 * 所以不拿它们当机制判据，只当回归哨兵。
 */
const PICKER = '[role="tablist"][aria-label="出行方式"]'

test.afterEach(async ({ request }) => {
  // `records` 开关是**服务端全局态**：无记录态那条用例把它切到 0 后必须复位，
  // 否则同一次运行里后面的用例会静默跑在无记录态（真踩过：整批读数全同）。
  await request.get(`${MOCK}/api/e2e/records?on=1`)
})

/** 开到真实模式，records=false 时历史列表为空 ⇒ 页面停在无记录态首屏 CTA 行 */
async function openLiveCta(page: import('@playwright/test').Page, records: boolean) {
  const set = await page.request.get(`${MOCK}/api/e2e/records?on=${records ? 1 : 0}`)
  expect(set.ok(), 'mock 后端没起来（webServer 没拉起 8799？）').toBe(true)
  await page.addInitScript(() => localStorage.setItem('verda.dataMode.v1', 'live'))
  await page.goto('/life-circle/custom')
  const cta = page.getByRole('button', { name: /开始体检/ })
  await expect(cta, '真实模式的「开始体检」入口没出现').toBeVisible()
  await expect(page.locator(PICKER), `${records ? '有' : '无'}记录态的出行方式段控没出现`).toBeVisible()
  // 段控在两个挂载点里各有一份，`toBeVisible()` 分不出页面停在哪一个 —— 两个 CTA 行的
  // placeholder 已统一成「社区名 / 经纬度」，唯一可分辨的是 aria-label。不锁这一条就会拿
  // 首帧的无记录态行（h-11，尚未布局时整行 0×0）去量有记录态的几何。
  await expect(
    page.getByLabel(records ? '重新体检目标（社区名或经纬度）' : '首次体检目标（社区名或经纬度）'),
    `${records ? '有' : '无'}记录态未生效：页面还停在另一个 CTA 挂载点上`,
  ).toBeVisible()
  return cta
}

/** 段控必须落在 CTA 行矩形内，且这一行既不横向溢出、也不被撑成两行 */
async function expectInlinePicker(page: import('@playwright/test').Page, rowMaxHeight: number) {
  const stat = await page.locator(PICKER).evaluate((el) => {
    const row = el.parentElement
    const input = row?.querySelector('input')
    if (!row || !input) throw new Error('段控不在含输入框的 CTA 行里 ⇒ 挂载点被改坏了')
    const rb = row.getBoundingClientRect()
    const pb = el.getBoundingClientRect()
    return {
      pickerW: +pb.width.toFixed(1),
      inputW: +input.getBoundingClientRect().width.toFixed(1),
      rowH: +rb.height.toFixed(1),
      overflow: +(row.scrollWidth - row.clientWidth).toFixed(1),
      insideRow: pb.y >= rb.y - 1 && pb.y + pb.height <= rb.y + rb.height + 1,
    }
  })
  expect(stat.pickerW, `段控宽 ${stat.pickerW}px < 126 ⇒ 三枚键被压窄了`).toBeGreaterThanOrEqual(126)
  expect(stat.insideRow, '段控越出 CTA 行矩形 ⇒ 已经不在同一行了').toBe(true)
  expect(stat.overflow, `CTA 行横向溢出 ${stat.overflow}px ⇒ 输入框不再可缩（min-w-0 被摘？）`).toBeLessThanOrEqual(1)
  expect(stat.inputW, `输入框只剩 ${stat.inputW}px ⇒ 段控把它的宽度抢走了`).toBeGreaterThanOrEqual(140)
  expect(stat.rowH, `CTA 行高 ${stat.rowH}px > ${rowMaxHeight} ⇒ 多占了一行`).toBeLessThanOrEqual(rowMaxHeight)
}

test('出行方式段控与 CTA 行同行：有记录态（h-9）与无记录态（h-11）两处都不加高', async ({ page }) => {
  await openLiveCta(page, true)
  await expectInlinePicker(page, 40)

  // 换到无记录态：同一个组件、另一个挂载点，重新加载页面即可
  await page.reload()
  const set = await page.request.get(`${MOCK}/api/e2e/records?on=0`)
  expect(set.ok()).toBe(true)
  await page.reload()
  await openLiveCta(page, false)
  await expectInlinePicker(page, 48)
})

test('没动段控 ⇒ 请求体不带 travel_mode 键，且默认显示步行（与后端缺省同口径）', async ({ page }) => {
  const cta = await openLiveCta(page, true)
  await expect(page.getByRole('tab', { name: '步行' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: '骑行' })).toHaveAttribute('aria-selected', 'false')

  const req = page.waitForRequest((r) => r.url().endsWith('/api/tasks') && r.method() === 'POST')
  await cta.click()
  const body = JSON.parse((await req).postData() ?? '{}')
  expect('travel_mode' in body, `未表态却替用户发了 travel_mode=${String(body.travel_mode)}`).toBe(false)
})

test('选骑行再发起 ⇒ 请求体 travel_mode=riding（同地点换口径不得复用缓存）', async ({ page }) => {
  const cta = await openLiveCta(page, true)
  await page.getByRole('tab', { name: '骑行' }).click()
  await expect(page.getByRole('tab', { name: '骑行' })).toHaveAttribute('aria-selected', 'true')

  const req = page.waitForRequest((r) => r.url().endsWith('/api/tasks') && r.method() === 'POST')
  await cta.click()
  const body = JSON.parse((await req).postData() ?? '{}')
  expect(body.travel_mode, `请求体没带上出行方式：${JSON.stringify(body)}`).toBe('riding')
})
