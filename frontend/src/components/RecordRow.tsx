/**
 * 归档记录行 —— 来源举证的唯一渲染出口。
 *
 * 文案一律由 `dataOriginBadge` / `degradeBanner` / `scoreGrade` 产出：列表层自己
 * 再拼一套 chip 就是「同一口径 N 处实现」（`lib/livingCircle.ts` 已为此写明纪律），
 * 历史页当年的「真实路网测评」即由此长出，与报告页的「真实数据」并存过。
 */
import { FileText, GitCompare, MapPin, Trash2, TriangleAlert } from 'lucide-react'
import type { ReportRecord } from '../lib/recordIndex'
import { RECORD_DOMAIN_LABEL, isComparableScore, fmtRecordTime } from '../lib/recordIndex'
import { dataOriginBadge, degradeBanner, scoreGrade, type OriginTone } from '../lib/livingCircle'

const TONE_CLASS: Record<OriginTone, string> = {
  live: 'bg-primary-tint text-primary-deep',
  warn: 'border border-warn/60 bg-warn/10 text-[#8A6420]',
  info: 'border border-line bg-bg text-ink-2',
}

export default function RecordRow({
  record,
  onOpen,
  onDelete,
}: {
  record: ReportRecord
  onOpen: (id: string) => void
  onDelete?: (record: ReportRecord) => void
}) {
  const scorable = isComparableScore(record)
  const grade = scorable ? scoreGrade(record.total_score ?? 0) : null
  const origin = record.data_origin
    ? dataOriginBadge({ data_origin: record.data_origin, served_from: record.served_from })
    : null
  const degrade = record.degraded ? degradeBanner(record) : null

  return (
    <div className="group flex items-center gap-4 rounded-card border border-line/60 bg-card p-4 shadow-card transition-all hover:border-primary-soft">
      {record.domain === 'living_circle' ? (
        <div
          className="grid h-14 w-14 shrink-0 place-items-center rounded-card font-serif text-[22px] font-semibold"
          style={
            scorable
              ? { color: grade!.color, background: `${grade!.color}14`, border: `1px solid ${grade!.color}40` }
              : { color: '#7c8680', background: '#eef2ee', border: '1px solid #e2e8e2', fontSize: 11 }
          }
        >
          {scorable ? record.total_score : origin ? origin.label : '—'}
        </div>
      ) : (
        <div className="grid h-14 w-14 shrink-0 place-items-center rounded-card bg-bg text-ink-3">
          <GitCompare size={20} />
        </div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <button
            onClick={() => onOpen(record.id)}
            className="block truncate text-left text-aux font-semibold text-ink hover:text-primary-deep"
            title={record.title}
          >
            {record.title}
          </button>
          <span
            className={`shrink-0 rounded-chip px-1.5 py-0.5 text-tag font-medium ${
              record.domain === 'living_circle'
                ? 'bg-primary-tint text-primary-deep'
                : 'bg-bg text-ink-3 ring-1 ring-line'
            }`}
          >
            {RECORD_DOMAIN_LABEL[record.domain]}
          </span>
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-tag text-ink-3">
          <span className="inline-flex items-center gap-1">
            <MapPin size={12} /> {record.subject}
            {record.city ? ` · ${record.city}` : ''}
          </span>
          <span>{fmtRecordTime(record.checked_at)}</span>

          {origin && (
            <span className={`rounded-chip px-1.5 py-0.5 ${TONE_CLASS[origin.tone]}`} title={origin.detail}>
              {origin.label}
            </span>
          )}
          {degrade && (
            <span
              className="rounded-chip border border-risk/60 bg-risk/10 px-1.5 py-0.5 text-[#8F5E56]"
              title={`${degrade.title} · ${degrade.action}`}
            >
              配额降级 · {degrade.label}
            </span>
          )}
          {grade && (
            <span className="rounded-chip bg-primary-tint px-1.5 py-0.5 text-primary-deep">
              综合 {grade.label}
            </span>
          )}
        </div>
      </div>

      {scorable && (
        <div className="hidden items-center gap-2 sm:flex">
          <span className="inline-flex items-center gap-1 text-tag text-ink-2">
            <TriangleAlert size={13} className={(record.blindspot_count ?? 0) > 0 ? 'text-warn' : 'text-ok'} />
            盲区 {record.blindspot_count} 处
          </span>
        </div>
      )}

      <button
        onClick={() => onOpen(record.id)}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
      >
        <FileText size={14} /> 打开报告
      </button>

      {onDelete && (
        <button
          type="button"
          aria-label={`删除${RECORD_DOMAIN_LABEL[record.domain]}`}
          onClick={() => onDelete(record)}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-btn text-ink-3 transition-colors hover:bg-risk/10 hover:text-risk"
        >
          <Trash2 size={15} />
        </button>
      )}
    </div>
  )
}
