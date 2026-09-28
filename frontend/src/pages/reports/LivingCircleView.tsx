import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronRight, Inbox, Layers } from 'lucide-react'
import RecordRow from '../../components/RecordRow'
import RecordStatsStrip from '../../components/RecordStatsStrip'
import { useLivingCircleRecords } from '../../hooks/useLivingCircleRecords'
import { fmtRecordTime, groupBySample, recordStats } from '../../lib/recordIndex'
import type { DomainViewProps } from '../../lib/domainViews'
import LoadFailure from './LoadFailure'

/**
 * 生活圈体检屏（步骤 0 拍定＝甲：同一样区折叠成组）。
 *
 * 分组键是「样区 + 城市」，实现在 `lib/recordIndex.ts` 的 `groupBySample` ——
 * 列表口径不散进组件，判据才钉得住（同名不同城不得并组）。
 * 默认只显每组最新一份，展开看历史；统计带仍按整域计算，不随展开态变。
 */
export default function LivingCircleView({ onDelete, refreshToken }: DomainViewProps) {
  const navigate = useNavigate()
  const { data, loading, failed, isFixture, reload } = useLivingCircleRecords(refreshToken)
  // null 只出现在加载/失败两态；这里收成"必有数组"，渲染处不必到处 ?? []
  const rows = useMemo(() => data ?? [], [data])
  const [open, setOpen] = useState<Record<string, boolean>>({})

  const groups = useMemo(() => groupBySample(rows), [rows])
  const stats = useMemo(() => recordStats(rows), [rows])

  if (failed) {
    return <LoadFailure detail="生活圈体检记录取数失败" onRetry={reload} />
  }
  if (loading) {
    return <div className="mt-16 text-center text-aux text-ink-3">正在加载归档记录……</div>
  }
  if (rows.length === 0) {
    return (
      <div className="mt-16 flex flex-col items-center gap-3 text-center">
        <Inbox size={32} className="text-ink-3" />
        <div className="text-h3 text-ink">还没有生活圈体检归档</div>
        <button
          onClick={() => navigate('/life-circle/kaili')}
          className="mt-1 inline-flex h-11 items-center gap-2 rounded-btn bg-primary px-6 font-medium text-white shadow-card hover:bg-primary-deep"
        >
          去发起一次体检
        </button>
      </div>
    )
  }

  return (
    <>
      {stats && (
        <>
          <RecordStatsStrip stats={stats} />
          <p className="mt-3 text-tag text-ink-3">
            统计仅计生活圈体检的可比评分（{stats.total}/{stats.visibleLcTotal} 份，N 为归档可见条数）；
            少数不合格几何记录已由后端读路径隐藏，归档条数不等于库内报告数。
          </p>
        </>
      )}

      <div className="mt-6 flex flex-col gap-3">
        {groups.map((g) => {
          const expanded = !!open[g.key]
          const shown = expanded ? g.rows : g.rows.slice(0, 1)
          return (
            <section
              key={g.key}
              className="rounded-card border border-line/60 bg-card p-3 shadow-card"
            >
              <button
                onClick={() => setOpen((s) => ({ ...s, [g.key]: !s[g.key] }))}
                aria-expanded={expanded}
                className="flex w-full items-center gap-3 px-1 py-1 text-left"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-btn bg-primary-tint text-primary-deep">
                  {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </span>
                <span className="text-aux font-semibold text-ink">
                  {g.scene}
                  {g.city ? <span className="font-normal text-ink-3"> · {g.city}</span> : null}
                </span>
                <span className="inline-flex shrink-0 items-center gap-1 rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">
                  <Layers size={12} /> {g.rows.length} 份
                </span>
                {g.scoreDelta !== null && (
                  <span
                    className={`shrink-0 rounded-chip px-2 py-0.5 text-tag ${
                      g.scoreDelta >= 0 ? 'bg-primary-tint text-primary-deep' : 'bg-risk/10 text-risk'
                    }`}
                  >
                    与最早一次 {g.scoreDelta > 0 ? '+' : ''}
                    {g.scoreDelta} 分
                  </span>
                )}
                <span className="ml-auto shrink-0 text-tag text-ink-3">
                  {g.rows.length > 1
                    ? expanded
                      ? `${g.rows.length} 份体检历史`
                      : '展开看历史'
                    : fmtRecordTime(g.rows[0].checked_at)}
                </span>
              </button>
              <div className="mt-2 flex flex-col gap-2">
                {shown.map((r) => (
                  <RecordRow
                    key={r.key}
                    record={r}
                    onOpen={(id) => navigate(`/report/${id}`)}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            </section>
          )
        })}
      </div>

      {isFixture && (
        <p className="mt-5 text-tag text-ink-3">
          内置快照：两样区真实百度实跑数据，离线一键复现；真实体检任务自动归档同源。
        </p>
      )}
    </>
  )
}
