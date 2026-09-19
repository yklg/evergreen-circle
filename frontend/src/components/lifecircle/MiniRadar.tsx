/**
 * 常青圈 · 简易评分雷达图（SVG，无外部依赖）。
 * F 阶段用于体检单/对比页；M 阶段可升级为 ECharts radar 保持契约不变。
 */
import type { LivingCircleReport } from '../../types'

export function MiniRadar({ report }: { report: LivingCircleReport }) {
  const dims = report.scores.radar.slice(0, 6)
  const cx = 92
  const cy = 92
  const r = 74
  const n = dims.length
  const pt = (i: number, k: number) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n
    return [cx + Math.cos(ang) * r * k, cy + Math.sin(ang) * r * k]
  }
  const ring = (k: number) => dims.map((_, i) => pt(i, k).join(',')).join(' ')
  const data = dims.map((d, i) => pt(i, d.score / 100).join(',')).join(' ')
  return (
    <svg viewBox="0 0 184 168" className="mx-auto block h-auto w-[168px]">
      <g stroke="#d8dfda" fill="none" strokeWidth={1}>
        {[0.33, 0.66, 1].map((k) => <polygon key={k} points={ring(k)} />)}
      </g>
      {dims.map((_, i) => {
        const [x, y] = pt(i, 1)
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#d8dfda" strokeWidth={1} />
      })}
      <polygon points={data} fill="rgba(124,152,133,0.40)" stroke="#5F7B69" strokeWidth={2} strokeLinejoin="round" />
      {dims.map((d, i) => {
        const [x, y] = pt(i, 1.16)
        return (
          <text key={d.dimension} x={x} y={y} textAnchor="middle" fontSize={11} fill="#78807a">
            {d.dimension}
          </text>
        )
      })}
    </svg>
  )
}