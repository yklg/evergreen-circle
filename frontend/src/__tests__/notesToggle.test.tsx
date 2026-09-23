// @vitest-environment jsdom
/**
 * 需求 A · 底图注记开关：集成 + 单元层守卫（TC-01 ~ TC-10）。
 *
 * 与 `bmapStyle.test.tsx` 共用同一套 BMapGL mock 思路，但本文件额外把
 * `getMapConfig` 的 `browserAk` / `mapStyleId` 做成 per-test 可控（夹具缺口 G1 扩展），
 * 以覆盖：① 挂载即读（R1）② 运行时切换（C4.3）③ 降级隐藏开关（T3/B）
 * ④ 对比页第三方声明（R5）⑤ 角标警示态（R4）⑥ styleId 优先（R7）⑦ T1b 遮罩兜底（R2/R3）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { LC_MAP_STYLE_LIGHT, LC_MAP_STYLE_NOTES_ON } from '../lib/bmapStyle'
import { useMapNotesStore } from '../store/mapNotesStore'

/** 记录每次 `setMapStyleV2` 的入参 —— 分支行为的唯一可观测出口。 */
const h = vi.hoisted(() => ({
  styleCalls: [] as unknown[],
  /** 由用例逐个改写：浏览器 AK 是否「配置了」 */
  browserAk: 'test-ak',
  /** 由用例逐个改写：控制台 styleId 是否「配置了」 */
  styleId: '' as string,
}))

vi.mock('../lib/bmap', () => {
  class Point {
    lng: number
    lat: number
    constructor(lng: number, lat: number) {
      this.lng = lng
      this.lat = lat
    }
  }
  class Size {
    constructor(..._a: unknown[]) {}
  }
  class Icon {
    constructor(..._a: unknown[]) {}
  }
  class InfoWindow {
    constructor(..._a: unknown[]) {}
  }
  class Polygon {
    constructor(..._a: unknown[]) {}
  }
  class Label {
    constructor(..._a: unknown[]) {}
  }
  class Marker {
    constructor(..._a: unknown[]) {}
    addEventListener() {}
  }
  class Map {
    constructor(..._a: unknown[]) {}
    enableScrollWheelZoom() {}
    addOverlay() {}
    removeOverlay() {}
    openInfoWindow() {}
    setViewport() {}
    centerAndZoom() {}
    addEventListener() {}
    removeEventListener() {}
    getContainer() {
      return document.createElement('div')
    }
    pointToPixel(p: { lng: number; lat: number }) {
      return { x: p.lng, y: p.lat }
    }
    setMapStyleV2(style: unknown) {
      h.styleCalls.push(style)
    }
  }
  return {
    // 受控：per-test 改 h.browserAk / h.styleId
    getMapConfig: async () => ({ browserAk: h.browserAk, mapStyleId: h.styleId }),
    loadBMapGL: async () => ({ Map, Point, Size, Icon, InfoWindow, Polygon, Marker, Label }),
    geolocateMe: async () => null,
  }
})

import LcMap from '../components/lifecircle/LcMap'

const REPORT = kaili as unknown as LivingCircleReport

type AnyStyle = { styleId?: string; styleJson?: unknown[] }
const lastStyle = (): AnyStyle => h.styleCalls.at(-1) as AnyStyle

beforeEach(() => {
  h.styleCalls.length = 0
  h.browserAk = 'test-ak'
  h.styleId = ''
  localStorage.clear()
  useMapNotesStore.setState({ on: false })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('TC-01 · 开启态样式常量（① 单元）', () => {
  it('LC_MAP_STYLE_NOTES_ON 含两条 on 规则且全量无 visibility:off（防把 off 反过来写错）', () => {
    const rules = LC_MAP_STYLE_NOTES_ON as { featureType?: string; elementType?: string; stylers?: { visibility?: string } }[]
    const hasOn = (ft: string, et: string) =>
      rules.some((r) => r.featureType === ft && r.elementType === et && r.stylers?.visibility === 'on')
    expect(hasOn('all', 'labels'), '缺少 {all/labels:on} ⇒ 开启态不显示第三方设施名').toBe(true)
    expect(hasOn('all', 'labels.icon'), '缺少 {all/labels.icon:on} ⇒ 开启态不显示 POI 图钉').toBe(true)
    const offs = rules.filter((r) => r.stylers?.visibility === 'off')
    expect(offs, '开启态不得残留任何 visibility:off（否则与「整段无 off」契约冲突）').toHaveLength(0)
  })

  it('LC_MAP_STYLE_LIGHT 仍含 off 规则（改动未破坏既有纪律）', () => {
    const rules = LC_MAP_STYLE_LIGHT as { featureType?: string; elementType?: string; stylers?: { visibility?: string } }[]
    expect(rules.some((r) => r.featureType === 'all' && r.elementType === 'labels' && r.stylers?.visibility === 'off')).toBe(true)
    expect(rules.some((r) => r.featureType === 'all' && r.elementType === 'labels.icon' && r.stylers?.visibility === 'off')).toBe(true)
  })
})

describe('TC-02 · 默认 off → 下发 LIGHT（② 集成，既有契约保持绿 + live 显示开关）', () => {
  it('默认 off → 初始 styleJson 即内置模板；live 态出现 role=switch 且默认关', async () => {
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    expect(lastStyle().styleJson).toBe(LC_MAP_STYLE_LIGHT)
    expect(lastStyle().styleId).toBeUndefined()
    const sw = screen.getByRole('switch', { name: '底图注记' }) as HTMLButtonElement
    expect(sw).toBeTruthy()
    expect(sw.getAttribute('aria-checked')).toBe('false')
    expect(sw.disabled).toBe(false)
  })
})

describe('TC-03 · 挂载即读 store（② 集成，抓 R1 刷新丢偏好）', () => {
  it('渲染前置 on=true → 初始即发 NOTES_ON（若只在运行时效应读 store，本用例必红）', async () => {
    useMapNotesStore.setState({ on: true })
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    expect(lastStyle().styleJson).toBe(LC_MAP_STYLE_NOTES_ON)
  })
})

describe('TC-04 · 运行时切换（② 集成，抓 C4.3）', () => {
  it('渲染(off) → store.set(true) → 收到第二次下发 = NOTES_ON', async () => {
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    expect(lastStyle().styleJson).toBe(LC_MAP_STYLE_LIGHT)
    act(() => {
      useMapNotesStore.getState().set(true)
    })
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(1))
    expect(lastStyle().styleJson).toBe(LC_MAP_STYLE_NOTES_ON)
    // 切回关
    act(() => {
      useMapNotesStore.getState().set(false)
    })
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(2))
    expect(lastStyle().styleJson).toBe(LC_MAP_STYLE_LIGHT)
  })
})

describe('TC-05 · 降级态隐藏开关（② 集成，抓 T3/B）', () => {
  it('getMapConfig→browserAk:"" → fallback，role=switch 计数 = 0', async () => {
    h.browserAk = ''
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(screen.getByText('地图降级 · 静态画布（无 AK / 离线）')).toBeTruthy())
    expect(screen.queryByRole('switch', { name: '底图注记' })).toBeNull()
    // 结构断言：fallback return 内不含注记开关节点
    expect(document.querySelectorAll('[role="switch"]')).toHaveLength(0)
  })
})

describe('TC-06 · 对比页第三方声明角标（② 集成，抓 R5）', () => {
  it('<LcMap compareReport/> + store on → 出现第三方声明角标', async () => {
    render(<LcMap report={REPORT} compareReport={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    act(() => {
      useMapNotesStore.getState().set(true)
    })
    await waitFor(() => expect(screen.getByLabelText('底图注记状态：已开启')).toBeTruthy())
    expect(screen.getByText(/第三方信息/)).toBeTruthy()
  })
})

describe('TC-07 · 角标视觉态（② 集成，抓 R4）', () => {
  it('off→灰底「已关闭」；on→警示色「已开启」含第三方声明', async () => {
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    const off = screen.getByLabelText('底图注记状态：已关闭')
    expect(off).toBeTruthy()
    expect(off.className).toContain('bg-white/95')

    act(() => {
      useMapNotesStore.getState().set(true)
    })
    await waitFor(() => expect(screen.getByLabelText('底图注记状态：已开启')).toBeTruthy())
    const on = screen.getByLabelText('底图注记状态：已开启')
    expect(on.className).toContain('border-warn/45')
    expect(on.className).toContain('bg-warn/10')
    expect(on.textContent).toContain('第三方信息')
  })
})

describe('TC-08 · styleId 优先哨兵（② 集成，🔵 抓 R7）', () => {
  it('store on + getMapConfig→{mapStyleId:"sid"} → 仍发 styleId，NOTES_ON 被压过', async () => {
    h.styleId = 'sid'
    useMapNotesStore.setState({ on: true })
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    expect(lastStyle().styleId).toBe('sid')
    expect(lastStyle().styleJson).toBeUndefined()
    // 运行时切换也不重发 styleJson（apply 在 mapStyleId 分支提前 return）
    act(() => {
      useMapNotesStore.getState().set(false)
    })
    expect(lastStyle().styleId).toBe('sid')
  })
})

describe('TC-09 · store 持久化（① 单元）', () => {
  it('默认 off；set(true) → localStorage="1"；set(false) → "0"（重建读取即 on）', () => {
    expect(useMapNotesStore.getState().on).toBe(false)
    act(() => {
      useMapNotesStore.getState().set(true)
    })
    expect(useMapNotesStore.getState().on).toBe(true)
    expect(localStorage.getItem('verda.mapNotes.v1')).toBe('1')
    act(() => {
      useMapNotesStore.getState().set(false)
    })
    expect(localStorage.getItem('verda.mapNotes.v1')).toBe('0')
  })
})

describe('TC-10 · T1b 遮罩（② 集成，抓 R2/R3）', () => {
  it('切换后不 fire tilesloaded → 3000ms 兜底移除遮罩；连点期开关禁用且遮罩不层叠', async () => {
    vi.useFakeTimers()
    try {
      render(<LcMap report={REPORT} />)
      // 用微任务轮询（fake timers 下不依赖 setTimeout 的 waitFor）
      await act(async () => {
        for (let i = 0; i < 20 && h.styleCalls.length === 0; i++) await Promise.resolve()
      })
      expect(h.styleCalls.length).toBeGreaterThan(0)

      const sw = screen.getByRole('switch', { name: '底图注记' }) as HTMLButtonElement
      // 连点 5 次（首点生效，余下命中 transition 守卫）
      for (let i = 0; i < 5; i++) {
        act(() => {
          fireEvent.click(sw)
        })
      }
      // 遮罩出现，且仅一层
      expect(screen.getByText('底图重载中…')).toBeTruthy()
      expect(screen.queryAllByText('底图重载中…')).toHaveLength(1)
      // 切换期开关禁用（防连点竞态）
      expect(sw.disabled).toBe(true)

      // 不 fire tilesloaded → 3000ms 兜底移除
      act(() => {
        vi.advanceTimersByTime(3000)
      })
      expect(screen.queryByText('底图重载中…')).toBeNull()
      expect(sw.disabled).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})
