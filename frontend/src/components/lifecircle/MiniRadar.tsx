/**
 * 常青圈 · 简易评分雷达图（SVG，无外部依赖）。
 * F 阶段用于体检单/对比页；M 阶段可升级为 ECharts radar 保持契约不变。
 */
import type { LivingCircleReport } from '../../types'

export function MiniRadar({ report }: { report: LivingCircleReport }) {
  // 渲染全部维度（与下层 ECharts 雷达同源同维）；不再 slice(0,6) 截断导致上下轴数不一致
  const dims = report.scores.radar
  const cx = 92
  const cy = 92
  const r = 74
  const n = dims.length
  // n=0（离线）时避免除零，返回空圆点
  const guard = n === 0 ? 0 : 1
  const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(n, 1)
  const pt = (i: number, k: number) => {
    const a = ang(i)
    return [cx + Math.cos(a) * r * k * guard, cy + Math.sin(a) * r * k * guard]
  }
  const ring = (k: number) => dims.map((_, i) => pt(i, k).join(',')).join(' ')
  const data = dims.map((d, i) => pt(i, d.score / 100).join(',')).join(' ')
  return (
    <svg viewBox="0 0 184 172" className="mx-auto block h-auto w-[168px]">
      <g stroke="#d8dfda" fill="none" strokeWidth={1}>
        {[0.33, 0.66, 1].map((k) => <polygon key={k} points={ring(k)} />)}
      </g>
      {dims.map((_, i) => {
        const [x, y] = pt(i, 1)
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#d8dfda" strokeWidth={1} />
      })}
      <polygon points={data} fill="rgba(124,152,133,0.40)" stroke="#5F7B69" strokeWidth={2} strokeLinejoin="round" />
      {dims.map((d, i) => {
        const cos = Math.cos(ang(i))
        // 边缘标签按角度翻转：右侧(end)与左侧(start)把文本拉回视口内，避免 8 轴时横轴两端标签裁切
        const anchor = cos > 0.3 ? 'end' : cos < -0.3 ? 'start' : 'middle'
        const [x, y] = pt(i, 1.18)
        return (
          <text key={d.dimension} x={x} y={y} textAnchor={anchor} fontSize={11} fill="#78807a">
            {d.dimension}
          </text>
        )
      })}
    </svg>
  )
}