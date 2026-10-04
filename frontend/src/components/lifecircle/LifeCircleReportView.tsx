/**
 * 常青圈 · 生活圈体检报告双层视图（F3 · A1 渲染适配器的 living_circle 分支）。
 *
 * 结构（D3 同页上下 + 锚点）：
 *   ① 顶层体检单（sticky 摘要条 + 首屏整单）—— 地图快照 / 总评分 / 雷达 / 三要素 / 盲区清单
 *   ② 下层完整章节报告 —— 医疗/教育/购物/养老/可达性/盲区/结论逐章（专家署名 + 图表 + 溯源）
 *
 * M 阶段 BMapGL 接入后仅替换快照渲染层，页面骨架不变。
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { VStatLine } from '../ui'
import {
  ChevronLeft,
  MapPin,
  Timer,
  TriangleAlert,
  Radar,
  Users,
  ArrowDown,
  GitCompare,
  Database,
  Sparkles,
  Share2,
  Plus,
  Layers,
  Info as InfoIcon,
} from 'lucide-react'
import type { Report, LivingCircleReport, LngLat, BlindSpot, ForensicAccount } from '../../types'
import {
  LC_CANVAS,
  LC_CAT_COLOR,
  LC_CAT_LABEL_OF,
  LC_ISO_COLORS,
  LC_BLIND_SEV,
  LC_BLIND_FIX_STRATEGY,
  affectedOf,
  fixesOf,
  footprintMetaOf,
  gapScoreOf,
  judgeRulerM,
  LC_JUDGE_SCALE_COLOR,
  severityOf,
  lcPolyPts,
  lcRightmost,
  lcToPx,
  lcSnapshotPoiLayer,
  scoreGrade,
  dataOriginBadge,
  blindspotCoverageNote,
  confidenceBadgeLabel,
  staleCaliberNotices,
  emptyBlindspotNote,
  samplingReach,
  poiConservationNote,
  poiMetricLabel,
  poiRenderSet,
  degradeBanner,
  forensicAccount,
  evidenceDiscs,
  partialBanner,
  roundAnchorCell,
  roundDroppedCell,
} from '../../lib/livingCircle'
import { tocLinkCls } from '../../lib/reportLayout'
import { MiniRadar } from './MiniRadar'
import { CategoryCaliberNotes } from './CategoryCaliberNotes'
import ShareModal from './ShareModal'
import { VChart } from '../VChart'
import { VDataGrid } from '../VDataGrid'
import { useExpertStore } from '../../store/expertStore'

/* ── 地图快照（静态投影，非交互） ─────────────────────────── */
function IsochroneSnapshot({ lc, shared = false }: { lc: LivingCircleReport; shared?: boolean }) {
  const { W, H } = LC_CANVAS
  const center: LngLat = lc.scene.center
  const isoZones = lc.isochrones
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full select-none" role="img" aria-label="等时圈快照">
      <rect x={0} y={0} width={W} height={H} fill="#f9faf8" />
      {[-2, -1, 0, 1, 2].map((i) => (
        <line key={`v${i}`} x1={W / 2 + (i * W) / 5} y1={0} x2={W / 2 + (i * W) / 5} y2={H} stroke="#e7ebe7" strokeWidth={1} />
      ))}
      {[-2, -1, 0, 1, 2].map((i) => (
        <line key={`h${i}`} x1={0} y1={H / 2 + (i * H) / 5} x2={W} y2={H / 2 + (i * H) / 5} stroke="#e7ebe7" strokeWidth={1} />
      ))}
      {[...isoZones].sort((a, b) => b.minutes - a.minutes).map((z) => {
        const color = LC_ISO_COLORS[isoZones.findIndex((x) => x.minutes === z.minutes)] ?? LC_ISO_COLORS[0]
        const ring = z.geojson.coordinates[0]
        const [lx, ly] = lcRightmost(center, ring)
        return (
          <g key={z.minutes}>
            <polygon points={lcPolyPts(center, ring)} fill={color.fill} stroke={color.stroke} strokeWidth={1.5} strokeLinejoin="round" />
            <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>
              {z.minutes} min
            </text>
          </g>
        )
      })}
      {lc.blindspots.map((b) => (
        <g key={b.id}>
          {shared ? (
            /* 分享脱敏（口径 ③-A）：不绘精确多边形，只画概略片区（面积等价圆，缺 meta 时用判定格距近似） */
            <BlindCoarseCircle lc={lc} b={b} />
          ) : (
            <polygon points={lcPolyPts(center, b.polygon.coordinates[0])} fill="rgba(120,120,120,0.16)" stroke="#8a8a8a" strokeWidth={1} strokeDasharray="5 4" />
          )}
          <circle cx={lcToPx(center, b.center[0], b.center[1])[0]} cy={lcToPx(center, b.center[0], b.center[1])[1]} r={5} fill="#E8B54D" stroke="#fff" strokeWidth={1.5} />
        </g>
      ))}
      {/* POI 真实点位：共享投影层（与 LcMap 降级画布同口径，点位与详细报告数字一致）；
          离线（poi.points 恒为空）时自然降级为空数组，不绘制。
          阶段 2.1/2.2：**不再传 cap** —— 报告给几个点就画几个点（旧默认 120 是渲染侧
          静默第二权威）。取数走 `poiRenderSet()` 与 LcMap live 路径同一份 `reps`。 */}
      {(() => {
        const set = poiRenderSet(lc.poi.points)
        return lcSnapshotPoiLayer(center, set.reps, Number.POSITIVE_INFINITY, set.counts).map((p) => (
          <circle key={p.key} cx={p.cx} cy={p.cy} r={6} fill={p.fill} stroke="#fff" strokeWidth={1.5} opacity={0.92}>
            {p.title && <title>{p.cluster > 1 ? `${p.title}（该网格聚合 ${p.cluster} 点）` : p.title}</title>}
          </circle>
        ))
      })()}
      {(() => {
        const [x, y] = lcToPx(center, center[0], center[1])
        return (
          <g>
            <circle cx={x} cy={y} r={14} fill="rgba(124,152,133,0.18)" stroke="#5F7B69" strokeWidth={1.5} strokeDasharray="3 3" />
            <circle cx={x} cy={y} r={6} fill="#5F7B69" stroke="#fff" strokeWidth={2} />
            <text x={x} y={y - 20} fontSize={12} fill="#3f5042" textAnchor="middle" fontWeight={600}>
              {lc.scene.name}
            </text>
          </g>
        )
      })()}
    </svg>
  )
}

/** 分享脱敏的概略片区（口径 ③-A）：不暴露精确多边形的逐格边界，只画「面积等价圆」+ 概略面积。
 *  缺 footprint_meta 时退化为判定格距近似圆。
 *
 *  C3：旁边再画一枚**判定尺**参考圈（半径 = 本次判定实际吃的那把尺）。不画它的代价是真实的：
 *  读者会把这枚灰色椭圆当成"判定范围"，于是"圈里看着空"又被读成"这里该判盲" —— 而它只是
 *  把 8 个格子的面积折算成等面积圆，跟"多大范围内找设施"没有关系。
 *  两枚都用同一组 px 比例换算（概览画布 x/y 比例不同 ⇒ 都是椭圆，不是圆），否则两者不可比。 */
function BlindCoarseCircle({ lc, b }: { lc: LivingCircleReport; b: BlindSpot }) {
  const { W, H, R } = LC_CANVAS
  const pxPerMx = (W / 2) / R
  const pxPerMy = (H / 2) / R
  const [cx, cy] = lcToPx(lc.scene.center, b.center[0], b.center[1])
  const fm = footprintMetaOf(b)
  const gridM = fm?.grid_m ?? 200
  const area = fm?.area_m2 ?? Math.PI * gridM * gridM
  const r = area > 0 ? Math.sqrt(area / Math.PI) : gridM
  const rx = Math.max(r * pxPerMx, 6)
  const ry = Math.max(r * pxPerMy, 6)
  const label = fm?.area_m2 != null ? `概略 ${(fm.area_m2 / 1e4).toFixed(1)}公顷（面积当量）` : '概略片区'
  const rulerM = judgeRulerM(lc)
  const srx = rulerM === null ? 0 : Math.max(rulerM * pxPerMx, 4)
  const sry = rulerM === null ? 0 : Math.max(rulerM * pxPerMy, 4)
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="rgba(120,120,120,0.10)" stroke="#8a8a8a" strokeWidth={1} strokeDasharray="4 3" />
      <text x={cx} y={cy - ry - 4} fontSize={10} fill="#8a8a8a" textAnchor="middle">
        {label}
      </text>
      {rulerM !== null && (
        <>
          <ellipse cx={cx} cy={cy} rx={srx} ry={sry} fill="none" stroke={LC_JUDGE_SCALE_COLOR} strokeWidth={1.4} strokeDasharray="6 4" />
          <text x={cx} y={cy + Math.max(ry, sry) + 10} fontSize={10} fill={LC_JUDGE_SCALE_COLOR} textAnchor="middle">
            {`判定尺 ${Math.round(rulerM)}m`}
          </text>
        </>
      )}
    </g>
  )
}

/** 分享报告页级水印：出处 + 生成日期，半透明、斜排铺满、不拦截交互（share=1 触发）。 */
function ShareWatermark({ lc }: { lc: LivingCircleReport }) {
  const source = lc.scene?.name || '生活圈'
  const originLabel: Record<string, string> = {
    live: '真实路网测时',
    offline: '离线估算',
    fixture_sample: '演示数据',
  }
  const gen = lc.generated_at ? new Date(lc.generated_at) : null
  const dateStr =
    gen && !Number.isNaN(gen.getTime())
      ? `${gen.getFullYear()}-${String(gen.getMonth() + 1).padStart(2, '0')}-${String(gen.getDate()).padStart(2, '0')}`
      : ''
  const line = `常青圈 · 生活圈体检 · 出处：${source}（${originLabel[lc.data_origin] ?? lc.data_origin}）${dateStr ? ` · 生成：${dateStr}` : ''}`
  return (
    <div className="pointer-events-none fixed inset-0 z-40 overflow-hidden" aria-hidden="true">
      <div className="grid h-full grid-cols-3 gap-x-16 gap-y-10 p-10 opacity-[0.08]">
        {Array.from({ length: 15 }).map((_, i) => (
          <div key={i} className="-rotate-12 truncate whitespace-nowrap text-sm font-semibold text-ink">
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}

/** 章节锚点跳转（sticky 摘要条内） */
function jumpToSection(id: string) {
  document.getElementById(`lc-sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 部分完成横幅（片 5）。与 `degradeBanner` 的 risk 色**分开**：
 *  降级说「这份换成了离线骨架」，这里说「仍是实时口径，只是有格没判出」。
 *  措辞一律走 `lib/livingCircle.partialBanner()` 一处，页面不自己拼句子。 */
function PartialNote({ lc }: { lc: LivingCircleReport }) {
  const b = partialBanner(lc)
  if (!b) return null
  return (
    <div className="mx-auto mt-3 flex max-w-6xl items-start gap-2 rounded-card border border-warn/60 bg-warn/10 px-4 py-3" role="status">
      <TriangleAlert size={15} className="mt-0.5 shrink-0 text-warn" />
      <div className="min-w-0 text-tag text-ink-2">
        <div className="text-aux font-semibold text-ink">{b.title}</div>
        {b.body && <div className="mt-0.5">{b.body}</div>}
      </div>
    </div>
  )
}

/** 取证回合小节（片 5）。数据只有 `caliber.forensic` 一个来源 —— 它与 `round` 事件
 *  那一份是后端同一个 `to_row()` 产的，上屏与落库无从各说各话。
 *  ⚠️ 缺 `forensic` ⇒ **整块不渲染**：离线估算与判盲口径升级前的旧快照从没走过取证，
 *  这里回落成「0 轮」就是替一次没发生的事举证。 */
function ForensicSection({ account }: { account: ForensicAccount }) {
  return (
    <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-aux font-semibold text-ink">
        <Layers size={15} className="text-primary" /> 取证回合
        <span className="text-tag font-normal text-ink-3">
          判盲共 {account.judging_passes} 趟 · 扩容 {account.rounds} 轮（上限 {account.max_rounds}）· 终点
          {account.stop_reason ?? '—'}
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
                {r.starved_terms > 0 && (
                  <span className="ml-1 font-medium text-warn" title="被额度拒绝、一次都没发的检索词">
                    饿词 {r.starved_terms}
                  </span>
                )}
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
        <InfoIcon size={12} className="mt-0.5 shrink-0" />
        {account.points_policy}
      </p>
    </div>
  )
}

/** 覆盖度脚注：只要存在未判定格，就必须写出来（否则盲区数会被读成「全貌」）。
 *
 * ⚠️ 判定与文案都来自 `lib/livingCircle`（体检台共用同一实现）——本组件不再自带一份，
 * 否则两处披露文案会各自漂移（旧版正是如此：报告页写了、体检台没写）。
 *
 * rev2 · D-3：证据不足时综合评分已按判定覆盖率打折 ⇒ 该脚注从灰字升为 warn 色并挂降档
 * 徽标。灰字只说「判了多少格」，读者仍会把「0 处盲区」当结论；徽标说的是「所以这个数
 * 偏乐观」。旧口径快照没有 `scores.confidence` ⇒ 徽标不出现（不猜成 full），脚注照旧。 */
function coverageNote(lc: LivingCircleReport) {
  const note = blindspotCoverageNote(lc)
  if (!note) return null
  const badge = confidenceBadgeLabel(lc)
  return (
    <p className={`mt-2 border-t border-line/60 pt-2 text-tag ${badge ? 'font-medium text-warn' : 'text-ink-3'}`}>
      {note}
      {badge && <span className="ml-1.5 rounded-chip bg-warn/10 px-1.5 py-0.5">{badge}</span>}
    </p>
  )
}

/** 口径陈旧提示（D-4）：口径升级前冻结的报告仍是用户的历史（不隐藏），但必须说明它偏乐观。
 *  与 `coverageNote` 分开的理由：后者只在存在未判定格时出现，而「尺子换过了」与当次覆盖率无关。
 *  ⚠️ 两轴各一句（判盲 `ev-*` / 评分 `cov-*`）：**哪句该出现**由 `staleCaliberNotices` 判，
 *  这里只渲清单 —— 页面各写一遍判据正是两页文案漂移的形态（旧版报告页写了、体检台没写）。 */
function caliberNote(lc: LivingCircleReport) {
  const notes = staleCaliberNotices(lc)
  if (!notes.length) return null
  return (
    <>
      {notes.map((n) => (
        <p key={n} className="mt-2 text-tag font-medium text-warn">
          {n}
        </p>
      ))}
    </>
  )
}

export default function LifeCircleReportView({ report }: { report: Report }) {
  const navigate = useNavigate()
  const [shareOpen, setShareOpen] = useState(false)
  const resolveExpert = useExpertStore((s) => s.resolve)
  const lc = report.living_circle as LivingCircleReport
  const grade = scoreGrade(lc.scores.total)
  // 报告 id 形如 lc-{sceneId}，反推样区路由参数（如 lc-kaili → kaili）
  const sceneKey = report.id.startsWith('lc-') ? report.id.slice(3) : 'kaili'
  // 采纳分档走唯一口径（lib/livingCircle.samplingReach）：timed≠可达，
  // 旧写法 `.filter(p => p.reachable)` 会把 1049 个点全说成「可达」（实际仅 inReach 个）
  const reach = samplingReach(lc)
  // R-7：降级披露唯一出口（存在 `degraded` 才是「被熔断」，否则只是未联网离线估算）
  const dgBanner = degradeBanner(lc)
  // 片 5：取证账目与证据域明细（两者都**不传不发** ⇒ 取不到就是 null / 空表，不回落 0）
  const forensic = forensicAccount(lc)
  const discs = evidenceDiscs(lc)
  const area15 = lc.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0
  const isShared = typeof window !== 'undefined' && window.location.search.includes('share=1')
  // C1：左竖排章节导航的当前高亮（scroll-spy，与 research 报告页同模式）
  const [activeSection, setActiveSection] = useState(report.toc[0]?.id ?? '')
  const mainRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const scroller = mainRef.current
    if (!scroller) return
    const onScroll = () => {
      let cur = ''
      for (const s of report.sections) {
        const node = document.getElementById(`lc-sec-${s.id}`)
        if (node && node.getBoundingClientRect().top - scroller.getBoundingClientRect().top <= 152) cur = s.id
      }
      if (cur) setActiveSection(cur)
    }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => scroller.removeEventListener('scroll', onScroll)
  }, [report.sections])

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg">
      {/* 顶部条：面包屑 + 数据徽标 + 右侧操作（章节导航已迁至左侧 aside） */}
      {isShared && <ShareWatermark lc={lc} />}
      <header className="z-30 shrink-0 border-b border-line bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-2.5">
          <button
            onClick={() => navigate(`/life-circle/${sceneKey}`)}
            title="返回体检地图"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-btn text-ink-2 hover:bg-primary-tint"
          >
            <ChevronLeft size={18} />
          </button>
          <div className="flex min-w-0 items-center gap-2">
            <MapPin size={15} className="shrink-0 text-primary" />
            <span className="truncate text-aux font-semibold text-ink">{lc.scene.name} · 生活圈体检报告</span>
            <span className="rounded-chip bg-primary-tint px-2 py-0.5 text-tag font-medium text-primary-deep">体检单</span>
            {(() => {
              const b = dataOriginBadge(lc)
              return (
                <span
                  title={b.detail}
                  className={`hidden rounded-chip px-2 py-0.5 text-tag font-medium sm:inline ${
                    b.tone === 'live' || b.tone === 'info'
                      ? 'bg-ok/10 text-primary-deep'
                      : 'border border-warn/60 bg-warn/10 text-ink-2'
                  }`}
                >
                  {b.label}
                </span>
              )
            })()}
          </div>
          <div className="ml-auto flex items-center gap-4">
            <span className="hidden items-center gap-1 text-tag text-ink-2 md:inline-flex">
              <Timer size={13} /> 15min 圈 {area15.toFixed(2)} km²
            </span>
            <span className="hidden items-center gap-1 text-tag text-ink-2 md:inline-flex">
              <TriangleAlert size={13} className="text-warn" /> 盲区 {lc.blindspots.length} 处
            </span>
            {/* 片 5：取证摘要 chip。数字与体检单里那张回合表同源（都读 `caliber.forensic`），
                缺键时整颗不出现 —— 不给离线/旧快照凭空造一个「0 轮」。 */}
            {forensic && (
              <span
                title={forensic.points_policy}
                className="hidden items-center gap-1 rounded-chip border border-warn/60 bg-warn/10 px-2 py-0.5 text-tag font-medium text-ink-2 md:inline-flex"
              >
                <Layers size={12} /> 取证 {forensic.rounds} 轮 · {forensic.calls} 次调用
              </span>
            )}
            {discs.length > 0 && (
              <span
                title="判定真正吃的证据域逐盘明细：虚线边界那一圈没查全（图层开关见体检地图页）"
                className="hidden items-center gap-1 rounded-chip border border-warn/60 bg-warn/10 px-2 py-0.5 text-tag font-medium text-ink-2 md:inline-flex"
              >
                <InfoIcon size={12} /> 证据域 {discs.length} 盘
              </span>
            )}
            <button
              onClick={() => setShareOpen(true)}
              title="分享报告直达链接 / 二维码"
              className="inline-flex items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
            >
              <Share2 size={14} /> 分享
            </button>
            <button
              onClick={() => navigate('/compare')}
              className="inline-flex items-center gap-1.5 rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
            >
              <GitCompare size={14} /> 双样例对比
            </button>
          </div>
        </div>
      </header>

      {/* 片 5：部分完成披露（与降级横幅分职；不存在 `partial` 时整块不渲染） */}
      <PartialNote lc={lc} />

      {/* 左：竖排章节目录（scroll-spy 高亮；lg 以下隐藏，与 research 报告页一致） */}
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r border-line bg-card/50 lg:flex lg:flex-col">
          <nav aria-label="章节目录" className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
            {report.toc.map((t, i) => {
              const active = activeSection === t.id
              return (
                <button
                  key={t.id}
                  onClick={() => jumpToSection(t.id)}
                  aria-current={active ? 'page' : undefined}
                  className={tocLinkCls(active)}
                >
                  <span
                    className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-chip text-[11px] font-semibold transition-colors ${
                      active ? 'bg-primary text-white' : 'bg-line/70 text-ink-3'
                    }`}
                  >
                    {i + 1}
                  </span>
                  <span className="break-words leading-snug">{t.title}</span>
                </button>
              )
            })}
          </nav>
        </aside>

        {/* 主可滚动区：scroll-spy 监听此容器 */}
        <main ref={mainRef} className="min-h-0 flex-1 overflow-y-auto">
        {isShared && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-center gap-2 rounded-card border border-primary-soft bg-primary-tint/70 px-4 py-2 text-tag text-ink-2">
              <InfoIcon size={14} className="shrink-0 text-primary-deep" /> 分享来源 · 该报告经由直达链接访问（可扫码/复制链接传播）
            </div>
          </div>
        )}
        {lc.served_from === 'cache' && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-center gap-2 rounded-card border border-primary-soft bg-primary-tint/70 px-4 py-2 text-tag text-ink-2">
              <InfoBadge /> 历史实时结果 · 离线可查：真实百度路网测时快照（{lc.sampling.interpolation === 'idw' ? 'IDW 反距离加权插值等时圈' : '等时圈'} · 采样 {reach.total} 点，≤{reach.reachFullMin} 分钟内可达 {reach.inReach}）
            </div>
          </div>
        )}
        {lc.data_origin === 'offline' && dgBanner && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-start gap-2 rounded-card border border-risk/50 bg-risk/10 px-4 py-2 text-tag text-ink-2">
              <RiskBadge />
              <span>
                <b className="text-[#8F5E56]">{dgBanner.title}</b>
                <br />
                {dgBanner.body}
                <span className="mt-0.5 block text-ink-3">{dgBanner.action}</span>
              </span>
            </div>
          </div>
        )}
        {lc.data_origin === 'offline' && !dgBanner && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-center gap-2 rounded-card border border-warn/40 bg-warn/10 px-4 py-2 text-tag text-ink-2">
              <InfoBadge /> 离线估算 · 距离模型（未联网采集 POI）：区县中心近似 + 直线距离 × 绕行系数测时，等时圈为圆形近似——评分与盲区需实时体检后给出，不可与实时分比较
            </div>
          </div>
        )}
        {lc.data_origin === 'live' && lc.served_from !== 'cache' && (
          <div className="mx-auto mt-4 max-w-6xl px-6">
            <div className="flex items-center gap-2 rounded-card border border-primary-soft bg-primary-tint/70 px-4 py-2 text-tag text-ink-2">
              <InfoBadge /> 真实百度路网测时数据（{lc.sampling.interpolation === 'idw' ? 'IDW 反距离加权插值等时圈' : '等时圈'} · 采样 {reach.total} 点，≤{reach.reachFullMin} 分钟内可达 {reach.inReach}）
            </div>
          </div>
        )}

        {/* ① 顶层体检单（一屏） */}
        <section className="mx-auto max-w-6xl px-6 pt-5" aria-label="体检单">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
            {/* 左：地图快照 + 图例 */}
            <div className="relative overflow-hidden rounded-card border border-line bg-card shadow-card">
              <IsochroneSnapshot lc={lc} shared={isShared} />
              <div className="absolute left-3 top-3 flex max-w-[150px] flex-col gap-1 rounded-btn border border-line bg-card/90 p-2.5 backdrop-blur">
                <span className="text-tag font-medium text-ink-2">图层</span>
                {Object.entries(LC_CAT_COLOR).map(([k, v]) => (
                  <span key={k} className="flex items-center gap-1.5 text-tag text-ink-3">
                    <span className="h-2 w-2 rounded-full" style={{ background: v }} />
                    {LC_CAT_LABEL_OF(k)}
                  </span>
                ))}
              </div>
            </div>

            {/* 右：评分 + 三要素 + 汇总 */}
            <div className="flex flex-col gap-4">
              <div className="rounded-card border border-line bg-card p-4 shadow-card">
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-aux font-semibold text-ink">{lc.scene.name} · 体检单</div>
                    <div className="mt-0.5 text-tag text-ink-3">
                      {lc.scene.city} · {lc.scene.address}
                    </div>
                  </div>
                  <div className="text-right">
                    {lc.data_origin === 'offline' ? (
                      <div className="text-right">
                        <div className="text-sm font-semibold leading-none text-ink-3">评分待实时体检</div>
                        <div className="mt-1 text-tag text-ink-3">离线估算 · 距离模型，不可与实时分比较</div>
                      </div>
                    ) : (
                      <div className="text-right">
                        <div className="font-serif text-[40px] font-semibold leading-none" style={{ color: grade.color }}>
                          {lc.scores.total}
                        </div>
                        <div className="mt-1 text-tag text-ink-3">
                          综合评分 · {grade.label}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-3 border-t border-line pt-3">
                  {lc.data_origin === 'offline' ? (
                    <p className="py-6 text-center text-tag text-ink-3">分类雷达需实时体检数据</p>
                  ) : (
                    <MiniRadar report={lc} />
                  )}
                  {/* 片 1c-β C1：维度旁那句门槛项口径说明（数字与名单都来自 payload） */}
                  <CategoryCaliberNotes lc={lc} />
                </div>
              </div>

              <div className="rounded-card border border-line bg-card p-4 shadow-card">
                <div className="mb-1 text-aux font-semibold text-ink">必备设施三要素（1km）</div>
                <div className="flex flex-wrap gap-2 py-2">
                  {lc.scores.triads.map((t) => (
                    <span
                      key={t.facility}
                      className={`inline-flex items-center gap-1.5 rounded-chip px-2.5 py-1 text-tag font-medium ${
                        t.covered ? 'bg-ok/10 text-primary-deep' : 'bg-warn/10 text-ink-2'
                      }`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${t.covered ? 'bg-ok' : 'bg-warn'}`} />
                      {t.facility} · {t.covered ? `最近 ${t.nearest_minutes}min` : '1km 内缺失'}
                    </span>
                  ))}
                </div>
                {/* 阶段 2.5：三段式单一口径（见 lib/livingCircle.poiMetricLabel） */}
                <VStatLine label="POI 采集" value={poiMetricLabel(lc)} />
                {/* 阶段 1.8：历史报告的面板数/图上点数打架时如实披露 */}
                {poiConservationNote(lc) && (
                  <p className="mt-1 text-tag text-risk">{poiConservationNote(lc)}</p>
                )}
                <VStatLine label="采样点" value={`${reach.total} 个（≤${reach.reachFullMin} 分钟内可达 ${reach.inReach}）`} />
                <VStatLine label="15min 等时圈面积" value={`${area15.toFixed(2)} km²`} />
                <VStatLine label="服务盲区" value={`${lc.blindspots.length} 处`} />
              </div>
            </div>
          </div>

          {/* 盲区清单（体检单内嵌）
              空结果**不得静默消失**：0 处盲区有两种截然不同的含义——
              ① 扫过的格子都判过、三要素齐备；② 绝大多数格子因采集半径不足**判不了**。
              两者在 UI 上必须可区分，否则「0 处」会被读成「没问题」。 */}
          {lc.data_origin === 'offline' ? (
            <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
              <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
                <TriangleAlert size={15} className="text-warn" /> 服务盲区清单
              </div>
              <p className="text-tag text-ink-3">离线估算未联网采集 POI，盲区识别需实时体检后给出</p>
            </div>
          ) : lc.blindspots.length > 0 ? (
            <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
              <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
                <TriangleAlert size={15} className="text-warn" /> 服务盲区清单（{lc.blindspots.length}）
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {lc.blindspots.map((b) => {
                  const sev = severityOf(b)
                  const sevSpec = LC_BLIND_SEV[sev]
                  const gap = gapScoreOf(b)
                  const affected = affectedOf(b) as { sampling_sites?: number; estimated_residents?: number } | null
                  const fix = (fixesOf(b) as { facility: string; strategy: string; priority: number }[])[0]
                  return (
                    <div key={b.id} className="rounded-btn border border-line/70 bg-bg p-2.5">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-aux font-medium text-ink">
                          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: sevSpec?.dot ?? '#8a8a8a' }} />
                          {b.id.replace(/^bs-/, '盲区 ')}
                        </span>
                        <span className="text-tag text-ink-3">
                          {isShared ? '概略片区' : `${b.center[0].toFixed(4)},${b.center[1].toFixed(4)}`}
                        </span>
                      </div>
                      <div className="mt-1 text-tag text-ink-3">
                        缺失：{b.missing_facilities.join(' / ')}
                        {sevSpec?.label ? <> · <span style={{ color: sevSpec.stroke }}>{sevSpec.label}</span></> : ''}
                        {!isShared && gap != null ? <> · 缺口 {gap}</> : ''}
                      </div>
                      {b.nearest[0] && (
                        <div className="mt-0.5 text-tag text-ink-3">
                          最近「{b.nearest[0].name}」{Math.round(b.nearest[0].distance_m)}m·{b.nearest[0].direction}
                        </div>
                      )}
                      {b.reach?.real_walk_min != null && (
                        <div className="mt-0.5 text-tag text-ink-3">
                          最近替代步行 {b.reach.real_walk_min}min{b.reach.isochrone_based ? '（实测等时圈）' : '（估算）'}
                        </div>
                      )}
                      {affected && affected.sampling_sites != null && (
                        <div className="mt-0.5 text-tag text-ink-3">
                          受估 {affected.estimated_residents ?? '?'} 人 · 采样 {affected.sampling_sites} 点
                        </div>
                      )}
                      {(() => {
                        const fm = footprintMetaOf(b)
                        if (!fm) return null
                        return (
                          <div className="mt-0.5 text-tag text-ink-3">
                            {fm.grid}网格 {fm.grid_m}m · 边界分辨率 {fm.resolution_m}m · 覆盖 {fm.cells} 格
                            {fm.area_m2 != null ? <> · 面积 {(fm.area_m2 / 1e4).toFixed(1)} 公顷</> : ''}
                            {fm.undersampled && <span className="ml-1 font-medium text-warn">欠采样</span>}
                          </div>
                        )
                      })()}
                      {fix && (
                        <div className="mt-0.5 text-tag font-medium" style={{ color: '#1f9e63' }}>
                          <Plus size={11} className="mr-0.5 inline-block" />
                          建议补{fix.facility} · {LC_BLIND_FIX_STRATEGY[fix.strategy] ?? fix.strategy} · P{fix.priority}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
              {coverageNote(lc)}
              {caliberNote(lc)}
            </div>
          ) : (
            <div className="mt-4 rounded-card border border-line bg-card p-4 shadow-card">
              <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
                <TriangleAlert size={15} className="text-warn" /> 服务盲区清单（0）
              </div>
              <p className="text-tag text-ink-3">{emptyBlindspotNote(lc)}</p>
              {coverageNote(lc)}
              {caliberNote(lc)}
            </div>
          )}

          {/* 片 5：取证回合账目（与顶部 chip、SSE `round` 事件三处同源一份 `to_row()`） */}
          {forensic && <ForensicSection account={forensic} />}

          <div className="mt-4 flex justify-center pb-4">
            <button
              onClick={() => report.toc[0] && jumpToSection(report.toc[0].id)}
              className="inline-flex items-center gap-2 rounded-btn bg-primary px-5 h-11 font-medium text-white shadow-card hover:bg-primary-deep"
            >
              查看完整章节报告 <ArrowDown size={16} />
            </button>
          </div>
        </section>

        {/* ② 下层完整章节报告 */}
        <main className="mx-auto max-w-4xl px-6 py-8">
          <div className="mb-6 flex items-center gap-2">
            <Radar size={17} className="text-primary" />
            <h2 className="font-serif text-h2 text-ink">完整章节报告</h2>
            <span className="ml-auto flex items-center gap-1 text-tag text-ink-3">
              <Users size={13} /> {report.experts.length} 位规划专家署名
            </span>
          </div>

          <div className="space-y-10">
            {report.sections.map((sec, idx) => (
              <section key={sec.id} id={`lc-sec-${sec.id}`} className="scroll-mt-28">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-card bg-primary-tint font-serif text-[18px] font-semibold text-primary-deep">
                    {idx + 1}
                  </span>
                  <h3 className="font-serif text-h2 text-ink">{sec.title}</h3>
                </div>

                {sec.key_takeaway && (
                  <div className="mt-3 flex gap-3 rounded-card border-l-[3px] border-primary bg-primary-tint/40 p-4">
                    <Sparkles size={18} className="mt-0.5 shrink-0 text-primary-deep" />
                    <p className="text-body font-medium text-ink">{sec.key_takeaway}</p>
                  </div>
                )}

                {sec.paragraphs && sec.paragraphs.length > 0 && (
                  <div className="mt-4 space-y-3">
                    {sec.paragraphs.map((p, i) => (
                      <p key={i} className="text-body leading-relaxed text-ink-2">
                        {p}
                      </p>
                    ))}
                  </div>
                )}

                {sec.claims && sec.claims.length > 0 && (
                  <div className="mt-5 space-y-2.5">
                    {sec.claims.map((c) => (
                      <div key={c.claim_id} className="flex items-start gap-2.5 rounded-card border border-line/60 bg-card/70 p-3">
                        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-chip bg-primary-tint text-[12px] font-semibold text-primary-deep">
                          {c.author[0]}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-aux leading-relaxed text-ink">{c.text}</p>
                          {c.cross_validated && (
                            <div className="mt-1 flex items-center gap-2">
                              <span className="inline-flex items-center gap-1 rounded-chip bg-ok/10 px-1.5 py-0.5 text-tag font-medium text-ok">
                                交叉验证
                              </span>
                              <span className="rounded-chip bg-primary-tint px-1.5 py-0.5 text-tag text-primary-deep">
                                {c.author} 署名
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {sec.charts && sec.charts.length > 0 && (
                  <div className="mt-5 grid grid-cols-1 gap-4">
                    {sec.charts.map((c) => (
                      <VChart key={c.chart_id} spec={c} />
                    ))}
                  </div>
                )}

                {sec.data_grid && <div className="mt-5"><VDataGrid grid={sec.data_grid} title={`${sec.title} · 盲区明细`} /></div>}

                {/* 章节溯源 + 专家署名 */}
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line/60 pt-3">
                  {sec.source_evidence_ids && sec.source_evidence_ids.length > 0 && (
                    <span className="inline-flex items-center gap-1 text-tag text-ink-3" title={sec.source_evidence_ids.slice(0, 3).join(', ')}>
                      <Database size={13} /> 证据 {sec.source_evidence_ids.length} 条
                    </span>
                  )}
                  <span className="text-tag text-ink-3">本章署名：</span>
                  {(sec.claims ?? []).slice(0, 1).map((c) => {
                    // D4 报告里 author 存的是姓名（竞品域报告存 id），resolve 两侧都容错
                    const e = resolveExpert(c.author)
                    const role = e ? e.role_title.split(' / ')[0] || '规划专家' : '规划专家'
                    return (
                      <span key={c.claim_id} className="rounded-chip bg-bg px-2 py-0.5 text-tag text-ink-2">
                        {e?.name ?? c.author} · {role}
                      </span>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>

          {/* 术语表 + 方法论 */}
          <section className="mt-10 border-t border-line pt-6">
            <div className="text-aux font-semibold text-ink">术语表</div>
            <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {report.glossary.map((g) => (
                <div key={g.term} className="rounded-card border border-line/60 bg-card/60 p-3">
                  <div className="text-aux font-semibold text-ink">{g.term}</div>
                  <p className="mt-1 text-tag leading-relaxed text-ink-2">{g.definition}</p>
                </div>
              ))}
            </div>
            {report.methodology?.note && (
              <p className="mt-4 rounded-card border border-dashed border-line bg-bg/60 p-3 text-tag leading-relaxed text-ink-3">
                方法论：{report.methodology.note}
              </p>
            )}
          </section>
        </main>
      </main>
      </div>

      {/* E1 分享弹窗（复制直达链接 + 二维码） */}
      {shareOpen && (
        <ShareModal reportId={report.id} title={report.title ?? lc.scene.name} onClose={() => setShareOpen(false)} />
      )}
    </div>
  )
}

function InfoBadge() {
  return <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-warn/20 text-[11px] font-bold text-warn">i</span>
}

/** R-7：降级横幅的图标（q-1 选 risk —— 降级是事故不是提示，色阶需与「未联网离线」拉开） */
function RiskBadge() {
  return <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-risk/20 text-[11px] font-bold text-[#8F5E56]">!</span>
}