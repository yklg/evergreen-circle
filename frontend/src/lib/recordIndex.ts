/**
 * 归档记录索引 —— 列表层的单一事实源。
 *
 * 详情层的等价物是后端 `get_report`（reports + living_circle_reports 双表兜底）；
 * 本文件是它在列表层的对应物：两域记录归一成一个判别式行模型，供报告中心渲染。
 * 后端将来提供统一列表端点时，只替换 `lcRecordToRow` / `researchCardToRow` 的输入源。
 */
import type { LifeCircleDegraded, LifeCircleRecord, ReportCard } from '../types'
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

export function buildRecordIndex(
  lcRecords: LifeCircleRecord[],
  researchCards: ReportCard[],
): ReportRecord[] {
  return [...lcRecords.map(lcRecordToRow), ...researchCards.map(researchCardToRow)].sort(
    (a, b) => sortKeyOf(b.checked_at) - sortKeyOf(a.checked_at),
  )
}

export type RecordFilter = RecordDomain | 'all'

/** 成员资格由域注册表派生；下表只决定展示顺序（生活圈在前），未列出的族自动追加在尾部 */
const DOMAIN_DISPLAY_ORDER: RecordDomain[] = ['living_circle', 'travel']
const REGISTERED_FAMILIES = [...new Set(Object.values(TASK_DOMAINS).map((d) => d.family))]

export const RECORD_DOMAINS: RecordDomain[] = [
  ...DOMAIN_DISPLAY_ORDER.filter((d) => REGISTERED_FAMILIES.includes(d)),
  ...REGISTERED_FAMILIES.filter((d) => !DOMAIN_DISPLAY_ORDER.includes(d)),
]

export function normalizeRecordFilter(raw: string | null): RecordFilter {
  return (RECORD_DOMAINS as string[]).includes(raw ?? '') ? (raw as RecordDomain) : 'all'
}

/** 归档行的域徽标与过滤 chip 共用同一份展示文案 */
export const RECORD_DOMAIN_LABEL: Record<RecordDomain, string> = {
  living_circle: '生活圈体检',
  travel: '目的地调研',
}

export function filterRecords(rows: ReportRecord[], filter: RecordFilter): ReportRecord[] {
  return filter === 'all' ? rows : rows.filter((r) => r.domain === filter)
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
