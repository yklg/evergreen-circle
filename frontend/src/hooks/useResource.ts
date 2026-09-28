import { useCallback, useEffect, useState } from 'react'

export interface Resource<T> {
  /** null = 还没有数据（加载中或失败）；空数组/空对象是合法数据，不与 null 混用 */
  data: T | null
  loading: boolean
  /** 取数失败：整屏失败态。绝不把它渲染成「暂无」——那是两种不同的可观察结果 */
  failed: boolean
  reload: () => void
}

/**
 * 一屏一源、各自三态。
 *
 * 分屏前是一根 `Promise.allSettled` 拉两源并算 `partialFailed`，于是生活圈屏会被
 * 调研取数连坐。拆成每屏自己的资源后：
 * - `enabled=false` 让"这一屏根本不该发请求"成为可证明的表达（演示态下的调研屏，
 *   判据钉的是 not.toHaveBeenCalled）；禁用态全部走派生，不在 effect 里同步 setState；
 * - `token` 变化即重取：删除成功后外壳自增它，屏自己回到服务端真相。
 */
export function useResource<T>(
  load: () => Promise<T>,
  enabled: boolean,
  token = 0,
): Resource<T> {
  const [state, setState] = useState<{ data: T | null; failed: boolean }>({
    data: null,
    failed: false,
  })
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    // 只在 promise 落点里 setState：effect 内同步改状态会引发级联渲染（先例 useMapConfig）
    void load().then(
      (value) => {
        if (!cancelled) setState({ data: value, failed: false })
      },
      (reason: unknown) => {
        if (cancelled) return
        console.warn('[reportDomain] 取数失败', reason)
        setState((s) => ({ data: s.data, failed: true }))
      },
    )
    return () => {
      cancelled = true
    }
  }, [enabled, token, nonce, load])

  if (!enabled) return { data: null, loading: false, failed: false, reload }
  const { data, failed } = state
  // 没失败又还没有数据 = 首帧在途，按加载中处理，避免闪一下假空态
  return { data, loading: !failed && data === null, failed, reload }
}
