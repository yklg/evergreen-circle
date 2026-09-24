// @vitest-environment jsdom
/**
 * 延迟优化 C · 热力采样点 Canvas 覆盖层（HeatFieldOverlay）集成契约（回归防线）。
 *
 * 守护三条契约：
 *  1. **渲染原语**：1049 采样点报告 → **零逐点 Marker**（旧实现逐点 DOM Marker 同步
 *     渲染 2-4s 的根因）；HeatFieldOverlay 单 Canvas 创建，draw() 逐点 fill（计数 == 可达点数）。
 *  2. **重绘**：map 平移/缩放事件（moveend 等）→ draw() 再次执行（像素随投影更新）。
 *  3. **悬停交互**：容器 mousemove 命中最近点（≤8px）→ 浮层 tooltip 文案
 *     `N 号采样点 · 步行 Xmin`；mouseleave / 地图平移开始（movestart）→ 隐藏。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { mockCanvasContext } from '../testUtils/canvasMock'
import type { CanvasCallCounts } from '../testUtils/canvasMock'

interface FakeMarker {
  point: { lng: number; lat: number }
  opts: Record<string, unknown>
}

interface FakeMap {
  listeners: Record<string, (() => void)[]>
}

import {
  assertBasemapStylesSound,
  instances,
  resetInstances,
  resetStyleCalls,
} from './helpers/bmapGLFake'

/** `instances` 是无类型注册表；本文件把视图收窄成自己关心的形状。 */
const allMarkers = () => instances.markers as FakeMarker[]
const firstMap = () => instances.maps[0] as FakeMap

/**
 * 替身取自 `helpers/bmapGLFake`（全套件唯一一份 `setMapStyleV2`）。
 * 本文件保留的分歧：`addOverlay` 必须桥接 `overlay.setMap(map)`、×1000 线性投影、
 * 地图级事件回放表 —— 这三样是热力覆盖层契约的一部分，不能收进通用基类。
 */
vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  class Map extends H.BMapMapBase {
    listeners: Record<string, (() => void)[]> = {}
    // BMapGL 契约：addOverlay → overlay.setMap(map)；HeatFieldOverlay 靠它触发
    // initialize/draw（假桩缺了这一步，canvas 永不创建、fill 恒 0 —— 与真 SDK 行为不一致）
    override addOverlay(o: { setMap?: (m: unknown) => void }) {
      o.setMap?.(this)
    }
    override removeOverlay(o: { setMap?: (m: unknown) => void }) {
      instances.removed.push(o)
      o.setMap?.(null)
    }
    override getContainer(): HTMLElement {
      // HeatFieldOverlay 把 canvas 挂到 map 容器 —— 返回 LcMap 真实渲染的容器 div
      return (document.querySelector('[data-lc-map="true"]') as HTMLElement | null) ?? document.createElement('div')
    }
    override pointToPixel(p: { lng: number; lat: number }) {
      // 测试用线性投影：像素 = 经纬度 × 1000（命中测试与 draw 共用同一投影）
      return { x: p.lng * 1000, y: p.lat * 1000 }
    }
    override addEventListener(type: string, fn: () => void) {
      ;(this.listeners[type] ??= []).push(fn)
    }
    override removeEventListener(type: string, fn: () => void) {
      this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)
    }
  }
  return H.fakeBMapModule({ Map })
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const REPORT = kaili as unknown as LivingCircleReport

/** 给地图容器伪造有布局的尺寸：jsdom clientWidth/clientHeight 恒 0 → draw() 会防御性早退 */
function fakeLayout(el: HTMLElement) {
  Object.defineProperty(el, 'clientWidth', { value: 800, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: 600, configurable: true })
}

async function mountMap(report: LivingCircleReport = REPORT) {
  const view = render(<LcMap report={report} />)
  const mapEl = view.container.querySelector('[data-lc-map="true"]') as HTMLElement
  fakeLayout(mapEl)
  vi.spyOn(mapEl, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    width: 800,
    height: 600,
    right: 800,
    bottom: 600,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  await waitFor(() => expect(instances.maps.length).toBeGreaterThan(0))
  return { mapEl, view }
}

let calls: CanvasCallCounts

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  calls = mockCanvasContext()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LcMap 热力采样点 Canvas 覆盖层（延迟优化 C）', () => {
  it('渲染原语：1049 点 → 零逐点 Marker，单 Canvas，draw 逐点 fill', async () => {
    const { view } = await mountMap()
    await waitFor(() => expect(calls.fill ?? 0).toBeGreaterThanOrEqual(1049))
    const heatMarkers = allMarkers().filter((m) => String(m.opts.title ?? '').includes('号采样点'))
    expect(heatMarkers).toHaveLength(0) // 旧的逐点 DOM Marker 一个都不许再出现
    expect(view.container.querySelectorAll('canvas').length).toBe(1) // 单 Canvas 覆盖层
  })

  it('重绘：map 平移/缩放事件 → draw() 再次执行（像素随投影更新）', async () => {
    await mountMap()
    await waitFor(() => expect(calls.fill ?? 0).toBeGreaterThanOrEqual(1049))
    const before = calls.fill ?? 0
    for (const fn of firstMap().listeners.moveend ?? []) fn()
    expect(calls.fill ?? 0).toBeGreaterThan(before)
  })

  it('悬停：mousemove 命中最近点 → tooltip 文案；mouseleave 隐藏', async () => {
    const { mapEl, view } = await mountMap()
    const tip = view.container.querySelector('[role="status"]') as HTMLElement
    // 采样点 0：{lng: 107.95069, lat: 26.5734, minutes: 61.1} → 投影 (107950.69, 26573.4)
    fireEvent.mouseMove(mapEl, { clientX: 107950.69, clientY: 26573.4 })
    expect(tip.textContent).toBe('0 号采样点 · 步行 61.1min')
    expect(tip.style.display).toBe('block')
    fireEvent.mouseLeave(mapEl)
    expect(tip.style.display).toBe('none')
  })

  it('平移开始（movestart）→ 浮层隐藏（点位像素已变，旧 tooltip 失真）', async () => {
    const { mapEl, view } = await mountMap()
    const tip = view.container.querySelector('[role="status"]') as HTMLElement
    fireEvent.mouseMove(mapEl, { clientX: 107950.69, clientY: 26573.4 })
    expect(tip.style.display).toBe('block')
    for (const fn of firstMap().listeners.movestart ?? []) fn()
    expect(tip.style.display).toBe('none')
  })

  /* TC-R12：本文件曾是「样式盲区」三兄弟之一（`setMapStyleV2` 空桩）。
     这条钉的是眼睛本身：样式必须真的被下发过，色值对错不归本文件管。 */
  it('底图样式确实被下发且结构自洽（夹具眼睛哨兵，非空桩）', async () => {
    await mountMap()
    assertBasemapStylesSound()
  })
})

/**
 * 阶段 −1 · **历史报告的热力层不得被字段迁移清空**。
 *
 * 库里 25 份既有报告的采样点全部只有旧名 `reachable`（无 `timed`、无汇总数）。
 * 若取数直接读 `p.timed`，这些点会全部落选 ⇒ 历史报告一打开就是「一张没有耗时的空图」，
 * 且**没有任何报错**——用户只会以为「这次没采样」。本组用例把这个静默零变回红灯。
 */
describe('LcMap 热力采样点 · 历史快照（旧名 reachable）读侧兼容', () => {
  /** 阶段 −1 之前形态：点带 `reachable`，sampling 无 timed_count/in_reach_count。 */
  function legacyReport(): LivingCircleReport {
    const mk = (idx: number, minutes: number | null) => ({
      idx,
      lng: 107.95 + idx * 0.002, // 收敛在凯里中心附近，投影后仍落在画布内
      lat: 26.573,
      minutes,
      reachable: minutes != null,
    })
    return {
      scene: { name: '凯里老街', city: '凯里市', address: '老街', center: [107.95, 26.573], study_radius_m: 2500 },
      generated_at: '2026-09-19T00:00:00.000Z',
      data_origin: 'live',
      caliber: { reach_full_min: 20 },
      isochrones: [
        { minutes: 5, area_km2: 0.1, geojson: { type: 'Polygon', coordinates: [[[107.94, 26.56], [107.96, 26.56], [107.96, 26.58], [107.94, 26.58], [107.94, 26.56]]] } },
        { minutes: 10, area_km2: 0.4, geojson: { type: 'Polygon', coordinates: [[[107.93, 26.55], [107.97, 26.55], [107.97, 26.59], [107.93, 26.59], [107.93, 26.55]]] } },
        { minutes: 15, area_km2: 0.9, geojson: { type: 'Polygon', coordinates: [[[107.92, 26.54], [107.98, 26.54], [107.98, 26.6], [107.92, 26.6], [107.92, 26.54]]] } },
        { minutes: 20, area_km2: 1.5, geojson: { type: 'Polygon', coordinates: [[[107.91, 26.53], [107.99, 26.53], [107.99, 26.61], [107.91, 26.61], [107.91, 26.53]]] } },
      ],
      sampling: {
        // 4 个有耗时 + 1 个未测时（必须被剔除，且不能把「未测时」画成 0 分钟）
        points: [mk(0, 3.2), mk(1, 12.5), mk(2, 20), mk(3, 45.7), mk(4, null)],
        interpolation: 'idw',
        is_scattered: true,
      },
      poi: { categories: [], total: 0, in_circle: 0, points: [] },
      blindspots: [],
      scores: { total: 60, radar: [], bars: [], triads: [], note: '' },
    } as unknown as LivingCircleReport
  }

  it('历史快照仍绘热力（fill ≥ 已测时点数 4，不为 0），且未测时点不参与', async () => {
    await mountMap(legacyReport())
    await waitFor(() => expect(calls.fill ?? 0).toBeGreaterThanOrEqual(4))
    // 未测时的那一个不画：draw 的次数必须正好是 4（不是 5，也不是 0）
    expect(calls.fill).toBe(4)
  })
})
