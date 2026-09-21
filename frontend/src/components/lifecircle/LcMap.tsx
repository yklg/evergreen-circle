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
import type { BlindSpot, LivingCircleReport, LngLat, PoiPoint } from '../../types'
import { getMapConfig, geolocateMe, loadBMapGL } from '../../lib/bmap'
import type { BMapGLNamespace, BMapMap, BMapMapOverlay, BMapPoint } from '../../lib/bmap'
import { LC_MAP_STYLE_LIGHT } from '../../lib/bmapStyle'
import { asBdLngLat, asBdLngLatOrNull, rejectBdLngLatSource, toDiagPair } from '../../lib/geo'
import type { CoordSys } from '../../lib/geo'
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
  fixesOf,
  gapScoreOf,
  lcFillSpec,
  lcPolyPts,
  lcRightmost,
  lcToPx,
  lcSnapshotPoiLayer,
  severityOf,
} from '../../lib/livingCircle'
import type { BlindBoundaryView } from '../../lib/livingCircle'

export type LcMapMode = 'boot' | 'live' | 'fallback'

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
}

const POI_MARKER_CAP = 120

/** 盲区悬浮信息（C2/C4：严重度/缺口/真实可达/受影响/补点；旧数据字段缺失时安全省略） */
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

/** 补点处方符号（C3：绿色加号，白描边 + 绿色十字），与盲区中心点在视觉上明确区分 */
function fixPlusIcon(bmap: BMapGLNamespace, color: string) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18">` +
    `<circle cx="9" cy="9" r="8" fill="rgba(31,158,99,0.16)" stroke="${color}" stroke-width="1.5"/>` +
    `<path d="M9 5 V13 M5 9 H13" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>` +
    `<path d="M9 5 V13 M5 9 H13" stroke="${color}" stroke-width="2" stroke-linecap="round"/></svg>`
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new bmap.Icon(url, new bmap.Size(18, 18), { anchor: new bmap.Size(9, 9) })
}

/** 冷热小点（8px 半透明，评审 40%「等时圈热力图」） */
function heatDotIcon(bmap: BMapGLNamespace, color: string) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">` +
    `<circle cx="4" cy="4" r="3.2" fill="${color}" fill-opacity="0.55"/></svg>`
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new bmap.Icon(url, new bmap.Size(8, 8), { anchor: new bmap.Size(4, 4) })
}

/** 耗时(分钟) → 热力色：0min 浅绿 → 20min 深绿（线性插值）；>20 用灰表示超圈 */
function minuteHeatColor(minutes: number): string {
  const t = Math.max(0, Math.min(1, minutes / 20))
  const from = [0x8f, 0xbf, 0xa2] // #8fbfa2
  const to = [0x2c, 0x5a, 0x3f] //   #2c5a3f
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

function centerIcon(bmap: BMapGLNamespace) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">` +
    `<circle cx="11" cy="11" r="7" fill="#5F7B69" stroke="#ffffff" stroke-width="2"/>` +
    `<circle cx="11" cy="11" r="10" fill="rgba(95,123,105,0.22)" stroke="#5F7B69" stroke-width="1.2" stroke-dasharray="3 3"/></svg>`
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new bmap.Icon(url, new bmap.Size(22, 22), { anchor: new bmap.Size(11, 11) })
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
      className="absolute left-2 top-2 z-10 flex items-center gap-0.5 rounded-full border border-ink-1/10 bg-white/95 px-1 py-0.5 shadow-sm"
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
            (value === o.key ? 'text-white' : 'text-ink-2 hover:bg-ink-1/5')
          }
          style={value === o.key ? { backgroundColor: '#1677ff' } : undefined}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

const LcMap = forwardRef<LcMapHandle, LcMapProps>(function LcMap(
  { report, customCenter, onCenterChange, draggableCenter = true, compareReport, onMapMode },
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

  /* 初始化：取 AK/样式配置 → 注入 BMapGL → 建图 + 个性化底图样式；失败降级静态画布 */
  useEffect(() => {
    let disposed = false
    let container: HTMLDivElement | null = null
    ;(async () => {
      const cfg = await getMapConfig()
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
        // C7 底图风格：控制台 styleId 优先（用户个性化样式），否则内置 S2 低饱和浅色模板
        map.setMapStyleV2(cfg.mapStyleId ? { styleId: cfg.mapStyleId } : { styleJson: LC_MAP_STYLE_LIGHT })
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
    }
  }, [])

  /* 覆盖层绘制：等时圈/盲区/POI/中心标记（真实态） */
  useEffect(() => {
    const map = mapRef.current
    const bmap = bmapRef.current
    if (mode !== 'live' || !map || !bmap) return

    overlaysRef.current.forEach((o) => map.removeOverlay(o))
    overlaysRef.current = []
    const add = (o: BMapMapOverlay) => {
      map.addOverlay(o)
      overlaysRef.current.push(o)
    }
    const pt = (lnglat: LngLat): BMapPoint => new bmap.Point(lnglat[0], lnglat[1])

    const center: LngLat = customCenter ?? report.scene.center
    const reports = compareReport ? [report, compareReport] : [report]
    const colorSets = compareReport ? [LC_ISO_COLORS, LC_ISO_COLORS_B] : [LC_ISO_COLORS]

    // 采样点耗时热力（赛题 40%「等时圈热力图」：渔网采样 → API 测时 → 逐点耗时着色）
    // 仅主报告、非对比模式；≤20min 可达点按耗时 浅绿→深绿 渐变，不可达置灰
    if (!compareReport) {
      report.sampling.points.forEach((sp) => {
        if (sp.minutes == null || !sp.reachable) return
        add(
          new bmap.Marker(pt([sp.lng, sp.lat]), {
            icon: heatDotIcon(bmap, minuteHeatColor(sp.minutes)),
            title: `${sp.idx} 号采样点 · 步行 ${sp.minutes}min`,
          }),
        )
      })
    }

    // 等时圈族（A 绿系 / B 蓝系）
    // ① 色阶必须与分钟数绑定（5min 最深 → 20min 最浅），与降级 SVG 画布一致；
    //    不可 sort(b-a) 后再取 colors[zi]——那会把最深色给 20min 圈，色阶倒挂。
    // ② 绘制顺序「大圈先、小圈后」：小圈叠在大圈之上，嵌套累积出热力观感。
    // ③ fillOpacity 取自色表声明的 alpha（BMapGL 不认 fillColor 里的 rgba 透明度）。
    const fitPts: BMapPoint[] = []
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
        add(
          new bmap.Polygon(pts, {
            strokeColor: c.stroke,
            fillColor: fill.color,
            strokeWeight: 1.5,
            fillOpacity: fill.opacity,
            strokeOpacity: 1,
            strokeStyle: 'solid',
          }),
        )
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
        add(
          new bmap.Polygon(pts, {
            strokeColor: gap == null ? '#8a8a8a' : spec.stroke,
            fillColor: heatFill.color,
            strokeWeight: 1.2,
            fillOpacity: heatFill.opacity,
            strokeStyle: gap == null ? 'dashed' : 'solid',
          }),
        )
        // 中心标号（C2：`#N · 重度` —— 严重度语义 + 序号，评分基线用）
        add(
          new bmap.Marker(pt(b.center), {
            icon: dotIcon(bmap, spec.dot),
            title,
          }),
        )
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
        // 补点处方（C3：绿核白边 Marker + 设施/策略/优先级 title），仅当存在 fixes
        ;(b.fixes ?? []).forEach((fix) => {
          const strategy = LC_BLIND_FIX_STRATEGY[fix.strategy] ?? fix.strategy
          add(
            new bmap.Marker(pt(fix.point), {
              icon: fixPlusIcon(bmap, LC_FIX_DOT),
              title: `补${fix.facility} · ${strategy} · P${fix.priority} · 覆盖 ${fix.served ?? '?'} 格`,
            }),
          )
        })
      })
    }

    // POI 真实坐标 Marker（仅主报告、非对比模式；旧快照 points 为空则跳过）
    if (!compareReport && report.poi.points?.length) {
      const points: PoiPoint[] = [...report.poi.points]
        .sort((a, b) => Number(b.in_circle) - Number(a.in_circle) || (a.minutes ?? 99) - (b.minutes ?? 99))
        .slice(0, POI_MARKER_CAP)
      points.forEach((p) => {
        const color = LC_CAT_COLOR[p.category] ?? '#7c6670'
        const marker = new bmap.Marker(pt(p.lnglat), {
          icon: dotIcon(bmap, color),
          title: `${p.name} · ${LC_CAT_LABEL_OF(p.category)}${p.minutes != null ? ` · ${p.minutes}min` : ' · 不可达'}`,
        })
        marker.addEventListener('click', () => {
          const win = new bmap.InfoWindow(
            `<div style="font-size:12px;line-height:1.6"><b>${p.name}</b><br/>` +
              `${LC_CAT_LABEL_OF(p.category)} · ${p.minutes != null ? `步行 ${p.minutes}min` : '不可达'}` +
              `${p.in_circle ? ' · 圈内' : ' · 圈外'}</div>`,
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
            report.sampling.points
              .filter((sp) => sp.reachable && sp.minutes != null)
              .slice(0, 300)
              .map((sp) => {
                const [hx, hy] = lcToPx(center, sp.lng, sp.lat)
                return <circle key={`heat-${sp.idx}`} cx={hx} cy={hy} r={2.6} fill={minuteHeatColor(sp.minutes!)} opacity={0.55} />
              })}

          {!secondary &&
            lcSnapshotPoiLayer(center, report.poi.points, 60).map((p) => (
              <circle key={p.key} cx={p.cx} cy={p.cy} r={5} fill={p.fill} stroke="#fff" strokeWidth={1.2} opacity={0.92}>
                {p.title && <title>{p.title}</title>}
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
        <div className="absolute right-2 top-2 rounded-chip border border-warn/50 bg-warn/10 px-2.5 py-1 text-tag font-medium text-ink-2">
          地图降级 · 静态画布（无 AK / 离线）
        </div>
        {canToggleRaw && <BoundaryToggle value={boundaryView} onChange={setBoundaryView} />}
      </div>
    )
  }

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" role="img" aria-label="生活圈真实地图" data-lc-map="true" />
      {canToggleRaw && <BoundaryToggle value={boundaryView} onChange={setBoundaryView} />}
    </div>
  )
})

export default LcMap
