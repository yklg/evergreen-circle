// @vitest-environment jsdom
/**
 * C3 · MiniRadar 顶部简易雷达 · 全维度渲染测试（覆盖方案 TC-07..10）
 *
 * ⚠️ TDD 红线：当前 MiniRadar 还是 `scores.radar.slice(0,6)`（6 轴）且标签全部
 *    `textAnchor="middle"`，本文件按其**目标态**（全 8 维 + 边缘标签角度翻转）
 *    断言，实施 C3 后自动转绿。
 *
 * 守护契约：
 *  - INV-全维：渲染全部 `scores.radar` 维度（去掉 slice 截断）
 *  - INV-轴数：辐条数与维度数、数据多边形同步
 *  - BD-边界：8 维时最左标签 text-anchor=end、最右=start、顶部=middle（不溢出 viewBox）
 *  - EQ-空：radar=[]（离线）渲染为空，不崩
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import type { LivingCircleReport } from '../types'

const kaili = getLivingCircleReportMock('lc-kaili')?.living_circle as LivingCircleReport
const DIM8 = kaili.scores.radar.length // 凯里老街 = 8

function textsOf(c: HTMLElement): SVGTextElement[] {
  return Array.from(c.querySelectorAll<SVGTextElement>('svg text'))
}

describe('MiniRadar · 顶部简易雷达', () => {
  it(`TC-07 渲染全部雷达维度（无 slice 截断）：标签数 === 维度数(${DIM8})`, () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const labels = textsOf(container).map((t) => t.textContent)
    expect(labels.length).toBe(DIM8)
    expect(new Set(labels).size).toBe(DIM8) // 维度不重复
    // 每个真实维度名都出现在标签里（漏维即红）
    for (const r of kaili.scores.radar) {
      expect(labels).toContain(r.dimension)
    }
  })

  it('TC-08 轴数=维数：辐条 line 数=DIM8，多边形总数为 4（3 网格 + 1 数据）', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    expect(container.querySelectorAll('svg line').length).toBe(DIM8)
    expect(container.querySelectorAll('svg polygon').length).toBe(4)
  })

  it('TC-09 8 维边缘标签按角度翻转 text-anchor：最左=start、最右=end、顶部=middle（文本留在视口内）', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const ts = textsOf(container)
    expect(ts.length).toBeGreaterThanOrEqual(8)
    const leftmost = ts.reduce((p, c) => (+c.getAttribute('x')! < +p.getAttribute('x')! ? c : p))
    const rightmost = ts.reduce((p, c) => (+c.getAttribute('x')! > +p.getAttribute('x')! ? c : p))
    const top = ts.reduce((p, c) => (+c.getAttribute('y')! < +p.getAttribute('y')! ? c : p))
    // 左边缘标签应 start（向右展开避免超出 viewBox 左边界），右边缘应 end，顶部应 middle
    expect(leftmost.getAttribute('text-anchor')).toBe('start')
    expect(rightmost.getAttribute('text-anchor')).toBe('end')
    expect(top.getAttribute('text-anchor')).toBe('middle')
  })

  it('TC-10 空 radar（离线）渲染为空且不崩', () => {
    const empty = { scores: { radar: [] } } as unknown as LivingCircleReport
    const { container } = render(<MiniRadar report={empty} />)
    expect(textsOf(container)).toHaveLength(0)
  })
})