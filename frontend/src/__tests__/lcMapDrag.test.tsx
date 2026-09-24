// @vitest-environment jsdom
/**
 * Q3 · 中心标记拖拽的**坐标契约**（回归防线）。
 *
 * ## 被守护的历史事故
 *
 * BMapGL 的 `dragend` 事件同时挂了三样东西，量级差 5 个数量级：
 *   - `e.latLng`  → BD-09 经纬度（`{lng: 107.97, lat: 26.57}`）✅ 唯一可直接用的事件字段
 *   - `e.point`   → **投影平面坐标**（墨卡托/像素米，`{lng: 11440230.81, lat: 2860409.52}`）❌
 *   - `e.target.getPosition()` → BD-09 经纬度 ✅ 权威回退
 *
 * 旧实现读的是 `e.point`，于是拖一下中心 → `(150.81, 84.60)`（北极圈）→ 无瓦片 →
 * 画布退化为纯色；更糟的是该值会经 `/api/tasks` 落库，**之后每次打开都必现**。
 *
 * ## 本文件的三条分支（= 实现里 `e.latLng ?? e.target?.getPosition?.()` 的决策树）
 *
 * | 分支 | 事件形状 | 期望 |
 * |---|---|---|
 * | A | 两者都在 | 采纳 `latLng`（优先级不得倒置） |
 * | B | 只有 `target.getPosition()` | 采纳之（回退必须真的生效） |
 * | C | 两者都没有（含只有 `e.point` 的历史标本） | **不采纳** + `console.warn`；绝不写坏中心 |
 *
 * 「不采纳」是本契约的核心：宁可不响应这次拖拽，也不能把非法坐标送进提交链路。
 *
 * ## 本契约的**已知盲区**（必须写下来，否则会误以为值域闸万能）
 *
 * 值域闸只判断「值长得对不对」，判断不了「值从哪来」。`e.point` 若被某处取模/包裹，
 * 会落进 `|lng|<=180, |lat|<=90` 成为「值域合法、语义全错」——`(150.81, 84.6)` 就是
 * 这类值，值域闸**查不出来**。故真正的第一道防线是**来源白名单**（只认 latLng /
 * getPosition），值域闸只是第二道。分支 A/B/C 正是在钉「来源纪律」这件事。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import kaili from '../mocks/fixtures/livingCircle/kaili.json'
import type { LivingCircleReport, LngLat } from '../types'
import { assertBasemapStylesSound, instances, resetInstances, resetStyleCalls } from './helpers/bmapGLFake'

/* ── BMapGL 假命名空间：只记录「谁被建出来了」，好让测试拿到中心标记 ── */

interface FakeMarker {
  point: { lng: number; lat: number }
  opts: Record<string, unknown>
  listeners: Record<string, (e: unknown) => void>
  getPosition: () => { lng: number; lat: number }
}

const h = vi.hoisted(() => ({
  /** 供断言「确实提示了用户/开发者，而不是静默吞掉」 */
  warnings: [] as string[],
}))

/**
 * 替身取自 `helpers/bmapGLFake`（全套件唯一一份 `setMapStyleV2`，见该文件头）。
 * 本文件只保留自己的分歧：Marker 的拖拽契约、Map 的 ×100 投影与容器复用。
 */
vi.mock('../lib/bmap', async () => {
  const H = await import('./helpers/bmapGLFake')
  class Marker extends H.BMapMarker implements FakeMarker {
    listeners: Record<string, (e: unknown) => void> = {}
    setPosition(p: { lng: number; lat: number }) {
      this.point = p
    }
    setTitle() {}
    setIcon() {}
    enableDragging() {}
    openInfoWindow() {}
    /** 权威回退来源：始终等于标记当前真实位置（BD-09） */
    override getPosition = (): { lng: number; lat: number } => ({
      lng: this.point.lng,
      lat: this.point.lat,
    })
    addEventListener(type: string, fn: (e: unknown) => void) {
      this.listeners[type] = fn
    }
  }
  // HeatFieldOverlay（延迟优化 C）契约：getContainer 挂 canvas、pointToPixel 投影、
  // 地图级事件订阅。jsdom 容器尺寸为 0 → draw() 防御性早退，无碍本文件拖拽契约。
  class Map extends H.BMapMapBase {
    private _c: HTMLElement | null = null
    override getContainer(): HTMLElement {
      this._c ??= document.createElement('div')
      return this._c
    }
    override pointToPixel(p: { lng: number; lat: number }) {
      return { x: p.lng * 100, y: p.lat * 100 }
    }
  }
  // AK 非空 → 走 live 分支（本文件只测真实态地图；降级态由 geo.ts / LcMap 降级画布用例覆盖）
  return H.fakeBMapModule({ Marker, Map })
})

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const REPORT = kaili as unknown as LivingCircleReport

/** 取中心标记：唯一带 `dragend` 监听的那个（POI/盲区标记都不注册拖拽） */
function centerMarker(): FakeMarker {
  const hit = (instances.markers as FakeMarker[]).find((m) => m.listeners.dragend)
  if (!hit) throw new Error('未找到注册了 dragend 的中心标记')
  return hit
}

async function mountMap(onCenterChange: (c: LngLat) => void) {
  render(<LcMap report={REPORT} draggableCenter onCenterChange={onCenterChange} />)
  // 初始化是异步的（getMapConfig → loadBMapGL → setMode('live') → 覆盖层 effect）
  await waitFor(() => expect((instances.markers as FakeMarker[]).some((m) => m.listeners.dragend)).toBe(true))
}

beforeEach(() => {
  resetInstances()
  resetStyleCalls()
  h.warnings.length = 0
  vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => {
    h.warnings.push(args.map(String).join(' '))
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LcMap 中心标记 dragend · BD-09 坐标契约', () => {
  it('分支 A：latLng 与 getPosition 同时存在 → 采纳 latLng（优先级不得倒置）', async () => {
    const onCenterChange = vi.fn()
    await mountMap(onCenterChange)

    // latLng 与 getPosition 故意给**不同**的值：只有真按优先级取才会得到 latLng 那个
    centerMarker().listeners.dragend({
      latLng: { lng: 107.981, lat: 26.575 },
      target: { getPosition: () => ({ lng: 108.999, lat: 27.999 }) },
    })

    expect(onCenterChange).toHaveBeenCalledTimes(1)
    expect(onCenterChange).toHaveBeenCalledWith([107.981, 26.575])
    expect(h.warnings).toEqual([])
  })

  it('分支 B：无 latLng → 回退 marker.getPosition()，回退必须真的生效', async () => {
    const onCenterChange = vi.fn()
    await mountMap(onCenterChange)

    // 事件上无 latLng，只有 target.getPosition（BMapGL 某些版本的实际形状）
    centerMarker().listeners.dragend({
      target: { getPosition: () => ({ lng: 107.9905, lat: 26.5801 }) },
    })

    expect(onCenterChange).toHaveBeenCalledTimes(1)
    expect(onCenterChange).toHaveBeenCalledWith([107.9905, 26.5801])
    expect(h.warnings).toEqual([])
  })

  it('分支 C：两者皆无（含只有 e.point 的历史标本）→ 不采纳 + 可操作的 console.warn', async () => {
    const onCenterChange = vi.fn()
    await mountMap(onCenterChange)

    centerMarker().listeners.dragend({
      // ⚠️ 历史事故标本：BMapGL 拖拽事件里 point 是投影平面米，不是经纬度。
      // 旧实现读它 ⇒ 中心落到北极圈，且经 API 落库永久复现。
      point: { lng: 11440230.81, lat: 2860409.52 },
      type: 'dragend',
    })

    expect(onCenterChange).not.toHaveBeenCalled()
    expect(h.warnings).toHaveLength(1)
    const w = h.warnings[0]
    // ① 说清「拒绝的是来源、不是值」——否则会被读成「值算错了」，排查方向跑偏
    expect(w).toContain('拒绝该坐标来源')
    // ② 必须把**实际收到的值**报出来，否则诊断价值为零（历史实现只报 null）
    expect(w).toContain('11440230.81')
    expect(w).toContain('墨卡托')
    // ③ 必须给出可操作的替代字段
    expect(w).toContain('getPosition')
  })

  it('分支 C′：latLng 存在但越界 → 仍不采纳（值域闸兜住「来源白名单被绕过」）', async () => {
    const onCenterChange = vi.fn()
    await mountMap(onCenterChange)
    const cm = centerMarker()

    // ① 纬度 126.5（超出 ±90）：包裹/错算的典型症状
    cm.listeners.dragend({ latLng: { lng: 107.97, lat: 126.5 } })
    // ② 墨卡托量级直接落在 latLng 上（万一某处把点改名为 latLng 传下来）
    cm.listeners.dragend({ latLng: { lng: 11440230.81, lat: 2860409.52 } })

    expect(onCenterChange).not.toHaveBeenCalled()
    expect(h.warnings).toHaveLength(2)
    expect(h.warnings[0]).toContain('非法 BD-09 坐标')
    expect(h.warnings[1]).toContain('墨卡托')
  })

  it('合法拖拽不产生告警（防止为了「安全」而把正常路径也拦掉）', async () => {
    const onCenterChange = vi.fn()
    await mountMap(onCenterChange)

    const cm = centerMarker()
    cm.listeners.dragend({ latLng: { lng: 107.97, lat: 26.57 } })
    cm.listeners.dragend({ latLng: { lng: -0.0001, lat: -0.0001 } }) // 边界内（南大西洋 0,0 附近）
    cm.listeners.dragend({ latLng: { lng: 180, lat: 90 } }) // 闭区间端点合法

    expect(onCenterChange).toHaveBeenCalledTimes(3)
    expect(h.warnings).toEqual([])
  })

  /* TC-R12：本文件曾是「样式盲区」三兄弟之一 —— `setMapStyleV2` 写成空桩，
     底图样式怎么改这里都全绿。这条用例钉的是**眼睛本身**：样式必须真的被下发过。
     色值对不对不归本文件管（那是 roadContrast.test.ts 带锚点阈值的职责）。 */
  it('底图样式确实被下发且结构自洽（夹具眼睛哨兵，非空桩）', async () => {
    await mountMap(vi.fn())
    assertBasemapStylesSound()
  })
})
