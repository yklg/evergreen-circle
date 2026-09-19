/**
 * A4 · 体检任务 SSE 事件流 mock 回放器。
 *
 * 在 VITE_USE_MOCK=1 时替代真实 EventSource：按 eventFlow.json 的时序
 * （intake→plan→measure→collect→diagnose→report→audit）以定时器重放事件，
 * 让 useTaskStream / 任务流 UI 在 mock 态以与 M3 完全一致的契约消费事件流。
 *
 * 契约：eventFlow.json 的每个条目 { type, data } 直接映射
 * onEvent(type, data)；禁止在回放层改字段，M 阶段换真实 SSE 零改动。
 */
import type { SSEEventType } from '../types'
import eventFlow from './livingCircle/eventFlow.json'

export const LC_STAGES = eventFlow.stages as readonly string[]

export const LC_STAGE_LABEL: Record<string, string> = {
  intake: '确立参数',
  plan: '专家编排',
  measure: '测时采样',
  collect: 'POI 采集',
  diagnose: '诊断评分',
  report: '报告撰写',
  audit: '质检签发',
}

export interface LivingCircleReplayOptions {
  /** 覆盖流内 report_ready/done 的目标报告 id（按当前样区所见即所得） */
  reportId?: string
  /** 事件步进间隔 ms（演示用；默认 140ms） */
  speed?: number
  onDone?: (reportId: string) => void
}

/** 阶段中文名（overlay/进度条复用） */
export function stageLabel(stage: string): string {
  return LC_STAGE_LABEL[stage] ?? stage
}

/** 回放体检任务事件流；返回 close()。事件顺序与 eventFlow.json 保持一致。 */
export function replayLivingCircleStream(
  _taskId: string,
  handlers: { onEvent: (type: SSEEventType, data: unknown) => void; onError?: (e: unknown) => void },
  opts: LivingCircleReplayOptions = {},
): () => void {
  const { reportId, speed = 140, onDone } = opts
  const timers: ReturnType<typeof setTimeout>[] = []
  let closed = false

  // 归一 taskId：demo 任务与样区任务共用同一事件序列（只改目标报告 id）
  const demo = eventFlow as unknown as { events: { type: SSEEventType; data: Record<string, unknown> }[] }
  const effectiveReportId = reportId ?? (eventFlow as unknown as { report_id: string }).report_id

  demo.events.forEach((ev, i) => {
    const t = setTimeout(() => {
      if (closed) return
      if (ev.type === 'report_ready') {
        handlers.onEvent('report_ready', { ...ev.data, report_id: effectiveReportId })
        return
      }
      if (ev.type === 'done') {
        handlers.onEvent('done', { ...ev.data, report_id: effectiveReportId })
        onDone?.(effectiveReportId)
        return
      }
      handlers.onEvent(ev.type, ev.data)
    }, i * speed)
    timers.push(t)
  })

  return () => {
    closed = true
    timers.forEach(clearTimeout)
  }
}