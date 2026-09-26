// @vitest-environment jsdom
/**
 * 「本章内容结构」退化态渲染（架构级修复的 C 段，用户 2026-09-21 裁决）。
 *
 * 背景：同一渲染器 ChapterMindmapSvg 在「四字段全空但有正文」时按 §6.0.6 降级为
 * 单分支「正文 → N 段」，三个盒子的连线被用户误读成「流程图」。
 * 契约（仅新报告有 structure_status，老报告 undefined 按 by_design 兜底）：
 *   - lost      → 不画 SVG，一行「本章结构提炼失败 · 正文 N 段完整」
 *   - by_design → 不画 SVG，一行「本章未产出可结构化要点 · 正文 N 段」
 *   - undefined → 同 by_design（老报告无此字段，不做迁移）
 *   - ok / repaired → 照常画 SVG（repaired 已有结构，不会走到说明分支）
 *   - 全空且无正文 → 组件整体不渲染（沿用既有行为）
 *   - summary 模式不受影响（仍是芯片态，内容源共用 chapterMapLeaves）
 *   - score_gap（T-13′）→ 一行「评分维度缺可核验数据 · <原因>」，**与 lost 正交**：
 *     结构完好的章节照样可以缺算分输入，折叠态也照常显示（结论面不藏在折叠后面）
 *
 * 选择器用 `svg[role="img"]`：折叠按钮的 lucide X 图标也是 <svg>，只数 svg 会误判。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { ChapterContentMap } from '../components/ChapterContentMap'
import type { ReportSection } from '../types'

afterEach(() => {
  cleanup()
})

const mk = (over: Partial<ReportSection>): ReportSection => ({
  id: 's1',
  title: '交通与抵达',
  level: 1,
  ...over,
})

/** 导图 SVG（ChapterMindmapSvg 的 role="img" + aria-label），区别于图标 svg */
const mindmapOf = (c: HTMLElement) => c.querySelector('svg[role="img"]')

const DEGRADED_NOTE_LOST = '本章结构提炼失败'
const DEGRADED_NOTE_BY_DESIGN = '本章未产出可结构化要点'

describe('ChapterContentMap（detail 模式：退化态换一行说明）', () => {
  it('lost → 不画 SVG，说明文案点明「结构提炼失败」与正文段数', () => {
    const { container } = render(
      <ChapterContentMap
        section={mk({
          structure_status: 'lost',
          paragraphs: Array(6).fill('p'),
          charts: [{ chart_id: 'c', type: 'bar', title: '图', data: {} }] as never,
        })}
      />
    )
    expect(mindmapOf(container)).toBeNull()
    expect(container.textContent).toContain(DEGRADED_NOTE_LOST)
    expect(container.textContent).toContain('正文 6 段完整')
  })

  it('by_design → 不画 SVG，说明文案为「本章未产出可结构化要点」', () => {
    const { container } = render(
      <ChapterContentMap
        section={mk({ structure_status: 'by_design', paragraphs: Array(3).fill('p') })}
      />
    )
    expect(mindmapOf(container)).toBeNull()
    expect(container.textContent).toContain(DEGRADED_NOTE_BY_DESIGN)
    expect(container.textContent).toContain('正文 3 段')
  })

  it('无 structure_status（老报告 r_f2cc14fd 形态）→ 按 by_design 兜底，不再画伪导图', () => {
    const { container } = render(
      <ChapterContentMap section={mk({ paragraphs: Array(6).fill('p') })} />
    )
    expect(mindmapOf(container)).toBeNull()
    expect(container.textContent).toContain(DEGRADED_NOTE_BY_DESIGN)
    expect(container.textContent).toContain('正文 6 段')
    expect(container.textContent).not.toContain(DEGRADED_NOTE_LOST)
  })

  it('ok（有 key_takeaway）→ 照常画 SVG，且不出现说明文案', () => {
    const { container } = render(
      <ChapterContentMap
        section={mk({ structure_status: 'ok', key_takeaway: '判断', paragraphs: ['p'] })}
      />
    )
    expect(mindmapOf(container)).not.toBeNull()
    expect(container.textContent).toContain('核心判断')
    expect(container.textContent).not.toContain(DEGRADED_NOTE_BY_DESIGN)
    expect(container.textContent).not.toContain(DEGRADED_NOTE_LOST)
  })

  it('repaired（补齐成功）→ 已有结构，照常画 SVG', () => {
    const { container } = render(
      <ChapterContentMap
        section={mk({ structure_status: 'repaired', highlights: ['亮点'], paragraphs: ['p'] })}
      />
    )
    expect(mindmapOf(container)).not.toBeNull()
    expect(container.textContent).toContain('关键亮点')
  })

  it('全空且无正文 → 组件整体不渲染（无标题、无说明、无 svg）', () => {
    const { container } = render(
      <ChapterContentMap section={mk({ structure_status: 'lost' })} />
    )
    expect(container.textContent).toBe('')
    expect(container.querySelector('svg')).toBeNull()
  })

  it('summary 模式不受退化态影响：仍走芯片态，不画 SVG 也不出说明', () => {
    const { container } = render(
      <ChapterContentMap
        mode="summary"
        section={mk({ structure_status: 'lost', paragraphs: Array(4).fill('p') })}
      />
    )
    expect(mindmapOf(container)).toBeNull()
    expect(container.textContent).not.toContain(DEGRADED_NOTE_LOST)
    expect(container.textContent).not.toContain(DEGRADED_NOTE_BY_DESIGN)
    expect(container.textContent).toContain('正文')
  })
})

describe('ChapterContentMap（score_gap：算分输入缺口 · T-13′）', () => {
  const GAP_SECTION = mk({
    structure_status: 'ok',
    key_takeaway: '判断',
    paragraphs: ['p'],
    score_gap: { kind: 'insufficient_input', reason: '可达性矩阵未给出「耗时/费用」数值' },
  })

  it('有 score_gap → 出一行「评分维度缺可核验数据 · 原因」，且不冒充 lost 文案', () => {
    const { container } = render(<ChapterContentMap section={GAP_SECTION} />)
    const note = container.querySelector('[data-score-gap]')
    expect(note).not.toBeNull()
    expect(note!.textContent).toContain('评分维度缺可核验数据')
    expect(note!.textContent).toContain('可达性矩阵未给出「耗时/费用」数值')
    expect(container.textContent).not.toContain(DEGRADED_NOTE_LOST)
    expect(container.textContent).not.toContain(DEGRADED_NOTE_BY_DESIGN)
  })

  it('结构完好（ok）与算分缺口并存：导图照画，说明另起一行（两条轴不互斥）', () => {
    const { container } = render(<ChapterContentMap section={GAP_SECTION} />)
    expect(mindmapOf(container)).not.toBeNull()
    expect(container.querySelector('[data-score-gap]')).not.toBeNull()
  })

  it('无 score_gap（null / 老报告缺字段）→ 不出现说明行', () => {
    const { container } = render(
      <ChapterContentMap section={mk({ structure_status: 'ok', key_takeaway: '判断', paragraphs: ['p'] })} />
    )
    expect(container.querySelector('[data-score-gap]')).toBeNull()
  })

  it('折叠态也显示缺口说明（结论面不藏在「显示本章内容结构」后面）', () => {
    const { container } = render(<ChapterContentMap section={GAP_SECTION} collapsed />)
    expect(container.querySelector('[data-score-gap]')).not.toBeNull()
    expect(container.textContent).toContain('显示本章内容结构')
  })
})
