/**
 * 常青圈 · 生活圈工具库（类型无关的纯函数 + 常量）。
 *
 * 单一实现来源：地图页 / 报告页快照 / 对比页共用同一套投影与配色，
 * 避免各页面各自复制一份「m 等距投影 → 像素」逻辑造成画布不一致。
 * M 阶段 BMapGL 接入后仅替换渲染层，投影语义保持不变。
 */
import type {
  CellsLedgerRaw,
  EvidenceDisc,
  FacilityCategoryStat,
  ForensicAccount,
  ForensicRoundRow,
  IsoCompare,
  LifeCircleDegraded,
  LifeCirclePartial,
  LngLat,
  LivingCircleReport,
  PoiPoint,
  ShapeCaliber,
  TriadFacility,
} from '../types'

/* 画布几何：研究范围 5km × 5km → 画布 W×H（m 等距投影局部近似，单一真相源） */
export const LC_CANVAS = { R: 2500, W: 860, H: 620 } as const

/** POI 类别配色（常青圈地图图例，报告快照共用） */
export const LC_CAT_COLOR: Record<string, string> = {
  market: '#C2642E',
  medical: '#E0483F',
  education: '#2F7FBF',
  shopping: '#8A6BD1',
  elderly: '#C09A2E',
  finance: '#5F8A6A',
  recreation: '#2FA09A',
  service: '#7C6670',
}

/** 类别 label 兜底（与 fixture 的 label 对齐，缺省回退）—— 单源在 `lcCatLabel`（rev3 §四I） */
import { LC_CAT_LABEL } from './lcCatLabel'
export { LC_CAT_LABEL }

/**
 * 等时圈分级配色（5→20 分钟由深到浅）；报告/地图共用。
 * ⚠️ 两条硬约束：① 必须保持 rgba 字符串 —— BMapGL 的 Polygon 忽略 fillColor 的 alpha、
 * 只认 fillOpacity，由 `lcFillSpec` 拆成 color+opacity（2026-09-19 现场事故），不能改写 hex；
 * ② 最内圈 alpha ≤ 0.30 —— 圈覆盖底图道路，更深会把道路分级整片压住。
 */
export const LC_ISO_COLORS = [
  { fill: 'rgba(124,152,133,0.30)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.20)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.12)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.06)', stroke: '#5F7B69' },
]

/** 对比页 B 社区等时圈配色（品牌蓝系，与 A 绿色系区分；同受上面两条约束，且与 A 同档差值不失衡） */
export const LC_ISO_COLORS_B = [
  { fill: 'rgba(22,119,255,0.28)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.18)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.10)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.05)', stroke: '#1677ff' },
]

/** 盲区严重度语义色带（C2：重度红 / 中度橙 / 轻度黄；老数据缺 severity → 灰） */
export const LC_BLIND_SEV: Record<string, { fill: string; stroke: string; label: string; dot: string }> = {
  heavy: { fill: 'rgba(214,69,69,0.30)', stroke: '#d64545', label: '重度', dot: '#d64545' },
  medium: { fill: 'rgba(232,154,60,0.30)', stroke: '#e89a3c', label: '中度', dot: '#e89a3c' },
  light: { fill: 'rgba(227,200,79,0.33)', stroke: '#d9bd3a', label: '轻度', dot: '#d9bd3a' },
}
/** 补点处方符号（C3：实心绿核 + 白边） */
export const LC_FIX_DOT = '#1f9e63'
/** 判定尺那一圈（C2）与概览小图的参考圆（C3）共用的颜色 —— tailwind `info` token（莫兰迪蓝）。
 *  选它是因为它**不在**严重度色阶（红/橙/黄）与等时圈五级色里：这一层说的是"尺子多大"，
 *  不该被读成"这里多严重"。两处必须同一个色，否则图例与概览说的不是一回事。 */
export const LC_JUDGE_SCALE_COLOR = '#8FA8C0'

/** 口径对照环的线色（笔 B）：与四档色阶、判定尺蓝都拉开，且**只描边不填充** ——
 *  解释层填了就会把五级等时圈色阶压掉（与判定尺、证据盘同一条纪律）。 */
export const LC_ISO_COMPARE_COLOR = '#B45309'
/** 固有尺寸（G5 定版）：SVG 串自带 18×18，图例等消费方用 CSS 缩放 —— 同源=串，尺寸归消费方 */
export const LC_FIX_ICON_SIZE = 18

/**
 * 补点处方图标 SVG 串（C4 单一出口）：地图 Marker（LcMap fixPlusIcon）与页面图例
 * （LifeCirclePage 图层卡）**消费同一导出**——图例即真实标记的样子（评审 R7 契约）。
 * 纯函数、零 bmap 依赖：lib 层不引入 SDK 类型（与 livingCircle.ts 现状一致）。
 */
export function fixPlusSvg(color: string = LC_FIX_DOT): string {
  const s = LC_FIX_ICON_SIZE
  const c = s / 2
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
    `<circle cx="${c}" cy="${c}" r="${c - 1}" fill="rgba(31,158,99,0.16)" stroke="${color}" stroke-width="1.5"/>` +
    `<path d="M${c} 5 V13 M5 ${c} H13" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>` +
    `<path d="M${c} 5 V13 M5 ${c} H13" stroke="${color}" stroke-width="2" stroke-linecap="round"/></svg>`
  )
}

/** fixPlusSvg → data URL（Marker Icon 与图例 <img> 共用的编码出口） */
export function fixPlusSvgDataUrl(color: string = LC_FIX_DOT): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fixPlusSvg(color))}`
}
export const LC_BLIND_SEV_ORDER = ['heavy', 'medium', 'light'] as const
/** 补建策略 → 中文（C3 补点 title/图例） */
export const LC_BLIND_FIX_STRATEGY: Record<string, string> = {
  mobile_service: '流动服务',
  reroute: '移动点/改道补充',
  build: '补建站点',
}
/** defs 连续缺口热力渐变 id（C1：低→高） */
export const LC_HEAT_GRADIENT_ID = 'lc-blind-heat'

export function blindSevSpec(sev: string | undefined) {
  return (LC_BLIND_SEV[sev as string] || { fill: 'rgba(120,120,120,0.16)', stroke: '#8a8a8a', label: '', dot: '#E8B54D' })
}

/* —— 盲区适配/缺省层（R4/契约文档 §5）：新字段缺失时不崩、不误判 —— */

const LC_BLIND_FALLBACK = { severity: 'light', gap_score: null, fixes: [], affected: null } as const

/** 严重度安全取值：缺省回退 light（老数据最保守，不夸大整改级别）。 */
export function severityOf(b: { severity?: string }): string {
  const sev = b?.severity
  return sev && LC_BLIND_SEV[sev as string] ? sev : LC_BLIND_FALLBACK.severity
}

/** 连续缺口指数安全取值：缺失/null/越界 → null（渲染层回退灰，不误绘热力）。 */
export function gapScoreOf(b: { gap_score?: unknown }): number | null {
  const g = b?.gap_score
  if (typeof g !== 'number' || !Number.isFinite(g)) return null
  return Math.min(1, Math.max(0, g))
}

/** 补点处方安全取值：缺失/非数组 → []（不崩）。 */
export function fixesOf(b: { fixes?: unknown }): unknown[] {
  const fx = b?.fixes
  return Array.isArray(fx) ? fx : []
}

/** 受影响人群安全取值：缺省/无 provenance → null（诚实标注，不漏报伪代理）。 */
export function affectedOf(b: { affected?: unknown }): unknown {
  const af = b?.affected
  return af && typeof af === 'object' && af != null && (af as { provenance?: string }).provenance ? af : null
}

/** 受影响的显著场景标签（v3：欠采样/粗分辨率时显示「细化边界不可用」入口） */
export function footprintMetaOf(b: { footprint_meta?: unknown }): {
  cells: number
  resolution_m: number
  grid_m: number
  refine: number
  area_m2: number | null
  undersampled: boolean
  grid: string
} | null {
  const m = b?.footprint_meta
  if (!m || typeof m !== 'object' || m == null) return null
  const d = m as Record<string, unknown>
  const num = (k: string) => (typeof d[k] === 'number' && Number.isFinite(d[k]) ? Number(d[k]) : 0)
  return {
    cells: num('cells'),
    resolution_m: num('resolution_m'),
    grid_m: num('grid_m'),
    refine: num('refine'),
    area_m2: typeof d.area_m2 === 'number' && Number.isFinite(d.area_m2) ? Number(d.area_m2) : null,
    undersampled: d.undersampled === true,
    grid: typeof d.grid === 'string' ? d.grid : 'square',
  }
}

/**
 * 分享脱敏（口径 ③-A）的「概略片区」折算 —— 全仓唯一实现。
 *
 * 不暴露精确多边形的逐格边界，只画**面积等价圆**：半径 = √(area_m2/π)；
 * 缺 `footprint_meta.area_m2` 时退化为判定格距近似圆。
 *
 * ⚠️ 报告静态快照（`BlindCoarseCircle`）与交互式地图（`LcMap` 的 `desensitize` 分支）
 * 必须共用本函数。两处各写一份 `sqrt(area/π)` 的话，一旦其中一处改了口径，
 * 公开分享链接就会有一侧仍在泄漏逐格边界 —— 而那正是这条脱敏要防的事。
 */
export function coarseBlindFootprint(b: { footprint_meta?: unknown }): { radiusM: number; label: string } {
  const fm = footprintMetaOf(b)
  const gridM = fm?.grid_m ?? 200
  const area = fm?.area_m2 ?? Math.PI * gridM * gridM
  const radiusM = area > 0 ? Math.sqrt(area / Math.PI) : gridM
  const label = fm?.area_m2 != null ? `概略 ${(fm.area_m2 / 1e4).toFixed(1)}公顷（面积当量）` : '概略片区'
  return { radiusM, label }
}

/** 分享态明细表脱敏（口径 ③-A 的表格侧补全）。
 *
 *  只剥两类粒度：① 经纬度对（`107.9758, 26.5734` 形态）② `gap 0.262` 这类缺口指数。
 *  方位与"最近 N m"保留 —— 与 `coarseBlindFootprint`/盲区清单在分享态的既有立场一致
 *  （清单里 gap 同样被隐藏）。CSV 导出与表格共用同一份 grid 对象，故一处生效两处干净。
 *
 *  ⚠️ 为什么必须有这条：地图脱敏做久了容易以为完事，但盲区明细表的 `source` 列一直带着
 *  精确中心经纬度（后端 `diagnosis_templates._sec_blindspot` 与 TS mock 同源），
 *  而 `?share=1` 是公开无鉴权链接 —— 表不脱等于没脱。真浏览器差分实测抓出来的。
 */
export function maskGridForShare<T extends { rows: Record<string, unknown>[] }>(grid: T): T {
  const COORD_PAIR = /-?\d{1,3}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}/g
  const GAP_VALUE = /gap\s*[0-9.]+/gi
  return {
    ...grid,
    rows: grid.rows.map((r) => {
      const out: Record<string, unknown> = { ...r }
      for (const k of Object.keys(out)) {
        if (typeof out[k] !== 'string') continue
        out[k] = (out[k] as string)
          .replace(COORD_PAIR, '概略片区')
          .replace(GAP_VALUE, '')
          .replace(/\s·\s*(?=·|\s*$)/g, '')
          .trim()
      }
      return out
    }),
  }
}

/** 盲区边界显示档位：精确锯齿（raw）↔ 显示圆角（smoothed）。 */
export type BlindBoundaryView = 'smoothed' | 'raw'

/** GeoJSON Polygon 的坐标维度（单环，盲区边界/等时圈共用）。 */
type BlindRingPolygon = { type?: string; coordinates?: LngLat[][] }

/**
 * 取当前档位对应的盲区多边形。raw 档缺 polygon_raw（老数据）时回退 polygon。
 * 返回 GeoJSON Polygon（坐标 LngLat[][]；null 不可用时调用方跳过绘制）。
 */
export function blindPolygonOf(
  b: { polygon?: unknown; polygon_raw?: unknown },
  view: BlindBoundaryView,
): BlindRingPolygon | null {
  const p = view === 'raw' ? b.polygon_raw : b.polygon
  const cand = p ?? b.polygon
  return cand && typeof cand === 'object' ? (cand as BlindRingPolygon) : null
}

/** 该档位是否可切（raw 无数据时仅 smoothed 可用 → 前端置灰 toggle）。 */
export function blindCanRaw(b: { polygon_raw?: unknown }): boolean {
  return !!b?.polygon_raw
}

/** blindTitle 用的本地严重度标签（避免与渲染层塞进同一常量造成双向依赖） */
const BLIND_SEV_LABEL: Record<string, string> = { heavy: '重度', medium: '中度', light: '轻度' }

/** 盲区悬浮信息（C2/C4：严重度/缺口/真实可达/受影响/补点；旧数据字段缺失时安全省略） */
export function blindLabelOf(b: { severity?: string; id?: string }): string {
  const sev = severityOf(b)
  const label = BLIND_SEV_LABEL[sev] ?? ''
  return `${b?.id ?? ''}${label ? `（${label}）` : ''}`
}

/** 连续缺口热力填充（C1：低→黄，中→橙，高→红；缺省灰）。返回 rgba 字符串。 */
export function blindHeatFill(gap: number | null): string {
  if (gap == null) return 'rgba(120,120,120,0.16)'
  const t = Math.min(1, Math.max(0, gap))
  const stops: [number, number, number][] = [
    [231, 196, 92], // 低 → 黄
    [232, 154, 60], // 中 → 橙
    [214, 69, 69], //  高 → 红
  ]
  const seg = t * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(seg))
  const f = seg - i
  const c = [0, 1, 2].map((k) => Math.round(stops[i][k] + (stops[i + 1][k] - stops[i][k]) * f))
  return `rgba(${c[0]},${c[1]},${c[2]},${0.18 + 0.2 * t})`
}

/**
 * rgba 契约色 → BMapGL 可用的「实色 + fillOpacity」。
 *
 * ⚠️ 实测缺陷：BMapGL 的 `Polygon` **忽略 `fillColor` 里的 alpha**，只认 `fillOpacity`
 * （rgba(120,120,120,0.16) 被画成完全不透明的 #787878，实测像素 rgb(121,121,121)）。
 * 而降级 SVG 画布走 CSS，rgba 正常生效 → 两端观感分裂。
 * 故渲染层统一用本函数把 LC_* 色表拆开，色表仍是唯一真源，live 与降级画布一致。
 */
export function lcFillSpec(css: string, fallbackOpacity = 1): { color: string; opacity: number } {
  const m = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)$/i.exec(css.trim())
  if (!m) return { color: css, opacity: fallbackOpacity }
  const hex2 = (n: string) => Number(n).toString(16).padStart(2, '0')
  return {
    color: `#${hex2(m[1])}${hex2(m[2])}${hex2(m[3])}`,
    opacity: m[4] === undefined ? fallbackOpacity : Number(m[4]),
  }
}

/** 中心点 → 米制偏移（等距局部近似，仅用于渲染尺寸，不做地理结算） */
export function lcMeters(center: LngLat, lng: number, lat: number): [number, number] {
  const dLat = lat - center[1]
  const dLng = lng - center[0]
  const mx = dLng * 111320 * Math.cos((center[1] * Math.PI) / 180)
  const my = dLat * 111320
  return [mx, my]
}

export function lcToPx(center: LngLat, lng: number, lat: number): [number, number] {
  const { R, W, H } = LC_CANVAS
  const [mx, my] = lcMeters(center, lng, lat)
  return [W / 2 + (mx / R) * (W / 2), H / 2 - (my / R) * (H / 2)]
}

export interface LcFrame { x: number; y: number; w: number; h: number }

/**
 * 内容包围盒 → 画框（分章静态地图拿它当 `viewBox`）。
 *
 * 为什么需要它：`lcToPx` 的画布恒以 `scene.center` 为原点、恒 860×620（研究半径 5km 的等距近似），
 * 而真实样区的可达场通常只占其中一小块 —— 凯里 live 实测内容包围盒 327×267，只占画布的
 * 38% × 43%。主图有底图瓦片填掉那片空白所以看不出问题，**静态分章图没有底图**，于是读者看到
 * "一小坨图歪在纸边中间"。收框把它放大居中，投影与几何一字不动。
 *
 * 口径：参与包围盒的就是画布上真画出来的那些 —— 等时圈族环、`poiRenderSet` 的代表点
 * （与 `lcSnapshotPoiLayer` 同一份点集，不是第二套取数）、盲区面与中心、场景中心自己。
 * 空载荷/退化（不足两点、全非有限值）退回整幅画布，绝不产 NaN 或零宽高框。
 */
/**
 * 一份载荷在**给定投影原点**下贡献的画布坐标点集。
 *
 * 取景只认这一份点集：`lcContentFrame`（分章静态图）与 `lcCoFrame`（对照态降级画布）共用它，
 * 免得两处各数一遍"哪些点该框进来"（那正是本仓一直在堵的第二实现）。
 * 口径与旧版逐字相同：等时圈族环、盲区面与盲区中心、`poiRenderSet` 的代表点、载荷自己的场景中心。
 */
function lcFramePx(lc: LivingCircleReport, origin: LngLat): Array<[number, number]> {
  const pts: Array<[number, number]> = []
  const push = (lng: number, lat: number): void => {
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) return
    const [x, y] = lcToPx(origin, lng, lat)
    if (Number.isFinite(x) && Number.isFinite(y)) pts.push([x, y])
  }
  const pushRing = (ring: LngLat[] | undefined): void => {
    for (const p of ring ?? []) if (Array.isArray(p) && p.length >= 2) push(p[0], p[1])
  }
  for (const z of lc.isochrones ?? []) pushRing(z.geojson?.coordinates?.[0])
  for (const b of lc.blindspots ?? []) {
    pushRing(b.polygon?.coordinates?.[0])
    if (Array.isArray(b.center) && b.center.length >= 2) push(b.center[0], b.center[1])
  }
  for (const p of poiRenderSet(lc.poi?.points ?? []).reps) {
    if (Array.isArray(p?.lnglat) && p.lnglat.length >= 2) push(p.lnglat[0], p.lnglat[1])
  }
  const own = lc.scene?.center as LngLat | undefined
  if (Array.isArray(own) && own.length >= 2) push(own[0], own[1])
  return pts
}

/** 点集 → 带留白的包围盒；不足两点或退化（零宽高）时退回整幅画布，绝不产 NaN 框。 */
function lcFrameBox(pts: Array<[number, number]>): LcFrame {
  const full: LcFrame = { x: 0, y: 0, w: LC_CANVAS.W, h: LC_CANVAS.H }
  if (pts.length < 2) return full
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const minX = Math.min(...xs); const maxX = Math.max(...xs)
  const minY = Math.min(...ys); const maxY = Math.max(...ys)
  const padX = Math.max((maxX - minX) * 0.08, 24)
  const padY = Math.max((maxY - minY) * 0.08, 24)
  const w = maxX - minX + padX * 2
  const h = maxY - minY + padY * 2
  if (!(w > 0) || !(h > 0)) return full
  return { x: minX - padX, y: minY - padY, w, h }
}

/**
 * 对照态降级画布的取景：把**两侧**真画得出来的内容都框进来，且保持画布宽高比。
 *
 * 为什么需要它（2026-10-10 真跑两发才第一次撞见）：降级画布原本恒用 `0 0 860 620`，
 * 而投影原点＝A 侧 `scene.center`、世界半径＝`LC_CANVAS.R` 2500 m —— 两份件相距 2486 m 时
 * B 侧格阵实测落在 x `722..1024`，**右边缘出框 164 px**（图被切，读者看到"少一侧"）。
 * 之前点不出来，是因为库里可见的四份两两最近 14,014 m ⇒ 全走双图那一支。
 *
 * 三条不变式（判据逐条钉）：
 *  ① 宽高比恒等于画布比例 ⇒ svg 自身高度与那个定高槽都不跟着变（改取景不许顺手改布局）；
 *  ② 结果**必含整幅画布** ⇒ 两侧内容没超出今天取景时（同中心那一对就是），
 *     返回逐字是 `{0,0,860,620}`，对照态今天的画面一格没动；
 *  ③ 只改"看得见多大一片"，投影原点与 `lcToPx` 一字不动 ⇒ 米制比例尺、判定尺圆、
 *     点击反投影全跟着同一个 frame 走（`LcMap` 那侧必须用返回值换算，不许再各算各的）。
 */
export function lcCoFrame(a: LivingCircleReport, b: LivingCircleReport, origin: LngLat): LcFrame {
  const box = lcFrameBox([...lcFramePx(a, origin), ...lcFramePx(b, origin)])
  const full: LcFrame = { x: 0, y: 0, w: LC_CANVAS.W, h: LC_CANVAS.H }
  // 内容还在今天的画布里 ⇒ **逐字**退回整幅（同中心那一对就是这种）。不这么做会留下
  // 1e-14 的浮点残渣（实测 `x: -5.68e-14`）—— 渲染上被 `toFixed(1)` 吃掉，但"没病的画面一格没动"
  // 这条不变式要能被判据**精确**问出来，而不是靠容差。
  if (box.x >= 0 && box.y >= 0 && box.x + box.w <= LC_CANVAS.W && box.y + box.h <= LC_CANVAS.H) return full
  const minX = Math.min(box.x, 0)
  const minY = Math.min(box.y, 0)
  const maxX = Math.max(box.x + box.w, LC_CANVAS.W)
  const maxY = Math.max(box.y + box.h, LC_CANVAS.H)
  const ar = LC_CANVAS.W / LC_CANVAS.H
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  let w = maxX - minX
  let h = maxY - minY
  if (w / h > ar) h = w / ar
  else w = h * ar
  return { x: cx - w / 2, y: cy - h / 2, w, h }
}

export function lcContentFrame(lc: LivingCircleReport): LcFrame {
  const center = lc.scene?.center as LngLat | undefined
  const full: LcFrame = { x: 0, y: 0, w: LC_CANVAS.W, h: LC_CANVAS.H }
  if (!Array.isArray(center) || center.length < 2) return full
  return lcFrameBox(lcFramePx(lc, center))
}

/** 画框 → `viewBox` 字符串（一位小数足够：画布本身是 860×620 的整数域）。 */
export function lcFrameViewBox(f: LcFrame): string {
  return `${f.x.toFixed(1)} ${f.y.toFixed(1)} ${f.w.toFixed(1)} ${f.h.toFixed(1)}`
}

/**
 * 画框 → CSS `aspect-ratio`。与 `lcFrameViewBox` 同用一位小数：槽的比例与 viewBox 的比例
 * 一旦一个取整一个不取，`meet` 就会按那点差再留一道缝（判据把两处钉成同一份数）。
 */
export function lcFrameAspectRatio(f: LcFrame): string {
  return `${f.w.toFixed(1)} / ${f.h.toFixed(1)}`
}

/**
 * 米偏移 → 经纬度：`lcMeters` 的**逆**，全仓唯一实现。
 *
 * 分母是 `111320`（米/度），**不是** `111320 × π/180` —— 后者把度当成弧度处理，
 * 环会放大 180/π ≈ 57.3 倍（第十六轮评审 P0-1：34 个证据盘整层落到画布外，
 * 描边档一个像素都看不见、填充档把画布染成一片灰）。
 * 纬度方向的 `cos` 取**原点**纬度：本函数的契约是「以 `origin` 为局部原点的米偏移」，
 * 与 `lcMeters` 同侧，正反两变换在同一处成立。
 */
export function lcFromMeters(origin: LngLat, mx: number, my: number): LngLat {
  const cos = Math.cos((origin[1] * Math.PI) / 180)
  return [origin[0] + mx / (111320 * cos), origin[1] + my / 111320]
}

/**
 * 以某点为圆心、`radiusM` 为半径的**投影后**环（走 `lcFromMeters`，即 `lcMeters` 的逆）。
 *
 * 为什么不能直接画 SVG `<circle r=米×比例>`：`lcToPx` 的横纵比例本就不同
 * （W/2÷R ≠ H/2÷R，画布是把 5km×5km 方形拉进 860×620 的矩形），一个正圆会把纵向
 * 多出 ~39% —— 那与等时圈多边形不是同一把尺。走这条逆投影生成环，再交 `lcPolyPts`，
 * 证据盘与等时圈在同一个各向异性里对齐。
 */
export function lcRing(point: LngLat, radiusM: number, steps = 48): LngLat[] {
  const out: LngLat[] = []
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2
    out.push(lcFromMeters(point, radiusM * Math.cos(a), radiusM * Math.sin(a)))
  }
  return out
}

/** 两场景中心点间的近似直线距离（米）。仅用于「是否可同框真实叠加」的判定，不做地理结算。 */
export function lcSceneDistanceM(a: LngLat, b: LngLat): number {
  const [mx, my] = lcMeters(a, b[0], b[1])
  return Math.hypot(mx, my)
}

/** 同城同片生活圈上限：两中心 ≤ 阈值才允许「同图真实叠加」。
 *  15 分钟步行圈半径约 1–3km，≤4km 时两圈可能同框且叠加语义成立。 */
export const LC_CO_LOCATED_M = 4000

/** 是否属于「同一片生活圈」（可在同一张绝对地图上真实叠加）。 */
export function lcCoLocated(a: LngLat, b: LngLat, thresholdM: number = LC_CO_LOCATED_M): boolean {
  return lcSceneDistanceM(a, b) <= thresholdM
}

/** 双样例对比的呈现策略。选择对象与「怎么展示」由同一决策驱动，跨城不再喂进真实叠加。 */
export interface SharedOverlayPlan {
  /** 是否可在同一张绝对地理图上真实叠加（同片生活圈）。 */
  shareMap: boolean
  /** 跨城/跨区时是否提供「归一化圈形对比示意」。 */
  normalize: boolean
  reason: 'co-located' | 'cross-location'
}

export function planComparisonOverlay(ca: LngLat, cb: LngLat): SharedOverlayPlan {
  if (lcCoLocated(ca, cb)) {
    return { shareMap: true, normalize: false, reason: 'co-located' }
  }
  return { shareMap: false, normalize: true, reason: 'cross-location' }
}

/** 环 → SVG polygon points */
export function lcPolyPts(center: LngLat, ring: LngLat[]): string {
  return ring.map(([lng, lat]) => lcToPx(center, lng, lat).map((v) => v.toFixed(1)).join(',')).join(' ')
}

export interface LcSnapshotPoiDot {
  /** React key：id + 像素坐标，保证同 id 不同坐标（或同名点）也不撞 key */
  key: string
  cx: number
  cy: number
  fill: string
  /**
   * 类目 id（与 `fill` 同源取色）。分章地图的灰化判据要问"这一点属不属于本章焦点类目" ——
   * 拿 `fill` 反查类目是把颜色当身份：未知类目今天正好兜底成政务那枚色，反查会认错。
   */
  category: string
  title?: string
  /** 该点代表了多少个原始点（网格聚合结果；未聚合恒为 1）。供 hover 文案披露 */
  cluster: number
}

/**
 * 共享 POI 投影层 —— 报告快照与 LcMap 降级画布点位的唯一口径。
 *
 * 职责：把真实 `poi.points` 投影为「圆点元数据」数组。IsochroneSnapshot（报告页）
 * 与 LcMap 降级画布都从它取点，保证两处点位永不漂移、也便于单测（本项目 TC-01..07）。
 *
 * 守卫：`points` 为空/undefined → []；非法坐标（缺失/NaN/Inf 或 lnglat 长度≠2）被过滤，
 * 绝不让坏点外溢画布。未知类别兜底色 `#7c6670`。
 *
 * ⚠️ **阶段 2.3：默认不再截断**（原 `cap = 120`）。那个默认值是渲染层的**第二权威**：
 * 报告声明「圈内 98 处」、`poi.points` 也确有 98 个，却只因渲染侧一句默认参数就悄悄只画
 * 前 120/60 个 —— 与装配层的静默截断是同一类缺陷，只是换了个位置复发。
 *
 * `cap` **保留为显式参数**（默认 `Infinity`）：需要 DOM 预算上限时由调用方**显式**声明，
 * 不允许再出现「谁都没写、但就是砍了」的默认行为。真正的限流职责在 `poiRenderSet()`。
 */
export function lcSnapshotPoiLayer(
  center: LngLat,
  points: PoiPoint[],
  cap = Number.POSITIVE_INFINITY,
  /** 网格聚合计数（来自 `poiRenderSet().counts`）：给出时每个圆点带上自己的簇计数 */
  counts?: Map<string, number>,
): LcSnapshotPoiDot[] {
  return (points ?? [])
    .slice(0, cap)
    .map((p): LcSnapshotPoiDot | null => {
      const ll = p.lnglat
      if (!Array.isArray(ll) || ll.length < 2 || !Number.isFinite(ll[0]) || !Number.isFinite(ll[1])) {
        return null
      }
      const [cx, cy] = lcToPx(center, ll[0], ll[1])
      return {
        key: `${p.id}-${cx.toFixed(1)}-${cy.toFixed(1)}`,
        cx,
        cy,
        fill: LC_CAT_COLOR[p.category] ?? '#7c6670',
        category: p.category ?? '',
        title: p.name,
        cluster: counts?.get(p.id) ?? 1,
      }
    })
    .filter((d): d is LcSnapshotPoiDot => d !== null)
}

/* ── 阶段 2 · POI 渲染点集（唯一入口）──────────────────────────────────────
 * 三处渲染入口（LcMap live BMapGL Marker / LcMap 降级 SVG / 报告页内嵌快照）
 * **必须取用同一份点集**，否则「图上点位与图例不一致」会在渲染层复发。
 * 故这里提供唯一入口 `poiRenderSet()`，三处一律经它取数（阶段 3 有 golden 测试钉住）。
 * ------------------------------------------------------------------------ */

/**
 * 触发「地理网格聚合」的点数阈值。
 *
 * 为什么需要它：阶段 2.3 删掉了渲染层的 120/60 静态上限（那是静默的第二权威），
 * 但**不能连 DOM 预算一起删掉** —— BMapGL 的 Marker 是一个 `<div>`/点，
 * 装配层 `POI_CAP_PER_CAT=200` × 8 类的理论最坏值 1600 个 DOM 节点会把页面拖垮。
 * 于是把「静态按数量砍」换成「超阈值时按**地理网格**聚合」：不再凭空丢点，
 * 而是把过密的点收成一个带簇计数的代表点（放大/缩放后仍是同一份数据）。
 *
 * 取值 400：当前最大报告 217 点（kaili 217 / jinsong 175），**永不触发** ⇒
 * 现行数据下「图上标记数 == 面板已展示 == 圈内数」严格成立（阶段 3 的护栏在此区间断言相等）。
 */
export const POI_THIN_THRESHOLD = 400

/**
 * 聚合网格边长（米）。30m ≈ 两个 Marker 直径量级：网格内的点在常规缩放级别下本就互相压盖，
 * 收成一个代表点不损失可读信息 —— 这与「静默砍掉 6 个购物点」有本质区别。
 */
export const POI_THIN_CELL_M = 30

export interface PoiRenderSet {
  /** **图上实际要画的点**（未聚合时 === `poi.points`，保持原序） */
  reps: PoiPoint[]
  /** 代表点 id → 该网格聚合了多少个原始点（未聚合时每项为 1） */
  counts: Map<string, number>
  /** 图上标记数 = `reps.length` */
  shown: number
  /** 下发给渲染层的点数 = `poi.points.length`（= 面板「已展示」数） */
  handed: number
  /** 是否发生了网格聚合（`shown < handed`）。true 时**必须**在图面披露 */
  thinned: boolean
}

/** 代表点权重：圈内优先 → 耗时更短优先 → id 兜底（保证**确定性**，同一输入永远同一代表点）。 */
function _poiRepWeight(p: PoiPoint): [number, number, string] {
  return [p.in_circle ? 0 : 1, p.minutes ?? Number.POSITIVE_INFINITY, p.id]
}

function _cmpRepWeight(a: PoiPoint, b: PoiPoint): number {
  const [ac, am, ai] = _poiRepWeight(a)
  const [bc, bm, bi] = _poiRepWeight(b)
  if (ac !== bc) return ac - bc
  if (am !== bm) return am - bm
  return ai < bi ? -1 : ai > bi ? 1 : 0
}

/**
 * POI 渲染点集 —— **三处渲染入口的唯一取数口**。
 *
 * 行为：
 *  - `points.length <= POI_THIN_THRESHOLD` → 原样返回（`thinned=false`，`counts` 全 1）；
 *  - 超阈值 → 按 `POI_THIN_CELL_M` 的**地理网格**（用中心点做米制投影，与 `lcToPx` 同族）
 *    分桶，每桶保留权重最高的 1 个代表点，桶内其余点计入该代表点的簇计数。
 *
 * ⚠️ **为什么是地理网格而不是屏幕像素网格**：像素网格依赖 `map.getBounds()`，
 * live（BMapGL）与两处 SVG 画布尺寸不同 ⇒ 同一份报告在三个入口会被聚合成**不同的点集**，
 * 「三处渲染点集逐点一致」这条验收当场失效。地理网格与画布无关，三处得到**同一份 `reps`**。
 * 这也意味着它**不随缩放变化**（避免面板数字随拖拽跳变）。
 *
 * 不变量：`Σ counts.values() === handed`（聚合不丢点，只是收拢显示）。
 */
export function poiRenderSet(points: PoiPoint[] | undefined | null): PoiRenderSet {
  const all = points ?? []
  const handed = all.length
  if (handed <= POI_THIN_THRESHOLD) {
    return {
      reps: all,
      counts: new Map(all.map((p) => [p.id, 1] as const)),
      shown: handed,
      handed,
      thinned: false,
    }
  }
  // 分桶键 = 米制投影 / 网格边长（向下取整）。中心点取首个合法点，仅作局部近似基准。
  const base: LngLat = (all[0]?.lnglat ?? [0, 0]) as LngLat
  const buckets = new Map<string, PoiPoint[]>()
  for (const p of all) {
    const ll = p.lnglat
    if (!Array.isArray(ll) || ll.length < 2) continue
    const [mx, my] = lcMeters(base, ll[0], ll[1])
    const key = `${Math.floor(mx / POI_THIN_CELL_M)}:${Math.floor(my / POI_THIN_CELL_M)}`
    const arr = buckets.get(key)
    if (arr) arr.push(p)
    else buckets.set(key, [p])
  }
  const reps: PoiPoint[] = []
  const counts = new Map<string, number>()
  for (const arr of buckets.values()) {
    let best = arr[0]
    for (const p of arr) if (_cmpRepWeight(p, best) < 0) best = p
    reps.push(best)
    counts.set(best.id, arr.length)
  }
  // 保持与原序一致，让「同一份报告」在三个入口的绘制顺序也相同
  const order = new Map(all.map((p, i) => [p.id, i] as const))
  reps.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
  return { reps, counts, shown: reps.length, handed, thinned: reps.length < handed }
}

/** 图上标记数 ≠ 下发点数时的一句话披露（未聚合返回 null）。 */
export function poiThinNote(set: PoiRenderSet): string | null {
  if (!set.thinned) return null
  return `点位过密：${set.handed} 处已按 ${POI_THIN_CELL_M}m 网格聚合为 ${set.shown} 个标记（放大后展开同一份数据，未丢点）`
}

/** 环上最靠右的顶点（放 "N min" 标注，避开中心文字） */
export function lcRightmost(center: LngLat, ring: LngLat[]): [number, number] {
  let best = ring[0]
  let bestX = -Infinity
  for (const p of ring) {
    const x = lcToPx(center, p[0], p[1])[0]
    if (x > bestX) {
      bestX = x
      best = p
    }
  }
  return lcToPx(center, best[0], best[1])
}

/** 评分档位文案（体检单 / 历史页共用口径） */
export function scoreGrade(total: number): { label: string; color: string } {
  if (total >= 85) return { label: '优', color: '#2F8F6B' }
  if (total >= 70) return { label: '良', color: '#5f8a6a' }
  if (total >= 55) return { label: '中', color: '#C09A2E' }
  return { label: '差', color: '#C2642E' }
}

export const LC_CAT_LABEL_OF = (key: string, fallback?: string) => LC_CAT_LABEL[key] ?? fallback ?? key

/** 可达判定阈值的兜底值（分钟）。真值来自 `caliber.reach_full_min`，这里只兜老快照。 */
export const LC_REACH_FULL_MIN_FALLBACK = 20

/** 采样点分档判定的最小可判结构（新字段可缺、旧字段 `reachable` 忽略）。 */
export interface SamplingPointLike {
  minutes: number | null
  timed?: boolean
  in_reach?: boolean
}

/**
 * 「已测时」判定 —— **全前端唯一实现**。
 *
 * 新口径读 `timed`；**历史快照**（阶段 −1 之前落库的报告）的点只有旧名 `reachable`、
 * 没有 `timed`，其真实语义就是「minutes 非空」，故字段缺失时按 `minutes != null` 回退。
 *
 * 为什么不能直接 `p.timed`：库里 25 份历史报告的 1049/1049 个点都只有 `reachable`，
 * 直接读 `p.timed` 会得 `undefined` ⇒ 三处热力层被静默清空（看着像「本次没采样」，
 * 实为字段迁移漏掉了读侧回退）——与本轮修掉的「静默 0」是同一类缺陷。
 */
export function isTimedPoint(p: SamplingPointLike): boolean {
  return p.timed ?? p.minutes != null
}

/**
 * 「圈内可达」判定 —— 唯一实现。已测时且 `minutes <= reachFullMin`。
 *
 * 阈值比较**带一位小数舍入**（`round(m,1)`），与后端 `isochrone._flag_of()` 逐字对齐：
 * 采样耗时本身是浮点，20.0000001 这类噪声若不舍入，会在阈值边界上与后端分档不一致。
 */
export function isInReachPoint(
  p: SamplingPointLike,
  reachFullMin: number = LC_REACH_FULL_MIN_FALLBACK,
): boolean {
  if (p.in_reach != null) return p.in_reach
  return isTimedPoint(p) && p.minutes != null && Math.round(p.minutes * 10) / 10 <= reachFullMin
}

/**
 * 热力采样点集合 —— **渲染层唯一入口**（LcMap 的 BMapGL 覆盖层与降级画布共用）。
 *
 * 取「已测时且 minutes 非空」的点（**不是**「仅可达」的点：热力表达的是耗时分布，
 * 若只画可达点，正片高耗时区会凭空消失）。`cap` 只用于降级画布的 DOM 预算。
 */
export function heatSamplePoints(
  lc: Pick<LivingCircleReport, 'sampling'>,
  cap = Number.POSITIVE_INFINITY,
): { idx: number; lng: number; lat: number; minutes: number }[] {
  const out: { idx: number; lng: number; lat: number; minutes: number }[] = []
  for (const p of lc.sampling?.points ?? []) {
    if (!isTimedPoint(p) || p.minutes == null) continue
    out.push({ idx: p.idx, lng: p.lng, lat: p.lat, minutes: p.minutes })
    if (out.length >= cap) break
  }
  return out
}

export interface SamplingReach {
  /** 已测时点数（**不是**可达数） */
  timed: number
  /** 圈内可达点数（`minutes <= reach_full_min`）——「可达率」的分子 */
  inReach: number
  /** 采样点总数（可达率的分母） */
  total: number
  /** 判定所用阈值（分钟），供文案显式化「≤N 分钟内可达」 */
  reachFullMin: number
}

/**
 * 采样点可达分档 —— **全前端唯一取值口径**。
 *
 * 为什么必须是唯一入口：后端 `sampling.timed_count` / `in_reach_count` 是随点集一起下发的
 * 汇总数，若每个消费方各自 `.filter(p => p.in_reach).length`，就又变成「同一语义 N 处实现」；
 * 更早的版本读的是 `p.reachable`（语义其实是「测时返回了值」），UI 于是把 1049 个点
 * 全说成「可达」，而真正 ≤reach_full_min 的只有 126 个。
 *
 * 汇总数缺失（历史快照）时按点回算，**回算走同一判据**（`isTimedPoint` / `isInReachPoint`）。
 */
export function samplingReach(
  lc: Pick<LivingCircleReport, 'sampling' | 'caliber'>,
): SamplingReach {
  const pts = lc.sampling?.points ?? []
  const reachFullMin = lc.caliber?.reach_full_min ?? LC_REACH_FULL_MIN_FALLBACK
  const timedCount = lc.sampling?.timed_count
  const inReachCount = lc.sampling?.in_reach_count
  if (typeof timedCount === 'number' && typeof inReachCount === 'number') {
    return { timed: timedCount, inReach: inReachCount, total: pts.length, reachFullMin }
  }
  let timed = 0
  let inReach = 0
  for (const p of pts) {
    if (!isTimedPoint(p)) continue
    timed += 1
    if (isInReachPoint(p, reachFullMin)) inReach += 1
  }
  return { timed, inReach, total: pts.length, reachFullMin }
}

/** 「采样 N 个（≤M 分钟内可达 K）」——三处渲染入口共用，避免文案各写一套。 */
export function samplingReachLabel(lc: Pick<LivingCircleReport, 'sampling' | 'caliber'>): string {
  const r = samplingReach(lc)
  return `采样 ${r.total} 个（≤${r.reachFullMin} 分钟内可达 ${r.inReach}）`
}

export interface PoiConservation {
  /** 报告声明的圈内设施数（面板上那个「圈内 N」） */
  declared: number
  /** 图上实际送达的点位数（`poi.points.length`） */
  actual: number
  /** `actual - declared`：正=图上比面板多（旧版把圈外点也送了），负=被截断 */
  delta: number
  ok: boolean
  /** 后端自检结论是否存在：`report` = 有（新报告）；`derived` = 无（历史报告） */
  source: 'report' | 'derived'
}

/**
 * POI 点数守恒判据 —— **全前端唯一实现**。
 *
 * 不变量：`sum(categories[].in_circle) === poi.points.length`。
 * 「面板写圈内 N 处」与「图上画 M 个点」必须能对上，否则读者无法把图追到数字
 * ——这正是用户最初报的「点位与图例对不上」的实质。
 *
 * ⚠️ **判据永远是重算的，不盲信 `poi.conservation.ok`**：校验器若直接采信被校验对象的
 * 自我声明，就等于没有校验器（负对照实测：只改 `categories` 不改 `conservation`，
 * 盲信版照样返回 ok=true）。故 `ok = 数据自洽 && 报告未声称违规`，两者取严。
 *
 * 三种形态：
 *  1. **新报告**带 `poi.conservation`（后端装配时自检的结论）→ 仍重算，并与其取严，`source='report'`；
 *  2. **历史报告**（阶段 1 之前落库，无该字段）→ 按 `categories` 求和与点集**回算**，
 *     实测库里 25 份有 15 份不守恒，且**两个方向都有**
 *     （`104 vs 98` 截断方向 / `18 vs 151` 旧版圈外点全送方向）⇒ **不可统一反算修正**，
 *     只能如实披露，让读者知道这份报告的图与数对不上；
 *  3. `categories` 为空（离线报告）→ 视为 `0 === points.length`，不误报。
 *
 * ⚠️ 与 `samplingReach` 一样：**不要在别处自行 `reduce` 或读 `poi.in_circle` 下结论**，
 * 一律走本函数，否则又会分叉成 N 份口径。
 */
export function poiConservation(lc: Pick<LivingCircleReport, 'poi'>): PoiConservation {
  const poi = lc.poi
  const declared = (poi?.categories ?? []).reduce((s, c) => s + (c.in_circle ?? 0), 0)
  const actual = (poi?.points ?? []).length
  const selfCheck = poi?.conservation
  return {
    declared,
    actual,
    delta: actual - declared,
    ok: declared === actual && selfCheck?.ok !== false,
    source: selfCheck ? 'report' : 'derived',
  }
}

/** 一句话披露不守恒；守恒时返回 null（与 `blindspotCoverageNote` 同风格）。 */
export function poiConservationNote(lc: Pick<LivingCircleReport, 'poi'>): string | null {
  const c = poiConservation(lc)
  if (c.ok) return null
  if (c.delta < 0) {
    return `图上仅 ${c.actual} 个点，报告圈内计数为 ${c.declared} 处（少 ${-c.delta} 处，旧版按每类上限截断所致）`
  }
  return `图上 ${c.actual} 个点，而报告圈内计数仅 ${c.declared} 处（多 ${c.delta} 个，本报告生成于旧版口径）`
}

/**
 * POI 指标文案 —— **全前端唯一实现**（阶段 2.5 · 决策 D2）。
 *
 * 三段式：`采集 N · 圈内 M · 已展示 K`
 *  - **N = `poi.total`**：**采集口径**（研究范围内检索到的总数，**含圈外**）—— 保留它，
 *    因为删掉会让人以为「只用 98 次检索就采到了图例里全部设施」，把额度账讲错。
 *  - **M = `sum(categories[].in_circle)`**：**可达口径**（15min 圈内），走 `poiConservation()`
 *    统一取值，不在文案里自己 `.reduce`。
 *  - **K = `poi.points.length`**：**下发给渲染层的点数**，即地图上画得出来的点。
 *    未触发聚合时 `K === M`（守恒不变量）；触发时（≥ `POI_THIN_THRESHOLD`）见 `poiThinNote`。
 *
 * 第四段**仅当装配层真的截断过**（`poi.truncated.dropped > 0`）才出现 ——
 * 这正是「静默截断」被消灭的可见证据：出现过一次截断，报告里就永久留痕。
 *
 * ⚠️ 与后端 `diagnosis_templates.py::_poi_metric_label` **逐字同口径**（Py/TS 各一份实现，
 * 靠契约测试对齐）。mock 副本也必须调本函数，不得手写字符串。
 */
export function poiMetricLabel(lc: Pick<LivingCircleReport, 'poi'>): string {
  const c = poiConservation(lc)
  const total = lc.poi?.total ?? 0
  const base = `采集 ${total} · 圈内 ${c.declared} · 已展示 ${c.actual}`
  const tr = lc.poi?.truncated
  const dropped = tr?.dropped ?? 0
  if (dropped <= 0) return base
  const detail = (tr?.categories ?? [])
    .filter((x) => (x.dropped ?? 0) > 0)
    .map((x) => `${x.category} ${x.dropped}`)
    .join('/')
  const cap = tr?.cap_per_cat
  return `${base} · 另有 ${dropped} 处未展示（${detail}${cap != null ? `，每类上限 ${cap}` : ''}）`
}

/**
 * POI 清洗规则文案 —— 与后端 `diagnosis_templates.poi_dedupe_rule_label` **逐字同口径**。
 *
 * 报告叙述里「做了什么清洗」必须**从报告自己的披露推出来**，不能手写。旧写法把
 * 「名称归一与 50m 聚簇去重」钉死在模板里，于是设施归并上线后报告仍在描述修复前的
 * 算法 —— 那是报告文本层造假，比数字错更难被发现（词表闸抓虚构指标，抓不到过期描述）。
 *
 * `poi.merged` 缺失 = 归并上线前冻结的快照 ⇒ 退回旧描述，而不是谎报新规则生效过。
 */
export function poiDedupeRuleLabel(lc: Pick<LivingCircleReport, 'poi'>): string {
  const base = '名称归一与 50m 聚簇去重'
  const mg = lc.poi?.merged
  if (!mg || !mg.enabled) return base
  const n = mg.absorbed ?? 0
  if (n <= 0) return `${base} + 设施实体归并（${mg.rule_version}，本次无同体子点）`
  const detail = (mg.categories ?? [])
    .filter((x) => (x.absorbed ?? 0) > 0)
    .map((x) => `${x.category} ${x.absorbed}`)
    .join('/')
  return `${base} + 设施实体归并（${mg.rule_version}，吸收 ${n} 处同体子点：${detail}）`
}

/* ── 对比页差异表 / 卡片指标行（阶段 5 · R6）───────────────────────────── */

/** 比较方向：`higher` = 数值越大越好；`lower` = 越小越好。 */
export type CompareBetter = 'higher' | 'lower'

/** 相等时的用词 —— 6 行**同一个词**（阶段 5 · 决策 6.1：不再「相当 / 持平」混用）。 */
export const COMPARE_EQUAL_WORD = '持平'

export interface CompareRowDef {
  /** 行名 —— 差异表表头与卡片键名**共用这一个**。只作标识与显示，**不参与分派**。 */
  key: string
  /**
   * 越大越好 / 越小越好。
   * ⚠️ **服务盲区是 `lower`** —— 写成 `higher` 会输出「盲区更少」挂在盲区**更多**那一侧，
   * 即事实相反（旧 `deriveDesc()` 的硬错形态）。契约夹具里 `服务盲区 a=0 b=1` 那条用例就是它的负对照。
   */
  better: CompareBetter
  /**
   * **比较用纯数值** —— 差异表的可比性全靠它。
   *
   * ⚠️ **必须走既有唯一出口，不得自算**（项目自证禁忌：`types.ts:551`「消费方请走
   * `poiConservation()`，不要自己求和下结论」· `types.ts:742`「缺失时请用 `samplingReach()`
   * 回算，不要自行 filter」）。历史事故：旧的 `deriveDesc()` 把 `statList()` 的**显示串**
   * 交给 `>`，JS 对字符串走逐字符字典序 ⇒ `'0 处' > '1 处'` 为 false ⇒ 盲区行结论事实相反。
   * 展示与比较必须在**值形态**上就分开，不能只在调用处小心。
   */
  num(r: LivingCircleReport): number
  /**
   * **展示形态**（卡片用：保留单位与上下文）。差异表不用它 —— 表里一律纯数值，单位写进行名。
   * 与 `num()` 分开，正是上一条纪律的落地形态。
   */
  cell(r: LivingCircleReport): string
  /** 解读句式模板：`{胜者}{template}`；相等时用 `COMPARE_EQUAL_WORD`。 */
  template: string
}

/**
 * 「{胜者}{template}」/「持平」—— **全前端唯一实现**。
 *
 * 为什么把方向与句式做成**数据 + 一个函数**、而不是每行各写一个 `desc()`：
 * 六个行各写一份会把「相等用词」和「谁是胜者」的判据复制六遍，改一处漏五处。
 *
 * ⚠️ 与后端 `main.py:_lc_diff` **逐字同源**（Py/TS 各一份实现，靠契约夹具
 * `frontend/src/__tests__/fixtures/compareDiffContract.json` 的 `desc_cases` 两侧各自断言对齐）。
 * 称呼（`nameA`/`nameB`）是**参数**：真实态传 `"A"`/`"B"`，演示态传场景实名 ——
 * 对齐的是**句式骨架**，称呼本身保留各自形态（真实态用代号是刻意的：城市名太长，表格放不下）。
 */
export function compareDesc(
  def: CompareRowDef,
  na: number,
  nb: number,
  nameA: string,
  nameB: string,
): string {
  if (na === nb) return COMPARE_EQUAL_WORD
  const aWins = def.better === 'higher' ? na > nb : na < nb
  return `${aWins ? nameA : nameB}${def.template}`
}

/**
 * 15min 等时圈面积 —— **展示值与比较值是同一个数**（两位小数）。
 *
 * ⚠️ 不要在这里返回原始 `area_km2`：后端 `_lc_diff()` 展示的是 `round(x, 2)`，
 * 若前端比的是原始值，同一份报告在两模式下会显示不同数字（`1.562` vs `1.56`）。
 * 更要紧的是：若**比较用原始值、展示用两位小数**，`1.561` 与 `1.564` 会显示成两个 `1.56`
 * 却判出「B可达范围更大」—— 读者无法用看到的数复核结论。判据必须挂在**展示的那个数**上。
 */
function _isoArea15(r: LivingCircleReport): number {
  const raw = r.isochrones.find((z) => z.minutes === 15)?.area_km2 ?? 0
  return Number(raw.toFixed(2))
}

/**
 * 对比页行定义表 —— **单一真源**（阶段 5 · R6）。
 *
 * 行名与行序与后端 `_lc_diff()` **逐项相同**（契约夹具 `compareDiffContract.json` 的
 * `rows` 一份清单，两侧测试各自深比较）。
 *
 * 消灭的三个老毛病：
 *  ① 旧 `statList()`（卡片）+ 旧 `ROWS`（差异表）= **两份平行行数据**，卡片与差异表同屏却
 *    各行其名 ⇒ 本次收成**一份**，加一行只改这里一处；
 *  ② 旧 `deriveDesc()` 按**行名字符串**分派（`if (row === '服务盲区')`）—— 改文案即改行为，
 *    行名一旦与分派键漂移就静默失灵；本次方向改由 `better` 字段承载；
 *  ③ 旧 `ROWS` 扩到 6 行而取值仍取 `statList()` 会得到 `undefined`，
 *    `undefined > undefined` = false ⇒ **静默给出结论**（不报错）。
 */
export const COMPARE_ROWS: CompareRowDef[] = [
  {
    key: '15min 等时圈面积 (km²)',
    better: 'higher',
    num: _isoArea15,
    cell: (r) => `${_isoArea15(r).toFixed(2)} km²`,
    template: '可达范围更大',
  },
  {
    key: '可达采样点数',
    better: 'higher',
    // 走唯一出口：汇总数缺失（历史快照）时由 samplingReach 内部按点回算，且回算走同一判据。
    num: (r) => samplingReach(r).inReach,
    cell: (r) => {
      const s = samplingReach(r)
      return `${s.inReach} 个（共采样 ${s.total}）`
    },
    template: '可达采样点更多',
  },
  {
    key: 'POI 采集',
    better: 'higher',
    // 本条直读 `poi.total` 是**合法**的：它是采集口径（含圈外）的**唯一字段**，不存在第二条读法。
    // 与之相对，「圈内 POI」有顶层 `poi.in_circle` 与 `Σ categories[].in_circle` 两个来源，
    // 所以那一行**必须**走 poiConservation()（见下一行）。
    num: (r) => r.poi?.total ?? 0,
    cell: (r) => `${r.poi?.total ?? 0} 处`,
    template: '采集面更广',
  },
  {
    key: '圈内 POI',
    better: 'higher',
    // 走唯一出口：poiConservation() 永远**重算** Σ segments 并与报告自证结论**取严**，
    // 不盲信 `poi.conservation.ok`（盲信版本已实测会被「只改数据不改自检字段」骗过）。
    num: (r) => poiConservation(r).declared,
    cell: (r) => `${poiConservation(r).declared} 处`,
    template: '可达设施更密',
  },
  {
    key: '服务盲区',
    better: 'lower', // ← 越小越好。详见 CompareRowDef.better 的注释。
    num: (r) => r.blindspots.length,
    cell: (r) => `${r.blindspots.length} 处`,
    template: '盲区更少',
  },
  {
    key: '综合评分',
    better: 'higher',
    num: (r) => r.scores.total,
    cell: (r) => `${r.scores.total}`,
    template: '更成熟',
  },
]

/** 差异表的一行（与后端 `_lc_diff()` 返回结构、`LifeCircleCompare['diff']` 同形）。 */
export interface CompareDiffRow {
  metric: string
  a_value: number | string
  b_value: number | string
  desc: string
}

/**
 * 演示态差异表 —— 把「行定义 + 口径版本守卫」收成**一处**，页面不再自己拼。
 *
 * 为什么要抽出来：`ComparePage` 里原先是 `COMPARE_ROWS.map(...compareDesc)` 一句直出，
 * 于是「判盲口径不同 ⇒ 那两行不可比」这条守卫只能写在页面里 —— 而它必须与后端
 * `_lc_diff()` 同判据，写在组件里既测不到也守不住（真实态走后端、演示态走页面，
 * 两条链各写一遍正是本仓反复出事的形态）。
 */
export function compareRows(
  lcA: LivingCircleReport,
  lcB: LivingCircleReport,
  nameA: string,
  nameB: string,
): CompareDiffRow[] {
  return COMPARE_ROWS.map((def) => {
    const na = def.num(lcA)
    const nb = def.num(lcB)
    return {
      metric: def.key,
      a_value: na,
      b_value: nb,
      // 行级按轴分派（#83）：横幅那一句是「两轴合起来」（`caliberGapDesc`），不能直接下发给
      // 每一行 —— 那样评分轴的差异会去拦一个它影响不到的行。每行只吃 `GAP_AXES` 写着的那几根轴。
      desc: rowGapDesc(def.key, lcA, lcB) ?? compareDesc(def, na, nb, nameA, nameB),
    }
  })
}

export interface BlindspotCoverage {
  /** 可达区内的网格格数 */
  inside: number
  /** 其中真正判定过的格数（1km 判定邻域被采集区完整覆盖） */
  judged: number
  /** 其中判定不了的格数（数据不足：既不算有盲区，也不算没盲区） */
  unknown: number
  /** 判定覆盖率（0-100 整数） */
  judgedPct: number
}

/**
 * 盲区判定覆盖度 —— 报告页与体检台**共用的一处口径**。
 *
 * 这三个数把「判不了」与「没问题」分开：扫了 `inside` 格，只有 `judged` 格的 1km 邻域
 * 被采集区完整覆盖，其余 `unknown` 格既不算有盲区也不算没盲区。没有它，
 * 「服务盲区 0 处」是无法解读的（可能是全扫完真没有，也可能是 87.5% 没判）。
 */
export function blindspotCoverage(lc: Pick<LivingCircleReport, 'caliber'>): BlindspotCoverage | null {
  const c = lc.caliber
  if (!c || c.cells_inside == null || c.cells_judged == null) return null
  const inside = c.cells_inside
  const judged = c.cells_judged
  const unknown = c.cells_unknown ?? inside - judged
  return {
    inside,
    judged,
    unknown,
    judgedPct: inside > 0 ? Math.round((judged / inside) * 100) : 0,
  }
}

/** 覆盖度一句话披露；存在未判定格时返回非空字符串（否则 null）。 */
export function blindspotCoverageNote(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const cov = blindspotCoverage(lc)
  if (!cov || cov.unknown <= 0) return null
  const collect = lc.caliber?.collect_radius_m ?? '—'
  return (
    `判定覆盖：网格 ${cov.inside} 格中已判定 ${cov.judged} 格（${cov.judgedPct}%），` +
    `其余 ${cov.unknown} 格因采集半径（${collect}m）不足以覆盖 1km 判定邻域而未判定 —— ` +
    `盲区数不含这些区域，存在少报可能。`
  )
}

/** 体检台的紧凑版披露（一行，放 StatRow 旁）。 */
export function blindspotCoverageBrief(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const cov = blindspotCoverage(lc)
  if (!cov) return null
  if (cov.unknown <= 0) return `可达区 ${cov.inside} 格已全部判定`
  return `可达区 ${cov.inside} 格中仅判 ${cov.judged} 格，${cov.unknown} 格数据不足未判`
}

/** 0 处盲区时的结论句：有未判定格就不能说「三要素齐备」。 */
export function emptyBlindspotNote(lc: Pick<LivingCircleReport, 'caliber'>): string {
  const cov = blindspotCoverage(lc)
  if (!cov) return '按赛题口径（1km 内无菜市场/药店/小学）扫描，本次未发现服务盲区。'
  if (cov.unknown > 0) {
    return `已在可判定范围内（${cov.judged} 格）确认三要素齐备，未发现 1km 服务盲区；但仍有 ${cov.unknown} 格无法判定，不能据此判定全圈无障碍。`
  }
  return `网格扫描 ${cov.inside} 格全部完成判定，菜市场/药店/小学三要素齐备，未发现 1km 服务盲区。`
}

/* ── rev2 · 判盲口径版本 / 证据置信度（D-3 折扣 + D-4 陈旧拦截的可见面）─────── */

/**
 * 判盲空间口径的当前版本 —— **三方同源**：后端 `scope.SCOPE_POLICY_VERSION`、
 * 契约夹具 `__tests__/fixtures/compareDiffContract.json` 的
 * `caliber_incomparable.policy_version_current`，以及这里。
 *
 * 为什么要前端也持有一份：前端要判断「我手上这份报告是不是升级前的」，而报告的版本是
 * **载荷里的一个事实**（不是缓存键、也不是一列状态位）—— 只有拿着当前版本才能比。
 * 换版本时只改后端 + 夹具，两侧测试各钉一次（后端
 * `test_caliber_gap_literals_match_contract_fixture` / 前端
 * `livingCircleContract.test.ts` + `compareDiffContract.test.ts:229`），不会一边新一边旧。
 *
 * `ev-1` = 证据域独立于可达域；`ev-2` = 追加逐格台账 `caliber.cells_ledger`（契约 B13）。
 * 升到 `ev-2` 的可见后果：出厂那两份 `ev-1` 快照（凯里演示件、劲松实测件）从此各带一行
 * 「判盲口径已升级……建议重新体检」—— 那是 D-4「只拦复用、不拦可见性」的正常表现。
 */
export const SCOPE_POLICY_VERSION = 'ev-2'

/**
 * 口径轴登记表 —— 差异表/横幅那句"不可比"的**唯一**措辞来源。
 *
 * 为什么要有这张表：原来"不可比"那句是按**轴的子集枚举**写死的（`CALIBER_GAP_DESC` /
 * `COVERAGE_GAP_DESC` / `BOTH_GAP_DESC` 三句），并在 `caliberGapDesc` 与 `rowGapDesc`
 * 各分了一次支。两把尺是 3 个非空子集，看着还好；**第三根轴就是 7 个子集 × 两处分支 ×
 * 两端常量** —— 加口径轴的成本会指数涨，而加轴恰恰是这套机制的常态演化。
 *
 * 改成组合式后：每轴只贡献一个子句，句子按**表的固定顺序**拼。加一根轴 ＝ 表加一行，
 * 子集常量与分支都不再增加。
 *
 * ⚠️ `clause` 必须**自带解释**，不许为了短而砍掉：`COVERAGE_GAP_DESC` 那句里的
 * 「（点数 → 门槛项）」是承重的（见下方原注释 —— 判盲轴解释不了 65.4 与 68.4 之间那 3 分
 * 是分子换代产生的）。组合式若把它丢了，两轴都不同那一档就又回到"只报半句"。
 */
export type CaliberAxis = 'ev' | 'cov' | 'rc' | 'sh'

interface CaliberAxisSpec {
  readonly axis: CaliberAxis
  /** 差异表/横幅里这一轴的完整子句（自带解释） */
  readonly clause: string
}

export const CALIBER_AXES: readonly CaliberAxisSpec[] = [
  { axis: 'ev', clause: '判盲口径已升级' },
  { axis: 'cov', clause: '评分口径已升级（点数 → 门槛项）' },
  // 第三根轴：实测耗时场**怎么被解释**（本次标定的常态绕行系数 + 残差耗时，笔 3-B）。
  // 与后端 `_GAP_CLAUSES` 逐字同源；子句同样必须自带解释。
  // ⚠️ 它今天**不拦差异表里的任何一行**（见下面 `GAP_AXES` 的注释），但横幅照报 ——
  // 横幅问的是"这对报告能不能并排看"，一侧有残差解释、一侧没有，本来就是两套解释。
  { axis: 'rc', clause: '可达口径已升级（耗时场新增常态绕行与残差解释）' },
  // 第四根轴（笔九 S20 · `sh-1`）：等时圈形状量（八方位最远可达 + 圆度 + 最弱方位比）。
  // 与 `rc` 同一条决定：**横幅照报、行级不拦**（`GAP_AXES` 里刻意不给任何一行写 'sh'）——
  // 两侧同 ev/cov 时每一行读数逐位相同，`scoring.WEIGHTS` 一行没动，这把尺只多一块诊断面板。
  // 那块面板在单份报告上的出现与否，由 `shapeOfZone(...) == null` 的缺键判据管，不归这句提示管。
  { axis: 'sh', clause: '形状口径已升级（等时圈新增八方位诊断尺）' },
]

/** 这一对报告**有哪几根**口径轴不同（表的顺序）。加一根轴就在这里多一行 —— 线性，不是子集。 */
function differingAxes(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): CaliberAxis[] {
  const out: CaliberAxis[] = []
  if (caliberPolicyGap(a, b)) out.push('ev')
  if (coverageCaliberGap(a, b)) out.push('cov')
  if (reachCaliberGap(a, b)) out.push('rc')
  if (shapeCaliberGap(a, b)) out.push('sh')
  return out
}

/**
 * 若干根轴不同 ⇒ 那一句结论（空集 ⇒ null ＝ 可比）。
 * 顺序恒为表的顺序，与调用方传入的轴顺序无关（否则同一对报告在两个页面上会拼出两种词序）。
 */
export function gapDescFor(axes: readonly CaliberAxis[]): string | null {
  const clauses = CALIBER_AXES.filter((s) => axes.includes(s.axis)).map((s) => s.clause)
  return clauses.length ? `不可比 · ${clauses.join('、')}` : null
}

/** 口径版本不同 ⇒ 差异表那两行的结论句（与后端 `_DIFF_DESC_CALIBER_GAP` 逐字同源）。 */
export const CALIBER_GAP_DESC = gapDescFor(['ev']) as string

/** 只有**评分口径**那根轴不同 ⇒ 同一格换这句（与后端 `_DIFF_DESC_COVERAGE_GAP` 逐字同源）。
 *  ⚠️ 不许复用上面那句：判盲轴解释不了"65.4 与 68.4 之间那 3 分是分子换代产生的"。 */
export const COVERAGE_GAP_DESC = gapDescFor(['cov']) as string

/** **两根轴都**不同 ⇒ 第三句（与后端 `_DIFF_DESC_BOTH_GAP` 逐字同源）。
 *  为什么要有第三句而不是"判盲优先"：两轴都换时只报判盲那半，读者仍会把分差归给一把尺。
 *  本笔起这句由表拼出，措辞从「判盲与评分口径都已升级」变成两句子句并列 —— 信息只增不减。 */
export const BOTH_GAP_DESC = gapDescFor(['ev', 'cov']) as string

/** 只有**可达口径**那根轴不同 ⇒ 同一格换这句（与后端 `_DIFF_DESC_REACH_GAP` 逐字同源）。 */
export const REACH_GAP_DESC = gapDescFor(['rc']) as string

/** 只有**形状口径**那根轴不同 ⇒ 同一格换这句（与后端 `_DIFF_DESC_SHAPE_GAP` 逐字同源）。 */
export const SHAPE_GAP_DESC = gapDescFor(['sh']) as string

/** **四根轴都**不同 ⇒ 由表拼出的最长那句（与后端 `_DIFF_DESC_ALL_GAP` 逐字同源）。
 *  这一档存在的意义是证明组合式没退化成"只报前几根"：句子必须四段子句全在、顺序恒定。 */
export const ALL_GAP_DESC = gapDescFor(['ev', 'cov', 'rc', 'sh']) as string

/** 两轴对照出的结论句（null = 两轴都同 ⇒ 可比）。差异表与横幅**共用这一处判据**。 */
export function caliberGapDesc(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  return gapDescFor(differingAxes(a, b))
}

/** 每行**受哪几根口径轴影响**（`ev` = 判盲那把尺、`cov` = 覆盖度分子）—— 与后端
 *  `app/main.py` 的 `_GAP_AXES` 同源，行名与轴归属由契约夹具 `gap.applies_to` /
 *  `gap.coverage_applies_to` 在两侧各自钉住。
 *
 *  ⚠️ #83：这里原来只有「一行行名 + 一把共用结论句」，于是**只评分轴不同**那一档，
 *  「服务盲区」也被写成「不可比 · 评分口径已升级（点数 → 门槛项）」—— 而分子换代影响不到
 *  盲区数（10-03 真库配对实测：两侧 `ev-2` 相同、盲区 1 vs 1，本该「持平」）。横幅那两句
 *  仍按「两轴合起来」说（`caliberGapDesc` 逐字不动），**行级**必须按轴分派。 */
const GAP_AXES: Record<string, readonly CaliberAxis[]> = {
  服务盲区: ['ev'],
  综合评分: ['ev', 'cov'],
  // ⚠️ `rc` **刻意不在任何一行的轴清单里**（与后端 `_GAP_AXES` 同一条决定）：rc-1 只新增
  // 对耗时场的解释，两侧同 ev/cov 时每一行的读数逐位相同。把 rc 写进某行 ⇒ 那一行被一句
  // 影响不到它的话拦住，正是 #83 抓过的形态（那次是评分轴去拦盲区行）反过来重演。
  // 残差进评分那一档（rc-2）再把 综合评分 扩成 ['ev','cov','rc']。
  // ⚠️ 第四根轴 `sh`（S20 · 形状量）同样**不给任何一行**：它不入 `scoring.WEIGHTS`，
  // 两侧同 ev/cov 时每行读数逐位相同，拦一行就是替这把尺撒谎。
}

/** 受**某根**轴影响的行并集（契约 `gap.applies_to`）。「POI 采集」那类**事实计数**不在其列：
 *  换判盲尺子不改变采到多少设施。 */
export const CALIBER_GAP_ROW_KEYS: readonly string[] = Object.keys(GAP_AXES)

/** 评分轴拦得住的行（契约 `gap.coverage_applies_to`）⇒ **盲区行不在其列**，这条就是 #83。 */
export const COVERAGE_GAP_ROW_KEYS: readonly string[] = CALIBER_GAP_ROW_KEYS.filter((key) =>
  GAP_AXES[key]?.includes('cov'),
)

/** 可达轴拦得住的行（契约 `gap.reach_applies_to`）⇒ **今天这个集合必须是空的**。
 *  空集本身就是判据：它记的是"rc-1 不改任何一行的读数"这件事。哪天残差进了评分，
 *  这个数组会非空、契约夹具的 `reach_applies_to` 必须同时改 —— 两边不同步即红。 */
export const REACH_GAP_ROW_KEYS: readonly string[] = CALIBER_GAP_ROW_KEYS.filter((key) =>
  GAP_AXES[key]?.includes('rc'),
)

/** 形状轴拦得住的行（契约 `gap.shape_applies_to`）⇒ **今天也必须是空的**（与 `rc` 同一条决定：
 *  它只多一块诊断面板，一行的读数都不改）。空集本身就是判据，非空那天要连同
 *  `GATED_CALIBER_VERSIONS` 一起改。 */
export const SHAPE_GAP_ROW_KEYS: readonly string[] = CALIBER_GAP_ROW_KEYS.filter((key) =>
  GAP_AXES[key]?.includes('sh'),
)

/**
 * **这一行**的口径不可比结论（null ⇒ 这一行可比），只看影响得到它的那几根轴。
 *
 * 与 `caliberGapDesc()`（两轴合起来那一句，供对比页横幅）分家是必须的：横幅问「这对报告
 * 整体能不能并排看」，行级问「这一行的两个数是不是同一把尺量出来的」。两轴都不同那一档
 * 两者就不同 —— 评分行拿第三句，盲区行仍只拿判盲句。
 */
export function rowGapDesc(
  key: string,
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  // 行级只看"影响得到这一行的轴"∩"这一对确实不同的轴"—— 与 `caliberGapDesc` 共用
  // `gapDescFor`，所以两轴都不同那一档自然拼出两句并列，不需要再枚举一个子集常量（#83）。
  const mine = GAP_AXES[key] ?? []
  return gapDescFor(differingAxes(a, b).filter((ax) => mine.includes(ax)))
}

/** 判盲口径版本号安全取值：旧快照 / 离线骨架没这个键 ⇒ `null`（不是空串）。 */
export function policyVersionOf(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = lc?.caliber?.scope_policy_version
  return typeof v === 'string' && v ? v : null
}

/** 两份报告用的是不是**同一把判盲尺**（含一侧根本没声明）。 */
export function caliberPolicyGap(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): boolean {
  return policyVersionOf(a) !== policyVersionOf(b)
}

/**
 * 旧口径报告的「建议重新体检」提示（当前口径 ⇒ null）。
 *
 * 为什么提示而不是隐藏：历史报告是用户的数据（D-4「只拦复用、不拦可见性」）。但旧口径
 * 的证据面只有可达区一角（凯里实测 5/97）—— 盲区天然少报、分数天然偏高，不说明就等于
 * 继续按「没有盲区」卖一遍。
 */
export function staleCaliberNotice(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = policyVersionOf(lc)
  if (v === SCOPE_POLICY_VERSION) return null
  return v == null
    ? '判盲口径已升级（证据域独立），本报告的盲区数与综合评分偏乐观 —— 建议重新体检'
    : `判盲口径已升级（本报告 ${v}，当前 ${SCOPE_POLICY_VERSION}），盲区数与综合评分偏乐观 —— 建议重新体检`
}

/* ── 第二根轴：评分口径（覆盖度分子）────────────────────────────────────────
 *
 * `cov-1` 把覆盖度的**分子**从「圈内点数」换成「门槛项数」，与判盲那把尺（`ev-*`）是
 * **两件独立的事**：换分子不改证据域，扩证据域也不改分子。所以这根轴必须**自己说一句** ——
 * 复用上面那句「判盲口径已升级」就是把评分账记到判盲头上（计划 §六 明令禁止的"两把键
 * 互相顶替"，第 21 轮 P1-3 抓到的正是这半边）。
 *
 * 版本常量**三方同源**：后端 `category_rule.COVERAGE_CALIBER_VERSION`、契约夹具
 * `caliber_incomparable.coverage_version_current`、这里。与 `SCOPE_POLICY_VERSION` 同一套
 * 换版流程：只改后端 + 夹具，两侧测试各钉一次。
 *
 * ⚠️ 这根键**不进** `caliber_payload_key`（缓存键）也**不进**契约门禁 B 系列 —— 前者会让
 * 每条缓存静默 miss 再烧一遍外呼配额，后者会让 B 系列变成双键门（§六 拍板）。它只走
 * 「复用门 + 名册 + 读侧披露」三条路。
 */
export const COVERAGE_CALIBER_VERSION = 'cov-1'

/** 评分口径版本号安全取值：`cov` 键上线前冻结的快照（存量 29 份）没这个键 ⇒ `null`。 */
export function coverageCaliberVersionOf(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = lc?.caliber?.coverage_caliber_version
  return typeof v === 'string' && v ? v : null
}

/** 两份报告用的是不是**同一把评分尺**（含一侧根本没声明）。 */
export function coverageCaliberGap(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): boolean {
  return coverageCaliberVersionOf(a) !== coverageCaliberVersionOf(b)
}

/**
 * 评分口径换代后的陈旧提示（当前口径 ⇒ null）。
 *
 * 「缺键」与「键值不同」说的是两件事，必须分开：缺键 = 这份快照冻结在分子换代**之前**，
 * 它的分数是**按点数**算的；值不同 = 换代之后又调过分子口径。把前者写成后者会谎报
 * "这份是 cov-0"（那份载荷里从来没有过任何评分口径声明）。
 */
export function staleCoverageCaliberNotice(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = coverageCaliberVersionOf(lc)
  if (v === COVERAGE_CALIBER_VERSION) return null
  return v == null
    ? '评分口径已升级（本报告按圈内点数计分，当前按门槛项数计分），类别覆盖度与综合评分不可与新报告直接比 —— 建议重新体检'
    : `评分口径已升级（本报告 ${v}，当前 ${COVERAGE_CALIBER_VERSION}），类别覆盖度与综合评分不可与新报告直接比 —— 建议重新体检`
}

/* ── 第三根轴：可达口径（耗时场怎么被解释）──────────────────────────────────
 *
 * `rc-1` 在 `sampling.detour` 里发射「本次实测标定的常态绕行系数 + 残差耗时分位」，与
 * `ev-*`（证据域）和 `cov-*`（覆盖度分子）是三件独立的事：换解释不改证据域、也不改分子。
 * 借前任何一根的键表达它，等于在版本记录上撒谎（`cov-1` 那次立的规矩）。
 *
 * 版本常量**三方同源**：后端 `caliber.REACH_CALIBER_VERSION`、契约夹具
 * `caliber_incomparable.reach_version_current`、这里。
 *
 * ⚠️ 这根轴**有意不发单份报告那句「建议重新体检」**（即它不在 `staleCaliberNotices` 里），
 * 两条理由都要记住：
 *  ① `rc-1` 没改任何读数 ⇒ 那句 CTA 会承诺一件重跑之后并不会发生的事（分数不变）。
 *     "报告偏乐观所以重跑"那两句只对 `ev`/`cov` 成立，套到 `rc` 上就是替它撒谎。
 *  ② 单份报告的正确形态是**缺键就不印**（与逐格台账 `cells_ledger`、取证账 `forensic` 同一
 *     条纪律）：没有 `sampling.detour` ⇒ 残差那一句整块不出现，而不是挂一条红字。
 * 它今天被消费的两处是：**对比页横幅**（两份载荷并排时"一根轴不同"是真事实，
 * `differingAxes` 自动带上 `rc`）与**残差句的 presence 判据**（`residualCaliberNote`）。
 * 等残差真的进了评分（rc-2，答案会变），再把它接进 `staleCaliberNotices`。
 */
export const REACH_CALIBER_VERSION = 'rc-1'

/** 可达口径版本号安全取值：这把键上线前冻结的快照没这个键 ⇒ `null`（不是空串）。 */
export function reachCaliberVersionOf(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = lc?.caliber?.reach_caliber_version
  return typeof v === 'string' && v ? v : null
}

/** 两份报告用的是不是**同一把耗时解释尺**（含一侧根本没声明）。 */
export function reachCaliberGap(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): boolean {
  return reachCaliberVersionOf(a) !== reachCaliberVersionOf(b)
}

/**
 * 形状口径版本号安全取值（`sh-*`）。**只读载荷自带的声明**，不跟任何"当前版本常量"比 ——
 * 那把尺的家在后端 `isochrone.SHAPE_CALIBER_VERSION`（另存一颗前端常量就是零消费者字段，
 * 还会诱导出"拿代码常量当对照值"那个老错：两份都没有这把尺时，它们互相之间确实是同一把）。
 */
export function shapeCaliberVersionOf(lc: Pick<LivingCircleReport, 'caliber'>): string | null {
  const v = lc?.caliber?.shape_caliber_version
  return typeof v === 'string' && v ? v : null
}

/**
 * 两份报告用的是不是**同一代形状口径**（`sh-*`，含一侧根本没声明）。
 *
 * ⚠️ 刻意**不在前端另存一颗"当前版本号"常量**：`rc`/`ev`/`cov` 那三把都有单份报告要读的
 * 当前值（陈旧提示、残差句），而 `sh` 只回答"这两份是不是同一代产物"，两边都比的是
 * **载荷自带的声明**。另存一颗就是零消费者字段，且会诱导出"拿代码常量当对照值"那个
 * 老错（两份旧报告都没有这把尺时，它们互相之间确实是同一把 —— 见后端 `_differing_axes`
 * 那条警告）。当前代次与契约夹具 `gap.shape_version_current` 的一致性由**后端**测试钉
 * （`isochrone.SHAPE_CALIBER_VERSION` 才是那把尺的家）。
 */
export function shapeCaliberGap(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): boolean {
  return shapeCaliberVersionOf(a) !== shapeCaliberVersionOf(b)
}

/**
 * 残差耗时那句口径说明（`rc-1` 的**唯一**上屏出口）。缺 `sampling.detour`、或本次没有可用
 * 样本 ⇒ `null`，**整块不出现** —— 与逐格台账（`cellsLedgerOf` 取不到就不摆空卡）、取证账
 * （`forensic` 缺键就不写"跑了 0 轮"）同一条纪律：这里印 0 会被读成"量到了 0 分钟残差"。
 *
 * 三件事必须同时说清，缺一句就是一句半真话：
 *  ① 这把尺是**本次实测标定**的，不是口径表里那个声明值（两者并列报出，差多少是明账）；
 *  ② 残差只有**分钟**，不换算是百分比（那是把减法重新写成除法，也让"远"和"堵"分不开）；
 *  ③ 它是**受阻代理**，不指认河道/天桥/围挡中的任何一个（数据里区分不开，综述也明确
 *     几何交互模型不适用微观尺度 ⇒ 不许宣称微观可达性精度）。
 */
export function residualCaliberNote(
  lc: Pick<LivingCircleReport, 'sampling'>,
): string | null {
  const d = lc?.sampling?.detour
  if (!d) return null
  const k = d.detour_factor_measured
  const res = d.residual_min
  if (k == null || !res) return null
  const e = d.excluded
  return (
    `残差耗时（受阻代理，不指认具体障碍）：按本次实测标定的常态绕行 ${k}× 扣除后`
    + `（口径声明值是 ${d.declared_detour_k}×），中位 ${res.p50}min、p90 ${res.p90}min、`
    + `最堵的一档 ${res.max}min；入样 ${d.points_used} 点，剔除 中心 ${e.near_center}`
    + `·未测时 ${e.untimed}·零耗时 ${e.non_positive}`
  )
}

/**
 * 口径对照环的**唯一取值口**（笔 B）：拿不到、或载荷的断言边界不是"只做口径对比"，就返回 `null`。
 *
 * `claim` 这一位不是装饰：后端契约 B16 会挡住非 `caliber_comparison_only` 的载荷，但那是**签发时**
 * 的闸；读侧（历史列表里的旧件、外部导入的镜像）可能绕过它。渲染层在这里再判一次，
 * 是因为"把群体有效窗口读成某个居民走不到"这句话一旦上屏就收不回来 —— 宁可不画。
 */
export function isoCompareOf(
  lc: Pick<LivingCircleReport, 'iso_compare'> | null | undefined,
): IsoCompare | null {
  const c = lc?.iso_compare
  if (!c || c.claim !== 'caliber_comparison_only') return null
  if (!(Number.isFinite(c.minutes) && c.minutes > 0)) return null
  if (!(Number.isFinite(c.area_km2) && c.area_km2 > 0)) return null
  if (!c.geojson?.coordinates?.[0]?.length) return null
  return c
}

/**
 * 口径对照那句（**渲染层只调这一颗**，图例副行与右栏口径区共用）。
 *
 * 措辞是纪律的一部分，不是文风：
 * ① 主语必须是**口径**（"按文献 X 分钟阈值重切"），不能是人群 —— 文献量的是群体有效窗口，
 *    写成"老人只能走到 X"就是把群体结论变成对具体社区/具体居民的能力断言；
 * ② 阈值一律读载荷的 `minutes`，不写死 8（写死＝第二个事实源，口径表改一次屏幕说一次谎）；
 * ③ 百分比的分母取 **15min 那档的面积**（政策原文是"约 15 分钟"，这个对比才有落点），
 *    且只在该档存在时才说 —— 拿 20min 圈当分母会把差距说小。
 * 缺载荷 ⇒ `null`（整行不出现，不是出现一句"暂无"）。
 */
export function isoCompareLabel(
  lc: Pick<LivingCircleReport, 'iso_compare' | 'isochrones'> | null | undefined,
): string | null {
  const c = isoCompareOf(lc)
  if (!c) return null
  const fifteen = (lc?.isochrones ?? []).find((z) => z.minutes === 15)
  const head = `口径对照：同一实测场按文献 ${c.minutes} 分钟阈值重切 = ${c.area_km2} km²`
  if (!fifteen || !(fifteen.area_km2 > 0)) return `${head}（两把尺的对比，不指认个体能力）`
  return `${head}，是 15 分钟圈的 ${Math.round((c.area_km2 / fifteen.area_km2) * 100)}%`
    + '（两把尺的对比，不指认个体能力）'
}

/**
 * 陈旧提示清单（**渲染层只调这一个**）：判盲句在前、评分句在后，各自独立出现。
 *
 * 为什么不合并成一句：两轴同时陈旧时合并只能报一半（"判盲口径已升级"里塞不进"分子换代"，
 * 反过来也一样），而每少报一半就少拦一种误读。两页（报告页 `caliberNote` / 体检台右栏）
 * 各写一遍"哪句该出现"正是漂移的形态 ⇒ 判断收在这里，页面只管渲。
 *
 * ⚠️ 第三根轴 `rc` **有意不在这份清单里**（理由与它被消费的两处都写在上面那段 `rc-1` 注释里）：
 * 那两句的共同点是"重跑一次答案会更准"，而 rc-1 不改任何读数 ⇒ 挂它等于挂一个空承诺。
 * 残差进评分（rc-2）时把它接进来，同时 `GATED_CALIBER_VERSIONS` 也要挪。
 */
export function staleCaliberNotices(lc: Pick<LivingCircleReport, 'caliber'>): string[] {
  return [staleCaliberNotice(lc), staleCoverageCaliberNotice(lc)].filter((s): s is string => !!s)
}

const DAY_S = 86400

/** `generated_at` 排成 `YYYY-MM-DD`；坏值/缺值 ⇒ `''`（不猜一个日期上屏）。
 *
 * ⚠️ **按 UTC 排，不按运行机器的时区排**。时间戳本身是 `...Z`（UTC），用 `getFullYear()`
 * 这类本地读法会让同一份报告在 CI（UTC）与 +08 的笔记本上印出两个"生成日期"——
 * `2026-09-30T16:00:25Z` 一台说 09-30、另一台说 10-01，而年龄算法用的是绝对时刻、两边都
 * 算得出 5 天 ⇒ 日期与年龄自相矛盾。这条是打印水印原本就带着的形状，这里统一收进来改对。
 */
export function generatedOn(lc: Pick<LivingCircleReport, 'generated_at'>): string {
  const t = Date.parse(lc?.generated_at ?? '')
  if (Number.isNaN(t)) return ''
  const d = new Date(t)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`
}

/** 这份数据距今多少**天**（向下取整，最小 0）；时间戳坏 ⇒ `null`。
 *  `now` 是**参数**而不是内部 `new Date()` —— 判据要能确定性地跑（同一份载荷在 CI 里
 *  不能因为今天几号而给出不同的话）。 */
export function dataAgeDays(
  lc: Pick<LivingCircleReport, 'generated_at'>,
  now: Date = new Date(),
): number | null {
  const t = Date.parse(lc?.generated_at ?? '')
  if (Number.isNaN(t) || Number.isNaN(now.getTime())) return null
  return Math.max(0, Math.floor((now.getTime() - t) / 1000 / DAY_S))
}

/**
 * 时效与复用条件那一句（4b 的唯一上屏出口）。
 *
 * 守的是"承诺与行为对齐"：这条链今天在同参数 30 天内、或中心 500m 内会**直接复用**旧答复
 * （省配额，是既定设计，`served_from` 也已经把来源标在屏上了）。缺的从来不是披露，而是
 * ⑴ 看不见这份数据多旧、⑵ 没有强制重测的入口。⑵这次补上了（图上「重新体检」带 `force`），
 * 这句就是把⑴与阈值一起说清 —— **三个数字全部读自 payload**（`reuse_window`），
 * 前端不抄一份 30/7/500：抄的那份会在阈值改动的那天开始说谎（本仓为这个形状立过多次规矩）。
 *
 * 缺 `reuse_window`（升级前落库的存量件）⇒ 只报时点与年龄，不编阈值。
 */
export function freshnessNote(
  lc: Pick<LivingCircleReport, 'generated_at' | 'reuse_window'>,
  now: Date = new Date(),
): string | null {
  const dateStr = generatedOn(lc)
  if (!dateStr) return null
  const age = dataAgeDays(lc, now)
  const ageStr = age == null ? '' : age === 0 ? '（今天）' : `（${age} 天前）`
  const w = lc?.reuse_window
  if (!w || !(w.report_ttl_s > 0) || !(w.nearby_radius_m > 0)) {
    return `数据时点 ${dateStr}${ageStr}`
  }
  return (
    `数据时点 ${dateStr}${ageStr} · 同参数 ${Math.round(w.report_ttl_s / DAY_S)} 天内、`
    + `中心 ${Math.round(w.nearby_radius_m)}m 内的既有体检会被直接复用（不重测）；`
    + '要重测点图上「重新体检」'
  )
}

/**
 * 类别旁那句门槛项口径说明（片 1c-β C1 甲档）。
 *
 * 要拦的误读：凯里教育柱 33 与正文「圈内 15 处」同屏，按点数复算 15÷3=100% ⇒ 读者只能认定
 * 数据对不上。这句把"分子换了"当场说出来，且**名字与数字全部来自 payload**。
 *
 * ⚠️ 三件事约束它的形状：
 *  ① 前端**不许**按点位名字重判子类（判类全仓只有后端 `evaluate_category` 一处）⇒ 名单读
 *     `scored_as`/`unscored_as`，缺键就**不印**（不猜、不退回硬编码名单）；
 *  ② `required_in_circle` 为 `null`（未建表 / 旧载荷）⇒ 返回 null，**不得**印成"0 处计入"；
 *  ③ 满分线（`ideal_circle`）**不在 payload 里** ⇒ 这句只报"圈内 N 处中 M 处"，不写「÷ 3」。
 *     要写分母得先把满分线交出来，那是另一次契约变更（计划 §十九 与片 1c-β C1 硬约束那条）。
 */
export function lcCategoryCaliberNote(c: FacilityCategoryStat): string | null {
  const req = c.required_in_circle
  const hit = c.scored_as
  if (req == null || !hit || hit.length === 0) return null
  const miss = c.unscored_as && c.unscored_as.length
    ? `（${c.unscored_as.join('、')}不计入分子）`
    : ''
  return `${c.label} · 覆盖度只数「${hit.join(' / ')}」：圈内 ${c.in_circle} 处中 ${req} 处 ⇒ ${Math.round(c.coverage * 100)}%${miss}`
}

/* ── 对比页逐类目差距（笔1 · P1/P2）─────────────────────────────────────────
 *
 * 立表理由：这两种空值在旧差异表里**塌成同一行**。
 *  - `total=0`（这一类在研究范围内一个都没有）⇒ 后端不给最近耗时（`min_minutes` 为 `null`）；
 *  - `in_circle=0` 而 `total>0`（有，但全在可达圈外）⇒ `min_minutes` 有值。
 * 旧表只有两个合计，凯里「养老一个都没有」与北京「养老有 2 家都在圈外」读出来都是「0」。
 *
 * 三件事约束它的形状：
 *  ① 展示值即比较值：`deltaMin` 先四舍五入到一位小数再返回，屏上印的就是被减出来的那个数
 *     （同 `_isoArea15` 那条纪律 —— 否则 7.44 与 13.94 显示成 7.4/13.9 却判出 +6.5 之外的差）；
 *  ② 前端**不许**重判子类：门槛口径只读 `required_in_circle`／`scored_as`，
 *     键缺席与 `null` 是两种事实，各自一档（`'absent'` / `'none'`），**都不许塌成 0**；
 *  ③ 类目按 `category` 键配对，不按数组下标 —— 两份载荷的类目顺序不保证一致。
 */

/** 一侧的类目读数；整份载荷没有这一类时调用方拿到 `null`（不是 0）。 */
export interface CategorySideStat {
  total: number
  inCircle: number
  /** `null` = 这一类一个都没有 ⇒ 没有"最近耗时"可言 */
  minMinutes: number | null
  /** `number` 门槛项数；`'none'` 发了子类表但这一类未建表；`'absent'` 整份载荷没发过子类表 */
  required: number | 'none' | 'absent'
  /** 按哪些类别计分（后端算好的名单，前端只印不判） */
  scoredAs: string[] | null
}

export interface CategoryCompareRow {
  category: string
  label: string
  a: CategorySideStat | null
  b: CategorySideStat | null
  /** B − A 的最近耗时（min，一位小数）；任一侧没值 ⇒ `null`，调用方不得印 0 */
  deltaMin: number | null
}

function _sideOf(c: FacilityCategoryStat | undefined): CategorySideStat | null {
  if (!c) return null
  const req = 'required_in_circle' in c ? c.required_in_circle : undefined
  return {
    total: c.total,
    inCircle: c.in_circle,
    minMinutes: c.min_minutes ?? null,
    required: req === undefined ? 'absent' : req === null ? 'none' : req,
    scoredAs: c.scored_as && c.scored_as.length ? c.scored_as : null,
  }
}

/**
 * 逐类目并排行。行名与行序取自 **A 侧载荷**，B 侧多出来的类别追加在末尾 ——
 * 与 `COMPARE_ROWS` 同一取向：行名来自 payload，不来自前端硬编码名单。
 */
export function categoryCompareRows(
  a: LivingCircleReport,
  b: LivingCircleReport,
): CategoryCompareRow[] {
  const ca = a.poi?.categories ?? []
  const cb = b.poi?.categories ?? []
  const codes: string[] = []
  for (const c of ca) if (!codes.includes(c.category)) codes.push(c.category)
  for (const c of cb) if (!codes.includes(c.category)) codes.push(c.category)
  return codes.map((code) => {
    const rowA = ca.find((c) => c.category === code)
    const rowB = cb.find((c) => c.category === code)
    const sa = _sideOf(rowA)
    const sb = _sideOf(rowB)
    const d = sa?.minMinutes != null && sb?.minMinutes != null ? sb.minMinutes - sa.minMinutes : null
    return {
      category: code,
      label: rowA?.label ?? rowB?.label ?? code,
      a: sa,
      b: sb,
      deltaMin: d === null ? null : Number(d.toFixed(1)),
    }
  })
}

/**
 * 对比页那句「一侧按门槛项计分、另一份整份没发过这个口径」。
 *
 * 为什么单份页面没有这句、两份并排才需要：`CategoryCaliberNotes` 的纪律是"缺席即不印"
 * （单份看没问题 —— 没口径就别提口径）。但并排时沉默会被读成"这一侧没有门槛要求"，
 * 而事实是"这份载荷没发过这个键"⇒ 两侧覆盖度不是同一把尺。这句只报这一件事。
 *
 * 判定仍走同一颗 `lcCategoryCaliberNote`：不另建一套"看键"逻辑，否则就成了第二份真源。
 */
export function lcCompareCaliberGapNote(a: LivingCircleReport, b: LivingCircleReport): string | null {
  const shipped = (lc: LivingCircleReport) =>
    (lc.poi?.categories ?? []).some((c) => lcCategoryCaliberNote(c) !== null)
  const sa = shipped(a)
  const sb = shipped(b)
  if (sa === sb) return null
  const gap = sa ? b : a
  const ok = sa ? a : b
  return `${gap.scene.name} 这份载荷没发过门槛项口径（覆盖度按圈内点数解释）；`
    + `${ok.scene.name} 按门槛项数计分 ⇒ 两侧覆盖度不是同一把尺，别横着比分子。`
}

/* ── 逐格台账（契约 B13 · 计划 cells-ledger-judge-scale §6）───────────────────
 *
 * 这片只做**解码**，不做判定：五个字母（`1`/`0`/`.`/`-`/格型）与十张矩阵的含义都由
 * 后端 `blindspot.render_cells_ledger` 定，前端若在这里重抄一遍"缺哪类算盲"，就成了
 * 同一判据的第二份实现 —— 那正是本仓反复出事的形状（不对称规则只许有 `_verdict_masks` 一处）。
 *
 * 取值一律走 `cellsLedgerOf`：**任何**不符（缺键、行数/行长不符、字母表外、格型或
 * schema 不是这一代）都返回 `null`，调用方据此**不画图层**。宁可少一层解释，
 * 也不能把半截台账读成一份结论。
 */

export const LEDGER_SCHEMA_VERSION = 1
export const LEDGER_GRID = 'square'
export const LEDGER_YES = '1'
export const LEDGER_NO = '0'
/** 第三态：这一类在该格**没被证明查全** ⇒ 命中与否无从知道。⚠️ 不是「没有」。 */
export const LEDGER_UNKNOWN = '.'
export const LEDGER_NO_DISTANCE = '-'
export const LEDGER_TRIAD_KEYS = ['market', 'pharmacy', 'primary'] as const

/** 一格的结论档。五档各自对应台账里的一句话，**不许合并**（合并即说谎）：
 *  `outside` 可达区外不判 · `blind` 判盲 · `clear` 三类皆有据且皆命中 ·
 *  `unknown` 有类没查全（我们的取证缺口）· `capped` 判不动且归因于接口封顶。 */
export type LedgerVerdict = 'outside' | 'blind' | 'clear' | 'unknown' | 'capped'

export interface LedgerClassState {
  key: string
  label: string
  /** 有据？null = 无从知道（`.`） */
  evidence: boolean | null
  /** 1km 内命中？null = 无从知道 */
  hit: boolean | null
  /** 最近举证点距离（米）；null = 没有距离可报 */
  nearestM: number | null
}

export interface LedgerCellState {
  i: number
  j: number
  verdict: LedgerVerdict
  classes: LedgerClassState[]
}

const LEDGER_CHARS = new Set([LEDGER_YES, LEDGER_NO, LEDGER_UNKNOWN])

const ledgerRows = (v: unknown, n: number): v is string[] =>
  Array.isArray(v) && v.length === n && v.every(
    (r) => typeof r === 'string' && r.length === n && [...r].every((c) => LEDGER_CHARS.has(c)),
  )

const ledgerDistRows = (v: unknown, n: number): v is string[] =>
  Array.isArray(v) && v.length === n && v.every(
    (r) => typeof r === 'string' && r.split(' ').length === n
      && r.split(' ').every((t) => t === LEDGER_NO_DISTANCE || /^\d+$/.test(t)),
  )

/** 取台账并验形；不合规 ⇒ `null`（不抛、不猜满）。 */
export function cellsLedgerOf(lc: Pick<LivingCircleReport, 'caliber'>): CellsLedgerRaw | null {
  const led = lc.caliber?.cells_ledger as CellsLedgerRaw | undefined | null
  if (!led || typeof led !== 'object') return null
  const n = led.n
  // n 必须是正的奇数：判定格阵恒为奇数（分析中心要恰好落在格心上，否则中心格被半格偏移污染）
  if (!Number.isInteger(n) || n <= 0 || n % 2 === 0) return null
  if (led.grid !== LEDGER_GRID || led.schema_version !== LEDGER_SCHEMA_VERSION) return null
  if (!Array.isArray(led.center) || led.center.length !== 2) return null
  if (!(led.step_m > 0) || !(led.scan_m > 0) || !(led.radius_m > 0)) return null
  for (const key of ['inside', 'capped', 'blind', 'verdict'] as const) {
    if (!ledgerRows(led[key], n)) return null
  }
  for (const triad of LEDGER_TRIAD_KEYS) {
    if (!ledgerRows(led[`judge.${triad}`], n) || !ledgerRows(led[`present.${triad}`], n)) return null
    if (!ledgerDistRows(led[`nearest.${triad}`], n)) return null
  }
  return led
}

/** 经纬度 → 格索引 `(i 行=y, j 列=x)`；落在格阵外 ⇒ `null`。
 *  格心轴是后端 `linspace(-scan, scan, n)`，这里用**同一个** `lcMeters` 换算（等距圆柱近似），
 *  两端同式才不会出现「点在这格、卡片说那格」。 */
export function cellAt(lc: Pick<LivingCircleReport, 'caliber'>, lnglat: LngLat): [number, number] | null {
  const led = cellsLedgerOf(lc)
  if (!led) return null
  return cellIndex(led, lnglat)
}

export function cellIndex(led: CellsLedgerRaw, lnglat: LngLat): [number, number] | null {
  const [x, y] = lcMeters(led.center, lnglat[0], lnglat[1])
  // `+ 0` 不是装饰：`Math.round(-0.2)` 给的是 `-0`，而 `Object.is(-0, 0)` 为 false ⇒
  // 同一格会被 React key 与测试当成两格。坐标本身是 NaN 时不回落，直接判"不在格阵里"。
  const i = Math.round((y + led.scan_m) / led.step_m) + 0
  const j = Math.round((x + led.scan_m) / led.step_m) + 0
  if (!Number.isFinite(i) || !Number.isFinite(j)) return null
  if (i < 0 || j < 0 || i >= led.n || j >= led.n) return null
  return [i, j]
}

/** 格索引 → 格心经纬度（画选中格与它的判定圆要用）。 */
export function cellCenter(led: CellsLedgerRaw, i: number, j: number): LngLat {
  return lcFromMeters(led.center, -led.scan_m + j * led.step_m, -led.scan_m + i * led.step_m)
}

/** 读一格的状态。**只读字符**：结论取自后端发下来的 `blind`/`verdict`/`capped` 三张位，
 *  不在这里重算不对称规则。 */
export function cellVerdict(lc: Pick<LivingCircleReport, 'caliber'>,
                            cell: [number, number] | null): LedgerCellState | null {
  const led = cellsLedgerOf(lc)
  if (!led || !cell) return null
  const [i, j] = cell
  if (i < 0 || j < 0 || i >= led.n || j >= led.n) return null
  const bit = (rows: string[]) => rows[i][j]
  const at = (rows: string[]) => rows[i]?.[j] ?? LEDGER_UNKNOWN
  const dist = (rows: string[]) => {
    const tok = rows[i]?.split(' ')[j]
    return tok === undefined || tok === LEDGER_NO_DISTANCE ? null : Number(tok)
  }
  let verdict: LedgerVerdict = 'outside'
  if (bit(led.inside) === LEDGER_YES) {
    if (bit(led.blind) === LEDGER_YES) verdict = 'blind'
    else if (bit(led.verdict) === LEDGER_YES) verdict = 'clear'
    else verdict = bit(led.capped) === LEDGER_YES ? 'capped' : 'unknown'
  }
  const classes: LedgerClassState[] = []
  for (const triad of LEDGER_TRIAD_KEYS) {
    const present = at(led[`present.${triad}`])
    classes.push({
      key: triad,
      label: lcEvidenceCategoryLabel(triad),
      evidence: at(led[`judge.${triad}`]) === LEDGER_YES ? true : false,
      hit: present === LEDGER_UNKNOWN ? null : present === LEDGER_YES,
      nearestM: dist(led[`nearest.${triad}`]),
    })
  }
  return { i, j, verdict, classes }
}

/** 本次判定那把尺（米）。两个来源按新旧排：台账（`ev-2` 起有）→ 盲区条目自带的 `radius_m`。
 *  两个都没有 ⇒ `null` —— **不许**回落到常量 1000：多模式分档后它不是常量，
 *  写死就会让图上 800m 的圆旁边标着 1km（复审 v1.2 P1-1 的落点）。 */
export function judgeRulerM(lc: Pick<LivingCircleReport, 'caliber' | 'blindspots'>): number | null {
  const led = cellsLedgerOf(lc)
  if (led) return led.radius_m
  const declared = (lc.blindspots ?? [])
    .map((b) => (typeof b.radius_m === 'number' && b.radius_m > 0 ? b.radius_m : null))
    .find((v): v is number => v !== null)
  return declared ?? null
}

/** 那把尺的上屏说法（图例与概览小图共用同一句，两处文案不许各写一份半径）。 */
export function judgeRulerLabel(lc: Pick<LivingCircleReport, 'caliber' | 'blindspots'>): string | null {
  const m = judgeRulerM(lc)
  return m === null ? null : `以格心为圆心、半径 ${Math.round(m)}m 的圆`
}

/**
 * 三要素那一排的取数出口（菜市场 / 药店 / 小学各一枚 chip）。
 *
 * 为什么要收成一处而不是让每个渲染面自己 `.map(lc.scores.triads)`：`visitorUnrated` 那条
 * 棘轮按**文本**扫「谁在读报告分数」，读法散到 `src/dev/` 的预览件上就会把渲染出口谎报成
 * 新的分数消费点。取数走这里（本文件已在基线内），预览件与生产视图共用同一份行对象，
 * 也顺带消灭了"探针自己抄一遍取数"这种第二实现。
 */
export function triadRows(
  lc: Pick<LivingCircleReport, 'scores'>,
): LivingCircleReport['scores']['triads'] {
  return lc.scores?.triads ?? []
}

/**
 * 三要素条目落在哪一种事实上 —— 后端 `_triad_state`（`diagnosis_templates.py`）的镜像。
 *
 * `scores.triads[]` 带着**两把尺**的产物：`in_reach`（可达区，实测耗时场 + 多边形封顶）与
 * `within_blind_radius`（中心 1km 直线）。此前只有一个 `covered`，于是"可达区内没有"被
 * 一路说成"1km 内缺失"—— 一家直线 950m、隔河需 35min 的药店会被报成根本没有，
 * 而同一份报告的盲区清单里就躺着它的 `distance_m`。
 *
 * 五态互斥，**「未查全」既不许塌成「没有」也不许并进「有」**（与逐格台账 `present` 的
 * int8 三态同一条纪律）。渲染面一律走这里，不许再各自写 `t.covered ? … : '1km 内缺失'`。
 */
export type TriadState = 'reachable' | 'blocked' | 'absent' | 'unknown' | 'missing'

export function triadState(t?: TriadFacility | null): TriadState {
  if (!t) return 'missing'
  const inReach = t.in_reach ?? t.covered
  if (inReach) return 'reachable'
  // 旧快照没这个键 ⇒ 读作"无从知道"，绝不等于"1km 内没有"
  if (t.within_blind_radius == null) return 'unknown'
  return t.within_blind_radius ? 'blocked' : 'absent'
}

/** 三要素 chip 上那半句文案（五态各说一句真话）。 */
export function triadChipText(t: TriadFacility | null | undefined): string {
  if (!t) return '未产出结论'
  const s = triadState(t)
  if (s === 'reachable') return `最近 ${t.nearest_minutes ?? '—'}min`
  if (s === 'blocked') return `1km 内有（${Math.round(t.nearest_m ?? 0)}m）· 步行到不了`
  if (s === 'absent') return '中心 1km 内没有'
  if (s === 'unknown') return '1km 内有没有未查全'
  return '未产出结论'
}

/** 三要素 chip 的配色档（`TRIAD_CHIP_CLASS` 的键）。 */
export type TriadChipTone = 'ok' | 'gap' | 'unknown'

/** 三要素 chip 的配色档：`unknown` 走中性，不许借用警告色（那等于替它下"没有"的结论）。 */
export function triadChipTone(t: TriadFacility | null | undefined): TriadChipTone {
  const s = triadState(t)
  if (s === 'reachable') return 'ok'
  if (s === 'unknown' || s === 'missing') return 'unknown'
  return 'gap'
}

/** 体检台、报告体检单与预览件三个渲染面共用这一份类名；各写一份就是三处配色实现。 */
export const TRIAD_CHIP_CLASS: Record<TriadChipTone, { chip: string; dot: string }> = {
  ok: { chip: 'bg-ok/10 text-primary-deep', dot: 'bg-ok' },
  gap: { chip: 'bg-warn/10 text-ink-2', dot: 'bg-warn' },
  unknown: { chip: 'bg-line/60 text-ink-3', dot: 'bg-ink-3' },
}

/**
 * 章节 key_takeaway 那半句 —— 后端 `_triad_takeaway` 的**同一份措辞**。
 * 演示态（本文件）与实时态（后端模板）此前各写一套，于是后端改了说法、mock 还在说旧的，
 * 而 `test_fixture_mirror` 只比 JSON 数据、不比渲染句子 ⇒ 这条漂移无人看守。
 * 现在两侧字面量由 `__tests__/triadProseMirror.test.ts` 逐条对齐。
 */
export function triadTakeawayText(t: TriadFacility | null | undefined): string {
  if (!t) return '未产出该要素结论'
  switch (triadState(t)) {
    case 'reachable':
      return `可达区内有（最近 ${fmtTriadMin(t.nearest_minutes)}）`
    case 'blocked':
      return `可达区内没有，但中心 1km 内有（最近 ${Math.round(t.nearest_m ?? 0)}m）⇒ 步行到不了`
    case 'absent':
      return '中心 1km 内没有'
    case 'unknown':
      return '可达区内没有；中心 1km 内有没有未查全'
    default:
      return '未产出该要素结论'
  }
}

/** claims 那半句 —— 后端 `_triad_claim` 的同一份措辞（论断挂证据 ID，措辞必须与尺对齐）。 */
export function triadClaimText(t: TriadFacility | null | undefined): string {
  if (!t) return '无法判定（缺该要素的三要素结论）'
  switch (triadState(t)) {
    case 'reachable':
      return '覆盖达标（可达区内有）'
    case 'blocked':
      return '可达区内缺口 —— 1km 内有但步行到不了'
    case 'absent':
      return '覆盖缺位（中心 1km 内没有）'
    case 'unknown':
      return '无法判定（可达区内没有，1km 内有没有未查全）'
    default:
      return '无法判定（缺该要素的三要素结论）'
  }
}

/** 概览那句三要素总评 —— 后端 `_triad_overview` 的同一份分桶逻辑。 */
export function triadOverviewText(triads: TriadFacility[]): string {
  if (!triads?.length) return '本次未产出三要素结论'
  const pick = (s: TriadState) => triads.filter((t) => triadState(t) === s).map((t) => t.facility)
  const blocked = pick('blocked')
  const absent = pick('absent')
  const unknown = pick('unknown')
  if (!blocked.length && !absent.length && !unknown.length) return '菜市场/药店/小学三要素在可达区内均有'
  const parts: string[] = []
  if (absent.length) parts.push(`「${absent.join('、')}」中心 1km 内没有`)
  if (blocked.length) parts.push(`「${blocked.join('、')}」1km 内有但步行到不了`)
  if (unknown.length) parts.push(`「${unknown.join('、')}」1km 内有没有未查全`)
  return '三要素：' + parts.join('；')
}

/** 教育段"就学通勤视角"那一句 —— 后端 `_triad_school_para` 的同一份措辞。 */
export function triadSchoolParaText(t: TriadFacility | null | undefined): string {
  if (!t) return '可达区内没有小学，而中心 1km 内有没有尚未查全，先补取证再谈学区'
  switch (triadState(t)) {
    case 'reachable':
      return `最近小学步行 ${t.nearest_minutes ?? '—'}min，处于可接受范围`
    case 'blocked':
      return `中心 1km 内有小学（最近 ${Math.round(t.nearest_m ?? 0)}m）但步行到不了，接送需绕行 —— 这正是「道路并非直线」落在上学这件事上的样子`
    case 'absent':
      return '中心 1km 内没有小学，需关注跨区就学问题'
    default:
      return '可达区内没有小学，而中心 1km 内有没有尚未查全，先补取证再谈学区'
  }
}

function fmtTriadMin(v: number | null | undefined): string {
  return v == null ? '—' : `${v}min`
}

/** 评分置信度安全取值：旧快照 / 离线骨架缺该键 ⇒ `null`（渲染层不给徽标，不猜成 full）。 */
export function confidenceOf(lc: Pick<LivingCircleReport, 'scores'>): 'full' | 'limited' | null {
  const c = lc?.scores?.confidence
  return c === 'full' || c === 'limited' ? c : null
}

/**
 * 对比页横幅的**判盲轴**那一句（判盲轴两侧都是当前口径 ⇒ null）。
 *
 * ⚠️ 页面不要直接调它，要调 `compareCaliberNotices` —— 只调这一颗会让"两轴都不同"那一屏
 * 横幅只报判盲、表格那格却写着两把尺都换了（同屏两处披露各说一半）。
 *
 * 两种病要分开说：**版本不同** ⇒ 那两个数不是同一把尺量出来的，直接禁止比较；
 * **两份都还是旧口径** ⇒ 彼此可比，但都偏乐观 —— 答辩演示拿的正是这两份内置快照，
 * 只拦「不同」不报「都旧」，观众看到的仍是两个被高估的分数并排。
 *
 * 第 21 轮 P1-3：这句原先是横幅**唯一**那句，于是"两份都 `ev-2`、但一份没有 `cov` 键"
 * 在对比页被判**可比** —— 而它的分差恰恰全部来自分子换代。评分轴那半见
 * `compareCoverageCaliberNotice`。
 */
export function compareCaliberNotice(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  const va = policyVersionOf(a)
  const vb = policyVersionOf(b)
  const shown = (v: string | null) => v ?? '升级前（未声明）'
  if (va !== vb) return `两侧判盲口径不同（${shown(va)} vs ${shown(vb)}）⇒ 服务盲区与综合评分不可直接比，建议重新体检较旧的一份`
  if (va === null && vb === null) return '两份报告都出自判盲口径升级前的版本 ⇒ 盲区数与综合评分偏乐观，建议重新体检'
  return null
}

/** 对比页横幅的**评分轴**那一句（判盲轴由上面那颗管，两句各说各的事）。 */
export function compareCoverageCaliberNotice(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  const ca = coverageCaliberVersionOf(a)
  const cb = coverageCaliberVersionOf(b)
  const shown = (v: string | null) => (v === null ? '换代前（按点数计分）' : v)
  if (ca !== cb) return `两侧评分口径不同（${shown(ca)} vs ${shown(cb)}）⇒ 类别覆盖度与综合评分不可直接比，建议重新体检较旧的一份`
  if (ca === null && cb === null) return '两份报告都出自评分口径换代前的版本 ⇒ 覆盖度与综合评分按圈内点数计，与新报告不可直接比'
  return null
}

/** 横幅句里"升级了什么"那半句的唯一来源：直接取登记表的子句，不在这里另抄一份措辞。
 *  登记表与后端 `_GAP_CLAUSES`、契约夹具逐字同源（由 `compareDiffContract` 两侧判据钉住）⇒
 *  改子句只需改表，横幅自动跟着变；在横幅里手写一份就等于造出第二份真源。
 *  ⚠️ 范围只到 rc/sh 这两句：ev/cov 那两句是**登记表之前**的手写措辞（各自带着"建议重新体检"
 *  那句 CTA），改表不带动它们 —— 2026-10-10 补 rc/sh 时按"不顺手改既有用户可见文案"留着，
 *  真要让四句同源是一次独立的措辞变更，得重取那两句的逐字判据。 */
function caliberClause(axis: CaliberAxis): string {
  return CALIBER_AXES.find((s) => s.axis === axis)?.clause ?? axis
}

const shownVersion = (v: string | null): string => v ?? '升级前（未声明）'

/**
 * 对比页横幅的**可达解释轴**那一句（`rc-*`）。
 *
 * ⚠️ 与 `compareCaliberNotice`/`compareCoverageCaliberNotice` 有**两处有意不同**，都是
 * `REACH_CALIBER_VERSION` 上头那两条理由的延伸，别当疏漏"顺手补齐"：
 *  ① 不发「建议重新体检较旧的一份」—— `rc-1` 没改任何一行读数，那句 CTA 承诺的是
 *     一件重跑之后并不会发生的事；
 *  ② 两份都没发这把键 ⇒ **不报**（它们互相之间确实是同一把尺），不像 ev/cov 那样
 *     另给一句"两份都旧"。
 */
export function compareReachCaliberNotice(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  const ra = reachCaliberVersionOf(a)
  const rb = reachCaliberVersionOf(b)
  if (ra === rb) return null
  return `两侧可达口径不同（${shownVersion(ra)} vs ${shownVersion(rb)}）⇒ ${caliberClause('rc')}；`
    + '它不改任何一行读数，只决定那块解释在不在 ⇒ 不必重新体检，但别把「没这块」读成「没有差异」'
}

/** 对比页横幅的**形状尺轴**那一句（`sh-*`）。两条"有意不同"与上面那颗同源。 */
export function compareShapeCaliberNotice(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string | null {
  const sa = shapeCaliberVersionOf(a)
  const sb = shapeCaliberVersionOf(b)
  if (sa === sb) return null
  return `两侧形状口径不同（${shownVersion(sa)} vs ${shownVersion(sb)}）⇒ ${caliberClause('sh')}；`
    + '报告页那一屏八方位诊断只在一侧存在 ⇒ 不必重新体检，但别把「没这块」读成「没有差异」'
}

/** 横幅清单（**页面只调这一个**）：四轴各一句，各出现各的。
 *
 * 为什么不是合成一句：只调 `compareCaliberNotice` 时，"两轴都不同"那一屏会出现**横幅只报判盲、
 * 表格里那格却写着"两把尺都换了"**的自相矛盾（10-01 落地后重渲预览当场看到的）—— 同屏两处披露
 * 各说一半，正是本批一直在堵的形状。
 *
 * ⚠️ 2026-10-10 L0 真实态现形：这里原本**只拼 ev + cov 两句**，而 `CALIBER_AXES` 与
 * `REACH_CALIBER_VERSION` 的注释都写着 rc/sh「对比页横幅照报」——那句承诺没有消费者：
 * 真库 `lc-51b782d2`（rc-1/sh-2）× `lc-4ef46187`（两戳都没发）只差这两根轴，
 * 行级按设计不拦、横幅又不报 ⇒ 屏上一句口径提示都没有。后两句就是补这条。
 */
export function compareCaliberNotices(
  a: Pick<LivingCircleReport, 'caliber'>,
  b: Pick<LivingCircleReport, 'caliber'>,
): string[] {
  return [
    compareCaliberNotice(a, b),
    compareCoverageCaliberNotice(a, b),
    compareReachCaliberNotice(a, b),
    compareShapeCaliberNotice(a, b),
  ].filter((s): s is string => !!s)
}

/**
 * 降档徽标文案（chip）—— 分数的折扣要解释**为什么**低了，不然像算法随机抖动。
 *
 * 覆盖率只从 `caliber` 的格数分账取（单一真源）；`scores.evidence.judged_share` 是评分侧
 * 的自述，两者由契约判据 B11 钉成同一个数 —— UI 不该再「信任」一遍自述来显示它。
 * 与 `blindspotCoverageBrief`（灰脚注）分工：那句说**判了多少**，这枚说**结论因此偏乐观**
 * 且**分数已打折**，两者不互相替换（旧口径快照没有 confidence ⇒ 这枚不出现，脚注仍在）。
 */
export function confidenceBadgeLabel(lc: Pick<LivingCircleReport, 'scores' | 'caliber'>): string | null {
  if (confidenceOf(lc) !== 'limited') return null
  const cov = blindspotCoverage(lc)
  return cov == null ? '证据面不足' : `证据面不足 · 覆盖率 ${cov.judgedPct}%`
}

export type OriginTone = 'live' | 'warn' | 'info'

export interface DataOriginBadge {
  /** 徽标主文案（地图页 / 报告页共用口径，D2） */
  label: string
  /** 补充说明（title 悬停） */
  detail: string
  /** 视觉基调：live=绿（真实）、warn=黄（估算/演示）、info=蓝（历史缓存） */
  tone: OriginTone
}

/** data_origin 四态徽标映射（P0-1/F1 单一真相源）：offline / served_from='cache'|'nearby_cache' / live / fixture_sample */
export function dataOriginBadge(r: Pick<LivingCircleReport, 'data_origin' | 'served_from'>): DataOriginBadge {
  if (r.served_from === 'cache' || r.served_from === 'nearby_cache') {
    // nearby_cache（邻近命中，v5 O1/D9）同样是缓存复用，不是本次实时重算 ——
    // 必须与 cache 同为 info 基调，否则横幅说「未消耗额度」徽标却写「真实数据」会自相矛盾
    const near = r.served_from === 'nearby_cache'
    return {
      label: near ? '邻近历史实时' : '历史实时 · 离线可查',
      detail: near ? '原中心距此 ≤500m 的既有实时结果（未消耗百度额度）' : '缓存命中的历史实时路网测时结果',
      tone: 'info',
    }
  }
  switch (r.data_origin) {
    case 'offline':
      return { label: '离线估算', detail: '距离模型估算 · 未联网，POI/评分/盲区待实时体检', tone: 'warn' }
    case 'fixture_sample':
      return { label: '演示数据', detail: '内置演示样例（fixture_sample）', tone: 'warn' }
    default:
      return { label: '真实数据', detail: '实时百度路网测时（live）', tone: 'live' }
  }
}

/* ── R-7 · 降级披露（「为什么这次是离线估算」）───────────────────── */

/**
 * `degraded.detail` → 中文归因标签。
 *
 * ⚠️ **与后端 `app/living_circle/degrade_policy.py::detail_label()` 是同一张表**，
 * 逐字对齐（同 `poiMetricLabel` / `poi_metric_label` 的跨语言同口径纪律）。
 * 未知/缺失一律回落 `'配额耗尽'` —— **不抛异常、不返回空串**（降级时更要说得出话）。
 */
export const DEGRADE_DETAIL_LABELS: Record<string, string> = {
  total_meltdown: '总量熔断',
  daily_budget_exhausted: '日预算熔断',
  quota_blocked: '配额受限',
  isochrone_empty: '测时失败',
  poi_empty: '采集为空',
  // 片 4：取证额度不足 —— **只**出现在 `report.partial.detail`，不是降级成因。
  // 说成"熔断"会让读者以为这份报告随时可能整份作废，而它说的是"按计划只打了这么多"。
  forensic_pool_short: '取证额度不足',
  unknown: '配额耗尽',
}

/** 未知取值的回落标签（也是「有降级标记但归因不明」时的说法：不猜） */
export const DEGRADE_DETAIL_FALLBACK = '配额耗尽'

export function degradeDetailLabel(detail?: string | null): string {
  return (detail && DEGRADE_DETAIL_LABELS[detail]) || DEGRADE_DETAIL_FALLBACK
}

export interface DegradeBanner {
  /** 归因标签（例：`总量熔断`）—— 给窄容器（chip/徽标）用，别去反解 `title` */
  label: string
  /** 标题：点名成因（例：「百度总量熔断：本次实时采集被熔断，已降级为离线估算」） */
  title: string
  /** 口径说明（与未联网离线的说明同构，保证「降级」不会比「离线」少说任何一件事） */
  body: string
  /** 行动提示（q-2：只给文案，不给按钮 —— 重检会重新消耗额度，不该由用户随手触发） */
  action: string
  /** 视觉基调：降级是事故不是提示 ⇒ 与「未联网离线（warn）」拉开色阶 */
  tone: 'risk'
}

/**
 * 降级披露**唯一出口**：`degraded` 存在 ⇒ 返回横幅三件套；否则 `null`（走原「离线估算」文案）。
 *
 * 为什么收成一个函数：报告页 / 地图页 / 历史列表三处都要说同一件事，
 * 各写一遍就是「同一口径 N 处实现」（本项目明确禁忌）。
 */
export function degradeBanner(
  r: Pick<LivingCircleReport, 'degraded'> | Pick<{ degraded?: LifeCircleDegraded | null }, 'degraded'>,
): DegradeBanner | null {
  const d = r.degraded
  if (!d) return null
  const label = degradeDetailLabel(d.detail)
  return {
    label,
    title: `百度${label}：本次实时采集被熔断，已降级为离线估算`,
    body: '区县中心近似 + 直线距离 × 绕行系数测时，等时圈为圆形近似——评分与盲区不可与实时分比较',
    action: d.note ? `${d.note} · 配额恢复后可发起实时重检` : '配额恢复后可发起实时重检',
    tone: 'risk',
  }
}

/**
 * 取证账目 / 证据域明细的**唯一取值出口**（计划 v7.1 片 5）。
 *
 * 为什么"缺键就是缺键"而不给默认值：`caliber.forensic` 与 `evidence_anchors` 都是
 * **不传不发**（后端 `scope.payload` 只在真走了取证阶段时才发射）。若这里回落成
 * `{rounds: 0}` 或 `[]`，离线估算与判盲口径升级前冻结的旧快照就会被前端说成
 * 「取证过了、只是没扩出东西」—— 替一次没发生的事举证。
 */
export function forensicAccount(
  lc: Pick<LivingCircleReport, 'caliber'>,
): ForensicAccount | null {
  return lc.caliber?.forensic ?? null
}

export function evidenceDiscs(lc: Pick<LivingCircleReport, 'caliber'>): EvidenceDisc[] {
  return lc.caliber?.evidence_anchors ?? []
}

/** 三要素检索类 → 展示层身份（中文名 + 配色借用哪个展示类）。
 *
 * ⚠️ 它的键集合 = 后端 `triad_keywords` 那三枚，与 `LC_CAT_LABEL`（8 个**展示类**，镜像后端
 * `CATEGORY_RULES`、键集由 `lcCatLabel.contract.test.ts` 钉住）是**两套键**：药店 / 小学不是展示
 * 类别，把它们并进那张表会当场撞那条两端契约。证据盘的 `category` 用的是这一套。
 *
 * 配色**不另起一套**：三要素本来就是对应展示类的代表点（药店∈医疗、小学∈教育），图例里那些点
 * 已经是这两个色；新造色等于让读者对两次色卡。 */
export const LC_TRIAD: Record<string, { label: string; colorClass: string }> = {
  market: { label: '菜市场', colorClass: 'market' },
  pharmacy: { label: '药店', colorClass: 'medical' },
  primary: { label: '小学', colorClass: 'education' },
}

/** 证据盘/回合账目里那一枚类别键怎么念：先查三要素表，再落展示类表，最后原样给键。 */
export function lcEvidenceCategoryLabel(key: string): string {
  return LC_TRIAD[key]?.label ?? LC_CAT_LABEL_OF(key, key)
}

/**
 * 证据盘配色 —— BMap 的 `Circle`、降级画布的 `<polygon>`、预览探针**共用这一个出口**。
 *
 * 为什么不能就地 `LC_CAT_COLOR[d.category] ?? '#5F7B69'`（第十六轮评审 P1）：三要素里的
 * `pharmacy` / `primary` 不在 `LC_CAT_COLOR` 的 8 枚展示类里 ⇒ 凯里实测 34 盘中 24 盘落进兜底色，
 * 而 `#5F7B69` **正是** `LC_ISO_COLORS` 四级的描边色 —— 图层打开后证据盘与等时圈同色，等于没打开。
 * 未知类别落 `#7c6670`（与 POI 点层同一枚兜底），**不落在等时圈绿上**。
 */
export function lcEvidenceDiscColor(key: string): string {
  return LC_CAT_COLOR[LC_TRIAD[key]?.colorClass ?? key] ?? '#7c6670'
}

/** 逐趟表「锚点」那一格的句子 —— 报告页与预览探针**共用这一处**（两处各写一份就会一新一旧：
 *  「只判了一次」那句就是探针先犯、组件跟着犯）。
 *
 * 未派发那趟**分两档**，因为"没派发"有两种真原因：
 * - `anchors_planned > 0`：缺口在、额度只容得下一部分，但那趟被我们自己的上限卡住 ⇒
 *   念「需求 N · 额度容 M · 一个没打」（凯里实测：17 / 3 / 14，收手 `rounds_exhausted`）。
 * - `anchors_planned === 0`：**排不出新锚点**（网格步长已到底，北京实测收手 `nothing_to_ask`）⇒
 *   念「没排出新锚点」。此时若还说"额度容 0"，就是把没点可打演成钱不够 —— 归因方向错到底，
 *   与后端 `degrade_policy.partial_block()` 那条优先级是同一族缺陷。 */
export function roundAnchorCell(r: ForensicRoundRow): string {
  if (r.dispatched) return `${r.anchors_planned}→${r.anchors_sent}→${r.anchors_used}`
  return r.anchors_planned === 0 ? '没排出新锚点' : `需求 ${r.anchors_planned} · 额度容 ${r.anchors_sent} · 一个没打`
}

/** 逐趟表「未跑 / 砍掉」那一格：未派发趟没有"跑了没成"这回事 ⇒ 未跑位给 `—`，砍掉的账照念。 */
export function roundDroppedCell(r: ForensicRoundRow): string {
  return r.dispatched ? `${r.anchors_not_run} / ${r.anchors_dropped}` : `— / ${r.anchors_dropped}`
}

/**
 * 合成盘：后端从**标量边界反推**出来的举证盘，没有逐锚点检索记录
 * （`stop_reason=null` 且实测半径 == 请求半径，见 `scope.py:892-894`「它按定义不自称查全」）。
 *
 * 为什么前端要单独认这一档（批 B 真打接口读数带出的缺陷）：这类盘上屏若走「未查全」，
 * 同一行就同时写着「实测查到 2367m / 请求 2367m」和「未查全」—— 读者只会读到矛盾。
 * 而把它说成「查全」更不行（后端就是按"没证明"发的）。⇒ 第三档，不是两档。
 * 真数据里两城都有：凯里 2/5 盘、北京 1/14 盘。
 */
export function isSyntheticDisc(d: EvidenceDisc): boolean {
  return (
    !d.complete &&
    d.stop_reason == null &&
    Math.abs(d.exhausted_radius_m - d.request_radius_m) < 0.5 // 后端两值各按 0.1 取整
  )
}

/** 一个证据盘的悬浮举证句 —— BMap 的 `Circle` 与降级画布的 `<polygon>` **共用这一句**。
 *  两个渲染分支各写一份 tooltip 文案，就会在"这圈到底查没查全"上说出不一致的话。 */
export function evidenceDiscTitle(d: EvidenceDisc): string {
  const cat = lcEvidenceCategoryLabel(d.category)
  const state = d.complete
    ? '查全'
    : isSyntheticDisc(d)
      ? '按首轮边界反推的举证盘（未逐锚点记录，不自称查全）'
      : `未查全${d.stop_reason ? `（${d.stop_reason}）` : ''}${d.cap_hit ? ' · 被接口上限截断' : ''}`
  return `${cat} 证据盘：实测查到 ${Math.round(d.exhausted_radius_m)}m / 请求 ${Math.round(
    d.request_radius_m,
  )}m · ${state}`
}

/** 锚点那一行的念法（A 档「亮的那颗点是什么」）。与 `evidenceDiscTitle` 同处出句：
 *  预览探针与地图浮层各写一份，就会出现"预览里有、实现里没有"那种偏离。 */
export function evidenceDiscAnchorLabel(d: EvidenceDisc): string {
  return `取证锚点 · ${lcEvidenceCategoryLabel(d.category)} · (${d.anchor[0].toFixed(4)}, ${d.anchor[1].toFixed(4)})`
}

/* ──── 圈选联动：命中判定 + 选中态描边（live / 降级 / 探针共用同一处） ──── */

/** 盘的像素域描述：调用方投影（live 走 `pointToPixel`，降级走 `lcToPx`）后交进来。
 *  `index` 是身份 —— `EvidenceDisc` 只有 7 个字段、后端不发 id（`types.ts:984-993`），
 *  同心盘（北京实测中心 3 盘同一 anchor）只能靠数组下标区分。 */
export interface LcDiscHitTarget {
  index: number
  centerPx: [number, number]
  radiusPx: number
}

export type LcDiscHitKind = 'ring' | 'center' | 'inside' | 'nearest'

export interface LcDiscHit {
  target: LcDiscHitTarget
  /** ring=压在环线上 / center=压在圆心 / inside=落在某盘内 / nearest=谁都没中、取最近圆心 */
  kind: LcDiscHitKind
  /** 该档判据下的距离（ring 为到环线的差，其余为到圆心的差），单位 px */
  deltaPx: number
}

/** 环带命中宽度：盘只描边 ⇒ 可指的是边界本身，与等时圈那条 14px 透明命中线同量级。 */
export const LC_HIT_BAND_PX = 12
/** 圆心命中半径：锚点标记与同心盘用这一档解歧。 */
export const LC_HIT_CENTER_PX = 10

/**
 * 光标 → 哪个盘。**确定性优先级 ①环带 > ②圆心 > ③内部归属 > ④最近圆心**，
 * 同级一律按下标升序取第一个 ⇒ 同心三盘（北京 market/pharmacy/primary）的消歧结果可写进用例，
 * 不依赖"谁碰巧近"。写不成全序就会让 live 与降级两分支各挑一个盘，正是本次投诉的机制。
 */
export function hitEvidenceDisc(
  cursor: [number, number],
  targets: LcDiscHitTarget[],
): LcDiscHit | null {
  if (targets.length === 0) return null
  const measured = targets.map((t) => ({ t, d: Math.hypot(cursor[0] - t.centerPx[0], cursor[1] - t.centerPx[1]) }))
  const bandDelta = (x: (typeof measured)[number]) => Math.abs(x.d - x.t.radiusPx)
  const byBand = measured
    .filter((x) => bandDelta(x) < LC_HIT_BAND_PX)
    .sort((a, b) => bandDelta(a) - bandDelta(b) || a.t.index - b.t.index)
  if (byBand.length)
    return { target: byBand[0].t, kind: 'ring', deltaPx: bandDelta(byBand[0]) }
  const byCenter = [...measured].sort((a, b) => a.d - b.d || a.t.index - b.t.index)
  if (byCenter[0].d < LC_HIT_CENTER_PX) return { target: byCenter[0].t, kind: 'center', deltaPx: byCenter[0].d }
  const inside = byCenter.filter((x) => x.d < x.t.radiusPx)
  if (inside.length) return { target: inside[0].t, kind: 'inside', deltaPx: inside[0].d }
  return { target: byCenter[0].t, kind: 'nearest', deltaPx: byCenter[0].d }
}

/** 盘的描边：常态 1.4 = `LcMap` 今天的构造值（`lifeCircleForensicUi.test.tsx:300` 钉住的是它）。
 *  ⚠️ 选中态**只加粗、只提不透明度**，绝不动 `fillOpacity:0` 与 `enableClicking:false`
 *  —— 那两枚是「勾开图层后地图仍能被拖动」那条真机证据的载体，改了就把"突出"做成"挡操作"。 */
export const LC_DISC_WEIGHT = { idle: 1.4, focus: 3.2, dim: 1 } as const

/** 盘的三档描边：`dim` 是"别的盘"——选中一个盘时其余要退到背景去，
 *  否则 14 个盘同屏时"突出"根本看不出来（预览第一轮 A/B 两张看不出区别就是这个原因）。
 *  与等时圈 hover 的淡化档同族（`LcMap` 的 `dimRings`）。 */
export function discStroke(state: 'idle' | 'focus' | 'dim'): { strokeWeight: number; strokeOpacity: number } {
  if (state === 'focus') return { strokeWeight: LC_DISC_WEIGHT.focus, strokeOpacity: 1 }
  if (state === 'dim') return { strokeWeight: LC_DISC_WEIGHT.dim, strokeOpacity: 0.14 }
  return { strokeWeight: LC_DISC_WEIGHT.idle, strokeOpacity: 0.9 }
}

/** 取证锚点标记（A 档「亮的那颗点」）：盘心现在图上**不存在任何标记** ——
 *  真读数两城 19 个盘的 anchor 与任一 POI 坐标逐位相等的有 0 个，所以必须新画一颗，
 *  不能拿附近的设施点冒充锚点。形状与 `fixPlusSvg` 同族（实心核 + 白边），纯函数零 SDK 依赖。 */
export function lcAnchorDotSvg(color: string, size = 22): string {
  const c = size / 2
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<circle cx="${c}" cy="${c}" r="${c - 1.5}" fill="none" stroke="#ffffff" stroke-width="3"/>` +
    `<circle cx="${c}" cy="${c}" r="${c - 1.5}" fill="none" stroke="${color}" stroke-width="1.6"/>` +
    `<circle cx="${c}" cy="${c}" r="3.2" fill="${color}"/></svg>`
  )
}

export function lcAnchorDotDataUrl(color: string, size = 22): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(lcAnchorDotSvg(color, size))}`
}

export interface PartialBanner {
  /** 归因标签（`取证额度不足` / `总量熔断`…），给窄容器用 */
  label: string
  /** 标题：按成因分支各给一句**为真**的话 —— 两族混成一句就是说假话 */
  title: string
  /** 正文：后端 `partial.note` 原样上屏（唯一措辞出处，前端不改写） */
  body: string
  /** 视觉基调：部分完成不是事故 ⇒ 与 `degradeBanner` 的 risk 拉开一档，走 warn */
  tone: 'warn'
}

/**
 * `partial` 横幅**唯一出口**（与 `degradeBanner()` 分名分职，不并入）。
 *
 * 两条分支的依据是后端 `degrade_policy.partial_block()`：`detail` 要么是
 * `forensic_pool_short`（额度按计划打完还有格没判出），要么是熔断族（取证那一格被闸掐住）。
 * 前者**不是**接口故障，后者是 —— 所以标题分两句写，正文一律吃后端 `note`。
 */
export function partialBanner(
  lc: Pick<LivingCircleReport, 'partial'>,
): PartialBanner | null {
  const p: LifeCirclePartial | undefined = lc.partial
  if (!p) return null
  const label = degradeDetailLabel(p.detail)
  const title =
    p.detail === 'forensic_pool_short'
      ? `${label}：扩容回合没把可达区铺完（不是接口故障）`
      : `${label}：取证阶段被熔断，本次只完成一部分`
  return { label, title, body: p.note ?? '', tone: 'warn' }
}

/**
 * 报告副标题的地点前缀：`城市 · 地址｜`，**空片段不参与拼接**；全空时整个前缀（含 `｜`）省略。
 *
 * 单一真相源：副标题在演示（mock）与真实（后端 `assemble_report`）两处生成，
 * 但都消费同一个 `Report.subtitle` 字符串。若前缀规则各写一份，两端口径会漂移。
 * 判空的必要性：`address` 可能为空（区划选择只给了城市），直接拼会产出
 * 「昆明市 · ｜综合 64.4 分」这种悬空分隔符 —— 分隔符只有两侧都有内容才有意义。
 */
export function lcLocPrefix(scene: { city?: string | null; address?: string | null }): string {
  const joined = [scene.city, scene.address]
    .map((s) => (s ?? '').trim())
    .filter(Boolean)
    .join(' · ')
  return joined ? `${joined}｜` : ''
}

/* ── 形状口径（第五把尺：只诊断，不入分）· 前端唯一出口 ───────────────────── */

/**
 * 「太圆＝可疑」的告警阈值。真测件 15min 圆度最高 0.795（北京劲松），
 * 而库里那三份 `fixture_sample`（模型造形）是 0.970 —— 0.95 是**分得开**的界，
 * 不是统计显著的分位（样本只有 2 城 + 3 份假件）。所以它只配触发一句告警，
 * 绝不参与评分，也不许在文案里写成"圆度超过 0.95 即数据造假"。
 */
export const SHAPE_SUSPECT_CIRCULARITY = 0.95

/** 与后端 `geo_utils.SHAPE_*` 逐字同值的四件口径声明。 */
const SHAPE_EXPECT = {
  bin_deg: 45,
  bin_phase: 'center',
  origin: 'scene.center',
  azimuth_fn: 'bearing',
  /**
   * 复算标量的允许误差 —— 与后端 `geo_utils.SHAPE_SCALAR_TOL` **同一把尺**。
   * 跨语言导不了常量，所以两端各留一份、由 `test_fixture_mirror.py` 逐条钉相等；
   * 圆度这一判原来写 1e-2（比签发侧松一个量级 ⇒ 绕过 B17 的载荷反而能上屏），已收进这里。
   */
  scalar_tol: 1e-3,
} as const

/**
 * 形状读数的**唯一取值口**：拿不到、或口径声明与生产不符 ⇒ `null`。
 *
 * 为什么读侧还要再判一次（后端契约 B17 已经拦过）：B17 是**签发时**的闸，
 * 而历史列表里的旧件、手写 mock、外部导入的镜像都可能绕过它。屏上把
 * "floor 分相的读数"当成"中心分相的读数"讲，收不回来 —— 后端球面实算换分相最弱方位
 * 会从 438m 变成 571m（缺口被相邻方向的最大值掩盖 133m），判据见 `test_shape_caliber.py`。
 * 宁可不画。
 */
export function shapeOfZone(
  lc: Pick<LivingCircleReport, 'isochrones'> | null | undefined,
  minutes: number,
): ShapeCaliber | null {
  const zone = lc?.isochrones?.find((z) => Number(z.minutes) === Number(minutes))
  const sh = zone?.shape
  if (!sh) return null
  if (sh.bin_deg !== SHAPE_EXPECT.bin_deg) return null
  if (sh.bin_phase !== SHAPE_EXPECT.bin_phase) return null
  if (sh.origin !== SHAPE_EXPECT.origin) return null
  if (sh.azimuth_fn !== SHAPE_EXPECT.azimuth_fn) return null
  const bins = sh.bins_m
  if (!Array.isArray(bins) || bins.length !== 8) return null
  // 每格只准是「正有限数」或「null＝该向未测到」（sh-2 语义）。`0.0` 一律不画 —— 它正是
  // 被换掉的那句谎（「一步都出不去」）。八格全未测到也不画：那块面板没有可读对象。
  if (bins.some((v) => v !== null && (!Number.isFinite(v) || v <= 0))) return null
  const measured = bins.filter((v): v is number => v !== null)
  if (measured.length === 0) return null
  if (!Array.isArray(sh.bins_word) || sh.bins_word.length !== 8) return null
  if (sh.bins_word.some((w) => !w)) return null
  // 词表**内容**不许在前端另抄一份（I-07：词表只有一份，随键下发；抄了就分叉）。
  // 读侧只能判结构：八个词里有重复 ⇒ 一定是被换过序/填错过，直接不画。
  // 「整体转一格」那种（无重复但错序）只有签发闸能判 —— 见后端 B17 的 bins_word 序核对。
  if (new Set(sh.bins_word).size !== sh.bins_word.length) return null
  const rMax = Math.max(...measured)
  const rMin = Math.min(...measured)
  // 两颗标量必须能由这一档自己的数复算出来（面积出处是本档 area_km2，不许反推）。
  // `weak_ratio` 与"测到几个方向"是绑死的：≥2 个才许是数、且必须等于 min/max；
  // 只测到 1 个方向时必须是 `null` —— 发 1.0 会被读成"八方一样远"，与事实正好相反。
  if (measured.length >= 2) {
    if (!Number.isFinite(sh.weak_ratio ?? NaN)
        || Math.abs((sh.weak_ratio as number) - rMin / rMax) > SHAPE_EXPECT.scalar_tol) return null
  } else if (sh.weak_ratio !== null) {
    return null
  }
  const area = Number(zone?.area_km2)
  if (!Number.isFinite(area) || area <= 0) return null
  if (!Number.isFinite(sh.circularity) || sh.circularity <= 0 || sh.circularity > 1) return null
  const wantC = Math.sqrt((area * 1e6) / Math.PI) / rMax
  if (Math.abs(sh.circularity - wantC) > SHAPE_EXPECT.scalar_tol) return null
  return sh
}

/** 未测到的那些方位词（`bins_m` 里为 `null` 的格）—— 屏上"另有 N 个方向未测到"那份账的唯一出处。 */
export function shapeUnmeasuredWords(sh: ShapeCaliber): string[] {
  return sh.bins_m.map((v, i) => (v === null ? sh.bins_word[i] : '')).filter(Boolean)
}

/**
 * 最弱 / 最强方位的下标（同值时取靠前者，保证跨端稳定）。
 *
 * ⚠️ 只在**测到的**那些格里挑：把 `null` 当 0 参与比较，等于让"没量到"去竞争"最弱方向"，
 * 屏上就会指着一个空格说"这里最堵"。只测到一个方向时 weak ＝ strong ＝ 那一格
 * （此时 `weak_ratio` 是 `null`，措辞出口 `shapeSentence` 改说"只测到一面"）。
 */
export function shapeWeakStrong(sh: ShapeCaliber): { weak: number; strong: number } {
  const idx = sh.bins_m
    .map((v, i) => ({ v, i }))
    .filter((x): x is { v: number; i: number } => x.v !== null)
  let weak = idx[0].i
  let strong = idx[0].i
  idx.forEach(({ v, i }) => {
    if (v < (sh.bins_m[weak] as number)) weak = i
    if (v > (sh.bins_m[strong] as number)) strong = i
  })
  return { weak, strong }
}

/**
 * 屏上那句方位读数（唯一文案出口，体检台与报告页共用）。
 *
 * 只说**方向**，不说好坏：圆度测的是各向均匀性（方差），"好不好"是水平（均值），
 * 拿方差冒充均值这条推断已被自有数据证伪（同址重跑圆度极差 0.309 > 地点间差 0.110；
 * 控制面积后与可达维偏相关翻负 −0.38）。
 */
export function shapeSentence(
  lc: Pick<LivingCircleReport, 'isochrones'> | null | undefined,
  minutes: number,
): string | null {
  const sh = shapeOfZone(lc, minutes)
  if (!sh) return null
  const unmeasured = shapeUnmeasuredWords(sh)
  const measuredCount = sh.bins_m.length - unmeasured.length
  // 只测到一个方向：没有"最弱/最强"可比，硬拼那半句就是编造 —— 改说这一档的实情。
  if (measuredCount < 2) {
    const only = sh.bins_word[shapeWeakStrong(sh).weak]
    return `八个方位只测到 1 个方向的顶点（${only} ${Math.round(
      sh.bins_m[shapeWeakStrong(sh).weak] as number,
    )} m），无最弱可比`
      + (unmeasured.length ? `；其余 ${unmeasured.length} 个方向未测到顶点` : '')
  }
  const { weak, strong } = shapeWeakStrong(sh)
  return (
    `最弱方向：${sh.bins_word[weak]} ${Math.round(sh.bins_m[weak] as number)} m`
    + `（最强 ${sh.bins_word[strong]} ${Math.round(sh.bins_m[strong] as number)} m，比值 ${sh.weak_ratio}）`
    // 「未测到」必须显式说数量与方向：不说，读者会把少画的那几格读成"那里没有缺口"。
    + (unmeasured.length
        ? `；另有 ${unmeasured.length} 个方向未测到顶点（${unmeasured.join('、')}）`
        : '')
  )
}

/** 「太圆＝可疑」那句告警；未命中返回 `null` ⇒ 整句不出现（不是返回空串）。 */
export function shapeSuspectNote(
  lc: Pick<LivingCircleReport, 'isochrones'> | null | undefined,
  minutes: number,
): string | null {
  const sh = shapeOfZone(lc, minutes)
  if (!sh) return null
  if (sh.circularity < SHAPE_SUSPECT_CIRCULARITY) return null
  return (
    `形态接近平圆（圆度 ${sh.circularity} ≥ ${SHAPE_SUSPECT_CIRCULARITY}），`
    + '疑为模型造形，不反映路网 —— 该件的形状读数不参与任何横向比较'
  )
}

/** 常驻防误读声明：与评分无关这件事，只在这里写一份。 */
export function shapeCaveatNote(
  lc: Pick<LivingCircleReport, 'isochrones'> | null | undefined,
  minutes: number,
): string | null {
  const sh = shapeOfZone(lc, minutes)
  if (!sh) return null
  return (
    `形状只作方向诊断，不参与综合评分（圆度 ${sh.circularity}）。`
    + `原点 ${sh.origin} · ${sh.bin_deg}° 分箱 · 分相 ${sh.bin_phase} · 方位角 ${sh.azimuth_fn}`
  )
}

/**
 * 点位落在哪个方位箱（前端唯一实现，渲染层与条形图共用）。
 *
 * 用的是等距平面 `atan2`，而后端键里声明的是球面 `bearing()` —— 两者在 1km 尺度
 * 单点差 ≤0.0024°，实测三份真件**无一个顶点压在箱界上**，故逐箱读数相同
 * （判据见 `__tests__/shapeCaliber.test.ts` 的跨端镜像那条：它拿真环逐箱对账，
 * 哪天出现临界顶点，红的是这条判据而不是屏上的错方向）。
 */
export function shapeBinOf(center: LngLat, lng: number, lat: number): number {
  const [mx, my] = lcMeters(center, lng, lat)
  const az = (Math.atan2(mx, my) * 180) / Math.PI          // 自北顺时针，(-180,180]
  const norm = (((az + 22.5) % 360) + 360) % 360           // 与后端 (方位角+22.5)//45 同分桶
  return Math.floor(norm / 45) % 8
}

