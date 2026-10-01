/**
 * 圈选联动（四档候选）· 选中态预览探针（**预览闸，不改生产组件**）
 *
 * 打开：`http://localhost:3400/preview-lc-disc.html`
 * 参数：`?tier=a|b|c|d`（默认 a）· `?focus=disc:0|iso:15|blind:0` · `?city=beijing|kaili` · `?disc_on=1`
 *
 * 要拍的一件事：用户原话「现在选择了某个圈，不能第一时间分辨是哪个点位」——
 * **选中一个圈之后，图上亮的到底是哪颗点、那句话念什么**。四档是四种"对应关系"，不是四种配色。
 *
 * 同源纪律（违反即预览作废）：
 * - 地图一律用真组件 `components/lifecircle/LcMap`，**不复制画法**；取色 / 举证句 / 命中判定
 *   走 `lib/livingCircle.ts` 出口（`lcEvidenceDiscColor` · `evidenceDiscTitle` · 新增的
 *   `hitEvidenceDisc` / `discStroke` / `lcAnchorDotDataUrl`）。高亮的那个盘是**命中函数判出来的**，
 *   不是 URL 下标直接指的 —— 否则预览亮的是我想看的，不是将来会上屏的。
 * - 数据 = `src/dev/fixtures/lcDiscFocus.json`：2026-09-30 两城**真打接口**落盘的 live 报告
 *   （`skip/tmp/out/lc_p5_live_*.json` 的 `stored_report` 逐字节内嵌，零造盘、零删点）。
 *   规模自报见该文件 `_meta.scale`。
 * - 选中态用 URL 烘进渲染（headless 不能 hover）；画法走 **setter 改属性**，setter 缺失时
 *   退化为"再盖一个覆盖物"——**走了哪条臂当场写在读数里**，不猜。
 * - B 档下半段是**示意**：后端 `EvidenceDisc` 只有 7 个字段、不带"这一趟检回了哪些点"，
 *   探针拿 `poi.points` 现算圈内点画灰虚线，并打显式水印（那不是检索产物）。
 * - 不改 `fillOpacity:0` / `enableClicking:false`（那是「勾开图层仍可拖动」那条真机证据的载体）。
 *
 * 覆盖物怎么拿：`LcMapHandle` 只暴露 `locate`，地图实例与图层都不出组件 ⇒
 * 探针在真组件挂载前给 `BMapGL.Map.prototype.addOverlay` 打计数补丁（真机取证用过的那招），
 * 再从登记册里按 `getRadius` / `getPath` 认领自己的层。**这是探针手法，不是落地的做法**
 * ——落地时选中态在组件内部，见计划 Step 3。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与 eslint。
 */
import { createRoot } from 'react-dom/client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import LcMap, { blindTitle } from '../components/lifecircle/LcMap'
import { getMapConfig, loadBMapGL } from '../lib/bmap'
import type { BMapGLNamespace, BMapMap, BMapMapOverlay, BMapPoint } from '../lib/bmap'
import {
  LC_DISC_WEIGHT,
  LC_FIX_DOT,
  blindPolygonOf,
  discStroke,
  evidenceDiscAnchorLabel,
  evidenceDiscTitle,
  evidenceDiscs,
  fixPlusSvg,
  hitEvidenceDisc,
  lcAnchorDotDataUrl,
  lcEvidenceCategoryLabel,
  lcEvidenceDiscColor,
  lcFromMeters,
  poiRenderSet,
} from '../lib/livingCircle'
import type { LcDiscHitTarget } from '../lib/livingCircle'
import type { BlindSpot, EvidenceDisc, LivingCircleReport, PoiPoint } from '../types'
import fixtures from './fixtures/lcDiscFocus.json'
import '../index.css'

const reports = {
  beijing: fixtures.beijing as unknown as LivingCircleReport,
  kaili: fixtures.kaili as unknown as LivingCircleReport,
} as const
const scale = (fixtures._meta as unknown as { scale: Record<string, Record<string, number>> }).scale

/* ───────────────────────── 覆盖物登记（探针取巧，见页首纪律） ───────────────────────── */

/** 探针用到的结构面：`bmap.ts` 的窄类型没声明这些取值方法（与 `LcMap` 里就地结构类型同一手法）。 */
interface OverlayView {
  getRadius?(): number
  getPath?(): BMapPoint[]
  getPosition?(): BMapPoint
  setStrokeWeight?(w: number): void
  setStrokeOpacity?(o: number): void
  setOpacity?(o: number): void
  setIcon?(icon: unknown): void
}
interface Rec {
  map: BMapMap
  overlay: OverlayView
}

const added: Rec[] = []
const camCount = new Map<BMapMap, number>()
let ns: BMapGLNamespace | null = null

function patchNamespace(bmap: BMapGLNamespace) {
  const proto = bmap.Map.prototype as unknown as {
    addOverlay(this: BMapMap, o: BMapMapOverlay): void
    centerAndZoom(this: BMapMap, p: BMapPoint, z: number): void
    __lcDiscProbe?: boolean
  }
  if (proto.__lcDiscProbe) return
  const origAdd = proto.addOverlay
  const origCam = proto.centerAndZoom
  proto.addOverlay = function (this: BMapMap, o: BMapMapOverlay) {
    added.push({ map: this, overlay: o as unknown as OverlayView })
    return origAdd.call(this, o)
  }
  proto.centerAndZoom = function (this: BMapMap, p: BMapPoint, z: number) {
    camCount.set(this, (camCount.get(this) ?? 0) + 1)
    return origCam.call(this, p, z)
  }
  proto.__lcDiscProbe = true
}

/** 第一个真正挂了覆盖物的地图实例 = live 那台（降级那台在 `new bmap.Map` 就抛了，一个都不挂）。 */
function firstLiveMap(): BMapMap | null {
  return added.length ? added[0].map : null
}

/** 降级栏与 live 栏同页共存靠的是顺序：先播空壳命名空间（组件 `new bmap.Map` 抛 ⇒ 自动 fallback），
 *  拿到 fallback 上报后再注真脚本（`loadScript` 见 `window.BMapGL` 已存在就直接返回，不再注）。 */
function seedEmptyNamespace() {
  ;(window as unknown as { BMapGL?: unknown }).BMapGL = {}
}
function unseedNamespace() {
  delete (window as unknown as { BMapGL?: unknown }).BMapGL
}

/* ───────────────────────── 参数与档位 ───────────────────────── */

type Tier = 'a' | 'b' | 'c' | 'd'
type City = 'beijing' | 'kaili'
const TIERS: Record<Tier, { badge: string; name: string; point: string; cost: string }> = {
  a: { badge: 'A', name: '档 A · 证据域盘 ↔ 取证锚点', point: '亮的点位 = 盘心那颗新画的锚点（现在图上不存在）', cost: '只改前端（LcMap 盘层 + 容器命中）· 不碰后端与契约' },
  b: { badge: 'B', name: '档 B · 证据域盘 ↔ 这一趟检回的设施点', point: '亮的点位 = 该盘检索回来的 POI 集', cost: '要动后端：scope.py 发射 + 契约 B12 扩 + 存量 27 份不回填' },
  c: { badge: 'C', name: '档 C · 等时圈 ↔ 圈内可达设施点', point: '亮的点位 = 该档内可达的 POI（圈外压暗）', cost: '只改前端 · 不碰契约（现成 `in_circle` / `minutes`）' },
  d: { badge: 'D', name: '档 D · 盲区 ↔ 它的补点处方', point: '亮的点位 = 该盲区的补点图标 / 最近设施', cost: '只改前端 · 不碰契约' },
}

function readParams() {
  const q = new URLSearchParams(window.location.search)
  const t = (q.get('tier') ?? 'a').toLowerCase()
  const tier = (t === 'b' || t === 'c' || t === 'd' ? t : 'a') as Tier
  const focus = q.get('focus') ?? (tier === 'c' ? 'iso:15' : tier === 'd' ? 'blind:0' : 'disc:0')
  const n = Number(focus.split(':')[1] ?? 0)
  const paramCity = q.get('city')
  const city: City = tier === 'd' ? 'kaili' : paramCity === 'kaili' ? 'kaili' : 'beijing'
  const discOn = (q.get('disc_on') ?? (tier === 'a' || tier === 'b' ? '1' : '0')) === '1'
  return { tier, city, focus, n, discOn }
}

/* ───────────────────────── 四档各自的选中态 ───────────────────────── */

type Row = [string, string]
const yes = (v: boolean) => (v ? '有' : '没有')

function projectDiscs(map: BMapMap, bmap: BMapGLNamespace, discs: EvidenceDisc[]) {
  const targets: LcDiscHitTarget[] = []
  for (const d of discs) {
    const c = map.pointToPixel(new bmap.Point(d.anchor[0], d.anchor[1]))
    const edge = map.pointToPixel(new bmap.Point(...lcFromMeters(d.anchor, d.exhausted_radius_m, 0)))
    targets.push({ index: targets.length, centerPx: [c.x, c.y], radiusPx: Math.hypot(edge.x - c.x, edge.y - c.y) })
  }
  return targets
}

function ringPointPx(map: BMapMap, bmap: BMapGLNamespace, d: EvidenceDisc, radiusM: number): [number, number] {
  const p = map.pointToPixel(new bmap.Point(...lcFromMeters(d.anchor, radiusM, 0)))
  return [p.x, p.y]
}

/** 认领这层的 Circle：盘的 `exhausted_radius_m` 集合 + 登记顺序（与 `evidenceDiscs()` 同序）。 */
function discOverlays(map: BMapMap, discs: EvidenceDisc[]): OverlayView[] {
  const want = new Set(discs.map((d) => Math.round(d.exhausted_radius_m)))
  return added
    .filter((r) => r.map === map && typeof r.overlay.getRadius === 'function' && want.has(Math.round(r.overlay.getRadius() ?? -1)))
    .map((r) => r.overlay)
}

function applyDiscStroke(
  o: OverlayView,
  map: BMapMap,
  bmap: BMapGLNamespace,
  d: EvidenceDisc,
  state: 'idle' | 'focus' | 'dim',
): 'setter' | 'overlay' {
  const s = discStroke(state)
  if (typeof o.setStrokeWeight === 'function') {
    o.setStrokeWeight(s.strokeWeight)
    o.setStrokeOpacity?.(s.strokeOpacity)
    return 'setter'
  }
  const color = lcEvidenceDiscColor(d.category)
  map.addOverlay(
    new bmap.Circle(new bmap.Point(d.anchor[0], d.anchor[1]), d.exhausted_radius_m, {
      strokeColor: color,
      strokeWeight: s.strokeWeight,
      strokeOpacity: s.strokeOpacity,
      strokeStyle: d.complete ? 'solid' : 'dashed',
      fillColor: color,
      fillOpacity: 0,
      enableClicking: false,
    }),
  )
  return 'overlay'
}

function addAnchorDot(map: BMapMap, bmap: BMapGLNamespace, d: EvidenceDisc, size: number) {
  const icon = new bmap.Icon(lcAnchorDotDataUrl(lcEvidenceDiscColor(d.category), size), new bmap.Size(size, size), {
    anchor: new bmap.Size(size / 2, size / 2),
  })
  map.addOverlay(new bmap.Marker(new bmap.Point(d.anchor[0], d.anchor[1]), { icon }))
}

function addChipLabel(map: BMapMap, bmap: BMapGLNamespace, at: [number, number], text: string, color: string) {
  map.addOverlay(
    new bmap.Label(text, {
      position: new bmap.Point(at[0], at[1]),
      offset: new bmap.Size(10, -8),
      styles: {
        color: '#10231b',
        fontSize: '12px',
        fontWeight: '700',
        background: 'rgba(255,255,255,.92)',
        border: `1.5px solid ${color}`,
        borderRadius: '999px',
        padding: '1px 6px',
      },
    }),
  )
}

function poiInDisc(points: PoiPoint[], d: EvidenceDisc, limit: number): PoiPoint[] {
  const out: PoiPoint[] = []
  for (const p of points) {
    const mx = (p.lnglat[0] - d.anchor[0]) * 111320 * Math.cos((d.anchor[1] * Math.PI) / 180)
    const my = (p.lnglat[1] - d.anchor[1]) * 111320
    if (Math.hypot(mx, my) <= d.request_radius_m) out.push(p)
    if (out.length >= limit) break
  }
  return out
}

/** 同心盘消歧的现场重放：光标分别放到「共享圆心」与「某盘内部（0.4 半径处）」，看命中函数判给谁。 */
function disambiguationRows(discs: EvidenceDisc[], targets: LcDiscHitTarget[]): Row[] {
  const groups = new Map<string, number[]>()
  discs.forEach((d, i) => groups.set(d.anchor.join(','), [...(groups.get(d.anchor.join(',')) ?? []), i]))
  const concentric = [...groups.values()].filter((g) => g.length > 1)
  if (!concentric.length) return [['同心盘', '这份报告里没有同心的盘 ⇒ 判据 ② 在本城无用武之地']]
  const g = concentric[0]
  const atCenter = hitEvidenceDisc(targets[g[0]].centerPx, targets)
  const inner = hitEvidenceDisc(
    [targets[g[0]].centerPx[0] + targets[g[0]].radiusPx * 0.4, targets[g[0]].centerPx[1]],
    targets,
  )
  return [
    [`同心 ${g.length} 盘（#${g.map((i) => i + 1).join(' #')}）· 光标压在共享圆心`, atCenter ? `判给 #${atCenter.target.index + 1}（kind=${atCenter.kind}）` : '无命中'],
    ['· 光标放进这组盘内部（离圆心 0.4 半径）', inner ? `判给 #${inner.target.index + 1}（kind=${inner.kind}）· 若判到别的盘，是它先撞上了别人的环线：①优先于③` : '无命中'],
    ['⇒ 要指到同心的第 2、3 盘，只能压在它自己的环线上（判据 ①）', `同级按下标取最小 ⇒ 圆心类判据永远指到 #${g[0] + 1}`],
  ]
}

function paintDiscTier(map: BMapMap, report: LivingCircleReport, tier: Tier, n: number): { rows: Row[]; card: string } {
  const bmap = ns
  const discs = evidenceDiscs(report)
  if (!bmap || !discs.length) return { rows: [['夹具读数', '没有盘可画 ⇒ 该档预览无效']], card: '' }
  const targets = projectDiscs(map, bmap, discs)
  const over = discOverlays(map, discs)
  const want = Math.min(Math.max(n, 0), discs.length - 1)
  // 选中态**由命中函数判**：光标放在第 want+1 盘的环线上（判据 ①）
  const cursor = ringPointPx(map, bmap, discs[want], discs[want].exhausted_radius_m)
  const hit = hitEvidenceDisc(cursor, targets)
  const chosen = hit ? hit.target.index : want
  const d = discs[chosen]
  const arms = new Set<'setter' | 'overlay'>()
  discs.forEach((one, i) => {
    const o = over[i]
    if (o) arms.add(applyDiscStroke(o, map, bmap, one, i === chosen ? 'focus' : 'dim'))
  })
  addAnchorDot(map, bmap, d, 22)
  addChipLabel(map, bmap, d.anchor, `#${chosen + 1}`, lcEvidenceDiscColor(d.category))
  const rows: Row[] = [
    ['① 光标放在这盘的环线上（容器像素）', `(${cursor[0].toFixed(1)}, ${cursor[1].toFixed(1)})`],
    ['② 命中函数判给了谁', hit ? `#${hit.target.index + 1} · ${lcEvidenceCategoryLabel(d.category)} · kind=${hit.kind} · 差 ${hit.deltaPx.toFixed(1)}px` : '无命中'],
    ['③ 图上实际加粗的那盘', `#${chosen + 1} · 线宽 ${LC_DISC_WEIGHT.idle} → ${LC_DISC_WEIGHT.focus}，其余 ${discs.length - 1} 盘压到 ${LC_DISC_WEIGHT.dim}/${discStroke('dim').strokeOpacity}`],
    ['④ 亮的点位', tier === 'a' ? '盘心的取证锚点（新画的一颗点）' : '锚点 + 这一趟检回的设施点（下半段是示意）'],
    ['覆盖物认领', `登记到 Circle ${over.length} 个 / 报告应有 ${discs.length} 个`],
    ['改属性这条路走得通吗', arms.has('setter') ? 'setter 可用 ⇒ 改属性、不重建图层' : 'setter 缺失 ⇒ 走盖覆盖物的退化臂'],
    ['锚点 Marker 能不能不吃点击', 'BMapMarkerCtor 的类型面没有 enableClicking ⇒ 落地要补这一项（锚点是装饰，不该抢地图取点）'],
    ['相机被复位过几次', `${camCount.get(map) ?? 0}（只该是挂载那一次）`],
    ...disambiguationRows(discs, targets),
  ]
  if (tier === 'b') {
    const near = poiInDisc(report.poi.points ?? [], d, 12)
    for (const p of near) {
      map.addOverlay(
        new bmap.Polyline([new bmap.Point(d.anchor[0], d.anchor[1]), new bmap.Point(p.lnglat[0], p.lnglat[1])], {
          strokeColor: '#8a8a8a',
          strokeWeight: 2,
          strokeStyle: 'dashed',
          strokeOpacity: 0.85,
        }),
      )
    }
    rows.push(['灰虚线连了几个点', `${near.length} 个`])
    rows.push(['⚠ 这一段的身份', '探针拿 poi.points 现算的圈内点（不是后端发的键） —— 后端从没发过「这一趟检回了哪些点」这个键'])
    rows.push([' ⇒ 该档落地的前置', '`scope.py` 发射 + 契约 B12 扩 + 存量 27 份报告不回填 ⇒ 前端"键缺即不出现"'])
  }
  return { rows, card: `${evidenceDiscTitle(d)}\n${evidenceDiscAnchorLabel(d)}` }
}

function findPolygon(map: BMapMap, ring: [number, number][]): OverlayView | null {
  if (!ring.length) return null
  for (const r of added) {
    if (r.map !== map || typeof r.overlay.getPath !== 'function' || typeof r.overlay.getRadius === 'function') continue
    const path = r.overlay.getPath?.() ?? []
    if (path.length === ring.length && Math.abs(path[0].lng - ring[0][0]) < 1e-6 && Math.abs(path[0].lat - ring[0][1]) < 1e-6) return r.overlay
  }
  return null
}

function findMarkerAt(map: BMapMap, lnglat: [number, number]): OverlayView | null {
  for (const r of added) {
    if (r.map !== map || typeof r.overlay.getPosition !== 'function') continue
    const p = r.overlay.getPosition?.()
    if (p && Math.abs(p.lng - lnglat[0]) < 1e-6 && Math.abs(p.lat - lnglat[1]) < 1e-6) return r.overlay
  }
  return null
}

function paintIsoTier(map: BMapMap, report: LivingCircleReport, minutes: number): { rows: Row[]; card: string } {
  const bmap = ns
  if (!bmap) return { rows: [['命名空间', '没拿到 ⇒ 该档预览无效']], card: '' }
  const sorted = [...report.isochrones].sort((a, z) => a.minutes - z.minutes)
  const z = sorted.find((x) => x.minutes === minutes) ?? sorted[sorted.length - 1]
  const ring = (z.geojson.coordinates[0] ?? []) as [number, number][]
  const poly = findPolygon(map, ring)
  const setterArm = typeof poly?.setStrokeWeight === 'function'
  if (poly) {
    poly.setStrokeWeight?.(3.5)
    poly.setStrokeOpacity?.(1)
  }
  const reps = poiRenderSet(report.poi.points).reps
  let inBand = 0
  let outBand = 0
  let dimmed = 0
  let noMinutes = 0
  let darkArm = '没有可压暗的标记'
  for (const p of reps) {
    if (p.minutes == null) {
      noMinutes++
      continue
    }
    if (p.minutes <= z.minutes) {
      inBand++
      continue
    }
    outBand++
    const m = findMarkerAt(map, p.lnglat)
    if (!m) continue
    if (typeof m.setOpacity === 'function') {
      m.setOpacity(0.16)
      darkArm = 'setOpacity（改属性）'
    } else {
      map.addOverlay(
        new bmap.Circle(new bmap.Point(p.lnglat[0], p.lnglat[1]), 70, {
          strokeColor: '#8a8a8a',
          strokeWeight: 1,
          strokeOpacity: 0.4,
          fillColor: '#eef1ef',
          fillOpacity: 0.9,
          enableClicking: false,
        }),
      )
      darkArm = '盖灰盘（退化臂）'
    }
    dimmed++
  }
  addChipLabel(map, bmap, z.geojson.coordinates[0][0] as [number, number], `${z.minutes}min`, '#11231c')
  return {
    rows: [
      ['① 光标压在哪条圈上', `${z.minutes}min 等时圈（面积 ${z.area_km2.toFixed(2)} km²）`],
      ['② 图上亮了什么', poly ? `这一圈描边 1.5 → 3.5（setter=${yes(setterArm)}）` : '没认领到这一圈的 Polygon ⇒ 该档预览无效'],
      ['③ 亮的点位', `圈内 ${inBand} 个点保持原样 · 圈外 ${outBand} 个点里实压暗 ${dimmed}（臂=${darkArm}）`],
      ['渲染点数', `报告给了 ${report.poi.points?.length ?? 0} 个 POI，图上实际画的是抽稀后的 ${reps.length} 个（poiRenderSet 出口）；其中无耗时报数 ${noMinutes} 个，不参与分档`],
      ['与今天的差在哪', '今天 hover 环线已经会加粗这一圈（LcMap.tsx:608 dimRings），但圈内圈外的点毫无反应 ⇒ 本档新增的是点位那一半'],
      ['相机被复位过几次', `${camCount.get(map) ?? 0}`],
    ],
    card: `${z.minutes}min 等时圈 · 面积 ${z.area_km2.toFixed(2)} km²\n（这句与 LcMap.tsx:661 同式 —— 那条串是内联的、没有出口，落地时要一并收进 lib）`,
  }
}

function paintBlindTier(map: BMapMap, report: LivingCircleReport, n: number): { rows: Row[]; card: string } {
  const bmap = ns
  const bs = report.blindspots ?? []
  if (!bmap) return { rows: [['命名空间', '没拿到 ⇒ 该档预览无效']], card: '' }
  if (!bs.length)
    return { rows: [['夹具读数', `这份报告盲区数 = 0 ⇒ 该档用真读数画不出来（北京 live=0、凯里 live=1）`]], card: '' }
  const b = bs[Math.min(Math.max(n, 0), bs.length - 1)] as BlindSpot
  const ring = (blindPolygonOf(b, 'smoothed')?.coordinates?.[0] ?? []) as [number, number][]
  const poly = findPolygon(map, ring)
  const fix = (b.fixes ?? [])[0]
  const fixMarker = fix ? findMarkerAt(map, fix.point as [number, number]) : null
  const size = 30
  let fixArm = fix ? '没认领到补点 Marker' : '这块盲区没有补点处方 ⇒ 无点位可亮'
  if (fix && fixMarker) {
    const icon = new bmap.Icon(
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fixPlusSvg(LC_FIX_DOT))}`,
      new bmap.Size(size, size),
      { anchor: new bmap.Size(size / 2, size / 2) },
    )
    if (typeof fixMarker.setIcon === 'function') {
      fixMarker.setIcon(icon)
      fixArm = 'setIcon 放大 18→30（改属性）'
    } else {
      map.addOverlay(new bmap.Marker(new bmap.Point(fix.point[0], fix.point[1]), { icon }))
      fixArm = '再盖一个大号 Marker（退化臂）'
    }
  }
  const setterArm = typeof poly?.setStrokeWeight === 'function'
  if (poly) {
    poly.setStrokeWeight?.(3.2)
    addChipLabel(map, bmap, b.center as [number, number], `#${Math.min(Math.max(n, 0), bs.length - 1) + 1}`, '#d9bd3a')
  }
  return {
    rows: [
      ['① 选中', `${b.id ?? ''} · 缺失 ${(b.missing_facilities ?? []).join('/')} · 严重度 ${b.severity} · 缺口 ${b.gap_score}`],
      ['② 图上亮了什么', poly ? `这块盲区的多边形描边 1.2 → 3.2（setter=${yes(setterArm)}）` : '没认领到盲区 Polygon ⇒ 该档预览无效'],
      ['③ 亮的点位', fix ? `${fixArm} · 补${fix.facility} · ${fix.strategy} · P${fix.priority}` : '这块盲区没有补点处方 ⇒ 无点位可亮'],
      ['今天 hover 这块盲区图上有什么变化', '只有右上角浮层文字，图面上零变化（LcMap.tsx:750-762）'],
      ['最近设施（真读数）', (b.nearest ?? []).map((x) => `${x.name} ${x.distance_m}m`).join(' ｜ ') || '—'],
      ['相机被复位过几次', `${camCount.get(map) ?? 0}`],
    ],
    card: `${blindTitle(b)}\n（这句是 LcMap 导出的 blindTitle() 真产出）`,
  }
}

/* ───────────────────────── UI ───────────────────────── */

/** 描边/圆角/底色抄生产容器（`LifeCirclePage.tsx:660`）；那里是 `min-h-[480px]` 靠外层网格撑开，探针外层不是网格，
 *  所以给**确定高度** 480px —— 否则 BMapGL 拿到 0 高度，图上什么都不剩。 */
function Frame({ children, h = 480 }: { children: ReactNode; h?: number }) {
  return (
    <div className="relative overflow-hidden rounded-card border border-line bg-card shadow-card" style={{ height: h }}>
      {children}
    </div>
  )
}

function Rows({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <div className="rounded-card border border-line bg-card p-3 shadow-card">
      <div className="mb-1.5 text-aux font-semibold text-ink">{title}</div>
      <table className="w-full border-collapse text-tag leading-snug text-ink-2">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-t border-line/60 align-top first:border-t-0">
              <td className="w-[44%] py-1 pr-2 font-medium text-ink">{k}</td>
              <td className="py-1">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LiveColumn({
  ready,
  tier,
  report,
  n,
  discOn,
}: {
  /** BMapGL 已加载并打好补丁 ⇒ 该挂真地图了。**不能**用"登记到覆盖物"当挂载条件：
   *  覆盖物正是这台地图挂上去才有的，拿它当门就是死锁（第一次出图 live 栏空白就是这么来的）。 */
  ready: boolean
  tier: Tier
  report: LivingCircleReport
  n: number
  discOn: boolean
}) {
  const [out, setOut] = useState<{ rows: Row[]; card: string }>({
    rows: [['状态', ready ? '等图层画完（轮询覆盖物登记）' : 'BMapGL 未就绪']],
    card: '',
  })
  const ticks = useRef(0)

  useEffect(() => {
    if (!ready) return
    ticks.current = 0
    const timer = window.setInterval(() => {
      ticks.current += 1
      const map = firstLiveMap()
      if (!map) {
        if (ticks.current >= 40) {
          setOut({ rows: [['覆盖物登记', '轮询 40 次一个都没登记 ⇒ live 分支没画出来，这一档预览无效']], card: '' })
          window.clearInterval(timer)
        }
        return
      }
      const discs = evidenceDiscs(report)
      const circles = discOverlays(map, discs).length
      const polys = added.filter((r) => r.map === map && typeof r.overlay.getPath === 'function').length
      const painted =
        tier === 'c'
          ? paintIsoTier(map, report, n)
          : tier === 'd'
            ? paintBlindTier(map, report, n)
            : paintDiscTier(map, report, tier, n)
      const layerReady = tier === 'a' || tier === 'b' ? circles >= Math.min(discs.length, 2) : polys >= 1
      if (!layerReady && ticks.current < 40) return
      setOut(painted)
      window.clearInterval(timer)
    }, 120)
    return () => window.clearInterval(timer)
  }, [ready, tier, report, n])

  const spec = TIERS[tier]
  return (
    <section>
      <div className="fcp-change">
        <span className="badge">{spec.badge}</span>
        <div className="grid grid-cols-[1fr_460px] gap-4 p-1">
          <div>
            <div className="mb-2 flex flex-wrap items-baseline gap-2">
              <span className="text-aux font-semibold text-ink">{spec.name}</span>
              <span className="text-tag text-ink-3">{spec.point}</span>
              <span className="text-tag text-ink-3">代价：{spec.cost}</span>
            </div>
            <Frame h={480}>
              {ready ? (
                <LcMap report={report} showEvidenceDiscs={discOn} />
              ) : (
                <div className="p-4 text-tag text-ink-3">底图未就绪（无 AK 或脚本失败）⇒ 这一档预览无效，不拿上面那栏冒充</div>
              )}
            </Frame>
          </div>
          <div>
            <Rows title="这一栏当场读数（探针实测，不是描述）" rows={out.rows} />
            {out.card && <pre className="mt-2 whitespace-pre-wrap rounded-card border border-line bg-white/85 p-3 text-tag leading-relaxed text-ink-2">{out.card}</pre>}
            {tier === 'b' && (
              <div className="mt-2 rounded-chip border border-warn/50 bg-warn/10 px-3 py-2 text-tag font-medium text-[#8A6420]">
                ⚠ 上半段是真读数；灰虚线那一段是<b>示意</b> —— 后端没发「这一趟检回了哪些点」的键，拿现算的圈内点冒充检索产物就是假读数。
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function Legend() {
  return (
    <div className="fcp-legend">
      <div className="legend-title">图例 · 哪些是真读数、哪些是探针的取巧</div>
      <ol>
        <li>
          <b>数据</b>
          <div>
            两城 live 报告逐字节内嵌 <code>src/dev/fixtures/lcDiscFocus.json</code>：北京 {scale.beijing.discs} 盘 / {scale.beijing.distinct_anchors} 个不同 anchor /
            查全盘 {scale.beijing.complete_true} 个 / 盲区 {scale.beijing.blindspots} 个；凯里 {scale.kaili.discs} 盘 / {scale.kaili.distinct_anchors} anchor / 盲区{' '}
            {scale.kaili.blindspots} 个 ⇒「实线=查全」那一档在真读数上从不出现。
          </div>
        </li>
        <li>
          <b>组件与文案</b>
          <div>
            地图 = 真 <code>LcMap</code>；举证句 = <code>evidenceDiscTitle()</code>；锚点行 = <code>evidenceDiscAnchorLabel()</code>；命中 = <code>hitEvidenceDisc()</code>
            （①环带 &lt;12px &gt; ②圆心 &lt;10px &gt; ③内部归属 &gt; ④最近圆心，同级按下标）
          </div>
        </li>
        <li>
          <b>覆盖物怎么拿到</b>
          <div>
            <code>LcMapHandle</code> 只暴露 <code>locate</code> ⇒ 探针给 <code>BMapGL.Map.prototype.addOverlay</code> 打计数补丁再认领。<b>这是探针手法，落地时选中态在组件内部</b>（计划 Step 3）
          </div>
        </li>
        <li>
          <b>为什么降级栏先挂</b>
          <div>探针先把 <code>window.BMapGL</code> 播成空壳（组件 <code>new bmap.Map</code> 抛 ⇒ 自动降级），拿到 fallback 上报后再注真脚本 —— 两分支才能同页共存</div>
        </li>
        <li>
          <b>不做什么</b>
          <div>
            不改 <code>fillOpacity:0</code> / <code>enableClicking:false</code>（"勾开图层仍可拖动"那条真机证据的载体）；不重建相机；不拿现算的圈内点冒充检索产物
          </div>
        </li>
      </ol>
      <div className="legend-foot">出图：headless Chrome <code>preview-lc-disc.html?tier=…&amp;focus=…</code>；判成败看 PNG 字节数（空壳 ~70KB，真渲染 ~500KB–1MB）。</div>
    </div>
  )
}

function App() {
  const { tier, city, focus, n, discOn } = readParams()
  const [stage, setStage] = useState<'seed' | 'live' | 'noak'>('seed')
  const report = reports[city]

  useEffect(() => {
    seedEmptyNamespace()
  }, [])

  const onFallbackMode = useCallback((mode: string) => {
    if (mode !== 'fallback') return
    void (async () => {
      unseedNamespace()
      const cfg = await getMapConfig()
      if (!cfg.browserAk) {
        setStage('noak')
        return
      }
      try {
        const bmap = await loadBMapGL(cfg.browserAk)
        patchNamespace(bmap)
        ns = bmap
        setStage('live')
      } catch {
        setStage('noak')
      }
    })()
  }, [])

  return (
    <>
      <div className="mb-3 rounded-card border border-line bg-card p-3 text-tag text-ink-2 shadow-card">
        当前：档 <b>{tier.toUpperCase()}</b> · 城市 <b>{city}</b>（{report.scene.name}，data_origin={report.data_origin}）· 选中 <code>{focus}</code> · 证据域图层
        {discOn ? '开' : '关'} · 阶段 <code>{stage}</code>
      </div>

      <section className="mb-6">
        <div className="mb-2 flex flex-wrap items-baseline gap-2">
          <span className="rounded-chip bg-ink-2 px-2 py-0.5 text-tag font-semibold text-white">对照</span>
          <span className="text-aux font-semibold text-ink">降级画布（无 AK / 离线时那版）</span>
          <span className="text-tag text-ink-3">这一栏本来就有逐盘 &lt;title&gt; 举证句 · 不是你投诉发生的地方</span>
        </div>
        <Frame h={430}>
          <LcMap report={report} showEvidenceDiscs onMapMode={onFallbackMode} />
        </Frame>
      </section>

      <LiveColumn ready={stage === 'live'} tier={tier} report={report} n={n} discOn={discOn} />
      {stage === 'noak' && (
        <div className="box">
          <b>这一档的 live 预览没出来</b>：拿不到浏览器 AK 或 BMapGL 脚本加载失败 ⇒ 真地图分支画不了。按纪律<b>不拿上面那栏降级画布冒充</b>，请在本机 Chrome 打开同一 URL 复核。
        </div>
      )}
      <Legend />
    </>
  )
}

const host = document.getElementById('lc-disc-root')
if (host) createRoot(host).render(<App />)
