// @vitest-environment jsdom
/**
 * 对照态降级画布的取景（`lcCoFrame`）· 出框修复的常驻判据。
 *
 * ## 它治的病
 * 降级静态画布原本恒用 `viewBox="0 0 860 620"`，而投影原点＝A 侧 `scene.center`、世界半径
 * ＝`LC_CANVAS.R` 2500 m ⇒ 两份件中心距一大，另一侧就**画到框外被切**。2026-10-10 真跑两发
 * 之前这条撞不见：库里选择器可见的四份两两最近 14,014 m，全走"两张图各居其城"那一支。
 * 实测那一对（相距 2486 m）B 侧格阵落在 x `722..1024`，右边缘出框 164 px（图证见
 * `预览-对照态两侧同框-2026-10-10/L0-同框/`）。
 *
 * ## 三条不变式，各一条判据
 *  ① **含得下**：画出来的每个点都在 viewBox 内 —— 问 DOM 上的 `points`/`cx`，不问 `lcCoFrame`
 *     自己（问函数等于让它自证）。
 *  ② **不许顺手改布局**：宽高比恒等于画布比例 ⇒ svg 自身高度与那个定高槽都不跟着变；
 *     且框**必含整幅画布**（只外扩，不缩小、不平移）。
 *  ③ **不无谓放大**：两侧内容没超出今天的取景时（同中心那一对就是），viewBox 必须**逐字**
 *     还是 `0.0 0.0 860.0 620.0` —— 修复不许把没病的画面一起改了。
 *
 * ## 数据为什么一半是合成的
 * 常驻夹具 `realCoFrameTrio.json` 是**裁剪过**的（删了 `isochrones[].geojson` 等大数组，见该文件头），
 * 而"画出来的点"必须有几何 ⇒ 用出厂件 `kaili-ev2` 现造一份东移 0.025°（≈2.49 km）的副本当 B 侧。
 * 真件对只用来问纯函数那两条（同中心 ⇒ 逐字不放大；不同几何 ⇒ 各外扩）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import ev2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import trio from './helpers/realCoFrameTrio.json'
import { LC_CANVAS, lcCoFrame, lcFrameViewBox, lcToPx } from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'
import { mapConfig, resetInstances } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')
const BASE = ev2 as unknown as LivingCircleReport
const TRIO = { a: trio.a, b: trio.b, c: trio.c } as unknown as Record<'a' | 'b' | 'c', LivingCircleReport>
const ON = { draggableCenter: false, onMapMode: () => {}, showIsoCompare: true, showShapeSectors: true, showCellsGrid: true }

/** 把一份载荷整体东移 `dLng` 度（要的就是"两侧离得远"这一件事，其余一字不动）。 */
function shiftedEast(lc: LivingCircleReport, dLng: number): LivingCircleReport {
  const ring = <T extends { coordinates: [number, number][][] }>(g: T): T => ({
    ...g, coordinates: g.coordinates.map((r) => r.map(([x, y]) => [x + dLng, y] as [number, number])),
  })
  return {
    ...lc,
    scene: { ...lc.scene, center: [lc.scene.center[0] + dLng, lc.scene.center[1]] },
    isochrones: lc.isochrones.map((z) => ({ ...z, geojson: z.geojson ? ring(z.geojson) : z.geojson })),
    iso_compare: lc.iso_compare
      ? { ...lc.iso_compare, geojson: lc.iso_compare.geojson ? ring(lc.iso_compare.geojson) : lc.iso_compare.geojson }
      : lc.iso_compare,
    blindspots: lc.blindspots.map((bl) => ({
      ...bl,
      center: [bl.center[0] + dLng, bl.center[1]] as [number, number],
      polygon: bl.polygon ? ring(bl.polygon) : bl.polygon,
    })),
    poi: { ...lc.poi, points: lc.poi.points.map((p: { lnglat: [number, number] }) => ({ ...p, lnglat: [p.lnglat[0] + dLng, p.lnglat[1]] })) },
    caliber: { ...lc.caliber!, cells_ledger: { ...lc.caliber!.cells_ledger!, center: [lc.caliber!.cells_ledger!.center[0] + dLng, lc.caliber!.cells_ledger!.center[1]] } },
  } as unknown as LivingCircleReport
}
const FAR = shiftedEast(BASE, 0.025)

const svgOf = (container: HTMLElement) => container.querySelector('svg[aria-label*="画布"]')!
const viewBoxOf = (container: HTMLElement) =>
  (svgOf(container).getAttribute('viewBox')!).split(/\s+/).map(Number) as unknown as [number, number, number, number]
/** 画布上真画出来的那些点：多边形顶点 + 圆心。jsdom 无排版引擎，但**几何属性字符串**读得到。 */
function drawnPoints(container: HTMLElement): Array<[number, number]> {
  const out: Array<[number, number]> = []
  for (const p of Array.from(svgOf(container).querySelectorAll('polygon'))) {
    for (const pair of (p.getAttribute('points') ?? '').trim().split(/\s+/)) {
      const [x, y] = pair.split(',').map(Number)
      if (Number.isFinite(x) && Number.isFinite(y)) out.push([x, y])
    }
  }
  for (const c of Array.from(svgOf(container).querySelectorAll('circle'))) {
    const x = Number(c.getAttribute('cx')); const y = Number(c.getAttribute('cy'))
    if (Number.isFinite(x) && Number.isFinite(y)) out.push([x, y])
  }
  return out
}
async function mountCo(a: LivingCircleReport, b: LivingCircleReport) {
  mapConfig.browserAk = ''   // 无 AK ⇒ 降级静态画布，图元进 DOM 才问得到
  const view = render(<LcMap report={a} compareReport={b} {...(ON as object)} />)
  await waitFor(() => expect(svgOf(view.container)).toBeTruthy())
  return view
}

beforeEach(() => { resetInstances(); mapConfig.browserAk = 'test-ak' })
afterEach(() => { cleanup(); mapConfig.browserAk = 'test-ak' })

describe('lcCoFrame · 不变式（纯函数侧）', () => {
  it('② 保画布宽高比，且**必含整幅画布**（只外扩，不缩小、不平移到画布外）', () => {
    for (const [a, b] of [[BASE, FAR], [TRIO.a, TRIO.b], [TRIO.b, TRIO.c]] as const) {
      const f = lcCoFrame(a, b, a.scene.center)
      expect(f.w / f.h, '比例漂了 ⇒ 定高槽会跟着改高度').toBeCloseTo(LC_CANVAS.W / LC_CANVAS.H, 6)
      expect(f.x, '框顶到画布左边之外（只许外扩，不许整体平移）').toBeLessThanOrEqual(0)
      expect(f.y).toBeLessThanOrEqual(0)
      expect(f.x + f.w).toBeGreaterThanOrEqual(LC_CANVAS.W)
      expect(f.y + f.h).toBeGreaterThanOrEqual(LC_CANVAS.H)
    }
  })
  it('③ 同中心那一对（真件 a×b）逐字退回今天的取景 ⇒ 修复不许动没病的画面', () => {
    expect(lcCoFrame(TRIO.a, TRIO.b, TRIO.a.scene.center)).toEqual({ x: 0, y: 0, w: LC_CANVAS.W, h: LC_CANVAS.H })
  })
  it('① 东移副本：两侧画得出来的点全在框内，而**旧取景下确实有点出框**（把"修了什么"也钉住）', () => {
    const origin = BASE.scene.center
    const f = lcCoFrame(BASE, FAR, origin)
    const pts = [BASE, FAR].flatMap((lc) => [
      ...lc.isochrones.flatMap((z) => z.geojson?.coordinates?.[0] ?? []),
      ...lc.blindspots.flatMap((bl) => [bl.center, ...(bl.polygon?.coordinates?.[0] ?? [])]),
      ...(lc.iso_compare?.geojson?.coordinates?.[0] ?? []),
    ]).map((p) => lcToPx(origin, p[0], p[1]))
    expect(pts.length, '一份几何都没取到 ⇒ 本条在自证').toBeGreaterThan(100)
    expect(pts.filter(([x, y]) => x < f.x || x > f.x + f.w || y < f.y || y > f.y + f.h), '有点在框外').toEqual([])
    const clipped = pts.filter(([x, y]) => x < 0 || x > LC_CANVAS.W || y < 0 || y > LC_CANVAS.H)
    expect(clipped.length, '旧取景下没有点出框 ⇒ 这条修复的前提没了').toBeGreaterThan(0)
  })
})

describe('降级画布真的按并集取景（问 DOM，不问函数）', () => {
  it('相距 2.49 km 那一对：viewBox 外扩，DOM 上每个图元坐标都落在 viewBox 内', async () => {
    const { container } = await mountCo(BASE, FAR)
    const [x, y, w, h] = viewBoxOf(container)
    expect(w, '框没外扩 ⇒ 这一对仍然会被切').toBeGreaterThan(LC_CANVAS.W)
    const pts = drawnPoints(container)
    expect(pts.length, '一个图元都没画出来 ⇒ 本条在自证').toBeGreaterThan(200)
    expect(pts.filter(([px, py]) => px < x || px > x + w || py < y || py > y + h), '有画出来的点在 viewBox 外').toEqual([])
  })
  it('两侧同中心（内容没超出画布）：viewBox 逐字还是今天那句', async () => {
    const { container } = await mountCo(BASE, BASE)
    expect(svgOf(container).getAttribute('viewBox'))
      .toBe(lcFrameViewBox({ x: 0, y: 0, w: LC_CANVAS.W, h: LC_CANVAS.H }))
  })
  it('单图那一支（不给 compareReport）：viewBox 逐字不变', async () => {
    mapConfig.browserAk = ''
    const view = render(<LcMap report={BASE} {...({ draggableCenter: false, onMapMode: () => {}, showIsoCompare: true } as object)} />)
    await waitFor(() => expect(svgOf(view.container)).toBeTruthy())
    expect(svgOf(view.container).getAttribute('viewBox')).toBe('0.0 0.0 860.0 620.0')
  })
})
