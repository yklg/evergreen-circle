import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Activity, ChevronDown, ChevronUp, X, Cpu, Clock } from 'lucide-react'
import type { TraceSpan } from '../types'
import { useExpertStore } from '../store/expertStore'

const STAGE_LABEL: Record<string, string> = {
  intake: '需求理解',
  orchestrator: '编排派遣',
  collect: '证据采集',
  analyze: '交叉分析',
  spots: '景点实体',
  write: '报告撰写',
  audit: '质检审裁',
  done: '签发交付',
}

/** 工作台悬浮可拖拽日志面板：实时滚动展示每个 Agent 的 LLM 调用 trace。
 *  revealKey 递增时强制展开（供外部入口唤起，如目的地降级横幅）；面板自身开合不受影响。 */
export function VTracePanel({ traces, revealKey = 0 }: { traces: TraceSpan[]; revealKey?: number }) {
  const byId = useExpertStore((s) => s.byId)
  const [open, setOpen] = useState(true)
  const [collapsed, setCollapsed] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (revealKey > 0) {
      setOpen(true)
      setCollapsed(false)
    }
  }, [revealKey])

  useEffect(() => {
    if (open && !collapsed) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [traces.length, open, collapsed])

  const totalTokens = traces.reduce((a, s) => a + (s.total_tokens || 0), 0)

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-full bg-primary-deep px-4 py-2.5 text-aux font-medium text-white shadow-lg"
      >
        <Activity size={15} />
        决策日志 · {traces.length}
      </button>
    )
  }

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragConstraints={{ left: -window.innerWidth + 380, right: 20, top: -window.innerHeight + 200, bottom: 20 }}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed bottom-5 right-5 z-50 w-[360px] overflow-hidden rounded-card border border-line bg-white/95 shadow-xl backdrop-blur"
    >
      {/* 标题栏（可拖拽手柄）*/}
      <div className="flex cursor-move items-center justify-between bg-primary-deep px-3.5 py-2.5 text-white">
        <div className="flex items-center gap-2">
          <Activity size={15} />
          <span className="text-aux font-semibold">Agent 决策日志 · Trace</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded-chip bg-white/20 px-2 py-0.5 text-tag">{traces.length} 步</span>
          <button onClick={() => setCollapsed((v) => !v)} aria-label="折叠决策日志" className="opacity-80 hover:opacity-100">
            {collapsed ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
          <button onClick={() => setOpen(false)} aria-label="关闭决策日志" className="opacity-80 hover:opacity-100">
            <X size={15} />
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          <div className="flex items-center gap-3 border-b border-line bg-paper px-3.5 py-2 text-tag text-ink-3">
            <span className="flex items-center gap-1"><Cpu size={11} /> 累计 {totalTokens.toLocaleString()} tokens</span>
            <span className="flex items-center gap-1"><Clock size={11} /> {traces.length} 次调用</span>
          </div>
          <div className="max-h-[42vh] overflow-y-auto px-2.5 py-2">
            {traces.length === 0 ? (
              <p className="px-2 py-6 text-center text-aux text-ink-3">等待 Agent 开始调用……</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                <AnimatePresence initial={false}>
                  {traces.map((sp) => {
                    const ex = sp.agent_id ? byId(sp.agent_id) : undefined
                    const isOpen = expandedId === sp.span_id
                    return (
                      <motion.div
                        key={sp.span_id}
                        initial={{ opacity: 0, x: 10 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="rounded-lg border border-line bg-white px-2.5 py-2"
                      >
                        <button
                          onClick={() => setExpandedId(isOpen ? null : sp.span_id)}
                          className="flex w-full items-center gap-2 text-left"
                        >
                          <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary-tint text-tag font-bold text-primary-deep">
                            {sp.seq}
                          </span>
                          <span className="rounded-chip bg-paper px-1.5 py-0.5 text-tag text-ink-3">
                            {STAGE_LABEL[sp.stage] || sp.stage}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-tag text-ink-2">
                            {sp.purpose || sp.decision || '调用'}
                          </span>
                          <span className="shrink-0 text-tag text-ink-3">{(sp.latency_ms / 1000).toFixed(1)}s</span>
                        </button>
                        <div className="mt-1 flex items-center gap-2 pl-7 text-tag text-ink-3">
                          <span className="rounded bg-ok/10 px-1 text-ok">{sp.model}</span>
                          <span>{sp.total_tokens} tok</span>
                          {ex && <span>· {ex.name}</span>}
                        </div>
                        {isOpen && (
                          <div className="mt-2 space-y-1.5 border-t border-line pt-2 pl-1">
                            <div>
                              <div className="text-tag font-medium text-ink-3">Prompt</div>
                              <p className="mt-0.5 max-h-24 overflow-y-auto rounded bg-paper p-1.5 text-tag leading-relaxed text-ink-2">
                                {sp.prompt}
                              </p>
                            </div>
                            <div>
                              <div className="text-tag font-medium text-ink-3">Output</div>
                              <p className="mt-0.5 max-h-24 overflow-y-auto rounded bg-paper p-1.5 text-tag leading-relaxed text-ink-2">
                                {sp.response}
                              </p>
                            </div>
                            <div className="text-tag text-ink-3">
                              tokens：输入 {sp.prompt_tokens} · 输出 {sp.completion_tokens} · 合计 {sp.total_tokens}
                            </div>
                          </div>
                        )}
                      </motion.div>
                    )
                  })}
                </AnimatePresence>
                <div ref={endRef} />
              </div>
            )}
          </div>
        </>
      )}
    </motion.div>
  )
}
