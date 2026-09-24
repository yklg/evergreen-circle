/**
 * 任务域元数据单一声明（融合决策 4）——「旅游调研 / 生活圈体检」双域的
 * 类型(type) ↔ 任务路由(kind) ↔ 演示方言(demoPurpose) ↔ 落地页/示例/名册
 * 唯一注册表。
 *
 * 设计纪律：
 * - 按**族（family）**建模：旅游族 guide/assessment 共享问卷与落地行为，
 *   落地解析只按 family × dataMode 分支，不按类型写 if；新增旅游类型只需加一行。
 * - **写权威、读宽容**：新代码写出一律用权威 type（guide/assessment/living_circle）；
 *   旧方言（assess/travel_guide/travel_assess）只允许在本模块的别名归一里出现。
 * - 演示回放器（mocks/researchStream）历史上只认 guide/assess，故 demoPurpose
 *   是注册表到回放器的唯一桥；openClarifyStream 无 fixture 分支，演示态旅游任务
 *   必须直落 /workspace（真实态才走 /clarify）。
 */
import type { DataMode } from '../store/dataModeStore'

export type DomainFamily = 'travel' | 'living_circle'
/** 权威旅游调研类型（与后端 research_types 注册表逐字一致） */
export type ResearchType = 'guide' | 'assessment'
/** 权威域类型全集（含生活圈） */
export type DomainType = ResearchType | 'living_circle'
export type ExpertDomain = 'travel' | 'living_circle'
export type ExamplesKey = 'travelGuide' | 'travelAssess' | 'livingCircle'

export interface DomainDescriptor {
  /** 权威类型 key（POST /api/tasks 的 type；落 task meta _type） */
  type: DomainType
  /** 业务族：落地/问卷/工作台角色按族解析 */
  family: DomainFamily
  /** 任务路由 kind（taskRegistry / 后端 KIND_PIPELINES 闭集） */
  kind: string
  /** 演示回放方言（喂 replayResearchStream）；生活圈无此桥 */
  demoPurpose?: string
  /** 真实态提交后是否先进澄清问卷（旅游 true；生活圈直达地图 false） */
  clarifyRequired: boolean
  /** 首页示例集槽位键 */
  examplesKey: ExamplesKey
  /** 输入框提示文案 */
  queryHint: string
  /** 专家名册域（C6 专家墙） */
  expertDomain: ExpertDomain
}

const guide: DomainDescriptor = {
  type: 'guide',
  family: 'travel',
  kind: 'travel_guide',
  demoPurpose: 'guide',
  clarifyRequired: true,
  examplesKey: 'travelGuide',
  queryHint: '想去哪里玩、几天、和谁一起？例如：帮我做一份大理 5 天亲子游攻略，含路线与住宿选型',
  expertDomain: 'travel',
}

const assessment: DomainDescriptor = {
  type: 'assessment',
  family: 'travel',
  kind: 'travel_assess',
  demoPurpose: 'assess',
  clarifyRequired: true,
  examplesKey: 'travelAssess',
  queryHint: '评估哪几个城市或区域？例如：评估成都和杭州哪个更适合长期居住',
  expertDomain: 'travel',
}

const livingCircle: DomainDescriptor = {
  type: 'living_circle',
  family: 'living_circle',
  kind: 'living_circle',
  clarifyRequired: false,
  examplesKey: 'livingCircle',
  queryHint: '输入中心点地名（区 / 街道 / 小区 / 景区），例如：凯里老街、北京劲松',
  expertDomain: 'living_circle',
}

/** 域注册表（按权威 type 索引）。新增业务类型 = 在此登记一行。 */
export const TASK_DOMAINS: Record<DomainType, DomainDescriptor> = {
  guide,
  assessment,
  living_circle: livingCircle,
}

/** 生活圈运行中任务落地路由前缀（TaskFloatBar/VSidebar 单一来源，勿在别处复制）。 */
export const LC_TASK_LANDING_BASE = '/life-circle/kaili'

/**
 * 旧方言 → 权威 type 的只读归一表。
 * 包含历史 localStorage / 旧 bundle 出现过的全部别名：
 * assess / travel_guide / travel_assess / guide / living_circle。
 */
const TYPE_ALIASES: Record<string, DomainType> = {
  guide: 'guide',
  assess: 'assessment',
  travel_guide: 'guide',
  travel_assess: 'assessment',
  living_circle: 'living_circle',
}

/**
 * 归一任意历史输入到权威 type。
 * - 权威 key / 已登记别名 → 返回权威 type；
 * - 未登记值：开发期响亮失败（注册封闭，避免新类型静默走错流水线）。
 *   运行期外部脏数据需回落的调用点（如旧记录读取）应先自行判空/白名单。
 */
export function resolveType(input: string | null | undefined): DomainType {
  const key = String(input ?? '').trim()
  if (key in TASK_DOMAINS) return key as DomainType
  if (key in TYPE_ALIASES) return TYPE_ALIASES[key]
  throw new Error(`未登记的任务类型 ${JSON.stringify(key)}：请在 lib/taskDomains.ts 登记后再使用`)
}

/** 与 resolveType 同源但不抛错：未登记回落默认类型（供只能容错的读层）。 */
export function resolveTypeOr(input: string | null | undefined, fallback: DomainType): DomainType {
  try {
    return resolveType(input)
  } catch {
    return fallback
  }
}

export function domainOf(type: DomainType | string): DomainDescriptor {
  return TASK_DOMAINS[resolveType(type)]
}

export function familyOf(type: DomainType | string): DomainFamily {
  return domainOf(type).family
}

/** 权威 type → 任务 kind。 */
export function kindOfType(type: DomainType | string): string {
  return domainOf(type).kind
}

/** 任务 kind → 族（含历史通用 kind 'research' → travel；未登记默认 travel 工作台角色）。 */
export function familyOfKind(kind: string | null | undefined): DomainFamily {
  const k = String(kind ?? '')
  if (k === 'living_circle') return 'living_circle'
  const hit = Object.values(TASK_DOMAINS).find((d) => d.kind === k)
  return hit ? hit.family : 'travel'
}

/**
 * 演示 purpose 方言 → kind（供 api.ts fixture 分流保持旧行为）：
 * guide→travel_guide、assess→travel_assess；未知 → 通用 research。
 */
export function kindForDemoPurpose(purpose: string): string {
  const key = String(purpose ?? '').trim()
  if (key === 'guide' || key === 'travel_guide') return 'travel_guide'
  if (key === 'assess' || key === 'travel_assess') return 'travel_assess'
  return 'research'
}

/** 权威 type → 演示回放方言（旅游两类型；生活圈返回 ''，其回放走 lc-* 通道）。 */
export function demoPurposeOf(type: DomainType | string): string {
  return domainOf(type).demoPurpose ?? ''
}

/**
 * 首页提交后的落地路由（初始发起场景，与任务恢复场景的 resolveTaskLanding 不同）：
 * - travel + live → /clarify/:taskId（SSE v2 问卷）
 * - travel + fixture → /workspace/:taskId（问卷 SSE 无 fixture 分支，演示态直进工作台回放）
 * - living_circle → /life-circle/custom（中心点在地图页确认）
 */
export function submitLanding(type: DomainType | string, mode: DataMode, taskId: string): string {
  const d = domainOf(type)
  if (d.family === 'living_circle') return '/life-circle/custom'
  return mode === 'fixture' ? `/workspace/${taskId}` : `/clarify/${taskId}`
}

/**
 * 运行中任务恢复落地（悬浮条/侧栏点击）：生活圈回地图带 taskId 续 SSE，其余进工作台。
 * 与 submitLanding 的差异：此处不含 clarify（问卷只在首次发起时走一次）。
 */
export function taskLanding(kind: string | null | undefined, taskId: string): string {
  return familyOfKind(kind) === 'living_circle'
    ? `${LC_TASK_LANDING_BASE}?taskId=${taskId}`
    : `/workspace/${taskId}`
}
