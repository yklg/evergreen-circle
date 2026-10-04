// @vitest-environment jsdom
/**
 * LcMap 分享脱敏入口（计划 P0-5）。
 *
 * 为什么单独一条文件：`?share=1` 的报告页是**公开可读、无鉴权**的
 * （`ShareModal.tsx:4`「报告页公开可读，无需鉴权」），而批次三要把 LcMap 嵌进报告页。
 * 嵌图之前必须先有脱敏入口，否则公开链接会画出盲区逐格边界、并在悬停/点卡里给出
 * 缺口指数、受估户数人数与实测步行耗时 —— 那正是报告静态快照口径 ③-A 一直挡掉的粒度
 * （`LifeCircleReportView.tsx` 的 `BlindCoarseCircle` + `概略片区` + 隐藏 gap）。
 *
 * 判据取 `blindTitle()` 的实际产物（`LcMap.tsx:125-141`）：
 *   `… · 缺口 0.262 · 步行 13.4min（实测） · 采样14点 · 估839人 · 建议补小学·P1`
 * 脱敏前必须出现「估839人」，脱敏后必须**完全不出现**，且改出现「面积当量」折算。
 * 只断"传了 prop"就是空桩 —— 这里断的是渲染结果。
 *
 * 走降级画布分支（`getMapConfig` 返回空 AK ⇒ `setMode('fallback')`，`LcMap.tsx:491-493`）：
 * 纯 SVG，可在 jsdom 里直接查 DOM，不依赖 BMapGL 与外网。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import type { LivingCircleReport } from '../types'

vi.mock('../lib/bmap', () => ({
  // 空 AK ⇒ LcMap 落 fallback 静态画布（与 e2e mock 的 map-config 同一形态）
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => {
    throw new Error('测试内不应注入 BMapGL')
  },
  geolocateMe: async () => null,
}))

const { default: LcMap } = await import('../components/lifecircle/LcMap')

const report = kailiEv2 as unknown as LivingCircleReport
/** `blindTitle()` 会带出的高粒度串（逐字取自夹具实算值）。 */
const PRECISE = ['估839人', '缺口 0.262', '采样14点']

async function settle() {
  // 让 getMapConfig 的 microtask 与 setMode 引发的重渲染落地
  await actAsync()
}
async function actAsync() {
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
}

beforeEach(() => {
  // LcMap 里用了 performance.now / ResizeObserver，jsdom 下给最小实现
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

afterEach(() => {
  cleanup()
})

describe.skipIf(!report.blindspots?.length)('LcMap · 分享脱敏（P0-5）', () => {
  it('前置自证：夹具盲区确实带着高粒度字段（否则下面两条都是空桩）', async () => {
    const b = report.blindspots[0]
    expect((b.affected as { estimated_residents?: number })?.estimated_residents).toBe(839)
    expect(b.gap_score).toBeCloseTo(0.262, 3)
    await render_({})
    await settle()
    const html = document.body.innerHTML
    for (const s of PRECISE) {
      expect(html).toContain(s)
    }
  })

  it('desensitize=true ⇒ 高粒度读数全部消失，盲区面换成面积等价圆', async () => {
    await render_({ desensitize: true })
    await settle()
    const html = document.body.innerHTML
    for (const s of PRECISE) {
      expect(html, `脱敏后仍暴露「${s}」`).not.toContain(s)
    }
    // 折算口径与报告静态快照同源（coarseBlindFootprint：√(area_m2/π) 与「面积当量」措辞）
    expect(html).toContain('面积当量')
    // 降级画布是另一棵根节点（`data-lc-map` 只挂在 live 分支的容器上，LcMap.tsx:1468）
    // ⇒ 本用例只渲染 LcMap 一个组件，直接全局查 ellipse。
    expect(document.querySelectorAll('ellipse').length).toBeGreaterThan(0)
  })

  it('两条路径共用同一折算：脱敏半径 = √(area_m2/π) 的像素当量', async () => {
    await render_({ desensitize: true })
    await settle()
    const fm = report.blindspots[0].footprint_meta as { area_m2: number }
    const radiusM = Math.sqrt(fm.area_m2 / Math.PI)
    // 降级画布用 LC_CANVAS（860×620 ÷ R 2500）横纵各自换算 ⇒ 是椭圆不是正圆
    const rx = (radiusM * (860 / 2)) / 2500
    const ry = (radiusM * (620 / 2)) / 2500
    const el = Array.from(document.querySelectorAll('ellipse'))
      .map((e) => [Number(e.getAttribute('rx')), Number(e.getAttribute('ry'))] as const)
      .find(([a, b]) => a > 0 && b > 0)
    expect(el, '没找到概略片区椭圆 ⇒ 脱敏分支没生效').toBeTruthy()
    expect(el![0]).toBeCloseTo(rx, 1)
    expect(el![1]).toBeCloseTo(ry, 1)
  })
})

async function render_(props: Record<string, unknown>) {
  cleanup()
  render(<LcMap report={report} {...props} />)
  return null
}
