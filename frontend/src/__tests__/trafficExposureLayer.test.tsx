// @vitest-environment jsdom
/**
 * 笔 D · 时段圆域图层（第五维 · `traffic-exposure`）。
 *
 * 钉的是四件事，都对应本域踩过的形状：
 *  ① **两档同一组层**：这层在 live 是一枚 `bmap.Circle`、在降级档是一枚 `lcRing` 逆投影多边形。
 *     历史上"只补一档"犯过四次（判定尺、对照环、扇区、选中格），每一次都是产品与文案一起说谎。
 *  ② **缺源整层不出现**：`coverage=absent` 时不许画 0 半径圈、不许留灰档图例 —— 那会把
 *     "没测到"读成"这个样区路况很好"，是伪造正结论（与"不许当 0 分"同一条纪律）。
 *  ③ **半径只从载荷取**：图上那一枚的米数必须逐位等于 `sampling.traffic.radius_m`
 *     （判定尺当年"写死 1000 却画出 800m"同族事故）。
 *  ④ **措辞禁令**：这一层量的是环境暴露度，屏上任何一句都不许写成居民的步行能力断言。
 *
 * 替身只走 `helpers/bmapGLFake` 这一个出口（`instances.circles` 是它的记账数组），不在本文件手写 fake。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import jinsong from '../mocks/fixtures/livingCircle/beijing-jinsong.json'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { LC_TRAFFIC_TIER_COLOR, trafficExposureLabel, trafficExposureOf } from '../lib/livingCircle'
import { parseLayerAttr } from '../components/lifecircle/lcLayers'
import { instances, mapConfig, resetInstances } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const J = jinsong as unknown as LivingCircleReport
const K = kaili as unknown as LivingCircleReport
/** 唯一被本文件动到的开关：其余判读层保持默认关，免得把别的层的几何混进断言。 */
const ON = { showTrafficExposure: true }
type Circle = { opts: Record<string, unknown>; radius: number; center?: unknown }
const circles = () => instances.circles as unknown as Circle[]
const declaredIn = (root: HTMLElement) =>
  parseLayerAttr(root.querySelector('[data-lc-layers]')?.getAttribute('data-lc-layers'))

async function mountLive(report: LivingCircleReport, props: Record<string, unknown> = {}) {
  mapConfig.browserAk = 'test-ak'
  const view = render(<LcMap report={report} {...(props as object)} />)
  await waitFor(() => expect(view.container.querySelector('[data-lc-map="true"]')).toBeTruthy())
  return view
}
async function mountFallback(report: LivingCircleReport, props: Record<string, unknown> = {}) {
  mapConfig.browserAk = ''
  const view = render(<LcMap report={report} {...(props as object)} />)
  await waitFor(() => expect(view.container.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
  return view
}

beforeEach(() => {
  resetInstances()
  mapConfig.mapStyleId = ''
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('夹具前提（拿真件当锚，别用自造数据把判据变成自证）', () => {
  it('劲松带 coverage=ok 的路况读数；凯里那份没有（缺源半边用的件）', () => {
    expect(J.sampling?.traffic?.coverage).toBe('ok')
    expect((J.sampling?.traffic?.radius_m ?? 0)).toBeGreaterThan(0)
    expect(trafficExposureOf(K)).toBeNull()
  })
})

describe('两档都画得出这一层', () => {
  it('有源＋勾选 ⇒ 两档申报同一组层，且各自真有对应几何', async () => {
    const fb = await mountFallback(J, ON)
    expect(declaredIn(fb.container)).toContain('traffic-exposure')
    const poly = fb.container.querySelector('[data-lc-layer="traffic-exposure"]')
    expect(poly, '降级档申报了这一层却没有图元').not.toBeNull()
    expect(poly!.getAttribute('points'), '环必须走 lcRing 逆投影，不许退化成 SVG 正圆').toContain(',')

    const live = await mountLive(J, ON)
    await waitFor(() => expect(declaredIn(live.container)).toEqual(declaredIn(fb.container)))
    const t = trafficExposureOf(J)!
    const mine = circles().find((c) => c.opts.fillOpacity === 0.08)
    expect(mine, 'live 档那枚圆没建出来').toBeTruthy()
    expect(mine!.radius, '半径必须逐位等于载荷读数（不许写死米数）').toBe(t.radiusM)
    expect(mine!.opts.strokeStyle, '与判定尺同一条纪律：虚线').toBe('dashed')
    expect(mine!.opts.enableClicking, '解释层不吃点击').toBe(false)
    // 圈色 = 圆域内占多数那一档（与第 9 章两张条形图同一组色，不另取一份色值）
    expect(Object.values(LC_TRAFFIC_TIER_COLOR)).toContain(mine!.opts.strokeColor)
  })

  it('不勾 ⇒ 两档都不出现（这一层不是常驻背景）', async () => {
    const fb = await mountFallback(J)
    expect(declaredIn(fb.container)).not.toContain('traffic-exposure')
    expect(fb.container.querySelectorAll('[data-lc-layer="traffic-exposure"]')).toHaveLength(0)
    const live = await mountLive(J)
    expect(declaredIn(live.container)).not.toContain('traffic-exposure')
    expect(circles()).toHaveLength(0)
  })
})

describe('缺源半边（本层最大的假绿风险）', () => {
  it('凯里：勾也开不出来 ⇒ 两档都零图元、申报里也没有这一层（不画 0 半径圈）', async () => {
    const fb = await mountFallback(K, ON)
    expect(declaredIn(fb.container)).not.toContain('traffic-exposure')
    expect(fb.container.querySelectorAll('[data-lc-layer="traffic-exposure"]')).toHaveLength(0)
    const live = await mountLive(K, ON)
    expect(declaredIn(live.container)).not.toContain('traffic-exposure')
    expect(circles()).toHaveLength(0)
  })
})

describe('读侧再判：半份声明不许变成一个像样的圆', () => {
  /** 在真件之上现造坏态（只动 `sampling.traffic` 这一格）—— 判的是那颗取值口的契约。 */
  const withTraffic = (tr: unknown) =>
    ({ ...J, sampling: { ...(J.sampling as object), traffic: tr } }) as unknown as LivingCircleReport
  const GOOD = (J.sampling as { traffic: Record<string, unknown> }).traffic

  it.each([
    ['整个键缺失', undefined],
    ['coverage=absent', { ...GOOD, coverage: 'absent' }],
    ['没有半径', (() => { const t = { ...GOOD }; delete t.radius_m; return t })()],
    ['半径 NaN', { ...GOOD, radius_m: Number.NaN }],
    ['半径 0', { ...GOOD, radius_m: 0 }],
    ['半径负数', { ...GOOD, radius_m: -1273 }],
    ['分数非有限', { ...GOOD, exposure_score: Number.POSITIVE_INFINITY }],
    ['指数非有限', { ...GOOD, exposure_index: Number.NaN }],
  ])('%s ⇒ null（不回落默认半径、不印 0 分）', (_why, tr) => {
    expect(trafficExposureOf(withTraffic(tr))).toBeNull()
  })

  it('正对照：把上面那些坏态逐一修回去就画得出来（防"恒 null"也算通过）', () => {
    expect(trafficExposureOf(withTraffic(GOOD))).not.toBeNull()
    expect(trafficExposureOf(withTraffic({ ...GOOD, coverage: 'absent' }))).toBeNull()
  })

  it('四档占比全 0 ⇒ 圈照画，但取中性色而不是硬挑一档（挑了就是给"没测到"编一个颜色）', () => {
    const t = trafficExposureOf(withTraffic({
      ...GOOD, tier_share: { 畅通: 0, 缓行: 0, 拥堵: 0, 严重拥堵: 0 },
    }))
    expect(t).not.toBeNull()
    expect(t!.dominantTier).toBeNull()
  })
})

describe('图注与措辞纪律', () => {
  it('那一圈的 title 就是唯一出口那颗函数给的句子，且当场否认"这就是可达区"', async () => {
    const fb = await mountFallback(J, ON)
    const label = trafficExposureLabel(J)
    expect(label).not.toBeNull()
    expect(label, '圆域≠可达区这句是口径的承重句，不许在实现里被洗掉').toContain('不是可达区')
    const title = fb.container.querySelector('[data-lc-layer="traffic-exposure"] title')?.textContent
    expect(title, '画布与图例不许各写一份说法').toBe(label)
    // 半径数字只许出现一处（来自载荷），窗口那句同 in 一句
    expect(label).toContain(String(Math.round(trafficExposureOf(J)!.radiusM)))
  })

  it('屏上那句不许把环境暴露度写成居民步行能力断言（短语禁令同族）', () => {
    const label = trafficExposureLabel(J) ?? ''
    for (const banned of ['走不到', '到不了', '步行能力', '居民无法', '走不动', '可达范围']) {
      expect(label, `出现被禁的说法：${banned}`).not.toContain(banned)
    }
  })
})
