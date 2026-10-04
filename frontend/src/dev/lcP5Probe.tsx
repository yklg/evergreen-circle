/**
 * 生活圈片 5（前端三件）· 三档形态预览探针（**预览闸，不改生产码**）
 *
 * 打开：`http://localhost:3400/preview-lc-p5.html`
 * 参数：`?view=now|jia|yi|cmp`（默认 cmp = 现状 / 档甲只常驻 / 档乙常驻+实时 三段同宽长图）
 *
 * 要拍的一件事：`round` 事件、`caliber.forensic`、`caliber.evidence_anchors`、`report.partial`
 * 这四份已经在线上发出去的东西，**用户在哪里看、看多少**。
 *
 * 真实渲染的口径（哪些是真、哪些是桩，页内图例里也写着）：
 * - 数据来自 `skip/tmp/lc_p5_dump.py`：跑生产 `data_source.live_forensic_steps` +
 *   `assemble_living_circle`，客户端是 `lc_p4_dry.StubClient` ⇒ **零真实调用**；
 *   `caliber.forensic` / `evidence_anchors` / `partial` 三块的键名与线上逐字一致，
 *   POI 名称与坐标是桩产物。
 * - 版式与色阶抄自生产件（`LifeCirclePage.tsx:603-627` 进度横幅、`LcMap.tsx:1022-1130`
 *   降级画布、`LifeCircleReportView.tsx:270-565` 体检单），文案一律走 `lib/livingCircle.ts`
 *   既有出口（`poiMetricLabel` / `blindspotCoverageNote` / `emptyBlindspotNote` / `degradeDetailLabel`）。
 * - 回合上屏那句 `text` 与后端 `pipeline/living_circle.py` 的 STEP_ROUND 分支同式；
 *   落地后前端直接显示事件自带的 text，不在前端重排句子。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与 eslint ——
 * 预览脚手架烂掉等于闸口烂掉。
 */
import { createRoot } from 'react-dom/client'
import type { ReactNode } from 'react'
import { Info, Layers, Play, TriangleAlert } from 'lucide-react'
import '../index.css'
import scenarios from './fixtures/lcP5Scenarios.json'
import { minuteHeatColor } from '../components/lifecircle/HeatFieldOverlay'
import { VStatLine } from '../components/ui'
import {
  LC_BLIND_SEV,
  LC_BLIND_SEV_ORDER,
  LC_CANVAS,
  lcEvidenceDiscColor,
  LC_ISO_COLORS,
  blindSevSpec,
  blindPolygonOf,
  blindspotCoverageNote,
  confidenceBadgeLabel,
  dataOriginBadge,
  emptyBlindspotNote,
  evidenceDiscs,
  evidenceDiscTitle,
  forensicAccount,
  gapScoreOf,
  heatSamplePoints,
  lcPolyPts,
  lcRightmost,
  lcRing,
  lcEvidenceCategoryLabel,
  lcSnapshotPoiLayer,
  lcToPx,
  partialBanner,
  roundAnchorCell,
  roundDroppedCell,
  poiConservationNote,
  poiMetricLabel,
  poiRenderSet,
  poiThinNote,
  samplingReach,
  severityOf,
  staleCaliberNotice,
  triadRows,
} from '../lib/livingCircle'
import type { ForensicAccount, ForensicRoundRow, LngLat, LivingCircleReport } from '../types'
import { stageLabel } from '../mocks/livingCircleStream'

/* 片 5 的三份形状已进 `types.ts` ⇒ 探针直接消费生产类型（不再自带一份镜像：
   预览与实现用的是同一个契约，类型写错这里当场红）。 */

const scenes = scenarios as unknown as {
  _meta: { source: string; honesty: string }
  one_round: { events: { type: string; text: string; round: ForensicRoundRow }[]; report: LivingCircleReport }
  first_round_complete: { report: LivingCircleReport }
}

const LIVE = scenes.one_round.report
const CLEAN = scenes.first_round_complete.report
const LIVE_EVENT = scenes.one_round.events[0]
const LIVE_ACCOUNT = forensicAccount(LIVE)

/* ── 改动区清单：徽标编号与页内图例的唯一真相源（闸口要求同源） ───────────── */

interface Region {
  id: string
  label: string
  now: string
  target: string
  effect: string
  tiers: string
}

const REGIONS: Region[] = [
  {
    id: 'P1',
    label: '体检进行中横幅',
    now: '只有 stage + 百分比 + 一条 message；`round` 事件被 `onFlowEvent` 静默丢弃（lifeCircleFlow.ts:62-82）',
    target: '横幅内多一行回合账：多少补算锚点、多少次调用、未决格 X→Y、额度还剩多少',
    effect: '补算那 10 秒不再是「进度条干爬」；`round` 事件第一次有真消费者',
    tiers: '仅档乙',
  },
  {
    id: 'P2',
    label: '报告顶部摘要条 chip',
    now: '数据源徽标 + 15min 圈面积 + 盲区数（LifeCircleReportView.tsx:270-296）',
    target: '再加两颗 chip：取证 N 轮 · 证据域 M 盘，悬浮给 `points_policy` 那句口径',
    effect: '不展开报告也知道「它自己补算过」；chip 悬浮即口径出处',
    tiers: '仅档乙',
  },
  {
    id: 'P3',
    label: '体检单新增「取证回合」小节',
    now: '`caliber.forensic` 已在落库件里，但前端 `caliber` 类型停在 `evidence_starved_terms`（types.ts:979-1030）⇒ 一个数都不显示',
    target: '逐趟表格（派发/调用/锚点 计划→派发→用/未跑·砍掉/未决格 X→Y/收手原因）+ 额度条 + 口径句',
    effect: '历史报告也能回答「这次为什么只判到 42 格」；缺 `forensic` 的旧快照整节不出现',
    tiers: '甲 + 乙',
  },
  {
    id: 'P4',
    label: 'partial 横幅（取证额度不足）',
    now: '`report.partial` 前端无类型、无出口；`degradeBanner()` 标题写死「已降级为离线估算」（livingCircle.ts:1083-1096），复用它就是说假话',
    target: '独立 warn 色横幅：标签走 `degradeDetailLabel(detail)`，正文用后端 `note`，不给「重检」按钮',
    effect: '「额度不足」与「接口熔断」在色阶与文案上分开 —— 前者是按计划只打了这么多，后者是事故',
    tiers: '甲 + 乙',
  },
  {
    id: 'P5',
    label: '证据域图层（逐锚点举证盘）',
    now: '地图只有 8 类 POI / 采样热力 / 盲区三档 / A-B 对比（LcMap.tsx:1022-1130）；这 34 个举证盘无处可看',
    target: '图例加「证据域」勾选（**落地默认关，本图是勾选后的样子**）；实线=查全、虚线=截断，逐盘 title 给实测/请求半径与 stop_reason',
    effect: '「为什么这格判不了」从一句话变成看得见的边界；代价见「附二」—— 34 个 1.4km 盘一叠加中心就糊，填充档最重',
    tiers: '甲 + 乙',
  },
]

function Chip({ children, title, tone = 'primary' }: { children: ReactNode; title?: string; tone?: 'primary' | 'warn' }) {
  const cls = tone === 'warn' ? 'border border-warn/60 bg-warn/10 text-ink-2' : 'bg-primary-tint text-primary-deep'
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-chip px-2 py-0.5 text-tag font-medium ${cls}`}>
      {children}
    </span>
  )
}

/* ── P1 · 体检进行中横幅（抄 LifeCirclePage.tsx:603-627） ─────────────────── */

function ProgressBanner({ withRound }: { withRound: boolean }) {
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-card border border-primary-soft bg-primary-tint px-4 py-3"
      role="status"
      aria-live="polite"
    >
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-btn bg-primary text-white">
        <Play size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-aux font-semibold text-ink">
          生活圈体检进行中 · {stageLabel('collect')}
          <span className="text-tag font-medium text-primary-deep">72%</span>
        </div>
        <div className="truncate text-tag text-ink-2" title="正在采集 8 类设施点位">
          正在采集 8 类设施点位…
        </div>
        {withRound && LIVE_EVENT && LIVE_ACCOUNT && (
          <div className="mt-1 flex items-start gap-1.5 rounded-btn bg-card/70 px-2 py-1 text-tag text-ink-2">
            <Layers size={12} className="mt-0.5 shrink-0 text-primary" />
            <span>
              {LIVE_EVENT.text}
              <span className="ml-1 text-ink-3">
                （取证额度剩 {LIVE_EVENT.round.pool_remaining}/{LIVE_ACCOUNT.pool_total} 次）
              </span>
            </span>
          </div>
        )}
      </div>
      <div className="h-1.5 w-40 overflow-hidden rounded-chip bg-line">
        <div className="h-full rounded-chip bg-primary" style={{ width: '72%' }} />
      </div>
    </div>
  )
}

/* ── P5 · 地图：降级画布 + 证据域图层（层级与投影抄 LcMap.tsx 的降级分支） ──── */

/** 证据域图层的三种"重量"：填充 / 只描边 / 只画未查全。
 *  出这三档不是凑数 —— 第一版长图里 34 个 1.4km 盘一叠加，整张图中心直接糊成一团，
 *  "能不能看清"这个前提在填充档上不成立，所以必须把更轻的画法一起摆出来比。 */
type DiscMode = 'off' | 'fill' | 'stroke' | 'gaps'

function LcCanvas({ lc, discMode = 'off' }: { lc: LivingCircleReport; discMode?: DiscMode }) {
  const discsOn = discMode !== 'off'
  const center = lc.scene.center as LngLat
  const poiSet = poiRenderSet(lc.poi.points)
  const allDiscs = evidenceDiscs(lc)
  const discs = discMode === 'gaps' ? allDiscs.filter((d) => !d.complete) : allDiscs
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${LC_CANVAS.W} ${LC_CANVAS.H}`}
        className="block w-full select-none"
        role="img"
        aria-label="生活圈等时圈画布（预览用降级投影）"
      >
        <rect x={0} y={0} width={LC_CANVAS.W} height={LC_CANVAS.H} fill="#f9faf8" />
        {[-2, -1, 0, 1, 2].map((i) => (
          <line key={`v${i}`} x1={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y1={0} x2={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y2={LC_CANVAS.H} stroke="#e7ebe7" strokeWidth={1} />
        ))}
        {[-2, -1, 0, 1, 2].map((i) => (
          <line key={`h${i}`} x1={0} y1={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} x2={LC_CANVAS.W} y2={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} stroke="#e7ebe7" strokeWidth={1} />
        ))}

        {lc.isochrones.map((z, zi) => {
          const ring = z.geojson.coordinates[0] ?? []
          const [lx, ly] = lcRightmost(center, ring)
          return (
            <g key={z.minutes}>
              <polygon points={lcPolyPts(center, ring)} fill={LC_ISO_COLORS[zi % LC_ISO_COLORS.length]?.fill} stroke={LC_ISO_COLORS[zi % LC_ISO_COLORS.length]?.stroke} strokeWidth={1.5} strokeLinejoin="round" />
              <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>{z.minutes} min</text>
            </g>
          )
        })}

        {/* P5 新增层：逐锚点举证盘（画在等时圈之上、盲区与 POI 之下）。
            环走 `lcRing` 逆投影 + `lcPolyPts`，与生产 `LcMap` 降级分支同一算法（画布横纵比例不同，
            SVG 正圆会把纵向多画 ~39%，那与等时圈不是同一把尺）。 */}
        {discsOn &&
          discs.map((d, i) => (
            <polygon
              key={`${d.category}-${i}`}
              points={lcPolyPts(center, lcRing([d.anchor[0], d.anchor[1]], d.exhausted_radius_m))}
              fill={discMode === 'fill' ? lcEvidenceDiscColor(d.category) : 'none'}
              fillOpacity={0.05}
              stroke={lcEvidenceDiscColor(d.category)}
              strokeWidth={discMode === 'fill' ? 1 : 1.4}
              strokeDasharray={d.complete ? undefined : '6 4'}
              strokeOpacity={discMode === 'fill' ? 0.85 : 0.9}
            >
              <title>{evidenceDiscTitle(d)}</title>
            </polygon>
          ))}

        {lc.blindspots.map((b, bi) => {
          const spec = blindSevSpec(severityOf(b) || undefined)
          const gap = gapScoreOf(b)
          const ring = blindPolygonOf(b, 'smoothed')?.coordinates?.[0] ?? []
          const [cx, cy] = lcToPx(center, b.center[0], b.center[1])
          return (
            <g key={b.id}>
              <polygon points={lcPolyPts(center, ring)} fill="rgba(180,60,50,0.18)" stroke={spec.stroke} strokeWidth={1.2}>
                <title>{`${b.id} 缺失 ${(b.missing_facilities ?? []).join('/')}`}</title>
              </polygon>
              <circle cx={cx} cy={cy} r={5} fill={spec.dot} stroke="#fff" strokeWidth={1.5} />
              {gap != null && (
                <text x={cx + 8} y={cy - 8} fontSize={10} fill="#3a2c00" fontWeight={600}>#{bi + 1}·{spec.label}</text>
              )}
            </g>
          )
        })}

        {heatSamplePoints(lc, 300).map((sp) => {
          const [hx, hy] = lcToPx(center, sp.lng, sp.lat)
          return <circle key={`heat-${sp.idx}`} cx={hx} cy={hy} r={2.6} fill={minuteHeatColor(sp.minutes)} opacity={0.55} />
        })}

        {lcSnapshotPoiLayer(center, poiSet.reps, Number.POSITIVE_INFINITY, poiSet.counts).map((p) => (
          <circle key={p.key} cx={p.cx} cy={p.cy} r={5} fill={p.fill} stroke="#fff" strokeWidth={1.2} opacity={0.92} />
        ))}

        {(() => {
          const [x, y] = lcToPx(center, center[0], center[1])
          return (
            <g>
              <circle cx={x} cy={y} r={14} fill="rgba(124,152,133,0.18)" stroke="#5F7B69" strokeWidth={1.5} strokeDasharray="3 3" />
              <circle cx={x} cy={y} r={6} fill="#5F7B69" stroke="#fff" strokeWidth={2} />
              <text x={x} y={y - 20} fontSize={12} fill="#3f5042" textAnchor="middle" fontWeight={600}>{lc.scene.name}</text>
              {discsOn && (
                <text x={x + 20} y={y + 4} fontSize={11} fill="#8a6420" fontWeight={600}>分析中心本身也查过一轮</text>
              )}
            </g>
          )
        })()}
      </svg>

      {/* 图例（抄 LifeCirclePage.tsx:646-670） */}
      <div className="absolute left-3 top-3 flex max-w-[190px] flex-col gap-1.5 rounded-btn border border-line bg-card/90 p-3 backdrop-blur">
        <span className="text-tag font-medium text-ink-2">图层</span>
        {['market', 'pharmacy', 'primary'].map((k) => (
          <span key={k} className="flex items-center gap-1.5 text-tag text-ink-3">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: lcEvidenceDiscColor(k) }} />
            {lcEvidenceCategoryLabel(k)}
          </span>
        ))}
        <span className="mt-1 flex items-center gap-1.5 border-t border-line/70 pt-1.5 text-tag text-ink-3">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: 'linear-gradient(135deg,#8fbfa2,#2c5a3f)' }} />
          采样点耗时热力（0→20min）
        </span>
        {LC_BLIND_SEV_ORDER.map((sev) => {
          const n = lc.blindspots.filter((b) => severityOf(b) === sev).length
          const spec = LC_BLIND_SEV[sev]
          return (
            <span key={sev} className="flex items-center gap-1.5 text-tag text-ink-3">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: spec.dot }} />
              {spec.label}盲区 {n}
            </span>
          )
        })}
        {allDiscs.length > 0 && (
          <div className="mt-1 flex items-start gap-1.5 border-t border-line/70 pt-1.5 text-tag font-medium text-ink-2">
            <span
              className={`mt-0.5 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-sm border ${
                discsOn ? 'border-primary bg-primary text-[9px] leading-none text-white' : 'border-line bg-card'
              }`}
            >
              {discsOn ? '✓' : ''}
            </span>
            <span>
              证据域（查到哪儿）
              <span className="mt-0.5 block font-normal text-ink-3">
                {discsOn ? `${discs.length} 盘 · 实线查全 / 虚线截断` : `${allDiscs.length} 盘可看 · 未勾选`}
              </span>
            </span>
          </div>
        )}
      </div>

      <div className="absolute right-2 top-2 flex flex-col items-end gap-1">
        <div className="rounded-chip border border-warn/50 bg-warn/10 px-2.5 py-1 text-tag font-medium text-ink-2">
          地图降级 · 静态画布（预览用同一投影）
        </div>
        {poiThinNote(poiSet) && (
          <div className="rounded-md border border-ink/10 bg-white/95 px-2 py-1 text-tag font-medium text-ink-3 shadow-sm">
            {poiThinNote(poiSet)}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── P3 · 取证回合小节 ─────────────────────────────────────────────────── */

function RoundSummary({ account }: { account: ForensicAccount }) {
  return (
    <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-aux font-semibold text-ink">
        <Layers size={15} className="text-primary" /> 取证回合
        <span className="text-tag font-normal text-ink-3">
          判盲共 {account.judging_passes} 趟 · 扩容 {account.rounds} 轮（上限 {account.max_rounds}）· 终点 {account.stop_reason ?? '—'}
        </span>
      </div>
      <table className="w-full border-collapse text-tag">
        <thead>
          <tr className="border-b border-line text-left text-ink-3">
            <th className="py-1 pr-2 font-medium">趟次</th>
            <th className="py-1 pr-2 font-medium">派发</th>
            <th className="py-1 pr-2 font-medium">调用</th>
            <th className="py-1 pr-2 font-medium">锚点 计划→派发→用</th>
            <th className="py-1 pr-2 font-medium">未跑 / 砍掉</th>
            <th className="py-1 pr-2 font-medium">未决格</th>
            <th className="py-1 font-medium">收手原因</th>
          </tr>
        </thead>
        <tbody>
          {account.rounds_detail.map((r) => (
            <tr key={r.pass_no} className="border-b border-line/60 last:border-0">
              <td className="py-1 pr-2 text-ink">第 {r.pass_no} 趟</td>
              <td className="py-1 pr-2">{r.dispatched ? '已派发' : '未派发'}</td>
              <td className="py-1 pr-2">{r.calls}</td>
              <td className="py-1 pr-2">{roundAnchorCell(r)}</td>
              <td className="py-1 pr-2">
                {roundDroppedCell(r)}
                {r.starved_terms ? <span className="ml-1 font-medium text-warn">饿词 {r.starved_terms}</span> : null}
              </td>
              <td className="py-1 pr-2">
                {r.cells_undecided_after == null
                  ? `${r.cells_undecided_before} →（本趟之后没再判）`
                  : `${r.cells_undecided_before} → ${r.cells_undecided_after}`}
              </td>
              <td className="py-1 text-ink-2">{r.stopped_by ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 border-t border-line/60 pt-2 text-tag text-ink-3">
        取证额度 {account.pool_used}/{account.pool_total} 次 · 补算回来的点位 {account.points_added_judging_only} 个
        <span className="ml-1.5 rounded-chip bg-warn/10 px-1.5 py-0.5 font-medium text-warn">只进判盲，不进评分</span>
      </p>
      <p className="mt-1 flex items-start gap-1 text-tag text-ink-3">
        <Info size={12} className="mt-0.5 shrink-0" />
        {account.points_policy}
      </p>
    </div>
  )
}

/* ── P4 · partial 横幅（措辞与色阶都走生产出口 `partialBanner()`，探针不自己拼句子） ── */

function PartialBanner({ lc }: { lc: LivingCircleReport }) {
  const b = partialBanner(lc)
  if (!b) return null
  return (
    <div className="mt-3 flex items-start gap-2 rounded-card border border-warn/60 bg-warn/10 px-4 py-3" role="status">
      <TriangleAlert size={15} className="mt-0.5 shrink-0 text-warn" />
      <div className="min-w-0 text-tag text-ink-2">
        <div className="text-aux font-semibold text-ink">{b.title}</div>
        {b.body && <div className="mt-0.5">{b.body}</div>}
      </div>
    </div>
  )
}

/* ── 报告首屏（P2 chip / P3 小节 / P4 横幅各自落在这屏的不同位置） ─────────── */

function ReportScreen({ lc, tier }: { lc: LivingCircleReport; tier: 'now' | 'jia' | 'yi' }) {
  const account = forensicAccount(lc)
  const reach = samplingReach(lc)
  const area15 = lc.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0
  const origin = dataOriginBadge(lc)
  const cov = blindspotCoverageNote(lc)
  const badge = confidenceBadgeLabel(lc)
  const discs = evidenceDiscs(lc)
  const show = tier !== 'now'
  const stale = staleCaliberNotice(lc)
  return (
    <div className="overflow-hidden rounded-card border border-line bg-bg">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-card/95 px-4 py-2.5">
        <span className="truncate text-aux font-semibold text-ink">{lc.scene.name} · 生活圈体检报告</span>
        <Chip>体检单</Chip>
        <span
          title={origin.detail}
          className={`rounded-chip px-2 py-0.5 text-tag font-medium ${
            origin.tone === 'live' || origin.tone === 'info' ? 'bg-ok/10 text-primary-deep' : 'border border-warn/60 bg-warn/10 text-ink-2'
          }`}
        >
          {origin.label}
        </span>
        {tier === 'yi' && account && (
          <Chip title={account.points_policy} tone="warn">取证 {account.rounds} 轮 · {account.calls} 次调用</Chip>
        )}
        {tier === 'yi' && (
          <Chip title="逐锚点举证盘的个数：虚线边界那一圈没查全" tone="warn">证据域 {discs.length} 盘</Chip>
        )}
        <span className="ml-auto flex items-center gap-3 text-tag text-ink-2">
          <span>15min 圈 {area15.toFixed(2)} km²</span>
          <span>盲区 {lc.blindspots.length} 处</span>
        </span>
      </header>

      <div className="p-4">
        {show && <PartialBanner lc={lc} />}

        <div className={`mt-3 rounded-card border border-line bg-card p-4 shadow-card ${tier === 'yi' ? 'fcp-change' : ''}`}>
          {tier === 'yi' && <span className="badge">P2</span>}
          <div className="mb-1 text-aux font-semibold text-ink">必备设施三要素（1km）</div>
          <div className="flex flex-wrap gap-2 py-2">
            {triadRows(lc).map((t) => (
              <span key={t.facility} className={`inline-flex items-center gap-1.5 rounded-chip px-2.5 py-1 text-tag font-medium ${t.covered ? 'bg-ok/10 text-primary-deep' : 'bg-warn/10 text-ink-2'}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${t.covered ? 'bg-ok' : 'bg-warn'}`} />
                {t.facility} · {t.covered ? `最近 ${t.nearest_minutes}min` : '1km 内缺失'}
              </span>
            ))}
          </div>
          <VStatLine label="POI 采集" value={poiMetricLabel(lc)} />
          {poiConservationNote(lc) && <p className="mt-1 text-tag text-risk">{poiConservationNote(lc)}</p>}
          <VStatLine label="采样点" value={`${reach.total} 个（≤${reach.reachFullMin} 分钟内可达 ${reach.inReach}）`} />
          <VStatLine label="15min 等时圈面积" value={`${area15.toFixed(2)} km²`} />
          <VStatLine label="服务盲区" value={`${lc.blindspots.length} 处`} />
        </div>

        <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
          <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
            <TriangleAlert size={15} className="text-warn" /> 服务盲区清单（{lc.blindspots.length}）
          </div>
          <p className="text-tag text-ink-3">{emptyBlindspotNote(lc)}</p>
          {cov && (
            <p className={`mt-2 border-t border-line/60 pt-2 text-tag ${badge ? 'font-medium text-warn' : 'text-ink-3'}`}>
              {cov}
              {badge && <span className="ml-1.5 rounded-chip bg-warn/10 px-1.5 py-0.5">{badge}</span>}
            </p>
          )}
          {stale && <p className="mt-2 text-tag font-medium text-warn">{stale}</p>}
        </div>

        {show && account && (
          <div className="fcp-change">
            <span className="badge">P3</span>
            <RoundSummary account={account} />
          </div>
        )}
        {show && lc.partial && (
          <div className="fcp-change">
            <span className="badge">P4</span>
            <PartialBanner lc={lc} />
            <p className="mt-1 text-tag text-ink-3">↑ 同一句话在报告里只该出现一次；上面首屏那处与本处落地时二选一（本图两处都画出来给你比位置）</p>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 一屏 = 进度区 + 地图 + 报告首屏 ─────────────────────────────────────── */

function Screen({ tier, title, note }: { tier: 'now' | 'jia' | 'yi'; title: string; note: string }) {
  const live = tier !== 'now'
  return (
    <section className="mb-10">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="font-serif text-h2 text-ink">{title}</h2>
        <p className="text-tag text-ink-3">{note}</p>
      </div>

      {tier === 'yi' ? (
        <div className="fcp-change">
          <span className="badge">P1</span>
          <ProgressBanner withRound />
        </div>
      ) : (
        <ProgressBanner withRound={false} />
      )}

      <div className={`mt-4 overflow-hidden rounded-card border border-line shadow-card ${live ? 'fcp-change' : ''}`}>
        {live && <span className="badge">P5</span>}
        {/* 画法必须与生产一致：用户拍的是**重量甲 = 只描边**（`LcMap` 两个分支都 `fillOpacity:0` /
            `fill="none"`）。这里此前写的是 `'fill'` ⇒ 预览比"落地的事"更早，重出图时会看见一个
            生产根本不会出现的色块。 */}
        <LcCanvas lc={LIVE} discMode={live ? 'stroke' : 'off'} />
      </div>

      <div className="mt-4">
        <ReportScreen lc={LIVE} tier={tier} />
      </div>
    </section>
  )
}

/** 附：两种终态对照 —— 首轮就查全（没有回合、没有 partial）与额度不足（本片主场景） */
function TerminalStates() {
  return (
    <section className="mb-10">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="font-serif text-h2 text-ink">附 · 两种终态各自长什么样</h2>
        <p className="text-tag text-ink-3">左：首轮就查全（`rounds: 0`、无 partial、三块都在）｜右：额度不够铺完（本片主场景）</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ReportScreen lc={CLEAN} tier="jia" />
        <ReportScreen lc={LIVE} tier="jia" />
      </div>
    </section>
  )
}

/** 单独一屏（`?view=disc`）· 证据域图层四种画法**同宽竖排**，逐张比。
 *
 * 为什么要单独出这一屏：附二那排是三列缩略，宽度只有整屏的 1/3 —— 用户回「渲染预览看看区别」
 * 要的不是"再给一张图"，而是**在真实尺寸上比**。同一批 34 个盘、同一投影、同一比例，只换画法。 */
function DiscStack() {
  const all = evidenceDiscs(LIVE)
  const gaps = all.filter((d) => !d.complete).length
  const variants: { mode: DiscMode; title: string; read: string; lose: string }[] = [
    {
      mode: 'off',
      title: '基准 · 不画（今天的样子）',
      read: '等时圈五级色阶、采样热力、POI 点位都清楚',
      lose: '「这格为什么判不了」只剩体检单里那句灰字，图面上没有任何证据边界可指',
    },
    {
      mode: 'stroke',
      title: '重量甲 · 只描边不填充',
      read: '每个锚点一圈、虚线=那一圈没查全；五级色阶在中心仍可辨，「分析中心也查过一轮」看得见',
      lose: '34 条弧线在证据域里织成网（本场景全部未查全 ⇒ 全虚线），外圈那些格被切过好几道；也看不出"哪些格被至少一个盘盖住"',
    },
    {
      mode: 'fill',
      title: '重量乙 · 填充 + 描边',
      read: '能看出被证据覆盖到的整片区域（= 判得了的地方）',
      lose: '34 层 5% 填充叠起来 ⇒ **整个证据域一带连片变紫褐**（不止中心），等时圈只剩最外一圈轮廓、POI 点被压住',
    },
    {
      mode: 'gaps',
      title: `重量丙 · 只画未查全的盘（本场景 ${gaps}/${all.length}）`,
      read: '真接口里若多数类查全，图面会明显干净，且留下的正是"缺口"这一件要解释的事',
      lose: '这份桩数据上 34 盘全部未查全 ⇒ **一个都没省掉**，与重量甲此刻逐像素相同；正面证据（这里确实查干净了）也没了',
    },
  ]
  return (
    <div className="wrap">
      <section>
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="font-serif text-h2 text-ink">证据域图层：四种画法同宽竖排</h2>
          <p className="text-tag text-ink-3">同一份报告（凯里桩 · 1 个取证回合 · 34 个举证盘）、同一投影同一比例，只换画法</p>
        </div>
        {variants.map((v) => (
          <div key={v.mode} className="mb-8">
            <div className="mb-2 rounded-card border border-line bg-card px-4 py-2.5 shadow-card">
              <div className="text-aux font-semibold text-ink">{v.title}</div>
              <p className="mt-0.5 text-tag text-ink-3">看得清：{v.read}</p>
              <p className="mt-0.5 text-tag text-warn">代价：{v.lose}</p>
            </div>
            <div className="overflow-hidden rounded-card border border-line shadow-card">
              <LcCanvas lc={LIVE} discMode={v.mode} />
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}

/** 附二 · 证据域图层的三种重量（同一批 34 个盘、同一投影、同一比例，只换画法）。
 *
 * ⚠️ 档位名与 `DiscStack`、与用户拍板**同一套**：甲=只描边、乙=填充+描边、丙=只画未查全。
 * 早先这里把"甲"标成了填充（那是拍板前的临时编号），而用户对"甲"下的令是「按甲落 LcMap.tsx」——
 * 两份名字表指同一个字却给相反的意思，比不写名字更容易出事。 */
function DiscVariants() {
  const all = evidenceDiscs(LIVE)
  const gaps = all.filter((d) => !d.complete).length
  const variants: { mode: DiscMode; title: string; note: string }[] = [
    { mode: 'stroke', title: '重量甲 · 只描边不填充（**已落地这一档**）', note: '盘的边界还在（虚线=没查全），底图与等时圈颜色不受叠加影响' },
    { mode: 'fill', title: '重量乙 · 填充 + 描边', note: '34 层 5% 填充叠起来 ⇒ 整个证据域一带连片变色，等时圈色阶与热力点都被吃掉' },
    { mode: 'gaps', title: '重量丙 · 只画未查全的盘', note: `本场景 ${all.length} 盘里 ${gaps} 个未查全 ⇒ 这条筛法在这份数据上一个都没省掉，只有真接口里"部分类查全"时才有差别` },
  ]
  return (
    <section className="mb-10">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="font-serif text-h2 text-ink">附二 · 证据域图层要画多重</h2>
        <p className="text-tag text-ink-3">同一批盘、同一投影、同一比例，只换画法 —— 三张图同宽可直接比</p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {variants.map((v) => (
          <div key={v.mode} className="overflow-hidden rounded-card border border-line bg-card shadow-card">
            <div className="border-b border-line px-3 py-2">
              <div className="text-aux font-semibold text-ink">{v.title}</div>
              <p className="mt-0.5 text-tag text-ink-3">{v.note}</p>
            </div>
            <LcCanvas lc={LIVE} discMode={v.mode} />
          </div>
        ))}
      </div>
    </section>
  )
}

function Legend() {
  return (
    <div className="fcp-legend">
      <div className="legend-title">改动区图例（P1–P5）· 与页内徽标同源</div>
      <ol>
        {REGIONS.map((r) => (
          <li key={r.id}>
            <b>{r.id} {r.label}</b> <span className="opacity-70">（{r.tiers}）</span>
            <div>现状：{r.now}</div>
            <div>改成：{r.target}</div>
            <div className="opacity-80">换来：{r.effect}</div>
          </li>
        ))}
      </ol>
      <div className="legend-foot">
        数据出处：<code>{scenes._meta.source}</code> —— 生产编排 <code>live_forensic_steps</code> + <code>assemble_living_circle</code> 现场装配，
        <b>零真实百度调用</b>；<code>caliber.forensic / evidence_anchors / partial</code> 的键名与线上逐字一致，POI 名称与坐标为桩产物。
        判盲口径升级前冻结的旧快照没有 <code>caliber.forensic</code> ⇒ P3 小节整块不渲染（不会回落成「0 轮」）。
        partial 文案与 <code>degradeBanner()</code> 的「已降级为离线估算」不同句：那份是事故，这份是按计划只打了这么多。
      </div>
    </div>
  )
}

function App() {
  const view = new URLSearchParams(window.location.search).get('view') ?? 'cmp'
  if (view === 'now')
    return <div className="wrap"><Screen tier="now" title="现状" note="今天用户能看到的全部" /></div>
  if (view === 'jia')
    return <div className="wrap"><Screen tier="jia" title="档甲 · 只常驻" note="报告里三件都有；进度区不动" /><TerminalStates /><Legend /></div>
  if (view === 'yi')
    return <div className="wrap"><Screen tier="yi" title="档乙 · 常驻 + 实时" note="甲的全部，再加实时一行与两颗 chip" /><TerminalStates /><Legend /></div>
  if (view === 'disc') return <DiscStack />
  return (
    <div className="wrap">
      <Screen tier="now" title="① 现状" note="`round` 事件被丢弃；forensic / evidence_anchors / partial 三块一个都不显示" />
      <Screen tier="jia" title="② 档甲 · 只常驻" note="报告里补齐三件；体检进行中那 10 秒仍只有进度条" />
      <Screen tier="yi" title="③ 档乙 · 常驻 + 实时" note="推荐：再加实时一行与两颗 chip，`round` 从此有真消费者" />
      <TerminalStates />
      <DiscVariants />
      <Legend />
    </div>
  )
}

const host = document.getElementById('lc-p5-root')
if (host) createRoot(host).render(<App />)
