// @vitest-environment jsdom
/**
 * R1 · 两档图层名册必须相等（**按实例问，不按页问**）。
 *
 * ## 它治的病
 * `LcMap` 有两棵渲染树。历史上"加一层只写一档"犯过四次（判定尺、口径对照环、形状扇面、选中格），
 * 每一次都是产品与文案一起说谎，而套件照绿。根因是**该画哪些层没有唯一出处**：两档各抄一遍条件，
 * 少抄一处没有任何东西报警。`lcLayers.layerRoster` 把判定收成一颗函数、两档的绘制点都消费它，
 * 本文件就是钉这条相等的判据。
 *
 * ## 为什么 live 半边能被判据问到
 * canvas 覆盖物不进 DOM —— 10-07 实测过：整页 `querySelector('[data-lc-layer]')` 在降级档全绿、
 * live 必红。所以组件自己把名册写回 DOM：live 侧由 effect 在建完覆盖物后 imperative 记
 * `data-lc-layers`（不走 state —— 在 effect 里同步 setState 是 react-hooks 的硬错，棘轮会拦），
 * 降级侧的申报串就是那棵树按名册渲染出来的结果。
 *
 * ## 三条设计决定
 *  ① 断言用**集合差**不用数量：两档都少两层也可能数量相同、名字不同，数量判据抓不住。
 *  ② `LC_LAYERS` 里每个名字都必须在"全开"那一例里出现过 ⇒ 往名册加一层却两档都没接，
 *     这条当场红（这正是"清单落生产侧"要换来的东西）。
 *  ③ 反面半边（数据取不到 ⇒ 两侧都空）与正面半边（全开 ⇒ 四层齐全）都写：
 *     只留前者，"两档都啥也不画"会被读成一致。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import ev2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { LC_ISO_COMPARE_COLOR, LC_JUDGE_SCALE_COLOR } from '../lib/livingCircle'
import { LC_LAYERS, parseLayerAttr } from '../components/lifecircle/lcLayers'
import { instances, mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

/** 四层数据齐的实跑件：1 处盲区（自带 1000m 尺）、iso_compare（claim 正确）、台账 15×15、15min 档带形状键。 */
const FULL = ev2 as unknown as LivingCircleReport
/**
 * 反面半边用的件：`kaili` 本身就无盲区、无台账（判据第一次跑就把它报出来了 —— 它其实**带着**
 * `iso_compare` 与形状键，所以"数据取不到"这句得自己造齐）。这里把那两样也摘掉，
 * 才配当"四层都没有东西可画"的那半边。
 */
const BARE = {
  ...(kaili as unknown as LivingCircleReport),
  iso_compare: undefined,
  isochrones: (kaili as unknown as LivingCircleReport).isochrones.map((z) => ({ ...z, shape: undefined })),
} as unknown as LivingCircleReport

const ALL_ON = { showJudgeScale: true, showIsoCompare: true, showShapeSectors: true, selectedCell: [1, 1] }

type Poly = { opts: Record<string, unknown> }
type Circle = { opts: Record<string, unknown>; radius: number }
const polys = () => instances.polys as unknown as Poly[]
const circles = () => instances.circles as unknown as Circle[]

/** live 侧的申报由 effect 写，要轮询；降级侧是渲染产物，一次读到位。 */
const declaredIn = (root: HTMLElement) => parseLayerAttr(root.querySelector('[data-lc-layers]')?.getAttribute('data-lc-layers'))

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

/** 两档各挂一次，返回两份申报（live 侧轮询到"不再变"为止 —— 四层分属四条 effect）。 */
async function bothModes(report: LivingCircleReport, props: Record<string, unknown>) {
  const live = await mountLive(report, props)
  const fb = await mountFallback(report, props)
  const want = declaredIn(fb.container)
  await waitFor(() => expect(declaredIn(live.container)).toEqual([...want].sort()))
  return { live, fb, want }
}

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  mapConfig.mapStyleId = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('夹具前提（拿真件当锚，别用自造数据把判据变成自证）', () => {
  it('ev2 四层的数据都在：盲区带尺、对照环 claim 正确、台账 15×15、15min 档有形状键', () => {
    expect((FULL.blindspots ?? []).length).toBeGreaterThan(0)
    expect(FULL.blindspots[0].radius_m).toBe(1000)
    expect(FULL.iso_compare?.claim).toBe('caliber_comparison_only')
    expect(FULL.caliber!.cells_ledger?.n).toBe(15)
    expect((FULL.isochrones.find((z) => z.minutes === 15) as unknown as { shape?: unknown }).shape).toBeTruthy()
  })
})

describe('两档名册相等 · 全开', () => {
  it('四层全开 ⇒ 两档申报同一组层，且每一层都真的画了东西', async () => {
    const { live, fb, want } = await bothModes(FULL, ALL_ON)
    expect(want.sort()).toEqual([...LC_LAYERS].sort())        // ② 名册里每个名字都得出现得齐
    expect(declaredIn(live.container)).toEqual(want)
    // 降级侧：申报过的层，DOM 里必须真有对应图元（不许只在字符串上"画了"）
    for (const n of want) {
      expect(fb.container.querySelectorAll(`[data-lc-layer="${n}"]`).length,
        `降级档申报了 ${n} 却没有对应图元`).toBeGreaterThan(0)
    }
    // live 侧：拿替身记账核验对象真被 addOverlay 过（各层自己的指纹，与那三条纪律同源）
    expect(circles().some((c) => c.opts.strokeColor === LC_JUDGE_SCALE_COLOR && c.opts.fillOpacity === 0),
      'live 档判定尺圆没建出来').toBe(true)
    expect(polys().some((p) => p.opts.strokeColor === LC_ISO_COMPARE_COLOR), 'live 档对照环没建出来').toBe(true)
    expect(polys().some((p) => p.opts.strokeColor === '#5F7B69' || p.opts.strokeColor === '#A5625B'),
      'live 档形状扇面没建出来').toBe(true)
    expect(polys().some((p) => p.opts.strokeColor === LC_JUDGE_SCALE_COLOR && p.opts.fillOpacity === 0.08),
      'live 档选中格方框没建出来').toBe(true)
  })
})

describe('两档名册相等 · 逐道闸各关一次', () => {
  it('关判定尺 ⇒ 两档**同样只少** judge-ruler，其余三层都在（用集合差，不用数量）', async () => {
    const { want } = await bothModes(FULL, { ...ALL_ON, showJudgeScale: false })
    expect(want).toEqual(['iso-compare', 'selected-cell', 'shape-sectors'])
  })

  it('脱敏态（分享链接）⇒ 两档都只少 selected-cell（P0-5 那道闸与名册同一处出口）', async () => {
    const { want, fb } = await bothModes(FULL, { ...ALL_ON, desensitize: true })
    expect(want).toEqual(['iso-compare', 'judge-ruler', 'shape-sectors'])
    expect(fb.container.querySelectorAll('[data-lc-layer="selected-cell"]')).toHaveLength(0)
  })

  it('对照态 ⇒ 解释层整批退场，两档都报空（这一条与上面几条一对，才排除"只有一档退场"）', async () => {
    const { want } = await bothModes(FULL, { ...ALL_ON, compareReport: FULL })
    expect(want).toEqual([])
  })
})

describe('两档名册相等 · 反面半边（数据取不到 ⇒ 谁都不许画）', () => {
  it('开关全开但四层的数据一个都取不到 ⇒ 两档都报空，且降级 DOM 里一枚 data-lc-layer 都没有', async () => {
    const { want, fb } = await bothModes(BARE, ALL_ON)
    expect(want).toEqual([])
    expect(fb.container.querySelectorAll('[data-lc-layer]')).toHaveLength(0)
    expect(declaredIn(fb.container)).toEqual([])
  })
})
