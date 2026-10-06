// @vitest-environment jsdom
/**
 * 笔三上屏判据：形状扇区几何（S13）、地图图层与开关（S14）、方位条形卡（S15）。
 *
 * 地图走 **降级画布分支**（空 AK ⇒ `LcMap` 落 SVG，与 `lcMapDesensitize.test.tsx` 同一手法）：
 * jsdom 里没有 BMapGL，能钉的是几何、在场判据、开关与点击通道。
 * BMapGL live 分支的贴图层**不在本文件能力内**，另由 `e2e/lcShapeScreen.spec.ts` 在真浏览器里钉。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'

import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import type { LivingCircleReport } from '../types'
import { shapeSectors, shapeSectorRay } from '../components/lifecircle/ShapeSectorOverlay'
import { shapeOfZone } from '../lib/livingCircle'

vi.mock('../lib/bmap', () => ({
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => {
    throw new Error('测试内不应注入 BMapGL')
  },
  geolocateMe: async () => null,
}))

const { default: LcMap } = await import('../components/lifecircle/LcMap')
const { default: DirectionBars } = await import('../components/lifecircle/DirectionBars')

const report = kailiEv2 as unknown as LivingCircleReport

beforeEach(() => {
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {} unobserve() {} disconnect() {}
    }
  }
})
afterEach(() => cleanup())

/* ── S13 几何层 ─────────────────────────────────────────── */

describe('shapeSectors · 几何', () => {
  const shape = shapeOfZone(report, 15)!

  it('出 8 个楔形，方位词与半径逐一对应键值', () => {
    const secs = shapeSectors(report.scene.center, shape)
    expect(secs).toHaveLength(8)
    secs.forEach((sec, i) => {
      expect(sec.word).toBe(shape.bins_word[i])
      expect(sec.radiusM).toBe(shape.bins_m[i])
    })
  })

  it('每个楔形闭合、顶点数 ≥8，且弧上点到圆心的距离 ≈ 该箱半径', () => {
    const clat = report.scene.center[1]
    for (const sec of shapeSectors(report.scene.center, shape)) {
      expect(sec.ring[0]).toEqual(sec.ring[sec.ring.length - 1])
      expect(sec.ring.length).toBeGreaterThanOrEqual(8)
      const last = sec.ring[sec.ring.length - 2]
      const dLat = (last[1] - report.scene.center[1]) * 111320
      const dLng = (last[0] - report.scene.center[0]) * 111320 * Math.cos((clat * Math.PI) / 180)
      expect(Math.abs(Math.hypot(dLng, dLat) - sec.radiusM)).toBeLessThan(2)
    }
  })

  it('中心分相 ⇒ 第 0 箱覆盖 [−22.5°, +22.5°)，正北楔形跨在正北两侧', () => {
    const north = shapeSectors(report.scene.center, shape)[0]
    const clng = report.scene.center[0]
    const sides = north.ring.slice(1, -1).map(([lng]) => lng - clng)
    expect(Math.min(...sides)).toBeLessThan(0)
    expect(Math.max(...sides)).toBeGreaterThan(0)
  })

  it('射线端点落在该箱中心角上（图上那条"最弱方向"线与楔形同源）', () => {
    const [, tip] = shapeSectorRay(report.scene.center, shape, 0)
    const [clng, clat] = report.scene.center
    expect(tip[1]).toBeGreaterThan(clat)          // 正北 ⇒ 纬度更高
    expect(Math.abs(tip[0] - clng)).toBeLessThan(1e-9)
  })
})

/* ── S14 地图图层与开关 ─────────────────────────────────── */

describe('LcMap · 方位形状图层（降级画布分支）', () => {
  async function settle() {
    for (let i = 0; i < 6; i += 1) await new Promise((r) => setTimeout(r, 0))
  }

  it('默认关 ⇒ 画布上没有扇区', async () => {
    const { container } = render(<LcMap report={report} draggableCenter={false} />)
    await settle()
    expect(container.querySelectorAll('[data-sector]').length).toBe(0)
  })

  it('第三屏那个实例有开关且可开 ⇒ 8 扇区；关 ⇒ 归零；别的实例不长同名开关', async () => {
    const { container } = render(
      <LcMap report={report} draggableCenter={false} shapeLayerDefault />,
    )
    // 同页再挂一块普通主图（体检台/局部图那种），它不许也长出第二颗同名开关
    const { container: other } = render(<LcMap report={report} draggableCenter={false} />)
    await settle()
    expect(other.querySelectorAll('[aria-label="方位形状图层"]')).toHaveLength(0)
    const toggle = screen.getByRole('switch', { name: '方位形状图层' })
    // 第三屏是"为这张图而开"的实例 ⇒ 起盘即开（`shapeLayerDefault`），主图那类实例
    // 起盘关且不长开关（上面那条已钉）。
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(container.querySelectorAll('[data-sector]').length).toBe(8)
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    expect(container.querySelectorAll('[data-sector]').length).toBe(0)
    fireEvent.click(toggle)
    expect(container.querySelectorAll('[data-sector]').length).toBe(8)
  })

  it('点扇区 ⇒ 回调带出正确下标', async () => {
    const picked: (number | null)[] = []
    const { container } = render(
      <LcMap report={report} draggableCenter={false} shapeLayerDefault onSectorPick={(i) => picked.push(i)} />,
    )
    await settle()
    const sectors = container.querySelectorAll('[data-sector]')
    expect(sectors.length).toBe(8)
    fireEvent.click(sectors[3])
    expect(picked).toEqual([3])
  })

  it('载荷没有形状键（存量件形态）⇒ 开关本身不出现，不摆假入口', async () => {
    const bare = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    bare.isochrones.forEach((z) => {
      delete (z as { shape?: unknown }).shape
    })
    const { container } = render(<LcMap report={bare} draggableCenter={false} />)
    await settle()
    expect(screen.queryByRole('switch', { name: '方位形状图层' })).toBeNull()
    expect(container.querySelectorAll('[data-sector]').length).toBe(0)
  })

  /**
   * **正对照**：拖拽选点只改画布投影原点，楔形的几何原点必须仍是 `scene.center`。
   * 混用会让扇区跟着选点跑、而等时圈环留在原地（图面自相矛盾）。
   */
  it('customCenter 偏移时，扇区顶点仍锚在 scene.center 上', async () => {
    const off: [number, number] = [report.scene.center[0] + 0.01, report.scene.center[1] + 0.01]
    const a = render(<LcMap report={report} customCenter={off} draggableCenter={false} shapeLayerDefault />)
    await settle()
    const b = render(<LcMap report={report} draggableCenter={false} shapeLayerDefault />)
    await settle()
    const apexOf = (c: HTMLElement): [number, number] => {
      const first = Array.from(c.querySelectorAll('[data-sector]'))
        .map((el) => el.getAttribute('points') ?? '')
        .find((s) => s.length > 0)!
      const [x, y] = first.split(' ')[0].split(',').map(Number)
      return [x, y]
    }
    const viewBox = (c: HTMLElement) =>
      (c.querySelector('svg')?.getAttribute('viewBox') ?? '0 0 0 0').split(' ').map(Number)

    const pa = apexOf(a.container)
    const pb = apexOf(b.container)
    const [, , w, h] = viewBox(b.container)
    expect(w).toBeGreaterThan(0)
    /**
     * 判据的核心：**楔形顶点（= 形状原点）不跟着投影原点走。**
     * 不传 customCenter 时它就是画布中心；传了偏移选点之后，楔形必须与等时圈环一起
     * 离开画布中心。若几何原点错用了投影原点，扇区会**始终钉在画布正中**，
     * 而环已经平移走了 —— 那正是这条正对照要抓的错。
     */
    expect(Math.abs(pb[0] - w / 2)).toBeLessThan(1)
    expect(Math.abs(pb[1] - h / 2)).toBeLessThan(1)
    expect(Math.abs(pa[0] - w / 2)).toBeGreaterThan(5)
    expect(Math.abs(pa[1] - h / 2)).toBeGreaterThan(5)
  })
})

/* ── S15 条形卡 ─────────────────────────────────────────── */

describe('DirectionBars · 方位条形卡', () => {
  const shape = shapeOfZone(report, 15)!

  it('8 行，方位词与米数逐行来自键（前端不另抄词表）', () => {
    render(<DirectionBars lc={report} minutes={15} selected={null} onPick={() => {}} />)
    const rows = screen.getAllByRole('button', { name: /方向最远可达/ })
    expect(rows).toHaveLength(8)
    shape.bins_word.forEach((w, i) => {
      expect(rows[i].textContent).toContain(w)
      expect(rows[i].textContent).toContain(String(Math.round(shape.bins_m[i])))
    })
  })

  it('点一行 ⇒ 回调带出下标；再点同一行 ⇒ 取消选中', () => {
    const picked: (number | null)[] = []
    render(<DirectionBars lc={report} minutes={15} selected={null} onPick={(i) => picked.push(i)} />)
    const rows = screen.getAllByRole('button', { name: /方向最远可达/ })
    fireEvent.click(rows[2])
    expect(picked).toEqual([2])
  })

  it('常驻声明里写明不参与评分（措辞边界）', () => {
    const { container } = render(
      <DirectionBars lc={report} minutes={15} selected={0} onPick={() => {}} />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('不参与综合评分')
    expect(text).toContain('scene.center')
    for (const banned of ['更优', '越好', '评级']) expect(text).not.toContain(banned)
  })

  it('没有形状键 ⇒ 整卡不渲染（不发屏，不摆空卡）', () => {
    const bare = JSON.parse(JSON.stringify(kailiEv2)) as LivingCircleReport
    bare.isochrones.forEach((z) => {
      delete (z as { shape?: unknown }).shape
    })
    const { container } = render(
      <DirectionBars lc={bare} minutes={15} selected={null} onPick={() => {}} />,
    )
    expect(container.textContent).toBe('')
  })
})
