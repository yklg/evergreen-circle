// @vitest-environment jsdom
/**
 * 模式申报 · `data-lc-mode` 是这张地图"现在在哪一档"的**唯一发话口**。
 *
 * ## 为什么补这三条
 *
 * 10-06~10-07 那场反复改写里，判据一直靠**从 DOM 反推**模式（数 `canvas` 有没有），而组件自己早就
 * 知道答案（`LcMap.tsx:416` 的 `mode` 状态、`:1306` 的 `onMapMode` 上报）。实测代价很硬：同一份工作区
 * 同一个下午，`e2e/lcReportLocalMap.spec.ts` 的「反向通道」上午走 fallback（被 skip）、下午走 live
 * （真红）——走哪一档只取决于那一刻有没有后端答 `/api/life-circle/map-config`。⇒ 由 DOM 猜出来的
 * 档不是稳定资产，本笔（R3）把它换成读组件申报的值。
 *
 * 另一条教训也钉在这里：`data-lc-map` 这个名字在本仓**只等于"BMapGL live 容器"**，10-06 我把它加宽到
 * 两档通用，实测打红 `lcStageStructure:90`（那条拿它当"还没从 boot 落定"的反证）并把
 * `judgeScaleCanvas:170` 那扇"已落到 live"的门变成恒真。所以这里第 1 条除了申报值，还要钉住
 * **降级树上不许再出现 `data-lc-map`** —— 那是既有语义，不是实现细节（§7.2 那条"一词多义"事故）。
 *
 * ## 效力上限
 * 本文件证的是"属性由 mode 状态派生、两档取值不同"，证不了真机上 BMapGL 到底加载没加载；
 * 那一档的实际行为仍只有 Playwright 说了算。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { mapConfig, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  return H.fakeBMapModule({})
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const BASE = kaili as unknown as LivingCircleReport

/** 造一处盲区（形状照 `judgeScaleCanvas.test.tsx` 的现成手法）：id 就是要被点名的那个值。 */
function blind(id: string, center: [number, number]) {
  const ring = (dx: number, dy: number) => [center[0] - 0.002 + dx, center[1] - 0.002 + dy]
  return {
    id,
    center,
    missing_facilities: ['primary'],
    nearest: [{ facility: 'primary', name: '某小学', distance_m: 1155, direction: '东北' }],
    polygon: {
      type: 'Polygon',
      coordinates: [[ring(0, 0), ring(0.004, 0), ring(0.004, 0.004), ring(0, 0.004), ring(0, 0)]],
    },
    severity: 'light',
  } as unknown as LivingCircleReport['blindspots'][number]
}

const C = BASE.scene.center
const ONE = { ...BASE, blindspots: [blind('bs-钩子-1', C)] } as LivingCircleReport
const TWO = {
  ...BASE,
  blindspots: [blind('bs-钩子-1', C), blind('bs-钩子-2', [C[0] + 0.004, C[1]])],
} as LivingCircleReport

const modeOf = (root: HTMLElement, sel: string) => root.querySelector(sel)?.getAttribute('data-lc-mode')

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

describe('模式申报 · 降级档', () => {
  it('无 AK ⇒ 根节点申报 `fallback`，且这棵树上**不许**有 `data-lc-map`', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={BASE} />)
    await waitFor(() => expect(container.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
    expect(modeOf(container, '[data-lc-mode]')).toBe('fallback')
    expect(container.querySelector('[data-lc-map]'),
      '把 `data-lc-map` 又贴回降级树 ⇒ `lcStageStructure:90` 会红、`judgeScaleCanvas:170` 那扇门变恒真').toBeNull()
  })
})

describe('模式申报 · live 档', () => {
  it('有 AK ⇒ 宿主申报 `live`，并且 `data-lc-map` 仍在（两件事各管各的，不许合并成一个属性）', async () => {
    const { container } = render(<LcMap report={BASE} />)
    await waitFor(() => expect(modeOf(container, '[data-lc-mode="live"]')).toBe('live'))
    expect(container.querySelector('[data-lc-map="true"]'),
      'live 那棵树丢了 data-lc-map ⇒ 5 处按它认档的判据一起失效').toBeTruthy()
  })

  it('还没落定时申报的是 `boot`，不是把 boot 谎报成 live 或 fallback', async () => {
    const { container } = render(<LcMap report={BASE} />)
    // 第一帧：mode 仍是初值 'boot'，而那棵容器树已经挂在 DOM 上 —— 这正是 e2e 需要排除它的原因
    expect(modeOf(container, '[data-lc-map]')).toBe('boot')
    await waitFor(() => expect(modeOf(container, '[data-lc-mode="live"]')).toBe('live'))
  })
})

describe('模式申报 · 正对照（不证这一条，上面几处可能只是恒绿的摆设）', () => {
  it('同一份报告、同一棵组件：两档申报出来的值必须**互不相同**且各等于自己的档', async () => {
    mapConfig.browserAk = ''
    const off = render(<LcMap report={BASE} />)
    await waitFor(() => expect(modeOf(off.container, '[data-lc-mode]')).toBe('fallback'))
    off.unmount()
    resetInstances()

    mapConfig.browserAk = 'test-ak'
    const on = render(<LcMap report={BASE} />)
    await waitFor(() => expect(modeOf(on.container, '[data-lc-mode]')).toBeTruthy())
    const declared = modeOf(on.container, '[data-lc-mode]')
    expect(declared, '两档报同一个值 ⇒ "在哪一档"这把尺失效，e2e 会静默走错分支').not.toBe('fallback')
    expect(declared).toBe('live')
  })
})

/**
 * `data-lc-blindspot` 的消费者搬到这里，是从 e2e 里搬出来的：那条 e2e 判据 10-07 实测两次被
 * **环境**翻脸（同一条用例一会儿 fallback 一会儿 live、甚至同页两个实例不同档），
 * 而 fallback 在 jsdom 里是确定的 ⇒ 归位到能确定复算的地方。
 * ⚠️ 这里刻意不断"恰好 1 枚"这种与夹具挂钩的数：写成 1 会在报告多一处盲区时红，而那不该红。
 */
describe('降级画布的盲区钩子 · 有名字才能被点名', () => {
  it('一处盲区 ⇒ 一枚 `data-lc-blindspot`，值就是报告里那条的 id', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={ONE} />)
    await waitFor(() => expect(container.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
    expect([...container.querySelectorAll('[data-lc-blindspot]')]
      .map((n) => n.getAttribute('data-lc-blindspot'))).toEqual(['bs-钩子-1'])
  })

  it('正对照：两处盲区 ⇒ 两枚（一盘一环）。没有这条，上面那条"1 枚"可能只是恒 1 的摆设', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={TWO} />)
    await waitFor(() => expect(container.querySelectorAll('[data-lc-blindspot]').length).toBe(2))
    expect([...container.querySelectorAll('[data-lc-blindspot]')]
      .map((n) => n.getAttribute('data-lc-blindspot'))).toEqual(['bs-钩子-1', 'bs-钩子-2'])
  })

  it('反面半边：报告没有盲区 ⇒ 一枚都不该有（否则"两处两枚"可能只是 DOM 里到处都在贴）', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<LcMap report={BASE} />)
    await waitFor(() => expect(container.querySelector('svg[aria-label*="画布"]')).toBeTruthy())
    expect(container.querySelectorAll('[data-lc-blindspot]')).toHaveLength(0)
  })
})
