import { History, MapPin, TrendingUp, TriangleAlert, FileText } from 'lucide-react'
import type { RecordStats } from '../lib/recordIndex'

/** 体检口径统计带（原历史页独占职责，归档入口收敛后随报告中心的过滤子集联动）。 */
export default function RecordStatsStrip({ stats }: { stats: RecordStats }) {
  return (
    <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
      <StatBlock icon={History} value={stats.total} unit="次" label="体检总数" tip={`归档可见 ${stats.visibleLcTotal} 份生活圈记录中，有可比评分的 ${stats.total} 份`} />
      <StatBlock icon={TrendingUp} value={stats.latestScore} unit="分" label="最近一次评分" tip="最新一轮体检的综合评分" color="text-primary" />
      <StatBlock icon={MapPin} value={stats.avg} unit="分" label="平均评分" tip="全部可比体检综合得分的平均值（离线估算不参与）" color="text-ok" />
      <StatBlock icon={TriangleAlert} value={stats.blindspots} unit="处" label="累计盲区" tip="历次识别服务盲区的总量（可能重复计数）" color="text-warn" />
    </div>
  )
}

function StatBlock({
  icon: Icon,
  value,
  unit,
  label,
  tip,
  color = 'text-ok',
}: {
  icon: typeof FileText
  value: number
  unit: string
  label: string
  tip: string
  color?: string
}) {
  return (
    <div className="rounded-card border border-line/60 bg-card p-4 shadow-card" title={tip}>
      <span className={`grid h-8 w-8 place-items-center rounded-btn bg-primary-tint ${color}`}>
        <Icon size={16} />
      </span>
      <div className="mt-2.5 flex items-end gap-0.5">
        <span className="font-serif text-[26px] leading-none text-ink">{value}</span>
        <span className="mb-0.5 text-aux text-ink-2">{unit}</span>
      </div>
      <div className="mt-1 text-tag font-medium text-ink-2">{label}</div>
    </div>
  )
}
