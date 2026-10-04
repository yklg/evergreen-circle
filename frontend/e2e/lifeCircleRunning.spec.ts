import { expect, test, type Route } from '@playwright/test'

/**
 * 2.2c · 「体检进行中」横幅按轮次增长时，地图与右栏不能被压塌
 *
 * 为什么单独一个文件：这条要在**真实模式**跑（那块横幅是 `!isFixture && runActive` 才出现），
 * 而布局那批用例走的是 fixture 态。两者数据通道完全不同，混在一起会让 beforeEach 变成
 * 一堆条件分支 —— 分开写，各自的前提都是直的。
 *
 * 数据流靠 `page.route` 造：POST `/api/tasks` 发一个任务号，`/api/tasks/{id}/stream` 回一段
 * 命名事件齐全的 SSE（5 个 `round` 就是真机上"取证扩容回合"最多的那一批的量级）。
 * 其余 `/api/**` 一律回空数组，且**必须先注册** —— Playwright 的路由按注册逆序匹配，
 * 后注册的具体路由才赢。地图 AK 也回空：走降级画布，几何照样能量，且不依赖外网。
 */

const TASK = 'lc-e2e-1'
const ROUNDS = 5

const sseEvent = (type: string, data: unknown) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`

/** 一轮取证回应的载荷：字段就是页面会读的那几个（pass_no/dispatched/pool_remaining/anchors_dropped） */
function roundRow(i: number) {
  return {
    round: {
      pass_no: i,
      dispatched: i % 2 === 0,
      pool_remaining: 32 - i * 4,
      anchors_dropped: i === 2 ? 1 : 0,
      calls: 1,
      anchors_sent: 1,
      anchors_used: 1,
    },
    text: `取证扩容 · 第 ${i + 1} 轮：药店在 6 格未覆盖，派 1 个锚点补采`,
  }
}

async function streamScript(route: Route) {
  let body = sseEvent('progress', { stage: 'collect', percent: 24 })
  body += sseEvent('message', { text: '采集圈内 POI 与采样点' })
  for (let i = 0; i < ROUNDS; i += 1) body += sseEvent('round', roundRow(i))
  body += sseEvent('progress', { stage: 'analyze', percent: 62 })
  // 刻意不发 report_ready / done：这条测的就是"进行中"那一屏，任务必须停在 running
  await route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body,
    headers: { 'cache-control': 'no-cache' },
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('verda.dataMode.v1', 'live'))
  // 兜底通配先注册 ⇒ 后面的具体路由优先
  await page.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/map-config*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"browser_ak":"","map_style_id":""}' }))
  // 生活圈这条链认 `taskId`（camelCase，见 api.ts:createLivingCircleTask 的校验）；
  // 别照 createTask 的 `task_id` 写 —— 那样会被判"创建体检任务失败（HTTP 200）"。
  await page.route('**/api/tasks', (r) => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ taskId: TASK, kind: 'life_circle' }),
  }))
  await page.route(`**/api/tasks/${TASK}/stream`, streamScript)
})

/**
 * 为什么现在标 fixme（不是删掉，也不是放宽断言凑绿）
 *
 * 已打通：`POST /api/tasks`（返回 `taskId`，不是 `task_id`）与 `GET /api/tasks/{id}/stream`
 * 都发出去了，SSE 载荷按 `progress` / `round` 的字段形状给全。
 * 没打通的是**任务注册表**：那块横幅的条件是 `!isFixture && runActive`，而 `runActive`
 * 取的是 `taskRegistry` 里该任务 `status === 'running'` —— 光把事件喂进 `EventSource`
 * 不足以让它进入 running（还要 register/派生那一层）。继续做就得把注册表的时序一起 stub，
 * 那等于伪造半个后端：一旦 stub 与真实实现漂移，这条测试就会"永远绿着但什么也没测"。
 *
 * 结案路径二选一：① CI 里带真后端（compose 已有 api 服务）跑这条；② 给 flow 层留一个
 * 测试注入口（`lifeCircleFlow.ts` 已有 `__test` 钩子，但只覆盖事件解析、不含注册表）。
 * 在那之前，像素层的 ⑤ 仍由源码钉子 TC-11 + `:648` 的限高兜着。
 */
test.fixme('真实模式 5 轮取证账上屏后，地图格与右栏仍有可用高度', async ({ page }) => {
  await page.goto('/life-circle/custom')
  const cta = page.getByRole('button', { name: /开始体检/ })
  await expect(cta, '真实模式的「开始体检」入口没出现（页面结构变了？）').toBeVisible()
  await page.locator('main input').first().fill('凯里老街')
  await cta.click()

  await expect(page.getByText('生活圈体检进行中 ·')).toBeVisible()
  await expect(page.getByText(/^取证扩容 · 第 /)).toHaveCount(ROUNDS)

  const view = page.viewportSize()!
  const cell = await (await page.locator('main [class*="lg:grid-rows-"] > div').first().boundingBox())!
  expect(cell.height, `地图格被压到 ${cell.height}px ⇒ 无界横幅又在抢视口`).toBeGreaterThan(view.height * 0.45)

  const aside = page.locator('main aside')
  const am = await aside.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight, top: el.getBoundingClientRect().top }))
  expect(am.client, '右栏没有可视高度了').toBeGreaterThan(240)
  expect(am.scroll).toBeGreaterThan(am.client)          // 内容仍超出 ⇒ 由右栏自己滚

  const legend = await (await page.locator('div[class*="left-3"][class*="top-3"]').first().boundingBox())!
  expect(legend.y, '图例被顶出地图格上沿').toBeGreaterThanOrEqual(cell.y - 1)
  expect(legend.y + legend.height, '图例超出视口下沿').toBeLessThanOrEqual(view.height + 1)
  expect(am.top + am.client, '右栏底边越出视口').toBeLessThanOrEqual(view.height + 1)
})
