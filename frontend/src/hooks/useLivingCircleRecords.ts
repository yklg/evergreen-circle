import { useCallback } from 'react'
import { fetchLifeCircleReports } from '../lib/api'
import { getLifeCircleRecords } from '../mocks/livingCircleReports'
import { livingCircleRows, type ReportRecord } from '../lib/recordIndex'
import { useDataModeStore } from '../store/dataModeStore'
import { useResource, type Resource } from './useResource'

/**
 * 生活圈屏的取数（一屏一源）。
 *
 * 演示态走内置快照，真实态走 `/api/life-circle`；两态都只出生活圈行 ——
 * 调研侧不再从这里经过，所以它的失败也不会把这屏抹成空。
 *
 * `refreshToken` 变化即重取：删除成功后外壳自增它，屏自己回到服务端真相。
 */
export function useLivingCircleRecords(refreshToken = 0): Resource<ReportRecord[]> & { isFixture: boolean } {
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')
  const load = useCallback(async (): Promise<ReportRecord[]> => {
    return livingCircleRows(isFixture ? getLifeCircleRecords() : await fetchLifeCircleReports())
  }, [isFixture])
  return { ...useResource(load, true, refreshToken), isFixture }
}
