/**
 * BMapGL 测试替身的**唯一出口**（TC-R12）。
 *
 * ## 为什么必须有这个文件
 *
 * `setMapStyleV2` 曾在本套件 5 份各自手写的 `class Map` 里出现 3 次**空桩**
 * （`lcIsoInteract` / `lcMapDrag` / `lcHeatField`）。空桩意味着：底图样式无论被改成什么，
 * 这三个文件永远全绿 —— 它们对样式回归**免疫**。而底图样式恰恰是「道路看不见」这类
 * 事故的现场（见 `lib/bmapStyle.ts` 文件头实测纪律）。
 *
 * 所以这里只统一**必须统一的那一件东西**：
 *   1. `setMapStyleV2` 的唯一实现 —— 必须记录入参，且在下发时就地做结构自检；
 *   2. 无行为分歧的值类（Point / Size / Icon / InfoWindow / Label / 简单 Polygon）。
 *
 * **不统一** `Map` / `Marker` 的行为分歧 —— 那些分歧是各文件测试意图的一部分
 * （投影倍率、`addOverlay` 是否桥接 `setMap`、容器取自何处），强行合并会把
 * 「一个万能替身」变成新的上帝对象。各文件 `extends BMapMapBase` 只覆写自己需要的那几个方法。
 *
 * ## 用法
 *
 * ```ts
 * vi.mock('../lib/bmap', async () => {
 *   const H = await import('./helpers/bmapGLFake')
 *   class Map extends H.BMapMapBase { /* 本文件特有的分歧 *\/ }
 *   return H.fakeBMapModule({ Map })
 * })
 * ```
 * 工厂内用 `await import` 而非顶层绑定，规避 `vi.mock` 被提升到 import 之前时
 * 外层变量尚未初始化的问题。断言侧直接顶层 `import { styleCalls }` 即可 ——
 * Vitest 按文件隔离模块图，两处解析到同一实例。
 */
import { expect } from 'vitest'

/** 一次 `setMapStyleV2` 的入参。百度官方语义：`styleId` 与 `styleJson` 互斥二选一。 */
export type BasemapStyleCall = { styleId?: string; styleJson?: unknown[] }

type StyleRule = { featureType?: unknown; elementType?: unknown; stylers?: unknown }

/** 全套件唯一的样式调用记录。`resetStyleCalls()` 由用例在 beforeEach 清空。 */
export const styleCalls: BasemapStyleCall[] = []

/** 下发时就地发现的结构性问题（不抛异常，避免污染被测行为断言；由显式断言函数收口）。 */
export const styleViolations: string[] = []

/** 各文件按需登记实例的注册表；具体装什么由覆写方决定。 */
export const instances: {
  maps: unknown[]
  markers: unknown[]
  polys: unknown[]
  polylines: unknown[]
  circles: unknown[]
  removed: unknown[]
} = { maps: [], markers: [], polys: [], polylines: [], circles: [], removed: [] }

/** `getMapConfig` 的受控替身：用例在 render 前改写这两个字段即可模拟后端下发差异。 */
export const mapConfig = { browserAk: 'test-ak', mapStyleId: '' }

export function resetStyleCalls(): void {
  styleCalls.length = 0
  styleViolations.length = 0
}

export function resetInstances(): void {
  for (const list of Object.values(instances)) list.length = 0
}

/** 最近一次下发的 styleJson（styleId 分支返回 undefined）。 */
export function lastStyleJson(): Record<string, unknown>[] | undefined {
  const call = styleCalls.at(-1)
  return call?.styleJson as Record<string, unknown>[] | undefined
}

/**
 * 结构自检：把「写了个非法结构、厂商静默忽略」这类与本次事故同形的失效，
 * 在替身层就地记下来。百度不发布 style-spec，所以这层只能验结构、验不了键名语义 ——
 * 键名有效性由真机探针产出的枚举清单把关（`src/dev/verifiedStyleKeys.ts`）。
 */
function auditStyleCall(call: BasemapStyleCall, nth: number): void {
  const tag = `第 ${nth} 次 setMapStyleV2`
  if (call.styleId !== undefined && call.styleJson !== undefined) {
    styleViolations.push(`${tag}：styleId 与 styleJson 同时下发（官方互斥二选一）`)
    return
  }
  if (call.styleId !== undefined) return
  const json = call.styleJson
  if (!Array.isArray(json)) {
    styleViolations.push(`${tag}：styleJson 缺失或不是数组`)
    return
  }
  json.forEach((raw, i) => {
    const rule = raw as StyleRule
    if (!rule || typeof rule !== 'object') {
      styleViolations.push(`${tag} #${i}：规则不是对象`)
      return
    }
    if (typeof rule.featureType !== 'string' || rule.featureType === '') {
      styleViolations.push(`${tag} #${i}：featureType 缺失或非法`)
    }
    if (typeof rule.elementType !== 'string' || rule.elementType === '') {
      styleViolations.push(`${tag} #${i}：elementType 缺失或非法`)
    }
    const st = rule.stylers
    if (!st || typeof st !== 'object') {
      styleViolations.push(`${tag} #${i}：stylers 缺失`)
      return
    }
    const s = st as Record<string, unknown>
    if (typeof s.color === 'string' && !/^#[0-9a-f]{6}$/i.test(s.color)) {
      styleViolations.push(`${tag} #${i}：color 不是 6 位 hex（${s.color}）`)
    }
    if (s.visibility !== undefined && s.visibility !== 'on' && s.visibility !== 'off') {
      styleViolations.push(`${tag} #${i}：visibility 只能是 on/off（${String(s.visibility)}）`)
    }
    if (s.color === undefined && s.visibility === undefined) {
      styleViolations.push(`${tag} #${i}：stylers 既无 color 也无 visibility —— 等于没写`)
    }
  })
}

/**
 * 底图样式下发的最低可观测性契约：**确实被调用过、且结构自洽**。
 *
 * 这条断言的意义是「把眼睛装上」：在它之前，3 个集成测试文件对样式改动完全无感。
 * 色值内容层面的对错不在这里 —— 那是 `roadContrast.test.ts` 的职责（有锚点阈值）。
 */
export function assertBasemapStylesSound(): void {
  expect(styleCalls.length, '未观测到任何 setMapStyleV2 下发 —— 底图样式链路断了').toBeGreaterThan(0)
  expect(styleViolations, `底图样式结构自检失败：\n${styleViolations.join('\n')}`).toEqual([])
}

/* ── 无分歧值类 ── */

type LngLat = { lng: number; lat: number }

export class BMapPoint implements LngLat {
  lng: number
  lat: number
  constructor(lng: number, lat: number) {
    this.lng = lng
    this.lat = lat
  }
}

export class BMapSize {
  w: number
  h: number
  constructor(w: number, h: number) {
    this.w = w
    this.h = h
  }
}

/** 记录构造入参：真 SDK 的这些类都带配置对象，替身留着便于「确实按预期构造」类断言。 */
export class BMapIcon {
  args: unknown[]
  constructor(...args: unknown[]) {
    this.args = args
  }
}

export class BMapInfoWindow {
  args: unknown[]
  constructor(...args: unknown[]) {
    this.args = args
  }
  open(): void {}
  close(): void {}
}

export class BMapLabel {
  text: string
  opts: Record<string, unknown>
  constructor(text: string, opts: Record<string, unknown> = {}) {
    this.text = text
    this.opts = opts
  }
}

/** 仅需「能构造、能存 opts」的文件用它；需要 listeners / setMap 回放的自行定义。 */
export class BMapPolygon {
  point: LngLat
  opts: Record<string, unknown>
  constructor(point: LngLat, opts: Record<string, unknown> = {}) {
    this.point = point
    this.opts = opts
    instances.polys.push(this)
  }
  getPosition = (): LngLat => this.point
}

/** 证据域图层（片 5）用的圆：形参按真 API 取 `(center, radius, opts)`，三样都留下供断言。
 *
 * 在此之前替身命名空间里**没有** `Circle` ⇒ 生产侧那句 `typeof bmap.Circle === 'function'`
 * 在 jsdom 里恒假，BMap 分支整块在测试面不可达（第十六轮评审 P1「BMap 分支零覆盖」）。
 * `instances.circles` 那枚注册表也是从这里开始才有主人。 */
export class BMapCircle {
  center: LngLat
  radius: number
  opts: Record<string, unknown>
  constructor(center: LngLat, radius: number, opts: Record<string, unknown> = {}) {
    this.center = center
    this.radius = radius
    this.opts = opts
    instances.circles.push(this)
  }
}

export class BMapMarker {
  point: LngLat
  opts: Record<string, unknown>
  constructor(point: LngLat, opts: Record<string, unknown> = {}) {
    this.point = point
    this.opts = opts
    instances.markers.push(this)
  }
  getPosition = (): LngLat => this.point
  /** 已注册的事件处理器；覆写方按需读取（`lcMapDrag` 靠 `listeners.dragend` 取中心标记）。 */
  handlers: Record<string, (...a: unknown[]) => unknown> = {}
  addEventListener(type: string, fn: (...a: unknown[]) => unknown): void {
    this.handlers[type] = fn
  }
}

/**
 * 记录一次样式下发。形参取 `unknown` 是为了能被 `vi.hoisted` 内的工厂注入
 * （那里 import 不到本模块的类型，只能按值传函数）。
 * 也供无法 `extends BMapMapBase` 的替身（如 `lcIsoInteract` 的富行为 Map）使用 ——
 * 保证「全套件只有一份记录逻辑」这条纪律不被绕开。
 */
export function recordStyleCall(style: unknown): void {
  const call = style as BasemapStyleCall
  auditStyleCall(call, styleCalls.length)
  styleCalls.push(call)
}

/* ── Map 基类：唯一一份 setMapStyleV2 ── */

/** 地图方法调用日志（方法名 + 入参），供「确实调用过」类断言使用。 */
export type MapCall = [method: string, args: unknown[]]

export class BMapMapBase {
  readonly calls: MapCall[] = []
  /**
   * 已注册的**地图级**事件处理器（`click` / `movestart` / `zoomstart` / `tilesloaded`）。
   *
   * 为什么要有它：本仓拿不到真实指针点击（第三方 SDK 不认合成事件，CDP 只能打元素中心，
   * 而地图中心恰被可拖的中心标记占着），所以"地图点选"这条链此前只能靠人工验收。
   * 有了注册表，`lcMapCellClick` 就能直接取到真 handler 并喂事件载荷。
   * 仍然 `log` —— 既有套件按 `calls` 断言过"确实订阅了"，摘掉会假红。
   */
  readonly handlers: Record<string, (...a: unknown[]) => unknown> = {}
  constructor(...args: unknown[]) {
    instances.maps.push(this)
    this.log('constructor', args)
  }
  protected log(method: string, args: unknown[]): void {
    this.calls.push([method, args])
  }
  /** 全套件唯一实现：记录 + 结构自检。覆写方**不得**把它改成空桩。 */
  setMapStyleV2(style: BasemapStyleCall): void {
    this.log('setMapStyleV2', [style])
    recordStyleCall(style)
  }
  enableScrollWheelZoom(): void {
    this.log('enableScrollWheelZoom', [])
  }
  addOverlay(...args: unknown[]): void {
    this.log('addOverlay', args)
  }
  removeOverlay(...args: unknown[]): void {
    this.log('removeOverlay', args)
    instances.removed.push(args[0])
  }
  openInfoWindow(...args: unknown[]): void {
    this.log('openInfoWindow', args)
  }
  setViewport(...args: unknown[]): void {
    this.log('setViewport', args)
  }
  centerAndZoom(...args: unknown[]): void {
    this.log('centerAndZoom', args)
  }
  addEventListener(...args: unknown[]): void {
    this.log('addEventListener', args)
    const [type, fn] = args as [string, (...a: unknown[]) => unknown]
    if (typeof type === 'string' && typeof fn === 'function') this.handlers[type] = fn
  }
  removeEventListener(...args: unknown[]): void {
    this.log('removeEventListener', args)
    const [type, fn] = args as [string, (...a: unknown[]) => unknown]
    if (typeof type === 'string' && this.handlers[type] === fn) delete this.handlers[type]
  }
  getContainer(): HTMLElement {
    return document.createElement('div')
  }
  pointToPixel(p: LngLat): { x: number; y: number } {
    return { x: p.lng, y: p.lat }
  }
}

export type FakeNamespace = Record<string, unknown>

/**
 * 组装交给 `vi.mock('../lib/bmap')` 的模块形状。
 * 未显式传入的构造器取上面的基类默认值 —— 这样 `Map` 一定是带记录的那份。
 */
export function fakeBMapModule(ns: FakeNamespace = {}) {
  const namespace: FakeNamespace = {
    Point: BMapPoint,
    Size: BMapSize,
    Icon: BMapIcon,
    InfoWindow: BMapInfoWindow,
    Polygon: BMapPolygon,
    Circle: BMapCircle,
    Marker: BMapMarker,
    Label: BMapLabel,
    Map: BMapMapBase,
    ...ns,
  }
  return {
    getMapConfig: async () => ({ browserAk: mapConfig.browserAk, mapStyleId: mapConfig.mapStyleId }),
    loadBMapGL: async () => namespace,
    geolocateMe: async () => null,
  }
}
