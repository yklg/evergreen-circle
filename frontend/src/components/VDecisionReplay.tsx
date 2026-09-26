import { useState } from 'react'
import { motion } from 'framer-motion'
import { PlayCircle, X, SkipBack, SkipForward, Cpu } from 'lucide-react'
import type { TraceSpan } from '../types'
import { useExpertStore } from '../store/expertStore'

const STAGE_LABEL: Record<string, string> = {
  intake: '需求理解', orchestrator: '编排派遣', collect: '证据采集',
  analyze: '交叉分析', spots: '景点实体', write: '报告撰写', audit: '质检审裁', done: '签发交付',
}

/** 报告页决策回放：拖动进度条回溯每个 Agent 的思考过程，高亮其关联证据。 */
export function VDecisionReplay({
  trace,
  onHighlightEvidence,
}: {
  trace: TraceSpan[]
  onHighlightEvidence?: (ids: string[]) => void
}) {
  const byId = useExpertStore((s) => s.byId)
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)

  if (!trace?.length) return null
  const cur = trace[Math.min(step, trace.length - 1)]
  const ex = cur.agent_id ? byId(cur.agent_id) : undefined

  function go(next: number) {
    const s = Math.max(0, Math.min(trace.length - 1, next))
    setStep(s)
    const sp = trace[s]
    if (sp.evidence_ids?.length) onHighlightEvidence?.(sp.evidence_ids)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-btn bg-card/90 px-3 h-9 text-aux font-medium text-ink-2 backdrop-blur hover:text-primary-deep"
      >
        <PlayCircle size={15} /> 决策回放
      </button>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed bottom-5 left-1/2 z-50 w-[min(640px,92vw)] -translate-x-1/2 overflow-hidden rounded-card border border-line bg-white/97 shadow-xl backdrop-blur"
    >
      <div className="flex items-center justify-between bg-primary-deep px-4 py-2.5 text-white">
        <div className="flex items-center gap-2 text-aux font-semibold">
          <PlayCircle size={15} /> 决策回放 · 第 {step + 1}/{trace.length} 步
        </div>
        <button onClick={() => setOpen(false)} className="opacity-80 hover:opacity-100"><X size={15} /></button>
      </div>

      <div className="px-4 py-3">
        <div className="flex items-center gap-2">
          {ex && <img src={ex.avatar} alt={ex.name} className="h-8 w-8 rounded-full object-cover" />}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag font-medium text-primary-deep">
                {STAGE_LABEL[cur.stage] || cur.stage}
              </span>
              <span className="text-tag text-ink-3">{ex?.name || cur.agent_id}</span>
              <span className="ml-auto inline-flex items-center gap-1 text-tag text-ink-3">
                <Cpu size={11} /> {cur.model} · {cur.total_tokens} tok · {(cur.latency_ms / 1000).toFixed(1)}s
              </span>
            </div>
            <div className="mt-1 text-aux font-medium text-ink">{cur.purpose || cur.decision || '调用'}</div>
          </div>
        </div>

        <div className="mt-2 max-h-28 overflow-y-auto rounded-btn bg-bg p-2 text-tag leading-relaxed text-ink-2">
          {cur.response || cur.prompt}
        </div>

        {cur.evidence_ids && cur.evidence_ids.length > 0 && (
          <button
            onClick={() => onHighlightEvidence?.(cur.evidence_ids!)}
            className="mt-2 text-tag text-primary-deep hover:underline"
          >
            高亮本步关联的 {cur.evidence_ids.length} 条证据 →
          </button>
        )}

        {/* 进度条 scrubber */}
        <div className="mt-3 flex items-center gap-2">
          <button onClick={() => go(step - 1)} className="text-ink-3 hover:text-primary-deep"><SkipBack size={16} /></button>
          <input
            type="range"
            min={0}
            max={trace.length - 1}
            value={step}
            onChange={(e) => go(Number(e.target.value))}
            className="h-1.5 flex-1 cursor-pointer accent-primary"
          />
          <button onClick={() => go(step + 1)} className="text-ink-3 hover:text-primary-deep"><SkipForward size={16} /></button>
        </div>
      </div>
    </motion.div>
  )
}
