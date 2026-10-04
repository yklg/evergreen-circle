// @vitest-environment jsdom
/**
 * LcMap 局部视图焦点过滤（计划笔 8 · 盲区章第二张图）。
 *
 * 报告体检单里那张局部图的全部依据是 `focusBlindspotId` 这一条 prop，而它有两个必须钉住的性质：
 *   ① **只削盲区图层**——设施点、等时圈、中心点照旧，否则图注「同主图」就是假的；
 *   ② **保住 `#N` 编号**——编号是读者在「盲区清单 ↔ 图面」之间对号的唯一凭据。
 *      一旦实现成 `blindspots.filter(...).map(...)`（先筛后编号，下标被重排），
 *      第 2 处就会被标成 `#1`，与清单首行打架；满屏图层里肉眼看不出来，只有断言拦得住。
 *
 * 夹具 `kaili-ev2` 只有 1 处盲区 ⇒ 复制成 2 处：两份**除 id 外逐字段相同**（真实
 * gap/affected/fixes 全保留，不造空壳），焦点故意选**第二处**。复制只为"有第二处可削"，
 * 判据仍取生产函数 `blindTitle()` 的实际产物。
 *
 * 走降级画布分支（同 `lcMapDesensitize.test.tsx`：`getMapConfig` 空 AK ⇒ `setMode('fallback')`），
 * 纯 SVG 可在 jsdom 直接查 DOM，不依赖 BMapGL 与外网。
 * ⚠️ 效力上限：降级画布不做重投影聚焦（`LcMap` 的 prop 注释已写明），所以本用例验的是
 *    **图层裁剪**，zoom 16 的视口收拢只在真机 live 分支生效，这里证不了。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import kailiEv2 from '../mocks/fixtures/livingCircle/kaili-ev2.json'
import { blindSevSpec, severityOf } from '../lib/livingCircle'
import type { BlindSpot, LivingCircleReport } from '../types'

vi.mock('../lib/bmap', () => ({
  // 空 AK ⇒ LcMap 落 fallback 静态画布
  getMapConfig: async () => ({ browserAk: '', mapStyleId: '' }),
  loadBMapGL: async () => {
    throw new Error('测试内不应注入 BMapGL')
  },
  geolocateMe: async () => null,
}))

const { default: LcMap, blindTitle } = await import('../components/lifecircle/LcMap')

const base = kailiEv2 as unknown as LivingCircleReport
const ONE = base.blindspots[0] as BlindSpot
const IDS = ['bs-甲-1', 'bs-乙-2'] as const
const twin = (id: string): BlindSpot => ({ ...ONE, id })
const report = { ...base, blindspots: IDS.map(twin) } as LivingCircleReport
const SEV_LABEL = blindSevSpec(severityOf(ONE) || undefined).label

/** 画面上「属于某处盲区」的浮层标题（`blindTitle()` 以 id 开头，据此认领）。 */
function drawnBlindIds(): string[] {
  const titles = Array.from(document.querySelectorAll('title')).map((t) => t.textContent ?? '')
  return IDS.filter((id) => titles.some((s) => s.startsWith(id)))
}
/** 图面 `#N·严重度` 编号批注，按出现顺序。 */
function numLabels(): string[] {
  return Array.from(document.querySelectorAll('text'))
    .map((t) => t.textContent ?? '')
    .filter((s) => /^#\d+·/.test(s))
}
/** 非盲区层的浮层标题集合 —— 局部视图不该动它，逐字比对。
 *  按**整棵盲区分组**排除：盲区组 `<g key={b.id}>` 里除了面和中心点，还装着 `#N` 批注
 *  与绿核补点（补点标题不带 id，第一轮只按 id 过滤时它被错算进"其它层"，
 *  于是 focus 少画一个补点反倒"挂了"——那是分类错，不是实现错）。 */
function otherLayerTitles(): string {
  const svg = document.querySelector('svg')
  expect(svg, '降级画布没渲染 ⇒ 本用例失去基线').toBeTruthy()
  const isBlindGroup = (el: Element) => IDS.some((id) => (el.textContent ?? '').includes(id))
  return Array.from(svg!.children)
    .filter((el) => !isBlindGroup(el))
    .flatMap((el) => Array.from(el.querySelectorAll('title')))
    .map((t) => t.textContent ?? '')
    .sort()
    .join('|')
}

async function render_(props: Record<string, unknown> = {}) {
  cleanup()
  render(<LcMap report={report} {...props} />)
  for (let i = 0; i < 4; i += 1) await new Promise((r) => setTimeout(r, 0))
}

beforeEach(() => {
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

afterEach(() => cleanup())

describe('LcMap · 局部视图焦点过滤（笔 8）', () => {
  it('前置自证：夹具盲区字段够真、两份副本 id 可区分、不传 focus 时两处都画', async () => {
    // 复制出来的两份若 title 相同，下面的"只画一处"就是空断言
    expect(blindTitle(twin(IDS[0]))).not.toBe(blindTitle(twin(IDS[1])))
    expect(base.blindspots).toHaveLength(1)
    await render_()
    expect(drawnBlindIds()).toEqual([...IDS])
    expect(numLabels()).toEqual([`#1·${SEV_LABEL}`, `#2·${SEV_LABEL}`])
    // 等时圈档数与夹具一致 ⇒ 非盲区层确实有东西可被"误削"
    expect(base.isochrones.length).toBeGreaterThan(1)
  })

  it('focus 第二处 ⇒ 只画那一处，编号仍是 #2（不是被重排成 #1）', async () => {
    await render_({ focusBlindspotId: IDS[1] })
    expect(drawnBlindIds()).toEqual([IDS[1]])
    expect(numLabels(), '`#N` 被重排 ⇒ 与盲区清单对不上号').toEqual([`#2·${SEV_LABEL}`])
  })

  it('局部视图只削盲区图层：其余各层的浮层标题一字不差', async () => {
    await render_()
    const all = otherLayerTitles()
    // 基线自证：比对集既不能空（否则"一字不差"是空话），也不能混进盲区组的東西
    expect(all.split('|').length, '非盲区层标题太少 ⇒ 断言失去效力').toBeGreaterThan(50)
    expect(all).not.toContain('补小学')
    await render_({ focusBlindspotId: IDS[1] })
    expect(otherLayerTitles()).toBe(all)
    expect(document.body.textContent).toContain(report.scene.name)
  })

  it('focus 一处不存在也安全落回（不抛、不画任何盲区层）', async () => {
    await render_({ focusBlindspotId: 'bs-查无此处' })
    expect(drawnBlindIds()).toEqual([])
    expect(numLabels()).toEqual([])
  })
})
