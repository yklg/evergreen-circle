/**
 * 目的地情报中心 · 两屏预览探针（波次 B 前置取证，架构评审 v4 §三）
 *
 * 打开：`http://localhost:3400/preview-intel-center.html`
 *
 * ## 本页回答什么
 *
 * 决定⑤（生活圈 POI 要不要进 `evidences` 表）与「选项 2 生活圈口径 / 选项 3 双域切换」
 * 都需要看见落地后的形状才能拍。文字描述会被驳回（同一口径只在真实渲染上才算说清），
 * 所以这里用**真实后端 + 真实客户端函数**把两屏并排画出来：
 *
 * - **屏 1 · 现状取证**：算法逐字复刻源页 `改造/frontend/src/pages/DashboardPage.tsx:87-139`
 *   （目的地图谱 / 信源三类 / 研判句），数据来自 `lib/api` 的真实函数（不是夹具）。
 * - **屏 2 · 落地形态模拟**：生活圈侧只用**列表端点真实可得**的字段
 *   （`scene_name`/`city`/`total_score`/`blindspot_count`/`data_origin`）现场聚合，
 *   渲染与屏 1 同构的图谱，并给出决定⑤要的并排数字。
 *
 * ## 两条固定局限（不藏）
 *
 * 1. 复刻渲染 ≠ 真页：本探针不 import 源页组件树（那页在别的分支槽位），只保证
 *    **算法与数据同源**；视觉沿用 `components/ui` 的真实 `VCard`/`VCountUp`。
 * 2. 「被几何规则隐藏了多少份生活圈报告」当前**不可证伪**（列表端点不暴露该口径），
 *    屏 2 卡角明写这一条，不用"对照数"假装能算。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与测试面 ——
 * 取证代码烂掉等于防线烂掉（先例 `dev/roadContrastProbe.ts` 的头注）。
 */
import { StrictMode, useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { VCard, VCountUp } from '../components/ui'
import {
  fetchEvidences,
  fetchIntel,
  fetchLifeCircleReports,
  fetchSubscriptions,
  fetchWorkload,
} from '../lib/api'
import type {
  EvidenceQueryResp,
  ExpertWorkload,
  IntelOverview,
  LifeCircleRecord,
  Subscription,
} from '../types'

/* ── 改动区清单：预览高亮与图例的唯一真相源（闸口要求同源） ───────────── */

interface Region {
  id: string
  label: string
  now: string
  target: string
  effect: string
}

const REGIONS: Region[] = [
  {
    id: 'C1',
    label: '情报资产总览（4 张统计卡）',
    now: '今天没有这页；同类数字散在首页与侧栏 workspace 块',
    target: '覆盖目的地 / 情报证据 / 产出结论 / 交叉验证率',
    effect: '四个数一眼看完情报资产厚度，且都点得清来源',
  },
  {
    id: 'C2',
    label: '业务闭环价值（节省人力 / 效率 / 信源覆盖）',
    now: '无任何页面呈现，答辩现场只能口述',
    target: '按 `/api/dashboard` 的 minutes_saved / avg_efficiency / avg_coverage 出卡',
    effect: '把"比人工快多少"变成可指认的数字，公式写在卡角',
  },
  {
    id: 'C3',
    label: '每次调研概览（cards 列表）',
    now: '报告中心只给标题与时间，看不到单份效率',
    target: '每份调研一行：证据数 / 结论数 / 效率倍数 / 节省时长',
    effect: '从"总量"下钻到"哪一次调研贡献了多少"',
  },
  {
    id: 'C4',
    label: '目的地情报图谱（横条排行 + 信源种类 + 平均可信度）',
    now: '屏 1 仍按源页算法从证据行现算；`/api/dashboard` 的 destination_distribution 已随瘦身移除，全库口径改由 `/api/intel` 的 destination_graph 给',
    target: '屏 1 按源页算法从证据行现算；屏 2 并排生活圈口径',
    effect: '决定⑤ 的判据可视化：生活圈进来后图谱会不会更厚',
  },
  {
    id: 'C5',
    label: '信源结构三类占比 + 一句话研判',
    now: '不存在',
    target: '权威一手 / 媒体报道 / 社媒口碑 三段条 + 研判句',
    effect: '暴露一处真实映射缺口：ctrip/mafengwo 不在源页词表里，会被并进「媒体报道」',
  },
  {
    id: 'C6',
    label: '全局证据溯源库（筛选 chip + 证据卡流）＋ 目的地持续追踪',
    now: '不存在；证据只在单份报告的溯源页里看，跨报告没有一处能翻',
    target: '左 2/3 证据流（共 N 条 · 当前 M 条 + 目的地/信源两类 chip），右 1/3 订阅面板',
    effect: '暴露两处真实缺陷：可信度被乘两遍（9800%）、订阅建成即零目的地永不复跑',
  },
  {
    id: 'C7',
    label: '专家贡献（按 missions 排序的前若干位）',
    now: '专家团页有名册，但没有"谁真的干了活"的聚合',
    target: 'missions>0 的专家卡 + 其产出证据/结论数',
    effect: '把 48 位名册收敛成实际出勤的少数几位',
  },
  {
    id: 'C8',
    label: '决定⑤ 并排数字（旅游证据口径 vs 生活圈 scene_name 口径）',
    now: '不存在；两域各说各话，没有一处能并排比',
    target: '三行对照：现状 / facets 口径 / 生活圈入库后',
    effect: '让"POI 进不进 evidences"变成看数拍板，而不是争论概念',
  },
]

/* ── 屏 1 算法：逐字复刻源页（不改口径，改了就不是取证而是创作） ───────── */

const SOURCE_LABEL: Record<string, string> = {
  official: '官网', news: '新闻媒体', douyin: '抖音', xiaohongshu: '小红书',
  bilibili: 'B站', weibo: '微博', zhihu: '知乎', review: '评测', financial_report: '财报', web: '网页',
}
function sourceLabel(t: string) {
  return SOURCE_LABEL[t] ?? t
}

const SOURCE_CATEGORY: Record<string, '权威一手' | '媒体报道' | '社媒口碑'> = {
  official: '权威一手', financial_report: '权威一手',
  news: '媒体报道', web: '媒体报道', review: '媒体报道',
  douyin: '社媒口碑', xiaohongshu: '社媒口碑', bilibili: '社媒口碑',
  weibo: '社媒口碑', zhihu: '社媒口碑',
}

interface DestinationIntel {
  destination: string
  count: number
  sourceTypes: number
  avgCred: number
  unmappedTypes: string[]
}

function buildDestinationIntel(items: EvidenceQueryResp['items']): DestinationIntel[] {
  const map = new Map<string, { count: number; types: Set<string>; cred: number }>()
  for (const it of items) {
    const d = (it.destination || '').trim()
    if (!d) continue // 源页原样：无归属的行整条跳过（屏 1 的局限标注就是为它准备）
    const cur = map.get(d) ?? { count: 0, types: new Set<string>(), cred: 0 }
    cur.count += 1
    cur.types.add(it.source_type)
    cur.cred += it.credibility || 0
    map.set(d, cur)
  }
  return Array.from(map.entries())
    .map(([destination, v]) => ({
      destination,
      count: v.count,
      sourceTypes: v.types.size,
      avgCred: v.count ? v.cred / v.count : 0,
      unmappedTypes: [...v.types].filter((t) => !(t in SOURCE_CATEGORY)),
    }))
    .sort((a, b) => b.count - a.count)
}

function buildSourceStructure(items: EvidenceQueryResp['items']) {
  const cat: Record<string, number> = { 权威一手: 0, 媒体报道: 0, 社媒口碑: 0 }
  const unmapped = new Map<string, number>()
  for (const it of items) {
    const c = SOURCE_CATEGORY[it.source_type]
    if (!c) unmapped.set(it.source_type, (unmapped.get(it.source_type) ?? 0) + 1)
    cat[c ?? '媒体报道'] += 1
  }
  const total = items.length || 1
  const pct = (n: number) => Math.round((n / total) * 100)
  const segs = (['权威一手', '媒体报道', '社媒口碑'] as const).map((k) => ({
    label: k, n: cat[k], pct: pct(cat[k]),
  }))
  const top = [...segs].sort((a, b) => b.n - a.n)[0]
  const firstHand = pct(cat['权威一手'])
  let insight: string
  if (firstHand >= 40) {
    insight = `一手权威信源占 ${firstHand}%，情报根基扎实，结论可信度高。`
  } else if (firstHand >= 20) {
    insight = `当前以「${top.label}」为主（${top.pct}%），一手信源占 ${firstHand}%，建议追加官方文旅站点/平台公告以加固关键结论。`
  } else {
    insight = `情报偏向「${top.label}」（${top.pct}%），一手信源仅 ${firstHand}%，重要结论需补充官方文旅站点与平台公告佐证。`
  }
  return { segs, insight, unmapped: [...unmapped.entries()].sort((a, b) => b[1] - a[1]) }
}

/* ── 屏 2 算法：生活圈侧只用列表端点真实可得的字段现场聚合 ─────────────── */

interface LcIntel {
  destination: string
  reports: number
  avgScore: number | null
  blindspots: number
  origins: string[]
  lastAt: string
}

function buildLcIntel(rows: LifeCircleRecord[]): LcIntel[] {
  const map = new Map<string, { reports: number; scores: number[]; blind: number; origins: Set<string>; last: string }>()
  for (const r of rows) {
    const d = (r.scene_name || '').trim()
    if (!d) continue
    const cur = map.get(d) ?? { reports: 0, scores: [], blind: 0, origins: new Set<string>(), last: '' }
    cur.reports += 1
    if (r.total_score != null && r.total_score > 0) cur.scores.push(r.total_score)
    cur.blind += r.blindspot_count ?? 0
    cur.origins.add(r.data_origin)
    if ((r.checked_at || '') > cur.last) cur.last = r.checked_at || ''
    map.set(d, cur)
  }
  return Array.from(map.entries())
    .map(([destination, v]) => ({
      destination,
      reports: v.reports,
      avgScore: v.scores.length ? Math.round((v.scores.reduce((a, b) => a + b, 0) / v.scores.length) * 10) / 10 : null,
      blindspots: v.blind,
      origins: [...v.origins],
      lastAt: v.last,
    }))
    .sort((a, b) => b.reports - a.reports)
}

/* ── 渲染 ─────────────────────────────────────────────────────────── */

type Phase =
  | { kind: 'loading' }
  | { kind: 'failed'; detail: string }
  | { kind: 'ready'; stats: IntelOverview; ev: EvidenceQueryResp; subs: Subscription[]; workload: ExpertWorkload[]; lc: LifeCircleRecord[]; lcFailed: string | null }

function Region_({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div className="fcp-change" data-fcp={id}>
      <span className="badge">{id}</span>
      {children}
    </div>
  )
}

function Num({ value, unit }: { value: number; unit?: string }) {
  return (
    <div className="num-line">
      <VCountUp value={value} />
      {unit && <span className="num-unit">{unit}</span>}
    </div>
  )
}

function StatCard({ value, unit, label, tip }: { value: number; unit?: string; label: string; tip: string }) {
  return (
    <VCard hover={false}>
      <div className="stat-card" title={tip}>
        <Num value={value} unit={unit} />
        <div className="stat-label">{label}</div>
      </div>
    </VCard>
  )
}

function Bar({ name, count, max, meta, tone }: { name: string; count: number; max: number; meta: string; tone: string }) {
  return (
    <div className="bar-row">
      <span className="bar-name" title={name}>{name}</span>
      <span className={`bar-track bar-${tone}`}>
        <span className="bar-fill" style={{ width: `${Math.max(2, Math.round((count / max) * 100))}%` }} />
      </span>
      <span className="bar-count">{count}</span>
      <span className="bar-meta">{meta}</span>
    </div>
  )
}

function App() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })

  useEffect(() => {
    void (async () => {
      // 取证件的失败必须显形：后端没起来就报"取数失败"，不渲染空壳假装成功
      let stats: IntelOverview
      let ev: EvidenceQueryResp
      let subs: Subscription[]
      let workload: ExpertWorkload[]
      try {
        ;[stats, ev, subs, workload] = await Promise.all([
          fetchIntel(), fetchEvidences(), fetchSubscriptions(), fetchWorkload('travel'),
        ])
      } catch (err) {
        setPhase({ kind: 'failed', detail: err instanceof Error ? err.message : String(err) })
        return
      }
      let lc: LifeCircleRecord[] = []
      let lcFailed: string | null = null
      try {
        lc = await fetchLifeCircleReports()
      } catch (err) {
        lcFailed = err instanceof Error ? err.message : String(err)
      }
      setPhase({ kind: 'ready', stats, ev, subs, workload, lc, lcFailed })
    })()
  }, [])

  if (phase.kind === 'loading') return <div className="box">正在取真实数据（/api/intel · /api/evidences · /api/subscriptions · /api/experts/workload · /api/life-circle）……</div>
  if (phase.kind === 'failed') return <div className="box"><b>取数失败：</b>{phase.detail}</div>

  const { stats, ev, subs, workload, lc, lcFailed } = phase
  const items = Array.isArray(ev.items) ? ev.items : []
  const intel = buildDestinationIntel(items)
  const structure = buildSourceStructure(items)
  const lcIntel = buildLcIntel(lc)
  const maxCount = intel.reduce((m, b) => Math.max(m, b.count), 1)
  const maxLc = lcIntel.reduce((m, b) => Math.max(m, b.reports), 1)
  const noDest = items.filter((i) => !(i.destination || '').trim()).length
  const cards = stats.cards
  const activeExperts = (Array.isArray(workload) ? workload : []).filter((w) => w.missions > 0).slice(0, 6)

  return (
    <>
      {/* ════════ 屏 1 · 现状取证 ════════ */}
      <section className="screen">
        <h2 className="screen-title">屏 1 · 现状取证<span className="screen-sub">真实后端 + 源页算法逐字复刻（生活圈侧尚未进证据表）</span></h2>

        <Region_ id="C1">
          <div className="grid4">
            <StatCard value={intel.length} label="覆盖目的地" tip="有情报沉淀的目的地数（按证据行现算）" />
            <StatCard value={stats?.evidence_total ?? 0} label="情报证据" tip={`库内累计 ${stats?.evidence_total ?? 0} 行；本页只取到 ${items.length} 行（端点 limit 默认 200）`} />
            <StatCard value={stats?.claim_total ?? 0} label="产出结论" tip="全部报告输出的分析结论总数" />
            <StatCard value={stats?.fact_accuracy ?? 0} unit="%" label="交叉验证率" tip="经 ≥2 个独立来源相互印证的结论占比" />
          </div>
          <p className="limit">
            局限 A：证据 <b>{items.length}</b> 行里有 <b>{noDest}</b> 行 <code>destination</code> 为空 ⇒ 源页算法整条跳过，
            图谱实际建立在 <b>{items.length - noDest}</b> 行上（库内共 {stats?.evidence_total ?? 0} 行，去重目的地 {ev.facets.by_destination && Object.keys(ev.facets.by_destination).length} 项由 facets 给出，带 LIMIT 12）。
          </p>
        </Region_>

        <Region_ id="C2">
          <VCard hover={false}>
            <div className="card-title">业务闭环价值<span className="card-hint">公式写在卡角 · 数据源 /api/dashboard</span></div>
            <div className="grid4">
              <StatCard value={Math.round(((stats?.minutes_saved ?? 0) / 60) * 10) / 10} unit="小时" label="累计节省人力" tip="∑(人工估时 − AI 实际耗时)" />
              <StatCard value={stats?.avg_efficiency ?? 0} unit="×" label="平均效率提升" tip="各报告 人工估时 ÷ AI 实际耗时 的平均倍数" />
              <StatCard value={stats?.avg_coverage ?? 0} unit="×" label="平均信源覆盖" tip="每份报告平均独立信源数" />
              <StatCard value={stats?.avg_evidence_per_report ?? 0} unit="条" label="平均每篇证据" tip="evidence_total ÷ reports" />
            </div>
          </VCard>
        </Region_>

        <Region_ id="C3">
          <VCard hover={false}>
            <div className="card-title">每次调研概览<span className="card-hint">共 {cards.length} 份 · 取前 8 行示意</span></div>
            <table className="cmp">
              <thead><tr><th>报告</th><th>证据</th><th>结论</th><th>高可信</th><th>效率倍数</th><th>节省</th></tr></thead>
              <tbody>
                {cards.slice(0, 8).map((c) => (
                  <tr key={c.id}>
                    <td className="cell-name" title={c.title}>{c.title}</td>
                    <td>{c.evidence_count}</td><td>{c.claim_count}</td><td>{c.high_conf_count}</td>
                    <td>{c.efficiency_multiple ? `${c.efficiency_multiple}×` : '—'}</td>
                    <td>{c.minutes_saved ? `${c.minutes_saved} 分钟` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </VCard>
        </Region_>

        <Region_ id="C4">
          <VCard hover={false}>
            <div className="card-title">目的地情报图谱<span className="card-hint">按证据行现算 · 共 {intel.length} 个目的地</span></div>
            {intel.slice(0, 12).map((b) => (
              <Bar key={b.destination} name={b.destination} count={b.count} max={maxCount} tone="travel"
                meta={`${b.sourceTypes} 类信源 · 平均可信度 ${Math.round(b.avgCred)}`} />
            ))}
          </VCard>
        </Region_>

        <Region_ id="C5">
          <VCard hover={false}>
            <div className="card-title">信源结构与研判<span className="card-hint">按本页取到的 {items.length} 行现算（非全库 {stats?.evidence_total ?? 0} 行）· 与源页同一口径</span></div>
            <div className="stack">
              {structure.segs.map((s) => (
                <span key={s.label} className={`seg seg-${s.label}`} style={{ width: `${s.pct}%` }} title={`${s.label} ${s.n} 条`}>
                  {s.label} {s.pct}%
                </span>
              ))}
            </div>
            <div className="seg-legend">
              {structure.segs.map((s) => <span key={s.label}>{s.label} <b>{s.n}</b> 条 · {s.pct}%</span>)}
            </div>
            <p className="insight">{structure.insight}</p>
            {structure.unmapped.length > 0 && (
              <p className="limit">
                映射缺口：{structure.unmapped.slice(0, 4).map(([t, n]) => `${t}(${n})`).join('、')} 不在源页词表里
                ⇒ 按源页口径被并入「媒体报道」。<b>这不是渲染 bug，是搬过来就会带上的真实分类错误。</b>
              </p>
            )}
          </VCard>
        </Region_>

        <Region_ id="C6">
          <div className="cols3">
            <VCard hover={false} className="col2">
              <div className="card-title">全局证据溯源库<span className="card-hint">共 {ev.facets.total} 条 · 当前 {items.length} 条</span></div>
              <div className="chips">
                <span className="chip chip-on">全部</span>
                {Object.entries(ev.facets.by_destination).slice(0, 6).map(([d, n]) => (
                  <span key={`d-${d}`} className="chip">{d} {n}</span>
                ))}
                {Object.entries(ev.facets.by_type).slice(0, 6).map(([t, n]) => (
                  <span key={`t-${t}`} className="chip chip-type">{sourceLabel(t)} {n}</span>
                ))}
              </div>
              <div className="feed">
                {items.slice(0, 5).map((it) => (
                  <div key={it.evidence_id} className="ev">
                    <div className="ev-head">
                      <span className="ev-title" title={it.title || it.domain}>{it.title || it.domain}</span>
                      <span className="ev-ext">↗</span>
                    </div>
                    <p className="ev-excerpt">{it.excerpt}</p>
                    <div className="ev-meta">
                      <span className="chip chip-sm">{sourceLabel(it.source_type)}</span>
                      {it.destination ? <span className="chip chip-sm chip-dest">{it.destination}</span> : <span className="chip chip-sm chip-nodest">无归属</span>}
                      <span className="ev-domain">{it.domain}</span>
                      <span className="ev-cred">可信度 {Math.round(it.credibility * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
              <p className="limit">
                复刻即带病：源页这行写的是 <code>可信度 = Math.round(credibility * 100)</code> 再拼百分号，而库里
                <code>credibility</code> 已经是 0–100 分制（如 98）⇒ 上面每条都显示成「可信度 9800%」。
                你截图里那个 9800% 不是数据脏，是源页把百分比乘了两遍。实施时要一并改成 0–100 直读（如「可信度 98%」），
                否则这块屏上线第一天就在报一个不可能的数。
              </p>
            </VCard>

            <VCard hover={false}>
              <div className="card-title">目的地持续追踪</div>
              <p className="sub-hint">订阅一个目的地主题，一键复跑获取最新动态</p>
              <div className="sub-form">
                <span className="sub-input">如：三亚 亲子游攻略</span>
                <span className="sub-btn">＋</span>
              </div>
              {subs.length === 0
                ? <p className="empty">还没有追踪订阅（订阅表当前 <b>0</b> 条）。</p>
                : <ul className="subs">{subs.map((s) => <li key={s.sub_id}>{s.query} · destinations={JSON.stringify(s.destinations)} · run_count={s.run_count}</li>)}</ul>}
              <p className="limit">
                源页建订阅调的是 <code>createSubscription(q, [])</code> —— 目的地恒为空数组，后端
                <code>SubscriptionBody.destinations</code> 又带默认值 ⇒ 能建成、返 200，但<b>永不复跑</b>。
                这屏把它显形为"看起来有功能、实际零追踪"。
              </p>
            </VCard>
          </div>
        </Region_>

        <Region_ id="C7">
          <VCard hover={false}>
            <div className="card-title">专家贡献<span className="card-hint">名册 {workload.length} 位，其中出勤（missions&gt;0）{activeExperts.length} 位入选</span></div>
            <div className="grid4">
              {activeExperts.map((w) => (
                <div key={w.id} className="expert">
                  <div className="expert-name">{w.name}</div>
                  <div className="expert-meta">{w.missions} 次任务 · 结论 {w.claims_authored} · 证据 {w.evidence_collected}</div>
                </div>
              ))}
            </div>
          </VCard>
        </Region_>
      </section>

      {/* ════════ 屏 2 · 落地形态模拟 ════════ */}
      <section className="screen">
        <h2 className="screen-title">屏 2 · 落地形态模拟<span className="screen-sub">生活圈口径：只用列表端点真实可得的字段现场聚合</span></h2>

        <Region_ id="C4">
          <VCard hover={false}>
            <div className="card-title">目的地情报图谱 · 生活圈口径并入后<span className="card-hint">目的地取 <code>scene_name</code>（列表可见 {lc.length} 份报告 → {lcIntel.length} 个目的地）</span></div>
            {lcIntel.map((b) => (
              <Bar key={b.destination} name={b.destination} count={b.reports} max={maxLc} tone="lc"
                meta={b.avgScore == null ? '不可比（无评分）' : `均分 ${b.avgScore}`} />
            ))}
            <p className="limit">
              局限 B：库内 <code>living_circle_reports</code> 共 27 行，列表只回 {lc.length} 份 ——
              <b>被几何规则隐藏了多少份，本屏无法量化 ⇒ 该口径当前不可证伪。</b>
              这里只用列表真实可得字段（scene_name / total_score / blindspot_count / data_origin）聚合，
              不假装能补出隐藏数。
            </p>
            {lcFailed && <p className="limit">生活圈列表取数失败：{lcFailed}（本屏按"取不到"渲染，不回落空数组）</p>}
          </VCard>
        </Region_>

        <Region_ id="C8">
          <VCard hover={false}>
            <div className="card-title">决定⑤ 要的并排数字</div>
            <table className="cmp">
              <thead><tr><th>口径</th><th>目的地数</th><th>可用行数</th><th>说明</th></tr></thead>
              <tbody>
                <tr>
                  <td>旅游证据（现状）</td><td>{intel.length}</td><td>{items.length - noDest} / {items.length}</td>
                  <td className="cell-note">按证据行 <code>destination</code> 现算；空归属行被源页算法整条跳过</td>
                </tr>
                <tr>
                  <td>旅游证据（facets 口径）</td><td>{Object.keys(ev.facets.by_destination).length}</td><td>{stats?.evidence_total ?? 0}</td>
                  <td className="cell-note">后端 facets 带 <code>LIMIT 12</code> ⇒ 与上一行不等，不可写"图谱数 == facets 之和"</td>
                </tr>
                <tr>
                  <td>生活圈按 scene_name 入库</td><td>+{lcIntel.length}</td><td>{lc.length} 份报告</td>
                  <td className="cell-note">若 POI 进 <code>evidences</code>，行数量级取决于每份报告的 POI 数 —— 列表端点拿不到，本屏不猜</td>
                </tr>
              </tbody>
            </table>
            <p className="insight">
              读法：并排两行"目的地数"差 {Math.abs(intel.length - lcIntel.length)} 个，但两者<b>不是同一件事的两种算法</b> ——
              旅游侧数的是证据归属，生活圈侧数的是样区名。要不要合进同一张图谱，取决于你希望这块屏回答
              "情报厚度"还是"体检覆盖"。
            </p>
          </VCard>
        </Region_>
      </section>

      {/* ════════ 图例（闸口要求：id → 位置 → 预期效果） ════════ */}
      <aside className="fcp-legend">
        <div className="legend-title">改动区图例 · 与预览同源（{REGIONS.length} 区）</div>
        <ol>
          {REGIONS.map((r) => (
            <li key={r.id}>
              <b>{r.id} {r.label}</b>
              <div>位置：{r.now}</div>
              <div>目标态：{r.target}</div>
              <div>预期效果：{r.effect}</div>
            </li>
          ))}
        </ol>
        <div className="legend-foot">
          高亮框与编号来自同一份 <code>REGIONS</code> 清单 ⇒ 预览与后续实施不会静默偏离。
          静态截图不含交互（图谱↔证据列表联动、目的地/信源筛选、订阅增删）；那三条要在实施后用真实页面复核。
        </div>
      </aside>
    </>
  )
}

const host = document.getElementById('intel-root')
if (host) createRoot(host).render(<StrictMode><App /></StrictMode>)
