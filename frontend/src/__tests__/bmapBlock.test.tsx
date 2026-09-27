// @vitest-environment jsdom
/**
 * 百度地图组件与榜单联动（TC-F02 / TC-F03 · M2e）
 *
 * 守护契约：
 *   BM-1 后端未下发浏览器端 AK → 出「地图数据源未就绪」降级位，且零地图构造（不炸任务）
 *   BM-2 marker 数 = 榜单中坐标齐备且 matched!==false 的景点数（未匹配实体不上图、不错位）
 *   BM-3 marker 点击 → 上抛该 spot_id（弹窗/选中走冻结实体键）
 *   BM-4 榜单行 hover → data-selected 提升，地图 panTo 对应 marker（双向联动）
 *   BM-5 底图样式必须随地图一起下发（C3 注记纪律）：缺一次 setMapStyleV2 即红
 *
 * 接缝：`vi.mock('../lib/bmap')` + `helpers/bmapGLFake`（全套件唯一替身出口，TC-R12），
 * AK 由 `mapConfig.browserAk` 逐用例控制 —— 组件侧已不再读构建期变量。
 *
 * ⚠️ 用例顺序有约束：`hooks/useMapConfig` 只缓存「取到 AK 的那一次」，
 * 所以 BM-1（无 AK）必须排在任何成功用例之前；顺序被改动时会以「BM-1 断言失败」
 * 的形式暴露，不会静默放行。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { LC_MAP_STYLE_LIGHT } from '../lib/bmapStyle'
import {
  assertBasemapStylesSound,
  instances,
  mapConfig,
  resetInstances,
  resetStyleCalls,
  styleCalls,
} from './helpers/bmapGLFake'

vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  /** 只补本文件要的 `panTo`（联动平移）；样式记录沿用基类唯一实现，不得改成空桩。 */
  class Map extends H.BMapMapBase {
    panTo = vi.fn()
  }
  return H.fakeBMapModule({ Map })
})

import { BMapBlock, type MapSpot } from '../components/BMapBlock'
import { VSpotAtlas } from '../components/VStructured'

type LoggedMap = { calls: [string, unknown[]][]; panTo: ReturnType<typeof vi.fn> }
type FakeMarker = { opts: { title?: string }; handlers: Record<string, (a?: unknown) => void> }

const mapAt = (i = 0): LoggedMap => instances.maps[i] as LoggedMap
const overlayTitles = (): (string | undefined)[] =>
  (instances.markers as FakeMarker[]).map((m) => m.opts.title)

beforeEach(() => {
  resetStyleCalls()
  resetInstances()
  mapConfig.browserAk = 'test-ak'
  mapConfig.mapStyleId = ''
})

afterEach(() => cleanup())

const SPOTS: MapSpot[] = [
  { spot_id: '大理_spot_1', name: '大理古城', lat: 25.69, lng: 100.16, matched: true, score: 88 },
  { spot_id: '大理_spot_2', name: '洱海廊道', lat: 25.75, lng: 100.21, matched: true },
  { spot_id: '大理_spot_3', name: '未匹配景点', lat: 25.6, lng: 100.1, matched: false },
  { spot_id: '大理_spot_4', name: '无坐标景点', lat: null, lng: null, matched: true },
]

describe('BMapBlock', () => {
  it('BM-1：后端未下发 AK → 降级文案且零地图构造', async () => {
    mapConfig.browserAk = ''
    const { container } = render(<BMapBlock spots={SPOTS} />)
    const ph = await waitFor(() => {
      const el = container.querySelector('[data-map-placeholder]')
      expect(el).toBeTruthy()
      return el!
    })
    expect(ph.textContent).toContain('浏览器端 AK')
    expect(ph.textContent).toContain('/api/life-circle/map-config')
    expect(instances.maps).toHaveLength(0)
  })

  it('BM-2：marker 数只等于可定位实体数，未匹配/缺坐标不上图', async () => {
    render(<BMapBlock spots={SPOTS} />)
    await waitFor(() => expect(instances.maps).toHaveLength(1))
    const added = mapAt().calls.filter(([m]) => m === 'addOverlay')
    expect(added).toHaveLength(2)
    expect(overlayTitles()).toEqual(['大理古城', '洱海廊道'])
    expect(mapAt().calls.some(([m]) => m === 'centerAndZoom')).toBe(true)
  })

  it('BM-3：marker 点击上抛 spot_id', async () => {
    const onSelect = vi.fn()
    render(<BMapBlock spots={SPOTS} onSelect={onSelect} />)
    await waitFor(() => expect(instances.maps).toHaveLength(1))
    ;(instances.markers[0] as FakeMarker).handlers.click()
    expect(onSelect).toHaveBeenCalledWith('大理_spot_1')
    expect(mapAt().calls.some(([m]) => m === 'openInfoWindow')).toBe(true)
  })

  it('BM-5：地图与底图样式同批下发，styleId 为空时用内置模板（注记关）', async () => {
    render(<BMapBlock spots={SPOTS} />)
    await waitFor(() => expect(instances.maps).toHaveLength(1))
    expect(styleCalls.at(-1)!.styleJson).toBe(LC_MAP_STYLE_LIGHT)
    expect(styleCalls.at(-1)!.styleId).toBeUndefined()
    assertBasemapStylesSound()
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
    const { container } = render(<VSpotAtlas data={RANKING as never} />)
    await waitFor(() => expect(instances.maps).toHaveLength(1))
    const row = container.querySelector('[data-spot-row="大理_spot_2"]')!
    fireEvent.mouseEnter(row)
    expect(row.getAttribute('data-selected')).toBe('true')
    await waitFor(() => expect(mapAt().panTo).toHaveBeenCalledWith({ lng: 100.21, lat: 25.75 }))
    // 未匹配实体无 marker：hover 只高亮表行，不上图不错位
    const badRow = container.querySelector('[data-spot-row="大理_spot_3"]')!
    fireEvent.mouseEnter(badRow)
    expect(badRow.getAttribute('data-selected')).toBe('true')
    expect(mapAt().panTo).not.toHaveBeenCalledWith({ lng: 100.1, lat: 25.6 })
    expect(overlayTitles()).not.toContain('未匹配景点')
  })
})
