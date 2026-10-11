import { expect, test } from '@playwright/test'
import { LS_DATA_MODE } from './stageChecks'

/**
 * 地标体检入口（片 2）· 报告页那张榜单卡的**几何**判据（测试覆盖评估 F-10）。
 *
 * ## 为什么这条只能在真浏览器里量
 *
 * 发起按钮是**常驻**的（未选中时 disabled），这是刻意的选择：榜单行是 **hover 即选中**
 * （`VSpotRanking` 的 `onMouseEnter`），若按钮"按选中出现/消失"，鼠标扫过榜单就会让
 * 这张卡反复长高、变矮，同时地图 `panTo` 跟着跑。这条主张是**几何事实**，
 * 而 jsdom 没有排版引擎（`getBoundingClientRect` 恒 0×0，见 `lcReportLocalMap.spec.ts:15`）
 * ⇒ 只能在真浏览器量。手法沿用该文件 `:120-121` 的"取整后相减"。
 *
 * ## 造数（无后端）
 *
 * 报告走 `page.route` 拦截 `api/reports` 前缀现造：这份夹具要的是"榜单 + 坐标齐备"这一种现场，
 * 内置样区给不出（都是生活圈体检单，不是攻略）。地图与回读端点同样桩掉，
 * ⇒ 本用例不依赖后端、不依赖 AK、不依赖网络。
 *
 * ## 这条**不**覆盖什么
 *
 * 真实地图 marker 的指针点击（第三方 SDK 不认合成事件，`lib/geo.ts:176-185` 记着）
 * ⇒ 那一步只能手测；本用例走的是**榜单行**那一支（它可自动化）。
 */
const REPORT_ID = 'r-e2e-spot-entry'

function guideReport() {
  return {
    id: REPORT_ID,
    report_type: 'guide',
    title: '地标体检入口回归',
    subtitle: '',
    query: '杭州',
    brands: [],
    mode: 'deep',
    created_at: '2026-10-11T00:00:00Z',
    experts: [],
    toc: [],
    charts: [],
    claims: [],
    evidence: [],
    glossary: [],
    methodology: { window: '单次调研', note: '' },
    sections: [
      {
        id: 'sec-spot',
        title: '二、景点分布调研 · Top榜与位置分布',
        paragraphs: [],
        structured: {
          type: 'spot_ranking',
          data: [
            {
              destination: '杭州',
              items: [
                { spot_id: 'spot_杭州动物园', name: '杭州动物园', rank: 1, score: 95, matched: true, lat: 30.2431, lng: 120.1249 },
                { spot_id: 'spot_杭州少年儿童公园', name: '杭州少年儿童公园', rank: 2, score: 62, matched: true, lat: 30.2389, lng: 120.1288 },
                { spot_id: 'spot_玉皇山', name: '玉皇山', rank: 3, score: 59, matched: true, lat: 30.2231, lng: 120.1499 },
              ],
            },
          ],
        },
      },
    ],
  }
}

test('地标体检入口 · 布局不随 hover 抖动，选中之后才可发起', async ({ page }) => {
  await page.route('**/api/life-circle/map-config', (route) =>
    // 桩成空 AK：本用例量的是那张卡的几何，与地图能不能画出来无关（拿不到 AK 时
    // BMapBlock 退化成 120px 占位，页面照常渲染按钮行）。
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ browser_ak: '', map_style_id: '' }),
    }),
  )
  await page.route('**/api/life-circle/**/spot-checks', (route) =>
    // 未体检过的常态：不出现「查看最近一次的体检」
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ checks: [] }) }),
  )
  await page.route('**/api/reports/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(guideReport()) }),
  )
  await page.addInitScript(([k, v]) => localStorage.setItem(k as string, v as string), [LS_DATA_MODE, 'live'])

  await page.goto(`/report/${REPORT_ID}`, { waitUntil: 'domcontentloaded' })

  const bar = page.locator('[data-spot-launch]')
  await expect(bar, '发起口那一行没渲染出来').toBeVisible({ timeout: 15_000 })
  const launchBtn = bar.getByRole('button', { name: /发起体检/ })

  // 未选中：入口在，但不可点（先点一行或点一个点位）
  await expect(launchBtn).toBeDisabled()

  const box = async () => bar.evaluate((el) => {
    const card = el.parentElement as HTMLElement
    const r = card.getBoundingClientRect()
    return { h: Math.round(r.height), w: Math.round(r.width) }
  })
  const base = await box()

  // 逐行 hover：选中态在行间来回切换，卡片高度与宽度都必须一字不变
  const rows = page.locator('[data-spot-row]')
  const n = await rows.count()
  expect(n, '夹具里没有榜单行 ⇒ 本判据吃不到目标（造数坏了，不是功能坏了）').toBeGreaterThan(1)
  for (let i = 0; i < n; i++) {
    await rows.nth(i).hover()
    const now = await box()
    expect(now.h, `第 ${i + 1} 行 hover 后卡片高度变了 ⇒ 布局随 hover 抖动`).toBe(base.h)
    expect(now.w, `第 ${i + 1} 行 hover 后卡片宽度变了`).toBe(base.w)
  }

  // 第二段：选中之后入口变可用，且文案带该景点名（两段式里"第二段"真的接上了）
  await rows.first().click()
  await expect(launchBtn).toBeEnabled()
  await expect(launchBtn).toContainText('杭州动物园')

  // 点过一行之后卡片几何仍不许变（这次是"选中"而不是"hover"引起的）
  const afterPick = await box()
  expect(afterPick.h, '选中之后卡片高度变了').toBe(base.h)
})
