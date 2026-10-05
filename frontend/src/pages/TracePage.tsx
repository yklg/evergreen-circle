import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, Cpu, Clock, Filter } from 'lucide-react'
import type { TraceSpan } from '../types'
import { fetchReportTrace } from '../lib/api'
import { useExpertStore } from '../store/expertStore'

const STAGE_LABEL: Record<string, string> = {
  intake: '需求理解', orchestrator: '编排派遣', collect: '证据采集',
  sentiment: '聚合口碑舆情', write: '报告撰写', audit: '质检审裁', done: '签发交付',
}
const STAGES = ['all', 'intake', 'orchestrator', 'collect', 'sentiment', 'write', 'audit', 'done']

/** 独立 Trace 页签：结构化展示每个 Agent 的完整调用链路（Prompt/输出/Token/决策）。 */
export default function TracePage() {
  const { reportId } = useParams()
  const navigate = useNavigate()
  const byId = useExpertStore((s) => s.byId)
  const [spans, setSpans] = useState<TraceSpan[]>([])
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    if (reportId) fetchReportTrace(reportId).then((r) => setSpans(r.spans || []))
  }, [reportId])

  const filtered = filter === 'all' ? spans : spans.filter((s) => s.stage === filter)
  const totalTokens = spans.reduce((a, s) => a + (s.total_tokens || 0), 0)
  const totalMs = spans.reduce((a, s) => a + (s.latency_ms || 0), 0)

  return (
    <div className="min-h-screen w-screen bg-bg">
      <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line bg-card/80 px-5 backdrop-blur">
        <button onClick={() => navigate(`/report/${reportId}`)} className="grid h-9 w-9 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint">
          <ChevronLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="text-aux font-semibold text-ink">Agent 决策链路 · Trace</div>
          <div className="text-tag text-ink-3">每个 Agent 的 Prompt / 输出 / Token / 决策全程可查可追溯</div>
        </div>
        <div className="flex items-center gap-3 text-tag text-ink-2">
          <span className="inline-flex items-center gap-1"><Cpu size={13} /> {totalTokens.toLocaleString()} tokens</span>
          <span className="inline-flex items-center gap-1"><Clock size={13} /> {(totalMs / 1000).toFixed(1)}s · {spans.length} 步</span>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-6">
        {/* 阶段过滤 */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Filter size={14} className="text-ink-3" />
          {STAGES.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`rounded-chip px-3 py-1 text-tag font-medium transition-colors ${
                filter === s ? 'bg-primary text-white' : 'bg-card text-ink-2 hover:bg-primary-tint'
              }`}
            >
              {s === 'all' ? '全部' : STAGE_LABEL[s]}
            </button>
          ))}
        </div>

        {filtered.length === 0 ? (
          <p className="py-16 text-center text-aux text-ink-3">暂无 Trace 数据。</p>
        ) : (
          <div className="relative space-y-3 border-l-2 border-line pl-6">
            {filtered.map((sp) => {
              const ex = sp.agent_id ? byId(sp.agent_id, 'travel') : undefined
              const isOpen = expanded === sp.span_id
              return (
                <div key={sp.span_id} className="relative">
                  <span className="absolute -left-[31px] top-3 grid h-5 w-5 place-items-center rounded-full bg-primary text-tag font-bold text-white">
                    {sp.seq}
                  </span>
                  <div className="rounded-card border border-line bg-white p-4">
                    <button onClick={() => setExpanded(isOpen ? null : sp.span_id)} className="flex w-full items-center gap-2 text-left">
                      {ex && <img src={ex.avatar} alt={ex.name} className="h-7 w-7 rounded-full object-cover" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag font-medium text-primary-deep">
                            {STAGE_LABEL[sp.stage] || sp.stage}
                          </span>
                          <span className="text-tag text-ink-3">{ex?.name || sp.agent_id}</span>
                        </div>
                        <div className="mt-0.5 text-aux font-medium text-ink">{sp.purpose || sp.decision}</div>
                      </div>
                      <div className="shrink-0 text-right text-tag text-ink-3">
                        <div className="rounded bg-ok/10 px-1.5 text-ok">{sp.model}</div>
                        <div className="mt-0.5">{sp.total_tokens} tok · {(sp.latency_ms / 1000).toFixed(1)}s</div>
                      </div>
                    </button>
                    {isOpen && (
                      <div className="mt-3 space-y-2 border-t border-line pt-3 text-tag">
                        <div>
                          <div className="font-medium text-ink-3">Prompt（输入）</div>
                          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg p-2 leading-relaxed text-ink-2">{sp.prompt}</pre>
                        </div>
                        <div>
                          <div className="font-medium text-ink-3">Output（输出）</div>
                          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg p-2 leading-relaxed text-ink-2">{sp.response}</pre>
                        </div>
                        <div className="flex gap-4 text-ink-3">
                          <span>输入 {sp.prompt_tokens} tok</span>
                          <span>输出 {sp.completion_tokens} tok</span>
                          <span>合计 {sp.total_tokens} tok</span>
                          <span>耗时 {(sp.latency_ms / 1000).toFixed(2)}s</span>
                        </div>
                        {sp.evidence_ids && sp.evidence_ids.length > 0 && (
                          <div className="text-ink-3">关联证据：{sp.evidence_ids.join(', ')}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
