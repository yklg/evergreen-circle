/**
 * 归档记录索引 —— 列表层的单一事实源。
 *
 * 详情层的等价物是后端 `get_report`（reports + living_circle_reports 双表兜底）；
 * 本文件是它在列表层的对应物：两域记录归一成一个判别式行模型，供报告中心渲染。
 * 后端将来提供统一列表端点时，只替换 `lcRecordToRow` / `researchCardToRow` 的输入源。
 */
import type { LifeCircleDegraded, LifeCircleRecord, ReportCard, ResearchCard } from '../types'
import type { DomainFamily } from './taskDomains'
import { TASK_DOMAINS } from './taskDomains'

export type RecordDomain = DomainFamily

export interface ReportRecord {
  key: string
  domain: RecordDomain
  id: string
  title: string
  /** 生活圈 = 样区名；目的地调研 = 调研关键词（`query`，缺失回落标题） */
  subject: string
  city: string | null
  checked_at: string
  /** 不可比时为 null（离线估算 / 调研域），绝不伪造 0 分 */
  total_score: number | null
  blindspot_count: number | null
  data_origin: LifeCircleRecord['data_origin'] | null
  /** 列表端点目前不透出此列（`db.py` 的 SELECT 未含 `served_from`），后端补上即自动生效 */
  served_from?: 'cache' | 'nearby_cache'
  degraded?: LifeCircleDegraded | null
  interpolation?: string | null
  /** 仅调研域有：删除确认里要点名会被一并清除的证据量 */
  evidence_count?: number
}

export interface RecordStats {
  /** 可比体检份数（统计块「体检总数」） */
  total: number
  /** 归档里生活圈记录的可见条数（含不可比），供 n/N 口径说明 */
  visibleLcTotal: number
  latestScore: number
  avg: number
  blindspots: number
}

/** 唯一可比性判据：0 分与「不可比(null)」是两件事（见 T5 契约） */
export function isComparableScore(r: Pick<ReportRecord, 'total_score'>): boolean {
  return r.total_score != null && r.total_score > 0
}

/** 排序键：两域时间戳格式不一律（真实态无时区后缀，夹具带 Z），必须解析而非字符串比较 */
export function sortKeyOf(iso: string): number {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? 0 : t
}

export function fmtRecordTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function lcRecordToRow(r: LifeCircleRecord): ReportRecord {
  return {
    key: `lc-${r.id}`,
    domain: 'living_circle',
    id: r.id,
    title: r.title,
    subject: r.scene_name,
    city: r.city || null,
    checked_at: r.checked_at,
    total_score: r.total_score,
    blindspot_count: r.blindspot_count,
    data_origin: r.data_origin,
    degraded: r.degraded ?? null,
    interpolation: r.interpolation,
  }
}

export function researchCardToRow(c: ReportCard): ReportRecord {
  return {
    key: `research-${c.report_id}`,
    domain: 'travel',
    id: c.report_id,
    title: c.title,
    subject: c.query || c.title,
    city: null,
    checked_at: c.created_at,
    total_score: null,
    blindspot_count: null,
    data_origin: null,
    degraded: null,
    interpolation: null,
    evidence_count: c.evidence_count,
  }
}

/**
 * 生活圈归档行（按体检时间倒序）。
 *
 * 取代原 `buildRecordIndex(lc, research)`：那个函数存在的唯一理由是"两域混排一条
 * 列表"，而混排列表正是双 tab 改造要拆掉的形状 —— 目的地 tab 现在是仪表盘，
 * 不再和生活圈共用一份 records。
 */
export function livingCircleRows(records: LifeCircleRecord[]): ReportRecord[] {
  return [...records.map(lcRecordToRow)].sort(
    (a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at),
  )
}

/**
 * `/api/intel` 的概览卡 → 归档行。
 *
 * 调研报告的删除入口在概览表行尾，确认文案要点名会被一并清除的证据量，
 * 所以卡片也要能变成一行记录。注意概览卡的主键叫 `id`、列表卡叫 `report_id`
 * （两份后端契约各叫各的），这里只做映射，不发明第三个名字。
 */
export function intelCardToRow(c: ResearchCard): ReportRecord {
  return {
    key: `research-${c.id}`,
    domain: 'travel',
    id: c.id,
    title: c.title,
    subject: c.query || c.title,
    city: null,
    checked_at: c.created_at,
    total_score: null,
    blindspot_count: null,
    data_origin: null,
    degraded: null,
    interpolation: null,
    evidence_count: c.evidence_count,
  }
}
/** 成员资格由域注册表派生；下表只决定展示顺序（生活圈在前），未列出的族自动追加在尾部 */
const DOMAIN_DISPLAY_ORDER: RecordDomain[] = ['living_circle', 'travel']
const REGISTERED_FAMILIES = [...new Set(Object.values(TASK_DOMAINS).map((d) => d.family))]

export const RECORD_DOMAINS: RecordDomain[] = [
  ...DOMAIN_DISPLAY_ORDER.filter((d) => REGISTERED_FAMILIES.includes(d)),
  ...REGISTERED_FAMILIES.filter((d) => !DOMAIN_DISPLAY_ORDER.includes(d)),
]

export type RecordFilter = RecordDomain

/** 缺省/非法深链的回落域：生活圈是这页的主用途，且它永远有内容可看 */
export const DEFAULT_RECORD_DOMAIN: RecordDomain = 'living_circle'

/**
 * 深链 `?domain=` 归一。
 *
 * 旧值 `'all'` 已随双 tab 改造退场：混排列表是"两域共用一份 records"的形状，
 * 目的地 tab 变成仪表盘后它撑不住了。**显式写了但无效**的值必须响亮回落 ——
 * 静默改写会让失效的分享链接看起来"本来就是这一页"。不带参数是正常入口，不打扰。
 */
export function normalizeRecordFilter(raw: string | null): RecordFilter {
  if ((RECORD_DOMAINS as string[]).includes(raw ?? '')) return raw as RecordDomain
  if (raw !== null) {
    console.warn(
      `[recordIndex] 域参数「${raw}」不是有效域，已回落「${RECORD_DOMAIN_LABEL[DEFAULT_RECORD_DOMAIN]}」` +
        `（可选值：${RECORD_DOMAINS.join(' / ')}；旧链接的 all 已下线）`,
    )
  }
  return DEFAULT_RECORD_DOMAIN
}

/** 归档行的域徽标、过滤 chip 与 tab 条共用同一份展示文案 */
export const RECORD_DOMAIN_LABEL: Record<RecordDomain, string> = {
  living_circle: '生活圈体检',
  travel: '目的地调研',
}

export function filterRecords(rows: ReportRecord[], filter: RecordFilter): ReportRecord[] {
  return rows.filter((r) => r.domain === filter)
}

/* ── 样区分组（报告中心生活圈 tab 的折叠形态）────────────────── */

/**
 * 分组键 = 样区名 + 城市。
 *
 * 只用样区名会把不同城市的同名样区并成一组（真实库里「北京劲松」同时挂着
 * 北京·朝阳 与 昆明市两条），那是错并；城市缺失时单独成组，不猜。
 */
export function groupKeyOf(r: ReportRecord): string {
  return `${r.subject}||${r.city ?? ''}`
}

export interface SampleGroup {
  key: string
  scene: string
  city: string | null
  /** 组内按体检时间倒序：[0] 就是最新一份 */
  rows: ReportRecord[]
  /** 最新一份与最早一份可比评分之差；只有一份、或任一端不可比时为 null（绝不把"没有历史"写成 0 分） */
  scoreDelta: number | null
}

/**
 * 按样区折叠。排序沿用全库口径的时间倒序，再按"组内最新一份"排组，
 * 所以刚体检过的样区一定在最上面。
 */
export function groupBySample(rows: ReportRecord[]): SampleGroup[] {
  const map = new Map<string, ReportRecord[]>()
  for (const r of rows) {
    const k = groupKeyOf(r)
    const bucket = map.get(k)
    if (bucket) bucket.push(r)
    else map.set(k, [r])
  }
  return [...map.entries()]
    .map(([key, list]) => {
      const sorted = [...list].sort((a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at))
      const latest = sorted[0]
      const oldest = sorted[sorted.length - 1]
      const delta =
        sorted.length > 1 && isComparableScore(latest) && isComparableScore(oldest)
          ? Math.round(((latest.total_score ?? 0) - (oldest.total_score ?? 0)) * 10) / 10
          : null
      return {
        key,
        scene: latest.subject,
        city: latest.city,
        rows: sorted,
        scoreDelta: delta,
      }
    })
    .sort((a, b) => sortKeyOf(b.rows[0].checked_at) - sortKeyOf(a.rows[0].checked_at))
}

/**
 * 体检口径统计：只计可比评分，离线估算不参与平均。
 * 无可比记录返回 null（统计带整体不渲染，不得把 null 当 0 计入）。
 */
export function recordStats(rows: ReportRecord[]): RecordStats | null {
  const lc = rows.filter((r) => r.domain === 'living_circle')
  const scored = lc.filter(isComparableScore)
  if (scored.length === 0) return null
  const avg = Math.round(scored.reduce((a, r) => a + (r.total_score ?? 0), 0) / scored.length)
  const latest = [...scored].sort((a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at))[0]
  return {
    total: scored.length,
    visibleLcTotal: lc.length,
    latestScore: latest?.total_score ?? 0,
    avg,
    blindspots: scored.reduce((a, r) => a + (r.blindspot_count ?? 0), 0),
  }
}
