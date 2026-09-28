import { useCallback, useEffect, useState } from 'react'
import { fetchLifeCircleReports, fetchReports } from '../lib/api'
import { getLifeCircleRecords } from '../mocks/livingCircleReports'
import { buildRecordIndex, type ReportRecord } from '../lib/recordIndex'
import { useDataModeStore } from '../store/dataModeStore'

export interface RecordIndexState {
  records: ReportRecord[] | null
  loading: boolean
  /** 两源都取不到：整页失败态，绝不渲染成「暂无报告」 */
  failed: boolean
  /** 只有一源失败：仍渲染成功那一侧，另给一条局部提示 */
  partialFailed: boolean
  isFixture: boolean
  reload: () => void
}

/** 归档索引取数（历史页 / 报告中心共用一份实现）。 */
export function useRecordIndex(): RecordIndexState {
  const isFixture = useDataModeStore((s) => s.mode === 'fixture')
  const [nonce, setNonce] = useState(0)
  const [records, setRecords] = useState<ReportRecord[] | null>(null)
  const [loading, setLoading] = useState(!isFixture)
  const [failed, setFailed] = useState(false)
  const [partialFailed, setPartialFailed] = useState(false)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (isFixture) {
      setRecords(buildRecordIndex(getLifeCircleRecords(), []))
      setLoading(false)
      setFailed(false)
      setPartialFailed(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setPartialFailed(false)
    // allSettled 而非 all：单源故障不该把另一侧已有的归档一起抹掉
    void Promise.allSettled([fetchLifeCircleReports(), fetchReports()]).then(([lc, research]) => {
      if (cancelled) return
      if (lc.status === 'rejected') console.warn('[recordIndex] 生活圈体检记录取数失败', lc.reason)
      if (research.status === 'rejected') console.warn('[recordIndex] 调研报告记录取数失败', research.reason)
      const rows = buildRecordIndex(
        lc.status === 'fulfilled' ? lc.value : [],
        research.status === 'fulfilled' ? research.value : [],
      )
      setRecords(rows)
      setPartialFailed((lc.status === 'rejected') !== (research.status === 'rejected'))
      setFailed(lc.status === 'rejected' && research.status === 'rejected')
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [isFixture, nonce])

  return { records, loading, failed, partialFailed, isFixture, reload }
}
