/**
 * 常青圈 · 简易评分雷达图（SVG，无外部依赖）。
 *
 * 几何一律来自 `layoutRadar`：画布由标签包围盒派生，本组件不持有任何尺寸常量。
 * 原先内联在此的 `cx/cy/r/1.18/viewBox` 五个手调常量与 `text-anchor` 反向翻转，
 * 正是 8 维时上下标签被裁、左右标签压在多边形上的根因 —— 见 `lib/radarLayout.ts`。
 */
import type { LivingCircleReport } from '../../types'
import { layoutRadar } from '../../lib/radarLayout'

export function MiniRadar({ report }: { report: LivingCircleReport }) {
  const layout = layoutRadar(report.scores.radar)
  return (
    <svg
      viewBox={layout.viewBox}
      className="mx-auto block h-auto w-full"
      style={{ maxWidth: layout.width }}
    >
      <g stroke="#d8dfda" fill="none" strokeWidth={1}>
        {layout.rings.map((g) => (
          <polygon key={g.k} points={g.points} />
        ))}
      </g>
      {layout.spokes.map((s, i) => (
        <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} stroke="#d8dfda" strokeWidth={1} />
      ))}
      <polygon
        points={layout.dataPoints}
        fill="rgba(124,152,133,0.40)"
        stroke="#5F7B69"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {layout.labels.map((l, i) => (
        <text
          key={`${i}-${l.text}`}
          x={l.x}
          y={l.y}
          textAnchor={l.anchor}
          fontSize={layout.fontSize}
          fill="#78807a"
        >
          {l.text}
        </text>
      ))}
    </svg>
  )
}
