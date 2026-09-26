import { RotateCcw, ArrowRight } from 'lucide-react'

interface QualityData {
  confidence_ratio?: number
  dimension_coverage_rate?: number
  destination_coverage_rate?: number
  schema_completeness?: number
}

const METRICS: { key: keyof QualityData; label: string }[] = [
  { key: 'confidence_ratio', label: '高置信占比' },
  { key: 'dimension_coverage_rate', label: '维度覆盖' },
  { key: 'destination_coverage_rate', label: '目的地覆盖' },
  { key: 'schema_completeness', label: '结构完整' },
]

/** 质检返工闭环：展示返工前后质量指标对比（对应需求 12）。 */
export function VQualityGate({ before, after }: { before?: QualityData; after?: QualityData }) {
  if (!before || !after) return null
  const changed = METRICS.some((m) => (before[m.key] ?? 0) !== (after[m.key] ?? 0))
  if (!changed) return null

  return (
    <div className="my-6 rounded-card border border-warn/40 bg-sun-soft p-4">
      <div className="flex items-center gap-1.5 text-aux font-semibold text-warn">
        <RotateCcw size={14} /> 质检反馈闭环 · 返工前后对比
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {METRICS.map((m) => {
          const b = Math.round((before[m.key] ?? 0) * 100)
          const a = Math.round((after[m.key] ?? 0) * 100)
          const up = a > b
          return (
            <div key={m.key} className="rounded-btn bg-white/70 p-2.5">
              <div className="text-tag text-ink-3">{m.label}</div>
              <div className="mt-1 flex items-center gap-1.5 text-aux">
                <span className="text-ink-3 line-through">{b}%</span>
                <ArrowRight size={12} className="text-ink-3" />
                <span className={`font-bold ${up ? 'text-ok' : 'text-ink'}`}>{a}%</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
