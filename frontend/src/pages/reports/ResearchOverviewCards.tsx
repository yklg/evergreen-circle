import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Network, Trash2 } from 'lucide-react'
import { VCard } from '../../components/ui'
import { intelCardToRow, type ReportRecord } from '../../lib/recordIndex'
import type { IntelOverview, ResearchCard } from '../../types'
import { CardTitle } from './CardTitle'
import { VISIBLE_CARDS, overviewTruncation } from './overviewTruncation'

function Mini({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-btn bg-card/60 py-1.5">
      <div className={`text-aux font-semibold ${accent ? 'text-primary-deep' : 'text-ink'}`}>{value}</div>
      <div className="text-tag text-ink-3">{label}</div>
    </div>
  )
}

function OverviewCard({ card, onDelete }: { card: ResearchCard; onDelete: (r: ReportRecord) => void }) {
  return (
    <div className="rounded-card border border-line/60 bg-bg p-4 transition-all hover:border-primary-soft hover:bg-card">
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/report/${card.id}`}
          className="line-clamp-2 text-aux font-medium text-ink hover:text-primary-deep"
        >
          {card.title}
        </Link>
        <button
          type="button"
          aria-label="删除目的地调研"
          onClick={() => onDelete(intelCardToRow(card))}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-btn text-ink-3 hover:bg-risk/10 hover:text-risk"
        >
          <Trash2 size={14} />
        </button>
      </div>
      {card.destinations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {card.destinations.slice(0, 4).map((d) => (
            <span key={d} className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">
              {d}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Mini label="证据" value={`${card.evidence_count}`} />
        <Mini label="结论" value={`${card.claim_count}`} />
        <Mini label="高置信" value={`${card.high_conf_count}`} />
        <Mini label="效率" value={card.efficiency_multiple ? `${card.efficiency_multiple}×` : '—'} accent />
        <Mini label="省时" value={card.minutes_saved ? `${Math.round(card.minutes_saved)} 分钟` : '—'} accent />
        <Mini label="耗时" value={card.elapsed_minutes ? `${card.elapsed_minutes} 分钟` : '—'} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Link
          to={`/report/${card.id}`}
          className="inline-flex h-7 items-center gap-1 rounded-btn bg-primary-tint px-2.5 text-tag font-medium text-primary-deep hover:bg-primary-soft/50"
        >
          <FileText size={12} /> 报告
        </Link>
        <Link
          to={`/trace/${card.id}`}
          className="inline-flex h-7 items-center gap-1 rounded-btn bg-bg px-2.5 text-tag font-medium text-ink-2 ring-1 ring-line hover:text-primary-deep"
        >
          <Network size={12} /> 决策日志
        </Link>
      </div>
    </div>
  )
}

/**
 * 「每次调研概览」卡片块（B 档：默认只画 `VISIBLE_CARDS` 份，截断必须写在脸上）。
 *
 * 换件前这里是 7 列 `<table>`。卡片形态读单份报告更省力，但表格"一眼数得完"的优点
 * 会随截断丢掉 —— 所以说明、按钮名与右下角的计数三处同时报数，任何一档状态都能核对。
 */
export default function ResearchOverviewCards({
  intel,
  onDelete,
}: {
  intel: IntelOverview
  onDelete: (r: ReportRecord) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const trunc = overviewTruncation(intel)
  const shown = trunc && !expanded ? intel.cards.slice(0, VISIBLE_CARDS) : intel.cards

  return (
    <VCard hover={false}>
      <div className="flex items-baseline gap-2">
        <CardTitle title="每次调研概览" hint={`共 ${intel.report_total} 份`} />
        {trunc && <span className="text-tag text-warn">{trunc.note}</span>}
      </div>

      {shown.length === 0 ? (
        <p className="mt-3 text-tag text-ink-3">
          库里还没有调研报告 —— 发起一次调研后，这里会长出概览卡。（整屏情报已取到，这不是取数失败）
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((c) => (
            <OverviewCard key={c.id} card={c} onDelete={onDelete} />
          ))}
        </div>
      )}

      {trunc && (
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex h-7 items-center rounded-btn bg-primary-tint px-3 text-tag font-medium text-primary-deep hover:bg-primary-soft/50"
          >
            {expanded ? '收起' : trunc.expandLabel}
          </button>
          <span className="ml-auto text-tag text-ink-3">
            当前 {shown.length} 张 · 已取回 {intel.cards.length} 份 · 库内 {intel.report_total} 份
          </span>
        </div>
      )}
    </VCard>
  )
}
