// @vitest-environment jsdom
/**
 * 阶段 0（T-FE-05）· 底图注记纪律：**关掉第三方设施名与图钉，保留空间参照**。
 *
 * ## 被守护的两起事故（都不是假想）
 *
 * **事故一 · 改了等于没改。** `bmapStyle.ts` 里的注记关闭规则写了很久，却从未生效：
 * `backend/.env` 配了 `BAIDU_MAP_STYLE_ID`（2026-09-21 发布的「高对比浅色 · 清晰标注」样式），
 * 而 `LcMap` 的分支是「styleId 有值就用 styleId」。内置模板成了**死代码**，
 * 百度第三方设施名照旧上屏。「文件改了 / 注释写了 / 单测没有」＝ 谁都不知道运行时走哪条分支。
 *
 * **事故二 · 规则本身是无效的。** 2026-09-22 用真实底图实测（凯里老街，zoom 13/15/17）发现：
 * 只写 `{poilabel, labels: off}` 时，图上仍有「和谐家园 / 香枫庭院 / 居然之家 / 交通驾校」，
 * 且**百度自带的 POI 图钉一个不少** —— 而那些图钉正是「第三方点冒充自家数据」的最强观感来源。
 * 详见 `bmapStyle.ts` 文件头的 ①~⑤ 条实测结论。
 *
 * ## 本文件锁四件事
 *
 * 1. **通配 + 图钉**：必须同时关 `all/labels` 与 `all/labels.icon`（后者单列，关不到就是漏点）。
 * 2. **顺序即语义**：白名单必须排在通配关**之后**（颠倒 = 参照系全灭）。
 * 3. **白名单不得带 `color`**：带上会把刚开回的可见性再次打掉（实测 zoom 13 一片空白）。
 * 4. **分支行为**：`mapStyleId` 空 → 下发 `styleJson`（且同一引用）；非空 → 下发 `styleId`。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport } from '../types'
import { LC_KEEP_LABELS, LC_MAP_STYLE_LIGHT } from '../lib/bmapStyle'

/** 记录每次 `setMapStyleV2` 的入参 —— 分支行为的唯一可观测出口。 */
const h = vi.hoisted(() => ({
  styleCalls: [] as unknown[],
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
    // styleId 由 h.styleId 控制（模拟后端 `map_style_id` 下发值）
    getMapConfig: async () => ({ browserAk: 'test-ak', mapStyleId: h.styleId }),
    loadBMapGL: async () => ({ Map, Point, Size, Icon, InfoWindow, Polygon, Marker, Label }),
    geolocateMe: async () => null,
  }
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')
/** 真实实现（绕过上面的模块 mock）—— 契约层用例验的是解析逻辑本身，必须用真模块。 */
const realBmap = await vi.importActual<typeof import('../lib/bmap')>('../lib/bmap')

const REPORT = kaili as unknown as LivingCircleReport

type Rule = { featureType?: string; elementType?: string; stylers?: Record<string, unknown> }
const RULES = LC_MAP_STYLE_LIGHT as Rule[]
const ruleOf = (ft: string, et: string) =>
  RULES.find((r) => r.featureType === ft && r.elementType === et)
const idxOf = (ft: string, et: string) =>
  RULES.findIndex((r) => r.featureType === ft && r.elementType === et)

beforeEach(() => {
  h.styleCalls.length = 0
  h.styleId = ''
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('阶段 0 · 注记纪律（内容层）', () => {
  it('文字注记用通配 `all` 全关 —— 枚举 POI 家族不可行（实测 20 个候选名全部无效）', () => {
    const r = ruleOf('all', 'labels')
    expect(r, '缺少 `all/labels` 通配规则 ⇒ 叫不出名字的 POI 家族会漏网（居然之家/和谐家园就是这么漏的）').toBeTruthy()
    expect(r!.stylers?.visibility).toBe('off')
  })

  it('图钉必须**单独**关（`labels.icon` 是独立 elementType，关 labels 关不掉它）', () => {
    const r = ruleOf('all', 'labels.icon')
    expect(r, '缺少 `all/labels.icon` ⇒ 百度自带 POI 图钉照旧上屏，被读成自家数据').toBeTruthy()
    expect(r!.stylers?.visibility).toBe('off')
  })

  it('白名单开回「空间参照」（行政区名 + 各级路名），且**只写 visibility**', () => {
    expect(LC_KEEP_LABELS.length).toBeGreaterThanOrEqual(6)
    for (const ft of LC_KEEP_LABELS) {
      const r = ruleOf(ft, 'labels')
      expect(r, `白名单要素 ${ft} 没有开回规则`).toBeTruthy()
      expect(r!.stylers?.visibility).toBe('on')
      // ⚠️ 带 color 会把刚开回的可见性再次打掉（官方「最后一条生效」语义；实测 zoom 13 一片空白）
      expect(
        r!.stylers?.color,
        `${ft} 的开回规则带了 color —— 实测会让整层注记再次消失，见 bmapStyle.ts 第 ④ 条`,
      ).toBeUndefined()
    }
    // 白名单里不得混入 POI 家族（`*label` 形态的第三方经营主体名）
    for (const ft of LC_KEEP_LABELS) {
      expect(String(ft)).not.toMatch(/poilabel|estatelabel|shoppinglabel|companylabel/)
    }
  })

  it('顺序即语义：**先关后开**（颠倒 = 参照系全灭）', () => {
    const hideAt = idxOf('all', 'labels')
    const hideIconAt = idxOf('all', 'labels.icon')
    expect(hideAt).toBeGreaterThanOrEqual(0)
    expect(hideIconAt).toBeGreaterThanOrEqual(0)
    for (const ft of LC_KEEP_LABELS) {
      expect(
        idxOf(ft, 'labels'),
        `白名单 ${ft} 排在通配关之前 —— 会被后置的通配规则覆盖，等于没开`,
      ).toBeGreaterThan(Math.max(hideAt, hideIconAt))
    }
  })

  it('面层配色仍在（land/water/green/road 四类面色齐全，否则出现未定义色块）', () => {
    for (const ft of ['land', 'water', 'green']) {
      expect(ruleOf(ft, 'geometry')?.stylers?.color, `缺少 ${ft} 面色`).toBeTruthy()
    }
    expect(RULES.length).toBeGreaterThanOrEqual(10)
  })
})

describe('阶段 0 · styleId / styleJson 分支行为（运行时层）', () => {
  it('styleId 为空 → 下发 styleJson 且**就是内置模板**（关注记纪律真的生效）', async () => {
    h.styleId = ''
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    const arg = h.styleCalls.at(-1) as { styleId?: string; styleJson?: unknown[] }
    expect(arg.styleId).toBeUndefined() // 不得同时下发（官方：二选一）
    expect(arg.styleJson).toBe(LC_MAP_STYLE_LIGHT) // 同一引用，不能是别处的副本
    const off = (arg.styleJson ?? []).find(
      (x) => (x as Rule).featureType === 'all' && (x as Rule).elementType === 'labels.icon',
    ) as Rule | undefined
    expect(off?.stylers?.visibility).toBe('off') // 下发的 JSON 里确实带图钉关闭
  })

  it('styleId 非空 → 下发 styleId（显式 opt-in 时仍可用控制台样式）', async () => {
    h.styleId = 'console-style-id'
    render(<LcMap report={REPORT} />)
    await waitFor(() => expect(h.styleCalls.length).toBeGreaterThan(0))
    const arg = h.styleCalls.at(-1) as { styleId?: string; styleJson?: unknown[] }
    expect(arg.styleId).toBe('console-style-id')
    expect(arg.styleJson).toBeUndefined()
  })
})

describe('阶段 0 · 后端下发的 styleId 默认被抑制（契约层）', () => {
  it('map_style_id 为空时 getMapConfig 返回空串（不回填旧值、不报错）', async () => {
    // 真实抑制在后端 `main.life_circle_map_config()`（`BAIDU_ALLOW_CONSOLE_STYLE` 未置位时恒返回空），
    // 由 backend/tests/test_living_circle_api.py 覆盖；此处只钉住前端解析不引入偏差。
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, browser_ak: 'ak', map_style_id: '' })))
    const cfg = await realBmap.getMapConfig()
    expect(cfg.mapStyleId).toBe('')
    expect(cfg.browserAk).toBe('ak')
    fetchSpy.mockRestore()
  })

  it('后端返回非空 styleId 时如实透传（前端不擅自改写后端决定）', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(JSON.stringify({ ok: true, browser_ak: 'ak', map_style_id: 'sid-1' })),
      )
    const cfg = await realBmap.getMapConfig()
    expect(cfg.mapStyleId).toBe('sid-1')
    fetchSpy.mockRestore()
  })
})
