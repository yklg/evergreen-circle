/**
 * 常青圈 · BMapGL v3.0 加载器（真实地图渲染层，F2 规划落地）。
 *
 * 流程：取浏览器 AK（`/api/life-circle/map-config` > `VITE_BAIDU_BROWSER_AK`）
 * → 注入百度 JS API 脚本 → 返回 `window.BMapGL` 命名空间。
 * 单例 promise：多页面/多实例共用一次脚本加载。
 * 无 AK / 脚本加载失败/超时 → reject，调用方降级为静态画布（评审无网可用）。
 *
 * 本文件只做「加载 + 坐标/逆地理」基础设施，不持有页面状态（渲染在 LcMap）。
 */
import type { LngLat } from '../types'

/** BMapGL 最小类型面（仅本项目用到；完整类型由百度 SDK 提供，避免引入类型包） */

export interface BMapPoint {
  lng: number
  lat: number
}

export interface BMapPixelSize {
  width: number
  height: number
}

export interface BMapMapOverlay {
  setMap(map: BMapMap | null): void
}

/** 不透明句柄类型（仅透传 SDK，无需内部结构） */
export type BMapIcon = object
export type BMapInfoWindow = object

export interface BMapMap {
  centerAndZoom(point: BMapPoint, zoom: number): void
  addOverlay(overlay: BMapMapOverlay): void
  removeOverlay(overlay: BMapMapOverlay): void
  clearOverlays(): void
  setMapStyleV2(style: { styleJson?: unknown[]; styleId?: string }): void
  setViewport(points: BMapPoint[]): void
  enableScrollWheelZoom(): void
  panTo(point: BMapPoint): void
  openInfoWindow(win: BMapInfoWindow, point: BMapPoint): void
}

export interface BMapMapCtor {
  new (container: HTMLElement, opts?: { zoom?: number; enableHighResZoom?: boolean }): BMapMap
}

/**
 * 覆盖物事件对象（仅声明本项目用到的字段）。
 *
 * ⚠️ **`point` 不是 BD-09 经纬度**，而是**投影平面坐标**（百度墨卡托米 / 像素，
 * 量级 1e6~1e7）。要取地理坐标请用 `latLng`，或用 `target.getPosition()`。
 *
 * 这里曾经把 `point` 声明成 `BMapPoint`（即 `{lng, lat}`）——那个类型声明本身就是
 * Q3 缺陷的邀请函：「类型正确、语义错误」的值被 TS 一路放行，最终经 API 落库
 * （实测标本 `(11440230.81, 2860409.52)` → 中心被打到北极圈 → 画布纯色）。
 * 现在把它的形状改成 `{x, y}`，**让 `e.point.lng` 编译不过**，从类型层堵住复发。
 */
export interface BMapOverlayEvent {
  type?: string
  target?: BMapMarker
  /** 地理坐标（BD-09）——拖拽事件的**正确**来源 */
  latLng?: BMapPoint
  /** 投影平面坐标（像素 / 墨卡托米）——**禁止**直接当经纬度用。
   *
   * 注意形状**随 SDK 版本/事件类型而异**：文档里 Pixel 是 `{x, y}`，
   * 但 dragend 实测给的是 `{lng, lat}` 且值为百度墨卡托米（11440230.81, 2860409.52）。
   * 故这里如实声明为「两种形状都可能」，由 `lib/geo.ts::toDiagPair` 统一归一为诊断用二元组。 */
  point?: { lng?: number; lat?: number; x?: number; y?: number }
  /** 屏幕像素坐标 */
  pixel?: { x: number; y: number }
}

export interface BMapMarker extends BMapMapOverlay {
  setPosition(point: BMapPoint): void
  /** 官方 API：取标注当前地理坐标（BD-09）——拖拽后的**权威**来源 */
  getPosition(): BMapPoint
  setTitle(title: string): void
  setIcon(icon: BMapIcon): void
  enableDragging(): void
  addEventListener(event: 'dragend' | 'click' | string, fn: (e: BMapOverlayEvent) => void): void
  openInfoWindow(win: BMapInfoWindow): void
}

export interface BMapMarkerCtor {
  new (point: BMapPoint, opts?: { icon?: BMapIcon; title?: string; enableDragging?: boolean }): BMapMarker
}

export type BMapPolygon = BMapMapOverlay

export interface BMapPolygonCtor {
  new (
    points: BMapPoint[],
    opts?: {
      strokeColor?: string
      fillColor?: string
      strokeWeight?: number
      fillOpacity?: number
      strokeStyle?: string
      strokeOpacity?: number
    },
  ): BMapPolygon
}

export interface BMapIconCtor {
  new (url: string, size: BMapPixelSize, opts?: { anchor?: BMapPixelSize }): BMapIcon
}

export interface BMapSizeCtor {
  new (width: number, height: number): BMapPixelSize
}

export interface BMapInfoWindowCtor {
  new (content: string, opts?: { width?: number; title?: string }): BMapInfoWindow
}

export interface BMapGeolocationResult {
  point: BMapPoint
}

export interface BMapGeolocation {
  getCurrentPosition(cb: (result: BMapGeolocationResult | null) => void): void
}

export interface BMapGeolocationCtor {
  new (): BMapGeolocation
}

export interface BMapGeocoderResult {
  address: string
  addressComponents?: { district?: string; street?: string; streetNumber?: string }
}

export interface BMapGeocoder {
  getLocation(point: BMapPoint, cb: (result: BMapGeocoderResult | null) => void): void
}

export interface BMapGeocoderCtor {
  new (): BMapGeocoder
}

export interface BMapGLNamespace {
  Map: BMapMapCtor
  Point: BMapPointCtor
  Polygon: BMapPolygonCtor
  Marker: BMapMarkerCtor
  Icon: BMapIconCtor
  Size: BMapSizeCtor
  InfoWindow: BMapInfoWindowCtor
  Geolocation: BMapGeolocationCtor
  Geocoder: BMapGeocoderCtor
}

export interface BMapPointCtor {
  new (lng: number, lat: number): BMapPoint
}

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const CB = '__lc_bmap_ready__'
const LOAD_TIMEOUT_MS = 8000

let pending: Promise<BMapGLNamespace> | null = null

function loadScript(ak: string): Promise<BMapGLNamespace> {
  const win = window as unknown as { BMapGL?: BMapGLNamespace; [CB]: () => void }
  if (win.BMapGL) return Promise.resolve(win.BMapGL)
  if (pending) return pending
  pending = new Promise<BMapGLNamespace>((resolve, reject) => {
    const script = document.createElement('script')
    const timer = window.setTimeout(() => {
      script.remove()
      pending = null
      reject(new Error('BMapGL 脚本加载超时'))
    }, LOAD_TIMEOUT_MS)
    win[CB] = () => {
      window.clearTimeout(timer)
      if (win.BMapGL) resolve(win.BMapGL)
      else reject(new Error('BMapGL 未注入 window'))
    }
    // 必须带 type=webgl：否则百度返回经典版 JS API（只注入 window.BMap，无 BMapGL）
    // → 回调触发但 window.BMapGL 永不存在 → 必然降级静态画布。
    script.src = `https://api.map.baidu.com/api?type=webgl&v=1.0&ak=${encodeURIComponent(ak)}&callback=${CB}`
    script.onerror = () => {
      window.clearTimeout(timer)
      pending = null
      reject(new Error('BMapGL 脚本加载失败'))
    }
    document.head.appendChild(script)
  })
  return pending
}

/** 浏览器 AK 获取（公开键，Referer 白名单限域）：后端 map-config 优先，VITE 环境变量兜底。 */
export async function getBrowserAk(): Promise<string> {
  const cfg = await getMapConfig()
  return cfg.browserAk
}

export interface LcMapConfig {
  browserAk: string
  /** 个性化地图 styleId（控制台发布）；空 → 前端回退内置 S2 styleJson */
  mapStyleId: string
}

/** 地图配置（AK + 个性化 styleId）：后端 map-config 优先，VITE 环境变量兜底。 */
export async function getMapConfig(): Promise<LcMapConfig> {
  try {
    const r = await fetch(`${API_BASE}/api/life-circle/map-config`)
    if (r.ok) {
      const data = (await r.json()) as { browser_ak?: string; map_style_id?: string }
      return {
        browserAk: data.browser_ak ?? '',
        mapStyleId: data.map_style_id ?? '',
      }
    }
  } catch {
    /* 后端不可达 → 走环境变量/降级 */
  }
  return {
    browserAk: import.meta.env.VITE_BAIDU_BROWSER_AK ?? '',
    mapStyleId: import.meta.env.VITE_BAIDU_MAP_STYLE_ID ?? '',
  }
}

/** 加载 BMapGL（单例）；失败 reject，调用方降级。 */
export function loadBMapGL(ak: string): Promise<BMapGLNamespace> {
  return loadScript(ak)
}

/**
 * 定位到我：浏览器定位 → BD-09 点 → 逆地理编码得社区名。
 * 依赖 BMapGL（Geolocation/Geocoder 负责 WGS-84→BD-09 与逆地理）。
 *
 * 返回值带 `coordSys: 'bd09'`：BMapGL 的 Geolocation **已经**做过坐标系转换，
 * 与下面 `LcMap` 里 `navigator.geolocation` 的降级分支（WGS-84 原始值）必须区分开，
 * 否则 600m 的坐标系偏差会静默进入体检中心。
 */
export function geolocateMe(bmap: BMapGLNamespace): Promise<{ lnglat: LngLat; name: string; coordSys: 'bd09' } | null> {
  return new Promise((resolve) => {
    const geo = new bmap.Geolocation()
    geo.getCurrentPosition((res) => {
      if (!res?.point) {
        resolve(null)
        return
      }
      const pt = res.point
      const g = new bmap.Geocoder()
      g.getLocation(pt, (loc) => {
        const comp = loc?.addressComponents
        const name =
          (comp ? `${comp.district ?? ''}${comp.street ?? ''}${comp.streetNumber ?? ''}`.trim() : '') ||
          loc?.address ||
          ''
        resolve({ lnglat: [pt.lng, pt.lat], name, coordSys: 'bd09' })
      })
    })
  })
}
