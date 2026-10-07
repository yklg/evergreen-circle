// @vitest-environment jsdom
/**
 * C5 · 判定尺图层的**落图**契约：live（BMapGL Circle）与降级（SVG polygon）两档必须同尺。
 *
 * ## 为什么补这份文件
 *
 * `judgeScaleToggle.test.tsx` 钉的是「开关出不出、那句话、受控翻转」——**一条都没验「勾了画没画」**。
 * 于是判定尺长期只有 live 分支有实现（`LcMap.tsx:1075`），降级画布分支零落点：那颗开关在降级态
 * 点下去毫无反应，而全套件没人能发现。本文件就是缺失的那只眼睛，并把「两档折算回米必须相等」
 * 钉成不变量 —— 这正是防它再次只补一半的防线。
 *
 * ## 被守护的契约
 *  ① 两档同尺：live 的 `Circle.radius` 与降级 polygon 折算回的米数**相等**，且等于产物里那把尺。
 *     锚值取 **800m 而非 1000m** —— 写死 1km 会当场红（`LcMap.tsx:1068` 记着的教训）。
 *  ② 降级档 x/y 两向都要是 800m：画布横纵比例本就不同（`lcToPx` 的 `W/2÷R ≠ H/2÷R`），
 *     图省事用 SVG 正圆会让纵向多出约 39%（`lib/livingCircle.ts:263-266` 那条 P0 记录）。
 *  ③ 只描边、不参与命中：live 侧 `fillOpacity: 0` + `enableClicking: false`，降级侧 `fill="none"`
 *     （可点面会吃掉圈内采样点 tooltip，`:587-592` 的真机 spike 早已否证）。
 *  ④ 缺席即未发生：两把尺都取不到 ⇒ 两档**整层不画**，不画 0 半径圈、不摆勾不动的入口。
 *  ⑤ 说法同处：降级 `<title>` 那句来自 `judgeRulerLabel`，两处不许各写一份半径。
 *
 * ## 效力上限（防「绿＝全对」的错觉）
 * 本文件证的是**米制折算相等**与**构造入参正确**，证不了真机上那圈落在屏幕哪个位置、
 * 画布边缘的盲区会不会被 viewBox 裁掉一半。那只有真浏览器一眼能答。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import {
  LC_CANVAS,
  LC_JUDGE_SCALE_COLOR,
  judgeRulerLabel,
  judgeRulerM,
  lcToPx,
} from '../lib/livingCircle'
import { instances, mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'
import { waitDrawn } from './helpers/waitDrawn'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

/** 锚值：故意不是 1000。分档后尺长取自产物，写死常量就会「800m 的圆标 1km」。 */
const RULER_M = 800

const BASE = kaili as unknown as LivingCircleReport

/** 造一处盲区：`center` 落在画布中心 ⇒ 折算像素时没有纬度差噪声，判据读得干净。 */
function blind(id: string, center: [number, number], radiusM: number | undefined) {
  const ring = (offset: number, offset2: number) =>
    [center[0] - 0.002 + offset, center[1] - 0.002 + offset2]
  return {
    id,
    center,
    ...(radiusM === undefined ? {} : { radius_m: radiusM }),
    missing_facilities: ['primary'],
    nearest: [{ facility: 'primary', name: '某小学', distance_m: 1155, direction: '东北' }],
    polygon: {
      type: 'Polygon',
      coordinates: [[ring(0, 0), ring(0.004, 0), ring(0.004, 0.004), ring(0, 0.004), ring(0, 0)]],
    },
    severity: 'light',
  } as unknown as LivingCircleReport['blindspots'][number]
}

const CENTER = BASE.scene.center
/** 一处盲区，中心即画布中心：用来量米制半径。 */
const ONE: LivingCircleReport = { ...BASE, blindspots: [blind('bs-尺-1', CENTER, RULER_M)] }
/** 两处盲区（第二处偏东 400m 左右）：用来量「一盘一环」的计数。 */
const TWO: LivingCircleReport = {
  ...BASE,
  blindspots: [blind('bs-尺-1', CENTER, RULER_M), blind('bs-尺-2', [CENTER[0] + 0.004, CENTER[1]], RULER_M)],
}
/** 两把尺都取不到（无台账、盲区自带 radius_m 缺失）⇒ 整层不该出现。 */
const NO_RULER: LivingCircleReport = { ...BASE, blindspots: [blind('bs-无尺', CENTER, undefined)] }

/** 降级画布里的判定尺环：按**颜色**取，不靠 React key（key 不进 DOM）。 */
function scalePolys(svg: Element): Element[] {
  return Array.from(svg.querySelectorAll('polygon')).filter(
    (p) => p.getAttribute('stroke') === LC_JUDGE_SCALE_COLOR,
  )
}

/**
 * 把降级环的像素外沿折算回米：与 `lcToPx` 同一个线性变换的逆
 * （`px = W/2 + (mx/R)*(W/2)` ⇒ `mx = (px − W/2)/(W/2)*R`；纵向同理取 `cy − minY`）。
 * steps=48 时 `cos(0)` 与 `sin(π/2)` 都恰好取到极值 ⇒ 两向外沿是精确值，不是插值近似。
 */
function ringMeters(poly: Element, centerPx: [number, number]): { rx: number; ry: number } {
  const pts = (poly.getAttribute('points') ?? '')
    .trim()
    .split(/\s+/)
    .map((pair) => pair.split(',').map(Number))
  expect(pts.length, '降级判定尺环没有点：几何断言将无从谈起').toBeGreaterThan(0)
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const [cx, cy] = centerPx
  return {
    rx: ((Math.max(...xs) - cx) / (LC_CANVAS.W / 2)) * LC_CANVAS.R,
    ry: ((cy - Math.min(...ys)) / (LC_CANVAS.H / 2)) * LC_CANVAS.R,
  }
}

function fallbackSvg(container: HTMLElement): Element {
  const svg = container.querySelector('svg[aria-label="生活圈等时圈画布（降级）"]')
  if (!svg) throw new Error('降级画布没出现（mode 没落到 fallback？检查 mapConfig.browserAk）')
  return svg
}

const circles = () => instances.circles as Array<{ radius: number; opts: Record<string, unknown> }>

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

describe('判定尺落图 · 夹具前提（锚值必须来自独立事实，不是被测代码自证）', () => {
  it('出厂 kaili：无台账、无盲区 ⇒ `judgeRulerM` 取不到尺（漂了本套就白测）', () => {
    expect(BASE.blindspots).toHaveLength(0)
    expect(judgeRulerM(BASE)).toBeNull()
    // 锚值成立的前提：尺是从盲区条目声明来的，而不是从 `judgeRulerM` 里"算"出来的
    expect(judgeRulerM(ONE)).toBe(RULER_M)
    expect(judgeRulerM(NO_RULER)).toBeNull()
  })
})

describe('判定尺落图 · live 档（BMapGL Circle）', () => {
  it('勾上 ⇒ 一处盲区一枚圆，半径取自产物（800 不是 1000），且只描边、不参与命中', async () => {
    const { container } = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(circles().length).toBe(1))

    const [c] = circles()
    expect(c.radius).toBe(RULER_M)
    expect(c.opts.enableClicking).toBe(false)
    expect(c.opts.fillOpacity).toBe(0)
    expect(c.opts.strokeStyle).toBe('dashed')
    expect(c.opts.strokeColor).toBe(LC_JUDGE_SCALE_COLOR)
    // 不该有别的 Circle 混进来（整改建议圈、选中格圈都要点击或 selectedCell 才建）
    expect(circles()).toHaveLength(1)
    expect(container).toBeTruthy()
  })

  it('两处盲区 ⇒ 两枚圆（一盘一环），计数不许按"首个可用项"糊过去', async () => {
    render(<LcMap report={TWO} showJudgeScale />)
    await waitFor(() => expect(circles().length).toBe(2))
    for (const c of circles()) expect(c.radius).toBe(RULER_M)
  })

  it('不勾 ⇒ 一枚都不建（同一条用例里先证"能看见"，否则"0 枚"可能只是时序空转）', async () => {
    // 正面半边：同一替身、同一报告，勾上必须观测到 2 枚 —— 这条红了说明观察通道断了，
    // 那反面那半的"0"就不值一分钱。
    const on = render(<LcMap report={TWO} showJudgeScale />)
    await waitFor(() => expect(circles().length).toBe(2))
    on.unmount()
    resetInstances()

    // 反面半边：不勾。等到 `[data-lc-map="true"]` 出现才判 0 —— 该节点只在 live 档渲染，
    // 所以它成立就意味着 mode 已落到 live、依赖 mode 的那条 effect 已经跑过。
    const off = render(<LcMap report={TWO} />)
    await waitFor(() => expect(off.container.querySelector('[data-lc-map="true"]')).toBeTruthy())
    expect(circles()).toHaveLength(0)
  })
})

describe('判定尺落图 · 降级档（SVG polygon）', () => {
  it('无 AK ⇒ 降级画布里出现判定尺环，且 x/y 两向折算回米都等于那把尺', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(scalePolys(fallbackSvg(container)).length).toBe(1))

    const px = lcToPx(CENTER, CENTER[0], CENTER[1])
    const { rx, ry } = ringMeters(scalePolys(fallbackSvg(container))[0], px)
    expect(Math.abs(rx - RULER_M)).toBeLessThanOrEqual(5)
    expect(Math.abs(ry - RULER_M)).toBeLessThanOrEqual(5)

    // 敏感性对照：同一把尺子必须分辨得出 800 与 1800 —— 否则上面两条 ±5 是自写恒真
    expect(Math.abs(rx - (RULER_M + 1000))).toBeGreaterThan(50)
    expect(Math.abs(ry - (RULER_M + 1000))).toBeGreaterThan(50)

    const poly = scalePolys(fallbackSvg(container))[0]
    expect(poly.getAttribute('fill'), '降级档必须只描边，填充会压掉五级等时圈色阶').toBe('none')
    expect(poly.getAttribute('stroke-dasharray')).toBe('6 4')
  })

  it('说法与图例同源：`<title>` 用的就是 `judgeRulerLabel`，且带 800m、不带 1000m', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(scalePolys(fallbackSvg(container)).length).toBe(1))

    const label = scalePolys(fallbackSvg(container))[0].querySelector('title')
    expect(label, '降级环没有 <title>：口径说明断了').toBeTruthy()
    expect(label!.textContent).toBe(judgeRulerLabel(ONE))
    expect(label!.textContent).toContain(`${RULER_M}m`)
    expect(label!.textContent).not.toContain('1000m')
  })

  it('不勾 ⇒ 画布里没有那枚环（同一条用例先证"勾上就有 2 枚"，颜色选择器才不是空转）', async () => {
    mapConfig.browserAk = ''

    // 正面半边：勾上 ⇒ 两处盲区两枚环（也顺带证明这个颜色选择器命中得了真东西）
    const on = render(<LcMap report={TWO} showJudgeScale />)
    await waitFor(() => expect(scalePolys(fallbackSvg(on.container)).length).toBe(2))
    on.unmount()

    // 反面半边：不勾 ⇒ 0 枚
    const { container } = render(<LcMap report={TWO} />)
    await waitFor(() => expect(fallbackSvg(container)).toBeTruthy())
    expect(scalePolys(fallbackSvg(container))).toHaveLength(0)
    // 选择器有效性自报：同一次渲染里盲区多边形确实存在，说明不是"整张画布空的"
    expect(fallbackSvg(container).querySelectorAll('polygon').length).toBeGreaterThan(0)
  })
})

describe('判定尺落图 · 两档同尺（本次回归的正面防点）', () => {
  it('同一份报告：live 的米数与降级折算的米数必须相等', async () => {
    // 先 live
    mapConfig.browserAk = 'test-ak'
    const live = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(circles().length).toBe(1))
    const liveR = circles()[0].radius
    live.unmount()

    // 再降级（同一份 report、同一个尺出口）
    resetInstances()
    mapConfig.browserAk = ''
    const fb = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(scalePolys(fallbackSvg(fb.container)).length).toBe(1))
    const px = lcToPx(CENTER, CENTER[0], CENTER[1])
    const { rx, ry } = ringMeters(scalePolys(fallbackSvg(fb.container))[0], px)

    expect(Math.abs(liveR - rx)).toBeLessThanOrEqual(5)
    expect(Math.abs(liveR - ry)).toBeLessThanOrEqual(5)
    expect(liveR).toBe(judgeRulerM(ONE))
  })

  it('两把尺都取不到 ⇒ 两档都整层不画（先证明两档都画得出来，那两个 0 才算数）', async () => {
    // ── 正面半边：同一套替身下，带尺的报告在两档都必须落图 ──
    mapConfig.browserAk = 'test-ak'
    const posLive = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(circles().length).toBe(1))
    posLive.unmount()
    resetInstances()

    mapConfig.browserAk = ''
    const posFb = render(<LcMap report={ONE} showJudgeScale />)
    await waitFor(() => expect(scalePolys(fallbackSvg(posFb.container)).length).toBe(1))
    posFb.unmount()
    resetInstances()

    // ── 反面半边：尺取不到 ⇒ 两档都 0 ──
    expect(judgeRulerM(NO_RULER)).toBeNull()

    mapConfig.browserAk = 'test-ak'
    const live = render(<LcMap report={NO_RULER} showJudgeScale />)
    await waitFor(() => expect(live.container.querySelector('[data-lc-map="true"]')).toBeTruthy())
    await waitDrawn({ maps: 1 })
    expect(instances.maps.length, 'live 那侧只该建出一幅地图').toBe(1)
    expect(circles()).toHaveLength(0)
    live.unmount()

    resetInstances()
    mapConfig.browserAk = ''
    const fb = render(<LcMap report={NO_RULER} showJudgeScale />)
    await waitFor(() => expect(fallbackSvg(fb.container)).toBeTruthy())
    expect(scalePolys(fallbackSvg(fb.container))).toHaveLength(0)
  })
})
