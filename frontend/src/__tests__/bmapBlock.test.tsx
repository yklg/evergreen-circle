// @vitest-environment jsdom
/**
 * 百度地图组件与榜单联动（TC-F02 / TC-F03 · M2e）
 *
 * 守护契约：
 *   BM-1 无 VITE_BAIDU_AK → 出「数据源暂不可用」占位，且不构造任何地图对象（不炸任务）
 *   BM-2 marker 数 = 榜单中坐标齐备且 matched!==false 的景点数（未匹配实体不上图、不错位）
 *   BM-3 marker 点击 → 上抛该 spot_id（弹窗/选中走冻结实体键）
 *   BM-4 榜单行 hover → data-selected 提升，地图 panTo 对应 marker（双向联动）
 *
 * 接缝：window.BMapGL 假命名空间（不注入真 script，JSAPI 加载路径由 loadBMap 单侧覆盖）。
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react'

const fakes = vi.hoisted(() => {
  class Point {
    lng: number
    lat: number
    constructor(lng: number, lat: number) { this.lng = lng; this.lat = lat }
  }
  const markers: any[] = []
  class Marker {
    position: any
    title: string
    listeners: Record<string, Function> = {}
    constructor(pt: any, opts: any) { this.position = pt; this.title = opts?.title ?? ''; markers.push(this) }
    addEventListener(ev: string, fn: Function) { this.listeners[ev] = fn }
    getPosition() { return this.position }
  }
  const maps: any[] = []
  class Map {
    overlays: any[] = []
    centerAndZoom = vi.fn()
    enableScrollWheelZoom = vi.fn()
    addOverlay = vi.fn((mk: any) => { this.overlays.push(mk) })
    panTo = vi.fn()
    openInfoWindow = vi.fn()
    constructor(_el: any) { maps.push(this) }
  }
  class InfoWindow {
    content: string
    constructor(c: string) { this.content = c }
  }
  return {
    Point, Marker, Map, InfoWindow, markers, maps,
    ns: null as any,
  }
})

import { BMapBlock } from '../components/BMapBlock'
import { VSpotAtlas } from '../components/VStructured'
import type { MapSpot } from '../components/BMapBlock'

function installFakeBMap() {
  const ns = {
    Point: fakes.Point, Marker: fakes.Marker, Map: fakes.Map, InfoWindow: fakes.InfoWindow,
  }
  ;(globalThis as any).BMapGL = ns
  ;(globalThis as any).window.BMapGL = ns
  return ns
}

beforeEach(() => {
  fakes.markers.length = 0
  fakes.maps.length = 0
})

afterEach(() => {
  cleanup()
  delete (globalThis as any).window.BMapGL
  delete (globalThis as any).window.__verdaBMapPromise
  vi.unstubAllEnvs()
})

const SPOTS: MapSpot[] = [
  { spot_id: '大理_spot_1', name: '大理古城', lat: 25.69, lng: 100.16, matched: true, score: 88 },
  { spot_id: '大理_spot_2', name: '洱海廊道', lat: 25.75, lng: 100.21, matched: true },
  { spot_id: '大理_spot_3', name: '未匹配景点', lat: 25.6, lng: 100.1, matched: false },
  { spot_id: '大理_spot_4', name: '无坐标景点', lat: null, lng: null, matched: true },
]

describe('BMapBlock', () => {
  it('BM-1：缺 AK → 占位文案且零地图构造', () => {
    installFakeBMap()
    // 显式钉空 AK：不依赖「本机恰好没有 .env.local」的环境假设（开发机配了真
    // VITE_BAIDU_AK 时 vitest 会加载 .env.local，隐式假设即破）。
    vi.stubEnv('VITE_BAIDU_AK', '')
    const { container } = render(<BMapBlock spots={SPOTS} />)
    const ph = container.querySelector('[data-map-placeholder]')
    expect(ph).toBeTruthy()
    expect(ph!.textContent).toContain('VITE_BAIDU_AK')
    expect(fakes.maps.length).toBe(0)
  })

  it('BM-2：marker 数只等于可定位实体数，未匹配/缺坐标不上图', async () => {
    installFakeBMap()
    vi.stubEnv('VITE_BAIDU_AK', 'TEST_AK')
    render(<BMapBlock spots={SPOTS} />)
    await waitFor(() => expect(fakes.maps.length).toBe(1))
    const map = fakes.maps[0]
    expect(map.overlays.length).toBe(2)
    expect(fakes.markers.map((m) => m.title)).toEqual(['大理古城', '洱海廊道'])
    expect(map.centerAndZoom).toHaveBeenCalled()
  })

  it('BM-3：marker 点击上抛 spot_id', async () => {
    installFakeBMap()
    vi.stubEnv('VITE_BAIDU_AK', 'TEST_AK')
    const onSelect = vi.fn()
    render(<BMapBlock spots={SPOTS} onSelect={onSelect} />)
    await waitFor(() => expect(fakes.maps.length).toBe(1))
    fakes.markers[0].listeners.click()
    expect(onSelect).toHaveBeenCalledWith('大理_spot_1')
    expect(fakes.maps[0].openInfoWindow).toHaveBeenCalled()
  })
})

describe('榜单 ↔ 地图双向联动（VSpotAtlas）', () => {
  const RANKING = [{
    destination: '大理',
    items: [
      { spot_id: '大理_spot_1', name: '大理古城', rank: 1, score: 88, matched: true, lat: 25.69, lng: 100.16 },
      { spot_id: '大理_spot_2', name: '洱海廊道', rank: 2, matched: true, lat: 25.75, lng: 100.21 },
      { spot_id: '大理_spot_3', name: '未匹配景点', rank: 3, matched: false, lat: 25.6, lng: 100.1 },
    ],
  }]

  it('BM-4：行 hover 提升 selected（data-selected），地图 panTo 对应 marker 坐标', async () => {
    installFakeBMap()
    vi.stubEnv('VITE_BAIDU_AK', 'TEST_AK')
    const { container } = render(<VSpotAtlas data={RANKING as any} />)
    await waitFor(() => expect(fakes.maps.length).toBe(1))
    const row = container.querySelector('[data-spot-row="大理_spot_2"]')!
    fireEvent.mouseEnter(row)
    expect(row.getAttribute('data-selected')).toBe('true')
    await waitFor(() =>
      expect(fakes.maps[0].panTo).toHaveBeenCalledWith({ lng: 100.21, lat: 25.75 }),
    )
    // 未匹配实体无 marker：hover 只高亮表行，不上图不错位
    const badRow = container.querySelector('[data-spot-row="大理_spot_3"]')!
    fireEvent.mouseEnter(badRow)
    expect(badRow.getAttribute('data-selected')).toBe('true')
    expect(fakes.maps[0].panTo).not.toHaveBeenCalledWith({ lng: 100.1, lat: 25.6 })
    expect(fakes.markers.map((m) => m.title)).not.toContain('未匹配景点')
  })
})
