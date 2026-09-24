/* 流水线视图协议：任务类型(kind) → 展示形态描述符。
 *
 * 结构性防线——把「任务类型 → 在哪渲染 / 用什么流」从事件形状的隐式推断提升为
 * 显式登记。域元数据（type/kind/落地/方言）的唯一真相源在 ./taskDomains；
 * 本文件只负责「kind → 工作台展示角色 TaskView」的派生视图，供 WorkspacePage 使用。
 */
import { TASK_DOMAINS, familyOfKind, kindForDemoPurpose, taskLanding } from './taskDomains'

export interface TaskView {
  /** 展示角色：research=角色专家流水线（工作台三栏）；life_circle=生活圈页 */
  role: 'research' | 'life_circle' | 'unknown'
  /** 是否应在工作台呈现角色流水线（false → 显示业务引导而非空白） */
  renderWorkspace: boolean
  /** 用 forceFixture === true 时，前端强制走内置演示流或占位（无可用数据源） */
  forceFixture: boolean
  /** 非工作台角色时的业务引导文案（替代空白） */
  hint: string
}

const RESEARCH_VIEW: TaskView = { role: 'research', renderWorkspace: true, forceFixture: false, hint: '' }
const LIFE_CIRCLE_VIEW: TaskView = {
  role: 'life_circle',
  renderWorkspace: false,
  forceFixture: false,
  hint: '生活圈体检请前往「生活圈」页查看进度与报告。',
}

function viewForFamily(family: 'travel' | 'living_circle'): TaskView {
  return family === 'living_circle' ? LIFE_CIRCLE_VIEW : RESEARCH_VIEW
}

/**
 * kind → TaskView 从 taskDomains 注册表派生：
 * 注册表里每个 kind 按族得一个视图；历史通用 kind 'research' 显式登记为旅游族；
 * brief/refine 等旧 kind 未登记 → normalizeKind 回落 research（保持既有行为）。
 */
const KNOWLEDGE_KINDS: Record<string, TaskView> = (() => {
  const out: Record<string, TaskView> = { research: RESEARCH_VIEW }
  for (const d of Object.values(TASK_DOMAINS)) {
    out[d.kind] = viewForFamily(d.family)
  }
  return out
})()

/** 归一化未知 kind（历史/直达/跨设备场景）到可控默认。 */
function normalizeKind(kind?: string | null): string {
  const k = kind || ''
  if (k in KNOWLEDGE_KINDS) return k
  return 'research'
}

/** 任务类型 → 展示形态。未知/空 → research（默认工作台角色流水线），避免直达空白。 */
export function taskViewProvider(kind?: string | null): TaskView {
  return KNOWLEDGE_KINDS[normalizeKind(kind)]
}

/** purpose → kind 归一（派生自 taskDomains 三方映射；供 api.ts fixture 分流）。 */
export function kindForPurpose(purpose: string): string {
  return kindForDemoPurpose(purpose)
}

/**
 * 任务 → 落地路由（单一事实源 taskDomains.taskLanding，供悬浮条 / 侧栏共用）。
 */
export function resolveTaskLanding(kind: string | null | undefined, taskId: string): string {
  return taskLanding(kind, taskId)
}

// familyOfKind 透出给需要按 kind 判族但不需要完整 TaskView 的消费方
export { familyOfKind }
