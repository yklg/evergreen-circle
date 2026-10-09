// @vitest-environment jsdom
/**
 * 选中格图层 · 两档同源（计划 R2）。
 *
 * ## 为什么这份文件存在
 * 「在地图上点一格 → 台账选中」这条通道，和它对应的**图上呈现**（那枚真实米制下的格框＋该格的
 * 判定尺圆），此前**只有 live 半边**：`LcMap` 是两棵渲染树，几何在两处各写一遍，于是没人能发现
 * 降级那半缺了一层 —— 而报告页的图注两档同印那句「图上带该格的判定尺圆」，在没 AK 的机器上就是
 * 半真话。本域为这类分叉写过三次勘误（判定尺只补 live 一半、口径对照环两档各写一遍、形状扇面）。
 * 收口方式不是"再补一遍"，而是把几何收进 `CellLayer.cellLayerPlan`，两档各只负责把自己的基元画出来。
 *
 * ## 被守护的契约
 *  ① 两档读**同一份** plan：live 的 Polygon 顶点逐位等于 `plan.corners`，降级 `<polygon>` 的
 *     `points` 逐字符等于 `lcPolyPts(center, plan.corners)` —— 谁另写一套换算，这里就红。
 *  ② 降级那侧折算回米必须等于 `plan.radiusM`，且 **x/y 两向分别验**（画布横纵比例不同，
 *     图省事用 SVG 正圆会纵向多约 39%，`livingCircle.ts:263` 那条 P0 记录）。
 *  ③ 点图 → 选格两档都有；落在格阵外 ⇒ 清选中，不回落"最近一格"。
 *  ④ 判定尺开关关着 ⇒ 不把手势解释成选格（没有依据的入口不摆），改中心照旧。
 *  ⑤ `desensitize`（P0-5）两档都整层不画，但**通道照旧通着**。
 *
 * ## 效力上限
 * jsdom 没有排版引擎，`getBoundingClientRect` 恒 0×0 —— 所以点击那两条必须 stub 出画布尺寸，
 * 否则会被 `LcMap:1392` 的除零守卫静默拦掉（那是**对的行为**：拿不到布局就不该折算坐标）。
 * 真机一侧（点哪个像素、Marker 会不会吃掉点击）只有 Playwright 答得了，见
 * `e2e/lcReportLocalMap.spec.ts` 的「反向通道」。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import contract from './fixtures/cellsLedgerContract.json'
import type { CellsLedgerRaw, LivingCircleReport } from '../types'
import {
  LC_CANVAS,
  LC_JUDGE_SCALE_COLOR,
  cellAt,
  cellCenter,
  lcFromMeters,
  lcMeters,
  lcPolyPts,
  lcRing,
  lcToPx,
} from '../lib/livingCircle'
import { LC_LEDGER_FILL, cellLayerPlan, cellsGridPlan } from '../components/lifecircle/CellLayer'
import { instances, mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const LEDGER = contract.sample as unknown as CellsLedgerRaw
const BASE = kaili as unknown as LivingCircleReport
const WITH_LEDGER: LivingCircleReport = {
  ...BASE,
  caliber: { ...BASE.caliber!, cells_ledger: LEDGER },
}
const CELL: [number, number] = [1, 1]

/** 降级画布里的选中格层（`data-lc-layer` 是给 R1「两档图层集合相等」留的抓手）。 */
const cellLayer = (root: Element | Document) => root.querySelectorAll('[data-lc-layer="selected-cell"] polygon')

/** jsdom 没有布局：不 stub 就会被 `:1392` 的除零守卫拦掉，测的就是"没测"。 */
function stubCanvasRect(svg: Element, w = LC_CANVAS.W, h = LC_CANVAS.H): void {
  svg.getBoundingClientRect = () => ({
    x: 0, y: 0, left: 0, top: 0, right: w, bottom: h, width: w, height: h,
    toJSON: () => ({}),
  } as DOMRect)
}

async function mountFallback(report: LivingCircleReport, props: Record<string, unknown> = {}) {
  mapConfig.browserAk = ''
  // 用 createElement 而不是 JSX 展开：`props` 是这文件自造的杂项袋（onCellPick/onCenterChange…），
  // JSX 展开会要求它先过 `LcMapProps` 的类型，而这里要验的正是"这些回调确实被组件接住了"。
  const view = render(createElement(LcMap, { report, ...props }))
  await waitFor(() => expect(view.container.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
  return view
}

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  mapConfig.browserAk = 'test-ak'
  mapConfig.mapStyleId = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('夹具前提（锚值必须来自独立事实，不是被测代码自证）', () => {
  it('这份件有台账，`cellLayerPlan` 取得出格框四角与半径（漂了本套就白测）', () => {
    const plan = cellLayerPlan(WITH_LEDGER, CELL)
    expect(plan, '取不到 plan ⇒ 两档都会"整层不画"，下面的断言就成了摆设').toBeTruthy()
    expect(plan!.corners).toHaveLength(4)
    expect(plan!.radiusM).toBe(LEDGER.radius_m)
    // 格心由 `cellCenter` 给，plan 不许自带第二套换算：圆心必须与格心逐位相同
    expect(plan!.center).toEqual(cellCenter(LEDGER, CELL[0], CELL[1]))
    // 越界与 null 都 ⇒ null（缺席即不渲染，不是画个 0 半径圈）
    expect(cellLayerPlan(WITH_LEDGER, [LEDGER.n, 0])).toBeNull()
    expect(cellLayerPlan(WITH_LEDGER, null)).toBeNull()
    expect(cellLayerPlan(BASE, CELL), 'BASE 没有台账 ⇒ 不许画').toBeNull()
    // 方框必须是"以格心为中心、边长 = step_m"的正方形。这一条是**独立锚**：它不读 plan 的实现，
    // 而是拿 `lcMeters` 把四个角反算回米再比半个格距 —— 行列转置、把 step_m 抄成 radius_m、
    // 只写对角这三种错法都会在这条红，而"两档都读同一份 plan"那两条抓不住（错在 plan 内部时
    // 两档会一起错、照样逐位相同）。
    for (const [dx, dy] of plan!.corners.map((p) => lcMeters(plan!.center, p[0], p[1]))) {
      expect(Math.abs(Math.abs(dx) - LEDGER.step_m / 2), `角点横向偏移 ${dx.toFixed(1)}m ≠ 半格距`).toBeLessThan(1)
      expect(Math.abs(Math.abs(dy) - LEDGER.step_m / 2), `角点纵向偏移 ${dy.toFixed(1)}m ≠ 半格距`).toBeLessThan(1)
    }
    // 转置单独验一遍，而且必须用**非对角**的格：`[1,1]` 转置后还是自己，上面三条一起都抓不住
    // "行拿去比经度、列拿去比纬度"这类经典错法（`lcMapCellClick` 给点选通道补过同一条，这里给图层补）。
    const ASYM: [number, number] = [2, 1]
    const p2 = cellLayerPlan(WITH_LEDGER, ASYM)!
    expect(p2.center, '格心算反 ⇒ 卡片说这格、图上画那格').toEqual(cellCenter(LEDGER, 2, 1))
    expect(p2.center, '行/列转置后仍在同一处？换非对角格才测得到').not.toEqual(cellCenter(LEDGER, 1, 2))
  })
})

describe('选中格图层 · live 档', () => {
  it('Polygon 顶点逐位等于 plan.corners，且只描边/不吃点击', async () => {
    render(<LcMap report={WITH_LEDGER} selectedCell={CELL} />)
    await waitFor(() => expect(cellLayerBoxPoly()).toBeTruthy())
    const plan = cellLayerPlan(WITH_LEDGER, CELL)!
    const pts = (cellLayerBoxPoly().point as unknown as Array<{ lng: number; lat: number }>)
      .map((p) => [p.lng, p.lat])
    expect(pts, 'live 自己另写一套格角换算 ⇒ 两档从此分叉').toEqual(plan.corners)
    expect(cellLayerBoxPoly().opts.fillOpacity).toBe(0.08)
    expect(cellLayerBoxPoly().opts.enableClicking, '方框接管点击 ⇒ 圈内采样点 tooltip 被清').toBe(false)
  })
})

describe('选中格图层 · 降级档', () => {
  it('同一份 plan：points 逐字符等于 lcPolyPts(center, plan.corners)，另有判定圆一共两枚', async () => {
    const { container } = await mountFallback(WITH_LEDGER, { selectedCell: CELL })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    expect(cellLayer(svg), '方框＋判定圆，少一枚就是只补了一半').toHaveLength(2)
    const plan = cellLayerPlan(WITH_LEDGER, CELL)!
    const center = WITH_LEDGER.scene.center
    expect(cellLayer(svg)[0].getAttribute('points')).toBe(lcPolyPts(center, plan.corners))
    expect(cellLayer(svg)[1].getAttribute('points')).toBe(lcPolyPts(center, lcRing(plan.center, plan.radiusM)))
    expect(cellLayer(svg)[1].getAttribute('fill'), '判定圆必须只描边（填充会压掉五级色阶）').toBe('none')
  })

  it('折算回米：x/y **两向**都等于 plan.radiusM（画布横纵比例不同，用 SVG 正圆会纵向多约 39%）', async () => {
    const { container } = await mountFallback(WITH_LEDGER, { selectedCell: CELL })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    const plan = cellLayerPlan(WITH_LEDGER, CELL)!
    const [cx, cy] = lcToPx(WITH_LEDGER.scene.center, plan.center[0], plan.center[1])
    const pts = (cellLayer(svg)[1].getAttribute('points') ?? '').trim().split(/\s+/)
      .map((p) => p.split(',').map(Number))
    expect(pts.length).toBeGreaterThan(0)
    const rx = ((Math.max(...pts.map((p) => p[0])) - cx) / (LC_CANVAS.W / 2)) * LC_CANVAS.R
    const ry = ((cy - Math.min(...pts.map((p) => p[1]))) / (LC_CANVAS.H / 2)) * LC_CANVAS.R
    expect(Math.round(rx), '横向折算不等于声明的尺').toBe(Math.round(plan.radiusM))
    expect(Math.round(ry), '纵向折算不等于声明的尺（SVG 正圆的典型错法）').toBe(Math.round(plan.radiusM))
  })

  it('脱敏态（P0-5）：这一层整层不画 —— 与 live 半边同一颗 predicate，不是再补一道闸', async () => {
    const { container } = await mountFallback(WITH_LEDGER, { selectedCell: CELL, desensitize: true })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    expect(cellLayer(svg)).toHaveLength(0)
  })
})

describe('点图 → 选格 · 降级档通道（与 live 同一颗 cellAt）', () => {
  it('点 (i,j) 的格心 ⇒ onCellPick 收到 (i,j)，且**不许**顺手挪中心', async () => {
    const onCellPick = vi.fn()
    const onCenterChange = vi.fn()
    const { container } = await mountFallback(WITH_LEDGER, {
      showJudgeScale: true, onCellPick, onCenterChange,
    })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    stubCanvasRect(svg)
    const [lng, lat] = cellCenter(LEDGER, CELL[0], CELL[1])
    const [px, py] = lcToPx(WITH_LEDGER.scene.center, lng, lat)
    fireEvent.click(svg, { clientX: px, clientY: py })
    expect(onCellPick).toHaveBeenCalledWith(CELL)
    expect(onCenterChange, '点一格看台账却把中心挪走 ⇒ 整份重算，两个手势在打架').not.toHaveBeenCalled()
  })

  it('落在格阵外 ⇒ 清选中（null），且照旧改中心（不许回落"最近一格"）', async () => {
    const onCellPick = vi.fn()
    const onCenterChange = vi.fn()
    const { container } = await mountFallback(WITH_LEDGER, {
      showJudgeScale: true, onCellPick, onCenterChange, selectedCell: CELL,
    })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    stubCanvasRect(svg)
    // 前提守卫：这个角落点在地理上**确实**落在格阵外 —— 否则这条测的不是"外面"，只是又一次点击。
    const cornerGeo = lcFromMeters(
      WITH_LEDGER.scene.center,
      ((4 - LC_CANVAS.W / 2) / (LC_CANVAS.W / 2)) * LC_CANVAS.R,
      ((LC_CANVAS.H / 2 - 4) / (LC_CANVAS.H / 2)) * LC_CANVAS.R,
    )
    expect(cellAt(WITH_LEDGER, cornerGeo), '夹具漂了：画布角落已在格阵内，这条抓不到"外面"').toBeNull()
    fireEvent.click(svg, { clientX: 4, clientY: 4 })       // 画布角落：必在格阵扫描范围外
    expect(onCellPick).toHaveBeenCalledWith(null)
    expect(onCenterChange, '格阵外照旧是"改中心"这一手势').toHaveBeenCalled()
  })

  it('判定尺开关关着 ⇒ 不把手势解释成选格（没依据的入口不摆），改中心照旧', async () => {
    const onCellPick = vi.fn()
    const onCenterChange = vi.fn()
    const { container } = await mountFallback(WITH_LEDGER, { onCellPick, onCenterChange })
    const svg = container.querySelector('svg[aria-label*="画布"]')!
    stubCanvasRect(svg)
    const [lng, lat] = cellCenter(LEDGER, CELL[0], CELL[1])
    const [px, py] = lcToPx(WITH_LEDGER.scene.center, lng, lat)
    fireEvent.click(svg, { clientX: px, clientY: py })
    expect(onCellPick, '开关关着却选格 ⇒ 与 live 的 `:1108` 半边不对称').not.toHaveBeenCalled()
    expect(onCenterChange).toHaveBeenCalled()
  })
})

/** live 侧那枚方框：判定尺色描边 + `fillOpacity: 0.08` 是唯一指纹（判定圆在 circles 里）。 */
function cellLayerBoxPoly() {
  const hit = (instances.polys as Array<{ opts: Record<string, unknown> }>)
    .find((p) => p.opts.strokeColor === LC_JUDGE_SCALE_COLOR && p.opts.fillOpacity === 0.08)
  if (!hit) throw new Error('live 侧没建出选中格方框（mode 没落到 live？或 plan 取空？）')
  return hit as unknown as { point: unknown[]; opts: Record<string, unknown> }
}

/* ── 笔3b · 整幅格阵的 plan（"画哪些格"必须有交叉锚，不能自证） ───────────── */
describe('cellsGridPlan（整幅格阵的几何与结论）', () => {
  const ev2 = kailiEv2 as unknown as LivingCircleReport

  it('格数与 `caliber.cells_inside` 逐字相等 —— 交叉锚，不是自造期望值', () => {
    const plan = cellsGridPlan(ev2)
    expect(plan, 'ev2 带 15×15 台账，plan 不该为空').not.toBeNull()
    expect(plan!.n).toBe(15)
    expect(plan!.cells.length, '画出来的格数必须等于载荷声明的"圈内格数"')
      .toBe(ev2.caliber!.cells_inside)
  })

  it('`outside` 一格都不画（与台账卡同一档口径：区外不上色，画了会像"这里没问题"）', () => {
    const plan = cellsGridPlan(ev2)!
    expect(plan.cells.some((c) => c.verdict === 'outside')).toBe(false)
    expect(plan.cells.every((c) => LC_LEDGER_FILL[c.verdict] !== 'transparent')).toBe(true)
  })

  it('每格是四角闭合方框（live 的 Polygon 与降级 SVG 都只吃这四角）', () => {
    for (const c of cellsGridPlan(ev2)!.cells.slice(0, 5)) {
      expect(c.corners).toHaveLength(4)
      expect(c.corners[0]).not.toEqual(c.corners[2])
    }
  })

  it('没发台账的样区 ⇒ null（整层不出现，不是画一张空图）', () => {
    expect(cellsGridPlan(kaili as unknown as LivingCircleReport)).toBeNull()
  })

  it('五档色表只有一份：台账卡里不许再自带字面量', async () => {
    // 路径按 `process.cwd()` 解（与 `roadContrast.test.ts` 那颗源扫守卫同一写法）：
    // jsdom 下 `import.meta.url` 不是 file: 协议，new URL(...) 会直接抛。
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf8')
    const card = read('src/components/lifecircle/CellsLedgerCard.tsx')
    expect(card.includes("outside: 'transparent'"),
      '台账卡又长出一份五档表 ⇒ 地图格阵与卡迟早一个灰一个红').toBe(false)
    const layer = read('src/components/lifecircle/CellLayer.ts')
    expect(layer.match(/outside: 'transparent'/g)).toHaveLength(1)
  })
})
