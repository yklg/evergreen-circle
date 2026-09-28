import { Activity, Database, Layers, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { VCard, VChip } from '../../components/ui'
import type { ExpertWorkload } from '../../types'

/**
 * 专家贡献榜（复刻图三形状：整卡可点 + 圆形头像 + 层级徽标 + 三项带图标）。
 *
 * 层级徽标统一走 `VChip` 的 neutral 面，**不在这里造配色**：仓里层级色已有两份互相
 * 冲突的实现（`pages/ExpertsPage.tsx:17-21` 硬编码三色 vs `pages/ExpertDetailPage.tsx:58`
 * 读 `badge_color`），而 `ExpertWorkload` 根本没有 `badge_color` 字段 ⇒ 再写一套就是第三份口径。
 *
 * 与换件前的一处**有意**差别：旧代码 `.slice(0, 8)` 把出过工的专家静默砍到 8 位，
 * 既不报"另有几位"、也不与总数同源 —— 那正是本轮在概览卡上消灭的形状，
 * 所以这块改成列全 `missions > 0` 的专家，不做静默截断。
 */
export default function ExpertContributionBoard({
  workload,
  failed,
  onRetry,
}: {
  workload: ExpertWorkload[]
  failed: boolean
  onRetry: () => void
}) {
  const active = workload.filter((w) => w.missions > 0)

  return (
    <VCard hover={false}>
      <div className="flex items-center gap-2 text-aux font-semibold text-ink">
        <Users size={16} className="text-primary" /> 专家贡献榜
        <span className="ml-1 text-tag text-ink-3">
          {failed ? '按真实参与任务量排序' : `按真实参与任务量排序 · ${active.length} 位出过工`}
        </span>
      </div>

      {failed ? (
        <p className="mt-2 text-tag text-ink-2">
          专家工作量取数失败（下面不是"没有专家出工"）。
          <button onClick={onRetry} className="ml-2 font-medium text-primary-deep underline">
            重试
          </button>
        </p>
      ) : active.length === 0 ? (
        <p className="mt-2 text-tag text-ink-3">
          工作量取数正常，但没有一位专家的参与任务数大于 0（这是"没出过工"，不是"取不到"）。
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {active.map((w) => (
            <Link
              key={w.id}
              to={`/experts/${w.id}`}
              className="flex items-center gap-3 rounded-card border border-line/60 bg-bg p-3 text-left transition-all hover:border-primary-soft hover:bg-card"
            >
              <img
                src={w.avatar}
                alt={w.name}
                className="h-10 w-10 shrink-0 rounded-full object-cover"
                onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-aux font-medium text-ink">{w.name}</span>
                  <VChip label={w.layer} className="!h-5 !px-1.5 !text-tag" />
                </div>
                <div className="mt-1 flex items-center gap-3 text-tag text-ink-3">
                  <span className="inline-flex items-center gap-1">
                    <Layers size={11} /> {w.missions} 任务
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Activity size={11} /> {w.claims_authored} 结论
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Database size={11} /> {w.evidence_collected} 证据
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </VCard>
  )
}
