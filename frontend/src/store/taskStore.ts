import { create } from 'zustand'
import type {
  ChartSpec,
  Claim,
  DAGNode,
  Evidence,
  ProgressInfo,
  SSEEventType,
  ThoughtItem,
  TraceSpan,
} from '../types'

export interface ImageItem {
  src: string
  alt?: string
  source_url?: string
  brand?: string
}

export interface StreamMessage {
  id: string
  kind: string
  expert?: string
  text?: string
  members?: string[]
  /** 组队降级原因：llm_error | llm_output_unusable | spec_violation；空表示真组队 */
  degraded?: string
  /** 指派产出被归一的痕迹（丢非法指派 / lead 悬空等），供决策回放核对 */
  repairs?: string[]
  claim?: Claim
  reason?: string
  diff?: { before: string; after: string }
  metrics_before?: Record<string, number>
  metrics_after?: Record<string, number>
  issues_resolved?: number
  envelope?: { sender?: string; receiver?: string; task_type?: string; payload?: unknown; issues?: unknown[] }
  mode?: string
}

// 节点集以 skip 侧权威契约为准（sentiment 段），与 `mocks/researchStream` 及活跃
// `taskStore.test.ts` 同构；旅游引擎的 analyze/spots 节点形态差异属另一条待决漂移，不在本片翻动。
const BASE_NODES: DAGNode[] = [
  { id: 'intake', label: '需求理解', status: 'idle' },
  { id: 'orchestrator', label: '编排派遣', status: 'idle' },
  { id: 'collect', label: '证据采集', status: 'idle' },
  { id: 'sentiment', label: '聚合口碑舆情', status: 'idle' },
  { id: 'write', label: '报告撰写', status: 'idle' },
  { id: 'audit', label: '质检审裁', status: 'idle' },
  { id: 'done', label: '签发交付', status: 'idle' },
]

interface TaskState {
  taskId: string | null
  query: string
  running: boolean
  finished: boolean
  reportId: string | null
  nodes: DAGNode[]
  activeNode: string | null
  thoughts: ThoughtItem[]
  messages: StreamMessage[]
  evidences: Evidence[]
  images: ImageItem[]
  charts: ChartSpec[]
  claims: Claim[]
  traces: TraceSpan[]
  progress: ProgressInfo
  teamMembers: string[]
  error: string | null
  // 目的地来自兜底链（计划降级）：只作温和横幅，与 error 通道无关；
  // 与澄清问卷的 destinations_fallback 分属两条流，各自独立（见 lib/destinationFallbackCopy）
  planFallback: boolean
  // 专家团队来自规则兜底（未经 LLM 动态指派）：取值 llm_error | llm_output_unusable |
  // spec_violation，空串/null 表示真组队。与 planFallback 同属「运行流降级」，
  // 不进报告 payload —— 报告是历史快照，降级只描述这一次怎么跑出来的。
  dispatchDegraded: string | null

  reset: (taskId: string, query: string) => void
  ingest: (type: SSEEventType, data: unknown) => void
  /** 冲刷派遣队列余量（订阅方卸载时调用，保证不丢帧）。 */
  flushDispatchQueue: () => void
}

const initProgress: ProgressInfo = {
  percent: 0,
  evidence_count: 0,
  token_used: 0,
  stage: 'intake',
}

/* SSE 下发的是动态 JSON，统一收敛成可索引对象再按事件类型断言 */
type LooseRecord = Record<string, unknown>
function asObj(d: unknown): LooseRecord {
  return (d ?? {}) as LooseRecord
}

/** 派遣帧逐条出场间隔（F2）；仅 setTimeout 驱动（fake timers 可测，禁用 performance.now 基准）。 */
export const DISPATCH_STAGGER_MS = 500

export const useTaskStore = create<TaskState>((set, get) => {
  // ── dispatch 节流队列（F2）──────────────────────────────
  // 只对「本次会话实时新增」的 kind=dispatch thought 帧排队逐条出场；
  // 回放帧（后端 subscribe 给 snapshot 打的 data.replay 标记）直刷不排队；
  // 终态（done/error）与卸载冲刷余量，reset 丢弃并清定时器。
  let dispatchBuf: ThoughtItem[] = []
  let pumpTimer: ReturnType<typeof setTimeout> | null = null

  const pushThought = (t: ThoughtItem) =>
    set((s) => ({ thoughts: [...s.thoughts, t] }))

  const stopPump = () => {
    if (pumpTimer !== null) {
      clearTimeout(pumpTimer)
      pumpTimer = null
    }
  }

  const tick = () => {
    pumpTimer = null
    const next = dispatchBuf.shift()
    if (next) pushThought(next)
    if (dispatchBuf.length > 0) pumpTimer = setTimeout(tick, DISPATCH_STAGGER_MS)
  }

  const enqueueDispatch = (t: ThoughtItem) => {
    if (pumpTimer === null && dispatchBuf.length === 0) {
      pushThought(t) // 首条立现，其后每 ~500ms 出队一条
      pumpTimer = setTimeout(tick, DISPATCH_STAGGER_MS)
      return
    }
    dispatchBuf.push(t)
    if (pumpTimer === null) pumpTimer = setTimeout(tick, DISPATCH_STAGGER_MS)
  }

  const flushDispatch = () => {
    stopPump()
    const rest = dispatchBuf
    dispatchBuf = []
    for (const t of rest) pushThought(t)
  }

  return {
  taskId: null,
  query: '',
  running: false,
  finished: false,
  reportId: null,
  nodes: BASE_NODES.map((n) => ({ ...n })),
  activeNode: null,
  thoughts: [],
  messages: [],
  evidences: [],
  images: [],
  charts: [],
  claims: [],
  traces: [],
  progress: { ...initProgress },
  teamMembers: [],
  error: null,
  planFallback: false,
  dispatchDegraded: null,

  reset: (taskId, query) => {
    stopPump()
    dispatchBuf = []
    set({
      taskId,
      query,
      running: true,
      finished: false,
      reportId: null,
      nodes: BASE_NODES.map((n) => ({ ...n })),
      activeNode: null,
      thoughts: [],
      messages: [],
      evidences: [],
      images: [],
      charts: [],
      claims: [],
      traces: [],
      progress: { ...initProgress },
      teamMembers: [],
      error: null,
      planFallback: false,
      dispatchDegraded: null,
    })
  },

  ingest: (type, data) => {
    const d = asObj(data)
    const s = get()
    switch (type) {
      case 'node_update': {
        if (Array.isArray(d.nodes)) {
          set({ nodes: d.nodes as DAGNode[] })
          return
        }
        const node = d.node as string
        const status = d.status as DAGNode['status']
        const expert = d.expert as string | undefined
        const nodes = s.nodes.map((n) =>
          n.id === node ? { ...n, status, expert: expert ?? n.expert } : n,
        )
        set({ nodes, activeNode: status === 'working' ? node : s.activeNode })
        return
      }
      case 'thought': {
        const { replay, ...t } = d as unknown as ThoughtItem & { replay?: boolean }
        if (t.kind === 'dispatch' && !replay) {
          enqueueDispatch(t as ThoughtItem)
          return
        }
        set({ thoughts: [...s.thoughts, t as ThoughtItem] })
        return
      }
      case 'message': {
        const msg = d as unknown as StreamMessage
        const patch: Partial<TaskState> = { messages: [...s.messages, msg] }
        if (msg.kind === 'team' && msg.members) patch.teamMembers = msg.members
        if (msg.kind === 'claim' && msg.claim)
          patch.claims = [...s.claims, msg.claim]
        if (msg.kind === 'plan_fallback') patch.planFallback = true
        if (msg.kind === 'team' && msg.degraded) patch.dispatchDegraded = msg.degraded
        set(patch)
        return
      }
      case 'evidence': {
        set({ evidences: [...s.evidences, d as unknown as Evidence] })
        return
      }
      case 'image': {
        set({ images: [...s.images, d as unknown as ImageItem] })
        return
      }
      case 'chart': {
        set({ charts: [...s.charts, d as unknown as ChartSpec] })
        return
      }
      case 'progress': {
        set({ progress: d as unknown as ProgressInfo })
        return
      }
      case 'trace': {
        set({ traces: [...s.traces, d as unknown as TraceSpan] })
        return
      }
      case 'report_ready': {
        set({ reportId: d.reportId as string })
        return
      }
      case 'done': {
        flushDispatch() // 终态冲刷余量：done 前所有派遣气泡必须已上屏
        set({ running: false, finished: true, reportId: (d.reportId as string) ?? s.reportId })
        return
      }
      case 'error': {
        flushDispatch()
        set({ error: (d.message as string) ?? '发生未知错误', running: false })
        return
      }
    }
  },

  flushDispatchQueue: () => flushDispatch(),
  }
})
