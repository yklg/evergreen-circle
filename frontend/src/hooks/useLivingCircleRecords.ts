import { useCallback, useEffect, useState } from 'react'
import { fetchLifeCircleReports } from '../lib/api'
import { applyDemoTombstones } from '../lib/demoArchive'
import { getLifeCircleRecords } from '../mocks/livingCircleReports'
import { livingCircleRows, type ReportRecord } from '../lib/recordIndex'
import { useDataModeStore } from '../store/dataModeStore'
import { subscribeDemoArchive } from '../store/demoArchiveStore'
import { useResource, type Resource } from './useResource'

/**
 * 生活圈屏的取数（一屏一源）。
 *
 * 演示态走内置快照，真实态走 `/api/life-circle`；两态都只出生活圈行 ——
 * 调研侧不再从这里经过，所以它的失败也不会把这屏抹成空。
 *
 * `refreshToken` 变化即重取：删除成功后外壳自增它，屏自己回到服务端真相。
 *
 * 演示态那一屏还要过一层本机减法（`applyDemoTombstones`）：快照列表是每次重新派生的
 * 纯函数，"这台机器摘掉了哪几行"存在 `store/demoArchiveStore` 里，不叠这一层就会
 * 出现"删了又长回来"（本轮实测的原始症状）。
 *
 * 最后一位 `demoTick`：**还原**发生在屏之外（点的是本页那条还原条，不是列表行），
 * 外壳的 `refreshToken` 不会动 ⇒ 不订阅存储的话，还原完屏幕要等下一次别的原因才刷新。
 */
export function useLivingCircleRecords(refreshToken = 0): Resource<ReportRecord[]> & { isFixture: boolean } {
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')
  const [demoTick, setDemoTick] = useState(0)
  useEffect(() => subscribeDemoArchive(() => setDemoTick((n) => n + 1)), [])
  const load = useCallback(async (): Promise<ReportRecord[]> => {
    const rows = livingCircleRows(isFixture ? getLifeCircleRecords() : await fetchLifeCircleReports())
    return isFixture ? applyDemoTombstones(rows, 'living_circle') : rows
  }, [isFixture])
  return { ...useResource(load, true, refreshToken + demoTick), isFixture }
}
