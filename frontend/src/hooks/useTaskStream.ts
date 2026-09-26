import { useEffect } from 'react'
import { openTaskStream, type OpenTaskStreamMeta } from '../lib/api'
import { useTaskStore } from '../store/taskStore'

/**
 * 接入任务 SSE 流：reset → 监听 → ingest 到 taskStore。
 * 组件卸载或 taskId 变化时关闭连接。
 * 注意：不使用 startedRef 守卫，否则 StrictMode 卸载会关闭连接后无法重连。
 *
 * meta.purpose 透传给演示态回放器（replayResearchStream 需知道 guide/assess 出对应体裁）；
 * 真实态仅需 taskId，purpose 由后端从任务落库读取，前端同样的事件契约零改动。
 *
 * 终态收口（TC-F1）：EventSource 规范下服务端关流后浏览器会自动重连，收到 done/error 后
 * 必须主动 close，否则即便后端已修好终态契约，页面仍会以极快节奏无限重连（每轮只拿一帧终态）。
 * 卸载时冲刷派遣队列余量（清定时器、不丢帧）。
 */
export function useTaskStream(taskId: string | undefined, query: string, meta: OpenTaskStreamMeta = {}) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)
  const flushDispatchQueue = useTaskStore((s) => s.flushDispatchQueue)

  useEffect(() => {
    if (!taskId) return

    reset(taskId, query)
    let close: (() => void) | null = null
    let closed = false
    const doClose = () => {
      closed = true
      close?.()
    }
    close = openTaskStream(
      taskId,
      {
        onEvent: (type, data) => {
          ingest(type, data)
          if ((type === 'done' || type === 'error') && !closed) doClose()
        },
        onError: () => {
          // SSE 在流结束时也会触发 error；done 已置 finished，故仅在未完成时记录
        },
      },
      meta,
    )
    return () => {
      doClose()
      flushDispatchQueue() // 卸载冲刷派遣队列余量（清定时器、不丢帧）
    }
  }, [taskId, query, meta.purpose, reset, ingest, flushDispatchQueue])
}
