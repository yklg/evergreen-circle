/**
 * 常青圈 · 双样例对比页（F0 实物版）。
 *
 * F 阶段：基于 fixture 的指标对比 + 双雷达；
 * F3/M 阶段：升级为同图叠加双等时圈（同比例尺/同中心/叠加三态）+ 对接真实对比端点。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, GitCompare, Inbox } from 'lucide-react'
import { SAMPLE_COMMUNITIES, USE_MOCK } from '../mocks/livingCircleMock'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import type { LivingCircleReport, LifeCircleCompare } from '../types'

function statList(r: LivingCircleReport) {
  return {
    '等时圈面积(15min)': `${(r.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0).toFixed(2)} km²`,
    采样点数: `${r.sampling.points.length}（可达 ${r.sampling.points.filter((p) => p.reachable).length}）`,
    'POI 采集': `${r.poi.total} 个（圈内 ${r.poi.in_circle}）`,
    服务盲区: `${r.blindspots.length} 处`,
    综合评分: r.scores.total,
  } as Record<string, number | string>
}

const ROWS = ['等时圈面积(15min)', '采样点数', 'POI 采集', '服务盲区', '综合评分'] as const

function deriveDesc(row: string, av: number | string, bv: number | string, titleA: string, titleB: string): string {
  if (row === '综合评分') return av > bv ? `${titleA}更成熟` : `${titleB}设施配置更强`
  if (row === '服务盲区') return av > bv ? `${titleA}盲区更多，需重点补配` : `${titleB}盲区更少`
  if (row === 'POI 采集') return bv > av ? `${titleB}设施密度更高` : `${titleA}主城区覆盖尚可`
  return bv > av ? `${titleB}可达范围更大` : `${titleA}可达范围更大`
}

export default function ComparePage() {
  const navigate = useNavigate()

  /* M3 真实分支：最近两次体检记录对比（后端 diff 表 + 双卡） */
  const [cmp, setCmp] = useState<LifeCircleCompare | null>(null)
  const [loading, setLoading] = useState(!USE_MOCK)

  useEffect(() => {
    if (USE_MOCK) return
    let cancelled = false
    fetchLifeCircleReports()
      .then((rows) => {
        if (cancelled || rows.length < 2) return
        return fetchLifeCircleCompare([rows[0].id, rows[1].id])
      })
      .then((d) => {
        if (!cancelled && d) setCmp(d)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const [a, b] = SAMPLE_COMMUNITIES
  const ra: LivingCircleReport = a.report
  const rb: LivingCircleReport = b.report
  const sa = statList(ra)
  const sb = statList(rb)

  const useReal = !USE_MOCK && cmp != null
  const names = useReal ? [cmp!.reports[0].scene.name, cmp!.reports[1].scene.name] : [a.title, b.title]
  const cards = useReal ? cmp!.reports : [ra, rb]
  const diffRows = useReal
    ? cmp!.diff.map((d) => ({ metric: d.metric, av: d.a_value, bv: d.b_value, desc: d.desc }))
    : ROWS.map((row) => ({
        metric: row,
        av: sa[row],
        bv: sb[row],
        desc: deriveDesc(row, sa[row], sb[row], a.title, b.title),
      }))

  if (!USE_MOCK && loading) {
    return (
      <div className="mx-auto flex min-h-full max-w-[1100px] items-center justify-center px-6 text-aux text-ink-3">
        正在加载对比数据……
      </div>
    )
  }

  if (!USE_MOCK && !cmp) {
    return (
      <div className="mx-auto flex min-h-full max-w-[1100px] flex-col items-center justify-center gap-3 px-6 text-center">
        <Inbox size={32} className="text-ink-3" />
        <div className="text-h3 text-ink">至少需要两次体检记录</div>
        <p className="text-aux text-ink-2">完成两次生活圈体检后，这里会按同一口径对比等时圈、设施覆盖与盲区</p>
        <button
          onClick={() => navigate('/')}
          className="mt-1 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
        >
          去发起体检
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-full max-w-[1100px] flex-col gap-4 px-6 py-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-h3 font-semibold text-ink">双样例对比</h2>
          <p className="mt-1 text-aux text-ink-2">
            {useReal
              ? `${names[0]} vs ${names[1]} —— 同一口径下的设施覆盖差距`
              : '凯里老街（欠发达样本）vs 北京劲松（成熟样本）—— 同一口径下的设施覆盖差距'}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card px-3 h-9 text-tag text-ink-3">
          <GitCompare size={13} /> {useReal ? '真实后端对比' : 'fixture 演示数据'}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {cards.map((r, i) => (
          <div key={i} className="rounded-card border border-line bg-card p-5 shadow-card">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-aux font-semibold text-ink">{names[i] ?? r.scene.name}</div>
                <div className="mt-0.5 text-tag text-ink-3">{r.scene.city || r.scene.address}</div>
              </div>
              <div className="text-right">
                <div className="font-serif text-[34px] font-semibold leading-none text-primary">{r.scores.total}</div>
                <div className="mt-1 text-tag text-ink-3">综合评分</div>
              </div>
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <MiniRadar report={r} />
            </div>
            <div className="mt-2 border-t border-line pt-3">
              {(Object.keys(statList(r)) as string[]).map((k) => (
                <div key={k} className="flex items-center justify-between gap-3 border-b border-line/60 py-1.5 last:border-0">
                  <span className="text-tag text-ink-3">{k}</span>
                  <span className="text-aux font-medium text-ink">{statList(r)[k]}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 指标差异表 */}
      <div className="rounded-card border border-line bg-card p-5 shadow-card">
        <div className="mb-3 text-aux font-semibold text-ink">关键差异</div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-tag text-ink-3">
                <th className="py-2 pr-3 font-medium">指标</th>
                <th className="py-2 pr-3 font-medium">{names[0]}</th>
                <th className="py-2 pr-3 font-medium">{names[1]}</th>
                <th className="py-2 font-medium">解读</th>
              </tr>
            </thead>
            <tbody>
              {diffRows.map((row) => (
                <tr key={row.metric} className="border-b border-line/60 text-body text-ink">
                  <td className="py-2.5 pr-3 font-medium text-ink">{row.metric}</td>
                  <td className="py-2.5 pr-3">{row.av}</td>
                  <td className="py-2.5 pr-3">{row.bv}</td>
                  <td className="py-2.5 text-aux text-ink-2">{row.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          onClick={() => navigate('/life-circle/kaili')}
          className="mt-4 inline-flex items-center gap-1.5 rounded-chip bg-primary px-3.5 py-2 text-aux font-medium text-white hover:bg-primary-deep"
        >
          {useReal ? '查看最新体检地图' : '回地图查看等时圈叠加'} <ArrowUpRight size={14} />
        </button>
      </div>
    </div>
  )
}