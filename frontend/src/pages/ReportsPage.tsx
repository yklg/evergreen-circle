/**
 * 报告中心（F3）：全部报告列表（生活圈体检 / 竞争调研），按类型过滤后打开阅读器。
 *
 * F 阶段（VITE_USE_MOCK=1）列出体检报告（fixture）；
 * M 阶段接入真实 /api/reports + /api/life-circle/list 后自动补齐两类数据。
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, MapPin, TriangleAlert, Inbox, GitCompare } from 'lucide-react'
import { getLifeCircleRecords } from '../mocks/livingCircleReports'
import { USE_MOCK } from '../mocks/livingCircleMock'
import { fetchReports, fetchLifeCircleReports } from '../lib/api'
import type { ReportCard, LifeCircleRecord } from '../types'

type TypeFilter = 'all' | 'living_circle' | 'research'

function fmtDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export default function ReportsPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<TypeFilter>('all')
  const [research, setResearch] = useState<ReportCard[]>([])
  const [realLcRecords, setRealLcRecords] = useState<LifeCircleRecord[]>([])

  useEffect(() => {
    if (USE_MOCK) return
    fetchReports().then((rows) => setResearch(Array.isArray(rows) ? rows : [])).catch(() => {})
    fetchLifeCircleReports().then(setRealLcRecords).catch(() => {})
  }, [])

  const items = useMemo(() => {
    const lcRecords = USE_MOCK ? getLifeCircleRecords() : realLcRecords
    const researchItems = research.map((r) => ({
      key: `research-${r.report_id}`,
      type: 'research' as const,
      title: r.title,
      scene_name: r.query || r.title,
      city: '',
      checked_at: r.created_at,
      score: 0,
      blindspots: 0,
      id: r.report_id,
    }))
    const lcItems = lcRecords.map((r) => ({
      key: `lc-${r.id}`,
      type: 'living_circle' as const,
      title: r.title,
      scene_name: r.scene_name,
      city: r.city,
      checked_at: r.checked_at,
      score: r.total_score,
      blindspots: r.blindspot_count,
      id: r.id,
    }))
    const all = [...lcItems, ...researchItems].sort((a, b) => (a.checked_at < b.checked_at ? 1 : -1))
    return filter === 'all' ? all : all.filter((i) => i.type === filter)
  }, [research, realLcRecords, filter])

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header>
        <h1 className="font-serif text-h1 text-ink">报告中心</h1>
        <p className="mt-1 text-aux text-ink-2">
          全部已生成报告（生活圈体检与竞争调研）—— 按类型过滤，点击打开完整阅读器
        </p>
      </header>

      {/* 类型过滤 + 数据源说明 */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        {(
          [
            { key: 'all', label: '全部' },
            { key: 'living_circle', label: '生活圈体检' },
            { key: 'research', label: '竞争调研' },
          ] as { key: TypeFilter; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setFilter(t.key)}
            className={`rounded-chip px-3 py-1.5 text-aux transition-colors ${
              filter === t.key ? 'bg-primary font-medium text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
            }`}
          >
            {t.label}
          </button>
        ))}
        {USE_MOCK && <span className="ml-auto text-tag text-ink-3">演示数据 · 与历史页同源</span>}
      </div>

      {items.length === 0 ? (
        <div className="mt-16 flex flex-col items-center gap-3 text-center">
          <Inbox size={32} className="text-ink-3" />
          <div className="text-h3 text-ink">暂无该类报告</div>
          <button
            onClick={() => navigate('/life-circle/kaili')}
            className="mt-1 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
          >
            去发起一次体检
          </button>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-3">
          {items.map((it) => (
            <div
              key={it.key}
              className="group flex items-center gap-4 rounded-card border border-line/60 bg-card p-4 shadow-card transition-all hover:border-primary-soft"
            >
              <div
                className={`grid h-12 w-12 shrink-0 place-items-center rounded-card ${
                  it.type === 'living_circle' ? 'bg-primary-tint text-primary-deep' : 'bg-bg text-ink-3'
                }`}
              >
                {it.type === 'living_circle' ? <MapPin size={20} /> : <GitCompare size={20} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => navigate(`/report/${it.id}`)}
                    className="truncate text-left text-aux font-semibold text-ink hover:text-primary-deep"
                    title={it.title}
                  >
                    {it.title}
                  </button>
                  <span
                    className={`shrink-0 rounded-chip px-1.5 py-0.5 text-tag font-medium ${
                      it.type === 'living_circle' ? 'bg-primary-tint text-primary-deep' : 'bg-bg text-ink-3 ring-1 ring-line'
                    }`}
                  >
                    {it.type === 'living_circle' ? '生活圈体检' : '竞争调研'}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-tag text-ink-3">
                  <span>{it.scene_name}{it.city ? ` · ${it.city}` : ''}</span>
                  <span>{fmtDate(it.checked_at)}</span>
                  {it.type === 'living_circle' && it.score > 0 && (
                    <>
                      <span className="font-medium text-ink">评分 {it.score}</span>
                      <span className="inline-flex items-center gap-0.5">
                        <TriangleAlert size={12} className="text-warn" /> 盲区 {it.blindspots} 处
                      </span>
                    </>
                  )}
                </div>
              </div>
              <button
                onClick={() => navigate(`/report/${it.id}`)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
              >
                <FileText size={14} /> 打开
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}