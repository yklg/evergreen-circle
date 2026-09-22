import { useEffect } from 'react'
import { openTaskStream } from '../lib/api'
import { useTaskStore } from '../store/taskStore'

/**
 * 接入任务 SSE 流：reset → 监听 → ingest 到 taskStore。
 * 组件卸载或 taskId 变化时关闭连接。
 * 注意：不使用 startedRef 守卫，否则 StrictMode 卸载会关闭连接后无法重连。
 */
export function useTaskStream(taskId: string | undefined, query: string) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)
  const flushDispatchQueue = useTaskStore((s) => s.flushDispatchQueue)

  useEffect(() => {
    if (!taskId) return

    reset(taskId, query)
    // 终态帧后必须主动 close：EventSource 规范下服务端关流后浏览器会自动重连，
    // 不 close 就会在 done/error 之后无限重连（每轮拿一帧终态，永不停止）。
    let close: (() => void) | null = null
    let closed = false
    const doClose = () => {
      closed = true
      close?.()
    }
    close = openTaskStream(taskId, {
      onEvent: (type, data) => {
        ingest(type, data)
        if ((type === 'done' || type === 'error') && !closed) doClose()
      },
      onError: () => {
        // SSE 在流结束时也会触发 error；done 已置 finished，故仅在未完成时记录
      },
    })
    return () => {
      doClose()
      flushDispatchQueue() // 卸载冲刷派遣队列余量（清定时器、不丢帧）
    }
  }, [taskId, query, reset, ingest, flushDispatchQueue])
}
