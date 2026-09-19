import type {
  CreateTaskResp,
  ClarifySSEHandlers,
  ClarifySSEEventType,
  DashboardStats,
  EvidenceQueryResp,
  Expert,
  ExpertWorkload,
  LifeCircleCompare,
  LifeCircleMode,
  LifeCircleRecord,
  PingLLMResp,
  PrefsResp,
  PrefsValues,
  Report,
  ReportCard,
  ReportSection,
  SaveSettingsResp,
  SSEEventType,
  SettingsResp,
  SettingsValues,
  Subscription,
  TraceSpan,
} from '../types'
import { USE_MOCK, LC_DATA_MODE } from '../mocks/livingCircleMock'
import { getLivingCircleReportMock } from '../mocks/livingCircleReports'
import { replayLivingCircleStream } from '../mocks/livingCircleStream'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function safeJson<T>(path: string, init?: RequestInit, fallback?: T): Promise<T> {
  try {
    const r = await fetch(`${API_BASE}${path}`, init)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return (await r.json()) as T
  } catch (e) {
    if (fallback !== undefined) return fallback
    throw e
  }
}

/* 48 专家：优先后端，失败回退本地 JSON（绝不白屏） */
export async function fetchExperts(): Promise<Expert[]> {
  try {
    const r = await fetch(`${API_BASE}/api/experts`)
    if (r.ok) {
      const data = await r.json()
      if (Array.isArray(data) && data.length) return data
      if (data?.experts?.length) return data.experts
    }
  } catch {
    /* fall through */
  }
  const local = await fetch('/assets/experts.json')
  return (await local.json()) as Expert[]
}

/* ── 模型配置 ─────────────────────────────────────────── */

/** 读取运行时配置（密钥已脱敏）。后端不可用时返回 null，由页面显示降级提示。 */
export async function fetchSettings(): Promise<SettingsResp | null> {
  try {
    const r = await fetch(`${API_BASE}/api/settings`)
    if (!r.ok) return null
    return (await r.json()) as SettingsResp
  } catch {
    return null
  }
}

/** 保存配置覆盖。密钥传空串 = 保留原值。校验失败抛带 errors 的 Error。 */
export async function saveSettings(patch: SettingsValues): Promise<SaveSettingsResp> {
  const r = await fetch(`${API_BASE}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patch }),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    // 422 整包校验失败：detail.errors 为 { 字段: 错误信息 }
    const errors = (data as { detail?: { errors?: Record<string, string> } })?.detail?.errors
    const msg = errors
      ? Object.entries(errors)
          .map(([k, v]) => `${k}: ${v}`)
          .join('\n')
      : `保存失败（HTTP ${r.status}）`
    const err = new Error(msg) as Error & { fieldErrors?: Record<string, string> }
    err.fieldErrors = errors
    throw err
  }
  return data as SaveSettingsResp
}

/** 连接测试：调 /api/llm/ping 验证当前 Key 是否可用。 */
export async function pingLLM(): Promise<PingLLMResp> {
  try {
    const r = await fetch(`${API_BASE}/api/llm/ping`)
    return (await r.json()) as PingLLMResp
  } catch (e) {
    return { ok: false, message: String(e) }
  }
}

export async function createTask(query: string, mode: string = 'deep', model?: string | null): Promise<CreateTaskResp> {
  return safeJson<CreateTaskResp>(
    '/api/tasks',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode, model: model ?? null }),
    },
    { taskId: `demo-${Date.now()}` },
  )
}

/* ── 生活圈体检（M3 真实编排，type=living_circle 独立流水线）────── */

/**
 * 发起生活圈体检任务。center=[lng,lat]（BD-09）可缺省——后端地理编码 / fixture 样例名匹配兜底。
 * 真实链路：失败必须显式抛出（假 taskId 会让工作台白屏，不做静默兜底）。
 */
export async function createLivingCircleTask(input: {
  query: string
  mode?: LifeCircleMode
  center?: [number, number] | null
  city?: string
  address?: string
  data_mode?: string
}): Promise<CreateTaskResp> {
  const r = await fetch(`${API_BASE}/api/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: input.query,
      mode: input.mode ?? 'standard',
      type: 'living_circle',
      center: input.center ?? null,
      city: input.city ?? '',
      address: input.address ?? '',
      data_mode: input.data_mode ?? LC_DATA_MODE,
    }),
  })
  const data = (await r.json().catch(() => ({}))) as { taskId?: string; detail?: string; message?: string }
  if (!r.ok || !data.taskId) {
    throw new Error(data.detail || data.message || `创建体检任务失败（HTTP ${r.status}）`)
  }
  return { taskId: data.taskId }
}

/** 历史体检记录列表（对齐 LifeCircleRecord，历史页 / 报告中心共用）。 */
export async function fetchLifeCircleReports(): Promise<LifeCircleRecord[]> {
  return safeJson<LifeCircleRecord[]>('/api/life-circle', undefined, [])
}

/** 完整体检报告（Report 挂载 living_circle，渲染适配器直接消费）。 */
export async function fetchLifeCircleReport(reportId: string): Promise<Report | null> {
  return safeJson<Report | null>(`/api/life-circle/${reportId}`, undefined, null)
}

/** 双社区对比（LifeCircleCompare：reports + diff 指标表）。 */
export async function fetchLifeCircleCompare(ids: string[]): Promise<LifeCircleCompare | null> {
  if (ids.length < 2) return null
  const qs = ids.map(encodeURIComponent).join(',')
  return safeJson<LifeCircleCompare | null>(`/api/life-circle/compare?ids=${qs}`, undefined, null)
}

export async function submitClarify(
  taskId: string,
  answers: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  return safeJson(
    `/api/tasks/${taskId}/clarify`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    },
    { ok: true },
  )
}

export async function fetchReport(reportId: string): Promise<Report | null> {
  // F 阶段：mock 态由 fixture 构造完整 Report（report_type/living_circle 由渲染适配器消费）
  if (USE_MOCK) return getLivingCircleReportMock(reportId)
  return safeJson<Report | null>(`/api/reports/${reportId}`, undefined, null)
}

/* 报告决策链路 Trace（决策回放 / Trace 页签） */
export async function fetchReportTrace(reportId: string): Promise<{ spans: TraceSpan[] }> {
  return safeJson<{ spans: TraceSpan[] }>(`/api/reports/${reportId}/trace`, undefined, { spans: [] })
}

/* 人工反馈（修正率 → 业务闭环指标） */
export async function submitFeedback(
  reportId: string,
  editedBlocks: number,
  totalBlocks: number,
  data: Record<string, unknown> = {},
): Promise<{ ok: boolean }> {
  return safeJson(
    `/api/reports/${reportId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edited_blocks: editedBlocks, total_blocks: totalBlocks, data }),
    },
    { ok: true },
  )
}

/* 按批注深化章节（人工介入二次调研） */
export async function refineSection(
  reportId: string,
  sectionId: string,
  annotations: string[],
): Promise<{ ok: boolean; section?: ReportSection; message?: string }> {
  return safeJson(
    `/api/reports/${reportId}/refine`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: sectionId, annotations }),
    },
    { ok: false, message: '请求失败' },
  )
}

/* 我的调研：真实历史报告列表 */
export async function fetchReports(): Promise<ReportCard[]> {
  return safeJson<ReportCard[]>('/api/reports', undefined, [])
}

export async function deleteReport(reportId: string): Promise<{ ok: boolean }> {
  return safeJson(`/api/reports/${reportId}`, { method: 'DELETE' }, { ok: true })
}

/* 一页纸精炼（简报，G7）：创建 kind='brief' 后台任务并返回 taskId。
 * 幂等/失败语义在任务流内：产物落库后 report.brief 就绪；历史补帧/终态重连由任务流保证。
 * HTTP 非 2xx（如 404）显式抛出；网络异常亦显式抛出（不做静默兜底）。 */
export async function generateReportBrief(reportId: string): Promise<{ taskId: string }> {
  const r = await fetch(`${API_BASE}/api/reports/${reportId}/brief`, { method: 'POST' })
  const data = (await r.json().catch(() => ({}))) as { taskId?: string; detail?: string; message?: string }
  if (!r.ok) {
    throw new Error(data.detail || data.message || `请求失败（HTTP ${r.status}）`)
  }
  if (!data.taskId) {
    throw new Error(data.message || '未返回任务 ID，请重试')
  }
  return { taskId: data.taskId }
}

/* 仪表盘真实统计 */
export async function fetchDashboard(): Promise<DashboardStats | null> {
  return safeJson<DashboardStats | null>('/api/dashboard', undefined, null)
}

/* 全局证据溯源库 */
export async function fetchEvidences(params?: {
  brand?: string
  source_type?: string
  min_cred?: number
  /** 证据归属过滤：'<rid>' = 仅该报告证据；不传 = 全部证据。 */
  report_id?: string
}): Promise<EvidenceQueryResp> {
  const qs = new URLSearchParams()
  if (params?.brand) qs.set('brand', params.brand)
  if (params?.source_type) qs.set('source_type', params.source_type)
  if (params?.min_cred != null) qs.set('min_cred', String(params.min_cred))
  if (params?.report_id != null) qs.set('report_id', params.report_id)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return safeJson<EvidenceQueryResp>(`/api/evidences${suffix}`, undefined, {
    items: [],
    facets: { total: 0, by_type: {}, by_brand: {} },
  })
}

/* 基于新归属的高可信度证据异步精修报告，返回 taskId（订阅 /api/tasks/{taskId}/stream 拿进度）。 */
export async function refineReportEvidence(
  reportId: string,
  opts: { evidence_ids?: string[]; min_cred?: number } = {},
): Promise<{ taskId: string }> {
  const body: Record<string, unknown> = {}
  if (opts.evidence_ids && opts.evidence_ids.length > 0) body.evidence_ids = opts.evidence_ids
  if (opts.min_cred != null) body.min_cred = opts.min_cred
  return safeJson<{ taskId: string }>(
    `/api/reports/${reportId}/refine-evidence`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    { taskId: '' },
  )
}

/* 竞品监控订阅 */
export async function fetchSubscriptions(): Promise<Subscription[]> {
  return safeJson<Subscription[]>('/api/subscriptions', undefined, [])
}

export async function createSubscription(query: string, brands: string[]): Promise<Subscription | null> {
  return safeJson<Subscription | null>(
    '/api/subscriptions',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, brands }),
    },
    null,
  )
}

export async function deleteSubscription(subId: string): Promise<{ ok: boolean }> {
  // 同上：写操作失败必须显式暴露，不做静默兜底。
  return safeJson<{ ok: boolean }>(`/api/subscriptions/${subId}`, { method: 'DELETE' })
}

/* 专家工作量看板 */
export async function fetchWorkload(): Promise<ExpertWorkload[]> {
  return safeJson<ExpertWorkload[]>('/api/experts/workload', undefined, [])
}

/* SSE：监听任务流，返回关闭函数 */
export interface SSEHandlers {
  onEvent: (type: SSEEventType, data: unknown) => void
  onError?: (e: unknown) => void
  onOpen?: () => void
}

export function openTaskStream(taskId: string, handlers: SSEHandlers): () => void {
  // A4：体检任务（lc-*）在 mock 态回放 fixture 事件流（默认报告 lc-kaili，样区页可显式覆写）；
  // M3 换真实 SSE，事件类型/字段契约不变，前端零改动。
  if (USE_MOCK && taskId.startsWith('lc-')) {
    return replayLivingCircleStream(taskId, handlers)
  }
  const url = `${API_BASE}/api/tasks/${taskId}/stream`
  const es = new EventSource(url)
  const types: SSEEventType[] = [
    'node_update',
    'thought',
    'message',
    'evidence',
    'chart',
    'image',
    'progress',
    'trace',
    'report_ready',
    'done',
    'error',
  ]
  es.onopen = () => handlers.onOpen?.()
  for (const t of types) {
    es.addEventListener(t, (ev) => {
      let parsed: unknown = (ev as MessageEvent).data
      try {
        parsed = JSON.parse((ev as MessageEvent).data)
      } catch {
        /* keep raw */
      }
      handlers.onEvent(t, parsed)
    })
  }
  es.onerror = (e) => {
    handlers.onError?.(e)
  }
  return () => es.close()
}

/* 澄清问卷 SSE：CreateTaskResp 不再带问卷，ClarifyPage 挂载后拉取并懒生成。 */
export function openClarifyStream(taskId: string, handlers: ClarifySSEHandlers): () => void {
  const url = `${API_BASE}/api/tasks/${taskId}/clarify/stream`
  const es = new EventSource(url)
  const types: ClarifySSEEventType[] = ['clarify_stage', 'clarify_ready', 'clarify_update', 'error']
  es.onopen = () => handlers.onOpen?.()
  for (const t of types) {
    es.addEventListener(t, (ev) => {
      let parsed: unknown = (ev as MessageEvent).data
      try {
        parsed = JSON.parse((ev as MessageEvent).data)
      } catch {
        /* keep raw */
      }
      handlers.onEvent(t, parsed)
    })
  }
  es.onerror = (e) => {
    handlers.onError?.(e)
  }
  return () => es.close()
}

export { API_BASE }

/* ── 任务运行态（悬浮条 + 侧栏入口 + 返回语义依赖）────────── */
export interface TaskStatusResp {
  status: 'created' | 'clarified' | 'running' | 'done' | 'failed' | null
  percent: number
  stage: string
  evidence_count: number
  report_id: string | null
  started_at: string | null
  updated_at: string | null
}

export interface RunningTask {
  task_id: string
  query: string
  status: string
  percent: number
  stage: string
  evidence_count: number
  started_at: string | null
}

/** 实时进度与状态；断连后仍在后台跑，可轮询感知终态。 */
export function getTaskStatus(taskId: string): Promise<TaskStatusResp> {
  return safeJson<TaskStatusResp>(`/api/tasks/${taskId}/status`, undefined, {
    status: null,
    percent: 0,
    stage: '',
    evidence_count: 0,
    report_id: null,
    started_at: null,
    updated_at: null,
  })
}

/** 进行中的任务列表。 */
export function listRunningTasks(): Promise<RunningTask[]> {
  return safeJson<RunningTask[]>('/api/tasks/running', undefined, [])
}

/* ── 用户级偏好（prefs）───────────────────────────────────
   与 fetchSettings/saveSettings 的分工：settings 是系统级运行时配置（密钥脱敏）；
   prefs 是用户级偏好（明文）。持久化策略（本地秒开 / 远端真相源 / 首次上推）
   不在本层，见 src/lib/persist.ts —— 本层只管 HTTP。 */

/**
 * 「当前部署根本没有这个接口」——与「临时网络故障」是两回事。
 *
 * 触发场景：Vercel 只读镜像 `api/index.py` 是**有意裁剪**的部署形态（该目录
 * 是 backend/ 的子集，见 backend/tests/test_api_mirror_guard.py），只写 /tmp、
 * 明确声明「刷新/重启后不持久化」。因此那边不存在 /api/prefs **不是 bug**。
 *
 * 拿到此错误意味着：应永久降级为纯本地持久化，而不是把它当成故障反复重推。
 */
export class PrefsUnsupportedError extends Error {
  constructor(status: number) {
    super(`该部署未提供 /api/prefs（HTTP ${status}），已降级为本地持久化`)
    this.name = 'PrefsUnsupportedError'
  }
}

/** 服务端偏好接口可用性。`unknown` 表示尚未观察到任何结论，此时正常发请求。 */
export type PrefsApiCapability = 'unknown' | 'supported' | 'unsupported'

let prefsCapability: PrefsApiCapability = 'unknown'

/** 供 persist 层查询：`unsupported` 时不再空推、不再刷告警。 */
export function getPrefsApiCapability(): PrefsApiCapability {
  return prefsCapability
}

/** 判定「接口不存在」的状态码（404 路由缺失 / 405 方法未实现）。 */
function isMissingEndpoint(status: number): boolean {
  return status === 404 || status === 405
}

/** 读取用户偏好。后端不可用时返回 null（由 persist 层决定"保留本地值"）。 */
export async function fetchPrefs(): Promise<PrefsResp | null> {
  try {
    const r = await fetch(`${API_BASE}/api/prefs`)
    if (isMissingEndpoint(r.status)) {
      prefsCapability = 'unsupported'
      return null
    }
    if (!r.ok) return null
    prefsCapability = 'supported'
    return (await r.json()) as PrefsResp
  } catch {
    return null
  }
}

/** 写入用户偏好（增量 patch）。失败抛错，由 persist 层保留 pending 标记待重推。 */
export async function savePrefs(patch: PrefsValues): Promise<void> {
  const r = await fetch(`${API_BASE}/api/prefs`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patch }),
  })
  if (isMissingEndpoint(r.status)) {
    // 该部署没有这个接口 → 记录能力缺失，抛专用错误让 persist 层永久降级
    prefsCapability = 'unsupported'
    throw new PrefsUnsupportedError(r.status)
  }
  if (!r.ok) {
    const data = await r.json().catch(() => ({}))
    const errors = (data as { detail?: { errors?: Record<string, string> } })?.detail?.errors
    const msg = errors
      ? Object.entries(errors)
          .map(([k, v]) => `${k}: ${v}`)
          .join('\n')
      : `偏好保存失败（HTTP ${r.status}）`
    throw new Error(msg)
  }
  prefsCapability = 'supported'
}
