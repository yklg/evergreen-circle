/**
 * 常青圈 · 生活圈真实地图组件（BMapGL v3.0，F2 规划渲染层落地）。
 *
 * 真实态（S2 底图）：百度底图 + 等时圈族/盲区 Polygon + POI 真实坐标 Marker
 *                  + 可拖拽中心标记；对比模式（compareReport）叠加 A/B 双色等时圈。
 * 降级态：无 AK / 脚本加载失败 / 离线 → 渲染原静态 SVG 投影画布 + 降级横幅
 *        （评审无网一键演示能力不退化；投影工具沿用 lib/livingCircle.ts）。
 *
 * 模式（live/fallback）通过 onMapMode 上报，页面据此切换徽标语义（C5）。
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import type { BlindSpot, LivingCircleReport, LngLat } from '../../types'
import { getMapConfig, geolocateMe, loadBMapGL } from '../../lib/bmap'
import type { BMapGLNamespace, BMapMap, BMapMapOverlay, BMapOverlayEvent, BMapPoint, BMapPolyline } from '../../lib/bmap'
import { lcMapStyle } from '../../lib/bmapStyle'
import { useMapNotesStore } from '../../store/mapNotesStore'
import { asBdLngLat, asBdLngLatOrNull, rejectBdLngLatSource, toDiagPair } from '../../lib/geo'
import type { CoordSys } from '../../lib/geo'
import { HeatFieldOverlay, minuteHeatColor } from './HeatFieldOverlay'
import type { HeatSamplePoint } from './HeatFieldOverlay'
import {
  LC_CANVAS,
  LC_CAT_COLOR,
  LC_CAT_LABEL_OF,
  LC_BLIND_FIX_STRATEGY,
  LC_FIX_DOT,
  LC_ISO_COLORS,
  LC_ISO_COLORS_B,
  affectedOf,
  blindCanRaw,
  blindHeatFill,
  blindPolygonOf,
  blindSevSpec,
  fixPlusSvg,
  fixesOf,
  gapScoreOf,
  heatSamplePoints,
  lcFillSpec,
  lcPolyPts,
  lcRightmost,
  lcToPx,
  lcSnapshotPoiLayer,
  poiRenderSet,
  poiThinNote,
  samplingReach,
  severityOf,
} from '../../lib/livingCircle'
import type { BlindBoundaryView } from '../../lib/livingCircle'

export type LcMapMode = 'boot' | 'live' | 'fallback'

/** 盲区严重度字面量（C8 回调载荷；severityOf 兜底 'light'，恒在表内） */
export type LcBlindSev = 'heavy' | 'medium' | 'light'

/** C2/C5/C7：交互信息卡（React 固定卡，审查 R1 定版——非 InfoWindow：按钮需真实事件绑定） */
export interface LcIsoCard {
  title: string
  rows: [string, string][]
  /** 对比页 B 社区卡（品牌蓝标） */
  blue?: boolean
  /** 「◎ 定位到此」目标（BD-09）；缺省不渲染按钮 */
  fly?: LngLat | null
}

export interface LcMapHandle {
  /** 定位到我：返回坐标 + 坐标系标签 + 逆地理社区名；用户拒绝/失败返回 null */
  locate: () => Promise<{ lnglat: LngLat; name: string; coordSys: CoordSys } | null>
}

export interface LcMapProps {
  report: LivingCircleReport
  /** 用户点选/拖拽的新中心（确认前仅就地标注，不触发计算，D2） */
  customCenter?: LngLat | null
  onCenterChange?: (center: LngLat) => void
  draggableCenter?: boolean
  /** 对比页第二份报告：叠加 A/B 双色等时圈（此时隐藏 POI Marker 防遮挡） */
  compareReport?: LivingCircleReport | null
  /** 渲染模式上报（页面据此切换徽标语义） */
  onMapMode?: (mode: LcMapMode) => void
  /** C8：悬停圈线 → 分钟数（离开=null）。挂 mouseover/mouseout 不挂 mousemove（审查 R6 低频纪律）；仅主报告触发 */
  onIsoHover?: (minutes: number | null) => void
  /** C8：悬停盲区 → 严重度（离开=null）。同上低频纪律 */
  onBlindHover?: (sev: LcBlindSev | null) => void
}

/**
 * 盲区悬浮信息（C2/C4：严重度/缺口/真实可达/受影响/补点；旧数据字段缺失时安全省略）
 */
export function blindTitle(b: BlindSpot): string {
  const id = b.id ?? ''
  const sev = severityOf(b)
  const label = LC_BLIND_SEV_LOCAL[sev]?.label
  const gap = gapScoreOf(b) != null ? ` · 缺口 ${gapScoreOf(b)}` : ''
  const reach =
    b.reach?.real_walk_min != null
      ? ` · 步行 ${b.reach.real_walk_min}min${b.reach.isochrone_based ? '（实测）' : '（估算）'}`
      : ''
  const affected = affectedOf(b) as BlindSpot['affected']
  const affectedStr =
    affected && affected.sampling_sites != null
      ? ` · 采样${affected.sampling_sites}点 · 估${affected.estimated_residents}人`
      : ''
  const fix = (fixesOf(b) as BlindSpot['fixes'])?.[0]
  const fixStr = fix ? ` · 建议补${fix.facility}·P${fix.priority}` : ''
  return `${id}${label ? `（${label}）` : ''} · 缺失${(b?.missing_facilities ?? []).join('/')}${gap}${reach}${affectedStr}${fixStr}`
}

/** blindTitle 依赖的本地严重度标签（避免与渲染层塞进同一常量造成双向依赖） */
const LC_BLIND_SEV_LOCAL: Record<string, { label: string }> = {
  heavy: { label: '重度' },
  medium: { label: '中度' },
  light: { label: '轻度' },
}

/** 分类色圆点 Marker 图标（SVG data-URL，避免引入图片资源） */
function dotIcon(bmap: BMapGLNamespace, color: string) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14">` +
    `<circle cx="7" cy="7" r="5.5" fill="${color}" stroke="#ffffff" stroke-width="1.5"/></svg>`
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new bmap.Icon(url, new bmap.Size(14, 14), { anchor: new bmap.Size(7, 7) })
}

/** S2 防御①（⚠️ 真机 spike 已修正其地位，勿再当成主防线）：
 *  2026-09-23 真 GL spike 实测（自建 BMapGL 实例 + 真实鼠标注入）：
 *  · Polyline / Polygon 的事件对象形状 = `{type,target,pixel,pointMC,latLng,isOverlay,point,domEvent,…}`，
 *    其中 **`domEvent` 键存在但值为 undefined** ⇒ 下面这句掐断在圈线/盲区多边形上**永不生效**（死分支）；
 *    Marker 是 DOM 节点，可能仍带 domEvent，故保留此调用（对 Marker 无害且可能有用）。
 *  · **overlay click 必连带派发 map click**（实测同一次点击 map 的 click 监听被触发 1 次）⇒
 *    真正的关卡防线是 `onBlankClick` 里的 **100ms 时间戳守卫**，删掉它卡片会「刚开就被秒关」。 */
function stopDomBubble(e: unknown) {
  try {
    ;(e as { domEvent?: { stopPropagation?: () => void } }).domEvent?.stopPropagation?.()
  } catch {
    /* 事件形状差异不致命 */
  }
}

/** 补点处方符号（C3：绿色加号，白描边 + 绿色十字），与盲区中心点在视觉上明确区分。
 *  SVG 串走 `lib/livingCircle.ts::fixPlusSvg` 单一出口（C4/R7：地图 Marker 与页面图例同源消费），
 *  此处只保留 bmap.Icon 包装（lib 层零 SDK 依赖）。 */
function fixPlusIcon(bmap: BMapGLNamespace, color: string) {
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fixPlusSvg(color))}`
  return new bmap.Icon(url, new bmap.Size(18, 18), { anchor: new bmap.Size(9, 9) })
}

/** 中心标记图标（实心绿点 + 虚线外圈；可拖拽，D2） */
function centerIcon(bmap: BMapGLNamespace) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">` +
    `<circle cx="11" cy="11" r="7" fill="#5F7B69" stroke="#ffffff" stroke-width="2"/>` +
    `<circle cx="11" cy="11" r="10" fill="rgba(95,123,105,0.22)" stroke="#5F7B69" stroke-width="1.2" stroke-dasharray="3 3"/></svg>`
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new bmap.Icon(url, new bmap.Size(22, 22), { anchor: new bmap.Size(11, 11) })
}

/** 热力悬停命中阈值（px）：与旧 DOM Marker title 的悬停半径同一量级 */
const HEAT_HIT_PX = 8

/** 最近热力点命中测试：cursor 像素 vs 各点投影像素，≤ HEAT_HIT_PX 取最近（O(N)，1049 点亚毫秒）。 */
function nearestHeatPoint(
  map: BMapMap,
  bmap: BMapGLNamespace,
  points: HeatSamplePoint[],
  px: number,
  py: number,
  threshold = HEAT_HIT_PX,
): HeatSamplePoint | null {
  let best: HeatSamplePoint | null = null
  let bestD = threshold * threshold
  for (const sp of points) {
    const p = map.pointToPixel(new bmap.Point(sp.lng, sp.lat))
    const dx = p.x - px
    const dy = p.y - py
    const d = dx * dx + dy * dy
    if (d <= bestD) {
      bestD = d
      best = sp
    }
  }
  return best
}

/** 盲区边界显示档位切换（双边界解耦的 raw/smoothed toggle，需求 §二·1 / §7.1.3）。 */
function BoundaryToggle({
  value,
  onChange,
}: {
  value: BlindBoundaryView
  onChange: (v: BlindBoundaryView) => void
}) {
  const opts: { key: BlindBoundaryView; label: string; tip: string }[] = [
    { key: 'smoothed', label: '平滑', tip: '显示圆角边界（默认，用于地图展示）' },
    { key: 'raw', label: '原始', tip: '精确锯齿边界（供严格的点内判断）' },
  ]
  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-ink/10 bg-white/95 px-1 py-0.5 shadow-sm"
      role="group"
      aria-label="盲区边界显示档位"
    >
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          title={o.tip}
          onClick={() => onChange(o.key)}
          aria-pressed={value === o.key}
          className={
            'rounded-full px-3 py-1 text-tag font-medium transition-colors ' +
            (value === o.key ? 'text-white' : 'text-ink-2 hover:bg-ink/5')
          }
          style={value === o.key ? { backgroundColor: '#1677ff' } : undefined}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/**
 * 底图注记披露角标（阶段 0.3）。
 *
 * 为什么必须显式披露：关掉底图 POI 注记后，用户第一反应是「地图上怎么没有商场/地铁名了」。
 * 没有这行字，这个改动会被读成「地图坏了」；有了它，「图上只剩应用数据」变成**可解释的设计**，
 * 也就把 §1 的原始困惑（图上点位与图例不一致）在源头截断。
 *
 * 同一推理对**面层**成立（grand-shoal-moth 步骤 4 补齐）：本项目**不写任何道路规则**
 * （实测写了会把整层打掉，见 `bmapStyle.ts` ⑪），故道路黄/橙是百度原始分级、不是配色事故；
 * 角标补「道路/水系为百度原生渲染」，防评审把它读成「项目配错色」或「地图被简化了」。
 *
 * 数字**与渲染层同源**（阶段 2.1 修正）：
 *  - 设施数取 `poiRenderSet().shown`（**实际画上去的标记数**）。旧实现取
 *    `min(points.length, POI_MARKER_CAP)` —— 一旦渲染层不再按常量截断，那个 `min` 就
 *    变成第三套「设施数」算法（面板一套、点数一套、角标又一套）。
 *  - 采样数取 `samplingReach().timed`，与热力层取数同一判据（契约测试已锁二者相等）。
 *  - 触发网格聚合时追加一行披露（`poiThinNote`），否则读者会以为点丢了。
 */
function MapNoteBadge({
  poiShown,
  heatShown,
  thinNote,
  notesOn,
}: {
  poiShown: number
  heatShown: number
  thinNote?: string | null
  notesOn?: boolean
}) {
  if (notesOn) {
    // 开启态：警示配色 + 第三方声明（第三方设施名/图钉观感与项目 Marker 接近，须显式区分）
    return (
      <div
        className="pointer-events-none absolute bottom-2 right-2 z-10 max-w-[calc(100%-1rem)] rounded-md border border-warn/45 bg-warn/10 px-2 py-1 text-tag font-medium text-[#8A6420] shadow-sm"
        role="note"
        aria-label="底图注记状态：已开启"
      >
        底图注记已开启 · 图中百度设施名 / 图钉为第三方信息，非本项目数据
        {thinNote && <div className="mt-0.5 text-ink-3">{thinNote}</div>}
      </div>
    )
  }
  return (
    <div
      className="pointer-events-none absolute bottom-2 right-2 z-10 max-w-[calc(100%-1rem)] rounded-md border border-ink/10 bg-white/95 px-2 py-1 text-tag font-medium text-ink-2 shadow-sm"
      role="note"
      aria-label="底图注记状态：已关闭"
    >
      底图注记已关闭 · 道路/水系为百度原生渲染 · 图上仅应用数据（设施 {poiShown} · 采样 {heatShown}）
      {thinNote && <div className="mt-0.5 text-ink-3">{thinNote}</div>}
    </div>
  )
}

/** 底图注记开关（需求 A）：右上竖列第一颗 pill；role=switch + aria-checked，默认关。 */
function NotesToggle({ on, onToggle, disabled }: { on: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label="底图注记"
      title={on ? '显示百度第三方设施名（非本项目数据）' : '仅显示应用数据（点击显示第三方设施名）'}
      disabled={disabled}
      onClick={onToggle}
      className={
        'flex items-center gap-1.5 rounded-full border px-3 py-1 text-tag font-medium shadow-sm transition-colors ' +
        (on
          ? 'border-warn/50 bg-warn/10 text-[#8A6420]'
          : 'border-ink/10 bg-white/95 text-ink-2 hover:bg-ink/5') +
        (disabled ? ' cursor-not-allowed opacity-60' : '')
      }
    >
      <span className={'h-1.5 w-1.5 rounded-full ' + (on ? 'bg-[#8A6420]' : 'bg-ink/30')} />
      底图注记 {on ? '开' : '关'}
    </button>
  )
}

const LcMap = forwardRef<LcMapHandle, LcMapProps>(function LcMap(
  { report, customCenter, onCenterChange, draggableCenter = true, compareReport, onMapMode, onIsoHover, onBlindHover },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<BMapMap | null>(null)
  const bmapRef = useRef<BMapGLNamespace | null>(null)
  const overlaysRef = useRef<BMapMapOverlay[]>([])
  const [mode, setMode] = useState<LcMapMode>('boot')
  /** 双边界档位：显示圆角（smoothed）↔ 精确锯齿（raw）。打开/切换后按需重绘覆盖层。 */
  const [boundaryView, setBoundaryView] = useState<BlindBoundaryView>('smoothed')
  const canToggleRaw = (report.blindspots ?? []).some((b) => blindCanRaw(b))
  /** 热力采样点（可达且 minutes 非空）—— 与 HeatFieldOverlay 同源，供 mousemove 命中测试 */
  const heatRef = useRef<HeatSamplePoint[]>([])
  /** 悬停浮层 DOM：ref 直改样式/文案，不经 React 状态 —— 60Hz mousemove 下零重渲染 */
  const tooltipRef = useRef<HTMLDivElement>(null)
  /** 地图级监听（movestart/zoomstart 隐藏浮层）跨 effect 重跑防累积 */
  const mapListenersRef = useRef<{ ev: string; fn: () => void }[]>([])
  const lastMoveTs = useRef(0)

  /* ═══ C1/C2/C5/C6/C7 交互系列（架构审查 R1–R6 + 技术评审 S1–S3 落地）═══ */
  /** 悬停锁：当前持有浮层仲裁权的目标（优先级 补点 > 盲区 > 圈线 > 热力点）。
   *  容器级热力命中（onContainerMove）**必须**看这把锁 —— 面命中或锁不仲裁，
   *  圈内热力点 tooltip 会被静默清零（审查 R2 一票否决项的教训）。 */
  const lockRef = useRef<'ring' | 'blind' | 'fix' | null>(null)
  /** C2：React 固定信息卡（R1 定版：非 InfoWindow——「定位到此」需真实事件绑定） */
  const [isoCard, setIsoCard] = useState<LcIsoCard | null>(null)
  /** S2 防御②：卡片打开时间戳——GL 若把 overlay click 连带派发成 map click（冒泡），
   *  100ms 内的 map click 视为同一次点击，不关卡（点圈后立刻点空白间隔远大于 100ms，不受影响）。 */
  const lastCardOpenAt = useRef(0)
  /** C6：当前 1km 服务范围圈。走 add() 双登记（重绘随 overlaysRef 摘除）+ 独立 ref 供替换/清除。 */
  const fixCircleRef = useRef<BMapMapOverlay | null>(null)
  /** C7：flyTo 起飞前视口快照（Esc 复位锚点；桩缺 getCenter/getZoom 时放弃快照=放弃复位，不影响飞行） */
  const flightRef = useRef<{ center: BMapPoint; zoom: number } | null>(null)

  /** 底图注记开关（需求 A）：全局单一真源，所有 LcMap 实例（地图页 / 对比页 A·B）同步翻转。 */
  const notesOn = useMapNotesStore((s) => s.on)
  /** 地图配置快照（供运行时重发 styleJson，避免重复 getMapConfig）。 */
  const cfgRef = useRef<{ mapStyleId: string } | null>(null)
  /** T1b 过渡态：切换期间遮罩 + 禁用开关，防连点竞态 / 遮罩层叠。 */
  const [transitioning, setTransitioning] = useState(false)
  const transitionTimerRef = useRef<number | null>(null)
  const tilesLoadedFnRef = useRef<(() => void) | null>(null)
  /** 点击开关：过渡期忽略连点（T1b 护栏），否则写 store（subscription 负责重发样式）。 */
  const toggleNotes = () => {
    if (transitioning) return
    useMapNotesStore.getState().set(!notesOn)
  }

  const showTooltip = (px: number, py: number, text: string) => {
    const el = tooltipRef.current
    if (!el) return
    el.textContent = text
    const cw = containerRef.current?.clientWidth ?? 0
    el.style.left = `${Math.min(px + 12, Math.max(0, cw - el.offsetWidth))}px`
    el.style.top = `${py + 12}px`
    el.style.display = 'block'
  }
  const hideTooltip = () => {
    if (tooltipRef.current) tooltipRef.current.style.display = 'none'
  }

  /** C6：清服务圈（地图 + overlaysRef 双摘；无圈时为无害空操作） */
  const clearFixCircle = () => {
    const map = mapRef.current
    const circle = fixCircleRef.current
    if (map && circle) {
      map.removeOverlay(circle)
      overlaysRef.current = overlaysRef.current.filter((o) => o !== circle)
    }
    fixCircleRef.current = null
  }

  /** S1（技术评审）：交互态整体复位。报告重绘会摘掉悬停中的覆盖物 → mouseout 永不派发 →
   *  若不就地复位，锁永久占用 = 热力 tooltip 静默死亡（「响亮失败 → 静默错误」族，审查 R2 教训）。 */
  const resetInteractionState = () => {
    lockRef.current = null
    hideTooltip()
    setIsoCard(null)
    clearFixCircle()
    flightRef.current = null
  }

  /** C7：「◎ 定位到此」。起飞前快照视口（Esc 复位锚点）；GL flyTo 缺桩回退 centerAndZoom。
   *  只读 SDK 视口（getCenter/getZoom 往返同源），无坐标换算 —— S3 白名单纪律天然满足。 */
  const flyToCenter = (target: LngLat) => {
    const map = mapRef.current
    const bmap = bmapRef.current
    if (!map || !bmap) return
    if (!flightRef.current && typeof map.getCenter === 'function' && typeof map.getZoom === 'function') {
      try {
        const c = map.getCenter()
        const zm = map.getZoom()
        if (c && typeof zm === 'number') flightRef.current = { center: c, zoom: zm }
      } catch {
        /* 桩缺失 → 放弃复位锚，不影响飞行本身 */
      }
    }
    const point = new bmap.Point(target[0], target[1])
    try {
      if (typeof map.flyTo === 'function') map.flyTo(point, 16)
      else map.centerAndZoom(point, 16)
    } catch {
      map.centerAndZoom(point, 16)
    }
  }

  /** 容器 mousemove：最近热力点命中（≤8px）→ 浮层 tooltip；未命中/离开 → 隐藏。
   *  节流 ~16ms：高频事件下命中测试 O(N) 投影 + 直改 DOM，无 React 重渲染/分配。
   *  ⚠️ 锁检查在最前（审查 R2）：圈线/盲区/补点持有悬停锁期间，热力命中必须让位 ——
   *  否则新交互会清零这条既有能力（症状转移）。无锁路径行为逐字节不变。 */
  const onContainerMove = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (lockRef.current) return
    const map = mapRef.current
    const bmap = bmapRef.current
    const container = containerRef.current
    const points = heatRef.current
    if (!map || !bmap || !container || !points.length) return
    const now = performance.now()
    if (now - lastMoveTs.current < 16) return
    lastMoveTs.current = now
    const rect = container.getBoundingClientRect()
    if (!(rect.width > 0) || !(rect.height > 0)) return // 未布局（jsdom/隐藏态）不命中
    const hit = nearestHeatPoint(map, bmap, points, e.clientX - rect.left, e.clientY - rect.top)
    if (hit) showTooltip(e.clientX - rect.left, e.clientY - rect.top, `${hit.idx} 号采样点 · 步行 ${hit.minutes}min`)
    else hideTooltip()
  }

  /* 初始化：取 AK/样式配置 → 注入 BMapGL → 建图 + 个性化底图样式；失败降级静态画布 */
  useEffect(() => {
    let disposed = false
    let container: HTMLDivElement | null = null
    ;(async () => {
      const cfg = await getMapConfig()
      cfgRef.current = cfg
      if (disposed) return
      if (!cfg.browserAk) {
        setMode('fallback')
        return
      }
      try {
        const bmap = await loadBMapGL(cfg.browserAk)
        if (disposed || !containerRef.current) return
        container = containerRef.current
        const map = new bmap.Map(container, { zoom: 15, enableHighResZoom: true })
        map.enableScrollWheelZoom()
        // C7 底图风格（阶段 0.2 / 决策 D4）：**内置模板优先**，因为「关掉底图 POI 注记」
        // 是数据可信度纪律而非配色偏好 —— 第三方设施名与我们的 Marker 同款呈现，会被读成
        // 自家数据。styleId 由后端默认不下发（见 `life_circle_map_config()`）；
        // `setMapStyleV2` 的 `styleId` 与 `styleJson` 互斥二选一，故这里也只可能生效一个。
        // 需求 A（R1）：挂载即读 store，否则刷新后已持久化的 notesOn=true 因初始值未变不触发
        // 运行时效应 ⇒ 刷新丢偏好。与运行时切换共用 `lcMapStyle` 单一出口。
        map.setMapStyleV2(cfg.mapStyleId ? { styleId: cfg.mapStyleId } : { styleJson: lcMapStyle(useMapNotesStore.getState().on) })
        mapRef.current = map
        bmapRef.current = bmap
        setMode('live')
      } catch {
        if (!disposed) setMode('fallback')
      }
    })()
    return () => {
      disposed = true
      mapRef.current = null
      bmapRef.current = null
      overlaysRef.current = []
      mapListenersRef.current = []
    }
  }, [])

  /* 需求 A · 运行时注记切换：订阅 store → 对同一地图实例重发 styleJson。
     与挂载下发共用 `lcMapStyle` 单一出口；styleId 分支下开关无效（百度 styleId/styleJson
     互斥），直接跳过，由后端控制台样式全权决定底图。 */
  useEffect(() => {
    const apply = (on: boolean) => {
      const map = mapRef.current
      const cfg = cfgRef.current
      if (!map || !cfg || cfg.mapStyleId) return
      // T1b 过渡遮罩：开遮罩 + 3000ms 兜底移除（tilesloaded 命中即提前移除），防遮罩永久盖图
      if (tilesLoadedFnRef.current && typeof map.removeEventListener === 'function') {
        map.removeEventListener('tilesloaded', tilesLoadedFnRef.current)
      }
      setTransitioning(true)
      if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
      const finish = () => {
        if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
        transitionTimerRef.current = null
        setTransitioning(false)
      }
      transitionTimerRef.current = window.setTimeout(finish, 3000)
      const onLoaded = () => {
        if (typeof map.removeEventListener === 'function') {
          map.removeEventListener('tilesloaded', onLoaded)
        }
        tilesLoadedFnRef.current = null
        finish()
      }
      tilesLoadedFnRef.current = onLoaded
      map.addEventListener?.('tilesloaded', onLoaded)
      map.setMapStyleV2({ styleJson: lcMapStyle(on) })
    }
    const unsub = useMapNotesStore.subscribe((s) => apply(s.on))
    return () => {
      unsub()
      if (tilesLoadedFnRef.current && mapRef.current && typeof mapRef.current.removeEventListener === 'function') {
        mapRef.current.removeEventListener('tilesloaded', tilesLoadedFnRef.current)
      }
      if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
    }
  }, [])

  /* 覆盖层绘制：等时圈/盲区/POI/中心标记（真实态） */
  useEffect(() => {
    const map = mapRef.current
    const bmap = bmapRef.current
    if (mode !== 'live' || !map || !bmap) return

    // 摘掉上一次 effect 挂的地图级监听（防跨渲染累积）；本次按需重挂
    for (const { ev, fn } of mapListenersRef.current) map.removeEventListener?.(ev, fn)
    mapListenersRef.current = []

    overlaysRef.current.forEach((o) => map.removeOverlay(o))
    overlaysRef.current = []
    // S1（技术评审）：重绘摘掉了悬停中的覆盖物 → mouseout 永不派发 → 锁/卡/服务圈必须就地复位
    resetInteractionState()
    const add = (o: BMapMapOverlay) => {
      map.addOverlay(o)
      overlaysRef.current.push(o)
    }
    const pt = (lnglat: LngLat): BMapPoint => new bmap.Point(lnglat[0], lnglat[1])

    const center: LngLat = customCenter ?? report.scene.center
    const reports = compareReport ? [report, compareReport] : [report]
    const colorSets = compareReport ? [LC_ISO_COLORS, LC_ISO_COLORS_B] : [LC_ISO_COLORS]
    // 阶段 2：POI 渲染点集唯一取数口（与降级画布/报告页快照同一份 reps）
    const set = poiRenderSet(report.poi.points)

    // 采样点耗时热力（延迟优化 C：HeatFieldOverlay 单 Canvas 覆盖层替代逐点 DOM Marker）
    // 根因是渲染原语错配：BMapGL Marker 是 DOM 节点，千级量级同步渲染 2-4s（live 步行
    // 1049 点）；Canvas 是密度无关解（O(N) 原生绘制 ~2ms/帧）。仅主报告、非对比模式；
    // 悬停交互由容器 mousemove 命中测试承担（onContainerMove），视觉契约零变化。
    if (!compareReport) {
      // 热力点 = 所有**已测时**的点（不是「仅可达」的点）—— 渲染行为与改名前一致：
      // 旧字段 reachable 的语义本就是 minutes!=null。取数走 `heatSamplePoints()` 单一入口，
      // 内含历史快照回退（老点无 `timed` ⇒ 按 minutes 非空判定），否则库里 25 份
      // 历史报告的热力层会被静默清空。
      const heatPoints: HeatSamplePoint[] = heatSamplePoints(report)
      heatRef.current = heatPoints
      const heatField = new HeatFieldOverlay(bmap)
      heatField.setPoints(heatPoints)
      add(heatField)
    } else {
      heatRef.current = []
    }

    // 等时圈族（A 绿系 / B 蓝系）
    // ① 色阶必须与分钟数绑定（5min 最深 → 20min 最浅），与降级 SVG 画布一致；
    //    不可 sort(b-a) 后再取 colors[zi]——那会把最深色给 20min 圈，色阶倒挂。
    // ② 绘制顺序「大圈先、小圈后」：小圈叠在大圈之上，嵌套累积出热力观感。
    // ③ fillOpacity 取自色表声明的 alpha（BMapGL 不认 fillColor 里的 rgba 透明度）。
    const fitPts: BMapPoint[] = []
    /* ═══ C1/C2/C3：圈线交互 ═══
       命中层 = 沿环线的透明加宽 Polyline（审查 R2 定版）：只占圈线附近 ~14px 条带，
       圈内热力点 tooltip（onContainerMove）不受影响 —— 面命中会让悬停锁盖住整个可达区（一票否决项）。

       ⚠️ 真机 spike 实测（2026-09-23：自建 BMapGL + 真实鼠标注入，非 mock）：
       ① 透明描边**可以拾取**：weight 14 配 strokeOpacity 0.01 与 0 **都能**正常触发
          mouseover/mousemove/click ⇒ 保留 0.01（肉眼不可见，对将来「像素 alpha 拾取」留余量）。
       ② **面填充同样可拾取**，且与压在它上面的命中线在**同一次悬停里同时触发**
          ⇒ 等时圈 Polygon **绝对不得挂 hover 处理器**（等于把锁铺满整个可达区，圈内热力 tooltip 被静默清零）。
       ③ `e.pixel` = **容器内像素坐标**（实测与注入坐标逐像素相等）⇒ showTooltip 直接用 pixel 定位成立；
          `e.latLng` 为 BD-09 经纬度（白名单外的 `e.point` 是投影平面坐标，勿用）。 */
    const isoPolys: {
      poly: BMapMapOverlay & {
        setStrokeWeight?(w: number): void
        setStrokeOpacity?(o: number): void
        setFillOpacity?(o: number): void
      }
      baseFillOp: number
      ri: number
    }[] = []
    const restoreRing = (it: (typeof isoPolys)[number]) => {
      it.poly.setStrokeWeight?.(1.5)
      it.poly.setStrokeOpacity?.(1)
      it.poly.setFillOpacity?.(it.baseFillOp)
    }
    /* 高亮仲裁（**与预览 setHighlight 同口径**——预览即实装口径）：
       ① 本圈：描边加粗 3.5 + 填充 +0.15（封顶 0.65）；
       ② 其余圈：淡化（填充 ×0.3、描边不透明度 0.35）—— ⚠️ **单报告模式同样淡化**。
          此前只在对比模式淡化，单报告下悬停一圈时其余圈毫无变化，「正在看哪一圈」无从判断
          （预览里一直是淡化的，实装漏了这一档 = 预览/实装口径分歧）。
       ③ 对比模式另加一档：另一份报告的圈压到 0.28（缺口 G1 定版，A/B 两侧要能一眼分开）。 */
    const DIM_SAME_FILL = 0.3
    const DIM_SAME_STROKE = 0.35
    const DIM_CROSS = 0.28
    const dimRings = (activeRi: number | null, activePoly: (typeof isoPolys)[number]['poly'] | null) => {
      for (const it of isoPolys) {
        if (activePoly == null) {
          restoreRing(it)
          continue
        }
        const isSelf = it.poly === activePoly
        const cross = compareReport != null && it.ri !== activeRi
        const fillK = cross ? DIM_CROSS : DIM_SAME_FILL
        const strokeK = cross ? DIM_CROSS : DIM_SAME_STROKE
        if (isSelf) {
          it.poly.setStrokeWeight?.(3.5)
          it.poly.setStrokeOpacity?.(1)
          it.poly.setFillOpacity?.(Math.min(0.65, it.baseFillOp + 0.15))
        } else {
          it.poly.setStrokeWeight?.(1.5)
          it.poly.setStrokeOpacity?.(strokeK)
          it.poly.setFillOpacity?.(it.baseFillOp * fillK)
        }
      }
    }
    reports.forEach((lc, ri) => {
      const colors = colorSets[ri] ?? LC_ISO_COLORS
      const ramp = [...lc.isochrones]
        .sort((a, b) => a.minutes - b.minutes)
        .map((z, i) => ({ z, c: colors[i % colors.length] ?? colors[0] }))
      for (const { z, c } of [...ramp].reverse()) {
        const ring = z.geojson.coordinates[0] ?? []
        const pts = ring.map((p) => pt([p[0], p[1]]))
        fitPts.push(...pts)
        const fill = lcFillSpec(c.fill)
        const poly = new bmap.Polygon(pts, {
          strokeColor: c.stroke,
          fillColor: fill.color,
          strokeWeight: 1.5,
          fillOpacity: fill.opacity,
          strokeOpacity: 1,
          strokeStyle: 'solid',
        })
        add(poly)
        const entry: (typeof isoPolys)[number] = { poly, baseFillOp: fill.opacity, ri }
        isoPolys.push(entry)
        /* 命中线：桩/SDK 缺 Polyline 时跳过（S6 mock 兼容纪律——能力降级，不炸渲染） */
        if (typeof bmap.Polyline === 'function') {
          const hit: BMapPolyline = new bmap.Polyline(pts, {
            strokeColor: '#000000',
            strokeWeight: 14,
            strokeOpacity: 0.01,
            cursor: 'pointer',
          })
          add(hit)
          const tag = compareReport ? (ri === 0 ? 'A' : 'B') : null
          const tipText = `${tag ? `${tag} 区 · ` : ''}${z.minutes}min 等时圈 · 面积 ${z.area_km2.toFixed(2)} km²`
          hit.addEventListener?.('mouseover', () => {
            lockRef.current = 'ring'
            dimRings(compareReport ? ri : null, poly)
            if (!compareReport) onIsoHover?.(z.minutes) // C8（R6：挂 over/out 不挂 move）
          })
          hit.addEventListener?.('mousemove', (e) => {
            // 浮层坐标来源：e.pixel（容器像素，BMapOverlayEvent 白名单字段）；取不到就让 tooltip 留原位
            if (e.pixel) showTooltip(e.pixel.x, e.pixel.y, tipText)
          })
          hit.addEventListener?.('mouseout', () => {
            if (lockRef.current === 'ring') lockRef.current = null
            hideTooltip()
            dimRings(null, null)
            if (!compareReport) onIsoHover?.(null)
          })
          hit.addEventListener?.('click', (e) => {
            stopDomBubble(e) // S2 防御①：对 Polyline 实测为死分支（见函数注释），主防线是 100ms 守卫
            lastCardOpenAt.current = performance.now()
            setIsoCard({
              title: `${tag ? `${tag} 区 · ` : ''}${z.minutes}min 等时圈`,
              blue: tag === 'B',
              fly: lc.scene.center,
              rows: [
                ['面积', `${z.area_km2.toFixed(2)} km²`],
                ['全域可达采样（≤20min）', String(samplingReach(lc).inReach)],
                ['可达口径', `步行 · ≤${samplingReach(lc).reachFullMin} 分钟`],
              ],
            })
          })
        }
      }
    })

    // 盲区：连续缺口热力填充（C1）+ 严重度语义色描边/标号（C2）+ 补点处方（C3）+ 详情（C4）。仅主报告。
    if (!compareReport) {
      report.blindspots.forEach((b, bi) => {
        const ring = blindPolygonOf(b, boundaryView)?.coordinates?.[0] ?? []
        const pts = ring.map((p) => pt([p[0], p[1]]))
        fitPts.push(...pts)
        const sev = severityOf(b)
        const spec = blindSevSpec(sev || undefined)
        const gap = gapScoreOf(b)
        const heatFill = lcFillSpec(blindHeatFill(gap))
        const title = `${blindTitle(b)}${
          b.reach?.isochrone_based ? ' · 真实可达据实测等时圈' : ' · 未见实测等时圈'
        }`
        const blindPoly = new bmap.Polygon(pts, {
          strokeColor: gap == null ? '#8a8a8a' : spec.stroke,
          fillColor: heatFill.color,
          strokeWeight: 1.2,
          fillOpacity: heatFill.opacity,
          strokeStyle: gap == null ? 'dashed' : 'solid',
        })
        add(blindPoly)
        /* ═══ C5：盲区交互（悬停锁 + 浮层 + 卡片；C8 严重度联动）═══ */
        const openBlindCard = (e: BMapOverlayEvent) => {
          stopDomBubble(e) // S2 防御①：多边形上实测不生效；Marker 分支可能生效
          lastCardOpenAt.current = performance.now()
          const fx = fixesOf(b) as BlindSpot['fixes']
          const aff = affectedOf(b) as BlindSpot['affected']
          setIsoCard({
            title: blindTitle(b),
            fly: b.center,
            rows: [
              ['缺失设施', (b.missing_facilities ?? []).join(' / ') || '—'],
              ['缺口指数', gap != null ? String(gap) : '—'],
              [
                '真实可达',
                b.reach?.real_walk_min != null
                  ? `步行 ${b.reach.real_walk_min}min${b.reach.isochrone_based ? '（实测）' : '（估算）'}`
                  : '—',
              ],
              [
                '受影响',
                aff?.sampling_sites != null ? `采样 ${aff.sampling_sites} 点 · 估 ${aff.estimated_residents} 人` : '—',
              ],
              [
                '补点处方',
                (fx ?? [])
                  .map((f) => `补${f.facility} · ${LC_BLIND_FIX_STRATEGY[f.strategy] ?? f.strategy} · P${f.priority}`)
                  .join('；') || '—',
              ],
            ],
          })
        }
        const toSev = () => (sev === 'heavy' || sev === 'medium' || sev === 'light' ? sev : null)
        blindPoly.addEventListener?.('mouseover', () => {
          lockRef.current = 'blind'
          onBlindHover?.(toSev())
        })
        blindPoly.addEventListener?.('mousemove', (e) => {
          if (e.pixel) showTooltip(e.pixel.x, e.pixel.y, title)
        })
        blindPoly.addEventListener?.('mouseout', () => {
          if (lockRef.current === 'blind') lockRef.current = null
          hideTooltip()
          onBlindHover?.(null)
        })
        blindPoly.addEventListener?.('click', openBlindCard)
        // 中心标号（C2：`#N · 重度` —— 严重度语义 + 序号，评分基线用）。
        // R3（审查）：原生 title 已移除——悬停统一走上方 DOM tooltip，防「DOM 浮层 + 原生气泡」双浮层。
        const centerMarker = new bmap.Marker(pt(b.center), {
          icon: dotIcon(bmap, spec.dot),
        })
        centerMarker.addEventListener?.('mouseover', () => {
          lockRef.current = 'blind'
          onBlindHover?.(toSev())
        })
        centerMarker.addEventListener?.('mousemove', (e) => {
          if (e.pixel) showTooltip(e.pixel.x, e.pixel.y, title)
        })
        centerMarker.addEventListener?.('mouseout', () => {
          if (lockRef.current === 'blind') lockRef.current = null
          hideTooltip()
          onBlindHover?.(null)
        })
        centerMarker.addEventListener?.('click', openBlindCard)
        add(centerMarker)
        // 编号文本批注（C2）：BMapGL 用 Label 叠加 "N·重度"
        if (gap != null) {
          add(
            new bmap.Label(`#${bi + 1}·${spec.label}`, {
              position: pt(b.center),
              offset: new bmap.Size(8, -6),
              styles: {
                color: '#3a2c00',
                fontSize: '11px',
                fontWeight: '600',
                background: 'rgba(255,255,255,0.85)',
                border: 'none',
                borderRadius: '6px',
                padding: '1px 5px',
              },
            }),
          )
        }
        // 补点处方（C3：绿核白边 Marker），仅当存在 fixes。
        // R3（审查）：原生 title 移除 → DOM tooltip（下方 mouseover），防双浮层。
        ;(b.fixes ?? []).forEach((fix) => {
          const strategy = LC_BLIND_FIX_STRATEGY[fix.strategy] ?? fix.strategy
          const fixTip = `补${fix.facility} · ${strategy} · P${fix.priority} · 覆盖 ${fix.served ?? '?'} 格`
          const fixMarker = new bmap.Marker(pt(fix.point), {
            icon: fixPlusIcon(bmap, LC_FIX_DOT),
          })
          fixMarker.addEventListener?.('mouseover', () => {
            lockRef.current = 'fix'
          })
          fixMarker.addEventListener?.('mousemove', (e) => {
            if (e.pixel) showTooltip(e.pixel.x, e.pixel.y, fixTip)
          })
          fixMarker.addEventListener?.('mouseout', () => {
            if (lockRef.current === 'fix') lockRef.current = null
            hideTooltip()
          })
          fixMarker.addEventListener?.('click', (e) => {
            stopDomBubble(e) // S2 防御①：Marker 上可能生效；主防线仍是 100ms 守卫
            lastCardOpenAt.current = performance.now()
            // C6：1km 服务范围虚线圆（半径米）——先清旧圈（替换语义，缺口 G4：同点再击=toggle 由
            // 空白点击/移出后重复点击的「先清后画」天然实现），再 add() 双登记（重绘随 overlaysRef 摘除）。
            clearFixCircle()
            if (typeof bmap.Circle === 'function') {
              const circle = new bmap.Circle(pt(fix.point), 1000, {
                strokeColor: LC_FIX_DOT,
                strokeWeight: 1.6,
                strokeOpacity: 0.9,
                fillColor: LC_FIX_DOT,
                fillOpacity: 0.07,
                strokeStyle: 'dashed',
              })
              add(circle)
              fixCircleRef.current = circle
            }
            setIsoCard({
              title: `补点处方 · 补${fix.facility}`,
              fly: fix.point,
              rows: [
                ['建议设施', fix.facility],
                ['策略', strategy],
                ['优先级', `P${fix.priority}`],
                ['可覆盖盲区格', String(fix.served ?? '?')],
                ['依据', '簇质心 1km 内缺失该要素'],
              ],
            })
          })
          add(fixMarker)
        })
      })
    }

    // POI 真实坐标 Marker（仅主报告、非对比模式；旧快照 points 为空则跳过）
    // 阶段 2.1：**删掉 `POI_MARKER_CAP=120`** —— 报告给几个点就画几个点。
    // 取数走 `poiRenderSet()`（阶段 2.4）：常规量级原样全画，仅当点数超阈值时按地理网格
    // 聚合显示，且聚合结果与两处 SVG 画布**逐点一致**（同一份 reps）。
    if (!compareReport && set.reps.length) {
      set.reps.forEach((p) => {
        const color = LC_CAT_COLOR[p.category] ?? '#7c6670'
        const n = set.counts.get(p.id) ?? 1
        const marker = new bmap.Marker(pt(p.lnglat), {
          icon: dotIcon(bmap, color),
          title:
            `${p.name} · ${LC_CAT_LABEL_OF(p.category)}${p.minutes != null ? ` · ${p.minutes}min` : ' · 不可达'}` +
            (n > 1 ? ` · 该网格聚合 ${n} 点` : ''),
        })
        marker.addEventListener('click', () => {
          const win = new bmap.InfoWindow(
            `<div style="font-size:12px;line-height:1.6"><b>${p.name}</b><br/>` +
              `${LC_CAT_LABEL_OF(p.category)} · ${p.minutes != null ? `步行 ${p.minutes}min` : '不可达'}` +
              `${p.in_circle ? ' · 圈内' : ' · 圈外'}${n > 1 ? `<br/>该网格聚合 ${n} 个点位` : ''}</div>`,
            { width: 170 },
          )
          map.openInfoWindow(win, pt(p.lnglat))
        })
        add(marker)
      })
    }

    // 中心标记（可拖拽，D2：拖后仅就地更新，确认才触发体检）
    const cm = new bmap.Marker(pt(center), {
      icon: centerIcon(bmap),
      title: report.scene.name,
      enableDragging: draggableCenter,
    })
    if (draggableCenter) {
      cm.addEventListener('dragend', (e) => {
        // ⚠️ 这里原先是 `e.point.lng/lat`。BMapGL 拖拽事件的 `point` 是**投影平面坐标**
        // （像素/墨卡托米，量级 1e6），不是 BD-09 经纬度 —— 实测标本 (11440230.81,
        // 2860409.52) 被当经纬度后地图中心落到北极圈，且该值会经 API 落库、永久复现。
        //
        // 权威来源有两个，任一即正确：事件上的 `latLng`，或 `marker.getPosition()`。
        // 两者都取不到就**不采纳**（宁可不动，也不写入坏中心）。
        //
        // 注意「值域闸」挡不住这类错误：`e.point` 若被某处取模包裹，会落进合法值域
        // （`|lng|<=180, |lat|<=90`）变成「值合法、语义全错」。故**采纳来源必须白名单**，
        // 值域校验只是第二道闸 —— 下面两条分支按来源严格分流。
        const src = e.latLng ?? e.target?.getPosition?.()
        const next = src
          ? asBdLngLatOrNull(toDiagPair(src), 'LcMap.centerMarker.dragend')
          : e.point
            ? rejectBdLngLatSource(
                toDiagPair(e.point),
                'LcMap.centerMarker.dragend',
                '拖拽事件只提供了 e.point（百度墨卡托平面米 / 像素），它不是 BD-09 经纬度；请改用 e.latLng 或 marker.getPosition()',
              )
            : rejectBdLngLatSource(null, 'LcMap.centerMarker.dragend', '拖拽事件未携带任何坐标字段（latLng / getPosition 均缺失）')
        if (next) onCenterChange?.(next)
      })
    }
    add(cm)

    // 平移/缩放时隐藏浮层（点位像素已变，旧 tooltip 位置失真）+ 清悬停锁（R2 兜底：拖图不该
    // 让锁残留——覆盖物像素已随视图移动，锁指向的目标已失真）；与 HeatFieldOverlay
    // 重绘订阅同一事件面（movestart/zoomstart），互不依赖。
    if (typeof map.addEventListener === 'function') {
      const hide = () => {
        hideTooltip()
        lockRef.current = null
      }
      for (const ev of ['movestart', 'zoomstart'] as const) {
        map.addEventListener(ev, hide)
        mapListenersRef.current.push({ ev, fn: hide })
      }
      // S2（技术评审）：live 模式的「点空白关卡」。降级画布的 onCanvasClick 不覆盖 live；
      // 防御②：GL 若把 overlay click 连带派发成 map click（冒泡），卡片打开后 100ms 内的
      // map click 视为同一次点击不关卡（配合 overlay handler 的 domEvent 掐断双保险）。
      const onBlankClick = () => {
        if (performance.now() - lastCardOpenAt.current < 100) return
        setIsoCard(null)
        clearFixCircle()
      }
      map.addEventListener('click', onBlankClick)
      mapListenersRef.current.push({ ev: 'click', fn: onBlankClick })
    }

    if (compareReport) {
      const all = fitPts.length ? fitPts : [pt(center), pt(compareReport.scene.center)]
      map.setViewport(all)
    } else {
      map.centerAndZoom(pt(center), 15)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, report, compareReport, customCenter, draggableCenter, boundaryView])

  useEffect(() => {
    onMapMode?.(mode)
  }, [mode, onMapMode])

  /* ═══ C7：Esc = 关卡 / 清服务圈 / 复位视图（一次完成当前存在的层，与预览同语义）═══
     R5 三守卫（技术评审）：① unmount 清理（本 effect return）；② 可编辑元素聚焦时 Esc 是输入
     语义，不劫持；③ 双实例自治——状态全读本实例 ref/state，不碰全局。 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (isoCard) setIsoCard(null)
      clearFixCircle()
      const map = mapRef.current
      const snap = flightRef.current
      if (snap && map?.centerAndZoom) {
        map.centerAndZoom(snap.center, snap.zoom)
        flightRef.current = null
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isoCard])

  /* 定位到我（顶部按钮调用）：live 用 BMapGL（WGS84→BD09+逆地理）；降级用原生定位裸坐标 */
  useImperativeHandle(
    ref,
    () => ({
      locate: async () => {
        const bmap = bmapRef.current
        if (bmap) {
          const hit = await geolocateMe(bmap)
          if (!hit) return null
          // BMapGL Geolocation 已做 WGS-84→BD-09，但仍过一道值域闸（防 SDK 变更后静默坏值）
          const lnglat = asBdLngLat(hit.lnglat, 'LcMap.locate.bmapgl')
          return { lnglat, name: hit.name, coordSys: hit.coordSys }
        }
        return new Promise((resolve) => {
          if (!navigator.geolocation) {
            resolve(null)
            return
          }
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              const { longitude, latitude } = pos.coords
              // ⚠️ 浏览器原生定位是 **WGS-84**，与 BD-09 相差约 600m（量级与 15 分钟生活圈同阶）。
              // 这里**不伪装**成 BD-09：如实标注 coordSys='wgs84'，由调用方决定是否让后端 geoconv 转换。
              // 旧实现把它当 BD-09 直接发起体检 ⇒ 中心静默偏 600m。
              const lnglat = asBdLngLat([longitude, latitude], 'LcMap.locate.navigator')
              resolve({ lnglat, name: '当前位置（WGS-84 原始坐标，提交时由服务端转 BD-09）', coordSys: 'wgs84' })
            },
            () => resolve(null),
            { timeout: 8000, maximumAge: 30000 },
          )
        })
      },
    }),
    [],
  )

  /* 降级静态画布（评审无网 / 无 AK 可用；图例与右栏由页面提供） */
  if (mode === 'fallback') {
    const center: LngLat = customCenter ?? report.scene.center
    const isoZones = report.isochrones
    const secondary = compareReport
    // 与 live 路径同一份点集（阶段 2.2：原 `cap=60` 与 live 的 120 口径不一，两图点数会打架）
    const poiSet = poiRenderSet(report.poi.points)
    const onCanvasClick = (e: ReactMouseEvent<SVGSVGElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      // ⚠️ rect 为 0×0 时（尚未布局 / 被 display:none 隐藏 / 无布局引擎的环境），
      // 下面的除法会得到 Infinity 或 NaN，并把「算出来的坏坐标」当合法值传出。
      // 这不是假想场景：jsdom 下每次点击都如此。拦在源头，而不是让它流进值域闸。
      if (!(rect.width > 0) || !(rect.height > 0)) {
        rejectBdLngLatSource(
          [rect.width, rect.height],
          'LcMap.fallbackCanvas.click',
          `画布尺寸为 ${rect.width}×${rect.height}，点击位置无法映射为坐标（除零），本次点击已忽略`,
        )
        return
      }
      const px = ((e.clientX - rect.left) / rect.width) * LC_CANVAS.W
      const py = ((e.clientY - rect.top) / rect.height) * LC_CANVAS.H
      const mx = ((px - LC_CANVAS.W / 2) / (LC_CANVAS.W / 2)) * LC_CANVAS.R
      const my = ((LC_CANVAS.H / 2 - py) / (LC_CANVAS.H / 2)) * LC_CANVAS.R
      const dLat = my / 111320
      const dLng = mx / (111320 * Math.cos((center[1] * Math.PI) / 180))
      // 这是**算出来的** BD-09（中心 + 米偏移反投影），仍需过值域闸：
      // R 派生自 study_radius_m 后若失控，算出的点会越界，此处是最后一道网。
      const next = asBdLngLatOrNull([center[0] + dLng, center[1] + dLat], 'LcMap.fallbackCanvas.click')
      if (next) onCenterChange?.(next)
    }
    return (
      <div className="relative h-full w-full">
        <svg viewBox={`0 0 ${LC_CANVAS.W} ${LC_CANVAS.H}`} className="block w-full cursor-crosshair select-none" role="img" aria-label="生活圈等时圈画布（降级）" onClick={onCanvasClick}>
          <rect x={0} y={0} width={LC_CANVAS.W} height={LC_CANVAS.H} fill="#f9faf8" />
          {[-2, -1, 0, 1, 2].map((i) => (
            <line key={`v${i}`} x1={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y1={0} x2={LC_CANVAS.W / 2 + (i * LC_CANVAS.W) / 5} y2={LC_CANVAS.H} stroke="#e7ebe7" strokeWidth={1} />
          ))}
          {[-2, -1, 0, 1, 2].map((i) => (
            <line key={`h${i}`} x1={0} y1={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} x2={LC_CANVAS.W} y2={LC_CANVAS.H / 2 + (i * LC_CANVAS.H) / 5} stroke="#e7ebe7" strokeWidth={1} />
          ))}

          {isoZones.map((z, zi) => {
            const ring = z.geojson.coordinates[0] ?? []
            const [lx, ly] = lcRightmost(center, ring)
            return (
              <g key={z.minutes}>
                <polygon points={lcPolyPts(center, ring)} fill={LC_ISO_COLORS[zi % LC_ISO_COLORS.length]?.fill} stroke={LC_ISO_COLORS[zi % LC_ISO_COLORS.length]?.stroke} strokeWidth={1.5} strokeLinejoin="round" />
                <text x={lx - 4} y={ly - 6} fontSize={12} fill="#5F7B69" textAnchor="end" fontWeight={600}>
                  {z.minutes} min
                </text>
              </g>
            )
          })}

          {secondary &&
            secondary.isochrones.map((z, zi) => {
              const ring = z.geojson.coordinates[0] ?? []
              const c = LC_ISO_COLORS_B[zi % LC_ISO_COLORS_B.length]
              return (
                <polygon key={`b-${z.minutes}`} points={lcPolyPts(center, ring)} fill={c.fill} stroke={c.stroke} strokeWidth={1.5} strokeLinejoin="round" />
              )
            })}

          {!secondary &&
            report.blindspots.map((b, bi) => {
              const sev = severityOf(b)
              const spec = blindSevSpec(sev || undefined)
              const gap = gapScoreOf(b)
              const ring = blindPolygonOf(b, boundaryView)?.coordinates?.[0] ?? []
              const [cx, cy] = lcToPx(center, b.center[0], b.center[1])
              return (
                <g key={b.id}>
                  <polygon
                    points={lcPolyPts(center, ring)}
                    fill={blindHeatFill(gap)}
                    stroke={gap == null ? '#8a8a8a' : spec.stroke}
                    strokeWidth={1.2}
                    strokeDasharray={gap == null ? '5 4' : undefined}
                  >
                    <title>{blindTitle(b)}</title>
                  </polygon>
                  <circle cx={cx} cy={cy} r={5} fill={spec.dot} stroke="#fff" strokeWidth={1.5}>
                    <title>{blindTitle(b)}</title>
                  </circle>
                  {gap != null && (
                    <g>
                      <rect x={cx + 7} y={cy - 20} rx={6} width={26} height={15} fill="rgba(255,255,255,0.88)" />
                      <text x={cx + 20} y={cy - 9} fontSize={10} fill="#3a2c00" textAnchor="middle" fontWeight={600}>
                        #{bi + 1}·{spec.label}
                      </text>
                    </g>
                  )}
                  {(b.fixes ?? []).map((fix, fi) => {
                    const [fx, fy] = lcToPx(center, fix.point[0], fix.point[1])
                    const strategy = LC_BLIND_FIX_STRATEGY[fix.strategy] ?? fix.strategy
                    return (
                      <g key={`fix-${b.id}-${fi}`}>
                        <circle cx={fx} cy={fy} r={6.5} fill="rgba(31,158,99,0.18)" stroke="#1f9e63" strokeWidth={1} />
                        <path d={`M${fx - 4} ${fy} H${fx + 4} M${fx} ${fy - 4} V${fy + 4}`} stroke={LC_FIX_DOT} strokeWidth={2} strokeLinecap="round">
                          <title>{`补${fix.facility} · ${strategy} · P${fix.priority} · 覆盖 ${fix.served ?? '?'} 格`}</title>
                        </path>
                      </g>
                    )
                  })}
                </g>
              )
            })}

          {/* 采样点耗时热力（降级画布亦保留，评审 40% 热力图口径不因无 AK 丢失） */}
          {!secondary &&
            heatSamplePoints(report, 300).map((sp) => {
                const [hx, hy] = lcToPx(center, sp.lng, sp.lat)
                return <circle key={`heat-${sp.idx}`} cx={hx} cy={hy} r={2.6} fill={minuteHeatColor(sp.minutes)} opacity={0.55} />
              })}

          {!secondary &&
            lcSnapshotPoiLayer(center, poiSet.reps, Number.POSITIVE_INFINITY, poiSet.counts).map((p) => (
              <circle key={p.key} cx={p.cx} cy={p.cy} r={5} fill={p.fill} stroke="#fff" strokeWidth={1.2} opacity={0.92}>
                {p.title && <title>{p.cluster > 1 ? `${p.title}（该网格聚合 ${p.cluster} 点）` : p.title}</title>}
              </circle>
            ))}

          {(() => {
            const [x, y] = lcToPx(center, center[0], center[1])
            return (
              <g>
                <circle cx={x} cy={y} r={14} fill="rgba(124,152,133,0.18)" stroke="#5F7B69" strokeWidth={1.5} strokeDasharray="3 3" />
                <circle cx={x} cy={y} r={6} fill="#5F7B69" stroke="#fff" strokeWidth={2} />
                <text x={x} y={y - 20} fontSize={12} fill="#3f5042" textAnchor="middle" fontWeight={600}>
                  {report.scene.name}
                </text>
              </g>
            )
          })()}
        </svg>
        <div className="absolute right-2 top-2 z-10 flex flex-col items-end gap-1">
          <div className="rounded-chip border border-warn/50 bg-warn/10 px-2.5 py-1 text-tag font-medium text-ink-2">
            地图降级 · 静态画布（无 AK / 离线）
          </div>
          {canToggleRaw && <BoundaryToggle value={boundaryView} onChange={setBoundaryView} />}
        </div>
        {/* 阶段 2.4：聚合是**渲染层行为**，必须在图面披露（否则读者会把「少画了几个」
            读成「数据少了」）。与 live 角标同一份 `poiThinNote` 文案。 */}
        {poiThinNote(poiSet) && (
          <div className="pointer-events-none absolute bottom-2 right-2 rounded-md border border-ink/10 bg-white/95 px-2 py-1 text-tag font-medium text-ink-3 shadow-sm">
            {poiThinNote(poiSet)}
          </div>
        )}
      </div>
    )
  }

  /* 角标数字（阶段 0.3 / 2.1）：与渲染层取数同源 —— 设施数取**实际画上去的标记数**、
     采样数取 timed 口径，聚合时另附披露 */
  const badgeSet = compareReport ? null : poiRenderSet(report.poi.points)
  const badgePoiShown = badgeSet ? badgeSet.shown : 0
  const badgeHeatShown = compareReport ? 0 : samplingReach(report).timed
  const badgeThinNote = badgeSet ? poiThinNote(badgeSet) : null

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        className="h-full w-full"
        role="img"
        aria-label="生活圈真实地图"
        data-lc-map="true"
        onMouseMove={onContainerMove}
        onMouseLeave={hideTooltip}
      />
      <div
        ref={tooltipRef}
        style={{ display: 'none' }}
        className="pointer-events-none absolute z-10 max-w-[220px] rounded-md border border-ink/10 bg-white/95 px-2 py-1 text-tag font-medium text-ink-2 shadow-sm"
        role="status"
        aria-live="polite"
      />
      {/* ═══ C2/C5/C7：交互信息卡（React 固定卡，审查 R1 定版）═══ */}
      {isoCard && (
        <div
          data-lc-iso-card="true"
          role="dialog"
          aria-label={isoCard.title}
          className="absolute right-2 top-14 z-20 w-60 rounded-btn border border-ink/10 bg-white/95 p-3 shadow-sm backdrop-blur"
        >
          <div className="mb-1.5 flex items-start justify-between gap-2">
            <span className="flex items-center gap-1.5 text-tag font-semibold text-ink">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: isoCard.blue ? '#1677ff' : '#5F7B69' }} />
              {isoCard.title}
            </span>
            <button
              type="button"
              aria-label="关闭信息卡"
              onClick={() => setIsoCard(null)}
              className="shrink-0 cursor-pointer text-ink-3 hover:text-ink"
            >
              ✕
            </button>
          </div>
          <table className="w-full text-tag">
            <tbody>
              {isoCard.rows.map(([k, v]) => (
                <tr key={k}>
                  <td className="py-0.5 text-ink-2">{k}</td>
                  <td className="py-0.5 text-right font-medium text-ink">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {isoCard.fly && (
            <button
              type="button"
              onClick={() => flyToCenter(isoCard.fly as LngLat)}
              className="mt-2 w-full cursor-pointer rounded-chip border border-primary/40 bg-primary/10 px-2 py-1 text-tag font-medium text-primary-deep hover:bg-primary/20"
            >
              ◎ 定位到此
            </button>
          )}
        </div>
      )}
      <div className="absolute right-2 top-2 z-30 flex flex-col items-end gap-1">
        {canToggleRaw && <BoundaryToggle value={boundaryView} onChange={setBoundaryView} />}
        <NotesToggle on={notesOn} onToggle={toggleNotes} disabled={transitioning} />
      </div>
      {(!compareReport || notesOn) && (
        <MapNoteBadge
          poiShown={badgePoiShown}
          heatShown={badgeHeatShown}
          thinNote={badgeThinNote}
          notesOn={notesOn}
        />
      )}
      {transitioning && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-md bg-white/70 text-tag font-medium text-ink-2"
          role="status"
          aria-live="polite"
        >
          底图重载中…
        </div>
      )}
    </div>
  )
})

export default LcMap
