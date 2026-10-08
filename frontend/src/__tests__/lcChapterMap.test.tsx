// @vitest-environment jsdom
/**
 * 分章局部地图（nar-3）的渲染契约。
 *
 * 屏上那五个失效模式各有对应的一条，都不是"看着有没有"的形容词：
 *  ① 静态图**不参与懒挂载** ⇒ 首屏 DOM 里就该在场。将来谁给它加 `useLazyInView`，
 *     在 jsdom（无 IntersectionObserver）里会退化成永不出现的骨架 —— 本仓 10-05 为同类
 *     坑写过判据，这条是同一课的续篇。
 *  ② 报告页的地图实例计数**不许被它抬高**：`LcMap` 仍是 3 个（主图／局部图／第三屏），
 *     `[data-lc-layers]` 仍是 3 枚 —— 那是「两档图层集合相等」那条判据取申报的抓手，
 *     分章图若也贴，`lcLayerRoster` 的 `querySelector` 会取到错的那一枚。
 *  ③ 灰化 ≠ 删点 ⇒ 焦点章图上"压淡的 ＋ 实色的"必须等于同一份载荷在主图里画的点位数。
 *  ④ 分享态粒度不许变粗也不许变细：8 类点位一张不少，盲区走面积等价圆，
 *     精确经纬度与 `bs-` 那类标识不进图注与 `<title>`（对照 `lcMapDesensitize` 的 PRECISE 清单）。
 *  ⑤ 图注整句来自后端 `map_focus.title`，且**绝不**用「局部视图：」开头 ——
 *     那个前缀是三处 strict 选择器的靶子（jsdom 与两份 e2e 各一处），整页只许出现一次。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import LifeCircleReportView from '../components/lifecircle/LifeCircleReportView'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import { poiRenderSet } from '../lib/livingCircle'
import type { LivingCircleReport, Report } from '../types'

vi.mock('../lib/bmap', () => ({
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => { throw new Error('测试内不应注入 BMapGL') },
  geolocateMe: async () => null,
}))
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => vi.fn() }
})
vi.mock('../components/VChart', () => ({ VChart: () => <div data-testid="mock-chart" /> }))

const CHIP = '地图降级 · 静态画布（无 AK / 离线）'
/** 分章图的 accessible name 后缀（唯一、由章名派生）。 */
const SUFFIX = ' · 本章设施分布'

const mockReport = (id: string): Report => getLivingCircleReportMock(id) as unknown as Report
const lcOf = (id: string): LivingCircleReport =>
  (getLivingCircleReportMock(id) as unknown as { living_circle: LivingCircleReport }).living_circle

async function open(id: string) {
  const view = render(
    <MemoryRouter initialEntries={[`/report/${id}`]}>
      <LifeCircleReportView report={mockReport(id)} />
    </MemoryRouter>,
  )
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
  return view
}

const chapterMaps = () => screen.getAllByRole('img', { name: new RegExp(`${SUFFIX}$`) })

beforeEach(() => {
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {} unobserve() {} disconnect() {}
    }
  }
})
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/') })

describe('nar-3 分章局部地图', () => {
  it('前置自证：ev2 有六个章发焦点、kaili 少一个（盲区清零走缺席态）', () => {
    expect(mockReport('lc-kaili-ev2').sections.filter((s) => s.map_focus).map((s) => s.id)).toEqual(
      ['medical', 'education', 'market', 'elderly', 'isochrone', 'blindspot'])
    expect(mockReport('lc-kaili').sections.filter((s) => s.map_focus).map((s) => s.id)).toEqual(
      ['medical', 'education', 'market', 'elderly', 'isochrone'])
    for (const s of mockReport('lc-kaili-ev2').sections) {
      if (!s.map_focus) expect(['overview', 'conclusion'], `${s.id} 不在场却没发焦点`).toContain(s.id)
    }
  })

  it('① 首屏就在 DOM：没有 IntersectionObserver 也不会退化成永不出现的骨架', async () => {
    await open('lc-kaili-ev2')
    expect(typeof IntersectionObserver, '本用例的前提是 jsdom 确实不带 IO').toBe('undefined')
    expect(chapterMaps()).toHaveLength(6)
    expect(document.body.textContent).not.toContain('滚动到此处加载')
  })

  it('② 不抬高地图实例计数：LcMap 仍 3 个、逐层申报仍 3 枚', async () => {
    await open('lc-kaili-ev2')
    expect(screen.queryAllByText(CHIP).length, '分章图若搬进降级角标，这个计数就涨了').toBe(3)
    expect(document.querySelectorAll('[data-lc-mode]').length, '模式申报只属于 LcMap 的三棵树').toBe(3)
    expect(document.querySelectorAll('[data-lc-layers]').length, '逐层申报只属于 LcMap 的三棵树').toBe(3)
    expect(document.querySelectorAll('[data-lc-map]').length, 'data-lc-map 仍只认 live 容器').toBe(0)
  })

  it('② 的机理侧：分章图组件不实例化 LcMap（零 GL、零额外 map-config fetch）', () => {
    const src = readFileSync(join(process.cwd(), 'src', 'components', 'lifecircle', 'LifeCircleReportView.tsx'), 'utf8')
    // 注意别给 split 传 limit=1 —— 那只会返回**前半段**，取 [1] 恒为 undefined（本条第一版就这么空过）。
    const body = src.split('function LcChapterMap')[1]
    expect(body, 'LcChapterMap 找不到 ⇒ 本条失去对象').toBeTruthy()
    // 作用域按"到下一个顶层 function 之前"切，不按花括号猜（第一版按 `\n}` 切，
    // 在带类型字面量的签名上提前断开，于是 <LcCanvasBackdrop /> 那条是假红）。
    const scope = body!.split('\nfunction ')[0]
    expect(scope, '分章图里出现 <LcMap ⇒ 每章多开一个 GL 实例，P0-7 回到原点').not.toContain('<LcMap')
    expect(scope).toContain('<LcCanvasBackdrop />')
  })

  it('③ 灰化不减点：压淡的 ＋ 实色的 == 主图同一份点集', async () => {
    await open('lc-kaili-ev2')
    const medical = screen.getByRole('img', { name: `医疗配置${SUFFIX}` })
    const expected = poiRenderSet(lcOf('lc-kaili-ev2').poi.points).reps.length
    const opacity = [...medical.querySelectorAll('circle')].map((c) => c.getAttribute('opacity'))
    const solid = opacity.filter((o) => o === '0.92').length
    const dimmed = opacity.filter((o) => o === '0.16').length
    expect(solid, '焦点类目一个实色点都没有 ⇒ 灰化判据取错了键，整张图都淡下去没人看得出')
      .toBeGreaterThan(0)
    expect(solid + dimmed, '实色＋压淡必须正好等于同一份载荷的点位（中心标记与盲区点都不带这两个 opacity）')
      .toBe(expected)
    expect(dimmed, '医疗章图里没有 0.16 的压淡点 ⇒ 焦点没生效').toBeGreaterThan(0)
  })

  it('⑤ 图注整句来自后端字段，且「局部视图：」前缀整页仍只出现一次', async () => {
    await open('lc-kaili-ev2')
    for (const sec of mockReport('lc-kaili-ev2').sections.filter((s) => s.map_focus)) {
      const title = sec.map_focus!.title
      expect(document.body.textContent, `${sec.id} 章没把后端那句图注印出来`).toContain(title)
      expect(title.startsWith('局部视图：'), `${sec.id} 的图注用了 strict 选择器的靶子前缀`).toBe(false)
    }
    const caps = [...document.querySelectorAll('div')].filter((d) => /^局部视图：/.test(d.textContent ?? ''))
    expect(caps.length, '整页「局部视图：」图注应当恰一处（台账配对那张）').toBe(1)
  })

  it('等时圈章那张只作打印替身：屏上隐藏、别章不隐藏（本章已有那张交互地图）', async () => {
    await open('lc-kaili-ev2')
    // svg 在「槽」里，槽在「卡」上 —— hidden print:block 是卡在槽的外层，所以往上两层。
    const card = (name: string) => (screen.getByRole('img', { name }).parentElement!.parentElement as HTMLElement)
    expect(card(`可达性与等时圈${SUFFIX}`).className, '等时圈章的静态图必须 hidden print:block')
      .toContain('print:block')
    expect(card(`医疗配置${SUFFIX}`).className).not.toContain('print:block')
  })

  it('④ 分享态：八类点位一张不少、盲区换成概略圆，精确标识不进图注与 <title>', async () => {
    window.history.replaceState({}, '', '/report/lc-1?share=1')
    await open('lc-kaili-ev2')
    const blind = screen.getByRole('img', { name: `服务盲区诊断${SUFFIX}` })
    const expected = poiRenderSet(lcOf('lc-kaili-ev2').poi.points).reps.length
    const opacity = [...blind.querySelectorAll('circle')].map((c) => c.getAttribute('opacity'))
    expect(opacity.filter((o) => o === '0.16' || o === '0.92').length)
      .toBeGreaterThanOrEqual(expected)
    expect(blind.querySelector('ellipse'), '分享态盲区应当换成面积等价圆').toBeTruthy()
    const flat = blind.outerHTML
    expect(flat).not.toMatch(/"bs-/)
    expect(flat, '精确多边形（5 4 虚线）在分享态不该出现').not.toContain('stroke-dasharray="5 4"')
    expect(flat).not.toMatch(/缺口\s*-?\d/)
  })
})
