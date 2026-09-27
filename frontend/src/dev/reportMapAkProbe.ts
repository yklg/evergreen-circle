/**
 * 报告地图 AK 链路 · 活体取证页（预览闸口产物，不改生产代码）。
 *
 * 打开：`http://localhost:3400/preview-report-map-ak.html`（可 `?report=<id>` 指定报告）
 *
 * 左列挂**真实** `BMapBlock`（改动后：读 `map-config` ⇒ 应与右列逐像素一致；
 * 改动前的灰框样子见 `预览-报告地图AK链路-2026-09-26/probe-改动前.png`）；
 * 右列按计划链路手搓同一张图：`getMapConfig()` → `loadBMapGL()` →
 * `setMapStyleV2(lcMapStyle(false))` → 打点/折线。
 * AK、加载器、底图样式全部取自 `lib/bmap` 与 `lib/bmapStyle`，与 `LcMap` 和单测同一份真源。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用，故不进生产包；但会被 `tsc` 与 `eslint` 纳入检查。
 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import { BMapBlock, type MapSpot } from '../components/BMapBlock'
import { getMapConfig, loadBMapGL } from '../lib/bmap'
import { lcMapStyle } from '../lib/bmapStyle'

type Row = Record<string, unknown>

function note(msg: string): void {
  const el = document.getElementById('status')
  if (el) el.textContent = msg
}

/** 深度遍历报告 JSON，收集 `type===t` 的结构化块 data（不假设章节顺序与层级）。 */
function collectBlocks(root: unknown, t: string, out: Row[] = []): Row[] {
  if (Array.isArray(root)) {
    for (const v of root) collectBlocks(v, t, out)
  } else if (root && typeof root === 'object') {
    const o = root as Row
    if (o.type === t && Array.isArray(o.data)) out.push(...(o.data as Row[]))
    for (const k of Object.keys(o)) collectBlocks(o[k], t, out)
  }
  return out
}

const isMappable = (s: MapSpot): boolean =>
  s.matched !== false && typeof s.lat === 'number' && typeof s.lng === 'number'

/** 榜单块 → 地图行（与 `VSpotAtlas` 的映射规则逐字段一致）。 */
function toSpots(rows: Row[]): MapSpot[] {
  return rows
    .flatMap((g) => (Array.isArray(g.items) ? (g.items as Row[]) : []))
    .map((it) => ({
      spot_id: String(it.spot_id ?? ''),
      name: String(it.name ?? ''),
      area: it.area ? String(it.area) : undefined,
      score: typeof it.score === 'number' ? it.score : undefined,
      matched: it.matched === false ? false : undefined,
      lat: it.lat as number | null | undefined,
      lng: it.lng as number | null | undefined,
    }))
    .filter((s) => s.spot_id)
}

/** 逐日路线块 → 有序折线行（与 `VRoutePlan` 的过滤规则一致）。 */
function toTrail(rows: Row[]): MapSpot[] {
  return rows
    .flatMap((d) => (Array.isArray(d.days) ? (d.days as Row[]) : []))
    .flatMap((day) => (Array.isArray(day.spots) ? (day.spots as Row[]) : []))
    .filter((s) => s.spot_id && !s.shop_id && typeof s.lat === 'number' && typeof s.lng === 'number')
    .map((s) => ({
      spot_id: String(s.spot_id),
      name: String(s.name ?? ''),
      lat: s.lat as number,
      lng: s.lng as number,
    }))
}

async function findReport(): Promise<{ id: string; title: string; spots: MapSpot[]; trail: MapSpot[] } | null> {
  const forced = new URLSearchParams(location.search).get('report')
  let ids: string[]
  if (forced) {
    ids = [forced]
  } else {
    const cards = (await (await fetch('/api/reports?limit=60')).json()) as { report_id?: string }[]
    ids = Array.isArray(cards) ? cards.map((c) => String(c.report_id ?? '')) : []
  }
  for (const id of ids) {
    if (!id) continue
    try {
      const r = (await (await fetch(`/api/reports/${id}`)).json()) as Row
      const spots = toSpots(collectBlocks(r, 'spot_ranking'))
      const trail = toTrail(collectBlocks(r, 'route_plan'))
      if (spots.some(isMappable) || trail.length >= 2) {
        return { id, title: String(r.title ?? id), spots, trail }
      }
    } catch {
      /* 逐份试：单份取不到就跳过，不假装成功 */
    }
  }
  return null
}

/** 目标态渲染：与计划 C1/C2/C3 描述的调用序列一致（取景方式刻意沿用现状，不顺手改）。 */
async function renderTarget(elId: string, spots: MapSpot[], trail: boolean): Promise<string> {
  const holder = document.getElementById(elId)
  if (!holder) return `${elId}: 容器缺失`
  const mappable = spots.filter(isMappable)
  if (mappable.length < (trail ? 2 : 1)) return `${elId}: 可定位点位不足（${mappable.length}）`
  const cfg = await getMapConfig()
  if (!cfg.browserAk) {
    holder.textContent = '（后端未下发浏览器端 AK —— 与现状同形）'
    return `${elId}: 无 AK`
  }
  const bmap = await loadBMapGL(cfg.browserAk)
  const first = mappable[0]
  const map = new bmap.Map(holder)
  map.centerAndZoom(new bmap.Point(first.lng as number, first.lat as number), 12)
  map.enableScrollWheelZoom()
  map.setMapStyleV2(
    cfg.mapStyleId ? { styleId: cfg.mapStyleId } : { styleJson: lcMapStyle(false) },
  )
  for (const s of mappable) {
    map.addOverlay(new bmap.Marker(new bmap.Point(s.lng as number, s.lat as number), { title: s.name }))
  }
  if (trail) {
    map.addOverlay(
      new bmap.Polyline(
        mappable.map((s) => new bmap.Point(s.lng as number, s.lat as number)),
        { strokeColor: '#7C9885', strokeWeight: 4, strokeOpacity: 0.85 },
      ),
    )
  }
  return `${elId}: ${mappable.length} 点已渲染 · 底图=${cfg.mapStyleId ? 'styleId' : '内置 styleJson（注记关）'}`
}

function mountCurrent(elId: string, spots: MapSpot[], trail: boolean): void {
  const el = document.getElementById(elId)
  if (!el) return
  createRoot(el).render(
    createElement(BMapBlock, trail ? { spots, trail, height: 380 } : { spots }),
  )
}

async function main(): Promise<void> {
  const pre = document.getElementById('precheck')
  const cfg = await getMapConfig()
  if (pre) {
    pre.innerHTML =
      `<b>map-config 实测</b>：browser_ak = <code>${cfg.browserAk ? `${cfg.browserAk.slice(0, 6)}…（后端已下发）` : '（空）'}</code>` +
      ` · map_style_id = <code>${cfg.mapStyleId || '（空 → 用内置 styleJson）'}</code>` +
      `<br>这份 AK 就是地图页现在在用的那一个；报告地图读不到它，只因为读的是另一个变量名。`
  }
  const rep = await findReport()
  if (!rep) {
    note('未找到含可定位景点的报告：用 ?report=<id> 指定一份目的地调研报告。')
    return
  }
  const rankingCount = rep.spots.filter(isMappable).length
  note(
    `取证报告：${rep.title}（${rep.id}）· 榜单可定位 ${rankingCount} 点 · 行程可定位 ${rep.trail.length} 站` +
      '（左列＝真实组件现状，右列＝计划改动后行为）',
  )
  mountCurrent('before-spot', rep.spots, false)
  /** 串联演示优先用该报告真实逐日坐标；无坐标时借用榜单点位（页面已标注，不冒充真实行程）。 */
  const synthetic = rep.trail.length < 2
  const trail = synthetic ? rep.spots.filter(isMappable) : rep.trail
  const log: string[] = []
  log.push(await renderTarget('after-spot', rep.spots, false))
  log.push(await renderTarget('after-trail', trail, true))
  if (synthetic) {
    const el = document.getElementById('trail-caveat')
    if (el) el.hidden = false
  }
  note(`取证报告：${rep.title}（${rep.id}）· ${log.join(' · ')}`)
}

main().catch((e: unknown) => note(`取证页异常：${String(e)}`))
