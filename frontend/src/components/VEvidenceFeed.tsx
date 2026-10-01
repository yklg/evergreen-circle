import { motion } from 'framer-motion'
import { ExternalLink, FileText } from 'lucide-react'
import type { Evidence } from '../types'
import { kindLabel } from '../lib/sourceKindsClient'

/* 标签的唯一真相源是后端信源类别注册表（app/core/source_type.py）：
   这里曾手抄一张 7 项 `SOURCE_LABEL`，于是新类别 `user_supplied` 上屏显示成裸 key，
   而且没有任何东西会变红（计划 v3 §二 G0 的展示面）。颜色仍归前端（表现，不是口径）。 */

const SOURCE_CLS: Record<string, string> = {
  douyin: 'bg-ink/10 text-ink',
  xiaohongshu: 'bg-risk/15 text-risk',
  bilibili: 'bg-info/15 text-info',
  weibo: 'bg-warn/15 text-warn',
  zhihu: 'bg-primary-tint text-primary-deep',
  official: 'bg-ok/15 text-ok',
  review: 'bg-sun-soft text-warn',
  user_supplied: 'bg-primary text-white',
}

/** 单条证据卡。credibility 为 0-100 整数。 */
export function VEvidenceCard({ ev, index, highlighted }: { ev: Evidence; index?: number; highlighted?: boolean }) {
  const label = kindLabel(ev.source_type)
  const cls = SOURCE_CLS[ev.source_type] ?? 'bg-primary-tint text-primary-deep'
  // 兼容旧数据：>1 视为 0-100 整数，<=1 视为 0-1 小数
  const credPct = ev.credibility > 1 ? Math.round(ev.credibility) : Math.round(ev.credibility * 100)
  const fdays = ev.freshness_days
  const freshLabel =
    fdays == null ? '' : fdays <= 30 ? '近一月' : fdays <= 365 ? '近一年' : fdays <= 730 ? '1-2年' : '较早'
  return (
    <motion.a
      id={`ev-${ev.evidence_id}`}
      href={ev.source_url}
      target="_blank"
      rel="noreferrer"
      initial={{ opacity: 0, x: 8 }}
      animate={highlighted ? { opacity: 1, x: 0, scale: [1, 1.04, 1] } : { opacity: 1, x: 0 }}
      transition={highlighted ? { duration: 0.7 } : undefined}
      className={`group block rounded-card border bg-card p-3.5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-float ${
        highlighted ? 'border-primary ring-2 ring-primary/40' : 'border-line/60'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center rounded-chip px-2 h-5 text-tag font-medium ${cls}`}>
          {label}
        </span>
        {typeof index === 'number' && (
          <span className="text-tag text-ink-3">#{index + 1}</span>
        )}
        {freshLabel && (
          <span className="rounded-chip bg-bg px-1.5 h-5 inline-flex items-center text-tag text-ink-3">{freshLabel}</span>
        )}
        <span className="ml-auto inline-flex items-center gap-1 text-tag text-ink-3">
          可信度 {credPct}
        </span>
      </div>
      <div className="mt-2 flex items-start gap-1.5">
        <FileText size={14} className="mt-0.5 shrink-0 text-ink-3" />
        <span className="line-clamp-1 text-aux font-medium text-ink">{ev.title}</span>
        <ExternalLink size={13} className="ml-auto shrink-0 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <p className="mt-1.5 line-clamp-2 text-tag leading-relaxed text-ink-2">{ev.excerpt}</p>
    </motion.a>
  )
}

/** 实时证据流。 */
export function VEvidenceFeed({ evidences }: { evidences: Evidence[] }) {
  if (evidences.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-ink-3">
        <FileText size={28} strokeWidth={1.5} />
        <p className="text-aux">证据采集中，稍候片刻……</p>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {evidences.map((ev, i) => (
        <VEvidenceCard key={ev.evidence_id} ev={ev} index={i} />
      ))}
    </div>
  )
}
