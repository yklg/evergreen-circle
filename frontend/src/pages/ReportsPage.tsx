/**
 * 报告中心（唯一归档入口）：生活圈体检 + 目的地调研的记录索引，按域过滤后打开阅读器。
 *
 * 原「历史」页（DashboardPage）的体检口径统计与来源举证行渲染已迁入本页；
 * 取数与列表口径的唯一实现在 `lib/recordIndex.ts` + `hooks/useRecordIndex.ts`。
 */
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Inbox, TriangleAlert } from 'lucide-react'
import RecordRow from '../components/RecordRow'
import RecordStatsStrip from '../components/RecordStatsStrip'
import { useRecordIndex } from '../hooks/useRecordIndex'
import { deleteLifeCircleReport, deleteReport } from '../lib/api'
import {
  RECORD_DOMAINS,
  RECORD_DOMAIN_LABEL,
  filterRecords,
  normalizeRecordFilter,
  recordStats,
  type RecordFilter,
  type ReportRecord,
} from '../lib/recordIndex'
import { VButton, VModal } from '../components/ui'

const FILTERS: { value: RecordFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  ...RECORD_DOMAINS.map((d) => ({ value: d as RecordFilter, label: RECORD_DOMAIN_LABEL[d] })),
]

export default function ReportsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filter = normalizeRecordFilter(params.get('domain'))
  const { records, loading, failed, partialFailed, isFixture, reload } = useRecordIndex()

  const rows = useMemo(() => filterRecords(records ?? [], filter), [records, filter])
  const stats = useMemo(() => recordStats(rows), [rows])

  const setFilter = (value: RecordFilter) => {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete('domain')
    else next.set('domain', value)
    setParams(next, { replace: true })
  }

  const [pendingDelete, setPendingDelete] = useState<ReportRecord | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const askDelete = (record: ReportRecord) => {
    setDeleteError(null)
    setPendingDelete(record)
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    setDeleteError(null)
    try {
      // 删除后以服务端为准重取索引，不在本地伪造"已移除"的列表状态
      if (pendingDelete.domain === 'living_circle') await deleteLifeCircleReport(pendingDelete.id)
      else await deleteReport(pendingDelete.id)
      setPendingDelete(null)
      reload()
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeleting(false)
    }
  }

  const deleteWarning = pendingDelete
    ? pendingDelete.domain === 'living_circle'
      ? `确定要删除《${pendingDelete.title}》吗？该操作不可撤销，重新体检会再次消耗百度配额。`
      : `确定要删除《${pendingDelete.title}》吗？该操作不可撤销，关联的 ${pendingDelete.evidence_count ?? 0} 条证据、决策链路与反馈也将一并清除。`
    : ''

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header>
        <h1 className="font-serif text-h1 text-ink">报告中心</h1>
        <p className="mt-1 text-aux text-ink-2">
          历次生活圈体检与目的地调研的归档 —— 点击重看完整体检单与阅读器
        </p>
      </header>

      {failed ? (
        <div className="mt-6 flex flex-col items-start gap-3 rounded-card border border-risk/60 bg-risk/10 p-5">
          <span className="inline-flex items-center gap-2 text-aux font-semibold text-ink">
            <TriangleAlert size={16} className="text-risk" /> 记录加载失败
          </span>
          <p className="text-tag text-ink-2">
            归档列表取数未成功（后端未就绪或无权限）。这里不显示「暂无报告」，因为无法区分是真的没有还是没取到。
          </p>
          <button
            onClick={reload}
            className="inline-flex h-9 items-center rounded-btn bg-primary px-4 text-aux font-medium text-white hover:bg-primary-deep"
          >
            重试
          </button>
        </div>
      ) : (
        <>
          {partialFailed && (
            <div className="mt-6 flex items-center gap-2 rounded-card border border-warn/60 bg-warn/10 px-4 py-3 text-tag text-ink-2">
              <TriangleAlert size={14} className="text-warn" /> 部分记录加载失败：另一数据源未取到，当前列表可能不完整。
              <button onClick={reload} className="ml-auto font-medium text-primary-deep underline">
                重试
              </button>
            </div>
          )}

          {/* 域过滤（值由 taskDomains 注册表派生，深链 ?domain= 与 chip 双向同步） */}
          <div className="mt-6 flex flex-wrap items-center gap-2">
            {FILTERS.map((t) => (
              <button
                key={t.value}
                onClick={() => setFilter(t.value)}
                aria-pressed={filter === t.value}
                className={`rounded-chip px-3 py-1.5 text-aux transition-colors ${
                  filter === t.value ? 'bg-primary font-medium text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {loading && (
            <div className="mt-16 text-center text-aux text-ink-3">正在加载归档记录……</div>
          )}

          {!loading && rows.length === 0 && (
            <div className="mt-16 flex flex-col items-center gap-3 text-center">
              <Inbox size={32} className="text-ink-3" />
              <div className="text-h3 text-ink">暂无该类报告</div>
              <button
                onClick={() => navigate('/life-circle/kaili')}
                className="mt-1 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
              >
                去发起一次体检
              </button>
            </div>
          )}

          {!loading && rows.length > 0 && (
            <>
              {stats && (
                <>
                  <RecordStatsStrip stats={stats} />
                  <p className="mt-3 text-tag text-ink-3">
                    统计仅计生活圈体检的可比评分（{stats.total}/{stats.visibleLcTotal} 份，N 为归档可见条数）；
                    目的地调研不参与评分。少数不合格几何记录已由后端读路径隐藏，归档条数不等于库内报告数。
                  </p>
                </>
              )}

              <div className="mt-6 flex flex-col gap-3">
                {rows.map((r) => (
                  <RecordRow
                    key={r.key}
                    record={r}
                    onOpen={(id) => navigate(`/report/${id}`)}
                    onDelete={askDelete}
                  />
                ))}
              </div>

              {isFixture && (
                <p className="mt-5 text-tag text-ink-3">
                  内置快照：两样区真实百度实跑数据，离线一键复现；真实体检任务自动归档同源。
                </p>
              )}
            </>
          )}
        </>
      )}
      <VModal
        open={pendingDelete !== null}
        onClose={() => !deleting && setPendingDelete(null)}
        title="删除归档记录"
        width={440}
        height="min(340px,80vh)"
      >
        <div className="flex h-full flex-col p-6">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-risk/10 text-risk">
              <AlertTriangle size={18} />
            </span>
            <p className="text-aux leading-relaxed text-ink-2">{deleteWarning}</p>
          </div>
          {deleteError && (
            <div className="mt-3 flex items-start gap-2 rounded-card border border-warn/40 bg-risk/10 px-3 py-2 text-tag text-ink-2">
              <TriangleAlert size={14} className="mt-0.5 shrink-0 text-risk" />
              <span>删除失败：{deleteError}（记录仍在归档里，可重试）</span>
            </div>
          )}
          <div className="mt-auto flex justify-end gap-3">
            <VButton variant="ghost" onClick={() => setPendingDelete(null)} disabled={deleting}>
              取消
            </VButton>
            <VButton onClick={confirmDelete} disabled={deleting}>
              {deleting ? '删除中…' : '删除'}
            </VButton>
          </div>
        </div>
      </VModal>
    </div>
  )
}
