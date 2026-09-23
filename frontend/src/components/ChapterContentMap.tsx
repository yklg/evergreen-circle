import { useState } from 'react'
import type { ReactElement } from 'react'
import { X, Lightbulb, Sparkles, BarChart3, Quote } from 'lucide-react'
import type { ReportSection } from '../types'
import { chapterMapLeaves, chapterMapChips } from '../lib/chapterMap'
import type { MapBranch } from '../lib/chapterMap'
import { ChapterMindmapSvg } from './ChapterMindmapSvg'

export type ContentMapMode = 'detail' | 'summary'

interface ChapterContentMapProps {
  section: ReportSection
  mode?: ContentMapMode
  collapsed?: boolean
}

/**
 * detail 模式渲染形态：§6.1 形态 A（横向自动布局 SVG 导图，用户 2026-09-17 裁决）。
 * 内容源与 summary 模式共用 chapterMapLeaves（规则不漂移）。
 */
const BRANCH_STYLE: Record<string, { icon: ReactElement; chip: string }> = {
  takeaway: { icon: <Lightbulb size={14} />, chip: 'bg-primary text-white' },
  highlights: { icon: <Sparkles size={14} />, chip: 'bg-amber-400 text-white' },
  claims: { icon: <Quote size={14} />, chip: 'bg-green-500 text-white' },
  data: { icon: <BarChart3 size={14} />, chip: 'bg-primary text-white' },
  fallback: { icon: <BarChart3 size={14} />, chip: 'bg-line text-ink-3' },
}

export function ChapterContentMap({
  section,
  mode = 'detail',
  collapsed = false,
}: ChapterContentMapProps) {
  const [isCollapsed, setIsCollapsed] = useState(collapsed)

  const branches = chapterMapLeaves(section)
  const hasContent = branches.length > 0

  if (!hasContent) return null

  // 算分输入缺口（后端 score_gap，与 structure_status 正交）：折叠态也照常显示——
  // 「本该有图却没出」的如实说明属于结论面，不该藏在「显示本章内容结构」后面。
  const gapNote = section.score_gap?.reason ? (
    <p
      data-score-gap
      className="mb-2 rounded-chip border border-dashed border-line bg-card/60 px-3 py-2 text-tag text-ink-2"
    >
      评分维度缺可核验数据 · {section.score_gap.reason}
    </p>
  ) : null

  if (isCollapsed) {
    return (
      <>
        {gapNote}
        <button
          onClick={() => setIsCollapsed(false)}
          className="flex w-full items-center justify-center gap-2 rounded-card border border-dashed border-line bg-card/60 px-3 py-2 text-tag text-ink-2 hover:border-primary hover:text-primary-deep"
        >
          <span>显示本章内容结构</span>
        </button>
      </>
    )
  }

  return (
    <div className="rounded-card border border-line bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-aux font-semibold text-ink">本章内容结构</span>
        <button
          onClick={() => setIsCollapsed(true)}
          className="grid h-6 w-6 place-items-center rounded-btn text-ink-3 hover:bg-primary-tint hover:text-ink"
          title="收起"
        >
          <X size={14} />
        </button>
      </div>

      {gapNote}

      {mode === 'detail' ? (
        isDegraded(branches) ? (
          <p className="rounded-chip border border-dashed border-line bg-card/60 px-3 py-2 text-tag text-ink-2">
            {degradedNote(section)}
          </p>
        ) : (
          <ChapterMindmapSvg title={section.title} branches={branches} />
        )
      ) : (
        renderSummaryMode(section)
      )}
    </div>
  )
}

/**
 * 只有一个「正文字数」降级分支时不再画导图：三个盒子的连线会被误读成「流程图」，
 * 而它其实代表「本章没拿到结构」。文案区分「写稿丢了结构」与「本章本就没有结构化材料」。
 */
function isDegraded(branches: MapBranch[]): boolean {
  return branches.length === 1 && branches[0].degraded === true
}

function degradedNote(section: ReportSection): string {
  const n = section.paragraphs?.length ?? 0
  return section.structure_status === 'lost'
    ? `本章结构提炼失败 · 正文 ${n} 段完整`
    : `本章未产出可结构化要点 · 正文 ${n} 段`
}

/** summary 模式：紧凑芯片态，内容源与 detail 共用 chapterMapLeaves（规则不漂移） */
function renderSummaryMode(section: ReportSection) {
  const chips = chapterMapChips(section)
  const elements: Array<{ icon: ReactElement; label: string; countStr: string; color: string }> =
    chips.map((c) => {
      const key = Object.keys(BRANCH_STYLE).find((k) => branchLabelOf(k) === c.label) ?? ''
      const style = BRANCH_STYLE[key] ?? BRANCH_STYLE.fallback
      return {
        icon: style.icon,
        label: c.label,
        countStr: `×${c.count}`,
        color: style.chip,
      }
    })

  if (elements.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-chip bg-gradient-to-r from-tint to-card p-2">
      {elements.map((el, idx) => (
        <div key={idx} className="flex items-center gap-1.5">
          <div className={`flex h-7 w-7 items-center justify-center rounded-md text-white ${el.color}`}>
            {el.icon}
          </div>
          <span className="text-xs font-medium text-ink">{el.label}</span>
          {el.countStr && <span className="text-[10px] text-ink-3">·{el.countStr}</span>}
          {idx < elements.length - 1 && <span className="text-ink-3">→</span>}
        </div>
      ))}
    </div>
  )
}

function branchLabelOf(key: string): string {
  const labels: Record<string, string> = {
    takeaway: '核心判断',
    highlights: '关键亮点',
    claims: '核心论点',
    data: '数据',
    fallback: '正文',
  }
  return labels[key] ?? key
}
