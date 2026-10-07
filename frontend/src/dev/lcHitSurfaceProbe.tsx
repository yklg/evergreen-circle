/**
 * 证据域图层 · 命中面与环段数对照探针（**预览闸，不改生产码**）
 *
 * 打开：`http://localhost:3400/preview-lc-hit.html`
 * 参数：`?city=kaili|beijing`（默认 kaili）· `?zoom=13|15|17|18|19`（默认 18）
 *
 * 要拍的一件事：证据盘这层**该占多大鼠标面积、该用几段画**。
 * 现状用 `bmap.Circle` + `fillOpacity:0` + `enableClicking:false` —— 视觉只剩一条边，
 * 但**可命中面是整个圆面**，而"不拦鼠标"这件事完全押在 `enableClicking` 这一枚
 * 第三方布尔上，且本仓从未真机验证过它生效（`LcMap.tsx:1028` 自陈）。
 *
 * 三屏：
 *  ① 现状对照 —— 挂**真组件** `LcMap`，勾开证据域。这一屏就是生产渲染，不复制画法。
 *  ② 命中面可视化 —— 把"鼠标能碰到哪儿"涂出来。档 A（圆面）vs 档 B/C（描边环）。
 *     「被挡面积 %」由真实 fixture 网格采样**当场算**，不是抄来的数。
 *  ③ 段数起棱放大 —— 沿环边界开一个放大窗，48 段（生产 `lcRing` 默认）vs 自适应段数，
 *     在所选 zoom 下直接看是否起棱，并列出弦长/弓高像素。
 *
 * 同源纪律（违反即预览作废）：
 * - ① 用真组件；②③ 的几何一律走 `lib/livingCircle.ts` 生产出口
 *   （`lcRing` / `lcMeters` / `lcToPx` / `LC_CANVAS` / `lcEvidenceDiscColor` /
 *   `evidenceDiscs` / `evidenceDiscTitle` / `LC_ISO_COLORS`），盘半径取真实读数。
 * - 数据 = `src/dev/fixtures/lcDiscFocus.json`：2026-09-30 两城**真打接口**落盘的 live
 *   报告（凯里 5 盘 / 北京 14 盘，`complete=true` 均为 0），零造盘、零删点。
 * - **档 C 的自适应段数是候选，生产里还没有这个函数** ⇒ 页内现算并打显式水印。
 *
 * 本屏**答不了**的两件事（留给真机 spike，页内图例也写明）：
 * - 真 BMapGL 上 `enableClicking` 到底生效吗（②涂的是"若失效会挡多大"，不是"失效了没"）；
 * - 真 BMapGL 的 `Polyline` 能不能画 `strokeStyle:'dashed'`（③画的是 SVG 虚线，仅示意）。
 *
 * 本目录（`src/dev/`）不被任何应用入口引用 ⇒ 不进生产包；但进 `tsc` 与 eslint。
 */
import { createRoot } from 'react-dom/client'
import { useMemo, useState } from 'react'
import '../index.css'
import fixture from './fixtures/lcDiscFocus.json'
import LcMap from '../components/lifecircle/LcMap'
import {
  LC_CANVAS,
  LC_ISO_COLORS,
  evidenceDiscs,
  evidenceDiscTitle,
  lcEvidenceDiscColor,
  lcMeters,
  lcRing,
  lcToPx,
} from '../lib/livingCircle'
import type { LivingCircleReport } from '../types'

type City = 'kaili' | 'beijing'
type Disc = ReturnType<typeof evidenceDiscs>[number]
type LngLat = [number, number]

const REPORTS = fixture as unknown as Record<City, LivingCircleReport>
const ZOOMS = [13, 15, 17, 18, 19] as const
/** 标准墨卡托每像素米数。百度档位表与此略有差异 ⇒ 页内一律标「估算」。 */
function mPerPx(zoom: number, lat: number): number {
  return (156543.03 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom
}
/** 档 B：生产 `lcRing` 的默认段数。 */
const STEPS_FIXED = 48
/** 档 C 候选：让弓高不超过 `budgetM` 米所需段数（生产里还没有这个函数）。 */
function adaptiveSteps(r: number, budgetM: number): number {
  const cos = 1 - budgetM / r
  if (cos <= -1) return 4
  return Math.max(4, Math.ceil(Math.PI / Math.acos(Math.min(1, cos))))
}
/** 弓高（米）：弦的中点落后圆弧多少。与 zoom 无关，是固定值。 */
function sagittaM(r: number, steps: number): number {
  return r * (1 - Math.cos(Math.PI / steps))
}

/* ───────────────────────── ① 现状对照 ───────────────────────── */

function CurrentScreen({ report }: { report: LivingCircleReport }) {
  /**
   * 照生产接法补中心点回调（`LifeCirclePage.tsx:687-688` 传 customCenter/onCenterChange，
   * `:803` 渲染那句 chip）。不接的话「拖中心点」这条判据在本页**永远不可能出现**，
   * spike 的三臂会全部假失败 —— 那是宿主缺件，不是图层挡的。
   */
  const [customCenter, setCustomCenter] = useState<LngLat | null>(null)
  const center: LngLat = customCenter ?? (report.scene.center as LngLat)
  return (
    <section className="box">
      <h2>① 现状对照 · 真组件生产渲染</h2>
      <p className="note">
        这一屏挂的是 <code>components/lifecircle/LcMap</code> 本体、<code>showEvidenceDiscs</code> 打开
        —— 不复制画法。看到的就是今天用户勾开「证据域」后看到的。
      </p>
      <div style={{ height: 520, borderRadius: 8, overflow: 'hidden', border: '1px solid #e3e8e5' }}>
        <LcMap report={report} showEvidenceDiscs customCenter={customCenter} onCenterChange={setCustomCenter} />
      </div>
      <div data-spike-center-chip="true" style={{ fontSize: 12.5, marginTop: 6, minHeight: 18, color: customCenter ? '#8a6420' : '#9aa39e' }}>
        {customCenter
          ? `已设定新中心点（${center[0].toFixed(4)}, ${center[1].toFixed(4)}）`
          : '（尚未拖拽中心点）'}
      </div>
    </section>
  )
}

/* ──────────────────── ② 命中面可视化 ──────────────────── */

type HitMode = 'face' | 'ring'

/** 网格采样算「被挡面积 / 可达区」。步长越小越准，20m 对 5km² 量级足够。 */
function hitShare(report: LivingCircleReport, discs: Disc[], mode: HitMode) {
  const center = report.scene.center as LngLat
  const cal = report.caliber as Record<string, number | undefined> | undefined
  const R = cal?.reach_circumradius_m ?? cal?.collect_radius_m ?? 1500
  // 档 B/C 的条带半宽 = 描边 1.4px 在 zoom 15（应用默认档，`LcMap.tsx:1012`）下的米数
  const bandHalf = (1.4 * mPerPx(15, center[1])) / 2
  /**
   * 步长取 bandHalf（≈3m）以保证至少每行都切到环带；档 A 数整片圆面，20m 足够。
   * ⚠️ 但实测两档读数对步长**不敏感**（20m→3m 只让档 B 从 0.61% 变 0.63%）⇒
   * 档 B 那个小数值是**几何本身如此**（多数环带整条落在可达区外），不是采样不足。
   * 步长随读数一起上屏供对账，别让人把"数得稀"当成"挡得少"的原因。
   */
  const step = mode === 'face' ? 20 : Math.max(0.5, bandHalf)
  const n = Math.ceil((2 * R) / step)
  const anchors = discs.map((d) => ({ m: lcMeters(center, d.anchor[0], d.anchor[1]), r: d.exhausted_radius_m }))
  let inside = 0
  let hit = 0
  for (let i = 0; i <= n; i++) {
    const x = -R + i * step
    for (let j = 0; j <= n; j++) {
      const y = -R + j * step
      if (Math.hypot(x, y) > R) continue
      inside++
      for (const a of anchors) {
        const dist = Math.hypot(x - a.m[0], y - a.m[1])
        const on = mode === 'face' ? dist <= a.r : Math.abs(dist - a.r) <= bandHalf
        if (on) {
          hit++
          break
        }
      }
    }
  }
  return { share: inside ? hit / inside : 0, R, km2: (hit * step * step) / 1e6, reachKm2: (inside * step * step) / 1e6, step }
}

/** 单盘各自能盖住可达区的最大比例 —— 用来判断"满格"是单盘造成的还是并集造成的。 */
function maxSingleShare(report: LivingCircleReport, discs: Disc[]): number {
  const center = report.scene.center as LngLat
  const cal = report.caliber as Record<string, number | undefined> | undefined
  const R = cal?.reach_circumradius_m ?? cal?.collect_radius_m ?? 1500
  let best = 0
  for (const d of discs) {
    const [ax, ay] = lcMeters(center, d.anchor[0], d.anchor[1])
    if (Math.hypot(ax, ay) + d.exhausted_radius_m <= R) {
      // 该盘整体落在可达区内，直接算面积比
      best = Math.max(best, (d.exhausted_radius_m / R) ** 2)
      continue
    }
    best = Math.max(best, singleDiscShare(R, ax, ay, d.exhausted_radius_m))
  }
  return best
}
function singleDiscShare(R: number, ax: number, ay: number, r: number): number {
  const step = 40
  const n = Math.ceil((2 * R) / step)
  let inside = 0
  let hit = 0
  for (let i = 0; i <= n; i++) {
    const x = -R + i * step
    for (let j = 0; j <= n; j++) {
      const y = -R + j * step
      if (Math.hypot(x, y) > R) continue
      inside++
      if (Math.hypot(x - ax, y - ay) <= r) hit++
    }
  }
  return inside ? hit / inside : 0
}

type HitStat = { share: number; km2: number; R: number; reachKm2: number; step: number }

function HitPanel({
  title,
  stat,
  mode,
  paths,
  anchors,
  isoPoints,
}: {
  title: string
  stat: HitStat
  mode: HitMode
  paths: string[]
  anchors: { category: string; px: [number, number] }[]
  isoPoints: string
}) {
  const { W, H } = LC_CANVAS
  return (
    <figure style={{ margin: 0, flex: '1 1 0', minWidth: 0 }}>
      <figcaption style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
        {title}
        <span style={{ marginLeft: 8, fontWeight: 400, color: '#8a2b2b' }}>
          被挡 {stat.share > 0.995 ? '≈100%' : `${(stat.share * 100).toFixed(2)}%`} 可达区 · {stat.km2.toFixed(2)}km²
          <span style={{ marginLeft: 6, opacity: 0.7 }}>（网格步长 {stat.step.toFixed(1)}m）</span>
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', background: '#f7faf8', border: '1px solid #e3e8e5', borderRadius: 8 }}>
        {isoPoints && <polygon points={isoPoints} fill={LC_ISO_COLORS[2].fill} stroke={LC_ISO_COLORS[2].stroke} strokeWidth={1} />}
        {paths.map((p, i) =>
          mode === 'face' ? (
            <polygon key={i} points={p} fill="#c0392b" fillOpacity={0.3} stroke="none" />
          ) : (
            <polyline key={i} points={p} fill="none" stroke="#c0392b" strokeOpacity={0.85} strokeWidth={2.4} />
          ),
        )}
        {anchors.map((a, i) => (
          <circle key={`a${i}`} cx={a.px[0]} cy={a.px[1]} r={2.5} fill={lcEvidenceDiscColor(a.category)} />
        ))}
      </svg>
    </figure>
  )
}

function HitScreen({ report, discs }: { report: LivingCircleReport; discs: Disc[] }) {
  const center = report.scene.center as LngLat
  const face = useMemo(() => hitShare(report, discs, 'face'), [report, discs])
  const ring = useMemo(() => hitShare(report, discs, 'ring'), [report, discs])
  const maxSingle = useMemo(() => maxSingleShare(report, discs), [report, discs])
  const iso = report.isochrones.find((z) => z.minutes === 15) ?? report.isochrones[0]

  const ringPath = (d: Disc) =>
    lcRing(d.anchor as LngLat, d.exhausted_radius_m, STEPS_FIXED)
      .map(([lng, lat]) => lcToPx(center, lng, lat).join(','))
      .join(' ')

  const facePaths = discs.map(ringPath)
  const anchors = discs.map((d) => ({ category: d.category, px: lcToPx(center, d.anchor[0], d.anchor[1]) }))
  const isoPoints = iso
    ? (iso.geojson.coordinates[0] as LngLat[]).map(([lng, lat]) => lcToPx(center, lng, lat).join(',')).join(' ')
    : ''

  return (
    <section className="box">
      <h2>② 命中面可视化 · 把「鼠标能碰到哪儿」涂出来</h2>
      <p className="note">
        现状 <code>fillOpacity:0</code> ⇒ 视觉上本来就只剩一条边，所以两种画法<b>看起来一样</b>；
        真正的区别在这里才现形：红色 = 鼠标会被这层接住的范围。
        「被挡 %」是拿这份真报告<b>当场数出来的</b>，不是抄的；网格步长随读数一起标在标题里。
        ⚠️ 档 B 之所以只剩个位数百分比，<b>主要不是因为环带窄</b>：本城{' '}
        {discs.filter((d) => d.exhausted_radius_m > face.R).length}/{discs.length} 个盘的半径大于可达区外接圆{' '}
        {face.R.toFixed(0)}m ⇒ 它们的环带整条落在可达区<b>之外</b>，本来就不挡事。
        真正要盯的是那些<b>擦进可达区</b>的弧。
      </p>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <HitPanel title="档 A · 现状（bmap.Circle ⇒ 可命中面 = 整个圆面）" stat={face} mode="face" paths={facePaths} anchors={anchors} isoPoints={isoPoints} />
        <HitPanel title="档 B · 描边环（沿圆周 Polyline ⇒ 可命中面 = 那条边）" stat={ring} mode="ring" paths={facePaths} anchors={anchors} isoPoints={isoPoints} />
      </div>
      <p className="note" style={{ marginTop: 10 }}>
        本城 {discs.length} 盘 / {new Set(discs.map((d) => d.anchor.join(','))).size} 个锚点，
        半径 {Math.min(...discs.map((d) => d.exhausted_radius_m)).toFixed(0)}–
        {Math.max(...discs.map((d) => d.exhausted_radius_m)).toFixed(0)}m，
        而可达区外接圆只有 {face.R.toFixed(0)}m ⇒{' '}
        {maxSingle > 0.995 ? (
          <>
            <b>单个盘就盖满整块可达区</b>（最大单盘覆盖 {(maxSingle * 100).toFixed(0)}%）。
          </>
        ) : (
          <>
            没有任何单盘盖满（最大单盘 {(maxSingle * 100).toFixed(0)}%），
            <b>是 {discs.length} 盘的并集盖满了整块可达区</b>。
          </>
        )}{' '}
        拖中心点、点空白关卡、悬停采样点这三件事的活动范围，全部落在这块隐形面底下。
      </p>
      <p className="warn">
        ⚠️ 这一屏涂的是「<b>若</b> <code>enableClicking</code> 失效会挡多大」，不是「它失效了没有」。
        后者只有真机能答 —— 那是 spike 的 R1，不在预览里充数。
      </p>
    </section>
  )
}

/* ──────────────────── ③ 段数起棱放大 ─────────────────── */

function FacetScreen({ discs, zoom, lat }: { discs: Disc[]; zoom: number; lat: number }) {
  const [r, setR] = useState(() => Math.max(...discs.map((d) => d.exhausted_radius_m)))
  const scale = mPerPx(zoom, lat)
  const VW = 640
  const VH = 340
  const budgetM = scale * 0.5 // 让弓高 ≤ 0.5px 所需的米预算

  const rows = [
    { name: '档 B · 48 段（生产 lcRing 默认）', steps: STEPS_FIXED },
    { name: '档 C · 自适应段数（候选，生产里还没有）', steps: adaptiveSteps(r, budgetM) },
  ]

  /**
   * 环在局部几乎是条竖线 ⇒ 窗必须按**弦长**开，而不是按屏幕米数开，
   * 否则弓高（几米）在 340px 高的窗里根本看不出来（上一版就是这么画废的）。
   * 每档出两图：左「真实比例」给可信形状，右「径向偏差 ×N」把弓高放大到肉眼可辨，
   * 放大倍率写在图注里 —— 放大的是偏差，不是把图谎报成 1:1。
   */
  const MAG = 20

  const ringPtsM = (steps: number): [number, number][] =>
    lcRing([0, 0], r, steps).map(([lng, lat2]) => lcMeters([0, 0], lng, lat2))

  /** 弦中点的半径按 mag 倍内缩，顶点仍落在真圆上 —— 锯齿即弓高。 */
  const jaggedPtsM = (steps: number, mag: number): [number, number][] => {
    const theta = (2 * Math.PI) / steps
    const rm = r - sagittaM(r, steps) * mag
    const out: [number, number][] = []
    for (let i = 0; i <= steps; i++) {
      const a = i * theta
      out.push([r * Math.cos(a), r * Math.sin(a)])
      if (i < steps) {
        const am = a + theta / 2
        out.push([rm * Math.cos(am), rm * Math.sin(am)])
      }
    }
    return out
  }

  const toPath = (pts: [number, number][], chord: number): string => {
    const pxPerM = VW / (2.6 * chord)
    return pts.map(([mx, my]) => `${(VW / 2 + (mx - r) * pxPerM).toFixed(1)},${(VH / 2 - my * pxPerM).toFixed(1)}`).join(' ')
  }

  return (
    <section className="box">
      <h2>③ 段数起棱 · 沿环边界按弦长开窗</h2>
      <p className="note">
        把环改成"沿圆周画线"要付的代价：<code>lcRing</code> 固定 {STEPS_FIXED} 段，半径越大越接近多边形。
        每档两图：<b>真实比例</b>（可信形状）与 <b>径向偏差 ×{MAG}</b>（把弓高放大到看得出，
        放大的是偏差量、倍率写在图注里）。灰线是 2000 段参考真圆。
      </p>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <label style={{ fontSize: 12.5 }}>
          盘半径（真读数）：
          <select value={r} onChange={(e) => setR(Number(e.target.value))}>
            {[...new Set(discs.map((d) => Math.round(d.exhausted_radius_m)))].sort((a, b) => a - b).map((v) => (
              <option key={v} value={v}>{v} m</option>
            ))}
          </select>
        </label>
        <span style={{ fontSize: 12.5 }}>
          zoom：<b>{zoom}</b>（估算 {scale.toFixed(2)} m/px）
        </span>
      </div>
      <div style={{ display: 'grid', gap: 14 }}>
        {rows.map((row) => {
          const sag = sagittaM(r, row.steps)
          const chord = 2 * r * Math.sin(Math.PI / row.steps)
          const sagPx = sag / scale
          return (
            <div key={row.name}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>
                {row.name} · {row.steps} 段
                <span style={{ marginLeft: 10, fontWeight: 400, color: '#1d211f' }}>
                  弦长 {chord.toFixed(0)}m ≈ {(chord / scale).toFixed(0)}px ｜ 弓高 {sag.toFixed(2)}m ≈{' '}
                  <b style={{ color: sagPx > 1 ? '#8a2b2b' : '#2f6b4f' }}>{sagPx.toFixed(1)}px</b>
                  {sagPx > 1 ? '（肉眼可辨）' : '（亚像素，看不出）'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {([['真实比例', 1], [`径向偏差 ×${MAG}`, MAG]] as const).map(([cap, mag]) => (
                  <figure key={String(cap)} style={{ margin: 0, flex: '1 1 340px', minWidth: 0 }}>
                    <figcaption style={{ fontSize: 11.5, color: '#5a625e' }}>{cap}</figcaption>
                    <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: '100%', background: '#f7faf8', border: '1px solid #e3e8e5', borderRadius: 8 }}>
                      <polyline points={toPath(ringPtsM(2000), chord)} fill="none" stroke="#c9d4cc" strokeWidth={1.2} />
                      <polyline
                        points={toPath(mag === 1 ? ringPtsM(row.steps) : jaggedPtsM(row.steps, mag), chord)}
                        fill="none"
                        stroke={LC_ISO_COLORS[2].stroke}
                        strokeWidth={1.6}
                        strokeDasharray="6 4"
                      />
                    </svg>
                  </figure>
                ))}
              </div>
            </div>
          )
        })}
      </div>
      <p className="note" style={{ marginTop: 10 }}>
        弓高是<b>固定米值</b>（与缩放无关），变的是它占多少像素 ⇒ 换 zoom 看那一列红/绿数字最直观。
        档 C 的段数按「弓高 ≤ 0.5px」现算，<b>生产里没有这个函数</b>：若走这条路，
        <code>lcRing</code> 要加自适应段数，而它是 4 处调用的共用出口
        （<code>LcMap.tsx:1217</code> 判定尺降级 · <code>:1283</code> 证据盘降级 ·
        <code>lcP5Probe.tsx:240</code> · <code>lifeCircleForensicUi.test.tsx:261</code>）。
      </p>
      <p className="warn">
        ⚠️ 这里画的是 SVG 虚线，只用来对照段数。真 BMapGL 的 <code>Polyline</code> 能不能画
        <code>strokeStyle:'dashed'</code> 从未实测（09-23 那次只测了「透明描边可拾取」）—— 那是 spike 的 R2。
      </p>
    </section>
  )
}

/* ──────────────────── 举证句（同源出口） ──────────────────── */

function DiscTable({ discs }: { discs: Disc[] }) {
  return (
    <section className="box">
      <h2>本屏用的真读数（零造盘）</h2>
      <table style={{ fontSize: 12.5, borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr style={{ textAlign: 'left', borderBottom: '1px solid #e3e8e5' }}>
            <th style={{ padding: '4px 6px' }}>类别</th>
            <th style={{ padding: '4px 6px' }}>锚点</th>
            <th style={{ padding: '4px 6px' }}>请求 m</th>
            <th style={{ padding: '4px 6px' }}>实测查到 m</th>
            <th style={{ padding: '4px 6px' }}>举证句（生产出口 evidenceDiscTitle）</th>
          </tr>
        </thead>
        <tbody>
          {discs.map((d, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #f0f3f1' }}>
              <td style={{ padding: '4px 6px' }}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, marginRight: 6, background: lcEvidenceDiscColor(d.category) }} />
                {d.category}
              </td>
              <td style={{ padding: '4px 6px' }}>{d.anchor.map((v) => (+v).toFixed(4)).join(', ')}</td>
              <td style={{ padding: '4px 6px' }}>{d.request_radius_m.toFixed(1)}</td>
              <td style={{ padding: '4px 6px' }}>{d.exhausted_radius_m.toFixed(1)}</td>
              <td style={{ padding: '4px 6px', color: '#5a625e' }}>{evidenceDiscTitle(d)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note" style={{ marginTop: 8 }}>
        <code>complete=true</code> 的盘：本城 {discs.filter((d) => d.complete).length} / {discs.length} ⇒
        图例上「实线=查全」那一档在存量报告里<b>从不出现</b>（两城真读数均为 0）。
      </p>
    </section>
  )
}

function Legend() {
  return (
    <section className="box">
      <h2>这屏答了什么 / 没答什么</h2>
      <ul style={{ fontSize: 12.5, lineHeight: 1.75, margin: '6px 0 0', paddingLeft: 20 }}>
        <li><b>答了</b>：两种画法的可命中面差多少（②，当场数出来的百分比）；48 段在多大 zoom 开始看得出棱（③，可切档）。</li>
        <li><b>没答</b>：真 BMapGL 读不读 <code>enableClicking</code> ⇒ spike 的 R1（且 R1 必须挂真组件测，自建 map 复制画法违反同源纪律）。</li>
        <li><b>没答</b>：真 BMapGL 的 <code>Polyline</code> 能不能画虚线 ⇒ spike 的 R2，09-23 那次从未测过这一项。</li>
        <li><b>没答</b>：<code>fill=&quot;none&quot;</code> 的 SVG 盘内到底响不响应悬停 ⇒ spike 的 R3（用 elementFromPoint 问浏览器）。</li>
      </ul>
    </section>
  )
}

function App() {
  const params = new URLSearchParams(location.search)
  const [city, setCity] = useState<City>(() => (params.get('city') === 'beijing' ? 'beijing' : 'kaili'))
  const [zoom, setZoom] = useState<number>(() => {
    const z = Number(params.get('zoom'))
    return (ZOOMS as readonly number[]).includes(z) ? z : 18
  })
  const report = REPORTS[city]
  const discs = evidenceDiscs(report)

  return (
    <div className="wrap">
      <div className="topbar">
        <h1>证据域图层 · 命中面与环段数对照</h1>
        <div className="sub">
          要拍的一件事：这层该占多大鼠标面积、该用几段画。数据 = 2026-09-30 两城真打接口落盘的 live 报告。
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
          <label style={{ fontSize: 12 }}>
            城市
            <select value={city} onChange={(e) => setCity(e.target.value as City)} style={{ marginLeft: 6 }}>
              {(['kaili', 'beijing'] as const).map((k) => (
                <option key={k} value={k}>
                  {(REPORTS[k].scene.name ?? k) + `（${evidenceDiscs(REPORTS[k]).length} 盘）`}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 12 }}>
            ③ 的 zoom
            <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))} style={{ marginLeft: 6 }}>
              {ZOOMS.map((z) => (
                <option key={z} value={z}>{z}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <CurrentScreen report={report} />
      <HitScreen report={report} discs={discs} />
      <FacetScreen discs={discs} zoom={zoom} lat={report.scene.center[1]} />
      <DiscTable discs={discs} />
      <Legend />
    </div>
  )
}

const host = document.getElementById('lc-hit-root')
if (host) createRoot(host).render(<App />)
