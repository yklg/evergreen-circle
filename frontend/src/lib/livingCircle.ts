/**
 * 常青圈 · 生活圈工具库（类型无关的纯函数 + 常量）。
 *
 * 单一实现来源：地图页 / 报告页快照 / 对比页共用同一套投影与配色，
 * 避免各页面各自复制一份「m 等距投影 → 像素」逻辑造成画布不一致。
 * M 阶段 BMapGL 接入后仅替换渲染层，投影语义保持不变。
 */
import type { LngLat, LivingCircleReport, PoiPoint } from '../types'

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

/** 类别 label 兜底（与 fixture 的 label 对齐，缺省回退） */
export const LC_CAT_LABEL: Record<string, string> = {
  market: '菜市场',
  medical: '医疗',
  education: '教育',
  shopping: '购物',
  elderly: '养老',
  finance: '金融',
  recreation: '文体',
  service: '政务',
}

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
}

/**
 * 共享 POI 投影层 —— 报告快照与 LcMap 降级画布点位的唯一口径。
 *
 * 职责：把真实 `poi.points` 投影为「圆点元数据」数组。IsochroneSnapshot（报告页）
 * 与 LcMap 降级画布都从它取点，保证两处点位永不漂移、也便于单测（本项目 TC-01..07）。
 *
 * 守卫：`points` 为空/undefined → []；`cap` 只取前 N；非法坐标（缺失/NaN/Inf 或
 * lnglat 长度≠2）被过滤，绝不让坏点外溢画布。未知类别兜底色 `#7c6670`。
 */
export function lcSnapshotPoiLayer(
  center: LngLat,
  points: PoiPoint[],
  cap = 120,
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
      }
    })
    .filter((d): d is LcSnapshotPoiDot => d !== null)
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

export type OriginTone = 'live' | 'warn' | 'info'

export interface DataOriginBadge {
  /** 徽标主文案（地图页 / 报告页共用口径，D2） */
  label: string
  /** 补充说明（title 悬停） */
  detail: string
  /** 视觉基调：live=绿（真实）、warn=黄（估算/演示）、info=蓝（历史缓存） */
  tone: OriginTone
}

/** data_origin 四态徽标映射（P0-1/F1 单一真相源）：offline / served_from='cache' / live / fixture_sample */
export function dataOriginBadge(r: Pick<LivingCircleReport, 'data_origin' | 'served_from'>): DataOriginBadge {
  if (r.served_from === 'cache') {
    return { label: '历史实时 · 离线可查', detail: '缓存命中的历史实时路网测时结果', tone: 'info' }
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