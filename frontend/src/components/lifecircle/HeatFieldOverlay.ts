/**
 * 热力采样点 Canvas 覆盖层（延迟优化 C：渲染原语修复）。
 *
 * 根因：用「每点一个 DOM Marker」表达密度场是**渲染原语错配** —— BMapGL Marker 是
 * DOM 节点，千级量级同步渲染 2-4s，天花板是硬性的；任何未来密度提升（riding 5km、
 * 付费档更细采样）都会重新撞墙。Canvas 是密度无关解：1 个覆盖层 O(N) 原生绘制
 * （1049 点每帧 ~2ms）。减点（≤250 魔数）只是把墙从 1049 移到 250，属症状修补，弃用。
 *
 * 遵循 BMapGL 自定义 Overlay 契约：`map.addOverlay(overlay)` → `setMap(map)` →
 * `initialize` 建画布 → 平移/缩放/尺寸变化时 `draw()` 重绘。`draw()` 触发由本层
 * 订阅 map 事件驱动（不依赖 SDK 对非内建覆盖物的 draw 调度时机）。
 * canvas `pointer-events:none`，不拦截拖拽/平移；悬停命中测试由调用方在 map 容器
 * mousemove 上做（最近点 ≤8px → tooltip），视觉契约与旧 Marker title 一致。
 */
import type { BMapMapOverlay } from '../../lib/bmap'

/** 采样点热力输入（`report.sampling.points` 中「已测时且 minutes 非空」的投影） */
export interface HeatSamplePoint {
  idx: number
  lng: number
  lat: number
  minutes: number
}

/** 地图最小面（BMapGL BMapMap 的真子集 + 覆盖层需要的像素/事件接口） */
export interface HeatMapLike {
  getContainer(): HTMLElement
  pointToPixel(point: { lng: number; lat: number }): { x: number; y: number }
  addEventListener?(event: string, fn: () => void): void
  removeEventListener?(event: string, fn: () => void): void
}

/** 耗时(分钟) → 热力色：0min 浅绿 → 20min 深绿（线性插值）；>20 按 20min 最深色 */
export function minuteHeatColor(minutes: number): string {
  const t = Math.max(0, Math.min(1, minutes / 20))
  const from = [0x8f, 0xbf, 0xa2] // #8fbfa2
  const to = [0x2c, 0x5a, 0x3f] //   #2c5a3f
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

/** 圆点尺寸/透明度与旧热力 Marker、降级画布保持一致（视觉契约零变化） */
const DOT_RADIUS = 2.6
const DOT_OPACITY = 0.55
const REDRAW_EVENTS = ['movestart', 'moveend', 'zoomend', 'resize'] as const

export class HeatFieldOverlay implements BMapMapOverlay {
  private _map: HeatMapLike | null = null
  private _canvas: HTMLCanvasElement | null = null
  private _ctx: CanvasRenderingContext2D | null = null
  private _points: HeatSamplePoint[] = []
  private _dispose: (() => void) | null = null
  private readonly _PointCtor: new (lng: number, lat: number) => { lng: number; lat: number }

  constructor(bmap: { Point: new (lng: number, lat: number) => { lng: number; lat: number } }) {
    this._PointCtor = bmap.Point
  }

  /** 注入「已测时且 minutes 非空」的采样点（全量，不需减点）；已挂载则立即重绘 */
  setPoints(points: HeatSamplePoint[]): void {
    this._points = points
    if (this._map) this.draw()
  }

  /** BMapMapOverlay 契约：map.addOverlay → setMap(map)；removeOverlay → setMap(null)。 */
  setMap(map: HeatMapLike | null): void {
    if (map === this._map) return
    this._teardown()
    this._map = map
    if (!map) return
    this.initialize(map)
    this._dispose = this._bind(map)
    this.draw()
  }

  /** BMapGL 自定义覆盖物惯例入口（initialize）：建画布并挂到 map 容器；幂等。 */
  initialize(map: HeatMapLike): HTMLElement {
    const existing = this._canvas
    if (existing && existing.parentNode === map.getContainer()) return existing
    const canvas = document.createElement('canvas')
    canvas.style.position = 'absolute'
    canvas.style.inset = '0'
    canvas.style.pointerEvents = 'none'
    canvas.style.zIndex = '1'
    map.getContainer().appendChild(canvas)
    this._canvas = canvas
    // 防御性空检：jsdom 的 getContext 返回 null/stub，与现有 try/catch 模式一致
    this._ctx = canvas.getContext('2d')
    return canvas
  }

  /** 逐点 pointToPixel → fill 圆形（O(N) 原生绘制，密度无关） */
  draw(): void {
    const map = this._map
    const canvas = this._canvas
    const ctx = this._ctx
    if (!map || !canvas || !ctx) return
    const container = map.getContainer()
    const w = container.clientWidth || 0
    const h = container.clientHeight || 0
    if (!(w > 0 && h > 0)) return // 未布局（jsdom/隐藏态）不绘制
    const dpr = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, 2)
    const bw = Math.round(w * dpr)
    const bh = Math.round(h * dpr)
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw
      canvas.height = bh
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.globalAlpha = DOT_OPACITY
    for (const sp of this._points) {
      const px = map.pointToPixel(new this._PointCtor(sp.lng, sp.lat))
      ctx.beginPath()
      ctx.arc(px.x, px.y, DOT_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = minuteHeatColor(sp.minutes)
      ctx.fill()
    }
    ctx.globalAlpha = 1
  }

  private _bind(map: HeatMapLike): () => void {
    if (typeof map.addEventListener !== 'function') return () => {}
    const redraw = (): void => this.draw()
    for (const ev of REDRAW_EVENTS) map.addEventListener(ev, redraw)
    return () => {
      for (const ev of REDRAW_EVENTS) map.removeEventListener?.(ev, redraw)
    }
  }

  private _teardown(): void {
    this._dispose?.()
    this._dispose = null
    if (this._canvas?.parentNode) this._canvas.parentNode.removeChild(this._canvas)
    this._canvas = null
    this._ctx = null
  }
}
