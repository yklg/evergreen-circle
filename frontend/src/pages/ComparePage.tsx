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
import { demoCompareSamples } from '../mocks/livingCircleMock'
import { useDataModeStore } from '../store/dataModeStore'
import { fetchLifeCircleReports, fetchLifeCircleCompare } from '../lib/api'
import { COMPARE_ROWS, compareCaliberNotices, compareRows, planComparisonOverlay, poiConservationNote } from '../lib/livingCircle'
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

  // 演示态这一对 = 名册首项 + 第一个**不同城**的样区。不能写死"取前两份"：名册里现在有
  // 两份同中心的凯里（台账上线前的冻结件 + ev-2 那份），按位置取会把这页配成同城一对，
  // 北京劲松直接从对比页消失（10-03 插样区那天实测红 5 条）。
  const a = DEMO_A
  const b = DEMO_B
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
              {COMPARE_ROWS.map((def) => (
                <VStatLine key={def.key} label={def.key} value={def.cell(r)} />
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