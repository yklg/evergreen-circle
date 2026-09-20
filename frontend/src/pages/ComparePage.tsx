/**
 * 常青圈 · 双样例对比页（F0 实物版 · 真实化升级 + 手动选择 + 跨城呈现决策）。
 *
 * 呈现策略由 planComparisonOverlay(centerA, centerB) 驱动：
 *  - 同片生活圈（≤4km）：A/B 等时圈真实叠加于同图（LcMap compareReport 模式，A 绿/B 蓝）；
 *  - 跨城/跨区：改为「真实双图各居其城」+「归一化圈形对比示意」（NormalizedOverlay）。
 * 真实联调态支持用户从历史体检记录手动任选 A/B 两份做对比；演示态保持内置样例。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftRight, ArrowUpRight, GitCompare, Inbox } from 'lucide-react'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'
import { useDataModeStore } from '../store/dataModeStore'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import { planComparisonOverlay } from '../lib/livingCircle'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { NormalizedOverlay } from '../components/lifecircle/NormalizedOverlay'
import LcMap from '../components/lifecircle/LcMap'
import type { LivingCircleReport, LifeCircleCompare, LifeCircleRecord } from '../types'

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

/** 对比对象下拉（原生 select，风格随项目，A/B 不可相同）。 */
function SceneSelect({ label, value, taken, options, onChange }: {
  label: string
  value: LifeCircleRecord | null
  taken?: LifeCircleRecord | null
  options: LifeCircleRecord[]
  onChange: (r: LifeCircleRecord) => void
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-tag font-medium text-ink-2">{label}</span>
      <select
        aria-label={label}
        value={value?.id ?? ''}
        onChange={(e) => {
          const hit = options.find((o) => o.id === e.target.value)
          if (hit && hit.id !== taken?.id) onChange(hit)
        }}
        className="h-10 w-full rounded-btn border border-line bg-card px-3 text-body text-ink outline-none transition-colors focus:border-primary"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id} disabled={o.id === taken?.id}>
            {o.scene_name} · {o.city}
            {o.total_score != null ? `（${o.total_score}分）` : '（离线估算）'}
          </option>
        ))}
      </select>
    </label>
  )
}

/** A/B 双色图例（单图叠加区与双图区共用）。 */
function OverlayLegend({ names }: { names: [string, string] }) {
  return (
    <div className="flex items-center gap-3 text-tag text-ink-3">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: '#5F7B69', background: 'rgba(124,152,133,0.4)' }} />
        A · {names[0]}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: '#1677ff', background: 'rgba(22,119,255,0.35)' }} />
        B · {names[1]}
      </span>
    </div>
  )
}

export default function ComparePage() {
  const navigate = useNavigate()
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')

  /* 真实分支：历史体检记录 + 用户手选的 A/B（默认最近两次） */
  const [records, setRecords] = useState<LifeCircleRecord[]>([])
  const [selA, setSelA] = useState<LifeCircleRecord | null>(null)
  const [selB, setSelB] = useState<LifeCircleRecord | null>(null)
  const [cmp, setCmp] = useState<LifeCircleCompare | null>(null)
  const [loading, setLoading] = useState(!isFixture)

  useEffect(() => {
    if (isFixture) return
    let cancelled = false
    fetchLifeCircleReports()
      .then((rows) => {
        if (cancelled) return
        setRecords(rows)
        if (rows.length >= 2) {
          // 默认选最近两次，保持既有主路径；选择变化由下列 effect 重新取数
          setSelA((prev) => prev ?? rows[0])
          setSelB((prev) => prev ?? rows[1])
        } else {
          setLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isFixture])

  useEffect(() => {
    if (isFixture) return
    // 选择未就绪或 A/B 相同（UI 已拦截）时不发请求；首次 cmp 即 null，无需同步置空
    if (!selA || !selB || selA.id === selB.id) return
    let cancelled = false
    fetchLifeCircleCompare([selA.id, selB.id])
      .then((d) => {
        if (!cancelled) setCmp(d)
      })
      .catch(() => {
        if (!cancelled) setCmp(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isFixture, selA, selB])

  const [a, b] = SAMPLE_COMMUNITIES
  const ra: LivingCircleReport = a.report
  const rb: LivingCircleReport = b.report
  const sa = statList(ra)
  const sb = statList(rb)

  if (!isFixture && loading) {
    return (
      <div className="mx-auto flex min-h-full max-w-[1100px] items-center justify-center px-6 text-aux text-ink-3">
        正在加载对比数据……
      </div>
    )
  }

  if (!isFixture && records.length < 2) {
    return (
      <div className="mx-auto flex min-h-full max-w-[1100px] flex-col items-center justify-center gap-3 px-6 text-center">
        <Inbox size={32} className="text-ink-3" />
        <div className="text-h3 text-ink">至少需要两次体检记录</div>
        <p className="text-aux text-ink-2">完成两次生活圈体检后，选择其中任两份即可对比等时圈、设施覆盖与盲区</p>
        <button
          onClick={() => navigate('/life-circle/kaili')}
          className="mt-1 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
        >
          去发起体检
        </button>
      </div>
    )
  }

  if (!isFixture && !cmp) {
    return (
      <div className="mx-auto flex min-h-full max-w-[1100px] flex-col items-center justify-center gap-3 px-6 text-center">
        <Inbox size={32} className="text-ink-3" />
        <div className="text-h3 text-ink">对比数据加载失败</div>
        <p className="text-aux text-ink-2">请改选对比对象后重试</p>
        <button
          onClick={() => navigate('/life-circle/kaili')}
          className="mt-1 inline-flex items-center gap-2 rounded-btn bg-primary px-6 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
        >
          去发起体检
        </button>
      </div>
    )
  }

  const useReal = !isFixture && cmp != null
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

  // 「选谁」与「怎么呈现」由同一决策驱动：同片→单图真实叠加；跨城→双图+归一示意
  const plan = cards.length >= 2 ? planComparisonOverlay(cards[0].scene.center, cards[1].scene.center) : null

  // 差异表抽为复用块：hasNormalize 时置于右列，否则全宽
  const hasNormalize = !!plan?.normalize && cards.length >= 2
  const diffBlock = (
    <div className="h-full rounded-card border border-line bg-card p-5 shadow-card">
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
  )

  const swap = () => {
    if (!selA || !selB || selA.id === selB.id) return
    setSelA(selB)
    setSelB(selA)
    setLoading(true)
  }

  // 选择即切换：事件上下文里同步置 loading（规避在 effect 里同步 setState 的级联渲染告警）
  const pickA = (r: LifeCircleRecord) => {
    setSelA(r)
    setLoading(true)
  }
  const pickB = (r: LifeCircleRecord) => {
    setSelB(r)
    setLoading(true)
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

      {/* 对比对象选择（真实联调态）：A/B 从历史体检记录任选，可一键交换 */}
      {!isFixture && records.length >= 2 && (
        <div className="rounded-card border border-line bg-card p-4 shadow-card">
          <div className="mb-2 text-aux font-semibold text-ink">对比对象</div>
          <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-[1fr_auto_1fr]">
            <SceneSelect label="场景 A" value={selA} taken={selB} options={records} onChange={pickA} />
            <button
              onClick={swap}
              disabled={!selA || !selB || selA.id === selB.id}
              aria-label="交换 A / B"
              title="交换 A / B"
              className="grid h-10 w-10 place-items-center rounded-btn border border-line bg-card text-ink-2 transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowLeftRight size={16} />
            </button>
            <SceneSelect label="场景 B" value={selB} taken={selA} options={records} onChange={pickB} />
          </div>
          <p className="mt-2 text-tag text-ink-3">
            从历史体检记录中任选两份对比（A/B 不可相同）；评价、雷达与差异表随选择即时更新。
          </p>
        </div>
      )}

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

      {/* 呈现策略：同片 → 单图真实叠加；跨城 → 双图各居其城 + 归一化圈形示意 */}
      {plan && cards.length >= 2 && (plan.shareMap ? (
        <div className="card">
          <div className="flex flex-wrap items-center justify-between gap-2 p-4 pb-2">
            <div className="text-aux font-semibold text-ink">同图叠加 · 等时圈对比</div>
            <OverlayLegend names={[names[0], names[1]]} />
          </div>
          {/* 必须有确定高度：BMapGL canvas 按父容器像素高度撑开 */}
          <div className="relative h-[440px]">
            <LcMap report={cards[0]} compareReport={cards[1]} draggableCenter={false} onMapMode={() => {}} />
          </div>
        </div>
      ) : (
        <div className="card flex flex-col gap-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-aux font-semibold text-ink">A / B 所在城市等时圈 · 真实地理位置</div>
            <OverlayLegend names={[names[0], names[1]]} />
          </div>
          <p className="text-tag text-ink-3">
            两样区位处不同城市或远离同框尺度，已按各自城市分别展示真实等时圈；跨城设施差距请以卡片与差异表为准。
          </p>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {cards.map((r, i) => (
              <div key={i} className="relative h-[400px]">
                <LcMap report={r} draggableCenter={false} onMapMode={() => {}} />
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* 归一化示意（左） + 关键差异（右）并排；无归一化时差异表全宽 */}
      {hasNormalize ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-w-0">
            <NormalizedOverlay a={cards[0]} b={cards[1]} />
          </div>
          <div className="min-w-0">{diffBlock}</div>
        </div>
      ) : (
        diffBlock
      )}
    </div>
  )
}