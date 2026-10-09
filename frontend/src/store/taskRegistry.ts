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
  /**
   * 当前这一步的**负责席位 id**（后端 `progress.expert`；演示夹具把它挂在 `message.expert` 上）。
   *
   * 刻意是**可选**：`load()` 是裸 `JSON.parse(...) as Record<string, TaskRecord>`，没有校验也没有
   * 版本迁移 ⇒ 旧的 localStorage 记录在下一次 upsert 之前读出来是 `undefined`。声明成非可选
   * 就是给读方（横幅）一个骗人的签名。
   * 它与 `stage` 必须同源：owner 是 stage 的注脚，分两处存就会出现"阶段已走到 collect、
   * 横幅还挂着 measure 的席位"。
   */
  expert?: string
  startedAt: string
  updatedAt: string
  reportId: string | null
}

interface TaskRegistryState {
  tasks: Record<string, TaskRecord>
  /**
   * 创建或合并更新一条任务（按 taskId 主键）。
   *
   * `expert` 比其余字段多一个 **null** 档：null＝"这一笔明确宣布这一步没有归属"（清掉），
   * 缺省＝"这一笔不碰归属"。只有 SSE 的 progress 写入者有资格发 null —— 见下面合并规则。
   * 这里必须 `Omit` 掉再重声明：`Partial<TaskRecord> & { expert?: string | null }` 会被
   * 交叉成 `(string|undefined) & (string|null|undefined)` ＝ `string | undefined`，
   * 于是发 null 的那一处在 tsc 下直接不通过（vitest 只剥类型，抓不到）。
   */
  upsert: (t: Omit<Partial<TaskRecord>, 'expert'> & { taskId: string; expert?: string | null }) => void
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
          // owner 的**唯一权威是 SSE 那一帧**，不是"这一笔有没有带 stage"。
          // 三种笔形分开对待：
          //   `expert: null`  ⇒ 这一帧明确没有归属 ⇒ 清掉。后端 C2 对被缓存跳过的五步就是
          //                     刻意不发 `expert`（那五步什么都没算），沿用旧值等于替没发生的事举证。
          //   `expert: 'L…'`  ⇒ 落这个值。
          //   **压根不带 expert 键** ⇒ 不碰。这条不是偷懒：`TaskFloatBar` 每 3s 轮
          //   `/api/tasks/{id}/status` 并 upsert 一份**带 stage 而不带归属**的快照（那个端点没有
          //   这一位），若按"带 stage 就重定归属"处理，横幅那行会被轮询节奏反复抹掉。
          expert:
            t.expert === null ? undefined : (t.expert ?? prev?.expert),
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
