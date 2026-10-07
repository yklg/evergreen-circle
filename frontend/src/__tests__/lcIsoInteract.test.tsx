// @vitest-environment jsdom
/**
 * C1–C8 等时圈/盲区/补点交互 · 契约测试（架构审查 R1–R6 + 技术评审 S1–S3 的测试化）。
 *
 * ## 被守护的契约
 *
 * | # | 契约 | 来源 |
 * |---|---|---|
 * | A | 悬停锁仲裁（成对）：锁持有期间容器热力命中让位；释放后恢复——若只有「锁下不显示」而无「释放后显示」，分不清「被仲裁」还是「热力命中根本坏了」 | 审查 R2 |
 * | B | movestart 清锁：拖图后锁不残留（像素已随视图移动，锁指向的目标失真） | R2 兜底 |
 * | C | 重绘清交互态：报告重绘摘掉悬停中的覆盖物 → mouseout 永不派发 → 锁/卡/服务圈必须就地复位（S1：不复位 = 热力 tooltip 静默死亡） | 技术评审 S1 |
 * | D | 圈线悬停 = 命中线事件 → tooltip + onIsoHover 恰好 over/out 各一次（mousemove 高频不触发 setState） | R6 |
 * | E | 点击圈 → React 固定卡；map click 空白关卡带 100ms 同源守卫（overlay click 连带派发不秒关） | R1/S2 |
 * | F | 盲区中心/补点 Marker 无原生 title（防「DOM 浮层 + 原生气泡」双浮层）；POI 的原生 title 保留 | R3 |
 * | G | 补点 click → 1km 服务圈，替换语义 = 先清后画；空白点击清除 | C6/G4 |
 * | H | Esc 三守卫 + 层级（关卡→清圈→复位）；unmount 移除 window 监听 | R5 |
 *
 * ## 已知盲区（本文件覆盖不到，防「测试全绿 = 全对」错觉）
 * - GL 遮罩/瓦片层的真实遮挡关系、真机手感（悬停跟手性、tooltip 位置观感）仍须人工验收。
 *
 * ## 已由真机 spike 闭环的两条（2026-09-23，自建 GL + 真实鼠标注入，勿再当悬案）
 * - ✅ **透明描边可拾取**：weight 14 + strokeOpacity 0.01（以及 0）都能触发 mouseover/mousemove/click
 *   ⇒ C1 命中层方案成立（原先担心 0.01 不可拾取需提到 0.05，实测无需）。
 * - ✅ **overlay click 会连带派发 map click**（实测同一次点击 map click 监听被触发 1 次），
 *   且 Polyline/Polygon 事件的 `domEvent` 实测为 **undefined**（`domEvent.stopPropagation()` 掐断不生效）
 *   ⇒ `onBlankClick` 的 **100ms 时间戳守卫是唯一有效的防秒关防线**，E 用例正守住它（NC 注入可红）。
 * - ✅ 另记：**面填充同样可拾取且与上层命中线同时触发** ⇒ 等时圈 Polygon 不得挂 hover（见 LcMap 注释）。
 *
 * ## 测试写法纪律（本文件实测踩过的坑）
 * - **覆盖物事件一律走 `fireOverlay`/`fireMap`（内部 `act()`）**：`setIsoCard` 等 state 更新若在 act 外
 *   派发，state 已变但 DOM 未 flush，`cardOf(view)` 读到旧树 → 卡片断言全 null（假红）。
 * - **不可用文案子串认 Marker**：`blindTitle` 自带「建议补药店·P1」（LcMap:105），用「补药店」找补点
 *   会命中盲区中心点 → 拿盲区浮层断言补点文案。补点 Marker = 无 title Marker 的**最后一个**（创建序）。
 * - **基线取构建参数（Polygon opts），不取被测函数输出**：`LC_ISO_COLORS` alpha 由深到浅
 *   `[0.55, 0.34, 0.20, 0.10]`，15min = 升序 index 2 = **0.20**（0.34 是 10min 档）。
 *   高亮期望 = `min(0.65, base+0.15)`，并配「增亮/淡化」关系断言兜底。
 *
 * ## mock 说明
 * vi.hoisted 工厂内聚全部桩类（Polygon/Polyline/Circle 带 listeners + 样式方法；Map 带
 * addOverlay→setMap 契约，lcHeatField:79 的教训）。与 lcHeatField/lcMapDrag 的 mock 是
 * 三胞胎——跨文件收敛成共享 helper 列入后续重构（测试评估 B-0），本文件先行内聚。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { assertBasemapStylesSound, resetStyleCalls } from './helpers/bmapGLFake'
import { waitDrawn } from './helpers/waitDrawn'

/* ── 测试盲区注入：kaili 无盲区（实测 blindspots:0），C5/C6 用手工构造的最小盲区 ── */
const TEST_BLIND = {
  id: 'bs-9',
  center: [107.95, 26.57],
  radius_m: 1000,
  missing_facilities: ['药店'],
  polygon: {
    type: 'Polygon',
    coordinates: [[[107.94, 26.56], [107.96, 26.56], [107.96, 26.58], [107.94, 26.58], [107.94, 26.56]]],
  },
  severity: 'light',
  gap_score: 0.21,
  reach: { real_walk_min: 5, isochrone_based: true },
  affected: { sampling_sites: 5, estimated_residents: 320, provenance: 'fixture' },
  fixes: [{ facility: '药店', strategy: 'mobile_service', priority: 1, point: [107.95, 26.57], served: 5 }],
}
const REPORT = {
  ...kaili,
  blindspots: [TEST_BLIND],
} as unknown as LivingCircleReport

/* ── fake BMapGL：vi.hoisted 工厂（mock 工厂只能引用 hoisted 值与 import）── */
const fb = vi.hoisted(() => {
  type Ev = { pixel?: { x: number; y: number }; latLng?: { lng: number; lat: number }; domEvent?: { stopPropagation?: () => void } }
  /**
   * `recordStyle` 由 mock 工厂注入 `helpers/bmapGLFake` 的 `recordStyleCall`。
   * 本文件的 Map 带富行为（事件回放、样式覆写、setMap 桥接），不便 extends 基类，
   * 但 `setMapStyleV2` **不得**写成空桩 —— 那会让本文件对底图样式回归永久免疫。
   */
  function makeNamespace(
    h: {
      maps: unknown[]
      polys: unknown[]
      polylines: unknown[]
      circles: unknown[]
      markers: unknown[]
      removed: unknown[]
    },
    recordStyle: (style: unknown) => void,
  ) {
    /* ⚠️ tsconfig 开了 erasableSyntaxOnly：类字段必须显式声明+赋值，禁 parameter properties */
    class Point {
      lng: number
      lat: number
      constructor(lng: number, lat: number) {
        this.lng = lng
        this.lat = lat
      }
    }
    class Size {
      width: number
      height: number
      constructor(width: number, height: number) {
        this.width = width
        this.height = height
      }
    }
    class Icon {
      constructor(..._: unknown[]) {}
    }
    class InfoWindow {
      constructor(..._: unknown[]) {}
    }
    /** 事件 + 样式基类：GL 覆盖物事件是 mouseover/mouseout（无 enter/leave，见 bmap.ts 注释） */
    class Base {
      listeners: Record<string, ((e: Ev) => void)[]> = {}
      styles: Record<string, number> = {}
      addEventListener(type: string, fn: (e: Ev) => void) {
        ;(this.listeners[type] ??= []).push(fn)
      }
      removeEventListener(type: string, fn: (e: Ev) => void) {
        this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)
      }
      fire(type: string, e: Ev = {}) {
        for (const fn of this.listeners[type] ?? []) fn(e)
      }
      setStrokeWeight(w: number) {
        this.styles.strokeWeight = w
      }
      setStrokeOpacity(o: number) {
        this.styles.strokeOpacity = o
      }
      setFillOpacity(o: number) {
        this.styles.fillOpacity = o
      }
    }
    class Polygon extends Base {
      points: unknown
      opts: Record<string, unknown>
      constructor(points: unknown, opts: Record<string, unknown> = {}) {
        super()
        this.points = points
        this.opts = opts
        h.polys.push(this)
      }
    }
    class Polyline extends Base {
      points: unknown
      opts: Record<string, unknown>
      constructor(points: unknown, opts: Record<string, unknown> = {}) {
        super()
        this.points = points
        this.opts = opts
        h.polylines.push(this)
      }
    }
    class Circle extends Base {
      center: unknown
      radius: number
      opts: Record<string, unknown>
      constructor(center: unknown, radius: number, opts: Record<string, unknown> = {}) {
        super()
        this.center = center
        this.radius = radius
        this.opts = opts
        h.circles.push(this)
      }
    }
    class Marker extends Base {
      point: { lng: number; lat: number }
      opts: Record<string, unknown>
      getPosition = () => this.point
      constructor(point: { lng: number; lat: number }, opts: Record<string, unknown> = {}) {
        super()
        this.point = point
        this.opts = opts
        h.markers.push(this)
      }
    }
    class Label {
      text: string
      opts: Record<string, unknown>
      constructor(text: string, opts: Record<string, unknown> = {}) {
        this.text = text
        this.opts = opts
      }
    }
    class Map {
      listeners: Record<string, ((...a: unknown[]) => void)[]> = {}
      added: unknown[] = []
      zoom = 15
      center = { lng: 107.97, lat: 26.57 }
      constructor(..._: unknown[]) {
        h.maps.push(this)
      }
      enableScrollWheelZoom() {}
      setMapStyleV2(style: unknown) {
        recordStyle(style)
      }
      /* BMapGL 契约：addOverlay → overlay.setMap(map)（lcHeatField:79——桩缺这步 canvas 永不创建） */
      addOverlay(o: { setMap?: (m: unknown) => void }) {
        o.setMap?.(this)
        this.added.push(o)
      }
      removeOverlay(o: unknown) {
        h.removed.push(o)
      }
      openInfoWindow() {}
      setViewport() {}
      /** GL 的尺寸监听开关（真 SDK 里 = `this._watchSize()`）。本文件不测这条链，
       *  留 inert 方法只为让生产码能跑；**记账版**在 `helpers/bmapGLFake.ts`，
       *  由 `lcMapResizeGuard.test.tsx` 负责钉。 */
      resize() {}
      centerAndZoom(c: { lng: number; lat: number }, z: number) {
        this.center = c
        this.zoom = z
      }
      getCenter() {
        return this.center
      }
      getZoom() {
        return this.zoom
      }
      flyTo(c: { lng: number; lat: number }, z: number) {
        this.center = c
        this.zoom = z
      }
      getContainer() {
        return (document.querySelector('[data-lc-map="true"]') as HTMLElement | null) ?? document.createElement('div')
      }
      pointToPixel(p: { lng: number; lat: number }) {
        return { x: p.lng * 1000, y: p.lat * 1000 }
      }
      addEventListener(type: string, fn: (...a: unknown[]) => void) {
        ;(this.listeners[type] ??= []).push(fn)
      }
      removeEventListener(type: string, fn: (...a: unknown[]) => void) {
        this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)
      }
      fireMap(type: string, ...a: unknown[]) {
        for (const fn of this.listeners[type] ?? []) fn(...a)
      }
    }
    return { Point, Size, Icon, InfoWindow, Polygon, Polyline, Circle, Marker, Label, Map }
  }
  return {
    makeNamespace,
    h: { maps: [], polys: [], polylines: [], circles: [], markers: [], removed: [] } as Record<string, unknown[]>,
  }
})

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  const NS = fb.makeNamespace(fb.h as never, H.recordStyleCall)
  return H.fakeBMapModule(NS)
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

/** jsdom 无布局：容器伪造 800×600（onContainerMove rect 守卫 :327 显式拒绝 0×0） */
function fakeLayout(el: HTMLElement) {
  Object.defineProperty(el, 'clientWidth', { value: 800, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: 600, configurable: true })
}

async function mountMap(props: Record<string, unknown> = {}) {
  const view = render(<LcMap report={REPORT} {...props} />)
  const mapEl = view.container.querySelector('[data-lc-map="true"]') as HTMLElement
  fakeLayout(mapEl)
  vi.spyOn(mapEl, 'getBoundingClientRect').mockReturnValue({
    left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}),
  })
  /* 只等"地图建出来"不够：本文件的取物函数按**创建序**下标（`hit(1)` 取第 2 条线、`ring(4)` 取
     第 5 个面、`noTitle().at(-1)` 取补点 Marker），而那些是等时圈绘制 effect 稍后才建的覆盖物。
     10-07 加压复跑（两个全量并发）时 `› C` 报 `Cannot read properties of undefined (reading 'fire')`
     —— 机器慢一步，下标就落在还没建出来的数组位置上，红的是抢 CPU 的顺序而不是代码。
     这些**隐藏前提**统一走 `waitDrawn`（task 23：全仓只有这一颗等待出口），数字与用例的下标同源。 */
  await waitDrawn({ maps: 1, polylines: 2, polys: 5, markers: 2 }, fb.h)
  return { mapEl, view }
}

const tipOf = (view: ReturnType<typeof render>) =>
  view.container.querySelector('[role="status"]') as HTMLElement
const cardOf = (view: ReturnType<typeof render>) =>
  view.container.querySelector('[data-lc-iso-card="true"]')

/** 命中线/多边形按 add 顺序：ramp reverse → 20min(0) / 15min(1) / 10min(2) / 5min(3) */
const hit = (i: number) => fb.h.polylines[i] as { fire: (t: string, e?: unknown) => void; styles: Record<string, number> }
const ring = (i: number) =>
  fb.h.polys[i] as { styles: Record<string, number>; opts: Record<string, unknown>; fire: (t: string, e?: unknown) => void }

/** 热力点 0（kaili sampling.points[0]）的容器投影像素坐标 */
const HEAT_PX = { clientX: 107950.69, clientY: 26573.4 }

/* ⚠️ 覆盖物事件会直接改 React state（卡片/图例行）——必须在 act() 内派发，
   否则 state 已更新但 DOM 未 flush，断言看到的是旧树（实测：卡片断言全 null）。
   只改 ref / 直改 DOM 的事件（圈的 mouseover/mousemove/mouseout）本不强制，为免歧义一律走同一入口。 */
const fireOverlay = (
  o: { fire: (t: string, e?: unknown) => void },
  t: string,
  e?: unknown,
) => act(() => { o.fire(t, e) })
const fireMap = (t: string) =>
  act(() => { (fb.h.maps[0] as { fireMap: (t: string) => void }).fireMap(t) })

beforeEach(() => {
  for (const key of Object.keys(fb.h)) fb.h[key].length = 0
  resetStyleCalls()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LcMap 交互系列（C1–C8 契约）', () => {
  it('A 成对：锁持有 → 热力浮层让位；释放 → 恢复（R2 仲裁不吞噬既有能力）', async () => {
    const { mapEl, view } = await mountMap()
    const tip = tipOf(view)
    fireOverlay(hit(1), 'mouseover') // 15min 命中线 → lock='ring'
    fireEvent.mouseMove(mapEl, HEAT_PX)
    expect(tip.style.display).toBe('none') // 锁下热力让位
    fireOverlay(hit(1), 'mouseout') // 释放
    fireEvent.mouseMove(mapEl, HEAT_PX)
    expect(tip.style.display).toBe('block') // 释放后恢复（成对断言的另一半）
    expect(tip.textContent).toBe('0 号采样点 · 步行 61.1min')
  })

  it('B：movestart 清锁（拖图后锁不残留）', async () => {
    const { mapEl, view } = await mountMap()
    const tip = tipOf(view)
    fireOverlay(hit(1), 'mouseover')
    fireMap('movestart')
    fireEvent.mouseMove(mapEl, HEAT_PX)
    expect(tip.style.display).toBe('block') // 锁已被 movestart 清掉 → 热力可命中
  })

  it('D：圈线悬停浮层 + 高亮 + C8 回调恰好 over/out 各一次（R6 哨兵）', async () => {
    const onIsoHover = vi.fn()
    const { view } = await mountMap({ onIsoHover })
    const tip = tipOf(view)
    const self = ring(1) // 15min（绘制序：reverse(5,10,15,20) → 20/15/10/5）
    const other = ring(0) // 20min
    /* 基线取自**构建参数**（Polygon opts，夹具字面量）而非被测函数输出：
       LC_ISO_COLORS 的 alpha 由深到浅 [0.30, 0.20, 0.12, 0.06]，
       15min = ramp 升序 index 2 → 0.12；20min = index 3 → 0.06。
       （先前把 15min 当 0.34 与 10min 档串了，才误算成 0.49。） */
    const baseSelf = Number(self.opts.fillOpacity)
    const baseOther = Number(other.opts.fillOpacity)
    expect(baseSelf).toBeCloseTo(0.12, 5)
    expect(baseOther).toBeCloseTo(0.06, 5)
    fireOverlay(hit(1), 'mouseover')
    fireOverlay(hit(1), 'mousemove', { pixel: { x: 12, y: 34 } })
    expect(tip.style.display).toBe('block')
    expect(tip.textContent).toContain('15min 等时圈 · 面积')
    // C8：mouseover 恰好一次
    expect(onIsoHover).toHaveBeenCalledTimes(1)
    expect(onIsoHover).toHaveBeenNthCalledWith(1, 15)
    // 高亮（预览 setHighlight 同口径）：本圈加粗 3.5 + 填充 +0.15；其余圈淡化 ×0.3 / 描边 0.35
    expect(self.styles.strokeWeight).toBe(3.5)
    expect(self.styles.strokeOpacity).toBe(1)
    expect(self.styles.fillOpacity).toBeCloseTo(Math.min(0.65, baseSelf + 0.15), 5) // 0.27
    expect(self.styles.fillOpacity).toBeGreaterThan(baseSelf) // 关系断言：确实增亮
    expect(other.styles.strokeWeight).toBe(1.5)
    expect(other.styles.strokeOpacity).toBe(0.35)
    expect(other.styles.fillOpacity).toBeCloseTo(baseOther * 0.3, 5) // 0.018
    expect(other.styles.fillOpacity).toBeLessThan(baseOther) // 关系断言：确实淡化
    // R6 负向哨兵：mousemove ×5 不增加 setState 回调
    for (let i = 0; i < 5; i++) fireOverlay(hit(1), 'mousemove', { pixel: { x: 12 + i, y: 34 } })
    expect(onIsoHover).toHaveBeenCalledTimes(1)
    // 离开：复原到**构建值**（不是「另一个常量」）+ 回调 null
    fireOverlay(hit(1), 'mouseout')
    expect(onIsoHover).toHaveBeenCalledTimes(2)
    expect(onIsoHover).toHaveBeenNthCalledWith(2, null)
    expect(tip.style.display).toBe('none')
    expect(self.styles.strokeWeight).toBe(1.5)
    expect(self.styles.strokeOpacity).toBe(1)
    expect(self.styles.fillOpacity).toBeCloseTo(baseSelf, 5)
    expect(other.styles.strokeOpacity).toBe(1)
    expect(other.styles.fillOpacity).toBeCloseTo(baseOther, 5)
  })

  it('E：点击圈 → 固定卡；map click 空白关卡（100ms 同源守卫，S2）', async () => {
    const { view } = await mountMap()
    const stopSpy = vi.fn()
    /* 时间改由本用例自己拨。生产那颗守卫读 `performance.now()`（`LcMap.tsx:1102`），而"开卡"与
       "同一次点击连带派发的 map click"之间只隔着几条同步断言 —— 平时差 ≈ 0ms，但机器被抢占时
       两句语句之间真的能过去 100ms，于是产品按文档把关卡掉、断言红。10-07 实测：同一份**干净树**
       并发跑两个全量，HEAD 与远端基线红在**同一条**用例、单跑 ×3 全绿 ⇒ 这条判据量的是"谁抢到 CPU"。
       把时间做成显式输入后，红不红只取决于代码。（`afterEach` 有 `vi.restoreAllMocks()`，桩不漏。） */
    let clock = 1_000_000
    vi.spyOn(performance, 'now').mockImplementation(() => clock)
    fireOverlay(hit(1), 'click', { domEvent: { stopPropagation: stopSpy } })
    const card = cardOf(view)
    expect(card).not.toBeNull()
    expect(card!.textContent).toContain('15min 等时圈')
    expect(card!.textContent).toContain('全域可达采样（≤20min）')
    expect(stopSpy).toHaveBeenCalled() // S2 防御①：构造出 domEvent 时确实调用掐断（真机 Polyline 的 domEvent 实测 undefined ⇒ 此分支不生效；主防线是下面的 100ms 守卫）
    // 同一击的连带派发：把时钟拨在守卫窗口**之内**（窗口大小由生产说了算，这里只保证在里面）→ 不关卡
    clock += 20
    fireMap('click')
    expect(cardOf(view)).not.toBeNull()
    // 越过守卫窗口的真空白点击 → 关卡。两条半边互为正对照：没有这条，上面那个"不关"可能只是关卡功能压根没接上
    clock += 150
    fireMap('click')
    expect(cardOf(view)).toBeNull()
  })

  it('F：盲区中心/补点无原生 title（R3）；盲区/补点悬停浮层与卡（C5）', async () => {
    const onBlindHover = vi.fn()
    const { view } = await mountMap({ onBlindHover })
    const tip = tipOf(view)
    // R3：不存在任何带原生 title 且文案来自盲区（blindTitle 含 bs-9）的 Marker；POI 的 title 不受影响
    const titled = fb.h.markers.filter((m) => typeof (m as { opts: Record<string, unknown> }).opts.title === 'string')
    expect(titled.length).toBeGreaterThan(0) // POI Marker 保留原生 title
    for (const m of titled) expect(String((m as { opts: { title: string } }).opts.title)).not.toContain('bs-9')
    // 盲区多边形 = 第 5 个 Polygon（4 圈之后）；悬停 → 浮层 + 严重度回调
    const blind = ring(4)
    fireOverlay(blind, 'mouseover')
    fireOverlay(blind, 'mousemove', { pixel: { x: 5, y: 6 } })
    expect(tip.textContent).toContain('bs-9')
    expect(onBlindHover).toHaveBeenCalledTimes(1)
    expect(onBlindHover).toHaveBeenCalledWith('light')
    /* 补点 Marker = 无原生 title 的 Marker 中**最后一个**（创建序：盲区多边形 → 中心点 → 补点）。
       ⚠️ 不可用「浮层含『补药店』」来认补点：blindTitle 自己就带「建议补药店·P1」（LcMap:105），
       那样会认到盲区中心点、拿盲区浮层去断言补点文案（实测就是这么挂的）。 */
    const noTitle = fb.h.markers.filter((m) => (m as { opts: Record<string, unknown> }).opts.title === undefined)
    expect(noTitle.length).toBeGreaterThanOrEqual(2) // 盲区中心 + 补点
    const fix = noTitle.at(-1) as { fire: (t: string, e?: unknown) => void }
    fireOverlay(fix, 'mouseover')
    fireOverlay(fix, 'mousemove', { pixel: { x: 7, y: 8 } })
    expect(tip.textContent).toContain('流动服务') // 补点专属（策略名），盲区文案里没有
    expect(tip.textContent).toContain('覆盖 5 格')
    expect(onBlindHover).toHaveBeenCalledTimes(1) // 负向：补点不冒充盲区严重度（否则图例行会乱跳）
    // 点击补点 → 服务圈 + 处方卡（G）
    fireOverlay(fix, 'click')
    expect(fb.h.circles.length).toBe(1)
    expect((fb.h.circles[0] as { radius: number }).radius).toBe(1000)
    expect(cardOf(view)!.textContent).toContain('补点处方')
    fireOverlay(blind, 'mouseout')
    expect(onBlindHover).toHaveBeenCalledTimes(2)
    expect(onBlindHover).toHaveBeenLastCalledWith(null)
  })

  it('G：服务圈替换语义 = 先清后画；空白点击清除（C6/G4）', async () => {
    const { view } = await mountMap()
    const noTitle = () => fb.h.markers.filter((m) => (m as { opts: Record<string, unknown> }).opts.title === undefined)
    const fix = noTitle().at(-1) as { fire: (t: string, e?: unknown) => void }
    fireOverlay(fix, 'click')
    fireOverlay(fix, 'click') // 同点再击 → 先清旧圈再画新圈（替换）
    expect(fb.h.circles.length).toBe(2) // 两个实例创建过
    expect(fb.h.removed.length).toBe(1) // 旧圈被 removeOverlay
    await new Promise((r) => setTimeout(r, 130))
    fireMap('click')
    expect(fb.h.removed.length).toBe(2) // 空白点击 → 服务圈清除
    expect(cardOf(view)).toBeNull()
  })

  it('C：报告重绘 → 交互态就地复位（S1：锁/卡/服务圈），热力立即恢复', async () => {
    const { mapEl, view } = await mountMap()
    fireOverlay(hit(1), 'mouseover') // 锁
    const noTitle = () => fb.h.markers.filter((m) => (m as { opts: Record<string, unknown> }).opts.title === undefined)
    fireOverlay(noTitle().at(-1) as { fire: (t: string, e?: unknown) => void }, 'click') // 服务圈 + 卡
    expect(cardOf(view)).not.toBeNull()
    view.rerender(
      <LcMap report={{ ...REPORT, scene: { ...REPORT.scene, name: '重绘后的社区' } } as LivingCircleReport} />,
    )
    expect(cardOf(view)).toBeNull() // 卡被复位
    expect(fb.h.removed.length).toBeGreaterThanOrEqual(1) // 服务圈随重绘被摘
    const tip = tipOf(view)
    fireEvent.mouseMove(mapEl, HEAT_PX)
    expect(tip.style.display).toBe('block') // 锁已清 → 热力立即命中（S1 的核心判据）
  })

  it('H：Esc 层级 + 可编辑聚焦守卫 + unmount 清理（R5）', async () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { view } = await mountMap()
    // 层级 1：卡开 → Esc 关卡
    fireOverlay(hit(1), 'click')
    expect(cardOf(view)).not.toBeNull()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(cardOf(view)).toBeNull()
    // 守卫：可编辑元素聚焦时 Esc 不劫持（先重新开卡，再在 input 上按 Esc）
    fireOverlay(hit(1), 'click')
    const input = document.createElement('input')
    view.container.appendChild(input)
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(cardOf(view)).not.toBeNull()
    input.blur()
    // unmount：window keydown 监听被移除（R5 守卫①）
    view.unmount()
    expect(removeSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
  })

  /* TC-R12：本文件的 `setMapStyleV2` 曾是空桩 ⇒ 底图样式怎么改这里都全绿。
     这条钉的是**眼睛本身**：样式必须真的被下发过且结构自洽。
     色值对不对不归本文件管（那是 roadContrast.test.ts 带锚点阈值的职责）。 */
  it('底图样式确实被下发且结构自洽（夹具眼睛哨兵，非空桩）', async () => {
    await mountMap()
    assertBasemapStylesSound()
  })
})
