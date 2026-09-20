// @vitest-environment jsdom
/** F5 · NormalizedOverlay 归一化圈形对比示意：跨城时 A/B 各居其城、同框叠加、明示 banner。 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NormalizedOverlay } from '../components/lifecircle/NormalizedOverlay'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'

const [kai_, jin] = SAMPLE_COMMUNITIES
const a = kai_.report
const b = jin.report

describe('NormalizedOverlay', () => {
  it('渲染 A/B 社区名、归一化说明与 banner（两圈中心归一对齐）', () => {
    render(<NormalizedOverlay a={a} b={b} />)
    expect(screen.getAllByText('圈形对比 · 归一化示意').length).toBeGreaterThan(0)
    expect(screen.getByText(/两圈中心已归一对齐/)).toBeTruthy()
    // A/B 各自名称出现（SVG 文本 + 图例）
    expect(screen.getAllByText(new RegExp(a.scene.name)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(new RegExp(b.scene.name)).length).toBeGreaterThan(0)
  })

  it('SVG 内同时绘制 A（绿系）与 B（蓝系）两家等时圈族，且不产生 NaN 坐标', () => {
    const { container } = render(<NormalizedOverlay a={a} b={b} />)
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
    const polys = svg!.querySelectorAll('polygon')
    // 两家各自 ≥4 条圈（5/10/15/20min），全部坐标可用
    expect(polys.length).toBeGreaterThanOrEqual(8)
    for (const p of Array.from(polys)) {
      expect(p.getAttribute('points')).toBeTruthy()
      expect(p.getAttribute('points')!).not.toContain('NaN')
    }
  })

  it('等高线式编码：填充降级为极低透明度弱染、圈结构交给描边（stroke-width ≥2）', () => {
    const { container } = render(<NormalizedOverlay a={a} b={b} />)
    const svg = container.querySelector('svg')!
    const polys = Array.from(svg.querySelectorAll('polygon')).filter(
      (p) => !p.hasAttribute('fill') || p.getAttribute('fill') === 'none',
    )
    const halo = Array.from(svg.querySelectorAll('polygon')).filter((p) => p.getAttribute('fill') === 'none')
    expect(halo.length).toBeGreaterThanOrEqual(4) // 顶层小场景的 4 条圈各配一层白 halo
    const strokes = polys.map((p) => Number(p.getAttribute('stroke-width')))
    expect(strokes.every((s) => s >= 2)).toBe(true) // 圈层以描边表达
    // 实心填充多边形透明度极低（<0.1），不再用 fill 抢占结构
    const colorPolys = Array.from(svg.querySelectorAll('polygon')).filter((p) => p.getAttribute('fill') && p.getAttribute('fill') !== 'none')
    expect(colorPolys.length).toBeGreaterThanOrEqual(8)
    for (const p of colorPolys) {
      const m = /rgba\(\s*\d+,\s*\d+,\s*\d+,\s*([0-9.]+)\s*\)/.exec(p.getAttribute('fill')!)
      expect(m).toBeTruthy()
      expect(Number(m![1])).toBeLessThan(0.1)
      expect(Number(p.getAttribute('stroke-width'))).toBeGreaterThanOrEqual(2)
    }
  })

  it('面积尺度由图例承载：图例内出现 A/B 各自名称与 15min 面积数值', () => {
    const { container } = render(<NormalizedOverlay a={a} b={b} />)
    const a15 = a.isochrones.find((z) => z.minutes === 15)!.area_km2.toFixed(2)
    const b15 = b.isochrones.find((z) => z.minutes === 15)!.area_km2.toFixed(2)
    const legend = container.querySelector('[data-testid="overlay-legend"]')!
    expect(legend).toBeTruthy()
    const texts = Array.from(legend.querySelectorAll('text')).map((t) => t.textContent ?? '')
    expect(texts.some((s) => s.includes(`${a.scene.name} · ${a15} km²`))).toBe(true)
    expect(texts.some((s) => s.includes(`${b.scene.name} · ${b15} km²`))).toBe(true)
  })

  it('图例嵌入 SVG 内部：opaque 面板含圆点·A/B·短线与名称面积', () => {
    const { container } = render(<NormalizedOverlay a={a} b={b} />)
    const svg = container.querySelector('svg')!
    const legend = svg.querySelector('[data-testid="overlay-legend"]')!
    expect(legend).toBeTruthy()
    // 白底面板 rect 存在
    expect(legend.querySelector('rect')).toBeTruthy()
    // A/B 锚点字母在图例中均有
    const ls = Array.from(legend.querySelectorAll('text')).map((t) => t.textContent)
    expect(ls).toContain('A')
    expect(ls).toContain('B')
    // 中心彩色锚点存在（含字母 A/B 的圆形）
    const anchors = Array.from(svg.querySelectorAll('circle')).filter((c) => Number(c.getAttribute('r')) === 11)
    expect(anchors.length).toBe(2)
  })

  it('外层限宽 max-w-[520px] 居中，标题行不再携带图例', () => {
    const { container } = render(<NormalizedOverlay a={a} b={b} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain('max-w-[520px]')
    expect(root.className).toContain('mx-auto')
    // 标题行（SVG 之外的卡片头部）不含面积文本，图例只存在于 SVG 内
    const svg = container.querySelector('svg')!
    const outsideSvg = Array.from(container.querySelectorAll('text')).filter((t) => !svg.contains(t))
    for (const t of outsideSvg) expect(t.textContent).not.toContain('km²')
  })
})