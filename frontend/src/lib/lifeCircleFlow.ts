/**
 * 生活圈体检回落 SSE 流控制器（评审 P1 闭合语义 + D 单一事实源治理）。
 *
 * 生活圈体检从发起→报告全程**不再进入工作台**：本模块把「建任务 → 订阅 SSE
 * progress/message/round/report_ready/done → 报告就绪自动取回渲染」收敛为单一入口，
 * 供 HomePage 与 LifeCirclePage 复用。SSE 断连/error/取消均强制 close，绝不挂起。
 *
 * ## 单一事实源（taskRegistry）
 * 订阅过程中把 progress/stage/evidence_count/report_ready/done/error 同步写入全局
 * `taskRegistry`（kind='living_circle'）。这样悬浮条 / 侧栏「生活圈体检中」入口与
 * LifeCirclePage 进度横幅读的都是同一份状态，不再各自维护并行进度。
 *
 * 契约：复用 openTaskStream（真实态走 `/api/tasks/{id}/stream`，演示态 lc-* 任务
 * 回放 living_circle fixture）。事件字段解析集中在 onFlowEvent——兼容
 * `reportId`（runner 传统字段）与 `report_id`（fixture 事件），杜绝演示态不触发。
 */
import { createLivingCircleTask, fetchLifeCircleReport, openTaskStream } from './api'
import { useTaskRegistry } from '../store/taskRegistry'
import type { CoordSys } from './geo'
import type { ForensicRoundRow, LngLat, LifeCircleMode, LivingCircleReport, TravelMode } from '../types'

export interface LifeCircleLaunchInput {
  query: string
  mode?: LifeCircleMode
  center?: LngLat | null
  city?: string
  address?: string
  coord_sys?: CoordSys
  /** 出行方式。**未表态时不要传**：后端缺省会回落 walking，但"客户端没选"与
   *  "客户端选了步行"在缓存键与口径追溯上是两件事，前端不替用户预先表态。 */
  travel_mode?: TravelMode
  /** 4b · 用户点名重测 ⇒ 请求带 `force`，后端跳过两级缓存复用真的重跑。
   *  只有「重新体检」这一个控件传它；「开始体检」与输入新目标都**不传** —— 那里的默认
   *  行为（同口径 30 天内、中心 500m 内直接复用并如实标注来源）是省配额的既定设计，
   *  不能被一次普通点击悄悄变成全额重测。 */
  force?: boolean
}

export interface LifeCircleFlowCallbacks {
  /** SSE progress 推近；message 文本经 message 参数透出。 */
  onProgress?: (stage: string, percent: number, message?: string) => void
  /** `round`：一个取证扩容回合派发完了。文案**取事件自带的 `text`**（后端是唯一措辞出处），
   *  行对象同时给出 —— 页面要显示「额度还剩多少」这类派生量时不必再拼一遍句子。 */
  onRound?: (round: ForensicRoundRow, text: string) => void
  /** 任务失败 / SSE 断网降级，交由页面渲染 banner（不重新导航）。 */
  onError?: (message: string) => void
  /** report_ready：自动取回完整体检报告后回调，由页面写入渲染层。 */
  onReportReady?: (report: LivingCircleReport, reportId: string) => void
  /** `message` 且 `kind:'team'`：本次专家队的成员与**降级码**。
   *  `degraded` 为空串＝模型按场景挑的人；非空＝换了保底名单（`llm_error` / `team_too_small`），
   *  页面要把这件事留在屏上，而不是让它被下一条 message 冲掉。 */
  onTeam?: (team: { members: string[]; degraded: string; text: string }) => void
  /** `warn`：非致命的口径告警（如名称与中心点不同源）。 */
  onWarn?: (code: string, text: string) => void
}

export interface LifeCircleFlowHandle {
  taskId: string
  close: () => void
}

/* 事件收敛：progress/message/report_ready/error 的 load 形状统一取可索引对象。
   report_ready 需同时兼容 reportId（runner 传统字段）与 report_id（fixture 事件）。 */
type Ev = {
  stage?: string
  percent?: number
  text?: string
  reportId?: string
  report_id?: string
  message?: string
  round?: ForensicRoundRow
  /** message 事件的分支标记：`kind:'team'` 带组队结果与降级码；warn 带告警码 */
  kind?: string
  degraded?: string
  members?: string[]
  code?: string
}

/** 终端报告 id：report_ready/done 统一取 reportId → report_id 的任一非空。 */
function reportIdOf(d: Ev): string | null {
  return d.reportId ?? d.report_id ?? null
}

/** 单条事件分流到回调（供订阅与被 mock 替换时复用；不涉及 registry，保持纯函数）。 */
function onFlowEvent(type: string, data: unknown, cb: LifeCircleFlowCallbacks) {
  const d = (data ?? {}) as Ev
  if (type === 'progress' && d.stage != null) {
    cb.onProgress?.(d.stage, d.percent ?? 0, d.text)
    return
  }
  if (type === 'message' && d.kind === 'team') {
    // 组队结果（含降级）走独立回调：横幅那句"专家队由保底名单编排"要**留在屏上**，
    // 不能像普通 progress 文案那样被下一条 message 冲掉。
    cb.onTeam?.({ members: d.members ?? [], degraded: d.degraded ?? '', text: d.text ?? '' })
    return
  }
  if (type === 'message' && d.text) {
    cb.onProgress?.('', 0, d.text)
    return
  }
  if (type === 'warn') {
    // 后端 `living_circle.py` 的 name_center_mismatch 等告警。此前 `warn` 不在
    // SSEEventType 里 ⇒ 传输层直接丢弃，这条分支形同虚设（现已登记并补守卫测试）。
    cb.onWarn?.(d.code ?? '', d.text ?? '')
    return
  }
  if (type === 'round' && d.round) {
    // 刻意**不**进 taskRegistry：回合不改 stage/percent（后端那条分支明确不发 progress），
    // 若在这里顺手 upsert，`stage_seq == 1..7` 那五处契约会被多出来的推进改写。
    cb.onRound?.(d.round, d.text ?? '')
    return
  }
  if (type === 'report_ready' && reportIdOf(d)) {
    const rid = reportIdOf(d) as string
    void fetchLifeCircleReport(rid).then((rep) => {
      if (rep?.living_circle) cb.onReportReady?.(rep.living_circle, rid)
    })
    return
  }
  if (type === 'error') {
    cb.onError?.(d.message ?? '体检任务失败')
  }
}

/** 同步 registry（订阅侧唯一写点）：progress/evidence 推进，report_ready/done/error 落终态。 */
function instrumentRegistry(taskId: string, type: string, data: unknown, getEvidence: () => number) {
  const d = (data ?? {}) as Ev
  const reg = () => useTaskRegistry.getState()
  if (type === 'evidence') {
    reg().upsert({ taskId, evidence_count: getEvidence() + 1 })
    return
  }
  if (type === 'progress' && d.stage != null) {
    // 终态（done/failed）后到达的迟到 progress 不回退状态/进度：幂等收敛。
    const cur = reg().tasks[taskId]
    if (!cur || cur.status !== 'running') return
    reg().upsert({ taskId, stage: d.stage, percent: d.percent ?? 0, evidence_count: getEvidence() })
    return
  }
  const rid = (type === 'report_ready' || type === 'done') && reportIdOf(d) ? reportIdOf(d) : null
  if (rid) {
    reg().markDone(taskId, rid)
    return
  }
  if (type === 'error') {
    reg().markFailed(taskId, d.message ?? '体检任务失败')
  }
}

/** 保证 registry 有该任务的一份 running 记录（launch 已种；resume/直达跨设备兜底）。 */
function seedRegistry(taskId: string) {
  const s = useTaskRegistry.getState()
  s.upsert({
    taskId,
    kind: 'living_circle',
    purpose: 'living_circle',
    query: s.tasks[taskId]?.query ?? '',
    status: 'running',
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  })
}

/** 订阅已建任务的 SSE 流（进度/终态同步 registry）；返回 close 函数。 */
export function subscribeLifeCircleTask(
  taskId: string,
  callbacks: LifeCircleFlowCallbacks = {},
): () => void {
  seedRegistry(taskId)
  const evidence = () => useTaskRegistry.getState().tasks[taskId]?.evidence_count ?? 0
  return openTaskStream(taskId, {
    onEvent: (type, data) => {
      instrumentRegistry(taskId, type, data, evidence)
      onFlowEvent(type, data, callbacks)
    },
    onError: (e) => {
      // 终态护栏：域级成功(done)后流正常关闭、或已落 failed 时，传输层告警不得覆盖终态
      // （否则成功任务在渲染报告后仍被误报「创建失败」）。消息规整为可读文案，杜绝 [object Event]。
      const cur = useTaskRegistry.getState().tasks[taskId]
      if (cur?.status === 'done' || cur?.status === 'failed') return
      const message =
        (typeof e === 'string' && e) ||
        (e as { message?: string })?.message?.trim() ||
        'SSE 连接中断'
      useTaskRegistry.getState().markFailed(taskId, message)
      callbacks.onError?.(message)
    },
  })
}

/**
 * 建任务 + 订阅 + 报告就绪取回渲染，一步到位。返回句柄（taskId / close），
 * 调用方负责在卸载/终态时 close（配合 abort，见 LifeCirclePage）。
 */
export async function launchLifeCircle(
  input: LifeCircleLaunchInput,
  callbacks: LifeCircleFlowCallbacks = {},
): Promise<LifeCircleFlowHandle> {
  // 刻意不无条件注入 city/address：城市应由后端按中心点逆地理补全（同源约束），
  // 仅当调用方显式提供时才透传，避免把无关城市写进请求污染报告 scene。
  const payload: {
    query: string
    mode: LifeCircleMode
    center: LngLat | null
    coord_sys: CoordSys
    city?: string
    address?: string
    travel_mode?: TravelMode
    force?: boolean
  } = {
    query: input.query,
    mode: input.mode ?? 'standard',
    center: input.center ?? null,
    coord_sys: input.coord_sys ?? 'bd09',
  }
  if (input.city) payload.city = input.city
  if (input.address) payload.address = input.address
  if (input.travel_mode) payload.travel_mode = input.travel_mode
  // 与 city/address 同一条形状纪律：**只在点名重测时才带这一位**，false/缺省一律不发。
  // 写成 `payload.force = input.force ?? false` 会让每次普通体检的载荷都多一个键，
  // 而"省配额的默认路径"与"用户要求重测"本来就该在请求上可分辨（后端守卫也只看有没有这一位）。
  if (input.force) payload.force = true
  const { taskId } = await createLivingCircleTask(payload)
  const close = subscribeLifeCircleTask(taskId, callbacks)
  return { taskId, close }
}

/* 供测试注入：替换内部 openTaskStream 实现。 */
export const __test = { onFlowEvent }