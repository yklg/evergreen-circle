import { expect, test } from '@playwright/test'
import { assertStageGeometry, legend, openStage } from './stageChecks'

/**
 * 2.10 的结案件：把"CI 换 Linux 后字体度量变了会不会打碎阈值"从**推断**变成**实测**。
 *
 * ## 思路
 *
 * 判据的数值是在 macOS Chromium 上量的，runner 上是 Linux Chromium：CJK 兜底字体不同、
 * 而且我们把 webfont 设成了 `display=optional` ⇒ 装了 `fonts-noto-cjk` 没有、字体目录如何，
 * 都可能在 CI 上换成另一套度量。本机起不了 Linux 浏览器（docker daemon 未启），
 * 所以不去猜"差多少"，而是**主动把度量往恶劣方向压**，看同一份判据扛不扛得住。六档：
 *
 *  ② 拦掉全部 webfont —— 页面只用系统兜底 CJK 字排版，正是 runner 上最可能的情形；
 *  ⑤⑥ **字宽 +5% / +8%** —— 这才是字体替换的合格代理，实测出来的理由：本仓字号 token 是
 *    **px 定值**（`fontSize.tag = ['11px', {lineHeight:'1.4'}]` ⇒ 行高恒 15.4px 与字体无关），
 *    换 CJK 字体不动行高，只动**字面宽度 ⇒ 某行标签是否折行**，一折就是 +15.4px；
 *  ③④ 根字号 1.25×（± 拦 webfont）—— 放大的是 rem **间距**（p-3 / gap-1.5 / mt-1 那一层）。
 *    ⚠ 第一版把它当"字体代理"是**错的**，已在下面 MODES 处更正；它现在钉的是另一条真实暴露面：
 *    用户浏览器缩放与紧凑间距 —— 这一档在 720 档把图例顶出 main 下沿 43.2px（见 fixme）。
 *
 * 结论（数字由 STRESS 日志现打）：地图格与右栏两条余量极大（≥34.4pt / 598–874px），六档全绿
 * ⇒ 换 OS 换不动它们；**唯一脆的是图例浮层** —— 它没有高度上限，720 档基线余量 20.2px，
 * 字宽 +5% 就只剩 4.8px。⇒ 2.10 从"推断不会碎"变成"知道会红在哪一条、为什么红"；
 * 修复候选见台账 2.11 与 `skip/preview-lc-legend-fit.html`。任一档红了都按**真缺陷**处理：
 * 改的是判据写法（换成对同源量的相对关系），不是放松阈值。
 */

interface Mode {
  tag: string
  blockWebfont?: boolean
  rootFontSize?: string
  letterSpacing?: string
}

const MODES: Mode[] = [
  { tag: '① 基线（webfont 尽力加载 + 本机字体）' },
  { tag: '② 拦掉全部 webfont（≈ runner 只剩系统兜底字）', blockWebfont: true },
  { tag: '③ 根字号 1.25×（rem 间距整体变大）', rootFontSize: '20px' },
  { tag: '④ ②+③ 叠加（最坏面）', blockWebfont: true, rootFontSize: '20px' },
  // ③ 放大的只是 rem 间距 —— 本仓字号 token 是 px 定值（`text-tag: 11px`，lineHeight 1.4 倍的是
  // 解析后的 px），所以"换一种 CJK 字面"的真正后果不在行高，而在**同一行文字变宽 ⇒ 标签换行**。
  // ⑤⑥ 用 letter-spacing 直接顶这个面：+5% 与 +8% 字宽，看第几行开始折。
  { tag: '⑤ 字宽 +5%（字体替换的直接代理）', letterSpacing: '0.05em' },
  { tag: '⑥ 字宽 +8%（更狠一档）', letterSpacing: '0.08em' },
]

for (const mode of MODES) {
  test(`字体度量压力 · ${mode.tag}`, async ({ page }) => {
    /**
     * 台账 2.11（已按方案 A 修上）：图例原先 `absolute left-3 top-3` + **内容自然高**，
     * 720 档基线下地图格 572px、图例 539.8px ⇒ 余量只有 20.2px（≈1.3 行 `text-tag`）；
     * 字宽 +5% 折出一行 ⇒ 剩 4.8px；rem 间距 1.25× ⇒ 图例 592.2px，`171.0+592.2=763.2`
     * vs main 下沿 720 ⇒ **溢出 43.2px**（当时那两档是显式 `test.fixme`）。
     * 现在 `LC_LEGEND` 带 `lg:max-h-[calc(100%-1.5rem)] + overflow-y-auto`、判读块 `sticky bottom-0`
     * ⇒ 高度挂在同源容器上，六档全绿。**这几档就是那条修复的验收**：摘掉 max-h 立刻会红。
     */
    if (mode.blockWebfont) {
      // CSS 与字体文件都要拦：只拦 css2 的话 @font-face 已经拿不到，但 gstatic 一并拦更干净
      await page.route('**/fonts.googleapis.com/**', (r) => r.abort())
      await page.route('**/fonts.gstatic.com/**', (r) => r.abort())
    }
    await openStage(page)

    if (mode.rootFontSize) {
      await page.evaluate((px) => { document.documentElement.style.fontSize = px }, mode.rootFontSize)
      await page.waitForTimeout(400)     // 等 re-flow 落定再量，别把过渡中的一帧当结论
    }
    if (mode.letterSpacing) {
      await page.evaluate((ls) => { document.documentElement.style.letterSpacing = ls }, mode.letterSpacing)
      await page.waitForTimeout(400)
    }

    /**
     * 拦住没有拦住，要**量出来**而不是假定。
     * 第一版这里写的是 `document.fonts.check('16px "Noto Sans SC"')`，结果与意图正好相反：
     * 拦住时 CSS 没了 ⇒ 没有 `@font-face` ⇒ check() 转而问"系统里有没有这族"，macOS 装了
     * Noto Sans SC ⇒ 返回 **true**；基线档 CSS 在、face 声明了但 `optional` 下还没加载 ⇒ **false**。
     * 改用 `document.fonts.size`（= 页面里 `@font-face` 的条数），它量的正是我要控制的那个开关。
     */
    const fontFaces = await page.evaluate(() => document.fonts.size)
    // 拦住了没有 —— 只有这一侧可以硬断言（route abort 与网络无关）。
    // 反过来 **不许**断言"基线档 CSS 一定到得了"：这条判据会把 CDN 连通性当功能回归。
    // 实测教训：本机某段时间连不上 fonts.googleapis.com，`fontFaces` 归 0、goto 卡满 10s，
    // 5 条压力档全红在正对照上 —— 红的是网络，不是布局。CI 上这本来就是不确定的（runner 未必出网）。
    // 所以基线档只**记录**：fontFaces=0 时这一档自动等价于 ②，日志里看得见，不假装量到了 webfont。
    if (mode.blockWebfont) expect(fontFaces, 'webfont 没被拦住 ⇒ 这档等于基线，白测').toBe(0)

    const g = await assertStageGeometry(page)
    const mapRatio = g.mapCell / g.viewportHeight
    const asideOverflow = g.asideScroll - g.asideClient
    // 有几行标签折成两行了 —— 这才是"换字体"真正会动的那个量（行高是 px 定值，不会动）
    const wrappedRows = await legend(page).evaluate((el) =>
      [...el.querySelectorAll(':scope > *')].filter((c) => (c as HTMLElement).getBoundingClientRect().height > 26).length,
    )

    // 数字进台账：与阈值对比的余量才是这条的真正产出。
    // 注意这里**不加**比主判据更严的新阈值 —— 压力档的作用是证明同一份判据扛得住换度量，
    // 不是另立一个只在压力档才成立的门槛；那种门槛红过一次就会被人当噪音放松掉。
    console.info(
      `STRESS|${mode.tag}|viewport=${g.viewportHeight}|main=${g.mainClient}/${g.mainScroll}` +
        `|aside=${g.asideClient}/${g.asideScroll}(超出 ${asideOverflow}px)` +
        `|cell=${g.mapCell}px(= 视口 ${(mapRatio * 100).toFixed(1)}%，判据下限 45% ⇒ 余量 ${(mapRatio * 100 - 45).toFixed(1)}pt)` +
        `|legend=${g.legendHeight}px(可视 ${g.legendClient}/内容 ${g.legendScroll}${g.legendScroll > g.legendClient + 1 ? ' ⇒ max-h 在挡' : ''})` +
        `|折行标签=${wrappedRows} 行|fontFaces=${fontFaces}${fontFaces ? '' : '（CSS 没到 ⇒ 本档等价②）'}`,
    )
  })
}
