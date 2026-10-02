/**
 * 片 R23-A（乙）+ R23-B1 + R23-B2 + R23-B3 + R23-C + R23-D ·
 * 「没查过 / 没查全 / 它不给 / 没查成 / 整轮没扩词 / 扩到一半没钱」—— 落地后的整页成图
 *
 * 打开：`http://localhost:3400/preview-lc-starved.html`
 * 参数：`?tier=a1|a2|b|c|d|f|g|h|i|j|all`
 * 同源计划：`skip/tmp/plan-r23-starved-preview.md`（R23-A）、`skip/tmp/plan-r23-b-stopline.md`（R23-B1/B2/B3、R23-C、R23-D）
 *
 * ⚠️ 这一版探针不再自带任何拟稿：屏上每一个字 —— 包括橙底那半 —— 都是
 * `buildLivingCircleReport()` 现产的（`mocks/livingCircleReports.ts::evidenceGapNote` ← `secMedical` / `secEducation`）。
 * 探针只做两件事：①换**内存里的输入载荷**（磁盘夹具零改动，用完还原）；
 * ②把新句那一段**描出来**（按 `另需交代：本次有` / `另需交代：本轮没有` / `另需交代：这一类的扩词` 定位，纯显示，不参与措辞）。
 *
 * 看图改掉的四处措辞（都不是代码逻辑，是"屏上的话"）：
 *  ① R23-A 那阵整段会出现<b>两次</b>「另需交代：」（一次归"停止线按点数算"那句、一次归本刀）——
 *     R23-B2 把采集<b>收手单位</b>并到与分子同一个之后，前一句成了假话、已同批撤走
 *     ⇒ 现在每段只剩<b>一个</b>，探针原先那套"定位后挖掉再示意"的机关随之删除（`afterR23b` 已退役）。
 *  ② 新句结尾原本又写了一遍「不能只读成「社区没有」。」，与前一句逐字重复 ⇒ 已删，
 *     由 `lcEvidenceGapNote.test.tsx` 与 `test_evidence_gap_note.py` 各钉一条"同段只许出现一次"。
 *  ③ R23-B1 的第三种成因<b>不以计数开头</b> ⇒ 「本次有 N 个」只能写在子句里、不能写进前缀，
 *     否则第三种会读成「本次有 0 个…」；连带描边锚点必须认两种开头（只认 `本次有` 会让 F 档整段描边消失）。
 *  ④ R23-B3 的第四种成因同样不以计数开头，且开头是「这一类的扩词…」⇒ 锚点<b>必须再加一条</b>：
 *     少了它，H 档（只有第四种命中）整段橙底会<b>消失</b>，而生产正文确实多印了一句 —— 这正是
 *     F 档当年踩过的同一个坑（见上面第 ③ 条）。
 *  ⑤（R23-D 记的正面一条）新拆出来的两位<b>都以「本次有 N 个」开头</b> ⇒ 锚点<b>不用再加</b>。
 *     这不是巧合，是第 ③ 条那条纪律的副产品：计数写在子句里，凡是"指得出词"的成因就共用同一种开头。
 */
import { createRoot } from 'react-dom/client'
import type { ReactNode } from 'react'
import '../index.css'
import { SAMPLE_COMMUNITIES } from '../mocks/livingCircleMock'
import { buildLivingCircleReport } from '../mocks/livingCircleReports'
import type { LivingCircleReport, Report, ReportSection } from '../types'

/* ───────────── 只用于**描边与说明**，不参与任何措辞 ───────────── */

/** 新句的定位锚：三种开头 —— 有计数子句以「本次有」开，第三种以「本轮没有」开，
 *  第四种（R23-B3）以「这一类的扩词」开。⚠️ 少任一条，那一档的橙底会**整段消失**
 *  （探针看起来"没变化"，而生产正文确实多印了一句）—— F 档当年就是这样红过一次。
 *  ⚠️ 原先还有第四种开头「另需交代：采集的停止线…」，它断言"收手按点数、分子按门槛项"——
 *     R23-B2 把两处单位并成同一个之后那句成了假话，已随换单位同批撤掉
 *     （撤没撤干净由 `test_fixture_mirror.py::test_retired_stop_line_note_is_gone_from_both_ends` 全仓扫）。 */
const NOTE_MARKS = ['另需交代：本次有', '另需交代：本轮没有', '另需交代：这一类的扩词']

/** 把生产段落切成「新句之前 / 新句本身 / 之后」；定位不到就整段原样渲染（不猜） */
function splitNote(p: string): { head: string; note: string; tail: string; found: boolean } {
  let start = -1
  let mark = ''
  for (const m of NOTE_MARKS) {
    const i = p.indexOf(m)
    if (i >= 0 && (start < 0 || i < start)) {
      start = i
      mark = m
    }
  }
  if (start < 0) return { head: p, note: '', tail: '', found: false }
  const end = p.indexOf('。', start + mark.length)
  const cut = end < 0 ? p.length : end + 1
  return { head: p.slice(0, start), note: p.slice(start, cut), tail: p.slice(cut), found: true }
}

/** 这一格凭什么印 / 凭什么不印 —— 读载荷现判，只是说明文字 */
function whyLine(lc: LivingCircleReport, category: string, printed: boolean): string {
  const cal = (lc.caliber ?? {}) as Record<string, unknown>
  const raw = (key: string) => {
    const v = cal[key]
    return Array.isArray(v) ? (v.filter((t) => typeof t === 'string') as string[]) : null
  }
  const [st, tr] = [raw('evidence_starved_terms'), raw('evidence_truncated_terms')]
  // R23-D 拆出来的两位（都是 `类:词` 形状，与前两位同一筛法）
  const [cp, fl] = [raw('evidence_capped_terms'), raw('evidence_failed_terms')]
  // ⚠️ 后两个键存的是**裸类别名**（`medical`），前四个存的是 `类:词` ⇒ 筛法不同。
  // 拿前缀去筛它们，说明文字会在医疗格上谎报「没有一条属于本类」，而生产代码确实会印。
  const un = raw('evidence_expansion_unfunded_categories')
  const ob = raw('evidence_expansion_out_of_budget_categories')
  const ofMine = (v: string[] | null) => (v ?? []).filter((t) => t.startsWith(`${category}:`))
  const ofCat = (v: string[] | null) => ((v ?? []).includes(category) ? [category] : [])
  const [s, t, k, f, u, o] = [ofMine(st), ofMine(tr), ofMine(cp), ofMine(fl), ofCat(un), ofCat(ob)]
  const c = lc.poi.categories.find((x) => x.category === category)
  const cov = Math.round(Number(c?.coverage ?? 0) * 100)
  if (printed) {
    const parts = [
      s.length ? `${s.length} 个没发起` : '',
      t.length ? `${t.length} 个没查全` : '',
      k.length ? `${k.length} 个被接口断了页` : '',
      f.length ? `${f.length} 个请求没成` : '',
      u.length ? '整轮没扩词' : '',
      o.length ? '扩到一半没钱' : '',
    ].filter(Boolean)
    return `载荷里本类有 ${parts.join('、')}，且该类覆盖度 ${cov}% <75%（缺口分支）、门槛项键在 ⇒ 印`
  }
  const KEYS: [string, string[] | null][] = [
    ['evidence_starved_terms', st],
    ['evidence_truncated_terms', tr],
    ['evidence_capped_terms', cp],
    ['evidence_failed_terms', fl],
    ['evidence_expansion_unfunded_categories', un],
    ['evidence_expansion_out_of_budget_categories', ob],
  ]
  const absent = KEYS.filter(([, v]) => v === null).map(([key]) => key)
  if (absent.length === 6) return '载荷里六个键都没有（换代前冻结的快照 = "不知道"）⇒ 不印，也不写「0 个」'
  const others =
    [...(st ?? []), ...(tr ?? []), ...(cp ?? []), ...(fl ?? [])]
      .filter((x) => !x.startsWith(`${category}:`)).length +
    (un ?? []).filter((x) => x !== category).length +
    (ob ?? []).filter((x) => x !== category).length
  if (others)
    return `键里有 ${others} 条账（${absent.length ? `另有 ${absent.length} 个键缺席=不知道` : '六键都在'}），但没有一条属于本类 ⇒ 不印：那是别类的账`
  if (c?.required_in_circle == null)
    return '本类有账，但该类没有 required_in_circle（门槛项口径之前的快照）⇒ 正文没有"门槛项不足"那句话，这句也不印'
  const termCount = s.length + t.length + k.length + f.length
  if (cov >= 0.75)
    return `本类确实有 ${termCount} 个词${u.length ? '、且整轮没扩词' : ''}${o.length ? '、且扩到一半没钱' : ''}，但该类覆盖度 ${cov}% ≥75%（达标分支）⇒ 不印：证据面不完整不会让"分子已计满"变假话`
  return '六个键都在、本类六条都是空 ⇒ 不印（这一类查全了，扩词也真跑到达标）'
}

/* ───────────── 输入载荷的拼装（换内存件，不改磁盘夹具） ───────────── */

const STARVED_BOTH = ['medical:社区医院', 'medical:社区卫生服务中心', 'education:小学']
const TRUNC_BOTH = ['medical:诊所', 'shopping:超市']
/** 第三种成因存的是**裸类别名**，不是 `类:词`（一整轮扩词都没发起 ⇒ 连词名都没有可记的） */
const UNFUNDED_MED = ['medical']
/** 第四种成因（R23-B3）同样存裸类别名；这一档照 §11 真跑那一格造：`education` */
const OUT_OF_BUDGET_EDU = ['education']

function buildWith(sceneId: string, mutate: (lc: LivingCircleReport) => void): Report {
  const sample = SAMPLE_COMMUNITIES.find((s) => s.id === sceneId)
  if (!sample) throw new Error(`缺演示件 ${sceneId}`)
  const saved = sample.report
  const clone = structuredClone(saved) as LivingCircleReport
  mutate(clone)
  sample.report = clone
  try {
    const r = buildLivingCircleReport(sceneId)
    if (!r) throw new Error(`buildLivingCircleReport(${sceneId}) 返回 null`)
    return r
  } finally {
    sample.report = saved
  }
}

const setCaliber =
  (patch: Record<string, unknown>) =>
  (lc: LivingCircleReport) => {
    lc.caliber = { ...(lc.caliber ?? {}), ...patch } as LivingCircleReport['caliber']
  }
/** 构造对照：把医疗类压成「门槛项未计满」⇒ 缺口分支才可达（两份演示件的医疗都是 100%） */
const forceMedGap = (lc: LivingCircleReport) => {
  const m = lc.poi.categories.find((c) => c.category === 'medical')
  if (m) {
    m.required_in_circle = 1
    m.coverage = 1 / 3
  }
}

/* ───────────── 渲染件 ───────────── */

function Panel({ title, tone, children }: { title: string; tone: 'now' | 'next'; children: ReactNode }) {
  const toneCls = tone === 'next' ? 'border-amber-400 bg-amber-50/70' : 'border-line bg-card/70'
  return (
    <div className={`rounded-lg border ${toneCls} p-4 mb-3`}>
      <div className="text-[12px] font-semibold text-ink-3 mb-2">{title}</div>
      {children}
    </div>
  )
}

function SectionCell({
  label,
  section,
  category,
  lc,
  badge = '本刀新增（R23-B1）',
}: {
  label: string
  section: ReportSection
  category: string
  lc: LivingCircleReport
  badge?: string
}) {
  const raw = section.paragraphs?.[0] ?? ''
  const { head, note, tail } = splitNote(raw)
  return (
    <Panel title={`${label} · 正文首段（生产出口现产，含新句）`} tone={note ? 'next' : 'now'}>
      <p className="text-body leading-relaxed text-ink-2">
        {head}
        {note ? (
          <span className="fcp-add">
            {note}
            <span className="fcp-add-badge">{badge}</span>
          </span>
        ) : null}
        {tail}
      </p>
      <div className="mt-2 text-[11.5px] leading-relaxed text-ink-3">↑ {whyLine(lc, category, Boolean(note))}</div>
    </Panel>
  )
}

function Fact({ children }: { children: ReactNode }) {
  return <div className="fcp-fact">{children}</div>
}

function Tier({
  id,
  title,
  why,
  report,
  sceneLabel,
  badge,
}: {
  id: string
  title: string
  why: ReactNode
  report: Report
  sceneLabel: string
  badge?: string
}) {
  const lc = report.living_circle as LivingCircleReport
  const med = report.sections.find((s) => s.id === 'medical') as ReportSection
  const edu = report.sections.find((s) => s.id === 'education') as ReportSection
  return (
    <section className="fcp-tier" id={`t-${id}`}>
      <h2 className="fcp-tier-title">
        <span className="fcp-tier-id">{id.toUpperCase()}</span>
        {title}
      </h2>
      <Fact>{why}</Fact>
      <SectionCell label={`${sceneLabel} · 医疗节`} section={med} category="medical" lc={lc} badge={badge} />
      <SectionCell label={`${sceneLabel} · 教育节`} section={edu} category="education" lc={lc} badge={badge} />
    </section>
  )
}

/* ───────────── 七档 ───────────── */

const A1 = buildLivingCircleReport('kaili')!
const A2 = buildLivingCircleReport('beijing-jinsong')!
const B = buildWith('kaili', (lc) => {
  forceMedGap(lc)
  setCaliber({ evidence_starved_terms: STARVED_BOTH, evidence_truncated_terms: TRUNC_BOTH })(lc)
})
const C = buildWith('kaili', (lc) => {
  forceMedGap(lc)
  setCaliber({ evidence_starved_terms: ['education:小学'], evidence_truncated_terms: ['shopping:超市'] })(lc)
})
const D = buildWith('beijing-jinsong', setCaliber({ evidence_starved_terms: ['medical:社区医院', 'medical:社区卫生服务中心'], evidence_truncated_terms: ['medical:诊所'] }))
/** 片 R23-B1：第三种成因**单独**命中 —— 前两个键在场但都是空表，只有「整轮没扩词」 */
const F = buildWith('kaili', (lc) => {
  forceMedGap(lc)
  setCaliber({
    evidence_starved_terms: [],
    evidence_truncated_terms: [],
    evidence_expansion_unfunded_categories: UNFUNDED_MED,
  })(lc)
})
/** 四种成因同时命中：看一句里子句怎么并起来（分号 + 同一个「另需交代：」前缀）。
 *  ⚠️ 医疗与教育**各领一种 B 阶段死法**（unfunded 给医疗、out_of_budget 给教育）——
 *  同一类不可能两个都进（谓词按 `searched` 是否为 0 分家），造一份"同类都占"的载荷就是假场景。 */
const G = buildWith('kaili', (lc) => {
  forceMedGap(lc)
  setCaliber({
    evidence_starved_terms: STARVED_BOTH,
    evidence_truncated_terms: TRUNC_BOTH,
    evidence_expansion_unfunded_categories: UNFUNDED_MED,
    evidence_expansion_out_of_budget_categories: OUT_OF_BUDGET_EDU,
  })(lc)
})
/** 片 R23-B3：第四种成因**单独**命中 —— 照 §11 真跑那一格造（教育扩了 4 轮、门槛项 1/3，
 *  而当时它只被 truncated 那一位交代 ⇒ 「扩到一半没钱」这半句没人说；这一档就是"那一格将来长这样"） */
const H = buildWith('kaili', setCaliber({
  evidence_starved_terms: [],
  evidence_truncated_terms: [],
  evidence_expansion_unfunded_categories: [],
  evidence_expansion_out_of_budget_categories: OUT_OF_BUDGET_EDU,
}))
/** 片 R23-D：⑤**接口断页**单独命中。词名取自 §19 那次真跑里教育类那两位（它们当时的停因是
 *  `page_cap`，这里换成 `server_cap` 的形状只为看"这一档将来长这样"⇒ 载荷是构造的，屏上写明）。
 *  六键全给（其余留空表）⇒ 这一档同时是"缺键 vs 空表"两种读法的分界证人：这里全是"有键且为空"。 */
const I = buildWith('kaili', setCaliber({
  evidence_starved_terms: [],
  evidence_truncated_terms: [],
  evidence_capped_terms: ['education:幼儿园', 'education:博南高级中学'],
  evidence_failed_terms: [],
  evidence_expansion_unfunded_categories: [],
  evidence_expansion_out_of_budget_categories: [],
}))
/** 片 R23-D：⑥**请求没成**单独命中（医疗节，覆盖度被压成缺口分支才可达） */
const J = buildWith('kaili', (lc) => {
  forceMedGap(lc)
  setCaliber({
    evidence_starved_terms: [],
    evidence_truncated_terms: [],
    evidence_capped_terms: [],
    evidence_failed_terms: ['medical:诊所'],
    evidence_expansion_unfunded_categories: [],
    evidence_expansion_out_of_budget_categories: [],
  })(lc)
})

const TIERS: { id: string; node: ReactNode }[] = [
  {
    id: 'a1',
    node: (
      <Tier
        id="a1"
        title="现状 · 键缺席（真数据，零构造）"
        sceneLabel="凯里老街演示件"
        report={A1}
        why={
          <>
            <b>存量不受打扰</b>：凯里演示件的 <code>caliber</code> 里两个键都没有；库里 30 份存量报告有 26 份是这个形状
            （<code>scope.py:878-880</code> 那三行 emit 是 09-27 才落地的）。两节正文与落地前<b>逐字相同</b> ——
            缺席即"不知道"：不硬编「0 个」，也不写「全部查全」。
          </>
        }
      />
    ),
  },
  {
    id: 'a2',
    node: (
      <Tier
        id="a2"
        title="现状 · 有截断词但达标（真数据，零构造）"
        sceneLabel="北京劲松演示件"
        report={A2}
        why={
          <>
            <b>这一档是"有真值却不该印"的那一支</b>：劲松件带 <code>evidence_starved_terms: []</code> 与 7 条
            <code>evidence_truncated_terms</code>（含 <code>medical:诊所</code>），但医疗/教育覆盖度都是 100%
            ⇒ 达标分支<b>不印</b>。库里 09-30 那 4 份 <code>live</code> 报告正是这个形状。
          </>
        }
      />
    ),
  },
  {
    id: 'b',
    node: (
      <Tier
        id="b"
        title="两种成因同时命中（构造）"
        sceneLabel="凯里老街（医疗类被压成缺口）"
        report={B}
        badge="R23-A 已落（上一刀）"
        why={
          <>
            <b>构造说明</b>：往内存载荷塞 3 条未发起 + 2 条没查全，并把医疗覆盖度压到 33% 让缺口分支可达
            （两份演示件的医疗都是 100%，不造就看不见那一支）。词名取自真词表 <code>category_rule.py:48/55</code>，
            形状取自 <code>poi_collector.py:230</code> 的 <code>{'f"{类}:{词}"'}</code>。
            效果：<b>医疗节"2 个未发起、1 个没查全"、教育节"1 个未发起"</b> —— 两节各筛各的，
            两种成因<b>并成一句</b>（共用一个「本次有」）。
            <br />
            ⚠️ 这一档在 R23-A 那阵会出现<b>两次</b>「另需交代：」（一次归"停止线按点数算"那句、一次归本刀）；
            R23-B2 把收手单位并到与分子同一个之后前一句成了假话、已同批撤走 ⇒ 现在只剩一次。
            （"两句各带一个前缀"这件事当年是看图才发现的，不是推出来的。）
          </>
        }
      />
    ),
  },
  {
    id: 'c',
    node: (
      <Tier
        id="c"
        title="反向对照 · 词全属别类（串类会在这一档当场露脸）"
        sceneLabel="凯里老街（医疗类被压成缺口）"
        report={C}
        badge="R23-A 已落（上一刀）"
        why={
          <>
            <b>这一档专治「分类串账」</b>：两个键都是<b>全类混合表</b>。载荷里只有 <code>education:小学</code> 与
            <code>shopping:超市</code> ⇒ 医疗节<b>必须一个字都不出现</b>（教育节照印自己那一条，
            见下方那格的橙底 —— 缺席是"筛掉了"而不是"根本没产"）。
            要是实现不筛前缀，医疗节会冒出「1 个医疗类检索词因预算未发起（education:小学）」。
          </>
        }
      />
    ),
  },
  {
    id: 'd',
    node: (
      <Tier
        id="d"
        title="反向对照 · 达标分支不印（构造）"
        sceneLabel="北京劲松（医疗/教育均 100%）"
        report={D}
        badge="R23-A 已落（上一刀）"
        why={
          <>
            <b>这一档管住「达标了却说没查完」</b>：本类既有未发起也有没查全，但覆盖度 100%。
            证据面不完整只会削弱<b>否定</b>结论，不会让「门槛项已计满」变成假话 ⇒ <b>不印</b>。
          </>
        }
      />
    ),
  },
  {
    id: 'f',
    node: (
      <Tier
        id="f"
        title="片 R23-B1 · 第三种成因单独命中（构造）"
        sceneLabel="凯里老街（医疗类被压成缺口）"
        report={F}
        why={
          <>
            <b>这一档是本刀新增那一种：整轮扩词一次都没发起。</b>前两个键<b>在场且都是空表</b>（= 首轮那 25
            个词全查完了、也没被预算拒绝），只有 <code>evidence_expansion_unfunded_categories: ['medical']</code>
            ⇒ 医疗节印「本轮没有额度为这一类扩词（一次都没扩成）」，而<b>教育节一个字都不印</b>
            —— 这一档同时是筛类别的反向对照：那个键里只有 <code>medical</code>。
            <br />
            它为什么不能并进前两种：<code>starved</code> 是「<b>某个词</b>被预算拒了、别词还在跑」，
            这一种是「<b>这一类</b>从第 0 次起就没轮到」—— 前者要说哪几个词，后者连词名都还没有，
            所以它存的是<b>裸类别名</b>而不是 <code>类:词</code>。也和 <code>capped</code> 不同：那是接口自称还有货
            却断了页（百度那边的天花板），这是我们自己的额度。
          </>
        }
      />
    ),
  },
  {
    id: 'g',
    node: (
      <Tier
        id="g"
        title="四种成因同时命中（构造）· 看子句怎么并起来"
        sceneLabel="凯里老街（医疗类被压成缺口）"
        report={G}
        badge="②③ = R23-A 已落 · ④ = R23-B1 已落 · ⑤ = 本刀"
        why={
          <>
            <b>这一档只管拼装形状</b>：子句共用<b>一个</b>「另需交代：」前缀、由「；」相连、
            末尾共用同一条交代（「…分子里含我们没查过或没查全的部分。」）。
            计数子句在前、不以计数开头的两种在后 —— 这就是为什么「本次有 N 个」写在<b>子句里</b>而不是前缀里。
            <br />
            医疗节这一档印三条（未发起 2 个 + 没查全 1 个 + 整轮没扩词），教育节印两条
            （未发起 1 个 + <b>扩到一半没钱</b>）；<code>shopping:超市</code> 那条没查全不属于这两节 ⇒ 仍被筛掉
            （串类会在这一档露脸）。B 阶段那两种死法按类分给医疗与教育，是因为同一类不可能两者都占。
          </>
        }
      />
    ),
  },
  {
    id: 'h',
    node: (
      <Tier
        id="h"
        title="片 R23-B3 · 第四种成因单独命中（照 §11 真跑那一格造）"
        sceneLabel="凯里老街（教育节，覆盖度 33% 未动过）"
        report={H}
        badge="本刀新增"
        why={
          <>
            <b>这一档是本刀新增那一种：扩过词、却在额度见底时仍没达标。</b>前三个键<b>在场且都是空表</b>
            （= 首轮那 25 个词全查完了、也没被预算拒、也没有整轮没跑），只有
            <code>evidence_expansion_out_of_budget_categories: ['education']</code>
            ⇒ 教育节印「这一类的扩词在到达标线之前因额度见底中断（扩过词，不是查够了）」，
            而<b>医疗节一个字都不印</b>（它覆盖度 100% 走达标分支 ⇒ 这一档同时是达标闸的反向对照）。
            <br />
            <b>为什么非造这一档不可</b>：§11 那次真跑（凯里老街，31 次真实调用）里
            <code>education</code> 拿到全部 4 个扩词单位、门槛项仍 1/3。重测（走 <code>bind_evidence</code>
            的那一版）核出那一位里有 <b>2 个教育类词"发了但没查全"</b>
            （<code>education:幼儿园</code>、<code>education:博南高级中学</code>）⇒ 教育节那句「另需交代」
            当时印的是<b>半个交代</b>：说了"没查全"，没说"扩词的额度也用光了"，而后者当时<b>还没有键能装</b>
            （本刀才加）。真实情况是我们查到一半没额度了 —— 与"社区没有"是两件事。
            <br />
            它为什么不并进第三种：第三种是「<b>排程没摊到</b>」（一次都没发起），这一种是「摊到了但<b>额度太薄</b>」——
            读者要做的判断不同（改排程 vs 加额度），合并就分不出该怪谁。也<b>不</b>并进
            <code>evidence_complete</code>：那把管证据边界（判盲 + 复用门 + 置信度），这把管分子召回。
          </>
        }
      />
    ),
  },
  {
    id: 'i',
    node: (
      <Tier
        id="i"
        title="片 R23-D · 第五种成因单独命中：接口自称还有货却断了页（构造）"
        sceneLabel="凯里老街（教育节，覆盖度 33% 未动过）"
        report={I}
        badge="本刀新增"
        why={
          <>
            <b>这一档是"再多的预算也拿不到那一截"。</b>六键都在、只有
            <code>evidence_capped_terms</code> 有货 ⇒ 教育节印「本次有 2 个教育类检索词接口自称还有货却断了页
            （education:幼儿园、education:博南高级中学）」，而<b>医疗节一个字都不印</b>（达标分支 ⇒ 反向对照）。
            <br />
            <b>为什么它以前不印</b>：那两位词今天混在 <code>evidence_truncated_terms</code> 里
            （那一位的谓词是 <code>not complete</code>，五种停法全落进来）⇒ 报告只会说
            「发了但没查全」，读者以为<b>多翻页深就能拿到</b>，而实际是百度自己断的页。
            <br />
            ⚠️ 载荷是<b>构造</b>：词名取自 §19 真跑那一格，但那两位当时的停因是 <code>page_cap</code>
            （我们没接着翻），不是 <code>server_cap</code>。今天真跑里 <code>capped</code> 是空的 ⇒
            这一档的兑现点仍是下一次真体检。
          </>
        }
      />
    ),
  },
  {
    id: 'j',
    node: (
      <Tier
        id="j"
        title="片 R23-D · 第六种成因单独命中：请求没成（构造）"
        sceneLabel="凯里老街（医疗类被压成缺口）"
        report={J}
        badge="本刀新增"
        why={
          <>
            <b>这一档是"这一词我们一无所知"。</b>只有 <code>evidence_failed_terms</code> 有货 ⇒
            医疗节印「本次有 1 个医疗类检索词请求没成（medical:诊所）」；教育节不印（本类没账）。
            <br />
            <b>这一位是从旧那句里救出来的假话</b>：那一行由 <code>_api_error_row</code> 造，
            它自己的 docstring 写着"一次<b>没发出去</b>/发出去没成的检索" —— 而旧谓词把它算进
            <code>truncated</code>，于是屏上那句是「<b>发了</b>但没查全」。对没发出去的那一半，
            "发了"两个字不成立 ⇒ 本刀把它单列。
            <br />
            ⚠️ §19 那次真跑里 <code>api_error</code> 也是 <b>0 实例</b>（31 次全成）⇒ 这一档同样是构造。
          </>
        }
      />
    ),
  },
]

function Legend() {
  return (
    <div className="fcp-legend">
      <div className="legend-title">图例 · 落地实际改了哪几处</div>
      <ol>
        <li>
          <b>后端生产正文</b>
          <div>
            <code>diagnosis_templates.py</code>：新增 <code>_evidence_gap_note(caliber, category, label)</code> 一处实现 +
            九个 <code>_GAP_*</code> 常量；<code>_med_cov_sentence</code> / <code>_edu_cov_sentence</code> 各多收一个
            <code>caliber</code> 参数，只在<b>缺口分支</b>挂这句（教育节本节没有分支，闸门显式写在函数里）。
          </div>
        </li>
        <li>
          <b>本刀（R23-B1）新增第三种成因的账</b>
          <div>
            <code>poi_collector.py</code>：<code>CollectionEvidence.expansion_unfunded</code> + B 阶段按
            <code>searched / no_vocab</code> 现判「这一类一次扩词都没发出去」；
            <code>scope.py</code> 发射 <code>caliber.evidence_expansion_unfunded_categories</code>；
            <code>types.ts</code> 声明该键（缺键 = 读作<b>不知道</b>，不得当成"没有被落下"）。
            ⚠️ 它<b>不</b>并进 <code>evidence_complete</code>：那把管证据边界（盲区判定 + 缓存复用门 + 置信度），
            这把管分子召回 —— 合并会把「我们没额度」写成「证据域完整」。
          </div>
        </li>
        <li>
          <b>前端演示态镜像</b>
          <div>
            <code>mocks/livingCircleReports.ts</code>：<code>evidenceGapNote</code> + 九个同名常量，
            <code>medCoverageSentence</code> / <code>eduCoverageSentence</code> 多收 <code>caliber</code>。
            措辞与后端<b>逐字同源</b>，由 <code>test_fixture_mirror.py::test_evidence_gap_note_is_one_text_on_both_ends</code>
            钉住（R23-D 起<b>名单不再手写</b>：两端各自枚举 <code>GAP_*</code> 再比<b>名字集合相等</b>
            + 两条"正文真的引用了它 3 次"计数 ⇒ 任何一端单独多一个常量都会红）。
          </div>
        </li>
        <li>
          <b>本刀（R23-B2）把收手单位并到与分子同一个</b>
          <div>
            <code>poi_collector.py</code>：B 阶段<b>两处</b>闸（进圈前的外层闸 + 每轮扩词后的达标闸）都改走
            <code>_at_target(cat, items, scope, ideal)</code> —— 有门槛项口径按<b>门槛项数</b>收手，
            <code>None</code>（没建子类表的六类）沿用<b>点数</b>；分子只读 <code>poi.required_count_from_raw_points</code>
            （与覆盖度同一份盖章 <code>stamp_sub_kind</code> + 同一个计数），采集侧不自写第二份判类。
            同批撤掉「停止线按点数算…」那句交代与它的前端镜像常量 —— 单位一并，那句话就成了假话。
            ⚠️ 边际止损（<code>quench</code> / <code>GAIN_STOP_THRESHOLD</code>）仍按点数增益判：计划 §5 丙未拍。
          </div>
        </li>
        <li>
          <b>本刀（R23-B3）给第四种成因补的账</b>
          <div>
            <code>poi_collector.py</code>：<code>CollectionEvidence.expansion_out_of_budget</code> + B 阶段新增两个局部旗标
            （<code>reached</code> 达标 / <code>failed</code> 调用失败），谓词写成
            <code>searched 且 remaining≤0 且 非(reached｜failed｜frozen)</code> —— 五种 while 出口各归各的披露位；
            <code>scope.py</code> 发射 <code>caliber.evidence_expansion_out_of_budget_categories</code>（分职注释从"四种"改"五种"）；
            <code>types.ts</code> 声明该键（缺键 = 读作<b>不知道</b>，不得当成"没有类别扩到一半停了"）。
            ⚠️ 读侧的类别表两支（第三种 / 第四种）在两端都收成<b>同一个循环</b>，不留两份判定。
            刻意<b>不写</b> <code>not no_vocab</code>：额度归零时 while 守卫根本不进循环 ⇒ <code>ctx.next</code>
            永不被调用，"没词"与本位在结构上互斥，写了是恒真的多余条件。
          </div>
        </li>
        <li>
          <b>本刀（R23-D · #71）把「发了但没查全」那一位按归责拆成三位</b>
          <div>
            <code>poi_collector.py</code>：<code>truncated_terms</code> 的谓词从 <code>not complete</code> 收窄成
            <b>排除式</b>（去掉 <code>cap_hit</code> 与 <code>api_error</code>）+ 新增 <code>failed_terms</code>；
            <code>capped_terms</code> 早就在算，只是<b>算了没发射</b>（<code>as_detail()</code> 有、
            <code>scope.payload()</code> 只取类级那份）⇒ 这就是「capped 没有屏上出口」的确切成因。
            <code>scope.py</code> 发射 <code>evidence_capped_terms</code> / <code>evidence_failed_terms</code>；
            <code>types.ts</code> 声明两键（缺键 = 读作<b>不知道</b>，且它同时是换代标记）。
            <br />
            ⚠️ 谓词写成"排除已归责的两档"而不是"枚举 <code>page_cap</code>/<code>dup_stop</code>"：
            未知或将来新增的停止原因<b>默认留在 truncated</b> ⇒ 最坏表现是多交代一句，绝不会让一个词
            从披露里静默消失。三位的并集与旧谓词<b>逐词相等</b>那条是主防线。
            ⚠️ <code>not_run</code> <b>不配拥有键</b>：四条通道页深全 ≥1（AST 扫 <code>max_pages=</code> 实参钉住），
            它进不了 <code>per_term</code> ⇒ 为结构上恒空的位造披露位 = 造一条没人能跑的假防线。
            ⚠️ 刻意<b>不升</b> <code>coverage_caliber_version</code>：那把键驱动的句子是
            「评分口径已升级…不可与新报告直接比 —— 建议重新体检」，而本刀一个分都没改 ⇒ 升它会让那句说假话
            并把用户推向花配额。换代信号由"两个新键在不在"承担（计划 §20⑥ 丁档）。
          </div>
        </li>
        <li>
          <b>判据</b>
          <div>
            后端 <code>test_evidence_gap_note.py</code>（拼装 + 分支真话 + 撤句后"同段只许一个另需交代"）、
            <code>test_expansion_unfunded.py</code>（8 条：正向「没钱 ⇒ 记账」+ 三档反向对照 + 不外溢到
            <code>complete/starved/aborted</code> + 从 <code>as_detail()</code> 传到 <code>scope.payload()</code>）、
            <b>新</b> <code>test_expansion_stop_unit.py</code>（7 条：门槛项 0/3 时与点数判法<b>给出不同答案</b> +
            两类逐格单调 + 六类与点数判法<b>逐格同值</b> + 端到端"三颗诊所必须多扩一轮"及反向对照 +
            闸与覆盖度<b>逐格等值</b>）、
            <code>test_fixture_mirror.py::test_retired_stop_line_note_is_gone_from_both_ends</code>
            （全仓扫那句撤走的交代，配"仍在用的那句必须扫得到"作活证人）、
            <b>新</b> <code>test_expansion_out_of_budget.py</code>（10 条：0..4 头寸扫"只收跑过扩词的类 + 与第三位互斥" +
            钱够反向对照 + 零头寸只进第三位 + 达标/冻结/调用失败三种收手各做<b>换桩差分</b> +
            "首轮就失败"的类不许被说成扩到一半 + ⑤ 同时进分子并集 +
            <code>as_detail()</code>→<code>scope.payload()</code> 同源 + 第四子句只为本类印）。
            <b>新</b> <code>test_truncated_attribution.py</code>（8 条：<b>守恒主防线</b>"三位并起来恰好等于旧谓词
            且两两互斥" + 每种停法各归各位 + <b>未知停止原因默认落 truncated</b>（反向对照：查全的两种永远不进任何一位）+
            两位新子句各说各的话、不许互相冒充 + 一类四种子句并列仍只一个前缀 + 两个新键从唯一发射点到 <code>payload()</code> +
            页深地板（含 <b>AST 扫</b> <code>max_pages=</code> 实参，第一版用正则把注释里的 <code>max_pages=3</code>
            当成调用点、伪装成一条在跑的判据））。
            <code>test_numerator_incomplete_union.py</code> 的 <code>_caliber()</code> 从<b>手抄键名映射</b>改成走
            <code>bind_evidence → payload()</code> —— 手抄那份在本刀加两个键时静默少发两位、把"正文印不印 ⇔ 并集有没有"
            测成反向，这条关系判据当场红；红的是判据的取证面，不是并集。
            前端 <code>lcEvidenceGapNote.test.tsx</code>（走真出口，含位置契约、"别类不印"与"同段只许一个另需交代"的反向对照，
            本刀 +3 条：⑤单独 / ⑥单独 / 四类同段）。
          </div>
        </li>
        <li>
          <b>橙底 = 新句那一段</b>
          <div>
            这一屏所有字都由生产出口现产，橙底只是按 <code>另需交代：本次有</code> /
            <code>另需交代：本轮没有</code> / <code>另需交代：这一类的扩词</code> 三种开头定位描的边，不参与措辞。
            ⚠️ 锚点必须三条都在：少了哪一条，<b>只有那一种成因命中</b>的那一档整段橙底会消失
            （F 档当年红过一次，H 档是同一坑的第二遍）。原先那块"灰框 = R23-B2 会撤走的那半"
            的示意机关已随撤句删除 —— 现在每段只剩<b>一个</b>「另需交代：」。
            <br />
            ✅ R23-D 新拆的两位<b>不需要</b>第四条锚点：它们指得出词 ⇒ 沿用「本次有 N 个…」开头，
            正好落在第一条锚上（这是"计数写在子句里、不写进前缀"那条纪律的副产品）。
          </div>
        </li>
        <li>
          <b>本刀没做</b>
          <div>
            不动 <code>evidence_complete</code>（乙2 只<b>加了键</b>
            <code>coverage_numerator_incomplete_categories</code>，三处消费点仍读老判据 ⇒ 丙′ 那笔仍欠；
            屏上这句话也<b>不读</b>那个键，它只管分子召回不管边界）· 不动边际止损单位（丙未拍）·
            不删 <code>poi_collector.py:686</code> 那条不可达的 <code>consume</code> 分支（它兼任扣款的返回值检查，§14⑤.2）·
            不动<b>类级</b>那份 <code>evidence_capped_categories</code>（它喂 <code>unjudgeable_by_cap</code> 判定，
            与措辞无关 ⇒ 本刀只是把<b>词级</b>那份也发射出去，没换它的用途）· 不动缓存键 · 不回填夹具
            ⇒ 存量 30 份报告<b>都没有这三个新键</b>（<code>out_of_budget</code> / <code>capped_terms</code> /
            <code>failed_terms</code>），一律读作"不知道"，而不是"没有类别扩到一半停了 / 没有词被断页 / 没有词没成"。
            <br />
            ⚠️ 本刀挖出、<b>下一刀已修</b>的一条（计划 §20⑦ / §21 / 台账 #81）：<code>scope.py</code> 那道
            "封顶名单 ⊆ 有实测边界的类"闸拿错了对照面 —— 边界表只认 <code>bind_evidence</code> 交进去的
            <b>三要素那三类</b>，而封顶事实按<b>所有类</b>收集 ⇒ 任何<b>非三要素</b>关键词类撞上
            <code>server_cap</code>，live 路径会在绑定期抛 <code>ValueError</code>、整份报告失败。
            今天没现形只因为真跑那两次的 capped 都是<b>空</b>。现已改为比对 <code>evidence_stop_reasons</code>
            （与 <code>capped</code> 同源），判据 <code>tests/test_capped_category_gate.py</code>。
            <br />
            <b>本屏同批改掉的一处假话</b>：第三种成因那句原写「一个扩词词都没发起」，而一类<b>首次</b>扩词就撞
            接口失败、此时额度归零 ⇒ 它<b>发起过</b>（<code>_record_failure</code> 留了 <code>api_error</code> 行），
            那句在这一档是假话 ⇒ 改「一次都没扩成」（两种分支都为真，判据
            <code>test_a_class_that_failed_its_first_attempt_is_labeled_truthfully</code>）。
            <br />
            真跑对照<b>已做过两次</b>（§11 与 §18④ 重测，凯里老街各 31 次真实调用 —— 本刀那一格的成因就是它抓出来的，
            而"四个键全空"那句也是重测推翻的），新键的兑现点是下一次真体检。
          </div>
        </li>
      </ol>
      <div className="legend-foot">
        读数交代：库里 30 份存量报告<b>没有一份</b>带 <code>required_in_circle</code>（= <code>cov-1</code> 之后还没产过报告）
        ⇒ 这一屏的 B/C/D/F/G/H 六档都是<b>构造载荷</b>，兑现点是下一次真体检。
        其中 <b>H 档那一格的死法不是编的</b>：§18④ 那次真跑重测里 <code>education</code> 就是它（扩了 4 轮、门槛项 1/3，
        而当时只被"没查全"那一位交代）。⚠️ 但"<b>只有</b>⑤命中"是构造 —— 真实那一格 ③⑤ <b>两位同时</b>命中，
        拼装形状见 <b>G</b>；这一档印的是"同一格将来该说全的话"。
      </div>
    </div>
  )
}

function App() {
  const want = new URLSearchParams(location.search).get('tier') ?? 'all'
  const shown = want === 'all' ? TIERS : TIERS.filter((t) => t.id === want)
  return (
    <>
      {shown.map((t) => (
        <div key={t.id}>{t.node}</div>
      ))}
      <Legend />
    </>
  )
}

createRoot(document.getElementById('lc-starved-root')!).render(<App />)
