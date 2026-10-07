import { expect, test, type Locator, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { LS_DATA_MODE } from './stageChecks'

/**
 * 报告页 · 盲区局部图的**真浏览器**挂载回归（计划笔 8 / P0-7）。
 *
 * ## 为什么 jsdom 那两条不够
 *
 * `lcReportLocalMap.test.tsx` 里的 IntersectionObserver 是我们自己造的替身，它证明的是
 * "代码逻辑对"；这一份证明的是"**这个元素在这个页面的滚动结构里真的会被观测到**"——
 * 报告页正文在 `main > div.overflow-y-auto` 里滚，而观察器用的是默认 root（视口）+
 * `rootMargin: 200px`。替身永远测不出"容器滚到位了却没进视口"这类错。
 * 同理，几何（两栏并排、不出横向滚）也只有真排版引擎说了算：jsdom 的
 * `getBoundingClientRect` 恒为 0×0（`lifeCircleStage.spec.ts` 文件头记着这条教训，
 * 内置浏览器面板更是 rAF 停摆 ⇒ 只能来这里）。
 *
 * ## 数据态
 *
 * `localStorage` 钉 fixture，不依赖后端；样区取 `lc-kaili-ev2`（唯一既有逐格台账、
 * 又有盲区可聚的那一份）。
 */

const REPORT = '/report/lc-kaili-ev2'
const PLACEHOLDER = '滚动到此处加载局部图…'

/** 局部图卡片：由图注反推父容器（图注在懒挂载之外，挂载前后都在）。 */
function card(p: Page): Locator {
  return p.getByText(/^局部视图：盲区图层只留/).locator('..')
}
/** 卡片里那块 360px 的地图槽。 */
function slot(c: Locator): Locator {
  return c.locator('[class*="h-[360px]"]')
}

/**
 * 这张地图现在落在哪一档：`live`／`fallback`／还没落定的 `boot`。
 *
 * 读的是**组件申报**的 `data-lc-mode`（`LcMap` 的 `mode` 状态，两棵根节点各贴一个），不再数 canvas ——
 * 数 canvas 是"从 DOM 反推模式"的第二份实现，而"问在哪一档"这件事仓里已经有发话人（`:9` 那句
 * "模式通过 onMapMode 上报"、`:416` 的 `mode`）。更要紧的是实测不可靠：同一份工作区、同一个下午，
 * 这条 spec 上午走 fallback（`反向通道` 被 skip）、下午走 live（同一条**真红**），差别只是那一刻
 * 有没有后端答 `/api/life-circle/map-config`（`src/lib/bmap.ts:4`）⇒ 由 DOM 猜出来的档不是稳定资产。
 *
 * 为什么仍要问档：CI 那个 e2e job 刻意"全 mock、不注入任何真实 AK"，于是两档都会跑到这里 ——
 * 而"canvas 随容器重画"这一族命题**只有 live 有对象**（降级画布走 viewBox 自适应，压根没有 canvas）。
 * 第一版没问档，把 6 条布局判据与 2 条 canvas 判据捆在一起，CI 里整文件红，看起来像"局部图坏了"。
 * 现在布局两档都验、canvas 只在 live 验，降级档改验"svg 确实落地且没塌高"。
 */
async function lcMode(s: Locator): Promise<'boot' | 'live' | 'fallback'> {
  const got = await s.locator('[data-lc-mode]').first().getAttribute('data-lc-mode')
  return got === 'live' || got === 'fallback' ? got : 'boot'
}

/** 滚回顶部：报告正文的滚动容器是运行时算出来的（按 computed overflow 判定，不保证是 div，
 *  第一版按 `ancestor::div` 找就直接超时），所以从卡片往上逐个问"你能不能竖滚"。 */
async function scrollToTop(c: Locator): Promise<void> {
  await c.evaluate((el) => {
    let p: HTMLElement | null = el.parentElement
    while (p) {
      if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) p.scrollTop = 0
      p = p.parentElement
    }
    window.scrollTo(0, 0)
  })
}

async function openReport(page: Page): Promise<Locator> {
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [LS_DATA_MODE, 'fixture'])
  await page.goto(REPORT, { waitUntil: 'domcontentloaded' })
  const c = card(page)
  await expect(c).toBeVisible()
  return c
}

test('首屏不预挂第二张：地图槽里只有占位，没有画布/SVG', async ({ page }) => {
  const c = await openReport(page)
  await scrollToTop(c)
  await expect(c.getByText(PLACEHOLDER)).toBeVisible()
  await expect(slot(c).locator('canvas, svg')).toHaveCount(0)
  // 主图仍在 ⇒ 少画的只是第二张，不是整页地图没渲染（否则下一条"挂上"也没有对照）
  await expect(page.locator('[data-lc-map], main svg').first()).toBeVisible()
})

test('滚到卡片 ⇒ 第二张真挂载（画布或 SVG 落地），占位撤走', async ({ page }) => {
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(c.getByText(PLACEHOLDER)).toHaveCount(0)
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  // 两个地图实例并排共存：主图 + 局部图，且横向不溢出。
  // ⚠️ 两条口径都改过，各留一次现场的账：
  //   ① 原来整页数 `[data-lc-map]` —— 那个属性只贴 live 那棵树，无 AK 的机器上数到 0（10-06 CI 红）。
  //      而我 10-06 试着把它也贴到降级根节点，实测**打红一条常驻判据**（`lcStageStructure:90`）并把
  //      `judgeScaleCanvas:170` 那扇门变成恒真 —— 加宽既有名字的含义就是 §7.2 那条"一词多义"事故。
  //      现由申报式的 `data-lc-mode` 承担"两档都数得到"，`data-lc-map` 保持只认 live。
  //   ② 必须 scope 到体检单那一栏：实测报告页共有**三张**局部图槽（方位形状那屏也挂 `h-[360px]`，
  //      但它不在任何 `<section aria-label>` 内），"整页 == 2"会随它何时 boot 而漂。
  //   `boot` 排除在外：还没落定的那张不算"在场的实例"。
  await expect(page.locator('section[aria-label="体检单"] [data-lc-mode]:not([data-lc-mode="boot"])')).toHaveCount(2)
  // ⚠️ 这里原本有一条"降级态才去数 `[data-lc-blindspot]`"的条件断言，10-07 撤掉，两次现场：
  //   ① 同一条用例、同一个下午，一次落 fallback（那条 skip）、一次落 live（那条真跑）——
  //      走哪档只取决于那一刻后端答不答 `/api/life-circle/map-config`，而本文件的立足点是
  //      "fixture 态、不依赖后端"（见文件头）⇒ 判据不该跟着一张会翻的脸走。
  //   ② 更狠的一次：desktop 那一档里主图申报 `live`、局部图申报 **`fallback`**（同一页两个实例
  //      不同档），于是条件分支被走到，而那张降级画布当场数到 **0** 枚盲区钩子。0 的成因我没查出来
  //      （用"拦 map-config"与"拦 BMapGL 脚本"两条路各复现一次，`:3400` 上钩子都是 1
  //      ⇒ 不是产品对库内件少画了一层，是这条断言在这个环境里不可复算）。
  // ⇒ 只断"必须落定"这件**与模式无关**的事实；`data-lc-blindspot` 的消费者移到 jsdom
  //   （`lcMapModeDeclaration.test.tsx` 里那条计数＋两处盲区的正对照），那边 fallback 是确定的。
  await expect.poll(async () => await lcMode(slot(c)) !== 'boot',
    '局部图迟迟没落定成 live 或 fallback').toBe(true)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, '两栏 grid 撑出横向滚动条 ⇒ 局部图挤掉了主栏').toBeLessThanOrEqual(2)
  // 卡片不许被 grid 的默认 stretch 拉高：台账卡实测 629px，不 `self-start` 就会在
  // 图注下面多出一截空白边框（这一条只有真排版引擎测得出来，jsdom 里全是 0×0）。
  const slack = await c.evaluate((el) => {
    const slotEl = el.querySelector('[class*="h-[360px]"]')!
    const capEl = el.lastElementChild!
    return Math.round(el.getBoundingClientRect().height
      - (slotEl.getBoundingClientRect().height + capEl.getBoundingClientRect().height))
  })
  expect(slack, '局部图卡被拉伸 ⇒ 图注下方出现空白边框').toBeLessThanOrEqual(2)
})

test('幽灵栏与左右：栏数由在场的卡派生，地图在左且与上行同缝', async ({ page }) => {
  // 图二那个缺陷的**几何**判据。为什么不放 jsdom：那里 `getBoundingClientRect` 恒 0×0，
  // 只能断 class 字符串——断实现细节会放走"另一个 class 造出同样空栏"，也会冤枉
  // "改用 auto-fit 得到同样正确几何"。空栏是几何事实，只能量。
  // 为什么用 page.route 造数据：这两种现场三份内置样区都给不出（ev2 台账与盲区同时有、
  // 另两份同时没有），而样区注册表 `SAMPLE_COMMUNITIES` 在 `livingCircleMock.ts`
  // ——那是用户的在制品，不该为一条判据去动它。live 态下 `fetchReport` 走
  // `/api/reports/{id}`（`lib/api.ts:250-254`），正好可拦。
  // 夹具直接读文件（e2e 的 tsconfig 没开 resolveJsonModule）。外壳字段是**体检单那一层**
  // 实际会读的最小集：`toc`/`sections` 留空不影响本判据（台账与两张卡都在体检单 section 里）。
  const fixture = JSON.parse(
    readFileSync(new URL('../src/mocks/fixtures/livingCircle/kaili-ev2.json', import.meta.url), 'utf8'),
  ) as Record<string, unknown> & { generated_at: string }
  const withReport = async (mutate: (r: Record<string, unknown>) => void) => {
    const lc = JSON.parse(JSON.stringify(fixture)) as Record<string, unknown>
    mutate(lc)
    await page.addInitScript(() => localStorage.setItem(LS_DATA_MODE, 'live'))
    await page.route('**/api/reports/**', (route) => route.fulfill({
      json: {
        id: 'lc-e2e-ghost', report_type: 'living_circle', title: '幽灵栏回归', subtitle: '',
        query: '', brands: [], mode: 'standard', created_at: fixture.generated_at,
        experts: [], toc: [], sections: [], charts: [], claims: [], evidence: [],
        glossary: [], methodology: { window: '单次体检', note: '' }, living_circle: lc,
      },
    }))
    await page.goto('/report/lc-e2e-ghost', { waitUntil: 'domcontentloaded' })
    const cap = page.getByText(/^局部视图：/)
    await expect(cap).toBeVisible({ timeout: 15_000 })
    await cap.scrollIntoViewIfNeeded()
    await page.waitForTimeout(3500)
    return await cap.evaluate((el) => {
      const mapCard = el.closest('.flex.flex-col') as HTMLElement
      const row = mapCard.parentElement!
      const kids = [...row.children] as HTMLElement[]
      const topRow = document.querySelector('section[aria-label="体检单"] > div') as HTMLElement
      return {
        rowW: Math.round(row.getBoundingClientRect().width),
        widths: kids.map((k) => Math.round(k.getBoundingClientRect().width)),
        cols: getComputedStyle(row).gridTemplateColumns.split(' ').length,
        // **按身份判左右**，不按数组下标：第一版写成 `widths[0] > widths[1]`，把两张卡对调
        // 之后台账占了 1.6fr 那格（670 > 418 仍成立），用例就这么放走了真正的回归。
        mapIsFirst: kids[0] === mapCard,
        mapW: Math.round(mapCard.getBoundingClientRect().width),
        // 「与上面统一」的可测形式：两行的地图同宽 ⇒ 竖向分栏缝对齐
        topMapW: Math.round(topRow.children[0].getBoundingClientRect().width),
      }
    })
  }

  // ① 有台账 + 0 盲区（上海那份的形状）：两张卡都在场 ⇒ 地图在左、且与上行同缝
  const two = await withReport((r) => { r.blindspots = [] })
  expect(two.widths.length).toBe(2)
  expect(two.cols, '两张卡却不是一个栏位轨道').toBe(2)
  expect(two.mapIsFirst, '地图不在最左 ⇒ 与上面那行的左右又反了').toBe(true)
  expect(two.mapW, '地图与上行地图不同宽 ⇒ 两行分栏缝不齐（"与上面统一"没做到）')
    .toBe(two.topMapW)
  expect(two.widths.find((w) => w !== two.mapW)!, '台账窄到没法看（1fr 实测 418）').toBeGreaterThan(300)

  // ② 有盲区 + 无台账：只剩地图一张卡 ⇒ 必须独占整行，不许留空轨道
  const one = await withReport((r) => {
    const cal = r.caliber as Record<string, unknown>
    delete cal.cells_ledger
  })
  expect(one.widths.length).toBe(1)
  expect(one.cols, '只剩一张卡还摆两栏 ⇒ 就是图二那个幽灵栏').toBe(1)
  expect(one.rowW - one.widths[0], '单卡却没铺满整行 ⇒ 空轨道还在').toBeLessThanOrEqual(2)
})

test('行高政策：选格让台账长出读数表，行高与地图都不许跟着变（第三次复发的正面判据）', async ({ page }) => {
  // 同一类症状在报告页连着出现三次：主图下 248px → 台账右幽灵栏 560px → 配对地图下 219px，
  // 而且**选中一格后台账长出读数表（实测 629→794），留白跟着涨到 384px**。上一版给地图卡写
  // `self-start` 让它贴内容，只是把空白换了个方向。现在政策收进 `stageContract.ts`：
  // 行高锁一个与两栏内容无关的显式值、地图铺满、会变高的台账自己滚。三条分别断。
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await page.waitForTimeout(3500)
  const geo = async () => await c.evaluate((el) => {
    // `c` 已经是地图卡（`card()` 取的就是图注的父层）⇒ 行是它的 parent，别再往上走一层
    const card = el
    const row = el.parentElement!
    const slot = card.querySelector('[class*="h-[360px]"]') as HTMLElement
    const cap = card.lastElementChild as HTMLElement
    return {
      rowH: Math.round(row.getBoundingClientRect().height),
      cardH: Math.round(card.getBoundingClientRect().height),
      // 图注顶 − 地图槽底：有正数缝隙就是地图没铺满
      gap: Math.round(cap.getBoundingClientRect().top - slot.getBoundingClientRect().bottom),
    }
  })
  const before = await geo()
  expect(before.rowH, '行高不是锁死的 640 ⇒ 又交给内容决定了').toBe(640)
  expect(before.cardH).toBe(640)
  expect(Math.abs(before.gap), '地图与图注之间有空白 ⇒ 槽没铺满卡').toBeLessThanOrEqual(2)

  await page.locator('rect[data-cell][fill-opacity="0.34"]').first().click()
  await page.waitForTimeout(1200)
  const after = await geo()
  expect(after.rowH, '选一格就把行撑高 ⇒ 政策又被内容反向决定，地图下面重新开始留白').toBe(before.rowH)
  expect(after.cardH).toBe(640)
  expect(Math.abs(after.gap), '选格后地图与图注之间又裂开 ⇒ 这次修的只是表象').toBeLessThanOrEqual(2)
  // 行锁死之后**唯一的新风险**：台账长出读数表却被 640 裁掉、滚也滚不到。
  // 这条不是装饰：前两版我都断错过 —— 先断"选格前就该可滚"（ev2 选格前装得进 640，直接红），
  // 再断"选格后必然顶出 640"（1280×720 那档字体度量下读数表仍装得进，又红）。
  // 真正的不变量与视口无关：**内容必须可达** —— 装得下就算对，装不下就得滚得到。
  const reachable = await c.evaluate(() => {
    const row = document.querySelector('rect[data-cell]')!.closest('div.grid')!
    const doc = [...row.children].find((k) => k.querySelector('table')) as HTMLElement
    const scrolls = doc.scrollHeight > doc.clientHeight
    doc.scrollTop = doc.scrollHeight          // 不可滚时是 no-op
    const ps = doc.querySelectorAll('p')
    const note = ps[ps.length - 1].getBoundingClientRect()
    const box = doc.getBoundingClientRect()
    return { scrolls, ok: note.bottom <= box.bottom + 2 }
  })
  expect(reachable.ok, '读数表被 640 的行高裁掉又滚不到 ⇒ 政策把内容吞了').toBe(true)
})

test('主图铺满整行：宽屏跟着右栏长高并撞上下限，窄屏退回显式 480px 而不是塌成 0', async ({ page }) => {
  // 图一那个缺陷的正面判据。三半都要测：
  //  ① lg 起地图槽改成 `lg:absolute lg:inset-0`，高度由体检单那一栏撑出来（实测 726）；
  //  ② 窄屏（单列）时 `h-full` 会塌成 0（BMapGL 读父容器 px，见组件里那条 ⚠️），
  //     所以必须退回显式 `h-[480px]`。只测 ① 的话，有人把 480 删干净也照样全绿。
  //  ③ `lg:min-h-[640px]` 这条下限**必须真的在生效**（自审不过点 4：不写永不生效的保险）。
  //     ev2 的右栏实测只有 611 ⇒ 卡高应被下限抬到 640，这条断言就是它的现场。
  await openReport(page)
  const live = (await lcMode(page.locator('section[aria-label="体检单"]'))) === 'live'
  const geo = async () => await page.evaluate(() => {
    const row = document.querySelector('section[aria-label="体检单"] > div')!
    const card = row.children[0]
    const slot = card.querySelector('[class*="h-[480px]"]')!
    const cv = card.querySelector('canvas')
    const sv = card.querySelector('svg')
    return {
      card: Math.round(card.getBoundingClientRect().height),
      slot: Math.round(slot.getBoundingClientRect().height),
      // canvas 的高度有两种写法（style.height 或属性），svg 只有排版盒 —— 都折算成"实际占了几 px"
      surfaceH: Math.round(cv ? (parseFloat(cv.style.height) || cv.height) : sv ? sv.getBoundingClientRect().height : 0),
    }
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.waitForTimeout(4000)
  const wide = await geo()
  expect(wide.slot, '地图没铺满整行 ⇒ 卡底下又是空白').toBeGreaterThanOrEqual(wide.card - 4)
  expect(wide.slot, '铺满后应明显高于旧的固定 480').toBeGreaterThan(560)
  // 「画布跟着容器长高」是 **live 独有**的性质：降级画布是 `w-full` + viewBox 860×620，
  // 高度被宽高比锁住，槽再高它也只按比例长（所以宽屏下槽 726 而 svg 约 578，下面留一截白）。
  // 这是两档的真实差异、不是这条判据要放过它 —— 但把它写成"两档都必须 >560"会把产品缺陷
  // 和判据写错混成一次红（第一版就这么红了），所以分开断、各自说清自己在验什么。
  if (live) {
    expect(wide.surfaceH, 'BMapGL 没跟着容器重画 ⇒ canvas 仍是 480').toBeGreaterThan(560)
  } else {
    expect(wide.surfaceH, '降级画布压根没落地 ⇒ svg 高度为 0').toBeGreaterThan(0)
  }
  // ev2 右栏实测 611 < 640 ⇒ 这里必须被下限抬起来；哪天右栏长过 640，这条会红，
  // 那时该改的是"下限是否仍然需要"，而不是把断言删掉。
  expect(wide.card, 'lg:min-h-[640px] 没生效（下限形同虚设）').toBeGreaterThanOrEqual(638)
  await page.setViewportSize({ width: 900, height: 1000 })
  await page.waitForTimeout(4000)
  const narrow = await geo()
  expect(narrow.slot, '单列时塌高 ⇒ 地图消失').toBeGreaterThanOrEqual(478)
  expect(narrow.surfaceH, live ? '单列时 canvas 没拿到显式 px' : '单列时降级画布没拿到显式 px').toBeGreaterThanOrEqual(478)
})

test('进过一次视口就常驻：滚走再滚回不该重看一次骨架', async ({ page }) => {
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  await scrollToTop(c)
  await page.waitForTimeout(500)
  await c.scrollIntoViewIfNeeded()
  await expect(c.getByText(PLACEHOLDER)).toHaveCount(0)
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
})

test('反向通道：点局部图 → 台账卡选中那一格', async ({ page }) => {
  // 台账卡 → 图 那一向由 jsdom 测（改 state 就重渲染）；**图 → 台账**要靠真指针：
  // LcMap 走的是地图 click 事件（`onCellPick`），jsdom 里既没有 BMapGL 也没有命中测试。
  // `lifeCircleStage.spec.ts` 记过"合成分派打不动 SDK"，但那是给 overlay 派发合成事件；
  // 这里用 CDP 的真实鼠标事件点画布空白处，2026-10-04 实测能选中格子。
  // 只断"选中了某一格"不断是哪一格：落点由视口尺寸与缩放决定，钉死坐标会漂。
  const c = await openReport(page)
  await c.scrollIntoViewIfNeeded()
  await expect(slot(c).locator('canvas, svg')).not.toHaveCount(0)
  // 10-07 R2 之后**两档都跑**（降级画布的点图分诊与 live 共用同一颗 `cellAt`，见 `LcMap` 的
  // `onCanvasClick`）⇒ 这条不再有 skip，也补上了当时那句老实话的反面：以前它只在"本机有 AK"那档
  // 生效，CI 恒不执行。历史两条教训留着，别改回去：
  //   ① 上一版这里点 `42%×55%` 在 CI 红过，我当场误读成"同一个比例在两档落到不同的格"——
  //      实测否证：那时降级档**换任何落点都是 0**，因为通道压根没实现（不是落点的锅）。
  //   ② 中途改点槽正中，live **实测 0 中** —— 正中是中心 Marker 的命中区（与本仓早先"环吃掉鼠标
  //      事件"那颗误判同源：别让几何中心替你担保）。
  // 现在落点分档各挑"确定在格阵里"的那一处：
  //   fallback ⇒ 指盲区图形自己的中心（`[data-lc-blindspot]`：判盲的前提就是它在判定域内）
  //   live     ⇒ `42% × 55%`（实测命中的三个偏中心点之一）
  const selected = page.locator('rect[data-cell]:not([stroke="#E3E8E3"])')
  // ⚠️ 图上那一枚（`data-lc-layer="selected-cell"`）故意**不叫** `data-cell` —— 那是台账示意网格的名字；
  //    撞名就会让下面这条"选中数 0"的前置断言把图上的也算进去，判据自己把自己验红（§7.2 同族事故）。
  await expect(selected).toHaveCount(0)
  await slot(c).scrollIntoViewIfNeeded()
  if (await lcMode(slot(c)) === 'fallback') {
    await slot(c).locator('[data-lc-blindspot]').first().click()
  } else {
    const bb = (await slot(c).boundingBox())!
    await slot(c).click({ position: { x: bb.width * 0.42, y: bb.height * 0.55 } })
  }
  await expect(selected).not.toHaveCount(0)
  // 图上必须出现这一格本身 —— 但**只有降级档能在 DOM 里问**：live 那侧那对方框是 BMapGL 的
  // canvas 覆盖物，压根不进 DOM。10-07 我先把这条写成整页断言，结果 fallback 全绿、live 两档
  // **各红一次**（`Received: 0`）—— 判据的前提只在其中一个环境成立，正是这条 spec 一直在避的坑。
  // live 那半的"画出来了"由 jsdom 验：`lcCellLayer.test.tsx` 的 live describe 读替身记账
  // （`instances.polys` 里那枚方框），顶点还逐位对着同一份 plan。
  // ⚠️ 顺带给 R1 留一条硬约束：「两档图层集合相等」的 live 半边**不能**问 DOM，必须让组件把
  //    overlay 名册申报出来（同 `data-lc-mode` 那条思路：由生产者发话）。
  if (await lcMode(slot(c)) === 'fallback') {
    await expect(page.locator('[data-lc-layer="selected-cell"]')).toHaveCount(1)
  }
})
