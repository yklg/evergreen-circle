import { motion } from 'framer-motion'
import { ShieldCheck, ShieldAlert, ShieldQuestion, Link2 } from 'lucide-react'
import type { Claim } from '../types'
import { useExpertStore } from '../store/expertStore'

const CONF_META = {
  high: { label: '高置信', cls: 'bg-ok/15 text-ok', icon: ShieldCheck },
  medium: { label: '中置信', cls: 'bg-warn/15 text-warn', icon: ShieldCheck },
  low: { label: '低置信', cls: 'bg-risk/15 text-risk', icon: ShieldAlert },
  unverified: { label: '待验证', cls: 'bg-ink-3/15 text-ink-3', icon: ShieldQuestion },
} as const

/** 论点卡：结论文本 + 置信度徽标 + 交叉验证标记 + 证据引用数 + 作者。 */
export function VClaimCard({
  claim,
  onCite,
}: {
  claim: Claim
  onCite?: (evidenceIds: string[]) => void
}) {
  const byId = useExpertStore((s) => s.byId)
  const meta = CONF_META[claim.confidence] ?? CONF_META.unverified
  const Icon = meta.icon
  const author = byId(claim.author)
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-card border border-line/60 bg-card p-4 shadow-card"
    >
      <p className="text-body text-ink">{claim.text}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1 rounded-chip px-2.5 h-6 text-tag font-medium ${meta.cls}`}>
          <Icon size={12} /> {meta.label}
        </span>
        {claim.cross_validated && (
          <span className="inline-flex items-center gap-1 rounded-chip bg-primary-tint px-2.5 h-6 text-tag font-medium text-primary-deep">
            交叉验证
          </span>
        )}
        {claim.evidence_ids.length > 0 ? (
          <button
            onClick={() => onCite?.(claim.evidence_ids)}
            className="inline-flex items-center gap-1 rounded-chip border border-line px-2.5 h-6 text-tag text-ink-2 transition-colors hover:bg-primary-tint hover:text-primary-deep"
          >
            <Link2 size={12} /> {claim.evidence_ids.length} 条证据
          </button>
        ) : (
          <span className="text-tag text-ink-3">无证据引用</span>
        )}
        {author && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-tag text-ink-3">
            <img src={author.avatar} alt={author.name} className="h-4 w-4 rounded-full object-cover" />
            {author.name}
          </span>
        )}
      </div>
    </motion.div>
  )
}
