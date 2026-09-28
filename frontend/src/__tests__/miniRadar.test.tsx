// @vitest-environment jsdom
/**
 * C3 · MiniRadar 顶部简易雷达 · 全维度渲染测试（覆盖方案 TC-07..14）
 *
 * ⚠️ 本文件历史上出过一次"把绷带当目标态"的错，记录以免重演：
 *    旧 TC-09 断言「最左=start、最右=end」，那正是 `MiniRadar.tsx` 为把标签硬塞进
 *    过小的 184×172 画布而做的 `text-anchor` **反向翻转**（与常规约定相反）。
 *    它让左右两端不再出界，代价是 6/8 个标签压进多边形（真实 Chrome 实测最深 −11.37），
 *    而上下两端依旧被裁（菜市场 −7.37、养老 −10.61）。
 *    头注释里那句「顶部=middle（不溢出 viewBox）」是**从未被断言、且当时为假**的宣称。
 *    现在画布由 `layoutRadar` 按标签派生，翻转不再需要，TC-09 已按真实意图翻正。
 *
 * 守护契约：
 *  - INV-全维：渲染全部 `scores.radar` 维度（去掉 slice 截断）
 *  - INV-轴数：辐条数与维度数、数据多边形同步
 *  - BD-边界：标签锚点朝外，且不溢出 —— 由 TC-14 逐标签量 bbox 兜底
 *  - EQ-空：radar=[]（离线）渲染为空，不崩
 *  - 反硬编码：viewBox 必须等于 `layoutRadar` 的输出（TC-12），防止"只修 lib 不修组件"
 *
 * ⚠️ 裁判强度分级（本文件三条新用例各自能抓什么、抓不到什么）：
 *  - TC-12 **接线锁**，不是量尺：只抓"组件把 viewBox 写回常量"，几何本身错了它照样绿。
 *  - TC-13 **前提在 jsdom 外**：它锁 `w-full` + `maxWidth=派生宽度`，但 jsdom 里没有卡片，
 *    所以卡片实际多宽它一概不知 —— "标签不低于 11px"这条得靠真浏览器量（见 radarLayout.test.ts
 *    头注释里的复验出口）。别把 TC-13 绿当成字号已验证。
 *  - TC-14 **半自证**：它用 `estimateTextBox` 重算组件刚从 `layoutRadar` 写出的 DOM 属性，
 *    因此只能抓"组件与库不一致"，抓不到"估算器与 Chrome 真实度量漂移"。
 *    估算器本身对 Chrome 的责任在 `radarLayout.test.ts` + 真浏览器量尺两侧，别只信这里。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { layoutRadar } from '../lib/radarLayout'
import { estimateTextBox } from '../lib/textMetrics'
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

  it('TC-09 8 维标签锚点朝外（远离圆心方向展开），裁切由派生 viewBox 兜底而非靠翻转文字方向', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const ts = textsOf(container)
    expect(ts.length).toBeGreaterThanOrEqual(8)
    const leftmost = ts.reduce((p, c) => (+c.getAttribute('x')! < +p.getAttribute('x')! ? c : p))
    const rightmost = ts.reduce((p, c) => (+c.getAttribute('x')! > +p.getAttribute('x')! ? c : p))
    const top = ts.reduce((p, c) => (+c.getAttribute('y')! < +p.getAttribute('y')! ? c : p))
    // 与旧实现相反：左边缘 end（向左展开）、右边缘 start（向右展开）。
    // 常规约定下文字朝外生长，所以它必须靠画布派生来容纳 —— 这正是 radarLayout 的职责。
    expect(leftmost.getAttribute('text-anchor')).toBe('end')
    expect(rightmost.getAttribute('text-anchor')).toBe('start')
    expect(top.getAttribute('text-anchor')).toBe('middle')
  })

  it('TC-10 空 radar（离线）渲染为空、不崩，且 viewBox 仍有效', () => {
    const empty = { scores: { radar: [] } } as unknown as LivingCircleReport
    const { container } = render(<MiniRadar report={empty} />)
    expect(textsOf(container)).toHaveLength(0)
    // 空态也不能吐 `0 0 NaN NaN`：ComparePage 的卡片直接映射用户选的任意历史体检记录
    expect(container.querySelector('svg')!.getAttribute('viewBox')).toMatch(/^0 0 \d+ \d+$/)
  })

  it('TC-12 viewBox 等于 layoutRadar 的输出（反硬编码锁：只修 lib 不修组件会在此红）', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const rendered = container.querySelector('svg')!.getAttribute('viewBox')
    expect(rendered).toBe(layoutRadar(kaili.scores.radar).viewBox)
  })

  it('TC-13 尺寸契约：w-full + maxWidth=派生宽度，使 1 单位 ≈ 1 CSS px', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const svg = container.querySelector('svg')!
    const layout = layoutRadar(kaili.scores.radar)
    expect(svg.classList.contains('w-full')).toBe(true)
    // React 对 maxWidth 自动补 px；锁住它是为了守住"标签不缩到 8px"这个设计决定
    expect(svg.style.maxWidth).toBe(`${layout.width}px`)
  })

  it('TC-14 每个标签的字形盒都落在渲染出的 viewBox 内（从 DOM 属性重算）', () => {
    const { container } = render(<MiniRadar report={kaili} />)
    const svg = container.querySelector('svg')!
    const [, , w, h] = svg.getAttribute('viewBox')!.split(' ').map(Number)
    for (const t of textsOf(container)) {
      const fontSize = Number(t.getAttribute('font-size'))
      const box = estimateTextBox(t.textContent!, fontSize)
      const x = Number(t.getAttribute('x'))
      const y = Number(t.getAttribute('y'))
      const anchor = t.getAttribute('text-anchor')
      const x0 = anchor === 'start' ? x : anchor === 'end' ? x - box.w : x - box.w / 2
      expect(x0, `${t.textContent} 左出界`).toBeGreaterThanOrEqual(0)
      expect(x0 + box.w, `${t.textContent} 右出界`).toBeLessThanOrEqual(w)
      expect(y - box.ascent, `${t.textContent} 上出界`).toBeGreaterThanOrEqual(0)
      expect(y + box.descent, `${t.textContent} 下出界`).toBeLessThanOrEqual(h)
    }
  })
})