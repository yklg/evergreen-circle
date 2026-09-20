/* 流水线视图协议：任务类型(kind) → 展示形态描述符。
 *
 * 结构性防线——把「任务类型 → 在哪渲染 / 用什么流」从事件形状的隐式推断提升为
 * 显式登记。未来新增流水线只需在此登记，工作台不再因新协议而空白。
 */
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

const KNOWLEDGE_KINDS: Record<string, TaskView> = {
  research: { role: 'research', renderWorkspace: true, forceFixture: false, hint: '' },
  travel_guide: { role: 'research', renderWorkspace: true, forceFixture: false, hint: '' },
  travel_assess: { role: 'research', renderWorkspace: true, forceFixture: false, hint: '' },
  living_circle: {
    role: 'life_circle',
    renderWorkspace: false,
    forceFixture: false,
    hint: '生活圈体检请前往「生活圈」页查看进度与报告。',
  },
}

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

/** purpose → kind 归一化（与后端 main.py post_task 映射一致）。 */
export function kindForPurpose(purpose: string): string {
  if (purpose === 'guide') return 'travel_guide'
  if (purpose === 'assess') return 'travel_assess'
  return 'research'
}

/**
 * 任务 → 落地路由（单一事实源，供悬浮条 / 侧栏「进行中任务」共用）。
 * 生活圈任务回落生活圈页（带 taskId 恢复 SSE），其余任务进工作台流水线。
 * kind 变更只需改这里，避免悬浮条 / 侧栏各写一次 if。
 */
export function resolveTaskLanding(kind: string | null | undefined, taskId: string): string {
  if (kind === 'living_circle') return `/life-circle/kaili?taskId=${taskId}`
  return `/workspace/${taskId}`
}