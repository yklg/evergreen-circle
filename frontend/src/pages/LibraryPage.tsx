import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, Plus, Clock, Network, ShieldCheck, Trash2, AlertTriangle } from 'lucide-react'
import { fetchReports, deleteReport } from '../lib/api'
import { coverFor } from '../lib/cover'
import { VModal } from '../components/ui'
import type { ReportCard } from '../types'
import { fadeUp, stagger } from '../lib/motion'

export default function LibraryPage() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportCard[]>([])
  const [loading, setLoading] = useState(true)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    fetchReports()
      .then(setReports)
      .finally(() => setLoading(false))
  }, [])

  const confirmTarget = reports.find((r) => r.id === confirmId) || null

  const doDelete = async () => {
    if (!confirmId) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteReport(confirmId)
      setReports((rs) => rs.filter((r) => r.id !== confirmId))
      setConfirmId(null)
    } catch (e) {
      // 删除失败必须显式呈现：保留列表项、不关闭弹窗，避免"假删除成功"
      setDeleteError(e instanceof Error && e.message ? e.message : '删除失败，请稍后重试')
      setConfirmId(null)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-h1 text-ink">我的调研</h1>
          <p className="mt-1 text-aux text-ink-2">所有已完成的目的地调研报告 · 结论可溯源、证据可沉淀</p>
        </div>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2 rounded-btn bg-primary px-5 h-11 font-medium text-white shadow-card transition-all hover:bg-primary-deep hover:shadow-float"
        >
          <Plus size={18} /> 发起新调研
        </button>
      </header>

      {loading ? (
        <div className="mt-16 text-center text-aux text-ink-3">正在加载历史调研……</div>
      ) : reports.length === 0 ? (
        <div className="mt-16 flex flex-col items-center justify-center gap-4 text-center">
          <img
            src="/assets/brand/empty-state.png"
            alt="empty"
            className="h-40 w-40 object-contain opacity-90"
            onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
          />
          <div>
            <div className="text-h3 text-ink">还没有调研记录</div>
            <p className="mt-1 text-aux text-ink-2">发起你的第一次调研，专家即刻就位</p>
          </div>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
          >
            <Plus size={18} /> 开始调研
          </button>
        </div>
      ) : (
        <motion.div
          variants={stagger}
          initial="initial"
          animate="animate"
          className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3"
        >
          {reports.map((r) => (
            <motion.div
              key={r.id}
              variants={fadeUp}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/report/${r.id}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  navigate(`/report/${r.id}`)
                }
              }}
              className="group flex flex-col overflow-hidden rounded-card border border-line/60 bg-card text-left shadow-card transition-all hover:-translate-y-1 hover:shadow-float"
            >
              <div className="relative h-32 overflow-hidden">
                <img
                  src={coverFor(r)}
                  alt={r.title}
                  className="h-full w-full object-cover transition-transform group-hover:scale-105"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-ink/50 to-transparent" />
                <button
                  type="button"
                  aria-label="删除调研"
                  onClick={(e) => {
                    e.stopPropagation()
                    setDeleteError(null)
                    setConfirmId(r.id)
                  }}
                  onKeyDown={(e) => e.stopPropagation()}
                  className="absolute right-2 top-2 z-10 grid h-8 w-8 place-items-center rounded-full bg-ink/45 text-white opacity-0 transition-all duration-200 ease-verda hover:bg-red-500 group-hover:opacity-100"
                >
                  <Trash2 size={15} />
                </button>
              </div>
              <div className="flex flex-1 flex-col p-4">
                <div className="line-clamp-2 text-aux font-semibold text-ink">{r.title}</div>
                <p className="mt-1 line-clamp-1 text-tag text-ink-3">{r.subtitle}</p>
                <div className="mt-auto flex items-center gap-3 pt-3 text-tag text-ink-3">
                  <span className="inline-flex items-center gap-1"><Clock size={12} /> {r.created_at}</span>
                  <span className="inline-flex items-center gap-1"><FileText size={12} /> {r.evidence_count} 证据</span>
                  <span className="inline-flex items-center gap-1 text-primary-deep">
                    <ShieldCheck size={12} /> {r.high_conf_count} 高置信
                  </span>
                  <span
                    className="ml-auto inline-flex items-center gap-1 text-primary-deep"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/graph/${r.id}`)
                    }}
                  >
                    <Network size={12} /> 图谱
                  </span>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}

      <VModal
        open={confirmId !== null}
        onClose={() => !deleting && setConfirmId(null)}
        title="删除调研"
        width={440}
        height="min(340px,80vh)"
      >
        <div className="flex h-full flex-col p-6">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-red-50 text-red-500">
              <AlertTriangle size={18} />
            </span>
            <p className="text-aux leading-relaxed text-ink-2">
              确定要删除《{confirmTarget?.title}》吗？该操作不可撤销，关联的{' '}
              {confirmTarget?.evidence_count ?? 0} 条证据、决策链路与反馈也将一并清除。
            </p>
            {deleteError && (
              <div className="mt-3 flex items-start gap-2 rounded-card border border-warn/40 bg-red-50 px-3 py-2 text-tag text-warn">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span>删除失败：{deleteError}</span>
              </div>
            )}
          </div>
          <div className="mt-auto flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setConfirmId(null)}
              disabled={deleting}
              className="inline-flex h-10 items-center rounded-btn border border-line px-5 text-sm font-medium text-ink-2 transition-colors duration-200 ease-verda hover:bg-primary-tint/40 disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={doDelete}
              disabled={deleting}
              className="inline-flex h-10 items-center rounded-btn bg-red-500 px-5 text-sm font-medium text-white shadow-card transition-all hover:bg-red-600 disabled:opacity-50"
            >
              {deleting ? '删除中…' : '删除'}
            </button>
          </div>
        </div>
      </VModal>
    </div>
  )
}
