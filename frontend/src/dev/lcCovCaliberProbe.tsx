/**
 * 片 1c-β · 「评分口径」上屏四改动区预览（**预览闸，不改生产组件**）
 *
 * 打开：`http://localhost:3400/preview-lc-cov.html`
 * 参数：`?region=c1|c2|c3|c4|all`（默认 all，长图自上而下四区）
 *
 * 四件事（同源计划：`skip/tmp/plan-1c-beta-preview.md`；10-01 用户已确认预览并拍 C1 走甲档）：
 *  C1 类别旁一句口径说明（甲档：后端把门槛项名单随 payload 发下来）
 *  C2 旧报告陈旧提示接第二根轴 `coverage_caliber_version`
 *  C3 对比页「综合评分可比性」那句（横幅 + 差异表两行，取乙档：三句并列）
 *  C4 报告正文那四处仍按点数解释 coverage 的句子
 *
 * 真实渲染的口径（这一屏现在**全部走生产出口**，探针不再自带拟稿）：
 * - **数据**：`src/mocks/fixtures/livingCircle/{kaili,beijing-jinsong}.json`，10-01 `cov-1` 回填后的
 *   真读数（凯里总分 65.4 / 教育 圈内 15 处·门槛项 1 处 / 医疗 25 处·门槛项 5 处）。零手编桩值。
 * - **措辞**：`lcCategoryCaliberNote` + 真组件 `CategoryCaliberNotes`（C1）、`staleCaliberNotices`（C2）、
 *   `compareCaliberNotice` / `compareRows`（C3）、`buildLivingCircleReport()` 的 `sections[].paragraphs|claims`
 *   （C4）—— 屏上每个字都是生产代码现产的，落地后预览与实屏同源。
 * - **构造对照**（当场写明是造的）：C3 那两栏把北京演示件的 `coverage_caliber_version` 删掉。
 *   出厂两份演示件 `cov` 轴相同 ⇒ 评分轴那句在真实演示对上永不出现，不造就看不见 P1-3 那一支。
 *   C1 第三栏删掉 `scored_as`/`unscored_as` 验"缺键整块不印"。
 * - **改前**的原文不在这里重打（手抄会抄出没核过的字）：记录在 `skip/tmp/shot1cb/*.png`（21:06–21:20 拍的，
 *   当时 mocks 与 lib 都还没改）。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与 eslint。
 */
import { createRoot } from 'react-dom/client'
import type { ReactNode } from 'react'
import '../index.css'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { CategoryCaliberNotes } from '../components/lifecircle/CategoryCaliberNotes'
import { buildLivingCircleReport } from '../mocks/livingCircleReports'
import {
  BOTH_GAP_DESC,
  CALIBER_GAP_DESC,
  compareCaliberNotices,
  compareRows,
  staleCaliberNotice,
  staleCaliberNotices,
} from '../lib/livingCircle'
import type { FacilityCategoryStat, LivingCircleReport, ReportSection } from '../types'

/* ───────────────────────── 数据（真夹具，现取） ───────────────────────── */

const KAILI = buildLivingCircleReport('kaili')!.living_circle as LivingCircleReport
const JINSONG = buildLivingCircleReport('beijing-jinsong')!.living_circle as LivingCircleReport
const KAILI_REPORT = buildLivingCircleReport('kaili')!
/** 构造对照：把北京演示件的评分口径版本键删掉 ⇒ 它读起来像 `cov` 键上线前冻结的存量报告。 */
const JINSONG_LEGACY_COV: LivingCircleReport = (() => {
  const clone = structuredClone(JINSONG) as LivingCircleReport & Record<string, unknown>
  const cal = (clone.caliber ?? {}) as Record<string, unknown>
  delete cal.coverage_caliber_version
  return clone
})()

const pct = (v: number) => `${Math.round(v * 100)}%`
const cat = (lc: LivingCircleReport, key: string) => lc.poi.categories.find((c) => c.category === key)
const section = (id: string): ReportSection =>
  KAILI_REPORT.sections.find((s) => s.id === id)!

/* ───────────────────────── C1：甲档已落地，走生产出口 ───────────────────────── */

/** 已否掉的乙档（只报数、不报名字）留作对照，用来看甲档多出来的信息量到底值不值一个契约字段 */
function noteYi(c: FacilityCategoryStat): string | null {
  if (c.required_in_circle == null) return null
  return `${c.label} · 覆盖度按门槛项计分：圈内 ${c.in_circle} 处中 ${c.required_in_circle} 处计入 ⇒ ${pct(c.coverage)}`
}
/** 取证行：圈内点位按 `sub_kind` 的实测分账（payload 现算，用来说明为什么那句不承诺"谁被采到了"） */
function subKindCounts(lc: LivingCircleReport, key: string): string {
  const n: Record<string, number> = {}
  for (const p of lc.poi.points) if (p.category === key) n[p.sub_kind ?? 'other'] = (n[p.sub_kind ?? 'other'] ?? 0) + 1
  const label: Record<string, string> = {
    primary: '小学', kindergarten: '幼儿园', secondary: '中学',
    community_health_center: '中心', health_service_station: '站', pharmacy: '药店',
    clinic: '诊所', hospital: '医院', other: '存疑',
  }
  return Object.entries(n).map(([k, v]) => `${label[k] ?? k} ${v}`).join(' / ')
}
/* C2 / C3 / C4 的"已落地"栏一律走生产出口现产（`staleCaliberNotices` / `caliberGapDesc` /
 * `compareCaliberNotice` / `buildLivingCircleReport()` 的段落与结论句）—— 探针不再自带拟稿，
 * 所以这一屏读到的就是将来上屏的那句话。"改前"栏里 C4 那三段是**改前那次渲染**的原文（本文件
 * 只做展示，不再复算），出处见 `skip/tmp/shot1cb/c4.png`（21:20 拍的，改前）。 */

/* ───────────────────────── 版式（抄生产件 class，不重造样式） ───────────────────────── */

function Frame({ children }: { children: ReactNode }) {
  return <div className="rounded-card border border-line bg-card p-4 shadow-card">{children}</div>
}
function Panel({ title, tone, children }: { title: string; tone: 'now' | 'next' | 'warn'; children: ReactNode }) {
  const toneCls =
    tone === 'now' ? 'bg-bg text-ink-3' : tone === 'next' ? 'bg-ok/10 text-primary-deep' : 'bg-warn/10 text-warn'
  return (
    <div className="mt-3 first:mt-0">
      <div className={`inline-flex items-center rounded-chip px-2 py-0.5 text-tag font-medium ${toneCls}`}>{title}</div>
      <div className="mt-2 rounded-card border border-line bg-card p-4 shadow-card">{children}</div>
    </div>
  )
}
/** 生产件里那行提示用的 class（报告页 `caliberNote` / 体检台 `:883-884` 同一套） */
function Note({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-tag font-medium text-warn">{children}</p>
}
function GrayNote({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-tag text-ink-3">{children}</p>
}
function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-black/5 px-1">{children}</code>
}

function C1() {
  const cats = KAILI.poi.categories
  const tabled = cats.filter((c) => c.required_in_circle != null)
  /** 旧快照臂：删掉名单键 ⇒ 真组件必须整块不出现（不猜、不退回前端硬编码名单） */
  const legacy = (() => {
    const clone = structuredClone(KAILI) as LivingCircleReport
    for (const c of clone.poi.categories) {
      delete (c as unknown as Record<string, unknown>).scored_as
      delete (c as unknown as Record<string, unknown>).unscored_as
    }
    return clone
  })()
  return (
    <Frame>
      <div className="text-aux font-semibold text-ink">凯里老街 · 体检单右栏（雷达图就在下面这块）</div>
      <Panel title="改前：雷达旁没有任何解释" tone="now">
        <MiniRadar report={KAILI} />
        <GrayNote>教育柱 33 · 正文却写「圈内 15 处」⇒ 按 15÷3 复算是 100%，两句话看着互斥</GrayNote>
      </Panel>
      <Panel title="已落地：真组件 CategoryCaliberNotes（措辞走生产出口 lcCategoryCaliberNote）" tone="next">
        <MiniRadar report={KAILI} />
        <CategoryCaliberNotes lc={KAILI} />
        <GrayNote>取证（凯里圈内点位实测分账）：医疗 {subKindCounts(KAILI, 'medical')}；教育 {subKindCounts(KAILI, 'education')} ⇒ 圈内 25 处医疗点里 <Code>pharmacy</Code> 是 0 颗，所以那句走"规则名单"、不写"谁被采到了"</GrayNote>
        <GrayNote>对照被否掉的乙档（只报数）：{noteYi(tabled[0]) ?? '—'} ⇒ 甲档多出来的就是「小学」这三个字</GrayNote>
      </Panel>
      <Panel title="旧快照臂：删掉 scored_as / unscored_as 之后" tone="warn">
        <MiniRadar report={legacy} />
        <CategoryCaliberNotes lc={legacy} />
        <GrayNote>这块<b>一行都不该出现</b>（上面雷达下面直接接这行灰字）—— 缺键不猜、也不许前端自己按名字凑名单</GrayNote>
      </Panel>
    </Frame>
  )
}

function C2() {
  const cases: { name: string; lc: LivingCircleReport; cov: string | null; ev: string | null }[] = [
    { name: '凯里演示件（cov-1 · 无 ev 键）', lc: KAILI, cov: 'cov-1', ev: null },
    { name: '北京演示件（cov-1 · ev-1）', lc: JINSONG, cov: 'cov-1', ev: 'ev-1' },
    { name: '构造：删掉 cov 键的存量报告', lc: JINSONG_LEGACY_COV, cov: null, ev: 'ev-1' },
  ]
  return (
    <Frame>
      <div className="text-aux font-semibold text-ink">陈旧提示（报告页与体检台同一处出口）</div>
      <Panel title="改前：只认判盲那一把尺（单出口 staleCaliberNotice，今天仍在，供逐字对照）" tone="now">
        {cases.map((c) => {
          const n = staleCaliberNotice(c.lc)
          return (
            <div key={c.name} className="mb-2">
              <div className="text-tag text-ink-3">{c.name}</div>
              {n ? <Note>{n}</Note> : <GrayNote>（null ⇒ 屏上什么都不印）</GrayNote>}
            </div>
          )
        })}
      </Panel>
      <Panel title="已落地：两轴各一句、各出现各的（生产出口 staleCaliberNotices）" tone="next">
        {cases.map((c) => {
          const notes = staleCaliberNotices(c.lc)
          return (
            <div key={c.name} className="mb-2">
              <div className="text-tag text-ink-3">{c.name}</div>
              {notes.map((n) => (
                <Note key={n}>{n}</Note>
              ))}
              {!notes.length && <GrayNote>（两轴都是当前口径 ⇒ 不印）</GrayNote>}
            </div>
          )
        })}
      </Panel>
    </Frame>
  )
}

function DiffTable({ a, b, descOf, names }: {
  a: LivingCircleReport
  b: LivingCircleReport
  descOf?: (metric: string, now: string) => string
  names: [string, string]
}) {
  const rows = compareRows(a, b, names[0], names[1]).filter(
    (r) => r.metric === '服务盲区' || r.metric === '综合评分',
  )
  return (
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
        {rows.map((row) => (
          <tr key={row.metric} className="border-b border-line/60 text-body text-ink">
            <td className="py-2 pr-3">{row.metric}</td>
            <td className="py-2 pr-3">{String(row.a_value)}</td>
            <td className="py-2 pr-3">{String(row.b_value)}</td>
            <td className="py-2">{descOf ? descOf(row.metric, row.desc) : row.desc}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function C3() {
  const pairNames: [string, string] = ['凯里老街', '北京劲松']
  /** 两轴同时不同的构造对：凯里（无 ev 键 · cov-1）vs 北京（ev-1 · 删掉 cov 键） */
  const bothGap = JINSONG_LEGACY_COV
  /** 横幅按生产件的渲染方式渲（ComparePage 调的就是 `compareCaliberNotices` 清单） */
  const Banner = ({ a, b }: { a: LivingCircleReport; b: LivingCircleReport }) => (
    <>
      {compareCaliberNotices(a, b).map((n) => (
        <p key={n} className="mb-2 rounded-chip bg-warn/10 px-3 py-2 text-tag font-medium text-warn">{n}</p>
      ))}
    </>
  )
  return (
    <Frame>
      <div className="text-aux font-semibold text-ink">对比页 · 横幅 + 差异表那两行（三句都走生产出口现产）</div>
      <Panel title="出厂演示对（凯里无 ev 键 / 北京 ev-1，cov 轴两边都是 cov-1）⇒ 改前改后同一句" tone="now">
        <Banner a={KAILI} b={JINSONG} />
        <DiffTable a={KAILI} b={JINSONG} names={pairNames} />
        <GrayNote>这一对只有<b>判盲</b>轴不同 ⇒ 结论句仍是 <Code>{CALIBER_GAP_DESC}</Code>（逐字未动）。它同时也是"为什么必须造对照"的证据：出厂两演示件的 <Code>cov</Code> 键相同，评分轴那句在这屏上永远不会出现</GrayNote>
      </Panel>
      <Panel title="构造 · 只删 cov 键（两份 ev 相同）⇒ 第 21 轮 P1-3 那一支，改后" tone="next">
        <Banner a={bothGap} b={JINSONG} />
        <DiffTable a={bothGap} b={JINSONG} names={['北京(存量·点数口径)', '北京(cov-1)']} />
        <GrayNote>改前这屏：横幅 <Code>null</Code>（什么都不印）、两行结论「持平」——判盲轴相同、评分轴一边缺键就被判<b>可比</b>，分差被读成"同一社区自己变了"。这一对是<b>只删键、不改分</b>的构造 ⇒ 两栏数字必然相同，看得出的只有最后一列那句结论</GrayNote>
      </Panel>
      <Panel title="构造 · 两轴同时不同（凯里无 ev 键 · 北京删 cov 键）⇒ 第三句 + 横幅两句并列" tone="next">
        <Banner a={KAILI} b={bothGap} />
        <DiffTable a={KAILI} b={bothGap} names={pairNames} />
        <GrayNote>两把尺都换过 ⇒ 表格里写全（<Code>{BOTH_GAP_DESC}</Code>），横幅也必须两句都在 —— 只报判盲那半就是同屏两处披露各说一半。被否掉的甲档（判盲优先）在这一格里同样只报半句</GrayNote>
      </Panel>
    </Frame>
  )
}

function C4() {
  const med = section('medical')
  const edu = section('education')
  const medClaim = med.claims![0]
  const eduClaim = edu.claims![0]
  return (
    <Frame>
      <div className="text-aux font-semibold text-ink">报告正文 · 医疗 / 教育两节（演示态真段落；真实态 <Code>diagnosis_templates.py</Code> 同四式）</div>
      <Panel title="已落地（生产出口现产：`buildLivingCircleReport('kaili')` 的段落与结论句）" tone="next">
        <div className="text-aux font-medium text-ink">{med.title}</div>
        <p className="mt-1 text-body text-ink-2">{med.paragraphs?.[0]}</p>
        <p className="mt-1 text-body text-ink-2">{med.paragraphs?.[1]}</p>
        <p className="mt-1 text-tag text-ink-3">结论句：{medClaim.text}</p>
        <div className="mt-3 text-aux font-medium text-ink">{edu.title}</div>
        <p className="mt-1 text-body text-ink-2">{edu.paragraphs?.[0]}</p>
        <p className="mt-1 text-tag text-ink-3">结论句：{eduClaim.text}</p>
        <GrayNote>改前那两屏原文不在这里重打（手抄会抄出我没核过的字）—— 记录在同目录 <Code>skip/tmp/shot1cb/c4.png</Code>，10-01 21:20 拍的，那份 mocks 还没改</GrayNote>
        <GrayNote>同一段模板套北京也成立（门槛项 {cat(JINSONG, 'education')!.required_in_circle} / 圈内 {cat(JINSONG, 'education')!.in_circle} ⇒ {pct(cat(JINSONG, 'education')!.coverage)}，覆盖度 ≥75% ⇒ 置信度 high，"达标"与置信度那对矛盾在这份上自然不出现）</GrayNote>
      </Panel>
    </Frame>
  )
}

function Legend() {
  return (
    <div className="fcp-legend">
      <div className="legend-title">改动区图例（同源计划：skip/tmp/plan-1c-beta-preview.md）</div>
      <ol>
        <li><b>C1 类别旁一句口径说明 · 甲档已落地</b>
          <div>落点：后端 <code>category_rule.sub_kind_rule_labels</code>（只读表、不吃点位）⇒ <code>poi.categories[].scored_as/unscored_as</code>；前端 <code>lib/livingCircle.lcCategoryCaliberNote</code> + 真组件 <code>CategoryCaliberNotes</code>，挂在 <code>LifeCircleReportView.tsx</code> 与 <code>LifeCirclePage.tsx</code> 的雷达正下方。效果：读者看得见"15 处里只有 1 处计分"，33 分不再像算错。</div>
        </li>
        <li><b>C2 陈旧提示接第二根轴</b>
          <div>落点：<code>livingCircle.ts</code> 新增 <code>COVERAGE_CALIBER_VERSION</code> / <code>coverageCaliberVersionOf</code> / <code>staleCoverageCaliberNotice</code> / <code>staleCaliberNotices</code>，报告页 <code>caliberNote()</code> 与体检台改成渲清单。效果：缺 <code>coverage_caliber_version</code> 的存量报告多一行"这份是点数口径算的分"；判盲那句逐字不动（10 处判据与契约夹具不碎）。</div>
        </li>
        <li><b>C3 对比页「综合评分可比性」那句 · 乙档已落地</b>
          <div>落点：横幅 <code>compareCaliberNotice</code>（前端独占）+ 差异表两行 <code>compareRows</code> 走 <code>caliberGapDesc</code>；后端 <code>main.py</code> 三个常量逐字同源，由契约夹具钉住。效果：评分轴单独不同时不再判"可比"；两轴都不同时报全。</div>
        </li>
        <li><b>C4 正文那四处按点数解释 coverage 的句子</b>
          <div>落点：前端 <code>mocks/livingCircleReports.ts</code>（医疗段/医疗结论句/教育段/教育结论句）+ 后端 <code>diagnosis_templates.py</code> 的 <code>_med_cov_sentence</code>/<code>_edu_cov_sentence</code>。只改文字：<Code>0.75</Code> 定档与 <Code>triad.covered</Code> 达标判据都不动。⚠️ 分母（满分线）只有后端那份写得出——它读 <code>CATEGORY_RULES</code>；payload 里没有这个数，前端那几句不写「≥3 家」。</div>
        </li>
      </ol>
      <div className="legend-foot">
        真 / 造：屏上每个字都由生产出口现产（探针零拟稿）；只有 C3 那两栏与 C1 第三栏是<b>构造</b>——分别删掉 <code>coverage_caliber_version</code> 与 <code>scored_as</code>，用来看见"评分轴单独不同"那一支和"缺键整块不印"那一臂。
        改前的原文记录在 <code>skip/tmp/shot1cb/</code>（21:06–21:20 那批，mocks 与 lib 都还没改）。
      </div>
    </div>
  )
}

function App() {
  const region = new URLSearchParams(location.search).get('region') ?? 'all'
  const blocks: { key: string; id: string; title: string; node: ReactNode }[] = [
    { key: 'c1', id: 'C1', title: '类别旁一句口径说明（雷达正下方）', node: <C1 /> },
    { key: 'c2', id: 'C2', title: '旧报告陈旧提示接第二根轴', node: <C2 /> },
    { key: 'c3', id: 'C3', title: '对比页「综合评分」可比性那句', node: <C3 /> },
    { key: 'c4', id: 'C4', title: '报告正文医疗/教育四句', node: <C4 /> },
  ]
  const picked = region === 'all' ? blocks : blocks.filter((b) => b.key === region)
  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      {picked.map((b) => (
        <div key={b.key} className="fcp-change">
          <span className="badge">{b.id}</span>
          <div className="mb-2 text-aux font-semibold text-ink">{b.title}</div>
          {b.node}
        </div>
      ))}
      <Legend />
    </div>
  )
}

createRoot(document.getElementById('lc-cov-root')!).render(<App />)
