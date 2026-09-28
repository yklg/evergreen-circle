import { History, MapPin, TrendingUp, TriangleAlert } from 'lucide-react'
import { VStatCard } from './ui'
import type { RecordStats } from '../lib/recordIndex'

/**
 * 体检口径统计带（原历史页独占职责，归档入口收敛后随报告中心的过滤子集联动）。
 *
 * 四格的面不再自带一份私有实现：统一走 `VStatCard surface="tile"`（仓内既有面）。
 * 形状与口径由 `__tests__/recordStatsStripDom.test.tsx` 逐条 class 钉住 ——
 * 换件前后都必须绿，否则就是被动改了这一屏的像素。
 */
export default function RecordStatsStrip({ stats }: { stats: RecordStats }) {
  return (
    <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
      <VStatCard
        icon={History}
        value={stats.total}
        unit="次"
        label="体检总数"
        color="text-ok"
        surface="tile"
        tip={`归档可见 ${stats.visibleLcTotal} 份生活圈记录中，有可比评分的 ${stats.total} 份`}
      />
      <VStatCard
        icon={TrendingUp}
        value={stats.latestScore}
        unit="分"
        label="最近一次评分"
        tip="最新一轮体检的综合评分"
        color="text-primary"
        surface="tile"
      />
      <VStatCard
        icon={MapPin}
        value={stats.avg}
        unit="分"
        label="平均评分"
        tip="全部可比体检综合得分的平均值（离线估算不参与）"
        color="text-ok"
        surface="tile"
      />
      <VStatCard
        icon={TriangleAlert}
        value={stats.blindspots}
        unit="处"
        label="累计盲区"
        tip="历次识别服务盲区的总量（可能重复计数）"
        color="text-warn"
        surface="tile"
      />
    </div>
  )
}
