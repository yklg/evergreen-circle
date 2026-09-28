import { useCallback } from 'react'
import { fetchIntel } from '../lib/api'
import type { IntelOverview } from '../types'
import { useResource, type Resource } from './useResource'

/**
 * 目的地调研屏的取数：`/api/intel` 一份载荷出全八块。
 *
 * `enabled=false` 用于演示态（T3 拍定＝甲）：fixture 下这屏挂显式说明态，
 * 一次请求都不该发 —— 判据钉的是 `fetchIntel` not.toHaveBeenCalled，
 * 所以"禁用"必须是结构性的（不挂载取数），不能靠拿完数据再隐藏。
 */
export function useIntelOverview(enabled: boolean, refreshToken = 0): Resource<IntelOverview> {
  const load = useCallback(() => fetchIntel(), [])
  return useResource(load, enabled, refreshToken)
}
