/**
 * 信源类别注册表的前端适配（计划 v3 §二 G0 的展示面）。
 *
 * - 真实态：GET /api/source-kinds（真相源 = 后端 `app/core/source_type.py` 注册表）；
 * - 演示态/离线/端点异常：回落 `scripts/gen-source-kinds-fixture.mjs` 生成的
 *   checked-in 快照（**禁止手抄**，形状与逐字段一致性由测试守卫）。
 *
 * 为什么要有快照而不是"各组件自己写一份 id→中文"：`VEvidenceFeed` 历史上就抄了
 * 一张 7 项映射表，于是新类别 `user_supplied` 上屏显示成裸 key，而且没有任何东西会变红。
 * 标签的真相源只能有一个。
 *
 * `kindLabel` 是同步读快照：证据卡是纯展示组件，不能为了一个标签去等一次网络；
 * 需要"以后端为准"的调用方用 `fetchSourceKinds()` / `useSourceKinds()`。
 */
import { isFixtureMode } from '../store/dataModeStore'
import type { SourceKindView } from '../types'
import snapshot from '../mocks/sourceKinds.json'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 视图形状与 `types.SourceKindView` 同一份（不在这里另声明一遍，防两处漂移）。 */
export type SourceKindOption = SourceKindView

function isValidKind(x: unknown): x is SourceKindOption {
  if (typeof x !== 'object' || x === null) return false
  const o = x as Record<string, unknown>
  return typeof o.id === 'string' && typeof o.label === 'string' && typeof o.in_stats === 'boolean'
}

/** 快照回落（模块级常量；形状由 sourceKindsClient.test.ts 钉住）。 */
export const SOURCE_KINDS_FALLBACK: SourceKindOption[] = Array.isArray(
  (snapshot as { kinds?: unknown }).kinds,
)
  ? ((snapshot as { kinds: unknown[] }).kinds.filter(isValidKind))
  : []

const FALLBACK_LABELS: Record<string, string> = Object.fromEntries(
  SOURCE_KINDS_FALLBACK.map((k) => [k.id, k.label]),
)

/** 同步取类别中文名；未登记类别回落 key 本身（与后端 `kind_label` 同一口径，不塌成空串）。 */
export function kindLabel(key: string): string {
  return FALLBACK_LABELS[key] ?? key
}

let cache: SourceKindOption[] | null = null

/** 拉类别视图；任何失败路径都不抛（回落快照），保证调用方总能渲染。 */
export async function fetchSourceKinds(): Promise<SourceKindOption[]> {
  if (isFixtureMode()) return SOURCE_KINDS_FALLBACK
  if (cache) return cache
  try {
    const r = await fetch(`${API_BASE}/api/source-kinds`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data: unknown = await r.json()
    const kinds = (data as { kinds?: unknown })?.kinds
    if (Array.isArray(kinds) && kinds.length > 0 && kinds.every(isValidKind)) {
      cache = kinds
      return cache
    }
    throw new Error('载荷形状非法')
  } catch (e) {
    // 可观测：真实态端点不可达时显式留痕一次（不静默吞），界面仍用快照渲染
    console.warn('[sourceKinds] 信源类别注册表拉取失败，回落本地快照', e)
    return SOURCE_KINDS_FALLBACK
  }
}

/** 测试 / 切换数据模式后清缓存用。 */
export function __resetSourceKindsCache(): void {
  cache = null
}
