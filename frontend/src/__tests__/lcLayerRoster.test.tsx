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
import type { LngLat, LivingCircleReport } from '../types'
import { LC_ISO_COMPARE_COLOR, LC_JUDGE_SCALE_COLOR } from '../lib/livingCircle'
import { LAYER_ATTR_BY_SIDE, LC_LAYERS, parseLayerAttr } from '../components/lifecircle/lcLayers'
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

const ALL_ON = { showJudgeScale: true, showIsoCompare: true, showShapeSectors: true, selectedCell: [1, 1], showCellsGrid: true }

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

/** 笔 3c：对照态一份申报说不清归谁 ⇒ 按侧读两份（属性名取自生产常量，不在此写死字面）。 */
function declaredSides(root: HTMLElement) {
  const read = (side: 'a' | 'b') => {
    const attr = LAYER_ATTR_BY_SIDE[side]
    const el = root.querySelector(`[${attr}]`)
    return { present: el !== null, layers: parseLayerAttr(el?.getAttribute(attr)) }
  }
  return { a: read('a').layers, b: read('b').layers, aPresent: read('a').present, bPresent: read('b').present }
}

async function bothSides(report: LivingCircleReport, props: Record<string, unknown>) {
  const live = await mountLive(report, props)
  const fb = await mountFallback(report, props)
  const wantA = declaredSides(fb.container).a
  const wantB = declaredSides(fb.container).b
  // live 侧那两份申报由四条 effect 分别写 ⇒ 轮询到与降级侧一致（不一致就是"只有一档画得出"）
  await waitFor(() => {
    const ls = declaredSides(live.container)
    expect(ls.a).toEqual([...wantA].sort())
    expect(ls.b).toEqual([...wantB].sort())
  })
  return { live, fb, wantA, wantB }
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
    // 格阵（笔3b）：五档色表里"判盲"那一档的填充色是它的指纹，与台账卡同一份表
    expect(polys().some((p) => p.opts.fillColor === '#6E6E6E'),
      'live 档整幅格阵没建出来（没有一格按 blind 档填充）').toBe(true)
  })
})

describe('两档名册相等 · 逐道闸各关一次', () => {
  it('关判定尺 ⇒ 两档**同样只少** judge-ruler，其余三层都在（用集合差，不用数量）', async () => {
    const { want } = await bothModes(FULL, { ...ALL_ON, showJudgeScale: false })
    expect(want).toEqual(['cells-grid', 'iso-compare', 'selected-cell', 'shape-sectors'])
  })

  it('关格阵开关 ⇒ 两档**同样只少** cells-grid（这一层不是常驻背景）', async () => {
    const { want, fb } = await bothModes(FULL, { ...ALL_ON, showCellsGrid: false })
    expect(want).toEqual(['iso-compare', 'judge-ruler', 'selected-cell', 'shape-sectors'])
    expect(fb.container.querySelectorAll('[data-lc-layer="cells-grid"]')).toHaveLength(0)
  })

  it('脱敏态（分享链接）⇒ 逐格地理边界一律不上屏：selected-cell 与 cells-grid 同时退场（P0-5）', async () => {
    const { want, fb } = await bothModes(FULL, { ...ALL_ON, desensitize: true })
    expect(want).toEqual(['iso-compare', 'judge-ruler', 'shape-sectors'])
    expect(fb.container.querySelectorAll('[data-lc-layer="selected-cell"]')).toHaveLength(0)
    expect(fb.container.querySelectorAll('[data-lc-layer="cells-grid"]')).toHaveLength(0)
  })

  /* 笔 3c 显式改写（不是删）：这条原来钉的是"对照态 ⇒ 解释层整批退场"。
     退场已被换成白名单（`SECONDARY_LAYERS`），所以这里改成钉**白名单边界**：
     三层进得来、两层（判定尺 / 选中格）仍旧两侧都进不来。
     为什么仍要"两档各问一次"这一对：本域四次出事都是"只有一档画得出"。 */
  it('对照态 ⇒ 白名单三层两档都报出，白名单外两层两侧都退场', async () => {
    const { wantA, wantB, fb } = await bothSides(FULL, { ...ALL_ON, compareReport: FULL })
    expect(wantA).toEqual(['cells-grid', 'iso-compare', 'shape-sectors'])
    expect(wantB).toEqual(wantA)                      // 两侧同值 ⇒ 同一组层（合枚，归两侧）
    expect(fb.container.querySelector('[data-lc-mode="fallback"]')
      ?.getAttribute('data-lc-layers'), '对照态下 legacy 那份申报仍是 A 侧那一份')
      .toEqual(wantA.join(','))
    for (const n of ['judge-ruler', 'selected-cell']) {
      expect(wantA.concat(wantB), `${n} 不该进对照态白名单`).not.toContain(n)
      expect(fb.container.querySelectorAll(`[data-lc-layer="${n}"]`), `${n} 一枚都不许画`).toHaveLength(0)
    }
  })
})

/* ══ 笔 3c · 同框图的层归属：同值合枚 / 一侧没发 / 不同值各画一枚 ══
 * 这三条钉的是"两侧画进同一坐标系时谁是谁"——预览量出来的事实：演示名册里唯一同框的那一对
 * （kaili-ev2 × kaili）四档环、对照环、八方位楔形**逐字节相同**，只有结论层不同。
 * 所以"按侧换色"在几何层买到零信息，规则改成：同值只画一枚、不同值才两枚、没发就显式缺席。 */
describe('笔3c · 对照态按侧归属', () => {
  /** 与 FULL 同形但对照环整体平移：造"两侧都有环、值不同"那一态（出厂件里没有这一态）。 */
  const SHIFTED_RING = (() => {
    const src = FULL as unknown as { iso_compare: { geojson: { coordinates: LngLat[][] } } }
    const ring = src.iso_compare.geojson.coordinates[0]
    const moved = ring.map(([lng, lat]) => [lng + 0.02, lat + 0.02] as LngLat)
    return { ...(FULL as unknown as LivingCircleReport), iso_compare: { ...src.iso_compare, geojson: { coordinates: [moved] } } } as unknown as LivingCircleReport
  })()

  it('两侧同值 ⇒ 该层只画一枚，且这一枚同时申报给两侧', async () => {
    const { fb, live } = await bothSides(FULL, { ...ALL_ON, compareReport: FULL })
    const root = fb.container.querySelector('[data-lc-mode="fallback"]')!
    for (const n of ['iso-compare', 'shape-sectors', 'cells-grid']) {
      const drawn = [...root.querySelectorAll(`[data-lc-layer="${n}"]`)]
      expect(drawn.length, `${n} 一枚都没画`).toBeGreaterThan(0)
      const sides = new Set(drawn.map((el) => el.getAttribute('data-lc-side')))
      // 合枚 = 这一层只有一份实例、归属写 both。两枚（a 与 b 各一份）就是没合。
      expect([...sides], `${n} 同值却按侧各画了一份`).toEqual(['both'])
    }
    // live 侧同判：两侧各自那份申报里都有这三层
    const ls = declaredSides(live.container)
    expect(ls.a).toEqual(ls.b)
  })

  it('一侧没发这一层 ⇒ 另一侧照画，缺席那侧申报为空（不是画 0 格、也不是整层退场）', async () => {
    const { wantA, wantB, fb } = await bothSides(FULL, { ...ALL_ON, compareReport: BARE })
    expect(wantA, 'A 侧三层都该在').toEqual(['cells-grid', 'iso-compare', 'shape-sectors'])
    expect(wantB, 'BARE 什么都没有 ⇒ 一侧都不报').toEqual([])
    const root = fb.container.querySelector('[data-lc-mode="fallback"]')!
    for (const n of ['iso-compare', 'shape-sectors', 'cells-grid']) {
      const sides = [...root.querySelectorAll(`[data-lc-layer="${n}"]`)].map((el) => el.getAttribute('data-lc-side'))
      expect([...new Set(sides)], `${n} 只该有 A 侧那一枚`).toEqual(['a'])
    }
    expect(root.getAttribute(LAYER_ATTR_BY_SIDE.b), 'B 侧那份申报必须存在且为空（属性在、值为空串）')
      .toBe('')
  })

  it('两侧都有但值不同 ⇒ 该层各画一枚，且两枚分别归侧（不合枚）', async () => {
    const { wantA, wantB, fb } = await bothSides(FULL, { ...ALL_ON, compareReport: SHIFTED_RING })
    expect(wantA).toContain('iso-compare')
    expect(wantB).toContain('iso-compare')
    const root = fb.container.querySelector('[data-lc-mode="fallback"]')!
    const rings = [...root.querySelectorAll('[data-lc-layer="iso-compare"]')]
    expect(rings, '对照环该有两枚（两侧不同值）').toHaveLength(2)
    expect(rings.map((el) => el.getAttribute('data-lc-side')).sort()).toEqual(['a', 'b'])
    // 形状楔形两侧仍旧同值 ⇒ 那一层必须还是只一枚（证明合枚是按层判的，不是一刀切）
    const secs = new Set([...root.querySelectorAll('[data-lc-layer="shape-sectors"]')]
      .map((el) => el.getAttribute('data-lc-side')))
    expect([...secs], '楔形两侧同值 ⇒ 仍只一枚').toEqual(['both'])
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
