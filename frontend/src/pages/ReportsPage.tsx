/**
 * 报告中心外壳：两个 tab，每个域一屏。
 *
 * 外壳只做三件事：域切换（深链 `?domain=`）、按登记表挂载该域屏、统一的删除确认。
 * 视图差异一律登记在 `lib/domainViews.ts`，这里不出现按域 if/switch ——
 * 判据见 `__tests__/domainEnumSingleSource.test.ts`。
 *
 * 取数也归各屏自己：原先一根 `Promise.allSettled` 拉两源，生活圈屏会被调研取数连坐。
 */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, TriangleAlert } from 'lucide-react'
import { VButton, VModal } from '../components/ui'
import { DOMAIN_VIEWS } from '../lib/domainViews'
import {
  RECORD_DOMAINS,
  RECORD_DOMAIN_LABEL,
  normalizeRecordFilter,
  type ReportRecord,
} from '../lib/recordIndex'

export default function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const domain = normalizeRecordFilter(params.get('domain'))
  const spec = DOMAIN_VIEWS[domain]

  const [pendingDelete, setPendingDelete] = useState<ReportRecord | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  const setDomain = (value: string) => {
    const next = new URLSearchParams(params)
    next.set('domain', value)
    setParams(next, { replace: true })
  }

  const askDelete = (record: ReportRecord) => {
    setDeleteError(null)
    setPendingDelete(record)
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    setDeleteError(null)
    try {
      // 删除后让这一屏自己重取：不在本地伪造"已移除"的列表状态
      await DOMAIN_VIEWS[pendingDelete.domain].remove(pendingDelete.id)
      setPendingDelete(null)
      setRefreshToken((n) => n + 1)
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header>
        <h1 className="font-serif text-h1 text-ink">报告中心</h1>
        <p className="mt-1 text-aux text-ink-2">
          生活圈体检与目的地调研各自的归档 —— 体检看重看完整体检单，调研看情报厚度与来源举证
        </p>
      </header>

      <div role="tablist" aria-label="报告中心域" className="mt-6 flex flex-wrap gap-2">
        {RECORD_DOMAINS.map((d) => (
          <button
            key={d}
            role="tab"
            id={`tab-${d}`}
            aria-selected={domain === d}
            aria-controls={`panel-${d}`}
            onClick={() => setDomain(d)}
            className={`rounded-btn px-4 h-10 text-aux transition-colors ${
              domain === d
                ? 'bg-primary font-medium text-white'
                : 'bg-bg text-ink-2 hover:bg-primary-tint'
            }`}
          >
            {RECORD_DOMAIN_LABEL[d]}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${domain}`} aria-labelledby={`tab-${domain}`}>
        <spec.View onDelete={askDelete} refreshToken={refreshToken} />
      </div>

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
            <p className="text-aux leading-relaxed text-ink-2">
              {pendingDelete ? DOMAIN_VIEWS[pendingDelete.domain].deleteWarning(pendingDelete) : ''}
            </p>
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
