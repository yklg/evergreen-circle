/**
 * ChapterMindmapSvg —— 形态 A：横向自动布局 SVG 导图（§6.1）。
 * 布局逻辑逐字移植自已验证的预览页 renderTree
 * （.workbuddy/evidence/report-toc/preview-mindmap-content-density.html），
 * 内容源仍是 chapterMapLeaves（② 精简要点档）—— 只换皮、不换内容规则。
 *
 * 纯 SVG：无依赖、换行按 CJK/ASCII 分别估宽、打印分页安全。
 * 颜色走 CSS 变量（--verda-*），跟随主题。
 */
import { useState } from 'react'
import type { MapBranch } from '../lib/chapterMap'

const FOLD = 6
const FT = 11 // 叶子字号
const LEAF_LH = 15
const LEAF_PAD = 6
const LEAF_W = 260
const ROOT_W = 110
const BR_W = 92
const GAP_Y = 6
const PAD = 10
const LINE_UNIT = Math.floor((LEAF_W - 20) / FT) // 每行可容纳的宽度单位（CJK=1 / ASCII=0.56）
const MAX_LINES = 2

const BRANCH_COLOR: Record<string, string> = {
  takeaway: '--verda-primary-deep',
  highlights: '--verda-warn',
  claims: '--verda-ok',
  data: '--verda-primary',
  fallback: '--verda-ink-3',
}

/** 宽度估行：CJK/全角算 1 单位，ASCII 算 0.56；超出 maxLines 时末行尾加省略号 */
function wrap(s: string, maxUnit: number, maxLines: number): string[] {
  const t = String(s)
  const out: string[] = []
  let cur = ''
  let w = 0
  for (const ch of t) {
    const cw = /[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? 1 : 0.56
    if (w + cw > maxUnit && cur) {
      out.push(cur)
      if (out.length === maxLines) {
        out[maxLines - 1] = out[maxLines - 1].slice(0, -1) + '…'
        return out
      }
      cur = ''
      w = 0
    }
    cur += ch
    w += cw
  }
  if (cur) out.push(cur)
  return out.length ? out : ['']
}

const v = (name: string) => `var(${name})`

interface PlannedLeaf {
  lines: string[]
  h: number
}

export function ChapterMindmapSvg({
  title,
  branches,
}: {
  title: string
  branches: MapBranch[]
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const shown = branches.map((b) => {
    const open = expanded.has(b.key)
    const visible = open ? b.leaves : b.leaves.slice(0, FOLD)
    const rest = b.leaves.length - visible.length
    return { b, visible, rest, open }
  })

  const plans: PlannedLeaf[][] = shown.map(({ visible }) =>
    visible.map((l) => {
      const lines = wrap(l.text || '', LINE_UNIT, MAX_LINES)
      const h = Math.max(24, LEAF_PAD * 2 + lines.length * LEAF_LH + (l.badge ? 12 : 0))
      return { lines, h }
    })
  )

  const branchHeights = plans.map((ps, i) => {
    const list = ps.reduce((a, p) => a + p.h + 4, -4)
    return list + (shown[i].rest > 0 ? 20 : 0)
  })

  const total =
    branchHeights.reduce((a, b) => a + b, 0) + GAP_Y * Math.max(0, shown.length - 1)
  const H = Math.max(total, 64) + PAD * 2
  const W = 8 + ROOT_W + 24 + BR_W + 24 + LEAF_W + 8
  const xBr = 8 + ROOT_W + 24
  const xLeaf = xBr + BR_W + 24
  const rCy = H / 2

  const rootLines = wrap(title, 9, 3)
  const rH = Math.max(32, rootLines.length * 13 + 16)

  let y = PAD + (H - PAD * 2 - total) / 2

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ minWidth: 520, height: 'auto', display: 'block' }}
        role="img"
        aria-label={`本章内容结构导图：${title}`}
      >
        {/* 根节点 */}
        <rect
          x={8}
          y={rCy - rH / 2}
          width={ROOT_W}
          height={rH}
          rx={9}
          fill={v('--verda-card')}
          stroke={v('--verda-primary')}
          strokeWidth={1.2}
        />
        {rootLines.map((l, i, a) => (
          <text
            key={i}
            x={8 + ROOT_W / 2}
            y={rCy + (i - (a.length - 1) / 2) * 13 + 4}
            textAnchor="middle"
            fontSize={10.5}
            fontWeight={600}
            fill={v('--verda-ink')}
          >
            {l}
          </text>
        ))}

        {shown.map(({ b, visible, rest, open }, bi) => {
          const top = y
          const h = branchHeights[bi]
          const cy = top + (h - (rest > 0 ? 20 : 0)) / 2
          const color = v(BRANCH_COLOR[b.key] ?? BRANCH_COLOR.fallback)
          const nodeH = b.note ? 30 : 24
          const nodeTop = cy - nodeH / 2
          const els: React.ReactNode[] = []

          // 根 → 分支 连接线
          els.push(
            <path
              key={`lb-${bi}`}
              d={`M ${8 + ROOT_W} ${rCy} C ${8 + ROOT_W + 14} ${rCy}, ${xBr - 14} ${cy}, ${xBr} ${cy}`}
              fill="none"
              stroke={color}
              strokeWidth={1.1}
              opacity={0.62}
            />
          )
          // 分支节点
          els.push(
            <rect
              key={`br-${bi}`}
              x={xBr}
              y={nodeTop}
              width={BR_W}
              height={nodeH}
              rx={6}
              fill={v('--verda-card')}
              stroke={color}
              strokeWidth={1.1}
            />
          )
          const labelY = b.note ? nodeTop + 14 : cy + 4
          els.push(
            <text key={`bt-${bi}`} x={xBr + 8} y={labelY} fontSize={10.5} fontWeight={600} fill={color}>
              {b.label}
            </text>,
            <text
              key={`bc-${bi}`}
              x={xBr + BR_W - 8}
              y={labelY}
              textAnchor="end"
              fontSize={9.5}
              fontFamily="ui-monospace, Menlo, monospace"
              fill={v('--verda-ink-3')}
            >
              {b.leaves.length}
            </text>
          )
          if (b.note) {
            els.push(
              <text key={`bn-${bi}`} x={xBr + 8} y={nodeTop + 24} fontSize={9} fill={v('--verda-ink-3')}>
                {b.note.length > 11 ? b.note.slice(0, 10) + '…' : b.note}
              </text>
            )
          }

          // 叶子
          let ly = top
          visible.forEach((leaf, li) => {
            const p = plans[bi][li]
            const lcy = ly + p.h / 2
            els.push(
              <path
                key={`ll-${bi}-${li}`}
                d={`M ${xBr + BR_W} ${cy} C ${xBr + BR_W + 14} ${cy}, ${xLeaf - 14} ${lcy}, ${xLeaf} ${lcy}`}
                fill="none"
                stroke={color}
                strokeWidth={1}
                opacity={0.38}
              />,
              <rect
                key={`lr-${bi}-${li}`}
                x={xLeaf}
                y={ly}
                width={LEAF_W}
                height={p.h}
                rx={6}
                fill={v('--verda-bg')}
                stroke={v('--verda-line')}
                strokeWidth={1}
              />,
              <rect
                key={`lc-${bi}-${li}`}
                x={xLeaf}
                y={ly}
                width={2.5}
                height={p.h}
                rx={1.2}
                fill={color}
                opacity={0.85}
              />
            )
            p.lines.forEach((ln, i2) => {
              els.push(
                <text
                  key={`lt-${bi}-${li}-${i2}`}
                  x={xLeaf + 10}
                  y={ly + LEAF_PAD + (i2 + 1) * LEAF_LH - 4}
                  fontSize={FT}
                  fill={v('--verda-ink-2')}
                >
                  {ln}
                  {i2 === 0 && leaf.raw && leaf.raw.length > leaf.text.length && (
                    <title>{leaf.raw}</title>
                  )}
                </text>
              )
            })
            if (leaf.badge) {
              els.push(
                <text
                  key={`lg-${bi}-${li}`}
                  x={xLeaf + 10}
                  y={ly + p.h - 5}
                  fontSize={9}
                  fill={v('--verda-ok')}
                >
                  ✓ {leaf.badge}
                </text>
              )
            }
            ly += p.h + 4
          })

          // 折叠行（点击展开/收起）
          if (rest > 0) {
            els.push(
              <text
                key={`fd-${bi}`}
                x={xLeaf + 10}
                y={ly + 4 + 10}
                fontSize={10}
                fill={v('--verda-primary-deep')}
                style={{ cursor: 'pointer' }}
                onClick={() => toggle(b.key)}
              >
                {open ? '收起' : `+${rest} 条未展开`}
              </text>
            )
          }

          y = top + h + GAP_Y
          return <g key={b.key}>{els}</g>
        })}
      </svg>
    </div>
  )
}
