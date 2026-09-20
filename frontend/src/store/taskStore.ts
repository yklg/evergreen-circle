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
  claim?: Claim
  reason?: string
  diff?: { before: string; after: string }
  metrics_before?: Record<string, number>
  metrics_after?: Record<string, number>
  issues_resolved?: number
  envelope?: { sender?: string; receiver?: string; task_type?: string; payload?: unknown; issues?: unknown[] }
  mode?: string
}

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

  reset: (taskId: string, query: string) => void
  ingest: (type: SSEEventType, data: unknown) => void
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

export const useTaskStore = create<TaskState>((set, get) => ({
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

  reset: (taskId, query) =>
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
    }),

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
        set({ thoughts: [...s.thoughts, d as unknown as ThoughtItem] })
        return
      }
      case 'message': {
        const msg = d as unknown as StreamMessage
        const patch: Partial<TaskState> = { messages: [...s.messages, msg] }
        if (msg.kind === 'team' && msg.members) patch.teamMembers = msg.members
        if (msg.kind === 'claim' && msg.claim)
          patch.claims = [...s.claims, msg.claim]
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
        set({ running: false, finished: true, reportId: (d.reportId as string) ?? s.reportId })
        return
      }
      case 'error': {
        set({ error: (d.message as string) ?? '发生未知错误', running: false })
        return
      }
    }
  },
}))
