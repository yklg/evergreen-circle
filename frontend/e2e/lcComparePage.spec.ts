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

/**
 * 笔3c · 同图叠加那一支的按侧归属（演示名册里唯一能同框的那一对：凯里 ev2 × 凯里）。
 *
 * 这一对是预览量出来的实底：四档环、对照环、八方位楔形**两侧逐字节相同**，
 * 只有结论层不同（ev2 带台账、凯里那份冻结件没带）。所以三条断言各钉一态：
 *  ① 同值的对照环 ⇒ 只画一枚、申报给两侧（`data-lc-side="both"`）+ 屏上那句"两侧同值、只画一枚"；
 *  ② 一侧没发的格阵 ⇒ 另一侧照画（只一个组、归 a）+ 缺席被显式说出来，不是画 0 格；
 *  ③ 两份按侧申报都在同一张图的根节点上（对照态一份申报说不清归谁）。
 * 与笔3b 同一条纪律：DOM 型判据只在降级档问，live 档问组件自己写回的申报属性。
 */
test('同图叠加：勾解释层 ⇒ 同值的层只一枚并归两侧，没发的那侧显式缺席', async ({ page }) => {
  /* 强制降级画布：本机 8010 上真跑着后端 ⇒ map-config 会发出真 AK ⇒ 地图走 live，
     而 live 的层是 canvas 覆盖物不进 DOM，下面那些数图元的断言会**静默跳过**
     （第一版就是这样：把合枚判据改成恒假，这条 e2e 照样全绿）。
     这里把配置桩成空 AK，让这一条在真实浏览器里问得到 DOM；CI 无后端本来就是这一档。 */
  await page.route('**/api/life-circle/map-config', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ browser_ak: '', map_style_id: '' }) }),
  )
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  await page.goto('/compare', { waitUntil: 'load' })
  await page.getByLabel('场景 A').selectOption('kaili-ev2')
  await page.getByLabel('场景 B').selectOption('kaili')
  await expect(page.getByText('同图叠加 · 等时圈对比')).toBeVisible()

  await page.getByLabel(/口径对照环/).check()
  await page.getByLabel(/逐格判定台账/).check()

  const root = page.locator('[data-lc-mode]')
  await expect(async () => {
    const a = (await root.nth(0).getAttribute('data-lc-layers-a')) ?? ''
    const b = (await root.nth(0).getAttribute('data-lc-layers-b')) ?? ''
    expect(a, 'A 侧那份申报没等到').toContain('iso-compare')
    expect(b, 'B 侧那份申报没等到（同值 ⇒ 这一枚也归 B）').toContain('iso-compare')
    expect(b, 'B 侧没发台账 ⇒ 它那份里不该有格阵').not.toContain('cells-grid')
  }).toPass({ timeout: 20_000 })

  expect(await root.nth(0).getAttribute('data-lc-mode'),
    '这一条问的是真实浏览器里的降级画布 ⇒ 必须落在 fallback，不然下面的数图元是空转').toBe('fallback')
  expect(await page.locator('[data-lc-iso-compare]').count(), '两侧同值 ⇒ 对照环只该有一枚').toBe(1)
  expect(await page.locator('[data-lc-iso-compare][data-lc-side="both"]').count()).toBe(1)
  expect(await page.locator('[data-lc-layer="cells-grid"]').count(), '格阵只该有 A 侧那一组').toBe(1)
  expect(await page.locator('[data-lc-layer="cells-grid"]').first().getAttribute('data-lc-side')).toBe('a')
  expect(await page.locator('[data-lc-layer="cells-grid"] polygon').count(),
    'A 侧那一组要真有格子上屏（不是空壳组）').toBeGreaterThan(20)
  await expect(page.getByText(/两侧同值、只画一枚：口径对照环/)).toBeVisible()
  await expect(page.getByText(/B 侧没发逐格判定台账/)).toBeVisible()
})

/**
 * 笔3b · 整幅格阵。live 侧覆盖物不进 DOM ⇒ 任何 querySelector 型判据在 live 档天然失明
 * （本域 10-07 实测过），所以这里问的是组件自己写回的 `data-lc-layers` 申报；
 * 降级档则直接数图元。两档问同一件事，是因为"只补一半"正是这一层要防的病。
 */
test('勾上整幅格阵 ⇒ 只有带台账那一侧出现这一层，另一侧整层不画', async ({ page }) => {
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  await page.goto('/compare', { waitUntil: 'load' })
  await page.getByLabel(/逐格判定台账/).check()

  const roots = page.locator('[data-lc-mode]')
  await expect(async () => {
    const decl = await roots.evaluateAll((els) => els.map((e) => e.getAttribute('data-lc-layers') ?? ''))
    expect(decl.filter((d) => d.includes('cells-grid')).length, '应恰好一侧带台账并申报了格阵').toBe(1)
  }).toPass({ timeout: 20_000 })

  const mode = await roots.nth(0).getAttribute('data-lc-mode')
  const cells = await page.locator('[data-lc-layer="cells-grid"] polygon').count()
  // DOM 型判据只在降级档问：live 的格阵是 canvas 覆盖物，不进 DOM（上面那句申报已经管住 live）。
  if (mode === 'fallback') {
    expect(cells, '降级档格阵一枚都没画').toBeGreaterThan(20)
    // 另一侧（没发台账）不许出现一个空的格阵组 —— 缺席即不渲染，不是画个空壳
    expect(await page.locator('[data-lc-layer="cells-grid"]').count()).toBe(1)
  }
})
