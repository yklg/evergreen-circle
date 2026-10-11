/**
 * 演示归档的本机还原条 —— 只在演示态、且这台机器确实摘掉过行时出现。
 *
 * 为什么需要它：演示态那几行报告不是库里的真行，而是每次取数重新派生的
 * （`getLifeCircleRecords` 是纯函数）。删除只能记在这台机器上（`store/demoArchiveStore`），
 * 所以"还原"也必须有一个出口 —— 否则用户删错一行就得去开控制台清 localStorage。
 *
 * `domain` 是**数据参数**，不是 `if (domain === …)`：报告中心的域分叉只许写在
 * `lib/domainViews.ts` 那一处（判据见 `domainEnumSingleSource.test.ts`）。
 */
import { useDemoArchiveStore, type DemoTombstone } from '../../store/demoArchiveStore'
import type { RecordDomain } from '../../lib/recordIndex'
import { VButton } from '../ui'

function fmtRemoved(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

export default function DemoArchiveStrip({ domain }: { domain: RecordDomain }) {
  const table = useDemoArchiveStore((s) => s.doc.removed[domain])
  const restoreAll = useDemoArchiveStore((s) => s.restoreAll)
  const restoreOne = useDemoArchiveStore((s) => s.restoreOne)

  const rows = Object.values(table ?? {}) as DemoTombstone[]
  if (!rows.length) return null

  return (
    <div className="mt-3 rounded-card border border-line bg-bg p-3" aria-label="本机已摘除的演示归档">
      <p className="text-tag text-ink-2">
        本机已摘掉 <strong className="font-medium text-ink">{rows.length}</strong> 份演示归档
        —— 只影响这台浏览器，清掉记录就重新出现（不改动内置快照本身）：
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 text-tag text-ink-3">
            <span className="truncate">
              {r.title}
              <span className="ml-2 opacity-70">摘除于 {fmtRemoved(r.removed_at)}</span>
            </span>
            <button
              type="button"
              onClick={() => restoreOne(domain, r.id)}
              className="shrink-0 underline-offset-2 hover:underline"
            >
              还原这一份
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex justify-end">
        <VButton variant="ghost" onClick={() => restoreAll(domain)}>
          一键还原全部 {rows.length} 份
        </VButton>
      </div>
    </div>
  )
}
