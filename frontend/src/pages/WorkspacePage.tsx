import { useEffect, useState } from 'react'
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
  ClipboardList,
  ChevronRight,
  Link2,
} from 'lucide-react'
import { useTaskStream } from '../hooks/useTaskStream'
import { useTaskStore } from '../store/taskStore'
import { useTaskRegistry } from '../store/taskRegistry'
import { useExpertStore } from '../store/expertStore'
import { taskViewProvider } from '../lib/viewRegistry'
import { VFlowDag } from '../components/VFlowDag'
import { VAgentStream } from '../components/VAgentStream'
import { VEvidenceFeed } from '../components/VEvidenceFeed'
import { VTracePanel } from '../components/VTracePanel'
import { VCountUp } from '../components/ui'
import { PLAN_FALLBACK_HINT } from '../lib/destinationFallbackCopy'
import { userSourceStateLabel } from '../lib/userSourceStates'

export default function WorkspacePage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { state } = useLocation() as { state: { query?: string; kind?: string; purpose?: string } | null }
  const locQuery = state?.query ?? ''

  const byId = useExpertStore((s) => s.byId)
  const upsertTask = useTaskRegistry((s) => s.upsert)
  const tasks = useTaskRegistry((s) => s.tasks)

  // kind 判定：导航 state 优先 → 本地 registry（刷新/直达存活）→ 默认 research
  const kind = taskId ? (state?.kind ?? tasks[taskId]?.kind ?? 'research') : 'research'
  const purpose = taskId ? (state?.purpose ?? tasks[taskId]?.purpose ?? '') : ''
  const view = taskViewProvider(kind)

  // 全部 hooks 无条件调用（渲染分支变化时 hook 顺序保持稳定）
  useTaskStream(taskId, locQuery, { purpose })

  const {
    nodes,
    thoughts,
    evidences,
    images,
    messages,
    progress,
    teamMembers,
    traces,
    userSources,
    reportId,
    finished,
    error,
    planFallback,
    query: storeQuery,
  } = useTaskStore()
  const displayQuery = storeQuery || locQuery
  // 降级横幅「查看决策日志」→ 递增以强制揭示已收起的 Trace 面板（须在早退前无条件调用）
  const [traceReveal, setTraceReveal] = useState(0)

  const reworkMsg = messages.find((m) => m.kind === 'rework')

  // 报告就绪后短暂停留再跳转
  useEffect(() => {
    if (finished && reportId) {
      const t = setTimeout(() => navigate(`/report/${reportId}`), 1600)
      return () => clearTimeout(t)
    }
  }, [finished, reportId, navigate])

  // 视图协议防线：非 research 任务误入工作台 → 业务引导而非空白
  if (view.role !== 'research') {
    return (
      <div className="grid min-h-screen place-items-center bg-bg p-6">
        <div className="max-w-md rounded-card border border-line bg-card p-6 text-center shadow-card">
          <ClipboardList size={28} className="mx-auto text-primary" />
          <div className="mt-2 text-h3 text-ink">{view.hint || '该任务不在此处展示'}</div>
          <p className="mt-1 text-tag text-ink-2">工作台仅承载『目的地攻略 / 评估』角色调研流水线。</p>
          <button
            onClick={() => navigate('/life-circle')}
            className="mt-4 inline-flex h-10 items-center gap-1.5 rounded-btn bg-primary px-4 font-medium text-white transition-colors hover:bg-primary-deep"
          >
            <ChevronRight size={15} /> 前往生活圈页
          </button>
        </div>
      </div>
    )
  }

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
          <div className="truncate text-aux font-medium text-ink">{displayQuery || '目的地调研任务'}</div>
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

      {/* 目的地降级：运行流专属的温和提示（非 error 通道），降级事实的持久来源是决策日志 */}
      {planFallback && (
        <div className="flex items-center gap-3 bg-sun-soft px-5 py-2 text-aux text-ink-2">
          <span className="flex-1">{PLAN_FALLBACK_HINT}</span>
          <button
            onClick={() => setTraceReveal((v) => v + 1)}
            className="flex items-center gap-1 rounded-btn border border-line bg-card px-2.5 h-7 text-tag text-ink-3 hover:text-primary-deep"
          >
            <Activity size={13} /> 查看决策日志
          </button>
        </div>
      )}

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

            {/* 用户指定信源逐条读取态（计划 v3 §二 F1/B2）：第二条真实出网口必须逐条可见，
                不接受"没报错即通过" —— 内网被拒 / 404 / 归并 / 跑题是四种不同结论。 */}
            {userSources.length > 0 && (
              <div className="mt-4 rounded-card border border-line/70 bg-bg/60 p-4">
                <div className="flex items-center gap-1.5 text-aux font-semibold text-ink">
                  <Link2 size={14} className="text-primary" />
                  用户指定信源读取（{userSources.filter((u) => u.state !== 'reading').length}/{userSources.length} 已有结论）
                </div>
                <ul className="mt-2 flex flex-col gap-1.5 text-tag">
                  {userSources.map((u) => (
                    <li key={u.id} className="flex items-baseline gap-2">
                      <span className={u.state === 'reading' ? 'text-primary-deep' : 'text-ink-2'}>
                        {u.state === 'reading' ? `正在读取第 ${u.index}/${u.total} 条` : userSourceStateLabel(u.state)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-ink-3" title={u.url}>{u.url}</span>
                      {u.reason && <span className="shrink-0 text-warn">{u.reason}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

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
      <VTracePanel traces={traces} revealKey={traceReveal} />
    </div>
  )
}
