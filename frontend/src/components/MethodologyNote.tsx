import { Info, AlertTriangle, Link2 } from 'lucide-react'
import type { ReportContradiction, ReportMethodology } from '../types'

/**
 * 方法论与局限披露（v2.1 客观性加固）：
 * 报告页侧栏「术语表」之后的附录区块——页首简短摘要 + 完整键值。
 * 纯文本渲染（无 dangerouslySetInnerHTML，防注入）；空数据自动隐藏。
 */
export default function MethodologyNote({
  methodology,
  contradictions,
}: {
  methodology?: ReportMethodology
  contradictions?: ReportContradiction[]
}) {
  if (!methodology) return null

  const rows: { label: string; value: string }[] = []
  if (typeof methodology.evidence_count === 'number') {
    rows.push({ label: '证据总数', value: String(methodology.evidence_count) })
  }
  if (typeof methodology.unique_groups === 'number') {
    rows.push({ label: '独立信源组', value: String(methodology.unique_groups) })
  }
  if (typeof methodology.dup_skipped === 'number') {
    rows.push({ label: '同质转载去重', value: String(methodology.dup_skipped) })
  }
  if (typeof methodology.viral_evidence === 'number') {
    rows.push({ label: '舆论过热标注', value: String(methodology.viral_evidence) })
  }
  if (typeof methodology.viral_checked_ratio === 'number') {
    rows.push({ label: '过热判定覆盖率', value: `${Math.round(methodology.viral_checked_ratio * 100)}%` })
  }
  if (typeof methodology.sentiment_samples === 'number') {
    if (typeof methodology.sentiment_corpus === 'number') {
      // 新口径：`sentiment_samples` 已收窄为「可核验用户口碑」条数，必须与检索语料并排显示，
      // 否则读者会拿新的 7 去比旧的 25，误读成「口碑暴跌」。
      rows.push({ label: '有效口碑', value: `${methodology.sentiment_samples} 条` })
      rows.push({ label: '检索相关语料', value: `${methodology.sentiment_corpus} 条` })
      if (methodology.sentiment_low_sample) {
        rows.push({ label: '情感呈现', value: '样本偏小·只报计数' })
      }
    } else {
      // 存量报告（本次之前生成）：只有旧口径那一个数，按今天的样子显示，不追注新口径。
      rows.push({ label: '舆情样本量', value: String(methodology.sentiment_samples) })
    }
  }
  if (methodology.window) {
    rows.push({ label: '搜索时效窗口', value: methodology.window })
  }

  const hasData = rows.length > 0 || !!methodology.note
  if (!hasData) return null

  const contrads = (contradictions || []).slice(0, 8)

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center gap-1.5 text-tag font-semibold text-ink-3">
        <Info size={13} /> 方法论与局限
      </div>
      <div className="rounded-card border border-line/60 bg-bg p-3">
        {rows.length > 0 && (
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {rows.map((r) => (
              <div key={r.label} className="flex items-baseline justify-between gap-2">
                <span className="text-tag text-ink-3">{r.label}</span>
                <span className="text-tag font-medium text-ink">{r.value}</span>
              </div>
            ))}
          </div>
        )}
        {methodology.note && (
          <p className="mt-2 text-tag leading-relaxed text-ink-2">{methodology.note}</p>
        )}
      </div>

      {contrads.length > 0 && (
        <div className="mt-3">
          <div className="mb-2 flex items-center gap-1.5 text-tag font-semibold text-ink-3">
            <AlertTriangle size={13} /> 存在分歧/未证实的陈述
          </div>
          <div className="flex flex-col gap-2">
            {contrads.map((c, i) => (
              <div key={i} className="rounded-card border border-warn/40 bg-bg p-3">
                <p className="text-tag leading-relaxed text-ink">{c.claim_text}</p>
                {c.note && <p className="mt-1 text-tag text-ink-2">{c.note}</p>}
                {c.evidence_ids && c.evidence_ids.length > 0 && (
                  <div className="mt-1.5 flex items-center gap-1 text-tag text-primary-deep">
                    <Link2 size={12} />
                    <span>{c.evidence_ids.map((id) => `[${id}]`).join(' ')}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}