/**
 * 调研屏样式复刻 · 出图探针（计划 lively-bay-bream v7，本波不改生产码）
 *
 * 打开：`http://localhost:3400/preview-overview-cards.html`
 *
 * 截图参数（headless 出图不能点击，故状态由 URL 决定）：
 * `?view=all|now|stats|cards|experts`（默认 all＝五段同宽长图）· `?expand=1`（B 档展成 25 张，看"展开全部"之后的样子）。
 *
 * 要拍的一件事：三块复刻成源页样式后**长什么样、代价在哪**，其中概览卡还要在
 * A（全画）/ B（只画 9 张 + 截断说明 + 展开全部）/ C（只画 9 张 + 容器内滚）之间拍一个。
 *
 * 真实渲染的口径：
 * - 数据走 `lib/api.fetchIntel()` ⇒ 真实后端 `/api/intel`、`fetchWorkload('travel')` ⇒ `/api/experts/workload`，不是夹具；
 * - 「现状」段的 class 与文案逐条抄自生产页 `pages/reports/ResearchIntelView.tsx`
 *   （那三块是页面私有函数，无法 import，故此处为 1:1 抄写；抄完已在真入口
 *   `/reports?domain=travel` 的 DOM 上比对过 class 串：统计格 `rounded-card border
 *   border-line/60 bg-card p-4 shadow-card`、表格 `w-full border-collapse text-tag` + 7 列表头 +
 *   25 行、专家格 `rounded-card border border-line/70 bg-bg/60 p-3` 全部一致）；
 * - 复刻段的 class 抄自源页 `52b0199:frontend/src/pages/DashboardPage.tsx`
 *   （`StatCard:530` / `ImpactCard:555` / 概览卡 `:250-298` / 专家榜 `:489-523`）。
 *
 * 诚实标注：B/C 两档的「只画 9 张」是**本页演示**——真实 `cards_truncated` 当前为 `false`
 * （后端 LIMIT ≥ 报告数），所以那两档显示的是"若真截断该怎么说"，不是现状。
 *
 * 本页不写库、不发删除请求：删除按钮只占位（`aria-label` 与生产同名，供比对位置）。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与 eslint ——
 * 取证代码烂掉等于防线烂掉。
 *
 * ⚠️ 出图前必做：dev server **不会**为新建的探针文件重扫 Tailwind 的 content，
 * 于是本页独有的 `xl:grid-cols-3` / `max-h-[520px]` 会**静默不生成**（第一版图就是
 * 2 列、C 档不裁剪，看着像"设计如此"）。先 `touch src/index.css` 再出图，
 * 或在控制台确认 `document.styleSheets` 里查得到 `xl\:grid-cols-3`。
 */
import { StrictMode, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Activity,
  Clock,
  Database,
  FileText,
  Gauge,
  Layers,
  Network,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  Users,
  Zap,
} from 'lucide-react'
import '../index.css'
import { VCard, VChip, VCountUp } from '../components/ui'
import { fetchIntel, fetchWorkload } from '../lib/api'
import type { IntelOverview, ResearchCard, ExpertWorkload } from '../types'

const Q = new URLSearchParams(window.location.search)
const VIEW = Q.get('view') ?? 'all'
const EXPAND_B = Q.get('expand') === '1'

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
    id: 'S1',
    label: '现状对照（未改）',
    now: '统计块无图标无解释文字；概览是 7 列表格；专家是名字 + 一行文字',
    target: '本段保持生产原样，只作横比基线',
    effect: '同一批数据、同一屏宽，差别一眼可数',
  },
  {
    id: 'S2',
    label: '统计卡丰富样式（图一）',
    now: '八格素卡：数字 + 标签，公式说明只在 title 悬浮里',
    target: '源页形状：图标面 + 大字 + 标签 + 解释文字直接可见；价值块用 flat 卡 + tooltip',
    effect: '不用悬停就知道"交叉验证率"怎么来的；卡更高，八块屏整体再长约一屏',
  },
  {
    id: 'S3',
    label: '每次调研概览卡片化（图一）',
    now: '25 行表格：一行一报告，六列数字，删除在行尾',
    target: '3 列卡片：目的地 chip + 六格 Mini + 报告/决策日志动作排，删除移到卡右上',
    effect: '单份报告更好读，但 25 张要滚；纵向高度约为表格的 3 倍',
  },
  {
    id: 'S3A',
    label: 'A 档 · 全画',
    now: '—',
    target: '库里 25 份就画 25 张，一次到底',
    effect: '不存在"看着像全列了"；代价是屏最长',
  },
  {
    id: 'S3B',
    label: 'B 档 · 只画 9 张 + 显式说明 + 展开全部',
    now: '—',
    target: '9 张，下方「仅列最近 9 份（库内共 25 份）」+ 展开全部按钮',
    effect: '屏短且截断可见；代价是多一次点击，且数字必须与 report_total 同源',
  },
  {
    id: 'S3C',
    label: 'C 档 · 只画 9 张 + 容器内滚',
    now: '—',
    target: '9 张进 max-h-[520px] 的滚动容器',
    effect: '屏最短；滚动条嵌在卡里，屏外的人看不见"还有多少"——三档里唯一要靠页面别处补总数的',
  },
  {
    id: 'S4',
    label: '专家贡献丰富样式（图三）',
    now: '8 格小卡：名字 + 一行三项计数，整卡不可点',
    target: '源页形状：整卡可点跳专家页 + 圆形头像 + 层级徽标 + 三项带图标',
    effect: '层级徽标用现成 VChip neutral，不再造第三套 L1/L2/L3 配色',
  },
  {
    id: 'S5',
    label: '未在本次复刻的三块',
    now: '目的地图谱 / 信源结构与研判 / 证据流与溯源追踪',
    target: '本波不动，图里也不重画',
    effect: '复刻若落地，这三块与卡片化概览同屏共存，屏长要按五段一起算',
  },
]

/* ── 通用外壳件 ─────────────────────────────────────────────────── */

function Change({ region, children }: { region: string; children: ReactNode }) {
  return (
    <div className="fcp-change">
      <span className="badge">{region}</span>
      {children}
    </div>
  )
}

function BlockTitle({ icon: Icon, title, hint }: { icon: typeof FileText; title: string; hint: string }) {
  return (
    <div className="flex items-center gap-2 text-aux font-semibold text-ink">
      <Icon size={16} className="text-primary" /> {title}
      <span className="ml-1 text-tag text-ink-3">{hint}</span>
    </div>
  )
}

/** 源页 `fmtSaved`：≥60 分钟折成小时 */
function fmtSaved(min: number): { value: number; unit: string } {
  if (min >= 60) return { value: Math.round((min / 60) * 10) / 10, unit: '小时' }
  return { value: Math.round(min), unit: '分钟' }
}

/* ── S1 现状：1:1 抄自 pages/reports/ResearchIntelView.tsx ────────── */

function StatNow({ value, unit = '', label, tip }: { value: number; unit?: string; label: string; tip: string }) {
  return (
    <div className="rounded-card border border-line/60 bg-card p-4 shadow-card" title={tip}>
      <div className="flex items-end gap-0.5">
        <span className="font-serif text-[26px] leading-none text-ink">{value}</span>
        {unit && <span className="text-aux text-ink-2">{unit}</span>}
      </div>
      <div className="mt-1 text-tag font-medium text-ink-2">{label}</div>
    </div>
  )
}

function CardTitleNow({ title, hint }: { title: string; hint: string }) {
  return (
    <h3 className="text-aux font-semibold text-ink">
      {title}
      <span className="ml-2 text-tag font-normal text-ink-3">{hint}</span>
    </h3>
  )
}

function VariantNow({ intel, workload }: { intel: IntelOverview; workload: ExpertWorkload[] }) {
  const nodes = intel.destination_graph.nodes
  return (
    <section className="mt-3">
      <h2 className="font-serif text-h2 text-ink">S1 · 现状（生产页这三块今天长这样）</h2>
      <p className="mt-1 text-tag text-ink-3">
        下面这些就是 <code>/reports?domain=travel</code> 的当前形态，class 逐条抄自
        <code>ResearchIntelView.tsx</code>，用来给 S2/S3/S4 当基线；其余五块（图谱、信源、证据流…）见 S5 说明，本波不动。
      </p>
      <Change region="S1">
        <div className="flex flex-col gap-4 p-2">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatNow
              value={nodes.length}
              label="覆盖目的地"
              tip={`全库 ${intel.destination_graph.scanned} 行证据里归并出的目的地数`}
            />
            <StatNow value={intel.evidence_total} label="情报证据" tip="库内证据行总数（全库口径）" />
            <StatNow value={intel.claim_total} label="产出结论" tip="全部报告输出的分析结论总数" />
            <StatNow value={intel.fact_accuracy} unit="%" label="交叉验证率" tip="高置信结论 ÷ 全部结论" />
          </div>

          <VCard hover={false}>
            <CardTitleNow title="业务闭环价值" hint="公式来自各报告 metrics · 数据源 /api/intel" />
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatNow
                value={Math.round((intel.minutes_saved / 60) * 10) / 10}
                unit="小时"
                label="累计节省人力"
                tip="∑(人工估时 − AI 实际耗时)"
              />
              <StatNow value={intel.avg_efficiency} unit="×" label="平均效率提升" tip="人工估时 ÷ 实际耗时 的平均倍数" />
              <StatNow value={intel.avg_coverage} unit="×" label="平均信源覆盖" tip="每份报告平均独立信源数" />
              <StatNow
                value={intel.avg_evidence_per_report}
                unit="条"
                label="平均每篇证据"
                tip="证据总数 ÷ 报告数"
              />
            </div>
          </VCard>

          <VCard hover={false}>
            <div className="flex items-baseline gap-2">
              <CardTitleNow title="每次调研概览" hint={`共 ${intel.report_total} 份`} />
              {intel.cards_truncated && (
                <span className="text-tag text-warn">
                  仅列最近 {intel.cards.length} 份（库内共 {intel.report_total} 份）
                </span>
              )}
            </div>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full border-collapse text-tag">
                <thead>
                  <tr className="text-left text-ink-3">
                    <th className="border-b border-line px-2 py-2 font-medium">报告</th>
                    <th className="border-b border-line px-2 py-2 font-medium">证据</th>
                    <th className="border-b border-line px-2 py-2 font-medium">结论</th>
                    <th className="border-b border-line px-2 py-2 font-medium">高可信</th>
                    <th className="border-b border-line px-2 py-2 font-medium">效率</th>
                    <th className="border-b border-line px-2 py-2 font-medium">节省</th>
                    <th className="border-b border-line px-2 py-2 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {intel.cards.map((c) => (
                    <tr key={c.id} className="hover:bg-bg/60">
                      <td className="max-w-[280px] truncate border-b border-line/60 px-2 py-2" title={c.title}>
                        {c.title}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2 tabular-nums">{c.evidence_count}</td>
                      <td className="border-b border-line/60 px-2 py-2 tabular-nums">{c.claim_count}</td>
                      <td className="border-b border-line/60 px-2 py-2 tabular-nums">{c.high_conf_count}</td>
                      <td className="border-b border-line/60 px-2 py-2 tabular-nums">
                        {c.efficiency_multiple ? `${c.efficiency_multiple}×` : '—'}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2 tabular-nums">
                        {c.minutes_saved ? `${c.minutes_saved} 分钟` : '—'}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2 text-right">
                        <span
                          aria-label="删除目的地调研"
                          className="grid h-8 w-8 place-items-center rounded-btn text-ink-3"
                        >
                          <Trash2 size={14} />
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </VCard>

          <VCard hover={false}>
            <CardTitleNow title="专家贡献" hint="按参与任务数排序" />
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {workload
                .filter((w) => w.missions > 0)
                .slice(0, 8)
                .map((w) => (
                  <div key={w.id} className="rounded-card border border-line/70 bg-bg/60 p-3">
                    <div className="text-aux font-medium text-ink">{w.name}</div>
                    <div className="mt-1 text-tag text-ink-3">
                      {w.missions} 次任务 · 结论 {w.claims_authored} · 证据 {w.evidence_collected}
                    </div>
                  </div>
                ))}
            </div>
          </VCard>
        </div>
      </Change>
    </section>
  )
}

/* ── S2 统计卡丰富样式：照搬源页 StatCard / ImpactCard ─────────────── */

function StatCardRich({
  icon: Icon,
  value,
  label,
  tip,
  unit,
  color = 'text-primary',
}: {
  icon: typeof FileText
  value: number
  label: string
  tip: string
  unit?: string
  color?: string
}) {
  return (
    <VCard hover={false}>
      <span className={`grid h-9 w-9 place-items-center rounded-btn bg-primary-tint ${color}`}>
        <Icon size={18} />
      </span>
      <div className="mt-3 flex items-end gap-0.5">
        <span className="font-serif text-[32px] leading-none text-ink">
          <VCountUp value={value} />
        </span>
        {unit && <span className="mb-1 text-h3 text-ink-2">{unit}</span>}
      </div>
      <div className="mt-1 text-aux font-medium text-ink">{label}</div>
      <p className="mt-1 text-tag leading-relaxed text-ink-3">{tip}</p>
    </VCard>
  )
}

function ImpactCardRich({
  icon: Icon,
  value,
  label,
  tip,
  unit,
  color = 'text-primary',
}: {
  icon: typeof FileText
  value: number
  label: string
  tip: string
  unit?: string
  color?: string
}) {
  return (
    <div className="rounded-card border border-line/60 bg-bg p-4" title={tip}>
      <span className={`grid h-8 w-8 place-items-center rounded-btn bg-primary-tint ${color}`}>
        <Icon size={16} />
      </span>
      <div className="mt-2.5 flex items-end gap-0.5">
        <span className="font-serif text-[26px] leading-none text-ink">
          <VCountUp value={value} />
        </span>
        {unit && <span className="mb-0.5 text-aux text-ink-2">{unit}</span>}
      </div>
      <div className="mt-1 text-tag font-medium text-ink-2">{label}</div>
    </div>
  )
}

function VariantStats({ intel }: { intel: IntelOverview }) {
  const saved = fmtSaved(intel.minutes_saved ?? 0)
  const g = intel.destination_graph
  return (
    <section className="mt-12">
      <h2 className="font-serif text-h2 text-ink">S2 · 统计卡复刻图一（丰富样式）</h2>
      <p className="mt-1 text-tag text-ink-3">
        口径一个字没改：目的地数仍取<b>全库图谱节点</b>、交叉验证率仍是「高置信 ÷ 全部结论」，
        换的只是面——图标 + 解释文字从 title 悬浮提到卡面上。第四格是源页的「累计 Token 算力」
        （<code>total_tokens ÷ 1000</code> 取整），它顶掉了现状的「平均每篇证据」。
      </p>
      <Change region="S2">
        <div className="p-2">
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <StatCardRich
              icon={Target}
              value={g.nodes.length}
              label="覆盖目的地"
              tip={`全库 ${g.scanned} 行证据里归并出的目的地数（其中 ${g.unattributed} 行无归属，不参与图谱）`}
            />
            <StatCardRich
              icon={Database}
              value={intel.evidence_total}
              label="情报证据"
              tip={`累计联网取证，平均每篇报告 ${intel.avg_evidence_per_report} 条`}
            />
            <StatCardRich icon={Sparkles} value={intel.claim_total} label="产出结论" tip="全部报告输出的分析结论总数" />
            <StatCardRich
              icon={ShieldCheck}
              value={intel.fact_accuracy}
              unit="%"
              color="text-ok"
              label="交叉验证率"
              tip="经 ≥2 个独立来源相互印证的结论占比（真实计算，越高越可信）"
            />
          </div>

          <div className="mt-5">
            <VCard hover={false}>
              <BlockTitle icon={Gauge} title="业务闭环价值" hint="相比传统人工调研的可量化提升 · 公式透明" />
              <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <ImpactCardRich
                  icon={Clock}
                  value={saved.value}
                  unit={saved.unit}
                  label="累计节省人力"
                  tip="∑(人工估时 − AI 实际耗时)，按每信息源约 8 分钟估算"
                />
                <ImpactCardRich
                  icon={Zap}
                  color="text-warn"
                  value={intel.avg_efficiency}
                  unit="×"
                  label="平均效率提升"
                  tip="各报告『人工估时 ÷ AI 实际耗时』的平均倍数"
                />
                <ImpactCardRich
                  icon={Layers}
                  color="text-ok"
                  value={intel.avg_coverage}
                  unit="×"
                  label="平均信源覆盖"
                  tip="各报告『独立信源数 ÷ 人工基线(6)』的平均倍数"
                />
                <ImpactCardRich
                  icon={Activity}
                  color="text-info"
                  value={Math.round((intel.total_tokens ?? 0) / 1000)}
                  unit="K"
                  label="累计 Token 算力"
                  tip="所有调研真实消耗的 LLM Token 总量（千）"
                />
              </div>
            </VCard>
          </div>
        </div>
      </Change>
    </section>
  )
}

/* ── S3 概览卡片化：源页卡片形状，三档摆法 ───────────────────────── */

function Mini({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-btn bg-card/60 py-1.5">
      <div className={`text-aux font-semibold ${accent ? 'text-primary-deep' : 'text-ink'}`}>{value}</div>
      <div className="text-tag text-ink-3">{label}</div>
    </div>
  )
}

function OverviewCard({ card, onDelete }: { card: ResearchCard; onDelete: (c: ResearchCard) => void }) {
  return (
    <div className="rounded-card border border-line/60 bg-bg p-4 transition-all hover:border-primary-soft hover:bg-card">
      <div className="flex items-start justify-between gap-2">
        <a
          href={`/report/${card.id}`}
          className="line-clamp-2 text-left text-aux font-medium text-ink hover:text-primary-deep"
        >
          {card.title}
        </a>
        <button
          type="button"
          aria-label="删除目的地调研"
          title="取证页不删记录，只看位置"
          onClick={() => onDelete(card)}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-btn text-ink-3 hover:bg-risk/10 hover:text-risk"
        >
          <Trash2 size={14} />
        </button>
      </div>
      {card.destinations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {card.destinations.slice(0, 4).map((b) => (
            <span key={b} className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag text-primary-deep">
              {b}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Mini label="证据" value={`${card.evidence_count}`} />
        <Mini label="结论" value={`${card.claim_count}`} />
        <Mini label="高置信" value={`${card.high_conf_count}`} />
        <Mini label="效率" value={card.efficiency_multiple ? `${card.efficiency_multiple}×` : '—'} accent />
        <Mini label="省时" value={card.minutes_saved ? `${Math.round(card.minutes_saved)}m` : '—'} accent />
        <Mini label="耗时" value={card.elapsed_minutes ? `${card.elapsed_minutes}m` : '—'} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <a
          href={`/report/${card.id}`}
          className="inline-flex items-center gap-1 rounded-btn bg-primary-tint px-2.5 text-tag font-medium text-primary-deep hover:bg-primary-soft/50"
          style={{ height: 28 }}
        >
          <FileText size={12} /> 报告
        </a>
        <a
          href={`/trace/${card.id}`}
          className="inline-flex items-center gap-1 rounded-btn bg-bg px-2.5 text-tag font-medium text-ink-2 ring-1 ring-line hover:text-primary-deep"
          style={{ height: 28 }}
        >
          <Network size={12} /> 决策日志
        </a>
      </div>
    </div>
  )
}

const GRID = 'grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3'

function VariantCards({ intel }: { intel: IntelOverview }) {
  const [expanded, setExpanded] = useState(EXPAND_B)
  const total = intel.report_total
  const head9 = useMemo(() => intel.cards.slice(0, 9), [intel.cards])
  const nothing = () => {}

  return (
    <section className="mt-12">
      <h2 className="font-serif text-h2 text-ink">S3 · 每次调研概览复刻图一（三档摆法，同宽连排）</h2>
      <p className="mt-1 text-tag text-ink-3">
        卡片内容与数字全部来自 <code>/api/intel · cards</code>（与 S1 表格同一批），差别只在<b>画多少张、怎么收</b>。
        真实 <code>cards_truncated</code> 现在是 <b>{String(intel.cards_truncated)}</b>（后端 LIMIT ≥ 报告数 ⇒ 不截断），
        所以 B/C 的「只画 9 张」是<b>本页演示</b>：看的是"若真截断，说明该摆在哪、长什么样"。
      </p>

      <Change region="S3">
        <div className="p-2">
          <h3 className="text-aux font-semibold text-ink">A · 全画 {total} 张</h3>
          <p className="mt-1 text-tag text-ink-3">
            S3A 代价：屏最长，但"列了多少"和"库里有几份"永远一致，不靠文案兜。
          </p>
          <div className={`mt-3 ${GRID}`}>
            {intel.cards.map((c) => (
              <OverviewCard key={`a-${c.id}`} card={c} onDelete={nothing} />
            ))}
          </div>
        </div>
      </Change>

      <Change region="S3B">
        <div className="p-2">
          <h3 className="text-aux font-semibold text-ink">B · 只画 9 张 + 显式说明 + 展开全部</h3>
          <div className={`mt-3 ${GRID}`}>
            {(expanded ? intel.cards : head9).map((c) => (
              <OverviewCard key={`b-${c.id}`} card={c} onDelete={nothing} />
            ))}
          </div>
          <div className="mt-3 flex items-center gap-3 rounded-card border border-line/60 bg-bg px-3 py-2">
            <span className="text-tag text-warn">仅列最近 9 份（库内共 {total} 份）</span>
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="rounded-btn bg-primary-tint px-3 text-tag font-medium text-primary-deep"
              style={{ height: 28 }}
            >
              {expanded ? '收起' : `展开全部 ${total} 份`}
            </button>
            <span className="ml-auto text-tag text-ink-3">当前画 {expanded ? total : 9} 张</span>
          </div>
        </div>
      </Change>

      <Change region="S3C">
        <div className="p-2">
          <h3 className="text-aux font-semibold text-ink">C · 只画 9 张 + 容器内滚（max-h-520）</h3>
          <p className="mt-1 text-tag text-ink-3">
            截图里能直接看见第 3 行被容器边裁掉——这就是它的代价：卡内滚动条，屏外的人不知道还有几份。
          </p>
          <div className="mt-3 max-h-[520px] overflow-y-auto pr-1">
            <div className={GRID}>
              {head9.map((c) => (
                <OverviewCard key={`c-${c.id}`} card={c} onDelete={nothing} />
              ))}
            </div>
          </div>
          <p className="mt-2 text-tag text-ink-3">共 {total} 份 · 容器内可滚（现状表格无此问题：26 行一眼数得完）</p>
        </div>
      </Change>
    </section>
  )
}

/* ── S4 专家贡献：源页榜卡形状，层级徽标走现成 VChip neutral ──────── */

function VariantExperts({ workload }: { workload: ExpertWorkload[] }) {
  const active = useMemo(() => workload.filter((w) => w.missions > 0), [workload])
  return (
    <section className="mt-12">
      <h2 className="font-serif text-h2 text-ink">S4 · 专家贡献复刻图三（丰富样式）</h2>
      <p className="mt-1 text-tag text-ink-3">
        排序与取数不变（<code>/api/experts/workload</code>，按 missions 降序，{workload.length} 位里筛出 {active.length}{' '}
        位出过工）。层级徽标用现成 <code>VChip level=&quot;neutral&quot;</code>——源页那行 class
        与它同色，所以零新映射，不再造第三套 L1/L2/L3 配色。
      </p>
      <Change region="S4">
        <VCard hover={false} className="mt-3">
          <BlockTitle icon={Users} title="专家贡献榜" hint="按真实参与任务量排序 · 点击进专家页" />
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {active.map((w) => (
              <a
                key={w.id}
                href={`/experts/${w.id}`}
                className="flex items-center gap-3 rounded-card border border-line/60 bg-bg p-3 text-left transition-all hover:border-primary-soft hover:bg-card"
              >
                <img
                  src={w.avatar}
                  alt={w.name}
                  className="h-10 w-10 shrink-0 rounded-full object-cover"
                  onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-aux font-medium text-ink">{w.name}</span>
                    <VChip label={w.layer} className="!h-5 !px-1.5 !text-tag" />
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-tag text-ink-3">
                    <span className="inline-flex items-center gap-1">
                      <Layers size={11} /> {w.missions} 任务
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Activity size={11} /> {w.claims_authored} 结论
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Database size={11} /> {w.evidence_collected} 证据
                    </span>
                  </div>
                </div>
              </a>
            ))}
          </div>
        </VCard>
      </Change>
    </section>
  )
}

/* ── S5 + 图例 ─────────────────────────────────────────────────── */

function Untouched() {
  return (
    <Change region="S5">
      <div className="p-3">
        <h3 className="text-aux font-semibold text-ink">本波不动的三块（复刻落地后与上面同屏共存）</h3>
        <p className="mt-2 text-tag text-ink-2">
          目的地情报图谱、信源结构与研判、证据流与溯源追踪——生产页现在已有这三块，样式不在本次参考图里，
          所以本探针不重画。要留意的是<b>整屏长度</b>：S2 比 S1 高、S3 的 A 档再高出约 1900px，
          落地后"八块"的总屏长按这五段的实际高度累加，不是我估的。
        </p>
      </div>
    </Change>
  )
}

function Legend({ intel }: { intel: IntelOverview }) {
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
        真实数据：/api/intel 共 {intel.report_total} 份报告 / {intel.evidence_total} 行证据 /{' '}
        {intel.destination_graph.nodes.length} 个目的地；专家来自 /api/experts/workload。
        本探针不写库、不删记录，删除按钮只占位。
      </div>
    </div>
  )
}

/** 导出只为满足 eslint 的 react-refresh 要求（同 `dev/wordcloudTierProbe.tsx:47`）；本页无消费者。 */
export function Probe() {
  const [intel, setIntel] = useState<IntelOverview | null>(null)
  const [workload, setWorkload] = useState<ExpertWorkload[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchIntel(), fetchWorkload('travel')])
      .then(([i, w]) => {
        setIntel(i)
        setWorkload(w)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (error) {
    return (
      <div className="box" style={{ color: '#8F5E56' }}>
        取数失败：{error}（本预览必须有真实 /api/intel，不用空壳假装渲染成功）
      </div>
    )
  }
  if (!intel) return <div className="box">正在取真实调研情报……</div>

  if (VIEW === 'now') return <VariantNow intel={intel} workload={workload} />
  if (VIEW === 'stats') return <VariantStats intel={intel} />
  if (VIEW === 'cards') return <VariantCards intel={intel} />
  if (VIEW === 'experts') return <VariantExperts workload={workload} />

  return (
    <>
      <VariantNow intel={intel} workload={workload} />
      <VariantStats intel={intel} />
      <VariantCards intel={intel} />
      <VariantExperts workload={workload} />
      <Untouched />
      <Legend intel={intel} />
    </>
  )
}

createRoot(document.getElementById('overview-cards-root')!).render(
  <StrictMode>
    <Probe />
  </StrictMode>,
)
