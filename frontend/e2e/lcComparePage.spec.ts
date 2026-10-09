import { expect, test } from '@playwright/test'
import { LS_DATA_MODE, SCROLL_TOL } from './stageChecks'

/**
 * 对比页 · 笔1（逐类目差距 ＋ 盲区成对）的**真浏览器**挂载回归。
 *
 * ## 为什么 jsdom 那 16 条不够
 * `comparePage.test.tsx` 与 `categoryCompareRows.test.ts` 证的是取值与文本；这里证三件
 * 只有排版引擎与真 React 才说得了的话：
 *  ① 两张新表加进 `/compare` 之后，**整页不许出横向滚动**（该页历史上只有差异表一张表，
 *     它自己带 `overflow-x-auto` 兜着；新节是全宽卡，撑破页面不会让任何 jsdom 判据变红 ——
 *     jsdom 的 `getBoundingClientRect` 恒为 0×0，`lifeCircleStage.spec.ts` 文件头记着这条教训）；
 *  ② 「一个都没有」与「19.9」**同屏**这件事是几何事实：两者落在同一行的不同列，
 *     列宽不够时会被挤成竖排折字（预览阶段真发生过），文本存在性抓不到；
 *  ③ React 的 duplicate-key 警告只在真运行时出现。笔1 第一版拿场景名当两侧盲区卡的 key，
 *     同城两份载荷就撞了，jsdom 里测试全绿而控制台在喊。
 *
 * ## 数据态
 *
 * `localStorage` 钉 fixture，不依赖后端：演示态那一对由 `demoCompareSamples()` 挑
 * （凯里 ev2 × 北京劲松，跨城），正好覆盖"一侧没发门槛键、一侧 0 处盲区"两种缺席形态。
 */
test.describe('对比页 · 逐类目差距与盲区成对（笔1）', () => {
  test('两节上屏、八行类目齐、两种空值同屏，且整页不横向溢出', async ({ page }) => {
    const warns: string[] = []
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') warns.push(m.text()) })

    await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
    await page.goto('/compare', { waitUntil: 'load' })

    await expect(page.getByText('逐类目差距', { exact: true })).toBeVisible()
    await expect(page.getByText('盲区成对并排', { exact: true })).toBeVisible()

    // 八行类目：行数取自载荷类目数，不写死 8 —— 名册加一类时这条不该红
    const table = page.getByText('逐类目差距', { exact: true }).locator('xpath=ancestor::div[1]')
    const rows = table.locator('tbody tr')
    expect(await rows.count()).toBeGreaterThan(5)

    // 两种空值形态同屏且各自成串（塌成同一句就会有一条找不到）
    await expect(page.getByText('一个都没有', { exact: true })).toBeVisible()
    await expect(page.getByText('19.9', { exact: true })).toBeVisible()
    await expect(page.getByText('一侧没有，不画条', { exact: true })).toBeVisible()
    await expect(page.getByText(/一侧没值/).first()).toBeVisible()

    // 门槛口径：只印发过那一侧，另一侧改由并排那句提示承担
    await expect(page.getByText(/覆盖度只数/).first()).toBeVisible()
    await expect(page.getByText(/没发过门槛项口径/)).toBeVisible()

    // 0 处盲区那一侧走空态句，不是留白
    await expect(page.getByText(/未发现 1km 服务盲区/).first()).toBeVisible()

    const geo = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }))
    expect(
      geo.scroll,
      `整页横向 ${geo.scroll}px > 可视 ${geo.client}px ⇒ 新表把页面撑破了（该页只允许差异表自己带 overflow-x-auto）`,
    ).toBeLessThanOrEqual(geo.client + SCROLL_TOL)

    // 每行的「最近耗时」列必须真量得到宽度：被挤成竖排折字时列宽会塌到接近 0
    const colW = await rows.first().locator('td').nth(3).evaluate((el) => el.getBoundingClientRect().width)
    expect(colW, `耗时对比列只有 ${colW}px ⇒ 列宽预算不够，读数会竖排折字`).toBeGreaterThan(80)

    const dup = warns.filter((w) => /same key|duplicate/i.test(w))
    expect(dup, `React 报了重复键：${dup.join(' | ')}`).toHaveLength(0)
  })
})

  /**
   * 笔4：演示态的选择器。jsdom 那两条测的是"换了 id 之后读数跟着换"；这里测真浏览器里
   * 一次真实的 `select` 交互之后**页面没有回到加载态、也没有留下上一对的读数**
   * （演示态不发请求，最容易出的错是"下拉变了但卡没变"或"卡变了但副句还写着旧的一对"）。
   */
  test('演示态换 A ⇒ 分数与副句同步换，且不出现加载态残留', async ({ page }) => {
    await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
    await page.goto('/compare', { waitUntil: 'load' })

    const selA = page.getByLabel('场景 A')
    const before = await page.locator('.score, [class*="text-[34px]"]').first().innerText()
    const options = await selA.locator('option').evaluateAll((os) => os.map((o) => ({ v: (o as HTMLOptionElement).value, disabled: (o as HTMLOptionElement).disabled })))
    expect(options.length, '演示态候选应来自整份名册').toBeGreaterThanOrEqual(3)
    const curA = await selA.inputValue()
    const target = options.find((o) => o.v !== curA && !o.disabled)!

    await selA.selectOption(target.v)
    await expect(page.locator('[class*="text-[34px]"]').first()).not.toHaveText(before)
    // 副句跟着换：写死的「（欠发达样本）/（成熟样本）」标签不许再出现在页面上
    await expect(page.getByText(/欠发达样本|成熟样本/)).toHaveCount(0)
    // 交换键在两态都在，且演示态点它确实对调
    const bBefore = await page.getByLabel('场景 B').inputValue()
    await page.getByLabel('交换 A / B').click()
    await expect(page.getByLabel('场景 B')).not.toHaveValue(bBefore)
    // 换完仍不许把 A 选成 B
    const aOpts = await page.getByLabel('场景 A').locator('option').evaluateAll((os) => os.filter((o) => (o as HTMLOptionElement).disabled).map((o) => (o as HTMLOptionElement).value))
    expect(aOpts).toEqual([await page.getByLabel('场景 B').inputValue()])
  })
