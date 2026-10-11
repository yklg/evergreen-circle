import { expect, test, type Page } from '@playwright/test'

import { LS_DATA_MODE } from './stageChecks'

/**
 * 演示态删除 → 刷新不复活 → 一键还原 —— 的**真浏览器**回归。
 *
 * ## 为什么 jsdom 那 9 条不够
 * `src/__tests__/demoArchiveDeleteRestore.test.tsx` 跑在 jsdom 上：那里的 `localStorage`
 * 是 Node 侧的假实现，同一个文件里的用例**互相看得见**，而"刷新之后还在不在"这件事的
 * 本体是浏览器自己的持久化 + 路由重启后的取数顺序。这一条把它钉在真 Chromium 上：
 * 真 `localStorage`、真 reload、真布局下那个还原按钮点得到点不到。
 *
 * ## 为什么"跨刷新"必须写进同一个 test
 * Playwright 每个 test 是**全新 context**（`playwright.config.ts` 里没有 `storageState`），
 * localStorage 天生不跨 test 继承 ⇒ 拆成两个 test 只能测出"第二个 test 本来就是空的"，
 * 那是恒真，不是回归。所以 reload 必须发生在同一个 test 内部。
 *
 * ## 为什么这里不需要后端
 * 演示态的删除归 `store/demoArchiveStore`（本机归档），**不发任何 HTTP** ——
 * 第一条用例末尾就把这件事断言出来（整段流程里 DELETE 请求数 == 0）。
 * CI 里没有真后端也能跑，这是"烘快照"这条路线比"演示态打后端"多出来的一格。
 *
 * 行用 `[data-record="<id>"]` 认（`components/RecordRow.tsx` 文件头写了为什么）：
 * 一行里同时有标题按钮、来源徽标和删除按钮，数祖先层级或靠 class 都会在下一次改排版时断。
 */

const EV2 = 'lc-kaili-ev2'
const JINSONG = 'lc-beijing-jinsong'
const STRIP = '[aria-label="本机已摘除的演示归档"]'

async function openReportsInDemoMode(page: Page): Promise<string[]> {
  const deletes: string[] = []
  // 只设数据模式；刻意**不清** `evergreen.demoArchive.v1` —— 新 context 本来就是空的，
  // 而 init script 每次导航（含 reload）都会跑，在那里清它等于自己把要测的持久化抹掉。
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  page.on('request', (req) => {
    if (req.method() === 'DELETE') deletes.push(req.url())
  })
  await page.goto('/reports', { waitUntil: 'domcontentloaded' })
  await expect(
    page.locator(`[data-record="${EV2}"]`),
    `演示态报告中心里没有 [data-record="${EV2}"] 那一行 ⇒ 本文件所有判据失去对象`,
  ).toBeVisible({ timeout: 20_000 })
  return deletes
}

/** 摘掉 EV2 那一行（走真实点击链：行内删除按钮 → 确认框里的「删除」）。 */
async function dropEv2Row(page: Page) {
  await page
    .locator(`[data-record="${EV2}"]`)
    .getByRole('button', { name: '删除生活圈体检' })
    .click()
  const dialog = page.locator('[role="dialog"]')
  await expect(dialog.getByText('删除归档记录')).toBeVisible()
  await dialog.getByRole('button', { name: '删除', exact: true }).click()
}

test('删一行 → 刷新仍不复活 → 一键还原把行放回来，且全程不发 DELETE', async ({ page }) => {
  const deletes = await openReportsInDemoMode(page)
  const row = page.locator(`[data-record="${EV2}"]`)
  const strip = page.locator(STRIP)

  await row.getByRole('button', { name: '删除生活圈体检' }).click()
  const dialog = page.locator('[role="dialog"]')
  await expect(dialog.getByText('删除归档记录')).toBeVisible()
  // 确认框的话要说两面（只断"不许吓唬人"会漏掉"根本没解释"这一支）：
  //   不许说：不可撤销 / 再次消耗配额（演示行一次接口都不发）
  //   必须说：只在这台机器上隐藏、可在本页下方一键还原
  await expect(dialog.getByText(/不可撤销/)).toHaveCount(0)
  await expect(dialog.getByText(/再次消耗/)).toHaveCount(0)
  await expect(dialog.getByText(/只在这台机器上隐藏/)).toBeVisible()
  await expect(dialog.getByText(/一键还原/)).toBeVisible()
  await dialog.getByRole('button', { name: '删除', exact: true }).click()

  await expect(row, '点了删除之后那一行还在 ⇒ 本机归档没接住这个写操作').toHaveCount(0)
  await expect(strip, '摘掉一行后还原条必须出现（否则删错一行得开控制台清 localStorage）').toBeVisible()
  await expect(strip.getByText('本机已摘掉')).toBeVisible()

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(
    page.locator(`[data-record="${EV2}"]`),
    '刷新后那一行又长回来了 —— 这正是本轮最初报的那个症状',
  ).toHaveCount(0)
  const stripAfterReload = page.locator(STRIP)
  await expect(stripAfterReload, '摘除记录没跨刷新留住 ⇒ "本机归档"这个所有者只是内存里的临时状态').toBeVisible()

  await stripAfterReload.getByRole('button', { name: /一键还原全部 \d+ 份/ }).click()
  await expect(page.locator(`[data-record="${EV2}"]`), '一键还原没把行放回来').toBeVisible()
  await expect(page.locator(STRIP), '还原之后还原条还挂着 ⇒ 本机摘除记录没被清空').toHaveCount(0)

  expect(deletes, `演示态删除不该发任何 DELETE 请求，实发 ${deletes.length} 次：${deletes.join(', ')}`).toEqual([])
})

test('本机减法只减那一条：摘 ev2 不许动别的生活圈行', async ({ page }) => {
  await openReportsInDemoMode(page)
  const other = page.locator(`[data-record="${JINSONG}"]`)
  await expect(other, '劲松那一行本来就该在演示态列表里（内置快照）').toBeVisible()

  await dropEv2Row(page)

  await expect(page.locator(`[data-record="${EV2}"]`)).toHaveCount(0)
  await expect(other, '摘一行却少了别的项目 ⇒ 本机减法的范围失控').toBeVisible()

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator(`[data-record="${EV2}"]`)).toHaveCount(0)
  await expect(other, '刷新后别的项目也必须照旧在（tombstone 按 id 存，不是"清空整屏"）').toBeVisible()
})
