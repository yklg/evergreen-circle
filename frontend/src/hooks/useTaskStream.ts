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
 */
export function useTaskStream(taskId: string | undefined, query: string, meta: OpenTaskStreamMeta = {}) {
  const reset = useTaskStore((s) => s.reset)
  const ingest = useTaskStore((s) => s.ingest)

  useEffect(() => {
    if (!taskId) return

    reset(taskId, query)
    const close = openTaskStream(taskId, {
      onEvent: (type, data) => ingest(type, data),
      onError: () => {
        // SSE 在流结束时也会触发 error；done 已置 finished，故仅在未完成时记录
      },
    }, meta)
    return () => close()
  }, [taskId, query, reset, ingest, meta.purpose])
}