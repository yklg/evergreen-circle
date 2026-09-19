/**
 * 历史页（F3 · DashboardPage 收敛）：历次体检记录列表。
 *
 * F 阶段（VITE_USE_MOCK=1）由 fixture 记录驱动（标题/样区/时间/评分/盲区数）；
 * M 阶段切真实接口（living_circle_reports 列表）返回同构记录，本页零改动。
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { History, FileText, MapPin, TriangleAlert, Database, TrendingUp, Inbox } from 'lucide-react'
import { getLifeCircleRecords } from '../mocks/livingCircleReports'
import { USE_MOCK } from '../mocks/livingCircleMock'
import { fetchLifeCircleReports } from '../lib/api'
import type { LifeCircleRecord } from '../types'
import { scoreGrade } from '../lib/livingCircle'

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [realRecords, setRealRecords] = useState<LifeCircleRecord[] | null>(null)
  const [loading, setLoading] = useState(!USE_MOCK)

  // F 阶段直接走 fixture；M 阶段从真实接口取数（/api/life-circle 历史体检记录）
  const records = USE_MOCK ? getLifeCircleRecords() : realRecords

  useEffect(() => {
    if (USE_MOCK) return
    let cancelled = false
    fetchLifeCircleReports()
      .then((rows) => {
        if (cancelled) return
        setRealRecords(rows.length ? rows : null)
        setLoading(false)
      })
      .catch(() => setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  // 体检记录侧统计（评分>0 的才算体检口径）
  const stats = useMemo(() => {
    const scored = (records ?? []).filter((r) => r.total_score > 0)
    if (scored.length === 0) return null
    const avg = Math.round(scored.reduce((a, r) => a + r.total_score, 0) / scored.length)
    const latest = [...scored].sort((a, b) => (a.checked_at < b.checked_at ? 1 : -1))[0]
    return {
      total: scored.length,
      avg,
      latestScore: latest?.total_score ?? 0,
      blindspots: scored.reduce((a, r) => a + r.blindspot_count, 0),
    }
  }, [records])

  return (
    <div className="mx-auto max-w-content px-8 py-8">
      <header>
        <h1 className="font-serif text-h1 text-ink">历史体检记录</h1>
        <p className="mt-1 text-aux text-ink-2">
          历次生活圈体检的快照与评分归档 —— 点击即可重看完整体检单与章节报告
        </p>
      </header>

      {loading ? (
        <div className="mt-16 text-center text-aux text-ink-3">正在加载历史记录……</div>
      ) : !records || records.length === 0 ? (
        <div className="mt-16 flex flex-col items-center gap-3 text-center">
          <Inbox size={32} className="text-ink-3" />
          <div className="text-h3 text-ink">还没有体检记录</div>
          <p className="text-aux text-ink-2">完成第一次生活圈体检后，这里会自动归档评分与盲区情况</p>
          <button
            onClick={() => navigate('/life-circle/kaili')}
            className="mt-2 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
          >
            发起体检
          </button>
        </div>
      ) : (
        <>
          {/* 体检口径统计 */}
          {stats && (
            <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
              <StatBlock icon={History} value={stats.total} unit="次" label="体检总数" tip="历次生活圈体检累计次数" />
              <StatBlock icon={TrendingUp} value={stats.latestScore} unit="分" label="最近一次评分" tip="最新一轮体检的综合评分" color="text-primary" />
              <StatBlock icon={MapPin} value={stats.avg} unit="分" label="平均评分" tip="全部体检综合得分的平均值" color="text-ok" />
              <StatBlock icon={TriangleAlert} value={stats.blindspots} unit="处" label="累计盲区" tip="历次识别服务盲区的总量（可能重复计数）" color="text-warn" />
            </div>
          )}

          {/* 记录列表 */}
          <div className="mt-6 flex flex-col gap-3">
            {records.map((r) => {
              const grade = r.total_score > 0 ? scoreGrade(r.total_score) : null
              const scorable = r.total_score > 0
              return (
                <div
                  key={r.id}
                  className="group flex items-center gap-4 rounded-card border border-line/60 bg-card p-4 shadow-card transition-all hover:border-primary-soft"
                >
                  {/* 评分圆 */}
                  <div
                    className="grid h-14 w-14 shrink-0 place-items-center rounded-card font-serif text-[22px] font-semibold"
                    style={
                      scorable
                        ? { color: grade!.color, background: `${grade!.color}14`, border: `1px solid ${grade!.color}40` }
                        : { color: '#7c8680', background: '#eef2ee', border: '1px solid #e2e8e2' }
                    }
                  >
                    {scorable ? r.total_score : '—'}
                  </div>

                  <div className="min-w-0 flex-1">
                    <button
                      onClick={() => navigate(`/report/${r.id}`)}
                      className="block truncate text-left text-aux font-semibold text-ink hover:text-primary-deep"
                      title={r.title}
                    >
                      {r.title}
                    </button>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-tag text-ink-3">
                      <span className="inline-flex items-center gap-1">
                        <MapPin size={12} /> {r.scene_name}
                        {r.city ? ` · ${r.city}` : ''}
                      </span>
                      <span>{fmtTime(r.checked_at)}</span>
                      {r.data_origin === 'fixture_sample' && (
                        <span className="rounded-chip border border-warn/60 bg-warn/10 px-1.5 py-0.5">演示数据</span>
                      )}
                      {scorable && (
                        <span className="rounded-chip bg-primary-tint px-1.5 py-0.5 text-primary-deep">综合 {grade!.label}</span>
                      )}
                    </div>
                  </div>

                  <div className="hidden items-center gap-2 sm:flex">
                    {scorable ? (
                      <span className="inline-flex items-center gap-1 text-tag text-ink-2">
                        <TriangleAlert size={13} className={r.blindspot_count > 0 ? 'text-warn' : 'text-ok'} />
                        盲区 {r.blindspot_count} 处
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-tag text-ink-3">
                        <Database size={13} /> 竞争调研
                      </span>
                    )}
                  </div>

                  <button
                    onClick={() => navigate(`/report/${r.id}`)}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
                  >
                    <FileText size={14} /> 打开报告
                  </button>
                </div>
              )
            })}
          </div>

          {USE_MOCK && (
            <p className="mt-5 text-tag text-ink-3">
              演示数据：含两样区实检与早期轮次快照；M 阶段由真实体检任务自动归档。
            </p>
          )}
        </>
      )}
    </div>
  )
}

function StatBlock({ icon: Icon, value, unit, label, tip, color = 'text-ok' }: {
  icon: typeof FileText
  value: number
  unit: string
  label: string
  tip: string
  color?: string
}) {
  return (
    <div className="rounded-card border border-line/60 bg-card p-4 shadow-card" title={tip}>
      <span className={`grid h-8 w-8 place-items-center rounded-btn bg-primary-tint ${color}`}>
        <Icon size={16} />
      </span>
      <div className="mt-2.5 flex items-end gap-0.5">
        <span className="font-serif text-[26px] leading-none text-ink">{value}</span>
        <span className="mb-0.5 text-aux text-ink-2">{unit}</span>
      </div>
      <div className="mt-1 text-tag font-medium text-ink-2">{label}</div>
    </div>
  )
}