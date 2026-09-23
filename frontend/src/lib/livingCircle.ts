/**
 * 常青圈 · 生活圈工具库（类型无关的纯函数 + 常量）。
 *
 * 单一实现来源：地图页 / 报告页快照 / 对比页共用同一套投影与配色，
 * 避免各页面各自复制一份「m 等距投影 → 像素」逻辑造成画布不一致。
 * M 阶段 BMapGL 接入后仅替换渲染层，投影语义保持不变。
 */
import type { LifeCircleDegraded, LngLat, LivingCircleReport, PoiPoint } from '../types'

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

/** 等时圈分级配色（5→20 分钟由深到浅）；报告/地图共用 */
export const LC_ISO_COLORS = [
  { fill: 'rgba(124,152,133,0.55)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.34)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.20)', stroke: '#5F7B69' },
  { fill: 'rgba(124,152,133,0.10)', stroke: '#5F7B69' },
]

/** 对比页 B 社区等时圈配色（品牌蓝系，与 A 绿色系区分） */
export const LC_ISO_COLORS_B = [
  { fill: 'rgba(22,119,255,0.45)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.28)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.16)', stroke: '#1677ff' },
  { fill: 'rgba(22,119,255,0.08)', stroke: '#1677ff' },
]

/** 盲区严重度语义色带（C2：重度红 / 中度橙 / 轻度黄；老数据缺 severity → 灰） */
export const LC_BLIND_SEV: Record<string, { fill: string; stroke: string; label: string; dot: string }> = {
  heavy: { fill: 'rgba(214,69,69,0.30)', stroke: '#d64545', label: '重度', dot: '#d64545' },
  medium: { fill: 'rgba(232,154,60,0.30)', stroke: '#e89a3c', label: '中度', dot: '#e89a3c' },
  light: { fill: 'rgba(227,200,79,0.33)', stroke: '#d9bd3a', label: '轻度', dot: '#d9bd3a' },
}
/** 补点处方符号（C3：实心绿核 + 白边） */
export const LC_FIX_DOT = '#1f9e63'
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