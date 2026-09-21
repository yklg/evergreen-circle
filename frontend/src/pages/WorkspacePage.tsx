import { useEffect } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sprout,
  ChevronLeft,
  Users,
  Activity,
  FileText,
  RotateCcw,
  Sparkles,
  CheckCircle2,
} from 'lucide-react'
import { useTaskStream } from '../hooks/useTaskStream'
import { useTaskStore } from '../store/taskStore'
import { useTaskRegistry } from '../store/taskRegistry'
import { useExpertStore } from '../store/expertStore'
import { VFlowDag } from '../components/VFlowDag'
import { VAgentStream } from '../components/VAgentStream'
import { VEvidenceFeed } from '../components/VEvidenceFeed'
import { VTracePanel } from '../components/VTracePanel'
import { VCountUp } from '../components/ui'

export default function WorkspacePage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { state } = useLocation() as { state: { query?: string } | null }
  const query = state?.query ?? ''

  useTaskStream(taskId, query)

  const {
    nodes,
    thoughts,
    evidences,
    images,
    messages,
    progress,
    teamMembers,
    traces,
    reportId,
    finished,
    error,
    query: storeQuery,
  } = useTaskStore()
  const byId = useExpertStore((s) => s.byId)
  const upsertTask = useTaskRegistry((s) => s.upsert)
  const displayQuery = storeQuery || query

  const reworkMsg = messages.find((m) => m.kind === 'rework')

  // 报告就绪后短暂停留再跳转
  useEffect(() => {
    if (finished && reportId) {
      const t = setTimeout(() => navigate(`/report/${reportId}`), 1600)
      return () => clearTimeout(t)
    }
  }, [finished, reportId, navigate])

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      {/* 顶栏 */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button
          onClick={() => {
            // 返回 = 收起到后台运行：任务仍在后端跑，悬浮条接管；不再硬杀连接
            if (taskId) {
              upsertTask({
                taskId,
                query: displayQuery,
                status: 'running',
                startedAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
              })
            }
            navigate('/')
          }}
          title="收起到后台运行（调研继续）"
          className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 transition-colors hover:bg-primary-tint hover:text-primary-deep"
        >
          <ChevronLeft size={20} />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-btn bg-primary-tint text-primary">
          <Sprout size={18} strokeWidth={1.8} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-aux font-medium text-ink">{displayQuery || '旅游调研任务'}</div>
          <div className="text-tag text-ink-3">任务 {taskId}</div>
        </div>
        {/* 进度 */}
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-1.5 text-tag text-ink-2 sm:flex">
            <FileText size={13} /> <VCountUp value={progress.evidence_count} /> 条证据
          </div>
          <div className="flex w-40 items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-chip bg-line">
              <motion.div
                className="h-full rounded-chip bg-primary"
                animate={{ width: `${progress.percent}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
            <span className="text-tag font-medium text-primary-deep">{progress.percent}%</span>
          </div>
        </div>
      </header>

      {error && (
        <div className="bg-risk/10 px-5 py-2 text-aux text-risk">采集流中断：{error}（已尽量降级，可返回重试）</div>
      )}

      {/* 三栏主体 */}
      <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr_340px]">
        {/* 左：DAG 指挥台 + 团队 */}
        <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto border-r border-line bg-card/40 p-5">
          <div>
            <div className="mb-3 flex items-center gap-1.5 text-aux font-semibold text-ink">
              <Activity size={15} className="text-primary" /> 任务流水线
            </div>
            <VFlowDag nodes={nodes} />
          </div>

          <div>
            <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
              <Users size={15} className="text-primary" /> 专家队（{teamMembers.length}）
            </div>
            <div className="flex flex-wrap gap-1.5">
              {teamMembers.map((id) => {
                const ex = byId(id)
                if (!ex) return null
                return (
                  <img
                    key={id}
                    src={ex.avatar}
                    alt={ex.name}
                    title={`${ex.name} · ${ex.role_title}`}
                    className="h-8 w-8 rounded-full border border-card object-cover shadow-card"
                  />
                )
              })}
            </div>
          </div>
        </aside>

        {/* 中：实时思维流 */}
        <section className="flex min-h-0 flex-col">
          <div className="flex items-center gap-1.5 border-b border-line px-6 py-3 text-aux font-semibold text-ink">
            <Sparkles size={15} className="text-primary" /> 实时协作思维流
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {thoughts.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-ink-3">
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ repeat: Infinity, duration: 3, ease: 'linear' }}
                >
                  <Sprout size={32} className="text-primary-soft" />
                </motion.div>
                <p className="text-aux">专家队正在集结，马上开始……</p>
              </div>
            ) : (
              <VAgentStream thoughts={thoughts} />
            )}

            {/* 返工闭环卡片 */}
            <AnimatePresence>
              {reworkMsg && reworkMsg.diff && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.96 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="mt-4 rounded-card border border-warn/40 bg-sun-soft p-4"
                >
                  <div className="flex items-center gap-1.5 text-aux font-semibold text-warn">
                    <RotateCcw size={14} /> 质检返工 · 真实反馈闭环
                  </div>
                  <p className="mt-1 text-tag text-ink-2">{reworkMsg.reason}</p>
                  <div className="mt-2 space-y-1.5 text-tag">
                    <div className="rounded-btn bg-risk/10 px-3 py-1.5 text-ink-2 line-through decoration-risk/50">
                      {reworkMsg.diff.before}
                    </div>
                    <div className="rounded-btn bg-ok/10 px-3 py-1.5 text-ink">{reworkMsg.diff.after}</div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 完成横幅 */}
            <AnimatePresence>
              {finished && reportId && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mt-5 flex items-center gap-3 rounded-card border border-primary-soft bg-primary-tint p-4"
                >
                  <CheckCircle2 size={22} className="text-primary" />
                  <div className="flex-1">
                    <div className="text-aux font-semibold text-ink">报告已签发，正在打开…</div>
                    <div className="text-tag text-ink-2">如未自动跳转，可点击右侧按钮</div>
                  </div>
                  <button
                    onClick={() => navigate(`/report/${reportId}`)}
                    className="rounded-btn bg-primary px-4 h-9 text-aux font-medium text-white hover:bg-primary-deep"
                  >
                    查看报告
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </section>

        {/* 右：实时证据流 + 图片 */}
        <aside className="flex min-h-0 flex-col border-l border-line bg-card/40">
          <div className="flex items-center gap-1.5 border-b border-line px-5 py-3 text-aux font-semibold text-ink">
            <FileText size={15} className="text-primary" /> 证据库（{evidences.length}）
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {images.length > 0 && (
              <div className="mb-4 grid grid-cols-3 gap-1.5">
                {images.slice(0, 6).map((im, i) => (
                  <img
                    key={`${im.src}-${i}`}
                    src={im.src}
                    alt={im.alt ?? ''}
                    className="aspect-square w-full rounded-btn border border-line object-cover"
                    onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                  />
                ))}
              </div>
            )}
            <VEvidenceFeed evidences={evidences} />
          </div>
        </aside>
      </div>

      {/* 悬浮可拖拽决策日志面板（可观测性 Trace）*/}
      <VTracePanel traces={traces} />
    </div>
  )
}
