import { create } from 'zustand'

/* 进行中任务的一等实体注册表（前端侧）。

把「运行中的任务」从 WorkspacePage 的局部状态提升为全局持久化实体：
- localStorage 持久化（verda.tasks.v1），刷新/重开浏览器不丢；
- 全局共享，悬浮条与侧栏入口都能读，不依赖 WorkspacePage 是否存在；
- 后端常驻执行后，断连/返回都不影响任务本身，注册表只镜像其状态。
*/

export type TaskStatus = 'running' | 'done' | 'failed'

export interface TaskRecord {
  taskId: string
  query: string
  kind: string
  purpose: string
  status: TaskStatus
  percent: number
  evidence_count: number
  stage: string
  startedAt: string
  updatedAt: string
  reportId: string | null
}

interface TaskRegistryState {
  tasks: Record<string, TaskRecord>
  /** 创建或合并更新一条任务（按 taskId 主键）。 */
  upsert: (t: Partial<TaskRecord> & { taskId: string }) => void
  markDone: (taskId: string, reportId: string) => void
  markFailed: (taskId: string, error?: string) => void
  remove: (taskId: string) => void
}

const LS_KEY = 'verda.tasks.v1'

function load(): Record<string, TaskRecord> {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as Record<string, TaskRecord>) : {}
  } catch {
    return {}
  }
}
function save(value: Record<string, TaskRecord>) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(value))
  } catch {
    /* ignore quota */
  }
}

export const useTaskRegistry = create<TaskRegistryState>((set) => ({
  tasks: load(),

  upsert: (t) =>
    set((s) => {
      const prev = s.tasks[t.taskId]
      const next: Record<string, TaskRecord> = {
        ...s.tasks,
        [t.taskId]: {
          taskId: t.taskId,
          query: t.query ?? prev?.query ?? '',
          kind: t.kind ?? prev?.kind ?? 'research',
          purpose: t.purpose ?? prev?.purpose ?? '',
          status: t.status ?? prev?.status ?? 'running',
          percent: t.percent ?? prev?.percent ?? 0,
          evidence_count: t.evidence_count ?? prev?.evidence_count ?? 0,
          stage: t.stage ?? prev?.stage ?? '',
          startedAt: t.startedAt ?? prev?.startedAt ?? new Date().toISOString(),
          updatedAt: t.updatedAt ?? new Date().toISOString(),
          reportId: t.reportId ?? prev?.reportId ?? null,
        },
      }
      save(next)
      return { tasks: next }
    }),

  markDone: (taskId, reportId) =>
    set((s) => {
      const prev = s.tasks[taskId]
      if (!prev) return s
      const next = { ...s.tasks, [taskId]: { ...prev, status: 'done' as const, reportId, updatedAt: new Date().toISOString() } }
      save(next)
      return { tasks: next }
    }),

  markFailed: (taskId, error) =>
    set((s) => {
      const prev = s.tasks[taskId]
      if (!prev) return s
      const next = { ...s.tasks, [taskId]: { ...prev, status: 'failed' as const, updatedAt: new Date().toISOString() } }
      void error
      save(next)
      return { tasks: next }
    }),

  remove: (taskId) =>
    set((s) => {
      if (!s.tasks[taskId]) return s
      const next = { ...s.tasks }
      delete next[taskId]
      save(next)
      return { tasks: next }
    }),
}))

/** 取进行中的任务（按 updatedAt 倒序），供悬浮条/侧栏展示。 */
export function selectRunning(s: TaskRegistryState): TaskRecord[] {
  return Object.values(s.tasks)
    .filter((t) => t.status === 'running')
    .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
}
