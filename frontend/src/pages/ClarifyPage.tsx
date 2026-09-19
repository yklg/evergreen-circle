import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Sprout, ArrowRight, SkipForward, Loader2, AlertTriangle, RefreshCw } from 'lucide-react'
import type { ClarifyQuestion } from '../types'
import { submitClarify, openClarifyStream } from '../lib/api'
import { VSunGlow } from '../components/ui'
import { fadeUp } from '../lib/motion'
import QuestionField from '../components/QuestionField'

interface NavState {
  query?: string
}

export default function ClarifyPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { state } = useLocation() as { state: NavState | null }
  const query = state?.query ?? ''

  // SSE 驱动的问卷状态（不再读 state.clarify，改为懒生成）
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([])
  const [ready, setReady] = useState(false) // 是否已收到首屏（partial 或完整）
  const [stage, setStage] = useState('正在准备问卷…') // loading 阶段文案
  const [error, setError] = useState<string | null>(null)
  const [runId, setRunId] = useState(0) // 重试时自增，重新拉起 SSE
  const [step, setStep] = useState(0) // 向导步：0..N-1 单题；===N 为核对屏
  // 流式加载反馈（C1/C2）：基础题已就绪但竞品发现仍在后台时展示进度条 + 标识
  const [discoveryOngoing, setDiscoveryOngoing] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressLabel, setProgressLabel] = useState('正在准备问卷…')
  // 竞品识别兜底（C6）：超时/异常时竞品为自动识别候选，需温和提示而非大警告
  const [competitorsFallback, setCompetitorsFallback] = useState(false)

  // 自动前进延时：单选为快速视觉锁定（一击即定）；多选需留时间勾多项，故更长且每次勾选都重置
  const SINGLE_ADVANCE_MS = 350
  const MULTI_ADVANCE_MS = 1200

  const [answers, setAnswers] = useState<Record<string, unknown>>({})
  const [submitting, setSubmitting] = useState(false)
  // 用户自定义补充的竞品（按题 id 存，目前主要用于 competitors 题）
  const [customInputs, setCustomInputs] = useState<Record<string, string>>({})

  // 每步切换 / 进入问卷时把焦点移到当前题容器，保证键盘 / 读屏可达
  const titleRef = useRef<HTMLDivElement>(null)
  // 自动前进定时器句柄：单选选中后延时跳下一题，用 ref 持有以便 clearTimeout，
  // 避免「选中后又点下一步」造成双跳，以及 step 变化 / 卸载时的泄漏。
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 是否已进入核对屏：clarify_update 到达时据此决定是否保持核对屏（C5）
  const reviewReachedRef = useRef(false)
  useEffect(() => {
    titleRef.current?.focus()
    return () => {
      if (advanceTimer.current) {
        clearTimeout(advanceTimer.current)
        advanceTimer.current = null
      }
    }
  }, [step, ready])

  // 跟踪是否已进入核对屏（供 clarify_update 到达时保持核对屏，C5）
  useEffect(() => {
    reviewReachedRef.current = ready && questions.length > 0 && step === questions.length
  }, [ready, questions, step])

  // 挂载后通过 SSE 懒生成问卷；loading 阶段绝不跳转（修 P0#3：原 questions.length===0 误跳）
  useEffect(() => {
    if (!taskId) return
    let closed = false
    // 终态已抵达标志：用于区分"流完成"与"连接失败"。
    // 注意：不能用 React state `ready` 做此判断——onError 闭包捕获的是
    // effect 创建时的 `ready` 快照，setReady(true) 不会更新该闭包，会导致守卫失效。
    let done = false
    // 切换任务即重置问卷状态（任务维度的有意模式）
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(false)
    setError(null)
    setQuestions([])
    setStep(0)
    // closeRef 持有 openClarifyStream 返回的关闭函数。真实 SSE 事件在连接建立后
    // （即本调用返回、closeRef.current 已赋值）才异步到达；若测试同步派发事件，
    // 尚未赋值，?.() 安全 no-op，避免 TDZ（Cannot access 'close' before initialization）。
    const closeRef: { current?: () => void } = {}
    let partialDone = false // 已收到 partial 基础题但尚未 complete（用于 onError 守卫）
    const close = openClarifyStream(taskId, {
      onEvent: (type, data) => {
        if (closed) return
        if (type === 'clarify_stage') {
          const d = data as { stage?: string; message?: string }
          if (d?.stage === 'understanding') {
            setProgress(20)
            setProgressLabel(d?.message || '正在理解你的需求…')
            if (d?.message) setStage(d.message)
          } else if (d?.stage === 'discovering') {
            setProgress(70)
            setProgressLabel('正在发现竞品…')
          } else if (d?.message) {
            setStage(d.message)
          }
        } else if (type === 'clarify_ready') {
          const d = data as {
            questions?: ClarifyQuestion[]
            partial?: boolean
            competitors_fallback?: boolean
          }
          if (d?.partial) {
            // 仅基础题：立即可答，竞品发现仍在后台（C3）——不关闭流、不置 done
            setQuestions(d?.questions ?? [])
            setReady(true)
            partialDone = true
            setDiscoveryOngoing(true)
            setProgress(50)
            setProgressLabel('基础问卷已就绪，正在发现竞品…')
          } else {
            // 完整问卷（重连 / 在途复用）：原行为，收齐即关闭流
            setQuestions(d?.questions ?? [])
            setReady(true)
            if (d?.competitors_fallback) setCompetitorsFallback(true)
            done = true
            closeRef.current?.() // 问卷已完整送达，主动关闭有限流，避免流关闭触发 onerror 误报
          }
        } else if (type === 'clarify_update') {
          // 竞品发现完成：增量替换整组题目（答案按 id 保留），保持当前步（C4/C5）
          const d = data as {
            questions?: ClarifyQuestion[]
            competitors_fallback?: boolean
            complete?: boolean
          }
          const newQs = d?.questions ?? []
          const wasAtReview = reviewReachedRef.current
          setQuestions(newQs)
          if (d?.competitors_fallback) setCompetitorsFallback(true)
          if (wasAtReview) setStep(newQs.length) // 已在核对屏 → 保持核对屏并补入新题
          setReady(true)
          setDiscoveryOngoing(false)
          setProgress(100)
          done = true
          closeRef.current?.()
        } else if (type === 'error') {
          const d = data as { message?: string }
          setError(d?.message ?? '问卷生成失败')
          setReady(true)
          done = true
        }
      },
      onError: () => {
        if (closed) return
        // 终态已抵达（完整或 partial）后，有限流关闭触发的 onerror 属正常重连，忽略（S2）；
        // partial 后流中断（发现未完成）也不误报，基础题仍可作答（C3 兜底）。
        if (done || partialDone) return
        setError('连接中断，请重试')
        setReady(true)
      },
    })
    closeRef.current = close
    return () => {
      closed = true
      close()
    }
  }, [taskId, runId])

  // 问卷就绪但为空数组（如降级也无题）→ 直接进入工作台（修 T-CP3 空问卷跳 workspace）
  useEffect(() => {
    if (ready && !error && questions.length === 0 && taskId) {
      navigate(`/workspace/${taskId}`, { replace: true, state: { query } })
    }
  }, [ready, error, questions, taskId, query, navigate])

  function retry() {
    setRunId((n) => n + 1)
  }

  function setAns(qid: string, val: unknown) {
    setAnswers((a) => ({ ...a, [qid]: val }))
  }

  // 自动前进：单选选中后快速跳（350ms），多选选中 ≥1 项后停顿跳（1200ms，每次勾选重置）。
  // 文本/滑块不自动跳（需显式确认）。delay 默认单选档，multi 传 MULTI_ADVANCE_MS。
  function scheduleAdvance(delay = SINGLE_ADVANCE_MS) {
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
    advanceTimer.current = setTimeout(() => {
      setStep((s) => s + 1)
      advanceTimer.current = null
    }, delay)
  }
  // 取消挂起的自动前进（手动点下一步 / 上一步 / step 已变时调用，防双跳与误跳）
  function cancelAdvance() {
    if (advanceTimer.current) {
      clearTimeout(advanceTimer.current)
      advanceTimer.current = null
    }
  }
  // 按题型统一触发自动前进：single 选中即跳；multi 选中 ≥1 项后停顿跳，归零则撤销。
  // 放 ClarifyPage（而非 QuestionField），保持题型控件为哑组件、避免「两套触发逻辑」漂移。
  function maybeAdvance(type: ClarifyQuestion['type'], value: unknown) {
    if (type === 'single') {
      scheduleAdvance(SINGLE_ADVANCE_MS)
    } else if (type === 'multi') {
      const n = Array.isArray(value) ? value.length : 0
      if (n > 0) scheduleAdvance(MULTI_ADVANCE_MS)
      else cancelAdvance() // 取消到 0 项 → 撤销挂起的自动前进
    }
  }

  // 添加自定义选项（如用户自己想调研的竞品），加入已选集合并成为可见 chip。
  // 返回合并后的数组（无输入返回 null）。是否自动前进由调用方经 maybeAdvance 决策，
  // 故此处不再持有 schedule 形参——「核对屏不自动前进」规则统一收敛到上层 wiring（review 不调 maybeAdvance）。
  function addCustom(qid: string): string[] | null {
    const raw = (customInputs[qid] ?? '').trim()
    if (!raw) return null
    // 支持一次输入多个，用逗号/顿号/空格分隔
    const items = raw.split(/[,，、\s]+/).map((s) => s.trim()).filter(Boolean)
    const cur = (answers[qid] as string[]) ?? []
    const merged = [...cur]
    for (const it of items) if (!merged.includes(it)) merged.push(it)
    setAnswers((a) => {
      const c = (a[qid] as string[]) ?? []
      const m = [...c]
      for (const it of items) if (!m.includes(it)) m.push(it)
      return { ...a, [qid]: m }
    })
    setCustomInputs((c) => ({ ...c, [qid]: '' }))
    return merged
  }

  async function go() {
    if (submitting || !taskId) return
    cancelAdvance() // 防止单步「跳过」时挂起的自动前进计时器在异步提交期间插队跳步
    setSubmitting(true)
    try {
      await submitClarify(taskId, answers)
    } finally {
      navigate(`/workspace/${taskId}`, { state: { query } })
    }
  }

  // ── loading 态：显示阶段进度，绝不跳转（修 P0#3）──
  if (!ready) {
    return (
      <div className="relative min-h-screen overflow-hidden bg-bg">
        <VSunGlow className="opacity-40" />
        <div className="relative z-10 mx-auto flex min-h-screen max-w-[680px] flex-col items-center justify-center px-6 text-center">
          <Loader2 size={40} className="animate-spin text-primary" />
          <div className="mt-5 text-h3 text-ink">正在为你准备调研问卷</div>
          <div className="mt-2 text-aux text-ink-2">{stage}</div>
        </div>
      </div>
    )
  }

  // ── error 态：提示 + 重试（降级而非静默卡死，P1#5）──
  if (error) {
    return (
      <div className="relative min-h-screen overflow-hidden bg-bg">
        <VSunGlow className="opacity-40" />
        <div className="relative z-10 mx-auto flex min-h-screen max-w-[680px] flex-col items-center justify-center px-6 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-full bg-amber-50 text-amber-500">
            <AlertTriangle size={28} />
          </span>
          <div className="mt-5 text-h3 text-ink">问卷生成遇到问题</div>
          <div className="mt-2 text-aux text-ink-2">{error}</div>
          <button
            onClick={retry}
            className="mt-7 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-12 font-medium text-white shadow-card transition-all hover:bg-primary-deep active:scale-95"
          >
            <RefreshCw size={18} /> 重试
          </button>
        </div>
      </div>
    )
  }

  const isReview = step === questions.length
  // 空问卷守卫：既有 effect 会跳 workspace，但 React 渲染先于 navigate 一帧，
  // 直接 questions[step] 会取到 undefined 而崩溃，故前置返回。
  if (!isReview && questions.length === 0) return null
  const q = !isReview ? questions[step] : null
  const pct = questions.length ? Math.round(((step + 1) / questions.length) * 100) : 0
  const competitorsPresent = questions.some((item) => item.id === 'competitors')

  // 派生：当前题是否为单选/多选（自动前进适用），及已选数量。
  // selectedCount>0 与「自动前进计时器挂起」等价（选中即排程、归零即撤销、前进即切步），
  // 故无需新增 state，直接派生按钮文案与锁定提示。
  const isChoice = q?.type === 'single' || q?.type === 'multi'
  const selectedCount = isChoice
    ? q!.type === 'multi'
      ? ((answers[q!.id] as string[]) ?? []).length
      : answers[q!.id] != null
        ? 1
        : 0
    : 0
  const btnLabel = q?.type === 'multi' && selectedCount > 0 ? '完成本题' : '下一步'

  return (
    <div className="relative min-h-screen overflow-y-auto bg-bg">
      <VSunGlow className="opacity-40" />
      {discoveryOngoing && (
        <div className="sticky top-0 z-20">
          <div className="h-1 w-full bg-line/60">
            <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${progress}%` }} />
          </div>
          <div className="flex items-center justify-center gap-2 bg-bg/90 py-1.5 text-tag text-ink-3 backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            {progressLabel}
            <span className="rounded-full border border-primary/40 px-2 py-0.5 text-primary-deep">竞品识别中…</span>
          </div>
        </div>
      )}
      <div className="relative z-10 mx-auto flex min-h-screen max-w-[680px] flex-col justify-center px-6 py-16">
        {!isReview && q && (
          <>
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="flex items-center gap-2.5">
              <span className="grid h-10 w-10 place-items-center rounded-btn bg-primary-tint text-primary">
                <Sprout size={22} strokeWidth={1.8} />
              </span>
              <div>
                <div className="text-h3 text-ink">在开始前，请确认几个关键点</div>
                <div className="text-aux text-ink-2">这能帮助专家队更精准地锁定调研范围</div>
              </div>
            </motion.div>

            {competitorsFallback && q?.id === 'competitors' && (
              <div className="mt-4 rounded-card border border-line/60 bg-card px-4 py-2.5 text-tag text-ink-3">
                {competitorsPresent
                  ? '以下竞品为自动识别候选，建议核对或手动补充。'
                  : '未能自动识别竞品，可在「补充」题说明你关注的对手。'}
              </div>
            )}

            {query && (
              <motion.div
                variants={fadeUp}
                initial="initial"
                animate="animate"
                className="mt-5 rounded-card border border-line/60 bg-card p-4 text-aux text-ink-2 shadow-card"
              >
                <span className="text-tag text-ink-3">你的需求</span>
                <p className="mt-1 text-body text-ink">{query}</p>
              </motion.div>
            )}

            {/* 进度条 */}
            <div className="mt-6 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line/60">
                <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
              </div>
              <span className="whitespace-nowrap text-tag text-ink-3">第 {step + 1} / {questions.length} 题</span>
            </div>

            <motion.div
              key={step}
              ref={titleRef}
              tabIndex={-1}
              variants={fadeUp}
              initial="initial"
              animate="animate"
              className="mt-5 rounded-card border border-line/60 bg-card p-5 shadow-card outline-none"
            >
              <p className="text-body font-medium text-ink">{q.question}</p>
              {q.hint && <p className="mt-1 text-tag text-ink-3">{q.hint}</p>}

              <QuestionField
                question={q}
                value={answers[q.id]}
                onChange={(v) => {
                  setAns(q.id, v)
                  maybeAdvance(q.type, v)
                }}
                customInput={q.id === 'competitors' ? (customInputs[q.id] ?? '') : undefined}
                onCustomInputChange={
                  q.id === 'competitors' ? (v) => { setCustomInputs((c) => ({ ...c, [q.id]: v })); cancelAdvance() } : undefined
                }
                onCustomAdd={
                  q.id === 'competitors'
                    ? () => {
                        const next = addCustom(q.id)
                        if (next) maybeAdvance('multi', next)
                      }
                    : undefined
                }
              />

              {/* 自动前进锁定提示：选中后短暂窗口内将自动跳，给用户看清 + 可控（点完成本题） */}
              {isChoice && selectedCount > 0 && (
                <div className="mt-3 flex items-center gap-1.5 text-tag text-primary-deep">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                  {q.type === 'single'
                    ? `已选择「${answers[q.id]}」，约 ${(SINGLE_ADVANCE_MS / 1000)} 秒后自动前进`
                    : `已选 ${selectedCount} 项，约 ${(MULTI_ADVANCE_MS / 1000)} 秒后自动前进（或点「完成本题」）`}
                </div>
              )}
            </motion.div>

            <div className="mt-7 flex items-center justify-between">
              <div className="flex items-center gap-3">
                {step > 0 && (
                  <button
                    onClick={() => { cancelAdvance(); setStep((s) => Math.max(0, s - 1)) }}
                    className="inline-flex items-center gap-1.5 text-aux text-ink-3 transition-colors hover:text-ink-2"
                  >
                    上一步
                  </button>
                )}
                <button
                  onClick={go}
                  className="inline-flex items-center gap-1.5 text-aux text-ink-3 transition-colors hover:text-ink-2"
                >
                  <SkipForward size={15} /> 跳过，直接开始
                </button>
              </div>
              <button
                onClick={() => { cancelAdvance(); setStep((s) => s + 1) }}
                className="inline-flex items-center justify-center gap-2 rounded-btn bg-primary px-6 h-12 font-medium text-white shadow-card transition-all hover:bg-primary-deep hover:shadow-float active:scale-95"
              >
                {btnLabel}
                <ArrowRight size={18} />
              </button>
            </div>
          </>
        )}

        {isReview && (
          <>
            <motion.div variants={fadeUp} initial="initial" animate="animate" className="flex items-center gap-2.5">
              <span className="grid h-10 w-10 place-items-center rounded-btn bg-primary-tint text-primary">
                <Sprout size={22} strokeWidth={1.8} />
              </span>
              <div>
                <div className="text-h3 text-ink">请核对，可直接修改</div>
                <div className="text-aux text-ink-2">确认无误后启动调研</div>
              </div>
            </motion.div>

            {competitorsFallback && (
              <div className="mt-4 rounded-card border border-line/60 bg-card px-4 py-2.5 text-tag text-ink-3">
                {competitorsPresent
                  ? '以下竞品为自动识别候选，建议核对或手动补充。'
                  : '未能自动识别竞品，可在「补充」题说明你关注的对手。'}
              </div>
            )}

            <motion.div
              key="review"
              ref={titleRef}
              tabIndex={-1}
              variants={fadeUp}
              initial="initial"
              animate="animate"
              className="mt-6 flex flex-col gap-5 outline-none"
            >
              {questions.map((item) => (
                <div key={item.id} className="rounded-card border border-line/60 bg-card p-5 shadow-card">
                  <p className="text-body font-medium text-ink">{item.question}</p>
                  {item.hint && <p className="mt-1 text-tag text-ink-3">{item.hint}</p>}

                  <QuestionField
                    question={item}
                    value={answers[item.id]}
                    onChange={(v) => setAns(item.id, v)}
                    customInput={item.id === 'competitors' ? (customInputs[item.id] ?? '') : undefined}
                    onCustomInputChange={
                      item.id === 'competitors' ? (v) => setCustomInputs((c) => ({ ...c, [item.id]: v })) : undefined
                    }
                    onCustomAdd={item.id === 'competitors' ? () => addCustom(item.id) : undefined}
                  />
                </div>
              ))}
            </motion.div>

            <div className="mt-7 flex items-center justify-between">
              <button
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className="inline-flex items-center gap-1.5 text-aux text-ink-3 transition-colors hover:text-ink-2"
              >
                上一步
              </button>
              <button
                onClick={go}
                disabled={submitting}
                className="inline-flex items-center justify-center gap-2 rounded-btn bg-primary px-6 h-12 font-medium text-white shadow-card transition-all hover:bg-primary-deep hover:shadow-float active:scale-95 disabled:opacity-50"
              >
                {submitting ? '正在派遣专家队…' : '启动调研'}
                <ArrowRight size={18} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
