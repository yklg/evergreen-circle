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
import { SAMPLE_COMMUNITIES, demoCompareSamples } from '../mocks/livingCircleMock'
import { useDataModeStore } from '../store/dataModeStore'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import {
  COMPARE_ROWS, LC_BLIND_SEV, LC_ISO_COLORS, LC_ISO_COLORS_B, categoryCompareRows, compareCaliberNotices, compareRows,
  emptyBlindspotNote, gapScoreOf, lcCompareCaliberGapNote, planComparisonOverlay, poiConservationNote, severityOf,
} from '../lib/livingCircle'
import type { CategorySideStat } from '../lib/livingCircle'
import { CategoryCaliberNotes } from '../components/lifecircle/CategoryCaliberNotes'
import { VStatLine } from '../components/ui'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { NormalizedOverlay } from '../components/lifecircle/NormalizedOverlay'
import LcMap from '../components/lifecircle/LcMap'
import type { LivingCircleReport, LifeCircleCompare, LifeCircleRecord } from '../types'

/**
 * 差异表的行定义**不在这里** —— 已收进 `lib/livingCircle.ts` 的 `COMPARE_ROWS`（单一真源）。
 *
 * 原来此处是**三份平行行数据**：`statList()`（卡片）+ `ROWS`（差异表）+ `deriveDesc()` 的
 * 行名字符串分派。卡片与差异表**同屏**却各有一套行名；`deriveDesc()` 又把 `statList()` 的
 * **显示串**交给 `>` 比较（JS 字符串走逐字符字典序）⇒ 盲区行 `'0 处' > '1 处'` 为 false，
 * 输出「北京劲松盲区更少」= **事实相反**。现在行名 / 取值 / 方向 / 句式都收在 `COMPARE_ROWS`。
 */

/** 演示态默认的一对对比样区：挑法收在 mock 层那一处出口，页面不自己写规则。 */
const [DEMO_A, DEMO_B] = demoCompareSamples()

/**
 * 选择器的一项。真实态来自历史体检记录、演示态来自内置样区名册 ——
 * 两边都只用到这四格，所以这里按**结构**收：让页面为了复用组件去伪造一份
 * `LifeCircleRecord`（补 `checked_at`、`data_origin` 那些用不到的字段）才是坏味道。
 */
interface SceneOption {
  id: string
  scene_name: string
  city: string
  total_score: number | null
}

/** 对比对象下拉（原生 select，风格随项目，A/B 不可相同）。 */
function SceneSelect({ label, value, taken, options, onChange }: {
  label: string
  value: SceneOption | null
  taken?: SceneOption | null
  options: SceneOption[]
  onChange: (r: SceneOption) => void
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

/**
 * 逐类目差距（笔1 · P1/P2）。
 *
 * 这张表存在的理由：差异表只有两个合计，于是「这一类一个都没有」（`total=0`、后端不给最近耗时）
 * 与「这一类有 N 家但全在可达圈外」（`in_circle=0`、最近耗时有值）在屏上**塌成同一句话** ——
 * 前者是供给缺失、后者是可达缺失，整改动作完全不同。
 *
 * 行内条与读数同排：不再"上面一张表、下面另一张图"读两遍。条只画在两侧都有值时 ——
 * 一侧没值时画半条会让读者把"没有"看成"很近"。
 */
const DB_MAX_MIN = 20

function MinBar({ a, b }: { a: number | null; b: number | null }) {
  const colA = LC_ISO_COLORS[0].stroke
  const colB = LC_ISO_COLORS_B[0].stroke
  const px = (v: number) => 6 + (Math.min(v, DB_MAX_MIN) / DB_MAX_MIN) * 148
  if (a == null || b == null) {
    return <span className="text-tag text-ink-3">{a == null && b == null ? '两侧都没有' : '一侧没有，不画条'}</span>
  }
  return (
    <svg width="160" height="14" viewBox="0 0 160 14" role="img" aria-label={`A ${a} 分钟，B ${b} 分钟`}>
      <line x1={px(a)} y1="7" x2={px(b)} y2="7" stroke={colA} strokeOpacity="0.35" strokeWidth="4" />
      <circle cx={px(a)} cy="7" r="4.5" fill={colA} />
      <circle cx={px(b)} cy="7" r="4.5" fill={colB} />
    </svg>
  )
}

const minText = (s: CategorySideStat | null) =>
  !s ? '没这一类' : s.minMinutes == null ? '一个都没有' : `${s.minMinutes}`

function CategoryGapTable({ a, b }: { a: LivingCircleReport; b: LivingCircleReport }) {
  const rows = categoryCompareRows(a, b)
  const gapNote = lcCompareCaliberGapNote(a, b)
  return (
    <div className="rounded-card border border-line bg-card p-5 shadow-card">
      <div className="mb-1 text-aux font-semibold text-ink">逐类目差距</div>
      <p className="mb-3 text-tag text-ink-3">
        点位数与圈内数是「有多少」，最近耗时是「够不够得着」；「一个都没有」与「有但全在圈外」各占一档写法。
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-line text-tag text-ink-3">
              <th className="py-2 pr-3 font-medium">类目</th>
              <th className="py-2 pr-3 font-medium">点位 A → B</th>
              <th className="py-2 pr-3 font-medium">圈内 A → B</th>
              <th className="py-2 pr-3 font-medium">最近耗时对比</th>
              <th className="py-2 pr-3 font-medium">A</th>
              <th className="py-2 pr-3 font-medium">B</th>
              <th className="py-2 font-medium">差</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.category} className="border-b border-line/60 text-body text-ink">
                <td className="py-2.5 pr-3 font-medium text-ink">{row.label}</td>
                <td className="py-2.5 pr-3 tabular-nums">{row.a ? row.a.total : '—'} → {row.b ? row.b.total : '—'}</td>
                <td className="py-2.5 pr-3 tabular-nums">{row.a ? row.a.inCircle : '—'} → {row.b ? row.b.inCircle : '—'}</td>
                <td className="py-2.5 pr-3"><MinBar a={row.a?.minMinutes ?? null} b={row.b?.minMinutes ?? null} /></td>
                <td className="py-2.5 pr-3 tabular-nums">{minText(row.a)}</td>
                <td className="py-2.5 pr-3 tabular-nums">{minText(row.b)}</td>
                <td className="py-2.5 text-aux text-ink-2 tabular-nums">
                  {row.deltaMin == null ? '一侧没值' : `${row.deltaMin > 0 ? '+' : ''}${row.deltaMin} min`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 border-t border-line pt-3 md:grid-cols-2">
        <div className="min-w-0">
          <div className="text-tag font-medium text-ink-2">门槛项口径 · {a.scene.name}</div>
          <CategoryCaliberNotes lc={a} className="mt-1" />
        </div>
        <div className="min-w-0">
          <div className="text-tag font-medium text-ink-2">门槛项口径 · {b.scene.name}</div>
          <CategoryCaliberNotes lc={b} className="mt-1" />
        </div>
      </div>
      {gapNote && (
        <p className="mt-2 rounded-chip bg-warn/10 px-3 py-2 text-tag font-medium text-warn">{gapNote}</p>
      )}
    </div>
  )
}

/**
 * 盲区成对并排（笔1 · P5）。
 *
 * 一句"0 处"不够：0 处到底是"三要素齐备"还是"还有格子判不了所以没说"，由
 * `emptyBlindspotNote` 按台账覆盖率给那句 —— 与体检台同一颗出口，不在这里另写一套。
 */
function BlindspotPair({ a, b }: { a: LivingCircleReport; b: LivingCircleReport }) {
  return (
    <div className="rounded-card border border-line bg-card p-5 shadow-card">
      <div className="mb-3 text-aux font-semibold text-ink">盲区成对并排</div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {[a, b].map((lc, side) => (
          // 键取槽位不取场景名：两份载荷同名（同城两份、或 A/B 互换后的同一份）时，
          // 用名字当键会撞出 duplicate key —— React 明说这种情况下渲染结果不可保证。
          <div key={`blindside-${side}`} className="min-w-0">
            <div className="text-tag font-medium text-ink-2">{lc.scene.name} · {lc.blindspots.length} 处</div>
            {lc.blindspots.length === 0 ? (
              <p className="mt-1.5 text-tag leading-relaxed text-ink-3">{emptyBlindspotNote(lc)}</p>
            ) : (
              <div className="mt-1.5 flex flex-col gap-2">
                {lc.blindspots.map((bs) => {
                  const spec = LC_BLIND_SEV[severityOf(bs)]
                  const gap = gapScoreOf(bs)
                  return (
                    <div key={bs.id} className="rounded-btn border border-line/70 bg-ink-3/10 p-2.5">
                      <div className="flex flex-wrap items-center gap-1.5 text-aux font-medium text-ink">
                        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: spec?.dot ?? '#8a8a8a' }} />
                        {bs.id.replace('bs-', '盲区 ')}
                        {spec?.label && <span style={{ color: spec.stroke }}>· {spec.label}</span>}
                        {gap != null && <span className="text-tag text-ink-3">· 缺口 {gap}</span>}
                      </div>
                      <div className="mt-1 text-tag text-ink-3">缺失：{bs.missing_facilities.join(' / ')}</div>
                      {bs.nearest.map((n) => (
                        <div key={`${bs.id}-${n.facility}`} className="text-tag text-ink-3">
                          最近「{n.name}」{Math.round(n.distance_m)}m（{n.direction}）
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ComparePage() {
  const navigate = useNavigate()
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')

  /* 真实分支：历史体检记录 + 用户手选的 A/B（默认最近两次） */
  const [records, setRecords] = useState<LifeCircleRecord[]>([])
  const [selA, setSelA] = useState<SceneOption | null>(null)
  const [selB, setSelB] = useState<SceneOption | null>(null)
  /** 演示态的 A/B（笔4）：默认那一对仍由 `demoCompareSamples()` 挑，这里只存被选中的 id。 */
  const [demoSel, setDemoSel] = useState<[string, string]>(() => {
    const [x, y] = demoCompareSamples()
    return [x.id, y.id]
  })
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

  // 演示态这一对 = 名册首项 + 第一个**不同城**的样区。不能写死"取前两份"：名册里现在有
  // 两份同中心的凯里（台账上线前的冻结件 + ev-2 那份），按位置取会把这页配成同城一对，
  // 北京劲松直接从对比页消失（10-03 插样区那天实测红 5 条）。
  const a = SAMPLE_COMMUNITIES.find((c) => c.id === demoSel[0]) ?? DEMO_A
  const b = SAMPLE_COMMUNITIES.find((c) => c.id === demoSel[1]) ?? DEMO_B
  const ra: LivingCircleReport = a.report
  const rb: LivingCircleReport = b.report

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
  /* 真实态的行由后端按**同一份行定义表**产出（一致性靠两侧测试读同一份契约夹具对齐）；
     演示态由 `compareRows()` 就地算 —— 两边**同一判据**，含 P0-3 的口径版本守卫
     （两侧 `caliber.scope_policy_version` 不同时，「服务盲区 / 综合评分」的结论必须换成
     「不可比」：旧口径只判了可达区一角的格，分差会被读成「社区不同」而不是「尺子换了」）。 */
  const caliberNotices = cards.length >= 2 ? compareCaliberNotices(cards[0], cards[1]) : []
  const diffRows: LifeCircleCompare['diff'] = useReal
    ? cmp!.diff
    : compareRows(cards[0], cards[1], names[0], names[1])

  /* R6.9：拆行把「圈内 POI」单列成一个数 —— 若不与拆行**同批**披露，图与数的矛盾就从
     「肉眼可见」变成「看不见」（症状转移）。文案直接调 poiConservationNote()，不新写一套。 */
  const conservationNotes =
    cards.length >= 2
      ? cards.slice(0, 2).flatMap((r, i) => {
          const note = poiConservationNote(r)
          return note ? [`${names[i]}：${note}`] : []
        })
      : []

  // 「选谁」与「怎么呈现」由同一决策驱动：同片→单图真实叠加；跨城→双图+归一示意
  const plan = cards.length >= 2 ? planComparisonOverlay(cards[0].scene.center, cards[1].scene.center) : null

  // 差异表抽为复用块：hasNormalize 时置于右列，否则全宽
  const hasNormalize = !!plan?.normalize && cards.length >= 2
  const diffBlock = (
    <div className="h-full rounded-card border border-line bg-card p-5 shadow-card">
      <div className="mb-3 text-aux font-semibold text-ink">关键差异</div>
      {caliberNotices.map((n) => (
        <p key={n} className="mb-3 rounded-chip bg-warn/10 px-3 py-2 text-tag font-medium text-warn">{n}</p>
      ))}
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
                <td className="py-2.5 pr-3">{row.a_value}</td>
                <td className="py-2.5 pr-3">{row.b_value}</td>
                <td className="py-2.5 text-aux text-ink-2">{row.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {conservationNotes.length > 0 && (
        <p className="mt-3 text-tag text-risk">{conservationNotes.join('　')}</p>
      )}
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

  /* 笔4：演示态的候选与选择。名册只有三份、且不发请求，所以这里只换 id；
     两态共用同一套选择器 JSX，差异收在下面 pairOptions / valueA / onA 这三对上。 */
  // 候选由名册现拼。读分数这件事留在页面（`visitorUnrated` 棘轮在册的消费点，且未评分支已在
  // `SceneSelect` 里）；往 mock 层加一颗 `scores.total` 消费点，等于给那本账添一个没有未评分支的新条目。
  const demoOptions = SAMPLE_COMMUNITIES.map((c) => ({
    id: c.id,
    scene_name: c.report.scene.name,
    city: c.city,
    total_score: c.report.scores.total,
  }))
  const swapDemo = () => setDemoSel(([x, y]) => [y, x])
  const pickDemo = (slot: 0 | 1) => (o: SceneOption) =>
    setDemoSel((cur) => (slot === 0 ? [o.id, cur[1]] : [cur[0], o.id]))

  // 选择即切换：事件上下文里同步置 loading（规避在 effect 里同步 setState 的级联渲染告警）
  const pickA = (r: SceneOption) => {
    setSelA(r)
    setLoading(true)
  }
  const pickB = (r: SceneOption) => {
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
              : `${names[0]} vs ${names[1]} —— 同一口径下的设施覆盖差距`}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-card px-3 h-9 text-tag text-ink-3">
          <GitCompare size={13} /> {useReal ? '真实后端对比' : 'fixture 演示数据'}
        </span>
      </div>

      {/* 对比对象选择（笔4 起两态都有）：真实态从历史体检记录任选，演示态从内置样区名册任选 */}
      {(isFixture ? demoOptions.length : records.length) >= 2 && (
        <div className="rounded-card border border-line bg-card p-4 shadow-card">
          <div className="mb-2 text-aux font-semibold text-ink">对比对象</div>
          <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-[1fr_auto_1fr]">
            <SceneSelect
              label="场景 A"
              value={isFixture ? demoOptions.find((o) => o.id === demoSel[0]) ?? null : selA}
              taken={isFixture ? demoOptions.find((o) => o.id === demoSel[1]) ?? null : selB}
              options={isFixture ? demoOptions : records}
              onChange={isFixture ? pickDemo(0) : pickA}
            />
            <button
              onClick={isFixture ? swapDemo : swap}
              disabled={isFixture
                ? demoSel[0] === demoSel[1]
                : !selA || !selB || selA.id === selB.id}
              aria-label="交换 A / B"
              title="交换 A / B"
              className="grid h-10 w-10 place-items-center rounded-btn border border-line bg-card text-ink-2 transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowLeftRight size={16} />
            </button>
            <SceneSelect
              label="场景 B"
              value={isFixture ? demoOptions.find((o) => o.id === demoSel[1]) ?? null : selB}
              taken={isFixture ? demoOptions.find((o) => o.id === demoSel[0]) ?? null : selA}
              options={isFixture ? demoOptions : records}
              onChange={isFixture ? pickDemo(1) : pickB}
            />
          </div>
          <p className="mt-2 text-tag text-ink-3">
            {isFixture
              ? '从内置样区名册中任选两份对比（A/B 不可相同）；评价、雷达、差异表与各并排节随选择即时更新。'
              : '从历史体检记录中任选两份对比（A/B 不可相同）；评价、雷达与差异表随选择即时更新。'}
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
              {COMPARE_ROWS.map((def) => (
                <VStatLine key={def.key} label={def.key} value={def.cell(r)} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 呈现策略：同片 → 单图真实叠加；跨城 → 双图各居其城 + 归一化圈形示意 */}
      {plan && cards.length >= 2 && (plan.shareMap ? (
        <div className="rounded-card border border-line bg-card shadow-card">
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
        <div className="flex flex-col gap-4 rounded-card border border-line bg-card p-4 shadow-card">
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

      {cards.length >= 2 && (
        <>
          <CategoryGapTable a={cards[0]} b={cards[1]} />
          <BlindspotPair a={cards[0]} b={cards[1]} />
        </>
      )}
    </div>
  )
}