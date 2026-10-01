/**
 * 生活圈体检地图页（F2 核心 · 真实化升级版）。
 *
 * 渲染层：BMapGL 真实百度地图（S2 低饱和浅色底图）——等时圈/盲区 Polygon、
 * POI 真实坐标 Marker、可拖拽中心标记（LcMap 组件）；无 AK/离线自动降级静态画布。
 * 数据：mock=内置快照（M5 真实路网覆写）；真实模式=最近一次体检报告。
 *
 * 契约：src/types.ts 的 LivingCircleReport（F0 冻结 + poi.points 增量）。
 * 投影/配色与报告页快照共用 src/lib/livingCircle.ts（单一真相源）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  TriangleAlert,
  Crosshair,
  RotateCcw,
  MapPin,
  Info,
  FileText,
  Layers,
  Play,
  X,
  Navigation,
} from 'lucide-react'
import {
  SAMPLE_COMMUNITIES,
  getLifeCircleMock,
} from '../mocks/livingCircleMock'
import { LC_REPORT_ID } from '../mocks/livingCircleReports'
import { replayLivingCircleStream, LC_STAGES, stageLabel } from '../mocks/livingCircleStream'
import { fetchLifeCircleReports, fetchLifeCircleReport } from '../lib/api'
import { launchLifeCircle, subscribeLifeCircleTask } from '../lib/lifeCircleFlow'
import { useDataModeStore } from '../store/dataModeStore'
import { useTaskRegistry } from '../store/taskRegistry'
import LcMap from '../components/lifecircle/LcMap'
import CellsLedgerCard from '../components/lifecircle/CellsLedgerCard'
import RegionSelector from '../components/lifecircle/RegionSelector'
import type { LcMapHandle, LcMapMode, LcBlindSev } from '../components/lifecircle/LcMap'
import type {
  ForensicRoundRow,
  LngLat,
  LivingCircleReport,
} from '../types'
import {
  LC_CAT_COLOR,
  LC_BLIND_SEV,
  LC_BLIND_SEV_ORDER,
  LC_BLIND_FIX_STRATEGY,
  LC_FIX_DOT,
  affectedOf,
  fixPlusSvgDataUrl,
  fixesOf,
  gapScoreOf,
  blindspotCoverageBrief,
  blindspotCoverageNote,
  confidenceBadgeLabel,
  staleCaliberNotices,
  emptyBlindspotNote,
  poiConservationNote,
  poiMetricLabel,
  samplingReachLabel,
  severityOf,
  degradeBanner,
  evidenceDiscs,
  cellsLedgerOf,
  cellVerdict,
  judgeRulerLabel,
} from '../lib/livingCircle'
import { asBdLngLat } from '../lib/geo'
import type { CoordSys } from '../lib/geo'
import { MiniRadar } from '../components/lifecircle/MiniRadar'
import { CategoryCaliberNotes } from '../components/lifecircle/CategoryCaliberNotes'

/** 待提交的中心点：坐标**与坐标系标签必须同行**，否则 600m 偏差会静默进入体检。 */
interface PendingCenter {
  lnglat: LngLat
  coordSys: CoordSys
}

/**
 * 发起体检的任务入参（唯一组装产物）。
 *
 * 刻意**不含 city**：城市与本次查询无关（旧实现取「当前展示报告」的城市，是第三个来源），
 * 改由后端按中心点逆地理补全，使名称/坐标/城市三者锚定在同一中心点上。
 */
interface TaskInput {
  query: string
  center?: LngLat
  coord_sys: CoordSys
}

function StatRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    // C8：图-面板联动（悬停地图 15min 圈 → 本行高亮）。inline style 避开 tailwind 调色板守卫风险，
    // 手法与图例计数徽标的 color-mix 同款（:648 先例）。
    <div
      className="flex items-center justify-between gap-3 border-b border-line/60 py-1.5 last:border-0"
      style={highlight ? { backgroundColor: 'color-mix(in srgb, #5F7B69 10%, transparent)', borderRadius: 6 } : undefined}
    >
      <span className="text-tag text-ink-3">{label}</span>
      <span className="text-aux font-medium text-ink">{value}</span>
    </div>
  )
}

export default function LifeCirclePage() {
  const { sceneId = 'kaili' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')
  // 首页生活圈域提交时把输入文字带到地图页（state.query）→ 直接作为中心点初始搜索值（不丢字）。
  const incomingQuery = (location.state as { query?: string } | null)?.query ?? ''
  const [customCenter, setCustomCenter] = useState<LngLat | null>(null)
  /* ═══ C8：图-面板联动状态（低频：LcMap 仅在 mouseover/mouseout 上报，审查 R6 纪律）═══ */
  const [isoHoverMinutes, setIsoHoverMinutes] = useState<number | null>(null)
  const [blindHoverSev, setBlindHoverSev] = useState<LcBlindSev | null>(null)
  /** 与 customCenter 同行的坐标系标签（地图拖拽/点击 → bd09；原生定位 → wgs84） */
  const [customCoordSys, setCustomCoordSys] = useState<CoordSys>('bd09')
  const [dragging, setDragging] = useState(false)
  /* BMapGL 真实地图渲染层（C5 徽标语义 + C3 定位按钮共用） */
  const lcMapRef = useRef<LcMapHandle>(null)
  const [mapMode, setMapMode] = useState<LcMapMode>('boot')
  /** 片 5：证据域图层开关（默认关 —— 它是解释层，不是主叙事层；见 LcMap.showEvidenceDiscs） */
  const [evidenceOn, setEvidenceOn] = useState(false)
  /** C1：判定尺图层开关（同样默认关）。它回答的是"判一格用的圆有多大"，
   *  与证据盘回答的"查到哪儿"是两件事，所以不合并成一个开关。 */
  const [judgeScaleOn, setJudgeScaleOn] = useState(false)
  /** C5：选中的判定格 `(行, 列)`。卡片格阵与地图点击共用这一个状态。 */
  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null)
  const [locating, setLocating] = useState(false)
  const [locateErr, setLocateErr] = useState('')
  /** v5 A：真实模式「定位到我」后的待确认定位（确认弹窗数据源，确认才发起体检） */
  const [pendingLocate, setPendingLocate] = useState<(PendingCenter & { name: string }) | null>(null)

  /* A4 演示任务流（仅 mock 分支；M3 真实分支由工作台 SSE 接管） */
  const [playing, setPlaying] = useState(false)
  const [playStage, setPlayStage] = useState('intake')
  const [playProgress, setPlayProgress] = useState(0)
  const [playMsg, setPlayMsg] = useState('')
  const closeRef = useRef<(() => void) | null>(null)

  /* M3 真实分支：拉取最近一次体检记录渲染画布 + 顶部「开始体检」CTA */
  const [realReport, setRealReport] = useState<LivingCircleReport | null>(null)
  const [realLatestId, setRealLatestId] = useState('')
  const [realLoading, setRealLoading] = useState(!isFixture)
  const [ctaText, setCtaText] = useState(incomingQuery)
  const [ctaBusy, setCtaBusy] = useState(false)
  const [ctaErr, setCtaErr] = useState('')
  const [regionOpen, setRegionOpen] = useState(false)
  /* D·回落 SSE 运行态（真实模式）：进度值单一事实源 = taskRegistry。
     本页只保留「当前正在跟随的任务 id」做订阅锚点，runStage/runPercent/runActive
     均由注册表派生（lifeCircleFlow 写入），不再维护并行的局部进度。 */
  const [runMsg, setRunMsg] = useState('')
  const [runTaskId, setRunTaskId] = useState('')
  /* 片 5：取证回合的实时那一行（`round` 事件的 `text` 原样上屏，前端不重排句子）。
     只在「开始跟随一个新任务」那两处清 —— 不挂在 runMsg 的五个写点上：横幅本身只在
     `runActive` 时渲染，任务一落终态就整块卸载，散五处反而漏一处就把上一轮的账挂到下一轮。 */
  const [roundLines, setRoundLines] = useState<{ text: string; row: ForensicRoundRow }[]>([])
  const lcTasks = useTaskRegistry((s) => s.tasks)
  const regTask = runTaskId ? lcTasks[runTaskId] : null
  const runActive = !!regTask && regTask.status === 'running'
  const runStage = regTask?.stage || 'intake'
  const runPercent = regTask?.percent ?? 0
  const flowRef = useRef<(() => void) | null>(null)
  const pendingTaskRef = useRef('')

  /* SSE 闭环回调：进度由 capture 写 register 后经派生渲染；失败/就绪仅做页面复位（服务/渲染层由 registry 落终态） */
  const flowCallbacks = {
    onProgress: (_stage: string, _percent: number, message?: string) => {
      if (message) setRunMsg(message)
    },
    onRound: (row: ForensicRoundRow, text: string) => {
      setRoundLines((prev) => [...prev, { text, row }])
    },
    onError: (message: string) => {
      setRunTaskId('')
      setRunMsg('')
      flowRef.current?.()
      flowRef.current = null
      pendingTaskRef.current = ''
      setCtaErr(message)
    },
    onReportReady: (report: LivingCircleReport, reportId: string) => {
      setRunTaskId('')
      setRunMsg('')
      flowRef.current?.()
      flowRef.current = null
      pendingTaskRef.current = ''
      setRealReport(report)
      setRealLatestId(reportId)
    },
  }

  /* 幂等订阅：HomePage 真实模式 navigate 携带 taskId → 本页接管 SSE 进度并自动渲染。
     重复挂载/重入同任务不重复开流。 */
  const incomingTaskId = (location.state as { taskId?: string } | null)?.taskId ?? ''
  useEffect(() => {
    if (isFixture || !incomingTaskId) return
    if (pendingTaskRef.current === incomingTaskId) return
    pendingTaskRef.current = incomingTaskId
    setRunTaskId(incomingTaskId)
    setRunMsg('')
    setRoundLines([])
    setCtaErr('')
    flowRef.current = subscribeLifeCircleTask(incomingTaskId, flowCallbacks)
  }, [incomingTaskId, isFixture])

  useEffect(() => {
    if (isFixture) return
    let cancelled = false
    fetchLifeCircleReports()
      .then((rows) => {
        if (cancelled || !rows.length) return
        setRealLatestId(rows[0].id)
        return fetchLifeCircleReport(rows[0].id)
      })
      .then((rep) => {
        if (!cancelled && rep?.living_circle) setRealReport(rep.living_circle)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setRealLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isFixture])

  const report = useMemo<LivingCircleReport | null>(() => {
    if (!isFixture) return realReport
    if (sceneId === 'custom') {
      // 演示态：自定义中心点复用最近样例
      return SAMPLE_COMMUNITIES[0] ? SAMPLE_COMMUNITIES[0].report : null
    }
    return getLifeCircleMock(sceneId)
  }, [sceneId, realReport, isFixture])

  const center: LngLat = customCenter ?? report?.scene.center ?? [0, 0]
  // R-7：降级披露唯一出口（与报告页同一函数，不在这里另写一套文案）
  const dgBanner = report ? degradeBanner(report) : null
  /** C6：判定尺那句口径的半径部分。取自产物（台账 → 盲区条目），取不到就整块不出现 ——
   *  写死 "1km" 会在分档后变成一句假话。 */
  const rulerLabel = report ? judgeRulerLabel(report) : null
  /** C4：逐格台账。取不到（`ev-2` 之前的报告、离线骨架、或台账半截不合形）⇒ 整张卡不出现。 */
  const ledger = report ? cellsLedgerOf(report) : null

  // 样区路由参数与报告 id：custom → 最近样例 kaili（仅演示分支使用）
  const effectiveScene = sceneId === 'custom' ? 'kaili' : sceneId
  const reportId = LC_REPORT_ID(effectiveScene)
  const targetReportId = isFixture ? reportId : realLatestId

  /**
   * 任务入参组装（阶段 2 P0）——**名称/坐标/坐标系一次性组装，同源同行**。
   *
   * ## 被修掉的事故
   *
   * 旧实现：`onLocate` 里 `setCtaText(hit.name)` 紧接着 `startRealCheck(hit.lnglat)`，
   * 而 `startRealCheck` 读 `ctaText.trim()`。React 的 setState 是排队的 —— 同一次事件
   * 回调里 state 还没更新，于是：
   *
   * | 字段 | 旧来源 | 实测值 |
   * |---|---|---|
   * | scene_name | 闭包里的**旧** ctaText | 北京劲松 |
   * | center | 定位的**新**坐标 | 102.76, 25.03（昆明） |
   * | city | `report?.scene.city`（**当前展示的报告**） | 北京·朝阳 |
   *
   * 三字段三个来源 → 报告自相矛盾（实测 `lc-d3cfa371`）。
   *
   * ## 修法
   *
   * 1. 名称改由**参数显式传入**（`nameOverride`），不再依赖 setState 后的 state；
   * 2. **城市不再随请求发送** —— 它与本次查询无关，改由后端对中心点逆地理补全
   *    （`reverse_geocoding`）；这样「名/坐标/城市」全部锚定在**同一个中心点**上。
   */
  function buildTaskInput(opts: { pending?: PendingCenter; nameOverride?: string }): TaskInput {
    const typed = ctaText.trim()
    const coordText = /^\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*$/.exec(typed)
    const explicitName = (opts.nameOverride ?? '').trim()

    if (opts.pending) {
      // 地图拖拽 / 浏览器定位：名称、坐标、坐标系同时到达
      return {
        query: explicitName || (coordText ? '' : typed) || '生活圈体检',
        center: opts.pending.lnglat,
        coord_sys: opts.pending.coordSys,
      }
    }
    if (coordText) {
      // 文本输入约定为 BD-09（占位文案已注明）；越界即当场报错，
      // 不允许把坏坐标写进库（一次写库 → 每次打开都复现）。
      return {
        query: explicitName || '生活圈体检',
        center: asBdLngLat([Number(coordText[1]), Number(coordText[2])], 'LifeCirclePage.坐标输入'),
        coord_sys: 'bd09',
      }
    }
    return { query: explicitName || typed || '生活圈体检', coord_sys: 'bd09' }
  }

  /** M3：以当前输入（或地图新中心点）发起真实体检任务 → 回落本页 SSE 进度（不再进工作台） */
  async function startRealCheck(opts: { pending?: PendingCenter; nameOverride?: string } = {}) {
    if (ctaBusy || runActive) return
    setCtaErr('')
    setCtaBusy(true)
    setRunTaskId('')
    setRunMsg('正在创建任务…')
    setRoundLines([])
    try {
      const input = buildTaskInput(opts)
      const handle = await launchLifeCircle(
        {
          query: input.query,
          center: input.center,
          coord_sys: input.coord_sys,
          // city 有意不传：由后端按中心点逆地理（见 buildTaskInput 注释）
        },
        flowCallbacks,
      )
      if (pendingTaskRef.current && pendingTaskRef.current !== handle.taskId) {
        handle.close() // 已有其它进行中任务 → 关闭新建流，防多流互串
      }
      pendingTaskRef.current = handle.taskId
      setRunTaskId(handle.taskId)
      flowRef.current = handle.close
    } catch (e) {
      setRunTaskId('')
      setRunMsg('')
      setCtaErr(e instanceof Error ? e.message : String(e))
    } finally {
      setCtaBusy(false)
    }
  }

  useEffect(
    () => () => {
      closeRef.current?.()
      flowRef.current?.()
    },
    [],
  )

  if (!report) {
    // 真实模式：暂无体检记录 → 引导发起
    if (!isFixture) {
      return (
        <div className="mx-auto flex min-h-full max-w-[720px] flex-col items-center justify-center gap-4 px-6 py-16 text-center">
          <Info size={32} className="text-ink-3" />
          <div className="text-h3 text-ink">还没有体检记录</div>
          <p className="text-aux text-ink-2">
            输入社区名或坐标发起第一次生活圈体检，完成后会在这里展示等时圈与体检单
          </p>
          {runActive && (
            <div
              className="mt-1 flex w-full max-w-md items-center gap-3 rounded-card border border-primary-soft bg-primary-tint px-4 py-3 text-left"
              role="status"
              aria-live="polite"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-btn bg-primary text-white">
                <Play size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                  体检进行中 · {stageLabel(runStage)}
                  <span className="text-tag font-medium text-primary-deep">{runPercent}%</span>
                </div>
                {runMsg && <div className="truncate text-tag text-ink-2" title={runMsg}>{runMsg}</div>}
              </div>
              <div className="h-1.5 w-24 overflow-hidden rounded-chip bg-line">
                <div className="h-full rounded-chip bg-primary" style={{ width: `${Math.max(0, Math.min(100, runPercent))}%` }} />
              </div>
            </div>
          )}
          <div className="mt-1 flex w-full max-w-md items-center gap-2">
            <input
              value={ctaText}
              onChange={(e) => setCtaText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') startRealCheck()
              }}
              placeholder="社区名 / 或 经度,纬度（BD-09）—— 例如：凯里老街"
              className="h-11 flex-1 rounded-btn border border-line bg-card px-4 text-aux text-ink outline-none placeholder:text-ink-3 focus:border-primary"
            />
            <button
              onClick={() => startRealCheck()}
              disabled={ctaBusy || realLoading}
              className="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-btn bg-primary px-5 font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <Play size={15} /> 开始体检
            </button>
          </div>
          {ctaErr && <div className="text-tag text-risk">创建失败：{ctaErr}</div>}
          {realLoading && <div className="text-tag text-ink-3">正在加载历史记录……</div>}
        </div>
      )
    }
    return (
      <div className="grid min-h-full place-items-center p-8 text-ink-2">
        <div className="rounded-card border border-line bg-card p-6 text-center">
          <Info size={22} className="mx-auto mb-2 text-ink-3" />
          <p>未找到该样区的体检数据</p>
        </div>
      </div>
    )
  }

  /** C3 定位到我：浏览器定位 → 逆地理社区名（live 走 BMapGL，降级用 WGS-84 原始坐标）→ 就地标注/发起体检 */
  async function onLocate() {
    if (locating) return
    setLocating(true)
    setLocateErr('')
    const hit = await lcMapRef.current?.locate()
    setLocating(false)
    if (!hit) {
      setLocateErr('定位失败或未授权，请检查浏览器定位权限')
      return
    }
    if (hit.coordSys === 'wgs84') {
      // 降级分支（无浏览器 AK）：拿到的是 WGS-84，偏约 600m，如实告知并由服务端转换
      setLocateErr('已定位（WGS-84 原始坐标，提交时由服务端转为 BD-09）')
    }
    if (isFixture) {
      setCustomCenter(hit.lnglat)
      setCustomCoordSys(hit.coordSys)
      setDragging(true)
    } else {
      // 输入框同步定位到的名称 —— **仅供人看**：请求的名称走下方的显式参数，
      // 不依赖这次 setState（setState 排队，同 tick 内读到的仍是旧值，即阶段 2 事故根因）。
      setCtaText(hit.name || '当前位置')
      // v5 A：定位结果先进确认框（名称/坐标/坐标系/额度提示），确认才发起体检
      setPendingLocate({ lnglat: hit.lnglat, coordSys: hit.coordSys, name: hit.name || '当前位置' })
    }
  }

  /** v5 A：确认框「确认体检」——以本次定位结果正式发起真实体检（取消则清空，不发起） */
  function confirmLocateCheck() {
    if (!pendingLocate) return
    const pending = pendingLocate
    setPendingLocate(null)
    void startRealCheck({
      pending: { lnglat: pending.lnglat, coordSys: pending.coordSys },
      nameOverride: pending.name,
    })
  }

  /** A4：回放体检流水线事件流（演示用；M3 由真实任务流接管） */
  function startDemoFlow() {
    setPlaying(true)
    setPlayStage('intake')
    setPlayProgress(0)
    setPlayMsg('')
    closeRef.current = replayLivingCircleStream(
      `lc-${effectiveScene}`,
      {
        onEvent: (type, data) => {
          const d = data as { stage?: string; percent?: number; text?: string }
          if (type === 'progress' && d?.stage) {
            setPlayStage(d.stage)
            setPlayProgress(d.percent ?? 0)
          }
          if (type === 'message' && d?.text) setPlayMsg(d.text)
        },
      },
      { reportId, onDone: (rid) => navigate(`/report/${rid}`) },
    )
  }

  function stopDemoFlow(skipToReport = false) {
    closeRef.current?.()
    closeRef.current = null
    setPlaying(false)
    if (skipToReport) navigate(`/report/${reportId}`)
  }

  return (
    <div className="mx-auto flex min-h-full max-w-[1240px] flex-col gap-4 px-6 py-6">
      {/* 顶栏：mock=场景切换 + 演示流水线；M3=真实「开始体检」CTA + 最新报告入口 */}
      {isFixture ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {SAMPLE_COMMUNITIES.map((c) => (
              <button
                key={c.id}
                onClick={() => navigate(`/life-circle/${c.id}`)}
                className={`flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux transition-colors ${
                  sceneId === c.id ? 'bg-primary text-white' : 'bg-primary-tint/60 text-ink-2 hover:bg-primary-tint'
                }`}
              >
                <MapPin size={14} />
                {c.title}
              </button>
            ))}
            <button
              onClick={startDemoFlow}
              disabled={playing}
              title="演示：回放体检 SSE 流水线（intake→…→audit）后打开报告"
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint disabled:opacity-50"
            >
              <Play size={13} /> 演示体检流水线
            </button>
            <button
              onClick={() => navigate('/compare')}
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
            >
              对比双样例 →
            </button>
            <button
              onClick={onLocate}
              disabled={locating}
              title="使用设备当前位置发起体检（C3）"
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint disabled:opacity-50"
            >
              <Navigation size={13} /> {locating ? '定位中…' : '定位到我'}
            </button>
          </div>
          {locateErr && <span className="text-tag text-risk">{locateErr}</span>}
          {report.data_origin === 'fixture_sample' && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-warn/60 bg-warn/10 px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> 演示数据模式（fixture · 等时圈为圆形近似，M5 后真实路网覆写）
            </span>
          )}
          {report.served_from === 'cache' && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-primary-soft bg-primary-tint px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> 历史实时结果 · 离线可查
            </span>
          )}
          {report.served_from === 'nearby_cache' && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-primary-soft bg-primary-tint px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> 邻近既有体检结果 · 原中心距此 ≤500m（未消耗百度额度）
            </span>
          )}
          {report.data_origin === 'offline' && dgBanner && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-risk/60 bg-risk/10 px-3 h-9 text-tag font-medium text-[#8F5E56]" title={dgBanner.action}>
              <TriangleAlert size={14} /> 百度配额熔断降级 · {dgBanner.label}
            </span>
          )}
          {report.data_origin === 'offline' && !dgBanner && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-warn/60 bg-warn/10 px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> 离线估算 · 距离模型（未联网，POI 与评分待实时体检）
            </span>
          )}
          {report.data_origin === 'live' && report.served_from !== 'cache' && (
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-primary-soft bg-primary-tint px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} />
              {mapMode === 'live'
                ? `真实地图 · 实时路网测时（${report.sampling.interpolation === 'idw' ? 'IDW 等时圈' : '等时圈'}）`
                : `内置快照 · 真实百度路网测时（${report.sampling.interpolation === 'idw' ? 'IDW 等时圈' : '等时圈'}）离线演示`}
            </span>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-[300px] flex-1 items-center gap-2">
            <input
              value={ctaText}
              onChange={(e) => setCtaText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') startRealCheck()
              }}
              placeholder="输入社区名 / 或 经度,纬度（BD-09）后重新体检，例如：凯里老街"
              className="h-9 flex-1 rounded-btn border border-line bg-card px-3 text-aux text-ink outline-none placeholder:text-ink-3 focus:border-primary"
            />
            <button
              onClick={() => startRealCheck({ pending: customCenter ? { lnglat: customCenter, coordSys: customCoordSys } : undefined })}
              disabled={ctaBusy}
              className="flex h-9 shrink-0 items-center gap-1.5 rounded-btn bg-primary px-4 text-aux font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <Play size={13} /> 开始体检
            </button>
          </div>
          <div className="flex items-center gap-2">
            {targetReportId && (
              <button
                onClick={() => navigate(`/report/${targetReportId}`)}
                className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
              >
                浏览最新报告 →
              </button>
            )}
            <button
              onClick={() => navigate('/compare')}
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint"
            >
              对比双样例 →
            </button>
            <button
              onClick={onLocate}
              disabled={locating}
              title="使用设备当前位置发起体检（C3）"
              className="flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux text-ink-2 transition-colors hover:bg-primary-tint disabled:opacity-50"
            >
              <Navigation size={13} /> {locating ? '定位中…' : '定位到我'}
            </button>
            {!isFixture && (
              <button
                onClick={() => setRegionOpen((v) => !v)}
                title="从全国行政区划选择地址（无 AK 也能出离线体检骨架）"
                className={`flex h-9 items-center gap-1.5 rounded-chip px-3 text-aux transition-colors ${
                  regionOpen ? 'bg-primary text-white' : 'text-ink-2 hover:bg-primary-tint'
                }`}
              >
                <MapPin size={13} /> 区划选择
              </button>
            )}
            <span className="inline-flex items-center gap-1.5 rounded-chip border border-warn/60 bg-warn/10 px-3 h-9 text-tag font-medium text-ink-2">
              <Info size={14} /> {report.served_from === 'nearby_cache' ? '邻近既有体检结果 · 原中心距此 ≤500m（未消耗百度额度）' : report.served_from === 'cache' ? '历史实时结果 · 离线可查' : report.data_origin === 'offline' ? '离线估算模式（未联网）' : report.data_origin === 'fixture_sample' ? '演示数据模式（fixture）' : '真实数据模式（live）'}
            </span>
          </div>
          {!isFixture && regionOpen && (
            <div className="mt-2">
              <RegionSelector
                visible={regionOpen}
                onPick={(s) => setCtaText(s)}
                onClose={() => setRegionOpen(false)}
              />
            </div>
          )}
        </div>
      )}
      {!isFixture && ctaErr && (
        <div className="rounded-btn bg-risk/10 px-3 py-1.5 text-tag text-risk" role="alert">
          体检任务创建失败：{ctaErr}
        </div>
      )}
      {!isFixture && locateErr && (
        <div className="rounded-btn bg-risk/10 px-3 py-1.5 text-tag text-risk" role="alert">
          {locateErr}
        </div>
      )}

      {/* 回落 SSE：报告生成中，进度直接显示在本页（不再跳工作台） */}
      {!isFixture && runActive && (
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
              生活圈体检进行中 · {stageLabel(runStage)}
              <span className="text-tag font-medium text-primary-deep">{runPercent}%</span>
            </div>
            {runMsg && <div className="truncate text-tag text-ink-2" title={runMsg}>{runMsg}</div>}
            {/* 片 5：取证扩容回合的实时账（文案 = 后端 `round` 事件自带 text，唯一措辞出处）。
                刻意不改 stage/percent：那一格额度花在补算上，但阶段没变（仍是采集）。 */}
            {roundLines.map((l) => (
              <div
                key={`${l.row.pass_no}-${l.row.dispatched ? 'sent' : 'skip'}`}
                className="mt-1 flex items-start gap-1.5 rounded-btn bg-card/70 px-2 py-1 text-tag text-ink-2"
              >
                <Layers size={12} className="mt-0.5 shrink-0 text-primary" />
                <span>
                  {l.text}
                  <span className="ml-1 text-ink-3">（取证额度剩 {l.row.pool_remaining} 次）</span>
                  {l.row.anchors_dropped > 0 && (
                    <span className="ml-1 font-medium text-warn">份额砍掉 {l.row.anchors_dropped} 个锚点</span>
                  )}
                </span>
              </div>
            ))}
          </div>
          <div className="h-1.5 w-40 overflow-hidden rounded-chip bg-line">
            <div
              className="h-full rounded-chip bg-primary"
              style={{ width: `${Math.max(0, Math.min(100, runPercent))}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* 地图画布：BMapGL 真实地图（LcMap），无 AK/离线自动降级静态画布 */}
        <div className="relative min-h-[480px] overflow-hidden rounded-card border border-line bg-card shadow-card">
          <LcMap
            ref={lcMapRef}
            report={report}
            customCenter={customCenter}
            onCenterChange={(c) => {
              setCustomCenter(c)
              setCustomCoordSys('bd09') // 地图交互产出的必然是 BD-09
              setDragging(true)
            }}
            onMapMode={setMapMode}
            onIsoHover={setIsoHoverMinutes}
            onBlindHover={setBlindHoverSev}
            showEvidenceDiscs={evidenceOn}
            showJudgeScale={judgeScaleOn}
            selectedCell={selectedCell}
            onCellPick={setSelectedCell}
          />

          {/* 图例（悬浮）。⚠️ `z-10` 不是装饰：百度 GL 会在地图容器里注入 `.BMap_mask`
              （实测 `position:absolute; z-index:9; pointer-events:auto`），而本面板原先是
              `z-index:auto` ⇒ 同层按 DOM 序，后注入的 mask 压在面板上。面板以前只有色块和文字
              （看不见也点不着，无人察觉），片 5 往里放了**第一个可交互控件**（证据域勾选）后，
              真机上 `elementFromPoint(勾选框中心)` 返回的是 `BMap_mask` —— 点击被地图吃掉。
              抬到 10（> mask 的 9）之后同一判据返回 INPUT，真指针点击成功。 */}
          <div className="absolute left-3 top-3 z-10 flex max-w-[190px] flex-col gap-1.5 rounded-btn border border-line bg-card/90 p-3 backdrop-blur">
            <span className="text-tag font-medium text-ink-2">图层</span>
            {Object.entries(LC_CAT_COLOR).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1.5 text-tag text-ink-3">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: v }} />
                {k === 'market' ? '菜市场' : k === 'medical' ? '医疗' : k === 'education' ? '教育' : k === 'shopping' ? '购物' : k === 'elderly' ? '养老' : k === 'finance' ? '金融' : k === 'recreation' ? '文体' : '政务/服务'}
              </span>
            ))}
            <span className="mt-1 flex items-center gap-1.5 border-t border-line/70 pt-1.5 text-tag text-ink-3">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: 'linear-gradient(135deg,#8fbfa2,#2c5a3f)' }} />
              采样点耗时热力（0→20min）
            </span>
            {LC_BLIND_SEV_ORDER.map((sev) => {
              const n = report.blindspots.filter((b) => severityOf(b) === sev).length
              return (
                <span
                  key={sev}
                  className="flex items-center gap-1.5 text-tag text-ink-3"
                  style={
                    blindHoverSev === sev
                      ? { backgroundColor: `color-mix(in srgb, ${LC_BLIND_SEV[sev].dot} 14%, transparent)`, borderRadius: 6 }
                      : undefined
                  }
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: LC_BLIND_SEV[sev].dot }} />
                  {LC_BLIND_SEV[sev].label}盲区 · 缺口≥0.6/0.33/其余
                  {n > 0 && (
                    <span className="ml-auto rounded-full px-1.5 text-tag font-medium" style={{ backgroundColor: `color-mix(in srgb, ${LC_BLIND_SEV[sev].dot} 16%, transparent)`, color: '#555' }}>
                      {n}
                    </span>
                  )}
                </span>
              )
            })}
            {/* C4（审查 R7）：图标 = fixPlusSvgDataUrl 单一出口，与地图 fixPlusIcon 同源——图例即真实标记的样子 */}
            <span className="flex items-center gap-1.5 text-tag text-ink-3">
              <img src={fixPlusSvgDataUrl(LC_FIX_DOT)} alt="" className="h-3.5 w-3.5" />
              补点处方（流动服务/改道/补建）
            </span>
            {/* 片 5：证据域图层开关。**没有明细就不出现**（旧快照/离线从没发过 `evidence_anchors`，
                给一个勾不动的复选框等于摆一个假入口）。 */}
            {evidenceDiscs(report).length > 0 && (
              <label className="mt-1 flex cursor-pointer items-start gap-1.5 border-t border-line/70 pt-1.5 text-tag font-medium text-ink-2">
                <input
                  type="checkbox"
                  className="mt-0.5 h-3.5 w-3.5"
                  checked={evidenceOn}
                  onChange={(e) => setEvidenceOn(e.target.checked)}
                />
                <span>
                  证据域（查到哪儿）
                  <span className="mt-0.5 block font-normal text-ink-3">
                    {evidenceDiscs(report).length} 盘 · 实线查全 / 虚线未查全
                  </span>
                </span>
              </label>
            )}
            {/* C1/C6 · 判定尺开关 + 那句口径。**没有尺就不出现**（同证据盘那条纪律：
                摆一个勾不动的复选框等于摆一个假入口）。半径取自产物，不写死 1km。 */}
            {rulerLabel && (
              <label className="mt-1 flex cursor-pointer items-start gap-1.5 border-t border-line/70 pt-1.5 text-tag font-medium text-ink-2">
                <input
                  type="checkbox"
                  className="mt-0.5 h-3.5 w-3.5"
                  checked={judgeScaleOn}
                  onChange={(e) => setJudgeScaleOn(e.target.checked)}
                />
                <span>
                  判定尺（判一格用多大）
                  <span className="mt-0.5 block font-normal text-ink-3">
                    判盲问的是{rulerLabel}，不是眼前这一小块
                  </span>
                </span>
              </label>
            )}
          </div>

          {dragging ? (
            <div className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-chip border border-line bg-card/95 px-4 py-2 shadow-card backdrop-blur">
              <span className="text-tag text-ink-2">
                已设定新中心点（{center[0].toFixed(4)}, {center[1].toFixed(4)}）
              </span>
              <button
                onClick={() => {
                  if (isFixture) {
                    const next = sceneId === 'custom' ? SAMPLE_COMMUNITIES[0] : SAMPLE_COMMUNITIES.find((c) => c.id === sceneId)
                    if (next) navigate(`/life-circle/${next.id}`)
                    setDragging(false)
                  } else {
                    setDragging(false)
                    startRealCheck({ pending: customCenter ? { lnglat: customCenter, coordSys: customCoordSys } : undefined })
                  }
                }}
                className="ml-2 inline-flex items-center gap-1 rounded-chip bg-primary px-2.5 py-1 text-tag font-medium text-white hover:bg-primary-deep"
              >
                <RotateCcw size={12} /> 重新体检
              </button>
            </div>
          ) : (
            <div className="absolute bottom-3 left-3 z-10 hidden items-center gap-1 rounded-chip bg-card/80 px-3 py-1.5 text-tag text-ink-3 backdrop-blur sm:flex">
              <Crosshair size={12} />
              {mapMode === 'live' ? '拖拽地图中心标记设定新中心点' : '点击画布任意位置设定新中心点'}
            </div>
          )}
        </div>

        {/* 体检单右栏 */}
        <aside className="flex flex-col gap-4">
          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="flex items-end justify-between">
              <div>
                <div className="text-aux font-semibold text-ink">{report.scene.name} · 生活圈体检单</div>
                <div className="mt-0.5 text-tag text-ink-3">
                  {report.scene.city} · {report.scene.address}
                </div>
              </div>
              <div className="text-right">
                {report.data_origin === 'offline' ? (
                  <div className="text-right">
                    <div className="text-sm font-semibold leading-none text-ink-3">评分待实时体检</div>
                    <div className="mt-1 text-tag text-ink-3">离线估算 · 距离模型，不可与实时分比较</div>
                  </div>
                ) : (
                  <div className="text-right">
                    <div className="font-serif text-[34px] font-semibold leading-none text-primary">{report.scores.total}</div>
                    <div className="mt-1 text-tag text-ink-3">综合评分</div>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-3 border-t border-line pt-3">
              {report.data_origin === 'offline' ? (
                <p className="py-6 text-center text-tag text-ink-3">分类雷达需实时体检数据</p>
              ) : (
                <MiniRadar report={report} />
              )}
              {/* 片 1c-β C1：与报告页同一处渲染（措辞判据在 `lib/livingCircle`，两页不各写一遍） */}
              <CategoryCaliberNotes lc={report} />
            </div>
          </div>

          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="mb-1 text-aux font-semibold text-ink">必备设施三要素</div>
            <div className="flex flex-wrap gap-2 py-2">
              {report.scores.triads.map((t) => (
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
            {/* 阶段 2.5：三段式「采集 · 圈内 · 已展示」，走 `poiMetricLabel` 单一实现。
                旧文案 `N 个（圈内 M）` 与图上点数对不上账（面板数取 `poi.in_circle`、
                图上点数取 `points.length`，两条链各算各的）。 */}
            <StatRow label="POI 采集" value={poiMetricLabel(report)} />
            {/* 阶段 1.8 读侧披露：历史报告里「面板数 ≠ 图上点数」时如实说明，
                不让读者自己发现两处数字打架。新报告由装配层守恒保证，不会出现。 */}
            {poiConservationNote(report) && (
              <p className="mt-1 text-tag text-risk">{poiConservationNote(report)}</p>
            )}
            <StatRow label="采样点" value={samplingReachLabel(report)} />
            <StatRow label="15min 等时圈面积" value={`${(report.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0).toFixed(2)} km²`} highlight={isoHoverMinutes === 15} />
            <StatRow label="服务盲区" value={`${report.blindspots.length} 处`} />
            {/* 阶段 −1.5：判盲覆盖度必须与盲区数同屏。只写「0 处」会被读成「全圈都没问题」，
                实际 kaili 只有 9/72 格被判定过（87.5% 数据不足未判）。
                rev2 · D-3：证据不足时综合评分已按覆盖率打折，脚注同时升为 warn 色并挂降档徽标
                —— 灰字只说明「判了多少」，读者仍会把「0 处盲区」当结论；徽标说的是「所以这个数
                偏乐观」。旧口径快照没有 confidence ⇒ 徽标不出现（不是猜成 full），脚注照旧。 */}
            {blindspotCoverageBrief(report) && (
              <p
                className={`mt-1 text-tag ${
                  confidenceBadgeLabel(report) ? 'font-medium text-warn' : 'text-ink-3'
                }`}
              >
                {blindspotCoverageBrief(report)}
                {confidenceBadgeLabel(report) && (
                  <span className="ml-1.5 rounded-chip bg-warn/10 px-1.5 py-0.5">{confidenceBadgeLabel(report)}</span>
                )}
              </p>
            )}
            {/* D-4：口径升级前的历史报告仍是用户的数据（不隐藏），但必须说明它偏乐观。
                两轴各一句（判盲 `ev-*` / 评分 `cov-*`）——「哪句该出现」收在 `staleCaliberNotices`，
                这里只渲清单：两页各写一遍判据就是两页文案漂移的起点。 */}
            {staleCaliberNotices(report).map((n) => (
              <p key={n} className="mt-1 text-tag font-medium text-warn">{n}</p>
            ))}
            
            {/* R2/R6：口径举证对象 */}
            {report.caliber && (
              <>
                <div className="mt-3 border-t border-line pt-3">
                  <div className="mb-2 text-tag font-medium text-ink-2">测算口径</div>
                  <StatRow label="出行方式" value={report.caliber.travel_mode === 'walking' ? '步行' : report.caliber.travel_mode === 'riding' ? '骑行' : report.caliber.travel_mode === 'driving' ? '驾车' : report.caliber.travel_mode} />
                  <StatRow label="速度" value={`${report.caliber.speed_m_per_min} m/min`} />
                  <StatRow label="绕行系数" value={`×${report.caliber.detour_k}`} />
                  <StatRow label="研究半径" value={`${report.caliber.study_radius_m} m`} />
                  <StatRow label="等时圈档位" value={report.caliber.iso_minutes.map(m => `${m}min`).join(' / ')} />
                  <div className="mt-2 text-tag text-ink-3 leading-relaxed">
                    {report.caliber.basis}
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 text-tag text-ink-3">
                    <span className={`inline-block h-2 w-2 rounded-full ${report.caliber.measured ? 'bg-ok' : 'bg-warn'}`} />
                    {report.caliber.measured ? '实测数据' : '估算模型'}
                  </div>
                </div>
              </>
            )}
            
            <button
              onClick={() => targetReportId && navigate(`/report/${targetReportId}`)}
              disabled={!targetReportId}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-4 h-10 font-medium text-white shadow-card hover:bg-primary-deep disabled:opacity-40"
            >
              <FileText size={15} /> 查看{isFixture ? '体检报告' : '最新报告'}
            </button>
          </div>

          {/* C4 · 逐格台账卡。**没有台账就不出现**（`ev-2` 之前的报告与离线骨架走这一支）：
              摆一张只能看不能对的空卡，等于又造一个假入口。 */}
          {ledger && (
            <CellsLedgerCard
              led={ledger}
              selected={selectedCell}
              onPick={setSelectedCell}
              verdictAt={(i, j) => cellVerdict(report, [i, j])}
            />
          )}

          <div className="rounded-card border border-line bg-card p-4 shadow-card">
            <div className="mb-2 flex items-center gap-1.5 text-aux font-semibold text-ink">
              <TriangleAlert size={15} className="text-warn" /> 服务盲区清单
            </div>
            {report.data_origin === 'offline' ? (
              <p className="text-tag text-ink-3">离线估算未联网采集 POI，盲区识别需实时体检后给出</p>
            ) : report.blindspots.length === 0 ? (
              <>
                <p className="text-tag text-ink-3">{emptyBlindspotNote(report)}</p>
                {blindspotCoverageNote(report) && (
                  <p className="mt-1 border-t border-line/60 pt-1.5 text-tag text-ink-3">
                    {blindspotCoverageNote(report)}
                  </p>
                )}
              </>
            ) : (
              <div className="flex flex-col gap-2">
                {report.blindspots.map((b) => {
                  const sev = severityOf(b)
                  const sevSpec = LC_BLIND_SEV[sev]
                  const gap = gapScoreOf(b)
                  const affected = affectedOf(b) as { sampling_sites?: number; estimated_residents?: number } | null
                  const fix = (fixesOf(b) as { facility: string; strategy: string; priority: number }[])[0]
                  return (
                    <div key={b.id} className="rounded-btn border border-line/70 bg-ink-3/10 p-2.5">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-aux font-medium text-ink">
                          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: sevSpec?.dot ?? '#8a8a8a' }} />
                          {b.id.replace('bs-', '盲区 ')}
                        </span>
                        <span className="text-tag text-ink-3">{b.center[0].toFixed(4)},{b.center[1].toFixed(4)}</span>
                      </div>
                      <div className="mt-1 text-tag text-ink-3">
                        缺失：{b.missing_facilities.join(' / ')}
                        {sevSpec?.label ? <> · <span style={{ color: sevSpec.stroke }}>{sevSpec.label}</span></> : ''}
                        {gap != null ? <> · 缺口 {gap}</> : ''}
                      </div>
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
                      {fix && (
                        <div className="mt-0.5 text-tag font-medium" style={{ color: '#1f9e63' }}>
                          建议补{fix.facility} · {LC_BLIND_FIX_STRATEGY[fix.strategy] ?? fix.strategy} · P{fix.priority}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* A4 演示流水线 overlay：回放 SSE 事件流 */}
      {playing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-card border border-line bg-card p-6 shadow-float">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                <Play size={15} className="text-primary" /> 常青圈 · 体检流水线
              </div>
              <button onClick={() => stopDemoFlow(true)} title="跳过并直接查看报告" className="grid h-8 w-8 place-items-center rounded-btn text-ink-3 hover:bg-primary-tint">
                <X size={15} />
              </button>
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {LC_STAGES.map((s) => (
                <span
                  key={s}
                  className={`rounded-chip px-2 py-1 text-tag font-medium ${
                    LC_STAGES.indexOf(s) < LC_STAGES.indexOf(playStage)
                      ? 'bg-ok/15 text-ok'
                      : s === playStage
                        ? 'bg-primary text-white'
                        : 'bg-bg text-ink-3'
                  }`}
                >
                  {stageLabel(s)}
                </span>
              ))}
            </div>
            <div className="mt-4">
              <div className="flex items-center justify-between text-tag text-ink-3">
                <span className="truncate pr-3">{playMsg || '流水线启动中…'}</span>
                <span className="shrink-0">{playProgress}%</span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-chip bg-line">
                <div className="h-full rounded-chip bg-primary transition-all duration-200" style={{ width: `${playProgress}%` }} />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between gap-2">
              <span className="text-tag text-ink-3">演示数据 · 事件契约与 M3 真实 SSE 一致（A4）</span>
              <button
                onClick={() => stopDemoFlow(true)}
                className="rounded-btn bg-primary-tint px-3 h-9 text-aux font-medium text-primary-deep hover:bg-primary-soft/40"
              >
                跳过并查看报告
              </button>
            </div>
          </div>
        </div>
      )}

      {/* v5 A：定位确认弹窗（真实模式「定位到我」→ 确认才发起体检；取消不发起、不耗额度） */}
      {!isFixture && pendingLocate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm"
          role="dialog"
          aria-label="确认发起体检"
        >
          <div className="w-full max-w-sm rounded-card border border-line bg-card p-6 shadow-float">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-aux font-semibold text-ink">
                <Crosshair size={15} className="text-primary" /> 确认发起体检
              </div>
              <button
                onClick={() => setPendingLocate(null)}
                title="关闭"
                className="grid h-8 w-8 place-items-center rounded-btn text-ink-3 hover:bg-primary-tint"
              >
                <X size={15} />
              </button>
            </div>
            <div className="mt-4 flex flex-col gap-2 text-tag">
              <div className="flex items-center justify-between gap-3">
                <span className="text-ink-3">定位名称</span>
                <span className="truncate font-medium text-ink" title={pendingLocate.name}>
                  {pendingLocate.name}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-ink-3">坐标</span>
                <span className="font-medium text-ink">
                  {pendingLocate.lnglat[0].toFixed(5)}, {pendingLocate.lnglat[1].toFixed(5)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-ink-3">坐标系</span>
                <span className="font-medium text-ink">
                  {pendingLocate.coordSys === 'wgs84' ? 'WGS-84（提交时服务端转 BD-09）' : 'BD-09'}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-ink-3">数据模式</span>
                <span className="font-medium text-ink">真实联调</span>
              </div>
            </div>
            <p className="mt-4 flex items-start gap-1.5 rounded-btn border border-warn/40 bg-warn/10 px-3 py-2 text-tag text-ink-2">
              <Info size={13} className="mt-0.5 shrink-0 text-warn" />
              <span>
                新中心点将消耗本次体检所需百度配额；同地点或邻近（≤500m）30 天内已有体检结果时走缓存，不消耗额度。
              </span>
            </p>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                onClick={() => setPendingLocate(null)}
                className="inline-flex h-9 items-center gap-1.5 rounded-btn px-3.5 text-aux font-medium text-ink-2 hover:bg-primary-tint"
              >
                取消
              </button>
              <button
                onClick={confirmLocateCheck}
                title="以本次定位结果发起真实体检"
                className="inline-flex h-9 items-center gap-1.5 rounded-btn bg-primary px-4 text-aux font-medium text-white shadow-card hover:bg-primary-deep"
              >
                <Crosshair size={14} /> 确认体检
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}