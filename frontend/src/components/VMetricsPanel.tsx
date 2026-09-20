import { Gauge, Layers, ShieldCheck, TrendingUp } from 'lucide-react'
import type { ReportMetrics } from '../types'

function pct(v: unknown): string {
  if (v == null || typeof v !== 'number') return '—'
  return `${Math.round(v * 100)}%`
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined
}

function num(v: unknown): number {
  return typeof v === 'number' ? v : 0
}

/** 量化提升 + 业务闭环指标面板（对应需求 17/19）。每项 title 展示公式可解释。 */
export function VMetricsPanel({ metrics }: { metrics?: ReportMetrics }) {
  if (!metrics) return null
  const eff = metrics.efficiency || {}
  const cov = metrics.coverage || {}
  const con = metrics.consistency || {}
  const biz = metrics.business || {}

  const cards = [
    {
      icon: TrendingUp, label: '效率提升', tint: 'text-primary',
      value: eff.efficiency_multiple != null ? `${eff.efficiency_multiple}×` : '—',
      sub: `实际 ${eff.elapsed_minutes ?? '—'} 分钟 vs 人工约 ${eff.manual_estimate_minutes ?? '—'} 分钟`,
      tip: str(eff.formula),
    },
    {
      icon: Layers, label: '信息覆盖度', tint: 'text-info',
      value: cov.coverage_multiple != null ? `${cov.coverage_multiple}×` : '—',
      sub: `${cov.independent_sources ?? 0} 个独立信源 · ${cov.platforms_covered ?? 0} 个平台`,
      tip: str(cov.formula),
    },
    {
      icon: ShieldCheck, label: '结构一致性', tint: 'text-ok',
      value: pct(con.value),
      sub: `挂证据论点 ${pct(con.claims_with_evidence_ratio)} · Schema ${pct(con.schema_completeness)}`,
      tip: str(con.formula),
    },
    {
      icon: Gauge, label: '事实准确率', tint: 'text-warn',
      value: pct(biz.accuracy),
      sub: `交叉验证 ${pct(biz.cross_validated_ratio)} · 返工 ${biz.rework_rounds ?? 0} 轮`,
      tip: str(biz.formula),
    },
  ]

  return (
    <div className="my-6">
      <div className="mb-3 flex items-center gap-1.5 text-aux font-semibold text-ink">
        <Gauge size={15} className="text-primary" /> 效能与业务闭环指标（公式透明可解释）
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map((c) => {
          const Icon = c.icon
          return (
            <div key={c.label} title={c.tip} className="rounded-card border border-line bg-white p-3.5">
              <div className={`flex items-center gap-1.5 text-tag ${c.tint}`}>
                <Icon size={13} /> {c.label}
              </div>
              <div className="mt-1 text-2xl font-bold text-ink">{c.value}</div>
              <div className="mt-0.5 text-tag leading-snug text-ink-3">{c.sub}</div>
            </div>
          )
        })}
      </div>
      {/* 业务闭环细分指标 */}
      <div className="mt-3 flex flex-wrap gap-2 text-tag">
        <Pill label="维度覆盖率" value={pct(biz.dimension_coverage)} />
        <Pill label="品牌覆盖率" value={pct(biz.brand_coverage)} />
        <Pill label="人工修正率" value={biz.correction_rate != null ? pct(biz.correction_rate) : '待反馈'} />
        <Pill label="Token 消耗" value={num(eff.tokens_used).toLocaleString()} />
      </div>
    </div>
  )
}

function Pill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-chip bg-paper px-2.5 py-1 text-ink-2">
      <span className="text-ink-3">{label}</span>
      <span className="font-semibold text-primary-deep">{value}</span>
    </span>
  )
}
