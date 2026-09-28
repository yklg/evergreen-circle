/**
 * 生活圈 tab 形态 · 两档预览探针（步骤 0 取证，计划 lively-bay-bream v4）
 *
 * 打开：`http://localhost:3400/preview-lc-tab.html`
 *
 * 截图参数（headless 出图不能点击，故状态由 URL 决定）：
 * `?view=a|b|both|cmp`（默认 both；`cmp` = 现状 / A / B 同宽三段对照）· `?expand=1`（A 全展开）· `?preselect=2`（B 预选两份）。
 *
 * 要拍的一件事：生活圈 tab 用 A（同一样区折叠成组）还是 B（一份一行 + 筛选与对比）。
 *
 * 真实渲染的口径：
 * - 数据走 `lib/api.fetchLifeCircleReports()` ⇒ 真实后端 `/api/life-circle`，不是夹具；
 * - 行与统计带直接 import 生产件 `components/RecordRow`、`components/RecordStatsStrip`，
 *   列表口径仍由 `lib/recordIndex` 的 `lcRecordToRow` / `recordStats` 单点产出；
 * - tab 条按 T8 定的 a11y 形状（tablist/tab/aria-selected/tabpanel）画，先验证判据可行。
 *
 * 本页不写库、不发删除请求：`onDelete` 只做视觉呈现。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与测试面 ——
 * 取证代码烂掉等于防线烂掉。
 */
import { StrictMode, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { ChevronDown, ChevronRight, GitCompare, Layers } from 'lucide-react'
import '../index.css'
import RecordRow from '../components/RecordRow'
import RecordStatsStrip from '../components/RecordStatsStrip'
import { fetchLifeCircleReports } from '../lib/api'
import { fmtRecordTime, lcRecordToRow, recordStats, sortKeyOf, type ReportRecord } from '../lib/recordIndex'

/* ── 改动区清单：徽标与图例的唯一真相源（闸口要求同源） ─────────────── */

interface Region {
  id: string
  label: string
  now: string
  target: string
  effect: string
}

const REGIONS: Region[] = [
  {
    id: 'L0',
    label: '外壳 tab 条',
    now: '三个过滤 chip（全部/生活圈/调研），aria-pressed',
    target: '恰 2 个 role="tab" + tabpanel，无「全部」',
    effect: '「全部」退场后两域各有自己的屏，判据 queryAllByRole("tab") 可钉',
  },
  {
    id: 'L1',
    label: '形态 A · 同一样区折叠成组',
    now: '15 条记录平铺，官渡区 6 条、凯里老街 3 条连续占位',
    target: '一组一样区，默认只显最新一份，展开看历史',
    effect: '屏高从 15 行降到组数；"这个样区最近怎么样"不用翻',
  },
  {
    id: 'L2',
    label: '形态 A · 组头字段',
    now: '样区名只在每行副标题里重复出现',
    target: '组头显 样区·城市 / 最新分 / 份数 / 时间跨度 / 与最早一次的分数差',
    effect: '同名多份从噪音变成"这个样区跑了几轮、趋势如何"',
  },
  {
    id: 'L3',
    label: '形态 B · 筛选带',
    now: '只有域过滤，城市与时间不可筛',
    target: '城市 chips + 时间范围 chips，统计带随子集联动',
    effect: '保留一份一行，靠筛选压信息量；统计数字口径跟着子集走',
  },
  {
    id: 'L4',
    label: '形态 B · 对比入口',
    now: '归档页没有任何对比动作',
    target: '行内勾选两份 → 底部出现「去对比」',
    effect: '把已有的 /compare 能力接进归档；注意其参数契约见 L5 下方说明',
  },
  {
    id: 'L5',
    label: '分组键口径警示',
    now: '（A 特有）用哪一列当"同一个样区"没有定过',
    target: '本页把两种键的真实分组数并排画出来',
    effect: '键选错会把"北京劲松"拆成两组、或把不同城市的同名样区并成一组',
  },
]

/* ── 分组键：两种口径同时算，供 L5 直接看数 ───────────────────────── */

const bySceneAndCity = (r: ReportRecord) => `${r.subject}||${r.city ?? ''}`
const bySceneOnly = (r: ReportRecord) => r.subject

interface SampleGroup {
  key: string
  scene: string
  city: string
  rows: ReportRecord[]
  latest: ReportRecord
  span: string
  delta: number | null
}

function buildGroups(rows: ReportRecord[], keyOf: (r: ReportRecord) => string): SampleGroup[] {
  const map = new Map<string, ReportRecord[]>()
  for (const r of rows) {
    const k = keyOf(r)
    const bucket = map.get(k)
    if (bucket) bucket.push(r)
    else map.set(k, [r])
  }
  return [...map.entries()].map(([key, list]) => {
    const sorted = [...list].sort((a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at))
    const latest = sorted[0]
    const oldest = sorted[sorted.length - 1]
    const comparable = (x: ReportRecord) => x.total_score != null && x.total_score > 0
    const delta =
      sorted.length > 1 && comparable(latest) && comparable(oldest)
        ? Math.round(((latest.total_score ?? 0) - (oldest.total_score ?? 0)) * 10) / 10
        : null
    return {
      key,
      scene: latest.subject,
      city: latest.city ?? '（无城市）',
      rows: sorted,
      latest,
      span:
        sorted.length > 1
          ? `${fmtRecordTime(oldest.checked_at)} → ${fmtRecordTime(latest.checked_at)}`
          : fmtRecordTime(latest.checked_at),
      delta,
    }
  }).sort((a, b) => sortKeyOf(b.latest.checked_at) - sortKeyOf(a.latest.checked_at))
}

/* ── 时间筛选：相对最新一条的窗口，避免"今天"随日期漂移把预览看成空 ── */

const TIME_WINDOWS = [
  { id: 'all', label: '全部时间', days: Infinity },
  { id: 'd7', label: '近 7 天', days: 7 },
  { id: 'd3', label: '近 3 天', days: 3 },
] as const

function withinWindow(rows: ReportRecord[], days: number): ReportRecord[] {
  if (!Number.isFinite(days)) return rows
  const newest = rows.reduce((a, r) => Math.max(a, sortKeyOf(r.checked_at)), 0)
  const cut = newest - days * 86400000
  return rows.filter((r) => sortKeyOf(r.checked_at) >= cut)
}

function Change({ region, children }: { region: string; children: ReactNode }) {
  return (
    <div className="fcp-change">
      <span className="badge">{region}</span>
      {children}
    </div>
  )
}

/* ── 外壳：tab 条按 T8 形状画 ───────────────────────────────────── */

function TabBar({ lcCount }: { lcCount: number }) {
  return (
    <Change region="L0">
      <div role="tablist" aria-label="报告中心域" className="flex gap-2 px-3 pt-3">
        <button
          role="tab"
          aria-selected="true"
          className="rounded-btn bg-primary px-4 h-9 text-aux font-medium text-white"
        >
          生活圈体检 <span className="opacity-80">({lcCount})</span>
        </button>
        <button
          role="tab"
          aria-selected="false"
          className="rounded-btn bg-bg px-4 h-9 text-aux text-ink-2 hover:bg-primary-tint"
        >
          目的地调研
        </button>
      </div>
      <p className="px-3 pt-2 text-tag text-ink-3">
        现状是三个 chip（含「全部」）用 aria-pressed；这里换成 role=tab + aria-selected，
        「全部」退场后 <code>queryAllByRole(&quot;tab&quot;)</code> 才恰为 2。
      </p>
    </Change>
  )
}

/* ── 现状：一份一行、无折叠无筛选（今天 /reports?domain=living_circle 的形状） ── */

function VariantNow({ rows }: { rows: ReportRecord[] }) {
  const stats = recordStats(rows)
  return (
    <section className="mt-3">
      <h2 className="font-serif text-h2 text-ink">现状 · 一份一行平铺</h2>
      <p className="mt-1 text-tag text-ink-3">
        今天这页的真实形状：{rows.length} 行连续排，同一样区不聚、城市与时间不可筛、没有对比动作。
      </p>
      {stats && <RecordStatsStrip stats={stats} />}
      <div className="mt-6 flex flex-col gap-3">
        {rows.map((r) => (
          <RecordRow key={r.key} record={r} onOpen={() => {}} onDelete={() => {}} />
        ))}
      </div>
    </section>
  )
}

/* ── 形态 A ─────────────────────────────────────────────────────── */

/* ── 截图参数：headless 出图无法点击，故用 URL 决定渲染哪一档/哪种状态 ── */

const Q = new URLSearchParams(window.location.search)
const VIEW = Q.get('view') ?? 'both'
const EXPAND_ALL = Q.get('expand') === '1'
const PRESELECT = Q.get('preselect') === '2'

function VariantA({ rows, expandAll }: { rows: ReportRecord[]; expandAll: boolean }) {
  const groups = useMemo(() => buildGroups(rows, bySceneAndCity), [rows])
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    expandAll ? Object.fromEntries(groups.map((g) => [g.key, true])) : {},
  )

  return (
    <section className="mt-3">
      <h2 className="font-serif text-h2 text-ink">形态 A · 同一样区折叠成组</h2>
      <p className="mt-1 text-tag text-ink-3">
        {rows.length} 份记录 → {groups.length} 个样区组；组头点开的历史行仍用生产件
        <code>RecordRow</code>，不新造行样式。
      </p>

      <Change region="L1">
        <div className="flex flex-col gap-3 p-2">
          {groups.map((g) => {
            const expanded = !!open[g.key]
            const shown = expanded ? g.rows : g.rows.slice(0, 1)
            return (
              <div key={g.key} className="rounded-card border border-line bg-card shadow-card">
                <button
                  onClick={() => setOpen((s) => ({ ...s, [g.key]: !s[g.key] }))}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left"
                >
                  <Change region="L2">
                    <span className="flex items-center gap-3">
                      <span className="grid h-8 w-8 place-items-center rounded-btn bg-primary-tint text-primary-deep">
                        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </span>
                      <span className="text-aux font-semibold text-ink">
                        {g.scene} <span className="text-ink-3 font-normal">· {g.city}</span>
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">
                        <Layers size={12} /> {g.rows.length} 份
                      </span>
                      {g.delta !== null && (
                        <span
                          className={`rounded-chip px-2 py-0.5 text-tag ${
                            g.delta >= 0 ? 'bg-primary-tint text-primary-deep' : 'bg-risk/10 text-risk'
                          }`}
                        >
                          与最早一次 {g.delta > 0 ? '+' : ''}
                          {g.delta} 分
                        </span>
                      )}
                    </span>
                  </Change>
                  <span className="ml-auto text-tag text-ink-3">{g.span}</span>
                </button>
                <div className="flex flex-col gap-2 px-3 pb-3">
                  {shown.map((r) => (
                    <RecordRow key={r.key} record={r} onOpen={() => {}} onDelete={() => {}} />
                  ))}
                  {!expanded && g.rows.length > 1 && (
                    <button
                      onClick={() => setOpen((s) => ({ ...s, [g.key]: true }))}
                      className="self-start px-2 text-tag text-primary-deep underline"
                    >
                      展开其余 {g.rows.length - 1} 份历史
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </Change>
    </section>
  )
}

/* ── 形态 B ─────────────────────────────────────────────────────── */

function VariantB({ rows, preselect }: { rows: ReportRecord[]; preselect: boolean }) {
  const cities = useMemo(
    () => [...new Set(rows.map((r) => r.city ?? '（无城市）'))].sort(),
    [rows],
  )
  const [city, setCity] = useState<string | null>(null)
  const [win, setWin] = useState<(typeof TIME_WINDOWS)[number]['id']>('all')
  const [picked, setPicked] = useState<string[]>(() => (preselect ? rows.slice(0, 2).map((r) => r.id) : []))

  const subset = useMemo(() => {
    const byCity = city ? rows.filter((r) => (r.city ?? '（无城市）') === city) : rows
    const days = TIME_WINDOWS.find((w) => w.id === win)!.days
    return withinWindow(byCity, days)
  }, [rows, city, win])

  const stats = recordStats(subset)
  const titleOf = (id: string) => rows.find((r) => r.id === id)?.title ?? id

  return (
    <section className="mt-10">
      <h2 className="font-serif text-h2 text-ink">形态 B · 一份一行 + 筛选与对比</h2>
      <p className="mt-1 text-tag text-ink-3">
        行模型与现状一致（不折叠），压信息量靠筛选；统计带用 <code>recordStats</code>
        跟着子集联动，数字口径与生产同源。
      </p>

      <Change region="L3">
        <div className="flex flex-wrap items-center gap-2 p-2">
          {cities.map((c) => (
            <button
              key={c}
              onClick={() => setCity(city === c ? null : c)}
              className={`rounded-chip px-3 py-1 text-tag ${
                city === c ? 'bg-primary text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
              }`}
            >
              {c}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-line" />
          {TIME_WINDOWS.map((w) => (
            <button
              key={w.id}
              onClick={() => setWin(w.id)}
              className={`rounded-chip px-3 py-1 text-tag ${
                win === w.id ? 'bg-primary-deep text-white' : 'bg-bg text-ink-2 hover:bg-primary-tint'
              }`}
            >
              {w.label}
            </button>
          ))}
          <span className="text-tag text-ink-3">当前 {subset.length} 份</span>
        </div>
      </Change>

      {stats ? <RecordStatsStrip stats={stats} /> : <p className="p-4 text-tag text-ink-3">该子集内无可比评分</p>}

      <Change region="L4">
        <div className="mt-6 flex flex-col gap-3 p-2">
          {subset.map((r) => {
            const on = picked.includes(r.id)
            return (
              <div key={r.key} className="flex items-start gap-2">
                <label
                  className={`mt-3 grid h-8 w-8 shrink-0 place-items-center rounded-btn border text-tag ${
                    on ? 'border-primary bg-primary text-white' : 'border-line bg-bg text-ink-3'
                  }`}
                  title={on ? '取消选择' : picked.length < 2 ? '加入对比' : '最多选两份'}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={on}
                    onChange={() =>
                      setPicked((p) =>
                        p.includes(r.id) ? p.filter((x) => x !== r.id) : p.length >= 2 ? p : [...p, r.id],
                      )
                    }
                  />
                  {on ? '已选' : '对比'}
                </label>
                <div className="min-w-0 flex-1">
                  <RecordRow record={r} onOpen={() => {}} onDelete={() => {}} />
                </div>
              </div>
            )
          })}
          <div className="sticky bottom-2 mt-1 flex items-center gap-3 rounded-card border border-line bg-card px-4 py-3 shadow-card">
            <GitCompare size={16} className={picked.length === 2 ? 'text-primary-deep' : 'text-ink-3'} />
            <span className="text-tag text-ink-2">
              {picked.length === 2
                ? `已选两份：${titleOf(picked[0])} ／ ${titleOf(picked[1])}`
                : `已选 ${picked.length} 份 · 需选两份才能对比`}
            </span>
            <button
              disabled={picked.length !== 2}
              onClick={() => {
                window.location.href = `/compare`
              }}
              className={`ml-auto rounded-btn px-4 h-9 text-aux font-medium ${
                picked.length === 2 ? 'bg-primary text-white' : 'bg-bg text-ink-3'
              }`}
            >
              去对比
            </button>
          </div>
        </div>
      </Change>
    </section>
  )
}

/* ── L5：分组键口径，用真实数据把两种键的差别画出来 ────────────────── */

function GroupKeyCaveat({ rows }: { rows: ReportRecord[] }) {
  const strict = buildGroups(rows, bySceneAndCity)
  const loose = buildGroups(rows, bySceneOnly)
  const splitApart = loose.filter((g) => strict.some((s) => s.scene === g.scene && g.rows.length > s.rows.length))
  return (
    <Change region="L5">
      <div className="p-3">
        <h3 className="text-aux font-semibold text-ink">A 的分组键该用哪个？两种键的真实结果都在下面</h3>
        <p className="mt-2 text-tag text-ink-2">
          样区 + 城市 → <b>{strict.length}</b> 组；只用样区名 → <b>{loose.length}</b> 组。
          差出来的这几组是真实数据里的同名不同城，不是我编的边界：
        </p>
        {splitApart.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-tag text-ink-2">
            {splitApart.map((g) => (
              <li key={g.scene}>
                「{g.scene}」只用样区名会并成 {g.rows.length} 份一组，按样区+城市则拆进{' '}
                {[...new Set(g.rows.map((r) => r.city ?? '（无城市）'))].join(' / ')} 两组
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-tag text-ink-3">
          另两点同样来自真实数据：「生活圈体检 · 生活圈体检报告」是任务未填样区名时的默认标题；
          凯里老街有 3 份里两份时间戳完全相同（2026-09-19 12:00）且同分 68.7 ——
          折叠成组会把"重复落库"从噪音变成同组内的相邻行，是否要在组头标注同分同刻，属形态之外的口径问题。
        </p>
        <p className="mt-3 text-tag text-ink-3">
          B 的对比入口有个跨模块前提：<code>pages/ComparePage.tsx:116</code> 自己选两份、不读 URL 参数，
          所以归档页只能跳 <code>/compare</code> 让用户重选；要"带走这两份"需改 ComparePage 的入参契约，属另一批确认。
        </p>
      </div>
    </Change>
  )
}

function Legend({ lcCount }: { lcCount: number }) {
  return (
    <div className="fcp-legend">
      <div className="legend-title">图例 · 橙框=本轮拟改动区（徽标编号与下方说明同源）</div>
      <ol>
        {REGIONS.map((r) => (
          <li key={r.id}>
            <b>
              {r.id} {r.label}
            </b>
            <div>现状：{r.now}</div>
            <div>拟改：{r.target}</div>
            <div>效果：{r.effect}</div>
          </li>
        ))}
      </ol>
      <div className="legend-foot">
        真实数据：/api/life-circle 共 {lcCount} 份生活圈归档（live 模式）；本探针不写库、不删记录。
        两档形态在同一页上下排列，滚动即得对照。
      </div>
    </div>
  )
}

function Probe() {
  const [rows, setRows] = useState<ReportRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchLifeCircleReports()
      .then((list) =>
        setRows([...list.map(lcRecordToRow)].sort((a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at))),
      )
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (error) {
    return (
      <div className="box" style={{ color: '#8F5E56' }}>
        取数失败：{error}（后端未就绪 ⇒ 本预览必须有真实 /api/life-circle，不用空壳假装渲染成功）
      </div>
    )
  }
  if (!rows) return <div className="box">正在取真实归档记录……</div>

  if (VIEW === 'cmp') {
    return (
      <>
        <VariantNow rows={rows} />
        <VariantA rows={rows} expandAll={false} />
        <VariantB rows={rows} preselect={false} />
      </>
    )
  }

  return (
    <>
      <TabBar lcCount={rows.length} />
      {VIEW !== 'b' && <VariantA rows={rows} expandAll={EXPAND_ALL} />}
      {VIEW !== 'a' && <VariantB rows={rows} preselect={PRESELECT} />}
      {VIEW !== 'b' && <GroupKeyCaveat rows={rows} />}
      <Legend lcCount={rows.length} />
    </>
  )
}

createRoot(document.getElementById('lc-tab-root')!).render(
  <StrictMode>
    <Probe />
  </StrictMode>,
)
