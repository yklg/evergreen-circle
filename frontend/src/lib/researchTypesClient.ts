/**
 * 调研类型卡数据适配（首页 C1/C2 单一数据源）。
 *
 * - 真实态：GET /api/research-types（真相源 = 后端 research_types 注册表）；
 * - 演示态/离线/端点异常：回落 scripts/gen-research-types-fixture.mjs 生成的
 *   checked-in 快照（禁止手抄，契约测试钉形状）。
 *
 * 首页类型卡文案只能来自本模块，不得在组件里写死第二份。
 */
import { isFixtureMode } from '../store/dataModeStore'
import snapshot from '../mocks/researchTypes.json'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export interface ResearchTypeOption {
  key: string
  label: string
  subtitle: string
}

function isValidOption(x: unknown): x is ResearchTypeOption {
  if (typeof x !== 'object' || x === null) return false
  const o = x as Record<string, unknown>
  return typeof o.key === 'string' && typeof o.label === 'string' && typeof o.subtitle === 'string'
}

/** 快照回落（模块级常量；形状由 researchTypesClient.test.ts 钉住）。 */
export const RESEARCH_TYPES_FALLBACK: ResearchTypeOption[] = Array.isArray(
  (snapshot as { types?: unknown }).types,
)
  ? ((snapshot as { types: unknown[] }).types.filter(isValidOption))
  : []

let cache: ResearchTypeOption[] | null = null

/** 拉首页类型卡选项；任何失败路径都不抛（回落快照），保证首页可渲染。 */
export async function fetchResearchTypes(): Promise<ResearchTypeOption[]> {
  if (isFixtureMode()) return RESEARCH_TYPES_FALLBACK
  if (cache) return cache
  try {
    const r = await fetch(`${API_BASE}/api/research-types`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data: unknown = await r.json()
    if (Array.isArray(data) && data.length > 0 && data.every(isValidOption)) {
      cache = data
      return data
    }
    throw new Error('载荷形状非法')
  } catch (e) {
    // 可观测：真实态端点不可达时显式留痕一次（不静默吞），页面仍用快照渲染
    console.warn('[researchTypes] 类型注册表拉取失败，回落本地快照', e)
    return RESEARCH_TYPES_FALLBACK
  }
}

/** 测试/切换数据模式后清缓存用。 */
export function __resetResearchTypesCache(): void {
  cache = null
}
